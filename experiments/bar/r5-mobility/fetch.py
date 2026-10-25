"""Fetch inputs for r5-mobility (playoff nights and NYC mobility) into the scratchpad cache.

Everything lands in r2-cache/ with the prefix r5playoffmobility_ (never the repo).

- TLC hourly aggregates, yellow + high-volume FHV (Uber/Lyft), 2022-01..2026-06, via duckdb httpfs
  over the TLC CloudFront parquet (only the needed columns are range-read; SoQL hourly grouping on
  Open Data took >10 min per month and 2026 is not on Open Data yet). Per pickup hour: citywide
  trips and driver gross; pickups, pickup driver gross and dropoffs for zone 186 (Penn Station /
  Madison Sq West = MSG), the MSG area (186, 100 Garment District, 164 Midtown South) and a fixed set
  of nightlife zones. Driver gross = fare + tip (yellow), driver_pay + tips (HVFHV).
- MTA Subway Hourly Ridership: Beginning 2025 (data.ny.gov 5wq4-mkjj), 2025-01..2026-06, SoQL
  aggregates for complexes 164 and 318 (34 St-Penn) and system-wide. 2022-2024 come from r4mh_*.
- ESPN scoreboards 2026-01-02..2026-06-30 (NBA, NHL); 2022-2025 come from r2-cache/espn/.

Run from backend/:  .venv/bin/python ../experiments/bar/r5-mobility/fetch.py [espn|mta|tlc ...]
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import duckdb
import httpx
import pandas as pd

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
P = "r5playoffmobility_"
TLC = CACHE / f"{P}tlc"
ESPN = CACHE / f"{P}espn"
PARQUET = "https://d37ci6vzurychx.cloudfront.net/trip-data/{svc}_tripdata_{ym}.parquet"
MTA = "https://data.ny.gov/resource/5wq4-mkjj.json"
TS = {"yellow": "tpep_pickup_datetime", "fhvhv": "pickup_datetime"}
USD = {"yellow": "coalesce(fare_amount, 0) + coalesce(tip_amount, 0)",
       "fhvhv": "coalesce(driver_pay, 0) + coalesce(tips, 0)"}
ZONES = {
    "z186": [186],
    "area": [186, 100, 164],
    # East Village, LES, West Village, Greenwich Village N/S, Union Sq, East Chelsea, Flatiron,
    # Clinton East, Williamsburg N/S
    "nl": [79, 148, 249, 113, 114, 234, 68, 90, 48, 255, 256],
}


SODA = "https://data.cityofnewyork.us/resource/{id}.json"
DATASETS = {
    "yellow": {2022: "qp3b-zxtp", 2023: "4b4i-vvec", 2024: "rwwi-khbc", 2025: "irx2-vgm4"},
    "fhvhv": {2022: "g6pj-fsah", 2023: "u253-aew4", 2024: "bqxa-629f", 2025: "nt46-nv3c"},
}
SODA_USD = {"yellow": "fare_amount + tip_amount", "fhvhv": "driver_pay + tips"}


def soql_month(job: tuple[str, str]) -> str:
    """Hourly pickups (count, driver gross) and dropoffs for the MSG-area and nightlife zones, one month.

    Filtered SoQL queries (zone IN (...)) run in seconds; unfiltered hourly GROUP BYs took >10 min.
    """
    svc, ym = job
    out = TLC / f"{svc}_{ym}.parquet"
    if out.exists():
        return f"{svc} {ym} cached"
    y, m = map(int, ym.split("-"))
    ts, usd = TS[svc], SODA_USD[svc]
    nxt = (date(y, m, 28) + timedelta(days=4)).replace(day=1)
    when = f"{ts} >= '{ym}-01T00:00:00' and {ts} < '{nxt}T00:00:00'"
    area = ",".join(f"'{z}'" for z in ZONES["area"])
    nl = ",".join(f"'{z}'" for z in ZONES["nl"])
    hour = f"date_trunc_ymd({ts}) as day, date_extract_hh({ts}) as hh"
    queries = {  # name -> (select, where, group)
        "pu": (f"{hour}, pulocationid as zone, count(*) as n, sum({usd}) as usd", f"pulocationid in ({area})", "day,hh,zone"),
        "do": (f"{hour}, dolocationid as zone, count(*) as n", f"dolocationid in ({area})", "day,hh,zone"),
        "nlpu": (f"{hour}, count(*) as n, sum({usd}) as usd", f"pulocationid in ({nl})", "day,hh"),
        "nldo": (f"{hour}, count(*) as n", f"dolocationid in ({nl})", "day,hh"),
    }
    frames = []
    for name, (sel, where, grp) in queries.items():
        err = None
        for _ in range(4):
            try:
                r = httpx.get(SODA.format(id=DATASETS[svc][y]), timeout=900, params={
                    "$select": sel, "$where": f"{when} and {where}", "$group": grp, "$limit": 50000})
                r.raise_for_status()
                break
            except httpx.HTTPError as e:
                err = e
        else:
            return f"{svc} {ym} FAILED {name} {err!s:.200}"
        d = pd.DataFrame(r.json())
        d["series"] = name
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    d["hour"] = pd.to_datetime(d.pop("day")) + pd.to_timedelta(d.pop("hh").astype(int), unit="h")
    d["zone"] = d.get("zone", pd.Series(dtype=str)).fillna("nl")
    for c in ("n", "usd"):
        d[c] = d[c].astype(float)
    d.to_parquet(out)
    return f"{svc} {ym} ok ({len(d)} rows)"


def tlc_month(job: tuple[str, str]) -> str:
    svc, ym = job
    out = TLC / f"{svc}_{ym}.parquet"
    if out.exists():
        return f"{svc} {ym} cached"
    ts, usd = TS[svc], USD[svc]
    sums = ["count(*) as trips", f"sum({usd}) as usd"]
    for k, ids in ZONES.items():
        z = ",".join(map(str, ids))
        sums += [f"sum(case when PULocationID in ({z}) then 1 else 0 end) as {k}_pu",
                 f"sum(case when PULocationID in ({z}) then {usd} else 0 end) as {k}_pu_usd",
                 f"sum(case when DOLocationID in ({z}) then 1 else 0 end) as {k}_do"]
    y, m = map(int, ym.split("-"))
    nxt = (date(y, m, 28) + timedelta(days=4)).replace(day=1)
    err = None
    for _ in range(3):
        try:
            con = duckdb.connect()
            con.execute("install httpfs; load httpfs; set enable_progress_bar=false;")
            d = con.execute(
                f"select date_trunc('hour', {ts}) as hour, {', '.join(sums)} "
                f"from read_parquet('{PARQUET.format(svc=svc, ym=ym)}') "
                f"where {ts} >= '{ym}-01' and {ts} < '{nxt}' group by 1 order by 1").df()
            for c in d.columns.drop("hour"):
                d[c] = d[c].astype(float)
            d.to_parquet(out)
            return f"{svc} {ym} ok ({len(d)} hours)"
        except Exception as e:  # noqa: BLE001
            err = e
    return f"{svc} {ym} FAILED {err!s:.200}"


def mta_month(m: pd.Period) -> pd.DataFrame:
    a, b = m.start_time.strftime("%Y-%m-%dT00:00:00"), m.end_time.strftime("%Y-%m-%dT23:00:00")
    where = f"transit_timestamp between '{a}' and '{b}'"
    out = []
    for extra, grp in ((" and station_complex_id in ('164','318')", "station_complex_id,transit_timestamp"),
                       ("", "transit_timestamp")):
        for attempt in range(4):
            try:
                r = httpx.get(MTA, params={"$select": f"{grp},sum(ridership) as r", "$where": where + extra,
                                           "$group": grp, "$limit": 50000}, timeout=600)
                r.raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == 3:
                    raise
        d = pd.DataFrame(r.json())
        if "station_complex_id" not in d:
            d["station_complex_id"] = "system"
        out.append(d)
    return pd.concat(out, ignore_index=True)


def espn_day(job: tuple[str, date]) -> None:
    league, day = job
    f = ESPN / league.replace("/", "_") / f"{day:%Y%m%d}.json"
    if f.exists():
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(4):
        try:
            r = httpx.get(f"https://site.api.espn.com/apis/site/v2/sports/{league}/scoreboard",
                          params={"dates": f"{day:%Y%m%d}"}, timeout=30)
            r.raise_for_status()
            f.write_text(json.dumps(r.json()))
            return
        except httpx.HTTPError:
            continue


def main() -> None:
    TLC.mkdir(parents=True, exist_ok=True)
    what = sys.argv[1:] or ["espn", "mta", "tlc"]
    if "espn" in what:
        days = [date(2026, 1, 2) + timedelta(d) for d in range((date(2026, 6, 30) - date(2026, 1, 2)).days + 1)]
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(espn_day, [(lg, d) for lg in ("basketball/nba", "hockey/nhl") for d in days]))
        print("espn done", flush=True)
    if "mta" in what:
        out = CACHE / f"{P}mta2025.parquet"
        if not out.exists():
            with ThreadPoolExecutor(6) as ex:
                d = pd.concat(ex.map(mta_month, pd.period_range("2025-01", "2026-06", freq="M")), ignore_index=True)
            d["r"] = d["r"].astype(float)
            d.to_parquet(out)
        print("mta done", flush=True)
    if "tlc" in what:
        # Apr-Jun (playoffs) first, then the other season months; Jul-Sep have no NBA/NHL games, so under
        # year-month FE they carry no information about game effects and are skipped.
        order = (4, 5, 6, 3, 10, 11, 12, 1, 2)
        jobs = [(s, f"{y}-{m:02d}") for m in order for y in range(2022, 2026) for s in ("fhvhv", "yellow")]
        with ThreadPoolExecutor(6) as ex:
            for msg in ex.map(soql_month, jobs):
                print(msg, flush=True)
    if "tlc2026" in what:  # CloudFront parquet; it 403s after a few months of range reads, so retry later
        jobs = [(s, f"2026-{m:02d}") for m in (4, 5, 6, 3, 2, 1) for s in ("fhvhv", "yellow")]  # playoff months first
        for msg in map(tlc_month, jobs):
            print(msg, flush=True)


if __name__ == "__main__":
    main()
