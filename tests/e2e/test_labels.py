"""C8-A15 labels_present_in_api (I6): the restaurant is `estimated`, the books are `simulated`."""

from conftest import HAS_RESTAURANT_DATA


def test_a15_businesses_labels(client):
    bs = {b["id"]: b for b in client.get("/businesses").json()}
    assert bs["restaurant"]["estimated"] is True and bs["restaurant"]["data_label"] == "estimated"
    assert bs["restaurant"]["avg_check_label"] == "assumed"
    assert bs["taxi"]["estimated"] is False and bs["taxi"]["data_label"] == "real"


def test_a15_ledger_and_reconcile_simulated(client):
    for b in ("taxi", "restaurant"):
        led = client.get(f"/businesses/{b}/ledger").json()
        assert led["simulated"] is True
        assert led["entries"] and all(e["simulated"] for e in led["entries"] if e["kind"] != "opening_deposit")
        rec = client.post(f"/businesses/{b}/reconcile", json={}).json()
        assert rec["simulated"] is True
        assert client.get(f"/businesses/{b}/ledger").json()["reconciliation"]["simulated"] is True


def test_a15_analyze_and_sample_week_labels(client):
    """/analyze has no per-response `estimated` flag (the contract labels the business, and the
    UI reads it from /businesses); the sample week is flagged on /health."""
    r = client.post("/businesses/restaurant/analyze", json={})
    assert r.status_code == (200 if HAS_RESTAURANT_DATA else 409)
    h = client.get("/health").json()
    assert h["sample_week"] is True and set(h["sample_businesses"]) == {"restaurant", "taxi"}
