"""R7 deferral: fetch public inputs into the scratchpad cache (r7deferral_* files).

- MTA daily ridership by mode (data.ny.gov sayj-mze2), 2024-01..2026-09.
- NOAA GHCN daily Central Park USW00094728, 2024..2026.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pandas as pd

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
NCEI = "https://www.ncei.noaa.gov/access/services/data/v1"


def main() -> None:
    p = CACHE / "r7deferral_mta.parquet"
    if not p.exists():
        r = httpx.get("https://data.ny.gov/resource/sayj-mze2.json", timeout=120, params={
            "$where": "date between '2024-01-01' and '2026-09-30T23:59:59'", "$limit": 50000})
        r.raise_for_status()
        pd.DataFrame(r.json()).to_parquet(p)
    print("mta", pd.read_parquet(p)["date"].agg(["min", "max", "count"]).tolist())
    p = CACHE / "r7deferral_ghcn.csv"
    if not p.exists():
        r = httpx.get(NCEI, timeout=300, params={
            "dataset": "daily-summaries", "stations": "USW00094728", "startDate": "2023-12-01",
            "endDate": "2026-10-20", "dataTypes": "PRCP,SNOW,TMAX,TMIN", "units": "standard", "format": "csv"})
        r.raise_for_status()
        p.write_text(r.text)
    print("ghcn", pd.read_csv(p)["DATE"].agg(["min", "max", "count"]).tolist())


if __name__ == "__main__":
    main()
