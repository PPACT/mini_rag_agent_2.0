"""运行态指标：进程内有界环形缓冲（只读监控台的数据源）。

**这是"运行态"不是"历史账本"**：
- 只保留最近 `CAPACITY` 次请求，进程重启即清空；
- 历史与离线数字仍在 `logs/*.json` 与审计日志里 —— ⛔ 两件事不合并（见 `2.0-67`）。

⛔ **不存问题原文、不存用户身份**：监控台只需要"这次请求花了多久 / 用了多少 token /
判定成什么"，⛔ 不需要知道问了什么、谁问的。存原文等于把业务数据复制进内存和接口响应，
而收益为零。要排查具体问题，用时间戳去对审计日志。

⚠️ **写指标绝不能反过来影响主链路**：`record()` 只做一次 `deque.append`，
不抛异常、不做 IO。调用方即使忘了 try/except 也不会把问答带崩。
"""
from __future__ import annotations

import math
from collections import Counter, deque
from threading import Lock

CAPACITY = 200

# 检索分段的字段名（`retriever` 写进 `trace["timings"]` 的那一组）。
# ⚠️ 只在这里定义一次 —— 两处各写一份就会漂移（本项目已踩过）。
STAGE_KEYS = ("rewrite_ms", "embed_ms", "lexical_ms", "vector_ms", "fuse_ms", "rerank_ms")

_events: deque[dict] = deque(maxlen=CAPACITY)
_lock = Lock()


def record(**fields) -> None:
    """追加一条请求级指标（新→旧由 `snapshot()` 负责排序）。"""
    with _lock:
        _events.append(dict(fields))


def reset() -> None:
    """清空缓冲（测试用；生产没有写端点，不暴露）。"""
    with _lock:
        _events.clear()


def usage_from_messages(messages) -> dict:
    """从 LangChain 消息里汇总 token 用量。

    ⚠️ 拿不到就是 `None`，⛔ 不写 0 —— "没采到"与"用了 0 个 token"是两件事
    （同 `2.0-59` / `2.0-68` 的口径）。
    """
    prompt = completion = None
    for m in messages or []:
        um = getattr(m, "usage_metadata", None) or {}
        if not um:
            continue
        if um.get("input_tokens") is not None:
            prompt = (prompt or 0) + um["input_tokens"]
        if um.get("output_tokens") is not None:
            completion = (completion or 0) + um["output_tokens"]
    return {"prompt": prompt, "completion": completion}


def merge_usage(*usages) -> dict:
    """合并多处 token 用量（生成侧 `usage_metadata` ／ 判定侧 `usage_out`）。

    两边的键名不同（`prompt`/`prompt_tokens`），这里统一成 `prompt`/`completion`。
    ⚠️ 任一来源拿不到就留 `None`，⛔ 不写 0 —— "没采到" ≠ "用了 0 个 token"。
    """
    prompt = completion = None
    for u in usages:
        if not isinstance(u, dict):
            continue
        p = u.get("prompt", u.get("prompt_tokens"))
        c = u.get("completion", u.get("completion_tokens"))
        if isinstance(p, int):
            prompt = (prompt or 0) + p
        if isinstance(c, int):
            completion = (completion or 0) + c
    return {"prompt": prompt, "completion": completion}


def _pct(values: list[float], p: float) -> float | None:
    """最近秩百分位（与评测产物的口径一致）；空列表 → None，⛔ 不写 0。"""
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, math.ceil(p / 100 * len(ordered)) - 1)
    return ordered[idx]


def _ms(items: list[dict], path: tuple[str, ...]) -> list[float]:
    """按字段路径取一组毫秒值（缺失 / None 的条目跳过）。"""
    out: list[float] = []
    for it in items:
        cur = it
        for key in path:
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(key)
        if isinstance(cur, (int, float)):
            out.append(float(cur))
    return out


def _latency(values: list[float]) -> dict:
    """延迟必须报 p50/p90/p95/max ＋ >5s 占比（⛔ 不许只报平均）。"""
    if not values:
        return {"count": 0, "p50": None, "p90": None, "p95": None, "max": None,
                "slow_5s_ratio": None}
    return {
        "count": len(values),
        "p50": round(_pct(values, 50), 1),
        "p90": round(_pct(values, 90), 1),
        "p95": round(_pct(values, 95), 1),
        "max": round(max(values), 1),
        "slow_5s_ratio": round(sum(1 for v in values if v > 5000) / len(values), 4),
    }


