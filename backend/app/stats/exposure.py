"""Exposure model, spec §5: one OLS per business on `train` rows, HC3 errors.

    revenue = α + Σ δ_d·DOW_d + Σ_k (a_k sin + b_k cos)(2πk·doy/365.25), k=1,2
              + γ·holiday + β·msg_event + β·home_game          (controls, never exposures)
              + β_w·home_win + β_r·rain + β_T·hot + ε           (hedgeable exposures)

Decisions:
- `hot = tmax > strike`, **strictly greater**. Kalshi KXHIGHNY pays only when the high is
  strictly above the strike, so the measured exposure must use the same flag the hedge
  settles on. This overrides the `>=` in spec §5 / issue #7.
- `hot` is fitted only when `strikes["hot"]` is given (the strike comes from the matched
  contract); otherwise it is left out of the model and the result.
- CI = β ± 1.645·se with HC3 se (normal, `use_t=False`, G9). Gates use the 2 dp Decimal
  values that are returned, so what is shown is what is judged.
- Money (`effect_usd`, `ci90`, `se`, `beta_settlement`) is Decimal 2 dp (CONTRACTS R1);
  `p_value` and `r2_*` stay floats and are always finite.
- A flag that is constant on train (e.g. never true) is dropped from the design and its
  exposure reported as 0 with every failing reason; non-finite stats become se 0, p 1.
- `estimated` propagates from the frame's `estimated` column (I6).

Pure: no I/O, no network, no DB.
"""

import math
from decimal import Decimal

import numpy as np
import pandas as pd
import statsmodels.api as sm
from pydantic import BaseModel, ConfigDict

from app.config import Thresholds, get_thresholds
from app.models import CENT, BasisStat, Event, Exposure, ModelCheck

Z90 = 1.645
COV_TYPE = "HC3"
EVENTS: tuple[Event, ...] = ("home_win", "rain", "hot")
CONTROLS = ("is_holiday", "msg_event", "home_game")
REASON_ORDER = ("below_size", "not_significant", "thin_support")
R2_PLACES = Decimal("0.0001")


class ExposureResult(BaseModel):
    """`fit_exposures` output (stats ACCEPTANCE §Produces). `model_check` is filled by the caller."""

    model_config = ConfigDict(extra="forbid")

    exposures: list[Exposure]
    dropped: list[Exposure]
    r2_train: float
    r2_holdout: float | None  # None when there are no holdout rows
    n_train: int
    n_holdout: int
    estimated: bool
    cov_type: str = COV_TYPE
    model_check: ModelCheck | None = None


def money(x: float) -> Decimal:
    return Decimal(repr(float(x))).quantize(CENT)


def event_flags(df: pd.DataFrame, strikes: dict[str, float] | None = None) -> dict[str, pd.Series]:
    """Hedgeable event flags as bool Series. `hot` only when a strike is given (strict `>`)."""
    strikes = strikes or {}
    flags = {"home_win": df["home_win"].astype(bool), "rain": df["rain"].astype(bool)}
    if strikes.get("hot") is not None:
        flags["hot"] = df["tmax"] > float(strikes["hot"])
    return flags


def build_design(
    df: pd.DataFrame, flags: dict[str, pd.Series], columns: pd.Index | None = None
) -> pd.DataFrame:
    """Regressors: const, DOW dummies (Monday base), season k=1,2, controls, then `flags`.

    Without `columns`, columns constant on `df` (other than const) are dropped, so
    degenerate flags never make the fit singular. With `columns` (a fitted design's), the
    same columns are returned unfiltered, for predicting on other rows. Callers may pass
    extra flags (e.g. modelcheck's `planted`).
    """
    X = pd.DataFrame(index=df.index)
    X["const"] = 1.0
    dow = df["dow"].astype(int)
    for d in range(1, 7):
        X[f"dow_{d}"] = (dow == d).astype(float)
    w = 2 * np.pi * df["doy"].astype(float) / 365.25
    for k in (1, 2):
        X[f"sin{k}"] = np.sin(k * w)
        X[f"cos{k}"] = np.cos(k * w)
    for c in CONTROLS:
        X[c] = df[c].astype(float)
    for name, flag in flags.items():
        X[name] = flag.astype(float)
    if columns is not None:
        return X[list(columns)]
    keep = [c for c in X.columns if c == "const" or X[c].nunique() > 1]
    # A control identical to an earlier column (e.g. msg_event == home_game when there
    # are no Dewey spikes) makes the design rank-deficient; drop the later copy. Flags
    # are never dropped this way.
    seen: list[str] = []
    for c in keep:
        if c in CONTROLS and any(X[c].equals(X[s]) for s in seen):
            continue
        seen.append(c)
    return X[seen]


def fit_ols(y: pd.Series, X: pd.DataFrame):
    """OLS with HC3 errors and normal inference (G9)."""
    return sm.OLS(y.astype(float), X).fit(cov_type=COV_TYPE, use_t=False)


