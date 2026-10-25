"""QuickBooks Online integration: demo company parity with the CSV upload, commitments, the
not-connected 409, and the live OAuth/query client against an httpx.MockTransport (no network)."""

import base64
import csv
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app import clock
from app.config import Settings
from app.integrations import quickbooks as qbo
from app.models import Commitments, QuickBooksResearch
from app.stats import research
from tests.api.conftest import app_env, client  # noqa: F401  (fixtures)

SAMPLE = Path(__file__).resolve().parents[3] / "frontend/public/samples/hudson_bike_co_daily_revenue.csv"
NOW = datetime(2026, 10, 25, 17, 0, tzinfo=timezone.utc)
REALM = "9130350000000001"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    """A temp app DB (the connection is stored there), no network, a pinned clock."""
    from app import config, db

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'qbo.db'}")
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.create_schema()
    qbo.reset()
    monkeypatch.setattr(qbo, "TRANSPORT", None)
    monkeypatch.setattr(clock, "now", lambda: NOW)
    yield
    qbo.reset()
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()


@pytest.fixture(scope="module")
def csv_report():
    return research.run(SAMPLE.read_bytes(), "Hudson Bike Co.")


def csv_daily() -> dict:
    lines = [ln for ln in SAMPLE.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    return {r["date"]: Decimal(r["revenue"]).quantize(Decimal("0.01")) for r in csv.DictReader(lines)}


# --- Demo company ------------------------------------------------------------------


def test_demo_daily_revenue_matches_csv_to_the_cent():
    src = qbo.DemoSource()
    daily = qbo.daily_revenue(src.query("SalesReceipt"), src.query("Invoice"))
    assert {d.isoformat(): v for d, v in daily.items()} == csv_daily()
    assert src.query("Invoice"), "the demo carves some corporate invoices out of daily revenue"


def test_demo_files_are_qbo_query_responses():
    for path in qbo.DEMO_DIR.glob("*.json"):
        body = json.loads(path.read_text())
        assert set(body) == {"QueryResponse", "time"}, path.name
        (entity,) = [k for k in body["QueryResponse"] if k not in ("startPosition", "maxResults")]
        assert path.stem == entity.lower()
    assert "SYNTHETIC" in qbo.DemoSource().query("CompanyInfo")[0]["CompanyName"]


def test_research_before_connect_is_409(client):
    for method, url in (("GET", "/integrations/quickbooks/commitments"), ("POST", "/integrations/quickbooks/research")):
        r = client.request(method, url)
        assert r.status_code == 409, url
        assert r.json()["error"]["code"] == "not_connected"
    s = client.get("/integrations/quickbooks/status").json()
    assert s == {"mode": "demo", "connected": False, "company_name": None, "realm_id": None,
                 "connected_at": None, "synthetic": True}


def test_demo_connect_research_matches_csv_upload(client, csv_report):
    con = client.post("/integrations/quickbooks/connect").json()
    assert con["authorize_url"] is None
    assert con["status"]["connected"] and con["status"]["synthetic"] and con["status"]["mode"] == "demo"
    assert con["status"]["company_name"] == "Hudson Bike Co. (SYNTHETIC)"

    r = client.post("/integrations/quickbooks/research")
    assert r.status_code == 200, r.text
    res = QuickBooksResearch.model_validate(r.json())
    assert res.synthetic and res.days == 1004
    assert (res.first_day.isoformat(), res.last_day.isoformat()) == ("2024-01-01", "2026-09-30")
    assert res.report.name == "Hudson Bike Co. (SYNTHETIC)"
    assert any("SYNTHETIC" in n for n in res.report.notes)  # I6: labeled in the report itself
    assert "accrual" in res.revenue_source

    verdicts = {h.id: h.verdict for h in res.report.hypotheses}
    assert verdicts == {h.id: h.verdict for h in csv_report.hypotheses}
    assert [verdicts[k] for k in ("rain", "cold", "warm")] == ["FOUND"] * 3
    rain, rain_csv = res.report.hypotheses[0], csv_report.hypotheses[0]
    assert rain.id == "rain" and rain.train.effect_usd == rain_csv.train.effect_usd == Decimal("-1923.43")
    assert rain.holdout.effect_usd == rain_csv.holdout.effect_usd
    assert res.report.hypotheses == csv_report.hypotheses  # identical fits, not just verdicts

    named = client.post("/integrations/quickbooks/research", params={"name": "My shop"}).json()
    assert named["report"]["name"] == "My shop"


def test_commitments_totals_and_filters(client):
    client.post("/integrations/quickbooks/connect")
    r = client.get("/integrations/quickbooks/commitments")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["committed_spend"], str) and body["synthetic"] is True
    c = Commitments.model_validate(body)
    assert c.as_of == clock.now().date()
    assert c.committed_spend == sum(x.amount for x in c.purchase_orders + c.bills)
    assert c.expected_revenue == sum(x.amount for x in c.estimates)
    assert c.inventory_value == sum(x.value for x in c.inventory)
    assert all(i.value == (i.qty_on_hand * i.unit_cost).quantize(Decimal("0.01")) for i in c.inventory)
    assert 5 <= len(c.purchase_orders) <= 8 and all(p.status == "Open" for p in c.purchase_orders)
    assert 6 <= len(c.bills) <= 10 and all(b.amount > 0 for b in c.bills)
    assert 4 <= len(c.estimates) <= 8 and {e.status for e in c.estimates} <= {"Pending", "Accepted"}
    assert 8 <= len(c.inventory) <= 15
    # the demo's closed PO, paid bill and closed/rejected estimates are filtered out
    ids = {x.id for x in c.purchase_orders + c.bills + c.estimates}
    assert not ids & {"PO-2039", "HPR-2610", "EST-305", "EST-309"}
    partly = next(b for b in c.bills if b.id == "VSW-88213")
    assert partly.status == "Partially paid" and partly.amount == Decimal("1317.40")


