"""Round 5: SF parking meter revenue on Warriors/Giants PLAYOFF home games, $ at stake per round,
the Kalshi advancement markets that settle on it, and a pre-round hedge backtest.

Revenue: SFMTA meter revenue, daily sum(gross_paid_amt) for the street blocks within 600 m of
Chase Center ("chase", 36 blocks) and Oracle Park ("oracle", 34 blocks). Reused from
r4-sfparking (cache r2-cache/r4sf_rev_*.csv).
Games: ESPN team schedules, season types 2 (regular), 3 (post) and 5 (play-in), Pacific date.
  Warriors home games count for SF only at Chase Center (2019-10 on). The 2017-2019 playoff home
  games at Oracle Arena (Oakland) are a placebo: they should not move SF meters.
  Giants: the only home playoff games 2017-2026 are the 2021 NLDS (3 at Oracle Park).

Model (Mon-Sat; Sundays are mostly free):
    log(rev_t) = year-month FE + DOW FE + holiday + b_reg*gsw_reg + b_po*gsw_po
                 + c_reg*sfg_reg + c_po*sfg_po + e,       HAC(7), t on df_resid
  gsw_po = Warriors play-in or playoff home game at Chase. Train = 2022 (title run, 12 games);
  holdout = 2023-01..2026-09 (2023 + 2025, 12 games incl. one play-in), fitted independently.
  The same model in $ levels gives the dollar uplift per game.

Exposure: best-of-7, 2-2-1-1-1 home pattern, per-game win prob from regular-season win% (log5)
plus a home-court edge, gives E[home games] per round. $ at stake on a series = the expected
uplift from all LATER rounds, conditional on winning it.
Hedge: before the play-in/playoffs and before each round, buy NO on "Warriors advance"
(KXNBAPLAYOFF, then KXNBASERIES) sized at $ at stake / $1. Prices: Kalshi daily candles where they
exist (2025, 2026), else the model probability + $0.02; fee 0.07*p*(1-p) per contract.

Run from backend/: .venv/bin/python ../experiments/bar/r5-sfplayoffs/sfplayoffs.py
"""

import importlib.util
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

import httpx
import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.holiday import USFederalHolidayCalendar
from scipy import stats

OUT = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("sfp", OUT.parent / "r4-sfparking" / "sfparking.py")
sfp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sfp)
CACHE = sfp.CACHE
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"

TRAIN = [("2022-01-01", "2022-12-31")]
HOLD = [("2023-01-01", "2026-09-30")]
GIANTS21 = [("2021-06-15", "2021-12-31")]  # full-capacity reopening to year end
PLACEBO = [("2017-01-01", "2019-08-31")]   # Oracle Arena era, Chase not yet open
BH_Q, EDGE, FEE, HCA = 0.10, 0.02, 0.07, 0.32  # HCA: logit home edge, ~58% home win rate
RNG = np.random.default_rng(5)
LINES: list[str] = []


def say(s=""):
    print(s, flush=True)
    LINES.append(s)


# ---------- data ----------
def games(league: str, team: str, seasons) -> pd.DataFrame:
    out = CACHE / f"r5sfplayoffs_games_{team}.csv"
    if out.exists():
        return pd.read_csv(out, parse_dates=["date"])
    rows = []
    for season in seasons:
        for st in (2, 3, 5):
            url = f"https://site.api.espn.com/apis/site/v2/sports/{league}/teams/{team}/schedule"
            d = httpx.get(url, params={"season": season, "seasontype": st}, timeout=60).json()
            for e in d.get("events", []):
                c = e["competitions"][0]
                me = next((t for t in c["competitors"] if t["team"]["abbreviation"].lower() == team), None)
                opp = next((t for t in c["competitors"] if t is not me), None)
                if me is None or not c.get("status", {}).get("type", {}).get("completed", True):
                    continue
                local = pd.Timestamp(e["date"]).tz_convert("America/Los_Angeles")
                rows.append({"date": local.normalize().tz_localize(None), "season": season, "stype": st,
                             "home": me.get("homeAway") == "home", "win": bool(me.get("winner")),
                             "opp": opp["team"]["abbreviation"] if opp else "",
                             "venue": c.get("venue", {}).get("fullName", ""),
                             "note": "; ".join(n.get("headline", "") for n in c.get("notes", []))})
    g = pd.DataFrame(rows).drop_duplicates(["date", "home"])
    g.to_csv(out, index=False)
    return g


