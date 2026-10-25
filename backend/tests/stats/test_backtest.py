"""C2-A17 (backtest half), C2-A23..A37: walk-forward backtest (issue #10, real tier from #13).

Synthetic frames only (numpy default_rng); no network. `flat_frame` removes the season so a
perfect hedge has something to remove; `synth_taxi` keeps it for the realistic cases.
"""

import json
import math
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.config import FALLBACK_MARKUP, FIXTURES_DIR
from app.models import BacktestResult, PerExposure
from app.stats.backtest import (
    BacktestConfig,
    BacktestContract,
    Quote,
    default_contracts,
    full_weeks,
    per_exposure_entry,
    quote_from_candles,
    quotes_from_history,
    reduction_pct,
    run_backtest,
    simulate,
    _ny_midnight_ts,
)
from app.stats.exposure import fit_exposures
from tests.fixtures.synth_features import DOW_EFFECT, make_synth, synth_bar, synth_taxi

WEEK_FIXTURE = Path(__file__).parents[1] / "fixtures" / "backtest_week.json"
MONDAY = date(2024, 1, 1)
RAIN_ONLY = {"rain": BacktestContract("rain", "settle_rain")}
IDEAL = BacktestConfig(markup=Decimal("0"), fees=False)  # price = p̂, fee = 0 (A25)


def flat_frame(
    *, seed: int = 0, n_train: int = 364, n_weeks: int = 26, beta_rain: float = 1000.0,
    sigma: float = 20.0, rain_prob: float = 0.3, start: date = MONDAY, estimated: bool = False,
) -> pd.DataFrame:
    """No season, small noise: revenue = 10000 + DOW + β·rain + ε. Holdout starts on a Monday."""
    df = make_synth(seed=seed, n_train=n_train, n_holdout=7 * n_weeks, start=start,
                    rain_prob=rain_prob, estimated=estimated)
    rng = np.random.default_rng(seed + 1000)
    df["revenue"] = 10000.0 + DOW_EFFECT[df["dow"]] + beta_rain * df["rain"] + rng.normal(0, sigma, len(df))
    df["settle_rain"] = df["rain"]
    return df


def run(df, contracts=RAIN_ONLY, cfg=IDEAL, exposures=None):
    return simulate(df, contracts, exposures if exposures is not None else fit_exposures(df), cfg)


def candle(d: date, ask: str | None, bid: str | None, volume: str = "500.00") -> dict:
    return {"end_period_ts": _ny_midnight_ts(d), "yes_ask_close": ask, "yes_bid_close": bid, "volume": volume}


# C2-A23
def test_week_structure_and_no_hedges():
    df = flat_frame(n_train=367, n_weeks=20)  # holdout starts on a Thursday: partial edge week
    df = df.iloc[:-5]  # and ends on a Friday
    run_ = run(df, contracts={})
    r = run_.result
    hold = df[df["split"] == "holdout"]
    hold_days = list(pd.to_datetime(hold["date"]).dt.date)
    assert hold_days[0].weekday() == 3 and hold_days[-1].weekday() == 4
    weeks = [w.week_start for w in r.weekly]
    assert all(w.weekday() == 0 for w in weeks)
    assert weeks[0] > hold_days[0] and weeks[-1] + timedelta(days=6) <= hold_days[-1]
    assert len(weeks) == len(full_weeks(hold_days)) == 18  # Mon Jan 6 .. Mon May 5
    by_date = dict(zip(pd.to_datetime(df["date"]).dt.date, df["revenue"]))
    for w in r.weekly:
        total = sum(by_date[w.week_start + timedelta(days=i)] for i in range(7))
        assert abs(float(w.unhedged) - total) < 0.04  # 7 daily cent roundings
        assert w.hedged == w.unhedged and w.premium == 0
    assert r.reduction_pct == 0.0 and r.std_hedged == r.std_unhedged
    assert r.total_premium == 0 and json.loads(r.model_dump_json())["total_premium"] == "0.00"
    assert r.n_hedges == r.n_declined == 0 and run_.days == []


