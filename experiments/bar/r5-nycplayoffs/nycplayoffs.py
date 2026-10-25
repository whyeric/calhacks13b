"""R5 nycplayoffs: what a Knicks/Rangers playoff run is worth to a bar near MSG, and whether Kalshi
advancement markets hedge the elimination risk.

Part A (uplift). Three public/aggregate daily series near MSG, each fit on log(y) with regular-season
home game and playoff home game flags, DOW, year-month FE, holiday and NOAA rain (GHCN USW00094728),
HAC(7) errors, on a train period and an independent holdout refit:
    dewey_0p5km   Dewey restaurant/bar visits, balanced stores within 0.5 km of MSG (r2-aggregate basket)
    dewey_zip     same, MSG ZIP basket                      train 2024-01..2025-03 | holdout 2025-04..2026-09
    mta_post      34 St-Penn entries 21-24h (r4-mtahourly), + log system entries, evening games only,
                  matinee control                              train 2022-2023     | holdout 2024
    taxi186       TLC zone 186 daily fares (features.build("taxi"))  train 2024-10..2025-09 | holdout 2025-10..2026-08
  Tests per period: playoff effect, regular-season effect, playoff minus regular (3 x 4 = 12), BH 10%.
  Per-season playoff effects (one dummy per team-season, full sample) are the replication table.
Part B ($ at stake). Per-game $ uplift = playoff effect x baseline; best-of-7 2-2-1-1-1 home pattern.
Part C (Kalshi). Pre-round prices from KXNBASERIES / KXNBAEAST / KXNBA daily candles (fetch.py).
Part D (backtest). Before each round buy "NY loses this round" sized to the $ of later home games
  that elimination removes; realised 2023-2026 runs plus Monte Carlo from the pre-round probabilities.

Run fetch.py first, then from backend/:  .venv/bin/python ../experiments/bar/r5-nycplayoffs/nycplayoffs.py
Writes results.csv, seasons.csv, rounds.csv, backtest.csv, output.txt (aggregates only, no venue ids).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from functools import lru_cache
from datetime import date, datetime
from itertools import product
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.holiday import USFederalHolidayCalendar

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app.data import features  # noqa: E402

OUT = Path(__file__).resolve().parent
CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
P = "r5nycplayoffs_"
NY = ZoneInfo("America/New_York")
Z = 1.645
CHECK = 35.0          # ASSUMED average check per visit (round-1 convention)
BAR_COVERS = 300      # ASSUMED baseline customers per night for the scenario bar
FEE = lambda q: 0.07 * q * (1 - q)  # noqa: E731
LINES: list[str] = []
PERIODS = {
    "dewey": {"train": ("2024-01-01", "2025-03-31"), "holdout": ("2025-04-01", "2026-09-27")},
    "mta": {"train": ("2022-01-01", "2023-12-31"), "holdout": ("2024-01-01", "2024-12-31")},
    "taxi": {"train": ("2024-10-01", "2025-09-30"), "holdout": ("2025-10-01", "2026-08-31")},
}
SERIES = {"dewey_0p5km": "dewey", "dewey_zip": "dewey", "mta_post": "mta", "taxi186": "taxi"}


def say(s: str = "") -> None:
    print(s)
    LINES.append(s)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ games
def games() -> pd.DataFrame:
    """Every completed Knicks/Rangers game 2021-22..2025-26 from the ESPN team schedules."""
    rows = []
    for team, tid in (("knicks", "18"), ("rangers", "13")):
        for season, st in product(range(2022, 2027), (2, 3)):
            for ev in json.loads((CACHE / f"{P}espn_{team}_{season}_{st}.json").read_text()).get("events", []):
                c = ev["competitions"][0]
                if not c.get("status", ev.get("status", {})).get("type", {}).get("completed", True):
                    continue
                me = next(x for x in c["competitors"] if x["team"]["id"] == tid)
                if me.get("winner") is None:
                    continue
                start = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(NY)
                head = (c.get("notes") or [{}])[0].get("headline", "")
                rows.append({"date": start.date(), "team": team, "season": season, "playoff": st == 3,
                             "home": me["homeAway"] == "home" and "Madison Square" in c.get("venue", {}).get("fullName", ""),
                             "start_h": start.hour + start.minute / 60, "win": bool(me["winner"]),
                             "round": head.split(" - ")[0] if st == 3 else "",
                             "opp": next(x for x in c["competitors"] if x["team"]["id"] != tid)["team"]["abbreviation"]})
    return pd.DataFrame(rows).drop_duplicates(["date", "team"])


def flags(g: pd.DataFrame, idx: pd.Index, evening_only: bool) -> pd.DataFrame:
    h = g[g["home"]].copy()
    if evening_only:
        h["evening"] = h["start_h"].between(18, 21)
    f = pd.DataFrame(index=idx)
    for col, m in (("reg", ~h["playoff"]), ("po", h["playoff"])):
        sel = h[m & h["evening"]] if evening_only else h[m]
        f[col] = idx.isin(set(sel["date"]))
    if evening_only:
        f["matinee"] = idx.isin(set(h.loc[~h["evening"], "date"])) & ~f["reg"] & ~f["po"]
    po = h[h["playoff"]]
    for (team, season), d in po.groupby(["team", "season"]):
        sel = d[d["evening"]] if evening_only else d
        f[f"po_{team}_{season}"] = idx.isin(set(sel["date"]))
    f.loc[f["po"], "reg"] = False  # a playoff night is not also a regular night
    return f


# ------------------------------------------------------------------ series
def weather() -> pd.Series:
    w = pd.read_csv(CACHE / "r4mh_ghcn.csv", usecols=["DATE", "PRCP"], low_memory=False)
    w = w[w["DATE"] >= "2021-12-01"]
    return pd.Series((w["PRCP"].values / 254) >= 0.01, index=pd.to_datetime(w["DATE"]).dt.date)


def dewey() -> pd.DataFrame:
    f = CACHE / f"{P}dewey.parquet"
    if not f.exists():
        agg, meta = load("r2agg", ROOT / "experiments/bar/r2-aggregate/run.py").series()
        out = agg[["date", "msg_within_0p5km", "msg_zip_cluster"]].copy()
        out["n0p5"], out["nzip"] = meta["n_stores"]["msg_within_0p5km"], meta["n_stores"]["msg_zip_cluster"]
        out.to_parquet(f)
    d = pd.read_parquet(f)
    d["date"] = pd.to_datetime(d["date"]).dt.date
    return d.set_index("date")


def mta() -> pd.DataFrame:
    penn, sys_ = load("r4mh", ROOT / "experiments/bar/r4-mtahourly/mtahourly.py").hourly()
    hrs = [21, 22, 23]
    return pd.DataFrame({"mta_post": penn[hrs].sum(axis=1, min_count=3), "sys_post": sys_[hrs].sum(axis=1, min_count=3)})


def taxi() -> pd.DataFrame:
    t = features.build("taxi")
    return pd.DataFrame({"taxi186": t["revenue"].values}, index=pd.to_datetime(t["date"]).dt.date)


# ------------------------------------------------------------------ model
def design(d: pd.DataFrame, cols: list[str], extra: list[str]) -> pd.DataFrame:
    ts = pd.to_datetime(pd.Series(d.index, index=d.index))
    X = pd.get_dummies(ts.dt.day_of_week, prefix="dow", drop_first=True).astype(float)
    X = X.join(pd.get_dummies(ts.dt.strftime("%Y%m"), prefix="ym", drop_first=True).astype(float))
    X.insert(0, "const", 1.0)
    hol = set(USFederalHolidayCalendar().holidays("2021-01-01", "2027-01-01").date)
    X["holiday"] = [x in hol or (x.month, x.day) in ((12, 24), (12, 31), (12, 26)) for x in d.index]
    X["rain"] = d["rain"].astype(float)
    for c in extra + cols:
        X[c] = d[c].astype(float)
    X = X.astype(float)
    return X.loc[:, (X.nunique() > 1) | (X.columns == "const")]


def fit(y: pd.Series, X: pd.DataFrame):
    return sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)


def frame(name: str, data: dict) -> tuple[pd.DataFrame, list[str]]:
    kind = SERIES[name]
    src = data[kind]
    d = pd.DataFrame({"y": src[{"dewey_0p5km": "msg_within_0p5km", "dewey_zip": "msg_zip_cluster"}.get(name, name)]})
    extra = []
    if kind == "mta":
        d["lsys"] = np.log(src["sys_post"])
        extra = ["lsys", "matinee"]
    d = d.join(flags(data["games"], d.index, evening_only=kind == "mta")).join(data["rain"].rename("rain"))
    d = d[d["y"] > 0].dropna(subset=["y", "rain"] + [e for e in extra if e != "matinee"])
    d["ly"] = np.log(d["y"].astype(float))
    return d, extra


def part_a(data: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, seas = [], []
    for name, kind in SERIES.items():
        d, extra = frame(name, data)
        for sp, (a, b) in PERIODS[kind].items():
            m = (d.index >= date.fromisoformat(a)) & (d.index <= date.fromisoformat(b))
            X = design(d[m], ["reg", "po"], extra)
            r = fit(d.loc[m, "ly"], X)
            diff = r.t_test("po - reg")
            for test, b_, se, p in (("reg", r.params["reg"], r.bse["reg"], r.pvalues["reg"]),
                                    ("po", r.params["po"], r.bse["po"], r.pvalues["po"]),
                                    ("po_minus_reg", float(diff.effect[0]), float(diff.sd[0][0]), float(diff.pvalue))):
                n = int(d.loc[m, test].sum()) if test != "po_minus_reg" else int(d.loc[m, "po"].sum())
                rows.append({"series": name, "period": sp, "range": f"{a}..{b}", "test": test, "n_ev": n,
                             "beta": b_, "se": se, "p": p, "pct": 100 * np.expm1(b_),
                             "lo": 100 * np.expm1(b_ - Z * se), "hi": 100 * np.expm1(b_ + Z * se)})
        # per team-season playoff dummies on the full sample (replication across seasons)
        pcols = [c for c in d.columns if c.startswith("po_") and d[c].any()]
        a, b = min(v[0] for v in PERIODS[kind].values()), max(v[1] for v in PERIODS[kind].values())
        m = (d.index >= date.fromisoformat(a)) & (d.index <= date.fromisoformat(b))
        pcols = [c for c in pcols if d.loc[m, c].any()]
        r = fit(d.loc[m, "ly"], design(d[m], ["reg"] + pcols, extra))
        pool = fit(d.loc[m, "ly"], design(d[m], ["reg", "po"], extra))
        for c in pcols + ["po", "reg"]:
            rr = pool if c in ("po", "reg") else r
            bb, se = rr.params[c], rr.bse[c]
            seas.append({"series": name, "term": "pooled_" + c if c in ("po", "reg") else c, "n_ev": int(d.loc[m, c].sum()),
                         "pct": 100 * np.expm1(bb), "lo": 100 * np.expm1(bb - Z * se), "hi": 100 * np.expm1(bb + Z * se),
                         "p": rr.pvalues[c], "beta": bb, "se": se,
                         "base": float(d.loc[m & ~d["reg"] & ~d["po"], "y"].mean())})
    t = pd.DataFrame(rows)
    for sp in ("train", "holdout"):
        mm = t["period"] == sp
        t.loc[mm, "q"] = bh(t.loc[mm, "p"])
    return t, pd.DataFrame(seas)


def bh(p: pd.Series) -> pd.Series:
    v = p.sort_values()
    adj = (v * len(v) / np.arange(1, len(v) + 1))[::-1].cummin()[::-1].clip(upper=1)
    return adj.reindex(p.index)


def verdicts(t: pd.DataFrame) -> pd.DataFrame:
    w = t.pivot_table(index=["series", "test"], columns="period", values=["pct", "lo", "hi", "n_ev", "q"], aggfunc="first")
    w.columns = [f"{b}_{a}" for a, b in w.columns]
    sig = lambda sp: (w[f"{sp}_lo"] > 0) | (w[f"{sp}_hi"] < 0)  # noqa: E731
    w["found"] = (sig("train") & (w["train_n_ev"] >= 10) & (w["train_q"] <= 0.10) & sig("holdout")
                  & (np.sign(w["train_pct"]) == np.sign(w["holdout_pct"])))
    return w.reset_index()


# ------------------------------------------------------------------ series maths
@lru_cache(maxsize=None)
def series_paths(p: float, hca: bool):
    """(prob, games, home games, won) for every best-of-7 path, 2-2-1-1-1 home pattern."""
    home = [True, True, False, False, True, False, True] if hca else [False, False, True, True, False, True, False]
    out = []
    def rec(w, l, k, pr, h):
        if w == 4 or l == 4:
            out.append((pr, k, h, w == 4))
            return
        hh = h + home[k]
        rec(w + 1, l, k + 1, pr * p, hh)
        rec(w, l + 1, k + 1, pr * (1 - p), hh)
    rec(0, 0, 0, 1.0, 0)
    return out


@lru_cache(maxsize=None)
def p_series(p: float) -> float:
    return sum(pr for pr, _, _, won in series_paths(p, True) if won)


@lru_cache(maxsize=None)
def p_game(P: float) -> float:
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if p_series(mid) < P else (lo, mid)
    return (lo + hi) / 2


@lru_cache(maxsize=None)
def e_home(P: float, hca: bool) -> float:
    return sum(pr * h for pr, _, h, _ in series_paths(p_game(P), hca))


# ------------------------------------------------------------------ Kalshi
def kalshi_price(ticker: str, before: date) -> tuple[float | None, float | None, float | None]:
    """(last trade close, yes bid, yes ask) of the last daily candle that ended before `before`."""
    f = CACHE / f"{P}cd_{ticker}.json"
    if not f.exists():
        return None, None, None
    cs = [c for c in json.loads(f.read_text())
          if datetime.fromtimestamp(c["end_period_ts"], NY).date() <= before]
    if not cs:
        return None, None, None
    c = cs[-1]
    g = lambda k: float(c[k]["close"]) if c.get(k) and c[k].get("close") is not None else None  # noqa: E731
    return g("price"), g("yes_bid"), g("yes_ask")


def kalshi_markets() -> pd.DataFrame:
    rows = []
    for f in sorted(CACHE.glob(f"{P}mk_*.json")):
        for m in json.loads(f.read_text()):
            if m["ticker"].rsplit("-", 1)[-1] in ("NYK", "NYR") or "NYK" in m["event_ticker"]:
                cf = CACHE / f"{P}cd_{m['ticker']}.json"
                cs = json.loads(cf.read_text()) if cf.exists() else []
                rows.append({"series": f.stem[len(P) + 3:], "ticker": m["ticker"], "title": m.get("title"),
                             "result": m.get("result"), "open": m["open_time"][:10], "close": m["close_time"][:10],
                             "n_candles": len(cs),
                             "volume": sum(float(c.get("volume") or 0) for c in cs),
                             "rule": (m.get("rules_primary") or "")[:160]})
    return pd.DataFrame(rows)


# Rounds of each MSG playoff run: (team, season, round label, Kalshi ticker on "NY wins this round").
ROUND_TICKERS = {
    ("knicks", 2025, "East 1st Round"): "KXNBASERIES-25DETNYK-NYK",
    ("knicks", 2025, "East Semifinals"): "KXNBASERIES-25NYKBOS-NYK",
    ("knicks", 2025, "East Finals"): "KXNBAEAST-25-NYK",
    ("knicks", 2026, "East 1st Round"): "KXNBASERIES-26ATLNYKR1-NYK",
    ("knicks", 2026, "East Semifinals"): "KXNBASERIES-26PHINYKR2-NYK",
    ("knicks", 2026, "East Finals"): "KXNBAEAST-26-NYK",
    ("knicks", 2026, "NBA Finals"): "KXNBA-26-NYK",
}
ORDER = {"knicks": ["East 1st Round", "East Semifinals", "East Finals", "NBA Finals"],
         "rangers": ["East 1st Round", "East 2nd Round", "East Final", "Stanley Cup Final"]}
BASE_HCA = {"knicks": 0.75, "rangers": 0.60}  # ASSUMED P(series win) for the home-court team when no market exists
RUNS = [("knicks", 2023), ("knicks", 2024), ("knicks", 2025), ("knicks", 2026), ("rangers", 2024)]


def rounds(g: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for team, season in RUNS:
        po = g[(g["team"] == team) & (g["season"] == season) & g["playoff"]].sort_values("date")
        for rnd, s in po.groupby("round", sort=False):
            s = s.sort_values("date")
            hca = bool(s.iloc[0]["home"])
            won = int(s["win"].sum()) == 4
            tk = ROUND_TICKERS.get((team, season, rnd))
            last, bid, ask = kalshi_price(tk, s.iloc[0]["date"]) if tk else (None, None, None)
            mid = (bid + ask) / 2 if bid and ask else last
            rows.append({"team": team, "season": season, "round": rnd, "k": ORDER[team].index(rnd), "opp": s.iloc[0]["opp"],
                         "g1": s.iloc[0]["date"], "games": len(s), "home_games": int(s["home"].sum()), "hca": hca,
                         "won": won, "ticker": tk or "", "kalshi_last": last, "kalshi_bid": bid, "kalshi_ask": ask,
                         "P": mid if mid else (BASE_HCA[team] if hca else 1 - BASE_HCA[team]),
                         "P_src": "kalshi" if mid else "assumed"})
    return pd.DataFrame(rows).sort_values(["team", "season", "k"]).reset_index(drop=True)


FUT_P = 0.5  # ASSUMED P(win) of each later, unknown round when sizing the hedge


@lru_cache(maxsize=None)
def future_home(k: int, team: str) -> float:
    """Expected home games in rounds after round k, given round k is won (later rounds 50/50 both ways)."""
    e, reach = 0.0, 1.0
    for _ in range(k + 1, 4):
        e += reach * 0.5 * (e_home(FUT_P, True) + e_home(FUT_P, False))
        reach *= FUT_P
    return e


def backtest(rd: pd.DataFrame, u: dict) -> pd.DataFrame:
    rows = []
    for (team, season), s in rd.groupby(["team", "season"]):
        rev = u[team] * s["home_games"].sum()
        pnl, cost = 0.0, 0.0
        for r in s.itertuples():
            n = u[team] * future_home(r.k, team)  # $ lost if eliminated now (contracts, $1 each)
            q = 1 - r.P                           # price of "NY loses this round"
            if r.ticker and r.kalshi_bid:
                q = 1 - r.kalshi_bid              # buying NO crosses the spread: pay 1 - yes bid
            pay = n * ((not r.won) - q - FEE(q))
            pnl += pay
            cost += n * (q + FEE(q))
        rows.append({"team": team, "season": season, "home_games": int(s["home_games"].sum()),
                     "rounds_won": int(s["won"].sum()), "revenue_unhedged": rev, "hedge_pnl": pnl,
                     "revenue_hedged": rev + pnl, "premium_paid": cost})
    return pd.DataFrame(rows)


def simulate(rd: pd.DataFrame, u: dict, n: int = 20000, seed: int = 0) -> pd.DataFrame:
    """Monte Carlo seasons per run: each round's outcome and length drawn from its pre-round P and
    actual home court; later rounds the run never reached use FUT_P and a coin-flip home court.
    The hedge is bought at the fair P (no spread) plus the Kalshi fee."""
    rng = np.random.default_rng(seed)
    rows, dist = [], []
    for (team, season), s in rd.groupby(["team", "season"]):
        known = {r.k: (r.P, r.hca) for r in s.itertuples()}
        first = min(known)
        un, he, nwon = [], [], []
        for _ in range(n):
            h_tot, pnl = 0, 0.0
            w = 0
            for k in range(first, 4):
                P, hca = known.get(k, (FUT_P, rng.random() < 0.5))
                paths = series_paths(p_game(P), hca)
                i = rng.choice(len(paths), p=[x[0] for x in paths])
                _, _, h, won = paths[i]
                h_tot += h
                q = 1 - P
                pnl += u[team] * future_home(k, team) * ((not won) - q - FEE(q))
                if not won:
                    break
                w += 1
            nwon.append(w)
            un.append(u[team] * h_tot)
            he.append(u[team] * h_tot + pnl)
        un, he, nwon = np.array(un), np.array(he), np.array(nwon)
        for w in range(5):
            if (nwon == w).any():
                dist.append({"team": team, "season": season, "rounds_won": w, "prob": float(np.mean(nwon == w)),
                             "mean_home_games": un[nwon == w].mean() / u[team], "mean_revenue": un[nwon == w].mean(),
                             "mean_revenue_hedged": he[nwon == w].mean()})
        rows.append({"team": team, "season": season, "mean_unhedged": un.mean(), "mean_hedged": he.mean(),
                     "sd_unhedged": un.std(), "sd_hedged": he.std(),
                     "p5_unhedged": np.quantile(un, 0.05), "p5_hedged": np.quantile(he, 0.05)})
    return pd.DataFrame(rows), pd.DataFrame(dist)



# ------------------------------------------------------------------ main
def main() -> None:
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    g = games()
    data = {"games": g, "rain": weather(), "dewey": dewey(), "mta": mta(), "taxi": taxi()}

    say("MSG playoff home games (ESPN):")
    hp = g[g["home"] & g["playoff"]]
    say(hp.groupby(["team", "season"]).agg(n=("date", "size"), first=("date", "min"), last=("date", "max"),
                                           rounds=("round", lambda r: ", ".join(dict.fromkeys(r)))).to_string())

    t, seas = part_a(data)
    t.to_csv(OUT / "results.csv", index=False, float_format="%.4g")
    seas.to_csv(OUT / "seasons.csv", index=False, float_format="%.4g")
    v = verdicts(t)
    say(f"\nPART A: {len(t)} fits ({len(t) // 2} per period), BH within period")
    say(v.round(3).to_string())
    say("\nPer team-season playoff effect (full sample per series, % vs a non-game day):")
    say(seas.round(3).to_string())

    # ---- $ per playoff home game
    say("\nPART B: $ per playoff home game")
    s0 = seas[(seas["series"] == "dewey_0p5km")].set_index("term")
    nst = int(data["dewey"]["n0p5"].iloc[0])
    base_store = s0.loc["pooled_po", "base"] / nst
    pct = {"pooled": s0.loc["pooled_po", "pct"], "lo": s0.loc["pooled_po", "lo"], "hi": s0.loc["pooled_po", "hi"]}
    say(f"  dewey 0.5 km basket: {nst} balanced stores, {base_store:.1f} panel visits/store/day on non-game days")
    for k, p_ in pct.items():
        say(f"  {k:6s} playoff uplift {p_:+.1f}% -> {base_store * p_ / 100:+.2f} panel visits/store/game "
            f"-> ${base_store * p_ / 100 * CHECK:+.0f}/store/game at ${CHECK:.0f} check;"
            f" scenario bar ({BAR_COVERS} covers x ${CHECK:.0f} = ${BAR_COVERS * CHECK:,.0f}/night): ${BAR_COVERS * CHECK * p_ / 100:+,.0f}/game")
    taxi_s = seas[(seas["series"] == "taxi186")].set_index("term")
    say(f"  taxi186 (zone 186 fares): playoff {taxi_s.loc['pooled_po', 'pct']:+.1f}% of "
        f"${taxi_s.loc['pooled_po', 'base']:,.0f}/day -> ${taxi_s.loc['pooled_po', 'base'] * taxi_s.loc['pooled_po', 'pct'] / 100:+,.0f}/game")
    # The $ basis for the bar: the scenario bar at the pooled dewey 0.5 km playoff uplift (floored at the
    # regular-season uplift if the playoff point estimate is lower; both shown).
    u_bar = BAR_COVERS * CHECK * max(pct["pooled"], 0) / 100
    u = {"knicks": u_bar, "rangers": u_bar}
    say(f"  -> hedge sizing uses u = ${u_bar:,.0f} per playoff home game (scenario bar, pooled dewey 0.5 km uplift)")

    say("\n  Best-of-7 (2-2-1-1-1) expected home games E[H] by series-win prob P and home court:")
    for P_ in (0.3, 0.5, 0.7, 0.85):
        say(f"    P={P_:.2f} per-game p={p_game(P_):.3f}  E[H|HCA]={e_home(P_, True):.2f}  E[H|no HCA]={e_home(P_, False):.2f}")
    for k in range(4):
        say(f"    $ lost if eliminated in round {k + 1} (later home games, FUT_P={FUT_P}): "
            f"E={future_home(k, 'knicks'):.2f} games = ${u_bar * future_home(k, 'knicks'):,.0f}")

    # ---- Kalshi
    km = kalshi_markets()
    km.to_csv(OUT / "kalshi_markets.csv", index=False)
    say("\nPART C: Kalshi NY markets (series, result, candles, volume):")
    say(km[["series", "ticker", "result", "open", "close", "n_candles", "volume"]].to_string())
    rd = rounds(g)
    rd.to_csv(OUT / "rounds.csv", index=False, float_format="%.4g")
    say("\nRounds of each MSG playoff run, with the pre-round price of 'NY wins this round':")
    say(rd.drop(columns=["k"]).to_string())

    # ---- backtest
    bt = backtest(rd, u)
    bt.to_csv(OUT / "backtest.csv", index=False, float_format="%.4g")
    say("\nPART D: realised runs, hedge = buy 'NY loses round' before each round, sized to later home games:")
    say(bt.round(0).to_string())
    say(f"  across runs: SD unhedged ${bt['revenue_unhedged'].std():,.0f} -> hedged ${bt['revenue_hedged'].std():,.0f}; "
        f"min ${bt['revenue_unhedged'].min():,.0f} -> ${bt['revenue_hedged'].min():,.0f}; "
        f"total hedge P&L ${bt['hedge_pnl'].sum():,.0f}")
    sim, dist = simulate(rd, u)
    sim.to_csv(OUT / "simulate.csv", index=False, float_format="%.4g")
    dist.to_csv(OUT / "outcomes.csv", index=False, float_format="%.4g")
    say("\nMonte Carlo (20k seasons per run, fair prices + fee):")
    say(sim.round(0).to_string())
    say("\nSeason playoff revenue by outcome (rounds won), Monte Carlo:")
    say(dist.round(3).to_string())
    (OUT / "output.txt").write_text("\n".join(LINES) + "\n")


if __name__ == "__main__":
    main()
