"""C6-A1: every route returns schema-valid JSON; C6-A4 (live): money fields are strings."""

import re

from pydantic import TypeAdapter

from app import db
from app.models import (
    BacktestResult, Business, ChatReply, Health, Hedge, LedgerResponse, LogEntry, RunAccepted, RunStatus,
    Settings,
)
from tests.api.conftest import FIXTURE_WEEK, load_example

MONEY_KEYS = {"premium", "cost", "fee", "budget", "spent", "remaining", "pending", "avg_price", "fair",
              "expected_cost", "effect_usd", "se", "unhedged_swing", "hedged_swing", "amount"}
DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")

ROUTES = {
    ("GET", "/health"), ("GET", "/businesses"), ("POST", "/businesses/{business_id}/analyze"),
    ("POST", "/businesses/{business_id}/desk/run"), ("GET", "/runs/{run_id}"),
    ("GET", "/businesses/{business_id}/hedges"), ("GET", "/businesses/{business_id}/backtest"),
    ("GET", "/businesses/{business_id}/ledger"), ("POST", "/businesses/{business_id}/reconcile"),
    ("POST", "/businesses/{business_id}/chat"), ("GET", "/businesses/{business_id}/decisions"),
    ("GET", "/businesses/{business_id}/settings"), ("PUT", "/businesses/{business_id}/settings"),
    ("POST", "/hedges/{hedge_id}/approve"), ("POST", "/hedges/{hedge_id}/reject"),
}


def money_are_strings(obj, path="$"):
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            scalar = not isinstance(v, (dict, list)) and v is not None
            if k in MONEY_KEYS and scalar and not (isinstance(v, str) and DECIMAL.match(v)):
                bad.append(f"{path}.{k}={v!r}")
            bad += money_are_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad += money_are_strings(v, f"{path}[{i}]")
    return bad


def test_openapi_lists_every_route(client):
    spec = client.get("/openapi.json").json()
    have = {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops}
    assert ROUTES <= have


def test_every_route_validates(client, stub_analysis):
    db.put_analysis("taxi", "backtest", load_example("backtest_result.json"), "2026-10-24T00:00:00Z")
    checks = []

    def ok(method, url, model, status=200, **kw):
        r = client.request(method, url, **kw)
        assert r.status_code == status, (url, r.text)
        body = r.json()
        TypeAdapter(model).validate_python(body)
        assert not money_are_strings(body), money_are_strings(body)
        checks.append(url)
        return body

    ok("GET", "/health", Health)
    for b in ok("GET", "/businesses", list[Business]):
        assert b["budget"]["week_start"] == FIXTURE_WEEK
    ok("POST", "/businesses/taxi/analyze", dict, json={})
    run = ok("POST", "/businesses/taxi/desk/run", RunAccepted, status=202, json={})
    ok("GET", f"/runs/{run['run_id']}", RunStatus)
    ok("GET", "/businesses/taxi/hedges", list[Hedge])
    ok("GET", "/businesses/taxi/backtest", BacktestResult)
    ok("GET", "/businesses/taxi/ledger", LedgerResponse)
    ok("POST", "/businesses/taxi/chat", ChatReply, json={"message": "why?"})
    ok("GET", "/businesses/taxi/decisions", list[LogEntry])
    settings = ok("GET", "/businesses/taxi/settings", Settings)
    ok("PUT", "/businesses/taxi/settings", Settings, json=settings)
    ok("POST", "/hedges/hdg_01/approve", Hedge, json={"actor": "owner"})
    ok("POST", "/hedges/hdg_02/reject", Hedge, json={"actor": "owner", "reason": "not this week"})
    r = client.post("/businesses/taxi/reconcile", json={})
    assert r.status_code in (200, 409) and ("error" in r.json() or "matches" in r.json())


def test_money_strings_on_hedges(client):
    hedges = client.get("/businesses/taxi/hedges", params={"week_of": FIXTURE_WEEK}).json()
    assert hedges and all(isinstance(h["premium"], (str, type(None))) for h in hedges)
    assert not money_are_strings(hedges)
