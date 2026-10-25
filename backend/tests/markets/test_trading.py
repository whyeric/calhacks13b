"""Kalshi DEMO trading (markets/trading.py): signing, demo-host guard, order caps (I1, price),
idempotent client_order_id, approval surviving the venue, settlement mapping, offline = no calls.

Everything authenticated runs against httpx.MockTransport; no real key exists.
"""

import base64
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
from fastapi.testclient import TestClient

from app import clock, config, db
from app.config import Settings
from app.markets import trading
from app.models import Hedge

EXAMPLES = Path(__file__).resolve().parents[2] / "fixtures" / "examples"
NOW = datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc)
DEMO = "https://demo-api.kalshi.co/trade-api/v2"
PROD = "https://external-api.kalshi.com/trade-api/v2"


@pytest.fixture(autouse=True)
def _no_sync_network(monkeypatch):
    """A request that reaches a real (sync) transport fails the test."""
    def refuse(self, request):
        raise AssertionError(f"network call in test: {request.url}")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def key_file(tmp_path, rsa_key):
    p = tmp_path / "kalshi-demo.pem"
    p.write_bytes(rsa_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
    return p


def settings(key_file: Path | None, **kw) -> Settings:
    base = dict(kalshi_trading_enabled=True, demo_offline=False, kalshi_demo_base_url=DEMO,
                kalshi_api_key_id="key-123", kalshi_private_key_path=str(key_file) if key_file else None)
    return Settings(_env_file=None, **(base | kw))


class MockVenue:
    """Kalshi demo routes: (METHOD, path) -> json body | (status, body) | callable(request)."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        key = (request.method, request.url.path.removeprefix("/trade-api/v2"))
        route = self.routes.get(key)
        if route is None:
            return httpx.Response(404, json={"error": {"code": "not_found", "message": "not found"}})
        if callable(route):
            route = route(request)
        status, body = route if isinstance(route, tuple) else (200, route)
        return httpx.Response(status, json=body)

    def posts(self) -> list[dict]:
        return [json.loads(r.content) for r in self.calls if r.method == "POST"]


def client_for(venue: MockVenue, rsa_key) -> trading.DemoTradingClient:
    return trading.DemoTradingClient(DEMO, "key-123", rsa_key, transport=venue.transport)


def approved(name: str = "hedge_proposed.json", **kw) -> Hedge:
    data = json.loads((EXAMPLES / name).read_text())
    data.update(status="approved", decided_by="owner", decided_at="2026-10-24T19:00:00Z", alternative=None,
                ledger_entry_ids=[f"le_{data['id']}_premium"])
    data.update(kw)
    return Hedge.model_validate(data)


def open_market(ticker: str, status: str = "active") -> dict:
    return {"market": {"ticker": ticker, "status": status}}


def order_resp(fill: str, avg: str | None = None, fee: str | None = None, oid: str = "ord-1") -> dict:
    body = {"order_id": oid, "client_order_id": "x", "fill_count": fill, "remaining_count": "0.00", "ts_ms": 1}
    if avg is not None:
        body |= {"average_fill_price": avg, "average_fee_paid": fee or "0.0175"}
    return body


@pytest.fixture
def logs():
    entries: list[dict] = []
    return entries


@pytest.fixture(autouse=True)
def mem_db(tmp_path, monkeypatch):
    """Every test gets a temp database, so nothing touches the dev db."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 't.db'}")
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.create_schema()
    monkeypatch.setattr(clock, "now", lambda: NOW)
    yield
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()


# --- Signing -----------------------------------------------------------------------------


def _verify(pub, sig_b64: str, message: str) -> None:
    pub.verify(base64.b64decode(sig_b64), message.encode(),
               padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
               hashes.SHA256())


def test_signature_is_rsa_pss_sha256_over_timestamp_method_path(rsa_key):
    sig = trading.sign(rsa_key, "1703123456789", "get", "/trade-api/v2/portfolio/orders?limit=5")
    _verify(rsa_key.public_key(), sig, "1703123456789GET/trade-api/v2/portfolio/orders")  # query stripped


