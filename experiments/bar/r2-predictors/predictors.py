"""Round 2: new predictors on the existing series (taxi, bar, MSG arena visits).

Run from backend/:  .venv/bin/python ../experiments/bar/r2-predictors/predictors.py

Weather comes from NOAA GHCN-Daily station USW00094728 (Central Park), which is the
station the NWS CLI report (and so KXHIGHNY / KXRAIN) settles on. Humidity / heat index
come from Open-Meteo at the Central Park grid point (no GHCN element). Downloads are
cached in the scratchpad r2-cache, never in the repo.

Design (one regression per predictor x series): const, DOW, season harmonics k=1,2,
is_holiday, home_game, + the predictor (plus its main effect for interactions / lags).
HAC (Newey-West, maxlags 7) errors, z = 1.645. Train = first 365 days, holdout = the
rest, each fitted independently. BH at 10% over every train p-value.
"""

import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import statsmodels.api as sm

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))
from app import config  # noqa: E402
from app.data import features  # noqa: E402

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
OUT = Path(__file__).resolve().parent
Z = 1.645
START, END = date(2024, 9, 20), date(2026, 8, 31)  # 11 extra days so lags exist on day 1


# ---------------------------------------------------------------- data
def ghcn() -> pd.DataFrame:
    p = CACHE / "ghcn_cp.csv"
    if not p.exists():
        url = ("https://www.ncei.noaa.gov/access/services/data/v1?dataset=daily-summaries"
               f"&stations=USW00094728&startDate={START}&endDate={END}"
               "&dataTypes=PRCP,SNOW,SNWD,TMAX,TMIN,AWND,WSF2&units=standard&format=csv")
        p.write_text(httpx.get(url, timeout=120).text)
    g = pd.read_csv(p)
    g["date"] = pd.to_datetime(g["DATE"]).dt.date
    return g[(g["date"] >= START) & (g["date"] <= END)].set_index("date")


def openmeteo() -> pd.DataFrame:
    p = CACHE / "om_cp.json"
    if not p.exists():
        lat, lon = config.SETTLEMENT_STATION_LATLON
        r = httpx.get("https://archive-api.open-meteo.com/v1/archive", timeout=120, params={
            "latitude": lat, "longitude": lon, "start_date": str(START), "end_date": str(END),
            "daily": "apparent_temperature_max,relative_humidity_2m_mean",
            "temperature_unit": "fahrenheit", "timezone": config.WEATHER_TZ})
        p.write_text(r.text)
    d = json.loads(p.read_text())["daily"]
    df = pd.DataFrame(d)
    df["date"] = pd.to_datetime(df["time"]).dt.date
    return df.set_index("date")


# NYC DOE recess weekdays (non-summer), 2024-25 and 2025-26 calendars (approximate, public).
SCHOOL_BREAKS = [
    ("2024-10-03", "2024-10-04"), ("2024-10-14", "2024-10-14"), ("2024-11-05", "2024-11-05"),
    ("2024-11-28", "2024-11-29"), ("2024-12-24", "2025-01-01"), ("2025-02-17", "2025-02-21"),
    ("2025-03-31", "2025-03-31"), ("2025-04-14", "2025-04-18"), ("2025-05-26", "2025-05-26"),
    ("2025-10-13", "2025-10-13"), ("2025-11-04", "2025-11-04"), ("2025-11-27", "2025-11-28"),
    ("2025-12-24", "2026-01-02"), ("2026-02-16", "2026-02-20"), ("2026-04-03", "2026-04-10"),
    ("2026-05-25", "2026-05-25"),
]
SUMMER = [("2025-06-27", "2025-09-03"), ("2026-06-27", "2026-08-31")]
DST = ["2024-11-03", "2025-03-09", "2025-11-02", "2026-03-08"]


def in_ranges(dates: pd.Series, ranges) -> pd.Series:
    out = pd.Series(False, index=dates.index)
    for a, b in ranges:
        out |= (dates >= date.fromisoformat(a)) & (dates <= date.fromisoformat(b))
    return out


