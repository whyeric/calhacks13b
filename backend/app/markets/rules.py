"""The decline rules (spec §8) plus `unstable`. All always run and are logged (I3, I5).

`unstable` (research hedgesim) declines an exposure whose recent-window refit
(`Exposure.stability`) has the other sign or a 90% CI that includes 0. It sits after
too_expensive in table order and runs whether or not a market was found; with no recent
window it is skipped, and `Thresholds.decline_unstable=False` records it without declining.

Thresholds come only from config (R19), never module constants.
"""

from __future__ import annotations

import hashlib
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

from app.config import FORECAST_NOTE_GAP, Thresholds
from app.models import BasisStat, Check, Decision, Side

from .match import Candidate
from .shapes import Sizing, dec, field

ZERO = Decimal("0")
ONE = Decimal("1")
NO_BASIS_NEEDED = {"home_win"}  # the business flag *is* the settlement flag
DECLINE_CODES = ("no_market", "illiquid", "overpriced", "basis_too_loose", "too_expensive", "unstable")
MARKET_CODES = DECLINE_CODES[:5]  # the checks that need a market (skipped with no_market)


def _q(x: Decimal, places: str, rounding=ROUND_HALF_UP) -> str:
    return str(x.quantize(Decimal(places), rounding=rounding))


def _price(x: Decimal) -> str:
    """Up to 4 dp, at least 2: 0.42 -> "0.42", 0.432857 -> "0.4329"."""
    s = _q(x, "0.0001").rstrip("0")
    return s + "0" * max(0, 2 - len(s.split(".")[1]))


def _money(x: Decimal) -> str:
    return _q(x, "0.01")


def _r2_min(th: Thresholds) -> Decimal:
    return Decimal(str(th.basis_r2_min))  # config keeps r2 as a stat (float); compare exactly


def resolve_h(basis: BasisStat | None, effect_usd: Decimal, th: Thresholds) -> Decimal | None:
    """h = min(1, |β_S|/|β|), or None when the flags agree too little to hedge (rule 4).

    `basis=None` means no basis is needed (home_win); `evaluate` rejects None elsewhere.
    """
    if basis is None:
        return ONE
    if basis.r2 < _r2_min(th):
        return None
    return min(ONE, abs(basis.beta_s) / abs(dec(effect_usd)))


# ---- individual checks (pure; the backtest calls 3–5 directly, R3)


def check_no_market(candidates: list[Candidate], venue_note: str | None = None) -> Check:
    """Counts per venue, so a no_market decline says both Kalshi and Polymarket were scanned."""
    metric: dict[str, Any] = {"n_candidates": len(candidates)}
    venues = {getattr(c, "venue", "kalshi") for c in candidates}
    if "polymarket" in venues or venue_note is not None:
        metric["n_kalshi"] = sum(getattr(c, "venue", "kalshi") == "kalshi" for c in candidates)
        metric["n_polymarket"] = sum(getattr(c, "venue", "kalshi") == "polymarket" for c in candidates)
    if venue_note:
        metric["venue_note"] = venue_note
    return Check(code="no_market", passed=bool(candidates), metric=metric)


def check_illiquid(n_target: int, n_filled: int, th: Thresholds) -> Check:
    ratio = Decimal(n_filled) / Decimal(n_target)
    # Nothing filled is never a hedge, whatever fill_decline says (a 0-contract, $0 proposal).
    passed = n_filled > 0 and ratio >= th.fill_decline
    return Check(code="illiquid", passed=passed, metric={
        "n_target": n_target, "n_filled": n_filled,
        # Rounded down so a failing 0.495 never displays as a passing "0.50".
        "fill_ratio": _q(ratio, "0.01", ROUND_DOWN),
        "partial": passed and ratio < th.fill_full,
    })


def check_overpriced(avg_price: Decimal, fair: Decimal, th: Thresholds, *, side: Side) -> Check:
    """One-sided: declines only when we'd pay more than the historical rate allows.

    A price below `fair` is not reported as a bargain (`overpay` floors at 0): it usually means
    the market is pricing today's forecast, which the historical rate can't see. When the two
    differ by more than FORECAST_NOTE_GAP, the receipt says so.
    """
    gap = avg_price - fair
    metric = {"avg_price": _price(avg_price), "fair": _price(fair), "overpay": _price(max(ZERO, gap))}
    if abs(gap) > FORECAST_NOTE_GAP:
        rate = fair if side == "yes" else ONE - fair  # the event's historical frequency, p̂
        metric["note"] = (
            "Market price reflects the current forecast; "
            f"historical rate is {_q(rate * 100, '1')}%."
        )
    return Check(code="overpriced", passed=gap <= th.overpay_max, metric=metric)


def check_basis(basis: BasisStat, effect_usd: Decimal, th: Thresholds) -> Check:
    h = resolve_h(basis, effect_usd, th)
    return Check(code="basis_too_loose", passed=h is not None, metric={
        "r2": _price(basis.r2), "beta_s": _money(basis.beta_s), "beta": _money(dec(effect_usd)),
        "h": None if h is None else _price(h), "resized": h is not None and h < ONE,
    })


def check_too_expensive(expected_cost: Decimal, effect_usd: Decimal, th: Thresholds) -> Check:
    swing = abs(dec(effect_usd))
    ratio = expected_cost / swing
    return Check(code="too_expensive", passed=ratio <= th.cost_ratio_max, metric={
        "expected_cost": _money(expected_cost), "swing": _money(swing), "ratio": _q(ratio, "0.01"),
    })


