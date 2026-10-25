"""Polymarket public market data, the desk's second venue next to Kalshi.

Read-only: this module never signs, places or cancels orders. Two public APIs, both cached on
disk exactly like Kalshi's (`fixtures/polymarket_cache/{gamma,clob}/`, `DEMO_OFFLINE=1` replays
and raises `CacheMiss` on a miss):

- Gamma (`/events`): which markets exist, their rules, tokens and fee schedule.
- CLOB (`/book?token_id=`): the order book of one outcome token.

What the desk can hedge here (checked against the live API on 2026-10-25):

- rain: "Where will it rain on <Month> <D>?" (`where-will-it-rain-on-october-27-2026`), one
  YES/NO market per city. New York, NY resolves on the NWS Daily Climate Report (CLI) for New
  York, which is the Central Park station: the same station Kalshi's KXRAIN and our settlement
  flags use, with the same 0.01 in threshold and trace = no.
- home_win: NBA/NHL game moneylines (`nba-det-nyk-2026-10-27`, `nhl-lak-nyr-2026-10-26`). The
  slug reads <league>-<away>-<home>-<date>; the outcome tokens are the two teams, so buying the
  New York token is the YES side and the opponent's token is the NO side. Home games come from
  the ESPN schedule fixtures (`schedule_knicks.csv`, `schedule_rangers.csv`), one slug lookup
  per game: listing a whole league's events is megabytes per call, too big to cache.
- hot: not eligible. "Highest temperature in NYC" resolves on LaGuardia (KLGA, via Wunderground),
  not Central Park, in 2 °F buckets; our basis is measured against Central Park, so the desk
  records why it skipped them instead of hedging on another station.

Each Polymarket outcome token has its own book of asks. They are folded into the Kalshi
`Orderbook` shape (bids only; a YES ask at p is a NO bid at 1 - p), so sizing, the book walk
and every decline rule run unchanged. Shares pay $1.00 each, so I1 holds as on Kalshi.

Fees: fee = rate x C x P x (1 - P) per the market's `feeSchedule` (docs.polymarket.com/trading/
fees; weather markets are currently 0, sports 0.05). Polymarket rounds to 5 dp; the desk rounds
the order's fee UP to the cent, so it never understates the cost.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any

from app.config import FIXTURES_DIR, POLYMARKET_EVENT_URL, get_settings
from app.models import Level

from .kalshi import CacheMiss, KalshiClient, KalshiError, Orderbook, best_ask, best_bid, parse_price
from .match import NY_TZ, Candidate, Depth, depth_within

DEFAULT_CACHE_DIR = FIXTURES_DIR / "polymarket_cache"
ONE = Decimal("1")
FEE_TYPE = "polymarket_taker"  # rate x C x P x (1 - P), exponent 1; anything else is unverified

RAIN_CITY = "New York, NY"
RAIN_SOURCE = "NWS Daily Climate Report, New York (Central Park)"
HOT_SKIP_NOTE = (
    "Polymarket NYC high-temperature markets settle at LaGuardia (KLGA), not Central Park; "
    "not eligible."
)
# schedule fixture, league, home team code in the slug, the team's outcome name
HOME_TEAMS = (("knicks", "nba", "nyk", "Knicks"), ("rangers", "nhl", "nyr", "Rangers"))
# ESPN abbreviations that differ from Polymarket's slug codes (checked: LA -> lak on 2026-10-25).
SLUG_CODES = {
    "nba": {"GS": "gsw", "NO": "nop", "SA": "sas", "UTAH": "uta", "WSH": "was", "NY": "nyk"},
    "nhl": {"LA": "lak", "NJ": "njd", "SJ": "sjs", "TB": "tbl", "UTAH": "uta", "WSH": "wsh"},
}


def game_slug(league: str, opponent: str, home: str, d: date) -> str:
    away = SLUG_CODES[league].get(opponent.upper(), opponent.lower())
    return f"{league}-{away}-{home}-{d.isoformat()}"
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december")


def rain_slug(d: date) -> str:
    return f"where-will-it-rain-on-{_MONTHS[d.month - 1]}-{d.day}-{d.year}"


def _parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _json_list(v: Any) -> list:
    """Gamma serializes `outcomes` and `clobTokenIds` as JSON strings inside the JSON."""
    return json.loads(v) if isinstance(v, str) else list(v or [])


def _count(s: Any) -> int:
    return int(Decimal(str(s)).to_integral_value(rounding=ROUND_FLOOR))


def _asks(book: dict) -> list[Level]:
    out = []
    for lv in book.get("asks") or []:
        n = _count(lv["size"])
        if n > 0:
            out.append(Level(price=parse_price(str(lv["price"])), count=n))
    return sorted(out, key=lambda lv: lv.price)


def combine_books(ticker: str, yes_book: dict, no_book: dict, fetched_at: datetime) -> Orderbook:
    """Two token books (asks) as one Kalshi-shaped book (bids): an ask at p is an opposite bid at 1 - p."""
    def flip(levels: list[Level]) -> list[Level]:
        return sorted((Level(price=ONE - lv.price, count=lv.count) for lv in levels),
                      key=lambda lv: lv.price, reverse=True)

    return Orderbook(ticker=ticker, yes_bids=flip(_asks(no_book)), no_bids=flip(_asks(yes_book)),
                     fetched_at=fetched_at)


def fee_terms(market: dict) -> tuple[str, Decimal]:
    """(fee_type, rate) from Gamma's `feeSchedule`; a missing schedule is recorded as unverified."""
    fs = market.get("feeSchedule")
    if not isinstance(fs, dict) or "rate" not in fs:
        return "polymarket_unknown", Decimal("0")
    rate = Decimal(str(fs["rate"]))
    return (FEE_TYPE if str(fs.get("exponent", 1)) in ("1", "1.0") else "polymarket_exponent"), rate