def predictors(base: pd.DataFrame) -> pd.DataFrame:
    """All candidate regressors aligned to base['date']. Flags are 0/1 floats."""
    g, om = ghcn(), openmeteo()
    full = pd.DataFrame(index=pd.Index(pd.date_range(START, END).date, name="date"))
    full = full.join(g[["PRCP", "SNOW", "SNWD", "TMAX", "TMIN", "WSF2"]]).join(
        om[["apparent_temperature_max", "relative_humidity_2m_mean"]])
    tmax, tmin, prcp = full["TMAX"], full["TMIN"], full["PRCP"]
    tavg = (tmax + tmin) / 2
    rain = (prcp >= 0.01).astype(float)
    P = pd.DataFrame(index=full.index)
    # weather (settleable on the CP CLI: PRCP, SNOW, TMAX)
    P["snow_day"] = (full["SNOW"] >= 0.1).astype(float)
    P["snow_depth_1in"] = (full["SNWD"] >= 1).astype(float)
    P["freezing_tmax_lt32"] = (tmax < 32).astype(float)
    P["precip_log1p_mm"] = np.log1p(prcp * 25.4)
    P["rain_ge_0.25in"] = (prcp >= 0.25).astype(float)
    P["cdd"] = (tavg - 65).clip(lower=0)
    P["hdd"] = (65 - tavg).clip(lower=0)
    P["gust_gt25mph"] = (full["WSF2"] > 25).astype(float)
    P["heat_index_ge90"] = (full["apparent_temperature_max"] >= 90).astype(float)
    P["humid_rh_ge80"] = (full["relative_humidity_2m_mean"] >= 80).astype(float)
    prev7 = tmax.shift(1).rolling(7).mean()
    P["first_nice_day"] = ((tmax >= 60) & (prev7 < 50)).astype(float)
    # Kalshi KXHIGHNY-style: thresholds (tmax > strike) and 10F brackets (base 60-69)
    for k in (80, 85, 90):
        P[f"tmax_gt{k}"] = (tmax > k).astype(float)
    bins = [(-99, 40), (40, 50), (50, 60), (70, 80), (80, 90), (90, 200)]
    for lo, hi in bins:
        P[f"bracket_{max(lo, 0)}_{hi if hi < 200 else 'up'}"] = ((tmax >= lo) & (tmax < hi)).astype(float)
    # calendar
    dts = pd.Series(full.index, index=full.index)
    dom = pd.to_datetime(dts).dt.day
    P["payday_1st_15th"] = dom.isin([1, 15]).astype(float)
    P["month_start_1to3"] = (dom <= 3).astype(float)
    P["school_break"] = in_ranges(dts, SCHOOL_BREAKS).astype(float)
    P["school_summer"] = in_ranges(dts, SUMMER).astype(float)
    dst = pd.Series(False, index=full.index)
    for d0 in DST:
        d0 = date.fromisoformat(d0)
        dst |= (dts >= d0) & (dts <= d0 + timedelta(days=6))
    P["dst_week"] = dst.astype(float)
    # lags / interactions (need main effects: stored as "x|main1,main2")
    P["rain"] = rain
    wkend = pd.Series((pd.to_datetime(dts).dt.dayofweek >= 5).to_numpy(float), index=full.index)
    P["rain_x_weekend"] = rain * wkend
    for L in (1, 2, 3):
        P[f"rain_lag{L}"] = rain.shift(L)
    P = P.loc[base["date"].tolist()].reset_index(drop=True)
    # MSG non-sport events: Dewey visit spike with no Knicks/Rangers home game
    m = pd.read_parquet(BACKEND / "fixtures" / "msg_visits_daily.parquet")
    spike = pd.Series(m["spike"].astype(bool).to_numpy(), index=pd.to_datetime(m["date"]).dt.date)
    P["msg_nongame_spike"] = (base["date"].map(spike).fillna(False).astype(bool) & ~base["home_game"]).astype(float).to_numpy()
    return P


