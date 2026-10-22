"""CFQA 小样本 · **检索层命中率（文件 ＋ 页）** —— ⭐ **零 token**（不调 LLM）。

⭐ **为什么能零 token**：CFQA 每题自带 `filename` ＋ `page` ⇒ 直接判「召回的块
**对不对**（文件 + 页）」即可，**不需要答案判官**（那要花钱）。
📌 口径来源：题集自带的分组（五类）。

⚠️ **数据不入库**：题目与 PDF 都在 `eval/local/`（目录级 gitignore，`2.0-53`）。
⚠️ **`page` 只对 PDF 有意义** —— Word/Excel 没有稳定页码，`page` 为 `None`。
   本脚本用的 CFQA 语料**全是 PDF**，故 `page` 可判；若换非 PDF 语料，指标要退化。

跑法::

    python eval/run_cfqa_retrieval.py --kb real --top 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.paths import ROOT  # noqa: E402
from src.rag.retriever import retrieve  # noqa: E402

CFQA_DIR = ROOT / "eval" / "local" / "cfqa"
QUESTIONS = CFQA_DIR / "gold_standard_500.json"

# ⚠️ 与评测侧一致：不按部门/密级过滤（这是**检索能力**测定，不是权限测定）
DEPARTMENTS = ["IT", "公司"]
SECRET_LEVEL = 3

# 只跑这 4 份（「恰好 10 题、五类各 2」的那批里挑的）
FILES = [
    "2024-03-20-601126.SH-四方股份-601126四方股份2023年年度报告.pdf",
    "2024-03-23-601088.SH-中国神华-601088中国神华2023年度报告.pdf",
    "2024-03-27-600030.SH-中信证券-600030中信证券股份有限公司2023年年度报告.pdf",
    "2024-03-29-601988.SH-中国银行-601988中国银行股份有限公司2023年年度报告.pdf",
]


def load_questions(files: list[str]) -> list[dict]:
    if not QUESTIONS.is_file():
        raise SystemExit(
            f"⛔ 找不到 CFQA 题目：{QUESTIONS}\n"
            "   先落地数据集（`hf download ZackZhu00/CFQA_Chinese_Finance_Question_Answering "
            "--repo-type dataset --local-dir eval/local/cfqa`）—— ⛔ 不静默跑成 0 题。")
    rows = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    return [r for r in rows if r["filename"] in set(files)]


async def one(row: dict, kb: str, top: int) -> dict:
    _, chunks = await retrieve(row["question"], DEPARTMENTS, SECRET_LEVEL, kb=kb, top_k=top)
    # ⭐ 命中判据：召回的块里，**有没有「同一文件 ＋ 同一页」**
    pages = [c.page for c in chunks]
    file_hit = any(c.source_file == row["filename"] for c in chunks)
    page_hit = any(c.source_file == row["filename"] and c.page == row["page"] for c in chunks)
    return {
        "id": None, "file": row["filename"], "question": row["question"][:60],
        "type": row["type"], "gold_page": row["page"],
        "file_hit": file_hit, "page_hit": page_hit,
        "got_pages": pages, "got_files": [c.source_file for c in chunks],
    }


async def main() -> int:
    ap = argparse.ArgumentParser(description="CFQA 检索层命中率（零 token）")
    ap.add_argument("--kb", default="real")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--json", default=str(ROOT / "logs" / "cfqa_retrieval.json"))
    args = ap.parse_args()

    rows = load_questions(FILES)
    print(f"CFQA 检索层 ｜ kb={args.kb} ｜ top={args.top} ｜ 题数 {len(rows)}"
          f"（{len(FILES)} 份年报 × 每份 10 题）")

    # ⚠️ 串行跑 —— `2.0-60` 已证明全并发会把耗时抬 10~66 倍（这里只求判据正确，不量延迟）
    results = []
    for r in rows:
        results.append(await one(r, args.kb, args.top))

    n = len(results)
    f_hit = sum(1 for r in results if r["file_hit"])
    p_hit = sum(1 for r in results if r["page_hit"])
    print(f"\n  文件命中   {f_hit}/{n}")
    print(f"  ⭐ 文件+页命中 {p_hit}/{n}")
    print("\n  按题型：")
    by = defaultdict(lambda: [0, 0, 0])
    for r in results:
        b = by[r["type"]]
        b[0] += 1; b[1] += r["file_hit"]; b[2] += r["page_hit"]
    for t, (c, f, p) in by.items():
        print(f"    {t:<8} n={c:>3}  文件 {f}/{c}  文件+页 {p}/{c}")

    (ROOT / "logs").mkdir(exist_ok=True)
    Path(args.json).write_text(json.dumps(
        {"kb": args.kb, "top": args.top, "files": FILES,
         "summary": {"n": n, "file_hit": f_hit, "page_hit": p_hit,
                     "by_type": {t: {"n": v[0], "file_hit": v[1], "page_hit": v[2]}
                                 for t, v in by.items()}},
         "rows": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n产物 → {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
