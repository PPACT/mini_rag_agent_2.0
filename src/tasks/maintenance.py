"""周期性维护任务（arq cron 驱动）。

目前只有一件：**过期 `staged` 清理**（`2.0-71`）。
⚠️ 与 commit 端的「过期显式报错」**同一口径**（`src.auth.access.commit_ttl_ok`），
一条判据两处用 —— 别一个查 `created_at`、一个查 `updated_at`（那必然漂移）。
"""
from __future__ import annotations

import os

from src.auth.access import STAGED_TTL_HOURS
from src.config.settings import get_settings
from src.db.connection import get_pool
from src.db.kb import KB_REAL, KB_STRESS
from src.observability.tracer import audit, audit_err


async def cleanup_expired_staged(ctx: dict) -> int:  # noqa: ARG001 —— arq 的 ctx 用不上
    """清掉**过期且仍未确认**的 `staged` 文档：标 `deleted` ＋ 删落盘文件 ＋ 审计。

    ⚠️ **只碰 `staged`** —— `pending` / `completed` / `quarantined` 一律不动：
    它们不是"忘了确认"，清理它们会删掉正在处理或已有结论的东西。
    ⚠️ 文件删不掉**不挡**状态清理（否则残留会永远清不掉），但要 `audit_err` 留痕。
    """
    settings = get_settings()
    removed = 0
    for kb in (KB_REAL, KB_STRESS):      # 两个库都要清 —— 单清一个会漏
        pool = await get_pool(kb)
        rows = await pool.fetch(
            "SELECT id::text, filename FROM documents "
            "WHERE status='staged' AND is_deleted=false "
            "AND created_at < now() - make_interval(hours => $1)",
            STAGED_TTL_HOURS,
        )
        for row in rows:
            path = os.path.join(settings.upload_dir_abs, row["filename"])
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as exc:
                audit_err("staged_cleanup_file", document_id=row["id"], kb=kb, error=str(exc))
            await pool.execute(
                "UPDATE documents SET status='deleted', is_deleted=true, updated_at=now(), "
                "error=$2 WHERE id=$1::uuid",
                row["id"],
                f"staged 超过 {STAGED_TTL_HOURS} 小时未 commit，已自动清理",
            )
            audit("staged_expired_cleanup", document_id=row["id"], kb=kb)
            removed += 1
    return removed
