"""歧义判定与澄清：避免"候选互相矛盾却擅自选一个"。

背景：当库中存在大量语义等价文档（如各部门的同一制度各有微差版本）时，
检索各环节指标都好看，但用户可能拿到**别人的版本**——指标全绿、业务全错。
此时正确行为是**温和澄清**，而不是硬答。

设计：
- **判定**：LLM 只判断"候选之间是否互相矛盾"（纯分类任务，易结构化）
- **三态（P0-1）**：`clear`（有答案）｜`ambiguous`（无唯一答案）｜`unknown`（无法判断）
- ~~门控~~（P1-3，**已移除**）：数据判它无效且有害 —— 通过率 98% 省不下调用，
  还制造 2~7 例漏报（见 `内部评测口径` §3 P1-3）。`is_diverse()` 作为**纯函数保留**，
  仅供 `eval/` 复现对照，**生产路径不再调用**。

⚠️ **一处被推翻的旧设计（P0-1 改的就是它）**：本模块原写
「任何异常/解析失败 → 判定为"无歧义"（**宁可漏报，不可误伤**）」。
现判定该回退**正是漏报的来源**：它把「**模型没答**」等同于「**模型答了：不歧义**」，
于是系统认为"问题不歧义"、拿互相矛盾的候选硬答 —— 而且**全程不报错**。
现在这类情况一律返回 `unknown`，由调用方显式处理（见 `src/api/chat_api.py`）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from src.config.litellm_client import LLMCallError, complete_with_meta
from src.config.prompts import load_ambiguity_check_templates, load_ambiguity_reply_templates
from src.config.settings import get_settings
from src.observability.tracer import audit, audit_err
from src.vector_store.base import Chunk

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)

# 判定三态（P0-1）。用字符串字面量而非 Enum：它要直接进 JSON 响应与审计日志。
JudgeStatus = Literal["clear", "ambiguous", "unknown"]
JUDGE_CLEAR: JudgeStatus = "clear"          # 有答案：判定跑了，判"不矛盾"
JUDGE_AMBIGUOUS: JudgeStatus = "ambiguous"  # 无唯一答案：判定跑了，判"互相矛盾"
JUDGE_UNKNOWN: JudgeStatus = "unknown"      # 无法判断：判定**想跑但没拿到有效结论**

# ⭐ `2.0-58`：`unknown` 的**成因分类**（只用于观测与处置，⛔ 不改三态语义）。
#   · `timeout` / `transient` / `fatal` —— 来自 `litellm_client.classify_failure`
#     （"慢" vs "坏" vs 致命；只有 `transient` 在客户端内被重试过一次）
#   · `unanswered`   —— 模型答了空 / 被 `max_tokens` 截断
#   · `unparsed`     —— 模型答了，但不符合约定格式
#   · `other`        —— 归不了类（兜底，别让它静默消失）
# 为什么需要它：`2.0-58` 之前所有成因都记成同一个 `unknown`，
# 于是一次"整批 unknown"到底是外部瞬时故障还是结构性缺陷**无法区分**，
# 也就没法给出不同处置。
FailureKind = Literal["timeout", "transient", "fatal",
                      "unanswered", "unparsed", "other"]


@dataclass
class ClarifyOption:
    """一个候选答案（用于向用户展示、让其明确意图）。"""

    source: str
    summary: str


@dataclass
class AmbiguityResult:
    """判定结果。**三态**（P0-1）：`clear` / `ambiguous` / `unknown`。

    ⚠️ `ambiguous` 与 `unknown` 是**两种不同的东西**，不要合并：
    - `ambiguous` = **模型答了**，而且答的是"候选互相矛盾" → 该澄清
    - `unknown`   = **模型没答**（异常/空/截断/不可解析）→ 该如实告诉用户"我无法确认"
    """

    status: JudgeStatus = JUDGE_CLEAR
    reason: str = ""
    options: list[ClarifyOption] = field(default_factory=list)
    # ⭐ `2.0-58`：仅当 `status == unknown` 时有值 —— 说清**是哪种没拿到**
    # （`timeout` / `transient` / `fatal` / `unanswered` / `unparsed` / `other`）。
    # ⛔ 不参与 `clear` / `ambiguous` 的判定，只用于观测与处置。
    failure_kind: FailureKind | None = None

    @property
    def ambiguous(self) -> bool:
        """**兼容既有调用点**：只有明确判为"有歧义"才算 True。

        ⚠️ `unknown` **不算** ambiguous —— 这正是修复点：旧实现把 unknown 也说成
        "不歧义"，现在它两个都不是，调用方必须显式看 `status`。
        """
        return self.status == JUDGE_AMBIGUOUS

    @property
    def unknown(self) -> bool:
        """无法判断：判定想跑但没拿到有效结论。"""
        return self.status == JUDGE_UNKNOWN


def is_diverse(chunks: list[Chunk], threshold: int) -> bool:
    """门控信号：top-K 是否来自 >= threshold 个不同来源。"""
    if not chunks:
        return False
    return len({c.source_file for c in chunks if c.source_file}) >= threshold


def _format_candidates(chunks: list[Chunk], snippet: int) -> str:
    # ⚠️ 同样是**不可信内容**（`2.0-5` 注入防护②）—— 歧义判定也会读块内容，必须一起隔开
    return "\n\n".join(
        f"[{i}] (来源: {c.source_file})\n"
        f"<untrusted_content>{c.content[:snippet]}</untrusted_content>"
        for i, c in enumerate(chunks, 1)
    )


def parse_result(raw: str) -> AmbiguityResult:
    """解析 LLM 输出。

    ⚠️ **P0-1 反转了旧行为**：原实现「无法解析 → 返回"无歧义"（安全回退）」，
    现改为 **`unknown`** —— 因为「模型没答」**不是**「模型答了：不歧义」。
    旧行为会让矛盾候选被硬答，且全程不报错（这正是 §3 P0-1 针对的头号风险）。

    判据：**必须有 `ambiguous` 这个键**才算"答了"。
    连键都没有（如 `{"reason": "..."}`）说明模型没按约定回答 → 同样 `unknown`。
    """
    match = _JSON_OBJ.search(raw or "")
    if not match:
        return AmbiguityResult(status=JUDGE_UNKNOWN, reason="模型未返回可解析的结论（空输出）")
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return AmbiguityResult(status=JUDGE_UNKNOWN, reason="模型返回的内容不是合法 JSON")
    if not isinstance(data, dict):
        return AmbiguityResult(status=JUDGE_UNKNOWN, reason="模型返回的不是 JSON 对象")
    if "ambiguous" not in data:
        return AmbiguityResult(status=JUDGE_UNKNOWN, reason="模型未按约定回答（缺 ambiguous 字段）")
    if not data.get("ambiguous"):
        # 明确答了"不矛盾" → 这才是 clear
        return AmbiguityResult(status=JUDGE_CLEAR, reason=str(data.get("reason", "")))

    options: list[ClarifyOption] = []
    for opt in data.get("options") or []:
        if isinstance(opt, dict) and opt.get("summary"):
            options.append(
                ClarifyOption(source=str(opt.get("source", "")), summary=str(opt["summary"]))
            )
    return AmbiguityResult(status=JUDGE_AMBIGUOUS, reason=str(data.get("reason", "")), options=options)


async def check_ambiguity(question: str, chunks: list[Chunk],
                          usage_out: dict | None = None) -> AmbiguityResult:
    """判定候选之间是否存在互相矛盾的答案。返回**三态**（P0-1）。

    ⚠️ **"没拿到有效结论"一律 `unknown`，绝不再退化成 `clear`**（旧实现的漏报来源）。

    `usage_out`（⭐ `2.0-59` 埋点）：传了就往里写这一次判定的 **token 用量**。
    ⛔ **纯观测** —— 不传时行为与返回**一字不变**（生产调用方都不传）。
    """
    settings = get_settings()
    if not settings.ambiguity_check_enabled or len(chunks) < 2:
        # **判定按设计未运行** → 归 `clear`，**不归 `unknown`**。
        # 理由：这是"设计上不需要判定"，硬答是预期行为；若归 unknown，
        # 一关开关全站都成"无法判断"，那不是三态的本意。
        return AmbiguityResult(status=JUDGE_CLEAR)

    # ⚠️ P1-3：**门控已移除**。原来这里有一道 `is_diverse(...)` 早退（来源不够分散就跳过判定），
    # 数据判它无效且有害：通过率 98% 省不下调用，还制造 2~7 例漏报。
    # `is_diverse()` 仍保留为纯函数，供 eval/ 复现对照，生产不再调用。

    system_tpl, human_tpl = load_ambiguity_check_templates()
    try:
        reply = await complete_with_meta(
            [
                {"role": "system", "content": system_tpl},
                {
                    "role": "user",
                    "content": human_tpl.format(
                        question=question,
                        candidates=_format_candidates(chunks, settings.ambiguity_snippet_chars),
                    ),
                },
            ],
            temperature=0,  # 判定必须可复现：同一候选集应给出同一结论
        )
    except LLMCallError as e:
        # ⭐ `2.0-58`：**带着失败类别回来**（"慢" / "坏" / 致命）。
        # 客户端已按类别决定过要不要重试 —— 走到这里说明**该试的都试过了**，
        # 所以这里只负责如实记录，⛔ 不再自行重试（那会把延迟上界弄丢）。
        audit_err("ambiguity_check_failed", question=question, kind=e.kind,
                  attempts=e.attempts, elapsed_s=round(e.elapsed_s, 3),
                  error=str(e.original))
        return AmbiguityResult(status=JUDGE_UNKNOWN,
                               reason=f"判定调用失败（{e.kind}）：{e.original}",
                               failure_kind=e.kind)
    except Exception as e:  # noqa: BLE001
        # 调用异常 → unknown（旧实现返回"无歧义"：一次网络抖动就等于"判定通过"）
        audit_err("ambiguity_check_failed", question=question, kind="other", error=str(e))
        return AmbiguityResult(status=JUDGE_UNKNOWN,
                               reason=f"判定调用失败：{e}", failure_kind="other")

    # ⭐ `2.0-59`：**只用观测** —— 调用成功才记（失败/未答也要记，
    #    否则分位数会把"失败但花了钱"的那几次悄悄丢掉）。⛔ 不影响下面任何判断。
    if usage_out is not None:
        usage_out.update({
            "prompt_tokens": reply.prompt_tokens,
            "completion_tokens": reply.completion_tokens,
            "called": True,
        })

    if not reply.answered:
        # 截断 / 空输出。`finish_reason=length` 是推理模型思考吃满的典型表现，
        # 与"模型确实无话可说"不是一回事 —— 但两者都**不能**当成"不歧义"。
        audit_err("ambiguity_unanswered", question=question, reason=reply.empty_reason,
                  finish_reason=reply.finish_reason)
        return AmbiguityResult(
            status=JUDGE_UNKNOWN,
            reason=("判定模型输出被 max_tokens 截断" if reply.truncated else "判定模型没有返回任何内容"),
            failure_kind="unanswered",
        )

    result = parse_result(reply.text)
    if result.unknown:
        audit_err("ambiguity_unparsed", question=question, raw_len=len(reply.text),
                  reason=result.reason, snippet=settings.ambiguity_snippet_chars)
        result.failure_kind = "unparsed"
    audit("ambiguity_check", question=question, status=result.status, options=len(result.options))
    return result


async def build_clarification(question: str, result: AmbiguityResult) -> str:
    """生成温和的澄清回复。失败时回退到模板化文案（不阻断主链路）。"""
    system_tpl, human_tpl = load_ambiguity_reply_templates()
    options_text = "\n".join(f"- {o.source}：{o.summary}" for o in result.options)
    try:
        return await complete(
            [
                {"role": "system", "content": system_tpl},
                {
                    "role": "user",
                    "content": human_tpl.format(question=question, reason=result.reason, options=options_text),
                },
            ]
        )
    except Exception as e:  # noqa: BLE001
        audit("ambiguity_reply_failed", question=question, error=str(e))
        return "我找到了多份相关文档，它们给出的答案不一致：\n" + options_text + "\n\n请问你指的是哪一种？"
