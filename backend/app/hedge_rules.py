"""Re-run the decline rules on a stored hedge from its recorded check metrics (no market
calls, no Claude). Used by `PUT /settings` (R14) and to apply this week's budget to a hedge.

Only checks whose metric carries the needed inputs are re-judged; the rest keep their
result. Skipped checks (`passed: null`) stay skipped.
"""

from decimal import Decimal
from typing import Any

from app.config import Thresholds
from app.models import Check, Decision, Hedge

UNDECIDED = ("proposed", "pending_approval", "declined")


def _dec(v: Any) -> Decimal | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _rejudge(check: Check, th: Thresholds, remaining: Decimal | None) -> Check:
    if check.passed is None:
        return check
    m = dict(check.metric)
    passed = check.passed
    if check.code == "illiquid" and (r := _dec(m.get("fill_ratio"))) is not None:
        passed = r >= th.fill_decline
    elif check.code == "overpriced" and (o := _dec(m.get("overpay"))) is not None:
        passed = not (o > th.overpay_max)
    elif check.code == "basis_too_loose" and "skipped" not in m and (r2 := _dec(m.get("r2"))) is not None:
        passed = r2 >= Decimal(str(th.basis_r2_min))
    elif check.code == "too_expensive" and (r := _dec(m.get("ratio"))) is not None:
        passed = not (r > th.cost_ratio_max)
    elif check.code == "over_budget" and remaining is not None and (p := _dec(m.get("premium"))) is not None:
        m["remaining"] = remaining.quantize(Decimal("0.01"))
        passed = p <= remaining
    return Check(code=check.code, passed=passed, metric=m)


def decision_from_checks(old: Decision, checks: list[Check]) -> Decision:
    failed = [c.code for c in checks if c.passed is False]
    declines = [c for c in failed if c != "over_budget"]
    status = "declined" if declines else "pending_approval" if failed else "proposed"
    return Decision(id=old.id, status=status, checks=checks, reasons=declines or failed, summary=old.summary)


def apply_rules(hedge: Hedge, th: Thresholds, remaining: Decimal | None = None) -> Hedge:
    """The hedge with its checks re-judged. Approved/rejected/settled hedges are returned as is.

    `remaining` is the budget left for this hedge (excluding its own premium); None keeps
    the stored over_budget result.
    """
    if hedge.status not in UNDECIDED:
        return hedge
    checks = [_rejudge(c, th, remaining) for c in hedge.decision.checks]
    decision = decision_from_checks(hedge.decision, checks)
    update: dict[str, Any] = {"decision": decision.model_dump(), "status": decision.status}
    if decision.status != "pending_approval":
        update["alternative"] = None
    return Hedge.model_validate(hedge.model_dump() | update)  # re-validated, not just copied