# C2-A24
@pytest.mark.parametrize("k", [3, 9])
def test_no_look_ahead(k):
    df = synth_taxi(2, n_train=365, n_holdout=280)
    df["settle_rain"] = df["rain"]
    base = run(df, cfg=BacktestConfig(), contracts=default_contracts())
    k_start = base.result.weekly[k].week_start

    poisoned = df.copy()
    future = pd.to_datetime(poisoned["date"]).dt.date >= k_start
    rng = np.random.default_rng(99)
    poisoned.loc[future, "revenue"] = rng.normal(50000, 20000, future.sum())
    for col in ("rain", "settle_rain", "home_win"):
        poisoned.loc[future, col] = ~poisoned.loc[future, col]
    after = run(poisoned, cfg=BacktestConfig(), contracts=default_contracts())

    before_days = [d for d in base.days if d.date < k_start]
    assert before_days and before_days == [d for d in after.days if d.date < k_start]
    assert base.result.weekly[:k] == after.result.weekly[:k]
    for f0, f1 in zip(base.fits, after.fits):
        if f0.start <= k_start:  # fitted only on rows before the refit date
            assert f0 == f1
            assert f0.n_window == int((pd.to_datetime(df["date"]).dt.date < f0.start).sum())
    assert any(f0 != f1 for f0, f1 in zip(base.fits, after.fits) if f0.start > k_start)  # poison is live
    assert base.result.weekly[k:] != after.result.weekly[k:]


# C2-A25
def test_perfect_hedge_reduces_swing():
    r = run(flat_frame()).result
    assert r.std_hedged < r.std_unhedged
    assert r.reduction_pct > 90
    assert r.n_hedges > 0 and r.n_declined == 0


def _with_wrong_settle(df: pd.DataFrame, share: float, seed: int = 7) -> pd.DataFrame:
    """The contract misses `share` of the business's rain days (settles NO on them)."""
    df = df.copy()
    rng = np.random.default_rng(seed)
    miss = df["rain"] & (rng.random(len(df)) < share)
    df["settle_rain"] = df["rain"] & ~miss
    return df


# C2-A26
def test_basis_loose_hedge():
    perfect = run(flat_frame()).result.reduction_pct
    loose = run(_with_wrong_settle(flat_frame(), 0.2))
    assert any(d.h < 1 for d in loose.days if d.hedged)
    assert loose.result.n_hedges > 0
    assert loose.result.reduction_pct < perfect
    # Wrong on half the rain days: flags agree too little (r2 < 0.5), rule 4 declines every day.
    broken = run(_with_wrong_settle(flat_frame(), 0.5))
    assert broken.result.n_hedges == 0 and broken.declined_by_reason.get("basis_too_loose", 0) > 0
    assert broken.result.reduction_pct < perfect


# C2-A27
def test_h_cap_per_hedge():
    df = flat_frame(beta_rain=600.0)
    rng = np.random.default_rng(3)
    df["settle_rain"] = df["rain"] & (rng.random(len(df)) < 0.8)
    df["revenue"] += 800.0 * df["settle_rain"]  # settle days hit harder: |β_S| > |β|
    r = run(df)
    assert any(abs(f.basis["rain"].beta_s) > abs(next(e.effect_usd for e in f.exposures if e.event == "rain"))
               for f in r.fits)
    hedged = [d for d in r.days if d.hedged]
    assert hedged
    for d in hedged:
        assert d.h <= 1
        assert d.n <= math.ceil(abs(d.beta))


def _bar_frame(**kw) -> pd.DataFrame:
    df = flat_frame(beta_rain=-1000.0, rain_prob=0.27, **kw)  # rain hurts: the hedge buys YES
    return df


# C2-A28
def test_declines_counted_when_overpriced():
    df = _bar_frame()
    days = pd.to_datetime(df["date"]).dt.date
    quotes = {d: Quote(yes=Decimal("0.80"), no=Decimal("0.80")) for d in days}
    contracts = {"rain": BacktestContract("rain", "settle_rain", None, quotes)}
    r = run(df, contracts=contracts, cfg=BacktestConfig())
    fair = {f.p_hat["rain"] for f in r.fits}
    assert all(abs(p - Decimal("0.27")) < Decimal("0.05") for p in fair)
    priced = r.days
    assert priced and all("overpriced" in d.declined for d in priced)
    assert len(priced) == 7 * len(r.result.weekly)  # declined every day
    assert r.result.n_declined == len(priced) and r.result.n_hedges == 0
    assert r.result.total_premium == 0 and r.declined_by_reason["overpriced"] == len(priced)


# C2-A29
def test_liquidity_and_budget_rules_skipped():
    df = _bar_frame()
    days = pd.to_datetime(df["date"]).dt.date
    quotes = {d: Quote(yes=Decimal("0.28"), no=None, volume=Decimal("1")) for d in days}
    contracts = {"rain": BacktestContract("rain", "settle_rain", None, quotes)}
    r = run(df, contracts=contracts, cfg=BacktestConfig(budget=Decimal("0")))
    assert r.result.n_hedges > 0
    assert not {"illiquid", "over_budget"} & set(r.declined_by_reason)


