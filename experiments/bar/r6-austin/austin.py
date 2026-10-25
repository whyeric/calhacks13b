"""R6 austin: heat -> night -> Sixth/Rainey, UT football, festivals, on Austin B-cycle 2014-2017.

Data
  Austin B-cycle trips, ~/Downloads/archive (3).zip, extracted to r2-cache/r6austin_x/ (deleted after).
  NOAA GHCN-D USW00013904 Austin Bergstrom (KXHIGHAUS settlement station), USW00094728 Central Park
  (wrong-city placebo). UT schedules from the ESPN site API.
Model
  log(1+trips) on event + DOW + federal holiday + year-month FE + rain + SXSW + ACL + UT home game,
  HAC(7), z=1.645. Train 2014-2015, holdout 2016-01..2017-07, fit independently.
  18 pre-registered tests (see RESULTS.md), BH at 10% on train p and holdout p separately.

Run from backend/: .venv/bin/python ../experiments/bar/r6-austin/austin.py
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import httpx
import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.holiday import USFederalHolidayCalendar

HERE = Path(__file__).parent
CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
X = CACHE / "r6austin_x"
Z, BH_Q, EDGE, FEE = 1.645, 0.10, 0.02, 0.07
TRAIN = ("2014-01-01", "2015-12-31")
HOLD = ("2016-01-01", "2017-07-31")

SR = [2565, 3390, 3619, 2571, 2562, 2536, 3660, 2707, 2563, 2576]
ZILKER = [2574, 1006, 2572, 2711, 3686, 3377, 2712]
DKR = (30.2837, -97.7323)
SXSW = [("2014-03-07", "2014-03-16"), ("2015-03-13", "2015-03-22"), ("2016-03-11", "2016-03-20"), ("2017-03-10", "2017-03-19")]
ACL = [("2014-10-03", "2014-10-05"), ("2014-10-10", "2014-10-12"), ("2015-10-02", "2015-10-04"), ("2015-10-09", "2015-10-11"),
       ("2016-09-30", "2016-10-02"), ("2016-10-07", "2016-10-09")]

out_lines: list[str] = []


def say(s: str = "") -> None:
    print(s)
    out_lines.append(s)


def dates_in(ranges) -> set:
    return {d for a, b in ranges for d in pd.date_range(a, b)}


# ---------------------------------------------------------------- data
def campus_ids() -> list[int]:
    st = pd.read_csv(X / "austin_bikeshare_stations.csv")
    lat, lon = np.radians(st.latitude), np.radians(st.longitude)
    la0, lo0 = np.radians(DKR[0]), np.radians(DKR[1])
    d = 6371 * 2 * np.arcsin(np.sqrt(np.sin((lat - la0) / 2) ** 2 + np.cos(lat) * np.cos(la0) * np.sin((lon - lo0) / 2) ** 2))
    return st.station_id[d <= 1.3].astype(int).tolist()


def daily(campus: list[int]) -> pd.DataFrame:
    f = X / "austin_bikeshare_trips.csv"
    lst = lambda ids: ",".join(map(str, ids))
    q = f"""
    with t as (
      select start_time::timestamp - interval 3 hour as ts, start_station_id::int s, end_station_id::int e
      from read_csv_auto('{f}') where start_time is not null)
    select ts::date d,
      count(*) all_n,
      count(*) filter (where hour(ts) between 3 and 15) all_day,          -- 06..18h local
      count(*) filter (where hour(ts) >= 16) all_night,                   -- 19..02h local
      count(*) filter (where hour(ts) >= 16 and e in ({lst(SR)})) sr_night,
      count(*) filter (where s in ({lst(campus)}) or e in ({lst(campus)})) campus_n,
      count(*) filter (where e in ({lst(ZILKER)})) zilker_in
    from t group by 1 order by 1"""
    df = duckdb.sql(q).df()
    df["d"] = pd.to_datetime(df.d)
    return df.set_index("d")


def ghcn(stn: str) -> pd.DataFrame:
    p = CACHE / f"r6austin_ghcn_{stn}.csv"
    if not p.exists():
        p.write_bytes(httpx.get(f"https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/{stn}.csv", timeout=120).content)
    g = pd.read_csv(p, usecols=["DATE", "TMAX", "PRCP"], parse_dates=["DATE"], low_memory=False).set_index("DATE")
    g["tmax_f"] = (g.TMAX / 10 * 9 / 5 + 32).round()
    g["rain"] = (g.PRCP / 10 / 25.4 >= 0.01).astype(float)
    return g[["tmax_f", "rain"]]


def ut_games() -> pd.DataFrame:
    p = CACHE / "r6austin_ut_games.json"
    if not p.exists():
        rows = []
        for s in (2014, 2015, 2016):
            r = httpx.get(f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/251/schedule?season={s}", timeout=30).json()
            for e in r["events"]:
                c = e["competitions"][0]
                me = [t for t in c["competitors"] if t["team"]["abbreviation"] == "TEX"][0]
                op = [t for t in c["competitors"] if t["team"]["abbreviation"] != "TEX"][0]
                rows.append(dict(season=s, utc=e["date"], home=me["homeAway"] == "home" and not c.get("neutralSite"),
                                 venue=c.get("venue", {}).get("fullName"), win=float(me["score"]["value"]) > float(op["score"]["value"])))
        p.write_text(json.dumps(rows))
    g = pd.DataFrame(json.loads(p.read_text()))
    g["d"] = pd.to_datetime(g.utc).dt.tz_convert("America/Chicago").dt.tz_localize(None).dt.normalize()
    return g


def panel() -> pd.DataFrame:
    camp = campus_ids()
    df = daily(camp)
    df = df.loc["2014-01-01":"2017-07-31"]
    aus, nyc = ghcn("USW00013904"), ghcn("USW00094728")
    df = df.join(aus).join(nyc.tmax_f.rename("nyc_tmax"))
    g = ut_games()
    hd = set(g.d[g.home]); ad = set(g.d[~g.home]); wins = set(g.d[g.home & g.win])
    df["home"] = df.index.isin(hd).astype(float)
    df["away"] = df.index.isin(ad).astype(float)
    df["home_win"] = df.index.isin(wins).astype(float)
    df["sxsw"] = df.index.isin(dates_in(SXSW)).astype(float)
    df["acl"] = df.index.isin(dates_in(ACL)).astype(float)
    df["hol"] = df.index.isin(USFederalHolidayCalendar().holidays("2013-01-01", "2018-01-01")).astype(float)
    for c in ["all_n", "all_day", "all_night", "sr_night", "campus_n", "zilker_in"]:
        df["y_" + c] = np.log1p(df[c])
    df["y_night_share"] = df.y_all_night - df.y_all_n
    df["y_sr_share"] = np.log1p(df.sr_night) - df.y_all_night
    df["ym"] = df.index.to_period("M").astype(str)
    df["dow"] = df.index.dayofweek
    say(f"panel: {len(df)} service days {df.index.min().date()}..{df.index.max().date()}, campus stations {len(camp)}: {camp}")
    say(f"missing days in range: {len(pd.date_range(df.index.min(), df.index.max())) - len(df)}")
    return df


# ---------------------------------------------------------------- fitting
def fit(df: pd.DataFrame, y: str, ev: str, controls: list[str]) -> dict:
    d = df.dropna(subset=[y, ev, "tmax_f", "rain"])
    Xm = pd.concat([d[[ev] + controls], pd.get_dummies(d.dow, prefix="dow", drop_first=True, dtype=float),
                    pd.get_dummies(d.ym, prefix="ym", drop_first=True, dtype=float)], axis=1)
    Xm = Xm.loc[:, (Xm.std() > 0) | (Xm.columns == ev)]
    Xm = sm.add_constant(Xm, has_constant="add")
    m = sm.OLS(d[y], Xm).fit(cov_type="HAC", cov_kwds={"maxlags": 7})
    b, se = m.params[ev], m.bse[ev]
    return dict(b=b, lo=b - Z * se, hi=b + Z * se, p=m.pvalues[ev], n_ev=int((d[ev] != 0).sum()), n=len(d), model=m)


def split(df, a, b):
    return df.loc[a:b]


def bh(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, float); n = len(p); o = np.argsort(p)
    q = p[o] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(n); out[o] = np.minimum(q, 1)
    return out


def pct(b):  # log points -> %
    return 100 * (np.exp(b) - 1)


BASE = ["hol", "rain", "sxsw", "acl", "home"]


def main() -> None:
    df = panel()
    tr, ho = split(df, *TRAIN), split(df, *HOLD)
    for k in (98, 101):
        df[f"hot{k}"] = (df.tmax_f >= k).astype(float)
        df[f"lead{k}"] = ((df.tmax_f.shift(-1) >= k) & (df.tmax_f < k)).astype(float)
    tr, ho = split(df, *TRAIN), split(df, *HOLD)
    say(f"hot days (>=101F) train {int(tr.hot101.sum())}, holdout {int(ho.hot101.sum())}; (>=98F) train {int(tr.hot98.sum())}, holdout {int(ho.hot98.sum())}")

    tests = []  # (chain, name, y, ev, controls, data_train, data_hold, kind)
    heat_y = [("H1 all trips", "y_all_n"), ("H2 day trips 06-18h", "y_all_day"), ("H3 night trips 19-02h", "y_all_night"),
              ("H4 night share", "y_night_share"), ("H5 SR night arrivals", "y_sr_night"), ("H6 SR share of night", "y_sr_share")]
    for k in (101, 98):
        for nm, y in heat_y:
            tests.append(("heat", f"{nm} | tmax>={k}", y, f"hot{k}", BASE))
    tests += [
        ("football", "F1 CAMPUS trips | home game", "y_campus_n", "home", ["hol", "rain", "sxsw", "acl", "away"]),
        ("football", "F2 SR night arrivals | home game", "y_sr_night", "home", ["hol", "rain", "sxsw", "acl", "away"]),
        ("football", "F3 SR night arrivals | away game", "y_sr_night", "away", ["hol", "rain", "sxsw", "acl", "home"]),
        ("football", "F4 SR night arrivals | home WIN vs loss", "y_sr_night", "home_win", ["hol", "rain", "sxsw", "acl", "home", "away"]),
    ]
    rows = []
    for chain, nm, y, ev, ctl in tests:
        a, b = fit(tr, y, ev, ctl), fit(ho, y, ev, ctl)
        rows.append(dict(chain=chain, test=nm, b_tr=a["b"], lo_tr=a["lo"], hi_tr=a["hi"], p_tr=a["p"], n_tr=a["n_ev"],
                         b_ho=b["b"], lo_ho=b["lo"], hi_ho=b["hi"], p_ho=b["p"], n_ho=b["n_ev"]))

    # Chain 3: heat x ACL, ACL days only, ZILKER arrivals on tmax with year FE
    acl = df[df.acl == 1].copy()
    acl["t10"] = acl.tmax_f / 10
    acl["hot90"] = (acl.tmax_f >= 90).astype(float)
    acl["dow"] = acl.index.dayofweek
    for nm, ev in [("A1 ZILKER arrivals on ACL days | per +10F", "t10"), ("A2 ZILKER arrivals on ACL days | tmax>=90", "hot90")]:
        res = []
        for a_, b_ in (TRAIN, HOLD):
            s = acl.loc[a_:b_]
            Xm = pd.concat([s[[ev, "rain"]], pd.get_dummies(s.index.year, prefix="y", drop_first=True, dtype=float).set_index(s.index),
                            pd.get_dummies(s.dow, prefix="dow", drop_first=True, dtype=float)], axis=1)
            Xm = sm.add_constant(Xm.loc[:, Xm.std() > 0], has_constant="add")
            if ev not in Xm or len(s) <= Xm.shape[1]:
                res.append(dict(b=np.nan, lo=np.nan, hi=np.nan, p=np.nan, n_ev=int((s[ev] != 0).sum()) if ev == "hot90" else len(s)))
                continue
            m = sm.OLS(s.y_zilker_in, Xm).fit(cov_type="HC3")
            bb, se = m.params[ev], m.bse[ev]
            res.append(dict(b=bb, lo=bb - Z * se, hi=bb + Z * se, p=m.pvalues[ev], n_ev=int((s[ev] != 0).sum()) if ev == "hot90" else len(s)))
        a, b = res
        rows.append(dict(chain="acl", test=nm, b_tr=a["b"], lo_tr=a["lo"], hi_tr=a["hi"], p_tr=a["p"], n_tr=a["n_ev"],
                         b_ho=b["b"], lo_ho=b["lo"], hi_ho=b["hi"], p_ho=b["p"], n_ho=b["n_ev"]))
    say(f"ACL days in panel: {len(acl)}; tmax on ACL days: {acl.tmax_f.describe()[['min','mean','max']].round(0).to_dict()}; >=90F: {int(acl.hot90.sum())}")
    say(f"ACL-day ZILKER arrivals vs other days in same months: {acl.zilker_in.mean():.0f} vs "
        f"{df[(df.acl == 0) & df.ym.isin(acl.ym)].zilker_in.mean():.0f} trips/day")

    R = pd.DataFrame(rows)
    R["q_tr"] = bh(R.p_tr.fillna(1).values)
    R["q_ho"] = bh(R.p_ho.fillna(1).values)
    R["FOUND"] = ((R.n_tr >= 10) & (R.lo_tr * R.hi_tr > 0) & (R.lo_ho * R.hi_ho > 0) & (np.sign(R.b_tr) == np.sign(R.b_ho))
                  & (R.q_tr <= BH_Q) & (R.q_ho <= BH_Q))
    R.to_csv(HERE / "results.csv", index=False)
    say(f"\n{len(R)} tests; BH at {BH_Q:.0%} on train p and holdout p separately. Effects in % (log outcomes), A1 per +10F.")
    say("| chain | test | train β % [90% CI] (n ev) | q tr | holdout β % [90% CI] (n ev) | q ho | FOUND |")
    say("|---|---|---|---|---|---|---|")
    for r in R.itertuples():
        f = lambda b, lo, hi: "n/a" if np.isnan(b) else f"{pct(b):+.1f} [{pct(lo):+.1f}, {pct(hi):+.1f}]"
        say(f"| {r.chain} | {r.test} | {f(r.b_tr, r.lo_tr, r.hi_tr)} ({r.n_tr}) | {r.q_tr:.3f} | {f(r.b_ho, r.lo_ho, r.hi_ho)} ({r.n_ho}) | {r.q_ho:.3f} | {'FOUND' if r.FOUND else 'no'} |")

    # ------------------------------------------------ placebos
    say("\n## Placebos")
    say("| placebo | outcome | train β % [CI] (n) | holdout β % [CI] (n) |")
    say("|---|---|---|---|")

    def prow(lab, y, ev, ctl, d1=tr, d2=ho):
        a, b = fit(d1, y, ev, ctl), fit(d2, y, ev, ctl)
        say(f"| {lab} | {y} | {pct(a['b']):+.1f} [{pct(a['lo']):+.1f}, {pct(a['hi']):+.1f}] ({a['n_ev']}) | "
            f"{pct(b['b']):+.1f} [{pct(b['lo']):+.1f}, {pct(b['hi']):+.1f}] ({b['n_ev']}) |")

    for y in ["y_all_n", "y_night_share", "y_sr_night", "y_sr_share"]:
        prow("lead: tomorrow >=101F, today not", y, "lead101", BASE + ["hot101"])
    df["nyc90"] = (df.nyc_tmax >= 90).astype(float)
    tr, ho = split(df, *TRAIN), split(df, *HOLD)
    for y in ["y_all_n", "y_night_share", "y_sr_night"]:
        prow("wrong city: Central Park >=90F", y, "nyc90", BASE + ["hot98"], tr, ho)

    # permutation of hot101 within year-month (pooled train+holdout, H4 and H5)
    rng = np.random.default_rng(6)
    full = df.loc[TRAIN[0]:HOLD[1]].copy()
    for y in ["y_all_n", "y_night_share", "y_sr_night"]:
        obs = fit(full, y, "hot101", BASE)["b"]
        perm = []
        for _ in range(300):
            full["perm"] = full.groupby("ym").hot101.transform(lambda s: rng.permutation(s.values))
            perm.append(fit(full, y, "perm", BASE)["b"])
        perm = np.array(perm)
        say(f"| permutation hot101 within ym (pooled, 300) | {y} | observed {pct(obs):+.1f}% | perm 5–95%: [{pct(np.quantile(perm, .05)):+.1f}, {pct(np.quantile(perm, .95)):+.1f}], p_perm={np.mean(np.abs(perm) >= abs(obs)):.3f} |")

    # football placebo: matched non-game fall Saturdays by tmax, and Sunday after
    g = ut_games()
    hd = g[g.home].d
    cand = df[(df.dow == 5) & (df.home == 0) & (df.away == 0) & (df.acl == 0) & df.index.month.isin([8, 9, 10, 11, 12])]
    fake = []
    for d in hd:
        c = cand[(cand.index.year == d.year) & ~cand.index.isin(fake)]
        if d in df.index and len(c):
            fake.append((c.tmax_f - df.loc[d, "tmax_f"]).abs().idxmin())
    df["fake_home"] = df.index.isin(fake).astype(float)
    df["sun_after"] = df.index.isin(hd + pd.Timedelta(days=1)).astype(float)
    nh = df[df.home == 0]
    trn, hon = split(nh, *TRAIN), split(nh, *HOLD)
    for y in ["y_campus_n", "y_sr_night"]:
        prow("matched-tmax non-game Saturday", y, "fake_home", ["hol", "rain", "sxsw", "acl", "away"], trn, hon)
    tr, ho = split(df, *TRAIN), split(df, *HOLD)
    for y in ["y_campus_n", "y_sr_night"]:
        prow("Sunday after home game", y, "sun_after", ["hol", "rain", "sxsw", "acl", "away", "home"], tr, ho)

    # Descriptive: mean SR night share and hour profile on hot vs not, Jul-Aug
    ja = df[df.index.month.isin([7, 8])]
    say("\n## Descriptive, Jul–Aug only")
    say(ja.groupby("hot101")[["all_n", "all_day", "all_night", "sr_night", "tmax_f"]].mean().round(1).to_string())
    say(f"hot101 days by year: {df.groupby(df.index.year).hot101.sum().astype(int).to_dict()}")
    say(f"UT home games in panel: {int(df.home.sum())} (wins {int(df.home_win.sum())}), away games {int(df.away.sum())}")
    (HERE / "output.txt").write_text("\n".join(out_lines) + "\n")


if __name__ == "__main__":
    main()
