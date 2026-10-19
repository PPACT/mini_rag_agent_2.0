"""`2.0-5` shadow 跑：**只报告、不动库**。

用法：
    python eval/run_clean_shadow.py --dir <corpus-dir>
    python eval/run_clean_shadow.py --dir <corpus-dir> --json logs/x.json

产物：
    终端 = **汇总表**（按规则：命中块数 / 命中次数 / 改动字符数 / 涉及文件数）
    文件 = `logs/clean_shadow_<日期>.json`（每条命中带**改前样例**，供人工判误伤）

⚠️ **它不写库、不改 `content`** —— 是否真删，等这份报告 + 抽样判过再定
（`内部工单 2.0-5`：漏洗可发现，**误洗不可发现** ⇒ shadow 先行）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.cleaning.report import merge, print_table  # noqa: E402
from src.cleaning.rules import CleanReport, apply_rules  # noqa: E402
from src.document_parser.loader import load_document  # noqa: E402
from src.document_parser.routing import DocumentParseError  # noqa: E402
from eval.paths import CORPUS_DIR  # noqa: E402


def _files(dirs: list[Path]) -> list[Path]:
    out: list[Path] = []
    for d in dirs:
        if d.exists():
            out.extend(sorted(p for p in d.glob("*") if p.is_file()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", action="append", default=None,
                    help=f"语料目录（可重复）。默认 {CORPUS_DIR}")
    ap.add_argument("--json", default=None, help="明细产物路径（默认 logs/clean_shadow_<日期>.json）")
    args = ap.parse_args()

    dirs = [Path(d) for d in args.dir] if args.dir else [CORPUS_DIR]
    out_path = Path(args.json) if args.json else (
        ROOT / "logs" / f"clean_shadow_{datetime.now():%Y%m%d}.json")

    reports: list[CleanReport] = []
    failures: list[dict] = []
    for path in _files(dirs):
        try:
            doc = load_document(str(path))
        except DocumentParseError as e:      # 路由拒收 / 解析失败 —— 与灌库时的口径一致
            failures.append({"file": path.name, "error": str(e)[:200]})
            continue
        reports.append(apply_rules(doc, path.name))

    # ---- 汇总：按规则聚合（多份报告合并）----
    agg, samples = merge(reports)
    print_table(agg)
    print(f"文件 {len(reports)} 份已扫；解析失败 {len(failures)} 份"
          + ("（见 JSON）" if failures else ""))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "corpus": [str(d) for d in dirs],
        "rules": {k: {**v, "files": sorted(v["files"])} for k, v in sorted(agg.items())},
        "samples": {k: v[:20] for k, v in sorted(samples.items())},
        "parse_failures": failures,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"明细 → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
