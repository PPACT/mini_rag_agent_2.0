"""`2.0-29` **第四问：端到端**（`交流区 §1.65③`）。

## 它回答什么

前三问只证明「**命中了那块，但块里数值与标签分在两行**」——
⚠️ **"那到底答不答得出来"，前三问没有回答**
（文档侧在 `§1.65②` 认领了这个缺口：判读表**少了一个维度**）。

结论落到判读表（`§1.65②` 修订版）：

| ① R@K | ②b 同行率 | **④ 端到端** | 结论 |
|---|---|---|---|
| 好 | 低 | ✅ 答对 | 🟡 **不用修** —— 「分离」不影响端到端 |
| 好 | 低 | ❌ 答错 | 🔴 **必修** —— 理由比"R@K 差"精确得多：**召回了，但读不出** |

## 口径（文档侧已给死，`§1.65③`）

    输入：⭐ 固定给**命中块**（= ②b 判定用的同一块）—— **不给 top-3 拼接**
          （多块会把"答案从哪来"搞混，这题就不再是在问"分离"了）
    两臂：A = **库里的块原文**（实测） ｜ B = **对照臂** = 正确文本（出题时那版）
    判"答对"：答案里出现正确数值，**且该数值挂在正确的标签/语境上**
              （"数字碰巧出现"不算对 —— 例如把 120 当成 6 的答案）
    报法：答对率 ＋ ⭐ **逐题把 LLM 答案原文贴出来**（7 题少，人工能复核）

## ⭐ 对照臂为什么必须有

    对照答对 / 实验答错 → 🔴 确诊：**问题在解析** → 必修
    对照也答错         → ⚠️ 是**题目或模型**的问题，**与 `2.0-29` 无关**

⚠️ 没有对照臂，第四问会把"**模型不会答**"记到"**解析**"头上
—— 正是 `P-2` / 「验收脚本自身也要被验收」那一类错。

## ⭐⭐ 第三臂 C：**盲猜臂**（⚠️ **我加的，不在文档侧给死的口径里**）

**为什么必须加**：这 7 题的标准值全是**常识性政策数值**（住宿上限、病假工资比例、婚假天数之类）。
模型**完全可能没读资料、凭先验就答对** —— 那 A 臂的"全对"就**证明不了"块读得通"**，
第四问会变成一个**没有区分度**的指标（正是 `§1.65⑥` 那条：**先证明它有区分度**）。

**做法**：同一套提示词、同一个模型，只把资料换成**无关内容**。
- C **0 命中** ⇒ 第四问有区分度，A 的答对可归因于块
- C **也命中** ⇒ 🔴 A 的答对**不可归因** —— 必须报这个，不能只报 A 好看

*（这是对"口径已给死"的一处**越界**：A/B 两臂的数字仍按原口径报，C 是我加的判别项。）*

## ⚠️ 适用范围（**别当强结论用**）

**7 题 · 单次** → **弱证据**，先看趋势（同 `§1.47` 迷你集的规矩）。

## ⚠️ 两个输入文件都**不入库**（内容 = 语料原文，协议 §12.5）

    eval/local/dataset_pdf_numeric.jsonl    题面 / anchor / value
    eval/local/pdf_numeric_reference.jsonl  对照臂的"正确文本"

## 判「语境对不对」：脚本只做**下界**

脚本只能判"**数值出没出现**"（确定性）。**"挂在正确的标签上"要人读** ——
所以本脚本**同时贴出逐题原文**，那一列**留空给人填**。

## 用法

    python eval/run_pdf_numeric_e2e.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.paths import CORPUS_DIR  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from src.agent.graph_builder import _build_model  # noqa: E402  ⭐ 与生成链路同一个构造器
from src.config.settings import get_settings  # noqa: E402
from src.db.connection import close_pool  # noqa: E402
from src.db.kb import KB_STRESS  # noqa: E402
from src.rag.retriever import retrieve  # noqa: E402

LOCAL = Path(__file__).resolve().parent / "local"
DATASET = LOCAL / "dataset_pdf_numeric.jsonl"
REFERENCE = LOCAL / "pdf_numeric_reference.jsonl"

# ⚠️ 与 `run_pdf_numeric_eval.py` **同一套基线口径**（少了它，两问就不可比）
EVAL_DEPARTMENT = ["IT", "公司"]
EVAL_SECRET_LEVEL = 3
MODE = {"use_rewrite": False, "use_rerank": False, "use_hybrid": False}

# ⚠️ **两臂共用同一套提示词** —— 唯一的变量必须是"给它的那段文字"（P-9）
SYSTEM = ("你是企业制度问答助手。**只依据【资料】作答**；"
          "资料里找不到答案时，直接回答「资料中没有」。答案简短，先给结论。")
HUMAN = "【资料】\n{ctx}\n\n【问题】{q}"

# ⚠️ **第三臂（消融）** —— 不在文档侧给死的口径里，是**我加的**，理由见 docstring：
#    这 7 题的标准值全是**常识性政策数值**（住宿上限 / 病假工资比例之类），
#    模型**可能根本没读资料、凭先验就答对** → 那第四问就是个**没有区分度**的指标。
#    给一段**无关资料**再看它答什么：仍答对 ⇒ 它在猜 ⇒ 第四问无效。
BLIND_CTX = "（本页为空白页，无任何制度内容。）"


def _load(path: Path, what: str) -> list[dict]:
    # ⛔ 不做"假装支持"：缺文件就**显式报错**并说清怎么建。
    if not path.exists():
        raise SystemExit(
            f"❌ 找不到{what}：{path}\n"
            "   它**不入库**（内容 = 语料原文，协议 §12.5）——\n"
            "   请按 eval/run_pdf_numeric_eval.py 的 docstring 自建一份放进 eval/local/。")
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _text(msg) -> str:
    c = msg.content
    if isinstance(c, list):                       # 有些厂商回结构化块
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
    return str(c)


RETRIES = 3


async def ask(model, ctx: str, q: str) -> tuple[str, str | None]:
    """返回 `(答案, 错误)`。

    ⚠️ 链路**实测会偶发失败**（撞过一次 `SSL: CERTIFICATE_VERIFY_FAILED`，自签证书在链里；
    同一构造器随后三次重试全通）→ **不能让它把"有答案"记成"没答案"**，所以重试。
    重试仍失败就**如实记下**，**不当答案用、也不计入分母**（else 结论会被网络噪声污染）。
    """
    last: Exception | None = None
    for _ in range(RETRIES):
        try:
            msg = await model.ainvoke([SystemMessage(SYSTEM),
                                       HumanMessage(HUMAN.format(ctx=ctx, q=q))])
            return _text(msg).strip(), None
        except Exception as e:  # noqa: BLE001
            last = e
    return "", f"{type(last).__name__}: {str(last)[:120]}"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", default=KB_STRESS)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--json", default=str(ROOT / "logs" / "pdf_numeric_e2e.json"))
    args = ap.parse_args()

    # ---- 跑前过闸（复用那道闸，不另写）----
    from eval.check_ingest_complete import check as gate

    g = await gate(args.kb, str(CORPUS_DIR))
    if g["missing"] or g["unexpected"] or g["empty"]:
        print("[X] **灌库不完整，先别评估**")
        return 1
    print(f"✅ 过闸：{g['known']} 个认得 / 库中 {g['in_db']} 份\n")

    dataset = _load(DATASET, "评测集")
    ref = {r["id"]: r["correct_text"] for r in _load(REFERENCE, "对照臂文本")}
    missing = [r["id"] for r in dataset if r["id"] not in ref]
    if missing:
        raise SystemExit(f"❌ 对照臂缺这几题：{missing}")

    s = get_settings()
    model = _build_model()
    # ---- ⭐ P-2：事后核实**实际生效**的参数（配置漂移是本项目最高频的坑）----
    print("【实际生效配置】")
    print(f"  模型        = {s.llm_model}")
    print(f"  温度        = 0.1（`_build_model` 写死）")
    print(f"  超时/重试   = {s.llm_timeout_generate}s × {s.llm_max_retries_generate}")
    print(f"  检索模式    = {MODE}（与 R@K 那轮同一套基线）")
    print(f"  answer_key  = {'已配置' if s.llm_api_key else '❌ 空 —— 会全部失败'}\n")
    if not s.llm_api_key:
        return 1

    rows = []
    for row in dataset:
        _, chunks = await retrieve(row["question"], EVAL_DEPARTMENT, EVAL_SECRET_LEVEL,
                                   kb=args.kb, top_k=args.top, **MODE)
        # ⭐ 命中块 = ②b 判定用的**同一块**
        rank, block = None, None
        for i, c in enumerate(chunks, start=1):
            if c.source_file == row["source"] and row["anchor"] in (c.content or ""):
                rank, block = i, c.content or ""
                break
        if block is None:
            rows.append({**row, "rank": None, "exp": "（未命中，无法喂给模型）", "ctl": "—",
                         "exp_has_value": None, "ctl_has_value": None})
            continue
        exp, exp_err = await ask(model, block, row["question"])
        ctl, ctl_err = await ask(model, ref[row["id"]], row["question"])
        blind, blind_err = await ask(model, BLIND_CTX, row["question"])
        rows.append({
            **row, "rank": rank, "exp": exp, "ctl": ctl, "blind": blind,
            # ⭐ **存下喂给 A 的那段块原文** —— 否则结论无法被复核
            #    （⚠️ 它是语料原文 → 只落 logs/，仓库里绝不出现）
            "exp_ctx": block,
            "exp_error": exp_err, "ctl_error": ctl_err, "blind_error": blind_err,
            # ⚠️ 脚本只判"值出没出现" = **下界**；"语境对不对"留给人
            "exp_has_value": None if exp_err else row["value"] in exp,
            "ctl_has_value": None if ctl_err else row["value"] in ctl,
            "blind_has_value": None if blind_err else row["value"] in blind,
        })

    print(f"【第四问 · {len(rows)} 题】")
    print(f"  {'#':<7}{'命中块':>6}  {'A 实验(库里的块)':<14}{'B 对照(正确文本)':<14}{'C 盲猜(无关资料)'}")
    for r in rows:
        f = lambda v: "—" if v is None else ("✅" if v else "❌")   # noqa: E731
        print(f"  {r['id']:<7}{('—' if r['rank'] is None else r['rank']):>6}  "
              f"{f(r['exp_has_value']):<14}{f(r['ctl_has_value']):<14}{f(r['blind_has_value'])}")

    n = sum(1 for r in rows if r["rank"] is not None)
    def cnt(k): return sum(1 for r in rows if r[k])
    def errs(k): return sum(1 for r in rows if r[f"{k}_error"])
    ea, ca, ba = cnt("exp_has_value"), cnt("ctl_has_value"), cnt("blind_has_value")
    ee, ce, be = errs("exp"), errs("ctl"), errs("blind")
    print(f"\n【汇总 · 可喂题 {n}】")
    for tag, c_, e_ in (("A 实验臂（库里的块）", ea, ee),
                        ("B 对照臂（正确文本）", ca, ce),
                        ("C 盲猜臂（无关资料）", ba, be)):
        print(f"  {tag}：出现正确数值 = {c_}/{n - e_}"
              + (f"   ⚠️ 调用失败 {e_} 题" if e_ else ""))
    print("\n  ⚠️ **这是下界** —— 「数值挂在正确的标签/语境上」要人读下面的原文")
    if ba:
        print(f"  🔴 **C 盲猜臂也命中 {ba} 题 ⇒ 第四问【没有区分度】**："
              "这些数值模型凭先验就能答，\n     A 的答对**不能归因于「块读得通」** —— 请连同 C 一起看。")
    else:
        print("  ✅ **C 盲猜臂 0 命中 ⇒ 第四问有区分度**：A 的答对**不是靠先验猜的**。")

    print("\n【逐题答案原文（文档侧点名要看）】")
    for r in rows:
        print(f"\n  ── #{r['id']} ｜ {r['question']}")
        print(f"     命中块排名 = {r['rank']} ｜ 标准值 = {r['value']}")
        if r.get("exp_ctx"):
            print(f"     喂给 A 的块（前 60 字）= {r['exp_ctx'][:60]!r}")
        for arm, key in (("A 实验臂", "exp"), ("B 对照臂", "ctl"), ("C 盲猜臂", "blind")):
            err = r.get(f"{key}_error")
            print(f"     [{arm}]" + (f" ⚠️ 调用失败：{err}" if err else f" {r[key]}"))

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps({
        "config": {"model": s.llm_model, "temperature": 0.1, "mode": MODE,
                   "top": args.top, "kb": args.kb},
        "summary": {"n": n, "exp_has_value": ea, "ctl_has_value": ca, "blind_has_value": ba},
        "rows": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n产物 → {args.json}")
    await close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