def test_request_headers_sign_the_full_path_without_query(rsa_key):
    venue = MockVenue({("GET", "/portfolio/fills"): {"fills": [], "cursor": ""}})
    client_for(venue, rsa_key).fills(ticker="KXRAIN-26OCT25-NYC")
    req = venue.calls[0]
    assert req.url.host == "demo-api.kalshi.co" and req.url.params["ticker"] == "KXRAIN-26OCT25-NYC"
    assert req.headers["KALSHI-ACCESS-KEY"] == "key-123"
    ts = req.headers["KALSHI-ACCESS-TIMESTAMP"]
    assert ts.isdigit() and len(ts) == 13  # milliseconds
    _verify(rsa_key.public_key(), req.headers["KALSHI-ACCESS-SIGNATURE"], f"{ts}GET/trade-api/v2/portfolio/fills")


def test_ed25519_keys_sign_the_message_directly():
    k = ed25519.Ed25519PrivateKey.generate()
    sig = trading.sign(k, "1", "POST", "/trade-api/v2/portfolio/events/orders")
    k.public_key().verify(base64.b64decode(sig), b"1POST/trade-api/v2/portfolio/events/orders")


def test_make_client_loads_the_pem(key_file):
    with trading.make_client(settings(key_file)) as c:
        assert c.base_url == DEMO and c.key_id == "key-123"


# --- Demo host only ----------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    PROD, "https://api.elections.kalshi.com/trade-api/v2", "http://demo-api.kalshi.co/trade-api/v2",
    "https://demo-api.kalshi.co.evil.example/trade-api/v2", "https://kalshi.co/trade-api/v2",
])
def test_refuses_any_host_but_demo(url, rsa_key, key_file, logs):
    with pytest.raises(trading.NotDemoHost):
        trading.DemoTradingClient(url, "key-123", rsa_key)
    with pytest.raises(trading.NotDemoHost):
        trading.make_client(settings(key_file, kalshi_demo_base_url=url))
    s = settings(key_file, kalshi_demo_base_url=url)
    assert trading.trading_off_reason(s) == "KALSHI_DEMO_BASE_URL is not a Kalshi demo host"
    h = approved()
    assert trading.on_owner_approval(h, logs.append, settings=s) == h and logs == []


def test_guard_is_checked_on_every_request(rsa_key):
    venue = MockVenue({})
    c = client_for(venue, rsa_key)
    c.base_url = PROD  # tampered after construction
    with pytest.raises(trading.NotDemoHost):
        c.balance()
    assert venue.calls == []


@pytest.mark.parametrize("url", ["https://demo-api.kalshi.co/trade-api/v2",
                                 "https://external-api.demo.kalshi.co/trade-api/v2"])
def test_both_documented_demo_hosts_are_allowed(url):
    trading.ensure_demo_url(url)


# --- The order: I1 cap, price cap, sides --------------------------------------------------


def test_no_hedge_buys_no_by_asking_yes_at_one_minus_the_cap(rsa_key, logs):
    h = approved()  # hdg_04: NO, 420 filled, levels 0.50 x300 + 0.52 x120
    venue = MockVenue({("GET", f"/markets/{h.ticker}"): open_market(h.ticker),
                       ("POST", "/portfolio/events/orders"): (201, order_resp("420.00", "0.4943", "0.0175"))})
    order = trading.place_hedge_order(client_for(venue, rsa_key), h, logs.append)
    body = venue.posts()[0]
    assert body == {"ticker": h.ticker, "client_order_id": trading.client_order_id(h.id), "side": "ask",
                    "count": "420", "price": "0.4800", "time_in_force": "immediate_or_cancel",
                    "self_trade_prevention_type": "taker_at_cross"}
    assert order.status == "filled" and order.filled == 420 and order.limit_price == Decimal("0.52")
    assert order.avg_price == Decimal("0.5057") and order.book_side == "ask"
    assert order.cost == Decimal("212.39") and order.fee == Decimal("7.35")
    assert [e["kind"] for e in logs] == ["order_placed", "order_filled"]
    assert all(e["numbers"]["venue"] == "kalshi_demo" and "Kalshi demo" in e["summary"] for e in logs)


def test_yes_hedge_bids_at_the_worst_quoted_level(rsa_key, logs):
    h = approved(side="yes", payoff=None, headline=None)
    venue = MockVenue({("GET", f"/markets/{h.ticker}"): open_market(h.ticker),
                       ("POST", "/portfolio/events/orders"): (201, order_resp("420.00", "0.5057"))})
    trading.place_hedge_order(client_for(venue, rsa_key), h, logs.append)
    body = venue.posts()[0]
    assert body["side"] == "bid" and body["price"] == "0.5200"


