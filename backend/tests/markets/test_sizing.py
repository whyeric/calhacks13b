"""C3-A1, A2, A5–A12: fee rounding, side, book walk, N*, cost, payoff."""

import random
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from app.markets.kalshi import Level, parse_orderbook
from app.markets.match import Candidate, Depth
from app.markets.sizing import (
    order_fee, payoff_table, size_hedge, taker_fee, target_contracts, walk_book,
)
from tests.conftest import load

T0 = datetime(2026, 10, 24, tzinfo=timezone.utc)
STD = {"fee_type": "quadratic", "fee_multiplier": "1"}


def lv(p, n):
    return Level(price=D(p), count=n)


def exposure(beta, side, var="rain"):
    return {"id": "exp", "business_id": "b", "effect_usd": str(beta), "hedge_side": side,
            "settlement_var": var, "direction": "positive"}


CAND = Candidate(
    ticker="T", series_ticker="S", title="", close_time=T0, status="active", rules_primary="",
    floor_strike=None, settlement_var="rain", fee_type="quadratic", fee_multiplier=D(1),
    yes_ask=None, no_ask=None, yes_bid=None, no_bid=None, depth_within_5c=Depth(yes=0, no=0), fetched_at=T0,
)
BOOK = parse_orderbook("T", load("markets_test/book_basic.json"), T0)  # A4 book


@pytest.mark.parametrize("c,p,fee", [(100, "0.40", "1.68"), (10, "0.62", "0.17"), (1, "0.50", "0.02"), (3, "0.10", "0.02")])
def test_taker_fee_rounds_up_to_cent(c, p, fee):
    got = taker_fee(c, D(p))
    assert got == D(fee) and str(got) == fee


def test_fee_multiplier_and_unverified_flag():
    assert taker_fee(10, D("0.62"), D(2)) == D("0.33")  # 0.32984 -> 0.33
    flags = {}
    for name, fee in {"std": STD, "x2": {"fee_type": "quadratic", "fee_multiplier": "2"},
                      "flat": {"fee_type": "flat", "fee_multiplier": "1"}}.items():
        flags[name] = size_hedge(exposure(100, "yes"), CAND, BOOK, D(1), D("0.27"), fee).fee_unverified
    assert flags == {"std": False, "x2": True, "flat": True}


def test_side_comes_only_from_hedge_side():
    no = size_hedge(exposure(1240, "no"), CAND, BOOK, D(1), D("0.27"), STD)
    yes = size_hedge(exposure(-900, "yes"), CAND, BOOK, D(1), D("0.27"), STD)
    assert (no.side, no.fills[0].price) == ("no", D("0.62"))
    assert (yes.side, yes.fills[0].price) == ("yes", D("0.42"))
    flipped = exposure(1240, "no") | {"direction": "negative"}
    assert size_hedge(flipped, CAND, BOOK, D(1), D("0.27"), STD) == no


def test_walk_three_levels_stops_on_slippage():
    f = walk_book([lv("0.42", 40), lv("0.45", 30), lv("0.50", 100)], 100)
    assert f.fills == [lv("0.42", 40), lv("0.45", 30)]
    assert (f.n_filled, f.n_unfilled, f.cost, f.stopped_reason) == (70, 30, D("30.30"), "slippage")
    assert round(f.avg_price, 6) == D("0.432857")
    assert order_fee(f.fills) == D("1.21")  # 0.68208 + 0.51975, rounded once


def test_walk_slippage_boundary_is_inclusive():
    f = walk_book([lv("0.42", 40), lv("0.47", 30), lv("0.48", 30)], 100)
    assert f.n_filled == 70 and f.fills[-1].price == D("0.47")


def test_walk_filled_and_exhausted():
    f = walk_book([lv("0.42", 40), lv("0.45", 30), lv("0.50", 100)], 30)
    assert (f.fills, f.stopped_reason) == ([lv("0.42", 30)], "filled")
    f = walk_book([lv("0.42", 20), lv("0.43", 20)], 500)
    assert (f.n_filled, f.stopped_reason) == (40, "book_exhausted")
    f = walk_book([], 10)
    assert (f.n_filled, f.avg_price, f.stopped_reason) == (0, None, "book_exhausted")


@pytest.mark.parametrize("beta,h,n", [("1240", "1", 1240), ("900", "0.5", 450), ("825", "0.5", 413), ("900", "0.3333", 300)])
def test_n_star_ceil(beta, h, n):
    assert target_contracts(D(beta), D(h)) == n


def test_contracts_never_exceed_exposure():
    rng = random.Random(7)
    for _ in range(500):
        beta = D(rng.randint(15000, 500000)) / 100 * rng.choice([1, -1])
        h = D(rng.randint(1, 10000)) / 10000
        n = target_contracts(beta, h)
        assert n <= int(abs(beta))
        assert walk_book([lv("0.40", 10**6)], n).n_filled <= n
    assert target_contracts(D("1240.50"), D(1)) == 1240
    assert target_contracts(D(900), D(620) / D(900)) == 620
    assert target_contracts(D(4999), D(999) / D(4999)) == 999  # 28-digit tail would ceil to 1000
    for bad in ("0", "1.01", "-0.5"):
        with pytest.raises(ValueError):
            target_contracts(D(900), D(bad))


def test_expected_cost_premium_and_no_side_fair():
    book = parse_orderbook("T", {"orderbook_fp": {"yes_dollars": [], "no_dollars": [
        ["0.5000", "100"], ["0.5500", "30"], ["0.5800", "40"]]}}, T0)
    hd = size_hedge(exposure(-100, "yes"), CAND, book, D(1), D("0.27"), STD)
    assert (hd.n_filled, hd.cost, hd.fee, hd.premium) == (70, D("30.30"), D("1.21"), D("31.51"))
    assert hd.expected_cost == D("12.61")
    assert size_hedge(exposure(100, "no"), CAND, BOOK, D(1), D("0.27"), STD).fair == D("0.73")


@pytest.mark.parametrize("beta,side,n", [("1240", "no", 1240), ("-900", "yes", 900), ("1240.50", "no", 1240)])
def test_payoff_has_premium_in_both_rows_and_is_flat(beta, side, n):
    P = D("41.20")
    ev, no_ev = payoff_table(exposure(beta, side), side, n, P)
    assert (ev.outcome, no_ev.outcome) == ("event", "no_event")
    assert ev.premium == no_ev.premium == -P
    assert ev.net_vs_base == D(beta) + (n if side == "yes" else 0) - P
    assert no_ev.net_vs_base == (n if side == "no" else 0) - P
    assert abs(ev.net_vs_base - no_ev.net_vs_base) <= abs(D(beta)) - n


def test_headline_matches_table():
    deep = parse_orderbook("T", {"orderbook_fp": {"yes_dollars": [["0.7000", "5000"]], "no_dollars": []}}, T0)
    hd = size_hedge(exposure(1240, "no"), CAND, deep, D(1), D("0.27"), STD)
    assert hd.headline.unhedged_swing == D("1240.00")
    assert hd.headline.hedged_swing == abs(hd.payoff[0].net_vs_base - hd.payoff[1].net_vs_base) == 0
    assert hd.headline.cost == hd.premium
