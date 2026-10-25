"""C6-A25 analyze (stub and real taxi), C6-A26 chat, C6-A28 backtest, R14 settings."""

import re
from decimal import Decimal

from app import analysis, db
from tests.api.conftest import FIXTURE_WEEK, load_example


def test_analyze_stub_returns_model_check(client, stub_analysis):
    r = client.post("/businesses/taxi/analyze", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["model_check"]["coverage"] == stub_analysis.model_check.coverage
    assert isinstance(body["r2_holdout"], float)
    assert body["dropped"] and all(d["reasons"] for d in body["dropped"])
    assert db.get_analysis("taxi", analysis.cache_key(None)) is not None  # cached


def test_analyze_real_taxi_and_null_holdout(client, monkeypatch):
    body = client.post("/businesses/taxi/analyze", json={}).json()
    assert body["model_check"]["n_seeds"] == 50
    assert body["exposures"] and all(isinstance(e["effect_usd"], str) for e in body["exposures"])

    from app.models import AnalyzeResponse

    res = AnalyzeResponse.model_validate(load_example("analyze_response.json") | {"r2_holdout": None})
    monkeypatch.setattr(analysis, "compute", lambda business_id, strike=None: res)
    assert client.post("/businesses/taxi/analyze", json={}).json()["r2_holdout"] is None


def test_analyze_without_data_409(client, monkeypatch):
    def missing(business_id, strike=None):
        raise analysis.AnalysisUnavailable("restaurant fixture missing")

    monkeypatch.setattr(analysis, "compute", missing)
    r = client.post("/businesses/restaurant/analyze", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "analysis_unavailable"


def test_chat_fallback_numbers_come_from_tools(client):
    r = client.post("/businesses/taxi/chat", json={"message": "why that hedge?"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] and isinstance(body["tool_calls"], list)
    call = body["tool_calls"][0]
    assert set(call) == {"name", "input", "output"}
    out = repr(call["output"])
    for num in re.findall(r"\d+(?:\.\d+)?", body["reply"].replace(",", "")):
        assert num in out, num
    assert db.list_log("taxi")[-1].kind == "chat"


def test_backtest_served_from_cache(client):
    db.put_analysis("taxi", "backtest", load_example("backtest_result.json"), "2026-10-24T00:00:00Z")
    body = client.get("/businesses/taxi/backtest").json()
    assert "reduction_pct" in body and "priced_real_pct" in body
    assert client.get("/businesses/restaurant/backtest").status_code == 409


def test_settings_put_reruns_rules_and_logs_flips(client):
    s = client.get("/businesses/taxi/settings").json()
    assert s["weekly_budget"] == "250.00"
    before = {h["id"]: h["status"] for h in client.get("/businesses/taxi/hedges").json()}
    s["weekly_budget"] = "5000.00"
    r = client.put("/businesses/taxi/settings", json=s)
    assert r.status_code == 200 and r.json()["weekly_budget"] == "5000.00"
    after = {h["id"]: h["status"] for h in client.get("/businesses/taxi/hedges").json()}
    assert before["hdg_02"] == "pending_approval" and after["hdg_02"] == "proposed"
    flips = [e for e in db.list_log("taxi") if e.kind == "threshold_changed"]
    assert [e.hedge_id for e in flips] == ["hdg_02"]
    budget = next(b for b in client.get("/businesses").json() if b["id"] == "taxi")["budget"]
    assert budget["week_start"] == FIXTURE_WEEK and Decimal(budget["budget"]) == Decimal("5000")


def test_settings_bad_body_422(client):
    r = client.put("/businesses/taxi/settings", json={"weekly_budget": 12.5})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"
