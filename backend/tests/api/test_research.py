"""POST /research (docs/RESEARCH_CONTRACT.md): the 422s in order, and the Hudson verdicts."""

from datetime import date, timedelta
from pathlib import Path

import pytest

from app import research
from app.models import ResearchResponse

HUDSON = Path(__file__).resolve().parents[3] / "frontend" / "public" / "samples" / "hudson_bike_co_daily_revenue.csv"


def _csv(days: int = 600, start: date = date(2024, 1, 1), rev: str = "1000.00") -> str:
    return "date,revenue\n" + "".join(f"{start + timedelta(days=i)},{rev}\n" for i in range(days))


def _post(client, text: str | bytes | None, **form):
    files = None if text is None else {"file": ("rev.csv", text if isinstance(text, bytes) else text.encode(), "text/csv")}
    return client.post("/research", files=files, data=form)


def _err(r, code):
    assert r.status_code == 422, r.text
    body = r.json()["error"]
    assert body["code"] == code, body
    assert body["message"]
    return body["detail"]


@pytest.fixture(scope="module")
def hudson() -> ResearchResponse:
    return research.research_csv(HUDSON.read_bytes())


# --- 422s ----------------------------------------------------------------------


@pytest.mark.parametrize("text,line", [
    (None, None),
    ("", None),
    ("day,amount\n2024-01-01,5\n", None),
    ("date,revenue\n2024-01-01,100\n2024-13-01,100\n", 3),
    ("# comment\ndate,revenue\n2024-01-01,abc\n", 3),
    (b"date,revenue\n2024-01-01,\xff\n", None),
])
def test_bad_csv(client, text, line):
    detail = _err(_post(client, text), "bad_csv")
    assert detail == ({"line": line} if line else None)


def test_bad_csv_too_large(client):
    assert _err(_post(client, b"date,revenue\n" + b"#" * (5 * 1024 * 1024)), "bad_csv") is None


def test_duplicate_dates(client):
    text = _csv(600) + "2024-01-05,10\n2024-01-05,11\n"
    assert _err(_post(client, text), "duplicate_dates") == {"dates": ["2024-01-05"]}


def test_negative_revenue(client):
    text = _csv(600).replace("2024-01-03,1000.00", "2024-01-03,-$1,000.00")
    assert _err(_post(client, text), "negative_revenue") == {"dates": ["2024-01-03"]}


def test_out_of_window(client):
    detail = _err(_post(client, _csv(600, start=date(2023, 12, 30))), "out_of_window")
    assert detail == {"dates": ["2023-12-30", "2023-12-31"], "window": ["2024-01-01", "2026-09-30"]}


def test_too_short_counts_only_nonzero_days(client):
    text = _csv(530) + "".join(f"{date(2025, 6, 14) + timedelta(days=i)},0\n" for i in range(30))
    assert _err(_post(client, text), "too_short") == {"days": 530, "min_days": 540}


def test_order_duplicates_before_negative(client):
    text = _csv(10) + "2024-01-01,-5\n"
    assert _err(_post(client, text), "duplicate_dates")["dates"] == ["2024-01-01"]


def test_name_too_long_is_422(client):
    r = _post(client, _csv(10), name="x" * 61)
    assert r.status_code == 422


def test_parse_strips_dollars_quotes_and_drops_closed_days():
    text = '# note\n\ndate,revenue\n2024-01-01,"$1,234.50"\n2024-01-02,0\n'
    with pytest.raises(research.ResearchError) as e:
        research.parse_csv(text.encode())
    assert e.value.code == "too_short" and e.value.detail["days"] == 1


# --- Hudson Bike Co. -------------------------------------------------------------


def test_hudson_route_validates(client):
    r = client.post("/research", files={"file": ("h.csv", HUDSON.read_bytes(), "text/csv")},
                    data={"name": "Hudson Bike Co.", "kind": "Bike rental"})
    assert r.status_code == 200, r.text
    body = ResearchResponse.model_validate(r.json())
    assert body.source == "live" and len(body.rows) == 6


def test_hudson_verdicts(hudson):
    got = {r.id: (r.verdict, r.verdictNote, r.sendable) for r in hudson.rows}
    assert got == {
        "rain": ("FOUND", "hedgeable", True),
        "cold": ("FOUND", None, False),
        "warm": ("FOUND", "upside, no protection needed", False),
        "hot": ("NOT FOUND", "Not distinguishable from zero", False),
        "knicks_home": ("NOT FOUND", "Not distinguishable from zero", False),
        "knicks_win": ("NOT FOUND", "Not distinguishable from zero", False),
    }
    assert [r.id for r in hudson.rows] == ["rain", "cold", "warm", "hot", "knicks_home", "knicks_win"]


def test_hudson_header_and_summary(hudson):
    assert (hudson.n_days, hudson.first, hudson.last) == (1004, date(2024, 1, 1), date(2026, 9, 30))
    assert hudson.protocol_chips[:2] == ["Training year: 2024", "Unseen: 2025–26"]
    assert not any(ch.isdigit() for ch in hudson.summary)
    assert "rain days" in hudson.summary


def test_hudson_formatting(hudson):
    rain = hudson.rows[0]
    assert rain.train.text.startswith("−") and "/day" in rain.train.text
    assert rain.train.ci.startswith("90% CI −$")
    assert all(str(x).startswith("-") for x in rain.train.plot)
    assert rain.placebo.startswith("Not significant (p 0.")
    assert hudson.rows[0].kalshi.startswith("KXRAIN")
    assert hudson.rows[4].kalshi.startswith("None")
    warm = hudson.rows[2]
    assert warm.train.text.startswith("+") and warm.train.ci.startswith("90% CI +$")


def test_bh():
    assert research.bh_reject([0.001, 0.01, 0.5, 0.9, 0.04, 0.2]) == [True, True, False, False, True, False]
    assert research.bh_reject([0.2] * 6) == [False] * 6
