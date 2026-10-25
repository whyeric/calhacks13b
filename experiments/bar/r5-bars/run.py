"""R5 playoffbars: do Manhattan bars fill on Knicks/Rangers PLAYOFF nights, home and away?

Run from backend/:  .venv/bin/python ../experiments/bar/r5-bars/run.py

1. Uplift. Daily aggregate Dewey visits (balanced panel, as in r2-aggregate) for drinking places
   (NAICS 722410) Manhattan-wide and by distance band from MSG, plus full-service restaurants.
   log(visits) ~ DOW + year-month FE + holiday + rain + {reg-season home, reg-season away,
   playoff home, playoff away} game-night flags (either team, ET local date), HAC(7).
   Train 2024-01-01..2025-09-30 (Knicks 2024 R1-R2, Rangers 2024 R1-ECF, Knicks 2025 R1-ECF),
   holdout 2025-10-01..2026-09-27 (Knicks 2026 R1-Finals), refit independently.
2. Exposure. $ per playoff night for a typical bar = uplift x baseline visits/bar x CHECK.
3. Hedge. Before each Knicks series buy "NYK loses series" (NO on the KXNBASERIES/KXNBAEAST/KXNBA
   market) sized to the expected bar revenue from the rounds that advancing would unlock;
   backtest on the 2024-2026 runs and on simulated seasons.

Only aggregates are written; no venue names, ids, addresses or per-venue series.
"""
from __future__ import annotations

import json
from math import comb
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app import config  # noqa: E402

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
ESPN = CACHE / "r5playoffbars_espn"
OUT = Path(__file__).resolve().parent
GLOB = str(ROOT / "data/01a16ff2-6017-7e10-86ac-94bf02853813/*.parquet")
START, TRAIN_END, END = date(2024, 1, 1), date(2025, 9, 30), date(2026, 9, 27)
Z = 1.645
CHECK = 35.0  # assumed $ spend per Dewey visit (same as rounds 1-4)
ET = ZoneInfo("America/New_York")
MSG_LAT, MSG_LON = config.MSG_LATLON
FLAGS = ["reg_home", "reg_away", "po_home", "po_away"]
ROUNDS = {"1st Round": 1, "Semifinals": 2, "2nd Round": 2, "Finals": 3, "Final": 3}


# ------------------------------------------------------------------ visits
def series() -> tuple[pd.DataFrame, dict]:
    con = duckdb.connect()
    con.execute(f"""
        create table w as select ID_STORE id, DATE_RANGE_START::date ws, NAICS_CODE naics,
            LATITUDE lat, LONGITUDE lon, from_json(VISITS_BY_DAY, '["INTEGER"]') v
        from '{GLOB}'""")
    con.execute("""
        create table st as select id, any_value(naics) naics, avg(lat) lat, avg(lon) lon,
            count(*) nwk, avg((list_min(v) = list_max(v))::int) flat
        from w group by id""")
    nweeks = con.execute("select count(distinct ws) from w").fetchone()[0]
    con.execute(f"""
        create table keep as select *,
            6371 * 2 * asin(sqrt(pow(sin(radians(lat - {MSG_LAT}) / 2), 2)
              + cos(radians(lat)) * cos(radians({MSG_LAT})) * pow(sin(radians(lon - ({MSG_LON})) / 2), 2))) km
        from st where nwk = {nweeks} and flat < 0.05""")
    baskets = {
        "bars_all": "naics = '722410'",
        "bars_le0p5km": "naics = '722410' and km <= 0.5",
        "bars_0p5_2km": "naics = '722410' and km > 0.5 and km <= 2",
        "bars_gt2km": "naics = '722410' and km > 2",
        "fullsvc_all": "naics = '722511'",
        "fullsvc_le0p5km": "naics = '722511' and km <= 0.5",
    }
    counts = ", ".join(f"sum(({c})::int) as {k}" for k, c in baskets.items())
    n = con.execute(f"select {counts} from keep").df().iloc[0].astype(int).to_dict()
    cols = ", ".join(f"sum(case when {c} then x end) as {k}" for k, c in baskets.items())
    df = con.execute(f"""
        with d as (select w.id, w.ws + (i - 1)::int as date, w.v[i] x
                   from w join keep using (id), range(1, 8) r(i))
        select date, {cols} from d join keep k using (id) group by date order by date""").df()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[(df.date >= START) & (df.date <= END)].reset_index(drop=True), n


