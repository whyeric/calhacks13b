"""R7 displacement: do big-TV nights pull people out of Manhattan bars, restaurants, subways and Ubers?

Run from backend/:  .venv/bin/python ../experiments/bar/r7-displacement/run.py
(after fetch.py has filled r2-cache/r7displacement_*).

Mechanism (stated before fitting): a big televised event (a New York team's postseason game outside
Manhattan, Giants/Jets primetime, the Super Bowl, March Madness, election night, USA at the World Cup)
-> more people watch at home -> fewer evening trips into Manhattan (subway, FHV) -> fewer visits to
bars and full-service restaurants. r5-bars found this for Knicks/Rangers AWAY playoff nights (-3.5%).

1. Families. One model per outcome and split with a day flag per event family (all families jointly,
   so overlapping days split additively): log(y) ~ DOW + year-month FE + holiday + Halloween + rain +
   Knicks/Rangers playoff home/away controls + family flags, HAC(7). Train 2024-01-01..2025-09-28,
   holdout 2025-09-29..2026-09-27 (FHV ends 2025-12-31), fitted independently.
2. Stakes. MLB round index (WC=1..WS=4) and March Madness stage (1..3) as slopes within the family,
   and a pooled big-TV flag with an audience-tier slope.
3. Placebo. Same weekday one week before each event day (dropping dates that are themselves events).
4. Seasonal exposure. Yankees/Mets postseason nights x per-night effect x baseline revenue, and a
   round-by-round hedge on Kalshi KXMLBSERIES.

Only aggregates are written; no venue names, ids, addresses or per-venue series.
"""
from __future__ import annotations

import glob
import json
import sys
from datetime import date, datetime, timedelta
from math import comb
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
P = "r7displacement_"
ESPN = CACHE / f"{P}espn"
OUT = Path(__file__).resolve().parent
GLOB = str(ROOT / "data/01a16ff2-6017-7e10-86ac-94bf02853813/*.parquet")
START, TRAIN_END, END = date(2024, 1, 1), date(2025, 9, 28), date(2026, 9, 27)
Z = 1.645
CHECK = 35.0  # assumed $ per Dewey visit (as in rounds 1-6)
ET = ZoneInfo("America/New_York")
YS = (40.8296, -73.9262)  # Yankee Stadium
FAMILIES = ["yankees_ps", "mets_ps", "nfl_prime", "superbowl", "march_madness", "election", "wc_usa", "wc_final"]
CONTROLS = ["kr_po_home", "kr_po_away", "halloween"]
OUTCOMES = ["bars_all", "fullsvc_all", "bars_ys_le5km", "bars_ys_gt5km", "mta_eve", "fhv_eve"]
MLB_ROUND = {"WC": 1, "DS": 2, "CS": 3, "World Series": 4}
# Approximate US audience band per event (assumption, from public Nielsen reporting, rounded):
# 1 = under ~8M (MLB WC/DS, MM First Four-2nd Round), 2 = ~8-30M (LCS, World Series, NFL primetime,
# MM Sweet 16-Final, USA World Cup), 3 = over ~40M (Super Bowl, election night, World Cup final).
TIER_MM = {1: 1, 2: 2, 3: 2}
TIER_MLB = {1: 1, 2: 1, 3: 2, 4: 2}