MAINS = {"rain_x_weekend": ["rain"], "rain_lag1": ["rain"], "rain_lag2": ["rain"], "rain_lag3": ["rain"]}
# Predictors a Kalshi NYC weather contract can settle (directly or via the CP CLI strike ladder).
SETTLEABLE = {"snow_day", "freezing_tmax_lt32", "cdd", "hdd"}
CONTRACT = {
    "snow_day": "NYC snowfall (CP CLI SNOW); Kalshi lists monthly/seasonal NYC snow totals",
    "snow_depth_1in": "none direct (snow depth is reported on CP CLI, no Kalshi market)",
    "freezing_tmax_lt32": "KXHIGHNY bottom bracket / 'below' strike at 32F",
    "precip_log1p_mm": "KXRAIN only settles >=0.01in; intensity needs a monthly-total (KXRAINNYCM) proxy",
    "rain_ge_0.25in": "no daily 0.25in contract; monthly rain total market only",
    "cdd": "KXHIGHNY strike ladder (CDD is a smooth fn of tmax)",
    "hdd": "KXHIGHNY strike ladder",
    "gust_gt25mph": "none",
    "heat_index_ge90": "none (proxy: KXHIGHNY > 85/90)",
    "humid_rh_ge80": "none",
    "first_nice_day": "KXHIGHNY > 60 (path-dependent; not a single contract)",
    "payday_1st_15th": "calendar, not an event (no contract needed/possible)",
    "month_start_1to3": "calendar",
    "school_break": "calendar",
    "school_summer": "calendar",
    "dst_week": "calendar",
    "rain": "KXRAIN (CP >= 0.01in)",
    "rain_x_weekend": "KXRAIN bought only for Sat/Sun dates",
    "msg_nongame_spike": "none (no concert-attendance contract)",
}
for k in (80, 85, 90):
    CONTRACT[f"tmax_gt{k}"] = f"KXHIGHNY > {k}F"
for L in (1, 2, 3):
    CONTRACT[f"rain_lag{L}"] = f"KXRAIN for the date {L} day(s) earlier"


def series() -> dict[str, pd.DataFrame]:
    taxi = features.build("taxi")
    bar = features.build("restaurant")
    m = pd.read_parquet(BACKEND / "fixtures" / "msg_visits_daily.parquet")
    m["date"] = pd.to_datetime(m["date"]).dt.date
    arena = taxi.drop(columns="revenue").merge(m[["date", "visits"]].rename(columns={"visits": "revenue"}), on="date")
    return {"taxi": taxi, "bar": bar, "msg_visits": arena}


