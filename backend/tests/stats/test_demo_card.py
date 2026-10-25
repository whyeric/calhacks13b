"""The scripted "Send to the desk" card (markets/demo_card.py) is sized from the live report (I1)."""

from decimal import Decimal
from pathlib import Path

import pytest

from app.markets import demo_card
from app.markets.sizing import taker_fee
from app.stats import research

SAMPLE = Path(__file__).resolve().parents[3] / "frontend/public/samples/hudson_bike_co_daily_revenue.csv"


@pytest.fixture(scope="module")
def report():
    rep = research.run(SAMPLE.read_bytes(), "Hudson Bike Co.")
    assert rep.demo_hedge is None  # stats stays pure; the route attaches the card
    return rep.model_copy(update={"demo_hedge": demo_card.plan(rep.hypotheses)})


def test_contracts_are_the_measured_rain_exposure(report):
    rain = next(h for h in report.hypotheses if h.id == "rain")
    card = report.demo_hedge
    assert card is not None and card.hypothesis_id == "rain"
    assert card.contracts == int(-rain.train.effect_usd)  # floor(|effect| / $1)
    assert card.contracts <= -rain.train.effect_usd  # I1
    assert card.payout == Decimal(card.contracts)


def test_premium_is_price_plus_kalshi_fee(report):
    card = report.demo_hedge
    assert card.price == demo_card.CARD_PRICE
    assert card.fee == taker_fee(card.contracts, card.price)
    assert card.premium == card.contracts * card.price + card.fee


def test_payoff_and_budgets_follow_the_premium(report):
    card = report.demo_hedge
    event, dry = card.payoff
    assert event.revenue_vs_base == next(h for h in report.hypotheses if h.id == "rain").train.effect_usd
    assert event.premium == dry.premium == dry.net_vs_base == -card.premium
    assert card.budgets.pending.pending == card.budgets.approved.spent == card.premium
    assert card.budgets.open.remaining == demo_card.DEMO_BUDGET
    assert card.expected_cost == (card.premium - card.payout * card.p_event).quantize(Decimal("0.01"))


def test_precomputed_size_reproduces_the_old_card():
    # The old hardcoded card (frontend DEMO_HEDGE): 1,955 contracts @ 33¢ → $30.26 fee, $675.41 premium.
    assert taker_fee(1955, demo_card.CARD_PRICE) == Decimal("30.26")
    assert 1955 * demo_card.CARD_PRICE + taker_fee(1955, demo_card.CARD_PRICE) == Decimal("675.41")


def test_no_card_without_a_sendable_rain_row(report):
    rows = [h.model_copy(update={"sendable": False}) if h.id == "rain" else h for h in report.hypotheses]
    assert demo_card.plan(rows) is None
