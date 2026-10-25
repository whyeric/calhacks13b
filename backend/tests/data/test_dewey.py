"""C1-A6..A11: Dewey weekly -> daily series. Synthetic inputs plus the checked-in aggregates."""

import logging
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.config import get_settings
from app.data import dewey

HERE = Path(__file__).parent / "fixtures"
WEEKLY = HERE / "dewey_weekly.parquet"


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    for key in ("AVG_CHECK_USD", "DEWEY_RESTAURANTS_DIR", "DEWEY_MSG_DIR", "DEWEY_PLACE_ID"):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def week(store="s1", start="2024-01-01", vbd="[1,2,3,4,5,6,7]"):
    return pd.DataFrame({"ID_STORE": [store], "DATE_RANGE_START": [pd.Timestamp(start)], "VISITS_BY_DAY": [vbd]})


def test_c1_a6_explodes_week_to_7_days():
    out = dewey.explode_weeks(week())
    assert list(out["date"]) == [date(2024, 1, 1) + timedelta(days=i) for i in range(7)]
    assert list(out["visits"]) == [1, 2, 3, 4, 5, 6, 7]
    assert out["visits"].sum() == 28


def test_c1_a6_overlapping_weeks_dedupe():
    df = pd.concat([week(vbd="[1,1,1,1,1,1,1]"), week(start="2024-01-04", vbd="[5,5,5,5,5,5,5]")])
    out = dewey.explode_weeks(df)
    assert out["date"].is_unique and len(out) == 10
    by_date = out.set_index("date")["visits"]
    assert by_date[date(2024, 1, 3)] == 1 and by_date[date(2024, 1, 4)] == 5


def test_c1_a7_filters():
    raw = pd.read_parquet(WEEKLY)
    kept = dewey.filter_weekly(raw)
    assert set(kept["ID_STORE"]) == {"s_keep", "s_msgzip"}
    assert (pd.to_datetime(kept["DATE_RANGE_START"]) >= "2024-01-01").all()
    # Same filters pushed down through duckdb on the parquet file.
    pushed = dewey.read_weekly(HERE)
    assert sorted(pushed["ID_STORE"]) == sorted(kept["ID_STORE"])
    assert "LOCATION_NAME" not in pushed.columns and "STREET_ADDRESS" not in pushed.columns


def test_c1_a7_ticker_routes_to_msg():
    rest, msg = pd.DataFrame({"x": [1]}), pd.DataFrame({"date": [date(2024, 1, 1)], "visits": [9], "spike": [False]})
    assert dewey.rows_for_ticker("NBA-A", rest, msg) is msg
    with pytest.raises(KeyError):
        dewey.rows_for_ticker("UNKNOWN", rest, msg)


def store_days(visits):
    d0 = date(2024, 1, 1)
    return pd.DataFrame({"store_id": "s1", "date": [d0 + timedelta(days=i) for i in range(len(visits))], "visits": visits})


def test_c1_a8_revenue_est_and_flag(monkeypatch):
    visits = [100, 120, 87, 0, 333, 41, 99]
    out = dewey.build_restaurant_daily(store_days(visits), avg_check_usd=Decimal("35"))
    assert list(out["revenue_est"]) == [v * 35.0 for v in visits]
    assert out["estimated"].all()
    assert out["place_id"].nunique() == 1 and out["place_id"].iloc[0] != "s1"

    monkeypatch.setenv("AVG_CHECK_USD", "35")
    get_settings.cache_clear()
    base = dewey.build_restaurant_daily(store_days(visits))["revenue_est"]
    monkeypatch.setenv("AVG_CHECK_USD", "70")
    get_settings.cache_clear()
    doubled = dewey.build_restaurant_daily(store_days(visits))["revenue_est"]
    assert list(doubled) == [2 * b for b in base]


@pytest.mark.parametrize("bad", ["[1,2,3,4,5,6]", None, "not json", '{"a": 1}', "[1,2,3,4,5,6,-1]"])
def test_c1_a9_malformed_week(bad, caplog):
    good = week(start="2024-01-08", vbd="[7,7,7,7,7,7,7]")
    df = pd.concat([week(vbd=bad), good])
    with pytest.raises(dewey.MalformedWeekError):
        dewey.explode_weeks(df, strict=True)
    with caplog.at_level(logging.WARNING):
        out = dewey.explode_weeks(df)
    assert "skipped 1 malformed" in caplog.text
    assert out.attrs["skipped_weeks"] == 1
    # The good week keeps its own dates; nothing shifts into the bad week's slot.
    assert list(out["date"]) == [date(2024, 1, 8) + timedelta(days=i) for i in range(7)]
    assert (out["visits"] == 7).all()


