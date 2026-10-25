"""R6 broadway follow-ups for the one candidate that passed (snow days -> Broadway weekly gross).

Run from backend/ after run.py:  .venv/bin/python ../experiments/bar/r6-broadway/hedge.py

1. Robustness (exploratory, NOT in the BH family): control for performances; effect on the
   number of performances; drop the 3 snowiest weeks; permutation placebo (snow_days shuffled
   across years within calendar month, 500 draws).
2. Basis: monthly count of >= 1 in snow days vs the KXNYCSNOWM settlement flag (Central Park
   monthly snowfall strictly greater than K in, K in {2, 4, 6, 8, 10, 12}).
3. Out-of-sample hedge backtest on holdout Dec-Mar months 2003-2020: buy KXNYCSNOWM YES at the
   train frequency + $0.02 plus fee 0.07 p (1 - p), sized from the train beta.
"""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bw", HERE / "run.py")
bw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bw)

TRAIN_END, HO_END = date(2002, 12, 31), date(2020, 3, 8)
STRIKES = (2, 4, 6, 8, 10, 12)
B_WEEK = 33e6  # $ weekly Broadway gross at 2018-19 scale, for $ conversion only
RNG = np.random.default_rng(6)


def frame() -> pd.DataFrame:
    wx, g = bw.ghcn(), bw.games()
    b = pd.read_csv(bw.CACHE / "r6broadway_grosses.csv", parse_dates=["week_ending"])
    perf = b.groupby("week_ending").performances.sum().rename("perfs").reset_index()
    w = bw.weekly(bw.broadway(), wx, g)
    w = w.merge(perf.assign(week_ending=perf.week_ending.dt.date), on="week_ending")
    return w[(w.wx_missing == 0) & (w.week_ending <= HO_END)].reset_index(drop=True), wx


def beta(s: pd.DataFrame, y: pd.Series, extra: dict | None = None):
    X = bw.wk_design(s, "snow_days", False)
    for k, v in (extra or {}).items():
        X.insert(1, k, v)
    r = bw.fit(y, X, 4)
    return r.params["flag"], r.bse["flag"]


