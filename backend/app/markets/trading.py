"""Orders on Kalshi's DEMO exchange after the owner approves a hedge, and the demo portfolio's
settlements for reconciliation (docs/KALSHI_DEMO.md).

Demo only. `DemoTradingClient` refuses any host outside `DEMO_HOSTS` before it signs or sends
anything, so a production URL in `.env` cannot place a real-money order. Demo money is fake and
everything here is labeled "kalshi_demo" (I6).

Who can trade: only `on_owner_approval`, which the approve route calls after the owner's
approval (and any controller co-sign) has booked. It re-checks `decided_by == "owner"`. Nothing
under `app.agent` imports this module, so the desk can never place an order (I4).

What is sent (Kalshi Trade API v2, verified against docs.kalshi.com, API 3.34.0):
  POST /portfolio/events/orders  {ticker, side: bid|ask, count, price, time_in_force,
       self_trade_prevention_type, client_order_id}
  V2 quotes every order on the YES leg: buying YES is `bid` at the YES price; buying NO is
  `ask` (sell YES) at 1 - the NO price. Counts and prices are fixed-point strings.
  - count  <= the hedge's filled contracts, which sizing already capped at the measured
              exposure (I1); the order never asks for more.
  - price  <= the hedge's worst quoted level (its book walk), floored to the cent.
  - time_in_force "immediate_or_cancel": fills what it can now, cancels the rest; nothing rests.
  - client_order_id is derived from the hedge id, so a retry can't double the order (Kalshi
    answers 409 for a duplicate, and we read the existing order back).

Booking is not touched: the ledger keeps the approved figures. The actual fill is stored on
`Hedge.venue_order` (and in the `order_*` log entries), so reconciliation can compare the
venue's fill with what was booked.

Auth: every request carries KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP (ms) and
KALSHI-ACCESS-SIGNATURE = base64(RSA-PSS-SHA256(timestamp + METHOD + path)), the path from
the host root (`/trade-api/v2/...`) without the query string. Ed25519 keys sign the same
message directly.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from app import clock, db
from app.books.sources import VenueSettlement
from app.config import FIXTURES_DIR, REPO_ROOT, Settings, get_settings
from app.models import Hedge, VenueOrder

log = logging.getLogger(__name__)

DEMO_HOSTS = frozenset({"demo-api.kalshi.co", "external-api.demo.kalshi.co"})
ORIGIN = "kalshi_demo"
TIME_IN_FORCE = "immediate_or_cancel"
SELF_TRADE = "taker_at_cross"
OPEN_STATUSES = frozenset({"active", "open"})
STAND_INS_FILE = FIXTURES_DIR / "kalshi_demo_stand_ins.json"
TIMEOUT_S = 10
MAX_PAGES = 20
ONE = Decimal("1")
CENT = Decimal("0.01")
TICK = Decimal("0.0001")
LABEL = "Kalshi demo (fake money)"
_COID_NS = uuid.UUID("6f1d8a52-5c1e-4b4e-9a53-0f7a8d3e2b10")  # fixed: client_order_id is reproducible


class TradingError(Exception):
    """A demo trading call that failed (HTTP error, bad response, refused host)."""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class NotDemoHost(TradingError):
    """The URL is not a Kalshi demo host. Nothing was signed or sent."""


# --- Settings and safety -----------------------------------------------------------------


def ensure_demo_url(url: str) -> None:
    """Refuse anything but https on a Kalshi demo host (raises NotDemoHost)."""
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in DEMO_HOSTS:
        raise NotDemoHost(f"refusing to trade on {parts.scheme}://{parts.hostname}: "
                          f"only the Kalshi demo hosts {sorted(DEMO_HOSTS)} are allowed", code="not_demo_host")


def _blank(v: str | None) -> bool:
    return v is None or not v.strip()


def private_key_file(s: Settings) -> Path | None:
    if _blank(s.kalshi_private_key_path):
        return None
    p = Path(s.kalshi_private_key_path.strip()).expanduser()
    return p if p.is_absolute() else REPO_ROOT / p


def host_allowed(s: Settings) -> bool:
    try:
        ensure_demo_url(s.kalshi_demo_base_url)
        return True
    except NotDemoHost:
        return False


def trading_off_reason(s: Settings | None = None) -> str | None:
    """None when approvals place demo orders; otherwise why they don't."""
    s = s or get_settings()
    if not s.kalshi_trading_enabled:
        return "KALSHI_TRADING_ENABLED is off"
    if s.demo_offline:
        return "DEMO_OFFLINE is on; no order is sent"
    if _blank(s.kalshi_api_key_id):
        return "KALSHI_API_KEY_ID is not set"
    key = private_key_file(s)
    if key is None or not key.is_file():
        return "KALSHI_PRIVATE_KEY_PATH does not point at a key file"
    if not host_allowed(s):
        return "KALSHI_DEMO_BASE_URL is not a Kalshi demo host"
    return None


