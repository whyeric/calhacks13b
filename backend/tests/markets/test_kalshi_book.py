"""C3-A3, C3-A4, C3-A29: price parsing, ask derivation from opposite bids, book shape."""

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import BaseModel

from app.markets.kalshi import (
    KalshiClient, Level, ask_levels, best_ask, parse_orderbook, parse_price,
)
from app.markets.match import build_candidates
from tests.conftest import FIXTURES, load

T0 = datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)
D = Decimal


def lv(p, n):
    return Level(price=D(p), count=n)


def test_parse_price_decimal_only():
    assert parse_price("0.4200") == D("0.42")
    assert str(parse_price("0.4200")) == "0.42"
    assert str(parse_price("1.0000")) == "1"
    with pytest.raises(TypeError):
        parse_price(0.42)
    with pytest.raises(ValueError):
        parse_price("1.01")


def test_ask_is_one_minus_opposite_best_bid():
    book = parse_orderbook("T", load("markets_test/book_basic.json"), T0)
    assert book.yes_bids == [lv("0.38", 50), lv("0.35", 20)]  # best first, despite ascending wire order
    assert best_ask(book, "yes") == D("0.42")
    assert best_ask(book, "no") == D("0.62")
    assert ask_levels(book, "yes") == [lv("0.42", 40), lv("0.45", 30), lv("0.50", 100)]
    assert ask_levels(book, "no") == [lv("0.62", 50), lv("0.65", 20)]

    no_yes_bids = book.model_copy(update={"yes_bids": []})
    assert best_ask(no_yes_bids, "no") is None
    assert ask_levels(no_yes_bids, "no") == []
    assert best_ask(no_yes_bids, "yes") == D("0.42")


def test_legacy_cents_shape_nulls_and_unknown_keys():
    body = {"orderbook": {"yes": [[35, 20], [38, 50]], "no": None, "mystery": 1}, "extra": {}}
    book = parse_orderbook("T", body, T0)
    assert book.yes_bids == [lv("0.38", 50), lv("0.35", 20)]
    assert book.no_bids == []
    assert best_ask(book, "yes") is None


def test_fractional_sizes_round_down():
    body = {"orderbook_fp": {"yes_dollars": [["0.3000", "0.60"], ["0.3800", "10.60"]], "no_dollars": []}}
    assert parse_orderbook("T", body, T0).yes_bids == [lv("0.38", 10)]  # sub-1 level dropped


def _cached(path_suffix: str) -> dict:
    index = json.loads((FIXTURES / "kalshi_cache/index.json").read_text())
    key = next(k for k, v in index.items() if v["path"].endswith(path_suffix))
    return json.loads((FIXTURES / f"kalshi_cache/{key}.json").read_text(), parse_float=Decimal)


def test_recorded_live_book_shape():
    # Live books carry fractional sizes ("1334302.28"); only whole contracts are usable.
    body = _cached("ORLNYK-NYK/orderbook")["response"]
    assert "orderbook_fp" in body
    book = parse_orderbook("KXNBAGAME-26OCT25ORLNYK-NYK", body, T0)
    for levels in (book.yes_bids, book.no_bids):
        assert levels and all(type(x.count) is int and x.count > 0 for x in levels)
        assert all(type(x.price) is Decimal for x in levels)
        assert [x.price for x in levels] == sorted((x.price for x in levels), reverse=True)
    wire_no = body["orderbook_fp"]["no_dollars"]
    assert best_ask(book, "yes") == 1 - max(D(p) for p, _ in wire_no)


def _walk_for_float(obj, path="$"):
    if isinstance(obj, float):
        raise AssertionError(f"float at {path}: {obj!r}")
    if isinstance(obj, BaseModel):
        obj = dict(obj)
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk_for_float(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _walk_for_float(v, f"{path}[{i}]")


async def test_no_float_in_book_or_candidates_from_real_cache():
    async with KalshiClient(offline=True) as k:
        cands = []
        for var in ("rain", "hot", "home_win"):
            cands += await build_candidates(k, {"settlement_var": var}, T0)
        assert cands
        for c in cands:
            _walk_for_float(c)
            _walk_for_float(await k.get_orderbook(c.ticker))
            _walk_for_float(await k.get_market(c.ticker))
        dumped = json.loads(cands[0].model_dump_json())
        assert isinstance(dumped["yes_ask"], str)
