"""C6-A13/A14 and lazy expiry (G10)."""

from datetime import date, datetime, timedelta, timezone

from app import clock, db
from app.models import Hedge
from tests.api.conftest import FIXTURE_WEEK


def test_declined_included_with_reasons(client):
    hedges = client.get("/businesses/taxi/hedges", params={"week_of": FIXTURE_WEEK}).json()
    statuses = {h["status"] for h in hedges}
    assert {"proposed", "pending_approval"} <= statuses
    restaurant = client.get("/businesses/restaurant/hedges", params={"week_of": FIXTURE_WEEK}).json()
    declined = [h for h in restaurant if h["status"] == "declined"]
    assert declined and all(h["decision"]["reasons"] and h["decision"]["checks"] for h in declined)
    failed = [c for c in declined[0]["decision"]["checks"] if c["passed"] is False]
    assert failed and all(c["metric"] for c in failed) and declined[0]["decision"]["summary"]


def _other_week_hedge() -> Hedge:
    h = db.get_hedge("hdg_01")
    return Hedge.model_validate(h.model_dump() | {"id": "hdg_next", "week_of": date(2026, 11, 2)})


def test_week_of_filter_snap_default_and_garbage(client):
    db.put_hedge(_other_week_hedge())
    monday = client.get("/businesses/taxi/hedges", params={"week_of": "2026-11-02"}).json()
    assert [h["id"] for h in monday] == ["hdg_next"]
    wednesday = client.get("/businesses/taxi/hedges", params={"week_of": "2026-11-04"}).json()
    assert [h["id"] for h in wednesday] == ["hdg_next"]
    default = client.get("/businesses/taxi/hedges").json()
    assert default and all(h["week_of"] == FIXTURE_WEEK for h in default)
    bad = client.get("/businesses/taxi/hedges", params={"week_of": "next tuesday"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "bad_week_of"


def test_unknown_business_404(client):
    r = client.get("/businesses/nope/hedges")
    assert r.status_code == 404 and r.json()["error"]["code"] == "business_not_found"


def test_lazy_expiry(client, monkeypatch):
    later = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)  # after the Oct 29 closes
    monkeypatch.setattr(clock, "now", lambda: later)
    hedges = client.get("/businesses/taxi/hedges", params={"week_of": FIXTURE_WEEK}).json()
    assert all(h["status"] not in ("proposed", "pending_approval") for h in hedges)
    assert any(h["status"] == "expired_unapproved" for h in hedges)
    kinds = [e.kind for e in db.list_log("taxi")]
    assert "expired_unapproved" in kinds
    assert timedelta(0) < later - datetime(2026, 10, 29, tzinfo=timezone.utc)
