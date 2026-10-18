"""`2.0-58`：判定路径**区分「慢」与「坏」**。

背景（`§1.92` / `§1.93①`）：判定路径是 `8s × 0 重试`，这个取舍算的是"单请求最坏延迟"，
漏掉了另一个维度 —— **一次瞬时故障 → 一次慢窗口 → 整批 `unknown`**，
代价从"一个用户等 8s"变成"**N 个用户各看到一段假标注**"。

⚠️ 但那**不等于把重试加回来**：加了就是 `8s × N`，长尾重新放大。
差别在于**失败本身花多久**：
  · **慢**（超时）已花掉整份预算 ⇒ ⛔ 不重试
  · **坏**（连接/SSL/5xx）秒级返回 ⇒ 再试一次几乎不花时间

本文件钉住四件事（每条都配**反向用例** —— 断言要能失败）：
1. 超时**不**重试（最容易搞反的一条：`litellm.Timeout` 是 `APIConnectionError` 的子类！）
2. 快速失败的连接错**重试一次**，成功后正常返回
3. **慢**的失败即使类别是 `transient` **也不**重试（否则上界被悄悄放大）
4. 失败类别一路带到 `AmbiguityResult.failure_kind`（⛔ 不再一律叫 `unknown`）
"""
from __future__ import annotations

import asyncio

import litellm
import openai

from src.config import litellm_client
from src.config.litellm_client import LLMCallError, classify_failure
from src.rag import ambiguity as amb
from src.rag.ambiguity import AmbiguityResult
from src.vector_store.base import Chunk


class _StubSettings:
    """只提供被测代码用到的字段，避免依赖真实 .env（含密钥）。"""

    llm_api_key = "test-key"
    llm_provider = "deepseek"
    llm_model = "test-model"
    llm_base_url = "https://example.invalid"
    llm_thinking_enabled = False
    llm_max_tokens = 512
    llm_timeout_judge = 8.0
    llm_max_retries_judge = 0
    llm_fastfail_retries = 1
    llm_fastfail_within_s = 2.0
    llm_drop_params = False


class _Msg:
    content = "ok"
    reasoning_content = None


class _Choice:
    message = _Msg()
    finish_reason = "stop"


class _Resp:
    choices = [_Choice()]
    usage = None


def _install(monkeypatch, behaviour, **overrides) -> list[int]:
    """装好桩，返回"调用次数"列表（长度即可数出尝试了几次）。

    `behaviour(attempt_no)` → 返回响应对象，或**抛出**异常。只接收**一次**调用时
    也可以用 `asyncio.sleep` 模拟"这次失败很慢"。
    """
    stub = _StubSettings()
    for k, v in overrides.items():
        setattr(stub, k, v)
    monkeypatch.setattr(litellm_client, "get_settings", lambda: stub)
    monkeypatch.setattr(litellm_client, "_thinking_warned", True)  # 静音告警

    calls: list[int] = []

    async def _fake_acompletion(**kwargs):  # noqa: ARG001
        calls.append(len(calls) + 1)
        return await behaviour(len(calls))

    monkeypatch.setattr(litellm_client.litellm, "acompletion", _fake_acompletion)
    return calls


def _run() -> None:
    asyncio.run(litellm_client.complete_with_meta([{"role": "user", "content": "hi"}]))


# ---- ① 分类顺序：Timeout 必须排在 APIConnectionError 前面 ----

def _conn_error(msg: str = "conn reset") -> litellm.APIConnectionError:
    return litellm.APIConnectionError(msg, llm_provider="deepseek", model="m")


def _timeout_error(msg: str = "timed out") -> litellm.Timeout:
    return litellm.Timeout(msg, model="m", llm_provider="deepseek")


def test_timeout_is_classified_as_timeout_not_transient():
    """⚠️ 反向用例：**陷阱在 openai 那一层**（实测 litellm 1.99.0）。

    `litellm.Timeout` 与 `litellm.APIConnectionError` 是**兄弟**，但
    `openai.APITimeoutError` **是** `openai.APIConnectionError` 的子类 ——
    而真实抛出来的异常经常是 openai 那套。若分类时先判 `APIConnectionError`，
    超时会被当成"坏" ⇒ **超时也会被重试**，8s 变 16s（正是本单要避免的回退）。
    """
    assert issubclass(openai.APITimeoutError, openai.APIConnectionError), (
        "前提变了：openai 若不再让 APITimeoutError 继承 APIConnectionError，本用例的分支要重审"
    )
    assert classify_failure(_timeout_error()) == "timeout"
    # 同一陷阱的 openai 版本（真实调用里更常见的那种）
    assert classify_failure(openai.APITimeoutError(request=None)) == "timeout"


def test_connection_error_is_transient_and_valueerror_is_fatal():
    assert classify_failure(_conn_error()) == "transient"
    assert classify_failure(openai.APIConnectionError(request=None)) == "transient"
    assert classify_failure(ConnectionError("refused")) == "transient"
    assert classify_failure(ValueError("boom")) == "fatal"


# ---- ② 超时不重试 ----

