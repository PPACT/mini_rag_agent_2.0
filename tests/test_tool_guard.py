"""`2.0-66`：**工具层身份注入 ＋ 参数级校验**。

判据（`改进计划.md` 2.0-66）：⭐「别指望 LLM 遵守权限，要在代码层拦」，
**必须有反向用例** —— 拿 A 问 B 必须被拦。

这里钉住四件事，每条都有反向用例：
1. **身份不出现在模型可见的 schema 里**（否则模型就能"填一个试试"）；
2. 身份由 `caller_scope` **强制注入**，模型塞同名参数也覆盖不掉；
3. **没有身份 ⇒ 拒绝**（fail closed，⛔ 不是放行）；
4. 工具名/描述**原样保留** —— 否则测的就不是"同一个工具"了。
"""
from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from src.agent.tool_guard import HIDDEN_ARGS, caller_scope, current_caller, guard_tool


class _FakeMcpTool:
    """够用的 MCP 工具替身：字段与真实 StructuredTool 一致（见 `2.0-66` 的 introspection）。"""

    name = "query_employee_info"
    description = "根据工号查询员工信息（姓名/部门/职位）。"
    args_schema = {
        "properties": {
            "employee_id": {"type": "string"},
            "caller_name": {"type": "string"},
        },
        "required": ["employee_id"],
    }

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def coroutine(self, **kwargs):
        self.calls.append(kwargs)
        return ("工具返回内容", None)


def _schema_fields(tool) -> set[str]:
    return set(tool.args_schema.model_fields)


# ---- ① 模型看不见身份字段 ----


def test_hidden_arg_is_not_in_model_visible_schema():
    """⚠️ 反向用例（本单的核心）：`caller_name` **不能**出现在模型看到的 schema 里。

    一旦出现，提示词注入只要让模型填 `caller_name="张三"` 就能冒充别人 ——
    校验再怎么严也没用，因为"是不是本人"这个事实被攻击者提供了。
    """
    original = _FakeMcpTool()
    # 前置：原始 schema **确实**带着它 —— 否则下面的断言会因为"本来就没有"而白过
    assert "caller_name" in original.args_schema["properties"]
    assert HIDDEN_ARGS, "隐藏字段清单是空的 ⇒ 这个测试什么也没验"

    guarded = guard_tool(original)
    fields = _schema_fields(guarded)
    assert "employee_id" in fields, "正常参数必须保留，否则工具没法用"
    for hidden in HIDDEN_ARGS:
        assert hidden not in fields, f"隐藏字段 {hidden} 泄漏到模型可见 schema"


def test_model_cannot_even_attempt_to_supply_identity():
    """反向用例②：模型硬塞 `caller_name` → **在校验层就被拒**（不是"传进去被忽略"）。"""
    guarded = guard_tool(_FakeMcpTool())
    with pytest.raises(ValidationError):
        asyncio.run(guarded.ainvoke({"employee_id": "E001", "caller_name": "张三"}))


# ---- ② 身份由本层注入 ----


def test_caller_scope_is_injected_into_the_call():
    fake = _FakeMcpTool()
    guarded = guard_tool(fake)
    with caller_scope("张三"):
        out = asyncio.run(guarded.ainvoke({"employee_id": "E001"}))
    assert fake.calls == [{"employee_id": "E001", "caller_name": "张三"}]
    assert out == "工具返回内容"


def test_injected_identity_overrides_whatever_was_passed():
    """即使将来有人把隐藏字段加回 schema，**注入值也必须赢**。

    这里直接调 `_guarded` 的下一层（coroutine）等价路径：把 `caller_name` 塞进 kwargs，
    期望它被剔除后**重新写入**我们自己的值 —— 而不是"两个都传下去"。
    """
    fake = _FakeMcpTool()
    guarded = guard_tool(fake)
    with caller_scope("李四"):
        # 绕过 schema 校验，直接打底层函数：模拟"注入的字段混进了参数里"
        asyncio.run(guarded.coroutine(employee_id="E001", caller_name="张三"))
    assert fake.calls == [{"employee_id": "E001", "caller_name": "李四"}], (
        f"模型给的身份没被覆盖：{fake.calls}"
    )


# ---- ③ 没有身份 = 拒绝（fail closed）----


def test_no_identity_fails_closed():
    """⚠️ 反向用例：没有调用者 ⇒ **不碰工具**并返回拒绝。

    "查不到调用者就当作放行"是这一层最典型的错，而且**平时看不出来**
    （正常请求都有身份，只有异常路径才走到）。
    """
    fake = _FakeMcpTool()
    guarded = guard_tool(fake)
    out = asyncio.run(guarded.ainvoke({"employee_id": "E001"}))
    assert "越权访问" in out
    assert fake.calls == [], "身份缺失时**不该**调用底层工具"


def test_scope_is_cleaned_up_after_exit():
    """`contextvar` 必须还原 —— 否则身份会**串到下一个请求**（最危险的串号）。"""
    with caller_scope("张三"):
        assert current_caller() == "张三"
    assert current_caller() is None


def test_scope_is_cleaned_up_on_exception():
    with pytest.raises(RuntimeError):
        with caller_scope("张三"):
            raise RuntimeError("boom")
    assert current_caller() is None


# ---- ④ 包装不改工具身份 ----


def test_name_and_description_are_preserved():
    """⛔ 改名/改描述会让模型的行为跟着变 —— 那测的就不是"同一个工具"了。"""
    original = _FakeMcpTool()
    guarded = guard_tool(original)
    assert guarded.name == original.name
    assert guarded.description == original.description
