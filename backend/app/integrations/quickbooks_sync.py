"""Write the desk's bookings back into QuickBooks as JournalEntries, and check they still match.

Beancount (`books/ledger.py`, the `ledger_entries` table) is the **system of record** for the
desk's entries: each one is owner-approved and in the decision log (I4, I5). QuickBooks gets a
**mirror**, so the bookkeeper sees hedge premiums, payouts and withdrawals in the books they
already use. Consequences:

- A QuickBooks failure never blocks or undoes a booking. `mirror_entries` never raises; it records
  the failure (`qbo_post_failed` in the decision log, status `failed` on the sync view) and retries
  the entry on the next mirror call.
- Mirroring is idempotent. A JournalEntry's `DocNumber` is our ledger entry id (hashed to QBO's 21
  characters when longer); before creating one we look for that DocNumber, and a posted entry is
  never posted again.
- `sync_report` reads every mirrored JournalEntry back and says which ones a bookkeeper deleted
  (`missing`) or edited (`amount_differs`). It only reads: Beancount is right, and fixing
  QuickBooks is a person's call.

Account mapping (found by name in the company, created with these types if missing):

    Beancount account            QBO account        AccountType          AccountSubType
    Assets:Kalshi:Cash           Kalshi Cash        Other Current Asset  OtherCurrentAssets
    Assets:Polymarket:Cash       Polymarket Cash    Other Current Asset  OtherCurrentAssets
    Assets:Bank:Checking         Checking (*)       Bank                 Checking
    Expenses:Hedging:Premiums    Hedging Premiums   Other Expense        OtherMiscellaneousExpense
    Expenses:Hedging:Fees        Hedging Fees       Other Expense        OtherMiscellaneousExpense
    Income:Hedging:Payouts       Hedging Payouts    Other Income         OtherMiscellaneousIncome

    (*) QBO_BANK_ACCOUNT_NAME; the business's existing checking account.

A posting with a positive amount is a Debit line, a negative one a Credit line (zero lines are
dropped), so debits equal credits to the cent exactly as the Beancount postings sum to zero.

Demo mode writes to a SYNTHETIC store in the app DB (`DemoBooks`), which answers the same calls as
QuickBooks, so the flow is visible offline. Live mode writes to the connected company.

Simulated ledger entries (simulated settlements, withdrawals and the opening deposit) are written
to a demo or sandbox company, labeled [SIMULATED], and never to a production company.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy.engine import Engine

from app import clock, db
from app.books.ledger import BANK, CASH, FEES, PAYOUTS, POLYMARKET_CASH, PREMIUMS
from app.config import get_settings
from app.integrations import quickbooks as qbo
from app.models import LedgerEntry, LogEntry, QboSyncLine, QboSyncReport

log = logging.getLogger("hedge_desk.quickbooks_sync")

DOC_NUMBER_MAX = 21  # QBO's limit on a transaction's DocNumber
PRIVATE_NOTE_MAX = 4000
DESCRIPTION_MAX = 4000
CENT = Decimal("0.01")
ZERO = Decimal("0")


@dataclass(frozen=True)
class QboAccount:
    name: str
    account_type: str
    sub_type: str


def account_map() -> dict[str, QboAccount]:
    """Beancount account -> the QBO account it posts to (see the module docstring)."""
    return {
        CASH: QboAccount("Kalshi Cash", "Other Current Asset", "OtherCurrentAssets"),
        POLYMARKET_CASH: QboAccount("Polymarket Cash", "Other Current Asset", "OtherCurrentAssets"),
        BANK: QboAccount(get_settings().qbo_bank_account_name, "Bank", "Checking"),
        PREMIUMS: QboAccount("Hedging Premiums", "Other Expense", "OtherMiscellaneousExpense"),
        FEES: QboAccount("Hedging Fees", "Other Expense", "OtherMiscellaneousExpense"),
        PAYOUTS: QboAccount("Hedging Payouts", "Other Income", "OtherMiscellaneousIncome"),
    }


class UnmappedAccount(ValueError):
    pass


def doc_number(entry_id: str) -> str:
    """Our ledger entry id as a DocNumber: as is when it fits in 21 characters, else its first 12
    characters, "-" and 8 hex characters of its SHA-1 (stable, so a re-post finds the same JE)."""
    if len(entry_id) <= DOC_NUMBER_MAX:
        return entry_id
    return f"{entry_id[:12]}-{hashlib.sha1(entry_id.encode()).hexdigest()[:8]}"


KIND_ORDER = {"opening_deposit": 0, "premium": 1, "payout": 2, "withdrawal": 3}  # within a day


def ledger_order(e: LedgerEntry) -> tuple:
    """Oldest first; on one day the deposit before the premium it funds, the payout before its withdrawal."""
    return (e.date, KIND_ORDER.get(e.kind, 9), e.id)


TRIGGER = {
    "premium": "on owner approval",
    "payout": "on settlement",
    "withdrawal": "on withdrawal",
    "opening_deposit": "as the opening deposit",
}


def private_note(entry: LedgerEntry) -> str:
    parts = ["[SIMULATED] " if entry.simulated else "", f"Hedge Desk ledger entry {entry.id} ({entry.kind})."]
    if entry.meta is not None:
        parts.append(f" Hedge {entry.meta.hedge_id}, decision {entry.meta.decision_id}, {entry.meta.ticker}.")
    parts.append(f" Posted by Hedge Desk {TRIGGER[entry.kind]}. Beancount is the record: change the desk's"
                 " ledger, not this entry.")
    return "".join(parts)[:PRIVATE_NOTE_MAX]


def debit_total(lines: list[dict[str, Any]]) -> Decimal:
    return sum((Decimal(str(ln["amount"])) for ln in lines if ln["posting_type"] == "Debit"), ZERO).quantize(CENT)


def journal_entry(entry: LedgerEntry, account_ids: dict[str, str]) -> dict[str, Any]:
    """The QBO JournalEntry for one ledger entry. `account_ids` maps Beancount accounts to QBO ids.
    Balanced by construction: the postings sum to zero (the LedgerEntry model checks it)."""
    lines = []
    for p in entry.postings:
        amount = p.amount.quantize(CENT)
        if amount == 0:
            continue
        if p.account not in account_ids:
            raise UnmappedAccount(f"no QuickBooks account for {p.account}")
        lines.append({
            "Description": entry.narration[:DESCRIPTION_MAX],
            "Amount": abs(amount),
            "DetailType": "JournalEntryLineDetail",
            "JournalEntryLineDetail": {"PostingType": "Debit" if amount > 0 else "Credit",
                                       "AccountRef": {"value": account_ids[p.account]}},
        })
    debits = sum((ln["Amount"] for ln in lines if ln["JournalEntryLineDetail"]["PostingType"] == "Debit"), ZERO)
    credits = sum((ln["Amount"] for ln in lines if ln["JournalEntryLineDetail"]["PostingType"] == "Credit"), ZERO)
    if debits != credits or debits == 0:
        raise ValueError(f"{entry.id}: debits {debits} != credits {credits}")
    return {"DocNumber": doc_number(entry.id), "TxnDate": entry.date.isoformat(),
            "PrivateNote": private_note(entry), "Line": lines}


def je_lines(je: dict[str, Any]) -> list[dict[str, Any]]:
    """A JournalEntry's lines as [{account_id, posting_type, amount}] (sorted, for comparing)."""
    out = []
    for ln in je.get("Line") or []:
        d = ln.get("JournalEntryLineDetail")
        if ln.get("DetailType") != "JournalEntryLineDetail" or not d:
            continue
        out.append({"account_id": str((d.get("AccountRef") or {}).get("value")),
                    "posting_type": str(d.get("PostingType")),
                    "amount": str(Decimal(str(ln.get("Amount") or 0)).quantize(CENT))})
    return sorted(out, key=lambda x: (x["posting_type"], x["account_id"], x["amount"]))