def check_unstable(exposure: Any, th: Thresholds) -> Check:
    """Fails when the recent-window effect flipped sign or its 90% CI includes 0 (and the rule is on)."""
    stab = exposure.get("stability") if isinstance(exposure, dict) else getattr(exposure, "stability", None)
    if stab is None:
        return _skip("unstable", "no_recent_window")
    lo, hi = (dec(x) for x in field(stab, "ci90"))
    stable = bool(field(stab, "stable"))
    return Check(code="unstable", passed=stable or not th.decline_unstable, metric={
        "effect_last_year_usd": _money(dec(field(exposure, "effect_usd"))),
        "effect_recent_usd": _money(dec(field(stab, "effect_usd"))),
        "recent_ci_low": _money(lo), "recent_ci_high": _money(hi),
        "recent_n_events": int(field(stab, "n_events")),
        "recent_start": str(field(stab, "start")), "recent_end": str(field(stab, "end")),
        "sign_flipped": not bool(field(stab, "same_sign")), "stable": stable,
        "enforced": th.decline_unstable,
    })


def check_over_budget(premium: Decimal, remaining: Decimal) -> Check:
    return Check(code="over_budget", passed=premium <= remaining, metric={
        "premium": _money(premium), "remaining": _money(remaining),
    })


def _hedgeable(exposure: Any) -> bool:
    # Contract Exposures always carry `hedgeable`; bare dicts used in unit tests may omit it.
    return exposure.get("hedgeable", True) if isinstance(exposure, dict) else exposure.hedgeable


def _skip(code: str, why: str) -> Check:
    return Check(code=code, passed=None, metric={"skipped": why})


# ---- composition


class NotHedgeableError(ValueError):
    """`evaluate` was handed an exposure the stats gates dropped (`hedgeable=false`).

    Such an exposure is "measured, not hedged" and must never reach a market. It can't be a
    declined Decision today: models.Decision.reasons is `list[CheckCode]` (the six market
    checks) and must equal the failed checks. Contract change needed (C6): add a
    `not_hedgeable` CheckCode ahead of `no_market`, whose metric carries the exposure's own
    gate flags (`below_size`, `not_significant`, `thin_support` as booleans).
    """

    def __init__(self, exposure_id: str, reasons: list[str]):
        super().__init__(
            f"{exposure_id} is not hedgeable ({', '.join(reasons)}); it is shown as measured, "
            "not hedged, and never matched. A declined Decision for it needs a `not_hedgeable` "
            "CheckCode in app/models.py."
        )
        self.exposure_id = exposure_id
        self.reasons = reasons


def evaluate(
    exposure: Any, candidates: list[Candidate], sizing: Sizing | None,
    basis: BasisStat | None, remaining_budget: Decimal, th: Thresholds,
    *, decision_id: str | None = None, venue_note: str | None = None,
) -> Decision:
    """Run every check in table order, always. Size with resolve_h's h first (G5).

    Raises NotHedgeableError for an exposure the stats gates dropped, before any check runs.
    """
    if not _hedgeable(exposure):
        raise NotHedgeableError(field(exposure, "id"), list(field(exposure, "reasons")))
    var = field(exposure, "settlement_var")
    if basis is None and var not in NO_BASIS_NEEDED:
        raise ValueError(f"{var} exposure needs a BasisStat for rule 4")
    beta = dec(field(exposure, "effect_usd"))
    remaining = dec(remaining_budget)

    checks = [check_no_market(candidates, venue_note)]
    if not candidates or sizing is None:
        checks += [_skip(c, "no_market") for c in MARKET_CODES[1:]]
        checks.append(check_unstable(exposure, th))
        checks.append(check_over_budget(ZERO, remaining))
    else:
        filled = sizing.n_filled > 0
        checks.append(check_illiquid(sizing.n_target, sizing.n_filled, th))
        # Exact average (cost / n), not the 4-dp display value, so the boundary is exact.
        checks.append(check_overpriced(sizing.avg_price, sizing.fair, th, side=sizing.side) if filled
                      else _skip("overpriced", "no_fill"))
        checks.append(check_basis(basis, beta, th) if var not in NO_BASIS_NEEDED else
                      Check(code="basis_too_loose", passed=True, metric={"skipped": "no_basis_needed", "h": "1"}))
        checks.append(check_too_expensive(sizing.expected_cost, beta, th) if filled
                      else _skip("too_expensive", "no_fill"))
        checks.append(check_unstable(exposure, th))
        checks.append(check_over_budget(sizing.premium, remaining))

    failed = [c.code for c in checks if c.passed is False]
    declines = [c for c in failed if c in DECLINE_CODES]
    status = "declined" if declines else "pending_approval" if failed else "proposed"
    if decision_id is None:
        key = f"{field(exposure, 'business_id')}|{field(exposure, 'id')}|{sizing.ticker if sizing else ''}"
        decision_id = "dec_" + hashlib.sha1(key.encode()).hexdigest()[:12]
    # models.Decision: reasons are the failed decline checks, or ["over_budget"] when only it failed.
    return Decision(id=decision_id, status=status, checks=checks, reasons=declines or failed, summary=None)
