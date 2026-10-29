"""`2.0-65`：`/demo` 的编排上限**与 `/chat` 同一条**。

⚠️ 为什么单独测 `/demo`：它是**同一条 ReAct agent 的第二个入口** ——
只在 `/chat` 加上限，等于留了一个绕过口（`/demo` 一样能被拖进工具循环、
一样在烧 token）。而且它的异常处理原本是**一把 `except Exception` 兜全部**，
超限会被报成「生成失败」，与真故障混在一起 —— 正是 `2.0-65` 要求区分开的那件事。
"""
from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage
from langgraph.errors import GraphRecursionError

from src.api import demo_api
from src.vector_store.base import Chunk


class _StubSettings:
    llm_api_key = "test-key"
    llm_model = "test-model"
    company_scope = "公司"
    agent_recursion_limit = 13
    rerank_local_model = "test-reranker"   # 回显用（`rerank.model` 字段）


class _FakeAgent:
    def __init__(self, raises=None, content="年假五天。") -> None:
        self._raises = raises
        self._content = content
        self.seen_configs: list = []

    async def ainvoke(self, _payload, config=None):
        self.seen_configs.append(config)
        if self._raises is not None:
            raise self._raises
        return {"messages": [AIMessage(content=self._content)]}


class _FakeAmbiguity:
    status = "clear"
    reason = ""
    ambiguous = False
    unknown = False
    options: list = []


def _chunk() -> Chunk:
    return Chunk(document_id="d", chunk_index=0, content="年假五天。",
                 source_file="员工手册.docx", id="c1")


def _wire(monkeypatch, agent):
    chunks = [_chunk()]
    monkeypatch.setattr(demo_api, "get_settings", lambda: _StubSettings())
    monkeypatch.setattr(demo_api, "resolve_backend", lambda _b: "local")

    async def _retrieve(*a, **kw):  # noqa: ARG001
        kw["trace"].update({"candidates": chunks, "final": chunks})
        return "ctx", chunks

    monkeypatch.setattr(demo_api, "retrieve", _retrieve)
    monkeypatch.setattr(demo_api, "get_agent", lambda: agent)
    monkeypatch.setattr(demo_api, "load_templates", lambda: ("sys", "{context}||{question}"))

    async def _amb(*a, **kw):  # noqa: ARG001
        return _FakeAmbiguity()

    monkeypatch.setattr(demo_api, "check_ambiguity", _amb)


def _ask():
    return asyncio.run(demo_api.demo_ask(demo_api.AskRequest(question="年假几天？")))


def test_demo_passes_same_recursion_limit(monkeypatch):
    agent = _FakeAgent()
    _wire(monkeypatch, agent)
    _ask()
    assert agent.seen_configs == [{"recursion_limit": 13}], (
        f"`/demo` 没按配置传上限：{agent.seen_configs} —— 等于留了个绕过口"
    )


def test_demo_step_limit_is_not_reported_as_failure(monkeypatch):
    """反向用例：超限**不能**落进 `[生成失败]` 那把大网 —— 那是真故障的话术。"""
    _wire(monkeypatch, _FakeAgent(raises=GraphRecursionError("limit")))
    out = _ask()
    assert "步数上限" in out["answer"]
    assert "生成失败" not in out["answer"], "超限 ≠ 上游故障"
    assert "生成环节未返回内容" not in out["answer"]


def test_demo_normal_answer_unaffected(monkeypatch):
    _wire(monkeypatch, _FakeAgent())
    out = _ask()
    assert out["answer"] == "年假五天。"
    assert "步数上限" not in out["answer"]


def test_demo_uses_context_from_retrieve(monkeypatch):
    """上下文必须**原样**用 `retrieve()` 的返回值。

    旧实现自己重拼，丢了 `<untrusted_content>` 隔离与复杂表 `raw_table` ——
    演示链路与 `/chat` 不同源。这里用 `"ctx"` 这个哨兵值证明没有重拼。
    """
    seen: list = []
    agent = _FakeAgent()

    async def _ainvoke(payload, config=None):  # noqa: ARG001
        seen.append(payload["messages"][0].content)
        return {"messages": [AIMessage(content="ok")]}

    monkeypatch.setattr(agent, "ainvoke", _ainvoke)
    _wire(monkeypatch, agent)
    _ask()
    assert seen and "ctx" in seen[0], f"没有复用 retrieve() 的上下文：{seen}"