def standings(season: int) -> dict:
    out = CACHE / f"r5sfplayoffs_nbastand_{season}.json"
    if not out.exists():
        d = httpx.get("https://site.api.espn.com/apis/v2/sports/basketball/nba/standings",
                      params={"season": season}, timeout=60).json()
        wp = {}
        for conf in d["children"]:
            for en in conf["standings"]["entries"]:
                st = {s["name"]: s.get("value") for s in en["stats"]}
                wp[en["team"]["abbreviation"]] = {"wp": st["winPercent"], "seed": st.get("playoffSeed"),
                                                  "conf": conf["abbreviation"]}
        out.write_text(json.dumps(wp))
    return json.loads(out.read_text())


def candles(ticker: str, start: str, end: str) -> pd.DataFrame:
    out = CACHE / f"r5sfplayoffs_cdl_{ticker}_{start}_{end}.csv"
    if out.exists():
        return pd.read_csv(out, parse_dates=["date"])
    rows = []
    for base in ("/historical/markets/", "/markets/"):
        p = {"start_ts": int(pd.Timestamp(start).timestamp()), "end_ts": int(pd.Timestamp(end).timestamp()),
             "period_interval": 1440}
        r = httpx.get(KALSHI + base + ticker + "/candlesticks", params=p, timeout=60)
        if r.status_code == 200 and r.json().get("candlesticks"):
            for c in r.json()["candlesticks"]:
                f = lambda k, j: float(c[k][j]) if c[k].get(j) is not None else np.nan
                rows.append({"date": pd.Timestamp(c["end_period_ts"], unit="s"), "close": f("price", "close"),
                             "bid": f("yes_bid", "close"), "ask": f("yes_ask", "close"),
                             "vol": float(c.get("volume") or 0), "oi": float(c.get("open_interest") or 0)})
            break
    df = pd.DataFrame(rows, columns=["date", "close", "bid", "ask", "vol", "oi"])
    df.to_csv(out, index=False)
    return df


def price_before(ticker: str, day: str, start: str) -> dict | None:
    """Last daily candle ending on/before `day` 00:00 UTC (~ 5pm PT the evening before)."""
    c = candles(ticker, start, (pd.Timestamp(day) + pd.Timedelta(days=2)).strftime("%Y-%m-%d"))
    c = c[c["date"] <= pd.Timestamp(day) + pd.Timedelta(hours=8)].dropna(subset=["bid", "ask"])
    c = c[(c["bid"] > 0) & (c["ask"] < 1)]
    if c.empty:
        return None
    r = c.iloc[-1]
    return {"date": r["date"].strftime("%Y-%m-%d"), "bid": r["bid"], "ask": r["ask"],
            "mid": (r["bid"] + r["ask"]) / 2, "vol": r["vol"], "oi": r["oi"]}


# ---------- model ----------
def in_periods(idx, periods):
    m = np.zeros(len(idx), bool)
    for lo, hi in periods:
        m |= np.asarray((idx >= lo) & (idx <= hi))
    return m


def frame(rev: pd.Series, gsw: pd.DataFrame, sfg: pd.DataFrame) -> pd.DataFrame:
    df = rev.to_frame()
    hol = USFederalHolidayCalendar().holidays("2016-01-01", "2026-12-31")
    df["holiday"] = df.index.isin(hol).astype(float)
    df["ym"] = df.index.to_period("M").astype(str)
    df["dow"] = df.index.day_of_week
    med = df.groupby(["ym", "dow"])["rev"].transform("median")
    df["gap"] = df["rev"] < 0.3 * med
    gh = gsw[gsw["home"]]
    chase = gh["venue"].str.contains("Chase", na=False)
    oak = gh["venue"].str.contains("Oracle Arena", na=False)
    sh = sfg[sfg["home"] & sfg["venue"].str.contains("Park", na=False)]
    sets = {"gsw_reg": gh[chase & (gh["stype"] == 2)], "gsw_po": gh[chase & (gh["stype"] != 2)],
            "oak_po": gh[oak & (gh["stype"] != 2)], "oak_reg": gh[oak & (gh["stype"] == 2)],
            "sfg_reg": sh[sh["stype"] == 2], "sfg_po": sh[sh["stype"] != 2]}
    for k, g in sets.items():
        df[k] = df.index.isin(g["date"]).astype(float)
    return df


