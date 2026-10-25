"""R7 deferral: does rain destroy NYC going-out demand, or just move it (to tomorrow, to indoor areas)?

Run from backend/:  .venv/bin/python ../experiments/bar/r7-deferral/run.py   (after fetch.py)

Mechanism stated before fitting (see RESULTS.md): a rain day cancels some outings; if a share of
them is rebooked (next day, the other weekend day) or redirected (indoor neighborhoods), the
weekly net loss is smaller than the sum of the daily losses and a daily KXRAIN hedge over-hedges.

Series (daily): Dewey balanced-panel visit totals for Manhattan bars (722410), full-service
restaurants (722511), limited-service (722513, a takeout proxy; no delivery data exists here),
an "outdoor" basket (722410+722511 in West Village / Meatpacking-Chelsea / Hell's Kitchen ZIPs
10014, 10011, 10036, 10019) and an "indoor/transit" basket (same NAICS in Midtown East, Garment/
Penn, FiDi ZIPs 10017, 10022, 10018, 10001, 10004, 10005, 10006, 10038); MTA subway (sayj-mze2);
TLC high-volume FHV trips citywide (2024-01..2025-12 only).
Weather: NOAA GHCN Central Park USW00094728 (KXRAIN settlement station), rain = PRCP >= 0.01.

Tests, each on train 2024-01..2025-03 and refit on holdout 2025-04..2026-09:
  T1 next-day rebound: rain_{t-1} in a daily model that also has rain_t, rain_{t+1}, tmax_t, snow_t.
  T2 within-weekend: Sat rain -> Sun visits (lag on Sundays); Sun rain -> Sat visits (lead on Saturdays).
  T3 weekly net: log weekly total on # rain days vs the daily rain effect x day share; the gap is
     the displaced share. Ratio CI by week-block bootstrap.
  T4 spatial: log(outdoor) - log(indoor) on rain_t (all days, weekends).
  Placebos (not in the BH family): rain_{t-7} and rain_{t+7}, which should show nothing.
Errors HAC(7) daily, HAC(4) weekly; year-month FE, DOW, holiday. Only aggregates are written.
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

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
OUT = Path(__file__).resolve().parent
GLOB = str(ROOT / "data/01a16ff2-6017-7e10-86ac-94bf02853813/*.parquet")
START, TRAIN_END, END = date(2024, 1, 1), date(2025, 3, 31), date(2026, 9, 27)
SPLITS = {"train": (START, TRAIN_END), "holdout": (date(2025, 4, 1), END)}
Z = 1.645
CHECK = 35.0  # $ per Dewey visit, as in earlier rounds
OUTDOOR = ("10014", "10011", "10036", "10019")
INDOOR = ("10017", "10022", "10018", "10001", "10004", "10005", "10006", "10038")
DEWEY = ["bars", "fullsvc", "limited", "outdoor", "indoor", "dining"]
SERIES = ["bars", "fullsvc", "limited", "outdoor", "indoor", "dining", "subway", "fhv"]
rng = np.random.default_rng(7)


# ------------------------------------------------------------------ data
def dewey() -> tuple[pd.DataFrame, dict]:
    con = duckdb.connect()
    con.execute(f"""
        create table w as select ID_STORE id, DATE_RANGE_START::date ws, NAICS_CODE naics,
            POSTAL_CODE zip, from_json(VISITS_BY_DAY, '["INTEGER"]') v from '{GLOB}'""")
    nweeks = con.execute("select count(distinct ws) from w").fetchone()[0]
    con.execute(f"""
        create table keep as select id, any_value(naics) naics, mode(zip) zip from w group by id
        having count(*) = {nweeks} and avg((list_min(v) = list_max(v))::int) < 0.05""")
    o, i = (",".join(f"'{z}'" for z in zs) for zs in (OUTDOOR, INDOOR))
    sit = "naics in ('722410', '722511')"
    baskets = {"bars": "naics = '722410'", "fullsvc": "naics = '722511'", "limited": "naics = '722513'",
               "outdoor": f"{sit} and zip in ({o})", "indoor": f"{sit} and zip in ({i})", "dining": sit}
    n = con.execute("select " + ", ".join(f"sum(({c})::int) {k}" for k, c in baskets.items())
                    + " from keep").df().iloc[0].astype(int).to_dict()
    cols = ", ".join(f"sum(case when {c} then x end) {k}" for k, c in baskets.items())
    df = con.execute(f"""
        with d as (select w.id, w.ws + (i - 1)::int as date, w.v[i] x
                   from w join keep using (id), range(1, 8) r(i))
        select date, {cols} from d join keep k using (id) group by date order by date""").df()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.set_index("date").astype(float), n


def frame() -> tuple[pd.DataFrame, dict]:
    d, n = dewey()
    m = pd.read_parquet(CACHE / "r7deferral_mta.parquet")
    m = m[m["mode"] == "Subway"]
    d = d.join(pd.Series(pd.to_numeric(m["count"]).values, index=pd.to_datetime(m["date"]).dt.date,
                         name="subway"))
    t = duckdb.sql(f"select date, trips from '{CACHE}/tlc/fhvhv_*.parquet'").df()
    d = d.join(pd.Series(t.trips.values, index=pd.to_datetime(t.date).dt.date, name="fhv"))
    w = pd.read_csv(CACHE / "r7deferral_ghcn.csv")
    w.index = pd.to_datetime(w.pop("DATE")).dt.date
    w = w[["PRCP", "TMAX", "SNOW"]].astype(float)
    w["rain"] = (w.PRCP >= 0.01).astype(float)
    for k in (1, 7):
        w[f"rain_l{k}"] = w.rain.shift(k)
        w[f"rain_f{k}"] = w.rain.shift(-k)
    w["tmax_l1"] = w.TMAX.shift(1)
    d = d.join(w)
    ts = pd.to_datetime(pd.Series(d.index, index=d.index))
    d["dow"] = ts.dt.day_of_week
    d["ym"] = ts.dt.strftime("%Y%m")
    d["holiday"] = d.index.isin(config.HOLIDAYS).astype(float)
    d["wk"] = (ts - pd.to_timedelta(d["dow"], unit="D")).dt.date  # Monday week start (= Dewey week)
    return d[(d.index >= START) & (d.index <= END)], n


# ------------------------------------------------------------------ fits
def controls(f: pd.DataFrame, dow: bool = True) -> pd.DataFrame:
    X = pd.get_dummies(f["ym"], prefix="ym", drop_first=True).astype(float)
    if dow:
        X = X.join(pd.get_dummies(f["dow"], prefix="dow", drop_first=True).astype(float))
    X.insert(0, "const", 1.0)
    X["holiday"] = f["holiday"]
    X["tmax"] = f["TMAX"]
    X["tmax2"] = (f["TMAX"] - 65) ** 2
    X["snow"] = (f["SNOW"] > 0).astype(float)
    return X


def ols(y, X, lags):
    ok = y.notna() & X.notna().all(axis=1)
    X = X[ok].loc[:, X[ok].nunique() > 1].assign(const=1.0)
    return sm.OLS(y[ok], X).fit(cov_type="HAC", cov_kwds={"maxlags": lags}, use_t=False), ok


def daily_terms(f: pd.DataFrame, model: str) -> pd.DataFrame:
    sat, sun = (f.dow == 5).astype(float), (f.dow == 6).astype(float)
    if model == "static":  # rain_t only: the "daily effect" a KXRAIN hedge is sized on
        return pd.DataFrame({"rain": f.rain})
    if model == "lag":     # T1 + placebos
        return pd.DataFrame({"rain": f.rain, "rain_l1": f.rain_l1, "rain_f1": f.rain_f1,
                             "rain_l7": f.rain_l7, "rain_f7": f.rain_f7, "tmax_l1": f.tmax_l1})
    if model == "weekend":  # T2
        return pd.DataFrame({"rain": f.rain, "sat_to_sun": f.rain_l1 * sun, "lag_other": f.rain_l1 * (1 - sun),
                             "sun_to_sat": f.rain_f1 * sat, "lead_other": f.rain_f1 * (1 - sat),
                             "tmax_l1": f.tmax_l1})
    raise ValueError(model)


def fit_daily(f, s, model):
    X = controls(f).join(daily_terms(f, model))
    return ols(np.log(f[s]), X, 7)


def weekly(f: pd.DataFrame, s: str) -> pd.DataFrame:
    g = f.groupby("wk")
    w = pd.DataFrame({"y": g[s].sum(min_count=7), "n": g[s].count(), "nrain": g.rain.sum(),
                      "TMAX": g.TMAX.mean(), "SNOW": g.SNOW.max(), "holiday": g.holiday.sum()})
    w = w[w.n == 7]
    w["nrain_next"] = g.rain.sum().shift(-1).reindex(w.index)  # placebo: next week's rain days
    w["ym"] = g.ym.agg(lambda x: x.mode().iloc[0])  # month holding 4+ of the 7 days (the Thursday's)
    return w


def fit_weekly(w):
    X = controls(w, dow=False)
    X["nrain"] = w.nrain
    return ols(np.log(w.y), X, 4)


def rain_share(f, s):
    """Mean share of its week's total that a rain day carries (DOW-weighted), for daily->weekly units."""
    tot = f.groupby("wk")[s].transform("sum")
    return float((f[s] / tot)[f.rain == 1].mean())