# ------------------------------------------------------------------ games
def games() -> pd.DataFrame:
    rows = []
    for team, abbr in (("knicks", "nyk"), ("rangers", "nyr")):
        for season in (2024, 2025, 2026):
            for st in (2, 3):
                p = ESPN / f"{abbr}_{season}_{st}.json"
                for e in json.loads(p.read_text()).get("events", []):
                    c = e["competitions"][0]
                    me = next(x for x in c["competitors"] if x["team"]["abbreviation"] in ("NY", "NYR"))
                    opp = next(x for x in c["competitors"] if x is not me)
                    note = (c.get("notes") or [{}])[0].get("headline", "")
                    rnd = next((v for k, v in ROUNDS.items() if k in note), None)
                    if note.startswith("NBA Finals") or note.startswith("Stanley Cup Final"):
                        rnd = 4
                    t = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(ET)
                    rows.append({"team": team, "season": season, "playoff": st == 3, "date": t.date(),
                                 "tip_et": t.strftime("%H:%M"), "home": me["homeAway"] == "home",
                                 "opp": opp["team"]["abbreviation"], "win": bool(me.get("winner")),
                                 "round": rnd if st == 3 else 0, "note": note})
    g = pd.DataFrame(rows)
    return g[(g.date >= START) & (g.date <= END)].sort_values("date").reset_index(drop=True)


def day_flags(g: pd.DataFrame, dates: pd.Series) -> pd.DataFrame:
    f = pd.DataFrame({"date": dates})
    for name, m in {"reg_home": ~g.playoff & g.home, "reg_away": ~g.playoff & ~g.home,
                    "po_home": g.playoff & g.home, "po_away": g.playoff & ~g.home}.items():
        f[name] = f["date"].isin(set(g.loc[m, "date"]))
    for r in (1, 2, 3, 4):
        f[f"po_r{r}"] = f["date"].isin(set(g.loc[g.playoff & (g["round"] == r), "date"]))
    f["po_any"] = f.po_home | f.po_away
    # a regular-season game on a playoff night cannot happen (seasons end first); assert it
    assert not (f.po_any & (f.reg_home | f.reg_away)).any()
    return f


def weather() -> pd.DataFrame:
    w = pd.concat(pd.read_csv(CACHE / f"ghcn_{y}.csv") for y in (2024, 2025, 2026))
    w["date"] = pd.to_datetime(w["DATE"]).dt.date
    return w.set_index("date")[["PRCP", "TMAX"]]


# ------------------------------------------------------------------ fits
def design(f: pd.DataFrame, flags: list[str]) -> pd.DataFrame:
    ts = pd.to_datetime(f["date"])
    X = pd.get_dummies(ts.dt.day_of_week, prefix="dow", drop_first=True).astype(float)
    X = X.join(pd.get_dummies(ts.dt.strftime("%Y%m"), prefix="ym", drop_first=True).astype(float))
    X.insert(0, "const", 1.0)
    X["holiday"] = f["date"].isin(config.HOLIDAYS).astype(float)
    X["rain"] = (f["PRCP"] >= 0.01).astype(float)
    for c in flags:
        X[c] = f[c].astype(float)
    X.index = f.index
    return X.loc[:, (X.nunique() > 1) | (X.columns == "const")]


def fit(y, X):
    return sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)


def coef_rows(res, f, mask, s, split, flags, model):
    out = []
    for c in flags:
        if c not in res.params:
            continue
        b, se = res.params[c], res.bse[c]
        out.append({"model": model, "series": s, "split": split, "term": c, "n": int(f.loc[mask, c].sum()),
                    "pct": 100 * b, "lo": 100 * (b - Z * se), "hi": 100 * (b + Z * se), "p": res.pvalues[c]})
    return out


