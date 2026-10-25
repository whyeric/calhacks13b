"""Seeded synthetic feature tables (spec §4.4 columns + `split`) with known effects.

Revenue is built from DOW + two-harmonic season + holiday + controls (`msg_event`,
`home_game`) + the hedgeable effects `β_win·home_win + β_rain·rain + β_hot·hot` + noise,
where `hot = tmax > hot_strike` (strict, as KXHIGHNY settles). Everything is in memory;
each call uses its own `numpy.random.default_rng(seed)` and never the global RNG.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

COLUMNS = [
    "date", "revenue", "dow", "doy", "is_holiday", "msg_event", "home_game", "home_win",
    "rain", "rain_open_hours", "tmax", "estimated", "split",
]
DOW_EFFECT = np.array([-500.0, -300.0, 0.0, 200.0, 800.0, 1200.0, 400.0])  # Mon..Sun
HOLIDAYS = {(1, 1), (5, 27), (7, 4), (9, 2), (11, 28), (12, 25)}


def make_synth(
    *,
    seed: int = 0,
    n_train: int = 365,
    n_holdout: int = 180,
    start: date = date(2024, 1, 1),
    base: float = 8000.0,
    beta_rain: float = 1200.0,
    beta_hot: float = 400.0,
    beta_win: float = 250.0,
    beta_msg: float = 900.0,
    beta_game: float = 300.0,
    beta_holiday: float = -1500.0,
    hot_strike: float = 85.0,
    sigma: float = 400.0,
    hetero: bool = False,
    rain_prob: float = 0.3,
    estimated: bool = False,
) -> pd.DataFrame:
    """One feature table: first `n_train` days `train`, the next `n_holdout` `holdout`.

    `hetero=True` scales the noise with DOW (σ·(1+dow)/4), for the HC3 test.
    """
    rng = np.random.default_rng(seed)
    n = n_train + n_holdout
    dates = [start + timedelta(days=i) for i in range(n)]
    dow = np.array([d.weekday() for d in dates])
    doy = np.array([d.timetuple().tm_yday for d in dates])
    is_holiday = np.array([(d.month, d.day) in HOLIDAYS for d in dates])

    home_game = rng.random(n) < 0.25
    home_win = home_game & (rng.random(n) < 0.55)
    msg_event = home_game | (rng.random(n) < 0.10)
    rain = rng.random(n) < rain_prob
    rain_open_hours = np.where(rain, rng.random(n) < 0.8, rng.random(n) < 0.03)
    tmax = 57.0 + 25.0 * np.sin(2 * np.pi * (doy - 105) / 365.25) + rng.normal(0, 6.0, n)
    hot = tmax > hot_strike

    w = 2 * np.pi * doy / 365.25
    season = 600.0 * np.sin(w) + 250.0 * np.cos(w) - 200.0 * np.sin(2 * w) + 150.0 * np.cos(2 * w)
    scale = sigma * (1 + dow) / 4 if hetero else np.full(n, sigma)
    revenue = (
        base + DOW_EFFECT[dow] + season + beta_holiday * is_holiday + beta_msg * msg_event
        + beta_game * home_game + beta_win * home_win + beta_rain * rain + beta_hot * hot
        + rng.normal(0.0, 1.0, n) * scale
    )
    return pd.DataFrame({
        "date": dates,
        "revenue": revenue,
        "dow": dow,
        "doy": doy,
        "is_holiday": is_holiday,
        "msg_event": msg_event,
        "home_game": home_game,
        "home_win": home_win,
        "rain": rain,
        "rain_open_hours": rain_open_hours,
        "tmax": tmax,
        "estimated": estimated,
        "split": np.where(np.arange(n) < n_train, "train", "holdout"),
    })[COLUMNS]


def synth_taxi(seed: int = 0, **kw) -> pd.DataFrame:
    """Taxi-like: rain and heat raise revenue. Planted β_rain=+1200, β_hot=+400, β_win=+250."""
    params = dict(beta_rain=1200.0, beta_hot=400.0, beta_win=250.0, estimated=False)
    return make_synth(seed=seed, **{**params, **kw})


def synth_bar(seed: int = 0, **kw) -> pd.DataFrame:
    """Bar-like (estimated): rain and heat cut revenue, wins lift it.
    Planted β_rain=-800, β_hot=-300, β_win=+600; smaller base and noise."""
    params = dict(
        base=4000.0, beta_rain=-800.0, beta_hot=-300.0, beta_win=600.0, beta_msg=1500.0,
        sigma=300.0, estimated=True,
    )
    return make_synth(seed=seed, **{**params, **kw})
