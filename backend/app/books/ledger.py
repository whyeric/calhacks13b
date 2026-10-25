"""Double-entry booking of approved hedges (spec §9, C5 Part 1: never cut).

The database (`ledger_entries`) is the source of truth. After every write the
per-business Beancount file `ledgers/<business>.beancount` is regenerated from it,
so the file is deterministic and re-booking leaves its bytes unchanged. The file is
only written when Beancount is installed (the `books` extra).

Entry shapes (all amounts `Decimal`, 2 dp, postings sum to zero):

    approve     Expenses:Hedging:Premiums  +cost
                Expenses:Hedging:Fees      +fee
                Assets:Kalshi:Cash         -premium      (premium = cost + fee)
    win         Assets:Kalshi:Cash         +N x $1.00    [SIMULATED]  (settlement.py)
                Income:Hedging:Payouts     -N x $1.00
    withdrawal  Assets:Bank:Checking       +amount       [SIMULATED]  (settlement.py)
                Assets:Kalshi:Cash         -amount
    opening     Assets:Kalshi:Cash         +500.00       [SIMULATED]
                Assets:Bank:Checking       -500.00

Entry ids are derived from the hedge id, which is what makes booking idempotent.

Public entry points:
    book_approval(hedge, actor) -> list[str]         # API contract (#15); hedge already approved
    approve_hedge(hedge, actor, at=) -> (Hedge, entries)  # proposed/pending -> approved + booked
    book_entries(hedge) -> list[LedgerEntry]         # same booking, returns the entries
    book_hedge(hedge, approval) -> list[str]         # ACCEPTANCE.md signature
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.engine import Engine

from app import db
from app.config import get_settings
from app.models import ApproveRequest, Hedge, LedgerEntry, LedgerMeta, LogEntry, Posting

CENT = Decimal("0.01")
NY = ZoneInfo("America/New_York")

CASH = "Assets:Kalshi:Cash"
POLYMARKET_CASH = "Assets:Polymarket:Cash"  # a Polymarket hedge's premium and payout (markets/polymarket.py)
VENUE_CASH = {"kalshi": CASH, "polymarket": POLYMARKET_CASH}
BANK = "Assets:Bank:Checking"
PREMIUMS = "Expenses:Hedging:Premiums"
FEES = "Expenses:Hedging:Fees"
PAYOUTS = "Income:Hedging:Payouts"
ACCOUNTS = (CASH, BANK, PREMIUMS, FEES, PAYOUTS)
EXTRA_ACCOUNTS = (POLYMARKET_CASH,)  # opened in the Beancount file only once a posting uses them
OPEN_DATE = date(2026, 1, 1)

OPENING_DEPOSIT = Decimal("500.00")  # simulated funding of the Kalshi account (ACCEPTANCE gap 2)
TAKER_FEE_RATE = Decimal("0.07")


class BookingRefused(ValueError):
    """Refused booking: not approved, not approved by the owner, or inconsistent amounts."""


BookingError = BookingRefused  # older name


# --- Small helpers -------------------------------------------------------------


def cents(x: Decimal) -> Decimal:
    if isinstance(x, float):  # never let a float in (C5-A16)
        raise TypeError("money must be Decimal, never float")
    return Decimal(x).quantize(CENT)


def taker_fee(contracts: int, price: Decimal) -> Decimal:
    """Kalshi taker fee `0.07 x C x P x (1 - P)`, rounded UP to the cent (spec §7)."""
    if isinstance(price, float):
        raise TypeError("price must be Decimal, never float")
    raw = TAKER_FEE_RATE * Decimal(contracts) * price * (1 - price)
    return raw.quantize(CENT, rounding=ROUND_CEILING)


def usd(x: Decimal) -> str:
    return f"${cents(abs(x))}"


def premium_entry_id(hedge_id: str) -> str:
    return f"le_{hedge_id}_premium"


def payout_entry_id(hedge_id: str) -> str:
    return f"le_{hedge_id}_payout"


def opening_entry_id(business_id: str, venue: str = "kalshi") -> str:
    return f"le_{business_id}_opening" if venue == "kalshi" else f"le_{business_id}_opening_{venue}"


def withdrawal_entry_id(business_id: str, on: date, hedge_ids: list[str]) -> str:
    key = hashlib.sha1(",".join(sorted(hedge_ids)).encode()).hexdigest()[:8]
    return f"le_{business_id}_wd_{on.isoformat()}_{key}"


def ny_date(ts: datetime) -> date:
    return ts.astimezone(NY).date()


def _beancount_available() -> bool:
    try:
        import beancount  # noqa: F401
    except ImportError:
        return False
    return True


# --- Period lock (books/close.py) --------------------------------------------------

CLOSES_KEY = "period_closes"  # analysis-cache key holding the business's PeriodClose records


def locked_through(business_id: str, engine: Engine | None = None) -> date | None:
    closes = db.get_analysis(business_id, CLOSES_KEY, engine) or []
    return max((date.fromisoformat(c["through"]) for c in closes), default=None)


def posting_date(business_id: str, on: date, engine: Engine | None = None) -> tuple[date, str]:
    """(date to book on, narration suffix). Nothing is dated inside a closed period: a late item
    lands on the first open day and says which closed date it belongs to."""
    lock = locked_through(business_id, engine)
    if lock is None or on > lock:
        return on, ""
    return lock + timedelta(days=1), f" [belongs to {on.isoformat()}; books closed through {lock.isoformat()}]"


def get_entry(business_id: str, entry_id: str, engine: Engine | None = None) -> LedgerEntry | None:
    for e in db.list_ledger_entries(business_id, engine):
        if e.id == entry_id:
            return e
    return None


# --- Opening deposit -------------------------------------------------------------


def ensure_opening_deposit(
    business_id: str,
    on: date,
    engine: Engine | None = None,
    amount: Decimal = OPENING_DEPOSIT,
    venue: str = "kalshi",
) -> LedgerEntry:
    """Labeled simulated funding of the venue's cash account; created once per business and venue."""
    existing = get_entry(business_id, opening_entry_id(business_id, venue), engine)
    if existing is not None:
        return existing
    amount = cents(amount)
    entry = LedgerEntry(
        id=opening_entry_id(business_id, venue),
        business_id=business_id,
        date=on,
        kind="opening_deposit",
        narration=f"[SIMULATED] Opening deposit to {venue.capitalize()}",
        postings=[Posting(account=VENUE_CASH[venue], amount=amount), Posting(account=BANK, amount=-amount)],
        meta=None,
        simulated=True,
    )
    db.put_ledger_entry(entry, engine)
    return entry


