"""R4 mtahourly: MSG games and rain timing in MTA Subway hourly ridership (wujg-7c2s).

Q1  34 St-Penn Station (complexes 164 A,C,E + 318 1,2,3; the two MSG stations) hourly entries on
    evening MSG home-game nights. Game vs no game (all days) and win vs loss (game nights only),
    Knicks, Rangers and pooled, in three pre-registered clock windows:
        pre   17:00-18:59   placebo: fans arrive by exiting, which the dataset does not count
        post  21:00-23:59   the exit wave after a ~19:00-19:30 start
        late  00:00-01:59   next calendar day, the "winning fans linger" window
    plus late_share = entries 23:00-00:59 / entries 21:00-00:59 (timing shift, not volume).
    Outcome log(Penn entries in window); controls log(system entries in the same window), DOW,
    year-month FE, holiday, NOAA daily rain, afternoon-game dummy. HAC 7 for all days, HC3 for the
    game-only win fits (with team, OT, month FE and year controls instead of year-month FE).
Q2  System-wide hourly entries by bucket (AM 06-09, MID 10-15, PM 16-19, EVE 20-23) against NOAA
    LCD Central Park hourly precipitation (FM-15, LST shifted to local clock). Joint rain flags for
    all four buckets, the daily KXRAIN flag (GHCN PRCP >= 0.01 in), and AM-only vs PM-only rain days
    on the daily total.

Train 2022-01-01..2023-12-31, holdout 2024-01-01..2024-12-31, refit independently; 2020-21 excluded.
BH at 10% over every test (both periods separately). Run fetch.py first, then from backend/:
    .venv/bin/python ../experiments/bar/r4-mtahourly/mtahourly.py
Writes results.csv, hedge.csv and output.txt (aggregates only; MTA/NOAA/ESPN are public).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.holiday import USFederalHolidayCalendar
from statsmodels.stats.multitest import multipletests

OUT = Path(__file__).resolve().parent
CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
NY = ZoneInfo("America/New_York")
Z = 1.645
PERIODS = {"train": ("2022-01-01", "2023-12-31"), "holdout": ("2024-01-01", "2024-12-31")}
PENN = ("164", "318")
TEAMS = {"knicks": ("basketball_nba", "18"), "rangers": ("hockey_nhl", "13")}
GAME_LEN_H = {"knicks": 2.33, "rangers": 2.58}  # typical start-to-final, for the reported end hour only
FARE = 2.90
LINES: list[str] = []


def say(s: str = "") -> None:
    print(s)
    LINES.append(s)


# ------------------------------------------------------------------ inputs
def hourly() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(penn, system): date x hour 0..23 entry matrices, local clock."""
    st = pd.read_parquet(CACHE / "r4mh_stations.parquet")
    sy = pd.read_parquet(CACHE / "r4mh_system.parquet")
    out = []
    for df in (st[st["station_complex_id"].isin(PENN)].groupby("transit_timestamp")["r"].sum().reset_index(), sy):
        ts = pd.to_datetime(df["transit_timestamp"])
        m = pd.DataFrame({"date": ts.dt.date, "h": ts.dt.hour, "r": df["r"].values})
        out.append(m.pivot_table(index="date", columns="h", values="r", aggfunc="sum"))
    return out[0], out[1]


def games() -> pd.DataFrame:
    """MSG home games 2022-2024 from the cached ESPN scoreboards: date, team, local start, win, OT."""
    rows = []
    for team, (league, tid) in TEAMS.items():
        for f in sorted((CACHE / "espn" / league).glob("202[234]*.json")):
            for ev in json.loads(f.read_text()).get("events", []):
                comp = (ev.get("competitions") or [{}])[0]
                sides = {c["team"]["id"]: c for c in comp.get("competitors", [])}
                if tid not in sides or "Madison Square" not in comp.get("venue", {}).get("fullName", ""):
                    continue
                stt = ev["status"]["type"]
                if not stt.get("completed") or ev.get("season", {}).get("type") in (1, 4):
                    continue
                start = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(NY)
                reg = 4 if team == "knicks" else 3
                rows.append({"date": start.date(), "team": team, "start_h": start.hour + start.minute / 60,
                             "win": bool(sides[tid].get("winner")), "ot": ev["status"].get("period", reg) > reg,
                             "playoff": ev["season"]["type"] == 3})
    g = pd.DataFrame(rows).drop_duplicates(["date", "team"])
    g = g[(g["date"] >= pd.Timestamp("2022-01-01").date()) & (g["date"] <= pd.Timestamp("2024-12-31").date())]
    # 7 doubleheaders (Knicks matinee + Rangers evening): keep the evening game, the one the windows measure
    g = g.sort_values("start_h").drop_duplicates("date", keep="last")
    return g.set_index("date")


