"""Builds backend/fixtures/examples/*.json and businesses/*.json, validating each through models.

Run from backend/: .venv/bin/python scripts/gen_examples.py
"""

import copy
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from pydantic import TypeAdapter  # noqa: E402

from app import models as m  # noqa: E402

EX = BACKEND / "fixtures" / "examples"
BIZ = BACKEND / "fixtures" / "businesses"
WEEK = "2026-10-26"
RUN_TS = "2026-10-24T15:00:00Z"


def write(path: Path, model, data):
    if isinstance(data, list):
        objs = TypeAdapter(list[model]).validate_python(data)
        out = [o.model_dump(mode="json") for o in objs]
    else:
        out = model.model_validate(data).model_dump(mode="json")
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")


def budget(spent="0.00", pending="0.00", remaining="250.00"):
    return {"budget": "250.00", "spent": spent, "remaining": remaining, "pending": pending, "week_start": WEEK}


# --- businesses ---------------------------------------------------------------
taxi = {
    "id": "taxi", "name": "Midtown taxi fleet", "kind": "taxi",
    "data_label": "real", "estimated": False,
    "revenue_source": "NYC TLC yellow-taxi metered fares, pickups in the Penn Station/Madison Sq West zone",
    "zone_id": 186,  # placeholder until the data chunk confirms (C2 check)
    "avg_check_usd": None, "avg_check_label": None,
    "budget": budget(),
}
restaurant = {
    "id": "restaurant", "name": "Bar across from MSG", "kind": "restaurant",
    "data_label": "estimated", "estimated": True,
    "revenue_source": "Advan daily visits x average check (dollars estimated)",
    "zone_id": None,
    "avg_check_usd": "35.00", "avg_check_label": "assumed",  # C4 default until a menu price is found
    "budget": budget(),
}

# --- exposures ----------------------------------------------------------------
exp_taxi_rain = {
    "id": "exp_rain", "business_id": "taxi", "event": "rain",
    "effect_usd": "1240.00", "ci90": ["880.00", "1600.00"], "se": "219.00", "p_value": 0.001,
    "n_events_train": 112, "direction": "positive", "hedge_side": "no",
    "settlement_var": "rain", "hedgeable": True, "reasons": [],
    "strike": None, "beta_settlement": "1265.00",
}
exp_taxi_hot = {
    "id": "exp_hot", "business_id": "taxi", "event": "hot",
    "effect_usd": "-210.00", "ci90": ["-318.00", "-102.00"], "se": "65.65", "p_value": 0.0014,
    "n_events_train": 58, "direction": "negative", "hedge_side": "yes",
    "settlement_var": "hot", "hedgeable": True, "reasons": [],
    "strike": 65.0, "beta_settlement": "-180.00",
}
exp_taxi_home_win = {
    "id": "exp_home_win", "business_id": "taxi", "event": "home_win",
    "effect_usd": "95.00", "ci90": ["-60.00", "250.00"], "se": "94.22", "p_value": 0.31,
    "n_events_train": 27, "direction": "positive", "hedge_side": "no",
    "settlement_var": "home_win", "hedgeable": False, "reasons": ["below_size", "not_significant"],
    "strike": None, "beta_settlement": None,
}

model_check = {
    "planted_usd": "500.00", "frac": 0.15, "n_seeds": 50,
    "example": {"seed": 7, "recovered": "512.40", "ci90": ["371.80", "653.00"], "contains_truth": True},
    "coverage": 0.9, "mean_recovered": "497.85", "target": 0.9,
}

basis_stat = {"r2": "0.84", "beta_s": "-180.00", "se": "61.30"}


def payoff(event_rev, event_pay, noevent_rev, noevent_pay, premium):
    from decimal import Decimal as D

    rows = []
    for outcome, rev, pay in (("event", event_rev, event_pay), ("no_event", noevent_rev, noevent_pay)):
        net = D(rev) + D(pay) - D(premium)
        rows.append({"outcome": outcome, "revenue_vs_base": rev, "contract_payout": pay,
                     "premium": f"-{premium}", "net_vs_base": str(net)})
    return rows


