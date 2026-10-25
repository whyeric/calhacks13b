"""Simulated settlement, withdrawal and bank statement (spec §9, C5 Part 2).

We never trade, so settlements are SIMULATED from real Kalshi market results (R11):
the hedge wins iff `market.result == hedge.side`; payout = n_filled x $1.00; no fee at
settlement (the taker fee was paid at entry, spec §7). Every entry, log event and bank
row produced here is labeled simulated (I6).
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.engine import Engine

from app import db
from app.books.ledger import (
    BANK,
    CASH,
    VENUE_CASH,
    PAYOUTS,
    BookingError,
    cents,
    get_entry,
    hedge_meta,
    opening_entry_id,
    payout_entry_id,
    posting_date,
    usd,
    withdrawal_entry_id,
    write_ledger,
)
from app.models import Hedge, LedgerEntry, LogEntry, Posting

ONE_DOLLAR = Decimal("1.00")
BANK_COLUMNS = ("date", "description", "amount", "currency", "reference", "simulated")


class SettlementRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hedge_id: str
    business_id: str
    ticker: str
    decision_id: str
    side: Literal["yes", "no"]
    result: Literal["yes", "no"]  # Kalshi's own value (R11)
    won: bool
    n_filled: int
    payout: Decimal
    fee: Decimal
    settled_on: date
    simulated: Literal[True] = True


def _settled_on(market: dict[str, Any]) -> date:
    for key in ("settled_on", "settlement_ts", "close_time", "expiration_time"):
        if market.get(key):
            v = str(market[key])
            return date.fromisoformat(v[:10])
    raise ValueError(f"market {market.get('ticker')} has no close/settlement date")


def simulate_settlement(hedge: Hedge, market: dict[str, Any]) -> SettlementRecord:
    """Outcome for `hedge` from the real market `result` ("yes"/"no"); flagged simulated."""
    result = market.get("result")
    if result not in ("yes", "no"):
        raise ValueError(f"market {market.get('ticker')} is not settled (result={result!r})")
    if hedge.ticker is None or market.get("ticker") not in (None, hedge.ticker):
        raise ValueError(f"market {market.get('ticker')} does not match hedge ticker {hedge.ticker}")
    won = result == hedge.side
    return SettlementRecord(
        hedge_id=hedge.id,
        business_id=hedge.business_id,
        ticker=hedge.ticker,
        decision_id=hedge.decision.id,
        side=hedge.side,
        result=result,
        won=won,
        n_filled=hedge.n_filled,
        payout=cents(ONE_DOLLAR * hedge.n_filled) if won else Decimal("0.00"),
        fee=cents(hedge.fee or Decimal("0")),
        settled_on=_settled_on(market),
    )


def _log_at(on: date) -> datetime:
    return datetime.combine(on, time(21, 0), UTC)


def book_settlement(
    hedge: Hedge,
    market: dict[str, Any],
    *,
    engine: Engine | None = None,
    ledger_dir: Path | None = None,
) -> list[LedgerEntry]:
    """Book the simulated settlement of an approved hedge. Win: payout txn (Kalshi cash
    +N, Income:Hedging:Payouts -N), log `settlement`. Loss: no cash posting, log `expired`
    and a Beancount `note`. Idempotent per hedge. Returns the new/existing payout entry,
    or [] on a loss."""
    if hedge.status not in ("approved", "settled") or hedge.decided_by != "owner":
        raise BookingError(f"{hedge.id} is {hedge.status}; only approved hedges settle")
    rec = simulate_settlement(hedge, market)
    numbers: dict[str, Any] = {
        "ticker": rec.ticker,
        "n_filled": rec.n_filled,
        "payout": rec.payout,
        "fee": rec.fee,
        "settled_on": rec.settled_on.isoformat(),
        "result": rec.result,
        "side": rec.side,
        "simulated": True,
    }
    entries: list[LedgerEntry] = []
    if rec.won:
        existing = get_entry(hedge.business_id, payout_entry_id(hedge.id), engine)
        if existing is not None:
            return [existing]
        on, late = posting_date(hedge.business_id, rec.settled_on, engine)
        entry = LedgerEntry(
            id=payout_entry_id(hedge.id),
            business_id=hedge.business_id,
            date=on,
            kind="payout",
            narration=f"[SIMULATED] Payout: {rec.ticker} {rec.side.upper()} x {rec.n_filled}{late}",
            postings=[Posting(account=VENUE_CASH[hedge.venue], amount=rec.payout),
                      Posting(account=PAYOUTS, amount=-rec.payout)],
            meta=hedge_meta(hedge),
            simulated=True,
        )
        db.put_ledger_entry(entry, engine)
        entries = [entry]
        kind, summary = "settlement", (
            f"Simulated settlement of {hedge.id}: market resolved {rec.result.upper()}, "
            f"{rec.n_filled} {rec.side.upper()} contracts pay {usd(rec.payout)}."
        )
    else:
        kind, summary = "expired", (
            f"Simulated settlement of {hedge.id}: market resolved {rec.result.upper()}, "
            f"{rec.n_filled} {rec.side.upper()} contracts expired worthless; no cash entry."
        )
    db.append_log(
        LogEntry(
            log_id=f"log_settle_{hedge.id}",
            business_id=hedge.business_id,
            kind=kind,
            created_at=_log_at(rec.settled_on),
            actor="system",
            agent=None,
            hedge_id=hedge.id,
            decision_id=hedge.decision.id,
            run_id=None,
            status="settled",
            checks=[],
            reasons=[],
            numbers=numbers,
            summary=summary,
        ),
        engine,
    )
    write_ledger(hedge.business_id, engine=engine, ledger_dir=ledger_dir)
    return entries


def book_withdrawal(
    business_id: str,
    amount: Decimal,
    on: date,
    hedge_ids: list[str],
    *,
    engine: Engine | None = None,
    ledger_dir: Path | None = None,
    venue: str = "kalshi",
) -> LedgerEntry:
    """Simulated transfer of venue cash to the bank: debit Bank:Checking, credit the venue's cash."""
    amount = cents(amount)
    entry_id = withdrawal_entry_id(business_id, on, hedge_ids)
    existing = get_entry(business_id, entry_id, engine)
    if existing is not None:
        return existing
    booked_on, late = posting_date(business_id, on, engine)
    entry = LedgerEntry(
        id=entry_id,
        business_id=business_id,
        date=booked_on,
        kind="withdrawal",
        narration=f"[SIMULATED] Withdrawal to bank: {', '.join(hedge_ids)}{late}",
        postings=[Posting(account=BANK, amount=amount), Posting(account=VENUE_CASH[venue], amount=-amount)],
        meta=None,
        simulated=True,
    )
    db.put_ledger_entry(entry, engine)
    write_ledger(business_id, engine=engine, ledger_dir=ledger_dir)
    return entry


