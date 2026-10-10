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

# 演示界面（Streamlit —— 开发侧版，`2.0-54`）
UI_PORT = 8501
UI = f"http://127.0.0.1:{UI_PORT}"

# 新前端（`web/`，归**前端侧**；React ＋ Tailwind ＋ Shadcn/ui）
# ⚠️ 取 **Vite 默认端口** —— 前端侧**不用额外配**，减少一处可能要改的东西。
# 🔴 与 8501 **必须分开**：开发侧的 Streamlit 版留作对照组，两版可能同时在跑。
WEB_DEV_PORT = 5173        # `npm run dev`（Vite dev server）
WEB_PREVIEW_PORT = 4173    # `npm run preview`（构建产物本地预览）
WEB = f"http://127.0.0.1:{WEB_DEV_PORT}"

# 旧的单页透视页（仍在 API 上，作为对照保留）
DEMO_PAGE = f"{API}/demo"

# `stop_demo.py` 要收的**全部**端口
# ⚠️ 含 `WEB_DEV_PORT`：那是**前端侧自己起的** dev server —— 停它只是停演示，不动代码。
SERVICE_PORTS = (API_PORT, UI_PORT, WEB_DEV_PORT)

PORT_LABEL = {
    API_PORT: "API（FastAPI）",
    UI_PORT: "演示界面（Streamlit · 开发侧版）",
    WEB_DEV_PORT: "新前端（web/ · 前端侧 · Vite dev）",
}

__all__ = [
    "API_PORT", "API", "UI_PORT", "UI",
    "WEB_DEV_PORT", "WEB_PREVIEW_PORT", "WEB",
    "DEMO_PAGE", "SERVICE_PORTS", "PORT_LABEL",
]
