"""R8 dcshutdown: aggregate Capital Bikeshare trip zips to station x day x time-band counts.

Run from backend/:  .venv/bin/python ../experiments/bar/r8-dcshutdown/build.py
Reads r2-cache/r8dc_cabi/*.zip (public, s3.amazonaws.com/capitalbikeshare-data), extracts one CSV at a
time into a temp dir, aggregates with duckdb and deletes the extract. Writes
r2-cache/r8dc_station_day.parquet: date, band, key (station number or name), name, lat, lng, n
where n counts trip starts plus trip ends at the station (a "touch").
"""
from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

import duckdb
import pandas as pd

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
ZIPS = CACHE / "r8dc_cabi"
OUT = CACHE / "r8dc_station_day.parquet"
BAND = """CASE WHEN h BETWEEN 6 AND 9 THEN 'am' WHEN h BETWEEN 10 AND 14 THEN 'lunch'
               WHEN h BETWEEN 15 AND 19 THEN 'pm' ELSE 'night' END"""


def agg_csv(con: duckdb.DuckDBPyConnection, csv: Path) -> pd.DataFrame:
    cols = [c.lower() for c in con.execute(f"SELECT * FROM read_csv_auto('{csv}', all_varchar=true) LIMIT 0").df().columns]
    if "started_at" in cols:  # 2020-04+ schema
        legs = [("started_at", "start_station_id", "start_station_name", "start_lat", "start_lng"),
                ("ended_at", "end_station_id", "end_station_name", "end_lat", "end_lng")]
    else:
        legs = [('"Start date"', '"Start station number"', '"Start station"', "NULL", "NULL"),
                ('"End date"', '"End station number"', '"End station"', "NULL", "NULL")]
    parts = []
    for ts, sid, name, lat, lng in legs:
        parts.append(f"""
            SELECT CAST(TRY_CAST({ts} AS TIMESTAMP) AS DATE) AS date,
                   hour(TRY_CAST({ts} AS TIMESTAMP)) AS h,
                   COALESCE(NULLIF({sid}, ''), {name}) AS key, {name} AS name,
                   TRY_CAST({lat} AS DOUBLE) AS lat, TRY_CAST({lng} AS DOUBLE) AS lng
            FROM read_csv_auto('{csv}', all_varchar=true)
            WHERE {name} IS NOT NULL AND {name} <> ''""")
    q = f"""
        SELECT date, {BAND} AS band, key, any_value(name) AS name,
               median(lat) AS lat, median(lng) AS lng, count(*) AS n
        FROM ({' UNION ALL '.join(parts)}) t
        WHERE date IS NOT NULL
        GROUP BY 1, 2, 3"""
    return con.execute(q).df()


def main() -> None:
    con = duckdb.connect()
    frames = []
    for z in sorted(ZIPS.glob("*.zip")):
        tmp = Path(tempfile.mkdtemp(dir=CACHE, prefix="r8dc_x_"))
        try:
            with zipfile.ZipFile(z) as zf:
                for member in zf.namelist():
                    if not member.endswith(".csv") or "__MACOSX" in member:
                        continue
                    p = Path(zf.extract(member, tmp))
                    frames.append(agg_csv(con, p))
                    p.unlink()
        finally:
            shutil.rmtree(tmp)
        print(z.name, sum(len(f) for f in frames))
    df = pd.concat(frames, ignore_index=True)
    df = (df.groupby(["date", "band", "key"], as_index=False)
            .agg(name=("name", "first"), lat=("lat", "median"), lng=("lng", "median"), n=("n", "sum")))
    df.to_parquet(OUT)
    print(OUT, len(df), df.date.min(), df.date.max())


if __name__ == "__main__":
    main()
