"""R4 iowa: Iowa Class E liquor orders vs college football results and NOAA weather.

Input: r2-cache/r4iowa_daily.parquet, aggregated by the duckdb step in build_daily()
from the Kaggle mirror of Iowa Liquor Sales (2012-01-03..2017-10-31). The raw CSV is
deleted after aggregation.

Run from backend/:  .venv/bin/python ../experiments/bar/r4-iowa/iowa.py
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.holiday import USFederalHolidayCalendar
from statsmodels.stats.multitest import multipletests

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
DAILY = CACHE / "r4iowa_daily.parquet"
Z = 1.645
TRAIN = ("2012-01-01", "2015-12-31")
HOLD = ("2016-01-01", "2017-10-31")  # data ends 2017-10-31
TEAMS = {"ICY": (2294, "Iowa"), "AMES": (66, "Iowa St.")}
STATIONS = {"DSM": "USW00014933", "ICY": "USC00134101", "MSP": "USW00014922", "CHI": "USW00014819"}


def build_daily(csv: Path) -> None:
    """One-off: aggregate the raw CSV to date x area x liquor group."""
    import duckdb

    duckdb.sql(f"""
    COPY (
    WITH r AS (
      SELECT strptime("Date",'%m/%d/%Y')::DATE AS d, upper(trim("City")) AS city,
             upper(coalesce("Category Name",'')) AS cat, "Store Number" AS store,
             try_cast(replace(replace("Sale (Dollars)",'$',''),',','') AS DOUBLE) AS usd
      FROM read_csv('{csv}', header=true, all_varchar=true, quote='"', escape='"',
                    parallel=false, strict_mode=false))
    SELECT d,
      CASE WHEN city IN ('DES MOINES','WEST DES MOINES','URBANDALE','ANKENY','CLIVE','JOHNSTON',
                         'ALTOONA','WINDSOR HEIGHTS','PLEASANT HILL') THEN 'DSM'
           WHEN city IN ('IOWA CITY','CORALVILLE','NORTH LIBERTY') THEN 'ICY'
           WHEN city='AMES' THEN 'AMES' ELSE 'OTHER' END AS area,
      CASE WHEN cat LIKE '%VODKA%' THEN 'vodka'
           WHEN cat LIKE '%WHISK%' OR cat LIKE '%BOURBON%' OR cat LIKE '%SCOTCH%' OR cat LIKE '%RYE%' THEN 'whiskey'
           WHEN cat LIKE '%RUM%' THEN 'rum' WHEN cat LIKE '%TEQUILA%' OR cat LIKE '%MEZCAL%' THEN 'tequila'
           WHEN cat LIKE '%SCHNAPP%' OR cat LIKE '%LIQUEUR%' OR cat LIKE '%CORDIAL%' OR cat LIKE '%CREME%' THEN 'liqueur'
           ELSE 'other' END AS grp,
      sum(usd) AS usd, count(*) AS lines, count(DISTINCT store) AS stores,
      count(*) FILTER (WHERE usd IS NULL) AS bad
    FROM r GROUP BY ALL ORDER BY d) TO '{DAILY}' (FORMAT parquet)""")


def games() -> pd.DataFrame:
    path = CACHE / "r4iowa_games.json"
    if path.exists():
        return pd.DataFrame(json.loads(path.read_text()))
    rows = []
    for area, (tid, name) in TEAMS.items():
        for season in range(2012, 2018):
            url = f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{tid}/schedule?season={season}"
            for e in httpx.get(url, timeout=30).json()["events"]:
                c = e["competitions"][0]
                me = next(x for x in c["competitors"] if str(x["team"]["id"]) == str(tid))
                rows.append(dict(area=area, team=name, season=season,
                                 date=pd.Timestamp(e["date"]).tz_convert("America/Chicago").strftime("%Y-%m-%d"),
                                 home=me["homeAway"] == "home" and not c.get("neutralSite", False),
                                 win=bool(me.get("winner"))))
    path.write_text(json.dumps(rows))
    return pd.DataFrame(rows)


def ghcn(station: str) -> pd.DataFrame:
    path = CACHE / f"r4iowa_ghcn_{station}.csv"
    if not path.exists():
        url = f"https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/{station}.csv"
        path.write_bytes(httpx.get(url, timeout=120).content)
    df = pd.read_csv(path, usecols=lambda c: c in {"DATE", "PRCP", "SNOW", "TMAX"}, low_memory=False)
    df["DATE"] = pd.to_datetime(df["DATE"])
    df = df[(df.DATE >= "2012-01-01") & (df.DATE <= "2017-10-31")].set_index("DATE")
    # GHCN units: PRCP/SNOW tenths of mm / mm, TMAX tenths of C
    out = pd.DataFrame(index=df.index)
    out["rain"] = (df["PRCP"] / 254.0 >= 0.01).astype(float).where(df["PRCP"].notna())
    out["snow"] = (df["SNOW"] / 25.4 >= 1.0).astype(float).where(df["SNOW"].notna()) if "SNOW" in df else np.nan
    out["hot"] = (df["TMAX"] / 10 * 9 / 5 + 32 >= 90).astype(float).where(df["TMAX"].notna()) if "TMAX" in df else np.nan
    return out


def holidays(idx: pd.DatetimeIndex) -> pd.Series:
    h = USFederalHolidayCalendar().holidays("2011-12-01", "2018-01-31")
    return pd.Series(idx.isin(h).astype(float), index=idx)


def fit(y: pd.Series, X: pd.DataFrame, ev: str, lags: int) -> dict:
    d = pd.concat([y.rename("y"), X], axis=1).dropna()
    d = d.loc[:, d.std() > 0].assign(const=1.0) if ev in d else d
    if ev not in d or d[ev].sum() < 1:
        return dict(beta=np.nan, lo=np.nan, hi=np.nan, p=np.nan, n_ev=0, n=len(d))
    r = sm.OLS(d["y"], d.drop(columns="y")).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    b, se = r.params[ev], r.bse[ev]
    return dict(beta=b, lo=b - Z * se, hi=b + Z * se, p=r.pvalues[ev], n_ev=int(d[ev].sum()), n=len(d), res=r)


def fe(idx: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.get_dummies(pd.Series(idx.strftime("%Y-%m"), index=idx), prefix="ym", drop_first=True, dtype=float)


def weekly(daily: pd.DataFrame) -> pd.DataFrame:
    w = daily.groupby([pd.Grouper(key="d", freq="W-SUN"), "area"]).usd.sum().unstack()  # Mon..Sun weeks
    w = w[w.index <= "2017-10-29"]
    return w


def football_tests(daily: pd.DataFrame, g: pd.DataFrame) -> list[dict]:
    w = weekly(daily)
    out = []
    state = w.sum(axis=1)
    hol = holidays(pd.date_range(w.index.min() - pd.Timedelta(days=6), w.index.max()))
    hol_w = hol.resample("W-SUN").max().reindex(w.index).fillna(0).rename("hol")
    for area, (_, name) in TEAMS.items():
        gg = g[g.area == area].copy()
        gg["wk"] = pd.to_datetime(gg.date).dt.to_period("W-SUN").dt.end_time.dt.normalize()
        f = pd.DataFrame(index=w.index)
        home = gg[gg.home].groupby("wk").size().reindex(w.index).fillna(0).clip(0, 1)
        homewin = gg[gg.home & gg.win].groupby("wk").size().reindex(w.index).fillna(0).clip(0, 1)
        anywin = gg[gg.win].groupby("wk").size().reindex(w.index).fillna(0).clip(0, 1)
        anyloss = gg[~gg.win].groupby("wk").size().reindex(w.index).fillna(0).clip(0, 1)
        f["home_L0"] = home                       # orders in the Mon-Sun week of a home game
        f["home_L1"] = home.shift(-1).fillna(0)   # orders the week before a home game
        f["homewin_post1"] = homewin.shift(1).fillna(0)
        f["win_post1"] = anywin.shift(1).fillna(0)
        played = (anywin + anyloss).clip(0, 1).shift(1).fillna(0).rename("played_post1")
        units = {f"{area}/rest": np.log(w[area]) - np.log(w["OTHER"]), f"state[{area} team]": np.log(state)}
        for unit, y in units.items():
            for ev in (["home_L0", "home_L1", "homewin_post1", "win_post1"] if "/rest" in unit else ["home_L0", "win_post1"]):
                X = pd.concat([f[[ev]], hol_w], axis=1)
                if ev in ("homewin_post1", "win_post1"):
                    X = X.join(played)            # win vs loss, conditional on a game last week
                    if ev == "homewin_post1":
                        X = X.join(home.shift(1).fillna(0).rename("home_post1"))
                for split, (a, b) in (("train", TRAIN), ("hold", HOLD)):
                    m = (y.index >= a) & (y.index <= b)
                    Xs = X[m].join(fe(y.index[m]))
                    r = fit(y[m], Xs, ev, 4)
                    out.append(dict(family="football", unit=unit, event=ev, split=split, **r))
    return out


def weather_tests(daily: pd.DataFrame) -> list[dict]:
    out = []
    tot = daily.groupby(["d", "area"]).usd.sum().unstack().fillna(0)
    tot.index = pd.to_datetime(tot.index)
    tot = tot[tot.sum(axis=1) > 50_000]  # order days only (drops Sundays/closures)
    units = {"state/DSM wx": (np.log(tot.sum(axis=1)), ghcn(STATIONS["DSM"])),
             "ICY/rest ICY wx": (np.log(tot["ICY"].clip(lower=1)) - np.log(tot["OTHER"]), ghcn(STATIONS["ICY"]))}
    for unit, (y, wx) in units.items():
        wx = wx.reindex(y.index)
        wx["snow_lag1"] = wx["snow"].shift(1)
        evs = ["rain", "snow", "hot", "snow_lag1"] if unit.startswith("state") else ["rain", "snow"]
        dow = pd.get_dummies(pd.Series(y.index.dayofweek, index=y.index), prefix="dow", drop_first=True, dtype=float)
        for ev in evs:
            X = wx[[ev]].join(dow).join(holidays(y.index).rename("hol"))
            for split, (a, b) in (("train", TRAIN), ("hold", HOLD)):
                m = (y.index >= a) & (y.index <= b)
                r = fit(y[m], X[m].join(fe(y.index[m])), ev, 7)
                out.append(dict(family="weather", unit=unit, event=ev, split=split, **r))
    return out


def basis() -> pd.DataFrame:
    dsm = ghcn(STATIONS["DSM"])
    rows = []
    for k in ("MSP", "CHI"):
        o = ghcn(STATIONS[k])
        for v in ("rain", "snow", "hot"):
            j = pd.concat([dsm[v], o[v]], axis=1).dropna()
            rows.append(dict(vs=k, flag=v, corr=j.corr().iloc[0, 1], n=len(j)))
    return pd.DataFrame(rows)


def main() -> None:
    daily = pd.read_parquet(DAILY)
    daily["d"] = pd.to_datetime(daily["d"])
    print(f"daily rows {len(daily)}, {daily.d.min().date()}..{daily.d.max().date()}, ${daily.usd.sum()/1e9:.2f}B")
    g = games()
    print(g.groupby(["team", "season"]).agg(home=("home", "sum"), win=("win", "sum"), n=("win", "size")).unstack(0).to_string())
    res = pd.DataFrame(football_tests(daily, g) + weather_tests(daily))
    res = res.drop(columns="res")
    tr = res[res.split == "train"].reset_index(drop=True)
    ho = res[res.split == "hold"].reset_index(drop=True)
    t = tr[["family", "unit", "event"]].copy()
    for c in ("beta", "lo", "hi", "p", "n_ev", "n"):
        t[f"tr_{c}"] = tr[c]
        t[f"ho_{c}"] = ho[c]
    ok = t.tr_p.notna()
    t.loc[ok, "bh_q"] = multipletests(t.loc[ok, "tr_p"], alpha=0.10, method="fdr_bh")[1]
    t["tr_sig"] = (t.tr_lo > 0) | (t.tr_hi < 0)
    t["ho_sig_same"] = np.sign(t.tr_beta) == np.sign(t.ho_beta)
    t["ho_sig_same"] &= (t.ho_lo > 0) | (t.ho_hi < 0)
    t["FOUND"] = t.tr_sig & (t.tr_n_ev >= 10) & t.ho_sig_same & (t.bh_q <= 0.10)
    pd.set_option("display.width", 250)
    cols = ["family", "unit", "event", "tr_beta", "tr_lo", "tr_hi", "tr_n_ev", "tr_n", "ho_beta", "ho_lo", "ho_hi",
            "ho_n_ev", "ho_n", "bh_q", "FOUND"]
    print(f"\n{len(t)} tests (each fitted on train and on holdout)")
    print(t[cols].to_string(float_format=lambda x: f"{x:.4f}"))
    t[cols].to_csv(Path(__file__).with_name("results.csv"), index=False)
    print("\nbasis: DSM flag vs Kalshi-city station flag (phi)")
    print(basis().to_string(float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build_daily(CACHE / "r4iowa_sales.csv")
    main()
