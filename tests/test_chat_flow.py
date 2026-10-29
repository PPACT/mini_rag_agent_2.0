"""`/chat` 端点的**分支级**集成测试（P0-1 / P0-4）。

**为什么必须有它**：P0-A 交付时我明确标注过一处**没做端到端** ——
`/chat` 的 `unknown → 标注` 分支**跑不起来**：真实库是**有意留空的**，
而 `/chat` 固定查真库 → 取不到候选 → 走不到判定。
（`/demo` 已验证"三态能抵达响应"，但**标注逻辑只在 `/chat` 里**。）

所以这里把 `chat()` 的**外部依赖全部换成桩**（检索 / 判定 / 生成 / Redis），
但**保留它自己的分支逻辑不动** —— 测的就是"判定为 unknown 时，这段代码到底做了什么"。

⚠️ 与 `test_answer_degrade.py` 的分工：那里测 `_annotate_unverified` **函数本身**，
这里测**它在 `chat()` 里有没有被正确接上**。
"""
from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from src.api import chat_api
from src.auth.deps import User
from src.observability import metrics
from src.rag.ambiguity import AmbiguityResult
from src.schemas.chat import ChatRequest, ChatResponse, ClarifyOption
from src.vector_store.base import Chunk

USER = User(name="测试用户", department="IT", secret_level=3)
QUESTION = "年假几天？"


class _FakeRedis:
    def __init__(self) -> None:
        self.stored: dict = {}

    async def get(self, key):
        return self.stored.get(key)

    async def set(self, key, value, ex=None):  # noqa: ARG002
        self.stored[key] = value


class _FakeAgent:
    """`2.0-65`：`ainvoke` 现在**必须带 `config`**（编排步数上限），桩也要接受它。"""

    def __init__(self, content: str, seen_configs: list | None = None,
                 raises: BaseException | None = None, extra_messages: list | None = None) -> None:
        self._content = content
        self._seen_configs = seen_configs
        self._raises = raises
        self._extra = extra_messages or []

    async def ainvoke(self, _payload, config=None):
        if self._seen_configs is not None:
            self._seen_configs.append(config)
        if self._raises is not None:
            raise self._raises
        return {"messages": [*self._extra, AIMessage(content=self._content)]}


class _StubSettings:
    llm_api_key = "test-key"
    company_scope = "公司"
    top_k = 5
    cache_ttl = 60
    agent_recursion_limit = 17   # ⚠️ 故意用非默认值：这样"取的是配置"才验得出来


def _chunk(source: str, cid: str = "c1") -> Chunk:
    return Chunk(document_id="d", chunk_index=0, content="年假五天。", source_file=source, id=cid)


