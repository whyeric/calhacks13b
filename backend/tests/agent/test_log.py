"""C4-A19 (append-only), C4-A20 (lifecycle events logged), C4-A34 (decimals lossless)."""

import asyncio
import json
from decimal import Decimal

import pytest
from sqlalchemy import text

from app import db
from app.agent import desk, log, policy
from app.models import LogEntry

from .conftest import WEEK


def entry(i: int, **kw):
    base = dict(business_id="taxi", kind="nudge", actor="system", agent=None, hedge_id=f"h_{i}",
                decision_id=None, run_id="run_t", status=None, checks=[], reasons=[],
                numbers={"premium": Decimal("66.47")}, summary=f"Entry costs ${Decimal('66.47')}.")
    return base | kw


def test_A19_append_only():
    ids = [log.append(entry(i)) for i in range(3)]
    assert not any(hasattr(log, name) for name in ("update", "delete", "remove", "edit"))
    eng = db.get_engine()
    for stmt in ("UPDATE log SET data = '{}'", "DELETE FROM log"):
        with pytest.raises(Exception, match="append-only"):
            with eng.begin() as conn:
                conn.execute(text(stmt))
    newest_first = [e.log_id for e in log.list("taxi") if e.run_id == "run_t"]
    assert newest_first == ids[::-1]
    assert [e.log_id for e in log.list("taxi") if e.run_id == "run_t"] == newest_first  # stable
    assert len(log.list("taxi", limit=2)) == 2


def test_A20_every_lifecycle_event_logged():
    run = asyncio.run(desk.run_week("taxi", WEEK, run_id="run_a20"))
    kinds = {e.kind for e in log.list("taxi") if e.run_id == "run_a20"}
    assert {"proposal"} <= kinds
    for e in log.list("taxi"):
        if e.run_id == "run_a20":
            assert e.checks, "proposal/decline entries carry checks"
    proposed = [h for h in run.hedges if h.status in ("proposed", "pending_approval")]
    policy.reject(proposed[0].id, "owner")
    if len(proposed) > 1:
        policy.approve(proposed[1].id, "owner", ledger_entry_ids=["led_stub_1"])
    # Booking and reconciliation are written by C5 (#4); stand-ins through the same append path.
    log.append(entry(9, kind="booking", actor="system", summary="Booked $66.47 premium."))
    log.append(entry(10, kind="reconciliation", actor="system", summary="Reconciled; one mismatch found."))
    kinds = {e.kind for e in log.list("taxi")}
    assert {"proposal", "rejection", "booking", "reconciliation"} <= kinds
    assert "approval" in kinds


def test_A20_decline_logged_with_checks(monkeypatch):
    from app.config import Thresholds

    monkeypatch.setattr(db, "get_business_thresholds", lambda *a, **k: Thresholds(overpay_max=Decimal("0.0")))
    asyncio.run(desk.run_week("taxi", WEEK, run_id="run_dec"))
    declines = [e for e in log.list("taxi") if e.run_id == "run_dec" and e.kind == "decline"]
    assert declines and all(e.checks and e.reasons for e in declines)


def test_A34_decimals_round_trip():
    log_id = log.append(entry(1, numbers={"premium": Decimal("1240.00"), "avg_price": Decimal("0.4260")},
                              summary="Premium $1,240.00 at $0.4260."))
    got = next(e for e in log.list("taxi") if e.log_id == log_id)
    assert got.numbers["premium"] == Decimal("1240.00") and isinstance(got.numbers["premium"], Decimal)
    raw = json.loads(got.model_dump_json())
    assert raw["numbers"] == {"premium": "1240.00", "avg_price": "0.4260"}
    assert LogEntry.model_validate_json(got.model_dump_json()) == got