def et(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(ET)


# ------------------------------------------------------------------ events
def events() -> pd.DataFrame:
    """One row per (family, date) with a within-family stakes index and an audience tier."""
    rows = []
    for team, fam in (("nyy", "yankees_ps"), ("nym", "mets_ps")):
        for season in (2024, 2025):
            for e in json.loads((ESPN / f"mlb_{team}_{season}.json").read_text()).get("events", []):
                note = (e["competitions"][0].get("notes") or [{}])[0].get("headline", "")
                r = next(v for k, v in MLB_ROUND.items() if k in note)
                t = et(e["date"])
                home = any(c["homeAway"] == "home" and c["team"]["abbreviation"] == team.upper()
                           for c in e["competitions"][0]["competitors"])
                rows.append({"family": fam, "date": t.date(), "stake": r, "tier": TIER_MLB[r],
                             "start": t.strftime("%H:%M"), "home": home})
    for team in ("nyg", "nyj"):
        for season in (2023, 2024, 2025, 2026):
            for e in json.loads((ESPN / f"nfl_{team}_{season}_2.json").read_text()).get("events", []):
                t = et(e["date"])
                if t.hour >= 19 and t.date() <= END:  # SNF/MNF/TNF; drops 09:30 ET international games
                    rows.append({"family": "nfl_prime", "date": t.date(), "stake": 1, "tier": 2, "start": t.strftime("%H:%M")})
    for season in (2023, 2024, 2025):
        for e in json.loads((ESPN / f"nfl_sb_{season}.json").read_text())["events"]:
            t = et(e["date"])
            rows.append({"family": "superbowl", "date": t.date(), "stake": 1, "tier": 3, "start": t.strftime("%H:%M")})
    stage = {"First Four": 1, "1st Round": 1, "2nd Round": 1, "Sweet 16": 2, "Elite 8": 2,
             "Final Four": 3, "National Championship": 3}
    mm = {}
    for f in sorted(glob.glob(str(ESPN / "ncaa_*.json"))):
        for e in json.loads(Path(f).read_text()).get("events", []):
            note = (e["competitions"][0].get("notes") or [{}])[0].get("headline", "")
            if "Men's Basketball Championship" in note:
                s = next((v for k, v in stage.items() if k in note), None)
                if s:
                    mm[et(e["date"]).date()] = s
    rows += [{"family": "march_madness", "date": d, "stake": s, "tier": TIER_MM[s], "start": ""} for d, s in mm.items()]
    # 2024 presidential election night; the 2025 NYC mayoral election night is the only holdout analog
    rows += [{"family": "election", "date": date(2024, 11, 5), "stake": 2, "tier": 3, "start": "19:00"},
             {"family": "election", "date": date(2025, 11, 4), "stake": 1, "tier": 2, "start": "21:00"}]
    seen = set()
    for f in sorted(glob.glob(str(ESPN / "wc_*.json"))):
        for e in json.loads(Path(f).read_text()).get("events", []):
            if e["id"] in seen:
                continue
            seen.add(e["id"])
            t = et(e["date"])
            if "United States" in e["name"]:
                rows.append({"family": "wc_usa", "date": t.date(), "stake": 1, "tier": 2, "start": t.strftime("%H:%M")})
            elif e.get("season", {}).get("slug") == "final":
                rows.append({"family": "wc_final", "date": t.date(), "stake": 1, "tier": 3, "start": t.strftime("%H:%M")})
    ev = pd.DataFrame(rows).drop_duplicates(["family", "date"])
    return ev[(ev.date >= START) & (ev.date <= END)].sort_values(["date", "family"]).reset_index(drop=True)


def knicks_rangers() -> pd.DataFrame:
    g = pd.read_csv(OUT.parent / "r5-bars/games.csv", parse_dates=["date"])
    g["date"] = g.date.dt.date
    return g[g.playoff]


# ------------------------------------------------------------------ outcomes
def dewey() -> pd.DataFrame:
    out = CACHE / f"{P}dewey.parquet"
    if out.exists():
        return pd.read_parquet(out)
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
    la, lo = YS
    con.execute(f"""
        create table keep as select *,
            6371 * 2 * asin(sqrt(pow(sin(radians(lat - {la}) / 2), 2)
              + cos(radians(lat)) * cos(radians({la})) * pow(sin(radians(lon - ({lo})) / 2), 2))) km
        from st where nwk = {nweeks} and flat < 0.05""")
    baskets = {"bars_all": "naics = '722410'", "fullsvc_all": "naics = '722511'",
               "bars_ys_le5km": "naics = '722410' and km <= 5", "bars_ys_gt5km": "naics = '722410' and km > 5"}
    n = con.execute("select " + ", ".join(f"sum(({c})::int) as {k}" for k, c in baskets.items()) + " from keep").df()
    cols = ", ".join(f"sum(case when {c} then x end) as {k}" for k, c in baskets.items())
    df = con.execute(f"""
        with d as (select w.id, w.ws + (i - 1)::int as date, w.v[i] x
                   from w join keep using (id), range(1, 8) r(i))
        select date, {cols} from d join keep k using (id) group by date order by date""").df()
    for k in baskets:
        df[f"n_{k}"] = int(n[k].iloc[0])
    df["date"] = pd.to_datetime(df["date"])
    df.to_parquet(out)
    return df


def panel() -> pd.DataFrame:
    d = dewey()
    d["date"] = pd.to_datetime(d["date"]).dt.date
    m = pd.read_parquet(CACHE / f"{P}mta_eve.parquet")
    m = pd.DataFrame({"date": pd.to_datetime(m.day).dt.date, "mta_eve": m.r.astype(float)})
    tf = glob.glob(str(CACHE / f"{P}tlc/fhvhv_*.parquet"))
    t = pd.concat(pd.read_parquet(x) for x in tf) if tf else pd.DataFrame({"day": [], "n": []})
    t = pd.DataFrame({"date": pd.to_datetime(t.day).dt.date, "fhv_eve": t.n.astype(float)})
    w = pd.concat(pd.read_csv(CACHE / f"ghcn_{y}.csv") for y in (2024, 2025, 2026))
    w = pd.DataFrame({"date": pd.to_datetime(w.DATE).dt.date, "PRCP": w.PRCP})
    f = d.merge(m, on="date", how="left").merge(t, on="date", how="left").merge(w, on="date", how="left")
    f = f[(f.date >= START) & (f.date <= END)].reset_index(drop=True)
    assert f.PRCP.notna().all(), "weather gaps"
    return f


def add_flags(f: pd.DataFrame, ev: pd.DataFrame, kr: pd.DataFrame) -> pd.DataFrame:
    f = f.copy()
    for fam in FAMILIES:
        e = ev[ev.family == fam].set_index("date")
        f[fam] = f.date.isin(e.index).astype(float)
        f[f"{fam}_stake"] = f.date.map(e.stake).fillna(0).astype(float)
    f["kr_po_home"] = f.date.isin(set(kr.loc[kr.home, "date"])).astype(float)
    f["kr_po_away"] = f.date.isin(set(kr.loc[~kr.home, "date"])).astype(float)
    f["halloween"] = f.date.map(lambda d: d.month == 10 and d.day == 31).astype(float)
    f["mlb_ps"] = ((f.yankees_ps + f.mets_ps) > 0).astype(float)
    f["mlb_round"] = np.maximum(f.yankees_ps_stake, f.mets_ps_stake)
    for fam, short in (("yankees_ps", "nyy"), ("mets_ps", "nym")):
        e = ev[ev.family == fam]
        f[f"{short}_home"] = f.date.isin(set(e.loc[e.home == True, "date"])).astype(float)  # noqa: E712
        f[f"{short}_away"] = f.date.isin(set(e.loc[e.home == False, "date"])).astype(float)  # noqa: E712
    mlb = ev[ev.family.isin(["yankees_ps", "mets_ps"])]
    f["mlb_home"] = f.date.isin(set(mlb.loc[mlb.home == True, "date"])).astype(float)  # noqa: E712
    f["mlb_eve"] = f.date.isin(set(mlb.loc[mlb.start >= "18:00", "date"])).astype(float)
    f["easter"] = f.date.isin({date(2024, 3, 31), date(2025, 4, 20), date(2026, 4, 5)}).astype(float)
    tier = ev.groupby("date").tier.max()
    f["bigtv"] = f.date.isin(tier.index).astype(float)
    f["bigtv_tier"] = f.date.map(tier).fillna(0).astype(float)
    # placebo: same weekday a week earlier, never on an event (or Knicks/Rangers playoff) day itself
    busy = set(ev.date) | set(kr.date)
    for fam in FAMILIES:
        pl = {d - timedelta(7) for d in ev.loc[ev.family == fam, "date"]} - busy
        f[f"pl_{fam}"] = f.date.isin(pl).astype(float)
    f["pl_bigtv"] = f[[f"pl_{x}" for x in FAMILIES]].max(axis=1)
    # placebo for the stakes slopes: the same stage codes moved one week earlier
    for fam, stake in (("mlb", "mlb_round"), ("mm", "march_madness_stake")):
        src = f.loc[f[stake] > 0, ["date", stake]] if fam == "mm" else f.loc[f.mlb_round > 0, ["date", "mlb_round"]]
        sh = {d - timedelta(7): v for d, v in zip(src.date, src[stake])}
        sh = {d: v for d, v in sh.items() if d not in busy}
        f[f"pl_{fam}_any"] = f.date.isin(sh).astype(float)
        f[f"pl_{fam}_stage"] = f.date.map(sh).fillna(0).astype(float)
    f["split"] = np.where(f.date <= TRAIN_END, "train", "holdout")
    return f


# ------------------------------------------------------------------ fits
def design(f: pd.DataFrame, terms: list[str]) -> pd.DataFrame:
    ts = pd.to_datetime(f["date"])
    X = pd.get_dummies(ts.dt.day_of_week, prefix="dow", drop_first=True).astype(float)
    X = X.join(pd.get_dummies(ts.dt.strftime("%Y%m"), prefix="ym", drop_first=True).astype(float))
    X.insert(0, "const", 1.0)
    X["holiday"] = f["date"].isin(config.HOLIDAYS).astype(float)
    X["rain"] = (f["PRCP"] >= 0.01).astype(float)
    for c in CONTROLS + terms:
        X[c] = f[c].astype(float)
    X.index = f.index
    return X.loc[:, (X.nunique() > 1) | (X.columns == "const")]


def fit(f: pd.DataFrame, y: str, terms: list[str]):
    """HAC(7) fit, with the classical fit attached as .nr: a flag on fewer than 10 days gets the
    classical SE, because a HAC/HC 'meat' over a near-saturated dummy is ~0 (one-day flags would
    otherwise get spurious p ~ 0)."""
    g = f[f[y].notna() & (f[y] > 0)]
    mod = sm.OLS(np.log(g[y]), design(g, terms))
    res = mod.fit(cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)
    res.nr = mod.fit()
    return res, g


def rows_for(res, g, y, split, model, terms, nflag=None):
    out = []
    for c in terms:
        if c not in res.params:
            continue
        n = int((g[nflag.get(c, c)] != 0).sum()) if nflag else int((g[c] != 0).sum())
        r = res if n >= 10 else res.nr
        b, se = r.params[c], r.bse[c]
        out.append({"model": model, "outcome": y, "split": split, "term": c, "n": n, "pct": 100 * b,
                    "lo": 100 * (b - Z * se), "hi": 100 * (b + Z * se), "p": float(r.pvalues[c]),
                    "se": "HAC" if n >= 10 else "classical"})
    return out


def bh(p: pd.Series) -> pd.Series:
    q = pd.Series(np.nan, index=p.index)
    v = p.dropna().sort_values()
    m = len(v)
    q[v.index] = (v * m / np.arange(1, m + 1))[::-1].cummin()[::-1].clip(upper=1)
    return q


def center(f: pd.DataFrame, flag: str, stake: str, mid: float) -> pd.Series:
    return np.where(f[flag] > 0, f[stake] - mid, 0.0)


def fit_all(f: pd.DataFrame) -> pd.DataFrame:
    f = f.copy()
    f["mlb_round_c"] = center(f, "mlb_ps", "mlb_round", 2.5)
    f["mm_stage_c"] = center(f, "march_madness", "march_madness_stake", 2.0)
    f["bigtv_tier_c"] = center(f, "bigtv", "bigtv_tier", 2.0)
    stakes_terms = ["mlb_ps", "mlb_round_c", "nfl_prime", "superbowl", "march_madness", "mm_stage_c",
                    "election", "wc_usa", "wc_final"]
    f["pl_mlb_stage_c"] = center(f, "pl_mlb_any", "pl_mlb_stage", 2.5)
    f["pl_mm_stage_c"] = center(f, "pl_mm_any", "pl_mm_stage", 2.0)
    nflag = {"mlb_round_c": "mlb_ps", "mm_stage_c": "march_madness", "bigtv_tier_c": "bigtv",
             "pl_mlb_stage_c": "pl_mlb_any", "pl_mm_stage_c": "pl_mm_any"}
    homeaway = ["nyy_home", "nyy_away", "nym_home", "nym_away"] + FAMILIES[2:]
    pl = [f"pl_{x}" for x in FAMILIES]
    rows = []
    for y in [o for o in OUTCOMES if f[o].notna().sum() > 200]:
        for split in ("train", "holdout", "all"):
            m = f if split == "all" else f[f.split == split]
            res, g = fit(m, y, FAMILIES)
            rows += rows_for(res, g, y, split, "family", FAMILIES)
            res, g = fit(m, y, stakes_terms)
            rows += rows_for(res, g, y, split, "stakes", ["mlb_round_c", "mm_stage_c"], nflag)
            res, g = fit(m, y, ["bigtv", "bigtv_tier_c"])
            rows += rows_for(res, g, y, split, "pooled", ["bigtv", "bigtv_tier_c"], nflag)
            res, g = fit(m, y, FAMILIES + pl)
            rows += rows_for(res, g, y, split, "placebo", pl)
            res, g = fit(m, y, ["bigtv", "pl_bigtv"])
            rows += rows_for(res, g, y, split, "placebo", ["pl_bigtv"])
            res, g = fit(m, y, homeaway)
            rows += rows_for(res, g, y, split, "homeaway", homeaway[:4])
            # robustness (not in BH): stakes slopes with MLB home and evening-start controls, + Easter
            res, g = fit(m, y, stakes_terms + ["mlb_home", "mlb_eve", "easter"])
            rows += rows_for(res, g, y, split, "stakes_ctrl", ["mlb_round_c", "mm_stage_c"], nflag)
            res, g = fit(m, y, stakes_terms + ["pl_mlb_any", "pl_mlb_stage_c", "pl_mm_any", "pl_mm_stage_c"])
            rows += rows_for(res, g, y, split, "placebo", ["pl_mlb_stage_c", "pl_mm_stage_c"], nflag)
    t = pd.DataFrame(rows)
    tests = t[(t.split == "train") & t.model.isin(["family", "stakes", "pooled", "homeaway"])].index
    t["bh_train"] = np.nan
    t.loc[tests, "bh_train"] = bh(t.loc[tests, "p"])
    return t


def verdicts(t: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (model, y, term), g in t[t.model.isin(["family", "stakes", "pooled", "homeaway", "stakes_ctrl"])].groupby(["model", "outcome", "term"], sort=False):
        tr = g[g.split == "train"]
        ho = g[g.split == "holdout"]
        if tr.empty:
            continue
        tr = tr.iloc[0]
        sig_tr = tr.lo > 0 or tr.hi < 0
        h = ho.iloc[0] if len(ho) else None
        sig_ho = h is not None and (h.lo > 0 or h.hi < 0) and np.sign(h.pct) == np.sign(tr.pct)
        found = bool(sig_tr and tr.n >= 10 and sig_ho and tr.bh_train <= 0.10)
        out.append({"model": model, "outcome": y, "term": term,
                    "train": f"{tr.pct:+.1f} [{tr.lo:+.1f}, {tr.hi:+.1f}]", "train_n": int(tr.n), "bh": tr.bh_train,
                    "holdout": "" if h is None else f"{h.pct:+.1f} [{h.lo:+.1f}, {h.hi:+.1f}]",
                    "holdout_n": 0 if h is None else int(h.n), "found": found})
    return pd.DataFrame(out)


# ------------------------------------------------------------------ exposure + hedge
def series_len_dist(p: float, wins: int) -> dict[int, float]:
    """Length distribution of a best-of-(2*wins-1) series with independent games at per-game p."""
    return {n: comb(n - 1, wins - 1) * (p ** wins * (1 - p) ** (n - wins) + (1 - p) ** wins * p ** (n - wins))
            for n in range(wins, 2 * wins)}


def game_p(q: float, wins: int) -> float:
    lo, hi = 0.01, 0.99
    for _ in range(60):
        mid = (lo + hi) / 2
        w = sum(comb(n - 1, wins - 1) * mid ** wins * (1 - mid) ** (n - wins) for n in range(wins, 2 * wins))
        lo, hi = (mid, hi) if w < q else (lo, mid)
    return (lo + hi) / 2


def exp_games(q: float, wins: int) -> float:
    return sum(n * w for n, w in series_len_dist(game_p(q, wins), wins).items())


WINS = [2, 3, 4, 4]  # WC best-of-3, DS best-of-5, CS and WS best-of-7
# Yankees series with Kalshi KXMLBSERIES markets (2025 inside Dewey; 2026 only for pricing the sim)
NYY_SERIES = {2025: [("WC", "KXMLBSERIES-25BOSNYY-NYY", date(2025, 9, 30)),
                     ("DS", "KXMLBSERIES-25NYYTOR-NYY", date(2025, 10, 4))],
              2026: [("WC", "KXMLBSERIES-26BOSNYYWC-NYY", None), ("DS", "KXMLBSERIES-26NYYTBALDS-NYY", None)]}


def kalshi_prices() -> dict[str, float]:
    """Last daily close strictly before game 1. r5-markets' cached 2025 NYY candles carry no prices,
    and no 2026 game dates are cached here, so 2026 uses the median of the first three traded daily
    closes (the pre-series window)."""
    c = json.loads((CACHE / "r5markets_candles.json").read_text())
    out = {}
    for season in NYY_SERIES.values():
        for _, tk, g1 in season:
            pts = [x for x in c.get(tk, []) if x["price"].get("close_dollars") is not None]
            if g1 is not None:
                cut = datetime(g1.year, g1.month, g1.day, tzinfo=ET).timestamp()
                pts = [x for x in pts if x["end_period_ts"] <= cut]
            if pts:
                closes = [float(x["price"]["close_dollars"]) for x in pts]
                out[tk] = closes[-1] if g1 is not None else float(np.median(closes[:3]))
    return out


def exposure_and_hedge(f: pd.DataFrame, t: pd.DataFrame, ev: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-night $ for a typical Manhattan bar on Yankees/Mets postseason nights, per-round value, and a
    simulated season hedged round by round with YES/NO on 'NYY wins series k'."""
    tr = f[f.split == "train"]
    base = tr[(pd.to_datetime(tr.date).dt.month.isin([4, 5, 6])) & (tr.bigtv == 0)]
    rows = []
    for y in ("bars_all", "fullsvc_all"):
        per_store = (base[y] / base[f"n_{y}"]).mean()
        R = per_store * CHECK
        for fam in ("yankees_ps", "mets_ps"):
            r = t[(t.model == "family") & (t.outcome == y) & (t.split == "train") & (t.term == fam)].iloc[0]
            nights = ev[(ev.family == fam)].groupby(pd.to_datetime(ev.date).dt.year).size().to_dict()
            rows.append({"outcome": y, "family": fam, "visits_per_store_day": per_store, "R_usd_day": R,
                         "pct_per_night": r.pct, "usd_per_night": R * r.pct / 100,
                         "usd_lo": R * r.lo / 100, "usd_hi": R * r.hi / 100,
                         "nights_2024": nights.get(2024, 0), "nights_2025": nights.get(2025, 0),
                         "usd_run_2024": R * r.pct / 100 * nights.get(2024, 0)})
    e = pd.DataFrame(rows)

    prices = kalshi_prices()
    print("\nKALSHI NYY series YES prices:", prices)
    rng = np.random.default_rng(7)
    sims = []
    ey = e[(e.outcome == "bars_all") & (e.family == "yankees_ps")].iloc[0]
    a, R = ey.pct_per_night / 100, ey.R_usd_day
    q26 = [prices.get(tk) for _, tk, _ in NYY_SERIES[2026]]
    q = [q26[0] or 0.5, q26[1] or 0.5, 0.5, 0.5]  # CS/WS: ASSUMED 0.50, no Kalshi price in hand
    for _ in range(20000):
        un, pnl = 0.0, 0.0
        for k in range(4):
            # before series k, hedge the value of series k+1's nights (if any)
            if k + 1 < 4:
                v = exp_games(q[k + 1], WINS[k + 1]) * a * R
                side_yes = v < 0
                p_buy = q[k] if side_yes else 1 - q[k]
                qty = abs(v)
            pg = game_p(q[k], WINS[k])
            w = l = n = 0
            while w < WINS[k] and l < WINS[k]:
                n += 1
                if rng.random() < pg:
                    w += 1
                else:
                    l += 1
            un += n * a * R
            won = w == WINS[k]
            if k + 1 < 4:
                pay = 1.0 if (won == side_yes) else 0.0
                pnl += qty * (pay - p_buy - 0.07 * p_buy * (1 - p_buy))
            if not won:
                break
        sims.append({"unhedged": un, "hedged": un + pnl})
    s = pd.DataFrame(sims)
    sim = pd.DataFrame([{"series": "unhedged", "mean": s.unhedged.mean(), "sd": s.unhedged.std(), "p5": s.unhedged.quantile(0.05)},
                        {"series": "hedged", "mean": s.hedged.mean(), "sd": s.hedged.std(), "p5": s.hedged.quantile(0.05)}])
    sim["a_per_night_pct"] = 100 * a
    sim["R_usd_day"] = R
    sim["q_used"] = str([round(x, 2) for x in q])
    return e, sim


# ------------------------------------------------------------------ main
def main() -> None:
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    ev = events()
    ev.to_csv(OUT / "events.csv", index=False)
    print(ev.assign(split=np.where(ev.date <= TRAIN_END, "train", "holdout")).groupby(["family", "split"]).size().unstack(fill_value=0))
    f = add_flags(panel(), ev, knicks_rangers())
    print("stores:", {k: int(f[f"n_{k}"].iloc[0]) for k in OUTCOMES[:4]})
    print("coverage:", {y: (str(f.loc[f[y].notna(), "date"].min()), str(f.loc[f[y].notna(), "date"].max())) for y in OUTCOMES})
    t = fit_all(f)
    t.to_csv(OUT / "results.csv", index=False, float_format="%.4g")
    ntests = int(t.bh_train.notna().sum())
    print(f"\nBH tests (train, non-placebo): {ntests}")
    v = verdicts(t)
    v.to_csv(OUT / "verdict.csv", index=False, float_format="%.4g")
    print(v.round(3).to_string())
    pl = t[t.model == "placebo"]
    print("\nPLACEBO (week-before same weekday)\n", pl[pl.split != "all"].round(3).to_string())
    pl.to_csv(OUT / "placebo.csv", index=False, float_format="%.4g")
    print("\nALL-PERIOD family fits\n", t[(t.split == "all") & (t.model != "placebo")].round(3).to_string())
    e, sim = exposure_and_hedge(f, t, ev)
    e.to_csv(OUT / "exposure.csv", index=False, float_format="%.4g")
    sim.to_csv(OUT / "hedge_sim.csv", index=False, float_format="%.4g")
    print("\nEXPOSURE\n", e.round(2).to_string())
    print("\nHEDGE SIM\n", sim.round(2).to_string())


if __name__ == "__main__":
    main()
