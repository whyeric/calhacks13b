"""R2 aggregate: do Kalshi-settleable events move SUMMED Dewey visit series?

Run from backend/:  .venv/bin/python ../experiments/bar/r2-aggregate/run.py

Builds daily aggregate visit series from the raw Dewey restaurants/bars export (balanced
panel: stores present all 143 weeks with <5% flat "weekly/7" weeks), regresses each on each
event flag with DOW + year-month fixed effects + holiday (+ MSG home game control for weather
events), HAC(7) errors, on train 2024-01-01..2025-03-31 and an independent holdout refit
2025-04-01..2026-09-27. Events are from the official GHCN Central Park record (USW00094728,
the NWS station Kalshi settles KXRAIN/KXHIGHNY on) and ESPN/fixture Knicks/Rangers schedules.

Only aggregates are written; no venue names, ids or addresses.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app import config  # noqa: E402
from app.data import sports  # noqa: E402

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
OUT = Path(__file__).resolve().parent
GLOB = str(ROOT / "data/01a16ff2-6017-7e10-86ac-94bf02853813/*.parquet")
START, TRAIN_END, END = date(2024, 1, 1), date(2025, 3, 31), date(2026, 9, 27)
Z = 1.645
TICKET = 35.0  # $/visit, as in round 1, for the hedge backtest only
MSG_LAT, MSG_LON = config.MSG_LATLON
MSG_ZIPS = ("10001", "10018", "10119", "10120", "10121", "10122", "10123", "10199")
NIGHT_ZIPS = ("10002", "10003", "10009", "10011", "10012", "10013", "10014")
CAFE_RE = r".*(coffee|cafe|café|espresso).*"
ICE_RE = r".*(ice cream|gelato|frozen yogurt|creamery|dessert).*"


# ------------------------------------------------------------------ series
def series() -> tuple[pd.DataFrame, dict]:
    con = duckdb.connect()
    con.execute(f"""
        create table w as select ID_STORE id, DATE_RANGE_START::date ws, NAICS_CODE naics,
            lpad(trim(POSTAL_CODE::varchar), 5, '0') zip, LATITUDE lat, LONGITUDE lon,
            lower(LOCATION_NAME) nm, from_json(VISITS_BY_DAY, '["INTEGER"]') v
        from '{GLOB}'""")
    con.execute("""
        create table st as select id, any_value(naics) naics, any_value(zip) zip,
            avg(lat) lat, avg(lon) lon, any_value(nm) nm, count(*) nwk,
            avg((list_min(v) = list_max(v))::int) flat
        from w group by id""")
    nweeks = con.execute("select count(distinct ws) from w").fetchone()[0]
    con.execute(f"""
        create table keep as select *,
            6371 * 2 * asin(sqrt(pow(sin(radians(lat - {MSG_LAT}) / 2), 2)
              + cos(radians(lat)) * cos(radians({MSG_LAT})) * pow(sin(radians(lon - ({MSG_LON})) / 2), 2))) km
        from st where nwk = {nweeks} and flat < 0.05""")
    baskets = {
        "full_service_722511": "naics = '722511'",
        "limited_service_722513": "naics = '722513'",
        "drinking_722410": "naics = '722410'",
        "cafe_keyword": f"regexp_matches(nm, '{CAFE_RE}')",
        "icecream_keyword": f"regexp_matches(nm, '{ICE_RE}')",
        "msg_zip_cluster": f"zip in {MSG_ZIPS}",
        "msg_within_0p5km": "km <= 0.5",
        "nightlife_bars": f"naics = '722410' and zip in {NIGHT_ZIPS}",
    }
    meta = {"stores_total": con.execute("select count(*) from st").fetchone()[0],
            "stores_balanced": con.execute("select count(*) from keep").fetchone()[0]}
    cols = ", ".join(f"sum(case when {cond} then x end) as {k}" for k, cond in baskets.items())
    counts = ", ".join(f"sum(({cond})::int) as {k}" for k, cond in baskets.items())
    meta["n_stores"] = con.execute(f"select {counts} from keep").df().iloc[0].astype(int).to_dict()
    df = con.execute(f"""
        with d as (
          select w.id, w.ws + (i - 1)::int as date, w.v[i] x
          from w join keep using (id), range(1, 8) r(i))
        select date, {cols} from d join keep k using (id) group by date order by date""").df()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[(df.date >= START) & (df.date <= END)].reset_index(drop=True), meta


# ------------------------------------------------------------------ events
def weather() -> pd.DataFrame:
    w = pd.concat(pd.read_csv(CACHE / f"ghcn_{y}.csv") for y in (2024, 2025, 2026))
    w["date"] = pd.to_datetime(w["DATE"]).dt.date
    return w.set_index("date")[["PRCP", "SNOW", "TMAX", "TMIN"]]


def games() -> pd.DataFrame:
    client = sports.ScoreboardClient(cache_dir=CACHE / "espn")
    out = {}
    for team in sports.TEAMS:
        early = sports.schedule_frame(sports.fetch_games(sports.TEAMS[team], START, date(2024, 10, 31), client))
        late = sports.read_schedule(team)
        sched = pd.concat([early, late[late["date"] > "2024-10-31"]])
        sched["home_win"] = sched["home_win"].map(lambda v: None if v is None or v == "" or pd.isna(v) else bool(v))
        out[team] = sports.daily_flags(sched, START, END).set_index("date")
    g = pd.DataFrame(index=out["knicks"].index)
    g["knicks_home"], g["rangers_home"] = out["knicks"]["home_game"], out["rangers"]["home_game"]
    g["home_game"] = g["knicks_home"] | g["rangers_home"]
    g["home_win"] = out["knicks"]["home_win"] | out["rangers"]["home_win"]
    return g


EVENTS = {  # name: (function of frame -> bool, control set)
    "rain_0.01in": (lambda f: f.PRCP >= 0.01, "weather"),
    "rain_1mm": (lambda f: f.PRCP >= 0.04, "weather"),
    "hot_gt80": (lambda f: f.TMAX > 80, "weather"),
    "hot_gt85": (lambda f: f.TMAX > 85, "weather"),
    "hot_gt90": (lambda f: f.TMAX > 90, "weather"),
    "cold_le32": (lambda f: f.TMAX <= 32, "weather"),
    "cold_le40": (lambda f: f.TMAX <= 40, "weather"),
    "snow_any": (lambda f: f.SNOW >= 0.1, "weather"),
    "knicks_home": (lambda f: f.knicks_home, "games"),
    "rangers_home": (lambda f: f.rangers_home, "games"),
    "msg_home_game": (lambda f: f.home_game, "games"),
    "msg_home_win": (lambda f: f.home_win, "win"),
}


def design(f: pd.DataFrame, flag: pd.Series, kind: str) -> pd.DataFrame:
    ts = pd.to_datetime(f["date"])
    X = pd.get_dummies(ts.dt.day_of_week, prefix="dow", drop_first=True).astype(float)
    X = X.join(pd.get_dummies(ts.dt.strftime("%Y%m"), prefix="ym", drop_first=True).astype(float))
    X.insert(0, "const", 1.0)
    X["holiday"] = f["date"].isin(config.HOLIDAYS).astype(float)
    if kind in ("weather", "win"):
        X["home_game"] = f["home_game"].astype(float)
    X["flag"] = flag.astype(float)
    return X.loc[:, (X.nunique() > 1) | (X.columns == "const")]


def fit(y: pd.Series, X: pd.DataFrame):
    return sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)


def run() -> None:
    agg, meta = series()
    f = agg.set_index("date").join(weather()).join(games()).reset_index()
    assert f[["PRCP", "TMAX"]].notna().all().all(), "weather gaps"
    f["split"] = np.where(f["date"] <= TRAIN_END, "train", "holdout")
    names = list(meta["n_stores"])
    rows = []
    for s in names:
        for ev, (fn, kind) in EVENTS.items():
            flag = fn(f).astype(bool)
            r = {"series": s, "event": ev}
            for sp in ("train", "holdout"):
                m = f["split"] == sp
                if kind == "win":
                    m &= f["home_game"]
                y = np.log(f.loc[m, s].astype(float))
                X = design(f[m], flag[m], kind)
                n_ev = int(flag[m].sum())
                if "flag" not in X or n_ev < 3:
                    r.update({f"{sp}_n": n_ev, f"{sp}_pct": np.nan, f"{sp}_lo": np.nan, f"{sp}_hi": np.nan, f"{sp}_p": np.nan})
                    continue
                res = fit(y, X)
                b, se = res.params["flag"], res.bse["flag"]
                r.update({f"{sp}_n": n_ev, f"{sp}_pct": 100 * b, f"{sp}_lo": 100 * (b - Z * se),
                          f"{sp}_hi": 100 * (b + Z * se), f"{sp}_p": res.pvalues["flag"]})
            rows.append(r)
    t = pd.DataFrame(rows)
    for sp in ("train", "holdout"):
        t[f"{sp}_bh"] = bh(t[f"{sp}_p"])
    sig = lambda sp: (t[f"{sp}_lo"] > 0) | (t[f"{sp}_hi"] < 0)
    t["train_pass"] = sig("train") & (t["train_n"] >= 10)
    t["holdout_pass"] = sig("holdout") & (np.sign(t["holdout_pct"]) == np.sign(t["train_pct"]))
    t["found"] = t["train_pass"] & t["holdout_pass"] & (t["train_bh"] <= 0.10)
    t.to_csv(OUT / "results.csv", index=False, float_format="%.4g")
    pd.set_option("display.width", 250)
    print(meta)
    print(f"tests: {t['train_p'].notna().sum()} train fits")
    print(t.round(3).to_string())
    print("\nFOUND:\n", t[t.found].round(3).to_string())
    robustness(f)
    hedges = [backtest(f, *rw) for rw in t.loc[t.found, ["series", "event"]].itertuples(index=False)]
    if hedges:
        h = pd.DataFrame(hedges)
        h.to_csv(OUT / "hedge.csv", index=False, float_format="%.4g")
        print("\nHEDGE:\n", h.round(2).to_string())


def robustness(f: pd.DataFrame, n_perm: int = 200) -> None:
    """Headline rain (>= 0.01 in) checks: week fixed effects instead of year-month, and a placebo
    that permutes the rain flag within year-month (train). Not counted as extra hypotheses."""
    rng = np.random.default_rng(0)
    rain = f["PRCP"] >= 0.01
    print("\nROBUSTNESS (rain_0.01in): week-FE pct [train, holdout]; placebo |t| 95th pct vs real |t| (train)")
    for s in ["full_service_722511", "limited_service_722513", "drinking_722410", "msg_zip_cluster", "nightlife_bars"]:
        out = []
        for sp in ("train", "holdout"):
            m = f["split"] == sp
            X = design(f[m], rain[m], "weather"); X = X[[c for c in X.columns if not c.startswith("ym_")]]
            wk = pd.to_datetime(f.loc[m, "date"]).dt.to_period("W-SUN").astype(str)
            X = X.join(pd.get_dummies(wk, prefix="wk", drop_first=True).astype(float))
            r = fit(np.log(f.loc[m, s].astype(float)), X)
            out.append(f"{100 * r.params['flag']:+.2f} [{100 * (r.params['flag'] - Z * r.bse['flag']):+.2f},{100 * (r.params['flag'] + Z * r.bse['flag']):+.2f}]")
        m = f["split"] == "train"
        y = np.log(f.loc[m, s].astype(float))
        real = abs(fit(y, design(f[m], rain[m], "weather")).tvalues["flag"])
        ym = pd.to_datetime(f.loc[m, "date"]).dt.strftime("%Y%m")
        ts = []
        for _ in range(n_perm):
            perm = rain[m].groupby(ym).transform(lambda v: pd.Series(rng.permutation(v.values), index=v.index))
            ts.append(abs(fit(y, design(f[m], perm, "weather")).tvalues["flag"]))
        print(f"  {s:24s} weekFE {out[0]} | {out[1]}   placebo |t| p95={np.quantile(ts, 0.95):.2f}, real |t|={real:.2f}, perm p={np.mean(np.array(ts) >= real):.3f}")


def bh(p: pd.Series) -> pd.Series:
    """Benjamini-Hochberg adjusted p over the non-missing entries."""
    q = pd.Series(np.nan, index=p.index)
    v = p.dropna().sort_values()
    m = len(v)
    adj = (v * m / np.arange(1, m + 1))[::-1].cummin()[::-1].clip(upper=1)
    q[v.index] = adj
    return q


def backtest(f: pd.DataFrame, s: str, ev: str) -> dict:
    """Train-fit level beta ($ = visits x TICKET, per average store); buy the side that pays on the bad outcome."""
    fn, kind = EVENTS[ev]
    flag = fn(f).astype(bool)
    n_st = 1  # per-basket $; scale is irrelevant to the SD ratio
    rev = f[s].astype(float) * TICKET / n_st
    tr = f["split"] == "train"
    ho = ~tr
    if kind == "win":
        tr &= f["home_game"]
        ho &= f["home_game"]
    b = fit(rev[tr], design(f[tr], flag[tr], kind)).params["flag"]
    p_train = flag[tr].mean()
    # b < 0: event hurts, buy YES on the event; b > 0: buy NO (pays when the event does not happen).
    pay = flag[ho] if b < 0 else ~flag[ho]
    p = (p_train if b < 0 else 1 - p_train) + 0.02
    fee = 0.07 * p * (1 - p)
    pnl = abs(b) * (pay.astype(float) - p - fee)
    # Compare on deseasonalised holdout revenue (the part a hedge can address): residual of a no-flag fit.
    Xh = design(f[ho], flag[ho], kind).drop(columns="flag")
    resid = rev[ho] - sm.OLS(rev[ho], Xh).fit().fittedvalues
    return {"series": s, "event": ev, "beta_usd": b, "price": p, "days": int(ho.sum()),
            "sd_unhedged": resid.std(), "sd_hedged": (resid + pnl).std(),
            "p5_unhedged": resid.quantile(0.05), "p5_hedged": (resid + pnl).quantile(0.05),
            "hedge_cost_per_day": pnl.mean(),
            "raw_sd_unhedged": rev[ho].std(), "raw_sd_hedged": (rev[ho] + pnl).std()}


if __name__ == "__main__":
    run()