# --- Where JournalEntries go ----------------------------------------------------------


class Books(Protocol):
    """The calls the mirror makes: QuickBooks itself (`quickbooks.LiveSource`) or `DemoBooks`."""

    synthetic: bool

    def find(self, entity: str, field_name: str, value: str) -> list[dict]: ...

    def get(self, entity: str, obj_id: str) -> dict | None: ...

    def create(self, entity: str, obj: dict) -> dict: ...


def _plain(v: Any) -> Any:
    """Decimals as strings, for JSON storage."""
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


class DemoBooks:
    """SYNTHETIC stand-in for the demo company's chart of accounts and journal: what the desk would
    have written to QuickBooks, kept in the app DB (`qbo_demo_objects`). Same calls as LiveSource."""

    synthetic = True

    def __init__(self, engine: Engine | None = None):
        self.engine = engine

    def _all(self, entity: str) -> list[dict]:
        return db.list_qbo_demo_objects(entity, self.engine)

    def find(self, entity: str, field_name: str, value: str) -> list[dict]:
        return [o for o in self._all(entity) if str(o.get(field_name)) == str(value)]

    def get(self, entity: str, obj_id: str) -> dict | None:
        rows = self.find(entity, "Id", obj_id)
        return rows[0] if rows else None

    def create(self, entity: str, obj: dict) -> dict:
        n = len(self._all(entity)) + 1
        while self.get(entity, f"demo-{entity.lower()}-{n}") is not None:
            n += 1
        now = clock.now().isoformat()
        out = {**_plain(obj), "Id": f"demo-{entity.lower()}-{n}", "SyncToken": "0",
               "MetaData": {"CreateTime": now, "LastUpdatedTime": now}, "synthetic": True}
        if entity == "JournalEntry":
            out["TotalAmt"] = str(sum((Decimal(str(ln["Amount"])) for ln in obj.get("Line") or []
                                       if ln["JournalEntryLineDetail"]["PostingType"] == "Debit"), ZERO))
        db.put_qbo_demo_object(entity, out["Id"], out, self.engine)
        return out

    # For tests and demos of the drift check: what a bookkeeper might do in QuickBooks.
    def edit(self, entity: str, obj_id: str, obj: dict) -> None:
        db.put_qbo_demo_object(entity, obj_id, _plain(obj), self.engine)

    def delete(self, entity: str, obj_id: str) -> None:
        db.delete_qbo_demo_object(entity, obj_id, self.engine)


