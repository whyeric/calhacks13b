"""R6 tvpower fetch: ESPN schedules for Philadelphia / Pittsburgh / Chicago teams, Open-Meteo hourly
temperature for the load zones, and the Kalshi sports series list (for the basis section).

Run from backend/:  .venv/bin/python ../experiments/bar/r6-tvpower/fetch.py
Everything lands in the scratchpad r2-cache/ with the r6tvpower_ prefix (public data only).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
P = "r6tvpower_"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/{lg}/teams/{tid}/schedule"
# team -> (city, league path, ESPN id)
TEAMS = {
    "eagles": ("phl", "football/nfl", "21"), "phillies": ("phl", "baseball/mlb", "22"),
    "flyers": ("phl", "hockey/nhl", "15"), "sixers": ("phl", "basketball/nba", "20"),
    "steelers": ("pit", "football/nfl", "23"), "penguins": ("pit", "hockey/nhl", "16"),
    "pirates": ("pit", "baseball/mlb", "23"),
    "bears": ("chi", "football/nfl", "3"), "cubs": ("chi", "baseball/mlb", "16"),
    "whitesox": ("chi", "baseball/mlb", "4"), "blackhawks": ("chi", "hockey/nhl", "4"),
    "bulls": ("chi", "basketball/nba", "4"),
}
SEASONS = range(2002, 2019)  # ESPN season: NFL/MLB = calendar year it starts, NBA/NHL = year it ends
CITIES = {"phl": (39.95, -75.17), "pit": (40.44, -80.00), "chi": (41.88, -87.63),
          "cmh": (39.96, -83.00), "ric": (37.54, -77.44)}  # cmh = AEP (Columbus), ric = DOM (Richmond)
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"


def get(c: httpx.Client, url: str, **params) -> dict:
    for i in range(6):
        r = c.get(url, params=params)
        if r.status_code == 429:
            time.sleep(2 + 2 * i)
            continue
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return {}


def espn(c: httpx.Client) -> None:
    for team, (_, lg, tid) in TEAMS.items():
        for s in SEASONS:
            for t in (2, 3):
                f = CACHE / f"{P}espn_{team}_{s}_{t}.json"
                if not f.exists():
                    f.write_text(json.dumps(get(c, ESPN.format(lg=lg, tid=tid), season=s, seasontype=t)))


def weather(c: httpx.Client) -> None:
    for city, (lat, lon) in CITIES.items():
        f = CACHE / f"{P}temp_{city}.json"
        if not f.exists():
            f.write_text(json.dumps(get(c, "https://archive-api.open-meteo.com/v1/archive", latitude=lat,
                                        longitude=lon, start_date="2002-01-01", end_date="2018-08-31",
                                        hourly="temperature_2m", temperature_unit="fahrenheit",
                                        timezone="America/New_York")))


def kalshi(c: httpx.Client) -> None:
    f = CACHE / f"{P}series.json"
    if not f.exists():
        f.write_text(json.dumps(get(c, f"{KALSHI}/series", category="Sports")))


if __name__ == "__main__":
    with httpx.Client(timeout=120) as c:
        espn(c)
        weather(c)
        kalshi(c)
