"""C8-A5 e2e_restaurant.

The restaurant's daily series (`restaurant_daily.parquet`, `msg_visits_daily.parquet`) are
Dewey-derived and gitignored (license, D2), so a fresh clone has no restaurant data:

* without the files, the API must degrade gracefully: `/analyze` -> 409 `analysis_unavailable`,
  the desk run fails contained (logged, no 5xx, sample week restored), everything else answers;
* with the files (after `make seed-data`), the full chain runs like taxi's.

The "without" test always runs: when the files exist it hides them from the feature builder.
"""

import pytest

from chain import check_chain, check_reconcile_runs
from conftest import HAS_RESTAURANT_DATA, run_desk


@pytest.fixture
def no_dewey(monkeypatch):
    from app.data import features

    if HAS_RESTAURANT_DATA:
        monkeypatch.setattr(features, "RESTAURANT_FIXTURE", "absent_restaurant_daily.parquet")
        monkeypatch.setattr(features, "MSG_VISITS_FIXTURE", "absent_msg_visits_daily.parquet")


def _estimated_labels(client):
    b = next(b for b in client.get("/businesses").json() if b["id"] == "restaurant")
    assert b["estimated"] is True and b["data_label"] == "estimated"
    assert b["avg_check_label"] == "assumed"
    ledger = client.get("/businesses/restaurant/ledger").json()
    assert ledger["simulated"] is True


def test_a5_restaurant_without_dewey_data(no_dewey, client):
    r = client.post("/businesses/restaurant/analyze", json={})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "analysis_unavailable"

    hedges_before = client.get("/businesses/restaurant/hedges").json()
    run = run_desk(client, "restaurant")
    assert run["status"] == "failed" and "AnalysisUnavailable" in run["error"]
    log = client.get("/businesses/restaurant/decisions").json()
    assert any(e["kind"] == "run_failed" and e["run_id"] == run["run_id"] for e in log)
    # the sample week (if any) is put back, so the dashboard is never emptied by a failed run
    assert {h["id"] for h in client.get("/businesses/restaurant/hedges").json()} == {h["id"] for h in hedges_before}

    _estimated_labels(client)
    for url in ("/businesses/restaurant/ledger", "/businesses/restaurant/decisions",
                "/businesses/restaurant/settings", "/health"):
        assert client.get(url).status_code == 200, url
    check_reconcile_runs(client, "restaurant")
    assert client.post("/businesses/restaurant/chat", json={"message": "why?"}).status_code == 200


@pytest.mark.skipif(not HAS_RESTAURANT_DATA, reason="fresh clone: Dewey series are gitignored; "
                    "run `make seed-data` to build them and exercise the full restaurant chain")
def test_a5_restaurant_full_chain(client):
    seen = check_chain(client, "restaurant")
    a = seen["analysis"]
    rain = next(e for e in a["exposures"] + a["dropped"] if e["event"] == "rain")
    assert rain["hedge_side"] == "yes" and rain["direction"] == "negative"
    taxi = client.post("/businesses/taxi/analyze", json={}).json()
    taxi_rain = next(e for e in taxi["exposures"] + taxi["dropped"] if e["event"] == "rain")
    assert taxi_rain["hedge_side"] == "no", "rain should cut the opposite way for the two businesses"
    _estimated_labels(client)
    bt = client.get("/businesses/restaurant/backtest")
    if bt.status_code == 200:
        assert bt.json()["estimated"] is True
    check_reconcile_runs(client, "restaurant")
