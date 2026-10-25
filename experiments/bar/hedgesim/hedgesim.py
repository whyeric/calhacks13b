"""Hedge backtest: does buying the opposite side of a measured exposure make holdout revenue steadier?

For each (business, event): fit `fit_exposures` on train, take beta (point, CI lo, CI hi). On each
holdout event-eligible day buy |beta| $1 contracts of the side that pays when revenue is hurt
(beta > 0 -> NO, beta < 0 -> YES), at price = train frequency of that side + 0.02 markup, plus a
Kalshi fee ceil_cents(0.07 * C * P * (1 - P)) per order. Compare unhedged vs hedged daily revenue.

Settlement: rain/hot settle on the station series (Central Park, as the contracts do), hot is
tmax > strike (strict, as exposure.py). home_win settles on the game itself; eligible = home games.
Run from backend/:  .venv/bin/python ../experiments/bar/hedgesim/hedgesim.py
"""

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

from app.data import features  # noqa: E402
from app.stats.exposure import build_design, event_flags, fit_exposures, fit_ols  # noqa: E402

MARKUP = 0.02
FEE_RATE = 0.07
STRIKE = 85.0


def fee(contracts: float, price: float, per_contract: bool) -> float:
    if per_contract:  # rounding each contract up to the cent (harsher reading)
        return contracts * math.ceil(FEE_RATE * price * (1 - price) * 100 - 1e-9) / 100
    return math.ceil(FEE_RATE * contracts * price * (1 - price) * 100 - 1e-9) / 100


def load(business: str) -> pd.DataFrame:
    df = features.build(business)
    df = features.add_settlement(df)
    st = pd.read_parquet(BACKEND / "fixtures" / "weather_station.parquet")
    st["date"] = pd.to_datetime(st["date"]).dt.date
    df["settle_hot"] = df["date"].map(st.set_index("date")["temperature_2m_max"]) > STRIKE
    return df


