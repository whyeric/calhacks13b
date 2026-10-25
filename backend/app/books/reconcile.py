"""Three-way reconciliation (spec §9, C5 Part 3). Pure and deterministic; no LLM.

Per settled hedge it compares
  (a) expected payout, recomputed from the market `result` and hedge side (R11),
  (b) the Kalshi cash ledger (the payout entry's Assets:Kalshi:Cash posting),
  (c) the simulated bank statement (rows whose `reference` is the hedge id, summed so a
      split deposit matches; rows with an unknown reference fall back to matching on
      amount, dated within MATCH_WINDOW_DAYS of the settlement).
Exact to the cent. Bank rows that match nothing are flagged `unexplained_bank_row`.
Likely causes: missing_deposit, reversed_sign, duplicate_deposit, fee_deducted_from_deposit,
transposed_digits, deposit_amount_differs (bank side) and ledger_payout_differs (ledger side).
`app.books.benchmark` scores them against planted errors with an answer key.
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
MATCH_WINDOW_DAYS = 3  # an unreferenced deposit may post up to 3 days after settlement


def statement_path(business_id: str) -> Path:
    """Taxi carries the planted mismatch in `fixtures/bank_statement.csv`; others are clean."""
    if business_id == "taxi":
        return FIXTURES_DIR / "bank_statement.csv"
    return FIXTURES_DIR / f"bank_statement_{business_id}.csv"


def has_settlements(business_id: str, engine: Engine | None = None) -> bool:
    """True once any hedge of this business has a simulated settlement or expiry."""
    return bool(_settled(business_id, engine))


def _settled(business_id: str, engine: Engine | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for log in db.list_log(business_id, engine=engine):
        if log.kind in ("settlement", "expired") and log.hedge_id:
            out[log.hedge_id] = {**log.numbers, "decision_id": log.decision_id}
    return out


def _transposed(a: Decimal, b: Decimal) -> bool:
    """True when `b` is `a` with two of its digits swapped (a keying error). Compared in whole
    cents: the difference is a multiple of 9 and exactly two positions hold each other's digit."""
    x, y = str(int(abs(cents(a)) * 100)), str(int(abs(cents(b)) * 100))
    if a == b or len(x) != len(y) or (int(x) - int(y)) % 9:
        return False
    pos = [i for i in range(len(x)) if x[i] != y[i]]
    return len(pos) == 2 and x[pos[0]] == y[pos[1]] and x[pos[1]] == y[pos[0]]


def _mismatch(
    hid: str, ticker: str, exp: Decimal, kal: Decimal, bank: Decimal, fee: Decimal,
    rows: list[Decimal] | None = None,
) -> ReconMismatch:
    """One mismatch with its most likely cause. `rows` are the bank rows referencing `hid`
    (a split deposit is several rows; a duplicate is the same deposit twice)."""
    rows = rows if rows is not None else ([bank] if bank else [])
    if exp != kal:
        pair, diff = "expected_vs_kalshi_ledger", kal - exp
        cause = "ledger_payout_differs"
        if exp == 0:
            explanation = (
                f"Kalshi ledger shows a {usd(kal)} payout for {hid}, but the market resolved against "
                f"the hedge, so nothing should have been paid."
            )
        else:
            explanation = (
                f"Kalshi ledger shows {usd(kal)} for {hid} but the market result implies {usd(exp)}; "
                f"the difference is {'-' if diff < 0 else ''}{usd(diff)}."
            )
        question = f"Should the {hid} payout be corrected from {usd(kal)} to {usd(exp)}?"
    else:
        pair, diff = "kalshi_ledger_vs_bank", bank - kal
        if not rows:
            cause = "missing_deposit"
            explanation = f"No bank deposit found for the {usd(kal)} Kalshi payout on {hid}."
            question = f"Has the {usd(kal)} withdrawal for {hid} reached your bank account?"
        elif kal != 0 and bank == -kal:
            cause = "reversed_sign"
            explanation = (
                f"Bank shows {usd(kal)} going out for {hid}, but the Kalshi payout of {usd(kal)} "
                "should come in; the sign is reversed."
            )
            question = f"Was the {usd(kal)} for {hid} recorded as a withdrawal instead of a deposit?"
        elif kal != 0 and len(rows) >= 2 and all(r == kal for r in rows):
            cause = "duplicate_deposit"
            explanation = (
                f"The {usd(kal)} Kalshi payout for {hid} was deposited {len(rows)} times; "
                f"the bank is {usd(diff)} over."
            )
            question = f"Should the extra {usd(diff)} deposited for {hid} be reversed?"
        elif fee > 0 and diff == -fee:
            cause = "fee_deducted_from_deposit"
            explanation = (
                f"Bank deposit is {usd(diff)} short of the Kalshi payout; "
                f"equals the {usd(fee)} fee recorded for {hid}."
            )
            question = f"Did you authorize the {usd(fee)} fee to be netted from this withdrawal?"
        elif len(rows) == 1 and _transposed(kal, bank):
            cause = "transposed_digits"
            explanation = (
                f"Bank deposit of {usd(bank)} for {hid} is the {usd(kal)} Kalshi payout with two "
                f"digits swapped (difference {usd(diff)}, a multiple of 9)."
            )
            question = f"Was the {usd(kal)} deposit for {hid} keyed as {usd(bank)}?"
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
    rows_by_hedge: dict[str, list[Decimal]] = {}
    unknown: list[dict[str, str]] = []
    opening = entries.get(opening_entry_id(business_id))
    for r in rows:
        amount = cents(Decimal(r["amount"]))
        ref = r["reference"]
        if ref in settled:
            bank_by_hedge[ref] = bank_by_hedge.get(ref, ZERO) + amount
            rows_by_hedge.setdefault(ref, []).append(amount)
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

    # Fallback: an unreferenced row matches a hedge with no bank row on amount, dated within
    # MATCH_WINDOW_DAYS of its settlement (bank postings lag); the closest date wins.
    still_unknown = []
    for r in unknown:
        amount = cents(Decimal(r["amount"]))
        on = date.fromisoformat(r["date"])
        options = sorted(
            (abs((on - date.fromisoformat(str(n["settled_on"]))).days), h)
            for h, n in settled.items()
            if h not in bank_by_hedge and n.get("settled_on") and amount != 0 and kalshi(h) == amount
        )
        if not options or options[0][0] > MATCH_WINDOW_DAYS:
            still_unknown.append(r)
        else:
            hit = options[0][1]
            bank_by_hedge[hit] = amount
            rows_by_hedge[hit] = [amount]

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
            mismatches.append(_mismatch(hid, ticker, exp, kal, bank, fee, rows_by_hedge.get(hid, [])))

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
