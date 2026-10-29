"""运行态指标**只读**端点 —— 给监控台取数。

⛔ **安全口径**（与 `/eval` 一致）：
- 只有 `GET`，没有任何写路由；
- 响应里**不含问题原文、不含用户身份**（见 `src/observability/metrics.py`）；
- 参数只有 `limit`，且被夹在缓冲容量内。

⚠️ **数据源分两半，失败方式也不同**：
- 请求指标 = 进程内环形缓冲（重启即空 —— 这是"运行态"的正常状态）；
- 系统侧 = 实时查库 / 队列，**查不到就明说 `available: false` ＋ 原因类型**，
  ⛔ 不返回 0 冒充"库里是空的"（同类静默降级已经踩过多次）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.db.connection import get_pool
from src.db.kb import KB_REAL
from src.observability import metrics
from src.tasks.queue import get_arq

router = APIRouter(prefix="/metrics", tags=["metrics"])


async def _system() -> dict:
    """库规模 ＋ 入库队列（best-effort，任何一半失败都不影响另一半）。"""
    out: dict = {}

    try:
        pool = await get_pool(KB_REAL)
        documents = await pool.fetchval(
            "SELECT count(*) FROM documents WHERE is_deleted = false")
        chunks = await pool.fetchval(
            "SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.document_id "
            "WHERE d.is_deleted = false")
        rows = await pool.fetch(
            "SELECT status, count(*) AS n FROM documents WHERE is_deleted = false "
            "GROUP BY status")
        out["db"] = {
            "available": True,
            "kb": KB_REAL,
            "documents": int(documents or 0),
            "chunks": int(chunks or 0),
            "documents_by_status": {r["status"]: int(r["n"]) for r in rows},
        }
    except Exception as e:  # noqa: BLE001
        # ⚠️ 只报异常类型：连接串之类的细节不该出现在只读接口里
        out["db"] = {"available": False, "kb": KB_REAL, "reason": type(e).__name__}

    try:
        arq = await get_arq()
        out["queue"] = {"available": True, "pending": int(await arq.zcard("arq:queue"))}
    except Exception as e:  # noqa: BLE001
        out["queue"] = {"available": False, "reason": type(e).__name__}

    return out


@router.get("/requests")
async def recent_requests(
    limit: int = Query(50, ge=1, le=metrics.CAPACITY),
) -> dict:
    """最近 `limit` 次问答的指标（新→旧）＋ 当前缓冲的汇总 ＋ 系统侧快照。

    ⚠️ `summary` 的范围是**整个缓冲**（`buffered` 条），不是 `limit` 条 ——
    响应里两个数都给了，页面必须写清范围。
    """
    data = metrics.snapshot(limit)
    data["system"] = await _system()
    return data