class PolymarketClient:
    """Gamma + CLOB reads through the same on-disk cache as Kalshi (one cache dir per API)."""

    def __init__(self, offline: bool | None = None, cache_dir: str | Path = DEFAULT_CACHE_DIR,
                 transport=None, *, backoff_s: int = 1):
        s = get_settings()
        offline = s.demo_offline if offline is None else offline
        cache_dir = Path(cache_dir)
        self.offline = offline
        self._gamma = KalshiClient(base_url=s.polymarket_gamma_url, offline=offline, cache_dir=cache_dir / "gamma",
                                   transport=transport, backoff_s=backoff_s)
        self._clob = KalshiClient(base_url=s.polymarket_clob_url, offline=offline, cache_dir=cache_dir / "clob",
                                  transport=transport, backoff_s=backoff_s)

    async def __aenter__(self) -> PolymarketClient:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._gamma.aclose()
        await self._clob.aclose()

    async def event(self, slug: str) -> dict | None:
        body, _ = await self._gamma.get_json("/events", {"slug": slug})
        return body[0] if body else None

    async def book(self, token_id: str) -> tuple[dict, datetime]:
        return await self._clob.get_json("/book", {"token_id": token_id})


# ---------------------------------------------------------------- candidates


def _days(now: datetime, week_of: date | None, window_days: int) -> list[date]:
    """Days a hedge may be about: strictly after today in New York, inside the desk week if given."""
    today_ny = now.astimezone(NY_TZ).date()
    if week_of is not None:
        days = [week_of + timedelta(days=i) for i in range(7)]
    else:
        days = [today_ny + timedelta(days=i) for i in range(1, window_days + 1)]
    return [d for d in days if d > today_ny]


async def _candidate(pm: PolymarketClient, *, ticker: str, event: dict, market: dict, yes_token: str,
                     no_token: str, settlement_var: str, source: str) -> tuple[Candidate, Orderbook]:
    (yes_book, fetched_at), (no_book, _) = await pm.book(yes_token), await pm.book(no_token)
    book = combine_books(ticker, yes_book, no_book, fetched_at)
    fee_type, rate = fee_terms(market)
    rules = (event.get("description") or market.get("description") or "").strip()
    return Candidate(
        ticker=ticker, series_ticker=event["slug"], title=market.get("question") or event.get("title") or ticker,
        close_time=_parse_time(market.get("endDate") or event["endDate"]), status="active",
        rules_primary=rules[:600], floor_strike=None, settlement_var=settlement_var,
        fee_type=fee_type, fee_multiplier=ONE, yes_ask=best_ask(book, "yes"), no_ask=best_ask(book, "no"),
        yes_bid=best_bid(book, "yes"), no_bid=best_bid(book, "no"),
        depth_within_5c=Depth(yes=depth_within(book, "yes"), no=depth_within(book, "no")),
        fetched_at=book.fetched_at, venue="polymarket", fee_rate=rate,
        market_url=POLYMARKET_EVENT_URL.format(slug=event["slug"]), settlement_source=source,
    ), book


