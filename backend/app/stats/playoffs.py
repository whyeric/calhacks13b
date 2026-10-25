"""Playoff home-game exposure: $ per unscheduled playoff home game at MSG (experiments r5).

Game *results* don't move nearby revenue; playoff *dates* do. A playoff home night lifts foot
traffic within 0.5 km of MSG by about 6%, more than double a regular home night, in every season
Dewey covers. The bar's own daily series has about 18 playoff nights in the window and too much
day-to-day noise to measure that alone, so the exposure is a class rating (experiments
r2-pooling): the pooled near-MSG uplift from `fixtures/playoff_uplift.json` (summary numbers only,
D2; rebuilt by `scripts/playoff_uplift.py`) applied to this bar's baseline night. The bar's own
fit is reported next to it in `basis_note` as a check, not used for the size.

    effect_usd = expm1(β_pooled) × mean revenue on days without an MSG home game

`expected_count` is the market-implied number of playoff home games this season (from the
season futures, `app.markets.season`), or None when no prices are available. The exposure is
always `estimated: true` (I6).

Pure apart from reading the fixture: no network, no DB.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

from app.config import FIXTURES_DIR, Thresholds, get_thresholds
from app.models import CENT, Exposure

UPLIFT_FIXTURE = "playoff_uplift.json"
EVENT = "playoff_home"
EXPOSURE_ID = f"exp_{EVENT}"
Z90 = 1.645


@dataclass(frozen=True)
class Pooled:
    """The committed summary of the near-MSG Dewey fit (no daily series)."""

    beta_log: float
    se_log: float
    p_value: float
    n_games: int
    n_stores: int | None
    window: tuple[str, str]
    regular_pct: float | None

    @property
    def pct(self) -> float:
        return math.expm1(self.beta_log)

    def ci_pct(self) -> tuple[float, float]:
        return math.expm1(self.beta_log - Z90 * self.se_log), math.expm1(self.beta_log + Z90 * self.se_log)


@dataclass(frozen=True)
class OwnFit:
    """The bar's own series, for the basis note: noisy by construction."""

    pct: float
    ci_pct: tuple[float, float]
    p_value: float
    n_games: int


def load_pooled(fixtures_dir: Path = FIXTURES_DIR) -> Pooled:
    path = fixtures_dir / UPLIFT_FIXTURE
    if not path.exists():
        raise FileNotFoundError(f"pooled playoff uplift missing: {path} (run scripts/playoff_uplift.py)")
    d = json.loads(path.read_text())
    return Pooled(beta_log=float(d["beta_log"]), se_log=float(d["se_log"]), p_value=float(d["p_value"]),
                  n_games=int(d["n_playoff_home_games"]), n_stores=d.get("n_stores"),
                  window=tuple(d["window"]), regular_pct=d.get("regular_uplift_pct"))


def daily_flags(games: pd.DataFrame, dates) -> pd.DataFrame:
    """Per date: `po_home` (a playoff game at MSG) and `reg_home` (a regular-season MSG game and no
    playoff game that day). `games` has the `fixtures/msg_games_playoffs.csv` schema."""
    home = games[games["home"].astype(bool)]
    po = set(home.loc[home["playoff"].astype(bool), "date"])
    reg = set(home.loc[~home["playoff"].astype(bool), "date"]) - po
    idx = pd.Index(list(dates))
    return pd.DataFrame({"date": idx, "po_home": idx.isin(po), "reg_home": idx.isin(reg)})


