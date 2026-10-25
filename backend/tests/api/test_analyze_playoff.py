"""/analyze for the bar across from MSG carries the playoff home-game exposure (offline)."""

from app import analysis
from app.config import Thresholds
from app.data import features
from tests.fixtures.synth_features import make_synth


def synth_restaurant(business_id, *a, **kw):
    return make_synth(seed=7, estimated=True)  # 2024-01-01 .. mid-2025: covers two Knicks playoff runs


def test_restaurant_analyze_includes_playoff_exposure(client, monkeypatch):
    monkeypatch.setattr(features, "build", synth_restaurant)
    r = client.post("/businesses/restaurant/analyze", json={})
    assert r.status_code == 200
    body = r.json()
    po = [e for e in body["exposures"] if e["event"] == "playoff_home"]
    assert len(po) == 1
    e = po[0]
    assert e["id"] == "exp_playoff_home" and e["hedge_side"] == "no" and e["estimated"] is True
    assert isinstance(e["effect_usd"], str) and float(e["effect_usd"]) > 0
    assert 2.0 < e["expected_count"] < 9.0  # from the cached season futures
    assert "class rating" in e["basis_note"]


def test_taxi_gets_no_playoff_exposure():
    assert analysis.playoff_exposure("taxi", make_synth(seed=1), Thresholds()) is None