def _open(market: dict, now: datetime) -> bool:
    end = market.get("endDate")
    return (bool(market.get("active")) and not market.get("closed") and market.get("acceptingOrders", True)
            and end is not None and _parse_time(end) > now)


async def _rain(pm: PolymarketClient, days: list[date], now: datetime) -> list[tuple[Candidate, Orderbook]]:
    out = []
    for d in days:
        event = await pm.event(rain_slug(d))
        if not event:
            continue
        for m in event.get("markets") or []:
            if not (m.get("groupItemTitle") or "").startswith(RAIN_CITY) or not _open(m, now):
                continue
            outcomes, tokens = _json_list(m.get("outcomes")), _json_list(m.get("clobTokenIds"))
            if outcomes != ["Yes", "No"] or len(tokens) != 2:
                continue
            out.append(await _candidate(pm, ticker=m["slug"], event=event, market=m, yes_token=tokens[0],
                                        no_token=tokens[1], settlement_var="rain", source=RAIN_SOURCE))
    return out


def _home_games(days: list[date]) -> list[tuple[str, str, str, str, date]]:
    """(league, opponent, home code, team name, day) for New York home games on `days`."""
    from app.data import sports

    out = []
    for fixture, league, home, team in HOME_TEAMS:
        try:
            df = sports.read_schedule(fixture)
        except FileNotFoundError:
            continue
        for row in df.itertuples():
            d = date.fromisoformat(row.date)
            if row.home and d in days:
                out.append((league, row.opponent, home, team, d))
    return out


async def _home_win(pm: PolymarketClient, days: list[date], now: datetime) -> list[tuple[Candidate, Orderbook]]:
    out = []
    for league, opponent, home, team, d in _home_games(days):
        event = await pm.event(game_slug(league, opponent, home, d))
        if not event:
            continue
        for m in event.get("markets") or []:
            if m.get("sportsMarketType") != "moneyline" or not _open(m, now):
                continue
            outcomes, tokens = _json_list(m.get("outcomes")), _json_list(m.get("clobTokenIds"))
            if team not in outcomes or len(outcomes) != 2 or len(tokens) != 2:
                continue
            i = outcomes.index(team)
            out.append(await _candidate(
                pm, ticker=m.get("slug") or event["slug"], event=event, market=m, yes_token=tokens[i],
                no_token=tokens[1 - i], settlement_var="home_win",
                source=f"Official {league.upper()} final result ({team} win = YES)"))
    return out


async def build_candidates(
    pm: PolymarketClient, settlement_var: str, now: datetime, *, week_of: date | None = None, window_days: int = 8,
) -> tuple[list[Candidate], dict[str, Orderbook], str | None]:
    """(candidates, books by ticker, note). A cache miss or API failure is (_, _, note), never an exception:
    Polymarket is an extra venue, so its absence must not fail the desk."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    if settlement_var == "hot":
        return [], {}, HOT_SKIP_NOTE
    fn = {"rain": _rain, "home_win": _home_win}.get(settlement_var)
    if fn is None:
        return [], {}, None
    try:
        pairs = await fn(pm, _days(now, week_of, window_days), now)
    except CacheMiss:
        return [], {}, "Polymarket not in the offline cache for this week."
    except (KalshiError, KeyError, ValueError) as e:
        return [], {}, f"Polymarket unavailable ({type(e).__name__})."
    pairs.sort(key=lambda cb: (-cb[0].depth_within_5c.yes, cb[0].ticker))
    return [c for c, _ in pairs], {c.ticker: b for c, b in pairs}, None