def summarize(items: list[dict]) -> dict:
    """把缓冲里的条目汇总成监控台要的一组数（范围 = 当前缓冲）。"""
    if not items:
        return {
            "requests": 0, "by_kind": {}, "cache_hit_ratio": None,
            "judge_status": {}, "answer_kind": {}, "tool_rounds_max": None,
            "candidates_avg": None, "fill_rate_avg": None, "cited_avg": None,
            "tokens": {"prompt": None, "completion": None, "unknown_requests": 0},
            "latency": _latency([]),
            "latency_uncached": _latency([]),
            "stages": {},
        }

    by_kind = Counter(i.get("kind", "unknown") for i in items)
    statuses = Counter(i.get("judge_status", "unknown") for i in items)
    kinds = Counter(i.get("answer_kind", "unknown") for i in items)
    cache_flags = [bool(i.get("cache_hit")) for i in items if "cache_hit" in i]

    candidates = [i["candidates"] for i in items if isinstance(i.get("candidates"), int)]
    fill = [i["fill_rate"] for i in items if isinstance(i.get("fill_rate"), (int, float))]
    cited = [i["cited"] for i in items if isinstance(i.get("cited"), int)]
    rounds = [i["tool_rounds"] for i in items if isinstance(i.get("tool_rounds"), int)]

    prompt_vals = [i["tokens"]["prompt"] for i in items
                   if isinstance(i.get("tokens"), dict)
                   and isinstance(i["tokens"].get("prompt"), int)]
    completion_vals = [i["tokens"]["completion"] for i in items
                       if isinstance(i.get("tokens"), dict)
                       and isinstance(i["tokens"].get("completion"), int)]

    stages = {
        "retrieve_ms": _latency(_ms(items, ("timings", "retrieve_ms"))),
        "generate_ms": _latency(_ms(items, ("timings", "generate_ms"))),
        "ambiguity_ms": _latency(_ms(items, ("timings", "ambiguity_ms"))),
        "rewrite_ms": _latency(_ms(items, ("retrieve", "rewrite_ms"))),
        "embed_ms": _latency(_ms(items, ("retrieve", "embed_ms"))),
        "lexical_ms": _latency(_ms(items, ("retrieve", "lexical_ms"))),
        "vector_ms": _latency(_ms(items, ("retrieve", "vector_ms"))),
        "fuse_ms": _latency(_ms(items, ("retrieve", "fuse_ms"))),
        "rerank_ms": _latency(_ms(items, ("retrieve", "rerank_ms"))),
    }

    return {
        "requests": len(items),
        "by_kind": dict(by_kind),
        "cache_hit_ratio": (round(sum(cache_flags) / len(cache_flags), 4)
                            if cache_flags else None),
        "judge_status": dict(statuses),
        "answer_kind": dict(kinds),
        "tool_rounds_max": max(rounds) if rounds else None,
        "candidates_avg": round(sum(candidates) / len(candidates), 2) if candidates else None,
        "fill_rate_avg": round(sum(fill) / len(fill), 4) if fill else None,
        "cited_avg": round(sum(cited) / len(cited), 2) if cited else None,
        "tokens": {
            "prompt": sum(prompt_vals) if prompt_vals else None,
            "completion": sum(completion_vals) if completion_vals else None,
            # ⚠️ 有多少条"没采到用量"——⛔ 不能把 None 当 0 混进上面的合计里
            "unknown_requests": len(items) - len(prompt_vals),
        },
        "latency": _latency(_ms(items, ("timings", "total_ms"))),
        # ⚠️ 缓存命中会在 1~2ms 内返回，混进 p50 会把"真实生成耗时"整体拉低
        #    ⇒ 单独给一份**非缓存**延迟（页面两个都要显示，别混着读）。
        "latency_uncached": _latency(
            _ms([i for i in items if not i.get("cache_hit")], ("timings", "total_ms"))),
        "stages": stages,
    }


def snapshot(limit: int = 50) -> dict:
    """返回最近 `limit` 条（**新→旧**）＋ 全缓冲汇总。

    ⚠️ 汇总的范围是**整个缓冲**（`buffered`），不是 `limit` 条；
    两者都返回，前端显示时要写清范围，否则会被读成"总共只处理了 50 次"。
    """
    with _lock:
        items = list(_events)
    recent = list(reversed(items))[:max(0, limit)]
    return {
        "capacity": CAPACITY,
        "buffered": len(items),
        "items": recent,
        "summary": summarize(items),
    }
