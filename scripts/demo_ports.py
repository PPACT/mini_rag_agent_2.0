"""演示服务的**端口单一来源**（`start_demo` / `stop_demo` / `demo_app` 都从这里读）。

⚠️ **为什么单列一个模块**：端口原先**硬编码在两处**（`start_demo.py` 的 `API` 常量、
`stop_demo.py` 的 `_pids_on_port(8000)`）。`2.0-54` 加一个界面端口就要改两处 ——
而**两处各写一份必然漂移**，且漂移是**静的**（`dev-agent.md`：同一事实只留一个来源）。

⚠️ 本文件**不含任何本机路径 / 凭据**（它是 tracked 的）。
"""
from __future__ import annotations

# API（FastAPI / uvicorn）
API_PORT = 8000
API = f"http://127.0.0.1:{API_PORT}"

# 演示界面（Streamlit）
UI_PORT = 8501
UI = f"http://127.0.0.1:{UI_PORT}"

# 旧的单页透视页（仍在 API 上，作为对照保留）
DEMO_PAGE = f"{API}/demo"

# `stop_demo.py` 要收的**全部**端口
SERVICE_PORTS = (API_PORT, UI_PORT)

__all__ = ["API_PORT", "API", "UI_PORT", "UI", "DEMO_PAGE", "SERVICE_PORTS"]
