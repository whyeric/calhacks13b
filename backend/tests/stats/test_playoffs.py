"""Playoff home-game exposure (app/stats/playoffs.py): a pooled near-MSG uplift applied to the bar."""

import math
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.config import Thresholds
from app.data.playoffs import read_games
from app.models import Exposure
from app.stats import playoffs as sp

POOLED = sp.Pooled(beta_log=0.057, se_log=0.0087, p_value=6e-11, n_games=33, n_stores=277,
                   window=("2024-01-01", "2026-09-27"), regular_pct=2.4)


def table(n=400, base=8000.0, po_lift=0.06, seed=0, start=date(2025, 1, 1)):
    rng = np.random.default_rng(seed)
    dates = [start + timedelta(days=i) for i in range(n)]
    po = {dates[i] for i in range(100, 160, 4)}  # 15 playoff home nights
    reg = {dates[i] for i in range(5, 100, 3)}
    rev = base * np.exp(rng.normal(0, 0.05, n)) * np.array([1 + po_lift * (d in po) for d in dates])
    df = pd.DataFrame({"date": dates, "revenue": rev, "home_game": [d in po or d in reg for d in dates],
                       "is_holiday": False, "rain": rng.random(n) < 0.3})
    games = pd.DataFrame([{"date": d, "team": "knicks", "season": 2025, "playoff": d in po, "home": True,
                           "round": "", "opponent": "BOS", "won": True} for d in sorted(po | reg)])
    return df, games


def test_effect_is_pooled_pct_times_quiet_night_baseline():
    df, games = table()
    e = sp.measure(df, business_id="restaurant", games=games, pooled=POOLED, expected_count=5.556)
    quiet = df.loc[~df["home_game"], "revenue"].mean()
    assert e.effect_usd == Decimal(repr(float(math.expm1(0.057) * quiet))).quantize(Decimal("0.01"))
    assert e.ci90[0] < e.effect_usd < e.ci90[1]
    assert (e.id, e.event, e.settlement_var, e.hedge_side) == ("exp_playoff_home", "playoff_home", "playoff_home", "no")
    assert e.estimated is True and e.hedgeable and e.reasons == []
    assert e.expected_count == 5.56 and e.n_events_train == 33
    assert "class rating" in e.basis_note and "0.5 km of MSG" in e.basis_note and "5.6" in e.basis_note
    assert Exposure.model_validate_json(e.model_dump_json()) == e


def test_own_series_fit_recovers_a_planted_lift_and_is_reported():
    df, games = table(po_lift=0.10, seed=3)
    own = sp.own_fit(df, sp.flags(df, games))
    assert own.n_games == 15
    assert own.ci_pct[0] < 0.10 < own.ci_pct[1]
    e = sp.measure(df, business_id="restaurant", games=games, pooled=POOLED)
    assert "own series alone" in e.basis_note and e.expected_count is None


def test_small_business_is_dropped_below_size():
    df, games = table(base=500.0)
    e = sp.measure(df, business_id="restaurant", games=games, pooled=POOLED, thresholds=Thresholds())
    assert not e.hedgeable and e.reasons == ["below_size"]


def test_regular_flag_excludes_playoff_nights():
    d = date(2025, 4, 20)
    games = pd.DataFrame([{"date": d, "team": "knicks", "season": 2025, "playoff": True, "home": True, "round": "R1",
                           "opponent": "DET", "won": True},
                          {"date": d, "team": "rangers", "season": 2025, "playoff": False, "home": True, "round": "",
                           "opponent": "BOS", "won": False}])
    f = sp.daily_flags(games, [d, d + timedelta(days=1)])
    assert f["po_home"].tolist() == [True, False] and f["reg_home"].tolist() == [False, False]


def test_committed_fixtures_load():
    pooled = sp.load_pooled()
    assert 0.03 < pooled.pct < 0.09 and pooled.n_games >= 30  # r5-nycplayoffs: +5.7% [4.0, 7.4]
    games = read_games()
    po_home = games[games["home"] & games["playoff"]]
    assert po_home.groupby(["team", "season"]).size().to_dict() == {
        ("knicks", 2024): 7, ("knicks", 2025): 9, ("knicks", 2026): 9, ("rangers", 2024): 8}


def test_missing_pooled_fixture_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        sp.load_pooled(tmp_path)