def _coef(res, name: str) -> tuple[float, float, float]:
    """(beta, se, p) for `name`, 0/0/1 when absent or non-finite."""
    if name not in res.params.index:
        return 0.0, 0.0, 1.0
    b, se, p = float(res.params[name]), float(res.bse[name]), float(res.pvalues[name])
    if not math.isfinite(b):
        return 0.0, 0.0, 1.0
    if not (math.isfinite(se) and math.isfinite(p)):
        return b, 0.0, 1.0
    return b, se, p


def _r2(y: np.ndarray, yhat: np.ndarray) -> float:
    sst = float(((y - y.mean()) ** 2).sum())
    if sst == 0.0:
        return 0.0
    return 1.0 - float(((y - yhat) ** 2).sum()) / sst


def _exposure(
    event: str, b: float, se: float, p: float, n_events: int, business_id: str,
    strike: float | None, beta_s: Decimal | None, th: Thresholds,
) -> Exposure:
    effect, se_d = money(b), money(se)
    lo, hi = money(b - Z90 * se), money(b + Z90 * se)
    failed = {
        "below_size": abs(effect) < th.min_size_usd,
        "not_significant": not (lo > 0 or hi < 0),
        "thin_support": n_events < th.min_support,
    }
    reasons = [r for r in REASON_ORDER if failed[r]]
    positive = effect > 0
    return Exposure(
        id=f"exp_{event}",
        business_id=business_id,
        event=event,
        effect_usd=effect,
        ci90=(lo, hi),
        se=se_d,
        p_value=p,
        n_events_train=n_events,
        direction="positive" if positive else "negative",
        hedge_side="no" if positive else "yes",
        settlement_var=event,
        hedgeable=not reasons,
        reasons=reasons,
        strike=float(strike) if event == "hot" else None,
        beta_settlement=beta_s,
    )


def _train(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["split"] == "train"] if "split" in df.columns else df


def _estimated(df: pd.DataFrame) -> bool:
    return bool(df["estimated"].any()) if "estimated" in df.columns else False


def fit_exposures(
    df: pd.DataFrame,
    strikes: dict[str, float] | None = None,
    *,
    business_id: str | None = None,
    settle_flags: dict[str, pd.Series] | None = None,
    thresholds: Thresholds | None = None,
) -> ExposureResult:
    """Fit the §5 model on `train`, gate each exposure, score `r2_holdout` out of sample.

    `strikes`: `{"hot": °F}`; hot is `tmax > strike`. `business_id` defaults to
    `df.attrs["business_id"]`. `settle_flags` (event -> contract settlement flag aligned to
    `df`) fills each exposure's `beta_settlement` via `beta_settlement()`.
    """
    th = thresholds or get_thresholds()
    strikes = strikes or {}
    business_id = business_id or df.attrs.get("business_id", "unknown")
    train = _train(df)
    holdout = df[df["split"] == "holdout"] if "split" in df.columns else df.iloc[0:0]

    flags = event_flags(train, strikes)
    X = build_design(train, flags)
    res = fit_ols(train["revenue"], X)
    y = train["revenue"].to_numpy(float)
    r2_train = _r2(y, X.to_numpy(float) @ res.params.to_numpy(float))

    r2_holdout = None
    if len(holdout):
        Xh = build_design(holdout, event_flags(holdout, strikes), columns=X.columns)
        yh = holdout["revenue"].to_numpy(float)
        r2_holdout = _r2(yh, Xh.to_numpy(float) @ res.params.to_numpy(float))

    exposures, dropped = [], []
    for event, flag in flags.items():
        b, se, p = _coef(res, event)
        beta_s = None
        if settle_flags and event in settle_flags:
            beta_s = beta_settlement(df, settle_flags[event], event=event, strikes=strikes).beta_s
        exp = _exposure(event, b, se, p, int(flag.sum()), business_id, strikes.get("hot"), beta_s, th)
        (exposures if exp.hedgeable else dropped).append(exp)

    return ExposureResult(
        exposures=exposures,
        dropped=dropped,
        r2_train=r2_train,
        r2_holdout=r2_holdout,
        n_train=len(train),
        n_holdout=len(holdout),
        estimated=_estimated(df),
    )


def beta_settlement(
    df: pd.DataFrame,
    settle_flag: pd.Series,
    *,
    event: str = "rain",
    strikes: dict[str, float] | None = None,
) -> BasisStat:
    """β_S (G1): the §5 model on `train` with the contract's settlement flag replacing the
    `event` flag (same controls, HC3). `r2` = Pearson² between the business's event flag and
    the settlement flag on train (0 if either is constant)."""
    strikes = strikes or {}
    train = _train(df)
    settle = settle_flag.reindex(train.index).fillna(False).astype(bool)
    flags = event_flags(train, strikes)
    own = flags[event]
    flags[event] = settle
    res = fit_ols(train["revenue"], build_design(train, flags))
    b, se, _ = _coef(res, event)

    a, s = own.to_numpy(float), settle.to_numpy(float)
    r2 = 0.0 if a.std() == 0 or s.std() == 0 else float(np.corrcoef(a, s)[0, 1] ** 2)
    return BasisStat(
        r2=Decimal(repr(r2)).quantize(R2_PLACES),
        beta_s=money(b),
        se=money(se),
    )