CONTROLS = ["gsw_reg", "gsw_po", "sfg_reg", "sfg_po", "oak_reg", "oak_po"]


def fit(df: pd.DataFrame, x: str, log=True, sundays=False, extra=()):
    d = df[~df["gap"] & (df["rev"] > 0)]
    if not sundays:
        d = d[d["dow"] != 6]
    X = pd.get_dummies(d["ym"], prefix="ym", drop_first=True).astype(float)
    X = X.join(pd.get_dummies(d["dow"], prefix="dow", drop_first=True).astype(float))
    X["holiday"] = d["holiday"]
    for c in [*CONTROLS, *extra]:
        X[c] = d[c]
    X = X.loc[:, X.std() > 0]
    X.insert(0, "const", 1.0)
    y = np.log(d["rev"]) if log else d["rev"]
    res = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 7})
    tc = stats.t.ppf(0.95, res.df_resid)
    out = {}
    for v in ([x] if isinstance(x, str) else x):
        if v not in res.params:
            out[v] = None
            continue
        b, se = res.params[v], res.bse[v]
        out[v] = dict(beta=b, se=se, lo=b - tc * se, hi=b + tc * se, p=2 * stats.t.sf(abs(b / se), res.df_resid),
                      n_event=int(d[v].sum()), n=len(d))
    return out, res


def diff_test(res, a: str, b: str):
    """po minus reg: same-model linear contrast."""
    if a not in res.params or b not in res.params:
        return None
    r = np.zeros(len(res.params))
    r[list(res.params.index).index(a)], r[list(res.params.index).index(b)] = 1, -1
    t = res.t_test(r)
    est, se = float(np.squeeze(t.effect)), float(np.squeeze(t.sd))
    tc = stats.t.ppf(0.95, res.df_resid)
    return dict(beta=est, se=se, lo=est - tc * se, hi=est + tc * se, p=float(np.squeeze(t.pvalue)), n_event=None)


def bh(p):
    p = np.asarray(p, float)
    n, o = len(p), np.argsort(p)
    adj, prev = np.empty(n), 1.0
    for rank, i in reversed(list(enumerate(o, start=1))):
        prev = min(prev, p[i] * n / rank)
        adj[i] = prev
    return adj


# ---------- series math ----------
def p_game(wp_a: float, wp_b: float, a_home: bool) -> float:
    lg = lambda p: np.log(p / (1 - p))
    z = lg(np.clip(wp_a, .05, .95)) - lg(np.clip(wp_b, .05, .95)) + (HCA if a_home else -HCA)
    return 1 / (1 + np.exp(-z))


def series_dist(wp_a, wp_b, a_hca: bool, best_of=7):
    """Exact distribution over (A wins series, # A home games) for 2-2-1-1-1."""
    home_pat = {7: [1, 1, 0, 0, 1, 0, 1], 5: [1, 1, 0, 0, 1], 3: [1, 1, 1]}[best_of]
    need = best_of // 2 + 1
    out = {}

    def rec(g, wa, wb, nh, pr):
        if wa == need or wb == need:
            k = (wa == need, nh)
            out[k] = out.get(k, 0) + pr
            return
        a_home = bool(home_pat[g]) == a_hca
        p = p_game(wp_a, wp_b, a_home)
        rec(g + 1, wa + 1, wb, nh + a_home, pr * p)
        rec(g + 1, wa, wb + 1, nh + a_home, pr * (1 - p))

    rec(0, 0, 0, 0, 1.0)
    return out


def series_summary(wp_a, wp_b, a_hca):
    d = series_dist(wp_a, wp_b, a_hca)
    pw = sum(v for (w, _), v in d.items() if w)
    eh = sum(v * h for (_, h), v in d.items())
    eh_w = sum(v * h for (w, h), v in d.items() if w) / max(pw, 1e-9)
    eh_l = sum(v * h for (w, h), v in d.items() if not w) / max(1 - pw, 1e-9)
    return dict(p_win=pw, e_home=eh, e_home_win=eh_w, e_home_loss=eh_l, dist=d)


GENERIC_OPP = {1: 0.55, 2: 0.62, 3: 0.65, 4: 0.66}  # typical later-round opponent regular-season win%