def contrast(res, a, b):
    """Wald test of coefficient a - b."""
    if a not in res.params or b not in res.params:
        return None
    L = pd.Series(0.0, index=res.params.index)
    L[a], L[b] = 1, -1
    t = res.t_test(L.values)
    d, se = float(t.effect[0]), float(t.sd[0][0])
    return d, se, float(t.pvalue)


def bh(p: pd.Series) -> pd.Series:
    q = pd.Series(np.nan, index=p.index)
    v = p.dropna().sort_values()
    m = len(v)
    q[v.index] = (v * m / np.arange(1, m + 1))[::-1].cummin()[::-1].clip(upper=1)
    return q


# ------------------------------------------------------------------ hedge
def series_len_dist(p: float) -> dict[int, float]:
    """Best-of-7 length distribution given a per-game win prob p (independent games)."""
    d = {}
    for n in (4, 5, 6, 7):
        d[n] = comb(n - 1, 3) * (p ** 4 * (1 - p) ** (n - 4) + (1 - p) ** 4 * p ** (n - 4))
    return d


def game_p_from_series_p(q: float) -> float:
    """Invert P(win best-of-7) = q to a per-game p by bisection."""
    lo, hi = 0.01, 0.99
    for _ in range(60):
        mid = (lo + hi) / 2
        win = sum(comb(n - 1, 3) * mid ** 4 * (1 - mid) ** (n - 4) for n in (4, 5, 6, 7))
        lo, hi = (mid, hi) if win < q else (lo, mid)
    return (lo + hi) / 2


def exp_games(q: float) -> float:
    d = series_len_dist(game_p_from_series_p(q))
    return sum(n * w for n, w in d.items())


# Per-series NYK win probabilities before each series. 2025/2026: Kalshi KXNBASERIES / KXNBAEAST /
# KXNBA prices (see RESULTS.md; filled from candlesticks in kalshi_prices()). 2024 has no Kalshi
# markets: an ASSUMED 0.60 per series (stated, not a market price).
ASSUMED_P = 0.60


def run() -> None:
    agg, nst = series()
    g = games()
    g.drop(columns=["note"]).to_csv(OUT / "games.csv", index=False)
    f = agg.merge(day_flags(g, agg["date"]), on="date").set_index("date").join(weather()).reset_index()
    assert f["PRCP"].notna().all(), "weather gaps"
    f["split"] = np.where(f["date"] <= TRAIN_END, "train", "holdout")
    names = list(nst)
    print("stores per basket:", nst)
    print(g[g.playoff].groupby(["team", "season", "round", "home"]).size().unstack(fill_value=0))

    rows, contrasts = [], []
    for s in names:
        y_all = np.log(f[s].astype(float))
        for split in ("train", "holdout", "all"):
            m = (f["split"] == split) if split != "all" else pd.Series(True, index=f.index)
            res = fit(y_all[m], design(f[m], FLAGS))
            rows += coef_rows(res, f, m, s, split, FLAGS, "main")
            for a, b in (("po_home", "reg_home"), ("po_away", "reg_away")):
                c = contrast(res, a, b)
                if c:
                    contrasts.append({"series": s, "split": split, "contrast": f"{a}-{b}", "pct": 100 * c[0],
                                      "lo": 100 * (c[0] - Z * c[1]), "hi": 100 * (c[0] + Z * c[1]), "p": c[2]})
            rf = ["reg_home", "reg_away", "po_r1", "po_r2", "po_r3", "po_r4"]
            res = fit(y_all[m], design(f[m], rf))
            rows += coef_rows(res, f, m, s, split, rf[2:], "round")
    t = pd.DataFrame(rows)
    tests = t[t.split == "train"].index
    t["bh_train"] = np.nan
    t.loc[tests, "bh_train"] = bh(t.loc[tests, "p"])
    t.to_csv(OUT / "uplift.csv", index=False, float_format="%.4g")
    pd.DataFrame(contrasts).to_csv(OUT / "contrasts.csv", index=False, float_format="%.4g")
    pd.set_option("display.width", 250)
    print(f"\ntrain tests: {len(tests)}")
    print(t.round(3).to_string())
    print(pd.DataFrame(contrasts).round(3).to_string())

    # FOUND per (series, term) in the main model
    piv = t[t.model == "main"].pivot_table(index=["series", "term"], columns="split",
                                           values=["pct", "lo", "hi", "n", "bh_train"], aggfunc="first")
    verdict = []
    for (s, term), r in piv.iterrows():
        tr = (r[("lo", "train")] > 0) | (r[("hi", "train")] < 0)
        ho = ((r[("lo", "holdout")] > 0) | (r[("hi", "holdout")] < 0)) and np.sign(r[("pct", "holdout")]) == np.sign(r[("pct", "train")])
        found = bool(tr and r[("n", "train")] >= 10 and ho and r[("bh_train", "train")] <= 0.10)
        verdict.append({"series": s, "term": term, "train_pct": r[("pct", "train")], "train_ci": f"[{r[('lo','train')]:+.1f}, {r[('hi','train')]:+.1f}]",
                        "train_n": int(r[("n", "train")]), "bh": r[("bh_train", "train")],
                        "hold_pct": r[("pct", "holdout")], "hold_ci": f"[{r[('lo','holdout')]:+.1f}, {r[('hi','holdout')]:+.1f}]",
                        "hold_n": int(r[("n", "holdout")]), "found": found})
    v = pd.DataFrame(verdict)
    v.to_csv(OUT / "verdict.csv", index=False, float_format="%.4g")
    print("\nVERDICT\n", v.round(3).to_string())

    robustness(f, g)
    e = exposure(f, t, nst, g)
    hedge(f, t, nst, g, e)


