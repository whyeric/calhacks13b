"""C5 wiring: approve logs approval before booking; reconcile and /ledger carry ReconResult."""

from app import db
from app.books.seed import seed_books


def test_approval_then_booking_in_log(client):
    client.post("/hedges/hdg_01/approve", json={"actor": "owner"})
    kinds = [e["kind"] for e in client.get("/businesses/taxi/decisions").json() if e["hedge_id"] == "hdg_01"]
    assert kinds.count("booking") == 1 and kinds.count("approval") == 1
    assert kinds.index("booking") < kinds.index("approval")  # feed is newest first: approval, then booking


def test_non_owner_403(client):
    r = client.post("/hedges/hdg_01/approve", json={"actor": "desk"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "owner_only"
    assert db.list_ledger_entries("taxi") == []


def test_reconcile_409_until_settled(client):
    r = client.post("/businesses/taxi/reconcile", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "nothing_to_reconcile"
    assert client.get("/businesses/taxi/ledger").json()["reconciliation"] is None


def _n_recon(client) -> int:
    return [e["kind"] for e in client.get("/businesses/taxi/decisions").json()].count("reconciliation")


def test_reconcile_catches_plant(client, app_env):
    before = _n_recon(client)  # the fixture log already holds one
    seed_books(ledger_dir=app_env / "ledgers", out_dir=app_env)  # writes CSVs to tmp, not fixtures/
    led = client.get("/businesses/taxi/ledger").json()
    assert led["simulated"] is True and led["reconciliation"]["summary"]["n_mismatched"] == 1
    r = client.post("/businesses/taxi/reconcile", json={})
    assert r.status_code == 200
    m = r.json()["mismatches"]
    assert len(m) == 1 and m[0]["hedge_id"] == "hdg_s01" and m[0]["difference"] == "-0.89"
    assert client.get("/businesses/taxi/ledger").json()["reconciliation"] == r.json()
    assert client.post("/businesses/restaurant/reconcile", json={}).json()["mismatches"] == []
    client.post("/businesses/taxi/reconcile", json={})  # same result: no duplicate log row
    assert _n_recon(client) == before + 1


def test_reconciliation_benchmark_route(client):
    r = client.get("/benchmarks/reconciliation")
    assert r.status_code == 200
    body = r.json()
    assert body["simulated"] is True
    assert body["n_caught"] == body["n_planted"] == 13 and body["false_flags"] == []
    assert db.list_ledger_entries("bench") == []  # the benchmark never touches the app's books
