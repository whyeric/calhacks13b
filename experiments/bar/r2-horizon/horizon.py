"""R2 horizon: do weather totals explain weekly / monthly revenue better than daily events explain daily revenue?

Series
  taxi_zone  : features.build("taxi") daily fares, Oct 2024 to Aug 2026 (daily / weekly / monthly)
  bar        : Dewey visits x $35 for the MSG bar (opaque id), Jan 2024 to Sep 2026 (weekly / monthly)
  yellow_trips, yellow_fare : TLC citywide yellow cab trips/day and farebox/day, monthly 2010-01 to 2026-07
  hvfhv_trips: TLC high-volume FHV (app rides) trips/day, monthly 2015-01 to 2026-07

Weather is NOAA GHCN-Daily USW00094728 (Central Park), the station behind the NWS CLI report that settles
KXRAINNYCM / KXHIGHNY. Weeks are Mon..Sun, as in KXRAINNYCW.

Every (series, horizon, predictor) cell is one OLS fit on train and an independent refit on holdout, HAC
errors, z = 1.645. BH at 10% runs over the train p-values of every cell.

Run from backend/:  .venv/bin/python ../experiments/bar/r2-horizon/horizon.py
Downloads (cached in the scratchpad r2-cache):
  https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00094728.csv
  https://www.nyc.gov/assets/tlc/downloads/csv/data_reports_monthly.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.multitest import multipletests

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))
from app import config  # noqa: E402
from app.data import features  # noqa: E402

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
GHCN_URL = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00094728.csv"
TLC_URL = "https://www.nyc.gov/assets/tlc/downloads/csv/data_reports_monthly.csv"
Z = 1.645
HOT_F = 85.0
COVID = (pd.Timestamp("2020-03-01"), pd.Timestamp("2022-06-30"))


def fetch(url: str, name: str) -> Path:
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        r = httpx.get(url, follow_redirects=True, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        path.write_bytes(r.content)
    return path


# ---------------------------------------------------------------- weather
def station_daily() -> pd.DataFrame:
    g = pd.read_csv(fetch(GHCN_URL, "r2h_ghcn_USW00094728.csv"), usecols=["DATE", "PRCP", "SNOW", "TMAX", "TMIN"],
                    low_memory=False)
    g["date"] = pd.to_datetime(g["DATE"])
    g = g[g["date"] >= "2009-12-01"].set_index("date")
    out = pd.DataFrame(index=g.index)
    out["precip"] = g["PRCP"] / 254.0  # tenths of mm -> in
    out["snow"] = g["SNOW"] / 25.4  # mm -> in
    tmax = g["TMAX"] / 10 * 9 / 5 + 32
    tavg = (g["TMAX"] + g["TMIN"]) / 20 * 9 / 5 + 32
    out["rainy_day"] = (out["precip"] >= 0.01).astype(float)
    out["hot_day"] = (tmax > HOT_F).astype(float)
    out["cdd"] = (tavg - 65).clip(lower=0)
    return out


def agg_weather(d: pd.DataFrame, freq: str) -> pd.DataFrame:
    a = d.resample(freq).agg({"rainy_day": "sum", "precip": "sum", "hot_day": "sum", "cdd": "sum", "snow": "sum"})
    a = a.rename(columns={"rainy_day": "rainy_days", "hot_day": "hot_days"})
    if freq.startswith("W"):  # KXRAINNYCW strikes: 0.25 / 0.5 / 1 / 2 in, strictly greater
        a["precip_gt_0.5"] = (a["precip"] > 0.5).astype(float)
        a["precip_gt_1"] = (a["precip"] > 1.0).astype(float)
    else:  # KXRAINNYCM strikes are whole inches; KXNYCSNOWM 2/4/6/8 in
        a["precip_gt_4"] = (a["precip"] > 4.0).astype(float)
        a["snow_gt_2"] = (a["snow"] > 2.0).astype(float)
    return a


DAILY_PREDS = ["rainy_day", "precip", "hot_day", "cdd", "snow"]
BLOCK = ["rainy_days", "precip", "hot_days", "cdd", "snow"]  # the weather block for variance share


# ---------------------------------------------------------------- series
def holidays_per(index: pd.DatetimeIndex, freq: str) -> pd.Series:
    h = pd.Series(1.0, index=pd.to_datetime(sorted(config.HOLIDAYS)))
    return h.resample(freq).sum().reindex(index, fill_value=0.0)


def taxi_daily() -> pd.DataFrame:
    df = features.build("taxi")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")[["revenue", "is_holiday"]]


def bar_daily() -> pd.DataFrame:
    b = pd.read_parquet(BACKEND / "fixtures" / "restaurant_daily.parquet")
    b["date"] = pd.to_datetime(b["date"])
    out = b.set_index("date")[["revenue_est"]].rename(columns={"revenue_est": "revenue"})
    out["is_holiday"] = out.index.date
    out["is_holiday"] = out["is_holiday"].isin(config.HOLIDAYS)
    return out


def to_period(daily: pd.DataFrame, freq: str) -> pd.DataFrame:
    g = daily.resample(freq)
    out = pd.DataFrame({"revenue": g["revenue"].sum(), "ndays": g["revenue"].count()})
    full = 7 if freq.startswith("W") else out.index.days_in_month
    out = out[out["ndays"] == full].drop(columns="ndays")  # whole periods only
    out["holidays"] = holidays_per(out.index, freq)
    return out


def tlc_monthly() -> pd.DataFrame:
    t = pd.read_csv(fetch(TLC_URL, "r2h_tlc_monthly.csv"), thousands=",", na_values=["-"])
    t["month"] = pd.to_datetime(t["Month/Year"]) + pd.offsets.MonthEnd(0)
    y = t[t["License Class"] == "Yellow"].set_index("month").sort_index()
    h = t[t["License Class"] == "FHV - High Volume"].set_index("month").sort_index()
    return pd.DataFrame({
        "yellow_trips": y["Trips Per Day"], "yellow_fare": y["Farebox Per Day"], "hvfhv_trips": h["Trips Per Day"],
    })


# ---------------------------------------------------------------- designs
def harmonics(idx: pd.DatetimeIndex, k: int) -> pd.DataFrame:
    doy = idx.dayofyear.to_numpy()
    cols = {}
    for j in range(1, k + 1):
        cols[f"s{j}"] = np.sin(2 * np.pi * j * doy / 365.25)
        cols[f"c{j}"] = np.cos(2 * np.pi * j * doy / 365.25)
    return pd.DataFrame(cols, index=idx)


def base_design(df: pd.DataFrame, horizon: str, long: bool) -> pd.DataFrame:
    idx = df.index
    X = pd.DataFrame({"const": 1.0, "trend": (idx - idx[0]).days / 365.25}, index=idx)
    if horizon == "D":
        X = X.join(pd.get_dummies(idx.day_of_week, prefix="dow", drop_first=True).set_index(idx).astype(float))
        X["holiday"] = df["is_holiday"].astype(float)
        X = X.join(harmonics(idx, 3))
    elif horizon == "W":
        X["holidays"] = df["holidays"]
        X = X.join(harmonics(idx, 3))
    elif long:  # long monthly: month dummies + year fixed effects + weekend-day count
        X = X.drop(columns="trend")
        X = X.join(pd.get_dummies(idx.month, prefix="m", drop_first=True).set_index(idx).astype(float))
        X = X.join(pd.get_dummies(idx.year, prefix="y", drop_first=True).set_index(idx).astype(float))
        X["weekend_days"] = [((pd.date_range(m - pd.offsets.MonthBegin(1), m).day_of_week >= 5).sum()) for m in idx]
    else:  # short monthly (<= 33 months): one annual harmonic + trend + holiday count
        X["holidays"] = df["holidays"]
        X = X.join(harmonics(idx, 1))
    return X.loc[:, X.std() > 0].assign(const=1.0) if "const" in X else X


HAC_LAGS = {"D": 7, "W": 4, "M": 3}


def fit(y: pd.Series, X: pd.DataFrame, horizon: str):
    return sm.OLS(y.astype(float), X.astype(float)).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS[horizon]})


def cell(name, horizon, long, unit, df, pred, train, hold):
    rows = {}
    for part, mask in (("train", train), ("holdout", hold)):
        d = df[mask]
        X = base_design(d, horizon, long)
        X[pred] = d[pred]
        n_event = int((d[pred] > 0).sum())
        if X.shape[0] <= X.shape[1] + 2 or d[pred].std() == 0:
            rows[part] = dict(b=np.nan, lo=np.nan, hi=np.nan, p=np.nan, n=len(d), n_event=n_event, df=0,
                              lo_t=np.nan, hi_t=np.nan)
            continue
        r = fit(d["y"], X, horizon)
        b, se = r.params[pred], r.bse[pred]
        # small-sample check: HC3 errors with a t(df_resid) critical value instead of HAC + normal
        r3 = sm.OLS(d["y"].astype(float), X.astype(float)).fit(cov_type="HC3")
        tcrit = stats.t.ppf(0.95, r.df_resid)
        rows[part] = dict(b=b, lo=b - Z * se, hi=b + Z * se, p=r.pvalues[pred], n=len(d), n_event=n_event,
                          df=int(r.df_resid), lo_t=b - tcrit * r3.bse[pred], hi_t=b + tcrit * r3.bse[pred])
    return dict(series=name, horizon=horizon, pred=pred, unit=unit,
                **{f"tr_{k}": v for k, v in rows["train"].items()},
                **{f"ho_{k}": v for k, v in rows["holdout"].items()})


def variance_share(df, horizon, long, train, hold, preds):
    """In-sample partial R2 of the weather block on the full sample, and out-of-sample R2 gain on holdout
    (train-fitted with vs without the block)."""
    Xb = base_design(df, horizon, long)
    Xf = Xb.join(df[preds])
    rb, rf = fit(df["y"], Xb, horizon), fit(df["y"], Xf, horizon)
    partial = 1 - rf.ssr / rb.ssr
    share_total = (rb.ssr - rf.ssr) / ((df["y"] - df["y"].mean()) ** 2).sum()
    oos = np.nan
    tr, ho = df[train], df[hold]
    Xbt, Xft = base_design(tr, horizon, long), base_design(tr, horizon, long).join(tr[preds])
    if long:
        oos = np.nan  # year FE cannot be projected into unseen years
    elif len(tr) > Xft.shape[1] + 2:
        Xbh = base_design(ho, horizon, long).reindex(columns=Xbt.columns, fill_value=0.0)
        Xfh = Xbh.join(ho[preds])
        eb = ho["y"] - Xbh @ fit(tr["y"], Xbt, horizon).params
        ef = ho["y"] - Xfh[Xft.columns] @ fit(tr["y"], Xft, horizon).params
        oos = 1 - (ef ** 2).sum() / (eb ** 2).sum()
    return dict(n=len(df), partial_r2=partial, share_of_total=share_total, oos_gain=oos)


def basis(wm: pd.DataFrame) -> pd.DataFrame:
    """Monthly agreement of the fitted weather totals with the flags a Kalshi monthly contract settles on."""
    w = wm[wm.index >= "2010-01-01"]
    out = []
    for k in (2, 3, 4, 5, 6):
        flag = (w["precip"] > k).astype(float)
        out.append(dict(contract=f"KXRAINNYCM > {k} in", freq=flag.mean(),
                        r2_rainy_days=w["rainy_days"].corr(flag) ** 2, r2_precip=w["precip"].corr(flag) ** 2))
    winter = w[w.index.month.isin([12, 1, 2, 3])]
    for k in (2, 4, 6):
        flag = (winter["snow"] > k).astype(float)
        out.append(dict(contract=f"KXNYCSNOWM > {k} in (Dec-Mar)", freq=flag.mean(),
                        r2_rainy_days=np.nan, r2_precip=winter["snow"].corr(flag) ** 2))
    return pd.DataFrame(out)


def hedge_backtest(df, tr, ho, wm, strike=4.0) -> dict:
    """Taxi monthly: revenue rises with rain, so a dry month hurts. Buy NO on KXRAINNYCM '> strike in' at
    (1 - p_hat) + $0.02 + 0.07 p (1 - p), p_hat = 2010..train-end GHCN frequency, sized |beta| contracts with
    beta from the train fit on the settlement flag itself. Holdout months only."""
    flag = f"precip_gt_{strike:g}"
    d = df[tr]
    X = base_design(d, "M", False)
    X[flag] = d[flag]
    beta = fit(d["y"], X, "M").params[flag]
    hist = wm[(wm.index >= "2010-01-01") & (wm.index < df[ho].index[0])]
    p_yes = float((hist["precip"] > strike).mean())
    price = (1 - p_yes) + 0.02
    cost = price + 0.07 * price * (1 - price)
    h = df[ho]
    pays = (h[flag] == 0).astype(float)  # NO pays $1 when the month is not above the strike
    pnl = abs(beta) * (pays - cost)
    Xh = base_design(h, "M", False).reindex(columns=X.columns.drop(flag), fill_value=0.0)
    base = Xh @ fit(d["y"], X.drop(columns=flag), "M").params
    resid, resid_h = h["y"] - base, h["y"] - base + pnl
    return dict(strike=strike, beta=beta, p_yes=p_yes, cost=cost, n_hold=len(h), contracts=abs(beta),
                hedge_pnl_total=pnl.sum(), sd_raw=h["y"].std(), sd_raw_hedged=(h["y"] + pnl).std(),
                sd_resid=resid.std(), sd_resid_hedged=resid_h.std(),
                worst_resid=resid.min(), worst_resid_hedged=resid_h.min())


# ---------------------------------------------------------------- main
def main() -> None:
    wd = station_daily()
    p = wd.loc["2026-09"]["precip"].sum()
    print(f"basis check: GHCN Central Park Sep 2026 precip = {p:.2f} in (KXRAINNYCM-26SEP expiration value 5.31)")

    series: list[tuple] = []  # (name, horizon, long, unit, df, train mask, holdout mask)

    for name, daily in (("taxi_zone", taxi_daily()), ("bar", bar_daily())):
        # taxi: the shared split (holdout from 2025-10-01); the bar runs from 2024-01, so split near its middle
        cut = pd.Timestamp(config.HOLDOUT_START) if name == "taxi_zone" else pd.Timestamp("2025-06-01")
        if name == "taxi_zone":
            d = daily.join(wd[DAILY_PREDS], how="inner").rename(columns={"revenue": "y"})
            series.append((name, "D", False, "$/day", d, d.index < cut, d.index >= cut))
        for h, freq in (("W", "W-SUN"), ("M", "ME")):
            pdf = to_period(daily, freq).join(agg_weather(wd, freq), how="inner").rename(columns={"revenue": "y"})
            unit = "$/week" if h == "W" else "$/month"
            start = pdf.index - (pd.Timedelta(days=6) if h == "W" else pd.offsets.MonthBegin(1))
            series.append((name, h, False, unit, pdf, start < cut, start >= cut))

    tlc = tlc_monthly()
    wm = agg_weather(wd, "ME")
    for col in ("yellow_trips", "yellow_fare", "hvfhv_trips"):
        s = tlc[[col]].dropna().rename(columns={col: "y"})
        s["y"] = np.log(s["y"])
        s = s.join(wm, how="inner")
        s = s[(s.index < COVID[0]) | (s.index > COVID[1])]
        if col == "hvfhv_trips":
            cut = pd.Timestamp("2024-07-01")  # 2015-2019 + 2022-07..2024-06 train, 2024-07.. holdout
        else:
            cut = pd.Timestamp("2018-01-01")  # 2010-2017 train, 2018-2019 + 2022-07..2026-07 holdout
        series.append((col, "M", True, "log pts", s, s.index < cut, s.index >= cut))

    cells, shares = [], []
    for name, h, long, unit, df, tr, ho in series:
        preds = DAILY_PREDS if h == "D" else [c for c in df.columns if c in BLOCK or c.startswith(("precip_gt", "snow_gt"))]
        for pred in preds:
            cells.append(cell(name, h, long, unit, df, pred, tr, ho))
        block = DAILY_PREDS if h == "D" else BLOCK
        shares.append(dict(series=name, horizon=h, n_train=int(tr.sum()), n_hold=int(ho.sum()),
                           sd_y=df["y"].std(), **variance_share(df, h, long, tr, ho, block)))

    res = pd.DataFrame(cells)
    ok = res["tr_p"].notna()
    res.loc[ok, "q_bh"] = multipletests(res.loc[ok, "tr_p"], alpha=0.10, method="fdr_bh")[1]
    res["train_ok"] = (np.sign(res.tr_lo) == np.sign(res.tr_hi)) & (res.tr_n_event >= 10)
    res["hold_ok"] = (np.sign(res.ho_lo) == np.sign(res.ho_hi)) & (np.sign(res.ho_b) == np.sign(res.tr_b))
    res["bh_ok"] = res["q_bh"] < 0.10
    res["verdict"] = np.where(res.train_ok & res.hold_ok & res.bh_ok, "FOUND", "not found")
    # robustness, not a gate: does the FOUND cell keep both CIs off 0 under HC3 + t(df)?
    res["small_n_ok"] = ((np.sign(res.tr_lo_t) == np.sign(res.tr_hi_t)) & (np.sign(res.ho_lo_t) == np.sign(res.ho_hi_t)))

    pd.set_option("display.width", 250, "display.max_rows", 200, "display.max_columns", 30)
    print(f"\n{len(res)} tests ({int(ok.sum())} with a train p-value); BH 10% over all of them")
    show = res.copy()
    for c in ("tr_b", "tr_lo", "tr_hi", "ho_b", "ho_lo", "ho_hi"):
        show[c] = show.apply(lambda r: f"{100 * r[c]:+.2f}%" if r["unit"] == "log pts" else f"{r[c]:+,.0f}", axis=1)
    print(show[["series", "horizon", "pred", "tr_n", "tr_n_event", "tr_b", "tr_lo", "tr_hi", "tr_p", "q_bh",
                "ho_n", "ho_b", "ho_lo", "ho_hi", "verdict"]].to_string(index=False, float_format="%.3f"))
    found = res[res.verdict == "FOUND"]
    print("\nFOUND cells, residual df and the HC3 + t(df) 90% CI")
    print(found[["series", "horizon", "pred", "tr_df", "tr_lo_t", "tr_hi_t", "ho_df", "ho_lo_t", "ho_hi_t",
                 "small_n_ok"]].to_string(index=False, float_format="%.4g"))
    print("\nvariance share of the weather block (rainy days, precip, hot days, CDD, snow)")
    print(pd.DataFrame(shares).to_string(index=False, float_format="%.3f"))
    print("\nbasis: R2 of monthly totals vs the settlement flag (GHCN Central Park, 2010-01 on)")
    print(basis(wm).to_string(index=False, float_format="%.3f"))
    name, h, long, unit, df, tr, ho = next(x for x in series if x[0] == "taxi_zone" and x[1] == "M")
    print("\nhedge backtest, taxi zone monthly, holdout months")
    for k, v in hedge_backtest(df, tr, ho, wm).items():
        print(f"  {k:>20}: {v:,.3f}")
    res.to_csv(CACHE / "r2h_results.csv", index=False)


if __name__ == "__main__":
    main()
