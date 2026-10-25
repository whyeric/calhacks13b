"""Shared assertions for the exposures -> market -> size -> decide -> log chain (C8-A4/A5)."""

from __future__ import annotations

import math
from decimal import Decimal

from conftest import run_desk, run_entries

DECIDABLE = ("proposed", "pending_approval")


def check_chain(client, business_id: str) -> dict:
    """Analyze, run the desk, and check every hedge the run wrote. Returns what it saw."""
    r = client.post(f"/businesses/{business_id}/analyze", json={})
    assert r.status_code == 200, r.text
    analysis = r.json()
    exposures = {e["id"]: e for e in analysis["exposures"]}
    assert analysis["model_check"] is not None

    run = run_desk(client, business_id)
    assert run["status"] == "done", run
    assert run["agent"] == "fallback"
    entries = run_entries(client, business_id, run["run_id"])
    hedges = [h for h in client.get(f"/businesses/{business_id}/hedges").json()
              if h["id"] in {e["hedge_id"] for e in entries}]
    # one hedge (proposed, pending or declined) per hedgeable exposure, none hidden (I3)
    assert {h["exposure_id"] for h in hedges} == set(exposures)

    for h in hedges:
        e = exposures[h["exposure_id"]]
        assert h["agent"] == "fallback"
        assert h["side"] == e["hedge_side"]
        dec = h["decision"]
        assert dec["status"] == h["status"] and dec["checks"], h["id"]
        if h["status"] == "declined":
            assert dec["reasons"], f"{h['id']} declined without reasons"
        if dec["reasons"] != ["no_market"]:
            assert h["ticker"] and h["market_title"], f"{h['id']} has no market"
            # I1: N <= ceil(h * |beta| / $1), from the basis check's own numbers
            basis = next(c for c in dec["checks"] if c["code"] == "basis_too_loose")["metric"]
            ratio = Decimal(h["h"])
            assert Decimal("0") < ratio <= Decimal("1")
            beta = abs(Decimal(basis.get("beta", e["effect_usd"])))
            assert h["n_target"] <= math.ceil(ratio * beta), (h["n_target"], ratio, beta)
            assert h["n_filled"] <= h["n_target"]
        # I5: the decision is in the log, with the same checks
        logged = [x for x in entries if x["hedge_id"] == h["id"]]
        assert logged and all(x["agent"] == "fallback" for x in logged)
        assert any(x["checks"] == dec["checks"] for x in logged)
    return {"analysis": analysis, "run": run, "hedges": hedges, "entries": entries}


def check_reconcile_runs(client, business_id: str) -> dict:
    r = client.post(f"/businesses/{business_id}/reconcile", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["simulated"] is True
    return body