# ---------------------------------------------------------------- stats
def design(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    X["const"] = 1.0
    for d in range(1, 7):
        X[f"dow_{d}"] = (df["dow"] == d).astype(float)
    w = 2 * np.pi * df["doy"].astype(float) / 365.25
    for k in (1, 2):
        X[f"sin{k}"], X[f"cos{k}"] = np.sin(k * w), np.cos(k * w)
    X["is_holiday"] = df["is_holiday"].astype(float)
    X["home_game"] = df["home_game"].astype(float)
    return X


def fit(y, X, name):
    keep = [c for c in X.columns if c == "const" or X[c].nunique() > 1]
    X = X[keep]
    if name not in X.columns:
        return None
    r = sm.OLS(y.astype(float), X).fit(cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)
    return float(r.params[name]), float(r.bse[name]), float(r.pvalues[name])


def bh(p: np.ndarray) -> np.ndarray:
    n = len(p)
    o = np.argsort(p)
    q = p[o] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(n)
    out[o] = np.minimum(q, 1)
    return out


def hedge_backtest(df, P, name, beta_train):
    """Holdout: buy the opposite side at train frequency + 0.02 + fee, |beta| contracts."""
    tr, ho = df["split"] == "train", df["split"] == "holdout"
    ev = P[name].astype(bool)
    side_yes = beta_train < 0  # revenue falls on the event -> buy YES
    hit = ev if side_yes else ~ev
    p = float(hit[tr].mean()) + 0.02
    cost = p + 0.07 * p * (1 - p)
    n = abs(beta_train)
    y = df.loc[ho, "revenue"]
    hedged = y + n * (hit[ho].astype(float) - cost)
    return {"sd_unhedged": y.std(), "sd_hedged": hedged.std(),
            "p5_unhedged": y.quantile(0.05), "p5_hedged": hedged.quantile(0.05),
            "mean_cost_per_day": float((n * (hit[ho].astype(float) - cost)).mean()),
            "side": "YES" if side_yes else "NO", "price": p}


def main():
    S = series()
    rows = []
    for sname, df in S.items():
        P = predictors(df)
        Xb = design(df)
        for name in P.columns:
            if name == "msg_nongame_spike" and sname == "msg_visits":
                continue  # tautological: spike is defined from these visits
            cols = MAINS.get(name, []) + [name]
            X = pd.concat([Xb, P[cols]], axis=1)
            ok = X.notna().all(axis=1)
            rec = {"series": sname, "predictor": name}
            for part in ("train", "holdout"):
                m = ok & (df["split"] == part)
                res = fit(df.loc[m, "revenue"], X[m], name)
                binary = set(P[name].dropna().unique()) <= {0.0, 1.0}
                rec[f"n_ev_{part}"] = int(P.loc[m, name].sum()) if binary else int(m.sum())
                b, se, p = res if res else (np.nan, np.nan, 1.0)
                rec.update({f"b_{part}": b, f"lo_{part}": b - Z * se, f"hi_{part}": b + Z * se, f"p_{part}": p})
            rec["binary"] = binary
            rows.append(rec)
    R = pd.DataFrame(rows)
    R["q_train"] = bh(R["p_train"].to_numpy())
    R["train_sig"] = (R["lo_train"] > 0) | (R["hi_train"] < 0)
    R["ho_rep"] = (np.sign(R["b_holdout"]) == np.sign(R["b_train"])) & ((R["lo_holdout"] > 0) | (R["hi_holdout"] < 0))
    R["support"] = R["n_ev_train"] >= 10
    R["contract"] = R["predictor"].map(CONTRACT).fillna("KXHIGHNY bracket")
    R["settleable"] = R["predictor"].isin(SETTLEABLE) | (R["predictor"].str.startswith(("tmax_gt", "bracket_", "rain")) & (R["predictor"] != "rain_ge_0.25in"))
    R["found"] = R["train_sig"] & R["ho_rep"] & R["support"] & (R["q_train"] < 0.10) & R["settleable"]
    R.to_csv(OUT / "results.csv", index=False, float_format="%.4g")

    pd.set_option("display.width", 250, "display.max_rows", 200)
    cols = ["series", "predictor", "n_ev_train", "b_train", "lo_train", "hi_train", "q_train",
            "n_ev_holdout", "b_holdout", "lo_holdout", "hi_holdout", "train_sig", "ho_rep", "settleable", "found"]
    print(f"tests: {len(R)}  train-sig: {R.train_sig.sum()}  q<0.10: {(R.q_train < 0.10).sum()}  holdout-replicating: {(R.train_sig & R.ho_rep).sum()}")
    print(R[cols].round({"b_train": 0, "lo_train": 0, "hi_train": 0, "b_holdout": 0, "lo_holdout": 0, "hi_holdout": 0, "q_train": 3}).to_string(index=False))

    # backtests + month-dummy robustness for FOUND binary rows (and any holdout-replicating one)
    for _, r in R[R["found"] | (R["train_sig"] & R["ho_rep"])].iterrows():
        df = S[r.series]
        P = predictors(df)
        X = pd.concat([design(df), P[MAINS.get(r.predictor, []) + [r.predictor]]], axis=1)
        month = pd.get_dummies(pd.to_datetime(df["date"]).dt.month, prefix="m", drop_first=True).astype(float)
        Xm = pd.concat([X.drop(columns=["sin1", "cos1", "sin2", "cos2"]), month], axis=1)
        out = {}
        for part in ("train", "holdout"):
            m = X.notna().all(axis=1) & (df["split"] == part)
            out[part] = fit(df.loc[m, "revenue"], Xm[m], r.predictor)
        print(f"\n{r.series}/{r.predictor}: month-dummy robustness train={out['train']} holdout={out['holdout']}")
        if r.binary:
            # leave-one-event-out on holdout: is the replication one storm?
            m = X.notna().all(axis=1) & (df["split"] == "holdout")
            loo = [fit(df.loc[m & (df.index != i), "revenue"], X[m & (df.index != i)], r.predictor)[0]
                   for i in df.index[m & P[r.predictor].astype(bool)]]
            print(f"  holdout leave-one-event-out beta range [{min(loo):.0f}, {max(loo):.0f}]")
            print("  backtest:", {k: (round(v, 2) if isinstance(v, float) else v) for k, v in hedge_backtest(df, P, r.predictor, r.b_train).items()})

    # basis: GHCN vs the repo's station (Open-Meteo) series
    st = pd.read_parquet(BACKEND / "fixtures" / "weather_station.parquet")
    st["date"] = pd.to_datetime(st["date"]).dt.date
    g = ghcn()
    j = st.set_index("date").join(g[["PRCP", "TMAX"]], how="inner")
    print("\nbasis GHCN vs fixture: rain>=0.01 agree", ((j.precipitation_sum >= 0.01) == (j.PRCP >= 0.01)).mean().round(3),
          " tmax corr", np.corrcoef(j.temperature_2m_max, j.TMAX)[0, 1].round(3),
          " mean diff (fixture - GHCN)", (j.temperature_2m_max - j.TMAX).mean().round(2))


if __name__ == "__main__":
    main()
