"""演示界面对后端的**调用封装**（`2.0-54`）。

⛔ **不改管道**（约束 2）：本模块**只调用**既有端点 ——
`POST /chat`（对话）与 `POST /demo/ask`（链路透视），不重写检索 / 生成 / 判定。

⭐ **不 import streamlit** —— 纯函数 + `httpx`，便于单测（约束 7）。
"""
from __future__ import annotations

from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TOKEN = "demo-it-token"
DEFAULT_TIMEOUT = 120.0


class ApiError(RuntimeError):
    """后端不可达 / 返回非 2xx —— ⚠️ **带状态码与响应体**，别把失败显示成"答案为空"。"""


def _post(path: str, *, base_url: str, json_body: dict, headers: dict | None = None,
          timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    try:
        resp = httpx.post(url, json=json_body, headers=headers or {}, timeout=timeout)
    except httpx.HTTPError as e:
        raise ApiError(f"连不上后端 {url} —— 先确认 `start_demo.py` 起过？({e})") from e
    if resp.status_code >= 400:
        raise ApiError(f"{path} 返回 {resp.status_code}：{resp.text[:300]}")
    return resp.json()


def ask_chat(question: str, *, base_url: str = DEFAULT_BASE_URL, token: str = DEFAULT_TOKEN,
             timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """走 `POST /chat`（**与线上同一条路**）。

    ⚠️ `/chat` 用 `Authorization: Bearer <token>` 鉴权（`src/auth/deps.py`），
    而 `/demo/ask` 把 token 放 body —— 两条路**不一致**，这里照各自的来。
    """
    return _post("/chat", base_url=base_url, json_body={"question": question},
                 headers={"Authorization": f"Bearer {token}"}, timeout=timeout)


def ask_demo(question: str, *, base_url: str = DEFAULT_BASE_URL, token: str = DEFAULT_TOKEN,
             kb: str = "real", use_hybrid: bool = True, use_rerank: bool = True,
             rerank_backend: str | None = None, with_answer: bool = True,
             timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """走 `POST /demo/ask`（**链路透视**：候选池 / 精排结果 / 耗时分解 / 判定三态）。

    ⚠️ `kb` 默认 `real`（与 `/chat` 一致）；压测库要**显式**选 —— 防"看错库"。
    """
    return _post("/demo/ask", base_url=base_url, json_body={
        "question": question, "token": token, "kb": kb,
        "use_hybrid": use_hybrid, "use_rerank": use_rerank,
        "rerank_backend": rerank_backend, "with_answer": with_answer,
    }, timeout=timeout)


def rank_key(item: dict[str, Any]) -> tuple:
    """块的**身份**（跨候选池 / 精排结果匹配用）。

    ⚠️ 用 `(source, chunk_index)` 而**不是** `rank` —— `rank` 两侧本来就会变（那正是要看的）。
    """
    return (item.get("source"), item.get("chunk_index"))


def rank_moves(candidates: list[dict], final: list[dict]) -> dict[tuple, str]:
    """`候选池 rank → 精排 rank` 的**位置变化标记**（约束 3 那条「提权 / 下移」）。

    - `up`   —— 精排后往前挪了（**精排提权**）
    - `down` —— 往后挪了（**精排下移**）
    - 不动的**不返回**（既没提也没压 —— 别给它加标记，否则标记就没信息量了）

    返回的 key 是**候选池那一侧的 `(source, chunk_index)`**，与 `candidates` 的项一一对应。
    """
    final_pos = {rank_key(x): i for i, x in enumerate(final, 1)}
    moves: dict[tuple, str] = {}
    for i, c in enumerate(candidates, 1):
        j = final_pos.get(rank_key(c))
        if j is None or j == i:
            continue
        moves[rank_key(c)] = "up" if j < i else "down"
    return moves
