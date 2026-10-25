"""R6 gas: weekly bike-share / rideshare demand vs retail gasoline prices.

Run from backend/:  .venv/bin/python ../experiments/bar/r6-gas/gas.py
Inputs (scratchpad r2-cache/, built once; see RESULTS.md):
  r6gas_*.xls                EIA weekly retail regular gasoline (hist_xls downloads)
  r6gas_divvy_daily.parquet  Divvy daily aggregates (from archive (2).zip, extract deleted)
  r6gas_austin_daily.parquet Austin B-cycle daily aggregates (archive (3).zip)
  r6gas_*_monthly_stations.parquet  distinct active stations per month
  citibike_jc_daily.parquet  (r2-citibike)   tlc/*.parquet (r2-taxi)
  r4iowa_ghcn_USW00014819.csv (Midway)  r6gas_ghcn_aus.csv (Bergstrom)  ghcnd_USW00094728.csv (CP)
  r6gas_kalshi.json          Kalshi KXAAAGAS* markets (settled + open)
"""
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

C = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
OUT = Path(__file__).parent
Z = 1.645
HAC_LAGS = 6
LEAD = 4  # placebo: gas price 4 weeks ahead

EIA = {
    "us": "EMM_EPMR_PTE_NUS_DPG",
    "chi": "EMM_EPMR_PTE_YORD_DPG",
    "midwest": "EMM_EPMR_PTE_R20_DPG",
    "tx": "EMM_EPMR_PTE_STX_DPG",
    "gulf": "EMM_EPMR_PTE_R30_DPG",
    "nyc": "EMM_EPMR_PTE_Y35NY_DPG",
    "nys": "EMM_EPMR_PTE_SNY_DPG",
}


# ---------------------------------------------------------------- data
def load_gas() -> pd.DataFrame:
    cache = C / "r6gas_eia.csv"
    if cache.exists():
        return pd.read_csv(cache, parse_dates=["week"]).set_index("week")
    sys.path.insert(0, str(C / "r6gas_pylib"))  # xlrd
    cols = {}
    for k, s in EIA.items():
        d = pd.read_excel(C / f"r6gas_{s}.xls", sheet_name="Data 1", skiprows=2, engine="xlrd")
        cols[k] = d.set_index("Date").iloc[:, 0]
    g = pd.DataFrame(cols)
    g.index = pd.to_datetime(g.index)
    g.index = g.index - pd.to_timedelta(g.index.dayofweek, unit="D")  # Monday of the week
    g.index.name = "week"
    g.to_csv(cache)
    return g


def weekly(daily: pd.DataFrame, how="sum") -> pd.DataFrame:
    d = daily.copy()
    d.index = pd.to_datetime(d.index)
    wk = d.index - pd.to_timedelta(d.index.dayofweek, unit="D")
    agg = d.groupby(wk).agg(how)
    n = d.groupby(wk).size()
    agg = agg[n == 7]  # full weeks only
    agg.index.name = "week"
    return agg


def ghcn_weekly(path: str) -> pd.DataFrame:
    w = pd.read_csv(path, usecols=lambda c: c in {"DATE", "PRCP", "SNOW", "TMAX"}, parse_dates=["DATE"])
    w = w.set_index("DATE").sort_index()
    w["rain"] = (w.PRCP >= 0.01).astype(float)
    w["SNOW"] = w.SNOW.fillna(0)
    d = pd.DataFrame({"tmax": w.TMAX, "rain_days": w.rain, "prcp": w.PRCP, "snow": w.SNOW})
    wk = weekly(d.dropna(subset=["tmax"]), how={"tmax": "mean", "rain_days": "sum", "prcp": "sum", "snow": "sum"})
    wk["tmax2"] = (wk.tmax - 65) ** 2 / 100
    return wk


def holidays_weekly(start, end) -> pd.Series:
    from pandas.tseries.holiday import USFederalHolidayCalendar
    days = pd.date_range(start, end)
    hol = USFederalHolidayCalendar().holidays(start, end)
    s = pd.Series(days.isin(hol).astype(float), index=days)
    return weekly(s.to_frame("hol"))["hol"]


