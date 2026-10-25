"""Fetch inputs for r7-displacement into the scratchpad cache (prefix r7displacement_, never the repo).

- MTA subway entries at MANHATTAN stations, 18:00-23:59, per day, 2024-01..2026-09, via SoQL
  aggregation on data.ny.gov (wujg-7c2s for 2024, 5wq4-mkjj for 2025+).
- TLC high-volume FHV (Uber/Lyft) trips ending in Manhattan nightlife zones with pickup 18:00-23:59,
  per day, 2024-01..2025-12, via SoQL on NYC Open Data (CloudFront parquet returns 403).
- ESPN schedules: Yankees/Mets postseason, Giants/Jets, Super Bowl, NCAA men's tournament, USA at the
  2026 World Cup and the World Cup final.

Run from backend/:  .venv/bin/python ../experiments/bar/r7-displacement/fetch.py [mta|tlc|espn ...]
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
P = "r7displacement_"
TLC = CACHE / f"{P}tlc"
ESPN = CACHE / f"{P}espn"
MTA = {2024: "https://data.ny.gov/resource/wujg-7c2s.json", 2025: "https://data.ny.gov/resource/5wq4-mkjj.json"}
SODA = "https://data.cityofnewyork.us/resource/{id}.json"
FHVHV = {2024: "bqxa-629f", 2025: "nt46-nv3c"}  # 2026 is not on Open Data yet
# Manhattan nightlife zones (as in r5-mobility, Williamsburg dropped): East Village, LES, West Village,
# Greenwich Village N/S, Union Sq, East Chelsea, Flatiron, Clinton East
NIGHTLIFE = [79, 148, 249, 113, 114, 234, 68, 90, 48]
SITE = "https://site.api.espn.com/apis/site/v2/sports"


def get(url: str, **params) -> httpx.Response:
    for attempt in range(4):
        try:
            r = httpx.get(url, params=params, timeout=600, follow_redirects=True)
            r.raise_for_status()
            return r
        except httpx.HTTPError:
            if attempt == 3:
                raise
    raise RuntimeError


def mta_month(m: pd.Period) -> pd.DataFrame:
    url = MTA[2024] if m.year == 2024 else MTA[2025]
    a, b = m.start_time.strftime("%Y-%m-%dT00:00:00"), m.end_time.strftime("%Y-%m-%dT23:00:00")
    r = get(url, **{"$select": "date_trunc_ymd(transit_timestamp) as day, sum(ridership) as r",
                    "$where": f"transit_timestamp between '{a}' and '{b}' and borough = 'Manhattan' "
                              f"and date_extract_hh(transit_timestamp) >= 18",
                    "$group": "day", "$limit": 5000})
    return pd.DataFrame(r.json())


def tlc_day(d: date) -> dict:
    """Evening (pickup 18:00-23:59) FHV trips ending in Manhattan nightlife zones on day d.

    CloudFront 403s, so this is SoQL on NYC Open Data. A month-level GROUP BY on the pickup hour ran
    >15 min; one plain range count per day takes ~2 s.
    """
    zones = ",".join(f"'{z}'" for z in NIGHTLIFE)
    r = get(SODA.format(id=FHVHV[d.year]), **{
        "$select": "count(*) as n",
        "$where": f"pickup_datetime >= '{d}T18:00:00' and pickup_datetime < '{d + timedelta(1)}T00:00:00' "
                  f"and dolocationid in ({zones})"})
    return {"day": str(d), "n": float(r.json()[0]["n"])}


def espn(path: str, name: str, **params) -> None:
    f = ESPN / f"{name}.json"
    if f.exists():
        return
    f.write_text(json.dumps(get(f"{SITE}/{path}", **params).json()))


def main() -> None:
    TLC.mkdir(parents=True, exist_ok=True)
    ESPN.mkdir(parents=True, exist_ok=True)
    what = sys.argv[1:] or ["espn", "mta", "tlc"]
    if "espn" in what:
        for team in ("nyy", "nym"):
            for season in (2024, 2025):
                espn(f"baseball/mlb/teams/{team}/schedule", f"mlb_{team}_{season}", season=season, seasontype=3)
        for team in ("nyg", "nyj"):
            for season in (2023, 2024, 2025, 2026):
                for st in (2, 3):
                    espn(f"football/nfl/teams/{team}/schedule", f"nfl_{team}_{season}_{st}", season=season, seasontype=st)
        for season in (2023, 2024, 2025):  # Super Bowl = NFL postseason week 5
            espn("football/nfl/scoreboard", f"nfl_sb_{season}", seasontype=3, week=5, dates=season)
        days = [date(y, 3, 14) + timedelta(d) for y in (2024, 2025, 2026) for d in range(28)]
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(lambda d: espn("basketball/mens-college-basketball/scoreboard", f"ncaa_{d:%Y%m%d}",
                                       dates=f"{d:%Y%m%d}", groups=100, limit=100), days))
        wc = [date(2026, 6, 11) + timedelta(d) for d in range(40)]
        with ThreadPoolExecutor(8) as ex:
            list(ex.map(lambda d: espn("soccer/fifa.world/scoreboard", f"wc_{d:%Y%m%d}", dates=f"{d:%Y%m%d}"), wc))
        print("espn done", flush=True)
    if "mta" in what:
        out = CACHE / f"{P}mta_eve.parquet"
        if not out.exists():
            with ThreadPoolExecutor(6) as ex:
                d = pd.concat(ex.map(mta_month, pd.period_range("2024-01", "2026-09", freq="M")), ignore_index=True)
            d["r"] = d["r"].astype(float)
            d.to_parquet(out)
        print("mta done", flush=True)
    if "tlc" in what:
        out = TLC / "fhvhv_daily.parquet"
        if not out.exists():
            days = [date(2024, 1, 1) + timedelta(i) for i in range((date(2025, 12, 31) - date(2024, 1, 1)).days + 1)]
            with ThreadPoolExecutor(8) as ex:
                pd.DataFrame(list(ex.map(tlc_day, days))).to_parquet(out)
        print("tlc done", flush=True)

if __name__ == "__main__":
    main()
