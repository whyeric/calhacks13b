"""R4-natural: natural hedges. Do NYC transport businesses move OPPOSITELY on the same weather event?

Run from backend/: .venv/bin/python ../experiments/bar/r4-natural/natural.py

Data (all public, cached in the scratchpad r2-cache/ by earlier experiments):
- MTA daily ridership by mode, data.ny.gov sayj-mze2 (r2-mta: mta_sayj.parquet). $ = riders x $2.90.
- TLC daily trips and $ citywide for yellow (total_amount) and HVFHV Uber/Lyft (base fare + tips),
  aggregated server-side by r2-taxi/fetch_tlc.py (r2-cache/tlc/<svc>_<YYYY-MM>.parquet).
- Citi Bike Jersey City daily trips, 2023-2025 only (r2-citibike: citibike_jc_daily.parquet). $ = trips x $4.
- Central Park NOAA GHCN-D USW00094728 PRCP/TMAX/SNOW in inches (r2-mta: noaa_centralpark.json),
  the station and daily record KXRAIN / KXHIGHNY settle on, so every flag here IS a settlement flag.

Per-event effect: log(y) on const + DOW + year-month FE + holiday + Dec 24-Jan 1 week + one event flag,
HAC (7 lags), z = 1.645. Train 2022-23, holdout 2024-25, fitted independently. BH at 10% over all
series x event tests, separately on train and holdout p-values. FOUND = the shared brief's criteria.
Pair = two FOUND effects of opposite sign on the same event.

Portfolio (out of sample): fit the calendar-only model in $ levels on the holdout; its residual still
contains the weather effect. Report corr of residuals, corr of the weather part (train joint-weather
betas applied to holdout flags), and the CV (residual SD / mean $) of A, B and A+B. Hedge comparison:
A alone, A + h*B with h = -beta_A$/beta_B$ sized on train (owning h of business B), and A + a Kalshi
rain contract (buy the side that pays when A is hurt, at train freq + $0.02 + fee 0.07p(1-p),
|beta_A$| contracts), all evaluated on the holdout.
"""

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.holiday import USFederalHolidayCalendar
from statsmodels.stats.multitest import multipletests

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from app.stats.exposure import Z90  # noqa: E402

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
OUT = Path(__file__).resolve().parent
START, END = date(2022, 1, 1), date(2025, 12, 31)
TRAIN = (date(2022, 1, 1), date(2023, 12, 31))
HOLD = (date(2024, 1, 1), date(2025, 12, 31))
HAC_LAGS = 7
FARE = 2.90
BIKE_USD = 4.0  # rough revenue per Citi Bike trip, only to put it on a $ scale
# series -> ($ column used for the portfolio, label)
SERIES = {
    "subway": "subway_usd", "bus": "bus_usd",
    "yellow_trips": "yellow_usd", "yellow_usd": "yellow_usd",
    "fhv_trips": "fhv_usd", "fhv_usd": "fhv_usd",
    "bike_jc": "bike_usd",
}
USD = ["subway_usd", "bus_usd", "yellow_usd", "fhv_usd", "bike_usd"]


def events(d: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "rain>=0.01in": d["PRCP"] >= 0.01,  # KXRAIN settlement
        "rain>=5mm": d["PRCP"] >= 0.20,
        "snow>=0.1in": d["SNOW"] >= 0.1,
        "cold<32F": d["TMAX"] < 32,
        "hot>90F": d["TMAX"] > 90,  # KXHIGHNY strict >
    }


def tlc(svc: str) -> pd.DataFrame:
    files = sorted((CACHE / "tlc").glob(f"{svc}_*.parquet"))
    d = pd.concat([pd.read_parquet(f) for f in files])
    d["date"] = pd.to_datetime(d["date"]).dt.date
    d = d[(d["date"] >= START) & (d["date"] <= END)]
    return d.groupby("date")[["trips", "total"]].sum()


