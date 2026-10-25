"""Round 2, R2: does Central Park weather move daily bike ridership, and does it replicate?

Series (public data, aggregated to daily totals on the fly, cached in the scratchpad):
- jc:  Citi Bike Jersey City/Hoboken trips per day (s3://tripdata JC-YYYYMM zips), start date.
       The NYC monthly zips are ~0.4-1 GB each (~20 GB for 2023-2025); at the ~5 MB/s this
       machine gets from S3 that is over an hour, so the NYC system is not used.
- dot: NYC DOT automated bike counters (NYC Open Data uczf-rk3c), summed over a fixed panel of
       counters that report on >= 95% of days in both periods (a Manhattan/East River proxy for
       NYC Citi Bike demand).
Weather: GHCN-Daily USW00094728 (Central Park), the station Kalshi KXRAIN / KXHIGHNY settle on.
TMAX is converted to whole degrees F like the NWS climate report, so the flags are the
settlement flags themselves (basis R2 = 1 by construction, up to C->F rounding).

Model per (series, event), fitted independently on train (2023-01..2024-12) and holdout (2025):
    trips = const + DOW + season(k=1,2) + holiday + trend + beta*event + e,  HAC(7) SEs, z=1.645
using app.stats.exposure.build_design (msg_event/home_game are 0 and dropped).
Revenue: trips x USD_PER_TRIP. BH at 10% over all tests, on train and holdout p separately.
Hedge backtest on holdout: buy |beta_usd| contracts on the side that pays when revenue is hurt,
price = train frequency (+0.02 if YES, side priced at 1-p if NO) + fee 0.07 p (1-p).

Run from backend/: .venv/bin/python ../experiments/bar/r2-citibike/citibike_weather.py
"""

import io
import sys
import zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

import httpx
import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.holiday import USFederalHolidayCalendar

from app.stats.exposure import Z90, build_design

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
CACHE.mkdir(parents=True, exist_ok=True)
TRAIN = ("2023-01-01", "2024-12-31")
HOLD = ("2025-01-01", "2025-12-31")
USD_PER_TRIP = 4.00  # stated assumption: blended member/casual revenue per ride
HAC_LAGS = 7
BH_Q = 0.10
EDGE, FEE = 0.02, 0.07


# ---------- data ----------
def jc_daily() -> pd.Series:
    out = CACHE / "citibike_jc_daily.parquet"
    if out.exists():
        return pd.read_parquet(out)["trips"]
    keys = httpx.get("https://s3.amazonaws.com/tripdata/?list-type=2", timeout=60).text
    import re
    names = [k for k in re.findall(r"<Key>(JC-20(?:23|24|25)\d\d-[^<]*)</Key>", keys)]
    counts: dict = {}
    with httpx.Client(timeout=300) as c:
        for k in sorted(names):
            z = zipfile.ZipFile(io.BytesIO(c.get(f"https://s3.amazonaws.com/tripdata/{k}").content))
            for f in z.namelist():
                if not f.endswith(".csv") or f.startswith("__MACOSX"):
                    continue
                df = pd.read_csv(z.open(f), usecols=["started_at"])
                d = pd.to_datetime(df["started_at"].str[:10]).dt.date.value_counts()
                for day, n in d.items():
                    counts[day] = counts.get(day, 0) + int(n)
            print("jc", k, flush=True)
    s = pd.Series(counts, name="trips").sort_index()
    s.index = pd.to_datetime(s.index)
    s.to_frame().to_parquet(out)
    return s


