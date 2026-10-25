"""C4-A1..A10: the I2 number validator."""

from decimal import Decimal as D

import pytest

from app.agent import log
from app.agent.log import allowed_numbers, validate_summary

from .conftest import example


def declined_checks():
    h = example("hedge_declined.json")
    return {c["code"]: c["metric"] for c in h["decision"]["checks"]}


def test_A1_exact_figures():
    m = declined_checks()
    m["too_expensive"]["ratio"] = "0.3647"
    assert validate_summary("Declined: 62¢ against a 27% rain rate ... 36% of the swing.", m) == []


@pytest.mark.parametrize("s,ok", [("36%", True), ("0.36", True), ("37%", False), ("0.4", False)])
def test_A2_rounding(s, ok):
    assert (validate_summary(s, {"ratio": D("0.3647")}) == []) is ok


@pytest.mark.parametrize("s,ok", [("$1,240", True), ("$1240", True), ("$1,240.00", True), ("$328.20", True),
                                  ("$1,300", False)])
def test_A3_dollars_commas(s, ok):
    assert (validate_summary(s, {"swing": D("1240.0"), "expected_cost": D("328.2")}) == []) is ok


@pytest.mark.parametrize("s,ok", [("62¢", True), ("62 cents", True), ("$0.62", True), ("$62", False)])
def test_A4_cents_dollars(s, ok):
    assert (validate_summary(s, {"avg_price": D("0.62")}) == []) is ok


@pytest.mark.parametrize("s,ok", [("27%", True), ("27 percent", True), ("0.27", True), ("2.7%", False),
                                  ("270%", False)])
def test_A5_percent_probability(s, ok):
    assert (validate_summary(s, {"fair": D("0.27")}) == []) is ok


@pytest.mark.parametrize("s,ok", [("68 days", True), ("41 of them", True), ("70 days", False)])
def test_A6_counts(s, ok):
    assert (validate_summary(s, {"days_paid": 68, "days_lost": 41}) == []) is ok


def test_A7_invented_number_rejected_log_unchanged():
    before = len(log.list("taxi"))
    entry = dict(business_id="taxi", kind="decline", actor="desk", agent="claude", hedge_id=None,
                 decision_id=None, run_id=None, status="declined", checks=[], reasons=[],
                 numbers=allowed_numbers(declined_checks()), summary="Declined: it would cost $500.")
    with pytest.raises(log.UnsupportedNumbers) as e:
        log.append(entry)
    assert e.value.offending == ["$500"]
    assert len(log.list("taxi")) == before


def test_A8_non_figures_exempt():
    s = "On Saturday, KXHIGHNY-26OCT25-T68 closes; the 12-call cap held for one or two runs on Oct 28."
    assert validate_summary(s, {}) == []
    assert validate_summary("It closes in 3 hours.", {}) == ["3"]
    assert validate_summary("It closes in 3 hours.", {"hours": 3}) == []


def test_A9_sizing_and_budget_attached():
    hedge = example("hedge_pending.json")
    budget = example("budget.json")
    s = (f"Waiting on you: {hedge['n_filled']} contracts cost ${hedge['premium']} against a "
         f"${budget['budget']} budget.")
    checks_only = allowed_numbers({c["code"]: {k: v for k, v in c["metric"].items() if k != "premium"}
                                   for c in hedge["decision"]["checks"]})
    attached = allowed_numbers({"hedge": {k: hedge[k] for k in ("n_filled", "premium")}, "budget": budget})
    assert validate_summary(s, attached) == []
    assert validate_summary(s, checks_only) != []


@pytest.mark.parametrize("s,ok", [("$420 lower", True), ("$-420", True), ("-$420", True), ("$4,200", False)])
def test_A10_negatives(s, ok):
    assert (validate_summary(s, {"effect": D("-420")}) == []) is ok


def test_sanitize_replaces_only_bad_tokens():
    out, bad = log.sanitize("It costs $500 against $1,240.", {"swing": D("1240")})
    assert bad == ["$500"] and "[unverified]" in out and "$1,240" in out
