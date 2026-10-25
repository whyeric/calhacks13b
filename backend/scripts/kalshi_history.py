"""Fetch settled Kalshi markets and their daily candles for the backtest's real-priced tier (#10).

    cd backend && .venv/bin/python -m scripts.kalshi_history            # network, read-only
    cd backend && .venv/bin/python -m scripts.kalshi_history --check    # print coverage only

Writes one compact file per settlement variable to `fixtures/kalshi_history/<var>.json`:

    {"series": [...], "fetched_at": iso, "markets": {
        "<YYYY-MM-DD>": {"ticker", "series", "result": "yes"|"no", "candles": [
            {"end_period_ts": int, "yes_ask_close": "0.21"|null, "yes_bid_close": "0.13"|null,
             "price_close": "0.30"|null, "volume": "3261.60"|null}, ...]}}}

Prices stay strings (parsed with Decimal downstream; never float). Raw responses go to the
KalshiClient cache in `data/kalshi_history_cache/` (gitignored) so a re-run is cheap. The backtest
reads only the compact file, so it runs offline.

Series per variable (C1 pins in app/markets/match.py, plus the archived NYC rain series):
- rain: `KXRAINNYC-<date>-T0` (2021-09 .. 2026-07-15) then `KXRAIN-<date>-NYC` (2026-07-16 on).
  Both resolve YES iff Central Park (NWS CLI) precipitation is strictly greater than 0 in.
- home_win: KXNBAGAME (NYK home) and KXNHLGAME (NYR home), YES = the NY team wins.
`hot` is not fetched: KXHIGHNY strikes change daily, so a fixed-strike exposure has no single
daily contract to price; hot stays on the frequency tier.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app import config
from app.markets.kalshi import CacheMiss, KalshiClient, KalshiError
from app.markets.match import SERIES_BY_VAR, eligible, event_date

NY = ZoneInfo("America/New_York")
OUT_DIR = config.FIXTURES_DIR / "kalshi_history"
CACHE_DIR = config.RAW_DATA_DIR / "kalshi_history_cache"
SERIES: dict[str, list[tuple[str, str | None]]] = {
    "rain": [("KXRAINNYC", None), ("KXRAIN", None)],
    "home_win": SERIES_BY_VAR["home_win"],
}
THROTTLE_S = 0.12


def _eligible(m: dict, var: str, series: str, team: str | None) -> bool:
    if series == "KXRAINNYC":
        return m.get("strike_type") == "greater" and str(m.get("floor_strike")) == "0"
    return eligible(m, var, team)


def _midnight_ts(d: date) -> int:
    return int(datetime.combine(d, time(0), NY).timestamp())


def _get(block: dict | None, key: str) -> str | None:
    if not block:
        return None
    v = block.get(key, block.get(f"{key}_dollars"))
    return None if v is None else str(v)


def _compact(c: dict) -> dict:
    vol = c.get("volume", c.get("volume_fp"))
    return {
        "end_period_ts": int(c["end_period_ts"]),
        "yes_ask_close": _get(c.get("yes_ask"), "close"),
        "yes_bid_close": _get(c.get("yes_bid"), "close"),
        "price_close": _get(c.get("price"), "close"),
        "volume": None if vol is None else str(vol),
    }


async def _markets(k: KalshiClient, series: str) -> list[dict]:
    out = []
    for path, extra in (("/historical/markets", {}), ("/markets", {"status": "settled"})):
        try:
            out += await k._paged(path, {"series_ticker": series, **extra}, "markets")
        except (KalshiError, CacheMiss) as e:
            print(f"  {series} {path}: {e}")
    return out


async def _candles(k: KalshiClient, series: str, ticker: str, d: date) -> list[dict]:
    params = {"start_ts": _midnight_ts(d - timedelta(days=3)), "end_ts": _midnight_ts(d + timedelta(days=1)),
              "period_interval": 1440}
    for path in (f"/historical/markets/{ticker}/candlesticks", f"/series/{series}/markets/{ticker}/candlesticks"):
        try:
            body, _ = await k._get(path, params)
            return body.get("candlesticks") or []
        except (KalshiError, CacheMiss):
            continue
    return []


async def fetch(var: str, start: date, end: date, offline: bool) -> dict:
    markets: dict[str, dict] = {}
    async with KalshiClient(offline=offline, cache_dir=CACHE_DIR) as k:
        for series, team in SERIES[var]:
            listed = await _markets(k, series)
            keep = []
            for m in listed:
                d = event_date(m)
                if d is None or not (start <= d <= end) or m.get("result") not in ("yes", "no"):
                    continue
                if _eligible(m, var, series, team):
                    keep.append((d, m))
            print(f"{var}: {series} listed {len(listed)}, eligible in window {len(keep)}", flush=True)
            for i, (d, m) in enumerate(sorted(keep, key=lambda x: x[0])):
                if d.isoformat() in markets:
                    continue  # both teams at MSG the same day: keep the first (NBA)
                # Candles only for the holdout (prices); train days keep the settled result only.
                raw = await _candles(k, series, m["ticker"], d) if d >= config.HOLDOUT_START else []
                markets[d.isoformat()] = {
                    "ticker": m["ticker"], "series": series, "result": m["result"],
                    "candles": [_compact(c) for c in raw],
                }
                if raw and not offline:
                    await asyncio.sleep(THROTTLE_S)
                if i % 50 == 0:
                    print(f"  {series} {i}/{len(keep)}", flush=True)
    return {
        "var": var, "series": [s for s, _ in SERIES[var]],
        "window": [start.isoformat(), end.isoformat()],
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "markets": dict(sorted(markets.items())),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--var", choices=sorted(SERIES), action="append")
    ap.add_argument("--offline", action="store_true", help="replay the raw cache only")
    ap.add_argument("--check", action="store_true", help="print coverage of the written files")
    args = ap.parse_args()
    variables = args.var or sorted(SERIES)
    if args.check:
        for var in variables:
            d = json.loads((OUT_DIR / f"{var}.json").read_text())
            n_c = sum(1 for m in d["markets"].values() if m["candles"])
            print(f"{var}: {len(d['markets'])} markets, {n_c} with candles, window {d['window']}")
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for var in variables:
        data = asyncio.run(fetch(var, config.WINDOW_START, config.WINDOW_END, args.offline))
        path: Path = OUT_DIR / f"{var}.json"
        path.write_text(json.dumps(data, indent=1) + "\n")
        print(f"wrote {path} ({len(data['markets'])} markets)")


if __name__ == "__main__":
    main()
