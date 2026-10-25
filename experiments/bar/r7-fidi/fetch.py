"""Fetch public inputs for r7-fidi into the scratchpad cache (r2-cache/r7fidi_*).

    backend/.venv/bin/python experiments/bar/r7-fidi/fetch.py

- FRED SP500 and VIXCLS daily closes (fredgraph CSV).
- Kalshi KXFEDDECISION and KXCPI markets (live + historical archive) and daily candlesticks,
  so event dates come from settlement times and surprises from pre-release prices.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

API = "https://api.elections.kalshi.com/trade-api/v2"
CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
client = httpx.Client(timeout=60, headers={"accept": "application/json"}, follow_redirects=True)


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


def markets(series: str) -> list[dict]:
    live = [dict(m, _src="live") for m in paged("/markets", series)]
    seen = {m["ticker"] for m in live}
    hist = [dict(m, _src="historical") for m in paged("/historical/markets", series) if m["ticker"] not in seen]
    return live + hist


def candles(m: dict) -> list[dict]:
    """Hourly candles over the 3 days before close (enough for a pre-release price)."""
    end = ts(m["close_time"])
    params = {"start_ts": end - 3 * 86400, "end_ts": end, "period_interval": 60}
    if m["_src"] == "historical":
        path = f"/historical/markets/{m['ticker']}/candlesticks"
    else:
        path = f"/series/{m['event_ticker'].split('-')[0]}/markets/{m['ticker']}/candlesticks"
    try:
        return get(path, params).get("candlesticks", [])
    except httpx.HTTPStatusError:
        return []


def main() -> None:
    for sid in ("SP500", "VIXCLS"):
        p = CACHE / f"r7fidi_fred_{sid}.csv"
        if not p.exists():
            r = client.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                           params={"id": sid, "cosd": "2023-10-01", "coed": "2026-10-23"})
            r.raise_for_status()
            p.write_text(r.text)
        print(sid, len(p.read_text().splitlines()), "rows")
    for series in ("KXFEDDECISION", "KXCPI"):
        p = CACHE / f"r7fidi_{series}.json"
        if p.exists():
            continue
        ms = [m for m in markets(series) if "2024-01-01" <= m["close_time"][:10] <= "2026-10-01"
              and m.get("result") in ("yes", "no")]
        print(series, len(ms), "settled markets; fetching candles", file=sys.stderr)
        for i, m in enumerate(ms):
            m["_candles"] = candles(m)
            if i % 50 == 0:
                print(" ", i, m["ticker"], len(m["_candles"]), file=sys.stderr)
        p.write_text(json.dumps(ms))


if __name__ == "__main__":
    main()