def lnpct(b):
    return 100 * (np.exp(b) - 1)


def row(res, term, n_ev, **kw):
    b, se = res.params[term], res.bse[term]
    return {**kw, "term": term, "n_events": int(n_ev), "pct": lnpct(b), "lo": lnpct(b - Z * se),
            "hi": lnpct(b + Z * se), "p": float(res.pvalues[term])}


def net_ratio(f, s, B=400):
    """Weekly net loss per rain day vs the static daily loss x day share; point and week-block bootstrap."""
    def one(ff):
        rd, _ = fit_daily(ff, s, "static")
        rw, _ = fit_weekly(weekly(ff, s))
        daily = (np.exp(rd.params["rain"]) - 1) * rain_share(ff, s)  # weekly fraction lost per rain day, summed daily
        wk = np.exp(rw.params["nrain"]) - 1                          # weekly fraction lost per rain day, net
        return daily, wk
    d0, w0 = one(f)
    groups = {k: g for k, g in f.groupby("wk")}
    weeks = list(groups)
    draws = []
    for _ in range(B):
        pick = rng.choice(len(weeks), size=len(weeks), replace=True)
        parts = [groups[weeks[i]].assign(wk=j) for j, i in enumerate(pick)]  # duplicated weeks stay distinct
        try:
            draws.append(one(pd.concat(parts, ignore_index=True)))
        except Exception:  # noqa: BLE001  (a draw can lose all variation in some FE)
            continue
    a = np.array(draws)
    return d0, w0, a


