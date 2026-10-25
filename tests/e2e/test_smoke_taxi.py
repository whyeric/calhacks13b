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


def test_a4_taxi_rain_declined_this_week(client):
    """The demo week's truth on the committed cache: the only NYC rain markets are for Sat/Sun Oct
    24-25, outside the desk week of Mon Oct 26, so rain is `no_market`; and the recent-window refit
    (+$303, CI across 0) makes it `unstable` too. Declined with both reasons, shown, not hidden."""
    seen = check_chain(client, "taxi")
    rain = next(h for h in seen["hedges"] if h["exposure_id"] == "exp_rain")
    assert rain["status"] == "declined" and rain["decision"]["reasons"] == ["no_market", "unstable"], rain["decision"]
    assert rain["ticker"] is None and rain["n_filled"] == 0  # never the Sunday market (desk week only)
    unstable = next(c for c in rain["decision"]["checks"] if c["code"] == "unstable")["metric"]
    assert unstable["stable"] is False and unstable["enforced"] is True
    assert unstable["effect_last_year_usd"] == next(e for e in seen["analysis"]["exposures"]
                                                    if e["id"] == "exp_rain")["effect_usd"]


def test_a4_taxi_approved_hedge_books(client):
    """An owner-approved hedge from this run writes ledger entries. Data-dependent: needs a
    real proposed/pending hedge, which the committed cache does not provide this week (rain is
    declined, see above), so it runs only after a re-warm (docs/DEMO.md)."""
    seen = check_chain(client, "taxi")
    decidable = [h for h in seen["hedges"] if h["status"] in DECIDABLE]
    if not decidable:
        pytest.skip("the committed Kalshi cache gives taxi no proposed/pending hedge this week "
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


def test_a4_taxi_backtest_served_offline(client):
    """The backtest is stored at startup (and by `make seed`), offline, before any click."""
    r = client.get("/businesses/taxi/backtest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["worst_week_unhedged"] and body["weekly"]
    assert body["estimated"] is False
    client.post("/businesses/taxi/analyze", json={})
    run_desk(client, "taxi")
    assert client.get("/businesses/taxi/backtest").json() == body  # a desk run doesn't disturb it


def test_a4_taxi_model_check(client):
    """Beat 5 proof: a planted $500 effect is recovered with ~90% CI coverage."""
    mc = client.post("/businesses/taxi/analyze", json={}).json()["model_check"]
    assert mc["planted_usd"] == "500.00" and mc["coverage"] >= 0.8
