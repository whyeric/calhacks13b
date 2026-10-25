"""R6 broadway fetch: public inputs only, cached in the scratchpad r2-cache/ (prefix r6broadway_).

Run from backend/:  .venv/bin/python ../experiments/bar/r6-broadway/fetch.py

- Broadway League weekly grosses per show, 1985-06..2020-03, as redistributed by the R4DS
  TidyTuesday project (2020-04-28, scraped from Playbill). Playbill's robots.txt disallows
  ClaudeBot/anthropic-ai and BroadwayWorld disallows its grosses export, so nothing after
  2020-03 is fetched (see RESULTS.md).
- ESPN Knicks/Rangers schedules (regular season and postseason), seasons 1986..2026.
NOAA GHCN Central Park (USW00094728) is already cached as ghcnd_USW00094728.csv.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
P = "r6broadway_"
GROSSES = "https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2020/2020-04-28/grosses.csv"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/{lg}/teams/{tid}/schedule"
TEAMS = {"knicks": ("basketball/nba", "18"), "rangers": ("hockey/nhl", "13")}
SEASONS = range(1986, 2027)  # ESPN season = year the playoffs end


def get(c: httpx.Client, url: str, **params) -> dict:
    for i in range(5):
        r = c.get(url, params=params)
        if r.status_code == 429:
            time.sleep(1 + i)
            continue
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()
    return {}


def main() -> None:
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        f = CACHE / f"{P}grosses.csv"
        if not f.exists():
            f.write_bytes(c.get(GROSSES).raise_for_status().content)
        for team, (lg, tid) in TEAMS.items():
            for s in SEASONS:
                for t in (2, 3):
                    f = CACHE / f"{P}espn_{team}_{s}_{t}.json"
                    if not f.exists():
                        f.write_text(json.dumps(get(c, ESPN.format(lg=lg, tid=tid), season=s, seasontype=t)))
                        time.sleep(0.2)


if __name__ == "__main__":
    main()