def dot_daily() -> pd.Series:
    out = CACHE / "nycdot_counters_daily.parquet"
    if out.exists():
        raw = pd.read_parquet(out)
    else:
        q = {
            "$select": "id, date_trunc_ymd(date) as d, sum(counts) as n",
            "$where": "date >= '2023-01-01' and date < '2026-01-01'",
            "$group": "id, d",
            "$limit": "200000",
        }
        r = httpx.get("https://data.cityofnewyork.us/resource/uczf-rk3c.json", params=q, timeout=300)
        r.raise_for_status()
        raw = pd.DataFrame(r.json())
        raw["d"] = pd.to_datetime(raw["d"])
        raw["n"] = raw["n"].astype(float)
        raw.to_parquet(out)
    wide = raw.pivot_table(index="d", columns="id", values="n", aggfunc="sum")
    days = pd.date_range(TRAIN[0], HOLD[1])
    wide = wide.reindex(days)
    tr, ho = wide.loc[TRAIN[0]:TRAIN[1]], wide.loc[HOLD[0]:HOLD[1]]
    ok = [c for c in wide.columns
          if tr[c].gt(0).mean() >= 0.95 and ho[c].gt(0).mean() >= 0.95]
    panel = wide[ok]
    # only days where every panel counter reported, so the sum is comparable day to day
    s = panel.dropna().sum(axis=1)
    s = s[(panel.loc[s.index] > 0).all(axis=1)]
    print(f"dot panel: {len(ok)} counters, {len(s)} complete days")
    return s.rename("trips")


def central_park() -> pd.DataFrame:
    out = CACHE / "ghcnd_USW00094728.csv"
    if not out.exists():
        url = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00094728.csv"
        out.write_bytes(httpx.get(url, timeout=300).content)
    w = pd.read_csv(out, usecols=["DATE", "PRCP", "SNOW", "TMAX"], parse_dates=["DATE"], low_memory=False)
    w = w.set_index("DATE").loc[TRAIN[0]:HOLD[1]]
    prcp_in = w["PRCP"] / 10 / 25.4  # tenths of mm -> inches
    tmax_f = np.round(w["TMAX"] / 10 * 9 / 5 + 32)
    snow_in = w["SNOW"] / 25.4
    return pd.DataFrame({
        "rain_001in": prcp_in >= 0.0095,  # recorded 0.3 mm = 0.01 in; trace is 0
        "rain_1mm": w["PRCP"] >= 10,
        "hot80": tmax_f > 80,
        "hot85": tmax_f > 85,
        "hot90": tmax_f > 90,
        "cold40": tmax_f < 40,
        "snow": snow_in >= 0.1,
    }).where(w[["PRCP", "TMAX", "SNOW"]].notna().all(axis=1).values[:, None].repeat(7, 1))


EVENTS = ("rain_001in", "rain_1mm", "hot80", "hot85", "hot90", "cold40", "snow")


def holidays(idx: pd.DatetimeIndex) -> pd.Series:
    h = set(USFederalHolidayCalendar().holidays(idx.min(), idx.max()))
    h |= {d for d in idx if (d.month, d.day) in ((12, 24), (12, 31))}
    return pd.Series(idx.isin(list(h)), index=idx)


# ---------- model ----------
def design(y: pd.Series, flag: pd.Series | None) -> pd.DataFrame:
    idx = y.index
    df = pd.DataFrame({
        "dow": idx.day_of_week, "doy": idx.day_of_year, "is_holiday": holidays(idx).values,
        "msg_event": 0, "home_game": 0,
    }, index=idx)
    X = build_design(df, {} if flag is None else {"event": flag})
    X.insert(1, "trend", (idx - idx[0]).days / 365.25)
    return X


def fit(y: pd.Series, flag: pd.Series | None):
    X = design(y, flag)
    return sm.OLS(y.astype(float), X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS}, use_t=False), X


def bh(p: np.ndarray, q: float) -> np.ndarray:
    n = len(p)
    order = np.argsort(p)
    ranked = p[order] * n / np.arange(1, n + 1)
    adj = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.minimum(adj, 1)
    return out


def period(s: pd.Series, w: pd.DataFrame, ev: str, span: tuple[str, str]):
    d = pd.concat([s.rename("y"), w[ev].rename("f")], axis=1, sort=True).loc[span[0]:span[1]].dropna()
    return d["y"], d["f"].astype(bool)


