"""R3 tie-breaker: why does r2-pooling find no rain effect near MSG and r2-aggregate find -2%?

Three candidate causes, crossed in a 2x2x2 grid and fit on the same venues:
  weather source  Open-Meteo MSG grid (repo fixture, precipitation_sum >= 0.01 in) vs NOAA GHCN
                  USW00094728 Central Park (PRCP >= 0.01 in, the KXRAIN settlement record)
  seasonality     harmonics k = 1, 2 (exposure.build_design) vs year-month fixed effects
  split           P = r2-pooling dates (train 2024-10-01..2025-09-30, holdout 2025-10-01..2026-08-31)
                  A = r2-aggregate dates (train 2024-01-01..2025-03-31, holdout 2025-04-01..2026-09-27)
Each cell is fit on three units:
  panel358   log(visits+1) of the 358 r2-pooling venues, venue FE (within), SE = max(date-cluster, DK HAC 7)
  sum358     log(mean visits per venue) of the same 358 venues, HAC 7
  zip710     log(summed visits) of the r2-aggregate balanced MSG-ZIP basket (710 stores), HAC 7
Common controls in every cell: DOW, holiday, MSG home game (Knicks or Rangers), rain. z = 1.645.

Part 2 refits the round-1 single-business models (features.build + exposure.build_design / fit_ols,
HC3, train = first 365 days, holdout refit independently) with NOAA rain and tmax in place of the
repo's Open-Meteo MSG weather, for the bar (restaurant fixture) and taxi.

Run from backend/:  .venv/bin/python ../experiments/bar/r3-noaa/noaa.py
Writes only aggregate numbers (grid.csv, round1.csv). No venue ids, names or daily series.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np
import pandas as pd
import statsmodels.api as sm

from app import config
from app.data import dewey, features
from app.stats.exposure import Z90, build_design, event_flags, fit_ols

OUT = Path(__file__).resolve().parent
CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
D = date.fromisoformat
SPLITS = {
    "P": ((D("2024-10-01"), D("2025-09-30")), (D("2025-10-01"), D("2026-08-31"))),
    "A": ((D("2024-01-01"), D("2025-03-31")), (D("2025-04-01"), D("2026-09-27"))),
}
SOURCES = {"openmeteo": "rain_om", "noaa": "rain_noaa"}
SEASONS = ("harm", "ymfe")
Q_BH = 0.10


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AGG = load_module("r2_aggregate", ROOT / "experiments/bar/r2-aggregate/run.py")


# ------------------------------------------------------------------ inputs
GHCN_URL = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00094728.csv"
GHCN_FILE = CACHE / "r3noaa_ghcn.csv"  # own copy; the shared r2-cache GHCN files were overwritten by other agents


def noaa() -> pd.DataFrame:
    """GHCN-Daily USW00094728 in inches / F (access CSV is tenths of mm / tenths of C), 2024-01..2026-09, no gaps."""
    if not GHCN_FILE.exists():
        import httpx
        GHCN_FILE.write_bytes(httpx.get(GHCN_URL, timeout=120).raise_for_status().content)
    w = pd.read_csv(GHCN_FILE, usecols=["DATE", "PRCP", "TMAX"], low_memory=False)
    w["date"] = pd.to_datetime(w["DATE"]).dt.date
    w = w.set_index("date")
    out = pd.DataFrame({"PRCP": (w["PRCP"] / 254).round(2), "TMAX": (w["TMAX"] / 10 * 9 / 5 + 32).round(0)})
    out = out[(out.index >= D("2024-01-01")) & (out.index <= D("2026-09-30"))]
    assert len(out) == 1004 and out.notna().all().all(), "GHCN gaps"
    return out


def openmeteo(name: str) -> pd.DataFrame:
    """Open-Meteo archive daily for 2024-01..2026-09 (fetched with app.data.weather.fetch; identical to the
    repo fixture on its 2024-10..2026-08 overlap)."""
    w = pd.read_parquet(CACHE / f"r3_om_{name}_daily.parquet")
    w["date"] = pd.to_datetime(w["date"]).dt.date
    return w.set_index("date")


def calendar_frame() -> pd.DataFrame:
    start, end = D("2024-01-01"), D("2026-09-27")
    cal = pd.DataFrame({"date": pd.date_range(start, end, freq="D").date})
    cal = cal.join(features.calendar(cal["date"]))
    g = AGG.games()
    cal["home_game"] = cal["date"].map(g["home_game"]).fillna(False).astype(bool)
    om, st, nw = openmeteo("msg"), openmeteo("station"), noaa()
    cal["rain_om"] = cal["date"].map(om["precipitation_sum"]).round(6) >= 0.01
    cal["rain_om_cp"] = cal["date"].map(st["precipitation_sum"]).round(6) >= 0.01
    cal["rain_noaa"] = cal["date"].map(nw["PRCP"]) >= 0.01
    cal["prcp_noaa"] = cal["date"].map(nw["PRCP"])
    cal["prcp_om"] = cal["date"].map(om["precipitation_sum"])
    cal["ym"] = pd.to_datetime(cal["date"]).dt.strftime("%Y%m")
    assert cal[["prcp_noaa", "prcp_om"]].notna().all().all(), "weather gaps"
    return cal


def units(cal: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(panel358 long frame, daily frame with sum358 and zip710)."""
    rest_daily, msg_daily = dewey.load_all()
    ranking = dewey.rank_candidates(rest_daily, msg_daily)
    eligible = set(ranking.index[ranking["eligible"]])
    rest_daily["place_id"] = rest_daily["store_id"].map(dewey.place_hash)
    panel = rest_daily[rest_daily["place_id"].isin(eligible)][["place_id", "date", "visits"]]
    panel = panel.merge(cal, on="date", how="inner")
    print(f"panel358: {panel['place_id'].nunique()} venues, {panel['date'].min()}..{panel['date'].max()}, "
          f"{len(panel)} venue-days")
    per_day = panel.groupby("date")["visits"].agg(["mean", "size"])
    zip_df, meta = AGG.series()
    print(f"zip710: {meta['n_stores']['msg_zip_cluster']} balanced MSG-ZIP stores")
    daily = cal.copy()
    daily["sum358"] = daily["date"].map(per_day["mean"])
    daily["n358"] = daily["date"].map(per_day["size"])
    daily["zip710"] = daily["date"].map(zip_df.set_index("date")["msg_zip_cluster"])
    return panel, daily