# ------------------------------------------------------------------ hedge
def hedge(f, s, beta_d, sizes, price):
    """Holdout daily and weekly $ for a typical sit-down venue: buy KXRAIN YES every day, sized at
    k x (same-day $ loss on a rain day) for each multiplier k in `sizes` (k=0 is no hedge)."""
    h = f[(f.index >= SPLITS["holdout"][0])].copy()
    h["rev"] = h[s] * CHECK
    base = h.groupby(["ym", "dow"])["rev"].transform("mean")   # within-month DOW baseline
    h["dev"] = h.rev - base
    size = -beta_d * base                                      # $ lost on a rain day -> contracts at $1
    fee = 0.07 * price * (1 - price)
    pnl_per = h.rain - price - fee                            # per $1 contract, buy YES each day
    out = {}
    for name, k in sizes.items():
        x = h.dev + k * size * pnl_per
        wk = x.groupby(h.wk).sum()
        out[name] = {"k": k, "daily_sd": x.std(), "weekly_sd": wk.std(), "weekly_p5": wk.quantile(0.05),
                     "weekly_mean": wk.mean()}
    return pd.DataFrame(out).T


def bh(p: pd.Series) -> pd.Series:
    v = p.sort_values()
    m = len(v)
    q = (v * m / np.arange(1, m + 1))[::-1].cummin()[::-1].clip(upper=1)
    return q.reindex(p.index)


