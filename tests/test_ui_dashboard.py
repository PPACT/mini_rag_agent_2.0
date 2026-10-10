"""`2.0-54` 演示界面的最小冒烟 ＋ 看板取数的口径测试。

⚠️ 为什么不依赖真产物：产物在 `logs/`（**不进仓库**、会被重跑覆盖）→
夹具在这里**现造**，口径钉死在测试里。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ui import api_client, logs_reader as L

# --------------------------------------------------------------------------
# 夹具：故意让「多 anchor 子集」和「多跳」**不是**同一个集合
# --------------------------------------------------------------------------

def _row(qid: str, kind: str, ranks_each: list[int | None]) -> dict:
    return {"id": qid, "kind": kind, "ranks_each": ranks_each, "answer": "a"}


def _layered_fixture() -> dict:
    rows = [
        _row("mh1", "multi_hop", [1, 2]),      # 中（两份都进前三）
        _row("mh2", "multi_hop", [1, 5]),      # 不中（第二份在第 5）
        _row("cf1", "conflict", [2, 3]),       # 中 —— ⭐ 它**不是**多跳，但属多 anchor
        _row("sh1", "single_hop", [1]),        # 单 anchor：不进 AllHit 分母
        _row("na1", "no_answer", [None]),      # 无答案：不算 R@K、也不算 AllHit
    ]
    return {
        "config": {"kb": "stress", "top": 5, "model": "m"},
        "dataset_size": 5,
        "results": {
            "臂A": {
                "rows": rows,
                "summary": {
                    "overall": {"R@1": 0.5},   # n_ans = 4 → 2/4
                    "refuse_ok": 1, "refuse_n": 1,
                    "false_refuse": 0, "false_n": 4,
                    "gen_error_n": 0,
                    "judge_status": {"clear": 5},
                    "per_kind": {},
                },
            },
        },
    }


# --------------------------------------------------------------------------
# ⭐ 反向用例：分母口径（`§1.99` 那次手算错的就是这个）
# --------------------------------------------------------------------------

def test_allhit_denominator_is_multi_anchor_not_multi_hop():
    """⭐ `AllHit@3` 的分母 = **多 anchor 子集**（含冲突 / 消歧），**不是「多跳」那个子集**。

    夹具刻意把两者错开（`cf1` 是多 anchor 但不是多跳）——
    若哪天有人把分母改回 `kind == "multi_hop"`，这条会红。
    """
    arms = L.layered_summary(_layered_fixture())
    hit, n = arms["臂A"]["AllHit@3"]
    assert (hit, n) == (2, 3), "分母必须是多 anchor 子集（3），不是多跳（2）"

    # ⭐ 自证有区分度：夹具里「多跳」只有 2 道、与分母 3 **确实不同** ——
    #    所以换成 `kind == "multi_hop"` 的实现会算出 (1, 2)，本条必红。
    mh_only = [r for r in _layered_fixture()["results"]["臂A"]["rows"]
               if r["kind"] == "multi_hop" and len(r["ranks_each"]) > 1]
    assert len(mh_only) == 2


def test_r1_count_is_derived_from_answerable_rows():
    """`R@K` 的分母 = **有答案题**（无答案题不算），且是从行里数出来的 —— 不硬编码 45。"""
    arms = L.layered_summary(_layered_fixture())
    assert arms["臂A"]["R@1"] == (2, 4)
    assert arms["臂A"]["n_total"] == 5          # 总数仍报（供人核对）
    assert arms["臂A"]["n_answerable"] == 4


# --------------------------------------------------------------------------
# 读产物：缺文件 / 坏 JSON **必须显式报错**
# --------------------------------------------------------------------------

def test_load_missing_raises_with_path(tmp_path: Path):
    with pytest.raises(L.ArtifactError) as e:
        L.load("nope.json", logs_dir=tmp_path)
    assert "nope.json" in str(e.value)          # ⚠️ 报错要带路径，否则定位不了


def test_load_bad_json_raises(tmp_path: Path):
    (tmp_path / "bad.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(L.ArtifactError):
        L.load("bad.json", logs_dir=tmp_path)


def test_load_non_object_top_level_raises(tmp_path: Path):
    (tmp_path / "arr.json").write_text("[1,2,3]", encoding="utf-8")
    with pytest.raises(L.ArtifactError):
        L.load("arr.json", logs_dir=tmp_path)


def test_list_artifacts_on_missing_dir_is_empty_not_error(tmp_path: Path):
    assert L.list_artifacts(logs_dir=tmp_path / "nope") == []


def test_list_artifacts_labels_known(tmp_path: Path):
    (tmp_path / "l0_report.json").write_text(json.dumps({"summary": {}}), encoding="utf-8")
    (tmp_path / "whatever.json").write_text("{}", encoding="utf-8")
    arts = {a["name"]: a for a in L.list_artifacts(logs_dir=tmp_path)}
    assert arts["l0_report.json"]["label"] == "L0 切分体检"
    assert arts["whatever.json"]["label"] == ""   # 未登记的**仍然列出来**（不假装不存在）


def test_layered_summary_rejects_foreign_shape():
    with pytest.raises(L.ArtifactError):
        L.layered_summary({"nope": 1})


def test_e2e_gen_error_counted_separately():
    """生成失败**单列** —— 不混进 `has_value` 的分母（否则两头都失真）。"""
    d = {"config": {}, "rows": [
        {"exp_has_value": True,  "exp_error": "",     "ctl_has_value": True,  "ctl_error": "",
         "blind_has_value": False, "blind_error": ""},
        {"exp_has_value": False, "exp_error": "boom", "ctl_has_value": True,  "ctl_error": "",
         "blind_has_value": False, "blind_error": ""},
    ]}
    arms = L.e2e_summary(d)["arms"]
    assert arms["exp"] == {"has_value": 1, "gen_error": 1, "n": 2}
    assert arms["ctl"] == {"has_value": 2, "gen_error": 0, "n": 2}


# --------------------------------------------------------------------------
# 链路透视：排名差量（约束 3 那条「提权 / 下移」）
# --------------------------------------------------------------------------

def _c(source: str, idx: int, rank: int) -> dict:
    return {"source": source, "chunk_index": idx, "rank": rank}


def test_rank_moves_nothing_moved():
    cands = [_c("a", 0, 1), _c("b", 0, 2)]
    assert api_client.rank_moves(cands, list(cands)) == {}


def test_rank_moves_up_and_down():
    cands = [_c("a", 0, 1), _c("b", 0, 2), _c("c", 0, 3)]
    final = [_c("b", 0, 1), _c("a", 0, 2), _c("c", 0, 3)]     # a 下移、b 提权、c 不动
    assert api_client.rank_moves(cands, final) == {("a", 0): "down", ("b", 0): "up"}


def test_rank_moves_ignores_chunks_missing_from_final():
    """精排**杀掉**的候选不该报成"下移" —— 它压根不在结果里。"""
    cands = [_c("a", 0, 1), _c("z", 0, 2)]
    final = [_c("a", 0, 1)]
    assert api_client.rank_moves(cands, final) == {}


def test_rank_moves_matches_on_identity_not_rank():
    """同名不同块的块**不能**被当成同一个 —— 否则差量全乱。"""
    cands = [_c("a", 7, 1)]
    final = [_c("a", 8, 1)]
    assert api_client.rank_moves(cands, final) == {}


def test_api_error_on_unreachable_backend():
    with pytest.raises(api_client.ApiError):
        api_client.ask_chat("x", base_url="http://127.0.0.1:1", timeout=2.0)


# --------------------------------------------------------------------------
# 冒烟：界面**起得来**（约束 7）
# --------------------------------------------------------------------------

def test_streamlit_app_boots_without_exception():
    """起得来 + 三个页签都渲染 —— 不连后端也应能渲染（看板走本地文件）。"""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(L.ROOT / "scripts" / "demo_app.py"), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    assert len(at.tabs) == 3
