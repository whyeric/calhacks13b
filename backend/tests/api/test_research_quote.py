"""POST /research/quote: a FOUND downside from an uploaded CSV priced live (offline caches)."""

from pathlib import Path

import pytest

from app import config

SAMPLE = Path(__file__).resolve().parents[3] / "frontend/public/samples/hudson_bike_co_daily_revenue.csv"


@pytest.fixture
def live_markets(monkeypatch):
    monkeypatch.setenv("MARKETS_BACKEND", "kalshi")
    monkeypatch.setenv("POLYMARKET_ENABLED", "1")
    config.get_settings.cache_clear()


def _quote(client, hypothesis="rain"):
    return client.post(f"/research/quote?hypothesis={hypothesis}&name=Hudson", content=SAMPLE.read_bytes(),
                       headers={"Content-Type": "text/csv"})


def test_rain_is_priced_across_both_venues(client, live_markets):
    r = _quote(client)
    assert r.status_code == 200, r.text
    q = r.json()
    h, e = q["hedge"], q["exposure"]
    assert e["event"] == "rain" and e["hedge_side"] == "yes" and e["business_id"] == "upload"
    assert h["n_target"] <= int(-float(e["effect_usd"]))  # I1: contracts <= |exposure| / $1
    assert [c["code"] for c in h["decision"]["checks"]][0] == "no_market"
    no_market = h["decision"]["checks"][0]["metric"]
    assert no_market["n_kalshi"] >= 1 and no_market["n_polymarket"] >= 1  # both venues were scanned
    assert "Also scanned" in h["match_reason"] and h["decision"]["summary"]
    assert q["window"]["start"] == "2026-10-25"


def test_non_sendable_rows_are_refused(client, live_markets):
    r = _quote(client, "cold")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_sendable"
    assert _quote(client, "snow").json()["error"]["code"] == "unknown_hypothesis"