# ------------------------------------------------------------------ models
def design(f: pd.DataFrame, season: str, rain: str) -> pd.DataFrame:
    X = pd.DataFrame(index=f.index)
    X["const"] = 1.0
    for d in range(1, 7):
        X[f"dow_{d}"] = (f["dow"] == d).astype(float)
    if season == "harm":
        w = 2 * np.pi * f["doy"].astype(float) / 365.25
        for k in (1, 2):
            X[f"sin{k}"], X[f"cos{k}"] = np.sin(k * w), np.cos(k * w)
    else:
        X = X.join(pd.get_dummies(f["ym"], prefix="ym", drop_first=True).astype(float))
    X["holiday"] = f["is_holiday"].astype(float)
    X["home_game"] = f["home_game"].astype(float)
    X["rain"] = f[rain].astype(float)
    return X.loc[:, (X.nunique() > 1) | (X.columns == "const")]


def fit_daily(y: pd.Series, X: pd.DataFrame) -> tuple[float, float, float]:
    r = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)
    return r.params["rain"], r.bse["rain"], r.pvalues["rain"]


def fit_panel(p: pd.DataFrame, season: str, rain: str) -> tuple[float, float, float]:
    """Within (venue FE) OLS; SE = max(date-clustered, Driscoll-Kraay-style HAC 7 on the daily mean), as r2-pooling."""
    X = design(p, season, rain).drop(columns="const")
    y = np.log1p(p["visits"].astype(float))
    g = p["place_id"]
    yd, Xd = y - y.groupby(g).transform("mean"), X - X.groupby(g).transform("mean")
    r = sm.OLS(yd, Xd).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(p["date"])[0]}, use_t=False)
    m = pd.concat([yd.rename("y"), Xd], axis=1).groupby(p["date"].values).mean()
    rdk = sm.OLS(m["y"], m[X.columns]).fit(cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)
    se = max(r.bse["rain"], rdk.bse["rain"])
    from scipy.stats import norm
    return r.params["rain"], se, 2 * norm.sf(abs(r.params["rain"]) / se)


def fit_unit(unit: str, panel: pd.DataFrame, daily: pd.DataFrame, lo: date, hi: date, season: str, rain: str):
    if unit == "panel358":
        p = panel[(panel["date"] >= lo) & (panel["date"] <= hi)].reset_index(drop=True)
        n = int(p.drop_duplicates("date")[rain].sum())
        return (*fit_panel(p, season, rain), n)
    f = daily[(daily["date"] >= lo) & (daily["date"] <= hi)].dropna(subset=[unit]).reset_index(drop=True)
    return (*fit_daily(np.log(f[unit].astype(float)), design(f, season, rain)), int(f[rain].sum()))


