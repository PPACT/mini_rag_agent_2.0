"""`2.0-72` / `提醒 #30`：`authority` 的**近分 tie-break**（⛔ 不是乘法加权）。

## 口径（`§1.138③` 的裁定，⛔ 不要改口径）

- **只在"分差很小"时起作用**：两条候选的精排分差 **≤ ε** 才让 `authority` 高者优先；
  分差大说明精排已经"看清楚"了，**不拿元数据去压它**。
- **⛔ 不做乘法加权**：乘数必然要调参，而调参在 23 份语料上没有区分度（`P-4`）。
- **ε 由数据定**（先测分差分布，取 p10），⛔ 不写死一个数。
- **默认关闭**：开关 `AUTHORITY_TIEBREAK_ENABLED` 默认 `False` ——
  没做过两臂对照的排序改动**不许默认生效**（`§1.138③` 要求留一条"默认 = 不生效"的测试）。

## 为什么是"簇"而不是"两两比较"

只看相邻两条会得到**不可传递**的排序（A≈B、B≈C 但 A 与 C 差很多）。
所以先把"相邻分差 ≤ ε"串成的**连续段**当作一个簇，簇内按 `authority` 降序（同级保持原序），
簇与簇之间**绝不跨越** —— 这样"大分差"永远是硬边界。
"""
from __future__ import annotations

from src.vector_store.base import Chunk

Scored = tuple[Chunk, "float | None"]


def _gap(prev: Scored, cur: Scored) -> float | None:
    """相邻两条的分差；任一侧没有分数 → None（表示"不可比"，必须当硬边界）。"""
    if prev[1] is None or cur[1] is None:
        return None
    return abs(float(prev[1]) - float(cur[1]))


def authority_tiebreak(ordered: list[Scored], epsilon: float) -> tuple[list[Scored], int]:
    """在"近分簇"内按 `authority` 降序重排。返回 (新列表, **被移动的条数**)。

    ⚠️ **改变的条数**是回执里必须报的"触发次数"口径之一：
    `0` = 这次查询里 tie-break **没起作用**（⛔ 不等于"没用"，见 `提醒 #30②`）。

    `epsilon <= 0` ⇒ 原样返回（等价于关闭）。
    """
    if epsilon <= 0 or len(ordered) < 2:
        return list(ordered), 0
    if any(s is None for _, s in ordered):
        # 拿不到可比的分差 ⇒ **不做**。⛔ 不能拿"名次差"冒充分差。
        return list(ordered), 0

    clusters: list[list[Scored]] = []
    cur = [ordered[0]]
    for prev, item in zip(ordered, ordered[1:]):
        gap = _gap(prev, item)
        if gap is not None and gap <= epsilon:
            cur.append(item)
        else:
            clusters.append(cur)
            cur = [item]
    clusters.append(cur)

    out: list[Scored] = []
    moved = 0
    for cluster in clusters:
        if len(cluster) == 1:
            out.extend(cluster)
            continue
        ranked = sorted(cluster, key=lambda t: -t[0].authority)  # 稳定排序：同级保序
        moved += sum(1 for a, b in zip(cluster, ranked) if a[0] is not b[0])
        out.extend(ranked)
    return out, moved