def _wire(monkeypatch, *, answer="年假五天。", ambiguity=None, chunks=None,
          agent=None, events: list | None = None):
    """把 `chat()` 的所有外部依赖换成桩；返回 (fake_redis, 捕获到的 ERR 事件名)。

    `events` 传入列表时，顺带收集 `audit()` 的 (事件名, 字段) —— 用于验证埋点。
    """
    chunks = [_chunk("员工手册.docx")] if chunks is None else chunks
    fake_redis = _FakeRedis()
    errs: list[str] = []

    monkeypatch.setattr(chat_api, "get_settings", lambda: _StubSettings())
    monkeypatch.setattr(chat_api, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(chat_api, "get_agent", lambda: agent if agent is not None else _FakeAgent(answer))
    monkeypatch.setattr(chat_api, "load_templates", lambda: ("sys", "{context}||{question}"))
    monkeypatch.setattr(chat_api, "audit_err", lambda e, **kw: errs.append(e))
    if events is not None:
        monkeypatch.setattr(chat_api, "audit", lambda e, **kw: events.append((e, kw)))

    async def _retrieve(question, departments, secret_level, **kw):  # noqa: ARG001
        return "检索上下文", chunks

    monkeypatch.setattr(chat_api, "retrieve", _retrieve)

    async def _ambiguity(question, ch, usage_out=None):  # noqa: ARG001
        return ambiguity if ambiguity is not None else AmbiguityResult()

    monkeypatch.setattr(chat_api, "check_ambiguity", _ambiguity)
    return fake_redis, errs


def _ask():
    return asyncio.run(chat_api.chat(ChatRequest(question=QUESTION), USER))


# ---- unknown → 答案 + 标注 + 反问（P0-A 的核心分支）----


def test_unknown_annotates_answer_and_sets_status(monkeypatch):
    """**这是 P0-A 真正要验的那条路**：判定无有效结论时，代码到底做了什么。"""
    _, errs = _wire(monkeypatch, ambiguity=AmbiguityResult(
        status="unknown", reason="判定模型没有返回任何内容"))
    resp = _ask()

    assert resp.judge_status == "unknown"
    assert resp.need_clarification is False, "unknown 的 answer 是真答案，不是澄清话术"
    assert "年假五天。" in resp.answer, "**不能拒答**：答案必须还在"
    assert "没有得到确认" in resp.answer
    assert "判定模型没有返回任何内容" in resp.answer, "要说清为什么不确定"
    assert "请指明" in resp.answer, "要反问了用户"
    assert "answer_unverified" in errs, "必须记 ERR（P0-1 要求）"


def test_clear_answer_is_not_annotated(monkeypatch):
    """判 clear 时**不得**画蛇添足 —— 否则人人都被加上"未经确认"。"""
    _, errs = _wire(monkeypatch, ambiguity=AmbiguityResult(status="clear"))
    resp = _ask()

    assert resp.judge_status == "clear"
    assert resp.answer == "年假五天。"
    assert "没有得到确认" not in resp.answer
    assert errs == []


# ---- ambiguous → 澄清（契约不能动）----


def test_ambiguous_takes_clarify_path(monkeypatch):
    calls: list = []

    async def _build(question, result):  # noqa: ARG001
        calls.append(1)
        return "请问你指的是哪一种？"

    monkeypatch.setattr(chat_api, "build_clarification", _build)
    _wire(monkeypatch, ambiguity=AmbiguityResult(
        status="ambiguous", reason="时限不一致",
        options=[ClarifyOption(source="a.docx", summary="90 天")]))
    resp = _ask()

    assert resp.need_clarification is True
    assert resp.judge_status == "ambiguous"
    assert resp.answer == "请问你指的是哪一种？"
    assert [o.source for o in resp.clarify_options] == ["a.docx"]
    assert calls == [1]


# ---- 生成侧静默降级（P0-4）----


def test_empty_generation_is_explicit_not_blank(monkeypatch):
    """空答案**不再原样返回**（原来用户看到一片空白，日志无异常）。"""
    _, errs = _wire(monkeypatch, answer="   ", ambiguity=AmbiguityResult())
    resp = _ask()

    assert resp.answer == chat_api._NO_ANSWER_TEXT
    assert resp.answer.strip(), "不能是空串"
    assert "answer_empty" in errs


def test_empty_answer_takes_precedence_over_annotation(monkeypatch):
    """两者**互斥**：没有答案就谈不上"标注不确定"。

    否则会给一段"我没能生成答案"的话，再加一句"这条答案未经确认" —— 自相矛盾。
    """
    _, errs = _wire(monkeypatch, answer="",
                    ambiguity=AmbiguityResult(status="unknown", reason="判定没答"))
    resp = _ask()

    assert resp.answer == chat_api._NO_ANSWER_TEXT
    assert "没有得到确认" not in resp.answer
    assert errs == ["answer_empty"], "不该同时记两条"


# ---- 缓存 ----


def test_normal_result_is_cached(monkeypatch):
    fake, _ = _wire(monkeypatch, ambiguity=AmbiguityResult(status="clear"))
    _ask()
    assert len(fake.stored) == 1


def test_unverified_result_is_not_cached(monkeypatch):
    """`unknown` 是"这次没判出来"，不是关于问题的结论 —— 缓存会把偶发故障固化 1 小时。"""
    fake, _ = _wire(monkeypatch, ambiguity=AmbiguityResult(status="unknown", reason="x"))
    _ask()
    assert len(fake.stored) == 0


def test_empty_result_is_not_cached(monkeypatch):
    """反向用例：空答案（`empty`）同样不写缓存。"""
    fake, _ = _wire(monkeypatch, answer="   ", ambiguity=AmbiguityResult())
    _ask()
    assert len(fake.stored) == 0


def test_cache_hit_short_circuits_retrieval(monkeypatch):
    """命中缓存时不该再走检索（这是缓存存在的意义）。"""
    fake, _ = _wire(monkeypatch)
    calls: list = []

    async def _retrieve(*a, **kw):  # noqa: ARG001
        calls.append(1)
        return "ctx", []

    monkeypatch.setattr(chat_api, "retrieve", _retrieve)
    key = chat_api._cache_key(QUESTION, USER.department, USER.secret_level,
                              _StubSettings.top_k, "real")
    fake.stored[key] = ChatResponse(answer="缓存里的答案", sources=[]).model_dump_json()

    assert _ask().answer == "缓存里的答案"
    assert calls == [], "命中缓存仍去检索了"


# ---- `2.0-65`：编排层执行上限 ----
#
# 判据（2.0-65）：⛔ 不能拍一个数；超限话术必须与"真故障"区分开；
# 且**触发率要有数据**（否则下次调上限还是拍）。


def test_agent_invoke_receives_recursion_limit(monkeypatch):
    """⚠️ 反向用例：上限必须**真的传给 LangGraph** —— 写在设置里不传 = 摆设。

    `_StubSettings.agent_recursion_limit = 17` 是故意取的非默认值：
    如果代码用字面量或默认值，这里就会红。
    """
    seen: list = []
    agent = _FakeAgent("年假五天。", seen_configs=seen)
    _wire(monkeypatch, agent=agent)
    _ask()
    assert seen == [{"recursion_limit": 17}], f"实际传入 {seen}"


def test_step_limit_returns_distinct_message(monkeypatch):
    """触到步数上限 → **一句固定话术**，且**不能**和"没答案"/"服务器繁忙"混为一谈。"""
    agent = _FakeAgent("", raises=GraphRecursionError("Recursion limit of 17 reached"))
    _, errs = _wire(monkeypatch, agent=agent)
    resp = _ask()

    assert resp.answer == chat_api._STEP_LIMIT_TEXT
    assert "步数上限" in resp.answer
    assert resp.answer != chat_api._NO_ANSWER_TEXT, "超限 ≠ 没答案"
    assert "没有找到" not in resp.answer, "我们**没有**得出'库里没有'这个结论"
    assert "服务器" not in resp.answer, "超限 ≠ 真故障（都回'繁忙'是又一次静默降级）"
    assert "agent_step_limit" in errs
    assert resp.need_clarification is False


def test_step_limit_result_is_not_cached(monkeypatch):
    """⚠️ 反向用例：触限写缓存会让"同一问题 1 小时内反复命中同一次故障"。

    旧行为是缓存（`test_step_limit_result_is_cached`），2026-10-29 改为不缓存。
    """
    fake, _ = _wire(monkeypatch,
                    agent=_FakeAgent("", raises=GraphRecursionError("limit")))
    _ask()
    assert len(fake.stored) == 0


def test_normal_answer_never_mentions_step_limit(monkeypatch):
    """反向用例：正常路径**不得**出现上限话术（否则等于把所有回答都标成中止）。"""
    _wire(monkeypatch)
    resp = _ask()
    assert resp.answer != chat_api._STEP_LIMIT_TEXT
    assert "步数上限" not in resp.answer


def test_tool_rounds_are_audited(monkeypatch):
    """触发率要有数据：每次问答把**实际工具轮次**记进审计。"""
    events: list = []
    tool_msgs = [ToolMessage(content="ok", tool_call_id="1"),
                 ToolMessage(content="ok", tool_call_id="2")]
    _wire(monkeypatch, agent=_FakeAgent("年假五天。", extra_messages=tool_msgs),
          events=events)
    _ask()
    llm_events = [kw for name, kw in events if name == "llm"]
    assert llm_events, "没记 llm 审计"
    assert llm_events[-1]["tool_rounds"] == 2
    assert llm_events[-1]["recursion_limit"] == 17


# ---- 运行态指标（`2.0-67`）----


def test_request_is_recorded_without_question_text(monkeypatch):
    """指标只记"这次怎么跑"，⛔ 不记问题原文 / 用户身份。"""
    metrics.reset()
    try:
        _wire(monkeypatch)
        _ask()

        snap = metrics.snapshot()
        assert snap["buffered"] == 1
        item = snap["items"][0]
        assert item["kind"] == "chat"
        assert item["kb"] == "real"
        assert item["judge_status"] == "clear"
        assert item["answer_kind"] == "normal"
        assert item["top_k"] == 5
        assert item["tool_rounds"] == 0
        assert "question" not in item, "⛔ 不存问题原文"
        assert "user" not in item, "⛔ 不存用户身份"
        assert snap["summary"]["requests"] == 1
    finally:
        metrics.reset()


def test_cache_hit_is_recorded_as_cache(monkeypatch):
    """缓存命中也要进指标 —— 否则监控台看到的请求数会少于真实访问量。"""
    metrics.reset()
    try:
        _wire(monkeypatch)
        _ask()      # 第一次：正常链路 + 写缓存
        _ask()      # 第二次：命中
        items = metrics.snapshot()["items"]
        assert [i["answer_kind"] for i in items] == ["cache", "normal"]
        assert items[0]["cache_hit"] is True
        # ⚠️ 缓存命中没走检索：候选数 / 填充率必须留 None（⛔ 不是 0）
        assert items[0]["candidates"] is None
        assert items[0]["fill_rate"] is None
    finally:
        metrics.reset()
