"""判官试点的**花费闸**必须有反向用例 —— 断言要能失败，否则闸等于没装。"""

import asyncio

import pytest

import eval.gen_quality_pilot as pilot


def _rows(ids=None):
    return [{"id": i, "kind": "single_hop", "question": f"q{i}"}
            for i in (ids or pilot.PILOT_IDS)]


def test_select_accepts_exactly_the_fixed_ten():
    rows = pilot.select_pilot_rows(_rows())
    assert [r["id"] for r in rows] == list(pilot.PILOT_IDS)
    assert len(rows) == 10


@pytest.mark.parametrize("bad_ids", [
    list(pilot.PILOT_IDS)[:9],                      # 少一条
    list(pilot.PILOT_IDS) + [5040],                 # 多一条
    [5001] * 10,                                    # 条数对、集合不对
    list(range(5001, 5011)),                        # 换成别的 10 条
])
def test_select_rejects_any_other_selection(bad_ids):
    with pytest.raises(ValueError):
        pilot.select_pilot_rows(_rows(), ids=bad_ids)


def test_select_rejects_missing_rows():
    with pytest.raises(ValueError, match="缺这些 id"):
        pilot.select_pilot_rows(_rows()[1:])


def test_eleventh_call_is_blocked():
    budget = pilot.JudgeBudget()
    for _ in range(pilot.MAX_CALLS):
        budget.before_call()
        budget.add_usage(100, 10)
    with pytest.raises(pilot.BudgetExceeded, match="调用次数超限"):
        budget.before_call()


def test_token_cap_aborts_immediately():
    budget = pilot.JudgeBudget(token_cap=1_000)
    budget.before_call()
    with pytest.raises(pilot.BudgetExceeded, match="token 累计"):
        budget.add_usage(1_200, 0)


def test_estimate_abort_raises_before_any_request(monkeypatch):
    async def fake_ctx(row, top):
        return "上下文" * 5_000            # 够长 → 估算必超预检线

    monkeypatch.setattr(pilot, "_context_for", fake_ctx)
    answers = {i: "答" for i in pilot.PILOT_IDS}
    with pytest.raises(pilot.BudgetExceeded, match="预检线"):
        asyncio.run(pilot.run_pilot(_rows(), answers, dry_run=True))


def test_dry_run_sends_nothing(monkeypatch):
    async def fake_ctx(row, top):
        return "上下文"

    class BoomModel:
        def bind(self, **kw):  # noqa: ARG002
            raise AssertionError("dry-run 不许构建请求")

    monkeypatch.setattr(pilot, "_context_for", fake_ctx)
    answers = {i: "答" for i in pilot.PILOT_IDS}
    result = asyncio.run(pilot.run_pilot(_rows(), answers, dry_run=True, model=BoomModel()))
    assert result["dry_run"] is True
    assert result["sent"] == 0 and result["tokens"] == 0
    assert len(result["items"]) == 10


def test_real_run_without_yes_refuses(monkeypatch):
    async def fake_ctx(row, top):
        return "上下文"

    monkeypatch.setattr(pilot, "_context_for", fake_ctx)
    answers = {i: "答" for i in pilot.PILOT_IDS}
    with pytest.raises(SystemExit, match="--yes"):
        asyncio.run(pilot.run_pilot(_rows(), answers, dry_run=False, assume_yes=False))


def test_missing_answer_is_refused(monkeypatch):
    async def fake_ctx(row, top):
        return "上下文"

    monkeypatch.setattr(pilot, "_context_for", fake_ctx)
    with pytest.raises(ValueError, match="答案产物里没有"):
        asyncio.run(pilot.run_pilot(_rows(), {}, dry_run=True))
