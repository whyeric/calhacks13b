"""Compute the walk-forward backtest (#10) and cache it so `GET /businesses/{id}/backtest` serves it.

    cd backend && .venv/bin/python -m scripts.run_backtest                  # taxi + restaurant, stored
    cd backend && .venv/bin/python -m scripts.run_backtest taxi --strike 85 --no-store
    cd backend && .venv/bin/python -m scripts.run_backtest --sweep          # + markup stress sweep

Offline: reads the feature fixtures and `fixtures/kalshi_history/*.json` (refresh those with
`python -m scripts.kalshi_history`). Writes only the db row `analysis(business, "backtest")`.

Settlement: the contract's own settled result (Kalshi `result`, which resolves on the NWS CLI
report for Central Park, i.e. NOAA) replaces the Open-Meteo `settle_rain` flag on every day a
market exists; other days keep the Open-Meteo station flag. The printout says how often the two
disagree, because the repo's weather pipeline is still Open-Meteo, not NOAA.
"""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
from pathlib import Path

from app import clock, config, db
from app.data import features
from app.models import BacktestResult
from app import backtest_job
from app.backtest_job import CACHE_KEY, HISTORY_DIR, RAIN_THRESHOLD_IN, backtest, frame  # noqa: F401 (re-exported)


def _print(business_id: str, run, fit, notes) -> None:
    r: BacktestResult = run.result
    print(f"\n=== {business_id}  (estimated={r.estimated}, tier={r.pricing_tier}, priced_real_pct={r.priced_real_pct})")
    print("train fit:", ", ".join(f"{e.id} {e.effect_usd} [{e.ci90[0]}, {e.ci90[1]}] {'hedgeable' if e.hedgeable else 'dropped ' + '/'.join(e.reasons)}"
                                  for e in fit.exposures + fit.dropped))
    print("monthly refits:", " ".join(
        f"{f.start:%Y-%m}:" + (",".join(f"{e.event}{'+' if e.effect_usd > 0 else '-'}" for e in f.exposures) or "none")
        for f in run.fits))
    print(f"settlement source: {notes}")
    print(f"weeks={len(r.weekly)} std_unhedged={r.std_unhedged} std_hedged={r.std_hedged} reduction_pct={r.reduction_pct}")
    print(f"n_hedges={r.n_hedges} n_declined={r.n_declined} by_reason={run.declined_by_reason} skipped={run.skipped}")
    pnl = sum((d.pnl for d in run.days), Decimal(0))
    payout = sum((d.payout for d in run.days if d.hedged), Decimal(0))
    print(f"total_premium={r.total_premium} payouts={payout} net_pnl={pnl}")
    print(f"worst week {r.worst_week_unhedged.week_start}: unhedged {r.worst_week_unhedged.income} -> hedged {r.worst_week_hedged.income}")
    for eid, pe in r.per_exposure.items():
        tiers = Counter(d.priced_real for d in run.days if d.exposure_id == eid)
        print(f"  {eid}: reduction {pe.reduction_pct}% premium {pe.total_premium} ineffective={pe.ineffective} "
              f"real-priced days {tiers[True]}/{tiers[True] + tiers[False]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("business", nargs="*", default=list(features.BUSINESSES))
    ap.add_argument("--strike", type=float, default=None, help="hot strike in °F (default: no hot exposure)")
    ap.add_argument("--markup", type=Decimal, default=config.FALLBACK_MARKUP)
    ap.add_argument("--fixtures-dir", type=Path, default=config.FIXTURES_DIR)
    ap.add_argument("--no-store", action="store_true")
    ap.add_argument("--if-missing", action="store_true",
                    help="only store businesses with no stored backtest, quietly (used by `make seed`)")
    ap.add_argument("--sweep", action="store_true", help="also print the frequency-tier markup stress sweep (G2)")
    args = ap.parse_args()
    db.create_schema()  # per-business threshold overrides are read from the db
    if args.if_missing:
        for b, outcome in backtest_job.ensure(args.business, fixtures_dir=args.fixtures_dir).items():
            print(f"backtest {b}: {outcome}")
        return
    for b in args.business:
        try:
            run, fit, notes = backtest(b, args.strike, args.fixtures_dir, args.markup)
        except (FileNotFoundError, ValueError) as e:
            print(f"\n=== {b}: skipped ({e})")
            continue
        _print(b, run, fit, notes)
        if args.sweep:
            for m in ("0.02", "0.10", "0.20"):
                s, _, _ = backtest(b, args.strike, args.fixtures_dir, Decimal(m), real=False)
                print(f"  sweep markup {m} (frequency tier): reduction {s.result.reduction_pct}% hedges {s.result.n_hedges} "
                      f"declined {s.result.n_declined} {s.declined_by_reason} premium {s.result.total_premium}")
        if not args.no_store:
            db.put_analysis(b, CACHE_KEY, run.result, clock.now().isoformat())
            print(f"stored analysis({b!r}, {CACHE_KEY!r})")


if __name__ == "__main__":
    main()