def synthetic_raw(data_dir: Path, weeks: int = 8) -> None:
    """Two raw-shaped folders: restaurants (3 stores, with names/addresses) and MSG (1 store)."""
    rng = np.random.default_rng(2)

    def rows(store, zip_, naics):
        return [
            {
                "ID_STORE": store, "POSTAL_CODE": zip_, "NAICS_CODE": naics,
                "DATE_RANGE_START": pd.Timestamp("2024-01-01") + pd.Timedelta(weeks=w),
                "VISITS_BY_DAY": str(list(map(int, rng.integers(50, 150, size=7)))),
                "LOCATION_NAME": f"Name {store}", "STREET_ADDRESS": "1 Secret St", "BRAND": "Brand",
                "LATITUDE": 40.75, "LONGITUDE": -73.99,
            }
            for w in range(weeks)
        ]

    rest = rows("s_a", "10001", "722410") + rows("s_b", "10119", "722511") + rows("s_far", "90210", "722511")
    for name, data in (("rest", rest), ("msg", rows("s_msg", "10001", "711211"))):
        (data_dir / name).mkdir()
        pd.DataFrame(data).to_parquet(data_dir / name / "w.parquet", index=False)


def test_c1_a10_no_pii_in_built_series(tmp_path, monkeypatch):
    synthetic_raw(tmp_path)
    monkeypatch.setenv("DEWEY_PLACE_ID", "s_a")
    get_settings.cache_clear()
    out_dir = tmp_path / "out"
    dewey.build(out_dir=out_dir, data_dir=tmp_path)
    for name, columns in (("restaurant_daily", dewey.RESTAURANT_COLUMNS), ("msg_visits_daily", dewey.MSG_COLUMNS)):
        path = out_dir / f"{name}.parquet"
        df = pd.read_parquet(path)
        assert list(df.columns) == columns
        dates = pd.to_datetime(df["date"])
        assert dates.is_unique and dates.is_monotonic_increasing
        assert len(df) == (dates.max() - dates.min()).days + 1 == 8 * 7
        assert df["visits"].dtype == np.int64
        raw_bytes = path.read_bytes()
        for secret in (b"Name s_", b"Secret St", b"Brand", b"s_a", b"s_msg"):
            assert secret not in raw_bytes
    rest = pd.read_parquet(out_dir / "restaurant_daily.parquet")
    assert rest["estimated"].all()
    assert set(rest["place_id"]) == {dewey.place_hash("s_a")}


def baseline(n):
    # Bounded noise: |x - median| <= MAD, so only real spikes clear median + 2 x MAD.
    return pd.Series(1000 + 10 * np.tile([-1, 1, 0, 1, -1, 0, 1], n // 7 + 1)[:n])


def test_c1_a11_msg_spike_rule():
    visits = baseline(120)
    spikes = [40, 70, 100]
    visits[spikes] = 1600
    flags = dewey.spike_flags(visits)
    assert list(np.flatnonzero(flags)) == spikes


def test_c1_a11_spike_rule_is_past_only():
    visits = baseline(90)
    visits[[30, 60]] = 1600
    full = dewey.spike_flags(visits)
    truncated = dewey.spike_flags(visits[:61])
    assert truncated.equals(full[:61])


def test_resolve_dirs_autodetects_msg(tmp_path):
    weekly = pd.read_parquet(WEEKLY)
    (tmp_path / "aaa").mkdir()
    (tmp_path / "bbb").mkdir()
    weekly.to_parquet(tmp_path / "aaa" / "x.parquet")
    weekly[weekly["ID_STORE"] == "s_keep"].to_parquet(tmp_path / "bbb" / "x.parquet")
    assert dewey.resolve_dirs(tmp_path) == (tmp_path / "aaa", tmp_path / "bbb")


def test_resolve_dirs_env_override(tmp_path, monkeypatch):
    for name in ("r", "m"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("DEWEY_RESTAURANTS_DIR", "r")
    monkeypatch.setenv("DEWEY_MSG_DIR", str(tmp_path / "m"))
    get_settings.cache_clear()
    assert dewey.resolve_dirs(tmp_path) == (tmp_path / "r", tmp_path / "m")


def test_missing_days_over_two_percent_fail():
    days = store_days(list(range(100)))
    with pytest.raises(ValueError, match="missing"):
        dewey.build_restaurant_daily(days.drop(index=range(10, 15)))
