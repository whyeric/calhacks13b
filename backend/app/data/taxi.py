"""Daily taxi revenue for one TLC zone (spec §4.1).

Raw TLC yellow-taxi monthly Parquet lives in repo-root `data/tlc/` (gitignored). DuckDB reads it in
place, keeps pickups in `TAXI_ZONE_ID`, drops `fare_amount <= 0` and `trip_distance == 0`, and sums
`fare_amount` by local NY date of `tpep_pickup_datetime` (TLC stores wall-clock NY time; tz-aware
inputs are converted). Revenue is metered fares only, no tips or tolls (gap G9).

Gap G3: the output is reindexed to every calendar day in the window. Days with no trips are filled
with revenue 0 / trips 0 explicitly and counted; the build fails above `MAX_MISSING_DAY_SHARE`.

CLI (from backend/): `python -m app.data.taxi` rebuilds `fixtures/taxi_daily.parquet`.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from app import config

log = logging.getLogger(__name__)

FIXTURE_NAME = "taxi_daily.parquet"
COLUMNS = ["date", "revenue", "trips"]


class TaxiBuildError(RuntimeError):
    pass


def _pickup_expr(con: duckdb.DuckDBPyConnection, source: str) -> str:
    """Local NY timestamp expression for the pickup column, whatever tz the files carry."""
    kind = con.execute(f"SELECT typeof(tpep_pickup_datetime) FROM {source} LIMIT 1").fetchone()
    if kind and "WITH TIME ZONE" in kind[0].upper():
        return f"timezone('{config.WEATHER_TZ}', tpep_pickup_datetime)"
    return "tpep_pickup_datetime"


def aggregate(
    files: list[Path] | str,
    zone_id: int = config.TAXI_ZONE_ID,
    start: date = config.WINDOW_START,
    end: date = config.WINDOW_END,
    max_missing_share: float = config.MAX_MISSING_DAY_SHARE,
) -> pd.DataFrame:
    """Daily `date, revenue, trips` for `zone_id`, one row per day in [start, end]."""
    paths = [files] if isinstance(files, str) else [str(p) for p in files]
    if not paths:
        raise TaxiBuildError("no TLC parquet files given")
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone = 'UTC'")
        source = f"read_parquet({paths!r}, union_by_name = true)"
        pickup = _pickup_expr(con, source)
        daily = con.execute(
            f"""
            SELECT CAST({pickup} AS DATE) AS date,
                   ROUND(SUM(fare_amount), 2)::DOUBLE AS revenue,  -- cents; drops float-sum noise
                   COUNT(*)::BIGINT AS trips
            FROM {source}
            WHERE PULocationID = ? AND fare_amount > 0 AND trip_distance <> 0
              AND CAST({pickup} AS DATE) BETWEEN ? AND ?
            GROUP BY 1
            """,
            [zone_id, start, end],
        ).df()
    finally:
        con.close()

    days = pd.date_range(start, end, freq="D").date
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    out = pd.DataFrame({"date": days}).merge(daily, on="date", how="left")
    missing = int(out["trips"].isna().sum())
    share = missing / len(out)
    if share > max_missing_share:
        raise TaxiBuildError(f"{missing} of {len(out)} days have no trips ({share:.1%} > {max_missing_share:.0%})")
    if missing:
        log.warning("taxi: %d day(s) with no trips zero-filled", missing)
    out["revenue"] = out["revenue"].fillna(0.0).astype("float64")
    out["trips"] = out["trips"].fillna(0).astype("int64")
    return out[COLUMNS].sort_values("date").reset_index(drop=True)


def raw_files(raw_dir: Path = config.RAW_TLC_DIR, start: date = config.WINDOW_START, end: date = config.WINDOW_END) -> list[Path]:
    """Monthly files covering the window; raises naming the first missing month."""
    months = pd.period_range(start, end, freq="M")
    files = [raw_dir / f"yellow_tripdata_{m.strftime('%Y-%m')}.parquet" for m in months]
    absent = [f for f in files if not f.exists()]
    if absent:
        raise TaxiBuildError(f"missing raw TLC file {absent[0]} ({len(absent)} month(s) absent)")
    return files


def build(raw_dir: Path = config.RAW_TLC_DIR, out_dir: Path = config.FIXTURES_DIR) -> pd.DataFrame:
    df = aggregate(raw_files(raw_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_dir / FIXTURE_NAME, index=False)
    return df


def load(fixtures_dir: Path = config.FIXTURES_DIR) -> pd.DataFrame:
    path = fixtures_dir / FIXTURE_NAME
    if not path.exists():
        raise FileNotFoundError(f"taxi fixture missing: {path} (run `python -m app.data.taxi`)")
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df = build()
    print(f"{len(df)} days {df['date'].min()}..{df['date'].max()}; median revenue {df['revenue'].median():,.0f}")