def weather() -> tuple[pd.Series, pd.DataFrame]:
    """(GHCN daily PRCP inches, LCD hourly precip date x local hour)."""
    w = pd.read_csv(CACHE / "r4mh_ghcn.csv", usecols=["DATE", "PRCP"], low_memory=False)
    w["date"] = pd.to_datetime(w["DATE"]).dt.date
    prcp = (w.set_index("date")["PRCP"] / 254).round(2)
    l = pd.read_csv(CACHE / "r4mh_lcd.csv", dtype=str)
    l = l[l["REPORT_TYPE"].str.strip() == "FM-15"].copy()
    v = l["HourlyPrecipitation"].fillna("").str.rstrip("s").replace({"T": "0", "": np.nan}).astype(float)
    lst = pd.to_datetime(l["DATE"])
    # LCD timestamps are local standard time; convert to the local wall clock used by the MTA data.
    utc = lst + pd.Timedelta(hours=5)
    local = utc.dt.tz_localize("UTC").dt.tz_convert(NY).dt.tz_localize(None)
    h = pd.DataFrame({"date": local.dt.date, "h": local.dt.hour, "p": v.values})
    return prcp, h.pivot_table(index="date", columns="h", values="p", aggfunc="sum")


def frame() -> pd.DataFrame:
    penn, sys_ = hourly()
    g = games()
    prcp, lcd = weather()
    d = pd.DataFrame(index=pd.Index(penn.index, name="date"))
    nxt = {x: x + timedelta(days=1) for x in d.index}
    def win(m, hrs, next_day=False):
        if not next_day:
            return m.reindex(d.index)[list(hrs)].sum(axis=1, min_count=len(hrs))
        return pd.Series([m.loc[nxt[x], list(hrs)].sum() if nxt[x] in m.index else np.nan for x in d.index], d.index)
    for name, mat in (("penn", penn), ("sys", sys_)):
        d[f"{name}_pre"] = win(mat, (17, 18))
        d[f"{name}_post"] = win(mat, (21, 22, 23))
        d[f"{name}_late"] = win(mat, (0, 1), next_day=True)
        d[f"{name}_n0"] = win(mat, (0,), next_day=True)
    for b, hrs in {"AM": range(6, 10), "MID": range(10, 16), "PM": range(16, 20), "EVE": range(20, 24)}.items():
        d[f"sys_{b}"] = win(sys_, tuple(hrs))
        d[f"rain_{b}"] = lcd.reindex(d.index)[list(hrs)].sum(axis=1).fillna(0) >= 0.01
    d["sys_day"] = sys_.reindex(d.index).sum(axis=1)
    d["rain_morn"] = lcd.reindex(d.index)[list(range(0, 13))].sum(axis=1).fillna(0) >= 0.01
    d["rain_aft"] = lcd.reindex(d.index)[list(range(13, 24))].sum(axis=1).fillna(0) >= 0.01
    d["late_share"] = (penn.reindex(d.index)[23] + d["penn_n0"]) / (d["penn_post"] + d["penn_n0"])
    d["kxrain"] = d.index.map(prcp) >= 0.01
    d["lcd_cov"] = lcd.reindex(d.index).notna().sum(axis=1)
    ts = pd.to_datetime(pd.Series(d.index, index=d.index))
    d["dow"], d["ym"], d["month"], d["year"] = ts.dt.dayofweek, ts.dt.strftime("%Y%m"), ts.dt.month, ts.dt.year
    hol = set(USFederalHolidayCalendar().holidays("2022-01-01", "2025-01-01").date)
    d["holiday"] = [x in hol or (x.month, x.day) in ((12, 24), (12, 31), (12, 26)) for x in d.index]
    d = d.join(g)
    d["game"] = d["team"].notna()
    d["evening"] = d["game"] & d["start_h"].between(18, 20.6)
    d["matinee"] = d["game"] & ~d["evening"]
    for t in TEAMS:
        d[f"{t}_game"] = d["evening"] & (d["team"] == t)
    d["win"] = d["win"].fillna(False).astype(bool)
    d["ot"] = d["ot"].fillna(False).astype(bool)
    return d


