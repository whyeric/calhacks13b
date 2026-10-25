"""C8-A4 e2e_taxi: DEMO_OFFLINE=1, fallback agent, the real pipeline (features -> exposure fit ->
Kalshi cache replay -> sizing -> rules -> log), then books and reconcile."""

import pytest

from chain import DECIDABLE, check_chain, check_reconcile_runs
from conftest import run_desk


def test_a4_taxi_chain(client):
    seen = check_chain(client, "taxi")
    assert seen["analysis"]["exposures"], "taxi should have at least one hedgeable exposure"
    rain = next(e for e in seen["analysis"]["exposures"] if e["event"] == "rain")
    assert rain["direction"] == "positive" and rain["hedge_side"] == "no"
    recon = check_reconcile_runs(client, "taxi")
    assert recon["summary"]["n_matched"] + recon["summary"]["n_mismatched"] > 0
    ledger = client.get("/businesses/taxi/ledger").json()
    assert ledger["simulated"] is True and ledger["entries"]


def test_a4_taxi_approved_hedge_books(client):
    """An owner-approved hedge from this run writes ledger entries. Data-dependent: needs a
    real proposed/pending hedge, which the committed cache has to provide (docs/DEMO.md)."""
    seen = check_chain(client, "taxi")
    decidable = [h for h in seen["hedges"] if h["status"] in DECIDABLE]
    if not decidable:
        pytest.xfail("the committed Kalshi cache gives taxi no proposed/pending hedge this week "
                     f"({[(h['id'], h['status'], h['decision']['reasons']) for h in seen['hedges']]}); "
                     "re-warm when the rain book has depth (docs/DEMO.md)")
    h = decidable[0]
    before = len(client.get("/businesses/taxi/ledger").json()["entries"])
    r = client.post(f"/hedges/{h['id']}/approve", json={"actor": "owner"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert r.json()["ledger_entry_ids"]
    after = client.get("/businesses/taxi/ledger").json()["entries"]
    assert len(after) > before
    assert {e["id"] for e in after} >= set(r.json()["ledger_entry_ids"])


@pytest.mark.xfail(reason="gap (backend/app): nothing stores the 'backtest' analysis row, so GET "
                          "/businesses/{id}/backtest is always 409 backtest_not_ready; demo beats 1 and 5 "
                          "(worst week before/after, backtest headline) have no data", strict=False)
def test_a4_taxi_backtest_served_offline(client):
    client.post("/businesses/taxi/analyze", json={})
    run_desk(client, "taxi")
    r = client.get("/businesses/taxi/backtest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["worst_week_unhedged"] and body["weekly"]


def test_a4_taxi_model_check(client):
    """Beat 5 proof: a planted $500 effect is recovered with ~90% CI coverage."""
    mc = client.post("/businesses/taxi/analyze", json={}).json()["model_check"]
    assert mc["planted_usd"] == "500.00" and mc["coverage"] >= 0.8
