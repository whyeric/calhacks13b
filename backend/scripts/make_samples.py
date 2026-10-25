"""Regenerate fixtures/samples/{hedge,decision}_*.json from the real sizing/rules code.

    cd backend && python -m scripts.make_samples

Offline only. Exposure numbers are illustrative (C2 owns the real ones). The proposed,
pending and no_market samples use the committed Kalshi cache; declined and partial use
hand-built books so they hit specific rules.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

from app.config import Thresholds
from app.markets.kalshi import KalshiClient, parse_orderbook
from app.markets.match import build_candidates, deterministic_pick
from app.markets.rules import evaluate, resolve_h, with_decision
from app.markets.shapes import BasisStat
from app.markets.sizing import no_market_hedge, size_hedge

OUT = Path(__file__).resolve().parents[2] / "fixtures" / "samples"
NOW = datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)
TH = Thresholds(weekly_budget=D(250))
STD_FEE = {"fee_type": "quadratic", "fee_multiplier": "1"}


def exp(id_, business, var, beta, side):
    return {"id": id_, "business_id": business, "settlement_var": var, "effect_usd": beta, "hedge_side": side}


async def live(k, exposure, basis, p_hat, remaining, now=NOW):
    cands = await build_candidates(k, exposure, now)
    pick = deterministic_pick(cands, exposure["hedge_side"])
    if pick is None:
        hedge = no_market_hedge(exposure)
    else:
        h = resolve_h(basis, D(exposure["effect_usd"]), TH) or D(1)
        hedge = size_hedge(exposure, pick, await k.get_orderbook(pick.ticker), h, p_hat,
                           await k.get_series(pick.series_ticker))
        hedge = hedge.model_copy(update={"match_reason": "Deepest NYC book closing this week.", "agent": "fallback"})
    return with_decision(hedge, evaluate(exposure, cands, hedge, basis, remaining, TH))


async def built(exposure, asks, basis, p_hat, remaining, ticker, cand_from):
    # Hand-built ladder on the hedge side: bids on the opposite side at 1 − ask.
    opp = "no_dollars" if exposure["hedge_side"] == "yes" else "yes_dollars"
    book = parse_orderbook(ticker, {"orderbook_fp": {opp: [[str(1 - D(p)), str(n)] for p, n in asks]}}, NOW)
    cand = cand_from.model_copy(update={"ticker": ticker})
    h = resolve_h(basis, D(exposure["effect_usd"]), TH) or D(1)
    hedge = size_hedge(exposure, cand, book, h, p_hat, STD_FEE)
    hedge = hedge.model_copy(update={"match_reason": "Illustrative book.", "agent": "fallback"})
    return with_decision(hedge, evaluate(exposure, [cand], hedge, basis, remaining, TH))


async def main() -> None:
    bar_rain = exp("exp_rain", "restaurant", "rain", "-900.00", "yes")
    rain_basis = BasisStat(r2=D("0.62"), beta_s=D("-700"), se=D("150"))
    full_basis = BasisStat(r2=D("0.81"), beta_s=D("-900"), se=D("120"))
    async with KalshiClient(offline=True) as k:
        samples = {
            "proposed": await live(k, bar_rain, rain_basis, D("0.27"), D(250)),
            "pending": await live(k, exp("exp_home_win", "restaurant", "home_win", "-500.00", "yes"),
                                  None, D("0.50"), D(250)),
            # A week on, every cached temperature market has closed: an empty candidate list.
            "no_market": await live(k, exp("exp_hot", "taxi", "hot", "300.00", "yes"),
                                    BasisStat(r2=D("0.9"), beta_s=D("300"), se=D("80")), D("0.1"), D(250),
                                    now=NOW + timedelta(days=7)),
        }
        rain_cand = (await build_candidates(k, bar_rain, NOW))[0]
    samples["declined"] = await built(bar_rain, [("0.62", 2000)], full_basis, D("0.27"), D(1000),
                                      "KXRAIN-26OCT25-NYC", rain_cand)
    samples["partial"] = await built(exp("exp_rain", "restaurant", "rain", "-100.00", "yes"),
                                     [("0.20", 40), ("0.22", 30), ("0.30", 100)], full_basis, D("0.27"), D(250),
                                     "KXRAIN-26OCT25-NYC", rain_cand)

    OUT.mkdir(parents=True, exist_ok=True)
    for name, hedge in samples.items():
        dumped = json.loads(hedge.model_dump_json())
        (OUT / f"hedge_{name}.json").write_text(json.dumps(dumped, indent=2) + "\n")
        (OUT / f"decision_{name}.json").write_text(json.dumps(dumped["decision"], indent=2) + "\n")
        print(f"{name:10} {hedge.status:17} reasons={hedge.decision.reasons} partial={hedge.partial}")


if __name__ == "__main__":
    asyncio.run(main())