# ------------------------------------------------------------------ models
def dummies(s: pd.Series, p: str) -> pd.DataFrame:
    return pd.get_dummies(s.astype(str), prefix=p, drop_first=True).astype(float)


def fit(y: pd.Series, X: pd.DataFrame, term: str, cov: str) -> dict:
    X = X.loc[:, (X.nunique() > 1) | (X.columns == "const")]
    ok = y.notna() & X.notna().all(axis=1)
    y, X = y[ok], X[ok]
    r = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 7}) if cov == "hac" else sm.OLS(y, X).fit(cov_type="HC3")
    b, se = r.params[term], r.bse[term]
    return {"beta": b, "se": se, "p": r.pvalues[term], "lo": b - Z * se, "hi": b + Z * se,
            "n": int(len(y)), "n_ev": int(X[term].sum()), "resid_sd": float(np.sqrt(r.scale))}


def base(f: pd.DataFrame, ym: bool = True) -> pd.DataFrame:
    X = pd.DataFrame({"const": 1.0}, index=f.index)
    X = X.join(dummies(f["dow"], "dow"))
    X = X.join(dummies(f["ym"], "ym") if ym else dummies(f["month"], "m").join(dummies(f["year"], "y")))
    X["holiday"] = f["holiday"].astype(float)
    return X


def q1_tests(f: pd.DataFrame) -> list[dict]:
    res = []
    for w in ("pre", "post", "late", "share"):
        y = np.log(f[f"penn_{w}"]) if w != "share" else f["late_share"]
        X0 = base(f)
        X0["rain"] = f["kxrain"].astype(float)
        if w != "share":
            X0["log_sys"] = np.log(f[f"sys_{w}"])
        X0["matinee"] = f["matinee"].astype(float)
        if w in ("pre", "post", "late"):
            for ev, col in (("MSG game", "evening"), ("Knicks game", "knicks_game"), ("Rangers game", "rangers_game")):
                X = X0.copy()
                X["ev"] = f[col].astype(float)
                if col != "evening":  # the other team's games are not in the control group
                    X["other"] = (f["evening"] & ~f[col]).astype(float)
                res.append({"q": "Q1", "event": ev, "outcome": f"penn_{w}", **fit(y, X, "ev", "hac")})
        if w in ("post", "late", "share"):
            for ev, teams in (("MSG win", ("knicks", "rangers")), ("Knicks win", ("knicks",)), ("Rangers win", ("rangers",))):
                s = f["evening"] & f["team"].isin(teams)
                g = f[s]
                X = base(g, ym=False)
                X["rain"] = g["kxrain"].astype(float)
                if w != "share":
                    X["log_sys"] = np.log(g[f"sys_{w}"])
                X["ot"] = g["ot"].astype(float)
                X["playoff"] = g["playoff"].astype(bool).astype(float)
                X["start_h"] = g["start_h"]
                if len(teams) == 2:
                    X["rangers"] = (g["team"] == "rangers").astype(float)
                X["ev"] = g["win"].astype(float)
                yy = y[s]
                res.append({"q": "Q1", "event": ev, "outcome": f"penn_{w}" if w != "share" else "late_share",
                            **fit(yy, X, "ev", "hc3")})
    return res