def connection(engine: Engine | None = None) -> qbo.QuickBooks:
    conn = qbo.get()
    return conn if engine is None else qbo.QuickBooks(conn.settings, engine)


def books_for(conn: qbo.QuickBooks) -> Books:
    if conn.mode == "demo":
        return DemoBooks(conn.engine)
    return conn.live()


# --- Accounts -----------------------------------------------------------------------

# (realm, QBO account name) -> Id, live companies only (the demo store is a cheap DB read). A
# failed post clears the realm's entries, so an account deleted in QuickBooks is looked up again.
_account_cache: dict[tuple[str, str], str] = {}


def ensure_accounts(books: Books, realm_id: str, accounts: set[str]) -> dict[str, str]:
    """QBO account ids for these Beancount accounts, creating any that are missing."""
    mapping = account_map()
    out = {}
    for acct in sorted(accounts):
        if acct not in mapping:
            raise UnmappedAccount(f"no QuickBooks account mapped for {acct}")
        spec = mapping[acct]
        key = (realm_id, spec.name)
        if books.synthetic or key not in _account_cache:
            found = [a for a in books.find("Account", "Name", spec.name) if a.get("Active", True) is not False]
            made = found[0] if found else books.create("Account", {
                "Name": spec.name, "AccountType": spec.account_type, "AccountSubType": spec.sub_type,
                "Description": "Created by Hedge Desk for its hedge bookings."})
            if books.synthetic:
                out[acct] = str(made["Id"])
                continue
            _account_cache[key] = str(made["Id"])
        out[acct] = _account_cache[key]
    return out


def forget_accounts(realm_id: str) -> None:
    for key in [k for k in _account_cache if k[0] == realm_id]:
        _account_cache.pop(key, None)


# --- Mirroring ----------------------------------------------------------------------


@dataclass
class MirrorResult:
    entry_id: str
    status: str  # "posted" (now or before), "failed", "skipped"
    qbo_id: str | None = None
    detail: str = ""


def _log(entry: LedgerEntry, kind: str, summary: str, numbers: dict[str, Any], engine: Engine | None) -> None:
    """Append qbo_posted / qbo_post_failed (I5), timed after the entry's own log events."""
    hedge_id = entry.meta.hedge_id if entry.meta else None
    at = clock.now()
    if hedge_id:
        last = max((e.created_at for e in db.list_log(entry.business_id, hedge_id=hedge_id, engine=engine)),
                   default=None)
        if last is not None and last >= at:
            at = last + timedelta(seconds=1)
    db.append_log(LogEntry(
        log_id=f"log_qbo_{uuid.uuid4().hex[:12]}", business_id=entry.business_id, kind=kind, created_at=at,
        actor="system", agent=None, hedge_id=hedge_id, decision_id=entry.meta.decision_id if entry.meta else None,
        run_id=None, status=None, checks=[], reasons=[], numbers=numbers, summary=summary,
    ), engine)


