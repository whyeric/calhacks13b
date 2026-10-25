"""C3-A28: exposure -> candidates -> pick -> size -> evaluate, offline from the committed cache."""

import json
from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest

from app.config import Thresholds
from app.markets.kalshi import KalshiClient
from app.markets.match import build_candidates, deterministic_pick
from app.markets.rules import evaluate, resolve_h
from app.markets.sizing import size_hedge, to_hedge
from app.models import BasisStat, Exposure, Hedge
from tests.conftest import load

T0 = datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)  # cache warmed 23:10 UTC (19:10 ET, Oct 24)
TH = Thresholds()
BUDGET = D("250.00")
BASIS = {"taxi": BasisStat(r2=D("0.81"), beta_s=D("1240"), se=D("200")),
         "restaurant": BasisStat(r2=D("0.62"), beta_s=D("-700"), se=D("150"))}


def p_hat_rain() -> D:
    # Central Park settle_rain frequency on train, from #20's feature table (scripts/settlement_rates.py).
    return D(load("settlement_rates.json")["rain"]["p_hat"])


async def desk(exposure: dict) -> Hedge:
    basis = BASIS[exposure["business_id"]]
    async with KalshiClient(offline=True) as k:
        cands = await build_candidates(k, exposure, T0)
        pick = deterministic_pick(cands, exposure["hedge_side"])
        sizing = None
        if pick is not None:
            h = resolve_h(basis, D(exposure["effect_usd"]), TH) or D(1)
            series = await k.get_series(pick.series_ticker)
            sizing = size_hedge(exposure, pick, await k.get_orderbook(pick.ticker), h, p_hat_rain(), series)
    decision = evaluate(exposure, cands, sizing, basis, BUDGET, TH)
    return to_hedge(exposure, sizing, decision, hedge_id=f"hdg_{exposure['business_id']}_rain",
                    week_of=date(2026, 10, 26), created_at=T0, agent="fallback")


async def test_taxi_and_bar_rain_offline_and_deterministic():
    taxi_exp, bar_exp = load("markets_test/exposure_taxi_rain.json"), load("markets_test/exposure_bar_rain.json")
    Exposure.model_validate(taxi_exp), Exposure.model_validate(bar_exp)
    taxi, bar = await desk(taxi_exp), await desk(bar_exp)

    # Same-day markets are skipped: at 19:00 ET on Oct 24 only the Oct 25 market is eligible.
    assert taxi.ticker == bar.ticker == "KXRAIN-26OCT25-NYC"
    # The recorded book has no YES bids, so there is nothing to buy on NO: a real decline.
    assert (taxi.side, taxi.n_filled, taxi.status, taxi.decision.reasons) == ("no", 0, "declined", ["illiquid"])
    # Bar buys YES at 1¢, resized to h = 700/900 by the basis rule.
    assert (bar.side, bar.n_target, bar.resized, bar.status) == ("yes", 700, True, "proposed")
    assert bar.fills[0].price == D("0.01") and bar.fair == D("0.3123")  # NOAA GHCN p̂ (Open-Meteo was 0.3973)
    overpriced = bar.decision.checks[2].model_dump(mode="json")["metric"]
    assert overpriced["overpay"] == "0.00"
    assert overpriced["note"] == "Market price reflects the current forecast; historical rate is 31%."
    assert bar.expected_cost == bar.fee  # never cheaper than its fee

    for hd in (taxi, bar):
        dumped = json.loads(hd.model_dump_json())
        assert Hedge.model_validate(dumped) == hd
        assert isinstance(dumped["premium"], (str, type(None))) and len(hd.decision.checks) == 7

    again = await desk(bar_exp)
    assert again.model_dump_json() == bar.model_dump_json()  # byte-identical replay


async def test_dropped_taxi_exposures_are_refused_never_proposed():
    """Taxi home_win and hot (fit on the CI feature table) fail the stats gates. Forced through
    the full pipeline they are refused before any check runs, so they can never come out proposed."""
    from app.markets.rules import NotHedgeableError
    from app.markets.summary import not_hedged_summary

    for name in ("exposure_taxi_home_win.json", "exposure_taxi_hot.json"):
        exposure = Exposure.model_validate(load(f"markets_test/{name}"))
        assert exposure.hedgeable is False and exposure.reasons == ["not_significant"]
        async with KalshiClient(offline=True) as k:
            cands = await build_candidates(k, exposure, T0)
            pick = deterministic_pick(cands, exposure.hedge_side)
            assert pick is not None  # a market exists, so only the gate stops it
            p_hat = D(load("settlement_rates.json")["home_win"]["p_hat"]) if exposure.event == "home_win" else D("0.4082")
            sizing = size_hedge(exposure, pick, await k.get_orderbook(pick.ticker), D(1), p_hat,
                                await k.get_series(pick.series_ticker))
        basis = None if exposure.event == "home_win" else BasisStat(r2=D("0.9233"), beta_s=D("-1273.68"), se=D("1473.67"))
        with pytest.raises(NotHedgeableError, match="not_significant.*not_hedgeable"):
            evaluate(exposure, cands, sizing, basis, BUDGET, TH)

    home_win = Exposure.model_validate(load("markets_test/exposure_taxi_home_win.json"))
    assert not_hedged_summary(home_win) == (
        "Not hedged: the measured effect (+$517/day) isn't distinguishable from zero "
        "(90% CI −$2,631 to +$3,665).")
