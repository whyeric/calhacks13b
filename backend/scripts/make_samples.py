"""Regenerate fixtures/samples/{hedge,decision}_*.json from the real sizing/rules code.

    cd backend && python -m scripts.make_samples

Offline only. Exposure and basis numbers are illustrative (C2 owns the real ones); p̂ comes from
fixtures/settlement_rates.json (#20's feature table). The proposed, pending and no_market samples
use the committed Kalshi cache; declined and partial use hand-built books to hit specific rules.
"""

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

from app.config import FIXTURES_DIR, Thresholds
from app.markets.kalshi import KalshiClient, parse_orderbook
from app.markets.match import build_candidates, deterministic_pick
from app.markets.rules import evaluate, resolve_h
from app.markets.sizing import size_hedge, to_hedge
from app.models import BasisStat, Hedge

OUT = FIXTURES_DIR / "samples"
NOW = datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)
WEEK_OF = date(2026, 10, 26)
TH = Thresholds()
BUDGET = D("250.00")
STD_FEE = {"fee_type": "quadratic", "fee_multiplier": "1"}
RATES = json.loads((FIXTURES_DIR / "settlement_rates.json").read_text())


def exp(id_, business, var, beta, side):
    return {"id": id_, "business_id": business, "settlement_var": var, "effect_usd": beta, "hedge_side": side}


def p_hat(var: str) -> D:
    return D(RATES[var]["p_hat"])


def finish(name, exposure, cands, sizing, basis, remaining=BUDGET):
    decision = evaluate(exposure, cands, sizing, basis, remaining, TH, decision_id=f"dec_sample_{name}")
    return to_hedge(exposure, sizing, decision, hedge_id=f"hdg_sample_{name}", week_of=WEEK_OF,
                    created_at=NOW, agent="fallback",
                    match_reason=None if sizing is None else "Deepest eligible book closing this week.")


async def live(k, name, exposure, basis, now=NOW, remaining=BUDGET):
    cands = await build_candidates(k, exposure, now)
    pick = deterministic_pick(cands, exposure["hedge_side"])
    sizing = None
    if pick is not None:
        h = resolve_h(basis, D(exposure["effect_usd"]), TH) or D(1)
        sizing = size_hedge(exposure, pick, await k.get_orderbook(pick.ticker), h,
                            p_hat(exposure["settlement_var"]), await k.get_series(pick.series_ticker))
    return finish(name, exposure, cands, sizing, basis, remaining)


def built(name, exposure, asks, basis, cand, remaining=BUDGET):
    # Hand-built ladder on the hedge side: bids on the opposite side at 1 − ask.
    opp = "no_dollars" if exposure["hedge_side"] == "yes" else "yes_dollars"
    book = parse_orderbook(cand.ticker, {"orderbook_fp": {opp: [[str(1 - D(p)), str(n)] for p, n in asks]}}, NOW)
    h = resolve_h(basis, D(exposure["effect_usd"]), TH) or D(1)
    sizing = size_hedge(exposure, cand, book, h, p_hat(exposure["settlement_var"]), STD_FEE)
    return finish(name, exposure, [cand], sizing, basis, remaining)


async def main() -> None:
    bar_rain = exp("exp_rain", "restaurant", "rain", "-900.00", "yes")
    rain_basis = BasisStat(r2=D("0.62"), beta_s=D("-700"), se=D("150"))
    full_basis = BasisStat(r2=D("0.81"), beta_s=D("-900"), se=D("120"))
    async with KalshiClient(offline=True) as k:
        samples = {
            "proposed": await live(k, "proposed", bar_rain, rain_basis),
            "pending": await live(k, "pending", exp("exp_home_win", "restaurant", "home_win", "-500.00", "yes"), None),
            # A week on, every cached temperature market has closed: an empty candidate list.
            "no_market": await live(k, "no_market", exp("exp_hot", "taxi", "hot", "300.00", "no"),
                                    BasisStat(r2=D("0.9"), beta_s=D("300"), se=D("80")), now=NOW + timedelta(days=7)),
        }
        rain_cand = (await build_candidates(k, bar_rain, NOW))[0]
    samples["declined"] = built("declined", bar_rain, [("0.80", 2000)], full_basis, rain_cand, remaining=D("1000.00"))
    samples["partial"] = built("partial", exp("exp_rain", "restaurant", "rain", "-100.00", "yes"),
                               [("0.20", 40), ("0.22", 30), ("0.30", 100)], full_basis, rain_cand)

    OUT.mkdir(parents=True, exist_ok=True)
    for name, hedge in samples.items():
        dumped = json.loads(hedge.model_dump_json())
        Hedge.model_validate(dumped)
        (OUT / f"hedge_{name}.json").write_text(json.dumps(dumped, indent=2) + "\n")
        (OUT / f"decision_{name}.json").write_text(json.dumps(dumped["decision"], indent=2) + "\n")
        print(f"{name:10} {hedge.status:17} reasons={hedge.decision.reasons} partial={hedge.partial} "
              f"ticker={hedge.ticker}")


if __name__ == "__main__":
    asyncio.run(main())
