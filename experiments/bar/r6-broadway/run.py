"""R6 broadway: snow/heat and Knicks/Rangers playoff home games vs Broadway grosses and Times Square visits.

Run from backend/:  .venv/bin/python ../experiments/bar/r6-broadway/fetch.py   (once)
                    .venv/bin/python ../experiments/bar/r6-broadway/run.py

The pre-registered tests, controls and splits are in RESULTS.md. Broadway is weekly (1985-2020,
public Broadway League grosses); Times Square is daily Dewey visits summed over a balanced panel
of restaurants/bars in ZIPs 10036+10019, with ZIP 10028 as the placebo. Only aggregates are
written; no venue names, ids or addresses.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm
from dateutil.easter import easter
from pandas.tseries.holiday import USFederalHolidayCalendar
from statsmodels.stats.multitest import multipletests

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app import config  # noqa: E402

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
OUT = Path(__file__).resolve().parent
GLOB = str(ROOT / "data/01a16ff2-6017-7e10-86ac-94bf02853813/*.parquet")
Z = 1.645
TEAMS = {"knicks": "18", "rangers": "13"}
TS_ZIPS, PLACEBO_ZIPS = ("10036", "10019"), ("10028",)
D_START, D_TRAIN_END, D_END = date(2024, 1, 1), date(2025, 3, 31), date(2026, 9, 27)


# ------------------------------------------------------------------ inputs
def ghcn() -> pd.DataFrame:
    """Central Park daily, in inches and deg F (GHCN raw: PRCP tenths mm, SNOW mm, TMAX tenths C)."""
    w = pd.read_csv(CACHE / "ghcnd_USW00094728.csv", usecols=["DATE", "PRCP", "SNOW", "TMAX"], low_memory=False)
    w["date"] = pd.to_datetime(w["DATE"]).dt.date
    w = w.set_index("date")
    return pd.DataFrame({"prcp": w.PRCP / 254.0, "snow": w.SNOW / 25.4, "tmax": w.TMAX / 10 * 9 / 5 + 32})


def games() -> pd.DataFrame:
    """One row per (team, local date) MSG home game; postseason flag. Old ESPN season labels are
    shifted by a year and overlap, so rows are deduped by date."""
    rows = []
    for team, tid in TEAMS.items():
        for s in range(1986, 2027):
            for t in (2, 3):
                txt = (CACHE / f"r6broadway_espn_{team}_{s}_{t}.json").read_text()
                for e in json.loads(txt or "{}").get("events", []):
                    comp = e["competitions"][0]
                    me = [x for x in comp["competitors"] if x["id"] == tid]
                    if not me or me[0]["homeAway"] != "home" or comp.get("neutralSite"):
                        continue
                    d = pd.Timestamp(e["date"]).tz_convert("America/New_York").date()
                    rows.append((team, d, t == 3))
    g = pd.DataFrame(rows, columns=["team", "date", "post"]).drop_duplicates(["team", "date"])
    return g


def broadway() -> pd.DataFrame:
    b = pd.read_csv(CACHE / "r6broadway_grosses.csv", parse_dates=["week_ending"])
    b["cap_seats"] = b.seats_in_theatre * (b.performances + b.previews)
    w = b.groupby("week_ending").agg(gross=("weekly_gross", "sum"), seats=("seats_sold", "sum"),
                                     cap=("cap_seats", "sum"), shows=("show", "nunique")).reset_index()
    w["capacity"] = 100 * w.seats / w.cap
    return w[(w.gross > 0) & (w.seats > 0)].reset_index(drop=True)


def dewey() -> pd.DataFrame:
    con = duckdb.connect()
    con.execute(f"""
        create table w as select ID_STORE id, DATE_RANGE_START::date ws,
            lpad(trim(POSTAL_CODE::varchar), 5, '0') zip, from_json(VISITS_BY_DAY, '["INTEGER"]') v
        from '{GLOB}'""")
    nweeks = con.execute("select count(distinct ws) from w").fetchone()[0]
    con.execute(f"""create table keep as select id, any_value(zip) zip from w group by id
        having count(*) = {nweeks} and avg((list_min(v) = list_max(v))::int) < 0.05""")
    n = con.execute(f"""select sum((zip in {TS_ZIPS})::int), sum((zip in ('10028'))::int) from keep""").fetchone()
    df = con.execute(f"""
        with d as (select w.id, w.ws + (i - 1)::int as date, w.v[i] x from w join keep using (id), range(1, 8) r(i))
        select date, sum(case when zip in {TS_ZIPS} then x end) times_sq,
                     sum(case when zip in ('10028') then x end) placebo_10028
        from d join keep k using (id) group by date order by date""").df()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[(df.date >= D_START) & (df.date <= D_END)].reset_index(drop=True)
    return df, {"times_sq": int(n[0]), "placebo_10028": int(n[1])}


# ------------------------------------------------------------------ weekly frame
def holiday_days(y0: int, y1: int) -> dict[str, set]:
    cal = USFederalHolidayCalendar().holidays(f"{y0}-01-01", f"{y1}-12-31", return_name=True)
    keep = {"Birthday of Martin Luther King, Jr.": "mlk", "Washington's Birthday": "presidents",
            "Memorial Day": "memorial", "Independence Day": "july4", "Labor Day": "labor",
            "Thanksgiving Day": "thanksgiving", "Christmas Day": "christmas", "New Year's Day": "newyear"}
    out: dict[str, set] = {v: set() for v in keep.values()} | {"easter": set()}
    for d, nm in cal.items():
        if nm in keep:
            out[keep[nm]].add(d.date())
    for y in range(y0, y1 + 1):
        out["easter"].add(easter(y))
        out["july4"].add(date(y, 7, 4))
        out["christmas"].add(date(y, 12, 25))
        out["newyear"].add(date(y, 1, 1))
    return out


def weekly(b: pd.DataFrame, wx: pd.DataFrame, g: pd.DataFrame) -> pd.DataFrame:
    hol = holiday_days(1984, 2021)
    po = g[g.post].groupby("date").size()
    reg = g[~g.post].groupby("date").size()
    rows = []
    for we in b.week_ending.dt.date:
        days = [we - timedelta(days=k) for k in range(6, -1, -1)]  # Mon..Sun
        x = wx.reindex(days)
        r = {"week_ending": we, "snow_days": int((x.snow >= 1.0).sum()), "big_snow": int((x.snow >= 6.0).any()),
             "heat_days": int((x.tmax >= 90).sum()), "heatwave": int((x.tmax >= 90).sum() >= 3),
             "playoff_home": int(po.reindex(days).fillna(0).sum()), "reg_home": int(reg.reindex(days).fillna(0).sum()),
             "wx_missing": int(x[["snow", "tmax"]].isna().any(axis=1).sum())}
        for k, s in hol.items():
            r[f"h_{k}"] = int(any(d in s for d in days))
        rows.append(r)
    w = b.assign(week_ending=b.week_ending.dt.date).merge(pd.DataFrame(rows), on="week_ending")
    for ev in ("snow_days", "big_snow", "heat_days", "heatwave", "playoff_home"):
        w[f"{ev}_lead"] = w[ev].shift(-1)  # placebo: next week's event
    return w


# ------------------------------------------------------------------ models
def fit(y: pd.Series, X: pd.DataFrame, lags: int):
    X = X.loc[:, (X.nunique() > 1) | (X.columns == "const")]
    return sm.OLS(y, X, missing="drop").fit(cov_type="HAC", cov_kwds={"maxlags": lags}, use_t=False)


def wk_design(w: pd.DataFrame, ev: str, playoff: bool) -> pd.DataFrame:
    ts = pd.to_datetime(w.week_ending)
    X = pd.get_dummies(ts.dt.strftime("%Y%m"), prefix="ym", drop_first=True).astype(float)
    X.insert(0, "const", 1.0)
    X = X.join(w.filter(like="h_").astype(float))
    X["log_shows"] = np.log(w.shows)
    if playoff:
        X["reg_home"] = w.reg_home.astype(float)
    X["flag"] = w[ev].astype(float)
    return X


def day_design(f: pd.DataFrame, flag: pd.Series) -> pd.DataFrame:
    ts = pd.to_datetime(f.date)
    X = pd.get_dummies(ts.dt.day_of_week, prefix="dow", drop_first=True).astype(float)
    X = X.join(pd.get_dummies(ts.dt.strftime("%Y%m"), prefix="ym", drop_first=True).astype(float))
    X.insert(0, "const", 1.0)
    X["holiday"] = f.date.isin(config.HOLIDAYS).astype(float)
    X["reg_home"] = f.reg_home.astype(float)
    X["flag"] = flag.astype(float)
    return X


def row(res, **kw) -> dict:
    b, se = res.params["flag"], res.bse["flag"]
    return kw | {"beta": b, "se": se, "lo": b - Z * se, "hi": b + Z * se, "p": res.pvalues["flag"], "nobs": int(res.nobs)}


WK_SPLITS = {"weather": [("train", date(1985, 6, 1), date(2002, 12, 31)), ("holdout", date(2003, 1, 1), date(2020, 3, 8))],
             "playoff": [("train", date(1993, 7, 1), date(2006, 12, 31)), ("holdout", date(2007, 1, 1), date(2020, 3, 8))]}
WK_EVENTS = {"snow_days": "weather", "big_snow": "weather", "heat_days": "weather", "heatwave": "weather",
             "playoff_home": "playoff"}
WK_Y = {"log_gross": lambda w: np.log(w.gross), "log_seats": lambda w: np.log(w.seats), "capacity_pp": lambda w: w.capacity}


def run_weekly(w: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ev, kind in WK_EVENTS.items():
        for yname, yfn in WK_Y.items():
            for test, col in (("main", ev), ("placebo_lead", f"{ev}_lead")):
                for split, lo, hi in WK_SPLITS[kind]:
                    s = w[(w.week_ending >= lo) & (w.week_ending <= hi) & (w.wx_missing == 0)].reset_index(drop=True)
                    s = s[s[col].notna()].reset_index(drop=True)
                    X = wk_design(s, col, kind == "playoff")
                    res = fit(yfn(s), X, 4)
                    rows.append(row(res, source="broadway_weekly", series=yname, event=ev, test=test, split=split,
                                    range=f"{lo}..{hi}", n_ev=int((s[col] > 0).sum()), ev_total=int(s[col].sum())))
    return pd.DataFrame(rows)


def run_daily(f: pd.DataFrame) -> pd.DataFrame:
    ev = {"snow_day": f.snow >= 1.0, "heat_day": f.tmax >= 90, "playoff_home": f.playoff_home > 0}
    rows = []
    for name, flag in ev.items():
        for series in ("times_sq", "placebo_10028"):
            for test, fl in (("main", flag), ("placebo_daybefore", flag.shift(-1, fill_value=False))):
                if series == "placebo_10028" and test != "main":
                    continue
                for split, lo, hi in (("train", D_START, D_TRAIN_END), ("holdout", D_TRAIN_END + timedelta(1), D_END)):
                    m = ((f.date >= lo) & (f.date <= hi)).to_numpy()
                    s, fls = f[m].reset_index(drop=True), fl[m].reset_index(drop=True)
                    res = fit(np.log(s[series]), day_design(s, fls), 7)
                    rows.append(row(res, source="dewey_daily", series=series, event=name,
                                    test=test if series == "times_sq" else "placebo_zip", split=split,
                                    range=f"{lo}..{hi}", n_ev=int(fls.sum()), ev_total=int(fls.sum())))
    return pd.DataFrame(rows)


def verdicts(r: pd.DataFrame) -> pd.DataFrame:
    """BH over the pre-registered family: train p-values of the 18 main tests."""
    key = ["source", "series", "event"]
    main = r[r.test == "main"]
    tr = main[main.split == "train"].set_index(key)
    ho = main[main.split == "holdout"].set_index(key)
    v = tr[["beta", "lo", "hi", "p", "n_ev"]].join(ho[["beta", "lo", "hi", "p", "n_ev"]], rsuffix="_ho")
    v["q"] = multipletests(v.p, alpha=0.10, method="fdr_bh")[1]
    sig = lambda lo, hi: (lo > 0) | (hi < 0)  # noqa: E731
    v["found"] = (sig(v.lo, v.hi) & (v.n_ev >= 10) & sig(v.lo_ho, v.hi_ho)
                  & (np.sign(v.beta) == np.sign(v.beta_ho)) & (v.q <= 0.10))
    return v.reset_index()


def main() -> None:
    wx, g = ghcn(), games()
    w = weekly(broadway(), wx, g)
    rw = run_weekly(w)

    d, nstores = dewey()
    po = g[g.post].groupby("date").size()
    reg = g[~g.post].groupby("date").size()
    f = d.set_index("date").join(wx).assign(playoff_home=po, reg_home=reg).fillna({"playoff_home": 0, "reg_home": 0})
    f = f.reset_index()
    assert f[["snow", "tmax"]].notna().all().all(), "weather gaps"
    rd = run_daily(f)

    r = pd.concat([rw, rd], ignore_index=True)
    r.to_csv(OUT / "results.csv", index=False, float_format="%.4g")
    v = verdicts(r)
    v.to_csv(OUT / "verdicts.csv", index=False, float_format="%.4g")
    pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_rows", 200)
    print("dewey stores:", nstores, "| broadway weeks:", len(w), w.week_ending.min(), w.week_ending.max())
    print("\n== verdicts (BH family = %d tests) ==" % len(v))
    print(v.to_string(float_format=lambda x: f"{x:.4g}"))
    print("\n== placebos ==")
    print(r[r.test != "main"][["source", "series", "event", "test", "split", "n_ev", "beta", "lo", "hi", "p"]]
          .to_string(float_format=lambda x: f"{x:.4g}"))
    # context for $ conversion
    mean_gross = w[w.week_ending >= date(2015, 1, 1)].gross.mean()
    print(f"\nmean weekly gross 2015..2020-03: ${mean_gross:,.0f}")
    print("snow-day weeks by split:", w.groupby(pd.to_datetime(w.week_ending).dt.year >= 2003).snow_days.sum().to_dict())


if __name__ == "__main__":
    main()
