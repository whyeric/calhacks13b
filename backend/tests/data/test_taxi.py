"""C1-A1..A5: taxi daily aggregation and the checked-in fixture."""

from datetime import date, datetime

import pandas as pd
import pytest

from app import config
from app.data import taxi

ZONE = config.TAXI_ZONE_ID


def _write(tmp_path, rows):
    df = pd.DataFrame(rows, columns=["tpep_pickup_datetime", "PULocationID", "fare_amount", "trip_distance"])
    df["tpep_pickup_datetime"] = pd.to_datetime(df["tpep_pickup_datetime"]).astype("datetime64[us]")
    df["PULocationID"] = df["PULocationID"].astype("int32")
    path = tmp_path / "yellow_tripdata_test.parquet"
    df.to_parquet(path, index=False)
    return [path]


def test_taxi_aggregates_by_local_date(tmp_path):  # C1-A1
    rows = [
        (datetime(2024, 1, 1, 23, 30), ZONE, 10.0, 1.2),
        (datetime(2024, 1, 2, 0, 30), ZONE, 20.5, 2.0),
        (datetime(2024, 1, 1, 8, 0), ZONE, 7.25, 0.8),
        (datetime(2024, 1, 2, 12, 0), ZONE, 15.0, 3.1),
        (datetime(2024, 1, 3, 9, 0), ZONE, 0.1, 0.1),
        (datetime(2024, 1, 3, 23, 59), ZONE, 33.3, 9.0),
    ] + [(datetime(2024, 1, d, 12, 0), 999, 50.0, 4.0) for d in (1, 1, 2, 2, 3, 3)]
    out = taxi.aggregate(_write(tmp_path, rows), ZONE, date(2024, 1, 1), date(2024, 1, 3))
    by = out.set_index("date")
    assert by.loc[date(2024, 1, 1), "trips"] == 2
    assert by.loc[date(2024, 1, 1), "revenue"] == pytest.approx(17.25, abs=1e-9)
    assert by.loc[date(2024, 1, 2), "revenue"] == pytest.approx(35.5, abs=1e-9)
    assert by.loc[date(2024, 1, 3), "trips"] == 2
    assert out["trips"].sum() == 6  # zone 999 dropped


def test_taxi_handles_tz_aware_timestamps(tmp_path):  # C1-A1 UTC-stored edge
    df = pd.DataFrame(
        {
            # 03:30 UTC on Jan 2 is 22:30 NY on Jan 1.
            "tpep_pickup_datetime": pd.to_datetime(["2024-01-02T03:30:00Z", "2024-01-02T17:00:00Z"]),
            "PULocationID": [ZONE, ZONE],
            "fare_amount": [10.0, 5.0],
            "trip_distance": [1.0, 1.0],
        }
    )
    path = tmp_path / "tz.parquet"
    df.to_parquet(path, index=False)
    out = taxi.aggregate([path], ZONE, date(2024, 1, 1), date(2024, 1, 2)).set_index("date")
    assert out.loc[date(2024, 1, 1), "revenue"] == 10.0
    assert out.loc[date(2024, 1, 2), "revenue"] == 5.0


def test_taxi_drops_bad_rows(tmp_path):  # C1-A2
    rows = [
        (datetime(2024, 1, 1, 10), ZONE, 0.0, 1.0),
        (datetime(2024, 1, 1, 11), ZONE, -3.5, 1.0),
        (datetime(2024, 1, 1, 12), ZONE, 12.0, 0.0),
        (datetime(2024, 1, 1, 13), ZONE, 9.0, 1.5),
    ]
    out = taxi.aggregate(_write(tmp_path, rows), ZONE, date(2024, 1, 1), date(2024, 1, 1))
    assert out["trips"].tolist() == [1]
    assert out["revenue"].tolist() == [9.0]


def test_taxi_fills_missing_days(tmp_path):  # C1-A3
    rows = [(datetime(2024, 1, 1) + pd.Timedelta(days=d - 1, hours=12), ZONE, 10.0, 1.0) for d in range(1, 61) if d != 15]
    out = taxi.aggregate(_write(tmp_path, rows), ZONE, date(2024, 1, 1), date(2024, 2, 29))
    assert len(out) == 60
    gap = out.set_index("date").loc[date(2024, 1, 15)]
    assert gap["revenue"] == 0.0 and gap["trips"] == 0


def test_taxi_fails_above_missing_share(tmp_path):  # gap G3
    rows = [(datetime(2024, 1, d, 12), ZONE, 10.0, 1.0) for d in range(1, 11)]
    with pytest.raises(taxi.TaxiBuildError, match="no trips"):
        taxi.aggregate(_write(tmp_path, rows), ZONE, date(2024, 1, 1), date(2024, 1, 31))


def test_taxi_cache_roundtrip(tmp_path):  # C1-A4
    rows = [(datetime(2024, 1, d, 12), ZONE, 10.0 + d, 1.0) for d in range(1, 8)]
    out = taxi.aggregate(_write(tmp_path, rows), ZONE, date(2024, 1, 1), date(2024, 1, 7))
    out.to_parquet(tmp_path / taxi.FIXTURE_NAME, index=False)
    back = taxi.load(tmp_path)
    assert list(back.columns) == taxi.COLUMNS
    assert str(back["revenue"].dtype) == "float64" and str(back["trips"].dtype) == "int64"
    assert all(isinstance(d, date) for d in back["date"])
    assert back["date"].is_unique and back["date"].is_monotonic_increasing
    assert not back["revenue"].isna().any()


def test_taxi_fixture_sanity():  # C1-A5
    df = taxi.load()
    assert df["date"].min() == config.WINDOW_START and df["date"].max() == config.WINDOW_END
    assert len(df) == (config.WINDOW_END - config.WINDOW_START).days + 1
    assert (df["revenue"] > 0).all()
    median = df["revenue"].median()
    lo, hi = config.TAXI_MEDIAN_BAND_USD
    assert lo <= median <= hi
    assert not (df["revenue"] > 5 * median).any()