def test_timeout_is_not_retried(monkeypatch):
    async def _always_timeout(n):
        raise _timeout_error()

    calls = _install(monkeypatch, _always_timeout)
    try:
        _run()
    except LLMCallError as e:
        assert e.kind == "timeout"
        assert e.attempts == 1
    else:
        raise AssertionError("超时必须抛出 LLMCallError")
    assert len(calls) == 1, f"超时不该重试，实际尝试了 {len(calls)} 次"


# ---- ③ 快速失败的"坏"重试一次后成功 ----

def test_fast_transient_is_retried_once_then_succeeds(monkeypatch):
    async def _fail_then_ok(n):
        if n == 1:
            raise _conn_error("ssl handshake failed")
        return _Resp()

    calls = _install(monkeypatch, _fail_then_ok)
    reply = asyncio.run(litellm_client.complete_with_meta([{"role": "user", "content": "hi"}]))
    assert reply.text == "ok", "重试成功后必须正常返回，⛔ 不能把一次瞬时故障变成 unknown"
    assert len(calls) == 2, "快速失败应重试一次"


def test_transient_exhausted_reports_attempts(monkeypatch):
    async def _always_fail(n):
        raise _conn_error("ssl handshake failed")

    calls = _install(monkeypatch, _always_fail)
    try:
        _run()
    except LLMCallError as e:
        assert e.kind == "transient"
        assert e.attempts == 2, "默认 1 次重试 ⇒ 共 2 次尝试"
    else:
        raise AssertionError("重试用尽后必须抛出 LLMCallError")
    assert len(calls) == 2


def test_retries_can_be_switched_off(monkeypatch):
    """反向用例：`llm_fastfail_retries=0` 时**一次都不能多试**（配置真的生效）。"""
    async def _always_fail(n):
        raise _conn_error()

    calls = _install(monkeypatch, _always_fail, llm_fastfail_retries=0)
    try:
        _run()
    except LLMCallError:
        pass
    assert len(calls) == 1


# ---- ④ "慢"的失败不重试（这是上界的守门人） ----

def test_slow_failure_is_not_retried_even_when_transient(monkeypatch):
    """⚠️ 反向用例：类别是 `transient`，但这次失败**花了时间** ⇒ 不许重试。

    否则"8s 超时"之外会多出一条没人算过的路径：`慢 → 重试 → 再慢`，
    最坏耗时悄悄翻倍，而 D9 的延迟改善正是靠"有上界"成立的。
    """
    async def _slow_fail(n):
        await asyncio.sleep(0.05)
        raise _conn_error("slow handshake failure")

    calls = _install(monkeypatch, _slow_fail, llm_fastfail_within_s=0.01)
    try:
        _run()
    except LLMCallError as e:
        assert e.kind == "transient"
        assert e.attempts == 1
    else:
        raise AssertionError("必须抛出 LLMCallError")
    assert len(calls) == 1, "超过 within_s 的失败不该重试"


# ---- ⑤ 类别要一路带到判定结果里 ----

def _chunk(source: str) -> Chunk:
    return Chunk(document_id="d", chunk_index=0, content="c", source_file=source, id="x")


def test_ambiguity_carries_failure_kind(monkeypatch):
    """`unknown` 必须带成因 —— 否则"整批 unknown 是外部故障还是结构缺陷"仍然分不出来。"""

    async def _stub(messages, temperature=0.1):  # noqa: ARG001
        raise LLMCallError(_timeout_error("t"),
                           "timeout", 1, 8.0)

    monkeypatch.setattr(amb, "complete_with_meta", _stub)
    r = asyncio.run(amb.check_ambiguity("q", [_chunk("a.md"), _chunk("b.md")]))
    assert r.status == "unknown"
    assert r.failure_kind == "timeout"
    assert "timeout" in r.reason


def test_unanswered_and_unparsed_have_distinct_kinds(monkeypatch):
    from src.config.litellm_client import LLMReply

    async def _empty(messages, temperature=0.1):  # noqa: ARG001
        return LLMReply(text="", finish_reason="length")

    monkeypatch.setattr(amb, "complete_with_meta", _empty)
    r = asyncio.run(amb.check_ambiguity("q", [_chunk("a.md"), _chunk("b.md")]))
    assert r.failure_kind == "unanswered"

    async def _garbage(messages, temperature=0.1):  # noqa: ARG001
        return LLMReply(text="我觉得差不多吧")

    monkeypatch.setattr(amb, "complete_with_meta", _garbage)
    r = asyncio.run(amb.check_ambiguity("q", [_chunk("a.md"), _chunk("b.md")]))
    assert r.failure_kind == "unparsed", "「模型没答」与「答了不合格式」修法不同，不能混为一类"


def test_clear_result_has_no_failure_kind(monkeypatch):
    """反向用例：正常结论不该挂 `failure_kind` —— 否则统计会把它算成失败。"""
    from src.config.litellm_client import LLMReply

    async def _ok(messages, temperature=0.1):  # noqa: ARG001
        return LLMReply(text='{"ambiguous": false, "reason": "", "options": []}')

    monkeypatch.setattr(amb, "complete_with_meta", _ok)
    r = asyncio.run(amb.check_ambiguity("q", [_chunk("a.md"), _chunk("b.md")]))
    assert r.status == "clear"
    assert r.failure_kind is None
    assert AmbiguityResult().failure_kind is None
