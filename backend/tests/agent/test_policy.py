"""C4-A21 (self-approval refused), C4-A22 (over budget goes pending), C4-A23 (budget accounting, D4),
C4-A24 (nudge once at T-3h) and C4-A25 (expire unapproved at T) with a fake clock (#46 part B)."""

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import db
from app.agent import desk, log, policy
from app.agent.tools import TOOL_NAMES
from app.models import Hedge

from .conftest import RAIN_HID, WEEK, example


@pytest.mark.parametrize("actor", ["desk", "claude", "agent", None, "OWNER ", "Owner", "system"])
def test_A21_only_exact_owner(actor):
    for action in ("approve", "reject", "book"):
        assert policy.can_act(actor, action) is False
        assert policy.can_act("owner", action) is True


def test_A21_refusal_raises_logged_and_no_approve_tool():
    asyncio.run(desk.run_week("taxi", WEEK, run_id="run_a21"))
    before = db.get_hedge(RAIN_HID)
    with pytest.raises(policy.PolicyError):
        policy.approve(RAIN_HID, "desk", ledger_entry_ids=["led_x"])
    with pytest.raises(policy.PolicyError):
        policy.reject(RAIN_HID, "claude")
    after = db.get_hedge(RAIN_HID)
    assert after == before and after.ledger_entry_ids == []
    assert db.list_ledger_entries("taxi") == []
    refusals = [e for e in log.list("taxi") if e.kind == "refusal" and e.hedge_id == RAIN_HID]
    assert len(refusals) == 2
    assert not any(n in TOOL_NAMES for n in ("approve", "approve_hedge", "book_hedge", "reject_hedge"))


def test_A22_over_budget_pending_full_size_with_alternative():
    assert policy.classify(Decimal("300"), Decimal("250")) == "over_budget"
    assert policy.classify(Decimal("250"), Decimal("250")) == "within"
    run = asyncio.run(desk.run_week("taxi", WEEK, run_id="run_a22"))
    rain = next(h for h in run.hedges if h.id == RAIN_HID)
    example_pending = Hedge.model_validate(example("hedge_pending.json"))
    assert rain.status == "pending_approval" and rain.decision.reasons == ["over_budget"]
    assert rain.premium > Decimal("250") and rain.n_filled == example_pending.n_filled  # size not reduced
    alt = rain.alternative
    assert alt is not None and alt.premium <= Decimal("250.00") and alt.n_filled < rain.n_filled
    assert rain.ledger_entry_ids == [] and db.list_ledger_entries("taxi") == []  # nothing booked


def _put(hedge_file: str, hid: str, status: str, week: date):
    h = example(hedge_file) | {"id": hid, "business_id": "taxi", "week_of": week.isoformat(), "status": status, "alternative": None}
    if status == "approved":
        h |= {"ledger_entry_ids": ["led_1"], "decided_by": "owner", "decided_at": "2026-11-02T15:00:00Z"}
    if status in ("approved", "proposed"):
        h["decision"] = h["decision"] | {"status": "proposed", "reasons": [], "checks": [
            c | {"passed": True} if c["code"] == "over_budget" else c for c in h["decision"]["checks"]]}
    db.put_hedge(Hedge.model_validate(h))


def test_A23_budget_accounting_D4():
    week = date(2026, 11, 9)
    _put("hedge_proposed.json", "h_approved", "approved", week)  # premium 219.75
    b = policy.check_budget("taxi", week)
    assert (b.budget, b.spent, b.pending, b.remaining) == (
        Decimal("250.00"), Decimal("219.75"), Decimal("0.00"), Decimal("30.25"))
    new_premium = Hedge.model_validate(example("hedge_partial.json")).premium  # 66.47
    assert policy.classify(new_premium, b.remaining) == "over_budget"  # -> pending_approval
    _put("hedge_partial.json", "h_pending", "proposed", week)
    b = policy.check_budget("taxi", week)
    assert b.pending == Decimal("66.47") and b.remaining == Decimal("-36.22")  # D4: pending counts
    nxt = policy.check_budget("taxi", date(2026, 11, 18))  # a Wednesday of the next week
    assert nxt.week_start == date(2026, 11, 16) and nxt.remaining == Decimal("250.00")  # new Monday resets