def robustness(w: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for split, m in (("train", w.week_ending <= TRAIN_END), ("holdout", w.week_ending > TRAIN_END)):
        s = w[m].reset_index(drop=True)
        cases = {
            "baseline log_gross": (s, np.log(s.gross), None),
            "+ log performances control": (s, np.log(s.gross), {"log_perfs": np.log(s.perfs)}),
            "y = log performances": (s, np.log(s.perfs), None),
        }
        top = s.nlargest(3, "snow_days").index
        d = s.drop(top).reset_index(drop=True)
        cases["drop 3 snowiest weeks"] = (d, np.log(d.gross), None)
        for name, (fr, y, ex) in cases.items():
            b_, se = beta(fr, y, ex)
            rows.append({"split": split, "check": name, "beta": b_, "lo": b_ - bw.Z * se, "hi": b_ + bw.Z * se})
        # permutation placebo: reassign each week's snow_days from a random other year's same-month week
        true_b, _ = beta(s, np.log(s.gross))
        mon = pd.to_datetime(s.week_ending).dt.month.to_numpy()
        groups = [np.flatnonzero(mon == k) for k in range(1, 13)]
        perm = []
        for _ in range(500):
            p = s.copy()
            sd = s.snow_days.to_numpy().copy()
            for idx in groups:
                sd[idx] = sd[RNG.permutation(idx)]
            p["snow_days"] = sd
            X = bw.wk_design(p, "snow_days", False)
            X = X.loc[:, (X.nunique() > 1) | (X.columns == "const")]
            perm.append(np.linalg.lstsq(X.to_numpy(float), np.log(p.gross).to_numpy(), rcond=None)[0][-1])
        perm = np.array(perm)
        rows.append({"split": split, "check": "permutation placebo (500, within month)", "beta": perm.mean(),
                     "lo": np.quantile(perm, 0.05), "hi": np.quantile(perm, 0.95),
                     "perm_p": float((np.abs(perm) >= abs(true_b)).mean())})
    return pd.DataFrame(rows)


def monthly(w: pd.DataFrame, wx: pd.DataFrame) -> pd.DataFrame:
    """Dec-Mar months: snow days, monthly CP snowfall, and a log-gross residual that keeps the
    month-level snow signal (year FE + calendar-month FE + holiday-week counts, no snow term)."""
    w = w.assign(ym=pd.to_datetime(w.week_ending).dt.to_period("M"))
    hcols = [c for c in w if c.startswith("h_")]
    m = w.groupby("ym").agg(gross=("gross", "mean"), shows=("shows", "mean"), snow_days=("snow_days", "sum"),
                            **{c: (c, "sum") for c in hcols}).reset_index()
    d = wx.copy()
    d.index = pd.to_datetime(d.index)
    m["snow_in"] = m.ym.map(d.snow.groupby(d.index.to_period("M")).sum())
    m = m[m.ym.dt.month.isin([12, 1, 2, 3])].reset_index(drop=True)
    m["winter"] = np.where(m.ym.dt.month == 12, m.ym.dt.year + 1, m.ym.dt.year)
    X = pd.get_dummies(m.winter.astype(str), prefix="y", drop_first=True).astype(float)
    X = X.join(pd.get_dummies(m.ym.dt.month.astype(str), prefix="m", drop_first=True).astype(float))
    X.insert(0, "const", 1.0)
    X = X.join(m[hcols].astype(float)).assign(log_shows=np.log(m.shows))
    import statsmodels.api as sm
    m["resid"] = sm.OLS(np.log(m.gross), X).fit().resid
    m["date"] = m.ym.dt.to_timestamp().dt.date
    return m


def basis_and_backtest(m: pd.DataFrame, b_train: float) -> tuple[pd.DataFrame, dict]:
    tr, ho = m[m.date <= TRAIN_END], m[m.date > TRAIN_END]
    rows = []
    for k in STRIKES:
        yes = (tr.snow_in > k).astype(float)
        rows.append({"strike_in": k, "train_freq": yes.mean(), "corr_snowdays_train": np.corrcoef(yes, tr.snow_days)[0, 1],
                     "corr_snowdays_holdout": np.corrcoef((ho.snow_in > k).astype(float), ho.snow_days)[0, 1],
                     "gap_snowdays": tr.snow_days[yes == 1].mean() - tr.snow_days[yes == 0].mean()})
    basis = pd.DataFrame(rows)
    best = basis.loc[basis.corr_snowdays_train.idxmax()]  # chosen on train only
    k = int(best.strike_in)
    p = best.train_freq + 0.02
    fee = 0.07 * p * (1 - p)
    weeks = 4.33
    n = abs(b_train) * B_WEEK * best.gap_snowdays  # $1 contracts: the $ loss gap between YES and NO months
    unhedged = ho.resid.to_numpy() * B_WEEK * weeks
    payoff = n * ((ho.snow_in > k).astype(float).to_numpy() - p - fee)
    hedged = unhedged + payoff
    bt = {"strike_in": k, "price": p, "fee": fee, "contracts": n, "months": len(ho),
          "yes_months_holdout": int((ho.snow_in > k).sum()),
          "sd_unhedged": unhedged.std(ddof=1), "sd_hedged": hedged.std(ddof=1),
          "p5_unhedged": np.quantile(unhedged, 0.05), "p5_hedged": np.quantile(hedged, 0.05),
          "mean_cost": payoff.mean(), "corr_resid_payout": np.corrcoef(unhedged, payoff)[0, 1]}
    return basis, bt


def main() -> None:
    w, wx = frame()
    rob = robustness(w)
    m = monthly(w, wx)
    b_train, _ = beta(w[w.week_ending <= TRAIN_END].reset_index(drop=True),
                      np.log(w[w.week_ending <= TRAIN_END].gross.reset_index(drop=True)))
    basis, bt = basis_and_backtest(m, b_train)
    rob.to_csv(HERE / "robustness.csv", index=False, float_format="%.4g")
    basis.to_csv(HERE / "basis.csv", index=False, float_format="%.4g")
    pd.DataFrame([bt]).to_csv(HERE / "hedge.csv", index=False, float_format="%.6g")
    pd.set_option("display.width", 200)
    print(rob.to_string(float_format=lambda x: f"{x:.4g}"))
    print(basis.to_string(float_format=lambda x: f"{x:.3f}"))
    for k, v in bt.items():
        print(f"{k:>20}: {v:,.4g}" if isinstance(v, float) else f"{k:>20}: {v}")


if __name__ == "__main__":
    main()
