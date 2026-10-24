"""The six decline rules (spec §8). All six always run and are logged (I3, I5).

Thresholds come only from config.Thresholds (R19), never module constants.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

from ..config import Thresholds
from .match import Candidate
from .shapes import BasisStat, Check, Decision, Hedge, dec, field

ONE = Decimal("1")
NO_BASIS_NEEDED = {"home_win"}  # the business flag *is* the settlement flag


def _q(x: Decimal, places: str, rounding=ROUND_HALF_UP) -> str:
    return str(x.quantize(Decimal(places), rounding=rounding))


def _price(x: Decimal) -> str:
    """Up to 4 dp, at least 2: 0.42 -> "0.42", 0.432857 -> "0.4329"."""
    s = _q(x, "0.0001").rstrip("0")
    return s + "0" * max(0, 2 - len(s.split(".")[1]))


def _money(x: Decimal) -> str:
    return _q(x, "0.01")


def resolve_h(basis: BasisStat | None, effect_usd: Decimal, th: Thresholds) -> Decimal | None:
    """h = min(1, |β_S|/|β|), or None when the flags agree too little to hedge (rule 4).

    `basis=None` means no basis is needed (home_win); `evaluate` rejects None elsewhere.
    """
    if basis is None:
        return ONE
    if basis.r2 < th.basis_r2_min:
        return None
    return min(ONE, abs(basis.beta_s) / abs(dec(effect_usd)))


# ---- individual checks (pure; the backtest calls 3–5 directly, R3)


def check_no_market(candidates: list[Candidate]) -> Check:
    return Check(code="no_market", passed=bool(candidates), metric={"n_candidates": len(candidates)})


def check_illiquid(n_target: int, n_filled: int, th: Thresholds) -> Check:
    ratio = Decimal(n_filled) / Decimal(n_target)
    passed = ratio >= th.fill_decline
    return Check(code="illiquid", passed=passed, metric={
        "n_target": n_target, "n_filled": n_filled,
        # Rounded down so a failing 0.495 never displays as a passing "0.50".
        "fill_ratio": _q(ratio, "0.01", ROUND_DOWN),
        "partial": passed and n_filled < n_target,
    })


def check_overpriced(avg_price: Decimal, fair: Decimal, th: Thresholds) -> Check:
    overpay = avg_price - fair
    return Check(code="overpriced", passed=overpay <= th.overpay_max, metric={
        "avg_price": _price(avg_price), "fair": _price(fair), "overpay": _price(overpay),
    })


def check_basis(basis: BasisStat, effect_usd: Decimal, th: Thresholds) -> Check:
    h = resolve_h(basis, effect_usd, th)
    return Check(code="basis_too_loose", passed=h is not None, metric={
        "r2": _q(basis.r2, "0.01"), "beta_s": _money(basis.beta_s), "beta": _money(dec(effect_usd)),
        "h": None if h is None else _q(h, "0.0001"), "resized": h is not None and h < ONE,
    })


def check_too_expensive(expected_cost: Decimal, effect_usd: Decimal, th: Thresholds) -> Check:
    swing = abs(dec(effect_usd))
    ratio = expected_cost / swing
    return Check(code="too_expensive", passed=ratio <= th.cost_ratio_max, metric={
        "expected_cost": _money(expected_cost), "swing": _money(swing), "ratio": _q(ratio, "0.01"),
    })


def check_over_budget(premium: Decimal, remaining: Decimal) -> Check:
    return Check(code="over_budget", passed=premium <= remaining, metric={
        "premium": _money(premium), "remaining": _money(remaining),
    })


def _skip(code: str, why: str) -> Check:
    return Check(code=code, passed=None, metric={}, skipped=why)


# ---- composition


def evaluate(
    exposure: Any, candidates: list[Candidate], hedge: Hedge | None,
    basis: BasisStat | None, remaining_budget: Decimal, th: Thresholds,
) -> Decision:
    """Run checks 1–6 in table order, always. Size the hedge with resolve_h's h first (G5)."""
    var = field(exposure, "settlement_var")
    if basis is None and var not in NO_BASIS_NEEDED:
        raise ValueError(f"{var} exposure needs a BasisStat for rule 4")
    beta = dec(field(exposure, "effect_usd"))
    remaining = dec(remaining_budget)

    checks = [check_no_market(candidates)]
    if not candidates or hedge is None or hedge.ticker is None:
        checks += [_skip(c, "no_market") for c in ("illiquid", "overpriced", "basis_too_loose", "too_expensive")]
        checks.append(check_over_budget(Decimal("0"), remaining))
    else:
        filled = hedge.n_filled > 0
        checks.append(check_illiquid(hedge.n_target, hedge.n_filled, th))
        # Exact average from cost / n, not the 4-dp display value, so boundaries are exact.
        checks.append(check_overpriced(hedge.cost / hedge.n_filled, hedge.fair, th) if filled
                      else _skip("overpriced", "no_fill"))
        checks.append(check_basis(basis, beta, th) if var not in NO_BASIS_NEEDED else
                      Check(code="basis_too_loose", passed=True, metric={}, skipped="no_basis_needed"))
        checks.append(check_too_expensive(hedge.expected_cost, beta, th) if filled
                      else _skip("too_expensive", "no_fill"))
        checks.append(check_over_budget(hedge.premium, remaining))

    reasons = [c.code for c in checks if c.passed is False]
    if any(c.passed is False for c in checks[:5]):
        status = "declined"
    elif checks[5].passed is False:
        status = "pending_approval"
    else:
        status = "proposed"
    return Decision(status=status, checks=checks, reasons=reasons)


def with_decision(hedge: Hedge, decision: Decision) -> Hedge:
    """Attach the decision; partial mirrors the illiquid metric (R4). Full size is kept when pending."""
    illiquid = decision.checks[1].metric
    return hedge.model_copy(update={
        "decision": decision, "status": decision.status,
        "partial": bool(illiquid.get("partial", False)),
    })