def future_value(wp: float, from_round: int, usd: float) -> float:
    """E[$ uplift from rounds >= from_round] given the team reaches from_round (generic opponents)."""
    if from_round > 4:
        return 0.0
    o = GENERIC_OPP[from_round]
    s = series_summary(wp, o, wp > o)
    return usd * s["e_home"] + s["p_win"] * future_value(wp, from_round + 1, usd)


def main():
    gsw = games("basketball/nba", "gs", range(2017, 2027))
    sfg = games("baseball/mlb", "sf", range(2017, 2027))
    po = gsw[(gsw["stype"] != 2)]
    say("# Warriors post-season (play-in = stype 5, playoffs = 3) home games")
    for s, g in po.groupby("season"):
        h = g[g["home"]]
        say(f"  {s}: {len(g)} games, {len(h)} home ({', '.join(sorted(h['venue'].unique()))}); "
            f"last: {g.sort_values('date').iloc[-1]['note']}")
    spo = sfg[(sfg["stype"] != 2)]
    say("# Giants post-season games: " + ", ".join(f"{s}: {len(g)} ({int(g['home'].sum())} home)"
                                                     for s, g in spo.groupby("season")))

    series = {"chase": sfp.area_rev("chase"), "oracle": sfp.area_rev("oracle")}
    frames = {k: frame(v, gsw, sfg) for k, v in series.items()}

    # ---------- 1. uplift ----------
    say("\n# 1. Per-game uplift (log points; Mon-Sat; ym+DOW FE, holiday, all game dummies)")
    tests = []
    hdr = f"{'series':7s} {'event':14s} {'period':8s} {'beta':>8s} {'90% CI':>18s} {'n_ev':>5s} {'p':>7s}"
    say(hdr)
    fits = {}
    for s, df in frames.items():
        for pname, per in (("train", TRAIN), ("holdout", HOLD)):
            sub = df[in_periods(df.index, per)]
            r, res = fit(sub, ["gsw_po", "gsw_reg", "sfg_reg"])
            r["po_minus_reg"] = diff_test(res, "gsw_po", "gsw_reg")
            rl, _ = fit(sub, ["gsw_po", "gsw_reg"], log=False)
            fits[(s, pname)] = (r, rl, sub)
            for k in ("gsw_po", "gsw_reg", "po_minus_reg"):
                tests.append((s, k, pname, r[k]))
        r, res = fit(df[in_periods(df.index, GIANTS21)], ["sfg_po", "sfg_reg"])
        r["po_minus_reg"] = diff_test(res, "sfg_po", "sfg_reg")
        fits[(s, "giants21")] = r
        for k in ("sfg_po", "sfg_reg", "po_minus_reg"):
            tests.append((s, "sfg:" + k if k == "po_minus_reg" else k, "2021", r[k]))
        r, _ = fit(df[in_periods(df.index, PLACEBO)], ["oak_po", "oak_reg"])
        for k in ("oak_po", "oak_reg"):
            tests.append((s, k + "(placebo)", "2017-19", r[k]))
    padj = bh([t[3]["p"] for t in tests])
    for (s, k, pn, r), pa in zip(tests, padj):
        ne = "-" if r["n_event"] is None else str(r["n_event"])
        say(f"{s:7s} {k:14s} {pn:8s} {r['beta']:+8.3f} [{r['lo']:+.3f},{r['hi']:+.3f}] {ne:>5s} "
            f"{r['p']:7.4f}  p_bh={pa:.4f}")
    say(f"{len(tests)} tests, BH at {BH_Q:.0%} over all of them.")

    # $ uplift: levels model, Mon-Sat; Sunday playoff home games valued with the Sunday reg-season estimate
    usd = {}
    for s in frames:
        for pn in ("train", "holdout"):
            _, rl, sub = fits[(s, pn)]
            usd[(s, pn)] = rl["gsw_po"]["beta"]
            say(f"$ uplift {s} {pn}: playoff +${rl['gsw_po']['beta']:,.0f} [{rl['gsw_po']['lo']:+,.0f},"
                f"{rl['gsw_po']['hi']:+,.0f}] per game, regular +${rl['gsw_reg']['beta']:,.0f} "
                f"[{rl['gsw_reg']['lo']:+,.0f},{rl['gsw_reg']['hi']:+,.0f}]")
    df_all = frames["chase"][in_periods(frames["chase"].index, [("2022-01-01", "2026-09-30")])]
    _, rl_all_res = fit(df_all, "gsw_po", log=False)
    rsun, _ = fit(df_all, ["gsw_po", "gsw_reg"], log=False, sundays=True,
                  extra=())
    df_all = df_all.assign(sun_game=((df_all["dow"] == 6) & ((df_all["gsw_reg"] + df_all["gsw_po"]) > 0)).astype(float))
    rsun2, _ = fit(df_all, ["gsw_po", "gsw_reg", "sun_game"], log=False, sundays=True, extra=("sun_game",))
    rpool, _ = fit(frames["chase"][in_periods(frames["chase"].index, [("2022-01-01", "2026-09-30")])],
                   ["gsw_po", "gsw_reg"], log=False)
    U = rpool["gsw_po"]["beta"]
    U_se = rpool["gsw_po"]["se"]
    say(f"Pooled 2022-2026 chase-block $ uplift per playoff home game (Mon-Sat): ${U:,.0f} (se {U_se:,.0f}); "
        f"regular ${rpool['gsw_reg']['beta']:,.0f}. With Sundays + Sunday-game term: po ${rsun2['gsw_po']['beta']:,.0f}, "
        f"Sunday game extra ${rsun2['sun_game']['beta']:+,.0f}.")
    _, rlo, subo = fits[("oracle", "holdout")]
    U_or = fit(frames["oracle"][in_periods(frames["oracle"].index, [("2022-01-01", "2026-09-30")])],
               ["gsw_po"], log=False)[0]["gsw_po"]["beta"]
    sf21 = fit(frames["oracle"][in_periods(frames["oracle"].index, GIANTS21)], ["sfg_po", "sfg_reg"], log=False)[0]
    say(f"Oracle-park blocks: Warriors playoff ${U_or:,.0f}/game; Giants 2021 NLDS ${sf21['sfg_po']['beta']:,.0f}/game "
        f"[{sf21['sfg_po']['lo']:+,.0f},{sf21['sfg_po']['hi']:+,.0f}] (n=3) vs Giants reg ${sf21['sfg_reg']['beta']:,.0f}")

    # Actual excess revenue on each unscheduled home date (rev - median of same ym x DOW non-game days)
    d = frames["chase"]
    nongame = d[(d[CONTROLS].sum(axis=1) == 0) & ~d["gap"]]
    base = nongame.groupby(["ym", "dow"])["rev"].median()
    pod = d[d["gsw_po"] == 1].copy()
    pod["base"] = [base.get((y, w), np.nan) for y, w in zip(pod["ym"], pod["dow"])]
    pod["excess"] = pod["rev"] - pod["base"]
    pod["season"] = pod.index.year
    say("\nPer-date excess on chase blocks (rev - same ym x DOW non-game median), by season:")
    for y, g in pod.groupby("season"):
        say(f"  {y}: {len(g)} home dates, excess ${g['excess'].sum():,.0f} total, ${g['excess'].mean():,.0f}/game "
            f"(min {g['excess'].min():,.0f}, max {g['excess'].max():,.0f})")

    # ---------- 2. exposure per round ----------
    say(f"\n# 2. $ at stake per round (chase blocks, U = ${U:,.0f}/home game)")
    say("Series table, best-of-7 2-2-1-1-1: P(win), E[home games], E[home|win], E[home|lose]")
    for wpa, wpb, hca in [(0.65, 0.55, True), (0.55, 0.65, False), (0.60, 0.60, True), (0.60, 0.60, False),
                          (0.50, 0.70, False)]:
        s = series_summary(wpa, wpb, hca)
        hd = {h: sum(v for (w, hh), v in s["dist"].items() if hh == h) for h in range(2, 5)}
        say(f"  wp {wpa:.2f} vs {wpb:.2f}, HCA={hca!s:5s}: P(win)={s['p_win']:.2f}  E[H]={s['e_home']:.2f} "
            f"(|win {s['e_home_win']:.2f}, |lose {s['e_home_loss']:.2f})  P(H=2,3,4)="
            + ",".join(f"{hd[h]:.2f}" for h in hd) + f"  -> ${U*s['e_home']:,.0f} this round")
    for wp in (0.50, 0.60, 0.70):
        say(f"  team wp {wp:.2f}: $ at stake on winning R1 = ${future_value(wp, 2, U):,.0f}, R2 = "
            f"${future_value(wp, 3, U):,.0f}, WCF = ${future_value(wp, 4, U):,.0f}, Finals = $0; "
            f"whole run from R1 E=${future_value(wp, 1, U):,.0f}")

    # ---------- 3/4. markets + backtest ----------
    say("\n# 3-4. Kalshi markets and pre-round hedge backtest (Warriors, Chase era)")
    plan = season_plans(gsw)
    seasons_out = []
    for yr, p in plan.items():
        st = standings(yr)
        wp = st["GS"]["wp"]
        realized = pod[(pod.index >= f"{yr}-04-01") & (pod.index <= f"{yr}-06-30")]["excess"].sum()
        pnl, legs = 0.0, []
        for leg in p["legs"]:
            if leg["p_model"] >= 1.0:  # already clinched: no advancement risk left to hedge
                continue
            if leg["kind"] == "makes":
                fv = future_value(wp, 1, U)
                q_model = leg["p_model"]
            else:
                fv = future_value(wp, leg["round"] + 1, U)
                q_model = leg["p_model"]
            px = price_before(leg["ticker"], leg["day"], leg["start"]) if leg.get("ticker") else None
            if px:
                no_cost = 1 - px["bid"]  # buy NO at the NO ask = 1 - YES bid
                src = f"Kalshi {px['date']} bid/ask {px['bid']:.2f}/{px['ask']:.2f} vol {px['vol']:,.0f}"
                q_yes = px["mid"]
            else:
                no_cost = (1 - q_model) + EDGE
                src = "model"
                q_yes = q_model
            fee = FEE * no_cost * (1 - no_cost)
            n = fv  # contracts paying $1 each when eliminated
            pays = 0.0 if leg["advanced"] else 1.0
            leg_pnl = n * (pays - no_cost - fee)
            pnl += leg_pnl
            legs.append(f"{leg['label']}: P(yes) {q_yes:.2f} [{src}], stake ${fv:,.0f} -> buy {n:,.0f} NO @ "
                        f"{no_cost:.2f}+fee {fee:.3f}; advanced={leg['advanced']}; P&L ${leg_pnl:+,.0f}")
        seasons_out.append(dict(yr=yr, realized=realized, pnl=pnl, wp=wp))
        say(f"{yr} (GSW reg wp {wp:.3f}): realized playoff/play-in excess ${realized:,.0f}; hedge P&L ${pnl:+,.0f}; "
            f"hedged ${realized + pnl:,.0f}")
        for l in legs:
            say("    " + l)
    so = pd.DataFrame(seasons_out)
    say(f"Across {len(so)} seasons: SD unhedged ${so['realized'].std():,.0f}, hedged ${(so['realized'] + so['pnl']).std():,.0f}; "
        f"min unhedged ${so['realized'].min():,.0f}, hedged ${(so['realized'] + so['pnl']).min():,.0f}; "
        f"mean hedge cost ${-so['pnl'].mean():,.0f}/season")

    # Simulation: seasons drawn from model probabilities, per-game $ noise from observed excess SD
    # within-season SD, so cross-season level drift in $/game is not counted as per-game noise
    sd_game = (pod["excess"] - pod.groupby("season")["excess"].transform("mean")).std()
    say(f"\nSimulation (20,000 seasons per profile; per-game $ ~ N(U, {sd_game:,.0f}); generic opponents; "
        f"hedge priced at fair p + ${EDGE:.2f} + fee)")
    for wp, p_make in ((0.65, 0.97), (0.57, 0.75), (0.52, 0.40)):
        sim(wp, p_make, U, sd_game)

    say("\n# Kalshi coverage for Warriors / Giants (series fetched; settled + active)")
    mk = json.loads((CACHE / "r5sfplayoffs_markets.json").read_text())
    for s, ms in mk.items():
        hits = [m for m in ms if any(k in m["ticker"] for k in ("GSW", "-SF")) or m["ticker"].endswith("SF")]
        if hits:
            say(f"  {s}: " + "; ".join(f"{m['ticker']}={m.get('result') or m['status']}" for m in hits[:6])
                + (" ..." if len(hits) > 6 else ""))
    (OUT / "output.txt").write_text("\n".join(LINES) + "\n")


