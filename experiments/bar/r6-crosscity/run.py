"""R6 crosscity: does storm/snow/heat at REMOTE Kalshi-settled stations move Penn Station / MSG demand?

Run from backend/:  .venv/bin/python ../experiments/bar/r6-crosscity/run.py

Outcomes (log):
  dewey_0p5km   Dewey visits, balanced stores <= 0.5 km of MSG        train 2024-01..2025-03, holdout 2025-04..2026-09
  dewey_msgzip  Dewey visits, balanced stores in the MSG ZIP basket   (same split)
  mta_penn      MTA entries at 34 St-Penn (164 + 318), daily, ctrl log(system)   train 2022-23, holdout 2024
  mta_penn_eve  same, 17-24h only, ctrl log(system 17-24h)
Events: GHCN-D at the Kalshi settlement stations (CLIORD, CLIDCA, CLIBOS, CLIPHL, ATL, DEN; placebo PHX, LAX):
  rain >= 0.5 in, snow >= 1 in, thunder (GHCN WT03), heat (tmax >= 95 F; PHX >= 110, LAX >= 90),
  plus hub_storm = any of ORD/DCA/BOS/PHL/ATL with rain>=0.5 | snow>=1 | thunder.  Lag 0 and lag 1.
Controls: DOW, year-month FE, holiday, MSG home game, Central Park rain>=0.01, rain>=0.5, snow>=1, tmax, tmax^2,
  prior-day CP rain.  HAC(7).  BH at 10% over every train fit (placebo cities included).
Only aggregates are written; no venue names, ids or addresses.
"""
from __future__ import annotations

import importlib.util
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

_spec = importlib.util.spec_from_file_location("r2agg", ROOT / "experiments/bar/r2-aggregate/run.py")
r2agg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(r2agg)

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
OUT = Path(__file__).resolve().parent
Z = 1.645
CITIES = ["ORD", "DCA", "BOS", "PHL", "ATL", "DEN", "PHX", "LAX"]
PLACEBO = {"PHX", "LAX"}
HUBS = ["ORD", "DCA", "BOS", "PHL", "ATL"]
HEAT = {"PHX": 110, "LAX": 90}
SPLITS = {"dewey": (date(2024, 1, 1), date(2025, 3, 31), date(2026, 9, 27)),
          "mta": (date(2022, 1, 1), date(2023, 12, 31), date(2024, 12, 31))}


# ------------------------------------------------------------------ weather
def ghcn(k: str) -> pd.DataFrame:
    w = pd.read_csv(CACHE / f"r6crosscity_ghcn_{k}.csv", low_memory=False)
    w = w[w.DATE >= "2021-12-01"]
    out = pd.DataFrame({"prcp": w.PRCP.values / 254, "snow": w.get("SNOW", pd.Series(np.nan, index=w.index)).values / 25.4,
                        "tmax": w.TMAX.values / 10 * 9 / 5 + 32, "thunder": w.get("WT03", pd.Series(np.nan, index=w.index)).notna().values},
                       index=pd.to_datetime(w.DATE).dt.date)
    return out


def events() -> pd.DataFrame:
    ev = {}
    for k in CITIES:
        w = ghcn(k)
        ev[f"{k}_rain05"] = w.prcp >= 0.5
        if k != "LAX":
            ev[f"{k}_snow1"] = w.snow.fillna(0) >= 1
        ev[f"{k}_thunder"] = w.thunder
        ev[f"{k}_heat"] = w.tmax >= HEAT.get(k, 95)
    e = pd.DataFrame(ev)
    e["HUB_storm"] = np.column_stack([e[f"{k}_rain05"] | e[f"{k}_snow1"] | e[f"{k}_thunder"] for k in HUBS]).any(axis=1)
    return e.astype(bool)


def nyc() -> pd.DataFrame:
    w = ghcn("NYC")
    c = pd.DataFrame(index=w.index)
    c["cp_rain"] = (w.prcp >= 0.01).astype(float)
    c["cp_rain05"] = (w.prcp >= 0.5).astype(float)
    c["cp_snow1"] = (w.snow >= 1).astype(float)
    c["cp_tmax"] = (w.tmax - 60) / 10
    c["cp_tmax2"] = c.cp_tmax ** 2
    c["cp_rain_lag1"] = c.cp_rain.shift(1)
    return c


