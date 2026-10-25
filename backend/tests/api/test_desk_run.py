"""C6-A6/A7/A10: background desk runs, contained failures, never self-approved."""

import time

from app import db
from app.agent import desk

NEXT_WEEK = "2026-11-02"


def poll(client, run_id, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        body = client.get(f"/runs/{run_id}").json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_desk_run_202_then_done(client, stub_analysis):
    t0 = time.monotonic()
    r = client.post("/businesses/taxi/desk/run", json={"week_of": NEXT_WEEK})
    assert r.status_code == 202 and time.monotonic() - t0 < 1.0
    assert r.json()["status"] == "queued"
    run = poll(client, r.json()["run_id"])
    assert run["status"] == "done" and run["agent"] == "fallback" and run["error"] is None
    hedges = client.get("/businesses/taxi/hedges", params={"week_of": NEXT_WEEK}).json()
    assert {h["exposure_id"] for h in hedges} == {e.id for e in stub_analysis.exposures}
    assert all(h["agent"] == "fallback" for h in hedges)
    logs = client.get("/businesses/taxi/decisions").json()
    assert {h["id"] for h in hedges} <= {e["hedge_id"] for e in logs if e["run_id"] == run["run_id"]}


def test_same_week_rerun_reuses_open_hedges(client, stub_analysis):
    for _ in range(2):
        run_id = client.post("/businesses/taxi/desk/run", json={"week_of": NEXT_WEEK}).json()["run_id"]
        assert poll(client, run_id)["status"] == "done"
    hedges = client.get("/businesses/taxi/hedges", params={"week_of": NEXT_WEEK}).json()
    open_ = [h for h in hedges if h["status"] in ("proposed", "pending_approval")]
    assert len({h["exposure_id"] for h in open_}) == len(open_)


def test_second_concurrent_run_409(client):
    from app.models import RunStatus

    db.put_run(RunStatus(run_id="run_busy", business_id="taxi", status="running", agent=None,
                         started_at=None, finished_at=None, error=None))
    r = client.post("/businesses/taxi/desk/run", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "run_in_progress"
    assert r.json()["error"]["detail"]["run_id"] == "run_busy"
    # another business is not blocked
    assert client.post("/businesses/restaurant/desk/run", json={}).status_code == 202


def test_failure_is_contained(client, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("markets exploded")

    monkeypatch.setattr(desk, "run_week", boom)
    n_before = len(db.list_log("taxi"))
    run_id = client.post("/businesses/taxi/desk/run", json={}).json()["run_id"]
    run = poll(client, run_id)
    assert run["status"] == "failed" and "markets exploded" in run["error"]
    assert client.get("/health").status_code == 200
    logs = db.list_log("taxi")
    assert len(logs) == n_before + 1 and logs[-1].kind == "run_failed" and logs[-1].run_id == run_id
    # the business can run again afterwards
    assert client.post("/businesses/taxi/desk/run", json={}).status_code == 202


def test_desk_never_self_approves(client, stub_analysis):
    """C6-A10: an over-budget hedge stays pending_approval and nothing is booked."""
    run_id = client.post("/businesses/taxi/desk/run", json={"week_of": NEXT_WEEK}).json()["run_id"]
    poll(client, run_id)
    hedges = client.get("/businesses/taxi/hedges", params={"week_of": NEXT_WEEK}).json()
    assert any(h["status"] == "pending_approval" for h in hedges)
    assert all(h["status"] != "approved" and h["ledger_entry_ids"] == [] for h in hedges)
    assert db.list_ledger_entries("taxi") == []
    assert all(e["actor"] != "owner" for e in client.get("/businesses/taxi/decisions").json()
               if e["run_id"] == run_id)


def test_real_analysis_desk_run_taxi(client):
    """End to end on the real taxi feature table (no stub): analyze, then run the desk."""
    a = client.post("/businesses/taxi/analyze", json={})
    assert a.status_code == 200
    run_id = client.post("/businesses/taxi/desk/run", json={"week_of": NEXT_WEEK}).json()["run_id"]
    assert poll(client, run_id, timeout=30)["status"] == "done"
    hedges = client.get("/businesses/taxi/hedges", params={"week_of": NEXT_WEEK}).json()
    assert {h["exposure_id"] for h in hedges} == {e["id"] for e in a.json()["exposures"]}