def _mirror_one(entry: LedgerEntry, books: Books, conn: qbo.QuickBooks, realm_id: str,
                engine: Engine | None) -> MirrorResult:
    record = db.get_qbo_mirror(realm_id, entry.id, engine)
    if record is not None and record.get("status") == "posted":
        return MirrorResult(entry.id, "posted", record.get("qbo_id"), "already posted")
    if entry.simulated and conn.environment == "production":
        return MirrorResult(entry.id, "skipped", None, "simulated entries are never written to a production company")
    doc = doc_number(entry.id)
    attempts = int((record or {}).get("attempts", 0)) + 1
    where = "the SYNTHETIC demo QuickBooks store" if books.synthetic else f"QuickBooks ({conn.environment})"
    amount = sum((p.amount for p in entry.postings if p.amount > 0), ZERO).quantize(CENT)
    try:
        ids = ensure_accounts(books, realm_id, {p.account for p in entry.postings if p.amount != 0})
        body = journal_entry(entry, ids)
        existing = books.find("JournalEntry", "DocNumber", doc)
        je = existing[0] if existing else books.create("JournalEntry", body)
        lines = je_lines(body)
    except Exception as e:  # contained: QuickBooks is a mirror, never a blocker
        forget_accounts(realm_id)
        reason = e.message if isinstance(e, qbo.QuickBooksError) else str(e) or type(e).__name__
        errors = (getattr(e, "detail", None) or {}).get("errors") if isinstance(e, qbo.QuickBooksError) else None
        if errors:
            reason += " " + "; ".join(errors)
        db.put_qbo_mirror(realm_id, entry.id, entry.business_id, {
            "status": "failed", "doc_number": doc, "qbo_id": None, "lines": [], "error": reason[:500],
            "attempts": attempts, "updated_at": clock.now().isoformat()}, engine)
        _log(entry, "qbo_post_failed",
             f"Couldn't mirror {entry.id} to {where}: {reason[:300]} The booking stands; Beancount is the record, "
             "and the mirror retries on the next booking.",
             {"amount": amount, "doc_number": doc, "attempts": attempts}, engine)
        log.warning("QuickBooks mirror of %s failed: %s", entry.id, type(e).__name__)
        return MirrorResult(entry.id, "failed", None, reason)
    qbo_id = str(je["Id"])
    db.put_qbo_mirror(realm_id, entry.id, entry.business_id, {
        "status": "posted", "doc_number": doc, "qbo_id": qbo_id, "sync_token": str(je.get("SyncToken", "0")),
        "lines": lines, "amount": str(amount), "error": None, "attempts": attempts,
        "adopted": bool(existing), "posted_at": clock.now().isoformat(), "updated_at": clock.now().isoformat()},
        engine)
    how = "found the existing" if existing else "posted"
    _log(entry, "qbo_posted",
         f"Mirrored {entry.id} to {where}: {how} JournalEntry {qbo_id} (DocNumber {doc}), "
         f"${amount} debits = ${amount} credits." + (" [SIMULATED entry]" if entry.simulated else ""),
         {"amount": amount, "qbo_id": qbo_id, "doc_number": doc}, engine)
    return MirrorResult(entry.id, "posted", qbo_id, how)


def mirror_entries(business_id: str, entries: list[LedgerEntry] | None = None,
                   engine: Engine | None = None) -> list[MirrorResult]:
    """Mirror the business's ledger entries into the connected QuickBooks company. Call it right
    after a booking: it posts `entries` and any earlier entry not yet posted (one booked before
    QuickBooks was connected, or one whose post failed), oldest first, so QuickBooks' balances
    follow the ledger's. A no-op when QuickBooks isn't connected or QBO_MIRROR_ENABLED is off.
    Never raises: a failure is logged (`qbo_post_failed`) and the booking stands."""
    try:
        if not get_settings().qbo_mirror_enabled:
            return []
        conn = connection(engine)
        realm_id = conn.realm_id
        if realm_id is None:
            return []
        books = books_for(conn)
        stored = db.list_ledger_entries(business_id, engine)
        ids = {e.id for e in stored}
        todo = stored + [e for e in entries or [] if e.id not in ids and e.business_id == business_id]
        todo.sort(key=ledger_order)
        return [_mirror_one(e, books, conn, realm_id, engine) for e in todo]
    except Exception as e:  # e.g. NotConnected on an expired grant: the booking still stands
        log.warning("QuickBooks mirror for %s skipped: %s", business_id, type(e).__name__)
        return []