# ------------------------------------------------------------------ outcomes
def dewey() -> pd.DataFrame:
    con = duckdb.connect()
    con.execute(f"""
        create table w as select ID_STORE id, DATE_RANGE_START::date ws,
            lpad(trim(POSTAL_CODE::varchar), 5, '0') zip, LATITUDE lat, LONGITUDE lon,
            from_json(VISITS_BY_DAY, '["INTEGER"]') v
        from '{r2agg.GLOB}'""")
    con.execute("""create table st as select id, any_value(zip) zip, avg(lat) lat, avg(lon) lon, count(*) nwk,
                   avg((list_min(v) = list_max(v))::int) flat from w group by id""")
    nweeks = con.execute("select count(distinct ws) from w").fetchone()[0]
    lat, lon = r2agg.MSG_LAT, r2agg.MSG_LON
    con.execute(f"""
        create table keep as select *, 6371 * 2 * asin(sqrt(pow(sin(radians(lat - {lat}) / 2), 2)
              + cos(radians(lat)) * cos(radians({lat})) * pow(sin(radians(lon - ({lon})) / 2), 2))) km
        from st where nwk = {nweeks} and flat < 0.05""")
    z = r2agg.MSG_ZIPS
    df = con.execute(f"""
        with d as (select w.id, w.ws + (i - 1)::int as date, w.v[i] x from w join keep using (id), range(1, 8) r(i))
        select date, sum(case when km <= 0.5 then x end) dewey_0p5km, sum(case when zip in {z} then x end) dewey_msgzip,
               sum(case when zip not in {z} and km > 2 then x end) dewey_rest
        from d join keep using (id) group by date order by date""").df()
    print("dewey stores:", con.execute(f"select sum((km<=0.5)::int), sum((zip in {z})::int), sum((zip not in {z} and km>2)::int) from keep").fetchone())
    df["date"] = pd.to_datetime(df.date).dt.date
    g = r2agg.games()[["home_game"]]
    df = df.set_index("date").join(g)
    a, _, b = SPLITS["dewey"]
    return df[(df.index >= a) & (df.index <= b)]


def mta() -> pd.DataFrame:
    st = pd.read_parquet(CACHE / "r4mh_stations.parquet")
    sy = pd.read_parquet(CACHE / "r4mh_system.parquet")
    for d in (st, sy):
        d["ts"] = pd.to_datetime(d.transit_timestamp)
        d["date"], d["hr"] = d.ts.dt.date, d.ts.dt.hour
    st = st[st.station_complex_id.isin(["164", "318"])]
    out = pd.DataFrame({
        "mta_penn": st.groupby("date").r.sum(), "sys": sy.groupby("date").r.sum(),
        "mta_penn_eve": st[st.hr >= 17].groupby("date").r.sum(), "sys_eve": sy[sy.hr >= 17].groupby("date").r.sum()})
    g = pd.read_csv(CACHE / "msg_games_2022_2025.csv", parse_dates=["date"])
    g["home_game"] = g.knicks_home_game | g.rangers_home_game
    out = out.join(g.set_index(g.date.dt.date)[["home_game"]])
    a, _, b = SPLITS["mta"]
    return out[(out.index >= a) & (out.index <= b)]


OUTCOMES = {"dewey_0p5km": ("dewey", None), "dewey_msgzip": ("dewey", None),
            "mta_penn": ("mta", "sys"), "mta_penn_eve": ("mta", "sys_eve")}


