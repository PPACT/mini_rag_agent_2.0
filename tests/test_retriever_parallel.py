"""检索多路必须**并发** —— 词法侧与向量侧不再一路一路排队。

判据用「栅栏」而不是耗时阈值：如果三路是串行的，第一路会等到超时（必然失败），
比"跑得快不快"稳定得多（耗时阈值在慢机器上会误报）。
"""
from __future__ import annotations

import asyncio

from src.rag import retriever
from src.vector_store.base import Chunk


class _BarrierStore:
    def __init__(self, expect: int) -> None:
        self.expect = expect
        self.started: list[str] = []
        self.all_started = asyncio.Event()
        self.calls: list[tuple[str, object]] = []

    def _join(self, tag: str) -> None:
        self.started.append(tag)
        if len(self.started) >= self.expect:
            self.all_started.set()

    async def search(self, vec, filters, top_k):  # noqa: ARG002
        self.calls.append(("vector", vec))
        self._join(f"v{len(self.calls)}")
        await asyncio.wait_for(self.all_started.wait(), timeout=2)
        return [Chunk(document_id="d", chunk_index=0, content=str(vec[0]),
                      source_file="a.docx", id=f"v-{vec[0]}", score=0.9)]

    async def search_lexical(self, query, filters, top_k):  # noqa: ARG002
        self.calls.append(("lexical", query))
        self._join("lexical")
        await asyncio.wait_for(self.all_started.wait(), timeout=2)
        return [Chunk(document_id="d", chunk_index=0, content=query,
                      source_file="a.docx", id="lex", score=0.1)]


class _InstantEmbedding:
    async def embed(self, texts):
        return [[float(i)] for i, _ in enumerate(texts)]


def test_lexical_and_vectors_run_concurrently(monkeypatch):
    store = _BarrierStore(expect=3)   # 1 路词法 + 2 路查询向量
    monkeypatch.setattr(retriever, "get_embedding", lambda: _InstantEmbedding())
    monkeypatch.setattr(retriever, "get_vector_store", lambda _kb: store)

    async def _rewrite(_q, _n):
        return ["q1", "q2"]

    monkeypatch.setattr(retriever, "expand_queries", _rewrite)

    trace: dict = {}
    context, chunks = asyncio.run(retriever.retrieve(
        "问题", None, None, kb="real", use_rewrite=True, use_rerank=False,
        use_hybrid=True, top_k=3, trace=trace))

    assert len(store.started) == 3, f"只有 {store.started} 先开始 —— 说明有串行"
    assert context and chunks
    # 词法命中的块同样是候选项（顺序：词法在前，向量在后）
    assert {"lexical", "vector"} <= {kind for kind, _ in store.calls}


def test_vector_queries_keep_their_order(monkeypatch):
    """并发不改变结果归属：每个查询向量各自得到自己的结果。"""
    store = _BarrierStore(expect=1)
    monkeypatch.setattr(retriever, "get_embedding", lambda: _InstantEmbedding())
    monkeypatch.setattr(retriever, "get_vector_store", lambda _kb: store)

    trace: dict = {}
    asyncio.run(retriever.retrieve(
        "问题", None, None, kb="real", use_rewrite=False, use_rerank=False,
        use_hybrid=False, top_k=3, trace=trace))

    assert [kind for kind, _ in store.calls] == ["vector"]
    assert trace["candidates"][0].id == "v-0.0"