def flags(df: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """`po_home` / `reg_home` aligned to the feature table's rows."""
    return daily_flags(games, df["date"]).set_index(df.index)


def baseline(df: pd.DataFrame, f: pd.DataFrame) -> float:
    """Mean daily revenue on days with no MSG home game (the base the uplift multiplies)."""
    quiet = ~(f["po_home"] | f["reg_home"] | df["home_game"].astype(bool))
    return float(df.loc[quiet, "revenue"].mean())


def own_fit(df: pd.DataFrame, f: pd.DataFrame) -> OwnFit | None:
    """log(revenue) on playoff/regular home nights, DOW, year-month FE, holiday and rain, HAC(7)."""
    n = int(f["po_home"].sum())
    if n == 0:
        return None
    y = np.log(df["revenue"].clip(lower=1.0).astype(float))
    ts = pd.to_datetime(df["date"])
    X = pd.get_dummies(ts.dt.day_of_week, prefix="dow", drop_first=True)
    X = X.join(pd.get_dummies(ts.dt.strftime("%Y%m"), prefix="ym", drop_first=True))
    X.insert(0, "const", 1.0)
    X["holiday"] = df["is_holiday"].astype(float)
    X["rain"] = df["rain"].astype(float)
    X["reg"] = f["reg_home"].astype(float)
    X["po"] = f["po_home"].astype(float)
    X = X.astype(float)
    X = X.loc[:, (X.nunique() > 1) | (X.columns == "const")]
    res = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)
    b, se = float(res.params["po"]), float(res.bse["po"])
    p = float(res.pvalues["po"])
    return OwnFit(pct=math.expm1(b), ci_pct=(math.expm1(b - Z90 * se), math.expm1(b + Z90 * se)),
                  p_value=p if math.isfinite(p) else 1.0, n_games=n)


def _money(x: float) -> Decimal:
    return Decimal(repr(float(x))).quantize(CENT)


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def basis_note(pooled: Pooled, base: float, own: OwnFit | None, expected_count: float | None) -> str:
    lo, hi = pooled.ci_pct()
    stores = f"{pooled.n_stores} " if pooled.n_stores else ""
    parts = [
        f"Estimated (class rating): playoff home nights lift foot traffic at the {stores}Dewey restaurants and bars "
        f"within 0.5 km of MSG by {_pct(pooled.pct)} (90% CI {_pct(lo)} to {_pct(hi)}, {pooled.n_games} playoff "
        f"home games, {pooled.window[0][:4]} to {pooled.window[1][:4]}), applied to this bar's ${base:,.0f} "
        "average night without an MSG game.",
    ]
    if own is not None:
        parts.append(
            f"The bar's own series alone gives {_pct(own.pct)} (90% CI {_pct(own.ci_pct[0])} to "
            f"{_pct(own.ci_pct[1])}) over {own.n_games} playoff home nights: too noisy to size a hedge on.")
    if expected_count is not None:
        parts.append(f"Expected playoff home games this season: {expected_count:.1f}, from Kalshi season "
                     "futures (make playoffs, East, title) through a series model.")
    else:
        parts.append("No season futures prices available, so the expected number of home games is unknown.")
    return " ".join(parts)


def measure(
    df: pd.DataFrame,
    *,
    business_id: str,
    games: pd.DataFrame,
    pooled: Pooled | None = None,
    expected_count: float | None = None,
    thresholds: Thresholds | None = None,
    fixtures_dir: Path = FIXTURES_DIR,
) -> Exposure:
    """The `playoff_home` Exposure for a business next to MSG.

    `df` is its feature table; `games` is `app.data.playoffs.read_games()` (ESPN, with playoff flags)."""
    th = thresholds or get_thresholds()
    pooled = pooled or load_pooled(fixtures_dir)
    f = flags(df, games)
    base = baseline(df, f)
    lo_pct, hi_pct = pooled.ci_pct()
    effect = _money(pooled.pct * base)
    lo, hi = _money(lo_pct * base), _money(hi_pct * base)
    se = _money(pooled.se_log * math.exp(pooled.beta_log) * base)  # delta method on expm1
    failed = {
        "below_size": abs(effect) < th.min_size_usd,
        "not_significant": not (lo > 0 or hi < 0),
        "thin_support": pooled.n_games < th.min_support,
    }
    reasons = [r for r in ("below_size", "not_significant", "thin_support") if failed[r]]
    positive = effect > 0
    return Exposure(
        id=EXPOSURE_ID, business_id=business_id, event=EVENT, effect_usd=effect, ci90=(lo, hi), se=se,
        p_value=pooled.p_value, n_events_train=pooled.n_games,
        direction="positive" if positive else "negative", hedge_side="no" if positive else "yes",
        settlement_var=EVENT, hedgeable=not reasons, reasons=reasons, strike=None, beta_settlement=None,
        expected_count=None if expected_count is None else round(float(expected_count), 2),
        estimated=True, basis_note=basis_note(pooled, base, own_fit(df, f), expected_count),
    )


__all__ = ["EVENT", "EXPOSURE_ID", "OwnFit", "Pooled", "baseline", "daily_flags", "load_pooled", "measure", "own_fit"]
