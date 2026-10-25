"""The scripted "Send to the desk" card for an uploaded business, sized from its research report.

The card stays scripted (fixed market, fixed 33¢ price, labeled in the UI), but its size follows
the live report so it never buys more than the measured exposure (I1):
contracts = floor(|train rain effect| / $1), premium = contracts x price + the Kalshi taker fee.
"""

from decimal import ROUND_FLOOR, Decimal

from app import clock
from app.markets.sizing import taker_fee
from app.models import Budget, DemoHedgeBudgets, DemoHedgePlan, PayoffRow, ResearchHypothesis

CARD_PRICE = Decimal("0.33")  # the scripted card's price (frontend DEMO_HEDGE)
DEMO_BUDGET = Decimal("1000.00")  # the demo business's weekly budget (frontend DEMO_BUDGETS)
CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def plan(rows: list[ResearchHypothesis]) -> DemoHedgePlan | None:
    row = next((h for h in rows if h.id == "rain" and h.sendable and h.train is not None), None)
    if row is None:
        return None
    effect = row.train.effect_usd
    contracts = int((-effect).to_integral_value(rounding=ROUND_FLOOR))
    if contracts < 1:
        return None
    fee = taker_fee(contracts, CARD_PRICE)
    premium = (contracts * CARD_PRICE + fee).quantize(CENT)
    payout = Decimal(contracts).quantize(CENT)
    p_event = (Decimal(row.train.n_event_days) / Decimal(row.train.n_days)).quantize(Decimal("0.0001"))
    week = clock.desk_week()
    return DemoHedgePlan(
        hypothesis_id=row.id, contracts=contracts, price=CARD_PRICE, fee=fee, premium=premium,
        payout=payout, p_event=p_event, expected_cost=(premium - payout * p_event).quantize(CENT),
        payoff=[
            PayoffRow(outcome="event", revenue_vs_base=effect, contract_payout=payout, premium=-premium,
                      net_vs_base=effect + payout - premium),
            PayoffRow(outcome="no_event", revenue_vs_base=ZERO, contract_payout=ZERO, premium=-premium,
                      net_vs_base=-premium),
        ],
        budgets=DemoHedgeBudgets(
            open=Budget(budget=DEMO_BUDGET, spent=ZERO, pending=ZERO, remaining=DEMO_BUDGET, week_start=week),
            pending=Budget(budget=DEMO_BUDGET, spent=ZERO, pending=premium, remaining=DEMO_BUDGET - premium,
                           week_start=week),
            approved=Budget(budget=DEMO_BUDGET, spent=premium, pending=ZERO, remaining=DEMO_BUDGET - premium,
                            week_start=week),
        ),
    )
