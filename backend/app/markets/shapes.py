"""Internal shapes for sizing and rules. Contract shapes (Hedge, Decision, Check,
BasisStat, Level, PayoffRow, Headline) live in app/models.py."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from app.models import Headline, Level, PayoffRow, Side


class Fill(BaseModel):
    fills: list[Level]
    n_filled: int
    n_unfilled: int
    avg_price: Decimal | None  # exact cost / n; rounded only when it reaches a Hedge
    cost: Decimal
    best_ask: Decimal | None
    stopped_reason: Literal["filled", "slippage", "book_exhausted"]


class Sizing(BaseModel):
    """What `size_hedge` computes; `to_hedge` turns it plus a Decision into a contract Hedge."""

    ticker: str
    series_ticker: str
    market_title: str
    close_time: datetime
    side: Side
    h: Decimal  # exact; the Hedge shows it at 4 dp
    resized: bool
    n_target: int
    n_filled: int
    n_unfilled: int
    partial: bool
    fills: list[Level]
    avg_price: Decimal | None  # exact
    cost: Decimal
    fee: Decimal
    premium: Decimal
    p_hat: Decimal  # settlement-flag frequency on train (R17), an input
    fair: Decimal
    expected_cost: Decimal
    fee_unverified: bool
    payoff: list[PayoffRow]
    headline: Headline
    venue: Literal["kalshi", "polymarket"] = "kalshi"
    market_url: str | None = None  # None: the Kalshi series page
    fee_rate: Decimal | None = None  # None: Kalshi's 0.07 x multiplier


def field(obj: Any, name: str) -> Any:
    """Exposure/series may arrive as a pydantic model or as its JSON dict."""
    return obj[name] if isinstance(obj, dict) else getattr(obj, name)


def dec(x: Any) -> Decimal:
    """Money from a model (Decimal) or JSON (string). Floats are rejected."""
    if isinstance(x, (float, bool)):
        raise TypeError(f"expected Decimal or string, got {type(x).__name__}: {x!r}")
    return x if isinstance(x, Decimal) else Decimal(str(x))
