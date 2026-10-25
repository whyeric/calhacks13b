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
from app.markets.shapes import BasisStat, Hedge
from app.markets.sizing import no_market_hedge, target_contracts

TH = Thresholds(weekly_budget=D(250))
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


def hedge(n_target=900, n_filled=900, avg="0.30", fair="0.27", expected_cost="50.00", premium="100.00"):
    return Hedge(
        business_id="restaurant", exposure_id="exp_rain", ticker="T1", side="yes", h=D(1),
        n_target=n_target, n_filled=n_filled, n_unfilled=n_target - n_filled, fills=[],
        # avg_price at 4 dp, as size_hedge stores it; cost stays exact.
        avg_price=D(avg).quantize(D("0.0001")), cost=D(avg) * n_filled, fee=D("1"), premium=D(premium), fair=D(fair),
        expected_cost=D(expected_cost), payoff=[], headline=None,
    )


def run(h=None, basis=GOOD_BASIS, remaining="250.00", th=TH, exposure=BAR, cands=CANDS):
    return evaluate(exposure, cands, hedge() if h is None else h, basis, D(remaining), th)


def test_rule1_no_market_declines_with_everything_logged():
    d = evaluate(BAR, [], no_market_hedge(BAR), GOOD_BASIS, D("250"), TH)
    assert (d.status, d.reasons) == ("declined", ["no_market"])
    assert [c.code for c in d.checks] == CODES
    assert all(c.passed is None and c.skipped == "no_market" for c in d.checks[1:5])
    assert d.checks[5].passed is True and d.checks[5].metric["premium"] == "0.00"
    assert no_market_hedge(BAR).ticker is None


@pytest.mark.parametrize("filled,passed,partial,status", [
    (49, False, False, "declined"), (50, True, True, "proposed"), (100, True, False, "proposed")])
def test_rule2_illiquid_threshold(filled, passed, partial, status):
    c = check_illiquid(100, filled, TH)
    assert (c.passed, c.metric["partial"]) == (passed, partial)
    d = run(hedge(n_target=100, n_filled=filled))
    assert d.status == status


def test_rule2_fill_ratio_display_never_rounds_up_into_a_pass():
    assert check_illiquid(200, 99, TH).metric["fill_ratio"] == "0.49"


@pytest.mark.parametrize("fair,passed,overpay", [("0.27", True, "0.15"), ("0.269", False, "0.151"), ("0.30", True, "0.12")])
def test_rule3_overpriced_is_strictly_greater(fair, passed, overpay):
    c = check_overpriced(D("0.42"), D(fair), TH)
    assert c.passed is passed
    assert c.metric == {"avg_price": "0.42", "fair": c.metric["fair"], "overpay": overpay}
    assert all(isinstance(v, str) for v in c.metric.values())


def test_rule3_uses_exact_average_not_display_rounding():
    # True avg 0.42004 is stored as 0.4200 (overpay exactly 0.15, a pass); the rule must see 0.15004.
    h = hedge(n_target=20000, n_filled=20000, avg="0.42004", fair="0.27")
    assert run(h).checks[2].passed is False


def test_rule4_basis_threshold_and_resize():
    assert check_basis(BasisStat(r2=D("0.499"), beta_s=D(900), se=D(1)), D(900), TH).passed is False
    assert check_basis(BasisStat(r2=D("0.50"), beta_s=D(900), se=D(1)), D(900), TH).passed is True
    c = check_basis(BasisStat(r2=D("0.6"), beta_s=D(620), se=D(1)), D(900), TH)
    assert (c.metric["h"], c.metric["resized"]) == ("0.6889", True)
    h = resolve_h(BasisStat(r2=D("0.6"), beta_s=D(620), se=D(1)), D(900), TH)
    assert target_contracts(D(900), h) == 620
    assert resolve_h(BasisStat(r2=D("0.6"), beta_s=D(1000), se=D(1)), D(900), TH) == 1
    assert resolve_h(BasisStat(r2=D("0.49"), beta_s=D(900), se=D(1)), D(900), TH) is None


def test_rule4_home_win_needs_no_basis_but_rain_does():
    win = BAR | {"settlement_var": "home_win"}
    assert run(exposure=win, basis=None).checks[3].skipped == "no_basis_needed"
    with pytest.raises(ValueError):
        run(basis=None)


@pytest.mark.parametrize("cost,passed,ratio", [("315.00", True, "0.35"), ("315.01", False, "0.35"), ("328.20", False, "0.36")])
def test_rule5_too_expensive_threshold(cost, passed, ratio):
    c = check_too_expensive(D(cost), D("-900"), TH)
    assert (c.passed, c.metric["ratio"]) == (passed, ratio)


@pytest.mark.parametrize("premium,status", [("250.00", "proposed"), ("250.01", "pending_approval")])
def test_rule6_over_budget_waits_for_owner(premium, status):
    d = run(hedge(premium=premium))
    assert d.status == status


def test_all_six_logged_after_failures():
    d = run(hedge(avg="0.62", fair="0.27", expected_cost="328.20"))
    assert [c.code for c in d.checks] == CODES
    assert all(c.passed is not None and c.metric for c in d.checks)
    assert (d.status, d.reasons) == ("declined", ["overpriced", "too_expensive"])


def test_status_precedence():
    d = run(hedge(expected_cost="400.00", premium="300.00"))
    assert (d.status, d.reasons) == ("declined", ["too_expensive", "over_budget"])
    assert run(hedge(premium="300.00")).status == "pending_approval"
    assert (run().status, run().reasons) == ("proposed", [])


def test_no_fill_declines_without_inventing_a_price():
    d = run(hedge(n_filled=0, avg="0"))
    assert d.status == "declined" and d.reasons == ["illiquid"]
    assert d.checks[2].skipped == d.checks[4].skipped == "no_fill"


def test_threshold_flip():
    h = hedge(expected_cost="328.20")
    assert run(h).status == "declined"
    assert run(h, th=replace(TH, cost_ratio_max=D("0.40"))).status == "proposed"
