"""Fetch daily TLC aggregates (yellow + high-volume FHV), 2022-01..2025-12.

Per month and service: daily trips and fare totals citywide, plus pickups in zone 186 (MSG area).
Aggregated server-side with SoQL on NYC Open Data's per-year TLC trip datasets (the CloudFront
parquet bucket started returning 403 after ~20 range-read months, so it is not used). Only daily
aggregates are kept (scratchpad r2-cache/tlc/<svc>_<YYYY-MM>.parquet). Also fetches the Central
Park GHCN-Daily record (USW00094728), the station Kalshi's NYC rain/high-temperature contracts
settle on.

Run from backend/: .venv/bin/python ../experiments/bar/r2-taxi/fetch_tlc.py
"""

import calendar
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pandas as pd

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
TLC = CACHE / "tlc"
SODA = "https://data.cityofnewyork.us/resource/{id}.json"
GHCN = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00094728.csv"
ZONE = "186"
DATASETS = {
    "yellow": {2022: "qp3b-zxtp", 2023: "4b4i-vvec", 2024: "rwwi-khbc", 2025: "irx2-vgm4"},
    "fhvhv": {2022: "g6pj-fsah", 2023: "u253-aew4", 2024: "bqxa-629f", 2025: "nt46-nv3c"},
}
TS = {"yellow": "tpep_pickup_datetime", "fhvhv": "pickup_datetime"}
USD = {"yellow": "total_amount", "fhvhv": "base_passenger_fare + tips"}


def month(job: tuple[str, str]) -> str:
    svc, ym = job
    out = TLC / f"{svc}_{ym}.parquet"
    if out.exists():
        return f"{svc} {ym} cached"
    y, m = map(int, ym.split("-"))
    ts, usd = TS[svc], USD[svc]
    params = {
        "$select": f"date_trunc_ymd({ts}) as date, count(*) as trips, sum({usd}) as total, "
        f"sum(case(pulocationid='{ZONE}', 1, true, 0)) as z_trips, "
        f"sum(case(pulocationid='{ZONE}', {usd}, true, 0)) as z_total",
        "$where": f"{ts} between '{ym}-01T00:00:00' and '{ym}-{calendar.monthrange(y, m)[1]:02d}T23:59:59'",
        "$group": "date", "$order": "date", "$limit": "100",
    }
    for attempt in range(4):
        try:
            r = httpx.get(SODA.format(id=DATASETS[svc][y]), params=params, timeout=600)
            r.raise_for_status()
            d = pd.DataFrame(r.json())
            d["date"] = pd.to_datetime(d["date"]).dt.date
            for c in ("trips", "total", "z_trips", "z_total"):
                d[c] = d[c].astype(float)
            d.to_parquet(out)
            return f"{svc} {ym} ok ({len(d)} days)"
        except Exception as e:  # noqa: BLE001
            err = e
    return f"{svc} {ym} FAILED {err!s:.160}"


def main() -> None:
    TLC.mkdir(parents=True, exist_ok=True)
    gh = CACHE / "ghcn_USW00094728.csv"
    if not gh.exists():
        gh.write_bytes(httpx.get(GHCN, timeout=120, follow_redirects=True).content)
    jobs = [(s, f"{y}-{m:02d}") for s in ("yellow", "fhvhv") for y in range(2022, 2026) for m in range(1, 13)]
    with ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 4) as ex:
        for msg in ex.map(month, jobs):
            print(msg, flush=True)


if __name__ == "__main__":
    main()
