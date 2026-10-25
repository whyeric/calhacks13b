"""Ledger booking on owner approval. MINIMAL STUB for the API (#15).

TODO(#4): replace with the real Beancount ledger (bean-check clean file, settlement,
withdrawals, reconciliation). Keep `book_approval(hedge, actor) -> list[str]`: the approve
route calls it before it stores the approved hedge, so a raise leaves the hedge unchanged.

The stub writes one premium transaction (premium + fee) per hedge to the db and appends it
to `ledgers/{business}.beancount`. Idempotent on hedge id.
"""

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from app import db
from app.config import get_settings
from app.models import Hedge, LedgerEntry, LedgerMeta, Posting

NY = ZoneInfo("America/New_York")
ACCOUNTS = ("Assets:Kalshi:Cash", "Assets:Bank:Checking", "Expenses:Hedging:Premiums",
            "Expenses:Hedging:Fees", "Income:Hedging:Payouts")


class BookingRefused(Exception):
    pass


def ledger_path(business_id: str) -> Path:
    return Path(get_settings().ledgers_dir) / f"{business_id}.beancount"


def _beancount(e: LedgerEntry) -> str:
    m = e.meta
    lines = [f'{e.date.isoformat()} * "Hedge Desk" "{e.narration}"']
    if m:
        lines.append(f'  hedge_id: "{m.hedge_id}"\n  ticker: "{m.ticker}"\n'
                     f'  decision_id: "{m.decision_id}"\n  approved_by: "{m.approved_by}"')
    lines += [f"  {p.account:<28} {p.amount:>10} USD" for p in e.postings]
    return "\n".join(lines) + "\n\n"


def _append_file(e: LedgerEntry, opened_on) -> None:
    path = ledger_path(e.business_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        head = 'option "operating_currency" "USD"\n\n'
        head += "".join(f"{opened_on.isoformat()} open {a} USD\n" for a in ACCOUNTS) + "\n"
        path.write_text(head)
    with path.open("a") as f:
        f.write(_beancount(e))


def book_approval(hedge: Hedge, actor: str) -> list[str]:
    """Book the premium and fee for an approved hedge. Raises BookingRefused unless the hedge
    is `approved` by exactly `owner` (I4)."""
    if actor != "owner" or hedge.status != "approved":
        raise BookingRefused("only an owner-approved hedge can be booked")
    if hedge.premium is None or hedge.cost is None or hedge.fee is None or hedge.ticker is None:
        raise BookingRefused("hedge has no sizing to book")
    entry_id = f"le_{hedge.id}_premium"
    if any(e.id == entry_id for e in db.list_ledger_entries(hedge.business_id)):
        return [entry_id]
    when = (hedge.decided_at or hedge.created_at).astimezone(NY).date()
    entry = LedgerEntry(
        id=entry_id, business_id=hedge.business_id, date=when, kind="premium",
        narration=f"Premium: {hedge.ticker} {hedge.side.upper()} x {hedge.n_filled}",
        postings=[
            Posting(account="Expenses:Hedging:Premiums", amount=hedge.cost),
            Posting(account="Expenses:Hedging:Fees", amount=hedge.fee),
            Posting(account="Assets:Kalshi:Cash", amount=-(hedge.cost + hedge.fee)),
        ],
        meta=LedgerMeta(hedge_id=hedge.id, ticker=hedge.ticker, decision_id=hedge.decision.id, approved_by="owner"),
        simulated=False,
    )
    _append_file(entry, date(2020, 1, 1))
    db.put_ledger_entry(entry)
    return [entry_id]


__all__ = ["book_approval", "BookingRefused", "ledger_path"]
