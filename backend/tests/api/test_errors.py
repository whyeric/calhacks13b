"""C6-A21: 403/404/409/422 (including FastAPI validation) share one error shape; C6-A20 CORS."""

from app.models import ErrorBody


def _shape(r, status, code=None):
    assert r.status_code == status, r.text
    body = r.json()
    ErrorBody.model_validate(body)
    assert set(body["error"]) == {"code", "message", "detail"}
    if code:
        assert body["error"]["code"] == code


def test_uniform_error_shape(client):
    _shape(client.post("/businesses/nope/analyze", json={}), 404, "business_not_found")
    _shape(client.get("/runs/nope"), 404, "run_not_found")
    _shape(client.get("/no/such/route"), 404, "not_found")
    _shape(client.post("/businesses/taxi/chat", json={"message": ""}), 422, "invalid_request")
    _shape(client.post("/businesses/taxi/chat", json={"msg": "hi"}), 422, "invalid_request")
    _shape(client.post("/businesses/taxi/analyze", json={"strike": "hot"}), 422, "invalid_request")
    _shape(client.post("/hedges/hdg_03/approve", json={"actor": "owner"}), 409, "invalid_state")
    _shape(client.post("/hedges/hdg_02/approve", json={"actor": "desk"}), 403, "owner_only")
    _shape(client.get("/businesses/taxi/backtest"), 409, "backtest_not_ready")
    _shape(client.get("/businesses/taxi/hedges", params={"week_of": "x"}), 422, "bad_week_of")


def test_cors_dev_origin_allowed_foreign_rejected(client):
    pre = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    for path in ("/businesses/taxi/desk/run", "/hedges/hdg_02/approve", "/businesses/taxi/chat"):
        ok = client.options(path, headers={"Origin": "http://localhost:3000", **pre})
        assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "http://localhost:3000"
        bad = client.options(path, headers={"Origin": "http://evil.example", **pre})
        assert bad.headers.get("access-control-allow-origin") != "http://evil.example"
