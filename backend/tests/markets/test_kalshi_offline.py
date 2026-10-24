"""C3-A25, C3-A27: online writes the cache (with pagination); offline replays it with zero network."""

import json

import httpx
import pytest

from app.markets.kalshi import CacheMiss, KalshiClient
from tests.conftest import MockKalshi, load

BASE = "https://kalshi.test/trade-api/v2"


def paged_markets(request: httpx.Request) -> httpx.Response:
    if request.url.params.get("cursor") == "p2":
        return httpx.Response(200, json={"markets": [{"ticker": "M3"}], "cursor": ""})
    return httpx.Response(200, json={"markets": [{"ticker": "M1"}, {"ticker": "M2"}], "cursor": "p2"})


ROUTES = {
    "/series": {"series": [{"ticker": "KXRAIN", "fee_type": "quadratic", "fee_multiplier": 1}]},
    "/markets": paged_markets,
    "/markets/M1": {"market": {"ticker": "M1", "floor_strike": 70.5, "rules_primary": "..."}},
    "/markets/M1/orderbook": load("markets_test/book_basic.json"),
}


async def _read_all(k: KalshiClient):
    return (
        await k.list_series("Climate and Weather"),
        await k.list_markets("KXRAIN"),
        await k.get_market("M1"),
        await k.get_orderbook("M1"),
    )


async def test_online_writes_cache_then_offline_replays_without_network(tmp_path):
    online = MockKalshi(ROUTES)
    async with KalshiClient(BASE, offline=False, cache_dir=tmp_path, transport=online.transport) as k:
        live = await _read_all(k)

    assert [m["ticker"] for m in live[1]] == ["M1", "M2", "M3"]  # followed the cursor
    assert len(online.calls) == 5  # series, 2 market pages, market, book
    index = json.loads((tmp_path / "index.json").read_text())
    assert len(index) == 5
    assert all((tmp_path / f"{key}.json").exists() for key in index)
    assert sorted(e["path"] for e in index.values()) == [
        "/markets", "/markets", "/markets/M1", "/markets/M1/orderbook", "/series"]

    def refuse(request):
        raise AssertionError(f"offline mode touched the network: {request.url}")
    offline = MockKalshi({})
    offline.transport = httpx.MockTransport(refuse)
    async with KalshiClient(BASE, offline=True, cache_dir=tmp_path, transport=offline.transport) as k:
        replay = await _read_all(k)
        with pytest.raises(CacheMiss):
            await k.get_orderbook("NOT-CACHED")

    assert replay == live  # includes Orderbook.fetched_at and Decimal floor_strike
    assert str(replay[2]["floor_strike"]) == "70.5"


def test_offline_flag_comes_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    assert KalshiClient(cache_dir=tmp_path).offline is True
    monkeypatch.setenv("DEMO_OFFLINE", "0")
    assert KalshiClient(cache_dir=tmp_path).offline is False
