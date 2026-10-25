"""C6-A15/A16: decisions newest first, paginated, and the log is append-only."""

import random
from datetime import datetime, timedelta, timezone

from app import db
from app.models import LogEntry


def _entry(i: int) -> LogEntry:
    return LogEntry(
        log_id=f"log_t{i}", business_id="taxi", kind="nudge",
        created_at=datetime(2026, 10, 25, tzinfo=timezone.utc) + timedelta(minutes=i),
        actor="system", agent=None, hedge_id=None, decision_id=None, run_id=None, status=None,
        checks=[], reasons=[], numbers={}, summary="Reminder.",
    )


def test_newest_first_and_paginates(client):
    order = list(range(5))
    random.Random(7).shuffle(order)
    for i in order:
        db.append_log(_entry(i))
    full = client.get("/businesses/taxi/decisions", params={"limit": 500}).json()
    stamps = [e["created_at"] for e in full]
    assert stamps == sorted(stamps, reverse=True) and len(set(stamps)) == len(stamps)

    pages, before = [], None
    while True:
        params = {"limit": 3} | ({"before": before} if before else {})
        page = client.get("/businesses/taxi/decisions", params=params).json()
        if not page:
            break
        pages += page
        before = page[-1]["log_id"]
    assert [e["log_id"] for e in pages] == [e["log_id"] for e in full]


def test_bad_cursor_422(client):
    r = client.get("/businesses/taxi/decisions", params={"before": "log_missing"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_cursor"


def test_log_append_only_across_state_changes(client):
    def snapshot():
        return {e.log_id: e.model_dump_json() for e in db.list_log()}

    before = snapshot()
    steps = [
        lambda: client.post("/hedges/hdg_01/approve", json={"actor": "owner"}),
        lambda: client.post("/hedges/hdg_02/reject", json={"actor": "owner"}),
        lambda: client.post("/hedges/hdg_04/approve", json={"actor": "desk"}),
        lambda: client.post("/businesses/taxi/chat", json={"message": "why?"}),
        lambda: client.post("/businesses/taxi/desk/run", json={"week_of": "2026-11-02"}),
    ]
    for step in steps:
        step()
        now = snapshot()
        assert len(now) >= len(before)
        assert all(now[k] == v for k, v in before.items())  # nothing updated or deleted
        before = now
