"""C5-A5, A6, A7 (settlement half): simulated settlement from Kalshi `result` (R11)."""

from decimal import Decimal

import pytest

from app import db
from app.books import ledger
from app.books.settlement import book_settlement, simulate_settlement

from .conftest import make_hedge


def _market(result: str, ticker: str = "KXHIGHNY-26OCT28-T65"):
    return {"ticker": ticker, "result": result, "settlement_ts": "2026-10-29T11:00:00Z"}


def _cash(engine) -> Decimal:
    return sum(
        (p.amount for e in db.list_ledger_entries("taxi", engine) for p in e.postings if p.account == ledger.CASH),
        Decimal("0"),
    )


@pytest.mark.parametrize("side", ["yes", "no"])
@pytest.mark.parametrize("result", ["yes", "no"])
def test_payout_only_on_win(side, result, approve, engine, ledger_dir):  # C5-A5
    approved, _ = approve(make_hedge(side=side, n=40))
    entries = book_settlement(approved, _market(result), engine=engine, ledger_dir=ledger_dir)
    payouts = [e for e in db.list_ledger_entries("taxi", engine) if e.kind == "payout"]
    if side == result:
        assert len(entries) == 1 and payouts == entries
        postings = {p.account: p.amount for p in entries[0].postings}
        assert postings == {ledger.CASH: Decimal("40.00"), ledger.PAYOUTS: Decimal("-40.00")}
        assert entries[0].simulated and entries[0].narration.startswith("[SIMULATED]")
    else:
        assert entries == [] and payouts == []


def test_no_cash_entry_on_expiry(approve, engine, ledger_dir):  # C5-A6
    approved, _ = approve(make_hedge(side="yes"))
    before_cash, before_n = _cash(engine), len(db.list_ledger_entries("taxi", engine))
    assert book_settlement(approved, _market("no"), engine=engine, ledger_dir=ledger_dir) == []
    assert _cash(engine) == before_cash
    assert len(db.list_ledger_entries("taxi", engine)) == before_n
    kinds = [e.kind for e in db.list_log("taxi", engine=engine)]
    assert "expired" in kinds and "settlement" not in kinds
    text = ledger.ledger_path("taxi", ledger_dir).read_text()
    assert " note Assets:Kalshi:Cash " in text and "expired worthless" in text


def test_idempotent_settlement(approve, engine, ledger_dir):  # C5-A7 (settlement)
    approved, _ = approve(make_hedge(side="no"))
    first = book_settlement(approved, _market("no"), engine=engine, ledger_dir=ledger_dir)
    path = ledger.ledger_path("taxi", ledger_dir)
    before = path.read_bytes()
    second = book_settlement(approved, _market("no"), engine=engine, ledger_dir=ledger_dir)
    assert [e.id for e in first] == [e.id for e in second]
    assert path.read_bytes() == before
    assert len([e for e in db.list_ledger_entries("taxi", engine) if e.kind == "payout"]) == 1


def test_simulate_settlement_record(approve):
    approved, _ = approve(make_hedge(side="no", n=40))
    rec = simulate_settlement(approved, _market("no"))
    assert rec.won and rec.payout == Decimal("40.00") and rec.simulated is True
    with pytest.raises(ValueError):
        simulate_settlement(approved, {"ticker": approved.ticker, "result": ""})


def test_unapproved_cannot_settle(engine, ledger_dir):
    with pytest.raises(ledger.BookingError):
        book_settlement(make_hedge(), _market("no"), engine=engine, ledger_dir=ledger_dir)
