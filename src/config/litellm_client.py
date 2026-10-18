"""LLM 统一收口（LiteLLM）。**换厂商只改配置，业务代码不动**。"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal

import litellm
import openai

from src.config.settings import get_settings
from src.observability.tracer import audit, audit_err

logger = logging.getLogger("rag.llm")

# 思考链告警只响一次（每进程）
_thinking_warned = False


# ════════════════════════════════════════════════════════════════════════
# `2.0-58`：**区分「慢」与「坏」**
# ════════════════════════════════════════════════════════════════════════
#
# 背景（`§1.92` 已定性）：判定路径 `8s × 0 重试` 的取舍算的是"单请求最坏延迟"，
# 漏掉了另一个维度 —— **一次瞬时故障 → 一次慢窗口 → 整批 `unknown`**，
# 代价从"一个用户等 8s"变成"**N 个用户各看到一段假标注**"。
#
# 但那不等于"把重试加回来"：加了就是 `8s × N`，长尾重新放大。
# 真正的差别在于**失败本身要花多久**：
#   · **慢**（超时）—— 已经花掉整份预算，再试只会让用户多等一份 ⇒ ⛔ 不重试
#   · **坏**（连接被拒 / SSL 握手失败 / 5xx）—— 秒级就返回，再试一次几乎不花时间
# ⇒ 只对后者重试，且**用时超过阈值的一律不重试**（那已经不是"坏"，是"慢"）。
#
FailureKind = Literal["timeout", "transient", "fatal"]

# ⚠️ **顺序要紧，而且陷阱在 openai 那一层**（实测 2026-10-18，litellm 1.99.0）：
#    `litellm.Timeout` 与 `litellm.APIConnectionError` 是**兄弟**（都挂在
#    `openai.APIConnectionError` 下面），但 **`openai.APITimeoutError`
#    是 `openai.APIConnectionError` 的子类**。真实抛出来的异常经常是 openai 那套
#    ⇒ 若先判 `openai.APIConnectionError`，**超时会被当成"坏"并被重试**，
#    正是本单要避免的那个回退。所以 timeout 那一组**必须排在前面**。
_TIMEOUT_ERRORS: tuple[type[BaseException], ...] = (
    litellm.Timeout,
    openai.APITimeoutError,
    asyncio.TimeoutError,
    TimeoutError,
)
# "坏"：秒级就能返回的那一类。`OSError` 覆盖 `ssl.SSLError`（`§1.92` 的 122 条 100% 是它）。
_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    litellm.APIConnectionError,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
    litellm.RateLimitError,
    openai.APIConnectionError,
    openai.InternalServerError,
    openai.RateLimitError,
    ConnectionError,
    OSError,
)


class LLMCallError(Exception):
    """一次 LLM 调用**最终失败**（该重试的已重试完），带**失败类别**。

    存在的理由：以前所有失败都只是一条裸异常，调用方一律记成 `unknown` ——
    **"慢"与"坏"长得一模一样**。于是既分不清"整批 `unknown`"是外部瞬时故障
    还是结构性缺陷，也给不出不同的处置。
    """

    def __init__(self, original: BaseException, kind: FailureKind,
                 attempts: int, elapsed_s: float) -> None:
        self.original = original
        self.kind = kind
        self.attempts = attempts
        self.elapsed_s = elapsed_s
        super().__init__(f"{kind}（尝试 {attempts} 次，累计 {elapsed_s:.2f}s）：{original}")


def classify_failure(exc: BaseException) -> FailureKind:
    """把一次调用异常归到「慢 / 坏 / 致命」三类（判定顺序见 `_TIMEOUT_ERRORS` 上方注释）。"""
    if isinstance(exc, _TIMEOUT_ERRORS):
        return "timeout"
    if isinstance(exc, _TRANSIENT_ERRORS):
        return "transient"
    return "fatal"


def warn_if_thinking_enabled() -> None:
    """开启思考链时告警（**幂等**：每进程只响一次）。

    ⚠️ D9-⑩ 指出的缺口：现有 `thinking_leaked` 只在「**本该关、却泄漏了**」时响，
    **不覆盖「主动打开」的情况** —— 而主动打开恰恰是那个 bug 的原始触发条件：
    `LLM_THINKING_ENABLED=true` 而 `LLM_MAX_TOKENS` 还是 2048 时，
    思考会把预算吃满 → `finish_reason=length`、`content` 为空 →
    判定器 `parse_result("")` **静默判"不歧义"**（漏报）。

    由应用启动（`src/main.py`）与每次 `complete()` 调用两处触发，
    这样入口是 API 还是离线评测脚本都能被提醒到。
    """
    global _thinking_warned
    if _thinking_warned:
        return
    s = get_settings()
    if not s.llm_thinking_enabled:
        return
    _thinking_warned = True
    logger.warning(
        "LLM_THINKING_ENABLED=true —— 思考链已开启，已知后果："
        "① 判定/精排这类分类任务会慢数倍；"
        "② 思考与结论**共用 LLM_MAX_TOKENS=%s**，思考吃满则 content 为空 → "
        "判定器静默判「不歧义」→ **漏报**。若出现空结论，先调大 LLM_MAX_TOKENS。"
        "除对比评测外建议保持 false。",
        s.llm_max_tokens,
    )
    audit("thinking_enabled_warning", provider=s.llm_provider,
          model=s.llm_model, max_tokens=s.llm_max_tokens)


@dataclass(frozen=True)
class LLMReply:
    """一次 LLM 调用的结果 **+ 元信息**（P0-1 / P0-4）。

    存在的唯一理由：**「模型没答」必须与「模型答了」可区分**。

    ⚠️ 原来 `complete()` 结尾是 `return msg.content or ""` —— **`finish_reason` 被丢弃**，
    于是「被 `max_tokens` 截断」与「模型本来就没答」在代码里长得一模一样，
    调用方只能拿到一个空串，然后**静默继续**。
    而 P0-1 明确要求把 `finish_reason=length` 判为"无法判断" ——
    **不把元信息带出来，那条要求根本实现不了。**
    """

    text: str
    finish_reason: str | None = None

    # ⭐ `2.0-59` 工程层埋点：**token 用量**（此前一个数都没有）。
    #    ⚠️ 字段名用 provider 的原生名（`prompt_tokens`/`completion_tokens`），
    #    不做"input/output"改写 —— 换 provider 时对得上文档。
    #    `None` = **这一次没拿到用量**（不是 0）—— 别把"没数据"记成"零成本"。
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def answered(self) -> bool:
        """模型是否给出了**可用内容**（纯空白不算答了）。"""
        return bool(self.text.strip())

    @property
    def truncated(self) -> bool:
        """是否因 `max_tokens` 被截断（这类"没答"与"模型确实无话可说"不是一回事）。"""
        return (self.finish_reason or "").lower() == "length"

    @property
    def empty_reason(self) -> str | None:
        """没答的原因（答了则为 None）。"""
        if self.answered:
            return None
        return "truncated" if self.truncated else "empty"


async def complete_with_meta(messages: list[dict], temperature: float = 0.1) -> LLMReply:
    """调用 LLM，返回**内容 + 元信息**。调用方**必须**判 `answered` 再决定怎么用。

    需要区分"没答"与"答了"的调用点用这个；只想要文本、且拿空串也无所谓的用 `complete()`。
    """
    """调用 LLM 生成回答，返回文本内容。

    temperature 约定：**要求可复现的任务（精排、歧义判定）传 0**；
    需要多样性的任务（查询改写）保留默认 0.1；答案生成由 Agent 侧控制。

    ⚠️ 本函数是**延迟敏感**路径（判定 / 精排）的收口：超时取自
    `llm_timeout_judge`（D9-⑨，**默认 8s**）——
    生成路径（Agent）走 `graph_builder`，另有更宽的一档，两者**不做对齐**。

    ⭐ `2.0-58`：**"慢"不重试，"坏"重试一次**。超时（已花掉整份预算）→ 直接
    `raise LLMCallError(kind="timeout")`；连接/SSL/5xx 这类**秒级失败** → 再试一次
    （`llm_fastfail_retries` / `llm_fastfail_within_s`），仍失败则
    `raise LLMCallError(kind="transient")`。调用方按 `kind` 区分处置，
    ⛔ 不要再把所有失败都叫 `unknown`。
    """
    settings = get_settings()
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY 未配置，请先在 .env 填入")
    warn_if_thinking_enabled()

    # 思考链：默认关闭。判定/精排都是分类任务，思考**既慢又会让 content 为空**
    # （思考与 content 共用 max_tokens 预算，吃满则 content 为空 → 调用方静默拿到空串）。
    extra: dict = {}
    if not settings.llm_thinking_enabled:
        # ⚠️ `reasoning_effort` 是 **DeepSeek 语义**。换 provider（如通用的 `openai/`）时，
        # 它可能被 `drop_params=True` **静默丢弃 → 思考链复活**。
        # 实测（eval/verify_provider_unbind.py）：deepseek/ 下 0 字思考 / 983ms；
        # 换 openai/ 后 7298 字思考 / 11591ms，且 finish=length。下面的告警就是兜这个底。
        extra["reasoning_effort"] = "none"

    call_kwargs = dict(
        # provider 前缀决定用哪套**协议适配器**（可配，默认 "deepseek"——理由见 settings.py）
        model=f"{settings.llm_provider}/{settings.llm_model}",
        messages=messages,
        api_key=settings.llm_api_key,
        api_base=settings.llm_base_url,
        temperature=temperature,
        max_tokens=settings.llm_max_tokens,   # D9-⑩：原为硬编码 2048
        timeout=settings.llm_timeout_judge,   # D9-⑨：原为硬编码 60（等于没有超时）
        # ⚠️ 仍是显式 0：**litellm 层的重试放弃不用**，重试由下面这一层做 ——
        #    因为只有这一层才知道"这次失败是快的还是慢的"（`2.0-58`）。
        num_retries=settings.llm_max_retries_judge,
        # ⚠️ **默认 False = 不静默丢弃**（`2.0-41`）。
        # 原来是写死的 `True`：换 provider 后 `reasoning_effort="none"` 会被**静默丢掉**
        # → **思考链复活且不报错**（D8 踩过的那个坑）。
        # 现在不支持就**报错** —— 从"静默失效"变成"响"。
        # ⚠️ 换 provider 后若这里报错，**那是设计如此**：去 `2.0-42` 补翻译，别改回 True。
        drop_params=settings.llm_drop_params,
        **extra,
    )

    # ⭐ `2.0-58`：只重试「坏」（秒级失败），⛔ 不重试「慢」（超时）。
    #   最坏耗时上界：一次性超时 = `timeout`（8s）；
    #   快速失败后撞超时 = `within_s + timeout`（2s + 8s = 10s）。
    #   ⛔ 不会回到 D9 之前的 `60s × 4`。
    max_attempts = 1 + max(0, settings.llm_fastfail_retries)
    started_at = time.perf_counter()
    resp = None
    for attempt in range(1, max_attempts + 1):
        attempt_started = time.perf_counter()
        try:
            resp = await litellm.acompletion(**call_kwargs)
            break
        except Exception as exc:  # noqa: BLE001 —— 分类后要么重试、要么包成 LLMCallError
            kind = classify_failure(exc)
            attempt_elapsed = time.perf_counter() - attempt_started
            retryable = (
                kind == "transient"                       # 只重试"坏"
                and attempt_elapsed < settings.llm_fastfail_within_s  # 且它确实是"秒级失败"
                and attempt < max_attempts
            )
            if retryable:
                # 留痕：否则"重试救回来的一次"在日志里完全看不见，
                # 下次有人看到延迟抬高会找不到原因。
                audit_err("llm_retry", provider=settings.llm_provider,
                          model=settings.llm_model, kind=kind, attempt=attempt,
                          attempt_elapsed_s=round(attempt_elapsed, 3))
                logger.warning("LLM 调用快速失败（%s，%.2fs），重试 %d/%d：%s",
                               kind, attempt_elapsed, attempt, max_attempts - 1, exc)
                continue
            raise LLMCallError(exc, kind, attempt,
                               time.perf_counter() - started_at) from exc

    if resp is None:  # 理论不可达（循环要么 break 要么 raise），留一道显式闸
        raise LLMCallError(RuntimeError("LLM 调用未产生结果"), "fatal", 0,
                           time.perf_counter() - started_at)

    msg = resp.choices[0].message

    # ⚠️ 兜底告警：本该关思考，却收到了思考内容 → 说明 provider 适配器把
    # `reasoning_effort="none"` 丢了（**换厂商时最容易踩的坑**）。
    # 必须让它"响"：否则表现为"莫名慢 10 秒 + 偶尔结论为空"，几周后才被发现。
    leaked = getattr(msg, "reasoning_content", None) or ""
    if not settings.llm_thinking_enabled and leaked:
        audit("thinking_leaked", provider=settings.llm_provider,
              model=settings.llm_model, reasoning_chars=len(leaked))

    # ⭐ `2.0-59`：把用量带出来。⚠️ provider 可能不给 `usage`（或给 `None`）→ **如实记 None**，
    #    ⛔ 不要 `getattr(..., 0)` 把"没拿到"伪装成"用了 0"。
    usage = getattr(resp, "usage", None)
    return LLMReply(
        text=msg.content or "",
        finish_reason=getattr(resp.choices[0], "finish_reason", None),
        prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
        completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
    )


async def complete(messages: list[dict], temperature: float = 0.1) -> str:
    """`complete_with_meta()` 的**文本兼容版**（原签名，5 个 eval 脚本仍在使用）。

    ⚠️ **中心化静默降级告警**：本函数会把"没答"记为 **ERR 审计**。
    这样即使某个调用点没迁去用 `complete_with_meta()`、仍然只拿一个空串，
    「模型没答」这件事也**一定会在日志里留下痕迹**（P0-4 要堵的就是这个洞）。
    与调用点自己的专项审计（如 `rerank_empty` / `ambiguity_unparsed`）**是互补的**：
    这里是"任何路径都不静默"的兜底，那里带具体上下文。
    """
    reply = await complete_with_meta(messages, temperature=temperature)
    if not reply.answered:
        audit_err("llm_empty_reply", reason=reply.empty_reason,
                  finish_reason=reply.finish_reason)
    return reply.text