def test_price_cap_never_exceeds_the_quote_and_floors_to_the_cent():
    h = approved(fills=None, avg_price="0.5057")
    count, limit = trading.order_limits(h)
    assert limit == Decimal("0.50") and limit <= h.avg_price
    h2 = approved()
    assert trading.order_limits(h2)[1] == max(f.price for f in h2.fills)


def test_count_is_capped_at_the_filled_contracts_i1(rsa_key, logs):
    # A partial hedge: 300 of 420 target filled. The order asks for 300, never the target.
    h = approved(n_filled=300, n_unfilled=120, fills=[{"price": "0.50", "count": 300}], partial=True)
    venue = MockVenue({("GET", f"/markets/{h.ticker}"): open_market(h.ticker),
                       ("POST", "/portfolio/events/orders"): (201, order_resp("300.00", "0.50"))})
    order = trading.place_hedge_order(client_for(venue, rsa_key), h, logs.append)
    assert venue.posts()[0]["count"] == "300" and order.requested == 300 <= h.n_target
    assert trading.order_limits(h)[0] <= h.n_filled <= h.n_target


def test_partial_fill_is_logged_and_flagged_against_the_booking(rsa_key, logs):
    h = approved()
    venue = MockVenue({("GET", f"/markets/{h.ticker}"): open_market(h.ticker),
                       ("POST", "/portfolio/events/orders"): (201, order_resp("300.00", "0.5000"))})
    order = trading.place_hedge_order(client_for(venue, rsa_key), h, logs.append)
    assert order.status == "partial" and order.filled == 300 and order.differs_from_booked
    assert order.avg_price == Decimal("0.5")
    assert logs[-1]["kind"] == "order_partial" and logs[-1]["numbers"]["booked_n"] == 420


def test_nothing_filled_is_order_failed(rsa_key, logs):
    h = approved()
    venue = MockVenue({("GET", f"/markets/{h.ticker}"): open_market(h.ticker),
                       ("POST", "/portfolio/events/orders"): (201, order_resp("0.00"))})
    order = trading.place_hedge_order(client_for(venue, rsa_key), h, logs.append)
    assert order.status == "failed" and order.filled == 0 and order.order_id == "ord-1"
    assert [e["kind"] for e in logs] == ["order_placed", "order_failed"]


def test_rejected_order_is_order_failed_with_the_reason(rsa_key, logs):
    h = approved()
    venue = MockVenue({("GET", f"/markets/{h.ticker}"): open_market(h.ticker),
                       ("POST", "/portfolio/events/orders"): (400, {"error": {"code": "insufficient_balance",
                                                                             "message": "insufficient balance"}})})
    order = trading.place_hedge_order(client_for(venue, rsa_key), h, logs.append)
    assert order.status == "failed" and "insufficient balance" in order.reason
    assert [e["kind"] for e in logs] == ["order_failed"]


# --- Idempotency --------------------------------------------------------------------------


def test_client_order_id_is_derived_from_the_hedge_id():
    assert trading.client_order_id("hdg_04") == trading.client_order_id("hdg_04")
    assert trading.client_order_id("hdg_04") != trading.client_order_id("hdg_01")


def test_duplicate_client_order_id_reads_the_existing_order_back(rsa_key, logs):
    h = approved()
    coid = trading.client_order_id(h.id)
    existing = {"order_id": "ord-first", "client_order_id": coid, "ticker": h.ticker, "status": "executed",
                "fill_count_fp": "420.00", "taker_fill_cost_dollars": "212.400000", "maker_fill_cost_dollars": "0",
                "taker_fees_dollars": "7.350000", "maker_fees_dollars": "0"}
    venue = MockVenue({("GET", f"/markets/{h.ticker}"): open_market(h.ticker),
                       ("POST", "/portfolio/events/orders"): (409, {"error": {"code": "duplicate", "message": "exists"}}),
                       ("GET", "/portfolio/orders"): {"orders": [existing], "cursor": ""}})
    order = trading.place_hedge_order(client_for(venue, rsa_key), h, logs.append)
    assert len(venue.posts()) == 1  # no second order
    assert order.order_id == "ord-first" and order.status == "filled" and order.avg_price == Decimal("0.5057")


