"""Mock MCP 服务（模拟企业内部业务工具：员工信息查询）。

上线后删除此文件，替换为企业真实 MCP 服务地址（在 mcp_client_wrapper.py 里改连接即可）。
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("employee_info")

_MOCK_DB = {
    "E001": {"name": "张三", "department": "IT", "position": "后端工程师"},
    "E002": {"name": "李四", "department": "HR", "position": "招聘专员"},
    "E003": {"name": "王五", "department": "财务", "position": "会计"},
}


@mcp.tool()
async def query_employee_info(employee_id: str, caller_name: str = "") -> str:
    """根据工号查询员工信息（姓名/部门/职位）。

    ⚠️ `caller_name`（`2.0-66`）：**不是给模型填的** —— 它由客户端
    `src/agent/tool_guard.py` 在调用前**强制注入**，且**不出现在模型看到的
    schema 里**。这里的校验是**纯代码**的，⛔ 不依赖模型自觉遵守。
    """
    emp = _MOCK_DB.get(employee_id)
    if emp is None:
        return f"未找到工号 {employee_id} 的员工"

    # 纯代码校验：**只允许查本人**。
    # ⭐ fail closed —— 身份缺失一律拒绝（"查不到就放行"是这一层最典型的错）。
    # 📌 更细粒度的权限模型（部门负责人 / HR 可查他人）属 `2.0-69`，⛔ 别在这里长出来。
    if not caller_name:
        return "越权访问：调用者身份缺失，工具拒绝返回员工信息。"
    if emp["name"] != caller_name:
        return f"越权访问：当前调用者只能查询本人信息（工号 {employee_id} 不属于你）。"

    return f"工号 {employee_id}：{emp['name']}，部门 {emp['department']}，职位 {emp['position']}"


if __name__ == "__main__":
    mcp.run()  # stdio 传输
