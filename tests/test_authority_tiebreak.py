"""`2.0-72` / `提醒 #30`：`authority` **近分 tie-break**（⛔ 不是乘法加权）。

口径（`§1.138③`）：
- 只有精排分差 **≤ ε** 才让 `authority` 高者优先；分差大 ⇒ 精排说了算。
- **默认关闭** —— 没做过两臂对照的排序改动不许默认生效。

⚠️ 这里钉住的是**规则本身**；"到底有没有效果"要看两臂实测，⛔ 不要拿单测当效果证据。
"""
from __future__ import annotations

from src.config.settings import get_settings
from src.rag.authority import authority_tiebreak
from src.vector_store.base import Chunk


def _c(cid: str, authority: int) -> Chunk:
    return Chunk(document_id="d", chunk_index=0, content=cid, source_file=f"{cid}.md",
                 id=cid, authority=authority)


# ---- 基本规则 ----


def test_near_tie_prefers_higher_authority():
    """分差 ≤ ε ⇒ 制度文档上浮。"""
    ordered = [(_c("a", 0), 0.90), (_c("b", 2), 0.88)]
    out, moved = authority_tiebreak(ordered, epsilon=0.05)
    assert [c.id for c, _ in out] == ["b", "a"]
    assert moved == 2, "两条都换了位置，触发量要如实记"


def test_large_gap_is_a_hard_boundary():
    """⚠️ 反向用例：分差 > ε ⇒ **不许**拿元数据去压精排。"""
    ordered = [(_c("a", 0), 0.90), (_c("b", 2), 0.10)]
    out, moved = authority_tiebreak(ordered, epsilon=0.05)
    assert [c.id for c, _ in out] == ["a", "b"]
    assert moved == 0


def test_equal_authority_keeps_original_order():
    """同级不许被"顺手"重排 —— 否则规则之外还改了东西。"""
    ordered = [(_c("a", 0), 0.90), (_c("b", 0), 0.89), (_c("c", 0), 0.88)]
    out, moved = authority_tiebreak(ordered, epsilon=0.05)
    assert [c.id for c, _ in out] == ["a", "b", "c"]
    assert moved == 0


def test_cluster_is_transitive_not_pairwise():
    """⭐ 用**簇**而不是两两比较：A≈B、B≈C 但 A 与 C 差很多时，
    两两比较会得到不可传递的顺序；簇内排序则稳定。"""
    # ⚠️ 分数特意避开 ε 的边界：`0.95 - 0.90` 在浮点下略大于 `0.05`，
    #    写成边界值会得到一个"测试自己绊自己"的假失败。
    ordered = [(_c("a", 0), 0.90), (_c("b", 0), 0.94), (_c("c", 2), 0.98)]
    # 相邻分差 0.04 / 0.04（≤ ε）⇒ 三段并成一簇，按 authority 排：c 先，a/b 保序
    out, _ = authority_tiebreak(ordered, epsilon=0.05)
    assert [c.id for c, _ in out] == ["c", "a", "b"]


def test_epsilon_zero_is_off():
    ordered = [(_c("a", 0), 0.5), (_c("b", 2), 0.5)]
    out, moved = authority_tiebreak(ordered, epsilon=0.0)
    assert [c.id for c, _ in out] == ["a", "b"]
    assert moved == 0, "ε=0 等价于关闭；不许把'完全同分'偷当成开启"


def test_missing_scores_are_not_comparable():
    """⚠️ 反向用例：拿不到分数（如 LLM 精排）⇒ **不做**。
    ⛔ 不能用"名次差"冒充满分差 —— 那不是同一把尺子。"""
    ordered = [(_c("a", 0), None), (_c("b", 2), None)]
    out, moved = authority_tiebreak(ordered, epsilon=0.05)
    assert [c.id for c, _ in out] == ["a", "b"]
    assert moved == 0


# ---- 默认不生效（`§1.138③` 明确要求的一条）----


def test_default_is_disabled():
    s = get_settings()
    assert s.authority_tiebreak_enabled is False, (
        "排序改动默认生效 = 没做对照就上线；要开请显式设 AUTHORITY_TIEBREAK_ENABLED=true"
    )


def test_enabled_requires_a_measured_epsilon():
    """⚠️ 反向用例：「开关打开但 ε=0」是**最坏的组合** ——
    看着启用了、实际一行不生效，而且日志里也看不出来（`moved` 恒为 0）。
    ε 只能来自实测分布（`logs/authority_tiebreak_epsilon_20261018.json`）。
    """
    s = get_settings()
    assert (not s.authority_tiebreak_enabled) or s.authority_tiebreak_epsilon > 0, (
        "开了开关却没设 ε ⇒ 等于没开，但看起来像开了"
    )