def stations_weekly(path, weeks) -> pd.Series:
    m = pd.read_parquet(path).set_index("ym")["stations_m"]
    return pd.Series([m.get(w.strftime("%Y-%m"), np.nan) for w in weeks], index=weeks)


def build_units():
    gas = load_gas()
    cp = ghcn_weekly(C / "ghcnd_USW00094728.csv")
    mdw = ghcn_weekly(C / "r4iowa_ghcn_USW00014819.csv")
    aus = ghcn_weekly(C / "r6gas_ghcn_aus.csv")
    hol = holidays_weekly("2013-01-01", "2026-01-01")

    units = {}

    dv = pd.read_parquet(C / "r6gas_divvy_daily.parquet").set_index("date")
    dvw = weekly(dv[["trips"]])  # the cleaned Kaggle file is 99.98% Subscriber trips, so no split
    st = stations_weekly(C / "r6gas_divvy_monthly_stations.parquet", dvw.index)
    units["divvy_trips"] = dict(y=dvw.trips, wx=mdw, local="chi", stations=st, train=(2014, 2015), hold=(2016, 2017))

    au = pd.read_parquet(C / "r6gas_austin_daily.parquet").set_index("date")
    auw = weekly(au[["trips", "casual"]])
    st = stations_weekly(C / "r6gas_austin_monthly_stations.parquet", auw.index)
    units["austin_trips"] = dict(y=auw.trips, wx=aus, local="tx", stations=st, train=(2014, 2015), hold=(2016, 2017))

    jc = pd.read_parquet(C / "citibike_jc_daily.parquet")
    units["citibike_jc_trips"] = dict(y=weekly(jc[["trips"]]).trips, wx=cp, local="nyc", stations=None,
                                      train=(2023, 2023), hold=(2024, 2025))

    def tlc(kind):
        fs = sorted(glob.glob(str(C / f"tlc/{kind}_*.parquet")))
        d = pd.concat([pd.read_parquet(f) for f in fs]).groupby("date")[["trips", "total"]].sum()
        d.index = pd.to_datetime(d.index)
        d = d.asfreq("D")
        if kind == "yellow":  # r2-taxi data-gap rule: <25% of 29-day rolling median -> missing
            med = d.trips.rolling(29, center=True, min_periods=10).median()
            d.loc[d.trips < 0.25 * med] = np.nan
        return weekly(d.dropna())

    fh = tlc("fhvhv")
    ye = tlc("yellow")
    for y, name in [(fh.trips, "fhv_trips"), (fh.total / fh.trips, "fhv_usd_per_trip"), (ye.trips, "yellow_trips")]:
        units[name] = dict(y=y, wx=cp, local="nyc", stations=None, train=(2022, 2023), hold=(2024, 2025))
    for u in units.values():
        u["hol"] = hol
    return units, gas


# ---------------------------------------------------------------- models
def frame(u, gas, gcol, years):
    df = pd.DataFrame({"y": np.log(u["y"])})
    df = df.join(u["wx"][["tmax", "tmax2", "rain_days", "prcp", "snow"]], how="inner")
    df["hol"] = u["hol"].reindex(df.index).fillna(0)
    lg = np.log(gas[gcol])
    df["lgas"] = lg.reindex(df.index)
    df["lgas_lead"] = lg.shift(-LEAD).reindex(df.index)
    if u["stations"] is not None:
        df["lstations"] = np.log(u["stations"].reindex(df.index))
    df = df[(df.index.year >= years[0]) & (df.index.year <= years[1])]
    return df


