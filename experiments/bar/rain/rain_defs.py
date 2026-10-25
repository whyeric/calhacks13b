"""Experiment: does a stricter / evening rain definition make the bar's rain exposure measurable?

For each rain definition, replace the `rain` column of features.build(business) and refit with
fit_exposures (same design: DOW, season k=1,2, controls, home_win, rain, hot>85F; HC3, z=1.645).
Also report agreement with the Kalshi settlement flag (station daily total >= 0.01 in, the
default add_settlement rule) as basis R2 = Pearson^2 on train, the gate used by markets rule 4.

Run from backend/: .venv/bin/python ../experiments/bar/rain/rain_defs.py
Summary numbers only; no daily series written.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

import numpy as np
import pandas as pd

from app import config
from app.data import features, weather
from app.stats.exposure import beta_settlement, fit_exposures

MM = 1 / 25.4  # inches per mm
EVENING = (17, 24)  # 5 PM to midnight local, hour-ending stamps 18..24


def hourly_by_day(w: weather.Weather, hours: tuple[int, int]) -> tuple[pd.Series, pd.Series]:
    """(total, max hourly) precipitation inside [open, close) per date, hour-ending convention."""
    hr = w.hourly
    hour = hr["time"].dt.hour
    day = (hr["time"] - pd.Timedelta(hours=1)).dt.date
    ending = hour.where(hour != 0, 24)
    m = (ending > hours[0]) & (ending <= hours[1])
    g = hr.loc[m, "precipitation"].groupby(day[m])
    return g.sum().round(6), g.max().round(6)


def definitions(dates: pd.Series, w: weather.Weather) -> dict[str, pd.Series]:
    daily = w.daily.set_index("date")["precipitation_sum"].round(6)
    d = dates.map(daily)
    open_tot, _ = hourly_by_day(w, config.BUSINESS_HOURS)
    eve_tot, eve_max = hourly_by_day(w, EVENING)
    ot = dates.map(open_tot).fillna(0.0)
    et, em = dates.map(eve_tot).fillna(0.0), dates.map(eve_max).fillna(0.0)
    return {
        "current: daily >= 0.01 in": d >= 0.01,
        "daily >= 1 mm": d >= 1 * MM,
        "daily >= 2.5 mm": d >= 2.5 * MM,
        "daily >= 5 mm": d >= 5 * MM,
        "daily >= 10 mm": d >= 10 * MM,
        "heavy: daily >= 20 mm": d >= 20 * MM,
        "rain_open_hours (11-23 >= 0.05 in)": ot >= config.RAIN_OPEN_HOURS_IN,
        "open hours >= 2.5 mm": ot >= 2.5 * MM,
        "evening any hour >= 1 mm/hr": em >= 1 * MM,
        "evening total >= 1 mm": et >= 1 * MM,
        "evening total >= 2.5 mm": et >= 2.5 * MM,
        "evening total >= 5 mm": et >= 5 * MM,
    }


def run(business: str, w: weather.Weather) -> list[dict]:
    base = features.add_settlement(features.build(business))
    train = base["split"] == "train"
    settle = base["settle_rain"]
    rows = []
    for name, flag in definitions(base["date"], w).items():
        df = base.copy()
        df["rain"] = flag.astype(bool).to_numpy()
        res = fit_exposures(df, strikes={"hot": 85}, business_id=business)
        e = next(x for x in res.exposures + res.dropped if x.event == "rain")
        bs = beta_settlement(df, settle, event="rain", strikes={"hot": 85})
        agree = float((df.loc[train, "rain"] == settle[train]).mean())
        rows.append({
            "business": business, "definition": name,
            "share_all": f"{df['rain'].mean():.1%}", "share_train": f"{df.loc[train, 'rain'].mean():.1%}",
            "n": e.n_events_train, "effect": float(e.effect_usd),
            "ci90": f"[{float(e.ci90[0]):.0f}, {float(e.ci90[1]):.0f}]", "p": round(e.p_value, 3),
            "sig": "yes" if "not_significant" not in e.reasons else "no",
            "hedgeable": e.hedgeable, "basis_r2": float(bs.r2), "agree": f"{agree:.1%}",
            "r2_tr": round(res.r2_train, 3), "r2_ho": round(res.r2_holdout, 3),
        })
    # beta_S of the settlement flag itself (same for every definition)
    rows.append({"business": business, "definition": "settlement flag beta_S", "effect": float(bs.beta_s),
                 "ci90": f"[{float(bs.beta_s) - 1.645 * float(bs.se):.0f}, {float(bs.beta_s) + 1.645 * float(bs.se):.0f}]",
                 "share_train": f"{settle[train].mean():.1%}"})
    return rows


if __name__ == "__main__":
    w = weather.load_weather(*config.MSG_LATLON, cache_dir=config.FIXTURES_DIR, offline=True)
    out = pd.DataFrame(run("restaurant", w) + run("taxi", w))
    pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 40)
    print(out.to_string(index=False))
