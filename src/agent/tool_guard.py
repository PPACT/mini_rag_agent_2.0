"""`2.0-66`：**工具层身份注入 ＋ 参数级校验**。

## 为什么要这一层

`2.0-70` 修的是 **API 层**（查询/更新要校验归属）；本条修的是**工具层** ——
Agent 调 MCP 工具时，**模型给的参数一律不可信**。⚠️ 路线图原话：
「**别指望 LLM 遵守权限，要在代码层拦**」。

具体到本项目（`mcp_mock_server.query_employee_info`）：原来**不校验调用者身份**，
拿 A 的身份能问 B。而这是最容易被提示词注入利用的一条路。

## 身份从哪来（⛔ 不能靠模型传）

MCP 走 **stdio 独立进程**，那一侧**没有 HTTP request / token 上下文**；
所以**不能**指望工具从 "请求上下文" 里自己读身份。
而**绝不能**把 `caller_name` 做成模型可见的参数 —— 那正是注入攻击要篡改的东西。

⇒ 本模块做两件事：
1. **身份只在进程内、由 API 层设置**（`caller_scope(user.name)`，`contextvar`）；
2. **包装 MCP 工具**：把 `caller_name` 从**模型可见的 schema 里去掉**，
   调用时**由这里强制注入**（即使模型硬塞了同名字段也会被覆盖）。
   工具侧（`mcp_mock_server`）只做**参数级校验 ＋ 拒绝**。

## 失败方向

⭐ **fail closed**：没有身份 ⇒ **拒绝**，⛔ 不是"放行"。
（"查不到调用者就当作管理员"是这一层最典型的错误。）
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from langchain_core.tools import StructuredTool
from pydantic import ConfigDict, create_model

# 当前请求的调用者（姓名）。**只在进程内传递**，⛔ 不从任何请求参数读。
_CALLER: ContextVar[str | None] = ContextVar("mcp_caller_name", default=None)

# 由 wrapper 注入、**模型不可见**的字段名（要加新的就登记在这里）
HIDDEN_ARGS = ("caller_name",)

_DENY_NO_IDENTITY = (
    "越权访问：调用者身份缺失。工具拒绝在没有身份的情况下返回员工信息。"
)


@contextmanager
def caller_scope(name: str | None) -> Iterator[None]:
    """在一次问答的范围内声明"调用者是谁"。

    用法（API 层）：
        with caller_scope(user.name):
            await agent.ainvoke(...)

    ⚠️ 必须**包住** `agent.ainvoke` 整段 —— 工具是在那里面被调用的。
    """
    token = _CALLER.set(name)
    try:
        yield
    finally:
        _CALLER.reset(token)


def current_caller() -> str | None:
    return _CALLER.get()


_JSON_TO_PY = {"string": str, "integer": int, "number": float, "boolean": bool}


def _visible_schema(original: StructuredTool) -> type:
    """按 MCP 工具自己的 JSON schema 造一个**去掉隐藏字段**的 pydantic 模型。

    ⚠️ 关键点：模型看到的参数集 = 这里返回的东西。隐藏字段**不出现**，
    模型就不可能"填一个 caller_name 进去试试"。
    """
    schema = original.args_schema if isinstance(original.args_schema, dict) else {}
    props: dict[str, Any] = schema.get("properties", {}) or {}
    required = set(schema.get("required", []) or [])

    fields: dict[str, tuple[Any, Any]] = {}
    for name, spec in props.items():
        if name in HIDDEN_ARGS:
            continue
        py_t = _JSON_TO_PY.get((spec or {}).get("type", "string"), str)
        fields[name] = (py_t, ... if name in required else None)
    # ⚠️ `extra="forbid"`：模型多塞一个字段（比如偷偷加 `caller_name`）要**报错**，
    #    而不是被悄悄丢掉 —— 静默丢弃会让"有人试图冒充"这件事在日志里完全看不见。
    return create_model(  # type: ignore[call-overload]
        f"{original.name}Arguments",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def guard_tool(tool: StructuredTool) -> StructuredTool:
    """把一个 MCP 工具包成「**身份由本层注入**、参数由工具侧校验」的版本。

    ⛔ 不改工具名与描述 —— 否则模型的行为会跟着变，测出来就不是"同一件事"了。
    """
    schema_model = _visible_schema(tool)

    async def _guarded(**kwargs: Any) -> Any:
        caller = current_caller()
        if not caller:
            # fail closed：没有身份就不给数据
            return _DENY_NO_IDENTITY
        # ⚠️ 先剔除模型可能塞进来的隐藏字段，再**强制**写入我们自己的值。
        #    （不剔除的话，`**kwargs` 与显式同名参数会冲突 → TypeError）
        for hidden in HIDDEN_ARGS:
            kwargs.pop(hidden, None)
        call_kwargs = {**kwargs, "caller_name": caller}
        # ⚠️ 直接调 MCP 适配器的 coroutine，而不是 `tool.ainvoke`：
        #    `ainvoke` 会按**原始 schema** 重新校验，把注入的字段丢掉。
        #    它的签名是 `(runtime=None, **arguments)`，多余的键会原样转给 MCP。
        content, _artifact = await tool.coroutine(**call_kwargs)  # type: ignore[misc]
        return content

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=schema_model,
        coroutine=_guarded,
    )