def test_disconnect(client):
    client.post("/integrations/quickbooks/connect")
    s = client.post("/integrations/quickbooks/disconnect").json()
    assert s["connected"] is False and s["company_name"] is None
    assert client.get("/integrations/quickbooks/commitments").status_code == 409


def test_demo_mode_when_offline_even_with_credentials():
    s = Settings(qbo_client_id="id", qbo_client_secret="secret", demo_offline=True)
    assert qbo.QuickBooks(s).mode == "demo"
    assert qbo.QuickBooks(Settings(qbo_client_id="id", qbo_client_secret="secret", demo_offline=False)).mode == "live"
    assert qbo.QuickBooks(Settings(qbo_client_id="id", qbo_client_secret=None, demo_offline=False)).mode == "demo"


# --- Live client (MockTransport) -----------------------------------------------------


def live_settings(**kw) -> Settings:
    return Settings(qbo_client_id="cid", qbo_client_secret="csecret", demo_offline=False,
                    qbo_redirect_uri="http://localhost:8000/integrations/quickbooks/callback", qbo_environment="sandbox",
                    frontend_url="http://localhost:3000", **kw)


class FakeIntuit:
    """Intuit's token endpoint and v3 query API. `tables` maps entity -> rows; `expired` lists
    access tokens that get a 401; `refuse_refresh` makes the refresh grant fail."""

    def __init__(self, tables: dict[str, list[dict]] | None = None):
        self.tables = tables or {"CompanyInfo": [{"CompanyName": "Sandbox Bikes"}]}
        self.expired: set[str] = set()
        self.refuse_refresh = False
        self.token_calls: list[dict] = []
        self.queries: list[str] = []
        self.issued = 0
        self.transport = httpx.MockTransport(self.handle)

    def _tokens(self) -> httpx.Response:
        self.issued += 1
        return httpx.Response(200, json={"access_token": f"a{self.issued}", "refresh_token": f"r{self.issued}",
                                         "expires_in": 3600, "x_refresh_token_expires_in": 8726400,
                                         "token_type": "bearer"})

    def handle(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == qbo.TOKEN_URL:
            assert request.method == "POST"
            assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"cid:csecret").decode()
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_calls.append(form)
            if form["grant_type"] == "refresh_token" and self.refuse_refresh:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return self._tokens()
        assert request.url.host == "sandbox-quickbooks.api.intuit.com"
        assert request.url.path == f"/v3/company/{REALM}/query"
        assert request.url.params["minorversion"] == "75"
        token = request.headers["Authorization"].removeprefix("Bearer ")
        if token in self.expired:
            return httpx.Response(401, json={"fault": {"error": [{"message": "AuthenticationFailed"}]}})
        q = request.url.params["query"]
        self.queries.append(q)
        words = q.split()
        entity, start, size = words[3], int(words[5]), int(words[7])
        rows = self.tables.get(entity, [])[start - 1:start - 1 + size]
        page = {entity: rows, "startPosition": start, "maxResults": len(rows)} if rows else {}
        return httpx.Response(200, text=json.dumps({"QueryResponse": page, "time": "2026-10-25T09:00:00.000-07:00"}))