def robustness(f: pd.DataFrame, g: pd.DataFrame, n_perm: int = 300) -> None:
    """bars_all and bars_le0p5km checks, not counted as extra hypotheses: week FE instead of
    year-month; placebo permuting playoff-away nights within year-month; one run at a time; and
    the Knicks vs Rangers split."""
    rng = np.random.default_rng(0)
    print("\nROBUSTNESS")
    for s in ("bars_all", "bars_le0p5km", "fullsvc_le0p5km"):
        y = np.log(f[s].astype(float))
        X = design(f, FLAGS)
        X = X[[c for c in X.columns if not c.startswith("ym_")]]
        wk = pd.to_datetime(f["date"]).dt.to_period("W-SUN").astype(str)
        X = X.join(pd.get_dummies(wk, prefix="wk", drop_first=True).astype(float))
        r = fit(y, X)
        print(f"  {s} week-FE (all): " + ", ".join(
            f"{c} {100 * r.params[c]:+.2f} [{100 * (r.params[c] - Z * r.bse[c]):+.2f},{100 * (r.params[c] + Z * r.bse[c]):+.2f}]" for c in FLAGS))
        for term in ("po_away", "po_home"):
            real = fit(y, design(f, FLAGS)).tvalues[term]
            ym = pd.to_datetime(f["date"]).dt.strftime("%Y%m")
            ts = []
            for _ in range(n_perm):
                ff = f.copy()
                # only shuffle among non-playoff-other / non-regular nights so flags stay disjoint
                free = ~(f.reg_home | f.reg_away | f[[x for x in ("po_home", "po_away") if x != term][0]])
                perm = f[term].copy()
                for _, idx in f[free].groupby(ym[free]).groups.items():
                    perm.loc[idx] = rng.permutation(f.loc[idx, term].values)
                ff[term] = perm
                ts.append(fit(y, design(ff, FLAGS)).tvalues[term])
            ts = np.array(ts)
            print(f"  {s} placebo {term}: real t={real:+.2f}, perm |t| p95={np.quantile(abs(ts), 0.95):.2f}, two-sided perm p={np.mean(abs(ts) >= abs(real)):.3f}")
        rows = []
        for (team, season), gg in g[g.playoff].groupby(["team", "season"]):
            ff = f.copy()
            for side, m in (("home", gg.home), ("away", ~gg.home)):
                ff[f"run_{side}"] = ff["date"].isin(set(gg.loc[m, "date"]))
                ff[f"po_{side}"] = ff[f"po_{side}"] & ~ff[f"run_{side}"]
            r = fit(y, design(ff, FLAGS + ["run_home", "run_away"]))
            rows.append(f"{team}{season}: home {100 * r.params['run_home']:+.2f}±{100 * Z * r.bse['run_home']:.2f} (n={int(ff.run_home.sum())}), "
                        f"away {100 * r.params['run_away']:+.2f}±{100 * Z * r.bse['run_away']:.2f} (n={int(ff.run_away.sum())})")
        print(f"  {s} by run: " + " | ".join(rows))


