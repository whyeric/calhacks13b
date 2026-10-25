"""C2-A19..A22: planted-effect model check on seeded synthetic feature frames."""

import random
import re
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.models import ModelCheck
from app.stats.exposure import build_design, event_flags
from app.stats.modelcheck import planted_fit, run_model_check
from tests.fixtures.synth_features import synth_bar, synth_taxi

MONEY = re.compile(r"^-?\d+\.\d{2}$")


@pytest.fixture(scope="module")
def taxi():
    return synth_taxi()


@pytest.fixture(scope="module")
def bar():
    return synth_bar()


@pytest.fixture(scope="module")
def taxi_check(taxi):
    return run_model_check(taxi)


def train_of(df):
    return df[df["split"] == "train"]


# C2-A19
@pytest.mark.parametrize("name", ["taxi", "bar"])
def test_planted_500_coverage(name, request):
    mc = run_model_check(request.getfixturevalue(name))
    assert mc.n_seeds == 50 and mc.frac == 0.15 and mc.planted_usd == Decimal("500.00")
    assert 0.80 <= mc.coverage <= 0.97
    assert Decimal("450") <= mc.mean_recovered <= Decimal("550")
    assert mc.target == 0.90


# C2-A20
def test_deterministic_and_global_rng_untouched(taxi, taxi_check):
    np_state = np.random.get_state()
    py_state = random.getstate()
    again = run_model_check(taxi)
    assert again == taxi_check
    assert again.example == taxi_check.example
    after = np.random.get_state()
    assert after[0] == np_state[0] and np.array_equal(after[1], np_state[1]) and after[2:] == np_state[2:]
    assert random.getstate() == py_state


def test_different_seeds_differ(taxi):
    train = train_of(taxi)
    a = planted_fit(train, seed=0)
    b = planted_fit(train, seed=1)
    assert not np.array_equal(a.model.exog[:, -1], b.model.exog[:, -1])
    assert a.params["planted"] != b.params["planted"]


# C2-A21
def test_planted_is_extra_regressor_and_train_not_mutated(taxi):
    train = train_of(taxi)
    before = train.copy(deep=True)
    res = planted_fit(train, seed=3)
    original = list(build_design(train, event_flags(train)).columns)
    assert res.model.exog_names == original + ["planted"]
    assert "rain" in res.model.exog_names
    planted = res.model.exog[:, -1]
    assert set(np.unique(planted)) == {0.0, 1.0}
    assert planted.sum() == round(0.15 * len(train))
    pd.testing.assert_frame_equal(train, before)
    assert "planted" not in taxi.columns


# C2-A22
def test_negative_control_effect_zero(taxi):
    mc = run_model_check(taxi, effect=0)
    assert mc.planted_usd == Decimal("0.00")
    assert 0.80 <= mc.coverage <= 0.97
    lo, hi = mc.example.ci90
    assert mc.example.contains_truth == (lo <= 0 <= hi)
    # The check only reports recovery; it carries no hedgeability label at all.
    assert "hedgeable" not in ModelCheck.model_fields
    assert "hedgeable" not in mc.model_dump()


def test_contains_truth_matches_ci90(taxi):
    for n in (1, 5):
        mc = run_model_check(taxi, n_seeds=n)
        lo, hi = mc.example.ci90
        assert lo <= mc.example.recovered <= hi
        assert mc.example.contains_truth == (lo <= mc.planted_usd <= hi)


def test_json_money_strings_and_schema(taxi_check):
    js = taxi_check.model_dump(mode="json")
    assert set(js) == {"planted_usd", "frac", "n_seeds", "example", "coverage", "mean_recovered", "target"}
    assert set(js["example"]) == {"seed", "recovered", "ci90", "contains_truth"}
    for v in (js["planted_usd"], js["mean_recovered"], js["example"]["recovered"], *js["example"]["ci90"]):
        assert isinstance(v, str) and MONEY.match(v)
    assert isinstance(js["coverage"], float) and isinstance(js["frac"], float)
    assert ModelCheck.model_validate(js) == taxi_check


def test_accepts_train_only_frame(taxi, taxi_check):
    assert run_model_check(train_of(taxi).drop(columns="split")) == taxi_check


def test_bad_frac_rejected(taxi):
    with pytest.raises(ValueError):
        run_model_check(taxi, frac=0.0)
    with pytest.raises(ValueError):
        run_model_check(taxi, n_seeds=0)


def test_hot_strike_kept_in_design(bar):
    res = planted_fit(train_of(bar), seed=0, strikes={"hot": 85.0}, event="hot")
    assert {"rain", "hot"} <= set(res.model.exog_names) and res.model.exog_names[-1] == "planted"
    mc = run_model_check(bar, strikes={"hot": 85.0}, n_seeds=10)
    assert 0.6 <= mc.coverage <= 1.0
    with pytest.raises(ValueError):
        run_model_check(bar, event="hot", n_seeds=1)


def test_planted_never_reaches_exposures(taxi):
    from app.stats.exposure import fit_exposures

    run_model_check(taxi, n_seeds=3)
    res = fit_exposures(taxi)
    assert all(e.event != "planted" for e in res.exposures + res.dropped)
