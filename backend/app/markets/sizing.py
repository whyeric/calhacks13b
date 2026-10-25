"""Hedge sizing (spec §7): target contracts, book walk, taker fee, premium, payoff.

Sizing never decides pass/fail; rules.py does. Exact Decimal only.
Invariant I1: contracts ≤ |β| / $1 and 0 < h ≤ 1.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any

from app.config import KALSHI_MARKET_URL
from app.models import Agent, Decision, Headline, Hedge, Level, PayoffRow, Side

from .kalshi import Orderbook, ask_levels
from .match import Candidate
from .shapes import Fill, Sizing, dec, field
from .summary import fallback_summary

ZERO = Decimal("0")
ONE = Decimal("1")
CENT = Decimal("0.01")
PLACES_4 = Decimal("0.0001")
TAKER_RATE = Decimal("0.07")
# Taker fee is 0.07·C·P·(1−P) for both. `quadratic_with_maker_fees` (NBA/NHL games) only adds a
# fee on resting orders, at a quarter of the taker rate (docs.kalshi.com changelog, 2026-08-22).
# The desk only ever takes, so its taker fee is the plain quadratic one.
# Polymarket's taker fee has the same shape with its own rate: rate·C·P·(1−P) (markets/polymarket.py).
VERIFIED_FEE_TYPES = {"quadratic", "quadratic_with_maker_fees", "polymarket_taker"}


def money(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def ceil_to_cent(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_CEILING)


def places4(x: Decimal) -> Decimal:
    """Prices and ratios reach the contract with at most 4 dp, trailing zeros dropped."""
    q = x.quantize(PLACES_4, rounding=ROUND_HALF_UP)
    return q.quantize(ONE) if q == q.to_integral_value() else q.normalize()


def target_contracts(effect_usd: Decimal, h: Decimal) -> int:
    """N* = min(ceil(h·|β|), floor(|β|)).

    h·|β| is rounded to the cent before the ceiling: an exact ratio such as
    999/4999 carries a 28-digit tail that would otherwise ceil 999 up to 1000.
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


def _raw_fee(contracts: int, price: Decimal, multiplier: Decimal, rate: Decimal = TAKER_RATE) -> Decimal:
    return rate * multiplier * contracts * price * (ONE - price)


def taker_fee(contracts: int, price: Decimal, multiplier: Decimal = ONE, rate: Decimal = TAKER_RATE) -> Decimal:
    return ceil_to_cent(_raw_fee(contracts, dec(price), dec(multiplier), dec(rate)))


def order_fee(fills: list[Level], multiplier: Decimal = ONE, rate: Decimal = TAKER_RATE) -> Decimal:
    """One order across several levels: sum the unrounded per-level fees, round up once (G3).
    Matches Kalshi's per-order fee accumulator for cent-precision accounts (docs: Fee Rounding).
    Polymarket passes its own `rate` (and rounds to 5 dp; rounding up to the cent overstates by <1¢)."""
    return ceil_to_cent(sum((_raw_fee(lv.count, lv.price, dec(multiplier), dec(rate)) for lv in fills), ZERO))


