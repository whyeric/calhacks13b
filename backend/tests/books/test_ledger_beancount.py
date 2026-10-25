"""C5-A1, A2: the generated Beancount file parses cleanly and every transaction balances."""

from decimal import Decimal

import pytest

from app.books import ledger

from .conftest import make_hedge

beancount = pytest.importorskip("beancount")


def test_ledger_passes_bean_check(approve, ledger_dir):  # C5-A1
    approve(make_hedge("hdg_01"))
    approve(make_hedge("hdg_02", ticker="KXRAINNYC-26OCT28", side="yes", n=7, price="0.33"))
    entries = ledger.load_ledger("taxi", ledger_dir)  # raises on any error
    text = ledger.ledger_path("taxi", ledger_dir).read_text()
    assert 'option "operating_currency" "USD"' in text
    for account in ledger.ACCOUNTS:
        assert f"open {account} USD" in text
    assert entries


def test_transactions_balance(approve, ledger_dir):  # C5-A2
    from beancount.core import data

    approve(make_hedge("hdg_01"))
    approve(make_hedge("hdg_02", ticker="KXRAINNYC-26OCT28", n=7, price="0.33"))
    txns = [e for e in ledger.load_ledger("taxi", ledger_dir) if isinstance(e, data.Transaction)]
    assert len(txns) == 3  # opening deposit + 2 premiums
    total = Decimal("0")
    for t in txns:
        s = sum(p.units.number for p in t.postings)
        assert s == 0
        total += s
    assert total == 0
    hedge_txns = [t for t in txns if "hedge_id" in t.meta]
    assert {t.meta["approved_by"] for t in hedge_txns} == {"owner"}
