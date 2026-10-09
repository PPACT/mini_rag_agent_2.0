"""`2.0-7` 分层评估集（50 题）—— **两轮：纯向量 / 混合检索+重排**。

口径见 `docs/local/eval_draft/layered_eval_design.md`（题面在同目录 `layered_eval_50q.md`）。

## 它回答什么（设计文档 §一）

1. ⭐ **「哪一类查询差」** —— 六大类**分层**报 R@1 / R@5（只报总平均就把分层意义抹掉了）
2. **纯向量 vs 混合检索+重排，差多少**
3. 口径写死 + 可导出（`2.0-53`）

## ⚠️ 三条设计原则（`§1.65⑥` 买来的教训，写在这里免得再犯）

1. **每个指标先证明它有区分度** —— 恒为常数的不叫指标
2. **不许自我实现** —— 自检**不许保证指标取值**（自检只验"anchor 在库里找得到"，那是**定位器**要求，
   不等于"一定命中"—— 命中还取决于检索）
3. **命中判据必须锚到「块内容」**，不能"文件对上了就算"

## 🔴 一个必须写死的参数（静默陷阱）

    settings.hybrid_search_enabled = True
      → 评测脚本【不传 use_hybrid】就等于【开了混合】
      → 「基线组」静默变成混合组，而结果看着完全正常

→ **「纯向量」那一轮必须【显式】传 `use_hybrid=False`**。本脚本两轮都**显式**给全三个开关，
   并把**实际生效的模式**打进产物（`P-2`：显式传参 + 事后核实实际生效值）。

## ⚠️「拒答」怎么判（设计文档 §四，口径写死）

系统「答不上来」有**四条出口**，**只有两条算拒答**：

| 出口 | 算不算 |
|---|---|
| `answer` 含哨兵句「知识库中没有找到相关信息」（`prompts/rag_system.yaml` 写死） | ✅ |
| 生成环节返回空（`chat_api._NO_ANSWER_TEXT`） | ✅ |
| `need_clarification=True`（"你问的不清 / 资料打架"，不是"没答案"） | ❌ |
| `judge_status="unknown"`（**判定器失败 ≠ 答案不存在**） | ❌ |

⚠️ **误拒率必须一并报** —— 只报拒答正确率 = **拒答越多分越高**，靠"全拒"就能刷满。

## ⚠️ 与生产链路的差别（**适用范围**）

生产 `/chat` 用 ReAct agent（带 MCP 工具）+ **固定查 `KB_REAL`**；
本脚本为了能跑在**压测库**上，直接 `retrieve()` → 用**同一套提示词模板 + 同一个模型构造器**生成。
**检索口径与判据一致；生成环节少了"工具调用"那一层** —— 读数字时记住这点。

## 输入（**不入库** —— 题面/答案/anchor 全是语料派生）

    eval/local/dataset_layered_50q.jsonl

## 用法

    python eval/run_layered_eval.py            # 两轮都跑
    python eval/run_layered_eval.py --rounds 纯向量
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.paths import CORPUS_DIR  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from src.agent.graph_builder import _build_model  # noqa: E402  ⭐ 与生成链路同一个构造器
from src.api.chat_api import _NO_ANSWER_TEXT  # noqa: E402  ⭐ 单一来源，不抄字符串
from src.config.prompts import load_templates  # noqa: E402
from src.config.settings import get_settings  # noqa: E402
from src.db.connection import close_pool, get_pool  # noqa: E402
from src.db.kb import KB_STRESS  # noqa: E402
from src.rag.ambiguity import check_ambiguity  # noqa: E402
from src.rag.retriever import retrieve  # noqa: E402

DATASET = Path(__file__).resolve().parent / "local" / "dataset_layered_50q.jsonl"

# ⚠️ 每个臂都把**三个开关显式给全**（§四 的静默陷阱）；名字即产物里的列名。
# ⭐ `2.0-49` **四臂**（`提醒 #14` 第 1 批）：把「混合」与「重排」**拆开** ——
#    原来那两轮**差了整整两个变量**（`hybrid` 与 `rerank` 同开同关），
#    所以「`R@1` 升 / `R@3` 降」**归因不了**（`P-7`：一次只改一个变量）。
ROUNDS: dict[str, dict] = {
    "纯向量":    {"use_rewrite": False, "use_rerank": False, "use_hybrid": False},
    "混合-only": {"use_rewrite": False, "use_rerank": False, "use_hybrid": True},
    "重排-only": {"use_rewrite": False, "use_rerank": True,  "use_hybrid": False},
    "混合+重排": {"use_rewrite": False, "use_rerank": True,  "use_hybrid": True},
}

KIND_CN = {
    "single_hop": "单跳事实", "multi_hop": "多跳关系", "conflict": "事实冲突",
    "disambiguation": "实体消歧", "table_numeric": "表格数值", "no_answer": "无答案",
}
KIND_ORDER = list(KIND_CN)
KS = (1, 3, 5)

# 哨兵句 —— 在 `prompts/rag_system.yaml` 里写死（这里只做**存在性**判定，不改提示词）
SENTINEL = "知识库中没有找到相关信息"

EVAL_DEPARTMENT = ["IT", "公司"]
EVAL_SECRET_LEVEL = 3
CONCURRENCY = 5
RETRIES = 3


def load_dataset() -> list[dict]:
    if not DATASET.exists():
        raise SystemExit(
            f"❌ 找不到评测集：{DATASET}\n"
            "   它**不入库**（题面/anchor/答案是语料派生，协议 §12.5）——\n"
            "   请从 docs/local/eval_draft/layered_eval_50q.md 重建到 eval/local/。")
    rows = [json.loads(ln) for ln in DATASET.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == 50, f"应 50 题，实际 {len(rows)}"
    return rows


def refuse_exit(ans: str, err: str | None) -> str:
    """**四条出口，只有两条算拒答**（`layered_eval_design.md §四`）。

    取值域：`sentinel` ／ `no_answer_text` ／ `none`
    ⚠️ **外加一个 spec 没枚举的状态 `gen_error`** —— 调用失败**不是"没答案"**，
    据实说清；`refused` 遇它取 `None`（**判不了，不硬判**）。
    """
    if err:
        return "gen_error"
    a = (ans or "").strip()
    if not a:
        return "no_answer_text"          # 生成环节返回空（`chat_api._NO_ANSWER_TEXT` 那条）
    if SENTINEL in a:
        return "sentinel"                # 系统提示词写死的哨兵句
    if _NO_ANSWER_TEXT[:15] in a:
        return "no_answer_text"
    return "none"


def rank_of(chunks, anchors: list[str]) -> tuple[int | None, list[int | None]]:
    """命中 = **块内容**里含 anchor（⚠️ 不是"文件对上了就算"）。

    多 anchor（冲突类给两处）→ 取**最小**名次当 R@K 依据，另记各自名次供复核。
    """
    each: list[int | None] = []
    for a in anchors:
        hit = next((i for i, c in enumerate(chunks, start=1) if a in (c.content or "")), None)
        each.append(hit)
    got = [r for r in each if r is not None]
    return (min(got) if got else None), each


async def ask(model, sem, system: str, human: str, ctx: str, q: str) -> tuple[str, str | None]:
    async with sem:
        last: Exception | None = None
        for _ in range(RETRIES):
            try:
                m = await model.ainvoke([SystemMessage(system),
                                         HumanMessage(human.format(context=ctx, question=q))])
                c = m.content
                return (("".join(p.get("text", "") for p in c) if isinstance(c, list) else str(c)).strip(),
                        None)
            except Exception as e:  # noqa: BLE001
                last = e
        return "", f"{type(last).__name__}: {str(last)[:120]}"


async def one_round(name: str, mode: dict, dataset, kb: str, top: int, model, sem, system, human):
    async def one(row) -> dict:
        # ⭐ 传 `trace` 进去（传引用）—— 拿**重排之前**的粗排候选池。
        #    这是 `提醒 #15` H1/H2 的判据：anchor 块**在不在**那 20 条里。
        trace: dict = {}
        _, chunks = await retrieve(row["question"], EVAL_DEPARTMENT, EVAL_SECRET_LEVEL,
                                   kb=kb, top_k=top, trace=trace, **mode)
        rank, each = rank_of(chunks, row.get("anchors") or [])
        # ---- 重排**之前**：anchor 在池里的位置与它的**向量分**（`None` = 压根没进池 = H1）----
        cands = trace.get("candidates") or []
        anchors = row.get("anchors") or []
        pre_rank, pre_vec_score = None, None
        for i, c in enumerate(cands, start=1):
            if anchors and any(a in (c.content or "") for a in anchors):
                pre_rank, pre_vec_score = i, c.score
                break
        ctx = "\n\n".join(f"[来源{i}] {c.content}" for i, c in enumerate(chunks, start=1))
        # ⭐ 歧义判定（三态）—— **只落字段，不算拒答**（spec §五①：别让"该澄清"混进"误拒"）
        amb = await check_ambiguity(row["question"], chunks)
        ans, err = await ask(model, sem, system, human, ctx, row["question"])

        hit_src = chunks[rank - 1].source_file if rank else None
        bait = row.get("bait") or []
        bait_hit = bool(bait) and any(c.source_file in bait for c in chunks)
        rx = refuse_exit(ans, err)
        refused = None if rx == "gen_error" else rx != "none"

        # ⭐ 语境判定 —— 把"喂了什么"变成"**够不够**"（spec §五②）
        if row.get("anchors"):
            ctx_ok, ctx_rule = rank is not None, "anchor_in_topk"
        elif bait:
            ctx_ok, ctx_rule = bait_hit, "bait_in_topk"
        else:
            ctx_ok, ctx_rule = False, "empty"

        # ⭐ 伴随量（spec §五③）—— **只自动判确定性的那一半**，其余 `null` + `manual` 交人
        if rx == "gen_error":
            answer_wrong, answer_judge = None, "manual"
        elif row.get("should_refuse"):
            # 该拒的题：拒了 = 对；⚠️ **没拒 → 它给了答案，是不是编的必须人看**
            answer_wrong, answer_judge = (False, "auto_sentinel") if refused else (None, "manual")
        else:
            # 有答案的题：拒了 = 没答出来 = 错；答了 → 对不对要人看
            answer_wrong, answer_judge = (True, "auto_sentinel") if refused else (None, "manual")

        return {"id": row["id"], "kind": row["kind"], "rank": rank, "ranks_each": each,
                # ⭐ `提醒 #15`：重排**之前**的池内位置 ＋ 向量分（H1/H2 的判据）
                "pre_rank": pre_rank, "pre_vec_score": pre_vec_score, "pool_n": len(cands),
                "hit_source": hit_src, "answer": ans, "gen_error": err,
                "refuse_exit": rx, "refused": refused,
                "need_clarification": amb.ambiguous, "judge_status": amb.status,
                "ctx_ok": ctx_ok, "ctx_rule": ctx_rule,
                "answer_wrong": answer_wrong, "answer_judge": answer_judge,
                "bait_hit": bait_hit}

    out = await asyncio.gather(*(one(r) for r in dataset))
    print(f"  [{name}] 完成（模式实际生效值：{mode}）")
    return list(out)


def summarize(rows: list[dict], name: str) -> dict:
    gradable = [r for r in rows if r["kind"] != "no_answer"]
    print(f"\n【{name}】分层 R@K（**只比 R@1 会漏掉「排第 2」**；分母 = 该类题数）")
    print(f"  {'类别':<10}{'题数':>4}" + "".join(f"{f'R@{k}':>12}" for k in KS))
    per_kind = {}
    for kind in KIND_ORDER:
        if kind == "no_answer":
            continue
        sub = [r for r in gradable if r["kind"] == kind]
        rec, cells = {}, []
        for k in KS:
            hit = sum(1 for r in sub if r["rank"] is not None and r["rank"] <= k)
            rec[f"R@{k}"] = hit / len(sub) if sub else 0.0
            cells.append(f"{hit}/{len(sub)}")
        print(f"  {KIND_CN[kind]:<10}{len(sub):>4}" + "".join(f"{c:>12}" for c in cells))
        per_kind[kind] = rec
    tot, cells = {}, []
    for k in KS:
        hit = sum(1 for r in gradable if r["rank"] is not None and r["rank"] <= k)
        tot[f"R@{k}"] = hit / len(gradable) if gradable else 0.0
        cells.append(f"{hit}/{len(gradable)}")
    print(f"  {'— 合计':<10}{len(gradable):>4}" + "".join(f"{c:>12}" for c in cells))

    # ⚠️ `gen_error`（生成失败）**必须剔出生成类的所有分母**（口径 `§1.79②`）：
    #    落在无答案题 → 拒答正确率**被压低**（看着更差）；落在有答案题 → 误拒率**被稀释**（看着更好）
    #    —— **两个都不是真数字。**
    gen_err_n = sum(1 for r in rows if r["refuse_exit"] == "gen_error")
    na = [r for r in rows if r["kind"] == "no_answer" and r["refused"] is not None]
    ok = [r for r in gradable if r["refused"] is not None]
    refused_ok = sum(1 for r in na if r["refused"])
    false_ref = sum(1 for r in ok if r["refused"])
    print(f"\n  拒答正确率 = {refused_ok}/{len(na)}")
    print(f"  误拒率     = {false_ref}/{len(ok)}"
          "   ⚠️ **必须与拒答正确率一起看** —— 只报前者可以靠「全拒」刷满")
    if gen_err_n:
        print(f"  ❗ **gen_error_n = {gen_err_n} 题**（**已剔出上面两个分母**）")
    print("  📌 **`R@K` 不受影响** —— 那是检索层，生成失败时 `rank` 照样有效；"
          "把生成失败剔出 `R@K` 分母反而会**掩盖真实回归**")

    # ⭐ 新增字段的分布（spec §五）—— 这些以前**只在报告里、不在产物里** → 回归时复现不了
    print("\n  字段分布（spec §五）：")
    print("    refuse_exit  =", dict(Counter(r["refuse_exit"] for r in rows)))
    print("    judge_status =", dict(Counter(r["judge_status"] for r in rows)))
    print(f"    need_clarification = {sum(1 for r in rows if r['need_clarification'])} 题"
          "   ❌ **不算拒答**（「资料打架」≠「没答案」）")
    print(f"    ctx_ok       = {sum(1 for r in rows if r['ctx_ok'])}/{len(rows)}"
          "   ⭐ 喂给模型的上下文里**够不够**（以前只能从 rank 反推，现在落字段）")
    aw = Counter(r["answer_wrong"] for r in rows)
    print(f"    answer_wrong = True {aw[True]} ｜ False {aw[False]} ｜ **未判 {aw[None]}**")
    unchecked = [r["id"] for r in rows if r["answer_wrong"] is None]
    if unchecked:
        print(f"    ⚠️ **待人工/LLM 判的题 {len(unchecked)} 道**：{unchecked}")
    return {"per_kind": per_kind, "overall": tot,
            "refuse_ok": refused_ok, "refuse_n": len(na),
            "false_refuse": false_ref, "false_n": len(ok),
            "gen_error_n": gen_err_n,          # ⚠️ 生成失败：**单列**，且已剔出上面两个分母
            # ⭐ spec §五 的字段分布 —— 回归 harness 直接吃这些，**不用去报告里抄**
            "refuse_exit": dict(Counter(r["refuse_exit"] for r in rows)),
            "judge_status": dict(Counter(r["judge_status"] for r in rows)),
            "need_clarification": sum(1 for r in rows if r["need_clarification"]),
            "ctx_ok": sum(1 for r in rows if r["ctx_ok"]),
            "answer_wrong": {str(k): v for k, v in
                             Counter(r["answer_wrong"] for r in rows).items()},
            "answer_unjudged": [r["id"] for r in rows if r["answer_wrong"] is None]}


async def main() -> int:
    # ⚠️ 输出重定向到文件时 stdout 是**块缓冲**的 → 中间进度不落盘，只能靠猜。
    #    行缓冲后，`> file` 也能实时看到进度（2026-10-08 实测踩过）。
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", default=KB_STRESS)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题（⚠️ 只给冒烟用；0 = 全跑）")
    ap.add_argument("--rounds", nargs="*", default=list(ROUNDS))
    ap.add_argument("--json", default=str(ROOT / "logs" / "layered_eval.json"))
    args = ap.parse_args()

    from eval.check_ingest_complete import check as gate
    g = await gate(args.kb, str(CORPUS_DIR))
    if g["missing"] or g["unexpected"] or g["empty"]:
        print("[X] 灌库不完整，先别评估")
        return 1
    print(f"✅ 过闸：{g['known']} 个认得 / 库中 {g['in_db']} 份")

    dataset = load_dataset()
    if args.limit:
        dataset = dataset[: args.limit]
        print(f"⚠️ **冒烟模式**：只跑前 {args.limit} 题 —— **这些数字不是结果**")

    # ---- 自检：anchor 与 bait **必须在库里找得到**（⚠️ 那是**定位器**要求，**不等于**一定命中）----
    pool = await get_pool(args.kb)
    texts = [(r["content"] or "") for r in await pool.fetch("SELECT content FROM chunks")]
    docs = {r["f"] for r in await pool.fetch(
        "SELECT COALESCE(original_name, filename) AS f FROM documents")}
    bad = []
    for row in dataset:
        for a in (row.get("anchors") or []):
            if not any(a in t for t in texts):
                bad.append(f"#{row['id']} anchor 在库里找不到：{a!r}")
        # ⚠️ `bait` 是**诱饵的出处（文件名）**，不是内容片段 —— 判据是"这个文件在不在库"。
        #    （设计文档 §交付②：**bait 通过自检 ≠ 有答案**，别把它当出处）
        for b in (row.get("bait") or []):
            if b not in docs:
                bad.append(f"#{row['id']} bait 文件不在库里：{b!r}")
    if bad:
        print("[X] 自检没过 —— 不产出任何数字：")
        for b in bad[:20]:
            print(f"    · {b}")
        return 1
    print(f"✅ 自检通过：{len(dataset)} 题的 anchor / bait 都在库里的块中找得到\n")

    s = get_settings()
    system, human = load_templates()
    model, sem = _build_model(), asyncio.Semaphore(CONCURRENCY)
    print("【实际生效配置】")
    print(f"  模型 = {s.llm_model} ｜ 温度 0.1 ｜ 检索 top_k = {args.top}")
    for name in args.rounds:
        print(f"  轮「{name}」= {ROUNDS[name]}")
    print()

    result = {}
    for name in args.rounds:
        rows = await one_round(name, ROUNDS[name], dataset, args.kb, args.top, model, sem,
                               system, human)
        result[name] = {"rows": rows, "summary": summarize(rows, name)}

    # 无答案那 5 题：逐题贴出来（人读"是不是真的答错" —— 设计文档 §四 的伴随量）
    for name in args.rounds:
        print(f"\n【{name} · 无答案 5 题逐题（人工看「会不会编」）】")
        for r in result[name]["rows"]:
            if r["kind"] != "no_answer":
                continue
            tag = "✅拒答" if r["refused"] else ("⚠️未拒答" if r["refused"] is not None else "❌生成失败")
            bait = "诱饵已召回" if r["bait_hit"] else "⚠️诱饵未召回"
            print(f"  #{r['id']} {tag} ｜ {bait} ｜ {r['answer'][:110]}")
        print("  ⚠️ 命中块排名（应为 None —— 无答案题**不算 R@K**）："
              + ", ".join(f"#{r['id']}={r['rank']}" for r in result[name]["rows"]
                          if r["kind"] == "no_answer"))

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps({
        "config": {"kb": args.kb, "top": args.top, "model": s.llm_model,
                   "rounds": {n: ROUNDS[n] for n in args.rounds}},
        "dataset_size": len(dataset),
        "results": result,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n产物 → {args.json}")
    await close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