def _opt(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


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
) -> Sizing:
    """Size a hedge on `exposure.hedge_side` and nothing else. Does not decide pass/fail.

    `p_hat` is the settlement flag's frequency on train, passed in by the caller from the
    feature table (`features.event_frequency(df, "settle_rain")`); this module never assumes one.
    """
    side: Side = field(exposure, "hedge_side")
    beta = dec(field(exposure, "effect_usd"))
    h = dec(h)
    p_hat = dec(p_hat)
    n_target = target_contracts(beta, h)
    fill = walk_book(ask_levels(book, side), n_target, max_slip)

    fee_type = field(series_fee, "fee_type")
    multiplier = dec(field(series_fee, "fee_multiplier"))
    rate = _opt(series_fee, "fee_rate")
    fee = order_fee(fill.fills, multiplier, TAKER_RATE if rate is None else dec(rate))
    cost = money(fill.cost)
    premium = cost + fee
    fair = fair_for_side(p_hat, side)
    # fee + (avg − fair)·n, one-sided: a price under the historical rate is not a saving
    # (the market is pricing the forecast), so it never makes the hedge look cheaper than its fee.
    expected_cost = money(fee + max(ZERO, fill.cost - fair * fill.n_filled))
    payoff = payoff_table(exposure, side, fill.n_filled, premium)

    return Sizing(
        ticker=candidate.ticker, series_ticker=candidate.series_ticker, market_title=candidate.title,
        close_time=candidate.close_time, side=side, h=h, resized=h < ONE,
        n_target=n_target, n_filled=fill.n_filled, n_unfilled=fill.n_unfilled,
        partial=0 < fill.n_filled < n_target, fills=fill.fills, avg_price=fill.avg_price,
        cost=cost, fee=fee, premium=premium, p_hat=p_hat, fair=fair, expected_cost=expected_cost,
        fee_unverified=fee_type not in VERIFIED_FEE_TYPES or multiplier != ONE,
        payoff=payoff,
        headline=Headline(
            unhedged_swing=money(abs(beta)),
            hedged_swing=abs(payoff[0].net_vs_base - payoff[1].net_vs_base),
            cost=premium,
        ),
        venue=candidate.venue, market_url=candidate.market_url,
        fee_rate=None if rate is None else dec(rate),
    )


def to_hedge(
    exposure: Any, sizing: Sizing | None, decision: Decision, *,
    hedge_id: str, week_of: date, created_at: datetime, agent: Agent, match_reason: str | None = None,
) -> Hedge:
    """The contract Hedge. With no market (`sizing=None`) only `decision` carries information.

    A null `decision.summary` gets the deterministic fallback sentence (summary.py)."""
    hedge = _build_hedge(exposure, sizing, decision, hedge_id=hedge_id, week_of=week_of,
                         created_at=created_at, agent=agent, match_reason=match_reason)
    if hedge.decision.summary is None:
        text = fallback_summary(hedge)
        if text is not None:
            hedge = hedge.model_copy(update={"decision": hedge.decision.model_copy(update={"summary": text})})
    return hedge


def _build_hedge(
    exposure: Any, sizing: Sizing | None, decision: Decision, *,
    hedge_id: str, week_of: date, created_at: datetime, agent: Agent, match_reason: str | None,
) -> Hedge:
    base = dict(
        id=hedge_id, business_id=field(exposure, "business_id"), exposure_id=field(exposure, "id"),
        week_of=week_of, status=decision.status, side=field(exposure, "hedge_side"),
        match_reason=match_reason, decision=decision, alternative=None, agent=agent,
        ledger_entry_ids=[], created_at=created_at, decided_by=None, decided_at=None,
    )
    if sizing is None:
        return Hedge(
            **base, ticker=None, market_title=None, market_url=None, close_time=None, h=None,
            n_target=0, n_filled=0, n_unfilled=0, partial=False, resized=False, fills=None,
            avg_price=None, cost=None, fee=None, premium=None, fair=None, expected_cost=None,
            fee_unverified=False, payoff=None, headline=None,
        )
    illiquid = decision.checks[1].metric
    return Hedge(
        **base, ticker=sizing.ticker, market_title=sizing.market_title,
        market_url=sizing.market_url or KALSHI_MARKET_URL.format(series=sizing.series_ticker.lower()),
        venue=sizing.venue, fee_rate=None if sizing.fee_rate is None else places4(sizing.fee_rate),
        close_time=sizing.close_time, h=places4(sizing.h), n_target=sizing.n_target,
        n_filled=sizing.n_filled, n_unfilled=sizing.n_unfilled,
        partial=bool(illiquid.get("partial", False)), resized=sizing.resized, fills=sizing.fills,
        avg_price=None if sizing.avg_price is None else places4(sizing.avg_price),
        cost=sizing.cost, fee=sizing.fee, premium=sizing.premium, fair=places4(sizing.fair),
        expected_cost=sizing.expected_cost, fee_unverified=sizing.fee_unverified,
        payoff=sizing.payoff, headline=sizing.headline,
    )
