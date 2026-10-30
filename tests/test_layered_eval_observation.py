"""评测产物的**可追溯字段**（`ambiguity_observation`）。

守的是什么：判官（歧义判定）**说了什么**必须能事后查到。
只存 `status` 时，一次「冲突题全判无冲突」只能重跑才能问出原因 —— 而重跑要起检索环境。
⚠️ 这是**观测字段**，不参与任何对错判定；下面的断言也不该被解读成"判定规则"。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from src.rag.ambiguity import (
    JUDGE_AMBIGUOUS,
    JUDGE_CLEAR,
    JUDGE_UNKNOWN,
    AmbiguityResult,
    ClarifyOption,
)
from src.vector_store.base import Chunk

_SPEC = importlib.util.spec_from_file_location(
    "run_layered_eval", Path(__file__).resolve().parents[1] / "eval" / "run_layered_eval.py")
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
ambiguity_observation = _MOD.ambiguity_observation


def _chunks(*files: str | None) -> list[Chunk]:
    return [Chunk(document_id=f"d{i}", chunk_index=i, content=f"c{i}", source_file=f)
            for i, f in enumerate(files)]


def test_clear_carries_reason_and_candidates():
    amb = AmbiguityResult(status=JUDGE_CLEAR, reason="片段约束不同主体")
    obs = ambiguity_observation(amb, _chunks("19.docx", "02.pdf"))

    assert obs["judge_status"] == JUDGE_CLEAR
    assert obs["need_clarification"] is False
    assert obs["ambiguity_reason"] == "片段约束不同主体", "判官给的理由必须落盘"
    assert obs["candidates"] == ["19.docx", "02.pdf"], "候选来源按送入顺序原样记录"


def test_ambiguous_sets_need_clarification():
    amb = AmbiguityResult(
        status=JUDGE_AMBIGUOUS,
        reason="两处金额不一致",
        options=[ClarifyOption(source="a", summary="20 万")],
    )
    obs = ambiguity_observation(amb, _chunks("a.docx", "b.docx"))

    assert obs["need_clarification"] is True
    assert obs["judge_status"] == JUDGE_AMBIGUOUS
    assert obs["ambiguity_reason"] == "两处金额不一致"


def test_unknown_keeps_failure_kind_and_reason():
    """反向用例：**判官没给出结论**时，理由和成因恰恰最需要被记下来。

    若这里只记 `status=unknown`，"判官为什么没答"就丢了 —— 而那正是唯一能区分
    「外部故障」与「结构性缺陷」的东西。
    """
    amb = AmbiguityResult(status=JUDGE_UNKNOWN, reason="模型返回的内容不是合法 JSON",
                          failure_kind="unparsed")
    obs = ambiguity_observation(amb, _chunks("x.docx", "y.docx"))

    assert obs["judge_status"] == JUDGE_UNKNOWN
    assert obs["need_clarification"] is False, "unknown ≠ ambiguous"
    assert obs["judge_failure_kind"] == "unparsed"
    assert obs["ambiguity_reason"], "失败理由不能为空 —— 空的等于没记"


def test_missing_source_file_is_preserved_not_dropped():
    """来源缺失时如实留 `None`，⛔ 不静默过滤 —— 过滤会让候选数对不上。"""
    obs = ambiguity_observation(AmbiguityResult(), _chunks("a.docx", None))
    assert obs["candidates"] == ["a.docx", None]
