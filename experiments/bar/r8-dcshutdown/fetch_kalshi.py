"""R8 dcshutdown: pull every Kalshi shutdown-related market (live + historical archive) and daily candles.

Run from backend/:  .venv/bin/python ../experiments/bar/r8-dcshutdown/fetch_kalshi.py
Writes r2-cache/r8dc_kalshi_markets.json and r8dc_kalshi_candles.json (public data).
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import httpx

API = "https://api.elections.kalshi.com/trade-api/v2"
CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
SERIES = [
    "KXGOVSHUT", "GOVSHUT", "SHUTLENGTH", "KXSHUTLENGTH", "GOVSHUTLENGTH", "KXGOVSHUTLENGTH",
    "KXGOVTSHUTLENGTH", "KXSHUTDOWNBY", "SHUTDOWNBY", "KXSHUTDOWNBYDATE", "KXGOVTSHUTDOWN",
    "KXGOVTFUND", "KXGOVTFULLFUND", "KXNUMSHUTDOWNS", "KXVOTESHUTDOWNS", "KXVOTESHUTDOWNH",
    "KXGOVTFUNDLENGTH", "KXVOTEFUNDING",
]
client = httpx.Client(timeout=30, headers={"accept": "application/json"})


def get(path: str, params: dict | None = None) -> dict:
    for attempt in range(6):
        r = client.get(f"{API}{path}", params=params)
        if r.status_code == 429:
            time.sleep(1.5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return {}


def paged(path: str, series: str) -> list[dict]:
    out, cursor = [], None
    while True:
        p = {"series_ticker": series, "limit": 1000}
        if cursor:
            p["cursor"] = cursor
        d = get(path, p)
        out += d.get("markets", [])
        cursor = d.get("cursor")
        if not cursor or not d.get("markets"):
            return out


def ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def main() -> None:
    markets = {}
    for s in SERIES:
        for src, path in (("live", "/markets"), ("historical", "/historical/markets")):
            try:
                ms = paged(path, s)
            except httpx.HTTPStatusError:
                ms = []
            for m in ms:
                m["_src"], m["_series"] = src, s
                markets.setdefault(m["ticker"], m)
        print(s, sum(1 for m in markets.values() if m["_series"] == s))
    (CACHE / "r8dc_kalshi_markets.json").write_text(json.dumps(list(markets.values())))
    candles = {}
    for t, m in markets.items():
        params = {"start_ts": ts(m["open_time"]) - 86400, "end_ts": ts(m["close_time"]) + 86400,
                  "period_interval": 1440}
        path = (f"/historical/markets/{t}/candlesticks" if m["_src"] == "historical"
                else f"/series/{m['_series']}/markets/{t}/candlesticks")
        try:
            candles[t] = get(path, params).get("candlesticks", [])
        except httpx.HTTPStatusError:
            candles[t] = []
    (CACHE / "r8dc_kalshi_candles.json").write_text(json.dumps(candles))
    print(len(markets), "markets;", sum(1 for c in candles.values() if c), "with candles")


if __name__ == "__main__":
    main()
