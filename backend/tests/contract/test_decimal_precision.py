"""C6-A5: Decimal values never pass through float; premium parts add up exactly."""

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app import models

from .conftest import EXAMPLES, EXAMPLES_DIR, load_json, validate_example


def _one_contract_hedge() -> dict:
    """The proposed example resized to one contract at 0.62 with a 0.01 fee."""
    h = load_json(EXAMPLES_DIR / "hedge_proposed.json")
    h.update(
        n_target=1, n_filled=1, n_unfilled=0, fills=[{"price": "0.62", "count": 1}],
        avg_price="0.62", cost="0.62", fee="0.01", premium="0.63",
        headline={"unhedged_swing": "420.00", "hedged_swing": "419.00", "cost": "0.63"},
        payoff=[
            {"outcome": "event", "revenue_vs_base": "420.00", "contract_payout": "0.00", "premium": "-0.63", "net_vs_base": "419.37"},
            {"outcome": "no_event", "revenue_vs_base": "0.00", "contract_payout": "1.00", "premium": "-0.63", "net_vs_base": "0.37"},
        ],
    )
    return h


def test_price_and_fee_serialize_exactly():
    out = json.loads(models.Hedge.model_validate(_one_contract_hedge()).model_dump_json())
    assert out["avg_price"] == "0.62"
    assert out["fills"][0]["price"] == "0.62"
    assert out["fee"] == "0.01"
    assert out["premium"] == "0.63"


def test_float_input_is_rejected():
    h = _one_contract_hedge()
    h["fee"] = 0.01
    with pytest.raises(ValidationError, match="never a float"):
        models.Hedge.model_validate(h)
    with pytest.raises(ValidationError, match="never a float"):
        models.Level(price=0.62, count=1)
    with pytest.raises(ValidationError, match="float"):
        models.Check(code="overpriced", passed=True, metric={"avg_price": 0.62})


def test_too_many_places_is_rejected_not_rounded():
    with pytest.raises(ValidationError, match="2 decimal places"):
        models.Posting(account="Assets:Kalshi:Cash", amount="0.625")
    with pytest.raises(ValidationError, match="4 decimal places"):
        models.Level(price="0.62711", count=1)


def test_money_always_two_places():
    p = models.Posting(account="Assets:Kalshi:Cash", amount=Decimal("0.1") + Decimal("0.2"))
    assert json.loads(p.model_dump_json())["amount"] == "0.30"
    assert json.loads(models.Posting(account="x", amount=250).model_dump_json())["amount"] == "250.00"


def test_premium_mismatch_is_rejected():
    h = _one_contract_hedge()
    h["premium"] = "0.64"
    with pytest.raises(ValidationError, match="premium must equal cost \\+ fee"):
        models.Hedge.model_validate(h)


def test_many_small_parts_sum_without_drift():
    # 0.1 + 0.2 style drift: float sum of ten 0.07 fills is 0.7000000000000001.
    fills = [{"price": "0.07", "count": 1}] * 10
    cost = sum(Decimal(f["price"]) for f in fills)
    level = models.HedgeLite(
        h="1", n_target=10, n_filled=10, avg_price="0.07", cost=cost, fee="0.05", premium=cost + Decimal("0.05"),
        payoff=[
            {"outcome": "event", "revenue_vs_base": "10.00", "contract_payout": "0.00", "premium": "-0.75", "net_vs_base": "9.25"},
            {"outcome": "no_event", "revenue_vs_base": "0.00", "contract_payout": "10.00", "premium": "-0.75", "net_vs_base": "9.25"},
        ],
        headline={"unhedged_swing": "10.00", "hedged_swing": "0.00", "cost": "0.75"},
    )
    assert json.loads(level.model_dump_json())["cost"] == "0.70"


@pytest.mark.parametrize("name", sorted(n for n, m in EXAMPLES.items() if m == "Hedge"))
def test_example_premiums_add_up(name):
    _, parsed = validate_example(name)
    for h in parsed if isinstance(parsed, list) else [parsed]:
        if h.premium is None:
            continue
        assert h.cost + h.fee == h.premium
        assert sum(f.price * f.count for f in h.fills) == h.cost
        for row in h.payoff:
            assert row.revenue_vs_base + row.contract_payout + row.premium == row.net_vs_base