def test_a_hedge_with_an_order_is_not_ordered_again(rsa_key, key_file, logs):
    h = approved()
    venue = MockVenue({})
    first = trading.on_owner_approval(h, logs.append, client=client_for(venue, rsa_key), settings=settings(key_file))
    assert first.venue_order is not None
    n = len(venue.calls)
    again = trading.on_owner_approval(first, logs.append, client=client_for(venue, rsa_key), settings=settings(key_file))
    assert again == first and len(venue.calls) == n


# --- Demo availability and stand-ins -------------------------------------------------------


def test_not_listed_on_demo_skips_the_order(rsa_key, logs, monkeypatch):
    monkeypatch.setattr(trading, "load_stand_ins", lambda: {})
    h = approved()
    venue = MockVenue({})  # 404 for the market
    order = trading.place_hedge_order(client_for(venue, rsa_key), h, logs.append)
    assert order.status == "skipped" and "not listed on demo" in order.reason and venue.posts() == []
    assert logs[0]["kind"] == "order_skipped"


def test_configured_stand_in_is_used_and_labeled(rsa_key, logs, monkeypatch):
    h = approved()
    alt = "KXNBAGAME-26OCT28NYKCHI-NYK"
    monkeypatch.setattr(trading, "load_stand_ins", lambda: {"KXNBAGAME": alt})
    venue = MockVenue({("GET", f"/markets/{alt}"): open_market(alt),
                       ("POST", "/portfolio/events/orders"): (201, order_resp("420.00", "0.4943"))})
    order = trading.place_hedge_order(client_for(venue, rsa_key), h, logs.append)
    assert venue.posts()[0]["ticker"] == alt and order.stand_in and order.production_ticker == h.ticker
    assert "demo stand-in, not the production contract" in logs[0]["summary"]


def test_closed_market_on_demo_is_not_listed(rsa_key, logs, monkeypatch):
    monkeypatch.setattr(trading, "load_stand_ins", lambda: {})
    h = approved()
    venue = MockVenue({("GET", f"/markets/{h.ticker}"): open_market(h.ticker, "closed")})
    assert trading.place_hedge_order(client_for(venue, rsa_key), h, logs.append).status == "skipped"


def test_stand_ins_file_parses():
    assert isinstance(trading.load_stand_ins(), dict)


# --- Who can trade (I4) -------------------------------------------------------------------


def test_only_owner_approved_hedges_are_traded(rsa_key, key_file, logs):
    data = json.loads((EXAMPLES / "hedge_proposed.json").read_text())
    h = Hedge.model_validate(data)  # proposed: not approved
    venue = MockVenue({})
    assert trading.on_owner_approval(h, logs.append, client=client_for(venue, rsa_key),
                                     settings=settings(key_file)) == h
    assert venue.calls == [] and logs == []


def test_the_desk_cannot_reach_the_trading_module():
    agent_dir = Path(trading.__file__).resolve().parents[1] / "agent"
    for p in agent_dir.rglob("*.py"):
        assert "trading" not in p.read_text(), f"{p} must not reference markets.trading (I4)"


# --- Offline / off ------------------------------------------------------------------------


@pytest.mark.parametrize("kw", [{"demo_offline": True}, {"kalshi_trading_enabled": False},
                                {"kalshi_api_key_id": None}, {"kalshi_api_key_id": "  "},
                                {"kalshi_private_key_path": None}])
def test_off_offline_or_no_keys_sends_nothing(kw, rsa_key, key_file, logs):
    venue = MockVenue({})
    h = approved()
    out = trading.on_owner_approval(h, logs.append, client=client_for(venue, rsa_key), settings=settings(key_file, **kw))
    assert out == h and out.venue_order is None and venue.calls == [] and logs == []


def test_missing_key_file_is_off(tmp_path):
    assert "KALSHI_PRIVATE_KEY_PATH" in trading.trading_off_reason(settings(tmp_path / "nope.pem"))


def test_offline_venue_source_makes_no_calls(rsa_key, key_file):
    venue = MockVenue({})
    src = trading.KalshiVenueSource(client_for(venue, rsa_key), settings(key_file, demo_offline=True))
    assert src.settlements("taxi") == [] and venue.calls == []
    assert trading.KalshiVenueSource(settings=settings(None)).settlements("taxi") == []