def fit(df, spec, xvars=("lgas",)):
    """A: month-of-year + year FE.  B: year-month FE.  C: 52-week log differences."""
    ctrl = ["tmax", "tmax2", "rain_days", "prcp", "snow", "hol"] + (["lstations"] if "lstations" in df else [])
    d = df.dropna(subset=["y", *xvars, *ctrl]).copy()
    if spec == "C":
        full = df.copy()
        full = full.reindex(pd.date_range(full.index.min(), full.index.max(), freq="7D"))
        diff = full - full.shift(52)
        d = diff.dropna(subset=["y", *xvars, *ctrl])
        X = sm.add_constant(d[[*xvars, *ctrl]], has_constant="add")
    else:
        if spec == "A":
            fe = pd.get_dummies(d.index.month.astype(str), prefix="m", drop_first=True).astype(float)
            fe = fe.join(pd.get_dummies(d.index.year.astype(str), prefix="y", drop_first=True).astype(float))
        else:
            fe = pd.get_dummies(d.index.strftime("%Y-%m"), prefix="ym", drop_first=True).astype(float)
        fe.index = d.index
        X = sm.add_constant(pd.concat([d[[*xvars, *ctrl]], fe], axis=1), has_constant="add")
    X = X.loc[:, X.std() > 0].assign(const=1.0) if len(X) else X
    if len(d) < 30:
        return None
    r = sm.OLS(d["y"].astype(float), X.astype(float)).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS}, use_t=False)
    out = {"n": int(r.nobs)}
    for v in xvars:
        b, se = r.params[v], r.bse[v]
        out[v] = (b, b - Z * se, b + Z * se, r.pvalues[v])
    # identifying variation: SD of the gas regressor after partialling the FE/controls
    xr = sm.OLS(d[xvars[0]].astype(float), X.drop(columns=list(xvars)).astype(float)).fit().resid
    out["sd_resid_gas"] = float(np.std(xr))
    return out


def main():
    units, gas = build_units()
    rows = []
    for name, u in units.items():
        for gcol in [u["local"], "us"]:
            for spec in ["A", "B", "C"]:
                tr = fit(frame(u, gas, gcol, u["train"]), spec)
                ho = fit(frame(u, gas, gcol, u["hold"]), spec)
                if tr is None or ho is None:
                    continue
                rows.append(dict(unit=name, gas=gcol, spec=spec,
                                 tr_n=tr["n"], tr_b=tr["lgas"][0], tr_lo=tr["lgas"][1], tr_hi=tr["lgas"][2], tr_p=tr["lgas"][3],
                                 tr_sdx=tr["sd_resid_gas"],
                                 ho_n=ho["n"], ho_b=ho["lgas"][0], ho_lo=ho["lgas"][1], ho_hi=ho["lgas"][2], ho_p=ho["lgas"][3],
                                 ho_sdx=ho["sd_resid_gas"]))
    res = pd.DataFrame(rows)
    res["bh_q"] = multipletests(res.tr_p, alpha=0.10, method="fdr_bh")[1]
    excl = lambda lo, hi: (lo > 0) | (hi < 0)
    res["found"] = (res.bh_q < 0.10) & excl(res.tr_lo, res.tr_hi) & excl(res.ho_lo, res.ho_hi) & (np.sign(res.tr_b) == np.sign(res.ho_b))
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    print(f"=== main grid: {len(res)} tests (elasticity of weekly trips wrt gas price; CI90) ===")
    print(res.round(3).to_string(index=False))
    res.to_csv(OUT / "results.csv", index=False)

    # ---- placebo: future gas price (4 weeks ahead), alone and jointly with the current price
    prow = []
    for name, u in units.items():
        for per in ["train", "hold"]:
            df = frame(u, gas, u["local"], u[per])
            lead_only = fit(df.drop(columns=["lgas"]).rename(columns={"lgas_lead": "lgas"}), "A")
            joint = fit(df, "A", xvars=("lgas", "lgas_lead"))
            if lead_only is None:
                continue
            prow.append(dict(unit=name, period=per, lead_only_b=lead_only["lgas"][0], lead_only_lo=lead_only["lgas"][1],
                             lead_only_hi=lead_only["lgas"][2],
                             joint_cur_b=joint["lgas"][0], joint_cur_lo=joint["lgas"][1], joint_cur_hi=joint["lgas"][2],
                             joint_lead_b=joint["lgas_lead"][0], joint_lead_lo=joint["lgas_lead"][1], joint_lead_hi=joint["lgas_lead"][2]))
    pl = pd.DataFrame(prow)
    print(f"\n=== placebo: lead{LEAD} gas (spec A, local gas) ===")
    print(pl.round(3).to_string(index=False))
    pl.to_csv(OUT / "placebo.csv", index=False)

    basis(gas)


