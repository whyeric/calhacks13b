"""C8-A8 reconcile_one_mismatch: settlements simulated from real settled Kalshi results
(`backend/fixtures/books/settled_markets.json`) against `backend/fixtures/bank_statement.csv`,
which carries one planted short deposit (answer key in `app/books/seed.py`)."""

import re

from conftest import FIXTURES

PLANTED = {"hedge_id": "hdg_s01", "difference": "-0.89", "likely_cause": "fee_deducted_from_deposit"}


def test_a8_bank_statement_is_fixed_not_random(app_env):
    """`make seed` regenerates the statements byte-for-byte (the plant is in the file)."""
    for name in ("bank_statement.csv", "bank_statement_clean.csv", "bank_statement_restaurant.csv"):
        assert (app_env / "statements" / name).read_bytes() == (FIXTURES / name).read_bytes(), name


def test_a8_reconcile_one_mismatch(client):
    r = client.post("/businesses/taxi/reconcile", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["simulated"] is True
    assert len(body["mismatches"]) == 1, body["mismatches"]
    m = body["mismatches"][0]
    assert {k: m[k] for k in PLANTED} == PLANTED
    amount = PLANTED["difference"].lstrip("-")
    assert f"${amount}" in m["explanation"], m["explanation"]
    assert m["action"] == "ask_owner" and m["question"]
    assert body["matches"] and body["summary"] == {"n_matched": len(body["matches"]), "n_mismatched": 1,
                                                   "total_difference": PLANTED["difference"],
                                                   "n_in_transit": 0}
    for row in body["matches"]:
        assert row["expected"] == row["kalshi_ledger"] == row["bank"], row

    log = client.get("/businesses/taxi/decisions").json()
    recon = next(e for e in log if e["kind"] == "reconciliation")  # newest first
    assert recon["created_at"] and (amount in recon["summary"] or
                                    amount in str(recon["numbers"])), recon
    # the ledger view serves the same stored result
    assert client.get("/businesses/taxi/ledger").json()["reconciliation"] == body


def test_a8_restaurant_reconciles_clean(client):
    body = client.post("/businesses/restaurant/reconcile", json={}).json()
    assert body["mismatches"] == [] and body["summary"]["n_mismatched"] == 0


def test_a8_seeded_log_agrees_with_answer_key(client):
    """The seeded log (approval, booking, reconciliation) tells the same story as the ledger tab:
    hdg_s01, $0.89 short (it used to say $1.05 short on hdg_s02)."""
    log = client.get("/businesses/taxi/decisions", params={"limit": 500}).json()
    recon = [e for e in log if e["kind"] == "reconciliation"]
    assert recon
    for e in recon:
        amounts = set(re.findall(r"\$(\d+\.\d\d)", e["summary"]))
        assert amounts <= {"0.89"}, e["summary"]
        assert e["hedge_id"] in (None, PLANTED["hedge_id"]) and "hdg_s02" not in e["summary"], e
    ledger = client.get("/businesses/taxi/ledger").json()["entries"]
    by_hedge = {(x.get("meta") or {}).get("hedge_id"): x for x in ledger if x["kind"] == "premium"}
    for e in (e for e in log if e["kind"] in ("approval", "booking") and e["hedge_id"] in by_hedge):
        booked = by_hedge[e["hedge_id"]]
        cash = next(p["amount"] for p in booked["postings"] if p["account"] == "Assets:Kalshi:Cash")
        assert f"${cash.lstrip('-')}" in e["summary"], (e["summary"], booked)