def pct(b: float) -> float:
    return 100 * (np.exp(b) - 1)


def bh(p: pd.Series) -> pd.Series:
    v = p.sort_values()
    m = len(v)
    adj = (v * m / np.arange(1, m + 1))[::-1].cummin()[::-1].clip(upper=1)
    return adj.reindex(p.index)


# ------------------------------------------------------------------ part 2: round-1 single-business refits
def round1() -> pd.DataFrame:
    nw = noaa()
    rows = []
    for biz in ("restaurant", "taxi"):
        base = features.build(biz)
        for src in ("repo_openmeteo", "noaa"):
            df = base.copy()
            if src == "noaa":
                df["rain"] = df["date"].map(nw["PRCP"]) >= 0.01
                df["tmax"] = df["date"].map(nw["TMAX"]).astype(float)
                assert df["tmax"].notna().all()
            for sp in ("train", "holdout"):
                d = df[df["split"] == sp].reset_index(drop=True)
                X = build_design(d, event_flags(d, {"hot": 85}))
                r = fit_ols(d["revenue"], X)
                for ev in ("rain", "hot", "home_win"):
                    flag = d["rain"] if ev == "rain" else (d["tmax"] > 85 if ev == "hot" else d["home_win"])
                    b, se = (r.params.get(ev, np.nan), r.bse.get(ev, np.nan))
                    rows.append(dict(business=biz, source=src, split=sp, event=ev, n_days=len(d),
                                     n_event=int(flag.sum()), usd=b, lo=b - Z90 * se, hi=b + Z90 * se,
                                     p=r.pvalues.get(ev, np.nan), first=d["date"].min(), last=d["date"].max()))
    return pd.DataFrame(rows)