def _week_frame(fx: dict) -> tuple[pd.DataFrame, dict]:
    """364 train days + the fixture's holdout week. Rain on 3 of every 10 train days."""
    start = MONDAY
    dates = [start + timedelta(days=i) for i in range(364 + 7)]
    rain_days = {date.fromisoformat(d) for d in fx["rain_days"]}
    rain = [(i % 10 in (0, 3, 6)) if i < 364 else d in rain_days for i, d in enumerate(dates)]
    base, eff = float(fx["base_revenue"]), float(fx["rain_effect_in_data"])
    df = pd.DataFrame({
        "date": dates,
        "revenue": [base + eff * r for r in rain],
        "dow": [d.weekday() for d in dates],
        "doy": [d.timetuple().tm_yday for d in dates],
        "is_holiday": False, "msg_event": False, "home_game": False, "home_win": False,
        "rain": rain, "rain_open_hours": rain, "tmax": 60.0, "estimated": False,
        "split": ["train"] * 364 + ["holdout"] * 7,
    })
    df["settle_rain"] = df["rain"]
    history = {"markets": {
        d.isoformat(): {"ticker": f"KXRAINNYC-{d:%y%b%d}-T0".upper(), "result": "yes" if r else "no",
                        "candles": [candle(d, fx["yes_ask_close"], fx["yes_bid_close"])]}
        for d, r in zip(dates[364:], rain[364:])
    }}
    return df, history


# C2-A30
def test_pnl_accounting_matches_hand_computed_week():
    fx = json.loads(WEEK_FIXTURE.read_text())
    df, history = _week_frame(fx)
    quotes, results = quotes_from_history(history)
    assert sum(results.values()) == len(fx["rain_days"])
    fit = fit_exposures(df)
    rain = next(e for e in fit.exposures + fit.dropped if e.event == "rain")
    rain = rain.model_copy(update={"effect_usd": Decimal(fx["beta"]), "hedgeable": True, "reasons": [],
                                   "hedge_side": "yes", "direction": "negative"})
    contracts = {"rain": BacktestContract("rain", "settle_rain", None, quotes)}
    r = simulate(df, contracts, [rain], BacktestConfig(refit=False))

    assert [d.date for d in r.days] == [date.fromisoformat(fx["week_start"]) + timedelta(days=i) for i in range(7)]
    for d in r.days:
        assert d.hedged and d.priced_real
        assert d.n == fx["n"] and d.h == Decimal(fx["h"]) and d.price == Decimal(fx["yes_ask_close"])
        assert d.fee == Decimal(fx["fee_per_day"]) and d.premium == Decimal(fx["premium_per_day"])
        assert d.payout == (Decimal(fx["payout_per_rain_day"]) if d.date.isoformat() in fx["rain_days"] else 0)
    (week,) = r.result.weekly
    assert sum((d.pnl for d in r.days), Decimal(0)) == Decimal(fx["week_pnl"])
    assert week.unhedged == Decimal(fx["unhedged"]) and week.hedged == Decimal(fx["hedged"])
    assert week.premium == r.result.total_premium == Decimal(fx["total_premium"])
    assert r.result.priced_real_pct == 1.0 and r.result.pricing_tier == "real"


# C2-A31
def test_decimal_boundary():
    fx = json.loads(WEEK_FIXTURE.read_text())
    df, history = _week_frame(fx)
    quotes, _ = quotes_from_history(history)
    q = next(iter(quotes.values()))
    assert isinstance(q.yes, Decimal) and q.yes == Decimal("0.3") and q.no == Decimal("0.72")
    with pytest.raises(TypeError):
        quote_from_candles([candle(MONDAY, 0.3, "0.28")], MONDAY)
    # Kalshi's own shapes parse too (historical {"close"}, live {"close_dollars"}).
    hist = {"end_period_ts": _ny_midnight_ts(MONDAY), "yes_ask": {"close": "0.2100"}, "yes_bid": {"close": "0.1300"},
            "volume": "3261.60"}
    live = {"end_period_ts": _ny_midnight_ts(MONDAY), "yes_ask": {"close_dollars": "0.2100"},
            "yes_bid": {"close_dollars": "0.1300"}, "volume_fp": "3261.60"}
    assert quote_from_candles([hist], MONDAY) == quote_from_candles([live], MONDAY) == Quote(
        yes=Decimal("0.2100"), no=Decimal("0.8700"), volume=Decimal("3261.60"))

    r = run(flat_frame(), cfg=BacktestConfig())
    for d in r.days:
        for v in (d.price, d.fair, d.fee, d.premium, d.payout, d.beta, d.h, d.pnl):
            assert isinstance(v, Decimal)
    out = json.loads(r.result.model_dump_json())
    for k in ("std_unhedged", "std_hedged", "total_premium"):
        assert isinstance(out[k], str)
    assert isinstance(out["worst_week_unhedged"]["income"], str)
    assert all(isinstance(w[c], str) for w in out["weekly"] for c in ("unhedged", "hedged", "premium"))
    assert isinstance(out["reduction_pct"], float) and isinstance(out["priced_real_pct"], float)
    BacktestResult.model_validate(out)