def test_reject_from_proposed_D1():
    asyncio.run(desk.run_week("taxi", WEEK, run_id="run_d1"))
    h = policy.reject(RAIN_HID, "owner", reason="Not this week.")
    assert h.status == "rejected" and h.decided_by == "owner"
    with pytest.raises(policy.PolicyError):
        policy.reject(RAIN_HID, "owner")  # already decided


# --- C4-A24 / C4-A25: approval timing sweep -------------------------------------------------

HID = "hdg_02"  # seeded taxi hedge, pending_approval
T = datetime(2026, 10, 29, 4, 59, tzinfo=timezone.utc)  # its market's close_time


def kinds(hid=HID):
    return [e.kind for e in log.list("taxi", hedge_id=hid)]


def test_A24_nudge_once_at_T_minus_3h(fake_clock):
    assert db.get_hedge(HID).close_time == T and db.get_hedge(HID).status == "pending_approval"
    fake_clock.set(T - timedelta(hours=3, minutes=1))
    policy.sweep()
    assert "nudge" not in kinds()
    fake_clock.set(T - timedelta(hours=3))
    new = policy.sweep()
    nudges = [e for e in log.list("taxi", hedge_id=HID) if e.kind == "nudge"]
    assert len(nudges) == 1 and nudges[0].log_id in new
    n = nudges[0]
    assert n.actor == "system" and n.status == "pending_approval"
    assert log.validate_summary(n.summary, n.numbers) == []  # I2 holds on the nudge text
    assert "waiting on you" in n.summary and "$942.80" in n.summary
    for minutes in (0, 30, 179):  # later sweeps before close: no duplicate
        fake_clock.set(T - timedelta(hours=3) + timedelta(minutes=minutes))
        policy.sweep()
    assert kinds().count("nudge") == 1
    assert db.get_hedge(HID).status == "pending_approval"  # a nudge changes nothing else


def test_A25_expire_unapproved_at_close_then_not_bookable(fake_clock):
    fake_clock.set(T - timedelta(hours=2))
    policy.sweep()
    fake_clock.set(T - timedelta(minutes=1))
    policy.sweep()
    assert "expired_unapproved" not in kinds()
    fake_clock.set(T)
    policy.sweep()
    assert kinds().count("expired_unapproved") == 1 and kinds().count("nudge") == 1
    h = db.get_hedge(HID)
    assert h.status == "expired_unapproved" and h.ledger_entry_ids == [] and h.alternative is None
    exp = next(e for e in log.list("taxi", hedge_id=HID) if e.kind == "expired_unapproved")
    assert log.validate_summary(exp.summary, exp.numbers) == []
    fake_clock.set(T + timedelta(hours=5))
    policy.sweep()
    assert kinds().count("expired_unapproved") == 1  # idempotent

    with pytest.raises(policy.PolicyError) as e:  # policy gate: terminal state
        policy.approve(HID, "owner", ledger_entry_ids=["led_x"])
    assert e.value.code == "conflict"

    from app.main import app

    with TestClient(app) as c:  # API: approve after expiry is a 409, nothing booked
        r = c.post(f"/hedges/{HID}/approve", json={"actor": "owner"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_state"
    assert db.list_ledger_entries("taxi") == [] and "approval" not in kinds()
    assert db.get_hedge(HID).status == "expired_unapproved"


def test_expire_sweep_skips_terminal_hedges(fake_clock):
    fake_clock.set(T + timedelta(days=1))
    policy.sweep()
    assert db.get_hedge("hdg_03").status == "declined"  # declined is terminal, never "expired"
    assert "expired_unapproved" not in kinds("hdg_03")


def test_desk_run_sweeps_first_expire(fake_clock):
    """Every desk run calls the sweep: the seeded week's open hedges closed Oct 29."""
    asyncio.run(desk.run_week("taxi", WEEK, run_id="run_sweep"))
    assert db.get_hedge(HID).status == "expired_unapproved"
    assert db.get_hedge("hdg_04").status == "proposed"  # another business, untouched by a taxi run


def test_background_loop_runs_sweep_nudge(fake_clock):
    from app import main

    fake_clock.set(T - timedelta(hours=1))

    async def run_briefly():
        task = asyncio.create_task(main._sweep_loop(0.01))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if "nudge" in kinds():
                break
        task.cancel()

    asyncio.run(run_briefly())
    assert kinds().count("nudge") == 1
