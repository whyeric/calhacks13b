"""C6-A8/A9 (owner only), A11 (allowed states, no duplicate booking), A12 (books and logs)."""

import pytest

from app import db
from app.books import ledger


@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.parametrize("body", [None, {"actor": "desk"}, {"actor": "agent"}, {"actor": "OWNER "}, {}])
def test_non_owner_403_and_unchanged(client, action, body):
    before = db.get_hedge("hdg_02")
    r = client.post(f"/hedges/hdg_02/{action}", json=body) if body is not None else client.post(f"/hedges/hdg_02/{action}")
    assert r.status_code == 403
    err = r.json()["error"]
    assert err["code"] == "owner_only" and "owner" in err["message"]
    assert db.get_hedge("hdg_02") == before
    assert db.list_ledger_entries("taxi") == []


def test_owner_approves_pending_and_proposed(client):
    for hid in ("hdg_02", "hdg_01"):  # D1: pending_approval and proposed both decidable
        r = client.post(f"/hedges/{hid}/approve", json={"actor": "owner", "note": "go"})
        assert r.status_code == 200, r.text
        h = r.json()
        assert h["status"] == "approved" and h["decided_by"] == "owner" and h["ledger_entry_ids"]


def test_owner_rejects(client):
    r = client.post("/hedges/hdg_02/reject", json={"actor": "owner", "reason": "too pricey"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert r.json()["ledger_entry_ids"] == []
    assert db.list_log(hedge_id="hdg_02")[-1].kind == "rejection"


def test_owner_token_when_configured(client, monkeypatch):
    from app import config

    monkeypatch.setenv("OWNER_TOKEN", "s3cret")
    config.get_settings.cache_clear()
    assert client.post("/hedges/hdg_02/approve", json={"actor": "owner"}).status_code == 403
    r = client.post("/hedges/hdg_02/approve", json={"actor": "owner"}, headers={"X-Owner-Token": "s3cret"})
    assert r.status_code == 200


@pytest.mark.parametrize("hid", ["hdg_03"])  # declined
def test_invalid_state_409(client, hid):
    r = client.post(f"/hedges/{hid}/approve", json={"actor": "owner"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_state"


def test_double_approve_and_approve_after_reject(client):
    assert client.post("/hedges/hdg_01/approve", json={"actor": "owner"}).status_code == 200
    entries = db.list_ledger_entries("taxi")
    again = client.post("/hedges/hdg_01/approve", json={"actor": "owner"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_state"
    assert db.list_ledger_entries("taxi") == entries
    assert client.post("/hedges/hdg_02/reject", json={"actor": "owner"}).status_code == 200
    assert client.post("/hedges/hdg_02/approve", json={"actor": "owner"}).status_code == 409


def test_approve_books_and_logs(client, app_env):
    h = client.post("/hedges/hdg_01/approve", json={"actor": "owner"}).json()
    text = (app_env / "ledgers" / "taxi.beancount").read_text()
    assert "hdg_01" in text and "Expenses:Hedging:Premiums" in text and "Expenses:Hedging:Fees" in text
    led = client.get("/businesses/taxi/ledger").json()
    assert led["simulated"] is True
    ids = [e["id"] for e in led["entries"]]
    assert h["ledger_entry_ids"] and set(h["ledger_entry_ids"]) <= set(ids)
    entry = next(e for e in led["entries"] if e["id"] == h["ledger_entry_ids"][0])
    amounts = {p["account"]: p["amount"] for p in entry["postings"]}
    assert amounts["Assets:Kalshi:Cash"] == "-" + h["premium"]
    kinds = [(e["kind"], e["actor"]) for e in client.get("/businesses/taxi/decisions").json() if e["hedge_id"] == "hdg_01"]
    assert ("approval", "owner") in kinds and ("booking", "system") in kinds


def test_ledger_failure_leaves_hedge_unchanged(client, monkeypatch):
    def broken(hedge, actor):
        raise OSError("disk full")

    monkeypatch.setattr(ledger, "book_approval", broken)
    before = db.get_hedge("hdg_01")
    r = client.post("/hedges/hdg_01/approve", json={"actor": "owner"})
    assert r.status_code == 500 and r.json()["error"]["code"] == "ledger_write_failed"
    assert db.get_hedge("hdg_01") == before


def test_unknown_hedge_404(client):
    r = client.post("/hedges/nope/approve", json={"actor": "owner"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "hedge_not_found"
