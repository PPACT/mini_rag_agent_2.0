"""D11：请求级切换精排后端时，**实例必须真的换**。

背景：`get_reranker()` 原本是**一个全局单例** —— 第一次调用就把后端固化了。
若只加一个请求级参数而不动单例，**切了后端也仍用第一次那个**：

> UI 能切、行为不变、且**不报错**

这正是本项目反复踩的那类「**配置值不生效**」陷阱（P-1 / P-2），
而且它比"报错"更贵 —— 因为它会让人拿着错误的对照结论下判断。

本文件把「切了就真换」和「同后端要复用」**同时**钉住：只满足一个都不对 ——
- 只换不复用 → 每个请求都重载本地模型（加载一次 160+ 秒）；
- 只复用不换 → 就是上面那个静默失效。
"""
from __future__ import annotations

import inspect

import pytest

from src.rag import reranker
from src.rag.reranker import (
    LLMReranker,
    LocalCrossEncoderReranker,
    get_reranker,
    resolve_backend,
)


class _StubSettings:
    """只覆盖 `rerank_backend`，其余字段**透传真实配置**。

    （曾把桩写成硬编码常量，结果 `LocalCrossEncoderReranker.__init__` 还要
    `rerank_local_model` / `rerank_local_device` / `rerank_snippet_chars` 就炸了 ——
    桩写成"半个 Settings"注定会随真实配置增长而失效。）
    """

    def __init__(self, backend: str = "local") -> None:
        self.rerank_backend = backend

    def __getattr__(self, name: str):
        from src.config.settings import get_settings

        return getattr(get_settings(), name)


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    """每个用例从空缓存起步，避免用例之间互相污染。"""
    monkeypatch.setattr(reranker, "_rerankers", {})


def test_switching_backend_returns_different_instances():
    """**D11 的核心断言**：两个后端拿到的是不同实例（切了真的换）。"""
    local, llm = get_reranker("local"), get_reranker("llm")
    assert isinstance(local, LocalCrossEncoderReranker)
    assert isinstance(llm, LLMReranker)
    assert local is not llm


def test_same_backend_is_cached():
    """同一后端必须复用 —— 本地模型加载一次要 160+ 秒。"""
    assert get_reranker("local") is get_reranker("local")


def test_switch_back_and_forth_does_not_rebuild():
    """来回切不该重建实例（local 模型不该被反复加载）。"""
    first = get_reranker("local")
    get_reranker("llm")
    assert get_reranker("local") is first


def test_none_follows_settings(monkeypatch):
    """不传 = 跟随配置（`local` 与 `llm` 各测一次，避免只测默认值就等于没测）。"""
    monkeypatch.setattr(reranker, "get_settings", lambda: _StubSettings("local"))
    assert isinstance(get_reranker(None), LocalCrossEncoderReranker)

    monkeypatch.setattr(reranker, "get_settings", lambda: _StubSettings("llm"))
    assert isinstance(get_reranker(None), LLMReranker)


def test_explicit_backend_overrides_settings(monkeypatch):
    """显式传参必须**压过**配置 —— 否则 `/demo` 的选择器就是个摆设。"""
    monkeypatch.setattr(reranker, "get_settings", lambda: _StubSettings("llm"))
    assert isinstance(get_reranker("local"), LocalCrossEncoderReranker)


@pytest.mark.parametrize("bad", ["openai", "", "  ", "LOCAL1"])
def test_unknown_backend_raises(bad):
    """非法后端名 → 抛错，**不静默回退**（local 与 llm 的质量/延迟差一个量级）。"""
    with pytest.raises(ValueError):
        resolve_backend(bad)
    with pytest.raises(ValueError):
        get_reranker(bad)


def test_resolve_normalizes_case_and_space():
    assert resolve_backend("  LOCAL ") == "local"
    assert resolve_backend("Llm") == "llm"


def test_retrieve_exposes_rerank_backend():
    """`retrieve()` 必须能收这个参数（默认 None = 跟随配置）。"""
    from src.rag.retriever import retrieve

    p = inspect.signature(retrieve).parameters
    assert "rerank_backend" in p
    assert p["rerank_backend"].default is None


def test_ask_request_carries_rerank_backend():
    """`/demo/ask` 的请求体契约：不传 = None（跟随配置），可显式指定。"""
    from src.api.demo_api import AskRequest

    assert AskRequest(question="q").rerank_backend is None
    assert AskRequest(question="q", rerank_backend="llm").rerank_backend == "llm"


# ===== 懒加载不能卡事件循环 =====
#
# 首次加载要 import torch + 载权重（160s+）。若在协程里同步加载，
# 这段时间**整个服务**的所有请求都不响应。


class _FakeModel:
    def predict(self, pairs):
        return [0.5 for _ in pairs]


def _chunks():
    from src.vector_store.base import Chunk

    return [Chunk(document_id="d", chunk_index=0, content="正文", source_file="a.docx", id="c1")]


def test_model_load_runs_off_event_loop(monkeypatch):
    """反向用例：加载必须发生在工作线程，而不是事件循环线程。"""
    import asyncio
    import threading

    r = LocalCrossEncoderReranker()
    seen: dict = {}

    def _load():
        seen["thread"] = threading.current_thread()
        r._model = _FakeModel()
        return r._model

    monkeypatch.setattr(r, "_ensure_model", _load)
    asyncio.run(r.score_order("q", _chunks()))
    assert seen["thread"] is not threading.main_thread(), \
        f"模型加载跑在主线程里：{seen['thread']}"


def test_concurrent_first_calls_load_once(monkeypatch):
    """并发首请求只加载一次 —— 否则同时载入多份权重（每份 ~1.1GB）。"""
    import asyncio
    import time

    r = LocalCrossEncoderReranker()
    calls: list = []

    def _slow_load():
        calls.append(1)
        time.sleep(0.05)
        r._model = _FakeModel()
        return r._model

    monkeypatch.setattr(r, "_ensure_model", _slow_load)

    async def _two():
        return await asyncio.gather(r.score_order("q", _chunks()),
                                    r.score_order("q", _chunks()))

    asyncio.run(_two())
    assert len(calls) == 1, f"并发首次调用加载了 {len(calls)} 次"