# --- Booking on approval (never cut) ----------------------------------------------


def _check_bookable(hedge: Hedge) -> tuple[str, Decimal, Decimal, Decimal]:
    if hedge.status not in ("approved", "settled"):
        raise BookingRefused(f"{hedge.id} is {hedge.status}; only approved hedges are booked")
    if hedge.decided_by != "owner":
        raise BookingRefused(f"{hedge.id} was not approved by the owner (I4)")
    if hedge.ticker is None or hedge.cost is None or hedge.fee is None or hedge.premium is None:
        raise BookingRefused(f"{hedge.id} has no market or sizing to book")
    if hedge.n_filled <= 0:
        raise BookingRefused(f"{hedge.id} has no filled contracts")
    cost, fee, premium = cents(hedge.cost), cents(hedge.fee), cents(hedge.premium)
    if cost + fee != premium:
        raise BookingRefused(f"{hedge.id}: cost {cost} + fee {fee} != premium {premium}")
    return hedge.ticker, cost, fee, premium


def hedge_meta(hedge: Hedge) -> LedgerMeta:
    return LedgerMeta(
        hedge_id=hedge.id, ticker=hedge.ticker or "", decision_id=hedge.decision.id, approved_by="owner"
    )


def book_entries(
    hedge: Hedge,
    *,
    engine: Engine | None = None,
    ledger_dir: Path | None = None,
    on: date | None = None,
    simulated: bool = False,
) -> list[LedgerEntry]:
    """Book an owner-approved hedge: premium + fee debited, Kalshi cash credited.

    `hedge.status` must be "approved" and `hedge.decided_by` "owner", else BookingRefused and
    nothing is written. Books the filled N (partial fills book what filled). Dated the
    approval day in America/New_York unless `on` is given.

    Idempotent per hedge: if the premium entry already exists it is returned unchanged and
    nothing is written. Returns the hedge's entries (one premium entry, id
    `premium_entry_id(hedge.id)`). Persists via `db.put_ledger_entry`, appends a `booking`
    log event (I5, timed 1 s after the approval so it sorts after the route's `approval`
    event), and rewrites `ledgers/<business>.beancount`. `simulated=True` labels a demo
    stand-in hedge (I6).
    """
    ticker, cost, fee, premium = _check_bookable(hedge)
    existing = get_entry(hedge.business_id, premium_entry_id(hedge.id), engine)
    if existing is not None:
        return [existing]

    booked_on = on or (ny_date(hedge.decided_at) if hedge.decided_at else datetime.now(NY).date())
    booked_on, late = posting_date(hedge.business_id, booked_on, engine)
    ensure_opening_deposit(hedge.business_id, booked_on, engine, venue=hedge.venue)
    where = "" if hedge.venue == "kalshi" else f" ({hedge.venue.capitalize()})"
    entry = LedgerEntry(
        id=premium_entry_id(hedge.id),
        business_id=hedge.business_id,
        date=booked_on,
        kind="premium",
        narration=("[SIMULATED] " if simulated else "") + f"Premium{where}: {ticker} {hedge.side.upper()} x {hedge.n_filled}"
        + late,
        postings=[
            Posting(account=PREMIUMS, amount=cost),
            Posting(account=FEES, amount=fee),
            Posting(account=VENUE_CASH[hedge.venue], amount=-premium),
        ],
        meta=hedge_meta(hedge),
        simulated=simulated,
    )
    db.put_ledger_entry(entry, engine)
    at = hedge.decided_at or datetime.combine(booked_on, datetime.min.time(), UTC)
    db.append_log(
        LogEntry(
            log_id=f"log_book_{hedge.id}",
            business_id=hedge.business_id,
            kind="booking",
            created_at=at + timedelta(seconds=1),
            actor="system",
            agent=None,
            hedge_id=hedge.id,
            decision_id=hedge.decision.id,
            run_id=None,
            status="approved",
            checks=[],
            reasons=[],
            numbers={"n_filled": hedge.n_filled, "cost": cost, "fee": fee, "premium": premium},
            summary=(
                f"Booked {hedge.id}: {hedge.n_filled} {hedge.side.upper()} contracts on {ticker}, "
                f"{usd(cost)} cost + {usd(fee)} fee = {usd(premium)} premium."
            ),
        ),
        engine,
    )
    write_ledger(hedge.business_id, engine=engine, ledger_dir=ledger_dir)
    return [entry]


