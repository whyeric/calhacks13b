"""Desk run for the season playoff hedge: one Hedge per futures leg, same exposure id, existing rules,
templated summaries that pass I2, every leg logged once (I5). Offline: fixture markets replay the
season futures from fixtures/kalshi_cache; sockets are blocked by the root conftest."""

import asyncio

import pytest

from app import analysis, db
from app.agent import desk, log
from app.models import AnalyzeResponse, Exposure, ModelCheck

from .conftest import NOW, WEEK, MockClaude, example

EXP = "exp_playoff_home"


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch):
    """Belt and braces on top of the root conftest: any socket connect fails the test."""
    import socket

    def refuse(self, *a, **kw):
        raise AssertionError(f"socket connect in an offline test: {a}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


@pytest.fixture(autouse=True)
def playoff_analysis(monkeypatch):
    e = Exposure.model_validate(example("exposure_playoff.json"))
    res = AnalyzeResponse(exposures=[e], dropped=[], model_check=ModelCheck.model_validate(example("model_check.json")),
                          r2_holdout=None)
    monkeypatch.setattr(analysis, "compute", lambda business_id, strike=None: res)
    return e


def run(run_id, client=None):
    return asyncio.run(desk.run_week("restaurant", WEEK, run_id=run_id, client=client, now=NOW, model="test-model"))


def test_one_hedge_per_leg_with_the_same_exposure_id():
    r = run("run_po1")
    legs = [h for h in r.hedges if h.exposure_id == EXP]
    assert {h.ticker for h in legs} == {"KXNBAPLAYOFF-27-NYK", "KXNBAEAST-27-NYK", "KXNBA-27-NYK"}
    assert len({h.id for h in legs}) == 3 and all(h.side == "no" for h in legs)
    assert {h.leg_label for h in legs} == {"Knicks miss the playoffs", "Knicks don't win the East",
                                          "Knicks don't win the title"}
    total = sum(h.premium for h in legs)
    assert {h.group_total_premium for h in legs} == {total}
    stored = {h.id: h for h in db.list_hedges("restaurant", WEEK)}
    assert all(stored[h.id] == h for h in legs)


def test_rules_run_and_budget_pauses_the_expensive_legs():
    legs = {h.ticker: h for h in run("run_po2").hedges}
    for h in legs.values():
        # Every check ran; `unstable` is skipped because a pooled playoff estimate has no recent window.
        skipped = [c.code for c in h.decision.checks if c.passed is None]
        assert skipped == ["unstable"]
        assert next(c for c in h.decision.checks if c.code == "unstable").metric == {"skipped": "no_recent_window"}
        assert h.status in ("proposed", "pending_approval", "declined")
    # The $250 weekly budget covers the cheap title leg; the others wait for the owner (D4).
    assert legs["KXNBA-27-NYK"].status == "proposed"
    assert legs["KXNBAEAST-27-NYK"].status == "pending_approval"
    assert legs["KXNBAEAST-27-NYK"].decision.reasons == ["over_budget"]
    budget_left = [next(c for c in h.decision.checks if c.code == "over_budget").metric["remaining"]
                   for h in legs.values()]
    assert len(set(budget_left)) > 1  # each leg sees the budget the earlier legs left


def test_every_leg_logged_once_with_a_summary_that_passes_I2():
    r = run("run_po3")
    entries = [e for e in log.list("restaurant") if e.run_id == "run_po3"]
    assert sorted(e.hedge_id for e in entries) == sorted(h.id for h in r.hedges)
    for e in entries:
        assert log.validate_summary(e.summary, e.numbers) == []
        assert "[unverified]" not in e.summary and e.summary.startswith("Season playoff hedge")
        assert e.agent == "fallback"


def test_same_week_rerun_reuses_all_legs():
    first = run("run_po4")
    again = run("run_po5")
    assert again.skipped_existing == [EXP]
    assert {h.id for h in again.hedges} == {h.id for h in first.hedges}
    assert not [e for e in log.list("restaurant") if e.run_id == "run_po5"]


def test_claude_is_not_called_for_the_season_hedge():
    client = MockClaude([])
    r = run("run_po6", client=client)
    assert client.calls == [] and len(r.hedges) == 3


def test_no_futures_cached_gives_one_no_market_decline(monkeypatch):
    from app.markets.kalshi import CacheMiss
    from app.markets.port import FixtureMarkets

    async def miss(self):
        raise CacheMiss("/markets/KXNBA-27-NYK", {})

    monkeypatch.setattr(FixtureMarkets, "season_quotes", miss)
    r = run("run_po7")
    assert len(r.hedges) == 1
    h = r.hedges[0]
    assert h.status == "declined" and h.decision.reasons == ["no_market"] and h.exposure_id == EXP
