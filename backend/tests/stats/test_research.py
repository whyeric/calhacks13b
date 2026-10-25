"""Live research protocol (stats/research.py) on the Hudson Bike Co. sample: a recovery check.

The sample is synthetic revenue with planted effects (about −20% rain, −28% below 40°F, +10%
above 80°F, no game effect) on real NOAA Central Park weather. The protocol must find exactly the
three planted effects, close to their planted sizes, and reject the rest.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from app.models import ResearchReport
from app.stats import research

SAMPLE = Path(__file__).resolve().parents[3] / "frontend/public/samples/hudson_bike_co_daily_revenue.csv"


@pytest.fixture(scope="module")
def report() -> ResearchReport:
    return research.run(SAMPLE.read_bytes(), "Hudson Bike Co.")


def rows(report):
    return {h.id: h for h in report.hypotheses}


def test_finds_exactly_the_planted_effects(report):
    verdicts = {h.id: h.verdict for h in report.hypotheses}
    assert verdicts == {"rain": "FOUND", "cold": "FOUND", "warm": "FOUND",
                        "hot": "NOT FOUND", "knicks_home": "NOT FOUND", "knicks_win": "NOT FOUND"}


@pytest.mark.parametrize(("hid", "planted"), [("rain", -20), ("cold", -28), ("warm", 10)])
def test_recovers_planted_sizes(report, hid, planted):
    h = rows(report)[hid]
    for est in (h.train, h.holdout):
        assert abs(est.pct - planted) <= 6, (hid, est.pct)
        assert est.ci_excludes_zero


def test_matches_the_offline_run_shown_before(report):
    """The scripted report's rain row (−18.4%, −$1,955.68/day) came from an offline run of the same
    protocol; the live run lands within a few dollars a percent of it."""
    rain = rows(report)["rain"]
    assert abs(rain.train.pct - (-18.4)) < 0.5
    assert abs(rain.train.effect_usd - Decimal("-1955.68")) < 60
    assert abs(rain.holdout.effect_usd - Decimal("-2485.41")) < 60


def test_split_and_counts(report):
    assert (report.n_rows, report.n_days, report.n_closed_days, report.n_outside_window) == (1004, 1004, 0, 0)
    assert str(report.train.start) == "2024-01-01" and str(report.train.end) == "2024-12-31"
    assert str(report.holdout.start) == "2025-01-01" and str(report.holdout.end) == "2026-09-30"
    assert any("SYNTHETIC" in n for n in report.notes)  # I6: the file's own label is surfaced


def test_reasons_and_sendable(report):
    r = rows(report)
    assert r["hot"].reasons == ["not_significant"]
    assert r["warm"].upside and not r["warm"].sendable
    assert r["rain"].sendable and not r["cold"].sendable
    assert all(h.placebo_p is not None and h.placebo_p >= research.PLACEBO_ALPHA
               for h in report.hypotheses if h.verdict == "FOUND")


def test_summary_has_no_numbers(report):
    assert not any(ch.isdigit() for ch in report.summary.replace("40°F", "").replace("80°F", "").replace("90°F", ""))


def test_deterministic(report):
    again = research.run(SAMPLE.read_bytes(), "Hudson Bike Co.")
    assert again.model_dump_json() == report.model_dump_json()


def test_bh_qvalues():
    q = research.bh_qvalues([0.01, 0.04, 0.03, 0.5])
    assert q == pytest.approx([0.04, 0.0533333, 0.0533333, 0.5], rel=1e-4)


def _csv(lines):
    return ("date,revenue\n" + "\n".join(lines) + "\n").encode()


@pytest.mark.parametrize(("raw", "code"), [
    (b"hello\n", "bad_csv"),
    (_csv(["2024-01-01,10", "2024-01-01,12"]), "duplicate_dates"),
    (_csv(["2024-01-01,10", "2024-01-02,-5"]), "negative_revenue"),
    (_csv([f"2010-01-{d:02d},10" for d in range(1, 29)]), "out_of_window"),
    (_csv([f"2024-01-{d:02d},10" for d in range(1, 29)]), "too_short"),
])
def test_input_errors(raw, code):
    with pytest.raises(research.ResearchInputError) as e:
        research.run(raw)
    assert e.value.code == code


def test_accepts_other_headers_and_money_formatting():
    lines = SAMPLE.read_text().splitlines()
    body = [ln for ln in lines if ln and not ln.startswith("#")][1:]
    raw = ("Day,Sales\n" + "\n".join(f'{d},"${float(v):,.2f}"' for d, v in (ln.split(",") for ln in body))).encode()
    rep = research.run(raw)
    assert {h.id for h in rep.hypotheses if h.verdict == "FOUND"} == {"rain", "cold", "warm"}