# ------------------------------------------------------------------ fit
def design(f: pd.DataFrame, flag: pd.Series, ctrl: str | None, rel: str | None = None) -> pd.DataFrame:
    ts = pd.to_datetime(pd.Series(f.index, index=f.index))
    X = pd.get_dummies(ts.dt.day_of_week, prefix="dow", drop_first=True).astype(float)
    X = X.join(pd.get_dummies(ts.dt.strftime("%Y%m"), prefix="ym", drop_first=True).astype(float))
    X.insert(0, "const", 1.0)
    X["holiday"] = pd.Series(f.index, index=f.index).isin(config.HOLIDAYS).astype(float)
    X["home_game"] = f.home_game.fillna(False).astype(float)
    X = X.join(f[["cp_rain", "cp_rain05", "cp_snow1", "cp_tmax", "cp_tmax2", "cp_rain_lag1"]])
    if ctrl:
        X["log_ctrl"] = np.log(f[ctrl].astype(float))
    if rel:
        X["log_rest"] = np.log(f[rel].astype(float))
    X["flag"] = flag.astype(float)
    return X.loc[:, (X.nunique() > 1) | (X.columns == "const")]


def fit1(y, X):
    return sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)


def est(f, ycol, flag, ctrl, rel=None):
    n = int(flag.sum())
    X = design(f, flag, ctrl, rel)
    if "flag" not in X or n < 3:
        return dict(n=n, pct=np.nan, lo=np.nan, hi=np.nan, p=np.nan)
    r = fit1(np.log(f[ycol].astype(float)), X)
    b, se = r.params["flag"], r.bse["flag"]
    return dict(n=n, pct=100 * b, lo=100 * (b - Z * se), hi=100 * (b + Z * se), p=r.pvalues["flag"])


def run() -> None:
    ev, cp = events(), nyc()
    frames = {"dewey": dewey().join(cp), "mta": mta().join(cp)}
    rows = []
    for ycol, (src, ctrl) in OUTCOMES.items():
        F = frames[src]
        a, te, b = SPLITS[src]
        for name in ev.columns:
            for lag in (0, 1):
                flag_all = ev[name].shift(lag).reindex(F.index).fillna(False).astype(bool)
                r = {"outcome": ycol, "event": name, "lag": lag, "placebo_city": name[:3] in PLACEBO}
                for sp, m in (("train", F.index <= te), ("holdout", F.index > te)):
                    for k, v in est(F[m], ycol, flag_all[m], ctrl).items():
                        r[f"{sp}_{k}"] = v
                rows.append(r)
    t = pd.DataFrame(rows)
    t.loc[t.train_n < 10, "train_p"] = np.nan  # below the event-count floor: not a test
    t["train_bh"] = r2agg.bh(t.train_p)
    t["holdout_bh"] = r2agg.bh(t.holdout_p.where(t.train_p.notna()))
    sig = lambda sp: (t[f"{sp}_lo"] > 0) | (t[f"{sp}_hi"] < 0)
    t["train_pass"] = sig("train") & (t.train_n >= 10)
    t["holdout_pass"] = sig("holdout") & (np.sign(t.holdout_pct) == np.sign(t.train_pct))
    t["found"] = t.train_pass & t.holdout_pass & (t.train_bh <= 0.10)
    t.to_csv(OUT / "results.csv", index=False, float_format="%.4g")
    pd.set_option("display.width", 250, "display.max_rows", 500)
    ntest = int(t.train_p.notna().sum())
    print(f"\ntests (train fits with n_ev >= 10): {ntest}")
    cols = ["outcome", "event", "lag", "train_n", "train_pct", "train_lo", "train_hi", "train_p", "train_bh",
            "holdout_n", "holdout_pct", "holdout_lo", "holdout_hi", "holdout_p", "found"]
    print("\nTrain-nominal-significant (90% CI excl 0):")
    print(t[t.train_pass][cols].round(3).to_string())
    print("\nHolding sign + significant in BOTH periods (ignoring BH):")
    print(t[t.train_pass & t.holdout_pass][cols].round(3).to_string())
    print("\nFOUND:", int(t.found.sum()))
    # nominal significance rate, real cities vs placebo (calibration)
    tt = t[t.train_p.notna()]
    print("\nnominal p<0.10 share, train: real-city", round((tt[~tt.placebo_city].train_p < .1).mean(), 3),
          "placebo-city", round((tt[tt.placebo_city].train_p < .1).mean(), 3))
    print("both-period same-sign-sig share: real", round((tt[~tt.placebo_city].train_pass & tt[~tt.placebo_city].holdout_pass).mean(), 3),
          "placebo", round((tt[tt.placebo_city].train_pass & tt[tt.placebo_city].holdout_pass).mean(), 3))
    checks(t, ev, frames)
    hedges = [backtest(frames[OUTCOMES[o][0]], o, e, l, ev) for o, e, l in t.loc[t.found, ["outcome", "event", "lag"]].itertuples(index=False)]
    if hedges:
        h = pd.DataFrame(hedges)
        h.to_csv(OUT / "hedge.csv", index=False, float_format="%.4g")
        print("\nHEDGE:\n", h.round(3).to_string())