def _home_win_frame() -> pd.DataFrame:
    df = flat_frame(n_weeks=1, beta_rain=0.0)
    rng = np.random.default_rng(5)
    n = len(df)
    game = rng.random(n) < 0.3
    hold = (df["split"] == "holdout").to_numpy()
    game[hold] = [True, False, True, False, True, True, False]  # 4 game days in the holdout week
    win = game & (rng.random(n) < 0.55)
    win[hold] = game[hold] & np.array([True, False, False, False, True, True, False])
    df["home_game"], df["home_win"], df["msg_event"] = game, win, game
    df["revenue"] += 2000.0 * df["home_win"]
    return df


# C2-A32
def test_priced_real_pct():
    df = _home_win_frame()
    hold_days = list(pd.to_datetime(df.loc[df["split"] == "holdout", "date"]).dt.date)
    games = [d for d, g in zip(hold_days, df.loc[df["split"] == "holdout", "home_game"]) if g]
    quotes = {d: Quote(yes=Decimal("0.55"), no=Decimal("0.47")) for d in games[:3]}
    r = run(df, contracts={"home_win": BacktestContract("home_win", "home_win", "home_game", quotes)},
            cfg=BacktestConfig())
    assert len(r.days) == 4 and [d.date for d in r.days] == games  # home_win only on game days
    assert r.result.priced_real_pct == 0.75 and r.result.pricing_tier == "mixed"

    none = run(df, contracts={"home_win": BacktestContract("home_win", "home_win", "home_game")},
               cfg=BacktestConfig())
    assert none.result.priced_real_pct == 0.0 and none.result.pricing_tier == "frequency"


# C2-A33
def test_per_exposure_ineffective_boundary():
    nine = reduction_pct(Decimal("100.00"), Decimal("91.00"))
    ten = reduction_pct(Decimal("100.00"), Decimal("90.00"))
    assert (nine, ten) == (9.0, 10.0)
    assert per_exposure_entry(nine, Decimal("1.00")).ineffective is True
    assert per_exposure_entry(ten, Decimal("1.00")).ineffective is False
    with pytest.raises(ValueError):
        PerExposure(reduction_pct=9.99, total_premium=Decimal("0"), ineffective=False)
    # In a run, the only exposure's entry matches the headline.
    r = run(flat_frame()).result
    assert r.per_exposure["exp_rain"].ineffective is False
    assert r.per_exposure["exp_rain"].reduction_pct == r.reduction_pct


# C2-A34
def test_worst_week():
    df = flat_frame()
    hold = df["split"] == "holdout"
    week5 = df.index[hold][7 * 5: 7 * 6]
    # A dry week (rain lifts taxi revenue, so its rain bump goes) that is also 300/day worse.
    df.loc[week5, "revenue"] -= 1000.0 * df.loc[week5, "rain"].astype(float) + 300.0
    df.loc[week5, ["rain", "settle_rain"]] = False
    r = run(df).result
    planted = pd.to_datetime(df.loc[week5[0], "date"]).date()
    assert r.worst_week_unhedged.week_start == planted == r.worst_week_hedged.week_start
    assert r.worst_week_unhedged.income == min(w.unhedged for w in r.weekly)
    row = next(w for w in r.weekly if w.week_start == planted)
    assert r.worst_week_hedged.income == row.hedged >= row.unhedged


