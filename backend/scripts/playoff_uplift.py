"""Pooled near-MSG playoff uplift from Dewey aggregates -> `fixtures/playoff_uplift.json`.

    cd backend && .venv/bin/python scripts/playoff_uplift.py                 # raw Dewey in data/
    cd backend && .venv/bin/python scripts/playoff_uplift.py --aggregate X   # a cached daily aggregate

The bar's own daily series is too noisy to measure an 18-game effect on its own, so the product
uses a class rating (experiments r2-pooling): the uplift measured on every balanced Dewey
restaurant/bar store within 0.5 km of MSG, summed per day, applied to the bar.

Method (experiments r5-nycplayoffs): log(daily visits) on `reg` (regular-season MSG home game)
and `po` (playoff MSG home game) with day-of-week, year-month FE, holiday and rain, HAC(7)
errors, 2024-01-01..2026-09-27. Games come from `fixtures/msg_games_playoffs.csv`.

D2: only the summary numbers are written (coefficient, SE, CI, n). No daily Dewey series and no
store identifiers are committed. The aggregate stays in gitignored data/.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app import config  # noqa: E402
from app.data import playoffs, weather  # noqa: E402
from app.stats.playoffs import daily_flags  # noqa: E402

START, END = date(2024, 1, 1), date(2026, 9, 27)
RADIUS_KM = 0.5
Z90 = 1.645
OUT = config.FIXTURES_DIR / "playoff_uplift.json"
AGG_CACHE = config.RAW_DATA_DIR / "dewey_msg_0p5km_daily.parquet"  # gitignored


def build_aggregate(glob: str) -> tuple[pd.DataFrame, int]:
    """Daily visits summed over balanced stores within RADIUS_KM of MSG (same build as r2-aggregate)."""
    import duckdb

    lat, lon = config.MSG_LATLON
    con = duckdb.connect()
    con.execute(f"""
        create table w as select ID_STORE id, DATE_RANGE_START::date ws, LATITUDE lat, LONGITUDE lon,
            from_json(VISITS_BY_DAY, '["INTEGER"]') v from '{glob}'""")
    con.execute("""create table st as select id, avg(lat) lat, avg(lon) lon, count(*) nwk,
        avg((list_min(v) = list_max(v))::int) flat from w group by id""")
    nweeks = con.execute("select count(distinct ws) from w").fetchone()[0]
    con.execute(f"""create table keep as select id from st where nwk = {nweeks} and flat < 0.05 and
        6371 * 2 * asin(sqrt(pow(sin(radians(lat - {lat}) / 2), 2)
          + cos(radians(lat)) * cos(radians({lat})) * pow(sin(radians(lon - ({lon})) / 2), 2))) <= {RADIUS_KM}""")
    n = con.execute("select count(*) from keep").fetchone()[0]
    df = con.execute("""
        with d as (select w.id, w.ws + (i - 1)::int as date, w.v[i] x from w join keep using (id), range(1, 8) r(i))
        select date, sum(x) visits from d group by date order by date""").df()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df, n


def load_aggregate(path: str | None) -> tuple[pd.Series, int | None]:
    if path:
        d = pd.read_parquet(path)
        col = "msg_within_0p5km" if "msg_within_0p5km" in d.columns else "visits"
        n = int(d["n0p5"].iloc[0]) if "n0p5" in d.columns else None
        return pd.Series(d[col].to_numpy(float), index=pd.to_datetime(d["date"]).dt.date), n
    if AGG_CACHE.exists():
        d = pd.read_parquet(AGG_CACHE)
        return pd.Series(d["visits"].to_numpy(float), index=pd.to_datetime(d["date"]).dt.date), int(d["n_stores"].iloc[0])
    folder = config.get_settings().dewey_restaurants_dir or str(next(p for p in config.RAW_DATA_DIR.iterdir() if p.is_dir()))
    df, n = build_aggregate(str(Path(folder) / "*.parquet"))
    df.assign(n_stores=n).to_parquet(AGG_CACHE)
    return pd.Series(df["visits"].to_numpy(float), index=df["date"]), n


def design(idx: pd.Index, flags: pd.DataFrame, rain: pd.Series) -> pd.DataFrame:
    ts = pd.to_datetime(pd.Series(idx, index=idx))
    X = pd.get_dummies(ts.dt.day_of_week, prefix="dow", drop_first=True).astype(float)
    X = X.join(pd.get_dummies(ts.dt.strftime("%Y%m"), prefix="ym", drop_first=True).astype(float))
    X.insert(0, "const", 1.0)
    X["holiday"] = [d in config.HOLIDAYS for d in idx]
    X["rain"] = rain.reindex(idx).astype(float).to_numpy()
    X["reg"] = flags["reg_home"].to_numpy(float)
    X["po"] = flags["po_home"].to_numpy(float)
    X = X.astype(float)
    return X.loc[:, (X.nunique() > 1) | (X.columns == "const")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aggregate", help="parquet with date + msg_within_0p5km (or visits)")
    args = ap.parse_args()

    y, n_stores = load_aggregate(args.aggregate)
    y = y[(y.index >= START) & (y.index <= END) & (y > 0)]
    w = weather.load_weather(*config.MSG_LATLON, START, END, cache_dir=config.RAW_DATA_DIR, offline=False)
    rain = weather.flags(w).set_index("date")["rain"]
    games = playoffs.read_games()
    flags = daily_flags(games, y.index)
    X = design(y.index, flags, rain)
    res = sm.OLS(np.log(y.to_numpy()), X).fit(cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)
    b, se, p = float(res.params["po"]), float(res.bse["po"]), float(res.pvalues["po"])
    reg_b = float(res.params["reg"])
    diff = res.t_test("po - reg")
    out = {
        "source": "Dewey daily visits, balanced restaurant/bar stores within 0.5 km of MSG, summed per day",
        "method": "log(visits) ~ playoff home + regular home + DOW + year-month FE + holiday + rain, HAC(7)",
        "window": [START.isoformat(), END.isoformat()],
        "n_stores": n_stores,
        "n_days": int(len(y)),
        "n_playoff_home_games": int(flags["po_home"].sum()),
        "n_regular_home_games": int(flags["reg_home"].sum()),
        "beta_log": round(b, 5),
        "se_log": round(se, 5),
        "p_value": float(f"{p:.3g}"),
        "uplift_pct": round(100 * np.expm1(b), 2),
        "ci90_pct": [round(100 * np.expm1(b - Z90 * se), 2), round(100 * np.expm1(b + Z90 * se), 2)],
        "regular_uplift_pct": round(100 * np.expm1(reg_b), 2),
        "playoff_minus_regular_pct_pts": round(100 * float(diff.effect[0]), 2),
        "replication": "positive with the 90% CI above 0 in every team-season Dewey covers "
                       "(Knicks 2024-2026, Rangers 2024); train and holdout both +5.7% (r5-nycplayoffs)",
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
