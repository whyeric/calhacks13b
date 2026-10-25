"""Model-specification experiment: is the bar's effect hidden by a weak model?

Compares the production fit_exposures design (const, DOW, k=1,2 harmonics, controls, HC3)
against six alternatives on features.build("restaurant") (the bar) and features.build("taxi").
Prints summary numbers only (no daily series). Run from backend/:
    .venv/bin/python ../experiments/bar/model/specs.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

from app.data import features  # noqa: E402
from app.stats import exposure  # noqa: E402

Z = exposure.Z90
STRIKES = {"hot": 85}
EVENTS = ("home_win", "rain", "hot")
HAC_LAGS = 7


def base_design(df, harmonics=2, months=False, trend=False):
    X = exposure.build_design(df, exposure.event_flags(df, STRIKES))
    if harmonics != 2 or months:
        X = X.drop(columns=[c for c in X.columns if c[:3] in ("sin", "cos")])
    if harmonics != 2 and not months:
        w = 2 * np.pi * df["doy"].astype(float) / 365.25
        for k in range(1, harmonics + 1):
            X[f"sin{k}"], X[f"cos{k}"] = np.sin(k * w), np.cos(k * w)
    if months:
        m = pd.to_datetime(df["date"]).dt.month
        for k in range(2, 13):
            X[f"m{k}"] = (m == k).astype(float)
    if trend:
        t0 = pd.Timestamp("2024-10-01")
        X["trend"] = (pd.to_datetime(df["date"]) - t0).dt.days / 365.25
    return X


def lag1(r):
    r = np.asarray(r, float)
    return float(np.corrcoef(r[:-1], r[1:])[0, 1])


def r2(y, yhat):
    y = np.asarray(y, float)
    return 1 - ((y - yhat) ** 2).sum() / ((y - y.mean()) ** 2).sum()


def run(df, name, *, y="level", cov="HC3", **kw):
    """Fit on train; return R2s, residual lag-1 AC and the $ effects with 90% CI."""
    df = df.copy()
    if y == "ratio":
        # baseline = mean of the previous 4 same-weekday days (lags 7..28)
        base = sum(df["revenue"].shift(7 * k) for k in range(1, 5)) / 4
        df["yv"] = df["revenue"] / base
        df = df[base.notna()]
    elif y == "log":
        df["yv"] = np.log(df["revenue"])
    else:
        df["yv"] = df["revenue"]
    tr, ho = df[df.split == "train"], df[df.split == "holdout"]
    X = base_design(tr, **kw)
    Xh = base_design(ho, **kw).reindex(columns=X.columns, fill_value=0.0)
    ols = sm.OLS(tr["yv"].astype(float), X)
    res = ols.fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS}, use_t=False) if cov == "HAC" \
        else ols.fit(cov_type="HC3", use_t=False)
    fit_tr = X.to_numpy(float) @ res.params.to_numpy()
    fit_ho = Xh.to_numpy(float) @ res.params.to_numpy()
    mean_rev = tr["revenue"].mean()
    # R2 always on the $ scale so specs are comparable
    if y == "log":
        smear = np.exp(res.resid).mean()  # Duan smearing
        p_tr, p_ho = np.exp(fit_tr) * smear, np.exp(fit_ho) * smear
    elif y == "ratio":
        b_tr = (tr["revenue"] / tr["yv"]).to_numpy()
        b_ho = (ho["revenue"] / ho["yv"]).to_numpy()
        p_tr, p_ho = fit_tr * b_tr, fit_ho * b_ho
    else:
        p_tr, p_ho = fit_tr, fit_ho
    out = dict(spec=name, r2_tr=r2(tr["revenue"], p_tr), r2_ho=r2(ho["revenue"], p_ho),
               ac1=lag1(res.resid), n_train=len(tr))
    for e in EVENTS:
        b, se = float(res.params[e]), float(res.bse[e])
        lo, hi = b - Z * se, b + Z * se
        if y == "log":  # % effect -> $ at the train mean
            conv = lambda v: (np.exp(v) - 1) * mean_rev  # noqa: E731
            b, lo, hi = conv(b), conv(lo), conv(hi)
        elif y == "ratio":  # ratio points -> $ at the train mean
            b, lo, hi = b * mean_rev, lo * mean_rev, hi * mean_rev
        out[e] = (b, lo, hi, int(X[e].sum()), lo > 0 or hi < 0)
    return out


SPECS = [
    ("0 current (DOW+k2, HC3)", {}),
    ("1 month dummies", {"months": True}),
    ("2 harmonics k=4", {"harmonics": 4}),
    ("3 + linear trend", {"trend": True}),
    ("4 log(revenue)", {"y": "log"}),
    ("5 ratio to 4-wk same-DOW mean", {"y": "ratio"}),
    ("6 current, HAC(7) SEs", {"cov": "HAC"}),
    ("7 ratio + HAC(7)", {"y": "ratio", "cov": "HAC"}),
    ("8 months + trend + HAC(7)", {"months": True, "trend": True, "cov": "HAC"}),
]


def main():
    for biz in ("restaurant", "taxi"):
        df = features.build(biz)
        print(f"\n## {biz}  (train mean ${df[df.split=='train'].revenue.mean():,.0f})")
        print("| spec | R2 train | R2 holdout | resid AC1 | home_win | rain | hot (>85F) |")
        print("|---|---|---|---|---|---|---|")
        for name, kw in SPECS:
            o = run(df, name, **kw)
            cells = []
            for e in EVENTS:
                b, lo, hi, n, sig = o[e]
                cells.append(f"{b:+,.0f} [{lo:,.0f}, {hi:,.0f}] n={n}{' *' if sig else ''}")
            print(f"| {name} | {o['r2_tr']:.3f} | {o['r2_ho']:.3f} | {o['ac1']:.2f} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