# --- Signing -----------------------------------------------------------------------------


def load_private_key(path: Path):
    from cryptography.hazmat.primitives import serialization

    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def sign(private_key: Any, timestamp_ms: str, method: str, path: str) -> str:
    """base64 signature of `timestamp_ms + METHOD + path` (query string stripped)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    message = f"{timestamp_ms}{method.upper()}{path.split('?')[0]}".encode()
    if isinstance(private_key, Ed25519PrivateKey):
        sig = private_key.sign(message)
    else:
        sig = private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
    return base64.b64encode(sig).decode()


# --- Parsing -----------------------------------------------------------------------------


def _dec(v: Any) -> Decimal:
    if isinstance(v, (float, bool)) or v is None:
        raise TradingError(f"expected a fixed-point string, got {v!r}")
    try:
        return Decimal(str(v))
    except InvalidOperation as e:
        raise TradingError(f"not a number: {v!r}") from e


def _count(v: Any) -> int:
    """Fixed-point count ("300.00") to whole contracts, rounded down."""
    return int(_dec(v).to_integral_value(rounding=ROUND_FLOOR))


def _price(v: Decimal) -> Decimal:
    q = v.quantize(TICK, rounding=ROUND_HALF_UP)
    return q.quantize(ONE) if q == q.to_integral_value() else q.normalize()


def client_order_id(hedge_id: str) -> str:
    """Deterministic per hedge (UUID form, like Kalshi's examples): a retry reuses it."""
    return str(uuid.uuid5(_COID_NS, f"hedge-desk/{hedge_id}"))


# --- Client ------------------------------------------------------------------------------


class DemoTradingClient:
    """Authenticated Kalshi demo client. Sync: the approve route is a sync handler."""

    def __init__(self, base_url: str, key_id: str, private_key: Any, *,
                 transport: httpx.BaseTransport | None = None, timeout: float = TIMEOUT_S):
        ensure_demo_url(base_url)
        self.base_url = base_url.rstrip("/")
        self.key_id = key_id
        self._key = private_key
        self._http = httpx.Client(transport=transport, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> DemoTradingClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                body: dict[str, Any] | None = None, ok_404: bool = False) -> Any:
        url = self.base_url + path
        ensure_demo_url(url)  # checked on every request, before signing
        ts = str(int(time.time() * 1000))
        headers = {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sign(self._key, ts, method, urlsplit(url).path),
            "Accept": "application/json",
        }
        content = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            content = json.dumps(body)
        try:
            r = self._http.request(method, url, params=params, headers=headers, content=content)
        except httpx.HTTPError as e:
            raise TradingError(f"{method} {path}: {type(e).__name__}: {e}") from e
        if ok_404 and r.status_code == 404:
            return None
        try:
            data = json.loads(r.text, parse_float=Decimal) if r.text else {}
        except ValueError:
            data = {}
        if r.status_code >= 400:
            err = data.get("error", data) if isinstance(data, dict) else {}
            err = err if isinstance(err, dict) else {}
            raise TradingError(f"{method} {path} -> {r.status_code}: {err.get('message') or r.text[:200]}",
                               status=r.status_code, code=err.get("code"))
        return data

    def _paged(self, path: str, field: str, params: dict[str, Any] | None = None) -> list[dict]:
        out: list[dict] = []
        params = dict(params or {}, limit=200)
        for _ in range(MAX_PAGES):
            data = self.request("GET", path, params=params)
            out += data.get(field) or []
            cursor = data.get("cursor")
            if not cursor:
                break
            params["cursor"] = cursor
        return out

    def balance(self) -> Decimal:
        data = self.request("GET", "/portfolio/balance")
        if data.get("balance_dollars") is not None:
            return _dec(data["balance_dollars"])
        return _dec(data["balance"]) / 100  # integer cents (older field)

    def market(self, ticker: str) -> dict | None:
        data = self.request("GET", f"/markets/{ticker}", ok_404=True)
        return None if data is None else data.get("market")

    def create_order(self, *, ticker: str, book_side: str, count: int, price: Decimal,
                     client_order_id: str, time_in_force: str = TIME_IN_FORCE) -> dict:
        return self.request("POST", "/portfolio/events/orders", body={
            "ticker": ticker,
            "client_order_id": client_order_id,
            "side": book_side,
            "count": str(count),
            "price": f"{price:.4f}",
            "time_in_force": time_in_force,
            "self_trade_prevention_type": SELF_TRADE,
        })

    def get_order(self, order_id: str) -> dict:
        return self.request("GET", f"/portfolio/orders/{order_id}")["order"]

    def find_order(self, ticker: str, client_order_id: str) -> dict | None:
        for o in self._paged("/portfolio/orders", "orders", {"ticker": ticker}):
            if o.get("client_order_id") == client_order_id:
                return o
        return None

    def fills(self, *, ticker: str | None = None, order_id: str | None = None) -> list[dict]:
        params = {k: v for k, v in (("ticker", ticker), ("order_id", order_id)) if v}
        return self._paged("/portfolio/fills", "fills", params)

    def positions(self) -> list[dict]:
        return self._paged("/portfolio/positions", "market_positions")

    def settlements(self) -> list[dict]:
        return self._paged("/portfolio/settlements", "settlements")


def make_client(s: Settings | None = None, *, transport: httpx.BaseTransport | None = None) -> DemoTradingClient:
    """Client from settings. Refuses a non-demo host before reading the key."""
    s = s or get_settings()
    ensure_demo_url(s.kalshi_demo_base_url)
    key = private_key_file(s)
    if _blank(s.kalshi_api_key_id) or key is None:
        raise TradingError("no Kalshi demo API key configured", code="no_key")
    return DemoTradingClient(s.kalshi_demo_base_url, s.kalshi_api_key_id.strip(), load_private_key(key),
                             transport=transport)


# --- Which demo market ---------------------------------------------------------------------


def load_stand_ins(path: Path = STAND_INS_FILE) -> dict[str, str]:
    """series ticker -> demo market ticker, explicitly configured (fixtures/kalshi_demo_stand_ins.json)."""
    try:
        return dict(json.loads(path.read_text()).get("stand_ins") or {})
    except FileNotFoundError:
        return {}


def series_of(ticker: str) -> str:
    return ticker.split("-", 1)[0]


def resolve_demo_ticker(client: DemoTradingClient, ticker: str,
                        stand_ins: dict[str, str] | None = None) -> tuple[str | None, bool, str]:
    """(demo ticker, is_stand_in, note). The same ticker when demo lists it open; else the
    configured stand-in for its series; else (None, False, why)."""
    m = client.market(ticker)
    if m is not None and m.get("status") in OPEN_STATUSES:
        return ticker, False, "same ticker listed on demo"
    series = series_of(ticker)
    alt = (load_stand_ins() if stand_ins is None else stand_ins).get(series)
    if alt:
        sm = client.market(alt)
        if sm is not None and sm.get("status") in OPEN_STATUSES:
            return alt, True, f"demo stand-in {alt} for series {series}, not the production contract"
        return None, False, f"not listed on demo, and the configured stand-in {alt} is not open there"
    status = "not listed" if m is None else f"listed but {m.get('status')}"
    return None, False, f"not listed on demo ({ticker} is {status}; no stand-in configured for {series})"


# --- Order on approval -------------------------------------------------------------------


def order_limits(hedge: Hedge) -> tuple[int, Decimal | None]:
    """(contracts, max price in the hedge's side). Count is the hedge's filled N, never above
    its target (I1); price is the worst level of the quoted book walk, floored to the cent."""
    count = min(hedge.n_filled, hedge.n_target)
    levels = [f.price for f in hedge.fills or []]
    top = max(levels) if levels else hedge.avg_price
    if top is None:
        return count, None
    top = top.quantize(CENT, rounding=ROUND_FLOOR)
    return count, top if Decimal("0") < top < ONE else None


def _book(side: str, limit: Decimal) -> tuple[str, Decimal]:
    """Kalshi V2 quotes YES: buy YES = bid at p; buy NO at p = ask (sell YES) at 1 - p."""
    return ("bid", limit) if side == "yes" else ("ask", ONE - limit)


def _order(hedge: Hedge, **kw: Any) -> VenueOrder:
    base: dict[str, Any] = dict(
        mode=ORIGIN, client_order_id=client_order_id(hedge.id), order_id=None, ticker=None,
        production_ticker=hedge.ticker, stand_in=False, side=hedge.side, book_side=None,
        time_in_force=TIME_IN_FORCE, requested=0, limit_price=None, filled=0, avg_price=None,
        cost=None, fee=None, differs_from_booked=True, reason=None, at=clock.now(),
    )
    return VenueOrder.model_validate(base | kw)


def _fill_from(resp: dict, side: str) -> tuple[int, Decimal | None, Decimal | None]:
    """(filled, avg price in the hedge's side, fee) from a V2 create response or an Order."""
    if "fill_count" in resp:  # CreateOrderV2Response
        filled = _count(resp["fill_count"])
        yes_avg = _dec(resp["average_fill_price"]) if filled and resp.get("average_fill_price") is not None else None
        fee = _dec(resp.get("average_fee_paid") or "0") * filled
    else:  # Order object (duplicate client_order_id: read back)
        filled = _count(resp.get("fill_count_fp") or "0")
        cost = _dec(resp.get("taker_fill_cost_dollars") or "0") + _dec(resp.get("maker_fill_cost_dollars") or "0")
        fee = _dec(resp.get("taker_fees_dollars") or "0") + _dec(resp.get("maker_fees_dollars") or "0")
        # fill cost is in the order's own outcome side already
        own = cost / filled if filled else None
        return filled, (_price(own) if own is not None else None), fee.quantize(CENT, rounding=ROUND_CEILING)
    if yes_avg is None:
        return filled, None, fee.quantize(CENT, rounding=ROUND_CEILING)
    avg = yes_avg if side == "yes" else ONE - yes_avg
    return filled, _price(avg), fee.quantize(CENT, rounding=ROUND_CEILING)


def place_hedge_order(client: DemoTradingClient, hedge: Hedge, log_fn: Callable[[dict], Any]) -> VenueOrder:
    """Send the approved hedge's order to Kalshi demo and log every step (I5). Never raises
    for a venue problem: the result's status says filled / partial / failed / skipped."""
    def event(kind: str, summary: str, numbers: dict[str, Any]) -> None:
        log_fn({"business_id": hedge.business_id, "kind": kind, "actor": "system", "hedge_id": hedge.id,
                "decision_id": hedge.decision.id, "status": hedge.status,
                "numbers": {k: v for k, v in numbers.items() if v is not None} | {"venue": ORIGIN},
                "summary": f"{LABEL}: {summary}"})

    def skipped(why: str) -> VenueOrder:
        event("order_skipped", f"no order for {hedge.id}: {why}.", {})
        return _order(hedge, status="skipped", reason=why)

    if hedge.venue != "kalshi":
        return skipped(f"{hedge.venue} hedges are not traded")
    if hedge.ticker is None:
        return skipped("the hedge has no market")
    count, limit = order_limits(hedge)
    if count <= 0:
        return skipped("the hedge has no filled contracts")
    if limit is None:
        return skipped("the hedge has no quoted price to cap the order")

    coid = client_order_id(hedge.id)
    try:
        ticker, stand_in, note = resolve_demo_ticker(client, hedge.ticker)
    except TradingError as e:
        event("order_failed", f"could not look up {hedge.ticker} on demo: {e}", {"requested": count})
        return _order(hedge, status="failed", requested=count, limit_price=limit, reason=f"market lookup failed: {e}")
    if ticker is None:
        return skipped(note)

    book_side, book_price = _book(hedge.side, limit)
    common = dict(ticker=ticker, stand_in=stand_in, book_side=book_side, requested=count, limit_price=limit)
    nums = {"requested": count, "limit_price": limit, "ticker": ticker, "stand_in": stand_in}
    try:
        try:
            resp = client.create_order(ticker=ticker, book_side=book_side, count=count, price=book_price,
                                       client_order_id=coid)
        except TradingError as e:
            if e.status != 409:  # 409: this client_order_id was already used, so read that order back
                raise
            resp = client.find_order(ticker, coid)
            if resp is None:
                raise
        order_id = resp.get("order_id")
        filled, avg, fee = _fill_from(resp, hedge.side)
    except TradingError as e:
        event("order_failed", f"order for {hedge.id} on {ticker} was not accepted: {e}. The approval and "
              "booking stand.", nums)
        return _order(hedge, status="failed", reason=str(e), **common)

    where = f"{ticker} (demo stand-in, not the production contract {hedge.ticker})" if stand_in else ticker
    event("order_placed", f"order {order_id} for {hedge.id}: up to {count} {hedge.side.upper()} on {where} "
          f"at or below ${limit}, immediate-or-cancel.", nums | {"order_id": order_id})
    cost = (avg * filled).quantize(CENT, rounding=ROUND_HALF_UP) if avg is not None else None
    differs = filled != hedge.n_filled or (avg is not None and hedge.avg_price is not None and avg != hedge.avg_price)
    out = nums | {"order_id": order_id, "filled": filled, "avg_price": avg, "cost": cost, "fee": fee,
                  "booked_n": hedge.n_filled, "booked_avg_price": hedge.avg_price}
    if filled == 0:
        why = "nothing filled at or below the limit; immediate-or-cancel canceled the order"
        event("order_failed", f"{hedge.id}: {why}. The approval and booking stand; booked figures now "
              "differ from the venue.", out)
        return _order(hedge, status="failed", order_id=order_id, reason=why, **common)
    status = "filled" if filled == count else "partial"
    if status == "filled":
        reason = None
        event("order_filled", f"{hedge.id}: filled {filled} {hedge.side.upper()} at avg ${avg}"
              + (" (differs from the booked figures)" if differs else "") + ".", out)
    else:
        reason = f"filled {filled} of {count} contracts; immediate-or-cancel canceled the rest"
        event("order_partial", f"{hedge.id}: {reason}, avg ${avg}. Booking stays at the approved "
              f"{hedge.n_filled}; reconciliation will flag the difference.", out)
    return _order(hedge, status=status, order_id=order_id, filled=filled, avg_price=avg, cost=cost,
                  fee=fee, differs_from_booked=differs, reason=reason, **common)


def on_owner_approval(hedge: Hedge, log_fn: Callable[[dict], Any], *,
                      client: DemoTradingClient | None = None, settings: Settings | None = None) -> Hedge:
    """After the owner's approval booked: place the demo order when trading is on.

    Off, offline or without keys this returns `hedge` untouched and sends nothing. It never
    raises: a venue failure is logged and recorded on the hedge, and the approval stands."""
    s = settings or get_settings()
    if hedge.status != "approved" or hedge.decided_by != "owner":  # I4: owner approvals only
        return hedge
    if trading_off_reason(s) is not None or hedge.venue_order is not None:
        return hedge
    order: VenueOrder | None = None
    try:
        own = client is None
        client = client or make_client(s)
        try:
            order = place_hedge_order(client, hedge, log_fn)
        finally:
            if own:
                client.close()
    except Exception as e:  # never let the venue turn an approval into a 5xx
        log.exception("demo order for %s failed", hedge.id)
        try:
            log_fn({"business_id": hedge.business_id, "kind": "order_failed", "actor": "system",
                    "hedge_id": hedge.id, "decision_id": hedge.decision.id, "status": hedge.status,
                    "numbers": {"venue": ORIGIN},
                    "summary": f"{LABEL}: order for {hedge.id} failed ({type(e).__name__}: {e}). "
                               "The approval and booking stand."})
            order = _order(hedge, status="failed", reason=f"{type(e).__name__}: {e}")
        except Exception:
            log.exception("could not record the failed demo order for %s", hedge.id)
            return hedge
    try:
        stored = db.get_hedge(hedge.id) or hedge
        db.put_hedge(stored.model_copy(update={"venue_order": order}))
    except Exception:
        log.exception("could not store the demo order on %s", hedge.id)
    return hedge.model_copy(update={"venue_order": order})


# --- Venue source for reconciliation -----------------------------------------------------


class KalshiVenueSource:
    """`books.sources.VenueSource` over the Kalshi demo portfolio.

    Kalshi settlement records carry the market ticker but no order id, so each settlement is
    tied to a hedge through the orders we placed: hedges whose `venue_order.ticker` matches,
    narrowed by the demo account's fills on that ticker (fill.order_id == venue_order.order_id).
    A settlement that maps to no hedge, or to more than one, comes back with hedge_id=None for
    every business, so reconciliation flags it. Offline or with trading off: no calls, []."""

    origin = ORIGIN

    def __init__(self, client: DemoTradingClient | None = None, settings: Settings | None = None):
        self._client = client
        self._settings = settings

    def settlements(self, business_id: str) -> list[VenueSettlement]:
        s = self._settings or get_settings()
        if s.demo_offline or (self._client is None and trading_off_reason(s) is not None):
            return []
        client = self._client or make_client(s)
        try:
            return self._read(client, business_id)
        finally:
            if self._client is None:
                client.close()

    def _read(self, client: DemoTradingClient, business_id: str) -> list[VenueSettlement]:
        from app.books.ledger import ny_date

        placed = [h for h in db.list_hedges() if h.venue_order is not None and h.venue_order.order_id]
        out: list[VenueSettlement] = []
        for st in client.settlements():
            ticker = st.get("ticker") or ""
            cands = [h for h in placed if h.venue_order.ticker == ticker]
            if cands:
                try:
                    ids = {f.get("order_id") for f in client.fills(ticker=ticker)}
                    cands = [h for h in cands if h.venue_order.order_id in ids] or cands
                except TradingError:
                    pass  # fall back to the ticker match
            hedge = cands[0] if len(cands) == 1 else None
            if hedge is not None and hedge.business_id != business_id:
                continue
            if st.get("revenue_dollars") is not None:
                revenue = _dec(st["revenue_dollars"])
            else:
                revenue = _dec(st.get("revenue", 0)) / 100  # integer cents
            settled_time = str(st.get("settled_time") or "")
            settled_on = ny_date(datetime.fromisoformat(settled_time.replace("Z", "+00:00"))) if settled_time \
                else clock.now().astimezone(UTC).date()
            out.append(VenueSettlement(
                hedge_id=hedge.id if hedge else None,
                ticker=ticker,
                settled_on=settled_on,
                revenue=revenue.quantize(CENT),
                fee=_dec(st.get("fee_cost") or "0").quantize(CENT, rounding=ROUND_CEILING),
                external_id=f"{ticker}@{settled_time}" if settled_time else ticker,
                origin=ORIGIN,
            ))
        return out