def main() -> None:
    cal = calendar_frame()
    panel, daily = units(cal)

    # Basis: how often do the flags agree, per split window?
    print("\nBASIS (share of days the flags agree; corr)")
    for nm, (tr, ho) in SPLITS.items():
        for part, (lo, hi) in (("train", tr), ("holdout", ho)):
            c = cal[(cal["date"] >= lo) & (cal["date"] <= hi)]
            a = (c["rain_om"] == c["rain_noaa"]).mean()
            a_cp = (c["rain_om_cp"] == c["rain_noaa"]).mean()
            print(f"  {nm} {part:7s} {lo}..{hi}: OM-MSG vs NOAA agree {a:.3f} corr {np.corrcoef(c['rain_om'], c['rain_noaa'])[0,1]:.3f}"
                  f" | OM-CP vs NOAA agree {a_cp:.3f} | wet-day rate OM {c['rain_om'].mean():.3f} NOAA {c['rain_noaa'].mean():.3f}"
                  f" | OM-only {int((c['rain_om'] & ~c['rain_noaa']).sum())} NOAA-only {int((~c['rain_om'] & c['rain_noaa']).sum())}")

    rows = []
    for unit in ("panel358", "sum358", "zip710"):
        for src, col in SOURCES.items():
            for season in SEASONS:
                for sp, (tr, ho) in SPLITS.items():
                    bt, st, pt, nt = fit_unit(unit, panel, daily, *tr, season, col)
                    bo, so, po, no = fit_unit(unit, panel, daily, *ho, season, col)
                    rows.append(dict(unit=unit, source=src, season=season, split=sp,
                                     n_tr=nt, b_tr=bt, se_tr=st, p_tr=pt, n_ho=no, b_ho=bo, se_ho=so, p_ho=po))
    g = pd.DataFrame(rows)

    r1 = round1()

    # One BH family: 24 grid cells (train p) + round-1 rain and hot, 2 businesses x 2 sources (train p).
    r1_tests = r1[(r1["split"] == "train") & r1["event"].isin(["rain", "hot"])]
    allp = pd.concat([g["p_tr"], r1_tests["p"]], ignore_index=True)
    adj = bh(allp)
    g["bh_tr"] = adj.iloc[: len(g)].to_numpy()
    r1.loc[r1_tests.index, "bh_tr"] = adj.iloc[len(g):].to_numpy()
    # Holdout BH within the grid only (the holdout is a replication check).
    g["bh_ho"] = bh(g["p_ho"])
    print(f"\nBH family (train): {len(allp)} tests = {len(g)} grid cells + {len(r1_tests)} round-1 refits")

    sig = lambda b, se: (np.abs(b) - Z90 * se) > 0
    g["found"] = (sig(g["b_tr"], g["se_tr"]) & sig(g["b_ho"], g["se_ho"]) & (np.sign(g["b_tr"]) == np.sign(g["b_ho"]))
                  & (g["n_tr"] >= 10) & (g["bh_tr"] <= Q_BH))
    for s in ("tr", "ho"):
        g[f"pct_{s}"] = g[f"b_{s}"].map(pct)
        g[f"lo_{s}"] = (g[f"b_{s}"] - Z90 * g[f"se_{s}"]).map(pct)
        g[f"hi_{s}"] = (g[f"b_{s}"] + Z90 * g[f"se_{s}"]).map(pct)
    pd.set_option("display.width", 250, "display.max_columns", 40)
    cols = ["unit", "source", "season", "split", "n_tr", "pct_tr", "lo_tr", "hi_tr", "p_tr", "bh_tr",
            "n_ho", "pct_ho", "lo_ho", "hi_ho", "p_ho", "bh_ho", "found"]
    print("\nGRID: rain effect, % change in visits [90% CI]")
    print(g[cols].round(3).to_string(index=False))
    g[cols].round(5).to_csv(OUT / "grid.csv", index=False)

    # Main effects: mean train/holdout % by factor level (each level averages 12 cells).
    print("\nFACTOR MEANS (avg % over the other factors; share of cells FOUND)")
    for fac in ("source", "season", "split", "unit"):
        print(g.groupby(fac)[["pct_tr", "pct_ho", "found"]].mean().round(3).to_string(), "\n")

    # Diagnostic (not in BH family): split rain into agree / OM-only / NOAA-only days, zip710 and panel358, full A window.
    print("DIAGNOSTIC: rain decomposed by source agreement, ymfe, A split (train | holdout)")
    for unit in ("zip710", "sum358"):
        for sp, (lo, hi) in zip(("train", "holdout"), SPLITS["A"]):
            f = daily[(daily["date"] >= lo) & (daily["date"] <= hi)].dropna(subset=[unit]).reset_index(drop=True)
            f = f.assign(both=f.rain_om & f.rain_noaa, om_only=f.rain_om & ~f.rain_noaa, noaa_only=~f.rain_om & f.rain_noaa)
            X = design(f, "ymfe", "rain_noaa").drop(columns="rain").join(f[["both", "om_only", "noaa_only"]].astype(float))
            r = sm.OLS(np.log(f[unit].astype(float)), X).fit(cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)
            print(f"  {unit} {sp:7s} " + "  ".join(
                f"{k} n={int(f[k].sum())} {pct(r.params[k]):+.2f}% [{pct(r.params[k]-Z90*r.bse[k]):+.2f},{pct(r.params[k]+Z90*r.bse[k]):+.2f}]"
                for k in ("both", "om_only", "noaa_only")))

    # Why do harmonics lose the effect? Month-level shocks the 4 harmonics miss, correlated with the month's wet-day share.
    print("\nDIAGNOSTIC: harmonic-model residuals by month (NOAA rain), and harmonics + linear trend")
    for unit in ("zip710", "sum358"):
        for sp, (tr, ho) in SPLITS.items():
            for part, (lo, hi) in (("train", tr), ("holdout", ho)):
                f = daily[(daily["date"] >= lo) & (daily["date"] <= hi)].dropna(subset=[unit]).reset_index(drop=True)
                y = np.log(f[unit].astype(float))
                X = design(f, "harm", "rain_noaa")
                res = sm.OLS(y, X.drop(columns="rain")).fit().resid
                m = pd.DataFrame({"res": res, "wet": f["rain_noaa"].astype(float), "ym": f["ym"]}).groupby("ym").mean()
                Xt = X.assign(trend=np.arange(len(f)) / 365.0)
                bt, st, _ = fit_daily(y, Xt)
                print(f"  {unit} {sp} {part:7s}: SD of monthly mean resid {100*m['res'].std():.1f}% "
                      f"(daily resid SD {100*res.std():.1f}%), corr(month wet share, month resid) {m['wet'].corr(m['res']):+.2f}; "
                      f"harm+trend rain {pct(bt):+.2f}% [{pct(bt-Z90*st):+.2f},{pct(bt+Z90*st):+.2f}]")

    print("\nROUND 1 REFITS ($/day, HC3, exposure.build_design + fit_ols)")
    print(r1.round({"usd": 0, "lo": 0, "hi": 0, "p": 4, "bh_tr": 4}).to_string(index=False))
    r1.round(4).to_csv(OUT / "round1.csv", index=False)


if __name__ == "__main__":
    main()