def hedge_base(**kw):
    base = {
        "market_url": None, "match_reason": None, "fee_unverified": False, "alternative": None,
        "agent": "claude", "ledger_entry_ids": [], "created_at": RUN_TS,
        "decided_by": None, "decided_at": None, "week_of": WEEK, "partial": False, "resized": False,
    }
    base.update(kw)
    return base


# 1. taxi hot: proposed, partial fill and resized h (rule 4)
dec_hot = {
    "id": "dec_01", "status": "proposed",
    "checks": [
        {"code": "no_market", "passed": True, "metric": {"n_candidates": 4}},
        {"code": "illiquid", "passed": True, "metric": {"n_target": 180, "n_filled": 150, "fill_ratio": "0.8333", "partial": True}},
        {"code": "overpriced", "passed": True, "metric": {"avg_price": "0.4260", "fair": "0.38", "overpay": "0.0460"}},
        {"code": "basis_too_loose", "passed": True, "metric": {"r2": "0.84", "beta_s": "-180.00", "beta": "-210.00", "h": "0.8571", "resized": True}},
        {"code": "too_expensive", "passed": True, "metric": {"expected_cost": "9.47", "swing": "210.00", "ratio": "0.0451"}},
        {"code": "over_budget", "passed": True, "metric": {"premium": "66.47", "remaining": "250.00"}},
    ],
    "reasons": [],
    "summary": "Proposed: 150 YES contracts on NYC topping 65°F on Oct 28 for $66.47. The book filled 150 of the 180 wanted, and the Central Park reading tracks your zone well enough to size at 0.8571 of the exposure.",
}
hedge_hot = hedge_base(
    id="hdg_01", business_id="taxi", exposure_id="exp_hot", status="proposed",
    ticker="KXHIGHNY-26OCT28-T65", market_title="Will the high temp in NYC be above 65°F on Oct 28, 2026?",
    market_url="https://kalshi.com/markets/kxhighny", close_time="2026-10-29T04:59:00Z", side="yes",
    match_reason="Only open NYC high-temperature market for Oct 28 at the exposure's 65°F strike.",
    h="0.8571", n_target=180, n_filled=150, n_unfilled=30, partial=True, resized=True,
    fills=[{"price": "0.42", "count": 120}, {"price": "0.45", "count": 30}],
    avg_price="0.4260", cost="63.90", fee="2.57", premium="66.47", fair="0.38", expected_cost="9.47",
    payoff=payoff("-210.00", "150.00", "0.00", "0.00", "66.47"),
    headline={"unhedged_swing": "210.00", "hedged_swing": "60.00", "cost": "66.47"},
    decision=dec_hot,
)

# 2. taxi rain: over budget -> pending_approval, with within-budget alternative
dec_rain_taxi = {
    "id": "dec_02", "status": "pending_approval",
    "checks": [
        {"code": "no_market", "passed": True, "metric": {"n_candidates": 2}},
        {"code": "illiquid", "passed": True, "metric": {"n_target": 1240, "n_filled": 1240, "fill_ratio": "1", "partial": False}},
        {"code": "overpriced", "passed": True, "metric": {"avg_price": "0.7471", "fair": "0.73", "overpay": "0.0171"}},
        {"code": "basis_too_loose", "passed": True, "metric": {"r2": "0.91", "beta_s": "1265.00", "beta": "1240.00", "h": "1", "resized": False}},
        {"code": "too_expensive", "passed": True, "metric": {"expected_cost": "37.60", "swing": "1240.00", "ratio": "0.0303"}},
        {"code": "over_budget", "passed": False, "metric": {"premium": "942.80", "remaining": "250.00"}},
    ],
    "reasons": ["over_budget"],
    "summary": "Needs your approval: full protection costs $942.80 against $250.00 left this week. A within-budget version buys 331 contracts for $249.40.",
}
hedge_rain_taxi = hedge_base(
    id="hdg_02", business_id="taxi", exposure_id="exp_rain", status="pending_approval",
    ticker="KXRAINNYC-26OCT28", market_title="Will it rain in NYC on Oct 28, 2026?",
    market_url="https://kalshi.com/markets/kxrainnyc", close_time="2026-10-29T04:59:00Z", side="no",
    match_reason="NYC daily rain market for Oct 28 settles on Central Park, the station nearest the zone.",
    h="1", n_target=1240, n_filled=1240, n_unfilled=0,
    fills=[{"price": "0.74", "count": 800}, {"price": "0.76", "count": 440}],
    avg_price="0.7471", cost="926.40", fee="16.40", premium="942.80", fair="0.73", expected_cost="37.60",
    payoff=payoff("1240.00", "0.00", "0.00", "1240.00", "942.80"),
    headline={"unhedged_swing": "1240.00", "hedged_swing": "0.00", "cost": "942.80"},
    decision=dec_rain_taxi,
    alternative={
        "h": "0.2669", "n_target": 331, "n_filled": 331, "avg_price": "0.74",
        "cost": "244.94", "fee": "4.46", "premium": "249.40",
        "payoff": payoff("1240.00", "0.00", "0.00", "331.00", "249.40"),
        "headline": {"unhedged_swing": "1240.00", "hedged_swing": "909.00", "cost": "249.40"},
    },
)

