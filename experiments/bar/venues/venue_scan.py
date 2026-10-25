"""Venue scan near MSG: does any eligible Dewey venue show a home_win (or rain) revenue effect?

For every eligible candidate in dewey.rank_candidates (coverage >= 98%, >= 200 visits/week; ZIPs
10001/10119/10121, NAICS 722511/722513/722410), revenue = daily visits x $35 is swapped into the
features.build("restaurant") table (same calendar, weather, schedule, split) and fit with
fit_exposures. Then BH-FDR (10%) and Bonferroni across venues, plus a train-vs-holdout stability fit.

Run from backend/:  .venv/bin/python ../experiments/bar/venues/venue_scan.py
Writes only summary numbers (opaque ids) to venue_scan_summary.csv next to this file.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

import numpy as np
import pandas as pd

from app.config import RAW_DATA_DIR, get_settings
from app.data import dewey, features
from app.stats.exposure import build_design, event_flags, fit_exposures, fit_ols

OUT = Path(__file__).resolve().parent
AVG = float(get_settings().avg_check_usd)
ALPHA_BH = 0.10
ALPHA_BONF = 0.10  # family-wise, matches the 90% gate


def bh(p: np.ndarray, q: float) -> np.ndarray:
    n = len(p)
    order = np.argsort(p)
    thresh = q * np.arange(1, n + 1) / n
    passed = p[order] <= thresh
    k = np.max(np.nonzero(passed)[0]) + 1 if passed.any() else 0
    out = np.zeros(n, bool)
    out[order[:k]] = True
    return out


def coef(df: pd.DataFrame, event: str) -> tuple[float, float, float, int]:
    """(beta, se, p, n_events) of `event` from the §5 design fit on all rows of `df`."""
    flags = event_flags(df, {"hot": 85})
    X = build_design(df, flags)
    if event not in X.columns:
        return 0.0, 0.0, 1.0, 0
    r = fit_ols(df["revenue"], X)
    return float(r.params[event]), float(r.bse[event]), float(r.pvalues[event]), int(flags[event].sum())


def main() -> None:
    rest_dir, _ = dewey.resolve_dirs(RAW_DATA_DIR)
    rest_daily, msg_daily = dewey.load_all()
    ranking = dewey.rank_candidates(rest_daily, msg_daily)
    eligible = ranking[ranking["eligible"]]

    attrs = dewey.read_weekly(rest_dir)[["ID_STORE", "POSTAL_CODE", "NAICS_CODE"]]
    attrs = attrs.groupby("ID_STORE").agg(lambda s: s.mode().iloc[0])
    attrs.index = [dewey.place_hash(s) for s in attrs.index]

    rest_daily["place_id"] = rest_daily["store_id"].map(dewey.place_hash)
    base = features.build("restaurant").drop(columns="revenue")

    rows = []
    for pid in eligible.index:
        s = rest_daily.loc[rest_daily["place_id"] == pid, ["date", "visits"]]
        df = base.merge(s, on="date", how="inner")
        df["revenue"] = df["visits"].astype(float) * AVG
        if (df["split"] == "train").sum() < 300 or (df["split"] == "holdout").sum() < 250:
            continue
        res = fit_exposures(df, strikes={"hot": 85}, business_id=pid)
        tr, ho = df[df["split"] == "train"], df[df["split"] == "holdout"]
        row = {
            "place_id": pid,
            "naics": attrs.loc[pid, "NAICS_CODE"],
            "zip": attrs.loc[pid, "POSTAL_CODE"],
            "weekly_visits": eligible.loc[pid, "weekly_visits"],
            "mean_rev": tr["revenue"].mean(),
            "r2_train": res.r2_train,
            "r2_holdout": res.r2_holdout,
        }
        for e in res.exposures + res.dropped:
            row[f"{e.event}_eff"] = float(e.effect_usd)
            row[f"{e.event}_lo"], row[f"{e.event}_hi"] = float(e.ci90[0]), float(e.ci90[1])
            row[f"{e.event}_se"] = float(e.se)
            row[f"{e.event}_p"] = e.p_value
            row[f"{e.event}_n"] = e.n_events_train
            row[f"{e.event}_gates"] = e.hedgeable
        for split_name, part in (("tr", tr), ("ho", ho)):
            b, se, p, n = coef(part, "home_win")
            row[f"hw_{split_name}_eff"], row[f"hw_{split_name}_se"], row[f"hw_{split_name}_p"], row[f"hw_{split_name}_n"] = b, se, p, n
            b, se, p, n = coef(part, "rain")
            row[f"rain_{split_name}_eff"], row[f"rain_{split_name}_p"] = b, p
            b, se, p, n = coef(part, "hot")
            row[f"hot_{split_name}_eff"], row[f"hot_{split_name}_p"] = b, p
        rows.append(row)

    out = pd.DataFrame(rows)
    m = len(out)
    for ev in ("home_win", "rain", "hot"):
        p = out[f"{ev}_p"].to_numpy(float)
        out[f"{ev}_t"] = out[f"{ev}_eff"] / out[f"{ev}_se"].replace(0, np.nan)
        out[f"{ev}_bh"] = bh(p, ALPHA_BH)
        out[f"{ev}_bonf"] = p <= ALPHA_BONF / m
    out.round(4).to_csv(OUT / "venue_scan_summary.csv", index=False)

    pd.set_option("display.width", 250, "display.max_columns", 40)
    print(f"eligible in ranking: {len(eligible)}; fitted: {m}")
    for ev in ("home_win", "rain", "hot"):
        sig = (out[f"{ev}_lo"] > 0) | (out[f"{ev}_hi"] < 0)
        print(f"{ev}: raw sig90 {sig.sum()} (pos {(sig & (out[f'{ev}_eff'] > 0)).sum()}, neg {(sig & (out[f'{ev}_eff'] < 0)).sum()}), "
              f"expected by chance {0.10 * m:.1f}; pass all gates {out[f'{ev}_gates'].sum()} "
              f"(pos {(out[f'{ev}_gates'] & (out[f'{ev}_eff'] > 0)).sum()}); BH10 {out[f'{ev}_bh'].sum()}; Bonf {out[f'{ev}_bonf'].sum()}; "
              f"median eff {out[f'{ev}_eff'].median():.1f}, mean t {out[f'{ev}_t'].mean():.2f}")
    # Split stability: correlation of train vs holdout home_win effects across venues.
    print("corr(train hw eff, holdout hw eff) across venues:", round(out["hw_tr_eff"].corr(out["hw_ho_eff"]), 3))
    print("corr(train rain eff, holdout rain eff):", round(out["rain_tr_eff"].corr(out["rain_ho_eff"]), 3))
    print("corr(train hot eff, holdout hot eff):", round(out["hot_tr_eff"].corr(out["hot_ho_eff"]), 3))
    hc = ["place_id", "naics", "zip", "weekly_visits", "hot_eff", "hot_lo", "hot_hi", "hot_p", "hot_n", "hot_bh", "hot_bonf",
          "r2_holdout", "hot_ho_eff", "hot_ho_p"]
    print("\nhot BH survivors:")
    print(out[out["hot_bh"]].sort_values("hot_p")[hc].round(3).to_string(index=False))
    print("holdout home_win days:", int(out["hw_ho_n"].median()))
    cols = ["place_id", "naics", "zip", "weekly_visits", "mean_rev", "home_win_eff", "home_win_lo", "home_win_hi",
            "home_win_p", "home_win_n", "home_win_t", "home_win_gates", "home_win_bh", "home_win_bonf",
            "r2_train", "r2_holdout", "hw_ho_eff", "hw_ho_se", "hw_ho_p"]
    print("\nTop 10 by home_win t:")
    print(out.sort_values("home_win_t", ascending=False)[cols].head(10).round(3).to_string(index=False))
    print("\nBottom 5 by home_win t:")
    print(out.sort_values("home_win_t")[cols].head(5).round(3).to_string(index=False))
    rc = ["place_id", "naics", "zip", "weekly_visits", "rain_eff", "rain_lo", "rain_hi", "rain_p", "rain_n", "rain_t",
          "rain_gates", "rain_bh", "rain_bonf", "r2_holdout", "rain_ho_eff", "rain_ho_p"]
    print("\nTop 5 rain by |t|:")
    print(out.reindex(out["rain_t"].abs().sort_values(ascending=False).index)[rc].head(5).round(3).to_string(index=False))
    print("\nChosen bar p_afa556030e60 present:", "p_afa556030e60" in set(out["place_id"]))
    print("NAICS counts:", out["naics"].value_counts().to_dict())
    print("t-stat sd (should be ~1 under null): hw", round(out["home_win_t"].std(), 2), "rain", round(out["rain_t"].std(), 2))


if __name__ == "__main__":
    main()
