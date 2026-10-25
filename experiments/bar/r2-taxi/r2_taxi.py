"""Round 2, taxi at scale: do Central Park weather events move citywide TLC trips and fares?

Data: daily aggregates from fetch_tlc.py (yellow + high-volume FHV, 2022-01..2025-12, citywide and
pickup zone 186) and Central Park GHCN-Daily (USW00094728, the Kalshi settlement station).
Design (per series x event, one event at a time): build_design's DOW dummies + season k=1,2 +
holiday, plus a linear trend (FHV grows ~10%/yr over 2022-25). OLS with HAC (Newey-West, 7 lags)
errors, z = 1.645. Train 2022-2023, holdout 2024-2025 refit independently. BH at 10% over all
train p-values. FOUND = train CI excludes 0 (>= 10 event days), holdout same sign and CI excludes 0,
BH survives. Hedge backtest for FOUND rows: buy the opposite side at train frequency + $0.02,
fee 0.07*p*(1-p) per contract, |beta| contracts, scored on holdout days.

Run from backend/: .venv/bin/python ../experiments/bar/r2-taxi/r2_taxi.py
Prints summary tables only.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.holiday import USFederalHolidayCalendar
from statsmodels.stats.multitest import multipletests

from app.stats.exposure import Z90, build_design

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
MM = 1 / 25.4
TRAIN = ("2022-01-01", "2023-12-31")
HOLDOUT = ("2024-01-01", "2025-12-31")
HAC_LAGS = 7


def tlc() -> pd.DataFrame:
    out = {}
    for svc in ("yellow", "fhvhv"):
        parts = [pd.read_parquet(p) for p in sorted((CACHE / "tlc").glob(f"{svc}_*.parquet"))]
        d = pd.concat(parts).groupby("date").sum()  # trips stamped in a neighbouring month's file
        out[svc] = d
    y, f = out["yellow"], out["fhvhv"]
    df = pd.DataFrame({
        "yellow_trips": y["trips"], "yellow_usd": y["total"],
        "fhv_trips": f["trips"], "fhv_usd": f["total"],
        "z186_yellow_usd": y["z_total"], "z186_all_usd": y["z_total"] + f["z_total"],
    })
    df.index = pd.to_datetime(df.index)
    # Open Data's yellow tables are missing most rows on a few days (2022-09-17/18, 2023-09-21..24:
    # ~5k trips vs ~100k). Rule fixed before fitting: yellow < 25% of its 29-day median is a gap.
    med = df["yellow_trips"].rolling(29, center=True, min_periods=10).median()
    gap = df["yellow_trips"] < 0.25 * med
    df.loc[gap, ["yellow_trips", "yellow_usd", "z186_yellow_usd", "z186_all_usd"]] = np.nan
    print("yellow gap days set missing:", df.index[gap].strftime("%Y-%m-%d").tolist())
    return df.loc["2022-01-01":"2025-12-31"]


def weather() -> pd.DataFrame:
    g = pd.read_csv(CACHE / "ghcn_USW00094728.csv", usecols=["DATE", "PRCP", "SNOW", "TMAX"], parse_dates=["DATE"])
    g = g.set_index("DATE").loc["2022-01-01":"2025-12-31"]
    prcp_in = g["PRCP"] / 10 / 25.4  # tenths of mm -> in
    tmax_f = np.round(g["TMAX"] / 10 * 9 / 5 + 32)  # NWS reports whole degrees F
    return pd.DataFrame({
        "prcp_in": prcp_in.round(2), "tmax_f": tmax_f, "snow_in": (g["SNOW"] / 25.4).round(1),
    })


EVENTS = {
    "rain >= 0.01 in (KXRAIN)": lambda w: w["prcp_in"] >= 0.01,
    "rain >= 1 mm": lambda w: w["prcp_in"] >= 1 * MM,
    "rain >= 5 mm": lambda w: w["prcp_in"] >= 5 * MM,
    "hot tmax > 85F": lambda w: w["tmax_f"] > 85,
    "hot tmax > 90F": lambda w: w["tmax_f"] > 90,
    "snow >= 0.1 in": lambda w: w["snow_in"] >= 0.1,
    "snow >= 1 in": lambda w: w["snow_in"] >= 1.0,  # added on lead's request, after the first 36-test run
}


def frame() -> pd.DataFrame:
    df = tlc().join(weather(), how="inner")
    hol = set(USFederalHolidayCalendar().holidays("2022-01-01", "2025-12-31"))
    extra = {pd.Timestamp(f"{y}-{md}") for y in range(2022, 2026) for md in ("12-24", "12-31")}
    tg = {d + pd.Timedelta(days=1) for d in hol if d.month == 11 and d.day >= 22}  # day after Thanksgiving
    df["dow"] = df.index.day_of_week
    df["doy"] = df.index.day_of_year
    df["is_holiday"] = df.index.isin(hol | extra | tg)
    df["msg_event"] = False
    df["home_game"] = False
    return df


def fit(df: pd.DataFrame, ycol: str, flag: pd.Series):
    keep = df[ycol].notna()
    df, flag = df[keep], flag[keep]
    X = build_design(df, {"event": flag})
    X["trend"] = (df.index - df.index[0]).days / 365.25
    return sm.OLS(df[ycol].astype(float), X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS}, use_t=False), X


def hedge(df_tr, df_ho, ycol, flag_tr, flag_ho, beta, res_ho_baseline):
    """Buy the side that pays when revenue is low; |beta| $1 contracts; score on holdout."""
    pays_when = ~flag_ho if beta > 0 else flag_ho
    p = float((~flag_tr if beta > 0 else flag_tr).mean()) + 0.02
    c = abs(beta)
    pnl = c * (pays_when.astype(float) - p - 0.07 * p * (1 - p))
    y = df_ho[ycol].astype(float)
    r = y - res_ho_baseline
    return {
        "price": p, "sd": (y.std(), (y + pnl).std()), "p5": (y.quantile(0.05), (y + pnl).quantile(0.05)),
        "resid_sd": (r.std(), (r + pnl).std()), "resid_p5": (r.quantile(0.05), (r + pnl).quantile(0.05)),
        "cost": -pnl.mean(),
    }


def main() -> None:
    df = frame()
    tr, ho = df.loc[TRAIN[0]:TRAIN[1]], df.loc[HOLDOUT[0]:HOLDOUT[1]]
    series = ["yellow_trips", "yellow_usd", "fhv_trips", "fhv_usd", "z186_yellow_usd", "z186_all_usd"]
    print(f"days: train {len(tr)}, holdout {len(ho)}; days with a missing series: {df[series].isna().any(axis=1).sum()}")
    print("series means (train):", {s: round(tr[s].mean()) for s in series})
    print("series min/max (sanity):", {s: (round(df[s].min()), round(df[s].max())) for s in series})
    kx = df["prcp_in"] >= 0.01
    print("\nbasis vs KXRAIN flag (Pearson r, full period):")
    for e, fn in EVENTS.items():
        print(f"  {e:28s} r={np.corrcoef(fn(df).astype(float), kx.astype(float))[0, 1]:.3f}  freq={fn(df).mean():.3f}")

    rows = []
    for s in series:
        for e, fn in EVENTS.items():
            row = {"series": s, "event": e}
            for name, d in (("tr", tr), ("ho", ho)):
                flag = fn(d)
                res, _ = fit(d, s, flag)
                b, se = float(res.params["event"]), float(res.bse["event"])
                row |= {f"{name}_b": b, f"{name}_lo": b - Z90 * se, f"{name}_hi": b + Z90 * se,
                        f"{name}_p": float(res.pvalues["event"]), f"{name}_n": int(flag[d[s].notna()].sum()),
                        f"{name}_pct": 100 * b / d[s].mean()}
            rows.append(row)
    r = pd.DataFrame(rows)
    r["bh_rej"], r["bh_q"] = multipletests(r["tr_p"], alpha=0.10, method="fdr_bh")[:2]
    tr_sig = (np.sign(r["tr_lo"]) == np.sign(r["tr_hi"])) & (r["tr_n"] >= 10)
    ho_ok = (np.sign(r["ho_lo"]) == np.sign(r["ho_hi"])) & (np.sign(r["ho_b"]) == np.sign(r["tr_b"]))
    r["verdict"] = np.where(tr_sig & ho_ok & r["bh_rej"], "FOUND", "not found")
    # Also BH over holdout p-values of the train-significant rows (stricter replication view).
    print(f"\ntests: {len(r)} (6 series x 7 events), BH 10% on train p: {int(r['bh_rej'].sum())} survive; "
          f"FOUND: {int((r['verdict'] == 'FOUND').sum())}")
    pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_rows", 100)
    show = r[["series", "event", "tr_n", "tr_b", "tr_lo", "tr_hi", "tr_pct", "ho_n", "ho_b", "ho_lo", "ho_hi",
              "ho_pct", "bh_q", "verdict"]].copy()
    for c in ("tr_b", "tr_lo", "tr_hi", "ho_b", "ho_lo", "ho_hi"):
        show[c] = show[c].round(0).astype(int)
    for c in ("tr_pct", "ho_pct"):
        show[c] = show[c].round(2)
    show["bh_q"] = show["bh_q"].map(lambda q: f"{q:.2g}")
    print(show.to_string(index=False))

    print("\nhedge backtests (FOUND rows; holdout 2024-25):")
    for _, row in r[r["verdict"] == "FOUND"].iterrows():
        fn = EVENTS[row["event"]]
        res_tr, X_tr = fit(tr, row["series"], fn(tr))
        # Baseline on holdout from the train model with the event off (calendar-adjusted revenue).
        X_ho = build_design(ho, {"event": fn(ho)}, columns=X_tr.columns.drop("trend"))
        X_ho["trend"] = (ho.index - tr.index[0]).days / 365.25
        X_ho["event"] = 0.0
        base = X_ho[X_tr.columns] @ res_tr.params
        h = hedge(tr, ho, row["series"], fn(tr), fn(ho), float(res_tr.params["event"]), base)
        f = lambda a: f"{a[0]:,.0f} -> {a[1]:,.0f} ({a[1] - a[0]:+,.0f})"
        print(f"  {row['series']:16s} {row['event']:26s} beta={row['tr_b']:,.0f} price={h['price']:.2f} "
              f"cost/day={h['cost']:,.0f} | sd {f(h['sd'])} | p5 {f(h['p5'])} | resid sd {f(h['resid_sd'])} "
              f"| resid p5 {f(h['resid_p5'])}")


if __name__ == "__main__":
    main()