# 3. restaurant rain: declined (spec §8 snippet)
dec_rain_bar = {
    "id": "dec_03", "status": "declined",
    "checks": [
        {"code": "no_market", "passed": True, "metric": {"n_candidates": 2}},
        {"code": "illiquid", "passed": True, "metric": {"n_target": 900, "n_filled": 900, "fill_ratio": "1", "partial": False}},
        {"code": "overpriced", "passed": False, "metric": {"avg_price": "0.62", "fair": "0.27", "overpay": "0.35"}},
        {"code": "basis_too_loose", "passed": True, "metric": {"r2": "0.55", "beta_s": "-930.00", "beta": "-900.00", "h": "1", "resized": False}},
        {"code": "too_expensive", "passed": False, "metric": {"expected_cost": "329.85", "swing": "900.00", "ratio": "0.3665"}},
        {"code": "over_budget", "passed": False, "metric": {"premium": "572.85", "remaining": "250.00"}},
    ],
    "reasons": ["overpriced", "too_expensive"],
    "summary": "Declined: the rain contract costs 62¢ against a 27% historical rain rate, and the hedge would cost 37% of the swing it removes.",
}
hedge_rain_bar = hedge_base(
    id="hdg_03", business_id="restaurant", exposure_id="exp_rain", status="declined",
    ticker="KXRAINNYC-26OCT28", market_title="Will it rain in NYC on Oct 28, 2026?",
    market_url="https://kalshi.com/markets/kxrainnyc", close_time="2026-10-29T04:59:00Z", side="yes",
    match_reason="NYC daily rain market for Oct 28; settles on Central Park.",
    h="1", n_target=900, n_filled=900, n_unfilled=0,
    fills=[{"price": "0.62", "count": 900}],
    avg_price="0.62", cost="558.00", fee="14.85", premium="572.85", fair="0.27", expected_cost="329.85",
    payoff=payoff("-900.00", "900.00", "0.00", "0.00", "572.85"),
    headline={"unhedged_swing": "900.00", "hedged_swing": "0.00", "cost": "572.85"},
    decision=dec_rain_bar,
)