def expected_revenue(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Train-fitted model on every row: full prediction (the "expected value" a hedge protects) and
    the baseline with event terms zeroed (calendar/season/controls only, i.e. what is not a surprise)."""
    train = df[df["split"] == "train"]
    X = build_design(train, event_flags(train, {"hot": STRIKE}))
    res = fit_ols(train["revenue"], X)
    Xa = build_design(df, event_flags(df, {"hot": STRIKE}), columns=X.columns)
    full = pd.Series(Xa.to_numpy(float) @ res.params.to_numpy(float), index=df.index)
    Xb = Xa.copy()
    for c in ("home_win", "rain", "hot"):
        if c in Xb:
            Xb[c] = 0.0
    base = pd.Series(Xb.to_numpy(float) @ res.params.to_numpy(float), index=df.index)
    return full, base


def holdout_beta(df: pd.DataFrame, event: str) -> float:
    """Same model refit on holdout only: what the effect actually was out of sample."""
    h = df[df["split"] == "holdout"]
    X = build_design(h, event_flags(h, {"hot": STRIKE}))
    return float(fit_ols(h["revenue"], X).params.get(event, float("nan")))


def backtest(df, exp_pred, base, event, beta, settle_col, eligible, p_yes, per_contract=False):
    """Daily hedge P&L on holdout. Returns a dict of summary stats."""
    hold = df["split"] == "holdout"
    rev = df.loc[hold, "revenue"]
    elig = eligible[hold]
    yes = df.loc[hold, settle_col].astype(bool)
    side_yes = beta < 0  # revenue falls when event happens -> buy YES
    p_side = p_yes if side_yes else 1 - p_yes
    price = min(p_side + MARKUP, 0.99)
    C = abs(beta)
    pays = yes if side_yes else ~yes
    f = fee(C, price, per_contract)
    pnl = np.where(elig, C * (pays.astype(float) - price) - f, 0.0)
    pnl = pd.Series(pnl, index=rev.index)
    hedged = rev + pnl
    below = rev < exp_pred[hold]
    paid = elig & pays
    def stats(x, mask=None):
        x = x if mask is None else x[mask]
        return x.std(ddof=1), np.percentile(x, 5), x.mean()
    su, p5u, mu = stats(rev)
    sh, p5h, mh = stats(hedged)
    surprise = rev - base[hold]  # calendar-adjusted revenue: the part an owner can't plan for
    ru, rh = surprise.std(ddof=1), (surprise + pnl).std(ddof=1)
    seu, _, _ = stats(rev, elig)
    seh, _, _ = stats(hedged, elig)
    return {
        "event": event, "beta": round(beta, 2), "side": "YES" if side_yes else "NO",
        "price": round(price, 3), "fee_day": round(f, 2), "n_elig": int(elig.sum()),
        "sd_un": su, "sd_h": sh, "sd_chg%": 100 * (sh / su - 1),
        "sd_elig_chg%": 100 * (seh / seu - 1),
        "resid_sd_un": ru, "resid_sd_chg%": 100 * (rh / ru - 1),
        "f_hold": round(float(yes[elig].mean()), 3),
        "p5_un": p5u, "p5_h": p5h, "mean_un": mu, "mean_h": mh, "cost_day": mu - mh,
        "hit_below%": 100 * paid[below & elig].mean() if (below & elig).any() else float("nan"),
        "hit_above%": 100 * paid[~below & elig].mean() if (~below & elig).any() else float("nan"),
    }


def run(business, events):
    df = load(business)
    exp_pred, base = expected_revenue(df)
    res = fit_exposures(df, strikes={"hot": STRIKE}, business_id=business)
    by = {e.event: e for e in res.exposures + res.dropped}
    train = df["split"] == "train"
    rows = []
    for event in events:
        e = by[event]
        if event == "home_win":
            eligible = df["home_game"].astype(bool)
            settle = "home_win"
            p_yes = df.loc[train & eligible, "home_win"].mean()
        else:
            eligible = pd.Series(True, index=df.index)
            settle = f"settle_{event}"
            p_yes = df.loc[train, settle].mean()
        lo, hi = float(e.ci90[0]), float(e.ci90[1])
        b_h = holdout_beta(df, event)
        # Best case: exact beta, zero price/fee error -> var falls by at most beta^2 p(1-p).
        sd_h = df.loc[~train, "revenue"].std(ddof=1)
        q = df.loc[~train & eligible, settle].mean() * (eligible[~train].mean())
        oracle = 100 * (math.sqrt(max(0.0, 1 - float(e.effect_usd) ** 2 * q * (1 - q) / sd_h**2)) - 1)
        print(f"{business}/{event}: train beta {float(e.effect_usd):,.0f}, holdout-refit beta {b_h:,.0f}, "
              f"oracle best sd change {oracle:.2f}%")
        for label, b in (("point", float(e.effect_usd)), ("ci_lo", lo), ("ci_hi", hi)):
            r = backtest(df, exp_pred, base, event, b, settle, eligible, p_yes)
            r.update(business=business, sizing=label, sig=e.hedgeable, ci=f"[{lo:,.0f}, {hi:,.0f}]",
                     n_train=e.n_events_train, p_hat=round(p_yes, 3))
            rows.append(r)
        r = backtest(df, exp_pred, base, event, float(e.effect_usd), settle, eligible, p_yes, per_contract=True)
        r.update(business=business, sizing="point,fee/contract", sig=e.hedgeable, ci="",
                 n_train=e.n_events_train, p_hat=round(p_yes, 3))
        rows.append(r)
        if event in ("rain", "hot"):  # perfect basis: settle on the business's own flag
            own = event_flags(df, {"hot": STRIKE})[event]
            df[f"own_{event}"] = own
            p_own = own[train].mean()
            r = backtest(df, exp_pred, base, event, float(e.effect_usd), f"own_{event}", eligible, p_own)
            r.update(business=business, sizing="point,own-flag", sig=e.hedgeable, ci="",
                     n_train=e.n_events_train, p_hat=round(p_own, 3))
            rows.append(r)
    print(f"{business}: r2 train {res.r2_train:.3f} holdout {res.r2_holdout:.3f}, n_holdout {res.n_holdout}")
    return rows


if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_columns", 40)
    rows = run("taxi", ["rain", "hot"]) + run("restaurant", ["rain", "home_win"])
    out = pd.DataFrame(rows)
    cols = ["business", "event", "sizing", "sig", "ci", "n_train", "beta", "side", "p_hat", "price",
            "fee_day", "n_elig", "f_hold", "sd_un", "sd_h", "sd_chg%", "sd_elig_chg%", "resid_sd_un", "resid_sd_chg%", "p5_un", "p5_h",
            "mean_un", "mean_h", "cost_day", "hit_below%", "hit_above%"]
    print(out[cols].round(2).to_string(index=False))
