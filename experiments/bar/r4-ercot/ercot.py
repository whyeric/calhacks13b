"""R4 ercot: do Texas grid load, wholesale prices and a small business's power bill rise on
Kalshi-settleable hot days?

Data (all public, cached in scratchpad r2-cache/ with prefix r4ercot_):
  ERCOT Native Load by weather zone, hourly, 2019-01..2026-09 (ercot.com/gridinfo/load/load_hist)
  ERCOT Historical DAM Load Zone and Hub Prices (NP4-180-ER, reportTypeId 13060), hourly
  NOAA GHCN-D TMAX for the four Kalshi Texas settlement stations (the CLI sites in the rules):
    AUS  Austin Bergstrom     USW00013904   KXHIGHAUS
    HOU  Houston Hobby        USW00012918   KXHIGHTHOU (CLIHOU)
    DFW  Dallas/Fort Worth    USW00003927   KXHIGHTDAL (CLIDFW)
    SAT  San Antonio          USW00012921   KXHIGHTSATX (CLISAT)

Pre-committed design (no holdout tuning):
  split    train 2019-01-01..2023-12-31 (5 y), holdout 2024-01-01..2026-09-30 (2.75 y), fit independently
  model    y ~ hot(tmax > K) + DOW + federal holiday + year-month FE, OLS, HAC 7 lags, z = 1.645
  events   K in {95, 100} F on the paired settlement station
  outcomes log daily load (MWh), log daily peak hour (MW), daily mean DAM price ($/MWh),
           and a demo business's daily power bill ($): a 1,370 kWh/day load shaped like its zone,
           (a) fixed retail rate $0.14/kWh, (b) indexed = hourly DAM hub price + $0.06/kWh adder
  pairs    system: ERCOT total load / HB_HUBAVG vs each station; local: COAST-HB_HOUSTON-HOU,
           NCENT-HB_NORTH-DFW, SCENT-LZ_AEN-AUS, SCENT-LZ_CPS-SAT
  BH 10% across every train test.
  variance share: partial R2 of the hot dummy given DOW + holiday + ym FE, and of a full tmax
           spline (knots 50/65/80/90/100 F) for "how much of within-month variance is weather".
  backtest (FOUND bill series): buy YES hot at the train frequency for that calendar month + $0.02
           + fee 0.07 p (1-p), size |beta| contracts of $1, holdout days; SD and 95th-pct bill.

Run from backend/:  PYTHONPATH=<scratchpad>/r4ercot_pylib .venv/bin/python ../experiments/bar/r4-ercot/ercot.py
(openpyxl is installed into the scratchpad, not the backend venv, to read ERCOT's xlsx files.)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.holiday import USFederalHolidayCalendar

HERE = Path(__file__).resolve().parent
CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
XDIR = CACHE / "r4ercot_x"
Z90 = 1.645
TRAIN = ("2019-01-01", "2023-12-31")
HOLD = ("2024-01-01", "2026-09-30")
STATIONS = {"AUS": "USW00013904", "HOU": "USW00012918", "DFW": "USW00003927", "SAT": "USW00012921"}
KWH_DAY = 1370.0
FIXED_RATE = 0.14
ADDER = 0.06


def _hour_index(dates: pd.Series, hours: pd.Series) -> pd.DataFrame:
    """ERCOT 'hour ending' 01:00..24:00 -> (date, he int)."""
    he = hours.astype(str).str.slice(0, 2).astype(int)
    return pd.DataFrame({"date": pd.to_datetime(dates, format="mixed").dt.normalize(), "he": he})


def load_hourly() -> pd.DataFrame:
    p = CACHE / "r4ercot_load.parquet"
    if p.exists():
        return pd.read_parquet(p)
    frames = []
    for f in sorted(XDIR.glob("Native_Load_*.xlsx")):
        x = pd.read_excel(f)
        x.columns = [str(c).strip().upper().replace(" ", "_") for c in x.columns]
        hcol = [c for c in x.columns if "HOUR" in c][0]
        s = x[hcol].astype(str).str.replace(" DST", "", regex=False).str.strip()
        parts = s.str.split(" ", n=1, expand=True)
        idx = _hour_index(parts[0], parts[1])
        x = x.rename(columns={"NORTH_C": "NCENT", "SOUTH_C": "SCENT", "FAR_WEST": "FWEST"})
        frames.append(pd.concat([idx, x[["COAST", "NCENT", "SCENT", "ERCOT"]].astype(float)], axis=1))
    df = pd.concat(frames).dropna()
    df = df.groupby(["date", "he"], as_index=False).mean()  # DST repeated hour
    df.to_parquet(p)
    return df


def dam_hourly() -> pd.DataFrame:
    p = CACHE / "r4ercot_dam.parquet"
    if p.exists():
        return pd.read_parquet(p)
    frames = []
    for f in sorted(XDIR.glob("*DAMLZHBSPP_*.xlsx")):
        for sh in pd.read_excel(f, sheet_name=None).values():
            sh = sh[sh["Settlement Point"].isin(["HB_HUBAVG", "HB_HOUSTON", "HB_NORTH", "LZ_AEN", "LZ_CPS"])]
            idx = _hour_index(sh["Delivery Date"], sh["Hour Ending"])
            frames.append(idx.assign(sp=sh["Settlement Point"].values, price=sh["Settlement Point Price"].values))
    df = pd.concat(frames).groupby(["date", "he", "sp"])["price"].mean().unstack("sp").reset_index()
    df.to_parquet(p)
    return df


def tmax() -> pd.DataFrame:
    g = pd.read_csv(CACHE / "r4ercot_ghcn.csv", parse_dates=["DATE"])
    inv = {v: k for k, v in STATIONS.items()}
    g["st"] = g["STATION"].map(inv)
    return g.pivot(index="DATE", columns="st", values="TMAX")


def daily() -> pd.DataFrame:
    L, P = load_hourly(), dam_hourly()
    h = L.merge(P, on=["date", "he"], how="inner")
    out = pd.DataFrame(index=sorted(h["date"].unique()))
    g = h.groupby("date")
    for z in ["ERCOT", "COAST", "NCENT", "SCENT"]:
        out[f"load_{z}"] = np.log(g[z].sum())
        out[f"peak_{z}"] = np.log(g[z].max())
    for sp in ["HB_HUBAVG", "HB_HOUSTON", "HB_NORTH", "LZ_AEN", "LZ_CPS"]:
        out[f"price_{sp}"] = g[sp].mean()
    # demo business: hourly kWh proportional to its zone's load, scaled so the train mean is KWH_DAY
    for z, sp in [("COAST", "HB_HOUSTON"), ("NCENT", "HB_NORTH"), ("SCENT", "LZ_AEN"), ("SCENT", "LZ_CPS")]:
        scale = KWH_DAY / h.loc[h["date"].between(*TRAIN)].groupby("date")[z].sum().mean()
        kwh = h[z] * scale
        bill_idx = (kwh * (h[sp] / 1000.0 + ADDER)).groupby(h["date"]).sum()
        out[f"billfix_{z}"] = (kwh.groupby(h["date"]).sum() * FIXED_RATE)
        out[f"billidx_{sp}"] = bill_idx
    out = out.join(tmax(), how="inner")
    out.index.name = "date"
    return out


def controls(idx: pd.DatetimeIndex) -> pd.DataFrame:
    hol = USFederalHolidayCalendar().holidays(idx.min(), idx.max())
    X = pd.get_dummies(pd.Series(idx.day_of_week, index=idx), prefix="dow", drop_first=True).astype(float)
    X["holiday"] = idx.isin(hol).astype(float)
    ym = pd.get_dummies(pd.Series(idx.strftime("%Y-%m"), index=idx), prefix="ym", drop_first=True).astype(float)
    X = X.join(ym)
    X.insert(0, "const", 1.0)
    return X


def spline(t: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({f"t{k}": np.maximum(t - k, 0) for k in [50, 65, 80, 90, 100]} | {"t": t}, index=t.index)


def ssr(y, X):
    return sm.OLS(y, X).fit().ssr


def fit(df: pd.DataFrame, y: str, st: str, K: float) -> dict:
    d = df[[y, st]].dropna()
    ev = (d[st] > K).astype(float).rename("hot")
    X0 = controls(d.index)
    X = X0.join(ev)
    res = sm.OLS(d[y], X).fit(cov_type="HAC", cov_kwds={"maxlags": 7})
    b, se = res.params["hot"], res.bse["hot"]
    s0 = ssr(d[y], X0)
    return {
        "beta": b, "lo": b - Z90 * se, "hi": b + Z90 * se, "p": res.pvalues["hot"], "n_ev": int(ev.sum()),
        "n": len(d), "pr2_hot": (s0 - res.ssr) / s0,
        "pr2_spline": (s0 - ssr(d[y], X0.join(spline(d[st])))) / s0,
        "r2_full": res.rsquared, "ymean": d[y].mean(),
    }


def bh(p: np.ndarray) -> np.ndarray:
    n = len(p)
    o = np.argsort(p)
    q = p[o] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(n)
    out[o] = np.minimum(q, 1)
    return out


def tests() -> list[tuple[str, str, str]]:
    """(outcome column, station, family label)."""
    t = []
    for st in STATIONS:
        t += [("load_ERCOT", st, "system"), ("peak_ERCOT", st, "system"), ("price_HB_HUBAVG", st, "system")]
    for z, sp, st in [("COAST", "HB_HOUSTON", "HOU"), ("NCENT", "HB_NORTH", "DFW"),
                      ("SCENT", "LZ_AEN", "AUS"), ("SCENT", "LZ_CPS", "SAT")]:
        t += [(f"load_{z}", st, "local"), (f"peak_{z}", st, "local"), (f"price_{sp}", st, "local"),
              (f"billfix_{z}", st, "bill"), (f"billidx_{sp}", st, "bill")]
    # SCENT load/peak/billfix appear for both AUS and SAT: keep both, they are distinct tests
    return t


def backtest(df: pd.DataFrame, y: str, st: str, K: float, beta: float) -> dict:
    tr = df.loc[TRAIN[0]:TRAIN[1]]
    ho = df.loc[HOLD[0]:HOLD[1], [y, st]].dropna()
    freq_m = (tr[st] > K).groupby(tr.index.month).mean()
    freq_all = (tr[st] > K).mean()
    out = {}
    for label, f in [("month", ho.index.month.map(freq_m).values), ("flat", np.full(len(ho), freq_all))]:
        p = np.clip(f + 0.02, 0.01, 0.99)
        cost = p + 0.07 * p * (1 - p)
        hot = (ho[st] > K).values.astype(float)
        n = abs(beta)
        sign = 1.0 if beta > 0 else -1.0  # bill rises on hot days -> buy YES hot
        pnl = n * (hot - cost) if sign > 0 else n * ((1 - hot) - (1 - p + 0.07 * p * (1 - p)))
        bill = ho[y].values
        net = bill - pnl
        # within-month view: what's left after the month's level, which no daily contract can hedge
        ym = ho.index.strftime("%Y-%m")
        dm = lambda v: v - pd.Series(v, index=ho.index).groupby(ym).transform("mean").values
        out[label] = {
            "sd_raw": (bill.std(), net.std()), "p95_raw": (np.percentile(bill, 95), np.percentile(net, 95)),
            "sd_within": (dm(bill).std(), dm(net).std()),
            "p95_within": (np.percentile(dm(bill), 95), np.percentile(dm(net), 95)),
            "mean": (bill.mean(), net.mean()), "contracts": n,
        }
    return out


def main() -> None:
    df = daily()
    print(f"daily rows {len(df)}  {df.index.min().date()}..{df.index.max().date()}")
    rows = []
    for y, st, fam in tests():
        for K in [95, 100]:
            r = {"outcome": y, "station": st, "family": fam, "K": K}
            for lab, (a, b) in [("tr", TRAIN), ("ho", HOLD)]:
                r |= {f"{k}_{lab}": v for k, v in fit(df.loc[a:b], y, st, K).items()}
            rows.append(r)
    R = pd.DataFrame(rows)
    R["q_tr"] = bh(R["p_tr"].values)
    R["found"] = (
        (R["n_ev_tr"] >= 10) & ((R["lo_tr"] > 0) | (R["hi_tr"] < 0)) & (R["q_tr"] <= 0.10)
        & (np.sign(R["beta_tr"]) == np.sign(R["beta_ho"])) & ((R["lo_ho"] > 0) | (R["hi_ho"] < 0))
    )
    R.to_csv(HERE / "results.csv", index=False)
    print(f"tests {len(R)}  FOUND {int(R['found'].sum())}")
    pct = lambda c: c.startswith(("load_", "peak_"))
    for _, r in R.iterrows():
        f = (lambda v: f"{100 * v:+.2f}%") if pct(r.outcome) else (lambda v: f"{v:+.2f}")
        print(f"{r.outcome:18s} {r.station} >{r.K} | tr {f(r.beta_tr)} [{f(r.lo_tr)},{f(r.hi_tr)}] n={r.n_ev_tr} "
              f"q={r.q_tr:.3g} pR2={r.pr2_hot_tr:.3f}/spl {r.pr2_spline_tr:.3f} | ho {f(r.beta_ho)} "
              f"[{f(r.lo_ho)},{f(r.hi_ho)}] n={r.n_ev_ho} pR2={r.pr2_hot_ho:.3f}/spl {r.pr2_spline_ho:.3f} "
              f"| mean tr {r.ymean_tr:.2f} | {'FOUND' if r.found else '-'}")
    print("\nbacktests (bill series, FOUND only), beta from train")
    bt = []
    for _, r in R[R.found & (R.family == "bill")].iterrows():
        res = backtest(df, r.outcome, r.station, r.K, r.beta_tr)
        for lab, v in res.items():
            bt.append({"outcome": r.outcome, "station": r.station, "K": r.K, "price": lab, "contracts": v["contracts"],
                       "sd_raw": v["sd_raw"][0], "sd_raw_h": v["sd_raw"][1],
                       "sd_within": v["sd_within"][0], "sd_within_h": v["sd_within"][1],
                       "p95_within": v["p95_within"][0], "p95_within_h": v["p95_within"][1],
                       "p95_raw": v["p95_raw"][0], "p95_raw_h": v["p95_raw"][1],
                       "mean": v["mean"][0], "mean_h": v["mean"][1]})
    print("\nper-year refits (descriptive, not part of the BH family): beta [90% CI] n_ev, >95 F")
    for y, st in [("load_NCENT", "DFW"), ("billfix_NCENT", "DFW"), ("price_HB_NORTH", "DFW"),
                  ("billfix_COAST", "HOU"), ("price_HB_HOUSTON", "HOU"), ("price_LZ_AEN", "AUS")]:
        cells = []
        for yr in range(2019, 2027):
            f = fit(df.loc[str(yr)], y, st, 95)
            m = 100 if pct(y) else 1
            cells.append(f"{yr} {m * f['beta']:+.1f} [{m * f['lo']:+.1f},{m * f['hi']:+.1f}] {f['n_ev']}")
        print(f"{y:16s} {st}: " + " | ".join(cells))
    B = pd.DataFrame(bt)
    B.to_csv(HERE / "backtest.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(B.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
