"""R6 wrigley: Cubs/Blackhawks/Bulls playoff home games -> crowds -> Divvy trips near the venue,
plus displacement at Loop / lakefront / rest-of-city stations. Chicago Divvy 2014-2017.

Inputs (scratchpad r2-cache, see fetch.py and the duckdb one-liner in RESULTS.md):
  r6wrigley_starts.parquet / r6wrigley_ends.parquet  station x hour trip counts
  r6wrigley_stations.parquet                         station id, name, lat, lon
  r6wrigley_games.csv, r6wrigley_ghcn_midway.csv     ESPN schedules, NOAA GHCN Midway

    backend/.venv/bin/python experiments/bar/r6-wrigley/wrigley.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.holiday import USFederalHolidayCalendar

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fetch import CACHE, games, weather  # noqa: E402

Z = 1.645
RNG = np.random.default_rng(6)
LINES: list[str] = []


def say(s=""):
    print(s, flush=True)
    LINES.append(s)


def hav(lat, lon, a, b):
    p1, p2 = np.radians(lat), np.radians(a)
    x = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(b - lon) / 2) ** 2
    return 2 * 6371000 * np.arcsin(np.sqrt(x))


# ---------- stations -> bands ----------
WRIGLEY, UC, LOOP = (41.9484, -87.6553), (41.8807, -87.6742), (41.8820, -87.6278)
LAKE_RE = ("Lake Shore|Streeter|Theater on the Lake|Shedd|Field Museum|Museum Campus|Lakefront|"
           "Harbor|Beach")


def bands() -> pd.Series:
    s = pd.read_parquet(CACHE / "r6wrigley_stations.parquet")
    dw, du, dl = hav(s.lat, s.lon, *WRIGLEY), hav(s.lat, s.lon, *UC), hav(s.lat, s.lon, *LOOP)
    lake = s.name.str.contains(LAKE_RE, case=False)
    b = np.select(
        [dw <= 450, dw <= 1000, dw <= 2000, du <= 700, du <= 1500, lake, dl <= 1000],
        ["W1_wrigley_450m", "W2_wrigley_1km", "W3_wrigley_2km", "U1_uc_700m", "U2_uc_1.5km",
         "LAKE_lakefront", "LOOP_1km"], "REST_city")
    return pd.Series(b, index=s.sid)


BANDS = ["W1_wrigley_450m", "W2_wrigley_1km", "W3_wrigley_2km", "U1_uc_700m", "U2_uc_1.5km",
         "LOOP_1km", "LAKE_lakefront", "REST_city"]


def hourly() -> pd.DataFrame:
    """band x hour trips (starts + ends), casual (Customer) share kept too."""
    b = bands()
    parts = []
    for f in ("r6wrigley_starts.parquet", "r6wrigley_ends.parquet"):
        x = pd.read_parquet(CACHE / f)
        x["band"] = x.sid.map(b).fillna("REST_city")
        parts.append(x.groupby(["band", "h"])[["n", "cust"]].sum())
    h = parts[0].add(parts[1], fill_value=0).reset_index()
    h = h[(h.h >= "2014-01-01") & (h.h < "2018-01-01")]
    return h


# ---------- calendar / events ----------
SPECIAL = {"hawks_parade": ["2015-06-18"], "cubs_parade": ["2016-11-04"],
           "ws_g7_night": ["2016-11-02"], "ws_g7_after": ["2016-11-03"]}


def calendar(g: pd.DataFrame) -> pd.DataFrame:
    days = pd.date_range("2014-01-01", "2017-12-31", name="d")
    c = pd.DataFrame(index=days)
    g = g.copy()
    g["d"] = g.start.dt.normalize()
    # 2017 NLDS G4 was rained out on 10-10 and played 10-11; ESPN lists both
    g = g[~((g.team == "chc") & (g.d == "2017-10-10"))]

    def flag(m):
        return c.index.isin(g.loc[m, "d"]).astype(float)

    cubs, uc = (g.team == "chc"), g.league.isin(["nhl", "nba"]) & (g.venue == "United Center")
    c["cubs_reg_home"] = flag(cubs & g.home & (g.stype == 2))
    c["cubs_po_home"] = flag(cubs & g.home & (g.stype == 3))
    c["cubs_po_away"] = flag(cubs & ~g.home & (g.stype == 3))
    c["uc_reg"] = flag(uc & (g.stype == 2))
    c["uc_po"] = flag(uc & (g.stype == 3))
    c["sox_home"] = flag((g.team == "chw") & g.home)
    for k, ds in SPECIAL.items():
        c[k] = c.index.isin(pd.to_datetime(ds)).astype(float)
    c.loc[c.ws_g7_night == 1, "cubs_po_away"] = 0.0  # G7 night is reported as its own event
    w = weather().set_index("DATE")
    c["rain"] = (w.PRCP.reindex(days).fillna(0) >= 3).astype(float)  # GHCN tenths mm; 0.01 in
    t = w.TMAX.reindex(days).interpolate() / 10
    c["tmax"], c["tmax2"] = t, (t - 15) ** 2 / 10
    c["holiday"] = c.index.isin(USFederalHolidayCalendar().holidays("2014", "2018")).astype(float)
    c["ym"] = c.index.strftime("%Y-%m")
    c["dow"] = c.index.dayofweek
    return c, g


EVENTS = ["cubs_reg_home", "cubs_po_home", "cubs_po_away", "uc_reg", "uc_po"]
CTRL = ["sox_home", "rain", "tmax", "tmax2", "holiday"] + list(SPECIAL)


def fit(y: pd.Series, c: pd.DataFrame, terms: list[str]):
    d = c.loc[y.index]
    X = pd.concat([d[terms + CTRL],
                   pd.get_dummies(d.ym, prefix="ym", drop_first=True, dtype=float),
                   pd.get_dummies(d.dow.astype(str) + "_" + d.index.month.astype(str), prefix="dowm",
                                  drop_first=True, dtype=float)], axis=1)
    X = X.loc[:, X.std() > 0]
    X = sm.add_constant(X)
    return sm.OLS(np.log(y), X).fit(cov_type="HAC", cov_kwds={"maxlags": 7})


def row(r, term, band, period, c, idx):
    if term not in r.params:
        return None
    b, se = r.params[term], r.bse[term]
    return {"band": band, "term": term, "period": period, "beta": b, "lo": b - Z * se,
            "hi": b + Z * se, "p": r.pvalues[term], "n_ev": int(c.loc[idx, term].sum())}


def bh(p: np.ndarray) -> np.ndarray:
    n = len(p)
    o = np.argsort(p)
    q = p[o] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(n)
    out[o] = np.minimum(q, 1)
    return out


def pct(b):
    return 100 * (np.exp(b) - 1)


# ---------- series math (MLB 2015-17 formats) ----------
P_HOME = 0.54  # per-game win prob at home in an even matchup (MLB home win rate ~54%)


def series(n_games: int, pattern: str, p_home=P_HOME, edge=0.0):
    """Exact enumeration. pattern: 'H'/'A' per game from our perspective.
    Returns P(win), E[home games], dist of home games."""
    need = n_games // 2 + 1
    out = {}  # (home games played, won) -> prob

    def rec(i, w, l, hg, pr):
        if w == need or l == need:
            out[(hg, w == need)] = out.get((hg, w == need), 0) + pr
            return
        home = pattern[i] == "H"
        q = (p_home if home else 1 - p_home) + edge
        rec(i + 1, w + 1, l, hg + home, pr * q)
        rec(i + 1, w, l + 1, hg + home, pr * (1 - q))
    rec(0, 0, 0, 0, 1.0)
    pw = sum(v for (h, won), v in out.items() if won)
    eh = sum(h * v for (h, won), v in out.items())
    return pw, eh, out


ROUNDS = [("WC", 1, "H", "A"), ("DS", 5, "HHAAH", "AAHHA"), ("CS", 7, "HHAAAHH", "AAHHHAA"),
          ("WS", 7, "HHAAAHH", "AAHHHAA")]


def season_dist(hca: dict, edge=0.0, wc=True):
    """Distribution of total playoff home games H given HCA per round, via enumeration."""
    dist = {0: 1.0}  # alive states: home games so far -> prob (alive)
    final = {}
    for name, n, ph, pa in ROUNDS:
        if name == "WC" and not wc:
            continue
        pat = ph if hca[name] else pa
        _, _, o = series(n, pat, edge=edge)
        nd = {}
        for h0, p0 in dist.items():
            for (hg, won), v in o.items():
                if won and name != "WS":
                    nd[h0 + hg] = nd.get(h0 + hg, 0) + p0 * v
                else:
                    final[h0 + hg] = final.get(h0 + hg, 0) + p0 * v
        dist = nd
    for h, v in dist.items():
        final[h] = final.get(h, 0) + v
    return final


def main():
    g = games()
    c, g = calendar(g)
    h = hourly()
    h["d"] = h.h.dt.normalize()
    day = h.groupby(["band", "d"]).n.sum().unstack(0).reindex(c.index).dropna(how="all")
    tot = day.sum(axis=1)
    bad = tot < 0.2 * tot.rolling(15, center=True, min_periods=5).median()  # export gaps
    say(f"Dropped {int(bad.sum())} partial-export days: " + ", ".join(str(d.date()) for d in day.index[bad]))
    day = day[~bad]
    say("# R6 wrigley output")
    nst = bands().value_counts()
    say("Stations per band: " + ", ".join(f"{b} {nst.get(b, 0)}" for b in BANDS))
    say("Mean daily trips (starts+ends) per band: " +
        ", ".join(f"{b} {day[b].mean():,.0f}" for b in BANDS))
    po = g[(g.team == "chc") & (g.stype == 3)].copy()
    say("Cubs playoff games (home/away) by season: " + ", ".join(
        f"{s}: {int(x.home.sum())}/{int((~x.home).sum())}" for s, x in po.groupby("season")))
    ucp = g[g.league.isin(["nhl", "nba"]) & (g.stype == 3) & g.home]
    say("UC playoff home games by year: " + ", ".join(
        f"{y}: {len(x)}" for y, x in ucp.groupby(ucp.d.dt.year)))

    # ---- 1. main fits: train/holdout per venue ----
    periods = {"cubs_train": ("2014-01-01", "2016-12-31"), "cubs_hold": ("2017-01-01", "2017-12-31"),
               "uc_train": ("2014-01-01", "2015-12-31"), "uc_hold": ("2016-01-01", "2017-12-31"),
               "s2015": ("2015-01-01", "2015-12-31"), "s2016": ("2016-01-01", "2016-12-31"),
               "s2017": ("2017-01-01", "2017-12-31"), "all": ("2014-01-01", "2017-12-31")}
    rows, fits = [], {}
    for band in BANDS:
        for per, (a, b) in periods.items():
            y = day.loc[a:b, band]
            y = y[y > 0]
            r = fit(y, c, EVENTS)
            fits[(band, per)] = r
            for t in EVENTS + list(SPECIAL):
                x = row(r, t, band, per, c, y.index)
                if x:
                    rows.append(x)
    R = pd.DataFrame(rows)
    # BH family: train tests, cubs terms on cubs_train, uc terms on uc_train, all 8 bands
    fam = R[R.term.isin(EVENTS) & (((R.period == "cubs_train") & R.term.str.startswith("cubs")) |
                                   ((R.period == "uc_train") & R.term.str.startswith("uc")))].copy()
    fam["p_bh"] = bh(fam.p.values)
    R = R.merge(fam[["band", "term", "period", "p_bh"]], how="left")
    R.to_csv(HERE / "uplift.csv", index=False)
    say(f"\nBH family: {len(fam)} train tests (8 bands x 5 event terms), q=0.10")

    say("\n## 1. Per-game uplift, % change in daily trips (log-OLS, year-month FE + DOW x month-of-year FE, weather, HAC7)")
    say("band | term | train %[90CI] n | p_bh | holdout %[90CI] n | verdict")
    verdict = []
    for band in BANDS:
        for t in EVENTS:
            tp, hp = ("cubs_train", "cubs_hold") if t.startswith("cubs") else ("uc_train", "uc_hold")
            a = R[(R.band == band) & (R.term == t) & (R.period == tp)]
            b = R[(R.band == band) & (R.term == t) & (R.period == hp)]
            if a.empty or b.empty:
                continue
            a, b = a.iloc[0], b.iloc[0]
            ok = (a.p_bh < 0.10 and a.n_ev >= 10 and np.sign(a.beta) == np.sign(b.beta)
                  and (b.lo > 0 or b.hi < 0) and (a.lo > 0 or a.hi < 0))
            v = "FOUND" if ok else "not found"
            verdict.append({"band": band, "term": t, "train_pct": pct(a.beta),
                            "train_lo": pct(a.lo), "train_hi": pct(a.hi), "n_train": a.n_ev,
                            "p_bh": a.p_bh, "hold_pct": pct(b.beta), "hold_lo": pct(b.lo),
                            "hold_hi": pct(b.hi), "n_hold": b.n_ev, "verdict": v})
            say(f"{band} | {t} | {pct(a.beta):+.1f} [{pct(a.lo):+.1f},{pct(a.hi):+.1f}] {a.n_ev} | "
                f"{a.p_bh:.3f} | {pct(b.beta):+.1f} [{pct(b.lo):+.1f},{pct(b.hi):+.1f}] {b.n_ev} | {v}")
    V = pd.DataFrame(verdict)
    V.to_csv(HERE / "verdict.csv", index=False)

    say("\n## 1a. Relative to rest of city: log(band) - log(REST_city), same model")
    rel = []
    for band in ["W1_wrigley_450m", "W2_wrigley_1km", "U1_uc_700m", "U2_uc_1.5km", "LOOP_1km",
                 "LAKE_lakefront"]:
        for t, (tp, hp) in (("cubs_po_home", ("cubs_train", "cubs_hold")),
                            ("cubs_reg_home", ("cubs_train", "cubs_hold")),
                            ("uc_po", ("uc_train", "uc_hold")), ("uc_reg", ("uc_train", "uc_hold"))):
            out = []
            for per in (tp, hp):
                a, b = periods[per]
                y = (day.loc[a:b, band] / day.loc[a:b, "REST_city"]).dropna()
                y = y[y > 0]
                x = row(fit(y, c, EVENTS), t, band + "/REST", per, c, y.index)
                rel.append(x)
                out.append(f"{pct(x['beta']):+.1f} [{pct(x['lo']):+.1f},{pct(x['hi']):+.1f}] n={x['n_ev']}")
            say(f"{band}/REST | {t} | train {out[0]} | holdout {out[1]}")
    pd.DataFrame(rel).to_csv(HERE / "uplift_relative.csv", index=False)

    say("\n## 1e. Casual (Customer) vs subscriber trips, cubs_po_home, train / holdout")
    hb = h.copy()
    hb["sub"] = hb.n - hb.cust
    for kind in ("cust", "sub"):
        dk = hb.groupby(["band", "d"])[kind].sum().unstack(0).reindex(day.index)
        for band in ["W1_wrigley_450m", "W2_wrigley_1km", "U1_uc_700m"]:
            out = []
            for t, (tp, hp) in (("cubs_po_home", ("cubs_train", "cubs_hold")),
                                ("uc_po", ("uc_train", "uc_hold"))):
                for per in (tp, hp):
                    a, b = periods[per]
                    y = dk.loc[a:b, band].fillna(0) + 1
                    x = row(fit(y, c, EVENTS), t, band, per, c, y.index)
                    out.append(f"{t} {per.split('_')[1]} {pct(x['beta']):+.0f}% "
                               f"[{pct(x['lo']):+.0f},{pct(x['hi']):+.0f}]")
            say(f"{kind} {band} (mean {dk[band].mean():.0f}/day): " + "; ".join(out))

    say("\n## 1b. Cubs playoff home uplift by season (each season fitted alone), W1/W2/LOOP/LAKE")
    for band in ["W1_wrigley_450m", "W2_wrigley_1km", "W3_wrigley_2km", "LOOP_1km",
                 "LAKE_lakefront", "REST_city"]:
        s = []
        for per in ("s2015", "s2016", "s2017"):
            x = R[(R.band == band) & (R.term == "cubs_po_home") & (R.period == per)]
            x2 = R[(R.band == band) & (R.term == "cubs_reg_home") & (R.period == per)]
            if not x.empty:
                x, x2 = x.iloc[0], x2.iloc[0]
                s.append(f"{per[1:]}: po {pct(x.beta):+.0f}% [{pct(x.lo):+.0f},{pct(x.hi):+.0f}] "
                         f"n={x.n_ev}; reg {pct(x2.beta):+.0f}%")
        say(f"{band}: " + " | ".join(s))

    say("\n## 1c. Playoff minus regular-season home (Wald, full 2014-17 fit)")
    for band in BANDS:
        r = fits[(band, "all")]
        for a_, b_ in (("cubs_po_home", "cubs_reg_home"), ("uc_po", "uc_reg")):
            L = pd.Series(0.0, index=r.params.index)
            L[a_], L[b_] = 1, -1
            est = float(L @ r.params)
            se = float(np.sqrt(L @ r.cov_params() @ L))
            say(f"{band} {a_}-{b_}: {100 * est:+.1f} log pts [{100 * (est - Z * se):+.1f},"
                f"{100 * (est + Z * se):+.1f}]")

    say("\n## 1d. Special days (full 2014-17 fit, log pts -> %)")
    for band in BANDS:
        r = fits[(band, "all")]
        say(f"{band}: " + ", ".join(
            f"{k} {pct(r.params[k]):+.0f}% (se {100 * r.bse[k]:.0f}lp)" for k in SPECIAL
            if k in r.params))

    # ---- 2. placebos ----
    say("\n## 2. Placebos (full 2014-17 fit, real event dummies kept in)")
    gd = set(c.index[c[EVENTS].sum(axis=1) > 0])  # dates with any modelled game event
    special = set(pd.to_datetime(sum(SPECIAL.values(), [])))
    pr = []
    for name, src, shifts in (("cubs_po_home+4/6wk (Nov, same DOW)", "cubs_po_home", (28, 42)),
                              ("cubs_po_home -1 day", "cubs_po_home", (-1,)),
                              ("uc_po+13wk (Jul-Sep, same DOW)", "uc_po", (91,)),
                              ("uc_po -1 day", "uc_po", (-1,))):
        base = c.index[c[src] == 1]
        pdts = sorted({d + pd.Timedelta(days=k) for d in base for k in shifts} - gd - special)
        c2 = c.copy()
        c2["placebo"] = c2.index.isin(pdts).astype(float)
        for band in (["W1_wrigley_450m", "W2_wrigley_1km", "LOOP_1km", "LAKE_lakefront"]
                     if src.startswith("cubs") else ["U1_uc_700m", "U2_uc_1.5km", "LOOP_1km"]):
            y = day[band]
            y = y[y > 0]
            r = fit(y, c2, EVENTS + ["placebo"])
            b, se = r.params["placebo"], r.bse["placebo"]
            pr.append({"placebo": name, "band": band, "beta": b, "lo": b - Z * se,
                       "hi": b + Z * se, "p": r.pvalues["placebo"], "n": len(pdts)})
            say(f"{name} | {band}: {pct(b):+.1f}% [{pct(b - Z * se):+.1f},{pct(b + Z * se):+.1f}] "
                f"p={r.pvalues['placebo']:.2f} n={len(pdts)}")
    # permutation: shuffle cubs_po_home within its year-months (Oct/Nov non-game days)
    for band, term in (("W1_wrigley_450m", "cubs_po_home"), ("LOOP_1km", "cubs_po_home"),
                       ("U1_uc_700m", "uc_po")):
        y = day[band]
        y = y[y > 0]
        t_real = fits[(band, "all")].tvalues[term]
        ts = []
        months = c.loc[c[term] == 1, "ym"].value_counts()
        for _ in range(200):
            c2 = c.copy()
            c2[term] = 0.0
            for ym, k in months.items():
                pool = c2.index[(c2.ym == ym) & ~c2.index.isin(gd) & ~c2.index.isin(special)]
                c2.loc[RNG.choice(pool, k, replace=False), term] = 1.0
            ts.append(fit(y, c2, EVENTS).tvalues[term])
        ts = np.abs(ts)
        say(f"permutation {term} within ym | {band}: real t={t_real:+.2f}, perm |t| p95="
            f"{np.quantile(ts, .95):.2f}, perm p={(1 + (ts >= abs(t_real)).sum()) / 201:.3f}")
    pd.DataFrame(pr).to_csv(HERE / "placebo.csv", index=False)

    # ---- 3. hourly profile near Wrigley on playoff home dates ----
    say("\n## 3. Hourly excess trips at W1+W2 (vs median of same ym x DOW non-game days)")
    hw = h[h.band.isin(["W1_wrigley_450m", "W2_wrigley_1km"])].groupby("h")[["n", "cust"]].sum()
    hw = hw.reindex(pd.date_range("2014-01-01", "2017-12-31 23:00", freq="h"), fill_value=0)
    hw["d"], hw["hr"] = hw.index.normalize(), hw.index.hour
    hw["ym"], hw["dow"] = hw.d.dt.strftime("%Y-%m"), hw.d.dt.dayofweek
    cubs_days = c.index[c[["cubs_reg_home", "cubs_po_home", "cubs_po_away"]].sum(axis=1) > 0]
    nongame = ~hw.d.isin(cubs_days) & ~hw.d.isin(special)  # UC games barely move W1/W2
    base = hw[nongame].groupby(["ym", "dow", "hr"])[["n", "cust"]].median()
    hw = hw.join(base, on=["ym", "dow", "hr"], rsuffix="_base")
    hw["ex"], hw["exc"] = hw.n - hw.n_base, hw.cust - hw.cust_base
    pod = c.index[c.cubs_po_home == 1]
    st = g[(g.team == "chc") & (g.stype == 3) & g.home].set_index("d").start
    prof = []
    for d in pod:
        x = hw[hw.d == d]
        s0 = st.loc[d].hour if not isinstance(st.loc[d], pd.Series) else st.loc[d].iloc[0].hour
        win = x[(x.hr >= s0 - 2) & (x.hr <= s0 + 4)]
        post = x[(x.hr >= s0 + 3) & (x.hr <= s0 + 5)]
        prof.append({"date": d.date(), "start_hr": s0, "day_ex": x.ex.sum(), "day_base": x.n_base.sum(),
                     "win_ex": win.ex.sum(), "post_ex": post.ex.sum(), "cust_ex": x.exc.sum()})
    P = pd.DataFrame(prof)
    say(P.to_string(index=False))
    say(f"mean per playoff home date: +{P.day_ex.mean():.0f} trips/day vs base {P.day_base.mean():.0f} "
        f"(+{100 * P.day_ex.mean() / P.day_base.mean():.0f}%), of which casual +{P.cust_ex.mean():.0f}")
    reg = c.index[(c.cubs_reg_home == 1) & (c.index.month.isin([9]))]
    xr = hw[hw.d.isin(reg)].groupby("d")[["ex", "n_base"]].sum()
    say(f"Sept regular-season home dates: +{xr.ex.mean():.0f} trips/day vs base {xr.n_base.mean():.0f}")
    hp = hw[hw.d.isin(pod)].groupby("hr")[["ex", "n_base"]].mean()
    say("avg hourly excess on playoff home dates (hr: excess/base): " +
        " ".join(f"{i}:{r.ex:+.0f}/{r.n_base:.0f}" for i, r in hp.iterrows() if 10 <= i <= 23 or i <= 1))

    # ---- 4. $ at stake per round ----
    say("\n## 4. Exposure per round (MLB 2015-17 format: WC 1 game, DS 2-2-1, CS/WS 2-3-2)")
    vw1 = V[(V.band == "W1_wrigley_450m") & (V.term == "cubs_po_home")].iloc[0]
    vw2 = V[(V.band == "W2_wrigley_1km") & (V.term == "cubs_po_home")].iloc[0]
    fa = fits[("W1_wrigley_450m", "all")]
    u_all = pct(fa.params["cubs_po_home"]) / 100
    u_lo = pct(fa.params["cubs_po_home"] - Z * fa.bse["cubs_po_home"]) / 100
    say(f"Pooled 2015-17 W1 uplift per playoff home game: {100 * u_all:+.0f}% (90% lo {100 * u_lo:+.0f}%)")
    for nm, n, ph, pa in ROUNDS:
        for hca in (True, False):
            pw, eh, o = series(n, ph if hca else pa)
            say(f"  {nm} HCA={hca!s:5}: P(win)={pw:.2f} E[home]={eh:.2f}")
    # bar cluster: assumption-driven $ translation
    BAR_DAY = 6000      # assumed avg non-game October day revenue for one Wrigleyville bar
    N_BARS = 60         # assumed bars/restaurants within ~450 m of Wrigley
    per_game_bar = u_all * BAR_DAY
    say(f"Assumptions: foot traffic elasticity 1 vs W1 bike trips; one bar = ${BAR_DAY:,}/normal Oct day; "
        f"{N_BARS} bars within 450 m.")
    say(f"=> per playoff home game: +${per_game_bar:,.0f} per bar, +${per_game_bar * N_BARS:,.0f} cluster "
        f"(lower 90% bound +${u_lo * BAR_DAY:,.0f} per bar)")
    divvy_trip_rev = 4.0  # ~$9.95 24h pass / ~2.5 rides, 2015-17
    say(f"Divvy operator: +{P.cust_ex.mean():.0f} casual trips/game x ${divvy_trip_rev:.0f} = "
        f"${P.cust_ex.mean() * divvy_trip_rev:,.0f}/game at W1+W2 (negligible)")
    scen = {"division winner, top-2 seed (HCA DS/CS, WS coin)": {"WC": True, "DS": True, "CS": True, "WS": True},
            "division winner, 3rd seed": {"WC": True, "DS": False, "CS": True, "WS": True},
            "wild card host": {"WC": True, "DS": False, "CS": False, "WS": False},
            "wild card visitor": {"WC": False, "DS": False, "CS": False, "WS": False}}
    rows4 = []
    for nm, hca in scen.items():
        wc = nm.startswith("wild")
        dist = season_dist(hca, wc=wc)
        eh = sum(k * v for k, v in dist.items())
        sd = np.sqrt(sum((k - eh) ** 2 * v for k, v in dist.items()))
        say(f"{nm}: E[H]={eh:.2f} SD={sd:.2f}; per bar E=${eh * per_game_bar:,.0f} "
            f"SD=${sd * per_game_bar:,.0f}; P(H): " +
            " ".join(f"{k}:{v:.2f}" for k, v in sorted(dist.items())))
        rows4.append({"scenario": nm, "E_H": eh, "SD_H": sd, "per_bar_E": eh * per_game_bar,
                      "per_bar_SD": sd * per_game_bar, "dist": json.dumps({int(k): round(v, 4) for k, v in dist.items()})})
    # $ at stake on winning each round, top seed (no WC): E[H | advance] - E[H | lose]
    hca = scen["division winner, top-2 seed (HCA DS/CS, WS coin)"]
    say("At stake per round, top seed, per bar (= E[future home games if win this round] x U):")
    rem = 0.0
    stake = {}
    for nm, n, ph, pa in reversed(ROUNDS[1:]):
        pw, eh, _ = series(n, ph if hca[nm] else pa)
        stake[nm] = rem
        rem = eh + pw * rem
    for nm in ("DS", "CS", "WS"):
        say(f"  win {nm}: {stake[nm]:.2f} more home games = ${stake[nm] * per_game_bar:,.0f}/bar, "
            f"${stake[nm] * per_game_bar * N_BARS:,.0f} cluster")
    pd.DataFrame(rows4).to_csv(HERE / "exposure.csv", index=False)

    # ---- 5. hedge backtest (simulated; Kalshi had no markets 2015-17) ----
    say("\n## 5. Hedge: 'hosts >= k' ladder (KXMLBPLAYOFFHOST) vs round-by-round series NO")
    # Top seed scenario; fair prices from the model, buy at fair+0.02 plus fee 0.07 p(1-p)
    dist = season_dist(hca, wc=False)
    ks, ps = np.array(sorted(dist)), np.array([dist[k] for k in sorted(dist)])
    sims = RNG.choice(ks, size=20000, p=ps / ps.sum())
    rev = sims * per_game_bar
    out = {"unhedged": rev}
    for strikes in ((2, 4, 6, 8), tuple(range(1, 12))):
        hedge = np.zeros_like(rev, dtype=float)
        for k in strikes:
            p_yes = ps[ks >= k].sum()
            p_no = 1 - p_yes
            cost = min(p_no + 0.02, 0.99) + 0.07 * p_no * (1 - p_no)
            size = per_game_bar * (8 / len(strikes) if strikes == (2, 4, 6, 8) else 1)
            hedge += size * ((sims < k).astype(float) - cost)
        out[f"ladder NO {strikes[0]}..{strikes[-1]}"] = rev + hedge
    for nm, x in out.items():
        say(f"{nm}: mean ${x.mean():,.0f} SD ${x.std():,.0f} p5 ${np.quantile(x, .05):,.0f}")
    say("Actual seasons (H, unhedged per bar, hedged w/ even ladder at model fair prices):")
    for yr, H in ((2015, 4), (2016, 8), (2017, 5)):
        hedge = sum(2 * per_game_bar * ((H < k) - (min(1 - ps[ks >= k].sum() + 0.02, .99)
                                                    + 0.07 * ps[ks >= k].sum() * (1 - ps[ks >= k].sum())))
                    for k in (2, 4, 6, 8))
        say(f"  {yr}: H={H} unhedged ${H * per_game_bar:,.0f} hedged ${H * per_game_bar + hedge:,.0f}")

    # ---- 6. Kalshi markets for the Cubs (basis) ----
    say("\n## 6. Kalshi Cubs advancement markets (cached by r5-markets)")
    m = json.load(open(CACHE / "r5markets_markets.json"))
    cd = json.load(open(CACHE / "r5markets_candles.json"))
    for ser in ("KXMLBPLAYOFFS", "KXMLBPLAYOFFHOST", "KXMLBSERIES", "KXMLBNLCSQUAL", "KXMLBNL", "KXMLB"):
        for x in m[ser]["markets"]:
            t = x["ticker"]
            if "CHC" not in t:
                continue
            cs = cd.get(t, [])
            first = last = None
            for k in cs:
                pr_ = k.get("price", {})
                v = pr_.get("close") or pr_.get("close_dollars")
                if v is None:
                    ya, yb = k.get("yes_ask", {}), k.get("yes_bid", {})
                    a_ = ya.get("close") or ya.get("close_dollars")
                    b_ = yb.get("close") or yb.get("close_dollars")
                    if a_ and b_:
                        v = (float(a_) + float(b_)) / 2
                if v is not None:
                    first = first if first is not None else float(v)
                    last = float(v)
            say(f"{t} | {x.get('yes_sub_title')} | result={x.get('result')} | first={first} last={last}"
                f" | n_candles={len(cs)}")
    (HERE / "output.txt").write_text("\n".join(LINES) + "\n")


if __name__ == "__main__":
    main()
