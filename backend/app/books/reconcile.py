"""Three-way reconciliation (spec §9, C5 Part 3). Pure and deterministic; no LLM.

Per settled hedge it compares
  (a) expected payout, recomputed from the market `result` and hedge side (R11),
  (b) the Kalshi cash ledger (the payout entry's Assets:Kalshi:Cash posting),
  (c) the simulated bank statement (rows whose `reference` is the hedge id; rows with
      an unknown reference fall back to matching on date + amount).
Exact to the cent. Bank rows that match nothing are flagged `unexplained_bank_row`.
Returns `ReconResult` (R9) and appends one `reconciliation` log event (I5).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine

from app import db
from app.books.ledger import CASH, cents, opening_entry_id, payout_entry_id, usd
from app.books.settlement import read_bank_statement
from app.config import FIXTURES_DIR
from app.models import LogEntry, ReconMatch, ReconMismatch, ReconResult, ReconSummary

ZERO = Decimal("0.00")


def statement_path(business_id: str) -> Path:
    """Taxi carries the planted mismatch in `fixtures/bank_statement.csv`; others are clean."""
    if business_id == "taxi":
        return FIXTURES_DIR / "bank_statement.csv"
    return FIXTURES_DIR / f"bank_statement_{business_id}.csv"


def _settled(business_id: str, engine: Engine | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for log in db.list_log(business_id, engine=engine):
        if log.kind in ("settlement", "expired") and log.hedge_id:
            out[log.hedge_id] = {**log.numbers, "decision_id": log.decision_id}
    return out


def _mismatch(hid: str, ticker: str, exp: Decimal, kal: Decimal, bank: Decimal, fee: Decimal) -> ReconMismatch:
    if exp != kal:
        pair, diff = "expected_vs_kalshi_ledger", kal - exp
        cause = "ledger_payout_differs"
        explanation = (
            f"Kalshi ledger shows {usd(kal)} for {hid} but the market result implies {usd(exp)}; "
            f"the difference is {'-' if diff < 0 else ''}{usd(diff)}."
        )
        question = f"Should the {hid} payout be corrected from {usd(kal)} to {usd(exp)}?"
    else:
        pair, diff = "kalshi_ledger_vs_bank", bank - kal
        if fee > 0 and diff == -fee:
            cause = "fee_deducted_from_deposit"
            explanation = (
                f"Bank deposit is {usd(diff)} short of the Kalshi payout; "
                f"equals the {usd(fee)} fee recorded for {hid}."
            )
            question = f"Did you authorize the {usd(fee)} fee to be netted from this withdrawal?"
        elif bank == 0:
            cause = "missing_deposit"
            explanation = f"No bank deposit found for the {usd(kal)} Kalshi payout on {hid}."
            question = f"Has the {usd(kal)} withdrawal for {hid} reached your bank account?"
        else:
            cause = "deposit_amount_differs"
            word = "short of" if diff < 0 else "over"
            explanation = f"Bank deposit is {usd(diff)} {word} the {usd(kal)} Kalshi payout for {hid}."
            question = f"Do you recognize the {usd(bank)} deposit for {hid}?"
    return ReconMismatch(
        hedge_id=hid, ticker=ticker, expected=exp, kalshi_ledger=kal, bank=bank, difference=cents(diff),
        source_pair=pair, explanation=explanation, likely_cause=cause, action="ask_owner", question=question,
    )


def reconcile(
    business_id: str,
    *,
    statement: Path | None = None,
    engine: Engine | None = None,
    log: bool = True,
) -> ReconResult:
    """Reconcile expected payouts vs the Kalshi cash ledger vs the bank CSV. Reads only;
    the ledger and CSV are never modified. Same inputs give identical output."""
    path = statement or statement_path(business_id)
    rows = read_bank_statement(path) if path.exists() else []
    entries = {e.id: e for e in db.list_ledger_entries(business_id, engine)}
    settled = _settled(business_id, engine)

    bank_by_hedge: dict[str, Decimal] = {}
    unknown: list[dict[str, str]] = []
    opening = entries.get(opening_entry_id(business_id))
    for r in rows:
        amount = cents(Decimal(r["amount"]))
        ref = r["reference"]
        if ref in settled:
            bank_by_hedge[ref] = bank_by_hedge.get(ref, ZERO) + amount
        elif ref == "opening_deposit" and opening is not None and amount == -next(
            p.amount for p in opening.postings if p.account == CASH
        ):
            continue
        else:
            unknown.append(r)

    def expected(n: dict[str, Any]) -> Decimal:
        return cents(Decimal(n["n_filled"])) if n["result"] == n["side"] else ZERO

    def kalshi(hid: str) -> Decimal:
        e = entries.get(payout_entry_id(hid))
        return next((p.amount for p in e.postings if p.account == CASH), ZERO) if e else ZERO

    # Fallback: an unreferenced row matches a hedge with no bank row on date + amount.
    still_unknown = []
    for r in unknown:
        amount = cents(Decimal(r["amount"]))
        hit = next(
            (h for h, n in sorted(settled.items())
             if h not in bank_by_hedge and n.get("settled_on") == r["date"] and kalshi(h) == amount),
            None,
        )
        if hit is None:
            still_unknown.append(r)
        else:
            bank_by_hedge[hit] = amount

    matches: list[ReconMatch] = []
    mismatches: list[ReconMismatch] = []
    for hid in sorted(settled):
        n = settled[hid]
        exp, kal, bank = expected(n), kalshi(hid), bank_by_hedge.get(hid, ZERO)
        ticker = str(n.get("ticker", ""))
        if exp == kal == bank:
            matches.append(ReconMatch(hedge_id=hid, ticker=ticker, expected=exp, kalshi_ledger=kal, bank=bank))
        else:
            fee = cents(Decimal(str(n.get("fee", "0"))))
            mismatches.append(_mismatch(hid, ticker, exp, kal, bank, fee))

    for r in still_unknown:
        amount = cents(Decimal(r["amount"]))
        mismatches.append(
            ReconMismatch(
                hedge_id=r["reference"], ticker="", expected=ZERO, kalshi_ledger=ZERO, bank=amount,
                difference=amount, source_pair="kalshi_ledger_vs_bank",
                explanation=(
                    f"Bank row of {'-' if amount < 0 else ''}{usd(amount)} on {r['date']} "
                    f"({r['description']}) has no matching Kalshi ledger entry."
                ),
                likely_cause="unexplained_bank_row", action="ask_owner",
                question=f"What is the {usd(amount)} bank row on {r['date']}?",
            )
        )

    dates = [e.date for e in entries.values()] + [date.fromisoformat(r["date"]) for r in rows]
    as_of = max(dates) if dates else date(2026, 1, 1)
    result = ReconResult(
        business_id=business_id,
        as_of=as_of,
        simulated=True,
        matches=matches,
        mismatches=mismatches,
        summary=ReconSummary(
            n_matched=len(matches),
            n_mismatched=len(mismatches),
            total_difference=sum((m.difference for m in mismatches), ZERO),
        ),
    )
    if log:
        _log(result, engine)
    return result


def _log(result: ReconResult, engine: Engine | None) -> None:
    digest = hashlib.sha1(result.model_dump_json().encode()).hexdigest()[:10]
    s = result.summary
    first = result.mismatches[0] if result.mismatches else None
    db.append_log(
        LogEntry(
            log_id=f"log_recon_{result.business_id}_{digest}",
            business_id=result.business_id,
            kind="reconciliation",
            created_at=datetime.combine(result.as_of, time(23, 0), UTC),
            actor="system",
            agent=None,
            hedge_id=first.hedge_id if first else None,
            decision_id=None,
            run_id=None,
            status=None,
            checks=[],
            reasons=[],
            numbers={
                "n_matched": s.n_matched,
                "n_mismatched": s.n_mismatched,
                "total_difference": s.total_difference,
                "simulated": True,
            },
            summary=(
                f"[SIMULATED] Reconciled {result.business_id}: {s.n_matched} matched, "
                f"{s.n_mismatched} mismatched" + (f". {first.explanation}" if first else ".")
            ),
        ),
        engine,
    )
