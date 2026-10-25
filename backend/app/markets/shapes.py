"""Output shapes for sizing and rules (#32 / #43 interface).

Interim home until C6's app/models.py lands; then these move there unchanged.
Decimals serialize as strings.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from .kalshi import Level

CheckCode = Literal["no_market", "illiquid", "overpriced", "basis_too_loose", "too_expensive", "over_budget"]
DecisionStatus = Literal["proposed", "declined", "pending_approval"]
HedgeStatus = Literal["proposed", "pending_approval", "approved", "settled", "declined", "rejected", "expired_unapproved"]


class BasisStat(BaseModel):
    """From C2 (R2): agreement of the business's flag with the contract's settlement flag on train."""
    r2: Decimal
    beta_s: Decimal
    se: Decimal


class Check(BaseModel):
    code: CheckCode
    passed: bool | None  # None = not computable (see `skipped`)
    metric: dict[str, Any]
    skipped: str | None = None


class Decision(BaseModel):
    status: DecisionStatus
    checks: list[Check]
    reasons: list[CheckCode]
    summary: str | None = None  # written by the agent (C4); every number must appear in checks


class Fill(BaseModel):
    fills: list[Level]
    n_filled: int
    n_unfilled: int
    avg_price: Decimal | None
    cost: Decimal
    best_ask: Decimal | None
    stopped_reason: Literal["filled", "slippage", "book_exhausted"]


class PayoffRow(BaseModel):
    outcome: Literal["event", "no_event"]
    revenue_vs_base: Decimal
    contract_payout: Decimal
    premium: Decimal  # negative
    net_vs_base: Decimal


class Headline(BaseModel):
    unhedged_swing: Decimal
    hedged_swing: Decimal
    cost: Decimal  # premium (R16)


class Hedge(BaseModel):
    id: str | None = None
    business_id: str
    exposure_id: str
    week_of: str | None = None
    ticker: str | None
    side: Literal["yes", "no"]
    match_reason: str | None = None
    h: Decimal | None
    resized: bool = False
    n_target: int | None
    n_filled: int | None
    n_unfilled: int | None
    partial: bool = False
    fills: list[Level] | None
    avg_price: Decimal | None
    cost: Decimal | None
    fee: Decimal | None
    premium: Decimal | None
    fair: Decimal | None
    expected_cost: Decimal | None
    fee_unverified: bool = False
    payoff: list[PayoffRow] | None
    headline: Headline | None
    decision: Decision | None = None
    status: HedgeStatus | None = None
    agent: Literal["claude", "fallback"] | None = None


def field(obj: Any, name: str) -> Any:
    """Exposure/series may arrive as a pydantic model or as its JSON dict."""
    return obj[name] if isinstance(obj, dict) else getattr(obj, name)


def dec(x: Any) -> Decimal:
    """Money from a model (Decimal) or JSON (string). Floats are rejected."""
    if isinstance(x, (float, bool)):
        raise TypeError(f"expected Decimal or string, got {type(x).__name__}: {x!r}")
    return x if isinstance(x, Decimal) else Decimal(str(x))
