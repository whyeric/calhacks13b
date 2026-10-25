"""R5 playoffmobility: taxi, Uber/Lyft and subway around MSG on Knicks and Rangers playoff nights.

Q1 Uplift. Per evening, log of a fixed clock-window count, regressed on day flags
       reg_home   regular-season (or play-in) Knicks/Rangers game at MSG, evening start 18:00-21:00
       post_home  playoff game at MSG, evening start
       post_away  playoff away game (no MSG game that day), evening start
   plus DOW, year-month FE, federal holiday and the KXRAIN flag (GHCN USW00094728 PRCP >= 0.01 in).
   Days with a matinee NY game (start < 18:00 or > 21:00) are dropped, so every kept game ends inside
   the windows. HAC(7) errors, z = 1.645. Outcomes (all public, aggregated):
     (TLC outcomes: Apr-Jun evenings only, see tlc())
       area_pu     TLC yellow + HVFHV pickups 21:00-00:59 in zones 186/100/164 (MSG, Garment, Midtown S)
       area_usd    driver gross of those pickups (fare + tip; HVFHV driver_pay + tips)
       area_do     TLC dropoffs 17:00-19:59 in the same zones (arrivals)
       penn_post   subway entries 21:00-00:59 at 34 St-Penn (complexes 164 + 318)
     reverse / natural hedge (do playoff nights pull riders off other modes or neighbourhoods?):
       nl_pu       TLC pickups 19:00-02:59 in 11 nightlife zones (EV, LES, WV, GV, Union Sq, Chelsea,
                   Flatiron, Hell's Kitchen, Williamsburg)
       city_trips  TLC citywide daily trips, yellow + HVFHV (r2-taxi daily cache, 2022-2025)
       sys_eve     subway system-wide entries 19:00-00:59
   Tests per period: 7 outcomes x {post_home, post_away, reg_home, post_home - reg_home} = 28.
   Train 2022-01-01..2023-12-31 (playoffs: Rangers 2022, 2023; Knicks 2023); holdout refit
   independently on 2024-01-01..2025-12-31 (TLC) / ..2026-06-30 (MTA; 2026 TLC when cached).
   BH at 10% inside each period over all 28. Per-season playoff-home effects are descriptive only.
Q2 Exposure per round, Q3 hedge backtest: see exposure section below (uses the pooled 2022-2026
   playoff-home $ uplift; Kalshi prices from r5-markets when cached, else a fair 50/50 series price).

Run fetch.py first, then from backend/:  .venv/bin/python ../experiments/bar/r5-mobility/mobility.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.holiday import USFederalHolidayCalendar
from statsmodels.stats.multitest import multipletests

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT))
import games as G  # noqa: E402
import hedge as H  # noqa: E402

CACHE = G.CACHE
Z = 1.645
PERIODS = {"train": ("2022-01-01", "2023-12-31"), "holdout": ("2024-01-01", "2026-06-30")}
EVENTS = ["post_home", "post_away", "reg_home"]
OUTCOMES = ["area_pu", "area_usd", "area_do", "penn_post", "nl_pu", "city_trips", "sys_eve"]
AREA = ("186", "100", "164")
LINES: list[str] = []


def say(s: str = "") -> None:
    print(s)
    LINES.append(s)


# ------------------------------------------------------------------ inputs
def _window(h: pd.DataFrame, col: str, hours: tuple[int, ...]) -> pd.Series:
    """Sum an hourly series over clock hours; hours 0-4 belong to the previous evening."""
    t = h["hour"]
    ev = (t - pd.Timedelta(hours=5)).dt.normalize()  # evening date
    keep = t.dt.hour.isin(hours)
    return h[keep].groupby(ev[keep])[col].sum()


def tlc() -> pd.DataFrame:
    fs = sorted((CACHE / "r5playoffmobility_tlc").glob("*.parquet"))
    if not fs:
        return pd.DataFrame()
    t = pd.concat([pd.read_parquet(f).assign(svc=f.name.split("_")[0]) for f in fs], ignore_index=True)
    if "series" not in t:  # 2026 parquet-derived files are wide; reshape to the SoQL long layout
        t["series"] = np.nan
    wide = t[t["series"].isna()]
    long = t[t["series"].notna()]
    rows = []
    if len(long):
        a = long[long["zone"].isin(AREA)]
        pu = a[a.series == "pu"].groupby("hour")[["n", "usd"]].sum().add_prefix("area_pu_")
        do = a[a.series == "do"].groupby("hour")["n"].sum().rename("area_do_n")
        nl = long[long.series == "nlpu"].groupby("hour")["n"].sum().rename("nl_pu_n")
        rows.append(pd.concat([pu, do, nl], axis=1))
    if len(wide):
        w = wide.groupby("hour")[["area_pu", "area_pu_usd", "area_do", "nl_pu"]].sum()
        rows.append(w.rename(columns={"area_pu": "area_pu_n", "area_do": "area_do_n", "nl_pu": "nl_pu_n"}))
    h = pd.concat(rows).groupby(level=0).sum().reset_index().rename(columns={"index": "hour"})
    h["hour"] = pd.to_datetime(h["hour"])
    # a month is complete only if both services are cached: drop evenings from half-cached months
    have = t.groupby(t["hour"].dt.to_period("M"))["svc"].nunique()
    full = set(have[have == 2].index)
    d = pd.DataFrame({
        "area_pu": _window(h, "area_pu_n", (21, 22, 23, 0)),
        "area_usd": _window(h, "area_pu_usd", (21, 22, 23, 0)),
        "area_do": _window(h, "area_do_n", (17, 18, 19)),
        "nl_pu": _window(h, "nl_pu_n", (19, 20, 21, 22, 23, 0, 1, 2)),
    })
    months = d.index.to_period("M")
    # TLC hourly is analysed for the playoff months only (Apr-Jun 2022-2026): hourly SoQL takes ~10 min
    # per HVFHV month and CloudFront 403s after a few reads, so the other season months were not all
    # fetched. reg_home in the TLC fits is therefore April regular-season home nights.
    return d[months.isin(full) & (months.month >= 4) & (months.month <= 6)]


def city_daily() -> pd.Series:
    fs = sorted((CACHE / "tlc").glob("*.parquet"))
    t = pd.concat([pd.read_parquet(f) for f in fs])
    t["date"] = pd.to_datetime(t["date"])
    n = t.groupby("date")["trips"].agg(["sum", "count"])
    return n.loc[n["count"] == 2, "sum"].rename("city_trips")


def mta() -> pd.DataFrame:
    st = pd.read_parquet(CACHE / "r4mh_stations.parquet")
    sy = pd.read_parquet(CACHE / "r4mh_system.parquet").assign(station_complex_id="system")
    new = pd.read_parquet(CACHE / "r5playoffmobility_mta2025.parquet")
    a = pd.concat([st, sy, new], ignore_index=True)
    a["hour"] = pd.to_datetime(a["transit_timestamp"])
    penn = a[a.station_complex_id.isin(("164", "318"))].groupby("hour")["r"].sum().reset_index()
    sys_ = a[a.station_complex_id == "system"].groupby("hour")["r"].sum().reset_index()
    return pd.DataFrame({"penn_post": _window(penn, "r", (21, 22, 23, 0)),
                         "sys_eve": _window(sys_, "r", (19, 20, 21, 22, 23, 0))}).iloc[:-1]


def rain() -> pd.Series:
    w = pd.read_csv(CACHE / "ghcn_USW00094728.csv", usecols=["DATE", "PRCP"], low_memory=False)
    w = w[w["DATE"] >= "2021-12-01"]
    return pd.Series((w["PRCP"].astype(float) / 254 >= 0.01).values, pd.to_datetime(w["DATE"]).values, name="rain")


def day_flags(g: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.DataFrame:
    g = g.copy()
    g["sh"] = g["start"].dt.hour + g["start"].dt.minute / 60
    g["evening"] = g["sh"].between(18, 21)
    f = pd.DataFrame(index=idx)
    home = g[g.home]
    f["matinee"] = idx.isin(g.loc[~g.evening, "date"])
    f["reg_home"] = idx.isin(home.loc[home.stype.isin(["reg", "playin"]) & home.evening, "date"])
    f["post_home"] = idx.isin(home.loc[(home.stype == "post") & home.evening, "date"])
    away = g[~g.home & (g.stype == "post") & g.evening]
    f["post_away"] = idx.isin(away["date"]) & ~idx.isin(home["date"])
    f["post_home_season"] = pd.Series(idx, index=idx).map(
        home[(home.stype == "post") & home.evening].drop_duplicates("date").set_index("date")["season"])
    return f


def frame() -> pd.DataFrame:
    parts = [mta(), city_daily().to_frame()]
    t = tlc()
    if len(t):
        parts.append(t)
    d = pd.concat(parts, axis=1)
    d = d[(d.index >= "2022-01-01") & (d.index <= "2026-06-30")]
    d = d.join(rain()).join(day_flags(G.load(), d.index))
    d["rain"] = d["rain"].fillna(False)
    d["dow"], d["ym"] = d.index.dayofweek, d.index.strftime("%Y%m")
    hol = set(USFederalHolidayCalendar().holidays("2022-01-01", "2026-12-31"))
    d["holiday"] = d.index.isin(hol) | [(x.month, x.day) in ((12, 24), (12, 31), (12, 26)) for x in d.index]
    return d[~d["matinee"]]


# ------------------------------------------------------------------ fits
def design(d: pd.DataFrame, events: list[str]) -> pd.DataFrame:
    X = pd.concat([d[events].astype(float), d[["rain", "holiday"]].astype(float),
                   pd.get_dummies(d["dow"], prefix="dow", drop_first=True, dtype=float),
                   pd.get_dummies(d["ym"], prefix="ym", drop_first=True, dtype=float)], axis=1)
    return sm.add_constant(X)


def fit(d: pd.DataFrame, y: str, events: list[str]):
    s = d.dropna(subset=[y])
    s = s[s[y] > 0]
    r = sm.OLS(np.log(s[y]), design(s, events)).fit(cov_type="HAC", cov_kwds={"maxlags": 7})
    return r, s


def pct(b: float) -> float:
    return 100 * (np.exp(b) - 1)


def run_q1(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for per, (a, b) in PERIODS.items():
        dp = d[(d.index >= a) & (d.index <= b)]
        for y in OUTCOMES:
            if dp[y].notna().sum() < 60:
                continue
            r, s = fit(dp, y, EVENTS)
            for e in EVENTS:
                rows.append({"period": per, "outcome": y, "event": e, "b": r.params[e], "se": r.bse[e],
                             "p": r.pvalues[e], "n_ev": int(s[e].sum()), "n": len(s),
                             "span": f"{s.index.min():%Y-%m}..{s.index.max():%Y-%m}"})
            c = np.zeros(len(r.params))
            c[list(r.params.index).index("post_home")] = 1
            c[list(r.params.index).index("reg_home")] = -1
            t = r.t_test(c)
            rows.append({"period": per, "outcome": y, "event": "post-reg", "b": float(t.effect[0]),
                         "se": float(t.sd[0][0]), "p": float(t.pvalue), "n_ev": int(s["post_home"].sum()),
                         "n": len(s), "span": f"{s.index.min():%Y-%m}..{s.index.max():%Y-%m}"})
    res = pd.DataFrame(rows)
    res["lo"], res["hi"] = res.b - Z * res.se, res.b + Z * res.se
    res["q"] = np.nan
    for per in PERIODS:
        m = res.period == per
        res.loc[m, "q"] = multipletests(res.loc[m, "p"], alpha=0.10, method="fdr_bh")[1]
    return res


def verdicts(res: pd.DataFrame) -> pd.DataFrame:
    tr = res[res.period == "train"].set_index(["outcome", "event"])
    ho = res[res.period == "holdout"].set_index(["outcome", "event"])
    out = tr.join(ho, lsuffix="_tr", rsuffix="_ho")
    ok_tr = (out.q_tr < 0.10) & ((out.lo_tr > 0) | (out.hi_tr < 0)) & (out.n_ev_tr >= 10)
    ok_ho = (out.q_ho < 0.10) & (np.sign(out.b_tr) == np.sign(out.b_ho)) & ((out.lo_ho > 0) | (out.hi_ho < 0))
    out["verdict"] = np.where(ok_tr & ok_ho, "FOUND", "NOT FOUND")
    return out.reset_index()


def by_season(d: pd.DataFrame, y: str) -> pd.DataFrame:
    """Descriptive: one playoff-home dummy per season (full sample), plus reg_home and post_away."""
    seasons = sorted(d["post_home_season"].dropna().unique())
    dd = d.copy()
    ev = ["reg_home", "post_away"]
    for s in seasons:
        dd[f"ph_{int(s)}"] = dd["post_home_season"] == s
        ev.append(f"ph_{int(s)}")
    r, s_ = fit(dd, y, ev)
    return pd.DataFrame({"b": r.params[ev], "se": r.bse[ev], "n_ev": s_[ev].sum()})


# ------------------------------------------------------------------ exposure + hedge
FLEET_TRIPS = 10 * 2 * 4  # 10 cars x ~2 trips/car-hour x the 4-hour post-game window
SUBWAY_FARE = 2.90


def exposure(d: pd.DataFrame) -> None:
    """$ per playoff home game (pooled 2022-26 fit), per-round stakes, backtest and simulation."""
    say("\nQ2  $ per playoff home game (pooled fit on all evenings 2022-01..2026-06)")
    po = d[d.index.month.isin([4, 5, 6])]
    base_days = po[~po.reg_home & ~po.post_home & ~po.post_away]
    us = {}
    for y, scale, label in (("area_usd", 1.0, "MSG-area TLC driver gross 21-01h (all drivers)"),
                            ("penn_post", SUBWAY_FARE, "34 St-Penn entries 21-01h x $2.90")):
        r, s_ = fit(d, y, EVENTS)
        b, se = r.params["post_home"], r.bse["post_home"]
        base = base_days[y].mean() * scale
        u = base * (np.exp(b) - 1)
        lo, hi = base * (np.exp(b - Z * se) - 1), base * (np.exp(b + Z * se) - 1)
        us[y] = u
        say(f"  {label}: base ${base:,.0f}/evening (Apr-Jun non-game), playoff home {pct(b):+.1f}% "
            f"-> ${u:,.0f} [{lo:,.0f}, {hi:,.0f}] per game (n={int(s_.post_home.sum())})")
    if "area_usd" in us and d.area_pu.notna().any():
        r, _ = fit(d, "area_pu", EVENTS)
        trips_game = base_days["area_pu"].mean() * np.exp(r.params["post_home"])
        share = FLEET_TRIPS / trips_game
        us["fleet10"] = us["area_usd"] * share
        us["driver"] = us["fleet10"] / 10
        say(f"  10-car fleet (constant share {share:.2%} of {trips_game:,.0f} game-night area pickups): "
            f"${us['fleet10']:,.0f}/game; single driver ${us['driver']:,.0f}/game")
        per_trip_base = base_days["area_usd"].mean() / base_days["area_pu"].mean()
        per_trip_game = (base_days["area_usd"].mean() + us["area_usd"]) / trips_game
        say(f"  driver gross per pickup: ${per_trip_base:.2f} normal -> ${per_trip_game:.2f} on a playoff home night "
            f"({100 * (per_trip_game / per_trip_base - 1):+.0f}%); same 8 trips, higher pay only: "
            f"${8 * (per_trip_game - per_trip_base):,.0f}/driver/game")
    series = H.nyk_nyr_series(G.load())
    series.to_csv(OUT / "series.csv", index=False)
    say("\n  $ at stake per round (value of advancing out of round r, later rounds at 50/50):")
    for k, u in us.items():
        say(f"    {k:9s} U=${u:,.0f}/game: " + ", ".join(f"R{r} ${H.advance_value(r, u):,.0f}" for r in (1, 2, 3)))
    hg = H.home_game_law([0.5] * 4, [True, True, False, False])
    say("  Home-game count if in R1 (50/50 series, home court R1-R2): " +
        ", ".join(f"{k}:{v:.0%}" for k, v in hg.items() if v >= 0.01))
    rows = []
    say("\nQ3  backtest: per-round 'opponent wins series' hedge (Kalshi KXNBASERIES/KXNHLSERIES price when"
        " listed, 2025-26; else 0.5)")
    for k, u in us.items():
        bt = H.backtest(series, u).assign(unit=k)
        rows.append(bt)
        say(f"  {k}: season revenue SD ${bt.revenue.std(ddof=0):,.0f} -> hedged ${bt.hedged.std(ddof=0):,.0f}; "
            f"min ${bt.revenue.min():,.0f} -> ${bt.hedged.min():,.0f}; mean ${bt.revenue.mean():,.0f} -> "
            f"${bt.hedged.mean():,.0f} (7 team-seasons)")
    bt = pd.concat(rows)
    bt.to_csv(OUT / "backtest.csv", index=False)
    say(bt[bt.unit == "fleet10"][["team", "season", "rounds", "home_games", "priced", "revenue", "hedge_cost",
                                  "hedge_payout", "hedged"]].round(0).to_string(index=False) if "fleet10" in us else "")
    sims = []
    scen = {"coin-flip team (0.5 every round, home court R1-R2)": ([0.5] * 4, [True, True, False, False]),
            "Knicks 2026 market prices (R1-F)": (list(series.query("team=='knicks' and season==2026").p_win),
                                                 list(series.query("team=='knicks' and season==2026").home_court)),
            "Knicks 2025 market prices (R1-CF, F at 0.5)": (
                list(series.query("team=='knicks' and season==2025").p_win) + [0.5],
                list(series.query("team=='knicks' and season==2025").home_court) + [False])}
    for k, u in us.items():
        for name, (ps, hcs) in scen.items():
            m = H.simulate(ps, hcs, u)
            sims.append({"unit": k, "scenario": name, **m})
    sims = pd.DataFrame(sims)
    sims.to_csv(OUT / "simulate.csv", index=False)
    say("\n  simulation (20,000 runs): SD unhedged -> hedged, 5th pct unhedged -> hedged, mean cost")
    for _, r in sims.iterrows():
        say(f"    {r.unit:9s} {r.scenario:48s} SD ${r.sd_unhedged:,.0f} -> ${r.sd_hedged:,.0f} "
            f"({100 * (r.sd_hedged / r.sd_unhedged - 1):+.0f}%), p5 ${r.p5_unhedged:,.0f} -> ${r.p5_hedged:,.0f}, "
            f"cost ${r.mean_unhedged - r.mean_hedged:,.0f}")


# ------------------------------------------------------------------ main
def main() -> None:
    d = frame()
    say(f"evenings kept {len(d)} (matinee-game days dropped); TLC area window evenings {d.area_pu.notna().sum()}"
        f" ({d.area_pu.dropna().index.min():%Y-%m}..{d.area_pu.dropna().index.max():%Y-%m})")
    for per, (a, b) in PERIODS.items():
        dp = d[(d.index >= a) & (d.index <= b)]
        say(f"{per}: reg_home {int(dp.reg_home.sum())}, post_home {int(dp.post_home.sum())}, "
            f"post_away {int(dp.post_away.sum())}")
    res = run_q1(d)
    res.to_csv(OUT / "results.csv", index=False)
    v = verdicts(res)
    say("\nQ1  (effect in %, 90% CI; q = BH within period)")
    for _, r in v.iterrows():
        say(f"{r.outcome:10s} {r.event:9s} train {pct(r.b_tr):+6.1f}% [{pct(r.lo_tr):+6.1f},{pct(r.hi_tr):+6.1f}] "
            f"n={r.n_ev_tr:3.0f} q={r.q_tr:.3f} | holdout {pct(r.b_ho):+6.1f}% [{pct(r.lo_ho):+6.1f},"
            f"{pct(r.hi_ho):+6.1f}] n={r.n_ev_ho:3.0f} q={r.q_ho:.3f}  {r.verdict}")
    say(f"tests: {len(res)} ({(res.period == 'train').sum()} train + {(res.period == 'holdout').sum()} holdout)")
    say("\nPer-season playoff-home effect (full sample, descriptive), % [90% CI] (n)")
    seas = {}
    for y in ("area_pu", "area_usd", "penn_post"):
        bs = by_season(d, y)
        seas[y] = bs
        say(f"  {y}: " + "; ".join(f"{k} {pct(r.b):+.0f}% [{pct(r.b - Z * r.se):+.0f},{pct(r.b + Z * r.se):+.0f}] ({r.n_ev:.0f})"
                                    for k, r in bs.iterrows()))
    pd.concat(seas, names=["outcome", "term"]).to_csv(OUT / "by_season.csv")
    exposure(d)
    (OUT / "output.txt").write_text("\n".join(LINES) + "\n")
    d.to_pickle(CACHE / "r5playoffmobility_frame.pkl")


if __name__ == "__main__":
    main()
