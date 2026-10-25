"""Polymarket as a second venue: book folding, fees, candidates, sizing and booking. Offline."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from app import config, db
from app.books import ledger
from app.markets import polymarket
from app.markets.kalshi import ask_levels, best_ask
from app.markets.rules import check_no_market
from app.markets.sizing import order_fee, size_hedge
from app.models import Exposure, Level

NOW = datetime(2026, 10, 24, 19, 0, tzinfo=UTC)  # Sat; New York's today is Oct 24
YES_TOKEN, NO_TOKEN = "111", "222"


def _rain_event(day: str = "october-26", city: str = "New York, NY", fee: dict | None = None) -> list[dict]:
    market = {
        "slug": f"where-will-it-rain-on-{day}-2026-new-york-ny", "groupItemTitle": city,
        "question": "Will it rain in New York, NY on October 26?", "outcomes": '["Yes", "No"]',
        "clobTokenIds": json.dumps([YES_TOKEN, NO_TOKEN]), "endDate": "2026-10-27T18:00:00Z",
        "active": True, "closed": False, "acceptingOrders": True,
        "feeSchedule": fee if fee is not None else {"exponent": 1, "rate": 0, "takerOnly": True, "rebateRate": 0},
    }
    return [{"slug": f"where-will-it-rain-on-{day}-2026", "title": "Where will it rain on October 26?",
             "endDate": "2026-10-27T18:00:00Z", "description": "NWS Daily Climate Report (CLI).",
             "markets": [market]}]


BOOKS = {
    YES_TOKEN: {"asks": [{"price": "0.99", "size": "10"}, {"price": "0.34", "size": "120.5"}, {"price": "0.36", "size": "80"}],
                "bids": [{"price": "0.30", "size": "50"}]},
    NO_TOKEN: {"asks": [{"price": "0.68", "size": "200"}], "bids": []},
}


def _transport(events: dict[str, list], books: dict = BOOKS) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "gamma.test" and request.url.path == "/events":
            return httpx.Response(200, json=events.get(request.url.params.get("slug"), []))
        if request.url.host == "clob.test" and request.url.path == "/book":
            return httpx.Response(200, json=books[request.url.params["token_id"]])
        return httpx.Response(404, json={})
    return httpx.MockTransport(handle)


@pytest.fixture
def pm_settings(monkeypatch):
    monkeypatch.setenv("POLYMARKET_GAMMA_URL", "https://gamma.test")
    monkeypatch.setenv("POLYMARKET_CLOB_URL", "https://clob.test")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def _client(tmp_path, events, books=BOOKS, offline=False):
    return polymarket.PolymarketClient(offline=offline, cache_dir=tmp_path / "pm", transport=_transport(events, books))


def test_token_asks_fold_into_a_kalshi_shaped_book():
    book = polymarket.combine_books("t", BOOKS[YES_TOKEN], BOOKS[NO_TOKEN], NOW)
    # YES asks come straight from the YES token, cheapest first; fractional shares round down.
    assert ask_levels(book, "yes") == [Level(price=Decimal("0.34"), count=120), Level(price=Decimal("0.36"), count=80),
                                       Level(price=Decimal("0.99"), count=10)]
    assert best_ask(book, "no") == Decimal("0.68")


def test_fee_rate_follows_the_market_schedule():
    assert polymarket.fee_terms({"feeSchedule": {"exponent": 1, "rate": 0.05}}) == ("polymarket_taker", Decimal("0.05"))
    assert polymarket.fee_terms({}) == ("polymarket_unknown", Decimal("0"))
    # docs.polymarket.com example: 100 shares at $0.50, sports rate 0.05 -> $1.25
    assert order_fee([Level(price=Decimal("0.5"), count=100)], rate=Decimal("0.05")) == Decimal("1.25")
    assert order_fee([Level(price=Decimal("0.5"), count=100)], rate=Decimal("0")) == Decimal("0.00")


async def test_rain_candidates_for_the_desk_week(tmp_path, pm_settings):
    events = {polymarket.rain_slug(date(2026, 10, 26)): _rain_event()}
    async with _client(tmp_path, events) as pm:
        cands, books, note = await polymarket.build_candidates(pm, "rain", NOW, week_of=date(2026, 10, 26))
    assert note is None
    [c] = cands
    assert (c.venue, c.ticker, c.yes_ask, c.depth_within_5c.yes) == (
        "polymarket", "where-will-it-rain-on-october-26-2026-new-york-ny", Decimal("0.34"), 200)
    assert c.settlement_source == polymarket.RAIN_SOURCE
    assert c.market_url == "https://polymarket.com/event/where-will-it-rain-on-october-26-2026"
    assert c.fee_type == "polymarket_taker" and c.fee_rate == 0
    assert c.ticker in books


async def test_other_cities_are_not_candidates(tmp_path, pm_settings):
    events = {polymarket.rain_slug(date(2026, 10, 26)): _rain_event(city="Boston, MA")}
    async with _client(tmp_path, events) as pm:
        cands, _, _ = await polymarket.build_candidates(pm, "rain", NOW, week_of=date(2026, 10, 26))
    assert cands == []


async def test_hot_is_skipped_with_the_station_reason(tmp_path, pm_settings):
    async with _client(tmp_path, {}) as pm:
        cands, _, note = await polymarket.build_candidates(pm, "hot", NOW, week_of=date(2026, 10, 26))
    assert cands == [] and "LaGuardia" in note


async def test_offline_miss_is_a_note_not_a_failure(tmp_path, pm_settings):
    async with _client(tmp_path, {}, offline=True) as pm:
        cands, books, note = await polymarket.build_candidates(pm, "rain", NOW, week_of=date(2026, 10, 26))
    assert (cands, books) == ([], {}) and "offline cache" in note


async def test_offline_replays_what_was_warmed(tmp_path, pm_settings):
    events = {polymarket.rain_slug(date(2026, 10, 26)): _rain_event()}
    async with _client(tmp_path, events) as pm:  # warm
        live, _, _ = await polymarket.build_candidates(pm, "rain", NOW, week_of=date(2026, 10, 26))
    async with _client(tmp_path, {}, books={}, offline=True) as pm:
        replay, _, _ = await polymarket.build_candidates(pm, "rain", NOW, week_of=date(2026, 10, 26))
    assert [c.model_dump(exclude={"fetched_at"}) for c in replay] == [c.model_dump(exclude={"fetched_at"}) for c in live]


async def test_game_slug_uses_polymarket_team_codes():
    assert polymarket.game_slug("nhl", "LA", "nyr", date(2026, 10, 26)) == "nhl-lak-nyr-2026-10-26"
    assert polymarket.game_slug("nba", "DET", "nyk", date(2026, 10, 27)) == "nba-det-nyk-2026-10-27"


async def test_sizing_on_a_polymarket_book_uses_its_fee_and_caps_at_exposure(tmp_path, pm_settings):
    events = {polymarket.rain_slug(date(2026, 10, 26)): _rain_event(fee={"exponent": 1, "rate": 0.05})}
    async with _client(tmp_path, events) as pm:
        [c], books, _ = await polymarket.build_candidates(pm, "rain", NOW, week_of=date(2026, 10, 26))
    exposure = {"business_id": "taxi", "id": "exp_rain", "effect_usd": "-150.40", "hedge_side": "yes"}
    s = size_hedge(exposure, c, books[c.ticker], Decimal("1"), Decimal("0.30"), c)
    assert s.n_target == 150  # I1: floor(|β| / $1)
    assert s.n_filled == 150 and s.cost == Decimal("51.60")  # 120 @ 0.34 + 30 @ 0.36
    raw = Decimal("0.05") * (120 * Decimal("0.34") * Decimal("0.66") + 30 * Decimal("0.36") * Decimal("0.64"))
    assert s.fee == raw.quantize(Decimal("0.01"), rounding="ROUND_CEILING")
    assert not s.fee_unverified and s.venue == "polymarket" and s.fee_rate == Decimal("0.05")


def test_no_market_counts_each_venue():
    assert check_no_market([], "").metric == {"n_candidates": 0, "n_kalshi": 0, "n_polymarket": 0}
    assert check_no_market([]).metric == {"n_candidates": 0}  # Kalshi-only callers are unchanged


def test_polymarket_hedge_books_to_its_own_cash_account(tmp_path):
    from tests.books.conftest import APPROVED_AT, make_hedge

    engine = db.make_engine(f"sqlite:///{tmp_path / 'b.db'}")
    db.create_schema(engine)
    hedge = make_hedge("hdg_pm", ticker="where-will-it-rain-on-october-26-2026-new-york-ny")
    hedge = hedge.model_copy(update={"venue": "polymarket", "fee_rate": Decimal("0")})
    approved, [entry] = ledger.approve_hedge(hedge, "owner", at=APPROVED_AT, engine=engine, ledger_dir=tmp_path)
    assert {p.account for p in entry.postings} == {ledger.PREMIUMS, ledger.FEES, ledger.POLYMARKET_CASH}
    assert entry.narration.startswith("Premium (Polymarket):")
    opening = ledger.get_entry("taxi", ledger.opening_entry_id("taxi", "polymarket"), engine)
    assert opening is not None and opening.postings[0].account == ledger.POLYMARKET_CASH
    assert f"open {ledger.POLYMARKET_CASH} USD" in ledger.render_ledger("taxi", engine)


async def test_committed_cache_replays_the_demo_week():
    """fixtures/polymarket_cache/ was warmed for the pinned demo time (make warm, DEMO_AS_OF)."""
    async with polymarket.PolymarketClient(offline=True) as pm:
        games, _, note = await polymarket.build_candidates(pm, "home_win", NOW, week_of=date(2026, 10, 26))
        rain, _, rain_note = await polymarket.build_candidates(pm, "rain", NOW, week_of=date(2026, 10, 26))
    assert note is None and rain_note is None
    assert "nhl-lak-nyr-2026-10-26" in [c.ticker for c in games]
    assert all(c.venue == "polymarket" and c.settlement_var == "home_win" for c in games)
    assert rain == []  # no "Where will it rain" event was listed yet for that week when it was warmed
