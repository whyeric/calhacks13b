"""Deterministic candidate filter and the off-list guard for Claude's pick.

The filter decides which markets are eligible; Claude only chooses among them
(`validate_pick`). An empty list is a valid answer and becomes the `no_market`
decline downstream.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.models import Side

from .kalshi import KalshiClient, Orderbook, ask_levels, best_ask, best_bid
from .shapes import field

MAX_SLIP = Decimal("0.05")
OPEN_STATUSES = {"open", "active"}  # the query param is "open"; markets report "active"

# settlement_var -> [(series, team)]. Pinned by the C1 check on 2026-10-24:
# - rain: NYC daily rain lives in the multi-city KXRAIN series as KXRAIN-<date>-NYC
#   (KXRAINNYC / KXRAINDNYC have no open markets).
# - hot: KXHIGHNY, "greater" markets only (G9). YES iff Central Park tmax > floor_strike.
# - home_win: game markets whose YES pays on a New York home win. Event codes read
#   <date><AWAY><HOME>, e.g. KXNBAGAME-26OCT25ORLNYK is Orlando at New York.
SERIES_BY_VAR: dict[str, list[tuple[str, str | None]]] = {
    "rain": [("KXRAIN", None)],
    "hot": [("KXHIGHNY", None)],
    "home_win": [("KXNBAGAME", "NYK"), ("KXNHLGAME", "NYR")],
}
RAIN_CITY = "NYC"
NY_TZ = ZoneInfo("America/New_York")
_MONTHS = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), start=1)}
_EVENT_DATE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})")


class Depth(BaseModel):
    yes: int
    no: int


class Candidate(BaseModel):
    ticker: str
    series_ticker: str
    title: str
    close_time: datetime
    status: str
    rules_primary: str
    floor_strike: Decimal | None
    settlement_var: str
    fee_type: str
    fee_multiplier: Decimal
    yes_ask: Decimal | None
    no_ask: Decimal | None
    yes_bid: Decimal | None
    no_bid: Decimal | None
    depth_within_5c: Depth
    fetched_at: datetime  # G13: lets the UI label cached prices
    # Second venue (markets/polymarket.py). Kalshi candidates keep the defaults. `fee_rate` is the
    # taker rate in fee = rate x C x P x (1 - P); None means Kalshi's 0.07 x fee_multiplier.
    venue: Literal["kalshi", "polymarket"] = "kalshi"
    fee_rate: Decimal | None = None
    market_url: str | None = None
    settlement_source: str | None = None


class OffListError(ValueError):
    def __init__(self, ticker: str, allowed: list[str]):
        super().__init__(f"{ticker!r} is not a candidate; allowed: {allowed}")
        self.ticker = ticker
        self.allowed = allowed


def _parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def event_date(market: dict) -> date | None:
    """The day the market is about, from its event ticker (KXRAIN-26OCT25, KXNBAGAME-26OCT25ORLNYK).

    Not `occurrence_datetime`: for KXRAIN it reads two days after the rain day.
    """
    m = _EVENT_DATE.search(market.get("event_ticker", ""))
    if not m or m.group(2) not in _MONTHS:
        return None
    return date(2000 + int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3)))


def eligible(market: dict, settlement_var: str, team: str | None) -> bool:
    ticker = market["ticker"]
    if settlement_var == "rain":
        return ticker.rsplit("-", 1)[-1] == RAIN_CITY
    if settlement_var == "hot":
        return market.get("strike_type") == "greater"
    if settlement_var == "home_win":
        # The YES side must be the NY team, and the NY team must be listed second (home).
        matchup = market["event_ticker"].split("-", 1)[-1]
        return ticker.rsplit("-", 1)[-1] == team and matchup.endswith(team)
    return False


def _is_future_day(market: dict, today_ny: date) -> bool:
    # A day that has started in New York is partly or wholly decided: never hedge it.
    # Unparseable event tickers are skipped rather than guessed.
    d = event_date(market)
    return d is not None and d > today_ny


def depth_within(book: Orderbook, side: Side, max_slip: Decimal = MAX_SLIP) -> int:
    levels = ask_levels(book, side)
    if not levels:
        return 0
    best = levels[0].price
    return sum(lv.count for lv in levels if lv.price - best <= max_slip)


def in_week(market: dict, week_of: date | None) -> bool:
    """The market's day falls in the desk week [Mon week_of, Sun week_of + 6]. `None` = no week filter."""
    if week_of is None:
        return True
    d = event_date(market)
    return d is not None and week_of <= d <= week_of + timedelta(days=6)


async def build_candidates(
    client: KalshiClient, exposure: Any, now: datetime, window_days: int = 8, *, week_of: date | None = None,
) -> list[Candidate]:
    """`week_of` (the desk week's Monday) keeps only markets about a day in that week, so a
    Saturday run for next week never picks Sunday's market."""
    settlement_var = field(exposure, "settlement_var")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    horizon = now + timedelta(days=window_days)
    if week_of is not None:  # the week's last day settles the morning after; leave a margin
        horizon = max(horizon, datetime.combine(week_of + timedelta(days=9), datetime.min.time(), timezone.utc))
    today_ny = now.astimezone(NY_TZ).date()

    survivors: list[tuple[dict, dict]] = []
    for series_ticker, team in SERIES_BY_VAR.get(settlement_var, []):
        series = await client.get_series(series_ticker)
        # No close-time bounds in the query: they'd put `now` into the cache key and make
        # every offline replay a CacheMiss. The window is applied locally instead.
        markets = await client.list_markets(series_ticker, status="open")
        for m in markets:
            if (
                m.get("status") in OPEN_STATUSES
                and now < _parse_time(m["close_time"]) <= horizon
                and _is_future_day(m, today_ny)
                and in_week(m, week_of)
                and eligible(m, settlement_var, team)
            ):
                survivors.append((m, series))

    books = await asyncio.gather(*(client.get_orderbook(m["ticker"]) for m, _ in survivors))

    out = []
    for (m, series), book in zip(survivors, books):
        strike = m.get("floor_strike")
        out.append(Candidate(
            ticker=m["ticker"],
            series_ticker=series["ticker"],
            title=m["title"],
            close_time=_parse_time(m["close_time"]),
            status=m["status"],
            rules_primary=m.get("rules_primary") or "",
            floor_strike=None if strike is None else Decimal(str(strike)),
            settlement_var=settlement_var,
            fee_type=series.get("fee_type") or "",
            fee_multiplier=Decimal(str(series.get("fee_multiplier", 1))),
            yes_ask=best_ask(book, "yes"),
            no_ask=best_ask(book, "no"),
            yes_bid=best_bid(book, "yes"),
            no_bid=best_bid(book, "no"),
            depth_within_5c=Depth(yes=depth_within(book, "yes"), no=depth_within(book, "no")),
            fetched_at=book.fetched_at,
        ))
    out.sort(key=lambda c: (-c.depth_within_5c.yes, c.ticker))
    return out


def validate_pick(candidates: list[Candidate], ticker: str, reason: str) -> Candidate:
    """Accept Claude's pick only if it is exactly one of the candidate tickers."""
    for c in candidates:
        if c.ticker == ticker:
            return c
    raise OffListError(ticker, [c.ticker for c in candidates])


def deterministic_pick(candidates: list[Candidate], side: Side) -> Candidate | None:
    """Fallback when Claude is unavailable: deepest book within 5¢ on the side we'd buy."""
    if not candidates:
        return None
    return min(candidates, key=lambda c: (-getattr(c.depth_within_5c, side), c.ticker))
