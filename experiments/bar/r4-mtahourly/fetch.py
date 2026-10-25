"""Fetch inputs for r4-mtahourly into the scratchpad cache (never the repo).

- MTA Subway Hourly Ridership 2020-2024 (data.ny.gov wujg-7c2s), SoQL aggregates only, 2022-01..2024-12:
    stations: hourly entries summed over payment/fare class for complexes
      164 34 St-Penn Station (A,C,E), 318 34 St-Penn Station (1,2,3), 607 34 St-Herald Sq,
      611 Times Sq-42 St, 610 Grand Central-42 St
    system: hourly entries summed over all complexes
- NOAA LCD Central Park (72505394728 = USW00094728) HourlyPrecipitation, FM-15 rows, 2022..2024.

Run from backend/:  .venv/bin/python ../experiments/bar/r4-mtahourly/fetch.py
"""

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pandas as pd

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
MTA = "https://data.ny.gov/resource/wujg-7c2s.json"
LCD = "https://www.ncei.noaa.gov/access/services/data/v1"
STATIONS = ("164", "318", "607", "611", "610")
MONTHS = pd.period_range("2022-01", "2024-12", freq="M")


def soql(params: dict) -> list[dict]:
    for attempt in range(4):
        try:
            r = httpx.get(MTA, params={**params, "$limit": 50000}, timeout=300)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            if attempt == 3:
                raise
    return []


def month_where(m: pd.Period) -> str:
    a = m.start_time.strftime("%Y-%m-%dT00:00:00")
    b = m.end_time.strftime("%Y-%m-%dT23:00:00")
    return f"transit_timestamp between '{a}' and '{b}'"


def stations_month(m: pd.Period) -> pd.DataFrame:
    ids = ",".join(f"'{s}'" for s in STATIONS)
    rows = soql({
        "$select": "station_complex_id,transit_timestamp,sum(ridership) as r",
        "$where": f"{month_where(m)} and station_complex_id in ({ids})",
        "$group": "station_complex_id,transit_timestamp",
    })
    assert len(rows) < 50000
    return pd.DataFrame(rows)


def system_month(m: pd.Period) -> pd.DataFrame:
    rows = soql({
        "$select": "transit_timestamp,sum(ridership) as r",
        "$where": month_where(m),
        "$group": "transit_timestamp",
    })
    return pd.DataFrame(rows)


def lcd_year(y: int) -> pd.DataFrame:
    r = httpx.get(LCD, params={
        "dataset": "local-climatological-data", "stations": "72505394728",
        "startDate": f"{y}-01-01", "endDate": f"{y}-12-31",
        "dataTypes": "HourlyPrecipitation", "format": "csv"}, timeout=300)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text), dtype=str)


def main() -> None:
    out_st, out_sys, out_lcd = CACHE / "r4mh_stations.parquet", CACHE / "r4mh_system.parquet", CACHE / "r4mh_lcd.csv"
    with ThreadPoolExecutor(6) as ex:
        if not out_st.exists():
            st = pd.concat(ex.map(stations_month, MONTHS), ignore_index=True)
            st["r"] = st["r"].astype(float)
            st.to_parquet(out_st)
            print("stations", len(st))
        if not out_sys.exists():
            sy = pd.concat(ex.map(system_month, MONTHS), ignore_index=True)
            sy["r"] = sy["r"].astype(float)
            sy.to_parquet(out_sys)
            print("system", len(sy))
        if not out_lcd.exists():
            pd.concat(ex.map(lcd_year, (2022, 2023, 2024)), ignore_index=True).to_csv(out_lcd, index=False)
            print("lcd done")


if __name__ == "__main__":
    main()
