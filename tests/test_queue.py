"""入队侧契约测试（D9-①）。

`enqueue_process_document` 改**关键字传参**后，「位置错位」这类静默故障消失了，
但换来了另一种漂移风险：**入队方发送的键**与 **worker 形参名**可以对不上
（位置传参下，"顺序"至少是被隐式钉住的）。

本文件把两侧钉在一起——任何一边改名/加必填参数，这里立刻红。
"""
from __future__ import annotations

import asyncio
import inspect

from src.tasks import queue as queue_mod
from src.tasks.document_task import process_document


class _FakeArq:
    """只记录调用，不碰 Redis。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    async def enqueue_job(self, name: str, *args, **kwargs) -> None:
        self.calls.append((name, args, kwargs))


def _enqueue(monkeypatch, **call_kwargs) -> tuple[str, tuple, dict]:
    """跑一次 enqueue_process_document，返回 (job_name, args, kwargs)。"""
    fake = _FakeArq()

    async def _fake_get_arq():
        return fake

    monkeypatch.setattr(queue_mod, "get_arq", _fake_get_arq)
    asyncio.run(queue_mod.enqueue_process_document(**call_kwargs))
    assert len(fake.calls) == 1, "应当恰好入队一次"
    return fake.calls[0]


def test_enqueue_uses_keywords_only(monkeypatch):
    """D9-① 回归：不得再出现位置参数——位置错位会静默灌错库，且不报错。"""
    name, args, kwargs = _enqueue(
        monkeypatch, kb="real", document_id="doc-1", department="IT", secret_level=2
    )
    assert name == "process_document"
    assert args == (), "入队参数必须全部走关键字；位置参数会让 kb 静默错位"
    assert kwargs == {
        "kb": "real",
        "document_id": "doc-1",
        "department": "IT",
        "secret_level": 2,
    }


def test_enqueue_keys_match_worker_signature(monkeypatch):
    """入队键集合 == worker 形参名集合（任一边改名即红）。"""
    _, _, kwargs = _enqueue(
        monkeypatch, kb="stress", document_id="doc-9", department=None, secret_level=0
    )
    params = list(inspect.signature(process_document).parameters)
    assert params[0] == "ctx", "worker 首参必须是 arq 注入的 ctx"
    assert set(kwargs) == set(params[1:]), (
        f"入队键 {sorted(kwargs)} 与 worker 形参 {sorted(params[1:])} 不一致——"
        f"改了一边就要同步另一边"
    )


def test_kb_is_required():
    """kb 必填：不设默认值，防止「忘传 → 静默落到真实库」。"""
    sig = inspect.signature(queue_mod.enqueue_process_document)
    assert sig.parameters["kb"].default is inspect.Parameter.empty


# ---- `2.0-57①`：队列与缓存**分实例** ----


def test_cache_and_queue_use_separate_redis_instances():
    """⚠️ 共用同一个 Redis 时，缓存写满（noeviction）⇒ 写入失败 ⇒ **队列也写不进去**，
    上传的文档进不了处理队列。两种用途的失败代价不同，就不该共用一个实例。
    """
    from src.config.settings import get_settings

    s = get_settings()
    assert s.redis_url, "缓存地址不能为空"
    assert s.queue_redis_url, "队列地址不能为空"
    assert s.redis_url != s.queue_redis_url, "队列与缓存指到了同一个 Redis —— 第 ① 项没生效"


def test_worker_and_enqueue_both_point_at_the_queue_instance():
    """⭐ 契约：**入队方**与**消费方**必须连**同一个**实例。

    只改一处（比如只改 `queue.py`）的后果是"入队进 A、消费从 B" ——
    任务**静默不执行**，而且两边日志都不会报错。
    """
    from urllib.parse import urlparse

    from src.config.settings import get_settings
    from src.tasks import worker as worker_mod

    s = get_settings()
    assert "queue_redis_url" in inspect.getsource(queue_mod), "入队侧还在用缓存实例"
    assert "get_settings().redis_url" not in inspect.getsource(queue_mod), (
        "入队侧误用了缓存实例（redis_url）"
    )
    assert "queue_redis_url" in inspect.getsource(worker_mod), "worker 侧还在用缓存实例"

    rs = worker_mod.WorkerSettings.redis_settings
    u = urlparse(s.queue_redis_url)
    assert rs.host == u.hostname, f"worker 连 {rs.host}，队列在 {u.hostname}"
    assert rs.port == (u.port or 6379), f"worker 连 {rs.port}，队列在 {u.port}"