def backtest(s: pd.Series, w: pd.DataFrame, ev: str, beta_usd: float, p_train: float) -> dict:
    """Holdout: revenue vs revenue + hedge. Also on train-model residual revenue (no season)."""
    ytr, ftr = period(s, w, ev, TRAIN)
    yho, fho = period(s, w, ev, HOLD)
    rev = yho * USD_PER_TRIP
    # side that pays when revenue is hurt: YES if beta<0, NO if beta>0
    yes = beta_usd < 0
    p = (p_train if yes else 1 - p_train) + EDGE
    pays = fho if yes else ~fho
    n = abs(beta_usd)
    pnl = n * (pays.astype(float) - p - FEE * p * (1 - p))
    # residual revenue: train controls-only model, predicted on holdout (trend extrapolated)
    base, Xtr = fit(ytr, None)
    Xho = design(yho, None)
    Xho["trend"] = (yho.index - ytr.index[0]).days / 365.25
    resid = (yho - base.predict(Xho[Xtr.columns])) * USD_PER_TRIP
    r = {}
    for name, v in (("raw", rev), ("resid", resid)):
        r[f"{name}_sd"], r[f"{name}_sd_h"] = v.std(), (v + pnl).std()
        r[f"{name}_p5"], r[f"{name}_p5_h"] = v.quantile(0.05), (v + pnl).quantile(0.05)
    r["hedge_cost_per_day"] = -pnl.mean()
    return r


def main() -> None:
    w = central_park()
    series = {"jc": jc_daily(), "dot": dot_daily()}
    rows = []
    for sname, s in series.items():
        s = s.loc[TRAIN[0]:HOLD[1]]
        for ev in EVENTS:
            row = {"series": sname, "event": ev}
            for tag, span in (("tr", TRAIN), ("ho", HOLD)):
                y, f = period(s, w, ev, span)
                res, _ = fit(y, f)
                b, se = res.params.get("event", 0.0), res.bse.get("event", np.nan)
                row |= {f"b_{tag}": b, f"lo_{tag}": b - Z90 * se, f"hi_{tag}": b + Z90 * se,
                        f"p_{tag}": res.pvalues.get("event", 1.0), f"n_{tag}": int(f.sum()),
                        f"N_{tag}": len(y), f"mean_{tag}": y.mean(), f"p_ev_{tag}": f.mean()}
            rows.append(row)
    t = pd.DataFrame(rows)
    t["bh_tr"], t["bh_ho"] = bh(t["p_tr"].values, BH_Q), bh(t["p_ho"].values, BH_Q)
    t["found"] = (
        (t["n_tr"] >= 10) & (t["n_ho"] >= 10)
        & ((t["lo_tr"] > 0) | (t["hi_tr"] < 0))
        & ((t["lo_ho"] > 0) | (t["hi_ho"] < 0))
        & (np.sign(t["b_tr"]) == np.sign(t["b_ho"]))
        & (t["bh_tr"] <= BH_Q) & (t["bh_ho"] <= BH_Q)
    )
    pd.set_option("display.width", 250)
    show = t[["series", "event", "n_tr", "b_tr", "lo_tr", "hi_tr", "n_ho", "b_ho", "lo_ho", "hi_ho",
              "bh_tr", "bh_ho", "found"]].copy()
    print(f"\n{len(t)} tests; effects in trips/day; $ = trips x {USD_PER_TRIP}")
    for sname in series:
        sub = t[t.series == sname]
        print(sname, "mean trips/day train", round(sub.mean_tr.iloc[0]), "holdout", round(sub.mean_ho.iloc[0]),
              "days", sub.N_tr.iloc[0], sub.N_ho.iloc[0])
    print(show.round(4).to_string(index=False))
    print("\nevent frequencies (train, holdout):")
    print(t[t.series == "jc"][["event", "p_ev_tr", "p_ev_ho"]].round(3).to_string(index=False))

    print("\nhedge backtest on 2025 holdout (USD/day), sized on train beta, priced at train freq:")
    bt = []
    for _, r in t[t.found].iterrows():
        s = series[r.series].loc[TRAIN[0]:HOLD[1]]
        bt.append({"series": r.series, "event": r.event, "contracts": abs(r.b_tr * USD_PER_TRIP),
                   **backtest(s, w, r.event, r.b_tr * USD_PER_TRIP, r.p_ev_tr)})
    if bt:
        print(pd.DataFrame(bt).round(1).to_string(index=False))


if __name__ == "__main__":
    main()
