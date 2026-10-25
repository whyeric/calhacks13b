"""GET /integrations/increase/status: which bank the reconciler reads (no network call)."""

from app.books.seed import seed_books
from app.models import IncreaseStatus


def test_increase_status_offline_is_demo(client):
    r = client.get("/integrations/increase/status")
    assert r.status_code == 200
    body = IncreaseStatus.model_validate(r.json())
    assert (body.mode, body.bank_origin, body.simulated, body.accounts) == ("demo", "csv_simulated", True, {})


def test_reconcile_route_reports_sources_and_record(client, app_env):
    seed_books(ledger_dir=app_env / "ledgers", out_dir=app_env)
    body = client.post("/businesses/taxi/reconcile", json={}).json()
    assert body["simulated"] is True
    assert body["sources"] == {
        "venue_origin": "simulated", "ledger_origin": "beancount_simulated", "bank_origin": "csv_simulated",
        "live": False, "notes": body["sources"]["notes"],
    }
    [m] = body["mismatches"]
    assert m["system_of_record"] == "bank" and m["venue"] == "60.00" and m["bank_origin"] == "csv_simulated"
    assert m["record_reason"].startswith("The bank is the record for cash")
