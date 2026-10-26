"""评测产物的**只读**端点 —— 给生产构建的看板取数。

为什么需要：评测看板的数据源原来是 Vite **dev server** 的插件（只在 `npm run dev`
下有效）。生产构建是纯静态文件，没有那层 ⇒ 看板会静默空白。
这里补一个只读端点，路径与前端现有调用一致（`/eval/<文件名>`，经 nginx 去掉 `/api` 前缀）。

⛔ **安全口径**：
- **只读**（没有任何写路由）；
- **只认白名单文件名**（`[A-Za-z0-9._-]+.json`）＋ 解析后的路径必须仍在产物目录**内**，
  杜绝路径穿越；
- 目录不存在 → 返回空列表（不是 500）—— 新部署还没跑过评测是**正常状态**。
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.ui import logs_reader as logs

router = APIRouter(prefix="/eval", tags=["eval"])

# ⚠️ 只允许"普通文件名 + .json"；`/`、`\`、`..` 都不在字符集里
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.json$")


def _safe_path(name: str) -> Path:
    """把名字变成产物目录下的路径；不合法 / 越界 ⇒ 400。"""
    if not _NAME_RE.fullmatch(name) or ".." in name:
        raise HTTPException(status_code=400, detail="非法的产物文件名（只接受 <名字>.json）")
    base = Path(logs.LOGS_DIR).resolve()
    path = (base / name).resolve()
    # 双保险：解析后必须仍在产物目录内
    if base != path.parent:
        raise HTTPException(status_code=400, detail="非法的产物路径")
    return path


@router.get("")
@router.get("/index")
def list_artifacts() -> dict:
    """列出可用产物文件名（目录不存在 ⇒ 空表）。

    ⚠️ 返回形状**必须与 dev server 插件一致**（`{files: [...]}`）——
    前端只读 `files`；两边不一致会表现为"看板永远空白"。"""
    return {"files": [a["name"] for a in logs.list_artifacts()]}


@router.get("/{name}")
def get_artifact(name: str) -> dict:
    """取一份产物。缺失 / 非法 JSON ⇒ 404（⛔ 不返回空表冒充"没有数据"）。"""
    _safe_path(name)
    try:
        return logs.load(name)
    except logs.ArtifactError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