def checks(t, ev, frames) -> None:
    """Falsification for the headline hub composite and every both-period hit: lead +3 placebo, and the Penn-specific
    (relative to rest-of-NYC Dewey) spec. Not counted as extra hypotheses."""
    keys = {("dewey_0p5km", "HUB_storm", 0), ("dewey_msgzip", "HUB_storm", 0), ("mta_penn", "HUB_storm", 0), ("mta_penn_eve", "HUB_storm", 0)}
    keys |= set(map(tuple, t.loc[t.train_pass & t.holdout_pass, ["outcome", "event", "lag"]].values))
    print("\nCHECKS: lead+3 placebo (should be null) | Dewey relative-to-rest spec")
    for o, e, l in sorted(keys):
        src, ctrl = OUTCOMES[o]
        F = frames[src]
        te = SPLITS[src][1]
        out = []
        for sp, m in (("train", F.index <= te), ("holdout", F.index > te)):
            lead = ev[e].shift(-3).reindex(F.index).fillna(False).astype(bool)
            r = est(F[m], o, lead[m], ctrl)
            s = f"{sp} lead3 {r['pct']:+.2f} [{r['lo']:+.2f},{r['hi']:+.2f}]"
            if src == "dewey":
                flag = ev[e].shift(l).reindex(F.index).fillna(False).astype(bool)
                rr = est(F[m], o, flag[m], None, rel="dewey_rest")
                s += f"  rel {rr['pct']:+.2f} [{rr['lo']:+.2f},{rr['hi']:+.2f}]"
                rr = est(F[m], "dewey_rest", flag[m], None)
                s += f"  rest-of-NYC {rr['pct']:+.2f} [{rr['lo']:+.2f},{rr['hi']:+.2f}]"
            dry = m & (F.cp_rain == 0) & (F.cp_rain_lag1 == 0)
            flag = ev[e].shift(l).reindex(F.index).fillna(False).astype(bool)
            rr = est(F[dry], o, flag[dry], ctrl)
            s += f"  dryNYC {rr['pct']:+.2f} [{rr['lo']:+.2f},{rr['hi']:+.2f}] n={rr['n']}"
            out.append(s)
        print(f"  {o:13s} {e:12s} lag{l}: " + " | ".join(out))


def backtest(F, o, e, lag, ev) -> dict:
    """Train-fit beta in visits/entries; buy the side paying on the bad outcome at train freq + 0.02 + fee."""
    src, ctrl = OUTCOMES[o]
    te = SPLITS[src][1]
    flag = ev[e].shift(lag).reindex(F.index).fillna(False).astype(bool)
    tr, ho = F.index <= te, F.index > te
    y = F[o].astype(float)
    b = fit1(y[tr], design(F[tr], flag[tr], ctrl)).params["flag"]
    pt = flag[tr].mean()
    pay = flag[ho] if b < 0 else ~flag[ho]
    p = (pt if b < 0 else 1 - pt) + 0.02
    pnl = abs(b) * (pay.astype(float) - p - 0.07 * p * (1 - p))
    Xh = design(F[ho], flag[ho], ctrl).drop(columns="flag")
    resid = y[ho] - sm.OLS(y[ho], Xh).fit().fittedvalues
    return {"outcome": o, "event": e, "lag": lag, "beta": b, "price": p, "days": int(ho.sum()),
            "sd_unhedged": resid.std(), "sd_hedged": (resid + pnl.values).std(),
            "p5_unhedged": resid.quantile(.05), "p5_hedged": (resid + pnl.values).quantile(.05)}


if __name__ == "__main__":
    run()