def book_approval(
    hedge: Hedge,
    actor: str | None,
    *,
    engine: Engine | None = None,
    ledger_dir: Path | None = None,
    simulated: bool = False,
) -> list[str]:
    """The API contract (#15): book an approved hedge, return its ledger entry ids.

    Raises BookingRefused unless `actor == "owner"` and the hedge is approved by the owner
    (I4); nothing is written then. Idempotent per hedge. See `book_entries`.
    """
    if actor != "owner":
        raise BookingRefused("only the owner can approve a hedge (I4)")
    entries = book_entries(hedge, engine=engine, ledger_dir=ledger_dir, simulated=simulated)
    return [e.id for e in entries]


def approve_hedge(
    hedge: Hedge,
    actor: str | None,
    *,
    at: datetime | None = None,
    engine: Engine | None = None,
    ledger_dir: Path | None = None,
    simulated: bool = False,
) -> tuple[Hedge, list[LedgerEntry]]:
    """Owner approval of a proposed/pending hedge: returns the approved Hedge (status
    approved, decided_by owner, `ledger_entry_ids` filled in, alternative cleared; saved via
    `db.put_hedge`) and its ledger entries. Books through the module-level `book_approval`
    (so tests can patch it); if booking raises, the stored hedge is unchanged.

    Raises BookingRefused if `actor != "owner"` (I4) or the hedge is not awaiting approval.
    Already-approved hedges are re-booked idempotently. Does not write the `approval` log
    event; the route does that.
    """
    if actor != "owner":
        raise BookingRefused("only the owner can approve a hedge (I4)")
    kw: dict[str, Any] = {k: v for k, v in (("engine", engine), ("ledger_dir", ledger_dir)) if v is not None}
    if simulated:
        kw["simulated"] = True
    if hedge.status in ("approved", "settled"):
        ids = book_approval(hedge, "owner", **kw)
    elif hedge.status in ("proposed", "pending_approval"):
        data: dict[str, Any] = hedge.model_dump()
        data.update(
            status="approved",
            decided_by="owner",
            decided_at=at or datetime.now(UTC),
            alternative=None,
            ledger_entry_ids=[premium_entry_id(hedge.id)],
        )
        hedge = Hedge.model_validate(data)
        ids = book_approval(hedge, "owner", **kw)
        hedge = hedge.model_copy(update={"ledger_entry_ids": ids})
        db.put_hedge(hedge, engine)
    else:
        raise BookingRefused(f"{hedge.id} is {hedge.status}; it cannot be approved")
    entries = [e for i in ids if (e := get_entry(hedge.business_id, i, engine)) is not None]
    return hedge, entries


