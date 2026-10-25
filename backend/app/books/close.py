"""Closing the books through a date (controller only). Pure code, no LLM.

A close checks the period, then locks it:

1. The date has passed in New York, and it moves the lock forward (no reopening).
2. Reconciliation runs (`reconcile.reconcile`, read-only). Open mismatches block the close
   unless the controller acknowledges them, and then they are carried in the close record as
   exceptions, word for word.
3. The trial balance as of the date is computed from the ledger and must sum to zero.
4. The close is stored and logged (`period_close`, I5). From then on the ledger refuses to
   date anything on or before the lock: a late booking or settlement lands on the next open day
   and its narration names the closed date it belongs to (`ledger.posting_date`).

Proposed and pending hedges have no ledger entries, so they never block a close; the record
counts them so the controller can see what is still waiting on the owner.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.engine import Engine

from app import clock, db
from app.agent import log
from app.books import ledger
from app.books import reconcile as recon
from app.models import PeriodClose, PeriodCloses, TrialBalanceRow

ZERO = Decimal("0.00")
KEY = ledger.CLOSES_KEY


class CloseRefused(ValueError):
    def __init__(self, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.detail = code, message, detail or {}


def list_closes(business_id: str, engine: Engine | None = None) -> PeriodCloses:
    closes = [PeriodClose.model_validate(c) for c in (db.get_analysis(business_id, KEY, engine) or [])]
    closes.sort(key=lambda c: c.through, reverse=True)
    return PeriodCloses(locked_through=closes[0].through if closes else None, closes=closes)


def trial_balance(business_id: str, through: date, engine: Engine | None = None) -> list[TrialBalanceRow]:
    sums: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for e in db.list_ledger_entries(business_id, engine):
        if e.date <= through:
            for p in e.postings:
                sums[p.account] += p.amount
    return [TrialBalanceRow(account=a, balance=ledger.cents(b)) for a, b in sorted(sums.items()) if b != 0]


def close_period(
    business_id: str, through: date, *, acknowledge_exceptions: bool = False, note: str | None = None,
    now: datetime | None = None, engine: Engine | None = None,
) -> PeriodClose:
    """Lock the books through `through`. The caller has already checked the actor is the controller."""
    now = now or clock.now()
    today = ledger.ny_date(now)
    if through >= today:
        raise CloseRefused("period_not_ended", f"The books can only be closed through a past date; "
                           f"{through.isoformat()} has not ended in New York yet.",
                           {"through": through.isoformat(), "today": today.isoformat()})
    previous = list_closes(business_id, engine).locked_through
    if previous is not None and through <= previous:
        raise CloseRefused("already_closed", f"The books are already closed through {previous.isoformat()}.",
                           {"locked_through": previous.isoformat()})

    exceptions: list[str] = []
    if recon.has_settlements(business_id, engine):
        result = recon.reconcile(business_id, engine=engine, log=False)
        exceptions = [m.explanation for m in result.mismatches]
    if exceptions and not acknowledge_exceptions:
        raise CloseRefused("unreconciled", f"{len(exceptions)} reconciliation mismatch(es) are open; resolve them "
                           "or close with acknowledge_exceptions to carry them.", {"exceptions": exceptions})

    period = [e for e in db.list_ledger_entries(business_id, engine)
              if (previous is None or e.date > previous) and e.date <= through]
    open_hedges = len(db.list_hedges(business_id, None, db.PENDING_STATUSES, engine))
    note_text, _ = log.sanitize(note, {}) if note else (None, [])  # a note is never a number source (I2)
    record = PeriodClose(
        business_id=business_id, through=through, previous_through=previous, closed_at=now,
        closed_by="controller", n_entries=len(period), trial_balance=trial_balance(business_id, through, engine),
        exceptions=exceptions, open_hedges=open_hedges, simulated=any(e.simulated for e in period),
        note=note_text,
    )
    stored = [c.model_dump(mode="json") for c in list_closes(business_id, engine).closes]
    db.put_analysis(business_id, KEY, [record.model_dump(mode="json")] + stored, now.isoformat(), engine)
    carried = f" with {len(exceptions)} reconciliation exception(s) carried" if exceptions else ""
    log.append(dict(
        business_id=business_id, kind="period_close", actor="controller", agent=None, hedge_id=None,
        decision_id=None, run_id=None, status=None, checks=[], reasons=[],
        numbers={"n_entries": record.n_entries, "n_exceptions": len(exceptions), "open_hedges": open_hedges,
                 "simulated": record.simulated},
        summary=(f"Controller closed the books through {through.isoformat()}: {record.n_entries} ledger "
                 f"entries in the period{carried}." + (f" Note: {note_text}" if note_text else "")),
        created_at=now,
    ), engine)
    return record
