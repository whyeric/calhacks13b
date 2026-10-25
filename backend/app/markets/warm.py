"""Warm backend/fixtures/kalshi_cache/ from the live public API and print the C1 inventory.

    make warm        # or: cd backend && python -m app.markets.warm

Read-only. Re-run before the demo (spec §15); then DEMO_OFFLINE=1 replays it.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from app.markets.kalshi import KalshiClient
from app.markets.match import SERIES_BY_VAR, eligible, build_candidates

SETTLED_SAMPLE = 5


async def main() -> None:
    now = datetime.now(timezone.utc)
    async with KalshiClient(offline=False) as k:
        # The Sports category list is ~6 MB and the desk never reads it (it uses
        # get_series per ticker), so only the weather list is kept for discovery.
        print(f"series[Climate and Weather]: {len(await k.list_series('Climate and Weather'))}")
        for var, side in (("rain", "no"), ("hot", "yes"), ("home_win", "yes")):
            cands = await build_candidates(k, {"settlement_var": var, "hedge_side": side}, now)
            print(f"\n{var}: {'GO' if cands else 'NO-GO (no_market)'} · {len(cands)} candidate(s)")
            for c in cands:
                print(f"  {c.ticker:34} close {c.close_time:%a %b %d %H:%MZ}  yes_ask {c.yes_ask}  no_ask {c.no_ask}"
                      f"  depth5c yes {c.depth_within_5c.yes} no {c.depth_within_5c.no}")
                await k.get_market(c.ticker)
        # A few settled markets + candles per series for the backtest.
        start = int((now - timedelta(days=14)).timestamp())
        end = int(now.timestamp())
        for var, pairs in SERIES_BY_VAR.items():
            for series, team in pairs:
                settled = [m for m in await k.list_settled(series, start, end) if eligible(m, var, team)]
                for m in settled[:SETTLED_SAMPLE]:
                    await k.candles(series, m["ticker"], start, end)
                print(f"settled[{series}]: {len(settled)} (candles cached for {min(len(settled), SETTLED_SAMPLE)})")


if __name__ == "__main__":
    asyncio.run(main())
