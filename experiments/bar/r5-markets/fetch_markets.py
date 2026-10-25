"""Catalogue Kalshi playoff-advancement series and pull their markets + price history.

Public, unauthenticated Kalshi API. Everything is cached in the scratchpad
(r2-cache/r5markets_*), never in the repo.

    backend/.venv/bin/python experiments/bar/r5-markets/fetch_markets.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

API = "https://api.elections.kalshi.com/trade-api/v2"
CACHE = Path(
    "/private/tmp/claude-501/-Users-main-calhacks13b/"
    "43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache"
)

# Series that settle on playoff advancement (or on a count tied to it).
TARGETS = {
    "NBA": [
        "KXNBAPLAYOFF", "KXNBASERIES", "KXNBASERIESGAMES", "KXNBASERIESSCORE",
        "KXNBAGAME7", "KXNBASWEEP", "KXNBAHOMECLINCH", "KXNBAPLAYOFFWINS",
        "KXNBAECFQUAL", "KXNBAWCFQUAL", "KXTEAMSINNBAEF", "KXTEAMSINNBAWF",
        "KXNBAEAST", "KXNBAWEST", "KXTEAMSINNBAF", "KXNBA", "KXNBAFINALSEXACT",
        "KXNBASEED",
    ],
    "NHL": [
        "KXNHLPLAYOFF", "KXNHLSERIES", "KXNHLSERIESGAMES", "KXNHLSERIESSCORE",
        "KXNHLEAST", "KXNHLWEST", "KXTEAMSINSC", "KXNHL", "KXNHLFINALSEXACT",
    ],
    "MLB": [
        "KXMLBPLAYOFFS", "KXMLBSERIES", "KXMLBSERIESGAMES", "KXMLBSERIESEXACT",
        "KXMLBSERIESSCORE", "KXMLBPLAYOFFHOST", "KXMLBALCSQUAL", "KXMLBNLCSQUAL",
        "KXMLBAL", "KXMLBNL", "KXTEAMSINWS", "KXMLB", "KXMLBWS", "KXMLBWSOUTCOME",
    ],
    "NFL": [
        "KXNFLPLAYOFF", "KXNFLPLAYOFFHOST", "KXNFLROUNDQUAL", "KXNFLSTAGEOFELIM",
        "KXNFLSEED", "KXNFLAFCCHAMP", "KXNFLNFCCHAMP", "KXTEAMSINSB", "KXSB",
        "KXSBHOST",
    ],
}

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


def _paged(path: str, series: str) -> list[dict]:
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


def all_markets(series: str) -> list[dict]:
    """Live markets plus the historical archive (markets settled before the cutoff)."""
    live = _paged("/markets", series)
    for m in live:
        m["_src"] = "live"
    hist = _paged("/historical/markets", series)
    for m in hist:
        m["_src"] = "historical"
    seen = {m["ticker"] for m in live}
    return live + [m for m in hist if m["ticker"] not in seen]


def _ts(iso: str) -> int:
    from datetime import datetime
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def candles(m: dict, period: int = 1440) -> list[dict]:
    """Daily candlesticks over the market's whole life."""
    start, end = _ts(m["open_time"]) - 86400, _ts(m["close_time"]) + 86400
    params = {"start_ts": start, "end_ts": end, "period_interval": period}
    if m["_src"] == "historical":
        path = f"/historical/markets/{m['ticker']}/candlesticks"
    else:
        series = m["event_ticker"].split("-")[0]
        path = f"/series/{series}/markets/{m['ticker']}/candlesticks"
    try:
        return get(path, params).get("candlesticks", [])
    except httpx.HTTPStatusError:
        return []


# Candles for every market in these series (series-level pricing / calibration),
# and for any market naming one of FOCUS in the others.
CANDLE_ALL = {
    "KXNBASERIES", "KXNHLSERIES", "KXMLBSERIES",
    "KXNBASERIESGAMES", "KXNHLSERIESGAMES", "KXMLBSERIESGAMES", "KXMLBPLAYOFFHOST",
    "KXNFLPLAYOFFHOST",
    "KXNBASERIESSCORE", "KXNHLSERIESSCORE", "KXMLBSERIESSCORE", "KXMLBSERIESEXACT",
    "KXNBAFINALSEXACT", "KXNHLFINALSEXACT", "KXNBAPLAYOFFWINS",
    "KXNBAEAST", "KXNBAWEST", "KXNBA", "KXNHLEAST", "KXNHLWEST", "KXNHL",
    "KXMLBAL", "KXMLBNL", "KXMLB",
    "KXNBAPLAYOFF", "KXNHLPLAYOFF", "KXMLBPLAYOFFS",
    "KXNFLPLAYOFF", "KXNFLAFCCHAMP", "KXNFLNFCCHAMP", "KXSB",
}
FOCUS = ("NYK", "NYR", "GSW", "SF", "NYG")


def want_candles(series: str, m: dict) -> bool:
    suffix = m["ticker"].rsplit("-", 1)[-1]
    if suffix in FOCUS:
        return True
    # Settled seasons only; next season's futures are only kept for FOCUS teams.
    return series in CANDLE_ALL and m.get("status") in ("finalized", "settled", "determined")


def main() -> None:
    f = CACHE / "r5markets_markets.json"
    data = json.loads(f.read_text()) if f.exists() else {}
    for league, sers in TARGETS.items():
        for s in sers:
            if s in data:
                continue
            try:
                info = get(f"/series/{s}").get("series", {})
            except httpx.HTTPStatusError as e:
                print(s, "series error", e.response.status_code, file=sys.stderr)
                info = {}
            ms = all_markets(s)
            data[s] = {"league": league, "series": info, "markets": ms}
            print(f"{league} {s}: {len(ms)} markets", flush=True)
            f.write_text(json.dumps(data))

    cf = CACHE / "r5markets_candles.json"
    cdata = json.loads(cf.read_text()) if cf.exists() else {}
    n = 0
    for s, blob in data.items():
        for m in blob["markets"]:
            if m["ticker"] in cdata or not want_candles(s, m):
                continue
            cdata[m["ticker"]] = candles(m)
            n += 1
            if n % 50 == 0:
                print("candles", n, flush=True)
                cf.write_text(json.dumps(cdata))
    cf.write_text(json.dumps(cdata))
    print("candles total", len(cdata))


if __name__ == "__main__":
    main()
