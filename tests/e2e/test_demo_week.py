"""C8-A6 demo_week_outcome_mix, C8-A7 pending_not_self_approved, C8-A9 declined_flips_with_threshold.

Two views of the demo week (Mon 2026-10-26):

* **as shipped** - `make seed` with the default `DEMO_SAMPLE_WEEK=1`: the labeled sample week
  (`backend/fixtures/examples/week_seed.json`), which is what `make demo` shows before anyone
  clicks Run desk (docs/DEMO.md);
* **real pipeline** - desk runs for both businesses on the committed Kalshi cache, sample hedges
  replaced. Which outcomes it yields depends on the books captured by `make warm`.
"""

from decimal import Decimal

import pytest

from chain import DECIDABLE
from conftest import DEMO_WEEK, HAS_RESTAURANT_DATA, run_desk

BUSINESSES = ("taxi", "restaurant")


def _hedges(client, b):
    return client.get(f"/businesses/{b}/hedges", params={"week_of": DEMO_WEEK}).json()


def _all(client):
    return [h for b in BUSINESSES for h in _hedges(client, b)]


def _within_budget(h) -> bool:
    """The desk's own over_budget check passed: the premium fit the budget left when it was decided
    (later pending legs count against `remaining`, D4, so that number alone can't tell)."""
    ob = next(c for c in h["decision"]["checks"] if c["code"] == "over_budget")
    return ob["passed"] is True and Decimal(ob["metric"]["premium"]) <= Decimal(ob["metric"]["remaining"])


def _assert_mix(client, hedges):
    declined = [h for h in hedges if h["status"] == "declined"]
    pending = [h for h in hedges if h["status"] == "pending_approval"]
    eligible = [h for h in hedges if h["status"] == "proposed" and _within_budget(h)]
    return declined, pending, eligible


# --- C8-A6 ------------------------------------------------------------------------


def test_a6_demo_week_as_shipped(client):
    health = client.get("/health").json()
    assert health["sample_week"] is True, "the shipped week must be labeled as sample (I6)"
    hedges = _all(client)
    declined, pending, eligible = _assert_mix(client, hedges)
    assert declined and all(h["decision"]["reasons"] for h in declined)
    assert pending, "no pending_approval hedge in the demo week"
    assert eligible, "no approved-eligible (proposed, within budget) hedge in the demo week"
    listed = {h["id"] for h in hedges}
    assert all(h["id"] in listed for h in declined)  # I3: declined ones are listed, not hidden


def test_a6_real_pipeline_outcome_mix(client):
    """Real desk runs on the committed cache. Taxi rain is declined (no_market + unstable). With the
    Dewey data the restaurant's playoff season hedge adds a within-budget leg (proposed) and legs
    that wait for the owner (pending_approval, over_budget), so the real week has the full mix."""
    for b in BUSINESSES:
        run = run_desk(client, b)
        assert run["status"] in ("done", "failed")
    real = [h for h in _all(client) if not h["id"].startswith("hdg_0")]  # sample ids are hdg_01..04
    declined, pending, eligible = _assert_mix(client, real)
    assert declined and all(h["decision"]["reasons"] for h in declined), real
    if not HAS_RESTAURANT_DATA:
        pytest.skip("fresh clone: the restaurant (playoff legs) needs the gitignored Dewey series; "
                    f"taxi alone gives {[(h['id'], h['status'], h['decision']['reasons']) for h in real]}")
    assert pending and eligible, [(h["id"], h["status"], h["decision"]["reasons"]) for h in real]
    assert all(h["exposure_id"] == "exp_playoff_home" for h in pending + eligible)
    assert all(h["estimated"] for h in pending + eligible)  # I6: restaurant dollars are estimated
    h = eligible[0]
    r = client.post(f"/hedges/{h['id']}/approve", json={"actor": "owner"})
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["ledger_entry_ids"], r.text


# --- C8-A7 ------------------------------------------------------------------------


def _pending(client):
    pending = [h for h in _all(client) if h["status"] == "pending_approval"]
    assert pending, "A7 needs a pending hedge (A6)"
    return pending[0]


