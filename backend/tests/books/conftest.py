"""Shared fixtures for C5 books tests: temp db, temp ledger dir, hedge factory. Offline."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app import db
from app.books import ledger
from app.models import Hedge

EXAMPLES = db.FIXTURES_DIR / "examples"
APPROVED_AT = datetime(2026, 10, 26, 16, 0, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path):
    e = db.make_engine(f"sqlite:///{tmp_path / 'books.db'}")
    db.create_schema(e)
    yield e
    e.dispose()


@pytest.fixture
def ledger_dir(tmp_path):
    d = tmp_path / "ledgers"
    d.mkdir()
    return d


def make_hedge(
    hedge_id: str = "hdg_01",
    *,
    business_id: str = "taxi",
    ticker: str = "KXHIGHNY-26OCT28-T65",
    side: str = "no",
    n: int = 40,
    price: str = "0.56",
    status: str = "proposed",
) -> Hedge:
    """A proposed hedge with cent-exact cost/fee/premium (fee by the Kalshi formula)."""
    data = json.loads((EXAMPLES / "hedge_proposed.json").read_text())
    p = Decimal(price)
    cost = (p * n).quantize(Decimal("0.01"))
    fee = ledger.taker_fee(n, p)
    data.update(
        id=hedge_id, business_id=business_id, ticker=ticker, side=side, status=status,
        n_target=n, n_filled=n, n_unfilled=0, fills=[{"price": price, "count": n}],
        avg_price=price, cost=str(cost), fee=str(fee), premium=str(cost + fee),
        payoff=None, headline=None,
    )
    data["decision"]["id"] = f"dec_{hedge_id}"
    if status == "declined":
        data["decision"]["status"] = "declined"
    elif status == "pending_approval":
        data["decision"]["status"] = "pending_approval"
    return Hedge.model_validate(data)


@pytest.fixture
def approve(engine, ledger_dir):
    def _approve(hedge: Hedge):
        return ledger.approve_hedge(hedge, "owner", at=APPROVED_AT, engine=engine, ledger_dir=ledger_dir)

    return _approve
