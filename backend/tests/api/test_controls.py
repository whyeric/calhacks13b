"""Segregation of duties, the controller's co-sign, decision receipts and period close."""

from datetime import date

from app import config, db
from app.books import ledger
from app.books.seed import seed_books
from app.books.settlement import book_withdrawal


def _cosign(client, hid="hdg_02", **body):
    return client.post(f"/hedges/{hid}/cosign", json={"actor": "controller", **body})


def test_material_hedge_waits_for_the_controller(client):
    h = client.get("/businesses/taxi/hedges").json()
    flags = {x["id"]: x["needs_controller"] for x in h}
    assert flags["hdg_02"] is True and flags["hdg_01"] is False  # $942.80 vs $66.47, materiality $200
    r = client.post("/hedges/hdg_02/approve", json={"actor": "owner"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "needs_controller"
    assert db.get_hedge("hdg_02").status == "pending_approval" and db.list_ledger_entries("taxi") == []
    assert db.list_log(hedge_id="hdg_02")[-1].kind == "refusal"  # the hold is on the record (I5)
    signed = _cosign(client, note="checked against the budget").json()
    assert signed["controller"]["decision"] == "signed" and signed["status"] == "pending_approval"
    assert db.list_log(hedge_id="hdg_02")[-1].actor == "controller"
    assert client.post("/hedges/hdg_02/approve", json={"actor": "owner"}).status_code == 200


def test_roles_cannot_do_each_others_part(client):
    for actor in ("owner", "desk", None, "Controller"):
        r = client.post("/hedges/hdg_02/cosign", json={"actor": actor})
        assert r.status_code == 403 and r.json()["error"]["code"] == "controller_only"
    assert _cosign(client).status_code == 200
    r = client.post("/hedges/hdg_02/approve", json={"actor": "controller"})  # co-signing isn't approving
    assert r.status_code == 403 and r.json()["error"]["code"] == "owner_only"


def test_controller_refusal_leaves_only_reject(client):
    assert _cosign(client, approve=False, note="not this week").json()["controller"]["decision"] == "refused"
    r = client.post("/hedges/hdg_02/approve", json={"actor": "owner"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "controller_refused"
    assert _cosign(client).json()["error"]["code"] == "already_cosigned"
    assert client.post("/hedges/hdg_02/reject", json={"actor": "owner"}).status_code == 200


def test_small_hedges_need_no_cosign(client):
    r = _cosign(client, "hdg_01")
    assert r.status_code == 409 and r.json()["error"]["code"] == "cosign_not_required"


def test_controller_token_when_configured(client, monkeypatch):
    monkeypatch.setenv("CONTROLLER_TOKEN", "c0ntr0l")
    config.get_settings.cache_clear()
    assert _cosign(client).status_code == 403
    r = client.post("/hedges/hdg_02/cosign", json={"actor": "controller"}, headers={"X-Controller-Token": "c0ntr0l"})
    assert r.status_code == 200


def test_only_the_controller_moves_materiality(client):
    s = client.get("/businesses/taxi/settings").json()
    s["thresholds"]["materiality_usd"] = "5000.00"
    r = client.put("/businesses/taxi/settings", json=s)  # the owner lifting the co-sign alone
    assert r.status_code == 403 and r.json()["error"]["code"] == "controller_only"
    assert client.put("/businesses/taxi/settings", json=s, headers={"X-Actor": "controller"}).status_code == 200
    assert client.get("/businesses/taxi/hedges").json()[0]["needs_controller"] is False
    s["weekly_budget"] = "300.00"  # other settings stay the owner's
    assert client.put("/businesses/taxi/settings", json=s).status_code == 200


def test_receipt_is_the_record(client, stub_analysis):
    _cosign(client)
    r = client.get("/hedges/hdg_02/receipt").json()
    assert r["hedge"]["id"] == "hdg_02" and r["approvals_required"] == ["owner", "controller"]
    assert r["exposure"]["id"] == r["hedge"]["exposure_id"]
    assert r["thresholds"]["materiality_usd"] == "200.00"
    assert [e["kind"] for e in r["trail"]][-1] == "cosign"
    assert any("order book" in s for s in r["sources"])
    assert client.get("/hedges/nope/receipt").status_code == 404


def test_close_needs_reconciled_books_and_locks_them(client, app_env):
    seed_books(ledger_dir=app_env / "ledgers", out_dir=app_env)
    body = {"actor": "controller", "through": "2026-10-23"}
    r = client.post("/businesses/taxi/close", json=body)  # the planted $0.89 short deposit is open
    assert r.status_code == 409 and r.json()["error"]["code"] == "unreconciled"
    assert client.post("/businesses/taxi/close", json={**body, "actor": "owner"}).status_code == 403
    r = client.post("/businesses/taxi/close", json={**body, "acknowledge_exceptions": True})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["closed_by"] == "controller" and len(c["exceptions"]) == 1 and "0.89" in c["exceptions"][0]
    assert sum(ledger.Decimal(row["balance"]) for row in c["trial_balance"]) == 0 and c["simulated"] is True
    assert client.get("/businesses/taxi/closes").json()["locked_through"] == "2026-10-23"
    assert db.list_log("taxi")[-1].kind == "period_close"
    again = client.post("/businesses/taxi/close", json={**body, "acknowledge_exceptions": True})
    assert again.json()["error"]["code"] == "already_closed"
    # A late item dated inside the closed period lands on the next open day and says so.
    e = book_withdrawal("taxi", ledger.cents(ledger.Decimal("1.00")), date(2026, 10, 22), ["hdg_late"],
                        ledger_dir=app_env / "ledgers")
    assert e.date == date(2026, 10, 24) and "belongs to 2026-10-22" in e.narration


def test_close_only_past_dates(client):
    r = client.post("/businesses/taxi/close", json={"actor": "controller", "through": "2026-10-24"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "period_not_ended"
