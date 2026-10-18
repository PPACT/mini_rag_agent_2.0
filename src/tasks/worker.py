"""Arq worker 入口（arq 0.28：自定义 WorkerSettings 类，用 `python -m arq` 启动）。"""
from __future__ import annotations

import logging

from arq import cron
from arq.connections import RedisSettings

from src.config.settings import get_settings
from src.tasks import document_task
from src.tasks.maintenance import cleanup_expired_staged

# ⚠️ **worker 也要配 logging** —— `src/main.py` 里那份只对 API 进程生效。
# 不配的后果：默认级别是 WARNING ⇒ `audit()`（`logger.info`）**静默消失**。
# 实测（2026-10-18）：隔离审计 `document_quarantined` 在日志里 **0 行**，
# 而 2.0-72 的验收要求「污染处置有审计」—— 静默 = 没做。
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")


async def startup(ctx: dict) -> None:
    """worker 启动钩子（可预热连接池等）。"""


async def shutdown(ctx: dict) -> None:
    """worker 关闭钩子（清理连接）。"""


class WorkerSettings:
    """worker 配置。启动：`python -m arq src.tasks.worker.WorkerSettings`（项目根目录下）。"""

    functions = [document_task.process_document]
    # `2.0-71`：每小时清一次过期 staged（:17 —— ⛔ 不卡整点，避开所有人的定时任务）
    cron_jobs = [cron(cleanup_expired_staged, minute=17)]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    on_shutdown = shutdown
    max_tries = 3       # 失败重试次数，超过后 job 判失败
    job_timeout = 1800  # 单任务超时（秒），大文档向量化较慢