def book_hedge(
    hedge: Hedge,
    approval: ApproveRequest,
    *,
    engine: Engine | None = None,
    ledger_dir: Path | None = None,
) -> list[str]:
    """ACCEPTANCE.md signature: entry ids for an approved hedge; raises unless owner."""
    return book_approval(hedge, approval.actor, engine=engine, ledger_dir=ledger_dir)


# --- Beancount text -----------------------------------------------------------------


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _entry_text(e: LedgerEntry) -> list[str]:
    lines = [f"{e.date.isoformat()} * {_q('Hedge Desk')} {_q(e.narration)}", f"  entry_id: {_q(e.id)}"]
    if e.meta is not None:
        for key in ("hedge_id", "ticker", "decision_id", "approved_by"):
            lines.append(f"  {key}: {_q(getattr(e.meta, key))}")
    if e.simulated:
        lines.append(f"  simulated: {_q('true')}")
    width = 28
    for p in e.postings:
        lines.append(f"  {p.account.ljust(width)}{str(cents(p.amount)).rjust(10)} USD")
    return lines


def _notes(business_id: str, engine: Engine | None) -> list[tuple[date, str, list[str]]]:
    """Beancount `note` directives for hedges that expired worthless (from the log)."""
    out = []
    for log in db.list_log(business_id, engine=engine):
        if log.kind != "expired" or log.hedge_id is None:
            continue
        on = date.fromisoformat(str(log.numbers.get("settled_on")))
        lines = [
            f"{on.isoformat()} note {CASH} {_q('[SIMULATED] ' + log.summary)}",
            f"  hedge_id: {_q(log.hedge_id)}",
            f"  simulated: {_q('true')}",
        ]
        out.append((on, log.hedge_id, lines))
    return sorted(out, key=lambda t: (t[0], t[1]))


def render_ledger(business_id: str, engine: Engine | None = None) -> str:
    """Deterministic Beancount text for one business, from the database."""
    head = [
        f"; Hedge Desk ledger: {business_id}. Generated from the app database; do not edit.",
        "; Entries marked [SIMULATED] / simulated: \"true\" are simulated from real Kalshi results;",
        "; the desk never places real orders.",
        f'option "title" {_q("Hedge Desk: " + business_id)}',
        'option "operating_currency" "USD"',
        "",
    ]
    entries = db.list_ledger_entries(business_id, engine)
    used = {p.account for e in entries for p in e.postings}
    head += [f"{OPEN_DATE.isoformat()} open {a} USD" for a in ACCOUNTS + tuple(a for a in EXTRA_ACCOUNTS if a in used)]
    blocks: list[tuple[date, int, str, list[str]]] = [(e.date, 0, e.id, _entry_text(e)) for e in entries]
    blocks += [(on, 1, hid, lines) for on, hid, lines in _notes(business_id, engine)]
    blocks.sort(key=lambda b: (b[0], b[1], b[2]))
    body: list[str] = []
    for *_, lines in blocks:
        body += [""] + lines
    return "\n".join(head + body) + "\n"


def ledger_path(business_id: str, ledger_dir: Path | None = None) -> Path:
    return Path(ledger_dir or get_settings().ledgers_dir) / f"{business_id}.beancount"


def write_ledger(business_id: str, *, engine: Engine | None = None, ledger_dir: Path | None = None) -> Path | None:
    """Rewrite ledgers/<business>.beancount if Beancount is installed; else no-op (db only).
    Skips the write when the bytes would not change."""
    if not _beancount_available():
        return None
    path = ledger_path(business_id, ledger_dir)
    text = render_ledger(business_id, engine)
    if not path.exists() or path.read_text() != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return path


def load_ledger(business_id: str, ledger_dir: Path | None = None) -> list[Any]:
    """Parse the Beancount file; raises ValueError on any parse/validation error."""
    from beancount import loader

    entries, errors, _ = loader.load_file(str(ledger_path(business_id, ledger_dir)))
    if errors:
        raise ValueError("; ".join(str(getattr(e, "message", e)) for e in errors))
    return entries


__all__ = ["BookingRefused", "approve_hedge", "book_approval", "book_entries", "ledger_path", "load_ledger"]