def exposure(f, t, nst, g) -> None:
    """$ per playoff night per typical bar, and the round-by-round hedge backtest."""
    rows = []
    po_season = f["date"].map(lambda d: d.month in (4, 5, 6))
    base_mask = po_season & ~f.po_any & ~f.reg_home & ~f.reg_away
    for s in nst:
        base = f.loc[base_mask, s].mean() / nst[s]
        for term in ("po_home", "po_away", "reg_home", "reg_away"):
            r = t[(t.model == "main") & (t.series == s) & (t.split == "all") & (t.term == term)].iloc[0]
            rows.append({"series": s, "term": term, "stores": nst[s], "base_visits_per_store": base,
                         "uplift_pct": r.pct, "lo": r.lo, "hi": r.hi,
                         "usd_per_night_per_store": base * r.pct / 100 * CHECK,
                         "usd_lo": base * r.lo / 100 * CHECK, "usd_hi": base * r.hi / 100 * CHECK})
    e = pd.DataFrame(rows)
    e.to_csv(OUT / "exposure.csv", index=False, float_format="%.4g")
    print("\nEXPOSURE ($/night/store, CHECK=$%.0f)\n" % CHECK, e.round(3).to_string())
    return e


# Knicks series in order, with the Kalshi market whose NYK-YES pays iff NYK wins that series
# (conditional on reaching it) and game-1 date. 2024 has no Kalshi markets.
SERIES = {
    2024: [("R1 PHI", None, date(2024, 4, 20)), ("R2 IND", None, date(2024, 5, 6))],
    2025: [("R1 DET", "KXNBASERIES-25DETNYK-NYK", date(2025, 4, 19)),
           ("R2 BOS", "KXNBASERIES-25NYKBOS-NYK", date(2025, 5, 5)),
           ("ECF IND", "KXNBAEAST-25-NYK", date(2025, 5, 21))],
    2026: [("R1 ATL", "KXNBASERIES-26ATLNYKR1-NYK", date(2026, 4, 18)),
           ("R2 PHI", "KXNBASERIES-26PHINYKR2-NYK", date(2026, 5, 4)),
           ("ECF CLE", "KXNBAEAST-26-NYK", date(2026, 5, 19)),
           ("Finals SAS", "KXNBA-26-NYK", date(2026, 6, 3))],
}


def kalshi_prices() -> dict[str, float]:
    """Last daily close strictly before game 1 (ET), from r5-markets' cached /historical candlesticks."""
    c = json.loads((CACHE / "r5markets_candles.json").read_text())
    out = {}
    for season in SERIES.values():
        for _, tk, g1 in season:
            if tk is None:
                continue
            cut = datetime(g1.year, g1.month, g1.day, tzinfo=ET).timestamp()
            pts = [x for x in c[tk] if x["end_period_ts"] <= cut and x["price"]["close"] is not None]
            out[tk] = float(pts[-1]["price"]["close"])
    return out


