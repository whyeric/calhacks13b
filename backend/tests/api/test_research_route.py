"""POST /research: live protocol on a raw CSV body; stateless; 422s carry the contract error body."""

from pathlib import Path

from app import db

SAMPLE = Path(__file__).resolve().parents[3] / "frontend/public/samples/hudson_bike_co_daily_revenue.csv"


def test_research_returns_report(client):
    before = len(db.list_businesses())
    r = client.post("/research?name=Hudson%20Bike%20Co.", content=SAMPLE.read_bytes(),
                    headers={"Content-Type": "text/csv"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Hudson Bike Co."
    assert [h["verdict"] for h in body["hypotheses"]] == ["FOUND", "FOUND", "FOUND", "NOT FOUND", "NOT FOUND", "NOT FOUND"]
    rain = body["hypotheses"][0]
    assert isinstance(rain["train"]["effect_usd"], str) and isinstance(rain["train"]["pct"], float)
    assert len(db.list_businesses()) == before  # nothing stored


def test_research_errors(client):
    r = client.post("/research", content=b"", headers={"Content-Type": "text/csv"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_csv"
    r = client.post("/research", content=b"date,revenue\n2024-01-01,1\n2024-01-01,2\n",
                    headers={"Content-Type": "text/csv"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "duplicate_dates"
    assert r.json()["error"]["detail"]["dates"] == ["2024-01-01"]
