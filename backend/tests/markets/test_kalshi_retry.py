"""C3-A26: retry timeouts / 429 / 5xx up to 3 tries; other 4xx fail at once with KalshiError."""

import httpx
import pytest

from app.markets.kalshi import KalshiClient, KalshiError

BASE = "https://kalshi.test/trade-api/v2"
OK = httpx.Response(200, json={"market": {"ticker": "M1"}})


def scripted(*steps):
    calls = []

    def handle(request):
        step = steps[len(calls)]
        calls.append(request)
        if isinstance(step, Exception):
            raise step
        return step
    return httpx.MockTransport(handle), calls


def client(transport, tmp_path, sleeps):
    async def sleep(s):
        sleeps.append(s)
    return KalshiClient(BASE, offline=False, cache_dir=tmp_path, transport=transport, sleep=sleep)


async def test_two_500s_then_success(tmp_path):
    sleeps = []
    t, calls = scripted(httpx.Response(500), httpx.Response(503), OK)
    async with client(t, tmp_path, sleeps) as k:
        assert (await k.get_market("M1"))["ticker"] == "M1"
    assert len(calls) == 3
    assert sleeps == [1, 2]  # exponential backoff


async def test_404_is_not_retried(tmp_path):
    t, calls = scripted(httpx.Response(404), OK)
    async with client(t, tmp_path, []) as k:
        with pytest.raises(KalshiError) as e:
            await k.get_market("M1")
    assert e.value.status == 404
    assert len(calls) == 1


async def test_timeouts_exhaust_into_kalshi_error(tmp_path):
    timeout = httpx.ReadTimeout("slow")
    t, calls = scripted(timeout, timeout, timeout, timeout)
    async with client(t, tmp_path, []) as k:
        with pytest.raises(KalshiError):
            await k.get_market("M1")
    assert len(calls) == 3


async def test_429_honors_retry_after(tmp_path):
    sleeps = []
    t, calls = scripted(httpx.Response(429, headers={"Retry-After": "4"}), OK)
    async with client(t, tmp_path, sleeps) as k:
        await k.get_market("M1")
    assert len(calls) == 2
    assert 4 in sleeps