def connected_live(fake: FakeIntuit, monkeypatch) -> qbo.QuickBooks:
    monkeypatch.setattr(qbo, "TRANSPORT", fake.transport)
    q = qbo.QuickBooks(live_settings())
    url = q.connect().authorize_url
    state = parse_qs(urlparse(url).query)["state"][0]
    q.callback("auth-code", state, REALM)
    return q


def test_live_connect_builds_authorize_url():
    con = qbo.QuickBooks(live_settings()).connect()
    assert con.status.mode == "live" and not con.status.connected and not con.status.synthetic
    u = urlparse(con.authorize_url)
    assert f"{u.scheme}://{u.netloc}{u.path}" == qbo.AUTHORIZE_URL
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert q["client_id"] == "cid" and q["response_type"] == "code"
    assert q["scope"] == "com.intuit.quickbooks.accounting"
    assert q["redirect_uri"] == "http://localhost:8000/integrations/quickbooks/callback"
    assert len(q["state"]) >= 20


def test_live_token_exchange_and_company(monkeypatch):
    fake = FakeIntuit()
    q = connected_live(fake, monkeypatch)
    assert fake.token_calls == [{"grant_type": "authorization_code", "code": "auth-code",
                                 "redirect_uri": "http://localhost:8000/integrations/quickbooks/callback"}]
    s = q.status()
    assert s.connected and s.realm_id == REALM and s.company_name == "Sandbox Bikes" and not s.synthetic
    assert q.source().query("Bill") == []  # empty QueryResponse


def test_live_state_mismatch_and_single_use(monkeypatch):
    fake = FakeIntuit()
    monkeypatch.setattr(qbo, "TRANSPORT", fake.transport)
    q = qbo.QuickBooks(live_settings())
    with pytest.raises(qbo.BadState):
        q.callback("code", "forged", REALM)
    state = parse_qs(urlparse(q.connect().authorize_url).query)["state"][0]
    q.callback("code", state, REALM)
    with pytest.raises(qbo.BadState):  # replay
        q.callback("code", state, REALM)
    assert len(fake.token_calls) == 1


def test_live_refresh_on_401(monkeypatch):
    fake = FakeIntuit({"CompanyInfo": [{"CompanyName": "Sandbox Bikes"}], "Bill": [{"Id": "1"}]})
    q = connected_live(fake, monkeypatch)
    fake.expired.add("a1")
    assert q.source().query("Bill") == [{"Id": "1"}]
    assert fake.token_calls[-1] == {"grant_type": "refresh_token", "refresh_token": "r1"}
    stored = q.load_tokens()
    assert stored.access_token == "a2" and stored.refresh_token == "r2"  # saved for the next call
    q.source().query("Bill")
    assert len(fake.token_calls) == 2


def test_live_refresh_when_token_expires(monkeypatch):
    fake = FakeIntuit({"CompanyInfo": [{"CompanyName": "Sandbox Bikes"}]})
    q = connected_live(fake, monkeypatch)
    monkeypatch.setattr(clock, "now", lambda: NOW + timedelta(hours=2))
    q.source().query("Bill")
    assert fake.token_calls[-1]["grant_type"] == "refresh_token"


