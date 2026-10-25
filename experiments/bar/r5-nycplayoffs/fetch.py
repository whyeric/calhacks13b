"""R5 nycplayoffs fetch: ESPN team schedules (regular + postseason) and Kalshi advancement markets.

Run from backend/:  .venv/bin/python ../experiments/bar/r5-nycplayoffs/fetch.py
Everything lands in the scratchpad r2-cache/ with the r5nycplayoffs_ prefix (public data only).
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import httpx

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
P = "r5nycplayoffs_"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/{lg}/teams/{tid}/schedule"
TEAMS = {"knicks": ("basketball/nba", "18"), "rangers": ("hockey/nhl", "13")}
SEASONS = (2022, 2023, 2024, 2025, 2026)  # ESPN season = year the playoffs end
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = ["KXNBASERIES", "KXNHLSERIES", "KXNBAEAST", "KXNHLEAST", "KXNBA", "KXNHL", "KXNBAPLAYOFF",
          "KXNHLPLAYOFF", "KXNBAECFQUAL", "KXTEAMSINNBAEF", "KXTEAMSINNBAF", "KXTEAMSINSC", "KXNBASERIESSCORE",
          "KXNHLSERIESSCORE", "KXNBAPLAYOFFWINS", "KXNBAGAME7", "KXNBAFINALSEXACT", "KXNHLFINALSEXACT",
          "KXNBAHOMECLINCH", "KXNBAPOLOSE", "KXNBASERIESGAMES", "KXNHLSERIESGAMES"]
NY_SIDES = ("NYK", "NYR")


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
    r.raise_for_status()
    return {}


def espn(c: httpx.Client) -> None:
    for team, (lg, tid) in TEAMS.items():
        for s in SEASONS:
            for t in (2, 3):
                f = CACHE / f"{P}espn_{team}_{s}_{t}.json"
                if not f.exists():
                    f.write_text(json.dumps(get(c, ESPN.format(lg=lg, tid=tid), season=s, seasontype=t)))


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def markets(c: httpx.Client, series: str) -> list[dict]:
    """Live markets plus the /historical archive (markets settled before the archive cutoff)."""
    out = []
    for path, src in (("/markets", "live"), ("/historical/markets", "historical")):
        cur = None
        while True:
            d = get(c, f"{KALSHI}{path}", series_ticker=series, limit=1000, **({"cursor": cur} if cur else {}))
            out += [m | {"_src": src} for m in d.get("markets", [])]
            cur = d.get("cursor")
            if not cur or not d.get("markets"):
                break
    seen, uniq = set(), []
    for m in out:
        if m["ticker"] not in seen:
            seen.add(m["ticker"])
            uniq.append(m)
    return uniq


def is_ny(m: dict) -> bool:
    """NY team side of the market, or an event (series) the NY team plays in."""
    side = m["ticker"].rsplit("-", 1)[-1]
    return side in NY_SIDES or any(k in m["event_ticker"] for k in NY_SIDES)


def kalshi(c: httpx.Client) -> None:
    for s in SERIES:
        f = CACHE / f"{P}mk_{s}.json"
        if not f.exists():
            ms = markets(c, s)
            f.write_text(json.dumps(ms))
            print(s, len(ms), "markets,", sum(map(is_ny, ms)), "NY")
    # daily candles over each NY market's life (one call: far below the 5000-candle cap)
    for s in SERIES:
        for m in json.loads((CACHE / f"{P}mk_{s}.json").read_text()):
            f = CACHE / f"{P}cd_{m['ticker']}.json"
            if not is_ny(m) or f.exists():
                continue
            path = (f"/historical/markets/{m['ticker']}/candlesticks" if m["_src"] == "historical"
                    else f"/series/{s}/markets/{m['ticker']}/candlesticks")
            d = get(c, f"{KALSHI}{path}", start_ts=_ts(m["open_time"]) - 86400,
                    end_ts=_ts(m["close_time"]) + 86400, period_interval=1440)
            f.write_text(json.dumps(d.get("candlesticks", [])))


if __name__ == "__main__":
    with httpx.Client(timeout=60) as c:
        espn(c)
        kalshi(c)