# ------------------------------------------------------------------ main
def main() -> None:
    d, nven = frame()
    print("venues per basket:", nven)
    rows, ratios = [], []
    for split, (a, b) in SPLITS.items():
        f = d[(d.index >= a) & (d.index <= b)]
        for s in SERIES:
            fs = f[f[s].notna()]
            if len(fs) < 120:
                continue
            r, ok = fit_daily(fs, s, "static")
            rows.append(row(r, "rain", fs.rain[ok].sum(), split=split, series=s, test="T0 daily rain"))
            r, ok = fit_daily(fs, s, "lag")
            rows.append(row(r, "rain_l1", fs.rain_l1[ok].sum(), split=split, series=s, test="T1 next-day rebound"))
            rows.append(row(r, "rain_f1", fs.rain_f1[ok].sum(), split=split, series=s, test="T1b day-before (anticipation)"))
            for t in ("rain_l7", "rain_f7"):
                rows.append(row(r, t, fs[t][ok].sum(), split=split, series=s, test="placebo"))
            # distributed-lag net: rain_t + rain_{t-1} + rain_{t+1}
            L = pd.Series(0.0, index=r.params.index)
            L[["rain", "rain_l1", "rain_f1"]] = 1
            tt = r.t_test(L.values)
            e, se = float(tt.effect[0]), float(tt.sd[0][0])
            rows.append({"split": split, "series": s, "test": "T1c 3-day net (t-1,t,t+1)", "term": "sum",
                         "n_events": int(fs.rain[ok].sum()), "pct": lnpct(e), "lo": lnpct(e - Z * se),
                         "hi": lnpct(e + Z * se), "p": float(tt.pvalue)})
            r, ok = fit_daily(fs, s, "weekend")
            wt = daily_terms(fs, "weekend")[ok]
            rows.append(row(r, "sat_to_sun", wt.sat_to_sun.sum(), split=split, series=s, test="T2 Sat rain -> Sun"))
            rows.append(row(r, "sun_to_sat", wt.sun_to_sat.sum(), split=split, series=s, test="T2 Sun rain -> Sat"))
            w = weekly(fs, s)
            rw, okw = fit_weekly(w)
            rows.append(row(rw, "nrain", len(w), split=split, series=s, test="T3 weekly per rain day"))
            Xp = controls(w, dow=False).assign(nrain=w.nrain, nrain_next=w.nrain_next)
            rp, _ = ols(np.log(w.y), Xp, 4)
            rows.append(row(rp, "nrain_next", len(w), split=split, series=s, test="placebo"))
            d0, w0, draws = net_ratio(fs, s, B=300)
            gap = draws[:, 1] - draws[:, 0]
            p_gap = 2 * min((gap <= 0).mean(), (gap >= 0).mean())
            ratios.append({"split": split, "series": s, "daily_implied_pct_of_week": 100 * d0,
                           "weekly_net_pct": 100 * w0, "net_over_daily": w0 / d0 if d0 else np.nan,
                           "ratio_lo": np.quantile(draws[:, 1] / draws[:, 0], 0.05),
                           "ratio_hi": np.quantile(draws[:, 1] / draws[:, 0], 0.95),
                           "overhedge": d0 / w0 if w0 else np.nan, "gap_pp": 100 * (w0 - d0),
                           "gap_lo": 100 * np.quantile(gap, 0.05), "gap_hi": 100 * np.quantile(gap, 0.95),
                           "p_gap": max(p_gap, 1 / len(draws)), "B": len(draws), "weeks": len(w)})
            rows.append({"split": split, "series": s, "test": "T3b displaced (weekly - daily sum)", "term": "gap",
                         "n_events": len(w), "pct": 100 * (w0 - d0), "lo": 100 * np.quantile(gap, 0.05),
                         "hi": 100 * np.quantile(gap, 0.95), "p": max(p_gap, 1 / len(draws))})
            print(split, s, "done", flush=True)
        # T4 spatial
        for lab, m in (("all days", f.index == f.index), ("weekends", f.dow >= 5)):
            g = f[m].copy()
            g["sp"] = np.log(g.outdoor) - np.log(g.indoor)
            X = controls(g).join(daily_terms(g, "static"))
            r, ok = ols(g.sp, X, 7)
            rows.append(row(r, "rain", g.rain[ok].sum(), split=split, series="outdoor-indoor",
                            test=f"T4 spatial ({lab})"))
    res = pd.DataFrame(rows)
    fam = (res.test != "placebo") & ~res.test.str.startswith("T0")
    for split in SPLITS:
        m = fam & (res.split == split)
        res.loc[m, "q_bh"] = bh(res.loc[m, "p"])
    res["ci_excl0"] = (res.lo > 0) | (res.hi < 0)
    tr = res[res.split == "train"].set_index(["series", "test", "term"])
    ho = res[res.split == "holdout"].set_index(["series", "test", "term"])
    v = tr.join(ho, lsuffix="_tr", rsuffix="_ho", how="left")
    v["found"] = (v.ci_excl0_tr & (v.q_bh_tr <= 0.10) & (v.n_events_tr >= 10) & v.ci_excl0_ho.fillna(False)
                  & (np.sign(v.pct_tr) == np.sign(v.pct_ho)))
    v["found"] = v["found"].astype(object)
    v.loc[v.index.get_level_values("test").isin(["placebo"]) | v.index.get_level_values("test").str.startswith("T0"),
          "found"] = np.nan
    rt = pd.DataFrame(ratios)
    res.to_csv(OUT / "results.csv", index=False)
    v.reset_index().to_csv(OUT / "verdict.csv", index=False)
    rt.to_csv(OUT / "net_ratio.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print(res.round(3).to_string())
    print(v[["n_events_tr", "pct_tr", "lo_tr", "hi_tr", "q_bh_tr", "pct_ho", "lo_ho", "hi_ho", "q_bh_ho", "found"]]
          .round(3).to_string())
    print(rt.round(3).to_string())
    print("BH family size per split:", int((fam & (res.split == "train")).sum()))

    # hedge on the Manhattan sit-down dining basket (bars + full service), per typical venue
    s = "dining"
    tr_f = d[(d.index >= START) & (d.index <= TRAIN_END)]
    r, _ = fit_daily(tr_f, s, "static")
    beta = np.exp(r.params["rain"]) - 1
    rr = rt[(rt.split == "train") & (rt.series == s)].iloc[0]
    k3 = (res.query("split == 'train' and series == @s and term == 'sum'").pct.iloc[0] / 100) / beta
    sizes = {"none": 0.0, "same_day_beta (1.0x)": 1.0, "deferral haircut (0.5x)": 0.5,
             f"3-day net ({k3:.2f}x)": k3, f"weekly net ({rr.net_over_daily:.2f}x)": rr.net_over_daily}
    price = tr_f.rain.mean() + 0.02
    dd = d.copy()
    dd[s] = dd[s] / nven[s]  # typical venue
    hb = hedge(dd, s, beta, sizes, price)
    hb.to_csv(OUT / "hedge.csv")
    print(f"hedge: train daily beta {100 * beta:.2f}%, price {price:.3f}, typical venue {nven[s]} in basket")
    print(hb.round(1).to_string())

    # basis: weekly KXRAINNYCW (total > X in) vs # rain days
    w = d.groupby("wk").agg(nrain=("rain", "sum"), tot=("PRCP", "sum"))
    print("corr(#rain days, weekly total):", round(w.nrain.corr(w.tot), 3),
          {x: round(w.nrain.corr((w.tot > x).astype(float)), 3) for x in (0.5, 1.0, 2.0)})


if __name__ == "__main__":
    main()