# 4. restaurant home_win: proposed, full fill, fallback agent
dec_win_bar = {
    "id": "dec_04", "status": "proposed",
    "checks": [
        {"code": "no_market", "passed": True, "metric": {"n_candidates": 1}},
        {"code": "illiquid", "passed": True, "metric": {"n_target": 420, "n_filled": 420, "fill_ratio": "1", "partial": False}},
        {"code": "overpriced", "passed": True, "metric": {"avg_price": "0.5057", "fair": "0.48", "overpay": "0.0257"}},
        {"code": "basis_too_loose", "passed": True, "metric": {"skipped": "no_basis_needed", "h": "1", "resized": False}},
        {"code": "too_expensive", "passed": True, "metric": {"expected_cost": "18.15", "swing": "420.00", "ratio": "0.0432"}},
        {"code": "over_budget", "passed": True, "metric": {"premium": "219.75", "remaining": "250.00"}},
    ],
    "reasons": [],
    "summary": "Proposed: buy 420 NO contracts for $219.75. Unhedged swing $420.00, hedged swing $0.00.",
}
hedge_win_bar = hedge_base(
    id="hdg_04", business_id="restaurant", exposure_id="exp_home_win", status="proposed",
    ticker="KXNBAGAME-26OCT28BOSNYK-NYK", market_title="Boston at New York: will the Knicks win on Oct 28, 2026?",
    market_url="https://kalshi.com/markets/kxnbagame", close_time="2026-10-29T03:00:00Z", side="no",
    match_reason="Most liquid candidate (fallback pick).",
    h="1", n_target=420, n_filled=420, n_unfilled=0,
    fills=[{"price": "0.50", "count": 300}, {"price": "0.52", "count": 120}],
    avg_price="0.5057", cost="212.40", fee="7.35", premium="219.75", fair="0.48", expected_cost="18.15",
    payoff=payoff("420.00", "0.00", "0.00", "420.00", "219.75"),
    headline={"unhedged_swing": "420.00", "hedged_swing": "0.00", "cost": "219.75"},
    decision=dec_win_bar, agent="fallback",
)

# --- books ----------------------------------------------------------------------
ledger_premium = {
    "id": "le_0005", "business_id": "taxi", "date": "2026-10-24", "kind": "premium",
    "narration": "Premium: KXHIGHNY-26OCT28-T65 YES x 150",
    "postings": [
        {"account": "Expenses:Hedging:Premiums", "amount": "63.90"},
        {"account": "Expenses:Hedging:Fees", "amount": "2.57"},
        {"account": "Assets:Kalshi:Cash", "amount": "-66.47"},
    ],
    "meta": {"hedge_id": "hdg_01", "ticker": "KXHIGHNY-26OCT28-T65", "decision_id": "dec_01", "approved_by": "owner"},
    "simulated": False,
}
recon = {
    "business_id": "taxi", "as_of": "2026-10-23", "simulated": True,
    "matches": [{"hedge_id": "hdg_s01", "ticker": "KXHIGHNY-26OCT14-T70", "expected": "45.00", "kalshi_ledger": "45.00", "bank": "45.00"}],
    "mismatches": [{
        "hedge_id": "hdg_s02", "ticker": "KXRAINNYC-26OCT16",
        "expected": "60.00", "kalshi_ledger": "60.00", "bank": "58.95", "difference": "-1.05",
        "source_pair": "kalshi_ledger_vs_bank",
        "explanation": "Bank deposit is $1.05 short of the Kalshi payout; equals the $1.05 fee recorded for hdg_s02.",
        "likely_cause": "fee_deducted_from_deposit", "action": "ask_owner",
        "question": "Did you authorize the $1.05 fee to be netted from this withdrawal?",
    }],
    "summary": {"n_matched": 1, "n_mismatched": 1, "total_difference": "-1.05"},
}
ledger_entries = [
    {"id": "le_0001", "business_id": "taxi", "date": "2026-10-12", "kind": "opening_deposit",
     "narration": "[SIMULATED] Opening deposit to Kalshi",
     "postings": [{"account": "Assets:Kalshi:Cash", "amount": "500.00"}, {"account": "Assets:Bank:Checking", "amount": "-500.00"}],
     "meta": None, "simulated": True},
    {"id": "le_0002", "business_id": "taxi", "date": "2026-10-15", "kind": "payout",
     "narration": "[SIMULATED] Payout: KXHIGHNY-26OCT14-T70 NO x 45",
     "postings": [{"account": "Assets:Kalshi:Cash", "amount": "45.00"}, {"account": "Income:Hedging:Payouts", "amount": "-45.00"}],
     "meta": {"hedge_id": "hdg_s01", "ticker": "KXHIGHNY-26OCT14-T70", "decision_id": "dec_s01", "approved_by": "owner"},
     "simulated": True},
    {"id": "le_0003", "business_id": "taxi", "date": "2026-10-17", "kind": "payout",
     "narration": "[SIMULATED] Payout: KXRAINNYC-26OCT16 NO x 60",
     "postings": [{"account": "Assets:Kalshi:Cash", "amount": "60.00"}, {"account": "Income:Hedging:Payouts", "amount": "-60.00"}],
     "meta": {"hedge_id": "hdg_s02", "ticker": "KXRAINNYC-26OCT16", "decision_id": "dec_s02", "approved_by": "owner"},
     "simulated": True},
    {"id": "le_0004", "business_id": "taxi", "date": "2026-10-20", "kind": "withdrawal",
     "narration": "[SIMULATED] Withdrawal to bank: hdg_s01, hdg_s02",
     "postings": [{"account": "Assets:Bank:Checking", "amount": "105.00"}, {"account": "Assets:Kalshi:Cash", "amount": "-105.00"}],
     "meta": None, "simulated": True},
    ledger_premium,
]