def test_a7_pending_not_self_approved(client):
    h = _pending(client)
    b = h["business_id"]

    def booked():
        return [e for e in client.get(f"/businesses/{b}/ledger").json()["entries"]
                if (e.get("meta") or {}).get("hedge_id") == h["id"]]

    assert not booked() and not h["ledger_entry_ids"]
    for body in ({"actor": "desk"}, {"actor": "system"}, {"actor": "Owner"}, {}):
        r = client.post(f"/hedges/{h['id']}/approve", json=body)
        assert r.status_code == 403, (body, r.status_code)
        assert r.json()["error"]["code"] == "owner_only"
    assert not booked()
    assert next(x for x in _hedges(client, b) if x["id"] == h["id"])["status"] == "pending_approval"

    r = client.post(f"/hedges/{h['id']}/approve", json={"actor": "owner"})
    assert r.status_code == 200, r.text
    approved = r.json()
    assert approved["status"] == "approved" and approved["decided_by"] == "owner"
    entries = booked()
    assert entries and all(e["meta"]["approved_by"] == "owner" for e in entries)
    log = client.get(f"/businesses/{b}/decisions").json()
    assert any(e["kind"] == "approval" and e["hedge_id"] == h["id"] and e["actor"] == "owner" for e in log)


# --- C8-A9 ------------------------------------------------------------------------


def _put(client, b, **thresholds):
    s = client.get(f"/businesses/{b}/settings").json()
    s["thresholds"].update(thresholds)
    r = client.put(f"/businesses/{b}/settings", json=s)
    assert r.status_code == 200, r.text


LOOSEN = {"overpriced": {"overpay_max": "0.99"}, "too_expensive": {"cost_ratio_max": "9.99"},
          "basis_too_loose": {"basis_r2_min": 0.0}, "illiquid": {"fill_decline": "0.0"}}


def test_a9_declined_flips_with_threshold(client):
    declined = [h for h in _all(client) if h["status"] == "declined"
                and set(h["decision"]["reasons"]) <= set(LOOSEN) and h["n_filled"] > 0]
    assert declined, "A9 needs a declined hedge whose failing rules are thresholds"
    h = declined[0]
    b = h["business_id"]
    original = client.get(f"/businesses/{b}/settings").json()

    _put(client, b, **{k: v for r in h["decision"]["reasons"] for k, v in LOOSEN[r].items()})
    flipped = next(x for x in _hedges(client, b) if x["id"] == h["id"])
    assert flipped["status"] in DECIDABLE, flipped["decision"]

    assert client.put(f"/businesses/{b}/settings", json=original).status_code == 200
    back = next(x for x in _hedges(client, b) if x["id"] == h["id"])
    assert back["status"] == "declined" and back["decision"]["reasons"] == h["decision"]["reasons"]

    log = [e for e in client.get(f"/businesses/{b}/decisions", params={"limit": 500}).json()
           if e["hedge_id"] == h["id"]]  # newest first
    flips = [e for e in log if e["kind"] == "threshold_changed"]
    assert [e["status"] for e in flips[:2]] == ["declined", flipped["status"]], flips
    assert all(e["checks"] for e in flips[:2]), "each re-evaluation is logged with its checks"
    assert any(e["status"] == "declined" and e["kind"] != "threshold_changed" for e in log), \
        "the original decline is still in the log"


def test_a9_zero_fill_never_becomes_a_proposal(client, monkeypatch):
    """Loosening fill_decline (and the unstable rule) never turns a 0-contract hedge into a $0
    proposal. The zero fill is the cached Sunday rain book (KXRAIN-26OCT25-NYC, no `no` depth),
    reached by lifting the desk-week filter for this test only."""
    from app.markets import match

    monkeypatch.setattr(match, "in_week", lambda market, week_of: True)
    run_desk(client, "taxi")
    zero = [h for h in _hedges(client, "taxi") if h["status"] == "declined" and h["n_filled"] == 0
            and "illiquid" in h["decision"]["reasons"]]
    assert zero, [(h["id"], h["status"], h["n_filled"], h["decision"]["reasons"]) for h in _hedges(client, "taxi")]
    _put(client, "taxi", fill_decline="0.0", decline_unstable=False, overpay_max="0.99",
         cost_ratio_max="9.99", basis_r2_min=0.0)
    after = next(x for x in _hedges(client, "taxi") if x["id"] == zero[0]["id"])
    assert after["status"] == "declined", (after["status"], after["n_filled"], after["premium"])
    assert after["decision"]["reasons"] == ["illiquid"]