def basis(gas):
    print("\n=== basis: local EIA vs US EIA ===")
    g = gas.dropna()
    for per, (a, b) in {"2014-2017": ("2014", "2017"), "2022-2025": ("2022", "2025"), "2014-2025": ("2014", "2025")}.items():
        s = g.loc[a:b]
        dl = np.log(s).diff().dropna()
        m = np.log(s.resample("ME").last())
        dm = m.diff().dropna()
        for loc in ["chi", "tx", "nyc"]:
            r_w = dl[loc].corr(dl.us)
            r_m = dm[loc].corr(dm.us)
            beta_m = np.polyfit(dm.us, dm[loc], 1)[0]
            spread = (s[loc] - s.us)
            print(f"{per} {loc:4s}: level r={s[loc].corr(s.us):.3f}  weekly dlog r={r_w:.3f} (R2 {r_w**2:.2f})  "
                  f"monthly dlog r={r_m:.3f} (R2 {r_m**2:.2f}) beta={beta_m:.2f}  spread mean {spread.mean():+.3f} sd {spread.std():.3f} $/gal")
    print("\nrange of local gas, by year ($/gal):")
    print(g[["us", "chi", "tx", "nyc"]].loc["2013":"2025"].groupby(g.loc["2013":"2025"].index.year).agg(["min", "max"]).round(2).to_string())

    # AAA (Kalshi settlement) vs EIA: back out the AAA US average from each settled strike ladder
    k = json.load(open(C / "r6gas_kalshi.json"))
    print("\n=== Kalshi settled ladders: implied AAA vs EIA (same Monday for KXAAAGASW) ===")
    for ser in ["KXAAAGASW", "KXAAAGASM", "KXAAAGASDIL", "KXAAAGASDTX", "KXAAAGASDNY"]:
        ms = [m for m in k[ser]["markets"] if m.get("result") in ("yes", "no") and m.get("floor_strike") is not None]
        ev = {}
        for m in ms:
            ev.setdefault(m["event_ticker"], []).append(m)
        out = []
        for e, mm in ev.items():
            yes = [m["floor_strike"] for m in mm if m["result"] == "yes"]
            no = [m["floor_strike"] for m in mm if m["result"] == "no"]
            if not yes or not no:
                continue
            lo, hi = max(yes), min(no)
            day = pd.Timestamp(mm[0]["close_time"][:10])  # rules: AAA average "on <ticker date>" = close date
            out.append((e, day, lo, hi))
        out.sort(key=lambda t: t[1])
        print(f"{ser}: {len(out)} settled events; strike spacing e.g. {sorted({m['floor_strike'] for m in ms})[:4]}")
        if ser == "KXAAAGASW":
            loc = "us"
        elif ser == "KXAAAGASM":
            loc = "us"
        else:
            loc = {"KXAAAGASDIL": "chi", "KXAAAGASDTX": "tx", "KXAAAGASDNY": "nyc"}[ser]
        diffs = []
        for e, day, lo, hi in out[-12:] if ser.startswith("KXAAAGASD") else out:
            wk = day - pd.Timedelta(days=day.dayofweek)
            eia = gas[loc].get(wk, np.nan)
            mid = (lo + hi) / 2
            diffs.append(mid - eia)
            print(f"   {e:28s} {day.date()} AAA in ({lo:.3f},{hi:.3f}]  EIA {loc} wk {wk.date()} = {eia:.3f}  diff {mid - eia:+.3f}")
        d = np.array(diffs, dtype=float)
        print(f"   mean AAA-EIA {np.nanmean(d):+.3f}  sd {np.nanstd(d):.3f}")
    print("Kalshi rules:", k["KXAAAGASM"]["markets"][0]["rules_primary"])


if __name__ == "__main__":
    main()
