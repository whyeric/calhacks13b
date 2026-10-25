"""Planted-effect model check, spec §5.1 (CONTRACTS R6 shape).

Copy the real `train` series, add a known effect on a random share of days,
refit with a `planted` indicator as an extra regressor (alongside every
original one, including the real event flag), and report how often the 90%
CI contains the truth across seeds. Pure: no I/O, never the global RNG.
"""

from decimal import Decimal

import numpy as np
import pandas as pd

from app.models import ModelCheck, ModelCheckExample
from app.stats.exposure import Z90, _train, build_design, event_flags, fit_ols
from app.stats.exposure import money as _money

TARGET = 0.90


def planted_fit(train: pd.DataFrame, seed: int, effect: float = 500, frac: float = 0.15,
                strikes: dict[str, float] | None = None, event: str = "rain"):
    """One seed: plant `effect` on round(frac·n) random train days and refit OLS/HC3.

    Same design and fit as `fit_exposures` (`build_design`/`fit_ols`) plus a last
    `planted` column. Returns the statsmodels result; `train` is not mutated.
    """
    n = len(train)
    k = int(round(frac * n))
    if k < 1 or k >= n:
        raise ValueError(f"frac={frac} plants {k} of {n} train days; need 1..n-1")
    rng = np.random.default_rng(seed)
    planted = np.zeros(n)
    planted[rng.choice(n, size=k, replace=False)] = 1.0

    flags = event_flags(train, strikes)
    if event not in flags:
        raise ValueError(f"event {event!r} not in the design (hot needs strikes['hot'])")
    flags["planted"] = pd.Series(planted, index=train.index)
    X = build_design(train, flags)
    y = train["revenue"].astype(float) + effect * planted
    return fit_ols(y, X)


def _recovered(res) -> tuple[Decimal, Decimal, Decimal]:
    beta = float(res.params["planted"])
    se = float(res.bse["planted"])
    return _money(beta), _money(beta - Z90 * se), _money(beta + Z90 * se)


def run_model_check(df: pd.DataFrame, event: str = "rain", n_seeds: int = 50, effect: float = 500,
                    frac: float = 0.15, strikes: dict[str, float] | None = None) -> ModelCheck:
    """Seeds are 0..n_seeds-1; the example is seed 0.

    `event` names the exposure the check is reported against (G11: `rain`); the
    real event flag stays in the design as an ordinary regressor.
    """
    if n_seeds < 1:
        raise ValueError("n_seeds must be >= 1")
    train = _train(df)
    truth = _money(effect)
    rows = []
    for seed in range(n_seeds):
        rec, lo, hi = _recovered(planted_fit(train, seed, effect, frac, strikes, event))
        # Decided on the 2dp values so contains_truth always agrees with the reported ci90.
        rows.append((seed, rec, lo, hi, lo <= truth <= hi))

    seed, rec, lo, hi, ok = rows[0]
    return ModelCheck(
        planted_usd=truth,
        frac=frac,
        n_seeds=n_seeds,
        example=ModelCheckExample(seed=seed, recovered=rec, ci90=(lo, hi), contains_truth=ok),
        coverage=sum(r[4] for r in rows) / n_seeds,
        mean_recovered=_money(np.mean([float(r[1]) for r in rows])),
        target=TARGET,
    )
