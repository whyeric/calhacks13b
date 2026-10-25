"""C1-A20..A30: feature table schema, derivations, split, flags, offline build."""

import time
from datetime import date

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from app import config
from app.data import features, weather

RESTAURANT_MISSING = not (config.FIXTURES_DIR / features.RESTAURANT_FIXTURE).exists()
skip_restaurant = pytest.mark.skipif(RESTAURANT_MISSING, reason="restaurant_daily.parquet not built yet (Dewey issue #23)")
BUSINESSES = ["taxi", pytest.param("restaurant", marks=skip_restaurant)]

DTYPES = {
    "revenue": "float64", "dow": "int64", "doy": "int64", "tmax": "float64",
    **{c: "bool" for c in ("is_holiday", "msg_event", "home_game", "home_win", "rain", "rain_open_hours", "estimated")},
}


@pytest.fixture(scope="module")
def taxi_df():
    return features.build("taxi")


@pytest.mark.parametrize("business", BUSINESSES)
def test_feature_table_schema(business):  # C1-A20
    df = features.build(business)
    assert list(df.columns) == features.COLUMNS + ["split"]
    for col, dtype in DTYPES.items():
        assert str(df[col].dtype) == dtype, col
    assert all(isinstance(d, date) for d in df["date"])
    assert df["date"].is_unique and df["date"].is_monotonic_increasing
    assert not df.isna().any().any()
    assert len(df) == (df["date"].max() - df["date"].min()).days + 1
    assert set(df["split"]) == {"train", "holdout"}


def test_feature_derivations():  # C1-A21
    cal = features.calendar(pd.Series(pd.date_range("2024-01-01", "2024-12-31").date))
    assert cal["dow"].iloc[0] == 0  # 2024-01-01 is a Monday
    assert cal["doy"].iloc[-1] == 366
    assert cal["is_holiday"].iloc[0] and not cal["is_holiday"].iloc[1]


def test_holidays_flagged_only_from_config(taxi_df):  # C1-A21
    flagged = set(taxi_df.loc[taxi_df["is_holiday"], "date"])
    in_window = {d for d in config.HOLIDAYS if taxi_df["date"].min() <= d <= taxi_df["date"].max()}
    assert flagged == in_window
    assert date(2024, 11, 28) in flagged and date(2024, 11, 27) not in flagged


def test_home_win_only_on_game_days(taxi_df):  # C1-A22
    assert not (taxi_df["home_win"] & ~taxi_df["home_game"]).any()
    assert not (taxi_df["home_game"] & ~taxi_df["msg_event"]).any()
    assert taxi_df["home_game"].sum() > 100


def test_split_boundary(taxi_df):  # C1-A23
    train = taxi_df[taxi_df["split"] == "train"]
    hold = taxi_df[taxi_df["split"] == "holdout"]
    assert len(train) == config.TRAIN_DAYS
    assert train["date"].iloc[0] == config.WINDOW_START and train["date"].iloc[-1] == config.TRAIN_END
    assert hold["date"].iloc[0] == config.HOLDOUT_START
    assert (train.index.max() + 1) == hold.index.min()


@pytest.mark.parametrize("business, expected", [("taxi", False), pytest.param("restaurant", True, marks=skip_restaurant)])
def test_estimated_flag_by_business(business, expected):  # C1-A24 (I6)
    assert (features.build(business)["estimated"] == expected).all()


def test_no_leakage_of_future(taxi_df):  # C1-A25
    cut = date(2025, 12, 31)
    short = features.build("taxi", end=cut)
    full = taxi_df[taxi_df["date"] <= cut].reset_index(drop=True)
    assert_frame_equal(short, full)
    assert features.event_frequency(short, "rain") == features.event_frequency(taxi_df, "rain")


def test_event_frequency_phat():  # C1-A26
    df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=130).date})
    df["split"] = ["train"] * 100 + ["holdout"] * 30
    df["rain"] = [True] * 27 + [False] * 73 + [True] * 30
    assert features.event_frequency(df, "rain") == pytest.approx(0.27)


def test_thresholds_from_config(taxi_df):  # C1-A27
    assert (config.RAIN_THRESHOLD_IN, config.RAIN_OPEN_HOURS_IN) == (0.01, 0.05)
    loose = features.build("taxi", rain_threshold=0.001, open_hours_threshold=0.01)
    strict = features.build("taxi", rain_threshold=0.5, open_hours_threshold=0.5)
    assert loose["rain"].sum() > taxi_df["rain"].sum() > strict["rain"].sum()
    assert loose["rain_open_hours"].sum() > taxi_df["rain_open_hours"].sum() > strict["rain_open_hours"].sum()
    assert features.hot(taxi_df, 85.0).sum() > features.hot(taxi_df, 95.0).sum() > 0
    s = features.add_settlement(taxi_df, strike=90.0)
    assert {"settle_rain", "settle_hot"} <= set(s.columns)
    assert 0 < features.event_frequency(s, "settle_rain") < 1


def test_settle_hot_is_strictly_above_strike(taxi_df):  # KXHIGHNY: high > strike
    station = weather.load_weather(*config.SETTLEMENT_STATION_LATLON, offline=True).daily.set_index("date")
    tmax = taxi_df["date"].map(station["temperature_2m_max"])
    strike = float(tmax.iloc[0])  # a real station high, so some day sits exactly at the strike
    s = features.add_settlement(taxi_df, strike=strike)
    at = tmax == strike
    assert at.any()
    assert not s.loc[at, "settle_hot"].any()
    assert s["settle_hot"].equals(tmax > strike)


def test_offline_build_end_to_end(monkeypatch):  # C1-A28
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    config.get_settings.cache_clear()
    try:
        for business in ["taxi"] + ([] if RESTAURANT_MISSING else ["restaurant"]):
            t0 = time.perf_counter()
            features.build(business)
            assert time.perf_counter() - t0 < 2.0
    finally:
        config.get_settings.cache_clear()


def test_determinism(taxi_df):  # C1-A29
    assert_frame_equal(features.build("taxi"), taxi_df)


def test_rain_sign_sanity(taxi_df):  # C1-A30
    for dow, g in taxi_df.groupby("dow"):
        ratio = g.loc[g["rain"], "revenue"].mean() / g.loc[~g["rain"], "revenue"].mean()
        assert 0.7 <= ratio <= 1.5, (dow, ratio)


def test_unknown_business():
    with pytest.raises(ValueError, match="unknown business_id"):
        features.build("bakery")


def test_restaurant_missing_fixture_is_clear(tmp_path):
    with pytest.raises(FileNotFoundError, match="restaurant_daily.parquet"):
        features.build("restaurant", fixtures_dir=tmp_path)
