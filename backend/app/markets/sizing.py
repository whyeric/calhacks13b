"""Hedge sizing (spec §7): target contracts, book walk, taker fee, premium, payoff.

Sizing never decides pass/fail; rules.py does. Exact Decimal only.
Invariant I1: contracts ≤ |β| / $1 and 0 < h ≤ 1.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any

from .kalshi import Level, Orderbook, Side, ask_levels
from .match import Candidate
from .shapes import Fill, Headline, Hedge, PayoffRow, dec, field

ZERO = Decimal("0")
ONE = Decimal("1")
CENT = Decimal("0.01")
TAKER_RATE = Decimal("0.07")
VERIFIED_FEE_TYPES = {"quadratic"}  # anything else is flagged until checked against Kalshi (C3-H3)


def money(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def ceil_to_cent(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_CEILING)


def target_contracts(effect_usd: Decimal, h: Decimal) -> int:
    """N* = min(ceil(h·|β|), floor(|β|)).

    h·|β| is rounded to the cent before the ceiling: an exact ratio such as
    620/900 carries a 28-digit tail that would otherwise ceil 620 up to 621.
    """
    h = dec(h)
    if not (ZERO < h <= ONE):
        raise ValueError(f"hedge ratio must be in (0, 1], got {h}")
    beta = abs(dec(effect_usd))
    want = int(money(h * beta).to_integral_value(rounding=ROUND_CEILING))
    return min(want, int(beta.to_integral_value(rounding=ROUND_FLOOR)))


def walk_book(levels: list[Level], n_target: int, max_slip: Decimal = Decimal("0.05")) -> Fill:
    """Take asks cheapest first while price − best_ask ≤ max_slip (exactly 5¢ is allowed)."""
    fills: list[Level] = []
    remaining = n_target
    stopped = "book_exhausted"
    best = levels[0].price if levels else None
    for lv in levels:
        if remaining == 0:
            break
        if lv.price - best > max_slip:
            stopped = "slippage"
            break
        take = min(lv.count, remaining)
        fills.append(Level(price=lv.price, count=take))
        remaining -= take
    if remaining == 0:
        stopped = "filled"
    n_filled = n_target - remaining
    cost = sum((lv.price * lv.count for lv in fills), ZERO)
    return Fill(
        fills=fills, n_filled=n_filled, n_unfilled=remaining,
        avg_price=cost / n_filled if n_filled else None, cost=cost,
        best_ask=best, stopped_reason=stopped,
    )


def _raw_fee(contracts: int, price: Decimal, multiplier: Decimal) -> Decimal:
    return TAKER_RATE * multiplier * contracts * price * (ONE - price)


def taker_fee(contracts: int, price: Decimal, multiplier: Decimal = ONE) -> Decimal:
    return ceil_to_cent(_raw_fee(contracts, dec(price), dec(multiplier)))


def order_fee(fills: list[Level], multiplier: Decimal = ONE) -> Decimal:
    """One order across several levels: sum the unrounded per-level fees, round up once (G3)."""
    return ceil_to_cent(sum((_raw_fee(lv.count, lv.price, dec(multiplier)) for lv in fills), ZERO))


def fair_for_side(p_hat: Decimal, side: Side) -> Decimal:
    """p̂ is the settlement flag's train frequency (R17); NO is fairly worth 1 − p̂."""
    return dec(p_hat) if side == "yes" else ONE - dec(p_hat)


def payoff_table(exposure: Any, side: Side, n: int, premium: Decimal) -> list[PayoffRow]:
    beta = dec(field(exposure, "effect_usd"))
    rows = []
    for outcome, revenue, pays in (("event", beta, side == "yes"), ("no_event", ZERO, side == "no")):
        payout = Decimal(n) if pays else ZERO
        rows.append(PayoffRow(
            outcome=outcome, revenue_vs_base=money(revenue), contract_payout=money(payout),
            premium=-money(premium), net_vs_base=money(revenue + payout - premium),
        ))
    return rows


def size_hedge(
    exposure: Any, candidate: Candidate, book: Orderbook, h: Decimal, p_hat: Decimal,
    series_fee: Any, max_slip: Decimal = Decimal("0.05"),
) -> Hedge:
    """Size a hedge on `exposure.hedge_side` and nothing else. Does not decide pass/fail."""
    side: Side = field(exposure, "hedge_side")
    beta = dec(field(exposure, "effect_usd"))
    h = dec(h)
    n_target = target_contracts(beta, h)
    fill = walk_book(ask_levels(book, side), n_target, max_slip)

    fee_type = field(series_fee, "fee_type")
    multiplier = dec(field(series_fee, "fee_multiplier"))
    fee = order_fee(fill.fills, multiplier)
    cost = money(fill.cost)
    premium = cost + fee
    fair = fair_for_side(p_hat, side)
    # fee + (avg − fair)·n, written without the rounded average.
    expected_cost = money(fee + fill.cost - fair * fill.n_filled)
    payoff = payoff_table(exposure, side, fill.n_filled, premium)

    return Hedge(
        business_id=field(exposure, "business_id"),
        exposure_id=field(exposure, "id"),
        ticker=candidate.ticker,
        side=side,
        h=h.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize(),
        resized=h < ONE,
        n_target=n_target,
        n_filled=fill.n_filled,
        n_unfilled=fill.n_unfilled,
        partial=0 < fill.n_filled < n_target,
        fills=fill.fills,
        avg_price=None if fill.avg_price is None else fill.avg_price.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        cost=cost,
        fee=fee,
        premium=premium,
        fair=fair,
        expected_cost=expected_cost,
        fee_unverified=fee_type not in VERIFIED_FEE_TYPES or multiplier != ONE,
        payoff=payoff,
        headline=Headline(
            unhedged_swing=money(abs(beta)),
            hedged_swing=abs(payoff[0].net_vs_base - payoff[1].net_vs_base),
            cost=premium,
        ),
    )


def no_market_hedge(exposure: Any) -> Hedge:
    """The card for an exposure with no candidate market: only `decision` gets filled."""
    return Hedge(
        business_id=field(exposure, "business_id"), exposure_id=field(exposure, "id"),
        ticker=None, side=field(exposure, "hedge_side"), h=None, n_target=None, n_filled=None,
        n_unfilled=None, fills=None, avg_price=None, cost=None, fee=None, premium=None,
        fair=None, expected_cost=None, payoff=None, headline=None,
    )
