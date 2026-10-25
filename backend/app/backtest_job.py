"""The walk-forward backtest job (#10): compute and store `analysis(business, "backtest")`, which
`GET /businesses/{id}/backtest` serves.

Offline: reads the feature fixtures and `fixtures/kalshi_history/*.json`. `ensure()` stores the
backtest for every business whose data is available and skips the rest (e.g. the restaurant on
a fresh clone without the gitignored Dewey parquets). It runs from `make seed`
(`python -m scripts.run_backtest --if-missing`) and at API startup when the row is missing.

Settlement: the contract's own settled result (Kalshi `result`, which resolves on the NWS CLI
report for Central Park, i.e. NOAA) replaces the Open-Meteo `settle_rain` flag on every day a
market exists; other days keep the Open-Meteo station flag.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy.engine import Engine

from app import clock, config, db

log = logging.getLogger("hedge_desk.backtest")

HISTORY_DIR = config.FIXTURES_DIR / "kalshi_history"
RAIN_THRESHOLD_IN = 0.01  # KXRAIN/KXRAINNYC: "strictly greater than 0 in"; the gauge reports hundredths
CACHE_KEY = "backtest"

_MEMO: dict[tuple, object] = {}  # same inputs -> same result (tests and repeated startups)


def _history(var: str) -> dict:
    path = HISTORY_DIR / f"{var}.json"
    return json.loads(path.read_text()) if path.exists() else {"markets": {}}


def frame(business_id: str, strike: float | None, fixtures_dir: Path) -> tuple[pd.DataFrame, dict, dict]:
    from app.data import features
    from app.stats.backtest import quotes_from_history

    df = features.build(business_id, fixtures_dir=fixtures_dir)
    df = features.add_settlement(df, rain_threshold=RAIN_THRESHOLD_IN, strike=strike, fixtures_dir=fixtures_dir)
    df.attrs["business_id"] = business_id
    quotes, notes = {}, {}
    dates = pd.to_datetime(df["date"]).dt.date
    for var, col in (("rain", "settle_rain"), ("home_win", "home_win")):
        q, results = quotes_from_history(_history(var))
        quotes[var] = q
        official = dates.map(results)
        have = official.notna()
        disagree = int((official[have].astype(bool) != df.loc[have, col]).sum())
        notes[var] = {"days_with_market": int(have.sum()), "disagree_with_repo_flag": disagree}
        if var == "rain" and have.any():
            df.loc[have, col] = official[have].astype(bool)  # settle on what the contract settled on
    return df, quotes, notes


def backtest(business_id: str, strike: float | None, fixtures_dir: Path, markup: Decimal, real: bool = True,
             engine: Engine | None = None):
    """(simulation run, train fit, settlement notes). Raises FileNotFoundError/ValueError when the
    business's data is missing."""
    from app.stats.backtest import BacktestConfig, default_contracts, simulate
    from app.stats.exposure import fit_exposures

    df, quotes, notes = frame(business_id, strike, fixtures_dir)
    strikes = {"hot": strike} if strike is not None else None
    th = db.get_business_thresholds(business_id, engine)
    fit = fit_exposures(df, strikes, business_id=business_id, thresholds=th)
    contracts = default_contracts(quotes if real else None)
    cfg = BacktestConfig(thresholds=th, markup=markup, strikes=strikes)
    return simulate(df, contracts, fit, cfg), fit, notes


def _inputs_key(business_id: str, fixtures_dir: Path, engine: Engine | None) -> tuple:
    th = db.get_business_thresholds(business_id, engine)
    files = sorted(p for p in [*fixtures_dir.glob("*.parquet"), *fixtures_dir.glob("*.csv"), *HISTORY_DIR.glob("*.json")])
    return (business_id, str(fixtures_dir), th, tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files))


def ensure(
    business_ids: list[str] | tuple[str, ...] | None = None, *, force: bool = False,
    fixtures_dir: Path = config.FIXTURES_DIR, engine: Engine | None = None,
) -> dict[str, str]:
    """Store the backtest for each business that has data. Returns {business_id: outcome}, where
    outcome is "stored", "exists" (already stored, `force=False`) or "skipped: <reason>"."""
    from app.data import features

    out: dict[str, str] = {}
    for b in business_ids or features.BUSINESSES:
        if not force and db.get_analysis(b, CACHE_KEY, engine) is not None:
            out[b] = "exists"
            continue
        try:
            key = _inputs_key(b, fixtures_dir, engine)
            result = _MEMO.get(key)
            if result is None:
                run, _fit, _notes = backtest(b, None, fixtures_dir, config.FALLBACK_MARKUP, engine=engine)
                result = _MEMO[key] = run.result
        except (FileNotFoundError, ValueError) as e:
            out[b] = f"skipped: {e}"
            log.info("backtest for %s skipped: %s", b, e)
            continue
        db.put_analysis(b, CACHE_KEY, result, clock.now().isoformat(), engine)
        out[b] = "stored"
    return out