def frame() -> pd.DataFrame:
    m = pd.read_parquet(CACHE / "mta_sayj.parquet")
    m["date"] = pd.to_datetime(m["date"]).dt.date
    m["count"] = pd.to_numeric(m["count"])
    m = m.pivot_table(index="date", columns="mode", values="count")[["Subway", "Bus"]]
    df = pd.DataFrame({"subway": m["Subway"], "bus": m["Bus"]})
    y, f = tlc("yellow"), tlc("fhvhv")
    df = df.join(pd.DataFrame({"yellow_trips": y["trips"], "yellow_usd": y["total"]}), how="left")
    df = df.join(pd.DataFrame({"fhv_trips": f["trips"], "fhv_usd": f["total"]}), how="left")
    b = pd.read_parquet(CACHE / "citibike_jc_daily.parquet")["trips"]
    b.index = pd.to_datetime(b.index).date
    df = df.join(b.rename("bike_jc"), how="left")
    df["subway_usd"], df["bus_usd"], df["bike_usd"] = df["subway"] * FARE, df["bus"] * FARE, df["bike_jc"] * BIKE_USD

    w = pd.DataFrame(json.loads((CACHE / "noaa_centralpark.json").read_text()))
    w["date"] = pd.to_datetime(w["DATE"]).dt.date
    for c in ("PRCP", "TMAX", "SNOW"):
        w[c] = pd.to_numeric(w[c].astype(str).str.strip().replace({"T": "0"}), errors="coerce")
    df = df.join(w.set_index("date")[["PRCP", "TMAX", "SNOW"]], how="inner")
    df = df[(df.index >= START) & (df.index <= END)].reset_index().rename(columns={"index": "date"})

    fed = USFederalHolidayCalendar().holidays(str(START), str(END))
    hol = {d.date() for d in fed}
    for yr in range(START.year, END.year + 1):
        thanks = [d for d in fed if d.year == yr and d.month == 11 and d.day >= 22]
        hol |= {(t + pd.Timedelta(days=1)).date() for t in thanks} | {date(yr, 12, 24), date(yr, 12, 31)}
    ts = pd.to_datetime(df["date"])
    df["dow"], df["ym"] = ts.dt.day_of_week, ts.dt.strftime("%Y-%m")
    df["holiday"] = df["date"].isin(hol).astype(float)
    df["hol_week"] = (((ts.dt.month == 12) & (ts.dt.day >= 24)) | ((ts.dt.month == 1) & (ts.dt.day == 1))).astype(float)
    return df


def calendar(d: pd.DataFrame) -> pd.DataFrame:
    X = pd.get_dummies(d["dow"], prefix="dow", drop_first=True, dtype=float)
    X = X.join(pd.get_dummies(d["ym"], prefix="ym", drop_first=True, dtype=float))
    X.insert(0, "const", 1.0)
    X["holiday"], X["hol_week"] = d["holiday"], d["hol_week"]
    return X


def period(df: pd.DataFrame, p: tuple[date, date], col: str) -> pd.DataFrame:
    d = df[(df["date"] >= p[0]) & (df["date"] <= p[1])]
    return d[d[col].notna() & (d[col] > 0)].reset_index(drop=True)


def fit_event(d: pd.DataFrame, col: str, name: str):
    flag = events(d)[name].astype(float)
    if flag.sum() == 0:
        return None
    X = calendar(d)
    X[name] = flag
    res = sm.OLS(np.log(d[col].astype(float)), X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS}, use_t=False)
    return {"b": res.params[name], "se": res.bse[name], "p": res.pvalues[name], "n_ev": int(flag.sum()), "n": len(d)}


