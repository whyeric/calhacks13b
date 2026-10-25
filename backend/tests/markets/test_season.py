"""Season playoff hedge (app/markets/season.py): live futures from the offline cache, min-variance
sizing, and every leg judged by the existing rules. No network (conftest blocks it)."""

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.config import Thresholds
from app.markets import season
from app.markets.kalshi import CacheMiss, KalshiClient, Orderbook
from app.models import CHECK_ORDER, Exposure, Hedge, Level

NOW = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
WEEK = date(2026, 10, 26)


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch):
    """Belt and braces on top of the root conftest: any socket connect fails the test."""
    import socket

    def refuse(self, *a, **kw):
        raise AssertionError(f"socket connect in an offline test: {a}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


def exposure(effect="502.94") -> Exposure:
    return Exposure(
        id="exp_playoff_home", business_id="restaurant", event="playoff_home", effect_usd=Decimal(effect),
        ci90=(Decimal("373.89"), Decimal("633.84")), se=Decimal("79.01"), p_value=1e-10, n_events_train=33,
        direction="positive", hedge_side="no", settlement_var="playoff_home", hedgeable=True, reasons=[],
        strike=None, beta_settlement=None, expected_count=5.56, estimated=True, basis_note="pooled",
    )


def quotes():
    q = season.cached_quotes()
    assert q is not None, "season futures missing from fixtures/kalshi_cache (scripts/fetch_playoffs.py --kalshi)"
    return q


def book(ticker, yes_bids, no_bids):
    lv = lambda xs: [Level(price=Decimal(p), count=n) for p, n in xs]  # noqa: E731
    return Orderbook(ticker=ticker, yes_bids=lv(yes_bids), no_bids=lv(no_bids), fetched_at=NOW)


def test_offline_client_replays_the_same_quotes_as_the_sync_reader():
    async def go():
        async with KalshiClient(offline=True) as k:
            return await season.fetch_quotes(k)

    live, cached = asyncio.run(go()), quotes()
    assert [q.leg.ticker for q in live] == ["KXNBAPLAYOFF-27-NYK", "KXNBAEAST-27-NYK", "KXNBA-27-NYK"]
    assert [(q.yes_bid, q.yes_ask) for q in live] == [(q.yes_bid, q.yes_ask) for q in cached]
    assert all(q.yes_bid < q.yes_ask for q in live)


def test_offline_miss_raises_cache_miss(tmp_path):
    async def go():
        async with KalshiClient(offline=True, cache_dir=tmp_path) as k:
            await season.fetch_quotes(k)

    with pytest.raises(CacheMiss):
        asyncio.run(go())
    assert season.cached_quotes(tmp_path) is None


def test_futures_ladder_is_consistent_and_expected_home_games_plausible():
    q = quotes()
    p_make, p_east, p_title = (x.mid for x in q)
    assert 0 < p_title <= p_east <= p_make <= 1
    assert 2.0 < season.expected_home_games(q) < 9.0


def test_plan_buys_no_on_each_leg_capped_at_its_swing():
    sp = season.plan(exposure(), quotes())
    assert [lp.quote.leg.key for lp in sp.legs] == ["playoffs", "east", "title"]
    for lp in sp.legs:
        assert 0 < lp.n_target <= int(lp.swing)  # I1 per leg: contracts <= the $ at stake
        assert lp.fair == 1 - lp.quote.mid
    assert 0.5 < sp.variance_removed < 1 and sp.sd_after < sp.sd_before
    assert sp.expected_uplift == (Decimal("502.94") * Decimal(repr(sp.expected_home_games))).quantize(Decimal("0.01"))


def test_plan_scales_linearly_with_the_uplift():
    small, big = season.plan(exposure("250.00"), quotes()), season.plan(exposure("500.00"), quotes())
    for a, b in zip(small.legs, big.legs):
        assert b.n_model == pytest.approx(2 * a.n_model)


def test_each_leg_is_a_full_hedge_judged_by_the_six_rules():
    e, sp = exposure(), season.plan(exposure(), quotes())
    for lp in sp.legs:
        h = season.leg_hedge(e, sp, lp, hedge_id=f"hdg_t_{lp.quote.leg.key}", week_of=WEEK, now=NOW,
                             agent="fallback", remaining=Decimal("10000.00"), thresholds=Thresholds())
        assert isinstance(h, Hedge) and h.exposure_id == e.id and h.side == "no"
        assert [c.code for c in h.decision.checks] == list(CHECK_ORDER)
        assert h.ticker == lp.quote.leg.ticker and h.leg_label == lp.quote.leg.label
        assert h.premium == h.cost + h.fee and h.n_filled <= h.n_target == lp.n_target
        assert h.payoff[0].revenue_vs_base == lp.swing and h.payoff[1].contract_payout == h.n_filled
        basis = next(c for c in h.decision.checks if c.code == "basis_too_loose").metric
        assert basis["h"] == 1 and basis["r2"] == Decimal(repr(sp.variance_removed)).quantize(Decimal("0.0001"))
        assert h.status in ("proposed", "declined")  # a big budget: never paused


def test_small_budget_pauses_a_leg_for_approval():
    e, sp = exposure(), season.plan(exposure(), quotes())
    east = next(lp for lp in sp.legs if lp.quote.leg.key == "east")
    h = season.leg_hedge(e, sp, east, hedge_id="hdg_t_east", week_of=WEEK, now=NOW, agent="fallback",
                         remaining=Decimal("250.00"), thresholds=Thresholds())
    assert h.status == "pending_approval" and h.decision.reasons == ["over_budget"]
    assert "Waiting for your approval" in season.leg_summary(h, east)


def test_overpriced_leg_is_declined():
    e, q = exposure(), quotes()
    # NO asks far above the market mid: 1 - mid is the fair NO price, so this overpays.
    q[0] = season.Quote(q[0].leg, q[0].market, q[0].series,
                        book(q[0].leg.ticker, [("0.60", 100000)], [("0.10", 100000)]))
    sp = season.plan(e, q)
    lp = next(lp for lp in sp.legs if lp.quote.leg.key == "playoffs")
    lp.fair = Decimal("0.10")  # pretend the model priced NO far below what the book asks
    h = season.leg_hedge(e, sp, lp, hedge_id="hdg_t_over", week_of=WEEK, now=NOW, agent="fallback",
                         remaining=Decimal("10000.00"), thresholds=Thresholds())
    assert h.status == "declined" and "overpriced" in h.decision.reasons
    assert h.decision.summary.startswith("Declined")


def test_group_total_is_the_sum_of_leg_premiums_on_every_leg():
    e, sp = exposure(), season.plan(exposure(), quotes())
    legs = [season.leg_hedge(e, sp, lp, hedge_id=f"hdg_g_{lp.quote.leg.key}", week_of=WEEK, now=NOW,
                             agent="fallback", remaining=Decimal("10000.00"), thresholds=Thresholds())
            for lp in sp.legs]
    out = season.with_group_total(legs)
    total = sum(h.premium for h in legs)
    assert {h.group_total_premium for h in out} == {total}