# --- Settlements for reconciliation -------------------------------------------------------


def test_settlements_map_to_hedges_through_our_orders(mem_db, rsa_key, key_file, logs):
    h = approved()
    t2 = approved(id="hdg_x", business_id="taxi", ticker="KXRAIN-26OCT25-NYC")
    venue = MockVenue({("GET", f"/markets/{h.ticker}"): open_market(h.ticker),
                       ("GET", f"/markets/{t2.ticker}"): open_market(t2.ticker),
                       ("POST", "/portfolio/events/orders"): lambda r: (201, order_resp(
                           "420.00", "0.4943", oid="ord-" + json.loads(r.content)["ticker"][:6]))})
    for hedge in (h, t2):
        db.put_hedge(hedge)
        trading.on_owner_approval(hedge, logs.append, client=client_for(venue, rsa_key), settings=settings(key_file))
    assert db.get_hedge(h.id).venue_order.order_id == "ord-KXNBAG"

    settlements = [
        {"ticker": h.ticker, "event_ticker": "E", "market_result": "no", "yes_count_fp": "0.00",
         "yes_total_cost_dollars": "0", "no_count_fp": "420.00", "no_total_cost_dollars": "212.39",
         "revenue": 42000, "settled_time": "2026-10-29T04:10:00Z", "fee_cost": "0.0000", "exchange_index": 0},
        {"ticker": t2.ticker, "event_ticker": "E2", "market_result": "yes", "yes_count_fp": "0.00",
         "yes_total_cost_dollars": "0", "no_count_fp": "420.00", "no_total_cost_dollars": "212.39",
         "revenue": 0, "settled_time": "2026-10-26T05:00:00Z", "fee_cost": "0", "exchange_index": 0},
        {"ticker": "KXOTHER-1", "event_ticker": "E3", "market_result": "yes", "yes_count_fp": "5.00",
         "yes_total_cost_dollars": "2.50", "no_count_fp": "0", "no_total_cost_dollars": "0",
         "revenue": 500, "settled_time": "2026-10-27T01:00:00Z", "fee_cost": "0.01", "exchange_index": 0},
    ]
    venue.routes[("GET", "/portfolio/settlements")] = {"settlements": settlements, "cursor": ""}
    venue.routes[("GET", "/portfolio/fills")] = lambda r: {"fills": [
        {"order_id": "ord-" + r.url.params["ticker"][:6], "ticker": r.url.params["ticker"]}], "cursor": ""}
    src = trading.KalshiVenueSource(client_for(venue, rsa_key), settings(key_file))
    assert src.origin == "kalshi_demo"

    rows = src.settlements("restaurant")
    by = {r.ticker: r for r in rows}
    assert set(by) == {h.ticker, "KXOTHER-1"}  # taxi's settlement belongs to taxi
    mine = by[h.ticker]
    assert mine.hedge_id == h.id and mine.revenue == Decimal("420.00") and mine.origin == "kalshi_demo"
    assert mine.settled_on.isoformat() == "2026-10-29" and mine.simulated  # demo money, not live
    assert by["KXOTHER-1"].hedge_id is None and by["KXOTHER-1"].revenue == Decimal("5.00")
    assert by["KXOTHER-1"].fee == Decimal("0.01")
    taxi = {r.ticker: r.hedge_id for r in src.settlements("taxi")}
    assert taxi == {t2.ticker: "hdg_x", "KXOTHER-1": None}


# --- Through the API: approval survives the venue -----------------------------------------


@pytest.fixture
def api(tmp_path, monkeypatch, key_file):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_MODEL", "")
    monkeypatch.setenv("MARKETS_BACKEND", "fixture")
    monkeypatch.setenv("LEDGERS_DIR", str(tmp_path / "ledgers"))
    monkeypatch.setenv("BACKTEST_ON_STARTUP", "0")
    monkeypatch.delenv("OWNER_TOKEN", raising=False)
    monkeypatch.delenv("CONTROLLER_TOKEN", raising=False)
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    monkeypatch.setattr(clock, "now", lambda: NOW)
    db.seed()
    from app.main import app

    with TestClient(app) as c:
        yield c
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()


