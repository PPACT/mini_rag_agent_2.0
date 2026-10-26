"""`2.0-68` 成本台账：把**已有**埋点汇总成一份可报的账（⛔ 不新增采集）。

## 口径

| 账目 | 来源 | 说明 |
|---|---|---|
| 每题 token | 评测产物 `summary.tokens` | `2.0-59` 的埋点：判定 / 生成 两段，另记 `n_measured` |
| 每题延迟 | 产物 `summary.latency` | p50 / p95 / max ＋ `>5s` 占比（⛔ 不只报平均） |
| 一轮评测总耗时 | **各题 `timings.total_ms` 求和** | ⭐ **串行口径**（并发跑会更快，见 `logs/bench_concurrency_*.json`） |
| 重嵌范围 | 直查向量库的切片数 | ⚠️ `content_hash` 未做（`2.0-30`）⇒ 改 `content` 就要**全量重嵌** |
| 入库耗时 | ⚠️ **未采集** | 历史产物里没有计时字段；本工具**不编数**，只如实标"缺" |

## 用

    python eval/cost_ledger.py                       # 自动扫 logs/ 下已有的评测产物
    python eval/cost_ledger.py --files logs/a.json logs/b.json --json logs/cost.json
    # 想折算成钱：自己给单价（每 100 万 token），⛔ 工具不内置任何价格
    python eval/cost_ledger.py --price-in 1.0 --price-out 2.0
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# ⚠️ `--no-db` 之外要查库时得 import `src.*`；脚本在 `eval/` 下跑时 `src` 不在 sys.path
sys.path.insert(0, str(ROOT))


def _pctl(values, q):
    s = sorted(v for v in values if isinstance(v, (int, float)))
    if not s:
        return None
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


def _ledger_for_eval(path: Path) -> list[dict]:
    """一个评测产物 → 每个臂一行账。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for arm, res in (data.get("results") or {}).items():
        s = res.get("summary") or {}
        rows = res.get("rows") or []
        tok = s.get("tokens") or {}
        n = tok.get("generate", {}).get("n_measured") or len(rows) or 0
        total_tokens = tok.get("grand_total_tokens")
        # ⚠️ 老产物（`2.0-59` 之前）没有 token 埋点：`0` 要显示成"无数据"，
        #    ⛔ 不能当"零成本"（那会把历史产物读成"免费"）
        if not total_tokens:
            total_tokens = None
        totals = [r.get("timings", {}).get("total_ms") for r in rows]
        totals = [t for t in totals if isinstance(t, (int, float))]
        lat = s.get("latency") or {}
        out.append({
            "artifact": path.name,
            "arm": arm,
            "n_questions": len(rows),
            "tokens_total": total_tokens,
            "tokens_per_q": round(total_tokens / n, 1) if total_tokens and n else None,
            "tokens_judge": tok.get("ambiguity", {}).get("total_tokens"),
            "tokens_generate": tok.get("generate", {}).get("total_tokens"),
            # ⚠️ 串行口径：各题耗时之和。并发跑的数字在 bench 产物里，⛔ 别混
            "serial_minutes": round(sum(totals) / 60000, 1) if totals else None,
            "latency_p50_ms": (lat.get("total_ms") or {}).get("p50"),
            "latency_p95_ms": (lat.get("total_ms") or {}).get("p95"),
            "latency_max_ms": (lat.get("total_ms") or {}).get("max"),
            "gt_5s_ratio": (lat.get("total_ms") or {}).get("gt_5s_ratio"),
        })
    return out