def q2_tests(f: pd.DataFrame) -> list[dict]:
    res = []
    f = f[f["lcd_cov"] >= 20]
    for b in ("AM", "MID", "PM", "EVE"):
        y = np.log(f[f"sys_{b}"])
        X = base(f)
        for bb in ("AM", "MID", "PM", "EVE"):
            X[f"r_{bb}"] = f[f"rain_{bb}"].astype(float)
        terms = [b] + (["AM"] if b in ("PM", "EVE") else [])
        for t in terms:
            label = f"rain in {t} bucket" + (" (own)" if t == b else " (carry-over)")
            res.append({"q": "Q2", "event": label, "outcome": f"sys_{b}", **fit(y, X, f"r_{t}", "hac")})
        Xk = base(f)
        Xk["kx"] = f["kxrain"].astype(float)
        res.append({"q": "Q2", "event": "KXRAIN daily flag", "outcome": f"sys_{b}", **fit(y, Xk, "kx", "hac")})
    y = np.log(f["sys_day"])
    X = base(f)
    X["morn_only"] = (f["rain_morn"] & ~f["rain_aft"]).astype(float)
    X["aft_only"] = (f["rain_aft"] & ~f["rain_morn"]).astype(float)
    X["both"] = (f["rain_aft"] & f["rain_morn"]).astype(float)
    for t, lab in (("morn_only", "rain 00-12 only"), ("aft_only", "rain 13-24 only")):
        res.append({"q": "Q2", "event": lab, "outcome": "sys_day", **fit(y, X, t, "hac")})
    return res


def sub(d: pd.DataFrame, period: str) -> pd.DataFrame:
    a, b = (pd.Timestamp(x).date() for x in PERIODS[period])
    return d[(d.index >= a) & (d.index <= b)]


SETTLEABLE = {"MSG win": "KXNBAGAME/KXNHLGAME", "Knicks win": "KXNBAGAME", "Rangers win": "KXNHLGAME",
              "KXRAIN daily flag": "KXRAIN"}


def hedge(d: pd.DataFrame, row: pd.Series) -> dict | None:
    """Out-of-sample hedge on 2024 for a FOUND settleable test, sized from train. Income = $2.90 x the
    test's outcome window entries (Penn or system)."""
    if row["event"] != "KXRAIN daily flag":
        return None  # only KXRAIN rows can be FOUND-and-settleable here; wins handled if they ever pass
    tr, ho = sub(d, "train"), sub(d, "holdout")
    tr, ho = tr[tr["lcd_cov"] >= 20], ho[ho["lcd_cov"] >= 20]
    col = row["outcome"]
    freq = tr["kxrain"].mean()
    beta_usd = (np.exp(row["beta_train"]) - 1) * FARE * tr[col].mean()
    price = min(freq + 0.02, 0.99)
    fee = 0.07 * price * (1 - price)
    n = abs(beta_usd)
    X = base(ho)
    inc = FARE * ho[col]
    resid = inc - sm.OLS(inc, X.loc[:, X.nunique() > 1].assign(const=1.0)).fit().fittedvalues
    pay = n * (ho["kxrain"].astype(float) - price - fee)
    hedged = resid + pay
    return {"event": row["event"], "outcome": col, "beta_usd_day": round(beta_usd), "price": round(price, 3),
            "sd_unhedged": round(resid.std()), "sd_hedged": round(hedged.std()),
            "sd_change_pct": round(100 * (hedged.std() / resid.std() - 1), 2),
            "p5_unhedged": round(np.percentile(resid, 5)), "p5_hedged": round(np.percentile(hedged, 5)),
            "mean_cost_day": round(pay.mean())}


