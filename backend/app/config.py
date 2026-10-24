"""App configuration. Owned by C6 (API & contracts); C3 added Thresholds only (R19)."""

import os
from dataclasses import dataclass, field
from decimal import Decimal


def _weekly_budget() -> Decimal:
    return Decimal(os.environ.get("WEEKLY_BUDGET_DEFAULT", "250"))


@dataclass(frozen=True)
class Thresholds:
    """Decline-rule thresholds (spec §8). Read by markets/rules.py, the backtest, and settings."""

    fill_decline: Decimal = Decimal("0.5")
    max_slip: Decimal = Decimal("0.05")
    overpay_max: Decimal = Decimal("0.15")
    basis_r2_min: Decimal = Decimal("0.5")
    cost_ratio_max: Decimal = Decimal("0.35")
    weekly_budget: Decimal = field(default_factory=_weekly_budget)
