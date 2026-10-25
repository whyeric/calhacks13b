"""C3-A13–A21: each decline rule at its threshold, logging, precedence, threshold flip."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from app.config import Thresholds
from app.markets.match import Candidate, Depth
from app.markets.rules import (
    check_basis, check_illiquid, check_overpriced, check_too_expensive, evaluate, resolve_h,
)
from app.markets.shapes import Sizing
from app.markets.sizing import target_contracts
from app.models import BasisStat, Headline

TH = Thresholds()
T0 = datetime(2026, 10, 24, tzinfo=timezone.utc)
CODES = ["no_market", "illiquid", "overpriced", "basis_too_loose", "too_expensive", "over_budget"]
BAR = {"id": "exp_rain", "business_id": "restaurant", "effect_usd": "-900.00",
       "hedge_side": "yes", "settlement_var": "rain"}
GOOD_BASIS = BasisStat(r2=D("0.81"), beta_s=D("-900"), se=D("100"))
CANDS = [Candidate(
    ticker="T1", series_ticker="S", title="", close_time=T0, status="active", rules_primary="",
    floor_strike=None, settlement_var="rain", fee_type="quadratic", fee_multiplier=D(1),
    yes_ask=D("0.42"), no_ask=None, yes_bid=None, no_bid=None, depth_within_5c=Depth(yes=900, no=0), fetched_at=T0,
)]


def sizing(n_target=900, n_filled=900, avg="0.30", fair="0.27", expected_cost="50.00", premium="100.00"):
    cost = D(avg) * n_filled
    return Sizing(
        ticker="T1", series_ticker="S", market_title="", close_time=T0, side="yes", h=D(1), resized=False,
        n_target=n_target, n_filled=n_filled, n_unfilled=n_target - n_filled, partial=False, fills=[],
        avg_price=D(avg) if n_filled else None, cost=cost, fee=D("1"), premium=D(premium),
        p_hat=D(fair), fair=D(fair), expected_cost=D(expected_cost), fee_unverified=False, payoff=[],
        headline=Headline(unhedged_swing=D("900"), hedged_swing=D("0"), cost=D(premium)),
    )


def run(s=None, basis=GOOD_BASIS, remaining="250.00", th=TH, exposure=BAR, cands=CANDS):
    return evaluate(exposure, cands, sizing() if s is None else s, basis, D(remaining), th)


def metric_json(check):
    return check.model_dump(mode="json")["metric"]


def test_rule1_no_market_declines_with_everything_logged():
    d = evaluate(BAR, [], None, GOOD_BASIS, D("250"), TH)
    assert (d.status, d.reasons) == ("declined", ["no_market"])
    assert [c.code for c in d.checks] == CODES
    assert all(c.passed is None and c.metric == {"skipped": "no_market"} for c in d.checks[1:5])
    assert d.checks[5].passed is True and metric_json(d.checks[5])["premium"] == "0.00"


@pytest.mark.parametrize("filled,passed,partial,status", [
    (49, False, False, "declined"), (50, True, True, "proposed"), (100, True, False, "proposed")])
def test_rule2_illiquid_threshold(filled, passed, partial, status):
    c = check_illiquid(100, filled, TH)
    assert (c.passed, c.metric["partial"]) == (passed, partial)
    assert run(sizing(n_target=100, n_filled=filled)).status == status


def test_rule2_fill_ratio_display_never_rounds_up_into_a_pass():
    assert metric_json(check_illiquid(200, 99, TH))["fill_ratio"] == "0.49"


@pytest.mark.parametrize("fair,passed,overpay", [("0.27", True, "0.15"), ("0.269", False, "0.151"), ("0.30", True, "0.12")])
def test_rule3_overpriced_is_strictly_greater(fair, passed, overpay):
    c = check_overpriced(D("0.42"), D(fair), TH, side="yes")
    assert c.passed is passed
    m = metric_json(c)
    assert (m["avg_price"], m["overpay"]) == ("0.42", overpay)


def test_rule3_never_calls_a_hedge_underpriced():
    c = check_overpriced(D("0.01"), D("0.3973"), TH, side="yes")
    m = metric_json(c)
    assert c.passed is True
    assert m["overpay"] == "0.00"  # not -0.3873
    assert m["note"] == "Market price reflects the current forecast; historical rate is 40%."


def test_rule3_note_threshold_and_no_side_rate():
    assert "note" not in metric_json(check_overpriced(D("0.37"), D("0.27"), TH, side="yes"))  # exactly 10 pts
    assert "note" in metric_json(check_overpriced(D("0.3701"), D("0.27"), TH, side="yes"))
    # NO side: fair is 1 − p̂ = 0.6027, but the receipt names the event's own rate, p̂ = 40%.
    m = metric_json(check_overpriced(D("0.99"), D("0.6027"), TH, side="no"))
    assert m["note"].endswith("historical rate is 40%.")
    assert m["overpay"] == "0.3873"


def test_rule3_uses_exact_average_not_display_rounding():
    # True avg 0.42004 would display as 0.4200 (overpay exactly 0.15, a pass); the rule sees 0.15004.
    assert run(sizing(n_target=20000, n_filled=20000, avg="0.42004", fair="0.27")).checks[2].passed is False


def test_rule4_basis_threshold_and_resize():
    assert check_basis(BasisStat(r2=D("0.499"), beta_s=D(900), se=D(1)), D(900), TH).passed is False
    assert check_basis(BasisStat(r2=D("0.50"), beta_s=D(900), se=D(1)), D(900), TH).passed is True
    c = check_basis(BasisStat(r2=D("0.6"), beta_s=D(620), se=D(1)), D(900), TH)
    assert (metric_json(c)["h"], c.metric["resized"]) == ("0.6889", True)
    h = resolve_h(BasisStat(r2=D("0.6"), beta_s=D(620), se=D(1)), D(900), TH)
    assert target_contracts(D(900), h) == 620
    assert resolve_h(BasisStat(r2=D("0.6"), beta_s=D(1000), se=D(1)), D(900), TH) == 1
    assert resolve_h(BasisStat(r2=D("0.49"), beta_s=D(900), se=D(1)), D(900), TH) is None


def test_rule4_home_win_needs_no_basis_but_rain_does():
    win = BAR | {"settlement_var": "home_win"}
    assert run(exposure=win, basis=None).checks[3].metric["skipped"] == "no_basis_needed"
    with pytest.raises(ValueError):
        run(basis=None)


@pytest.mark.parametrize("cost,passed,ratio", [("315.00", True, "0.35"), ("315.01", False, "0.35"), ("328.20", False, "0.36")])
def test_rule5_too_expensive_threshold(cost, passed, ratio):
    c = check_too_expensive(D(cost), D("-900"), TH)
    assert (c.passed, metric_json(c)["ratio"]) == (passed, ratio)


@pytest.mark.parametrize("premium,status", [("250.00", "proposed"), ("250.01", "pending_approval")])
def test_rule6_over_budget_waits_for_owner(premium, status):
    assert run(sizing(premium=premium)).status == status


def test_all_six_logged_after_failures():
    d = run(sizing(avg="0.62", fair="0.27", expected_cost="328.20"))
    assert [c.code for c in d.checks] == CODES
    assert all(c.passed is not None and c.metric for c in d.checks)
    assert (d.status, d.reasons) == ("declined", ["overpriced", "too_expensive"])


def test_status_precedence():
    d = run(sizing(expected_cost="400.00", premium="300.00"))
    assert d.status == "declined" and d.checks[5].passed is False
    assert d.reasons == ["too_expensive"]  # models.Decision: declines only, budget is a pause
    d = run(sizing(premium="300.00"))
    assert (d.status, d.reasons) == ("pending_approval", ["over_budget"])
    assert (run().status, run().reasons) == ("proposed", [])


def test_no_fill_declines_without_inventing_a_price():
    d = run(sizing(n_filled=0))
    assert d.status == "declined" and d.reasons == ["illiquid"]
    assert d.checks[2].metric == d.checks[4].metric == {"skipped": "no_fill"}


def test_threshold_flip():
    s = sizing(expected_cost="328.20")
    assert run(s).status == "declined"
    assert run(s, th=replace(TH, cost_ratio_max=D("0.40"))).status == "proposed"
