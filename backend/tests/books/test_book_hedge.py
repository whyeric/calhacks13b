"""C5-A3, A4, A7 (booking half), A8, A9, A16, A17 (booking half): booking on approval."""

from decimal import Decimal

import pytest

from app import db
from app.books import ledger
from app.books.ledger import BookingError, book_approval, book_hedge
from app.models import ApproveRequest

from .conftest import APPROVED_AT, make_hedge


def _postings(entry):
    return {p.account: p.amount for p in entry.postings}


def test_premium_fee_match_hedge(approve, engine):  # C5-A3
    hedge = make_hedge(n=40, price="0.56")
    approved, entries = approve(hedge)
    assert len(entries) == 1
    p = _postings(entries[0])
    assert p[ledger.PREMIUMS] == Decimal("22.40")
    assert p[ledger.PREMIUMS] + p[ledger.FEES] == approved.premium
    assert p[ledger.CASH] == -approved.premium
    assert p[ledger.FEES] == ledger.taker_fee(40, Decimal("0.56")) == Decimal("0.69")
    assert sum(p.values()) == 0
    assert approved.status == "approved" and approved.ledger_entry_ids == [entries[0].id]
    assert db.get_hedge(hedge.id, engine) == approved
    assert entries[0].date.isoformat() == "2026-10-26"  # approval day, New York


def test_metadata_complete(approve):  # C5-A4
    _, entries = approve(make_hedge())
    meta = entries[0].meta
    assert meta is not None
    for key in ("hedge_id", "ticker", "decision_id", "approved_by"):
        assert getattr(meta, key)
    assert meta.approved_by == "owner"
    assert meta.hedge_id == "hdg_01" and meta.decision_id == "dec_hdg_01"


def test_idempotent_rebooking(approve, engine, ledger_dir):  # C5-A7 (booking)
    approved, first = approve(make_hedge())
    path = ledger.ledger_path("taxi", ledger_dir)
    before = path.read_bytes()
    again = book_approval(approved, engine=engine, ledger_dir=ledger_dir)
    _, third = approve(approved)
    assert [e.id for e in again] == [e.id for e in third] == [e.id for e in first]
    assert path.read_bytes() == before
    premium_rows = [e for e in db.list_ledger_entries("taxi", engine) if e.kind == "premium"]
    assert len(premium_rows) == 1
    assert before.decode().count('hedge_id: "hdg_01"') == 1


@pytest.mark.parametrize("status", ["declined", "pending_approval", "rejected", "expired_unapproved", "proposed"])
def test_rejected_never_booked(status, engine, ledger_dir):  # C5-A8
    hedge = make_hedge().model_copy(update={"status": status, "decided_by": "owner", "decided_at": APPROVED_AT})
    with pytest.raises(BookingError):
        book_approval(hedge, engine=engine, ledger_dir=ledger_dir)
    assert db.list_ledger_entries("taxi", engine) == []
    assert not any(e.kind == "booking" for e in db.list_log("taxi", engine=engine))
    assert not ledger.ledger_path("taxi", ledger_dir).exists()


def test_cannot_approve_declined(engine, ledger_dir):  # C5-A8 via approve_hedge
    hedge = make_hedge().model_copy(update={"status": "declined"})
    with pytest.raises(BookingError):
        ledger.approve_hedge(hedge, "owner", engine=engine, ledger_dir=ledger_dir)
    assert db.list_ledger_entries("taxi", engine) == []


def test_non_owner_cannot_book(engine, ledger_dir):  # C5-A9
    hedge = make_hedge()
    with pytest.raises(BookingError):
        ledger.approve_hedge(hedge, "desk", engine=engine, ledger_dir=ledger_dir)
    approved_by_desk = hedge.model_copy(update={"status": "approved", "decided_by": None})
    with pytest.raises(BookingError):
        book_approval(approved_by_desk, engine=engine, ledger_dir=ledger_dir)
    with pytest.raises(BookingError):
        book_hedge(approved_by_desk, ApproveRequest(actor="desk"), engine=engine, ledger_dir=ledger_dir)
    assert db.list_ledger_entries("taxi", engine) == []


def test_book_hedge_signature(approve, engine, ledger_dir):
    approved, entries = approve(make_hedge())
    assert book_hedge(approved, ApproveRequest(actor="owner"), engine=engine, ledger_dir=ledger_dir) == [
        entries[0].id
    ]


def test_decimal_precision():  # C5-A16
    # 0.07 * 7 * 0.33 * 0.67 = 0.1083390 -> rounds UP to 0.11
    fee = ledger.taker_fee(7, Decimal("0.33"))
    assert fee == Decimal("0.11") and isinstance(fee, Decimal)
    assert fee.as_tuple().exponent == -2
    assert ledger.taker_fee(100, Decimal("0.50")) == Decimal("1.75")  # exact, no round-up
    with pytest.raises(TypeError):
        ledger.taker_fee(7, 0.33)
    with pytest.raises(TypeError):
        ledger.cents(1.5)


def test_fractional_cent_fee_books_exactly(approve):  # C5-A16
    _, entries = approve(make_hedge(n=7, price="0.33"))
    p = _postings(entries[0])
    assert p[ledger.FEES] == Decimal("0.11")
    assert all(isinstance(v, Decimal) and v.as_tuple().exponent == -2 for v in p.values())


def test_booking_logged(approve, engine):  # C5-A17 (booking half)
    approve(make_hedge())
    logs = [e for e in db.list_log("taxi", engine=engine) if e.kind == "booking"]
    assert len(logs) == 1
    assert logs[0].hedge_id == "hdg_01" and logs[0].actor == "system"
    assert logs[0].numbers["premium"] == Decimal("23.09")


def test_opening_deposit_once(approve, engine):
    approve(make_hedge("hdg_01"))
    approve(make_hedge("hdg_02", ticker="KXRAINNYC-26OCT28"))
    opening = [e for e in db.list_ledger_entries("taxi", engine) if e.kind == "opening_deposit"]
    assert len(opening) == 1 and opening[0].simulated
    assert opening[0].narration.startswith("[SIMULATED]")
