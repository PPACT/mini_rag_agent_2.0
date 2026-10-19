"""`2.0-68` 成本台账：**只汇总已有产物**，⛔ 不新增采集。

这里钉住三件事：
1. 每题 / 每轮的 token 与**串行**耗时口径；
2. **没有埋点的老产物不能被读成"零成本"**（显示"无数据"，不是 0）；
3. 折算成钱**必须由使用者给单价**，⛔ 工具不内置价格（写死的价格会悄悄过期）。
"""
from __future__ import annotations

import json

from eval import cost_ledger


def _artifact(tmp_path, *, with_tokens=True):
    data = {
        "dataset_size": 2,
        "results": {
            "纯向量": {
                "rows": [
                    {"timings": {"total_ms": 3000}},
                    {"timings": {"total_ms": 5000}},
                ],
                "summary": {
                    "tokens": (
                        {"ambiguity": {"total_tokens": 1000},
                         "generate": {"total_tokens": 3000},
                         "grand_total_tokens": 4000, "n_measured": 2}
                        if with_tokens else {}
                    ),
                    "latency": {"total_ms": {"p50": 3000, "p95": 5000, "max": 5000,
                                             "gt_5s_ratio": 0.0}},
                },
            }
        },
    }
    p = tmp_path / "eval.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_per_question_tokens_and_serial_minutes(tmp_path):
    rows = cost_ledger._ledger_for_eval(_artifact(tmp_path))
    assert len(rows) == 1
    r = rows[0]
    assert r["tokens_total"] == 4000
    assert r["tokens_per_q"] == 2000.0            # 4000 / 2 题
    assert r["serial_minutes"] == 0.1              # (3000+5000)ms = 8s ≈ 0.1 分钟
    assert r["latency_p50_ms"] == 3000


def test_old_artifact_without_instrumentation_is_not_zero(tmp_path):
    """⚠️ 反向用例：`2.0-59` 之前的产物没有 token 埋点 —— 必须显示"无数据"。

    若读成 0，历史评测会被当成"零成本"，后续所有对比都会失真。
    """
    r = cost_ledger._ledger_for_eval(_artifact(tmp_path, with_tokens=False))[0]
    assert r["tokens_total"] is None
    assert r["tokens_per_q"] is None


def test_money_requires_explicit_prices():
    assert cost_ledger._money(4000, 1000, 3000, None, None) is None, "没给单价就不该折算"
    assert cost_ledger._money(4000, 1_000_000, 1_000_000, 1.0, 2.0) == 3.0
