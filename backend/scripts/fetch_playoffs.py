"""Refresh the playoff fixtures (network, read-only).

    cd backend && .venv/bin/python scripts/fetch_playoffs.py            # ESPN + Kalshi
    cd backend && .venv/bin/python scripts/fetch_playoffs.py --kalshi   # Kalshi only

1. ESPN team schedules (regular season + postseason) -> `fixtures/msg_games_playoffs.csv`.
2. The live Knicks season futures (make playoffs / East / title): series, market and order book
   -> `fixtures/kalshi_cache/`, so a desk run replays them with DEMO_OFFLINE=1.

The pooled near-MSG uplift is a separate, local step: `scripts/playoff_uplift.py` (raw Dewey).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.data import playoffs  # noqa: E402
from app.markets.kalshi import KalshiClient, best_ask, best_bid  # noqa: E402
from app.markets.season import LEGS  # noqa: E402


async def warm_kalshi() -> None:
    async with KalshiClient(offline=False) as k:
        for leg in LEGS:
            await k.get_series(leg.series)
            m = await k.get_market(leg.ticker)
            book = await k.get_orderbook(leg.ticker)
            print(f"{leg.ticker:22} {m['status']:7} yes {best_bid(book, 'yes')}/{best_ask(book, 'yes')} "
                  f"no {best_bid(book, 'no')}/{best_ask(book, 'no')}  close {m['close_time']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kalshi", action="store_true", help="only refresh the Kalshi cache")
    args = ap.parse_args()
    if not args.kalshi:
        df = playoffs.fetch()
        print(df[df["home"]].groupby(["team", "season", "playoff"]).size().to_string())
    asyncio.run(warm_kalshi())


if __name__ == "__main__":
    main()
