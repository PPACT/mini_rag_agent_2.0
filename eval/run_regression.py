"""`2.0-9` 自动回归 harness —— **抖动测量** ＋ **基线比对**。

口径：`docs/local/eval_draft/regression_spec.md`（第一版）
上游：`layered_eval_design.md`（指标口径 / 判读表）

## 它只回答一个问题

> **这次改动，让数字变好了还是变坏了？**

## ⚠️ 两条地基（口径 §三 / §二）

1. **余量不许凭空拍** —— 先**量抖动**，再定线：
   - **检索类**（`R@K` / `rank`）**理论零抖动**（向量检索无随机 ＋ 本地交叉编码器**无采样**）
     → 逐题一致 ⇒ **零余量**：**丢 1 题就是真回归**
   - **生成类**（拒答 / 误拒 / 答案对错）`temperature=0.1` → **有抖动**
     → 余量 = **观测抖动上限**
2. **⛔ 不许跨臂比** —— `纯向量` 与 `混合+重排` 各比各的（两臂差两个变量）

## 用法

    # ① 量抖动：同配置重跑 N 次，比逐题翻面率
    python eval/run_regression.py jitter logs/regression/run*.json

    # ② 基线比对：L1 总体 / L2 分层 / ⭐L3 逐题差量
    python eval/run_regression.py compare --baseline logs/regression/base.json \
                                          --current  logs/regression/run1.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

KIND_CN = {
    "single_hop": "单跳事实", "multi_hop": "多跳关系", "conflict": "事实冲突",
    "disambiguation": "实体消歧", "table_numeric": "表格数值", "no_answer": "无答案",
}
KS = (1, 3, 5)


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rows(doc: dict, arm: str) -> list[dict]:
    return doc["results"][arm]["rows"]


# ---------------------------------------------------------------- ① 抖动测量
def jitter(paths: list[str]) -> int:
    docs = [load(p) for p in paths]
    arms = list(docs[0]["results"])
    print(f"【抖动测量】{len(docs)} 次同配置重跑 ｜ 臂：{'、'.join(arms)}")
    verdict = {"检索类": True, "生成类": []}

    for arm in arms:
        # 校验：这几次必须是**同配置**，否则比了也没意义
        modes = {json.dumps(d["config"]["rounds"].get(arm), sort_keys=True) for d in docs}
        assert len(modes) == 1, f"⛔ {arm} 的配置不一致：{modes}"
        runs = [{r["id"]: r for r in _rows(d, arm)} for d in docs]
        ids = sorted(runs[0])

        print(f"\n  ── 臂「{arm}」｜配置 {modes.pop()}")
        # 检索类：rank 必须逐题一致
        bad_rank, flipped, gfail = [], [], []
        for qid in ids:
            ranks = [r[qid]["rank"] for r in runs]
            if len(set(ranks)) != 1:
                bad_rank.append((qid, ranks))
            refs = [r[qid].get("refused") for r in runs]
            # ⚠️ **三种状态要分开**：一致 / **翻面**（真抖动）/ **生成失败**（`None` = LLM 没答上来）
            #    —— 把"生成失败"算成"翻面"是**取数错误**（本项目已栽过这类）
            n_fail = sum(1 for x in refs if x is None)
            vals = {x for x in refs if x is not None}
            if n_fail:
                gfail.append((qid, refs, n_fail))
            elif len(vals) > 1:
                flipped.append((qid, refs))
        if bad_rank:
            verdict["检索类"] = False
            print("    🔴 **检索类不一致** —— 我们以为确定性的东西其实是随机的：")
            for qid, v in bad_rank:
                print(f"       #{qid}: {v}")
        else:
            print(f"    ✅ 检索类（rank）**逐题一致**（{len(ids)} 题 × {len(docs)} 次）→ **零余量**")
        if flipped:
            print(f"    ⚠️ 生成类 **翻面 {len(flipped)} 题**（真抖动）：")
            for qid, v in flipped:
                ones = sum(1 for x in v if x)
                print(f"       #{qid}: {v}  → 翻面率 {min(ones, len(v) - ones)}/{len(v)}")
        else:
            print("    ✅ 生成类 **无翻面**")
        if gfail:
            print(f"    ❗ **生成失败 {len(gfail)} 题**（`refused=None`，**不是翻面**）：")
            for qid, v, n in gfail:
                print(f"       #{qid}: {v}  → {n}/{len(v)} 次没答上来（⚠️ 计入「不可比」，不计入余量）")
        verdict["生成类"].append((arm, len(flipped), len(ids), len(gfail)))

    print("\n【结论】")
    print(f"  检索类：{'✅ 零抖动 → **零余量**（丢 1 题即告警）' if verdict['检索类'] else '🔴 **有抖动 → 先查根因，别急着定余量**'}")
    for arm, n, tot, nf in verdict["生成类"]:
        print(f"  生成类（{arm}）：**翻面 {n}/{tot} 题**"
              + (f"　❗另 {nf} 题生成失败（不计入）" if nf else "")
              + ("　（零翻面，但生成 `temperature=0.1` → 仍按「可翻面」处理）" if n == 0 else ""))
    return 0 if verdict["检索类"] else 1


# ---------------------------------------------------------------- ② 基线比对
def compare(base_path: str, cur_path: str) -> int:
    base, cur = load(base_path), load(cur_path)
    red = False
    for arm in cur["results"]:
        b, c = base["results"].get(arm), cur["results"][arm]
        if b is None:
            print(f"⚠️ 基线里没有臂「{arm}」—— 跳过（⛔ 不许拿别的臂当基线）")
            continue
        print(f"\n【{arm}】基线 {Path(base_path).name} → 本次 {Path(cur_path).name}")

        # ---- L1 总体：检索类**零余量**（丢 1 题即红）----
        bo, co = b["summary"]["overall"], c["summary"]["overall"]
        print("  L1 总体：")
        for k in KS:
            bh, ch = bo[f"R@{k}"], co[f"R@{k}"]
            flag = "🔴 红" if ch < bh else ("✅" if ch == bh else "🟢 升")
            if ch < bh:
                red = True
            print(f"    {k}：{bh:.4f} → {ch:.4f}   {flag}")
        bs, cs = b["summary"], c["summary"]
        print(f"    拒答正确率：{bs['refuse_ok']}/{bs['refuse_n']} → {cs['refuse_ok']}/{cs['refuse_n']}"
              "   ⚠️ **必须与误拒率一起看**")
        print(f"    误拒率：  {bs['false_refuse']}/{bs['false_n']} → {cs['false_refuse']}/{cs['false_n']}"
              "   ⚠️ 只报拒答率可以靠「全拒」刷满")

        # ---- L2 分层：⚠️ 只"注意"，除非掉到 0 ----
        print("  L2 分层（**只注意，不判红** —— 小分母类 1 题 = 20%）：")
        for kind, rec in c["summary"]["per_kind"].items():
            brec = b["summary"]["per_kind"].get(kind)
            if not brec:
                continue
            for k in KS:
                if rec[f"R@{k}"] < brec[f"R@{k}"]:
                    zero = rec[f"R@{k}"] == 0 and brec[f"R@{k}"] > 0
                    tag = "  🔴 **整类掉到 0** → 判红" if zero else "  ⚠️ 注意"
                    if zero:
                        red = True
                    print(f"    {KIND_CN.get(kind, kind)} {k}："
                          f"{brec[f'R@{k}']:.2f} → {rec[f'R@{k}']:.2f}{tag}")

        # ---- ⭐ L3 逐题差量：最可操作的一档 ----
        bmap = {r["id"]: r for r in b["rows"]}
        worse = [(r["id"], bmap[r["id"]]["rank"], r["rank"])
                 for r in c["rows"]
                 if r["id"] in bmap and _worse(bmap[r["id"]]["rank"], r["rank"])]
        print(f"  ⭐ L3 逐题差量：**退化 {len(worse)} 题**"
              + ("（`rank` 由有名次 → 没进 top-K，或名次变大）" if worse else " ✅"))
        for qid, b_, c_ in worse:
            print(f"    #{qid}  rank {b_} → {c_}")
    print("\n【判定】" + ("🔴 **有回归**" if red else "✅ 无回归（L1 未降、无整类归零）"))
    return 1 if red else 0


def _worse(before, after) -> bool:
    """检索类**零余量**：名次变大、或掉出 top-K（`None`）都算退化。"""
    if before is None:
        return False
    return after is None or after > before


def main() -> int:
    ap = argparse.ArgumentParser(description="2.0-9 回归 harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("jitter", help="同配置重跑多次 → 逐题翻面率")
    j.add_argument("files", nargs="+")
    c = sub.add_parser("compare", help="基线比对：L1 / L2 / L3")
    c.add_argument("--baseline", required=True)
    c.add_argument("--current", required=True)
    a = ap.parse_args()
    return jitter(a.files) if a.cmd == "jitter" else compare(a.baseline, a.current)


if __name__ == "__main__":
    raise SystemExit(main())
