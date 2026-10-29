"""运行态指标（`2.0-67`）：汇总口径、缓冲边界、端点形状、失败不装成 0。

⚠️ 三条反向口径（本项目踩过的坑）：
1. **"没采到"≠ 0** —— token 缺失必须是 `None`，汇总里还要单列 `unknown_requests`；
2. **系统侧查不到就明说** —— `available: false` ＋ 异常类型，⛔ 不返回 0 冒充空库；
3. **缓冲是有界的** —— 只留最近 `CAPACITY` 条，页面读到的不是"全部历史"。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import metrics_api
from src.observability import metrics


@pytest.fixture(autouse=True)
def _clean_metrics():
    metrics.reset()
    yield
    metrics.reset()


def _item(**kw) -> dict:
    base = {
        "kind": "chat", "kb": "real", "cache_hit": False,
        "answer_kind": "normal", "judge_status": "clear",
        "need_clarification": False, "tool_rounds": 0, "cited": 3,
        "candidates": 20, "top_k": 5, "fill_rate": 1.0,
        "timings": {"retrieve_ms": 100.0, "generate_ms": 1000.0,
                    "ambiguity_ms": 200.0, "total_ms": 1300.0},
        "tokens": {"prompt": 100, "completion": 20},
        "rerank": {"enabled": True, "backend": "local"},
        "retrieve": {"rewrite_ms": 10.0, "embed_ms": 20.0, "lexical_ms": 5.0,
                     "vector_ms": 15.0, "fuse_ms": 1.0, "rerank_ms": 49.0},
    }
    base.update(kw)
    return base


# ---- 汇总口径 ----


def test_latency_percentiles_and_slow_ratio():
    """延迟必须报 p50/p90/p95/max ＋ >5s 占比（⛔ 不许只报平均）。"""
    for v in (100, 200, 300, 400, 6000):
        metrics.record(kind="chat", timings={"total_ms": float(v)})

    lat = metrics.snapshot()["summary"]["latency"]
    assert lat["count"] == 5
    assert lat["p50"] == 300.0
    assert lat["p95"] == 6000.0
    assert lat["max"] == 6000.0
    assert lat["slow_5s_ratio"] == 0.2


def test_missing_tokens_stay_none_and_are_counted():
    """⛔ 拿不到用量不算 0：合计留 `None`，另外单列"没采到"的条数。"""
    metrics.record(**_item(tokens={"prompt": None, "completion": None}))
    s = metrics.snapshot()["summary"]["tokens"]
    assert s["prompt"] is None and s["completion"] is None
    assert s["unknown_requests"] == 1

    metrics.record(**_item(tokens={"prompt": 10, "completion": 2}))
    s = metrics.snapshot()["summary"]["tokens"]
    assert s["prompt"] == 10 and s["completion"] == 2
    assert s["unknown_requests"] == 1, "已知的一条不该被算成未知"


def test_summary_counts_status_and_answer_kinds():
    metrics.record(**_item(judge_status="unknown", answer_kind="unverified"))
    metrics.record(**_item(judge_status="clear"))
    metrics.record(**_item(kind="demo", judge_status="ambiguous", answer_kind="answer"))

    s = metrics.snapshot()["summary"]
    assert s["requests"] == 3
    assert s["by_kind"] == {"chat": 2, "demo": 1}
    assert s["judge_status"] == {"unknown": 1, "clear": 1, "ambiguous": 1}
    assert s["answer_kind"] == {"unverified": 1, "normal": 1, "answer": 1}
    assert s["cited_avg"] == 3.0
    assert s["fill_rate_avg"] == 1.0


def test_empty_buffer_reports_none_not_zero():
    """没跑过请求时，延迟 / token 都是 `None` —— ⛔ 不是 0。"""
    s = metrics.snapshot()["summary"]
    assert s["requests"] == 0
    assert s["latency"]["p50"] is None
    assert s["tokens"]["prompt"] is None


# ---- 缓冲边界 ----


def test_snapshot_is_newest_first_and_limited():
    for i in range(5):
        metrics.record(kind="chat", seq=i)

    snap = metrics.snapshot(limit=2)
    assert snap["buffered"] == 5, "汇总范围是整个缓冲"
    assert [i["seq"] for i in snap["items"]] == [4, 3], "列表是新→旧，且只给 limit 条"


def test_buffer_is_bounded():
    for i in range(metrics.CAPACITY + 10):
        metrics.record(kind="chat", seq=i)
    snap = metrics.snapshot()
    assert snap["buffered"] == metrics.CAPACITY
    assert snap["items"][0]["seq"] == metrics.CAPACITY + 9


# ---- 端点 ----


class _Pool:
    async def fetchval(self, sql, *args):  # noqa: ARG002
        return 30 if "JOIN" in sql else 7

    async def fetch(self, sql, *args):  # noqa: ARG002
        return [{"status": "completed", "n": 6}, {"status": "pending", "n": 1}]


class _Arq:
    async def zcard(self, name):  # noqa: ARG002
        return 3


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(metrics_api.router)
    return TestClient(app)


def test_endpoint_returns_items_summary_and_system(client, monkeypatch):
    async def _pool(_kb):
        return _Pool()

    async def _arq():
        return _Arq()

    monkeypatch.setattr(metrics_api, "get_pool", _pool)
    monkeypatch.setattr(metrics_api, "get_arq", _arq)
    metrics.record(**_item())

    r = client.get("/metrics/requests?limit=10")
    assert r.status_code == 200
    data = r.json()
    assert data["buffered"] == 1
    assert data["items"][0]["kind"] == "chat"
    assert data["summary"]["requests"] == 1
    assert data["system"]["db"] == {
        "available": True, "kb": "real", "documents": 7, "chunks": 30,
        "documents_by_status": {"completed": 6, "pending": 1},
    }
    assert data["system"]["queue"] == {"available": True, "pending": 3}


def test_system_failure_is_reported_not_zeroed(client, monkeypatch):
    """库 / 队列查不到时：`available: false` ＋ 异常类型，状态码仍是 200。

    ⚠️ 还要求**不泄露细节**（连接串之类只在异常消息里）—— 响应里不能出现。
    """
    async def _boom(*_a, **_kw):
        raise RuntimeError("postgresql://user:pass@host/db")

    monkeypatch.setattr(metrics_api, "get_pool", _boom)
    monkeypatch.setattr(metrics_api, "get_arq", _boom)

    r = client.get("/metrics/requests")
    assert r.status_code == 200
    sys_ = r.json()["system"]
    assert sys_["db"] == {"available": False, "kb": "real", "reason": "RuntimeError"}
    assert sys_["queue"] == {"available": False, "reason": "RuntimeError"}
    assert "postgresql://" not in r.text and "pass" not in r.text


def test_limit_is_validated(client):
    assert client.get("/metrics/requests?limit=0").status_code == 422
    assert client.get(f"/metrics/requests?limit={metrics.CAPACITY + 1}").status_code == 422