# --- Simulated bank statement ----------------------------------------------------------


def generate_bank_statement(
    business_id: str,
    settlements: list[SettlementRecord],
    *,
    plant_hedge_id: str | None = None,
    engine: Engine | None = None,
) -> str:
    """CSV text of the simulated bank statement: the opening deposit out of the bank and one
    deposit per winning hedge (reference = hedge_id, `simulated=true` on every row).

    ANSWER KEY (planted mismatch): if `plant_hedge_id` is given, that hedge's deposit is
    written SHORT BY ITS ENTRY FEE (e.g. 60.00 payout -> 58.95 deposited when the fee was
    1.05), as if the fee had been netted from the withdrawal. The reconciler must flag
    exactly that row with difference == -fee and likely_cause fee_deducted_from_deposit.
    """
    rows: list[tuple[str, str, str, str, str, str]] = []
    opening = get_entry(business_id, opening_entry_id(business_id), engine)
    if opening is not None:
        out = -next(p.amount for p in opening.postings if p.account == CASH)
        rows.append(
            (opening.date.isoformat(), "SIMULATED transfer to Kalshi (opening deposit)", str(cents(out)), "USD",
             "opening_deposit", "true")
        )
    planted = False
    for s in sorted(settlements, key=lambda r: (r.settled_on, r.hedge_id)):
        if not s.won:
            continue
        amount = s.payout
        if s.hedge_id == plant_hedge_id:
            amount = s.payout - s.fee  # the plant: deposit short by the fee
            planted = True
        rows.append(
            (s.settled_on.isoformat(), f"SIMULATED Kalshi withdrawal {s.ticker}", str(cents(amount)), "USD",
             s.hedge_id, "true")
        )
    if plant_hedge_id is not None and not planted:
        raise ValueError(f"cannot plant on {plant_hedge_id}: not a winning settlement")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(BANK_COLUMNS)
    w.writerows(rows)
    return buf.getvalue()


def read_bank_statement(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]