# --- log --------------------------------------------------------------------------
def checks_numbers(dec, **extra):
    nums = {}
    for c in dec["checks"]:
        for k, v in c["metric"].items():
            if not isinstance(v, bool) and k not in ("skipped",):
                nums[k] = v
    nums.update(extra)
    return nums


log_approval = {
    "log_id": "log_0001", "business_id": "taxi", "kind": "approval", "created_at": "2026-10-12T15:02:00Z",
    "actor": "owner", "agent": None, "hedge_id": "hdg_s02", "decision_id": "dec_s02", "run_id": None,
    "status": "approved", "checks": [], "reasons": [],
    "numbers": {"n_filled": 60, "premium": "29.85", "fee": "1.05"},
    "summary": "Owner approved hdg_s02: 60 NO contracts for $29.85.",
}
log_booking = {
    "log_id": "log_0002", "business_id": "taxi", "kind": "booking", "created_at": "2026-10-12T15:02:01Z",
    "actor": "system", "agent": None, "hedge_id": "hdg_s02", "decision_id": "dec_s02", "run_id": None,
    "status": "approved", "checks": [], "reasons": [],
    "numbers": {"premium": "28.80", "fee": "1.05", "total": "29.85"},
    "summary": "Booked $28.80 premium and $1.05 fee to Expenses:Hedging; Assets:Kalshi:Cash credited $29.85.",
}
log_recon = {
    "log_id": "log_0003", "business_id": "taxi", "kind": "reconciliation", "created_at": "2026-10-23T13:00:00Z",
    "actor": "system", "agent": None, "hedge_id": None, "decision_id": None, "run_id": None,
    "status": None, "checks": [], "reasons": [],
    "numbers": {"n_matched": 1, "n_mismatched": 1, "difference": "-1.05", "fee": "1.05"},
    "summary": "Reconciled 1 hedge cleanly; flagged 1 bank deposit $1.05 short, equal to the hdg_s02 fee. Asking the owner.",
}
log_proposal = {
    "log_id": "log_0004", "business_id": "taxi", "kind": "proposal", "created_at": "2026-10-24T15:00:10Z",
    "actor": "desk", "agent": "claude", "hedge_id": "hdg_01", "decision_id": "dec_01", "run_id": "run_0007",
    "status": "proposed", "checks": dec_hot["checks"], "reasons": [],
    "numbers": checks_numbers(dec_hot, n_filled=150, floor_strike="65", unhedged_swing="210.00", hedged_swing="60.00"),
    "summary": dec_hot["summary"],
}
log_pending = {
    "log_id": "log_0005", "business_id": "taxi", "kind": "proposal", "created_at": "2026-10-24T15:00:20Z",
    "actor": "desk", "agent": "claude", "hedge_id": "hdg_02", "decision_id": "dec_02", "run_id": "run_0007",
    "status": "pending_approval", "checks": dec_rain_taxi["checks"], "reasons": ["over_budget"],
    "numbers": checks_numbers(dec_rain_taxi, alt_n_filled=331, alt_premium="249.40"),
    "summary": dec_rain_taxi["summary"],
}
log_decline = {
    "log_id": "log_0006", "business_id": "restaurant", "kind": "decline", "created_at": "2026-10-24T15:05:10Z",
    "actor": "desk", "agent": "claude", "hedge_id": "hdg_03", "decision_id": "dec_03", "run_id": "run_0008",
    "status": "declined", "checks": dec_rain_bar["checks"], "reasons": ["overpriced", "too_expensive"],
    "numbers": checks_numbers(dec_rain_bar),
    "summary": dec_rain_bar["summary"],
}
log_fallback = {
    "log_id": "log_0007", "business_id": "restaurant", "kind": "proposal", "created_at": "2026-10-24T15:05:20Z",
    "actor": "desk", "agent": "fallback", "hedge_id": "hdg_04", "decision_id": "dec_04", "run_id": "run_0008",
    "status": "proposed", "checks": dec_win_bar["checks"], "reasons": [],
    "numbers": checks_numbers(dec_win_bar, unhedged_swing="420.00", hedged_swing="0.00"),
    "summary": dec_win_bar["summary"],
}
log_chat = {
    "log_id": "log_0008", "business_id": "restaurant", "kind": "chat", "created_at": "2026-10-24T15:12:00Z",
    "actor": "desk", "agent": "claude", "hedge_id": "hdg_03", "decision_id": "dec_03", "run_id": None,
    "status": None, "checks": [], "reasons": [],
    "numbers": {"avg_price": "0.62", "fair": "0.27", "overpay": "0.35"},
    "summary": "Q: Why no rain insurance this week? A: The contract costs 62¢ but it has rained on 27% of comparable days, so you'd overpay by 35¢ per contract.",
}