# --- Drift check ----------------------------------------------------------------------

EXPLANATION = (
    "Beancount, the desk's ledger, is the system of record for hedge entries: each one was approved by "
    "the owner and is in the decision log. QuickBooks holds a mirror of them as journal entries for the "
    "bookkeeper. Where the two disagree, the ledger is right: restore or re-post the QuickBooks entry "
    "instead of changing the ledger. This check only reads; it changes nothing in either."
)


def sync_report(business_id: str, engine: Engine | None = None) -> QboSyncReport:
    """Every ledger entry of the business next to its JournalEntry, read back from QuickBooks.
    Raises NotConnected (409) or Unavailable (502)."""
    conn = connection(engine)
    realm_id = conn.realm_id
    if realm_id is None:
        raise qbo.NotConnected("QuickBooks isn't connected; connect it first.", {"mode": conn.mode})
    books = books_for(conn)
    records = db.list_qbo_mirrors(realm_id, business_id, engine)
    lines = []
    for e in sorted(db.list_ledger_entries(business_id, engine), key=ledger_order):
        amount = sum((p.amount for p in e.postings if p.amount > 0), ZERO).quantize(CENT)
        rec = records.get(e.id)
        base = {"entry_id": e.id, "kind": e.kind, "date": e.date, "amount": amount, "simulated": e.simulated,
                "doc_number": doc_number(e.id)}
        if rec is None:
            why = ("simulated entries are never written to a production company"
                   if e.simulated and conn.environment == "production" else
                   "not mirrored yet: booked before QuickBooks was connected, or the mirror is off; "
                   "it is posted with the next booking")
            lines.append(QboSyncLine(**base, qbo_id=None, qbo_amount=None, status="not_posted", detail=why))
            continue
        if rec["status"] == "failed":
            lines.append(QboSyncLine(**base, qbo_id=None, qbo_amount=None, status="failed",
                                     detail=f"Posting failed after {rec.get('attempts', 1)} attempt(s): "
                                            f"{rec.get('error')}. Retried with the next booking."))
            continue
        je = books.get("JournalEntry", rec["qbo_id"])
        if je is None:
            lines.append(QboSyncLine(**base, qbo_id=rec["qbo_id"], qbo_amount=None, status="missing",
                                     detail=f"JournalEntry {rec['qbo_id']} is no longer in QuickBooks (deleted "
                                            "there?). The ledger still has the entry; re-post it in QuickBooks."))
            continue
        got = je_lines(je)
        qbo_amount = debit_total(got)
        if got == rec["lines"]:
            lines.append(QboSyncLine(**base, qbo_id=rec["qbo_id"], qbo_amount=qbo_amount, status="posted",
                                     detail="Matches the ledger, line for line."))
            continue
        lines.append(QboSyncLine(**base, qbo_id=rec["qbo_id"], qbo_amount=qbo_amount, status="amount_differs",
                                 detail=_differences(rec["lines"], got, amount, qbo_amount)))
    counts = {s: 0 for s in ("posted", "missing", "amount_differs", "failed", "not_posted")}
    for ln in lines:
        counts[ln.status] += 1
    return QboSyncReport(
        business_id=business_id, checked_at=clock.now(), mode=conn.mode, realm_id=realm_id,
        company_name=conn.company_name, synthetic=books.synthetic, system_of_record="beancount",
        explanation=EXPLANATION, lines=lines, counts=counts,
    )


def _differences(want: list[dict], got: list[dict], amount: Decimal, qbo_amount: Decimal) -> str:
    key = lambda ln: (ln["posting_type"], ln["account_id"])  # noqa: E731
    w = {key(ln): ln["amount"] for ln in want}
    g = {key(ln): ln["amount"] for ln in got}
    parts = []
    for k in sorted(set(w) | set(g)):
        if w.get(k) != g.get(k):
            parts.append(f"{k[0].lower()} to account {k[1]}: ledger ${w.get(k, '0.00')}, QuickBooks ${g.get(k, '0.00')}")
    head = (f"Edited in QuickBooks: totals ledger ${amount}, QuickBooks ${qbo_amount}" if amount != qbo_amount
            else "Edited in QuickBooks: same total, different lines")
    return head + " (" + "; ".join(parts) + "). The ledger is right; correct the QuickBooks entry."
