"""Budget and owner-only approval policy (spec §11, invariant I4). Gates are code, not prompt.

- `can_act(actor, action)`: the single approval gate. Only the exact string "owner" may
  approve, reject or book. "desk", "claude", "agent", None and "OWNER " are all refused.
- `require_owner(...)`: `can_act` plus a logged refusal (kind "refusal") and `PolicyError`.
- `check_budget(business_id, now)`: `Budget{budget, spent, remaining, pending, week_start}`
  via `db.compute_budget` for the Monday-start week containing `now`.
  D4 (proposed default, used here): pending hedges count, `remaining = budget − spent − pending`.
- `classify(premium, remaining)`: "within" | "over_budget". Over budget keeps full size and
  goes to `pending_approval` with a within-budget alternative (`within_budget_alternative`,
  re-sized from the hedge's own fills).
- `reject(hedge_id, actor)` / `approve(hedge_id, actor, ledger_entry_ids)`: owner-only state
  changes from `proposed` or `pending_approval` (D1 default), each logged (I5). Booking the
  ledger is C5's `book_hedge`; it must call `can_act` too and pass its entry ids here.
- `sweep(now, business_id=None)`: approval timing (spec §11, C4-A24/A25, G8). For every open
  hedge (`proposed` or `pending_approval`, D1 default) with a `close_time`: one `nudge` entry
  once `now >= close_time - NUDGE_BEFORE_CLOSE` (3 h), never twice; at `now >= close_time` the
  hedge becomes `expired_unapproved` (R5 terminal, so approve answers 409) with one logged
  entry. Idempotent; returns the new log ids. Run by the 60 s loop in `main.py` and at the
  start of every desk run.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP, Decimal

from sqlalchemy.engine import Engine

from app import clock, db
from app.agent import log
from app.models import Budget, Headline, Hedge, HedgeLite, PayoffRow

OWNER = "owner"
OWNER_ACTIONS = frozenset({"approve", "reject", "book"})
DECIDABLE = ("proposed", "pending_approval")  # D1: every passing hedge waits for the owner


NUDGE_BEFORE_CLOSE = timedelta(hours=3)


class PolicyError(PermissionError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def can_act(actor: object, action: str) -> bool:
    """True only for the exact actor "owner" on approve/reject/book (I4)."""
    if action in OWNER_ACTIONS:
        return isinstance(actor, str) and actor == OWNER
    return False


def week_start(d: date | datetime | None = None) -> date:
    if d is None:
        d = clock.now()
    if isinstance(d, datetime):
        d = d.date()
    return d - timedelta(days=d.weekday())


def check_budget(business_id: str, now: date | datetime | None = None, engine: Engine | None = None) -> Budget:
    return db.compute_budget(business_id, week_start(now), engine)


def remaining(business_id: str, now: date | datetime | None = None, engine: Engine | None = None) -> Decimal:
    return check_budget(business_id, now, engine).remaining


def classify(premium: Decimal, remaining_budget: Decimal) -> str:
    return "within" if premium <= remaining_budget else "over_budget"


def _fee(fills: list[tuple[Decimal, int]]) -> Decimal:
    raw = sum((Decimal("0.07") * c * p * (1 - p) for p, c in fills), Decimal(0))
    return raw.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def within_budget_alternative(hedge: Hedge, remaining_budget: Decimal) -> HedgeLite | None:
    """Largest smaller hedge on the same market whose premium fits `remaining_budget` (G10).

    Re-uses the hedge's own fills (cheapest levels first) and Kalshi's taker-fee formula, so
    every figure is computed here from the sizing tool's output. None if nothing fits."""
    if remaining_budget <= 0 or not hedge.fills or hedge.payoff is None or hedge.headline is None:
        return None
    levels = sorted(((lv.price, lv.count) for lv in hedge.fills), key=lambda t: t[0])
    beta = hedge.payoff[0].revenue_vs_base
    swing = hedge.headline.unhedged_swing
    best = None
    for n in range(min(hedge.n_filled - 1, int(abs(beta))), 0, -1):
        take, left = [], n
        for p, c in levels:
            if left == 0:
                break
            k = min(c, left)
            take.append((p, k))
            left -= k
        cost = sum((p * k for p, k in take), Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        fee = _fee(take)
        premium = cost + fee
        if premium <= remaining_budget:
            best = (n, take, cost, fee, premium)
            break
    if best is None:
        return None
    n, take, cost, fee, premium = best
    rows = []
    for outcome, revenue, pays in (("event", beta, hedge.side == "yes"), ("no_event", Decimal("0.00"), hedge.side == "no")):
        payout = Decimal(n) if pays else Decimal(0)
        rows.append(PayoffRow(outcome=outcome, revenue_vs_base=revenue, contract_payout=payout.quantize(Decimal("0.01")),
                              premium=-premium, net_vs_base=(revenue + payout - premium).quantize(Decimal("0.01"))))
    h = (Decimal(n) / abs(beta)).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    avg = (sum((p * k for p, k in take), Decimal(0)) / n).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return HedgeLite(
        h=h, n_target=n, n_filled=n, avg_price=avg, cost=cost, fee=fee, premium=premium, payoff=rows,
        headline=Headline(unhedged_swing=swing, hedged_swing=abs(rows[0].net_vs_base - rows[1].net_vs_base),
                          cost=premium),
    )


def _refusal(business_id: str, hedge_id: str | None, actor: object, action: str, engine: Engine | None) -> None:
    text, _ = log.sanitize(f"Refused {action} by {actor!r}: only the owner can {action}.", {})
    log.append(
        dict(
            business_id=business_id, kind="refusal", actor="system", agent=None, hedge_id=hedge_id,
            decision_id=None, run_id=None, status=None, checks=[], reasons=[], numbers={},
            summary=text,
        ),
        engine,
    )


def require_owner(
    actor: object, action: str, *, business_id: str, hedge_id: str | None = None, engine: Engine | None = None
) -> None:
    """Raise PolicyError (and log the refusal) unless `can_act(actor, action)`."""
    if not can_act(actor, action):
        _refusal(business_id, hedge_id, actor, action, engine)
        raise PolicyError("owner_only", f"only the owner can {action}")


def _decide(
    hedge_id: str, actor: object, action: str, new_status: str, kind: str,
    ledger_entry_ids: list[str], note: str | None, now: datetime | None, engine: Engine | None,
) -> Hedge:
    hedge = db.get_hedge(hedge_id, engine)
    if hedge is None:
        raise PolicyError("not_found", f"no hedge {hedge_id}")
    require_owner(actor, action, business_id=hedge.business_id, hedge_id=hedge_id, engine=engine)
    if hedge.status not in DECIDABLE:
        raise PolicyError("conflict", f"hedge {hedge_id} is {hedge.status}; cannot {action}")
    now = now or clock.now()
    updated = hedge.model_copy(update={
        "status": new_status, "decided_by": OWNER, "decided_at": now, "ledger_entry_ids": ledger_entry_ids,
    })
    updated = Hedge.model_validate(updated.model_dump())
    db.put_hedge(updated, engine)
    numbers = log.allowed_numbers({"n_filled": hedge.n_filled, "premium": hedge.premium, "fee": hedge.fee})
    verb = "approved" if action == "approve" else "rejected"
    text = f"Owner {verb} {hedge.id}"
    if hedge.premium is not None:
        text += f": {hedge.n_filled} {hedge.side.upper()} contracts for ${hedge.premium:,.2f}"
    text += "." if not note else f". {note}"
    text, _ = log.sanitize(text, numbers)  # an owner's note never smuggles in a number
    log.append(
        dict(
            business_id=hedge.business_id, kind=kind, actor=OWNER, agent=None, hedge_id=hedge.id,
            decision_id=hedge.decision.id, run_id=None, status=new_status, checks=[], reasons=[],
            numbers=numbers, summary=text,
        ),
        engine,
    )
    return updated


def approve(
    hedge_id: str, actor: object, ledger_entry_ids: list[str], *, note: str | None = None,
    now: datetime | None = None, engine: Engine | None = None,
) -> Hedge:
    """Owner approval. `ledger_entry_ids` come from C5's booking (an approved hedge is booked)."""
    if not ledger_entry_ids:
        raise PolicyError("not_booked", "an approved hedge needs its ledger entries (C5 book_hedge)")
    return _decide(hedge_id, actor, "approve", "approved", "approval", ledger_entry_ids, note, now, engine)


def reject(
    hedge_id: str, actor: object, *, reason: str | None = None, now: datetime | None = None,
    engine: Engine | None = None,
) -> Hedge:
    return _decide(hedge_id, actor, "reject", "rejected", "rejection", [], reason, now, engine)


# --- Approval timing: nudge and expiry (C4-A24/A25) ------------------------------------


def _nudged(hedge_id: str, engine: Engine | None) -> bool:
    return any(e.kind == "nudge" for e in db.list_log(hedge_id=hedge_id, engine=engine))


def _timing_entry(hedge: Hedge, kind: str, status: str, summary: str, now: datetime,
                  engine: Engine | None) -> str:
    numbers = log.allowed_numbers({"n_filled": hedge.n_filled, "premium": hedge.premium})
    summary, _ = log.sanitize(summary, numbers)
    return log.append(
        dict(
            business_id=hedge.business_id, kind=kind, actor="system", agent=None, hedge_id=hedge.id,
            decision_id=hedge.decision.id, run_id=None, status=status, checks=[], reasons=[],
            numbers=numbers, summary=summary, created_at=now,
        ),
        engine,
    )


def _what(hedge: Hedge) -> str:
    if hedge.premium is None:
        return hedge.id
    return f"{hedge.id} ({hedge.n_filled} {hedge.side.upper()} contracts for ${hedge.premium:,.2f})"


def sweep(now: datetime | None = None, *, business_id: str | None = None,
          engine: Engine | None = None, nudge_before_close: timedelta = NUDGE_BEFORE_CLOSE) -> list[str]:
    """Nudge once at close - 3 h, expire at close. Returns the log ids it appended."""
    from app import clock

    now = now or clock.now()
    out: list[str] = []
    for hedge in db.list_hedges(business_id, None, DECIDABLE, engine):
        close = hedge.close_time
        if close is None:
            continue
        if now >= close:
            expired = Hedge.model_validate(hedge.model_dump() | {"status": "expired_unapproved", "alternative": None})
            db.put_hedge(expired, engine)
            out.append(_timing_entry(
                hedge, "expired_unapproved", "expired_unapproved",
                f"Expired unapproved: {_what(hedge)}. The market closed before the owner decided, "
                "so it can no longer be booked.", now, engine))
        elif now >= close - nudge_before_close and not _nudged(hedge.id, engine):
            out.append(_timing_entry(
                hedge, "nudge", hedge.status,
                f"Reminder: {_what(hedge)} is still waiting on you, and its market closes at "
                f"{close.astimezone(timezone.utc):%H:%M} UTC. If you don't decide by then, it expires.",
                now, engine))
    return out
