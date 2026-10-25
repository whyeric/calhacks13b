"""R2-places: which kinds of Dewey places show large, replicating weather sensitivity?

Series: daily Dewey visits for (a) the 300 largest venues (coverage >= 98%, < 5% flat weeks) and
(b) aggregates over a fixed panel of stable venues: all Manhattan, each NAICS code, each
TOP_CATEGORY, and each Manhattan ZIP with >= 20 stable venues.

Model per series and period (fixed a priori, never tuned on holdout):
    visits ~ const + DOW + season k=1,2 (build_design) + holiday + linear trend + rain + hot
with rain = Central Park daily precip >= 0.01 in (the KXRAIN settlement itself) and
hot = Central Park tmax > 85 F (KXHIGHNY strict), Newey-West HAC errors (maxlags 7), z = 1.645.
Effect is beta / mean visits of the period. Train 2024-01-01..2025-03-31, holdout
2025-04-01..2026-09-27, each fitted independently. BH at 10% over every train test.

Privacy: only opaque ids (v001.. ranked by size) and aggregate summaries are written.
Run from backend/:  .venv/bin/python ../experiments/bar/r2-places/places.py
"""

import math
import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

from app import config  # noqa: E402
from app.data import weather  # noqa: E402
from app.data.features import calendar  # noqa: E402
from app.stats.exposure import build_design  # noqa: E402

OUT = Path(__file__).resolve().parent
CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
REST_DIR = BACKEND.parent / "data" / "01a16ff2-6017-7e10-86ac-94bf02853813"
START, END = date(2024, 1, 1), date(2026, 9, 27)
TRAIN_END, HOLD_START = date(2025, 3, 31), date(2025, 4, 1)
STRIKE, RAIN_IN, Z90, BH_Q, MIN_EFFECT = 85.0, 0.01, 1.645, 0.10, 0.05
N_VENUES, MIN_ZIP_VENUES = 300, 20
AVG_CHECK, MARKUP, FEE = 35.0, 0.02, 0.07


def load_weather() -> pd.DataFrame:
    path = CACHE / "weather_cp_2024_2026.parquet"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        w = weather.fetch(*config.SETTLEMENT_STATION_LATLON, START, END)
        w.daily.to_parquet(path, index=False)
    d = pd.read_parquet(path)
    d["date"] = pd.to_datetime(d["date"]).dt.date
    d["rain"] = d["precipitation_sum"] >= RAIN_IN
    d["tmax"] = d["temperature_2m_max"]
    return d[["date", "rain", "tmax"]]


def store_days() -> pd.DataFrame:
    """(store, date, visits, naics, cat, zip, flat) with overlapping weeks deduped (latest wins)."""
    path = CACHE / "store_days.parquet"
    if path.exists():
        return pd.read_parquet(path)
    sql = f"""
    with w as (
      select ID_STORE s, NAICS_CODE naics, TOP_CATEGORY cat, substr(POSTAL_CODE,1,5) zip,
             cast(DATE_RANGE_START as date) ws, from_json(VISITS_BY_DAY, '["BIGINT"]') a
      from '{REST_DIR}/*.parquet' where DATE_RANGE_START >= DATE '{START}'
    ), d as (
      select s, naics, cat, zip, ws, list_min(a) = list_max(a) flat,
             unnest(range(7)) i, unnest(a) v
      from w where len(a) = 7
    )
    select s, naics, cat, zip, flat, cast(ws + i * interval 1 day as date) date, v visits
    from d qualify row_number() over (partition by s, ws + i * interval 1 day order by ws desc) = 1
    """
    df = duckdb.sql(sql).df()
    df.to_parquet(path, index=False)
    return df


def fit(y: pd.Series, frame: pd.DataFrame) -> dict:
    """One period's fit; returns effect as share of mean, its CI and p, plus raw beta (visits)."""
    flags = {"rain": frame["rain"], "hot": frame["tmax"] > STRIKE}
    X = build_design(frame, flags)
    X["trend"] = np.arange(len(frame)) / 365.25
    res = sm.OLS(y.astype(float).to_numpy(), X.to_numpy(float)).fit(
        cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)
    cols = list(X.columns)
    m = float(y.mean())
    out = {}
    for ev in ("rain", "hot"):
        n = int(flags[ev].sum())
        if ev not in cols:
            out[ev] = dict(beta=0.0, pct=0.0, lo=0.0, hi=0.0, p=1.0, n=n)
            continue
        j = cols.index(ev)
        b, se, p = float(res.params[j]), float(res.bse[j]), float(res.pvalues[j])
        out[ev] = dict(beta=b, pct=b / m, lo=(b - Z90 * se) / m, hi=(b + Z90 * se) / m, p=p, n=n)
    return out