def _chunk_counts() -> dict:
    """直查两个库的切片数 —— "重嵌范围"就是它（`content_hash` 未做 ⇒ 全量重嵌）。"""
    try:
        import asyncio

        from src.db.connection import get_pool
        from src.db.kb import KB_REAL, KB_STRESS

        async def go():
            res = {}
            for name, kb in (("real", KB_REAL), ("stress", KB_STRESS)):
                try:
                    pool = await get_pool(kb)
                    res[name] = int(await pool.fetchval("SELECT count(*) FROM chunks"))
                except Exception as e:  # noqa: BLE001
                    res[name] = f"查询失败：{type(e).__name__}"
            return res

        return asyncio.run(go())
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def _money(tokens: int | None, prompt: int | None, completion: int | None,
           pin: float | None, pout: float | None) -> float | None:
    if tokens is None or pin is None or pout is None:
        return None
    if prompt is None or completion is None:
        return None
    return round((prompt / 1e6) * pin + (completion / 1e6) * pout, 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", default=None)
    ap.add_argument("--json", default=str(ROOT / "logs" / "cost_ledger.json"))
    ap.add_argument("--price-in", type=float, default=None, help="每 100 万输入 token 的单价（自己给）")
    ap.add_argument("--price-out", type=float, default=None, help="每 100 万输出 token 的单价（自己给）")
    ap.add_argument("--no-db", action="store_true", help="跳过切片数查询（无 DB 时）")
    args = ap.parse_args()

    files = ([Path(f) for f in args.files] if args.files else
             [Path(p) for p in sorted(glob.glob(str(ROOT / "logs" / "layered_eval_*.json")))
              + sorted(glob.glob(str(ROOT / "logs" / "regression_*_2026*.json")))])
    files = [f for f in files if f.exists()]

    rows: list[dict] = []
    for f in files:
        try:
            rows.extend(_ledger_for_eval(f))
        except Exception as e:  # noqa: BLE001
            rows.append({"artifact": f.name, "arm": "—", "error": f"{type(e).__name__}: {e}"})

    for r in rows:
        r["cost_estimate"] = _money(r.get("tokens_total"), r.get("tokens_judge"),
                                    r.get("tokens_generate"), args.price_in, args.price_out)

    chunks = {} if args.no_db else _chunk_counts()
    ledger = {
        "scope": {
            "note": "只汇总**已有产物**，⛔ 不新增采集；延迟/耗时是**串行口径**",
            "artifacts": [f.name for f in files],
            "price_in_per_mtok": args.price_in,
            "price_out_per_mtok": args.price_out,
        },
        "evals": rows,
        "reembed_scope": {
            "chunks": chunks,
            "why_full": "`content_hash` 未做（2.0-30）⇒ 改 `content` 只能全量重嵌",
        },
        "ingest_cost": {
            "status": "未采集",
            "why": "历史产物里没有入库计时字段；本工具不编数",
            "how_to_fill": "跑一次 ingest 时用 `--json` 或外部计时代为记录（属新增采集，需另立项）",
        },
    }

    out = Path(args.json)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        # ⚠️ 容器里 `logs/` 是**只读挂载**（产物由宿主提供）—— 退回临时目录并**明说**，
        #    ⛔ 不静默失败（否则会以为"出了一份账"，其实没落盘）。
        out = Path(tempfile.gettempdir()) / Path(args.json).name
        out.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"⚠️ 原路径不可写（{type(e).__name__}: {e}）→ 已改写到 {out}")

    print("\n【评测成本台账】（串行口径）")
    print(f"{'产物':<34}{'臂':<10}{'题数':>4}{'总token':>9}{'每题token':>10}{'串行分钟':>9}")
    for r in rows:
        if "error" in r:
            print(f"{r['artifact']:<34}{'—':<10}  ❌ {r['error']}")
            continue
        tok = "—" if r["tokens_total"] is None else str(r["tokens_total"])
        per = "—" if r["tokens_per_q"] is None else str(r["tokens_per_q"])
        mins = "—" if r["serial_minutes"] is None else str(r["serial_minutes"])
        print(f"{r['artifact']:<34}{r['arm']:<10}{r['n_questions']:>4}{tok:>9}{per:>10}{mins:>9}")
    print("\n【重嵌范围】每个库的全部切片数（改 content 就得全量重嵌）：", chunks)
    print(f"【入库耗时】ledger['ingest_cost'] —— ⚠️ {ledger['ingest_cost']['status']}")
    print(f"\n产物 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