def test_live_refresh_failure_is_unavailable(monkeypatch):
    fake = FakeIntuit()
    q = connected_live(fake, monkeypatch)
    fake.expired.add("a1")
    fake.refuse_refresh = True
    with pytest.raises(qbo.Unavailable):
        q.commitments()


def test_live_paging_over_1000_rows(monkeypatch):
    rows = [{"Id": str(i), "TxnDate": "2026-01-01", "TotalAmt": 1} for i in range(1, 2501)]
    fake = FakeIntuit({"CompanyInfo": [{"CompanyName": "Sandbox Bikes"}], "SalesReceipt": rows})
    q = connected_live(fake, monkeypatch)
    got = q.source().query("SalesReceipt")
    assert [r["Id"] for r in got] == [str(i) for i in range(1, 2501)]
    pages = [x for x in fake.queries if "SalesReceipt" in x]
    assert pages == [f"SELECT * FROM SalesReceipt STARTPOSITION {s} MAXRESULTS 1000" for s in (1, 1001, 2001)]


def test_live_parses_same_as_demo(monkeypatch):
    """The demo files served through the live client give the same commitments (same parser)."""
    demo = qbo.DemoSource()
    tables = {e: json.loads((qbo.DEMO_DIR / f"{e.lower()}.json").read_text())["QueryResponse"][e]  # as sent: floats
              for e in ("CompanyInfo", "PurchaseOrder", "Bill", "Estimate", "Item")}
    q = connected_live(FakeIntuit(tables), monkeypatch)
    live = q.commitments()
    want = qbo.build_commitments(demo, NOW.date())
    assert live.model_dump(exclude={"synthetic"}) == want.model_dump(exclude={"synthetic"})
    assert live.synthetic is False and want.synthetic is True


# --- Live endpoints ------------------------------------------------------------------


@pytest.fixture
def live_client(app_env, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from app import config
    from app.main import app

    for k, v in {"QBO_CLIENT_ID": "cid", "QBO_CLIENT_SECRET": "csecret", "DEMO_OFFLINE": "0",
                 "FRONTEND_URL": "http://localhost:3000", "QBO_ENVIRONMENT": "sandbox",
                 "QBO_REDIRECT_URI": "http://localhost:8000/integrations/quickbooks/callback"}.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()
    with TestClient(app) as c:
        yield c


def test_live_callback_routes(live_client, monkeypatch):
    fake = FakeIntuit()
    monkeypatch.setattr(qbo, "TRANSPORT", fake.transport)
    r = live_client.get("/integrations/quickbooks/callback", params={"code": "c", "state": "nope", "realmId": REALM},
                        follow_redirects=False)
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_state"

    con = live_client.post("/integrations/quickbooks/connect").json()
    assert con["status"]["connected"] is False and con["authorize_url"].startswith(qbo.AUTHORIZE_URL)
    state = parse_qs(urlparse(con["authorize_url"]).query)["state"][0]
    r = live_client.get("/integrations/quickbooks/callback",
                        params={"code": "c", "state": state, "realmId": REALM}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "http://localhost:3000/?qbo=connected"
    s = live_client.get("/integrations/quickbooks/status").json()
    assert s["connected"] and s["mode"] == "live" and s["company_name"] == "Sandbox Bikes"

    fake.expired.add("a1")
    fake.refuse_refresh = True
    r = live_client.get("/integrations/quickbooks/commitments")
    assert r.status_code == 502 and r.json()["error"]["code"] == "quickbooks_unavailable"


def test_live_callback_token_failure_redirects_error(live_client, monkeypatch):
    def refuse(request):
        return httpx.Response(400, json={"error": "invalid_grant"})

    monkeypatch.setattr(qbo, "TRANSPORT", httpx.MockTransport(refuse))
    state = parse_qs(urlparse(live_client.post("/integrations/quickbooks/connect").json()["authorize_url"]).query)["state"][0]
    r = live_client.get("/integrations/quickbooks/callback",
                        params={"code": "c", "state": state, "realmId": REALM}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "http://localhost:3000/?qbo=error"
    assert live_client.get("/integrations/quickbooks/status").json()["connected"] is False
