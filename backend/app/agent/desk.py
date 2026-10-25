"""Weekly desk run. MINIMAL STUB for the API (#15).

TODO(#45): replace with the real loop (Claude tool loop capped at Thresholds.max_tool_calls,
I2 validator via agent/log.py, policy.py). Keep the `run_week` name and signature: the
`/desk/run` route calls it from a background task.

What the stub does, deterministically (agent "fallback"): for each hedgeable exposure from
the cached analysis, ask the markets port for a hedge, apply this week's remaining budget,
store it, and append a proposal/decline log entry with a templated summary built only from
the hedge's own numbers. It never approves (I4).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app import analysis, clock, db
from app.markets.port import get_markets
from app.models import Agent, Hedge, LogEntry

OPEN = ("proposed", "pending_approval")


@dataclass
class DeskRun:
    run_id: str
    agent: Agent
    hedges: list[Hedge] = field(default_factory=list)
    log_ids: list[str] = field(default_factory=list)
    summary: str = ""


def _summary(h: Hedge) -> str:
    if h.status == "declined":
        reasons = ", ".join(r.replace("_", " ") for r in h.decision.reasons)
        return f"Declined {h.ticker or 'this exposure'}: {reasons}."
    side = h.side.upper()
    if h.status == "pending_approval":
        return f"Over budget, waiting for you: {h.n_filled} {side} contracts on {h.ticker} for ${h.premium}."
    return f"Proposed: {h.n_filled} {side} contracts on {h.ticker} for ${h.premium}, waiting for your approval."


def _numbers(h: Hedge) -> dict:
    nums: dict = {}
    for c in h.decision.checks:
        nums.update({k: v for k, v in c.metric.items() if not isinstance(v, (bool, str)) and v is not None})
    for k in ("n_target", "n_filled", "n_unfilled", "avg_price", "cost", "fee", "premium", "fair", "expected_cost"):
        v = getattr(h, k)
        if v is not None:
            nums[k] = v
    return nums


async def run_week(business_id: str, week_of: date, *, run_id: str) -> DeskRun:
    """Run the desk for one business and week. Raises on failure; the route records it."""
    now = clock.now()
    res = analysis.cached_or_compute(business_id)
    markets = get_markets()
    thresholds = db.get_business_thresholds(business_id)
    run = DeskRun(run_id=run_id, agent="fallback")
    existing = {(h.exposure_id): h for h in db.list_hedges(business_id, week_of, OPEN)}

    for exp in res.exposures:
        if exp.id in existing:  # G14: same-week rerun reuses the open hedge
            run.hedges.append(existing[exp.id])
            continue
        hedge_id = f"hdg_{business_id}_{week_of:%Y%m%d}_{exp.event}_{run_id[-6:]}"
        remaining = db.compute_budget(business_id, week_of).remaining
        hedge = await markets.hedge_for(
            exp, hedge_id=hedge_id, week_of=week_of, now=now, agent="fallback",
            remaining=remaining, thresholds=thresholds,
        )
        text = _summary(hedge)
        hedge = hedge.model_copy(update={"decision": hedge.decision.model_copy(update={"summary": text})})
        db.put_hedge(hedge)
        log_id = f"log_{hedge_id}"
        db.append_log(LogEntry(
            log_id=log_id, business_id=business_id,
            kind="decline" if hedge.status == "declined" else "proposal",
            created_at=clock.now(), actor="desk", agent="fallback", hedge_id=hedge.id,
            decision_id=hedge.decision.id, run_id=run_id, status=hedge.status,
            checks=hedge.decision.checks, reasons=hedge.decision.reasons,
            numbers=_numbers(hedge), summary=text,
        ))
        run.hedges.append(hedge)
        run.log_ids.append(log_id)

    total = sum((h.premium or Decimal(0) for h in run.hedges if h.status in OPEN), Decimal("0.00"))
    run.summary = f"{len(run.hedges)} hedges this week; ${total} waiting for approval."
    return run
