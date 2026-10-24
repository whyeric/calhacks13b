"""C3-A28: exposure -> candidates -> pick -> size -> evaluate, offline from the committed cache."""

import json
from datetime import datetime, timezone
from decimal import Decimal as D

from app.config import Thresholds
from app.markets.kalshi import KalshiClient
from app.markets.match import build_candidates, deterministic_pick
from app.markets.rules import evaluate, resolve_h, with_decision
from app.markets.shapes import BasisStat, Hedge
from app.markets.sizing import no_market_hedge, size_hedge
from tests.conftest import load

T0 = datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)  # cache warmed 23:10 UTC
TH = Thresholds(weekly_budget=D(250))
BASIS = {"taxi": BasisStat(r2=D("0.81"), beta_s=D("1240"), se=D("200")),
         "restaurant": BasisStat(r2=D("0.62"), beta_s=D("-700"), se=D("150"))}
P_HAT = D("0.27")


async def desk(exposure: dict) -> Hedge:
    basis = BASIS[exposure["business_id"]]
    async with KalshiClient(offline=True) as k:
        cands = await build_candidates(k, exposure, T0)
        pick = deterministic_pick(cands, exposure["hedge_side"])
        if pick is None:
            hedge = no_market_hedge(exposure)
        else:
            h = resolve_h(basis, D(exposure["effect_usd"]), TH) or D(1)
            series = await k.get_series(pick.series_ticker)
            hedge = size_hedge(exposure, pick, await k.get_orderbook(pick.ticker), h, P_HAT, series)
    return with_decision(hedge, evaluate(exposure, cands, hedge, basis, TH.weekly_budget, TH))


async def test_taxi_and_bar_rain_offline_and_deterministic():
    taxi = await desk(load("businesses/exposure_taxi_rain.json"))
    bar = await desk(load("businesses/exposure_bar_rain.json"))

    # The recorded book has no YES bids, so there is nothing to buy on NO: a real decline.
    assert (taxi.side, taxi.n_filled, taxi.status, taxi.decision.reasons) == ("no", 0, "declined", ["illiquid"])
    # Bar buys YES at 1¢, resized to h = 700/900 by the basis rule.
    assert (bar.side, bar.n_target, bar.resized, bar.status) == ("yes", 700, True, "proposed")
    assert bar.fills[0].price == D("0.01")

    for hd in (taxi, bar):
        dumped = json.loads(hd.model_dump_json())
        assert Hedge.model_validate(dumped) == hd
        assert isinstance(dumped["premium"], str) and isinstance(dumped["h"], str)
        assert len(hd.decision.checks) == 6

    again = await desk(load("businesses/exposure_bar_rain.json"))
    assert again.model_dump_json() == bar.model_dump_json()  # byte-identical replay
