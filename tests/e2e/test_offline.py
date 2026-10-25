"""C8-A10 offline_never_touches_network: with DEMO_OFFLINE=1 the full A4 and A5 flows make zero
outbound requests (httpx transports spied, sockets and DNS blocked by conftest), and a missing
cache file raises `CacheMiss` instead of a live call."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil

import httpx
import pytest

from conftest import CACHE_DIR, HAS_RESTAURANT_DATA, run_desk


@pytest.fixture
def http_spy(monkeypatch):
    calls: list[str] = []

    async def async_refuse(self, request):
        calls.append(f"{request.method} {request.url}")
        raise httpx.ConnectError("e2e: offline", request=request)

    def refuse(self, request):
        calls.append(f"{request.method} {request.url}")
        raise httpx.ConnectError("e2e: offline", request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_refuse)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    return calls


def _flow(client, b):
    client.post(f"/businesses/{b}/analyze", json={})
    run = run_desk(client, b)
    for h in client.get(f"/businesses/{b}/hedges").json():
        if h["status"] in ("proposed", "pending_approval"):
            client.post(f"/hedges/{h['id']}/approve", json={"actor": "owner"})
    client.post(f"/businesses/{b}/reconcile", json={})
    for url in ("/ledger", "/decisions", "/backtest", "/settings"):
        assert client.get(f"/businesses/{b}{url}").status_code < 500, url
    assert client.post(f"/businesses/{b}/chat", json={"message": "why was it declined?"}).status_code == 200
    return run


def test_a10_full_flows_make_no_requests(client, http_spy):
    assert client.get("/health").json()["offline"] is True
    taxi = _flow(client, "taxi")
    assert taxi["status"] == "done"
    restaurant = _flow(client, "restaurant")
    assert restaurant["status"] == ("done" if HAS_RESTAURANT_DATA else "failed")
    assert http_spy == [], f"outbound HTTP while offline: {http_spy}"


def test_a10_missing_cache_file_is_cache_miss(tmp_path, http_spy):
    from app.markets.kalshi import CacheMiss, KalshiClient

    cache = tmp_path / "kalshi_cache"
    shutil.copytree(CACHE_DIR, cache)
    index = json.loads((cache / "index.json").read_text())
    key, req = next((k, v) for k, v in index.items() if v["path"] == "/markets")
    (cache / f"{key}.json").unlink()

    async def go():
        async with KalshiClient(offline=True, cache_dir=cache) as k:
            with pytest.raises(CacheMiss):
                await k._get(req["path"], req["params"])
            other = next(kk for kk, v in index.items() if kk != key)
            await k._get(index[other]["path"], index[other]["params"])  # the rest still replays

    asyncio.run(go())
    assert http_spy == []


def test_a10_desk_survives_cache_miss_without_going_live(client, http_spy, monkeypatch, caplog):
    """Every cache read misses: the desk must not fall through to the network; the miss is loud
    (logged or surfaced on the run / hedge) and the API stays up."""
    from app.markets import kalshi

    monkeypatch.setattr(kalshi.KalshiClient, "_read_cache", lambda self, key: None)
    with caplog.at_level(logging.WARNING):
        run = run_desk(client, "taxi")
    assert http_spy == []
    hedges = client.get("/businesses/taxi/hedges").json()
    surfaced = ("CacheMiss" in (run.get("error") or "") or "CacheMiss" in caplog.text
                or any("no_market" in h["decision"]["reasons"] for h in hedges if h["id"].startswith("hdg_taxi")))
    assert surfaced, (run, caplog.text[-2000:])
    print(f"\nC8-A10 cache miss: run {run['status']} error={run.get('error')!r}; hedges "
          f"{[(h['id'], h['status'], h['decision']['reasons']) for h in hedges]}")
    assert client.get("/health").status_code == 200
