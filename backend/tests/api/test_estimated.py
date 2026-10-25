"""I6: the business-level `estimated` flag reaches /analyze and hedges (e2e gap: only /businesses
and the backtest carried it)."""

import time
from datetime import date

from app import db
from tests.api.conftest import FIXTURE_WEEK


def _estimated(client):
    return {b["id"]: b["estimated"] for b in client.get("/businesses").json()}


def test_analyze_carries_the_business_estimated_flag(client, stub_analysis):
    est = _estimated(client)
    assert est == {"taxi": False, "restaurant": True}
    for b in ("taxi", "restaurant"):
        body = client.post(f"/businesses/{b}/analyze", json={}).json()
        assert body["estimated"] is est[b], b


def test_real_taxi_analyze_is_not_estimated(client):
    assert client.post("/businesses/taxi/analyze", json={}).json()["estimated"] is False


def test_hedges_carry_the_business_estimated_flag(client):
    est = _estimated(client)
    for b in ("taxi", "restaurant"):
        hedges = client.get(f"/businesses/{b}/hedges", params={"week_of": FIXTURE_WEEK}).json()
        assert hedges, b
        assert all(h["estimated"] is est[b] for h in hedges), [(h["id"], h["estimated"]) for h in hedges]


def test_desk_run_stores_estimated_on_hedges_of_an_estimated_business(client):
    """The desk stamps `estimated` on what it stores (taxi relabeled estimated, since the restaurant
    needs the gitignored Dewey data to run)."""
    taxi = db.get_business("taxi")
    db.put_business(taxi.model_copy(update={"estimated": True, "data_label": "estimated"}))
    run_id = client.post("/businesses/taxi/desk/run", json={}).json()["run_id"]
    for _ in range(400):
        if client.get(f"/runs/{run_id}").json()["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert client.get(f"/runs/{run_id}").json()["status"] == "done"
    stored = db.list_hedges("taxi", date.fromisoformat(FIXTURE_WEEK))
    real = [h for h in stored if not h.id.startswith("hdg_0")]  # sample ids are hdg_01..04
    assert real and all(h.estimated for h in real), [(h.id, h.estimated) for h in stored]
