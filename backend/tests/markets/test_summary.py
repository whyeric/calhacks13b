"""Deterministic fallback summaries: one sentence per decline reason, numbers from the metrics."""

import json
from datetime import date, datetime, timezone
from decimal import Decimal as D

from app.config import Thresholds
from app.markets.kalshi import KalshiClient
from app.markets.match import build_candidates, deterministic_pick
from app.markets.rules import evaluate, resolve_h
from app.markets.sizing import size_hedge, to_hedge
from app.markets.summary import not_hedged_summary
from app.models import BasisStat, Hedge
from tests.conftest import FIXTURES, load

T0 = datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)
TH = Thresholds()

TAXI_RAIN = {  # the taxi's fitted rain exposure on the CI feature table
    "id": "exp_rain", "business_id": "taxi", "event": "rain", "effect_usd": "2011.70",
    "ci90": ["312.63", "3710.77"], "se": "1033.00", "p_value": 0.0515, "n_events_train": 148,
    "direction": "positive", "hedge_side": "no", "settlement_var": "rain", "hedgeable": True,
    "reasons": [], "strike": None, "beta_settlement": "1122.97",
}


async def test_taxi_rain_illiquid_sentence():
    basis = BasisStat(r2=D("0.8158"), beta_s=D("1122.97"), se=D("1049.90"))
    async with KalshiClient(offline=True) as k:
        cands = await build_candidates(k, TAXI_RAIN, T0)
        pick = deterministic_pick(cands, "no")
        sizing = size_hedge(TAXI_RAIN, pick, await k.get_orderbook(pick.ticker),
                            resolve_h(basis, D("2011.70"), TH), D(load("settlement_rates.json")["rain"]["p_hat"]),
                            await k.get_series(pick.series_ticker))
    d = evaluate(TAXI_RAIN, cands, sizing, basis, D("250.00"), TH)
    hedge = to_hedge(TAXI_RAIN, sizing, d, hedge_id="h", week_of=date(2026, 10, 26), created_at=T0, agent="fallback")
    assert hedge.decision.summary == (
        "Declined: nobody is selling NO on NYC rain for Oct 25, so 0 of 1,123 contracts could be bought.")


def _sample(name: str) -> Hedge:
    return Hedge.model_validate(json.loads((FIXTURES / f"samples/hedge_{name}.json").read_text()))


def test_sentence_per_reason_from_samples():
    assert _sample("declined").decision.summary == (
        "Declined: YES on NYC rain for Oct 25 costs 80¢ a contract, 40.27¢ more than its historical "
        "fair price of 39.73¢. Also, the hedge is expected to cost $372.51 to remove a $900.00 swing, "
        "41% of what it protects.")
    assert _sample("pending").decision.summary == (
        "Waiting for your approval: the $298.43 premium is more than the $250.00 left in this week's budget.")
    assert _sample("no_market").decision.summary == (
        "Declined: there is no open Kalshi market for an NYC hot day this week, so there is nothing to buy.")
    assert _sample("proposed").decision.summary is None  # only declines and pauses get a fallback


def test_claude_summary_is_never_overwritten():
    exposure = load("markets_test/exposure_bar_rain.json")
    basis = BasisStat(r2=D("0.62"), beta_s=D("-700"), se=D("150"))
    d = evaluate(exposure, [], None, basis, D("250.00"), TH)
    hedge = to_hedge(exposure, None, d, hedge_id="h", week_of=date(2026, 10, 26), created_at=T0, agent="fallback")
    assert hedge.decision.summary.startswith("Declined: there is no open Kalshi market for NYC rain")
    written = to_hedge(exposure, None, d.model_copy(update={"summary": "Claude's words."}),
                       hedge_id="h", week_of=date(2026, 10, 26), created_at=T0, agent="claude")
    assert written.decision.summary == "Claude's words."


def test_not_hedged_reasons():
    e = load("markets_test/exposure_taxi_hot.json")
    assert not_hedged_summary(e) == (
        "Not hedged: the measured effect (−$1,244/day) isn't distinguishable from zero "
        "(90% CI −$3,613 to +$1,125).")
    small = e | {"effect_usd": "-90.00", "ci90": ["-120.00", "-60.00"], "n_events_train": 6,
                 "reasons": ["below_size", "thin_support"]}
    assert not_hedged_summary(small) == (
        "Not hedged: the measured effect (−$90/day) is smaller than the $150/day worth hedging. "
        "Also, only 6 hot days in the training year, fewer than the 10 needed to measure it.")
