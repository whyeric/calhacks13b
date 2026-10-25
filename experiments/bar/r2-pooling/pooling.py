"""R2 pooling: one panel model across all eligible Dewey venues near MSG ("class rating").

Question: is there a category-level % effect of rain / hot (>85F) / home_game / home_win on daily
visits for the "typical venue near MSG", that holds on train AND on an independent holdout fit?

Panel:  log(visits+1)_it = a_i + DOW + season(k=1,2) + holiday + msg_event + home_game + home_win
                            + rain + hot + e_it
Venue fixed effects by within-demeaning (per fit sample); SEs clustered by date (all regressors are
date-level, so the effective n is the number of days). Robustness: Driscoll-Kraay-style HAC on the
cross-venue mean of the demeaned series, and the same model on the category total.
Heterogeneity: per-venue OLS (HC3) on log visits, then empirical-Bayes (DerSimonian-Laird) shrinkage
toward the pooled mean; a venue counts only if its shrunken 90% interval excludes 0 in train and
holdout (independent fits) with the same sign.
BH 10% across every test run here (count printed).

Run from backend/:  .venv/bin/python ../experiments/bar/r2-pooling/pooling.py
Writes only aggregate / opaque-id numbers to pooling_summary.csv and eb_summary.csv.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

import numpy as np
import pandas as pd
import statsmodels.api as sm

from app.config import get_settings
from app.data import dewey, features
from app.stats.exposure import Z90, build_design, event_flags

OUT = Path(__file__).resolve().parent
AVG = float(get_settings().avg_check_usd)
EVENTS = ("rain", "hot", "home_game", "home_win")
DEMO_BAR = "p_afa556030e60"
Q_BH = 0.10


def bh(p: np.ndarray, q: float = Q_BH) -> tuple[np.ndarray, np.ndarray]:
    """(passed, BH-adjusted p)."""
    p = np.asarray(p, float)
    n = len(p)
    order = np.argsort(p)
    adj = np.empty(n)
    adj[order] = np.minimum.accumulate((p[order] * n / np.arange(1, n + 1))[::-1])[::-1]
    adj = np.minimum(adj, 1)
    return adj <= q, adj


def design(df: pd.DataFrame) -> pd.DataFrame:
    """exposure.build_design with home_game as a reported regressor (it is a control there anyway)."""
    X = build_design(df, event_flags(df, {"hot": 85}))
    if "home_game" not in X.columns:  # dropped only when identical to msg_event; keep it, drop msg_event
        X = X.drop(columns="msg_event", errors="ignore")
        X["home_game"] = df["home_game"].astype(float)
    return X


def panel_fit(panel: pd.DataFrame) -> dict:
    """Within (venue FE) OLS, date-clustered SEs; plus DK-style HAC on the daily mean."""
    X = design(panel).drop(columns="const")
    y = np.log1p(panel["visits"].astype(float))
    g = panel["place_id"]
    yd = y - y.groupby(g).transform("mean")
    Xd = X - X.groupby(g).transform("mean")
    dates = pd.factorize(panel["date"])[0]
    r = sm.OLS(yd, Xd).fit(cov_type="cluster", cov_kwds={"groups": dates}, use_t=False)
    # Driscoll-Kraay flavour: average the demeaned data by date, Newey-West 7 lags.
    m = pd.concat([yd.rename("y"), Xd], axis=1).groupby(panel["date"].values).mean()
    rdk = sm.OLS(m["y"], m[X.columns]).fit(cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)
    out = {}
    for e in EVENTS:
        out[e] = dict(b=r.params[e], se=r.bse[e], p=r.pvalues[e], se_dk=rdk.bse[e], p_dk=rdk.pvalues[e],
                      n=int(panel.drop_duplicates("date")[e if e != "hot" else "tmax"].pipe(
                          lambda s: (s > 85).sum() if e == "hot" else s.astype(bool).sum())))
    out["_n_obs"], out["_n_days"], out["_n_venues"] = len(panel), panel["date"].nunique(), g.nunique()
    return out


def total_fit(df: pd.DataFrame) -> dict:
    """Category total log(sum visits + 1), HAC 7 lags (cross-check: visits-weighted)."""
    X = design(df)
    r = sm.OLS(np.log1p(df["visits"].astype(float)), X).fit(cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)
    return {e: dict(b=r.params[e], se=r.bse[e], p=r.pvalues[e]) for e in EVENTS}


def venue_fits(panel: pd.DataFrame) -> pd.DataFrame:
    """Per-venue OLS (HC3) of the venue's log visits *relative to the category* on the design.

    Relative = (y_it - a_i) - mean_j(y_jt - a_j): the common date shock is removed, so these
    are deviations from the pooled effect with honest, roughly independent SEs.
    """
    y = np.log1p(panel["visits"].astype(float))
    yd = y - y.groupby(panel["place_id"]).transform("mean")
    rel = yd - yd.groupby(panel["date"]).transform("mean")
    rows = []
    for pid, d in panel.assign(rel=rel).groupby("place_id"):
        X = design(d)
        r = sm.OLS(d["rel"], X).fit(cov_type="HC3", use_t=False)
        rows.append({"place_id": pid, **{f"{e}_b": r.params.get(e, np.nan) for e in EVENTS},
                     **{f"{e}_se": r.bse.get(e, np.nan) for e in EVENTS}})
    return pd.DataFrame(rows).set_index("place_id")


def eb(d: pd.Series, se: pd.Series, mu: float, se_mu: float) -> pd.DataFrame:
    """EB on venue deviations d_i (DerSimonian-Laird tau^2), then venue effect = pooled mu + shrunk d_i.

    Var(venue effect) = se_mu^2 + B_i se_i^2, where se_mu is the panel's (conservative) SE: the
    pooled mean carries the date-level uncertainty that independent-venue formulas would ignore.
    """
    from scipy.stats import norm

    ok = d.notna() & se.notna() & (se > 0)
    d, se = d[ok], se[ok]
    w = 1 / se**2
    dbar = (w * d).sum() / w.sum()
    Q = (w * (d - dbar) ** 2).sum()
    k = len(d)
    tau2 = max(0.0, (Q - (k - 1)) / (w.sum() - (w**2).sum() / w.sum()))
    B = tau2 / (tau2 + se**2)
    dev = B * (d - dbar)
    post = mu + dev
    psd = np.sqrt(se_mu**2 + B * se**2)
    z_dev = dev / np.sqrt(B * se**2).replace(0, np.nan)
    return pd.DataFrame({"raw_dev": d, "dev": dev, "post": post, "psd": psd,
                         "p": 2 * norm.sf(np.abs(post / psd)),
                         "p_dev": 2 * norm.sf(np.abs(z_dev.fillna(0))),
                         "tau": np.sqrt(tau2), "Q_p": 1 - __import__("scipy.stats").stats.chi2.cdf(Q, k - 1),
                         "I2": max(0.0, (Q - (k - 1)) / Q) if Q > 0 else 0.0})


def pct(b: float) -> float:
    return 100 * (np.exp(b) - 1)


def main() -> None:
    rest_daily, msg_daily = dewey.load_all()
    ranking = dewey.rank_candidates(rest_daily, msg_daily)
    eligible = set(ranking.index[ranking["eligible"]])
    attrs = dewey.read_weekly(dewey.resolve_dirs()[0])[["ID_STORE", "NAICS_CODE"]]
    naics = attrs.groupby("ID_STORE")["NAICS_CODE"].agg(lambda s: s.mode().iloc[0])
    naics.index = [dewey.place_hash(s) for s in naics.index]

    rest_daily["place_id"] = rest_daily["store_id"].map(dewey.place_hash)
    rest_daily = rest_daily[rest_daily["place_id"].isin(eligible)][["place_id", "date", "visits"]]
    base = features.build("restaurant").drop(columns="revenue")
    base = features.add_settlement(base, strike=85)
    panel = base.merge(rest_daily, on="date", how="inner")
    panel["naics"] = panel["place_id"].map(naics)
    tr, ho = panel[panel["split"] == "train"], panel[panel["split"] == "holdout"]

    # Basis: MSG-grid flags vs Central Park settlement flags.
    days = base.drop_duplicates("date")
    hot_grid = days["tmax"] > 85
    print("basis: rain agree", round((days["rain"] == days["settle_rain"]).mean(), 3),
          "corr", round(np.corrcoef(days["rain"], days["settle_rain"])[0, 1], 3),
          "| hot agree", round((hot_grid == days["settle_hot"]).mean(), 3),
          "corr", round(np.corrcoef(hot_grid, days["settle_hot"])[0, 1], 3))

    tests = []  # (family, label, event, train_b, train_se, train_p, ho_b, ho_se, ho_p, n_tr, n_ho)
    fits = {}
    for name, sub in [("pooled_all", None), *[(f"pooled_{c}", c) for c in sorted(panel["naics"].dropna().unique())]]:
        t = tr if sub is None else tr[tr["naics"] == sub]
        h = ho if sub is None else ho[ho["naics"] == sub]
        ft, fh = panel_fit(t), panel_fit(h)
        fits[name] = (ft, fh)
        print(f"\n{name}: train obs {ft['_n_obs']} days {ft['_n_days']} venues {ft['_n_venues']}; "
              f"holdout obs {fh['_n_obs']} days {fh['_n_days']} venues {fh['_n_venues']}")
        for e in EVENTS:
            a, c = ft[e], fh[e]
            tests.append(dict(family="panel", label=name, event=e, b_tr=a["b"], se_tr=a["se"], p_tr=a["p"],
                              se_dk_tr=a["se_dk"], p_dk_tr=a["p_dk"], n_tr=a["n"],
                              b_ho=c["b"], se_ho=c["se"], p_ho=c["p"], se_dk_ho=c["se_dk"], p_dk_ho=c["p_dk"], n_ho=c["n"]))

    # Category total (visits-weighted) cross-check.
    for nm, part in (("tr", tr), ("ho", ho)):
        agg = part.groupby("date", as_index=False)["visits"].sum().merge(base, on="date")
        fits[f"total_{nm}"] = total_fit(agg)
    for e in EVENTS:
        a, c = fits["total_tr"][e], fits["total_ho"][e]
        tests.append(dict(family="total", label="category_total", event=e, b_tr=a["b"], se_tr=a["se"], p_tr=a["p"],
                          b_ho=c["b"], se_ho=c["se"], p_ho=c["p"]))

    # Station-settled flags (rain, hot) in place of the MSG grid flags, pooled_all.
    for nm, part in (("tr", tr), ("ho", ho)):
        p2 = part.copy()
        p2["rain"] = p2["settle_rain"]
        p2["tmax"] = np.where(p2["settle_hot"], 86.0, 80.0)  # event_flags reads tmax > 85
        fits[f"station_{nm}"] = panel_fit(p2)
    for e in ("rain", "hot"):
        a, c = fits["station_tr"][e], fits["station_ho"][e]
        tests.append(dict(family="panel_station", label="pooled_all_station", event=e, b_tr=a["b"], se_tr=a["se"],
                          p_tr=a["p"], se_dk_tr=a["se_dk"], p_dk_tr=a["p_dk"], n_tr=a["n"],
                          b_ho=c["b"], se_ho=c["se"], p_ho=c["p"], se_dk_ho=c["se_dk"], p_dk_ho=c["p_dk"], n_ho=c["n"]))

    # Heterogeneity: per-venue fits + EB shrinkage, train and holdout independently.
    vt, vh = venue_fits(tr), venue_fits(ho)
    eb_rows = []
    pa_tr, pa_ho = fits["pooled_all"]
    for e in EVENTS:
        mt, mh = pa_tr[e], pa_ho[e]
        et = eb(vt[f"{e}_b"], vt[f"{e}_se"], mt["b"], max(mt["se"], mt["se_dk"]))
        eh = eb(vh[f"{e}_b"], vh[f"{e}_se"], mh["b"], max(mh["se"], mh["se_dk"]))
        print(f"EB {e}: train tau {100*et['tau'].iloc[0]:.2f}pp I2 {et['I2'].iloc[0]:.2f} Q p {et['Q_p'].iloc[0]:.3f} | "
              f"holdout tau {100*eh['tau'].iloc[0]:.2f}pp I2 {eh['I2'].iloc[0]:.2f} Q p {eh['Q_p'].iloc[0]:.3f} | "
              f"corr(raw dev tr, ho) {et['raw_dev'].corr(eh['raw_dev']):+.3f}; "
              f"venues with shrunk dev != 0 (90%): tr {(et['p_dev'] < 0.10).sum()}, ho {(eh['p_dev'] < 0.10).sum()}")
        j = et.add_suffix("_tr").join(eh.add_suffix("_ho"), how="inner")
        for pid, r in j.iterrows():
            eb_rows.append(dict(family="eb_venue", label=pid, event=e, b_tr=r["post_tr"], se_tr=r["psd_tr"],
                                p_tr=r["p_tr"], b_ho=r["post_ho"], se_ho=r["psd_ho"], p_ho=r["p_ho"],
                                dev_tr=r["raw_dev_tr"], dev_ho=r["raw_dev_ho"], p_dev_tr=r["p_dev_tr"],
                                n_tr=mt["n"], naics=naics.get(pid)))
    ebdf = pd.DataFrame(eb_rows)

    res = pd.concat([pd.DataFrame(tests), ebdf], ignore_index=True)
    # Gate p for the train stage: date-clustered p (panel) or the conservative max with DK where available.
    res["p_gate_tr"] = res[["p_tr", "p_dk_tr"]].max(axis=1) if "p_dk_tr" in res else res["p_tr"]
    res["p_gate_ho"] = res[["p_ho", "p_dk_ho"]].max(axis=1) if "p_dk_ho" in res else res["p_ho"]
    res["bh_pass_tr"], res["p_bh_tr"] = bh(res["p_gate_tr"].fillna(1).to_numpy())
    agg_mask = res["family"] != "eb_venue"
    res["p_bh_tr_aggonly"] = np.nan
    res.loc[agg_mask, "p_bh_tr_aggonly"] = bh(res.loc[agg_mask, "p_gate_tr"].to_numpy())[1]
    res["ci_tr_cluster_only"] = (res["b_tr"].abs() - Z90 * res["se_tr"]) > 0
    res["ci_ho_cluster_only"] = (res["b_ho"].abs() - Z90 * res["se_ho"]) > 0
    res["bh_pass_ho"], res["p_bh_ho"] = bh(res["p_gate_ho"].fillna(1).to_numpy())
    sig = lambda b, se: (np.abs(b) - Z90 * se) > 0
    se_tr = np.fmax(res["se_tr"], res.get("se_dk_tr", res["se_tr"]).fillna(0))
    se_ho = np.fmax(res["se_ho"], res.get("se_dk_ho", res["se_ho"]).fillna(0))
    res["ci_tr"], res["ci_ho"] = sig(res["b_tr"], se_tr), sig(res["b_ho"], se_ho)
    res["same_sign"] = np.sign(res["b_tr"]) == np.sign(res["b_ho"])
    res["n_ok"] = res["n_tr"].fillna(99) >= 10
    res["FOUND"] = res["ci_tr"] & res["ci_ho"] & res["same_sign"] & res["bh_pass_tr"] & res["n_ok"]
    print(f"\nTOTAL TESTS (BH family): {len(res)}  (panel/total/station {len(tests)}, EB venue-event {len(ebdf)})")

    # $ at the demo bar's and at the median venue's mean daily revenue (train visits x $35).
    tr_mean = tr.groupby("place_id")["visits"].mean() * AVG
    bar_rev = float(tr_mean.get(DEMO_BAR, np.nan))
    med_rev = float(tr_mean.median())
    print(f"demo bar mean rev ${bar_rev:,.0f}/day (in panel: {DEMO_BAR in tr_mean.index}); median venue ${med_rev:,.0f}/day")

    agg = res[res["family"] != "eb_venue"].copy()
    for s in ("tr", "ho"):
        se = se_tr if s == "tr" else se_ho
        agg[f"pct_{s}"] = agg[f"b_{s}"].map(pct)
        agg[f"lo_{s}"] = (agg[f"b_{s}"] - Z90 * se[agg.index]).map(pct)
        agg[f"hi_{s}"] = (agg[f"b_{s}"] + Z90 * se[agg.index]).map(pct)
        agg[f"usd_bar_{s}"] = agg[f"pct_{s}"] / 100 * bar_rev
        agg[f"usd_med_{s}"] = agg[f"pct_{s}"] / 100 * med_rev
    pd.set_option("display.width", 250, "display.max_columns", 40)
    cols = ["label", "event", "n_tr", "pct_tr", "lo_tr", "hi_tr", "p_tr", "p_gate_tr", "p_bh_tr", "p_bh_tr_aggonly", "n_ho", "pct_ho", "lo_ho",
            "hi_ho", "p_ho", "p_gate_ho", "usd_bar_tr", "usd_bar_ho", "usd_med_tr", "FOUND"]
    print(agg[cols].round(3).to_string(index=False))
    agg[cols + ["b_tr", "se_tr", "p_tr", "se_dk_tr", "p_dk_tr", "b_ho", "se_ho", "p_ho", "se_dk_ho", "p_dk_ho"]].round(5) \
        .to_csv(OUT / "pooling_summary.csv", index=False)

    v = res[res["family"] == "eb_venue"]
    for e in EVENTS:
        ve = v[v["event"] == e]
        print(f"EB {e}: venues shrunk-CI excl 0 train {int(ve['ci_tr'].sum())}, holdout {int(ve['ci_ho'].sum())}, "
              f"both same sign {int((ve['ci_tr'] & ve['ci_ho'] & ve['same_sign']).sum())}, BH-train pass {int(ve['bh_pass_tr'].sum())}, "
              f"FOUND {int(ve['FOUND'].sum())}; corr(post tr, post ho) {ve['b_tr'].corr(ve['b_ho']):+.3f}")
    top = v[v["FOUND"]].copy()
    if len(top):
        top["pct_tr"], top["pct_ho"] = top["b_tr"].map(pct), top["b_ho"].map(pct)
        print(top[["label", "naics", "event", "pct_tr", "p_tr", "p_bh_tr", "pct_ho", "p_ho"]].round(4).to_string(index=False))
    v[["label", "naics", "event", "b_tr", "se_tr", "p_tr", "p_bh_tr", "b_ho", "se_ho", "p_ho", "FOUND"]] \
        .round(5).rename(columns={"label": "place_id"}).to_csv(OUT / "eb_summary.csv", index=False)


if __name__ == "__main__":
    main()