def season_plans(gsw: pd.DataFrame) -> dict:
    """Per Chase-era season: hedge legs (make playoffs, then each series), each with the decision day,
    the Kalshi ticker if one exists, the model P(advance) and the outcome."""
    plans = {}
    for yr in (2022, 2023, 2024, 2025, 2026):
        st = standings(yr)
        wp = st["GS"]["wp"]
        g = gsw[(gsw["season"] == yr) & (gsw["stype"] != 2)].sort_values("date")
        legs = []
        pin = g[g["stype"] == 5]
        poff = g[g["stype"] == 3]
        first = g["date"].min().strftime("%Y-%m-%d") if len(g) else f"{yr}-04-14"
        if len(pin) or len(poff) == 0:
            # play-in team: needs 1 (7/8 seed, two tries) or 2 (9/10) wins; opponents ~ .55
            seed = st["GS"]["seed"] or 10
            pw = p_game(wp, 0.55, seed <= 8)
            p_make = 1 - (1 - pw) * (1 - p_game(wp, 0.55, True)) if seed <= 8 else pw * p_game(wp, 0.55, False)
            legs.append(dict(kind="makes", label=f"make playoffs (seed {seed:.0f}, play-in)", day=first,
                             ticker=f"KXNBAPLAYOFF-{str(yr)[2:]}-GSW" if yr >= 2025 else None,
                             start=f"{yr-1}-07-01", p_model=p_make, advanced=len(poff) > 0))
        else:
            legs.append(dict(kind="makes", label="make playoffs (clinched before window)", day=first,
                             ticker=None, start=first, p_model=1.0, advanced=True))
        for rnd, (opp, gg) in enumerate(poff.groupby("opp", sort=False), start=1):
            gg = gg.sort_values("date")
            ow = st.get(opp, {}).get("wp", 0.6)
            hca = bool(gg.iloc[0]["home"])
            s = series_summary(wp, ow, hca)
            won = gg["win"].sum() == 4
            day = gg["date"].min().strftime("%Y-%m-%d")
            tk = None
            if yr == 2025:
                tk = {"HOU": "KXNBASERIES-25GSWHOU-GSW", "MIN": "KXNBASERIES-25GSWMIN-GSW"}.get(opp)
            legs.append(dict(kind="series", round=rnd, label=f"R{rnd} vs {opp} (opp wp {ow:.3f}, HCA={hca})",
                             day=day, ticker=tk, start=(gg["date"].min() - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
                             p_model=s["p_win"], advanced=bool(won)))
        plans[yr] = {"legs": legs}
    return plans


def sim(wp: float, p_make: float, U: float, sd_game: float, n=20000):
    rev, hedged = np.zeros(n), np.zeros(n)
    for i in range(n):
        r = h = 0.0
        made = RNG.random() < p_make
        fv = future_value(wp, 1, U)
        no = (1 - p_make) + EDGE
        h += fv * ((0.0 if made else 1.0) - no - FEE * no * (1 - no))
        rnd = 1
        while made and rnd <= 4:
            o = GENERIC_OPP[rnd]
            s = series_summary(wp, o, wp > o)
            keys = list(s["dist"])
            k = keys[RNG.choice(len(keys), p=np.array([s["dist"][x] for x in keys]))]
            won, nh = k
            r += RNG.normal(U, sd_game, nh).sum()
            fv = future_value(wp, rnd + 1, U)
            no = (1 - s["p_win"]) + EDGE
            h += fv * ((0.0 if won else 1.0) - no - FEE * no * (1 - no))
            if not won:
                break
            rnd += 1
        rev[i], hedged[i] = r, r + h
    say(f"  wp {wp:.2f}, P(make) {p_make:.2f}: mean ${rev.mean():,.0f} -> ${hedged.mean():,.0f}; "
        f"SD ${rev.std():,.0f} -> ${hedged.std():,.0f} ({hedged.std()/rev.std()-1:+.0%}); "
        f"p5 ${np.percentile(rev, 5):,.0f} -> ${np.percentile(hedged, 5):,.0f}; "
        f"p95 ${np.percentile(rev, 95):,.0f} -> ${np.percentile(hedged, 95):,.0f}")


if __name__ == "__main__":
    main()