def _trading_on(monkeypatch, key_file, rsa_key, venue: MockVenue | None, boom: Exception | None = None):
    monkeypatch.setattr(trading, "get_settings", lambda: settings(key_file))

    def make(_s=None, **_kw):
        if boom is not None:
            raise boom
        return client_for(venue, rsa_key)
    monkeypatch.setattr(trading, "make_client", make)


def test_offline_approval_is_unchanged(api):
    r = api.post("/hedges/hdg_01/approve", json={"actor": "owner"})
    assert r.status_code == 200 and r.json()["venue_order"] is None
    assert not [e for e in db.list_log(hedge_id="hdg_01") if e.kind.startswith("order_")]


@pytest.mark.parametrize("failure", ["http_500", "network", "exception"])
def test_approval_and_booking_stand_when_the_venue_fails(api, monkeypatch, key_file, rsa_key, failure):
    def network(_r):
        raise httpx.ConnectError("down")
    route = (500, {"error": {"message": "boom"}}) if failure == "http_500" else network
    venue = MockVenue({("GET", "/markets/KXHIGHNY-26OCT28-T65"): open_market("KXHIGHNY-26OCT28-T65"),
                       ("POST", "/portfolio/events/orders"): route})
    _trading_on(monkeypatch, key_file, rsa_key, venue, RuntimeError("kaput") if failure == "exception" else None)
    r = api.post("/hedges/hdg_01/approve", json={"actor": "owner"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved" and body["ledger_entry_ids"]
    assert body["venue_order"]["status"] == "failed" and body["venue_order"]["mode"] == "kalshi_demo"
    stored = db.get_hedge("hdg_01")
    assert stored.status == "approved" and stored.venue_order.status == "failed"
    assert [e.kind for e in db.list_ledger_entries("taxi")].count("premium") == 1
    kinds = [e.kind for e in db.list_log(hedge_id="hdg_01")]
    assert {"approval", "booking", "order_failed"} <= set(kinds)


def test_approval_places_the_order_and_keeps_booking_at_approved_figures(api, monkeypatch, key_file, rsa_key):
    t = "KXHIGHNY-26OCT28-T65"  # hdg_01: YES, 150 filled, levels 0.42 x120 + 0.45 x30, premium 66.47
    venue = MockVenue({("GET", f"/markets/{t}"): open_market(t),
                       ("POST", "/portfolio/events/orders"): (201, order_resp("100.00", "0.4300"))})
    _trading_on(monkeypatch, key_file, rsa_key, venue)
    r = api.post("/hedges/hdg_01/approve", json={"actor": "owner"})
    assert r.status_code == 200
    vo = r.json()["venue_order"]
    assert vo["status"] == "partial" and vo["filled"] == 100 and vo["requested"] == 150
    assert vo["limit_price"] == "0.45" and vo["avg_price"] == "0.43" and vo["differs_from_booked"] is True
    assert venue.posts()[0]["count"] == "150" and venue.posts()[0]["price"] == "0.4500"
    premium = next(e for e in db.list_ledger_entries("taxi") if e.kind == "premium")
    assert -min(p.amount for p in premium.postings) == Decimal("66.47")  # booked as approved
    assert db.get_hedge("hdg_01").venue_order.filled == 100
    kinds = [e.kind for e in db.list_log(hedge_id="hdg_01")]
    assert "order_placed" in kinds and "order_partial" in kinds


def test_status_route_off_offline(api):
    r = api.get("/integrations/kalshi/status")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "off" and body["reachable"] is None and body["balance"] is None


def test_status_route_reports_demo_balance(api, monkeypatch, key_file, rsa_key):
    from app.integrations import kalshi_routes

    venue = MockVenue({("GET", "/portfolio/balance"): {"balance": 100000, "balance_dollars": "1000.0000",
                                                         "portfolio_value": 0, "updated_ts": 1}})
    monkeypatch.setattr(kalshi_routes, "get_settings", lambda: settings(key_file))
    monkeypatch.setattr(trading, "make_client", lambda _s=None, **_k: client_for(venue, rsa_key))
    body = api.get("/integrations/kalshi/status").json()
    assert body["mode"] == "demo" and body["reachable"] is True and body["balance"] == "1000.00"