# --- backtest -----------------------------------------------------------------------
def backtest():
    import statistics
    from decimal import ROUND_HALF_EVEN, Decimal as D

    weeks = ["2025-10-06", "2025-10-13", "2025-10-20", "2025-10-27", "2025-11-03", "2025-11-10", "2025-11-17", "2025-11-24"]
    unhedged = ["41250.00", "38410.00", "44980.00", "35120.00", "42060.00", "39870.00", "43310.00", "36940.00"]
    premium = ["212.40", "198.75", "240.10", "185.30", "220.05", "205.60", "231.90", "190.45"]
    pnl = ["1820.00", "-198.75", "-1640.10", "3410.70", "-220.05", "540.40", "-1131.90", "2059.55"]
    hedged = [str(D(u) + D(p)) for u, p in zip(unhedged, pnl)]
    q = lambda x: D(x).quantize(D("0.01"), ROUND_HALF_EVEN)
    su = statistics.stdev([float(x) for x in unhedged])
    sh = statistics.stdev([float(x) for x in hedged])
    worst = min(range(len(weeks)), key=lambda i: D(unhedged[i]))
    return {
        "std_unhedged": str(q(su)), "std_hedged": str(q(sh)), "reduction_pct": round(100 * (1 - sh / su), 1),
        "worst_week_unhedged": {"week_start": weeks[worst], "income": unhedged[worst]},
        "worst_week_hedged": {"week_start": weeks[worst], "income": hedged[worst]},
        "total_premium": str(sum(D(p) for p in premium)), "n_hedges": 31, "n_declined": 9,
        "priced_real_pct": 64.5,
        "per_exposure": {
            "exp_rain": {"reduction_pct": 38.2, "total_premium": "1214.60", "ineffective": False},
            "exp_hot": {"reduction_pct": 4.1, "total_premium": "469.95", "ineffective": True},
        },
        "weekly": [{"week_start": w, "unhedged": u, "hedged": h, "premium": p} for w, u, h, p in zip(weeks, unhedged, hedged, premium)],
        "pricing_tier": "mixed", "estimated": False,
    }