def hedge(f, t, nst, g, e) -> None:
    """Myopic round-by-round hedge for a typical Manhattan bar (bars_all) on the Knicks runs.

    Revenue unit R = baseline visits/bar x CHECK. Effects a_home, a_away come from the TRAIN fit
    (so 2026 is out of sample). Before series k, the extra nights of series k+1 (if NYK advances)
    are worth N_{k+1} x a_bar x R, a_bar = (a_home + a_away)/2. If that is negative (a deep run
    costs the bar), buy YES "NYK wins series k" with that $ notional; if positive, buy NO.
    Cost = price + 0.07 p(1-p) per $1 contract."""
    prices = kalshi_prices()
    print("\nKALSHI pre-game-1 NYK YES prices:", prices)
    rows, sims = [], []
    for s in ("bars_all", "bars_le0p5km", "fullsvc_le0p5km"):
        base = e[(e.series == s)].base_visits_per_store.iloc[0]
        R = base * CHECK
        a = {k: t[(t.model == "main") & (t.series == s) & (t.split == "train") & (t.term == k)].pct.iloc[0] / 100
             for k in ("po_home", "po_away")}
        for season, ser in SERIES.items():
            gg = g[(g.team == "knicks") & (g.season == season) & g.playoff]
            unhedged = R * (a["po_home"] * gg.home.sum() + a["po_away"] * (~gg.home).sum())
            pnl = 0.0
            for k, (name, tk, g1) in enumerate(ser):
                q = prices.get(tk, ASSUMED_P)
                nxt = ser[k + 1] if k + 1 < len(ser) else None
                if nxt is None and season != 2026 and k + 1 == len(ser):
                    nxt = ("lost", None, None)  # they lost series k; the next round would have existed
                if nxt is None:  # Finals: nothing after
                    continue
                q_next = prices.get(nxt[1], ASSUMED_P)
                at_stake = exp_games(q_next) * (a["po_home"] + a["po_away"]) / 2 * R
                won = (k + 1 < len(ser)) or (season == 2026)
                p_side = q if at_stake < 0 else 1 - q
                fee = 0.07 * p_side * (1 - p_side)
                pays = won if at_stake < 0 else not won
                pnl += abs(at_stake) * (float(pays) - p_side - fee)
            rows.append({"series": s, "season": season, "nights": len(gg), "home": int(gg.home.sum()),
                         "unhedged_usd": unhedged, "hedge_pnl_usd": pnl, "hedged_usd": unhedged + pnl, "R_usd": R,
                         "a_home_pct": 100 * a["po_home"], "a_away_pct": 100 * a["po_away"]})
        sims.append(simulate(s, R, a, prices))
    h = pd.DataFrame(rows)
    h.to_csv(OUT / "hedge_backtest.csv", index=False, float_format="%.4g")
    print("\nHEDGE BACKTEST (Knicks runs; 2024 priced at assumed %.2f)\n" % ASSUMED_P, h.round(1).to_string())
    for s, gs in h.groupby("series"):
        print(f"  {s}: SD unhedged {gs.unhedged_usd.std():.0f}, hedged {gs.hedged_usd.std():.0f} (n=3 seasons)")
    sm_ = pd.DataFrame(sims)
    sm_.to_csv(OUT / "hedge_sim.csv", index=False, float_format="%.4g")
    print("\nSIMULATED SEASONS (2026 Kalshi pre-series prices, 20k draws)\n", sm_.round(1).to_string())


def simulate(s, R, a, prices, n=20000) -> dict:
    """Seasons drawn from the 2026 pre-series prices (per-game p implied by each series price),
    home court = NYK for 4 of 7 slots (2-2-1-1-1). Same myopic hedge as the backtest."""
    rng = np.random.default_rng(1)
    qs = [prices[tk] for _, tk, _ in SERIES[2026]]
    home_slots = [1, 1, 0, 0, 1, 0, 1]
    un, hd = np.zeros(n), np.zeros(n)
    abar = (a["po_home"] + a["po_away"]) / 2
    for i in range(n):
        for k, q in enumerate(qs):
            p = game_p_from_series_p(q)
            w = l = j = 0
            while w < 4 and l < 4:
                h = home_slots[j]
                un[i] += R * (a["po_home"] if h else a["po_away"])
                if rng.random() < p:
                    w += 1
                else:
                    l += 1
                j += 1
            if k + 1 < len(qs):
                at_stake = exp_games(qs[k + 1]) * abar * R
                p_side = q if at_stake < 0 else 1 - q
                fee = 0.07 * p_side * (1 - p_side)
                pays = (w == 4) if at_stake < 0 else (w < 4)
                hd[i] += abs(at_stake) * (float(pays) - p_side - fee)
            if w < 4:
                break
    hd += un
    return {"series": s, "R_usd": R, "mean_unhedged": un.mean(), "sd_unhedged": un.std(), "p5_unhedged": np.quantile(un, 0.05),
            "mean_hedged": hd.mean(), "sd_hedged": hd.std(), "p5_hedged": np.quantile(hd, 0.05),
            "sd_ratio": hd.std() / un.std()}


if __name__ == "__main__":
    run()
