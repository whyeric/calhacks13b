"""C3-A22, C3-A23, C3-A24: candidate filter, empty list, off-list guard."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import httpx
import pytest

from app.markets.kalshi import KalshiClient
from app.markets.match import (
    Candidate, Depth, OffListError, build_candidates, deterministic_pick, validate_pick,
)
from tests.conftest import MockKalshi, load

BASE = "https://kalshi.test/trade-api/v2"
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def mkt(ticker, close, status="active", **kw):
    return {"ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0], "title": ticker,
            "close_time": iso(close), "status": status, "rules_primary": "", **kw}


def series(ticker):
    return {"series": {"ticker": ticker, "fee_type": "quadratic", "fee_multiplier": 1}}


def routes(markets_by_series, books=None):
    def markets(request):
        return httpx.Response(200, json={"markets": markets_by_series.get(
            request.url.params["series_ticker"], []), "cursor": ""})
    r = {f"/series/{s}": series(s) for s in ("KXRAIN", "KXHIGHNY", "KXNBAGAME", "KXNHLGAME")}
    r["/markets"] = markets
    for s in markets_by_series.values():
        for m in s:
            r[f"/markets/{m['ticker']}/orderbook"] = (books or {}).get(m["ticker"], load("markets_test/book_basic.json"))
    return r


async def candidates(markets_by_series, var, tmp_path, books=None):
    mock = MockKalshi(routes(markets_by_series, books))
    async with KalshiClient(BASE, offline=False, cache_dir=tmp_path, transport=mock.transport) as k:
        return await build_candidates(k, {"settlement_var": var, "hedge_side": "yes"}, NOW)


async def test_rain_filter_city_status_and_window_boundary(tmp_path):
    d = timedelta(days=1)
    rain = [
        mkt("KXRAIN-26OCT31-NYC", NOW + 7 * d),
        mkt("KXRAIN-26OCT31-LAX", NOW + 7 * d),                      # wrong city
        mkt("KXRAIN-26OCT26-NYC", NOW + 2 * d, status="closed"),     # not open
        mkt("KXRAIN-26NOV02-NYC", NOW + 9 * d),                      # day 9
        mkt("KXRAIN-26NOV01-NYC", NOW + 8 * d),                      # exactly now+8d: in
        mkt("KXRAIN-26NOV01X-NYC", NOW + 8 * d + timedelta(seconds=1)),  # +1s: out
        mkt("KXRAIN-26OCT23-NYC", NOW - timedelta(seconds=1)),       # already closed
    ]
    got = await candidates({"KXRAIN": rain}, "rain", tmp_path)
    assert sorted(c.ticker for c in got) == ["KXRAIN-26NOV01-NYC", "KXRAIN-26OCT31-NYC"]
    c = got[0]
    assert (c.yes_ask, c.no_ask, c.yes_bid, c.no_bid) == (
        D("0.42"), D("0.62"), D("0.38"), D("0.58"))
    assert c.depth_within_5c == Depth(yes=70, no=70)  # 0.42+0.45 (0.50 is +8¢); 0.62+0.65


async def test_home_win_only_ny_home_yes_side(tmp_path):
    d = timedelta(days=1)
    nba = [
        mkt("KXNBAGAME-26OCT25ORLNYK-NYK", NOW + 3 * d),  # Knicks at home, YES = Knicks win
        mkt("KXNBAGAME-26OCT25ORLNYK-ORL", NOW + 3 * d),  # same game, YES = Orlando win
        mkt("KXNBAGAME-26OCT29NYKBOS-NYK", NOW + 5 * d),  # Knicks away
    ]
    nhl = [mkt("KXNHLGAME-26OCT26LANYR-NYR", NOW + 4 * d), mkt("KXNHLGAME-26OCT26LANYR-LA", NOW + 4 * d)]
    got = await candidates({"KXNBAGAME": nba, "KXNHLGAME": nhl}, "home_win", tmp_path)
    assert sorted(c.ticker for c in got) == ["KXNBAGAME-26OCT25ORLNYK-NYK", "KXNHLGAME-26OCT26LANYR-NYR"]


async def test_hot_uses_greater_threshold_markets_only(tmp_path):
    close = NOW + timedelta(days=1)
    hi = [
        mkt("KXHIGHNY-26OCT25-T71", close, strike_type="greater", floor_strike=71),
        mkt("KXHIGHNY-26OCT25-T64", close, strike_type="less", cap_strike=64),
        mkt("KXHIGHNY-26OCT25-B66.5", close, strike_type="between", floor_strike=66, cap_strike=67),
    ]
    got = await candidates({"KXHIGHNY": hi}, "hot", tmp_path)
    assert [c.ticker for c in got] == ["KXHIGHNY-26OCT25-T71"]
    assert str(got[0].floor_strike) == "71"


async def test_no_nyc_rain_market_is_empty_not_error(tmp_path):
    rain = [mkt("KXRAIN-26OCT25-LAX", NOW + timedelta(days=1))]
    assert await candidates({"KXRAIN": rain}, "rain", tmp_path) == []
    assert await candidates({}, "rain", tmp_path) == []


def cand(ticker, yes=0, no=0):
    return Candidate(
        ticker=ticker, series_ticker="S", title="", close_time=NOW, status="active", rules_primary="",
        floor_strike=None, settlement_var="rain", fee_type="quadratic", fee_multiplier=1,
        yes_ask=None, no_ask=None, yes_bid=None, no_bid=None,
        depth_within_5c=Depth(yes=yes, no=no), fetched_at=NOW,
    )


def test_validate_pick_rejects_off_list():
    cs = [cand("T1"), cand("T2")]
    assert validate_pick(cs, "T1", "deepest book").ticker == "T1"
    for bad in ("T3", "", "t1"):
        with pytest.raises(OffListError) as e:
            validate_pick(cs, bad, "x")
        assert e.value.allowed == ["T1", "T2"]
    with pytest.raises(OffListError):
        validate_pick([], "T1", "x")


def test_deterministic_pick_uses_hedge_side_depth():
    cs = [cand("A", yes=100, no=5), cand("B", yes=10, no=50)]
    assert deterministic_pick(cs, "yes").ticker == "A"
    assert deterministic_pick(cs, "no").ticker == "B"
    assert deterministic_pick([], "no") is None