def bh(p: np.ndarray, q: float = BH_Q) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg: (reject mask, adjusted p)."""
    n = len(p)
    order = np.argsort(p)
    adj = np.empty(n)
    adj[order] = np.minimum.accumulate((p[order] * n / np.arange(1, n + 1))[::-1])[::-1]
    adj = np.minimum(adj, 1.0)
    return adj <= q, adj


def hedge_backtest(y: pd.Series, frame: pd.DataFrame, ev: str, beta_visits: float, freq: float) -> dict:
    """Holdout: every day buy |beta|*$35 $1 contracts of the side that pays when visits are hurt."""
    rev = y.to_numpy(float) * AVG_CHECK
    flag = (frame["rain"] if ev == "rain" else frame["tmax"] > STRIKE).to_numpy(bool)
    pays_on_event = beta_visits < 0  # revenue falls on the event -> buy YES
    hit = flag if pays_on_event else ~flag
    price = min((freq if pays_on_event else 1 - freq) + MARKUP, 0.99)
    c = abs(beta_visits) * AVG_CHECK
    pnl = c * (hit.astype(float) - price) - FEE * c * price * (1 - price)
    hedged = rev + pnl
    # Remove calendar/season so SD measures surprise, not weekday swings.
    X = build_design(frame, {})
    X["trend"] = np.arange(len(frame)) / 365.25
    def resid(v):
        return v - X.to_numpy(float) @ np.linalg.lstsq(X.to_numpy(float), v, rcond=None)[0]
    ru, rh = resid(rev), resid(hedged)
    return dict(contracts=c, price=price, sd_raw_u=rev.std(), sd_raw_h=hedged.std(),
                sd_res_u=ru.std(), sd_res_h=rh.std(),
                p5_u=np.percentile(ru, 5), p5_h=np.percentile(rh, 5), cost=-pnl.sum())


def main() -> None:
    w = load_weather()
    sd = store_days()
    sd["date"] = pd.to_datetime(sd["date"]).dt.date
    sd = sd[(sd["date"] >= START) & (sd["date"] <= END)]
    span = (END - START).days + 1
    zipn = pd.to_numeric(sd["zip"], errors="coerce")
    sd = sd[(zipn >= 10001) & (zipn <= 10282)]

    g = sd.groupby("s")
    meta = pd.DataFrame({"days": g.size(), "visits": g["visits"].mean(), "flat_share": g["flat"].mean(),
                         "naics": g["naics"].first(), "cat": g["cat"].first(), "zip": g["zip"].first()})
    meta["coverage"] = meta["days"] / span
    stable = meta[(meta["coverage"] >= 0.98) & (meta["flat_share"] < 0.05)]
    print(f"venues in Manhattan ZIPs: {len(meta)}, stable panel: {len(stable)}")

    cal = pd.DataFrame({"date": pd.date_range(START, END).date})
    cal = cal.join(calendar(cal["date"])).merge(w, on="date", how="left")
    for c in ("msg_event", "home_game"):
        cal[c] = False
    assert cal["tmax"].notna().all(), "weather gap"
    periods = {"train": (START, TRAIN_END), "holdout": (HOLD_START, END)}

    panel = sd[sd["s"].isin(stable.index)]
    wide = panel.pivot_table(index="date", columns="s", values="visits", aggfunc="sum")
    wide = wide.reindex(cal["date"])
    wide = wide.interpolate(limit=3).bfill().ffill()  # <= 2% gaps on a fixed panel

    series: dict[str, tuple[str, pd.Series]] = {}
    series["all_manhattan"] = ("aggregate", wide.sum(axis=1))
    for n, ids in stable.groupby("naics").groups.items():
        series[f"naics_{n}"] = ("aggregate", wide[list(ids)].sum(axis=1))
    for c, ids in stable.groupby("cat").groups.items():
        key = "cat_drinking" if c.startswith("Drinking") else "cat_restaurants"
        series[key] = ("aggregate", wide[list(ids)].sum(axis=1))
    zips = stable.groupby("zip").groups
    for z, ids in sorted(zips.items()):
        if len(ids) >= MIN_ZIP_VENUES:
            series[f"zip_{z}"] = ("zip", wide[list(ids)].sum(axis=1))
    top = stable.sort_values("visits", ascending=False).head(N_VENUES)
    vid = {s: f"v{i + 1:03d}" for i, s in enumerate(top.index)}
    for s in top.index:
        series[vid[s]] = ("venue", wide[s])

    rows = []
    for name, (kind, y) in series.items():
        y = pd.Series(y.to_numpy(), index=cal.index)
        fits = {}
        for per, (a, b) in periods.items():
            m = (cal["date"] >= a) & (cal["date"] <= b)
            fits[per] = fit(y[m].reset_index(drop=True), cal[m].reset_index(drop=True))
        for ev in ("rain", "hot"):
            t, h = fits["train"][ev], fits["holdout"][ev]
            rows.append(dict(series=name, kind=kind, event=ev, n_train=t["n"], tr_pct=t["pct"], tr_lo=t["lo"],
                             tr_hi=t["hi"], tr_p=t["p"], tr_beta=t["beta"], n_hold=h["n"], ho_pct=h["pct"],
                             ho_lo=h["lo"], ho_hi=h["hi"], ho_p=h["p"]))
    r = pd.DataFrame(rows)
    r["tr_bh"], r["tr_padj"] = bh(r["tr_p"].to_numpy())
    r["large"] = r["tr_pct"].abs() >= MIN_EFFECT
    r["candidate"] = r["tr_bh"] & r["large"] & (r["n_train"] >= 10)
    r["ho_same_sign_sig"] = (np.sign(r["ho_pct"]) == np.sign(r["tr_pct"])) & ((r["ho_lo"] > 0) | (r["ho_hi"] < 0))
    # Holdout BH among the train candidates only (one-sided p in the train direction).
    r["ho_padj"] = np.nan
    cand = r["candidate"]
    if cand.any():
        one = np.where(np.sign(r.loc[cand, "ho_pct"]) == np.sign(r.loc[cand, "tr_pct"]),
                       r.loc[cand, "ho_p"] / 2, 1 - r.loc[cand, "ho_p"] / 2)
        r.loc[cand, "ho_padj"] = bh(one)[1]
    r["found"] = cand & r["ho_same_sign_sig"] & (r["ho_padj"] <= BH_Q)
    r.to_csv(OUT / "results_all.csv", index=False, float_format="%.5g")

    pd.set_option("display.width", 220)
    show = ["series", "kind", "event", "n_train", "tr_pct", "tr_lo", "tr_hi", "tr_padj",
            "n_hold", "ho_pct", "ho_lo", "ho_hi", "ho_padj", "found"]
    print(f"\ntests: {len(r)} ({r['series'].nunique()} series x 2 events)")
    for kind in ("aggregate", "zip", "venue"):
        k = r[r["kind"] == kind]
        print(f"\n{kind}: {len(k)} tests, raw train p<0.10: {(k['tr_p'] < 0.10).sum()}, "
              f"BH pass: {k['tr_bh'].sum()}, large+BH: {k['candidate'].sum()}, "
              f"holdout replicate: {(k['candidate'] & k['ho_same_sign_sig']).sum()}, found: {k['found'].sum()}")
        for ev in ("rain", "hot"):
            e = k[k["event"] == ev]
            print(f"  {ev}: median train {e['tr_pct'].median():+.1%}, median holdout {e['ho_pct'].median():+.1%}, "
                  f"corr(train, holdout) {e['tr_pct'].corr(e['ho_pct']):.2f}")
    print("\naggregates:")
    print(r[r["kind"] == "aggregate"][show].round(3).to_string(index=False))
    print("\ncandidates (train BH + large):")
    print(r[r["candidate"]][show].round(3).to_string(index=False))
    # Category mix of the venue candidates and found ones.
    vmeta = top.assign(series=[vid[s] for s in top.index]).set_index("series")[["naics"]]
    vc = r[(r["kind"] == "venue")].join(vmeta, on="series")
    print("\nvenue candidates / found by NAICS and event:")
    print(vc.groupby(["naics", "event"])[["candidate", "found"]].sum().join(
        vc.groupby(["naics", "event"]).size().rename("n")).to_string())
    print("\nvenue rain median effects by NAICS (train / holdout):")
    print(vc.groupby(["naics", "event"])[["tr_pct", "ho_pct"]].median().round(3).to_string())

    found = r[r["found"]]
    if len(found):
        print("\nhedge backtests (holdout, beta from train):")
        for _, f in found.iterrows():
            y = pd.Series(series[f["series"]][1].to_numpy(), index=cal.index)
            tr = (cal["date"] >= START) & (cal["date"] <= TRAIN_END)
            ho = (cal["date"] >= HOLD_START) & (cal["date"] <= END)
            flag = cal["rain"] if f["event"] == "rain" else cal["tmax"] > STRIKE
            freq = float(flag[tr].mean())
            hb = hedge_backtest(y[ho].reset_index(drop=True), cal[ho].reset_index(drop=True),
                                f["event"], f["tr_beta"], freq)
            print(f"  {f['series']} {f['event']}: " + ", ".join(
                f"{k}={v:,.1f}" if not isinstance(v, str) else f"{k}={v}" for k, v in hb.items()))


if __name__ == "__main__":
    main()