def effects(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col in SERIES:
        for name in events(df):
            a, h = fit_event(period(df, TRAIN, col), col, name), fit_event(period(df, HOLD, col), col, name)
            if a is None or h is None:
                continue
            rows.append({
                "series": col, "event": name,
                "tr_n": a["n"], "tr_nev": a["n_ev"], "tr_pct": 100 * a["b"],
                "tr_lo": 100 * (a["b"] - Z90 * a["se"]), "tr_hi": 100 * (a["b"] + Z90 * a["se"]), "tr_p": a["p"],
                "ho_n": h["n"], "ho_nev": h["n_ev"], "ho_pct": 100 * h["b"],
                "ho_lo": 100 * (h["b"] - Z90 * h["se"]), "ho_hi": 100 * (h["b"] + Z90 * h["se"]), "ho_p": h["p"],
            })
    t = pd.DataFrame(rows)
    t["tr_q"] = multipletests(t["tr_p"], method="fdr_bh")[1]
    t["ho_q"] = multipletests(t["ho_p"], method="fdr_bh")[1]
    sig = lambda lo, hi: (lo > 0) | (hi < 0)  # noqa: E731
    t["found"] = (
        sig(t["tr_lo"], t["tr_hi"]) & (t["tr_nev"] >= 10) & sig(t["ho_lo"], t["ho_hi"])
        & (np.sign(t["tr_pct"]) == np.sign(t["ho_pct"])) & (t["tr_q"] <= 0.10) & (t["ho_q"] <= 0.10)
    )
    return t


def pairs(t: pd.DataFrame) -> pd.DataFrame:
    f = t[t["found"]]
    rows = []
    for ev, g in f.groupby("event"):
        for _, a in g[g["tr_pct"] < 0].iterrows():
            for _, b in g[g["tr_pct"] > 0].iterrows():
                rows.append({"event": ev, "down": a["series"], "down_tr": a["tr_pct"], "down_ho": a["ho_pct"],
                             "up": b["series"], "up_tr": b["tr_pct"], "up_ho": b["ho_pct"]})
    return pd.DataFrame(rows)


def weather_X(d: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({k: v.astype(float) for k, v in events(d).items()}, index=d.index)


def portfolio(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Holdout $ residuals (calendar-only, still containing weather) and OOS weather parts per $ series."""
    cols = [c for c in USD if c != "bike_usd"]  # bike has no 2022, keep the portfolio panel balanced
    ho = df[(df["date"] >= HOLD[0]) & (df["date"] <= HOLD[1])].dropna(subset=cols).reset_index(drop=True)
    tr = df[(df["date"] >= TRAIN[0]) & (df["date"] <= TRAIN[1])].dropna(subset=cols).reset_index(drop=True)
    resid, wpart, beta = {}, {}, {}
    for c in cols:
        Xh = calendar(ho)
        cal = sm.OLS(ho[c].astype(float), Xh).fit()
        resid[c] = ho[c] - cal.fittedvalues
        Xt = calendar(tr).join(weather_X(tr))
        bt = sm.OLS(np.log(tr[c].astype(float)), Xt).fit().params[list(weather_X(tr).columns)]
        wpart[c] = cal.fittedvalues * (np.exp(weather_X(ho) @ bt) - 1)
        wpart[c] -= wpart[c].mean()
        beta[c] = bt
    return pd.DataFrame(resid).assign(date=ho["date"]), pd.DataFrame(wpart), pd.DataFrame(beta), ho, tr


def hedge(df: pd.DataFrame, a: str, b: str, ev: str = "rain>=0.01in") -> dict:
    """Holdout: A alone vs A + h*B (natural) vs A + Kalshi `ev` contract, all sized on train."""
    resid, _, _, ho, tr = portfolio(df)
    fa, fb = fit_event(period(df, TRAIN, a), a, ev), fit_event(period(df, TRAIN, b), b, ev)
    ba = (np.exp(fa["b"]) - 1) * tr[a].mean()
    bb = (np.exp(fb["b"]) - 1) * tr[b].mean()
    h = -ba / bb
    p_ev = float(events(tr)[ev].mean())
    pays_on_event = ba < 0
    p = (p_ev if pays_on_event else 1 - p_ev) + 0.02
    price = p + 0.07 * p * (1 - p)
    flag = events(ho)[ev].astype(float).to_numpy()
    payoff = (flag if pays_on_event else 1 - flag) - price
    ra, rb = resid[a].to_numpy(), resid[b].to_numpy()
    out = {"A": a, "B": b, "beta_A$": ba, "beta_B$": bb, "h": h, "price": price}
    for k, s in (("alone", ra), ("natural", ra + h * rb), ("kalshi", ra + abs(ba) * payoff)):
        out[f"sd_{k}"] = s.std()
        out[f"p5_{k}"] = np.percentile(s, 5)
        out[f"evday_mean_{k}"] = s[flag == 1].mean()
        out[f"mean_{k}"] = s.mean()
    out["mean_rev_A"] = ho[a].mean()
    out["mean_rev_B_scaled"] = h * ho[b].mean()
    return out


def main() -> None:
    df = frame()
    cov = {c: (int(period(df, TRAIN, c).shape[0]), int(period(df, HOLD, c).shape[0])) for c in SERIES}
    print("days (train, holdout) per series:", cov)
    t = effects(df)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    print(f"\ntests: {len(t)} (series {len(SERIES)} x events {len(events(df))})")
    cols = ["series", "event", "tr_nev", "tr_pct", "tr_lo", "tr_hi", "tr_q", "ho_nev", "ho_pct", "ho_lo", "ho_hi", "ho_q", "found"]
    print(t[cols].round(3).to_string(index=False))
    t.to_csv(OUT / "effects.csv", index=False)

    pr = pairs(t)
    print("\nopposite-sign pairs, both FOUND on the same event:")
    print(pr.round(2).to_string(index=False) if len(pr) else "  none")
    pr.to_csv(OUT / "pairs.csv", index=False)

    resid, wpart, beta, ho, _ = portfolio(df)
    r = resid.drop(columns="date")
    print("\ntrain joint-weather betas (log points):")
    print(beta.round(4).to_string())
    print("\nholdout $ residual correlation (calendar-only model, includes weather):")
    print(r.corr().round(3).to_string())
    print("\nholdout correlation of the weather-driven part (train betas x holdout flags):")
    print(wpart.corr().round(3).to_string())
    print("\nholdout CV = SD(resid)/mean($), alone vs revenue-weighted pair (A+B):")
    rows = []
    for i, a in enumerate(r.columns):
        for b in r.columns[i + 1:]:
            cva, cvb = r[a].std() / ho[a].mean(), r[b].std() / ho[b].mean()
            cvp = (r[a] + r[b]).std() / (ho[a].mean() + ho[b].mean())
            wa, wb = wpart[a].std() / ho[a].mean(), wpart[b].std() / ho[b].mean()
            wp = (wpart[a] + wpart[b]).std() / (ho[a].mean() + ho[b].mean())
            rows.append({"A": a, "B": b, "corr_resid": r[a].corr(r[b]), "corr_weather": wpart[a].corr(wpart[b]),
                         "cv_A": cva, "cv_B": cvb, "cv_A+B": cvp, "cv_wA": wa, "cv_wB": wb, "cv_wA+B": wp,
                         "w_share_A": (wa / cva) ** 2, "w_var_red_vs_A": 1 - (wp / wa) ** 2,
                         "var_red_vs_A": 1 - (cvp / cva) ** 2})
    pf = pd.DataFrame(rows)
    print(pf.round(4).to_string(index=False))
    pf.to_csv(OUT / "portfolio.csv", index=False)

    print("\nhedge comparison on holdout (rain>=0.01in), $/day:")
    hs = pd.DataFrame([hedge(df, a, b) for a, b in (("subway_usd", "fhv_usd"), ("bus_usd", "fhv_usd"),
                                                    ("fhv_usd", "subway_usd"))])
    print(hs.round(3).to_string(index=False))
    hs.to_csv(OUT / "hedge.csv", index=False)


if __name__ == "__main__":
    main()
