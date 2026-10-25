"""Kalshi public market-data client with an on-disk cache and offline replay.

Read-only: this module never places, amends, or cancels orders.

Money and prices are Decimal end to end. Response bodies are parsed with
``parse_float=Decimal`` so no float can enter from the wire, and the cache
stores the raw body text so offline replay parses the exact same bytes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

from app.config import FIXTURES_DIR, get_settings
from app.models import Level, Side

DEFAULT_CACHE_DIR = FIXTURES_DIR / "kalshi_cache"

ONE = Decimal("1")
TRIES = 3
TIMEOUT_S = 10
MAX_CONCURRENCY = 4
PAGE_LIMIT = 1000
MAX_RETRY_AFTER_S = 10


class KalshiError(Exception):
    """A request that failed for good (after retries, or a non-retryable 4xx)."""

    def __init__(self, message: str, *, status: int | None = None, path: str = ""):
        super().__init__(message)
        self.status = status
        self.path = path


class CacheMiss(Exception):
    """Offline mode and no cached response for this request. Never hits the network."""

    def __init__(self, path: str, params: dict[str, Any]):
        super().__init__(f"no cached response for GET {path} {params}")
        self.path = path
        self.params = params


class Orderbook(BaseModel):
    ticker: str
    yes_bids: list[Level]  # best (highest) first
    no_bids: list[Level]
    fetched_at: datetime


# ---------------------------------------------------------------- parsing


def parse_price(s: str | Decimal | int) -> Decimal:
    """Fixed-point dollar string ("0.4200") to Decimal. Floats are rejected."""
    if isinstance(s, (float, bool)):
        raise TypeError(f"price must be a string or Decimal, not {type(s).__name__}: {s!r}")
    try:
        d = Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"not a price: {s!r}") from e
    if not (0 <= d <= 1):
        raise ValueError(f"price out of [0, 1]: {s!r}")
    # Strip trailing zeros so "0.4200" serializes as "0.42"; avoid "1E+0".
    return d.quantize(ONE) if d == d.to_integral_value() else d.normalize()


def _parse_count(c: str | Decimal | int) -> int:
    # Kalshi reports fractional resting size ("1334302.28"). Only whole
    # contracts are fillable, so round down.
    if isinstance(c, (float, bool)):
        raise TypeError(f"count must be a string, Decimal or int: {c!r}")
    return int(Decimal(c).to_integral_value(rounding=ROUND_FLOOR))


def _levels(raw: list | None, *, cents: bool) -> list[Level]:
    out = []
    for price, count in raw or []:
        p = parse_price(Decimal(price) / 100) if cents else parse_price(price)
        n = _parse_count(count)
        if n > 0:
            out.append(Level(price=p, count=n))
    return sorted(out, key=lambda lv: lv.price, reverse=True)


def parse_orderbook(ticker: str, body: dict, fetched_at: datetime) -> Orderbook:
    """Accept both book shapes Kalshi has served (gap G1).

    Current (pinned from the live C1 call, 2026-10-24):
        {"orderbook_fp": {"yes_dollars": [["0.3800", "50.00"], ...], "no_dollars": [...]}}
    Legacy: {"orderbook": {"yes": [[38, 50]], "no": [...]}} (integer cents), optionally
    with "yes_dollars"/"no_dollars" inside. Lists are ascending on the wire; may be null.
    Unknown keys are ignored.
    """
    book = body.get("orderbook_fp") or body.get("orderbook") or {}
    sides = {}
    for side in ("yes", "no"):
        if f"{side}_dollars" in book:
            sides[side] = _levels(book[f"{side}_dollars"], cents=False)
        else:
            sides[side] = _levels(book.get(side), cents=True)
    return Orderbook(ticker=ticker, yes_bids=sides["yes"], no_bids=sides["no"], fetched_at=fetched_at)


def _opposite_bids(book: Orderbook, side: Side) -> list[Level]:
    if side == "yes":
        return book.no_bids
    if side == "no":
        return book.yes_bids
    raise ValueError(f"side must be 'yes' or 'no', got {side!r}")


def best_ask(book: Orderbook, side: Side) -> Decimal | None:
    """The book holds bids only: a YES ask is 1 − best NO bid, and vice versa."""
    bids = _opposite_bids(book, side)
    return ONE - max(lv.price for lv in bids) if bids else None


def best_bid(book: Orderbook, side: Side) -> Decimal | None:
    bids = book.yes_bids if side == "yes" else book.no_bids
    return max(lv.price for lv in bids) if bids else None


def ask_levels(book: Orderbook, side: Side) -> list[Level]:
    """Ask ladder for `side`, cheapest first: each opposite bid at p is an ask at 1 − p."""
    bids = sorted(_opposite_bids(book, side), key=lambda lv: lv.price, reverse=True)
    return [Level(price=ONE - lv.price, count=lv.count) for lv in bids]


# ---------------------------------------------------------------- client


def _cache_key(path: str, params: dict[str, Any]) -> str:
    query = urlencode(sorted((k, str(v)) for k, v in params.items()))
    return hashlib.sha1(f"GET{path}?{query}".encode()).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class KalshiClient:
    def __init__(
        self,
        base_url: str | None = None,
        offline: bool | None = None,
        cache_dir: str | Path = DEFAULT_CACHE_DIR,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        backoff_s: int = 1,
        sleep=asyncio.sleep,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.kalshi_base_url).rstrip("/")
        self.offline = settings.demo_offline if offline is None else offline
        self.cache_dir = Path(cache_dir)
        self._backoff_s = backoff_s
        self._sleep = sleep
        self._sem = asyncio.Semaphore(MAX_CONCURRENCY)
        self._http = httpx.AsyncClient(
            base_url=self.base_url, timeout=TIMEOUT_S, transport=transport,
            headers={"Accept": "application/json"},
        )

    async def __aenter__(self) -> KalshiClient:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- cache

    def _cache_file(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> tuple[dict, datetime] | None:
        f = self._cache_file(key)
        if not f.exists():
            return None
        entry = json.loads(f.read_text(), parse_float=Decimal)
        return entry["response"], datetime.fromisoformat(entry["fetched_at"])

    def _write_cache(self, key: str, path: str, params: dict, body: str, fetched_at: datetime) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        request = {"method": "GET", "path": path, "params": {k: str(v) for k, v in sorted(params.items())}}
        # The body is embedded verbatim (not re-serialized) so replay parses identical bytes.
        text = (
            '{"request": ' + json.dumps(request) + ',\n'
            ' "fetched_at": ' + json.dumps(fetched_at.isoformat()) + ',\n'
            ' "response": ' + body.strip() + '}\n'
        )
        self._cache_file(key).write_text(text)
        index_file = self.cache_dir / "index.json"
        index = json.loads(index_file.read_text()) if index_file.exists() else {}
        index[key] = {"path": path, "params": request["params"], "fetched_at": fetched_at.isoformat()}
        index_file.write_text(json.dumps(dict(sorted(index.items(), key=lambda kv: (kv[1]["path"], kv[0]))), indent=1) + "\n")

    # -- transport

    async def _get(self, path: str, params: dict[str, Any] | None = None, *, daily: bool = False) -> tuple[dict, datetime]:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        key = _cache_key(path, params)
        if self.offline:
            hit = self._read_cache(key)
            if hit is None:
                raise CacheMiss(path, params)
            return hit
        if daily:
            hit = self._read_cache(key)
            if hit is not None and hit[1].date() == _utcnow().date():
                return hit
        try:
            body = await self._fetch(path, params)
        except KalshiError as e:
            # G15: if public reads are ever rejected, serve the cache rather than fail the desk.
            hit = self._read_cache(key) if e.status in (401, 403) else None
            if hit is None:
                raise
            return hit
        fetched_at = _utcnow()
        self._write_cache(key, path, params, body, fetched_at)
        return json.loads(body, parse_float=Decimal), fetched_at

    async def _fetch(self, path: str, params: dict[str, Any]) -> str:
        last = ""
        for attempt in range(TRIES):
            if attempt:
                await self._sleep(self._backoff_s * 2 ** (attempt - 1))
            try:
                async with self._sem:
                    r = await self._http.get(path, params=params)
            except httpx.TransportError as e:  # includes timeouts
                last = f"{type(e).__name__}: {e}"
                continue
            if r.status_code == 200:
                return r.text
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code == 429:
                ra = r.headers.get("Retry-After", "")
                wait = min(int(ra), MAX_RETRY_AFTER_S) if ra.isdigit() else 0
                if wait > 0 and attempt < TRIES - 1:
                    await self._sleep(wait)
                continue
            if r.status_code >= 500:
                continue
            raise KalshiError(f"GET {path} failed: {last}", status=r.status_code, path=path)
        raise KalshiError(f"GET {path} failed after {TRIES} tries: {last}", path=path)

    async def get_json(self, path: str, params: dict[str, Any] | None = None, *, daily: bool = False) -> tuple[Any, datetime]:
        """Any cached GET on this client's base URL (the Polymarket client reuses the cache this way)."""
        return await self._get(path, params, daily=daily)

    async def _paged(self, path: str, params: dict[str, Any], field: str) -> list[dict]:
        out: list[dict] = []
        cursor = None
        while True:
            body, _ = await self._get(path, {**params, "limit": PAGE_LIMIT, "cursor": cursor})
            out.extend(body.get(field) or [])
            cursor = body.get("cursor")
            if not cursor:
                return out

    # -- endpoints

    async def list_series(self, category: str) -> list[dict]:
        body, _ = await self._get("/series", {"category": category}, daily=True)
        return body.get("series") or []

    async def get_series(self, series_ticker: str) -> dict:
        """One series' metadata (fee_type, fee_multiplier, settlement_sources)."""
        body, _ = await self._get(f"/series/{series_ticker}", daily=True)
        return body["series"]

    async def list_markets(
        self, series_ticker: str, status: str = "open",
        min_close_ts: int | None = None, max_close_ts: int | None = None,
    ) -> list[dict]:
        return await self._paged("/markets", {
            "series_ticker": series_ticker, "status": status,
            "min_close_ts": min_close_ts, "max_close_ts": max_close_ts,
        }, "markets")

    async def get_market(self, ticker: str) -> dict:
        body, _ = await self._get(f"/markets/{ticker}")
        return body["market"]

    async def get_orderbook(self, ticker: str) -> Orderbook:
        body, fetched_at = await self._get(f"/markets/{ticker}/orderbook")
        return parse_orderbook(ticker, body, fetched_at)

    async def list_settled(self, series_ticker: str, min_close_ts: int | None, max_close_ts: int | None) -> list[dict]:
        return await self.list_markets(series_ticker, "settled", min_close_ts, max_close_ts)

    async def candles(
        self, series_ticker: str, ticker: str, start_ts: int, end_ts: int, period_interval: int = 1440,
    ) -> list[dict]:
        """Daily candles. Markets settled before the archive cutoff (GET /historical/cutoff)
        404 on the live path and are only served under /historical/."""
        params = {"start_ts": start_ts, "end_ts": end_ts, "period_interval": period_interval}
        try:
            body, _ = await self._get(f"/series/{series_ticker}/markets/{ticker}/candlesticks", params)
        except (KalshiError, CacheMiss) as e:
            # Offline, the live path was never cached for archived markets; try /historical/ too.
            if isinstance(e, KalshiError) and e.status != 404:
                raise
            body, _ = await self._get(f"/historical/markets/{ticker}/candlesticks", params)
        return body.get("candlesticks") or []