# C2-A35
def test_fallback_price_is_trailing_p_hat_plus_markup():
    df = synth_taxi(2, n_train=365, n_holdout=120)
    df["settle_rain"] = df["rain"]
    r = run(df, cfg=BacktestConfig())
    assert r.result.pricing_tier == "frequency" and r.result.priced_real_pct == 0.0
    dates = pd.to_datetime(df["date"]).dt.date
    for d in r.days[::17]:
        prior = df.loc[(dates < d.date) & (dates >= d.date - timedelta(days=365)), "settle_rain"]
        p = (Decimal(int(prior.sum())) / Decimal(len(prior))).quantize(Decimal("0.0001"))
        assert d.p_hat_trailing == p
        side_p = p if d.side == "yes" else 1 - p
        assert d.price == side_p + FALLBACK_MARKUP and not d.priced_real


# C2-A36
def test_overpriced_fires_only_in_stress():
    df = synth_taxi(2, n_train=365, n_holdout=180)
    df["settle_rain"] = df["rain"]
    base = run(df, cfg=BacktestConfig(markup=Decimal("0.02")))
    stress = run(df, cfg=BacktestConfig(markup=Decimal("0.20")))
    assert base.declined_by_reason.get("overpriced", 0) == 0
    assert stress.declined_by_reason.get("overpriced", 0) > 0
    assert all(Decimal(d.price) - d.fair > Decimal("0.15") for d in stress.days if "overpriced" in d.declined)


# C2-A37
def test_determinism_and_speed():
    df = synth_taxi(4, n_train=364, n_holdout=364)
    df["settle_rain"] = df["rain"]
    t0 = time.perf_counter()
    fit = fit_exposures(df)
    t_fit = time.perf_counter() - t0
    t0 = time.perf_counter()
    a = run_backtest(df, default_contracts(), fit, BacktestConfig())
    t_bt = time.perf_counter() - t0
    b = run_backtest(df, default_contracts(), fit, BacktestConfig())
    assert len(a.weekly) == 52
    assert a.model_dump_json() == b.model_dump_json()
    assert t_fit < 0.5 and t_bt < 5.0


# C2-A17 (BacktestResult half)
def test_estimated_propagates():
    bar = synth_bar(2)
    bar["settle_rain"] = bar["rain"]
    taxi = synth_taxi(2)
    taxi["settle_rain"] = taxi["rain"]
    assert run(bar, cfg=BacktestConfig()).result.estimated is True
    assert run(taxi, cfg=BacktestConfig()).result.estimated is False


def test_refit_drops_and_readmits():
    """D5: the effect flips sign in the holdout. Monthly refits on the expanding window first
    drop the exposure (CI spans 0), then readmit it on the other side once the gates pass again."""
    df = flat_frame(n_weeks=60)
    hold = df["split"] == "holdout"
    df.loc[hold, "revenue"] -= 3000.0 * df.loc[hold, "rain"]  # +1000 in train, -2000 in holdout
    r = run(df)
    state = []
    for f in r.fits:
        rain = [e for e in f.exposures if e.event == "rain"]
        state.append(rain[0].hedge_side if rain else "dropped")
    assert state[0] == "no" and "dropped" in state and state[-1] == "yes"
    first_drop = state.index("dropped")
    assert all(s_ != "no" for s_ in state[first_drop:])
    assert all(f.n_window < g.n_window for f, g in zip(r.fits, r.fits[1:]))
    for d in r.days:  # no contract is priced in a month whose fit dropped the exposure
        assert state[max(i for i, f in enumerate(r.fits) if f.start <= d.date)] != "dropped"


@pytest.mark.skipif(not (FIXTURES_DIR / "kalshi_history" / "rain.json").exists(), reason="no history fixture")
def test_real_history_fixture_parses():
    hist = json.loads((FIXTURES_DIR / "kalshi_history" / "rain.json").read_text())
    quotes, results = quotes_from_history(hist)
    assert results and quotes  # midnight gate: some holdout days have real prices
    for d, q in quotes.items():
        assert all(v is None or (isinstance(v, Decimal) and 0 < v < 1) for v in (q.yes, q.no))


def test_result_round_trips_through_the_backtest_cache_row(tmp_path):
    """The job stores `run_backtest` output as analysis(business, "backtest"); the route
    validates that row as BacktestResult."""
    from app import db

    engine = db.make_engine(f"sqlite:///{tmp_path / 'bt.db'}")
    db.create_schema(engine)
    r = run(flat_frame(), cfg=BacktestConfig()).result
    db.put_analysis("taxi", "backtest", r, "2026-10-24T00:00:00Z", engine=engine)
    assert BacktestResult.model_validate(db.get_analysis("taxi", "backtest", engine=engine)) == r
