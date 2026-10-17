"""清洗报告的**汇总 + 打印**（`2.0-5`）—— shadow 脚本与 `ingest --clean shadow` 共用。

⚠️ 单一来源：汇总口径只写一次，避免两处各算一套（本项目 `_SUFFIXES` / `_ALLOWED` 的老教训）。
"""
from __future__ import annotations

from collections import defaultdict

from src.cleaning.rules import CleanReport


def merge(reports: list[CleanReport]) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """多份报告 → (按规则聚合, 每规则样例)。"""
    agg: dict[str, dict] = defaultdict(
        lambda: {"action": "", "files": set(), "blocks": 0, "hits": 0, "removed": 0})
    samples: dict[str, list[dict]] = defaultdict(list)
    for rep in reports:
        for h in rep.hits:
            a = agg[h.rule]
            a["action"] = h.action
            a["files"].add(rep.path)
            a["blocks"] += 1
            a["hits"] += h.count
            a["removed"] += h.removed
            samples[h.rule].append({"file": rep.path, "where": h.where, "count": h.count,
                                    "before": h.before, "after": h.after})
    return agg, samples


def print_table(agg: dict[str, dict]) -> None:
    """汇总表刷终端（明细写文件，`交付格式` 口径）。"""
    print(f"{'规则':<9}{'动作':<10}{'文件':>4}{'块':>6}{'命中次数':>9}{'改动字符':>9}")
    print("-" * 50)
    for rule in sorted(agg):
        a = agg[rule]
        print(f"{rule:<9}{a['action']:<10}{len(a['files']):>4}{a['blocks']:>6}"
              f"{a['hits']:>9}{a['removed']:>9}")
    print("-" * 50)