def main():
    EX.mkdir(parents=True, exist_ok=True)
    BIZ.mkdir(parents=True, exist_ok=True)
    write(BIZ / "taxi.json", m.Business, taxi)
    write(BIZ / "restaurant.json", m.Business, restaurant)
    files = {
        "business_taxi.json": (m.Business, taxi),
        "business_restaurant.json": (m.Business, restaurant),
        "budget.json": (m.Budget, budget(spent="66.47", remaining="183.53")),
        "exposure.json": (m.Exposure, exp_taxi_rain),
        "exposure_dropped.json": (m.Exposure, exp_taxi_home_win),
        "basis_stat.json": (m.BasisStat, basis_stat),
        "model_check.json": (m.ModelCheck, model_check),
        "check.json": (m.Check, dec_rain_bar["checks"][2]),
        "decision.json": (m.Decision, dec_hot),
        "hedge_proposed.json": (m.Hedge, hedge_win_bar),
        "hedge_partial.json": (m.Hedge, hedge_hot),
        "hedge_pending.json": (m.Hedge, hedge_rain_taxi),
        "hedge_declined.json": (m.Hedge, hedge_rain_bar),
        "hedge_lite.json": (m.HedgeLite, hedge_rain_taxi["alternative"]),
        "week_seed.json": (m.Hedge, [hedge_win_bar, hedge_hot, hedge_rain_taxi, hedge_rain_bar]),
        "log_entry.json": (m.LogEntry, [log_proposal, log_approval, log_fallback]),
        "decisions_seed.json": (m.LogEntry, [log_approval, log_booking, log_recon, log_proposal, log_pending, log_decline, log_fallback, log_chat]),
        "backtest_result.json": (m.BacktestResult, backtest()),
        "ledger_entry.json": (m.LedgerEntry, ledger_premium),
        "reconciliation.json": (m.ReconResult, recon),
        "ledger_response.json": (m.LedgerResponse, {"entries": ledger_entries, "reconciliation": recon, "simulated": True}),
        "settings.json": (m.Settings, {
            "thresholds": {"min_size_usd": "150.00", "min_support": 10, "overpay_max": "0.15", "cost_ratio_max": "0.35",
                           "fill_decline": "0.5", "fill_full": "1.0", "max_slip": "0.05", "basis_r2_min": 0.5, "max_tool_calls": 12},
            "weekly_budget": "250.00"}),
        "analyze_request.json": (m.AnalyzeRequest, {"strike": 65.0}),
        "analyze_response.json": (m.AnalyzeResponse, {"exposures": [exp_taxi_rain, exp_taxi_hot], "dropped": [exp_taxi_home_win],
                                                      "model_check": model_check, "r2_holdout": 0.58}),
        "desk_run_request.json": (m.DeskRunRequest, {"week_of": WEEK}),
        "run_accepted.json": (m.RunAccepted, {"run_id": "run_0007", "status": "queued"}),
        "run_status.json": (m.RunStatus, {"run_id": "run_0007", "business_id": "taxi", "status": "done", "agent": "claude",
                                          "started_at": "2026-10-24T15:00:00Z", "finished_at": "2026-10-24T15:00:41Z", "error": None}),
        "approve_request.json": (m.ApproveRequest, {"actor": "owner", "note": "Fine, book it."}),
        "reject_request.json": (m.RejectRequest, {"actor": "owner", "reason": "Too much for one week."}),
        "chat_request.json": (m.ChatRequest, {"message": "Why didn't you buy rain insurance this week?"}),
        "chat_reply.json": (m.ChatReply, {
            "reply": "The rain contract costs 62¢ but it has rained on 27% of comparable days, so you'd overpay by 35¢ per contract.",
            "tool_calls": [{"name": "read_log", "input": {"business_id": "restaurant", "hedge_id": "hdg_03", "limit": 1},
                            "output": [{"log_id": "log_0006", "kind": "decline", "reasons": ["overpriced", "too_expensive"],
                                        "numbers": {"avg_price": "0.62", "fair": "0.27", "overpay": "0.35"}}]}]}),
        "health.json": (m.Health, {"status": "ok", "offline": True, "anthropic": "fallback"}),
        "error.json": (m.ErrorBody, {"error": {"code": "owner_only", "message": "Only the owner can approve or reject a hedge; send actor \"owner\".",
                                               "detail": {"actor": "desk"}}}),
    }
    for name, (model, data) in files.items():
        write(EX / name, model, copy.deepcopy(data))
    print(f"wrote {len(files)} examples")


main()