def main() -> None:
    d = frame()
    say(f"days {len(d)}, evening MSG games {int(d['evening'].sum())} "
        f"(Knicks {int(d['knicks_game'].sum())}, Rangers {int(d['rangers_game'].sum())}), matinee {int(d['matinee'].sum())}")
    for p in PERIODS:
        s = sub(d, p)
        gs = s[s["evening"]]
        say(f"  {p}: evening games {len(gs)}, wins {int(gs['win'].sum())}, OT {int(gs['ot'].sum())}, "
            f"median start {gs['start_h'].median():.2f}; mean Penn post-window entries game {s.loc[s['evening'], 'penn_post'].mean():.0f}"
            f" vs no game {s.loc[~s['game'], 'penn_post'].mean():.0f}")
    # basis: hourly-bucket rain flags vs the KXRAIN settlement flag
    ok = d[d["lcd_cov"] >= 20]
    say(f"LCD coverage: {len(ok)}/{len(d)} days with >= 20 hourly FM-15 reports")
    lcd_any = ok[[f"rain_{b}" for b in ("AM", "MID", "PM", "EVE")]].any(axis=1) | ok["rain_morn"] | ok["rain_aft"]
    say(f"basis: LCD any-hour rain vs GHCN KXRAIN flag agreement {np.mean(lcd_any == ok['kxrain']):.3f}, "
        f"phi {np.corrcoef(lcd_any, ok['kxrain'])[0, 1]:.3f}")
    for b in ("AM", "MID", "PM", "EVE"):
        say(f"  rain_{b}: freq {ok[f'rain_{b}'].mean():.3f}, phi with KXRAIN {np.corrcoef(ok[f'rain_{b}'], ok['kxrain'])[0, 1]:.3f}, "
            f"P(KXRAIN | rain_{b}) {ok.loc[ok[f'rain_{b}'], 'kxrain'].mean():.3f}")

    rows = {}
    for p in PERIODS:
        s = sub(d, p)
        for r in q1_tests(s) + q2_tests(s):
            rows.setdefault((r["q"], r["event"], r["outcome"]), {})[p] = r
    tab = []
    for (q, ev, oc), v in rows.items():
        t, h = v["train"], v["holdout"]
        tab.append({"q": q, "event": ev, "outcome": oc,
                    **{f"{k}_train": t[k] for k in ("beta", "lo", "hi", "p", "n", "n_ev")},
                    **{f"{k}_holdout": h[k] for k in ("beta", "lo", "hi", "p", "n", "n_ev")}})
    tab = pd.DataFrame(tab)
    tab["q_train"] = multipletests(tab["p_train"], alpha=0.10, method="fdr_bh")[1]
    tab["q_holdout"] = multipletests(tab["p_holdout"], alpha=0.10, method="fdr_bh")[1]
    excl = lambda lo, hi: (lo > 0) | (hi < 0)
    tab["found"] = (excl(tab["lo_train"], tab["hi_train"]) & (tab["n_ev_train"] >= 10)
                    & excl(tab["lo_holdout"], tab["hi_holdout"])
                    & (np.sign(tab["beta_train"]) == np.sign(tab["beta_holdout"]))
                    & (tab["q_train"] <= 0.10) & (tab["q_holdout"] <= 0.10))
    tab["settles_on"] = tab["event"].map(SETTLEABLE).fillna("none (no hourly or schedule contract)")
    tab.to_csv(OUT / "results.csv", index=False, float_format="%.5g")
    say(f"\n{len(tab)} tests, BH 10% on each period")
    pct = lambda b: 100 * (np.exp(b) - 1)
    for _, r in tab.iterrows():
        unit = (lambda b: f"{b:+.4f}") if r["outcome"] == "late_share" else (lambda b: f"{pct(b):+.1f}%")
        say(f"{r['q']} {r['event']:<28} {r['outcome']:<10} train {unit(r['beta_train'])} [{unit(r['lo_train'])},{unit(r['hi_train'])}] "
            f"n_ev {r['n_ev_train']} q {r['q_train']:.3f} | hold {unit(r['beta_holdout'])} [{unit(r['lo_holdout'])},{unit(r['hi_holdout'])}] "
            f"n_ev {r['n_ev_holdout']} q {r['q_holdout']:.3f} | {'FOUND' if r['found'] else '-'}")
    hed = [h for _, r in tab[tab["found"]].iterrows() if (h := hedge(d, r))]
    if hed:
        pd.DataFrame(hed).to_csv(OUT / "hedge.csv", index=False)
        say("\nhedge backtest (2024, sized from train):")
        for h in hed:
            say(f"  {h}")
    (OUT / "output.txt").write_text("\n".join(LINES) + "\n")


if __name__ == "__main__":
    main()
