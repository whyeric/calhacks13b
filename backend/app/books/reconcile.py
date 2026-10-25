"""Three-way reconciliation (spec §9, C5 Part 3). Pure and deterministic; no LLM.

Three independent records of every settled hedge, each the system of record for one fact:

    venue   what the exchange says it paid, and the fee it charged   (a `VenueSource`)
    ledger  what we booked: the payout entry's venue-cash posting     (Beancount, `ledger.py`)
    bank    what cash actually arrived                                (a `BankSource`)

plus (a) the expected payout recomputed from the market `result` and hedge side (R11), kept as a
sanity check on all three. When they disagree, the mismatch names the source to trust for the
disputed fact and why: the venue for what was paid, the bank for cash received, the ledger for
what we booked. So "Kalshi paid $60.00 and we booked $60.00; the bank received $58.95" is a real
$1.05 cash shortfall (the bank is the record for cash), not a booking error.

Bank rows tie to a hedge by `reference` (summed, so a split deposit matches). Rows with no known
reference fall back to amount (the payout, or the payout net of the venue fee) dated within
MATCH_WINDOW_DAYS of the settlement; banks don't carry our hedge ids. A deposit that hasn't posted
yet is a timing difference, not an error: it is reported `in_transit` while it is pending at the
bank or still within DEPOSIT_WINDOW_DAYS of the settlement, and `missing_deposit` after that.

Likely causes. Venue side: ledger_payout_differs, venue_paid_differs_from_booked,
result_differs_from_venue, venue_record_missing, unbooked_venue_settlement, fee_differs_from_venue.
Bank side: missing_deposit, reversed_sign, duplicate_deposit, fee_deducted_from_deposit,
transposed_digits, deposit_amount_differs, unexplained_bank_row.
`app.books.benchmark` scores them against planted errors with an answer key.

Every row records the origin of its venue and bank legs; `ReconResult.simulated` is true unless
every leg is live (I6). Returns `ReconResult` (R9) and appends one `reconciliation` log event (I5).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine

from app import clock, db
from app.books.ledger import (
    CASH,
    FEES,
    POLYMARKET_CASH,
    VENUE_CASH,
    cents,
    ny_date,
    opening_entry_id,
    payout_entry_id,
    premium_entry_id,
    usd,
)
from app.books.sources import (
    BankRow,
    BankSource,
    CsvBankSource,
    SimulatedVenueSource,
    SourceUnavailable,
    VenueSettlement,
    VenueSource,
    get_venue_source,
    statement_path,  # noqa: F401  (re-exported: callers import it from here)
)
from app.models import (
    LogEntry,
    ReconInTransit,
    ReconMatch,
    ReconMismatch,
    ReconResult,
    ReconSources,
    ReconSummary,
)

ZERO = Decimal("0.00")
MATCH_WINDOW_DAYS = 3  # an unreferenced deposit may post up to 3 days after settlement
DEPOSIT_WINDOW_DAYS = 3  # a deposit not seen yet is "in transit" this long after settlement (ACH T+2, +1)

# Which source to trust for which fact, and why. Quoted on every mismatch.
RECORD_REASON = {
    "venue": "The venue is the record for what was paid and the fee it charged: its settlement is the "
             "exchange's own statement of the position.",
    "bank": "The bank is the record for cash received: only a posted deposit is money in the account.",
    "ledger": "The ledger is the record for what we booked.",
}


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


def _paid_twice(kal: Decimal, rows: list[Decimal]) -> bool:
    """The payout deposited twice, as whole rows or split: the rows sum to 2 x kal and some of
    them (a strict, non-empty subset) sum to exactly kal."""
    if kal == 0 or len(rows) < 2 or sum(rows, ZERO) != 2 * kal:
        return False
    if len(rows) > 12:  # subset search is exponential; real statements never split this much
        return False
    return any(sum(c, ZERO) == kal for k in range(1, len(rows)) for c in combinations(rows, k))


def _signed(x: Decimal) -> str:
    return f"{'-' if x < 0 else ''}{usd(x)}"


def _mismatch(
    hid: str, ticker: str, exp: Decimal, kal: Decimal, bank: Decimal, fee: Decimal,
    rows: list[Decimal] | None = None,
    *,
    venue: Decimal | None = None,
    venue_fee: Decimal | None = None,
    ledger_fee: Decimal | None = None,
    venue_name: str = "Kalshi",
    venue_origin: str | None = None,
    bank_origin: str | None = None,
    pending: bool = False,
) -> ReconMismatch:
    """One mismatch with its most likely cause and the source to trust. `rows` are the bank rows
    tied to `hid` (a split deposit is several rows; a duplicate is the same deposit twice).
    Without `venue` it is the two-way check (expected vs ledger vs bank)."""
    rows = rows if rows is not None else ([bank] if bank else [])
    V = venue_name
    common: dict[str, Any] = dict(
        hedge_id=hid, ticker=ticker, expected=exp, kalshi_ledger=kal, bank=bank, action="ask_owner",
        venue=venue, venue_fee=venue_fee, ledger_fee=ledger_fee,
        venue_origin=venue_origin, bank_origin=bank_origin,
    )
    received = f"the bank received {usd(bank)}" if rows else "the bank has received nothing"

    if venue is not None and venue != kal:  # the venue's own record vs our books
        pair, diff, record = "venue_vs_kalshi_ledger", kal - venue, "venue"
        paid = f"{V} paid {usd(venue)}" if venue else f"{V} paid nothing"
        if kal == exp:
            cause = "venue_paid_differs_from_booked"
            explanation = (
                f"{paid} for {hid}, but we booked {usd(kal)}, the payout the market result implies; "
                f"{received}. {V} is the record for what was paid"
                + (", and the bank agrees with it" if rows and bank == venue else "")
                + f", so the books {'overstate' if diff > 0 else 'understate'} the payout by {usd(diff)}. "
                "Our fill count or side for this hedge may not match the venue's position."
            )
            question = (f"{V} paid {usd(venue)} for {hid}, not the {usd(kal)} we booked; should the payout "
                        f"be corrected to {usd(venue)}, or disputed with {V}?")
        else:
            cause = "ledger_payout_differs"
            explanation = (
                f"{paid} for {hid}"
                + (" (the market resolved against the hedge)" if venue == 0 else "")
                + f", but we booked {usd(kal)}; {received}. {V} is the record for what was paid, so the "
                f"books are {usd(diff)} {'over' if diff > 0 else 'short'}"
                + (f" and {usd(diff)} is likely still in the {V} account" if diff < 0 and rows and bank == kal
                   else "")
                + "."
            )
            question = f"Should the {hid} payout be corrected from {usd(kal)} to {usd(venue)}?"
    elif venue is not None and exp != venue:  # venue and books agree; our recomputation doesn't
        pair, diff, record = "expected_vs_venue", venue - exp, "venue"
        cause = "result_differs_from_venue"
        explanation = (
            f"{V} paid {usd(venue)} for {hid} and we booked {usd(kal)}, but the market result and the hedge's "
            f"side imply {usd(exp)}. {V} is the record for what was paid, so check the hedge's recorded side "
            "and fill count."
        )
        question = f"Is the recorded side and size of {hid} right, given that {V} paid {usd(venue)}?"
    elif venue is None and exp != kal:  # two-way: no venue record read
        pair, diff, record = "expected_vs_kalshi_ledger", kal - exp, "ledger"
        cause = "ledger_payout_differs"
        if exp == 0:
            explanation = (
                f"{V} ledger shows a {usd(kal)} payout for {hid}, but the market resolved against "
                f"the hedge, so nothing should have been paid."
            )
        else:
            explanation = (
                f"{V} ledger shows {usd(kal)} for {hid} but the market result implies {usd(exp)}; "
                f"the difference is {_signed(diff)}."
            )
        question = f"Should the {hid} payout be corrected from {usd(kal)} to {usd(exp)}?"
    else:  # venue and books agree; the bank is the record for cash
        pair, diff, record = "kalshi_ledger_vs_bank", bank - kal, "bank"
        lead = f"{V} paid {usd(kal)} and we booked {usd(kal)}" if venue is not None else f"We booked {usd(kal)}"
        cash = "The bank is the record for cash"
        if not rows:
            cause = "missing_deposit"
            explanation = (f"{lead} for {hid}; the bank has received nothing and the deposit is past its "
                           f"{DEPOSIT_WINDOW_DAYS}-day posting window. {cash}, so the {usd(kal)} has not arrived.")
            question = f"Has the {usd(kal)} withdrawal for {hid} reached your bank account?"
        elif kal != 0 and bank == -kal:
            cause = "reversed_sign"
            explanation = (f"{lead} for {hid}, but the bank shows {usd(kal)} going out; the payout should "
                           "come in, so the sign is reversed.")
            question = f"Was the {usd(kal)} for {hid} recorded as a withdrawal instead of a deposit?"
        elif kal != 0 and len(rows) >= 2 and (all(r == kal for r in rows) or _paid_twice(kal, rows)):
            cause = "duplicate_deposit"
            how = (f"{len(rows)} times" if all(r == kal for r in rows)
                   else f"twice, the second time split across rows ({', '.join(usd(r) for r in rows)})")
            explanation = (f"{lead} for {hid}; the bank received it {how}. {cash}, so the account holds "
                           f"{usd(diff)} more than {V} paid.")
            question = f"Should the extra {usd(diff)} deposited for {hid} be reversed?"
        elif fee > 0 and diff == -fee:
            cause = "fee_deducted_from_deposit"
            explanation = (f"{lead} for {hid}; {received}. {cash}, so the {usd(diff)} is real and equals "
                           f"the {usd(fee)} entry fee: it looks netted from the withdrawal.")
            question = f"Did you authorize the {usd(fee)} fee to be netted from this withdrawal?"
        elif len(rows) == 1 and _transposed(kal, bank):
            cause = "transposed_digits"
            explanation = (f"{lead} for {hid}; {received}, which is {usd(kal)} with two digits swapped "
                           f"(difference {_signed(diff)}, a multiple of 9).")
            question = f"Was the {usd(kal)} deposit for {hid} keyed as {usd(bank)}?"
        else:
            cause = "deposit_amount_differs"
            word = "short of" if diff < 0 else "over"
            explanation = (f"{lead} for {hid}; {received}. {cash}: the deposit is {usd(diff)} {word} the "
                           "payout and no fee explains it.")
            question = f"Do you recognize the {usd(bank)} deposit for {hid}?"
        if pending:
            explanation += " Part of it is still pending at the bank."
    return ReconMismatch(
        **common, difference=cents(diff), source_pair=pair, explanation=explanation, likely_cause=cause,
        question=question, system_of_record=record, record_reason=RECORD_REASON[record],
    )


def _fee_mismatch(hid: str, ticker: str, exp: Decimal, kal: Decimal, bank: Decimal, *, venue: Decimal,
                  venue_fee: Decimal, ledger_fee: Decimal, venue_name: str, venue_origin: str | None,
                  bank_origin: str | None) -> ReconMismatch:
    diff = venue_fee - ledger_fee
    return ReconMismatch(
        hedge_id=hid, ticker=ticker, expected=exp, kalshi_ledger=kal, bank=bank, venue=venue,
        venue_fee=venue_fee, ledger_fee=ledger_fee, difference=cents(diff), source_pair="ledger_fee_vs_venue_fee",
        explanation=(f"{venue_name} charged a {usd(venue_fee)} fee on {hid} but we booked {usd(ledger_fee)}. "
                     f"{venue_name} is the record for the fee it charged, so fee expense is "
                     f"{usd(diff)} {'understated' if diff > 0 else 'overstated'} in the books."),
        likely_cause="fee_differs_from_venue", action="ask_owner",
        question=f"Should the {hid} fee be corrected from {usd(ledger_fee)} to {usd(venue_fee)}?",
        system_of_record="venue", record_reason=RECORD_REASON["venue"],
        venue_origin=venue_origin, bank_origin=bank_origin,
    )


def _default_bank(business_id: str) -> BankSource:
    from app.integrations.increase import get_bank_source

    return get_bank_source(business_id)


def reconcile(
    business_id: str,
    *,
    statement: Path | None = None,
    engine: Engine | None = None,
    log: bool = True,
    bank: BankSource | None = None,
    venue: VenueSource | None = None,
) -> ReconResult:
    """Reconcile venue vs ledger vs bank (with the expected payout as a sanity check). Reads only;
    no source is modified. Same inputs give identical output. `statement` reads that bank CSV;
    otherwise `bank` / `venue` default to the configured sources (Increase or the CSV; simulated venue)."""
    notes: list[str] = []
    if bank is None:
        bank = CsvBankSource(statement) if statement is not None else _default_bank(business_id)
    if venue is None:
        venue = get_venue_source(business_id, engine)
    try:
        rows: list[BankRow] = bank.rows(business_id)
        bank_origin = bank.origin
    except SourceUnavailable as e:
        notes.append(f"Bank: {bank.origin} could not be read ({e}); used the simulated bank statement instead.")
        fallback = CsvBankSource(statement)
        rows, bank_origin = fallback.rows(business_id), fallback.origin
    try:
        venue_rows: list[VenueSettlement] = venue.settlements(business_id)
        venue_origin = venue.origin
    except SourceUnavailable as e:
        notes.append(f"Venue: {venue.origin} could not be read ({e}); used the simulated settlement instead.")
        fallback_v = SimulatedVenueSource(engine)
        venue_rows, venue_origin = fallback_v.settlements(business_id), fallback_v.origin

    entries = {e.id: e for e in db.list_ledger_entries(business_id, engine)}
    settled = _settled(business_id, engine)

    # --- venue records -> hedges (by hedge id, else by ticker) ---
    venue_by_hedge: dict[str, VenueSettlement] = {}
    unbooked: list[VenueSettlement] = []
    for v in venue_rows:
        hid = v.hedge_id if v.hedge_id in settled else next(
            (h for h, n in sorted(settled.items()) if n.get("ticker") == v.ticker and h not in venue_by_hedge), None)
        if hid is None or hid in venue_by_hedge:
            unbooked.append(v)
        else:
            venue_by_hedge[hid] = v

    def expected(n: dict[str, Any]) -> Decimal:
        return cents(Decimal(n["n_filled"])) if n["result"] == n["side"] else ZERO

    def payout_posting(hid: str) -> tuple[Decimal, str]:
        e = entries.get(payout_entry_id(hid))
        p = next((p for p in e.postings if p.account in VENUE_CASH.values()), None) if e else None
        return (p.amount, p.account) if p else (ZERO, CASH)

    def ledger_fee(hid: str) -> Decimal | None:
        e = entries.get(premium_entry_id(hid))
        return next((p.amount for p in e.postings if p.account == FEES), None) if e else None

    def venue_name(hid: str) -> str:
        return "Polymarket" if payout_posting(hid)[1] == POLYMARKET_CASH else "Kalshi"

    def fee_for_cash(hid: str, n: dict[str, Any]) -> Decimal:
        v = venue_by_hedge.get(hid)
        if v is not None:
            return cents(v.fee)
        lf = ledger_fee(hid)
        return cents(lf) if lf is not None else cents(Decimal(str(n.get("fee", "0"))))

    # --- bank rows -> hedges ---
    rows_by_hedge: dict[str, list[BankRow]] = {}
    unknown: list[BankRow] = []
    opening = entries.get(opening_entry_id(business_id))
    opening_out = -next(p.amount for p in opening.postings if p.account == CASH) if opening else None
    opening_seen = False
    for r in rows:
        amount = cents(r.amount)
        if r.reference in settled:
            rows_by_hedge.setdefault(r.reference, []).append(r)
        elif r.reference == "opening_balance" and amount > 0:
            # Owner money already in the account before hedging started (the staged sandbox funds
            # its account this way): the statement's opening balance, not hedge activity.
            notes.append(f"Bank: {usd(amount)} opening balance on {r.date.isoformat()} is outside hedge activity.")
        elif (r.reference == "opening_deposit" or (r.reference is None and not opening_seen)) \
                and opening_out is not None and amount == opening_out and not opening_seen:
            opening_seen = True
        else:
            unknown.append(r)

    # Fallback: an unreferenced row matches a hedge with no bank row on amount (the payout, or the
    # payout net of the venue fee), dated within MATCH_WINDOW_DAYS of its settlement (bank postings
    # lag); the exact payout beats the net amount, then the closest date wins.
    still_unknown: list[BankRow] = []
    for r in unknown:
        amount = cents(r.amount)
        options = []
        for h, n in settled.items():
            kal = payout_posting(h)[0]
            if h in rows_by_hedge or not n.get("settled_on") or amount == 0 or kal == 0:
                continue
            fee = fee_for_cash(h, n)
            rank = 0 if amount == kal else 1 if fee > 0 and amount == kal - fee else None
            if rank is not None:
                options.append((rank, abs((r.date - date.fromisoformat(str(n["settled_on"]))).days), h))
        options.sort()
        if not options or options[0][1] > MATCH_WINDOW_DAYS:
            still_unknown.append(r)
        else:
            rows_by_hedge[options[0][2]] = [r]

    posted_dates = [r.date for r in rows if r.status == "posted"]
    dates = [e.date for e in entries.values()] + posted_dates
    if bank_origin.startswith("increase"):
        dates.append(ny_date(clock.now()))  # a live bank is read as of today
    as_of = max(dates) if dates else date(2026, 1, 1)

    matches: list[ReconMatch] = []
    mismatches: list[ReconMismatch] = []
    in_transit: list[ReconInTransit] = []
    for hid in sorted(settled):
        n = settled[hid]
        exp, (kal, _) = expected(n), payout_posting(hid)
        ticker = str(n.get("ticker", ""))
        v = venue_by_hedge.get(hid)
        vpaid = cents(v.revenue) if v is not None else None
        tied = rows_by_hedge.get(hid, [])
        posted = [cents(r.amount) for r in tied if r.status == "posted"]
        pending = [cents(r.amount) for r in tied if r.status == "pending"]
        bank = sum(posted, ZERO)
        settled_on = date.fromisoformat(str(n["settled_on"])[:10]) if n.get("settled_on") else as_of
        days = (as_of - settled_on).days
        lfee, vfee = ledger_fee(hid), (cents(v.fee) if v is not None else None)
        legs = dict(venue_origin=v.origin if v is not None else None, bank_origin=bank_origin)
        name = venue_name(hid)

        if v is None:
            mismatches.append(ReconMismatch(
                hedge_id=hid, ticker=ticker, expected=exp, kalshi_ledger=kal, bank=bank, venue=ZERO,
                ledger_fee=lfee, difference=kal, source_pair="venue_vs_kalshi_ledger",
                explanation=(f"{name} reports no settlement for {hid}, but we booked {usd(kal)}. {name} is the "
                             "record for what was paid, so the settlement can't be confirmed."),
                likely_cause="venue_record_missing", action="ask_owner",
                question=f"Does {name} show {hid} ({ticker}) as settled?",
                system_of_record="venue", record_reason=RECORD_REASON["venue"],
                venue_origin=venue_origin, bank_origin=bank_origin,
            ))
            continue

        books_ok = vpaid == kal == exp
        if books_ok and vfee is not None and lfee is not None and vfee != cents(lfee):
            mismatches.append(_fee_mismatch(hid, ticker, exp, kal, bank, venue=vpaid, venue_fee=vfee,
                                            ledger_fee=cents(lfee), venue_name=name, **legs))
            continue
        if books_ok and bank == kal and not pending:
            matches.append(ReconMatch(hedge_id=hid, ticker=ticker, expected=exp, kalshi_ledger=kal, bank=bank,
                                      venue=vpaid, **legs))
            continue
        waiting_on_bank = not posted and (sum(pending, ZERO) == kal if pending else days <= DEPOSIT_WINDOW_DAYS)
        if books_ok and kal != 0 and waiting_on_bank:
            seen = sum(pending, ZERO)
            why = (f"the bank shows {usd(seen)} pending" if pending
                   else f"it is {days} day(s) since settlement, inside the {DEPOSIT_WINDOW_DAYS}-day posting window")
            in_transit.append(ReconInTransit(
                hedge_id=hid, ticker=ticker, expected=exp, venue=vpaid, kalshi_ledger=kal, bank_pending=seen,
                settled_on=settled_on, days_outstanding=days, window_days=DEPOSIT_WINDOW_DAYS,
                explanation=(f"{name} paid {usd(vpaid)} and we booked {usd(kal)} for {hid}; the deposit hasn't "
                             f"posted yet, but {why}. A timing difference, not an error: "
                             + ("it becomes cash when the bank posts it." if pending else
                                "it becomes a missing deposit only if it hasn't posted after the window.")),
                **legs,
            ))
            continue
        mismatches.append(_mismatch(
            hid, ticker, exp, kal, bank + sum(pending, ZERO), fee_for_cash(hid, n), posted + pending,
            venue=vpaid, venue_fee=vfee, ledger_fee=cents(lfee) if lfee is not None else None,
            venue_name=name, pending=bool(pending), **legs,
        ))

    for v in unbooked:
        subject = v.hedge_id or v.external_id or v.ticker
        mismatches.append(ReconMismatch(
            hedge_id=subject, ticker=v.ticker, expected=ZERO, kalshi_ledger=ZERO, bank=ZERO, venue=cents(v.revenue),
            venue_fee=cents(v.fee), difference=-cents(v.revenue), source_pair="venue_vs_kalshi_ledger",
            explanation=(f"The venue reports a {usd(v.revenue)} settlement on {v.ticker} ({v.settled_on}) that "
                         "matches no hedge in our books. The venue is the record for what was paid, so it is "
                         "real until shown otherwise."),
            likely_cause="unbooked_venue_settlement", action="ask_owner",
            question=f"Which position is the {usd(v.revenue)} settlement on {v.ticker}?",
            system_of_record="venue", record_reason=RECORD_REASON["venue"],
            venue_origin=v.origin, bank_origin=None,
        ))

    for r in still_unknown:
        amount = cents(r.amount)
        state = "pending " if r.status == "pending" else ""
        mismatches.append(
            ReconMismatch(
                hedge_id=r.reference or r.external_id or f"bank_{r.date.isoformat()}_{amount}",
                ticker="", expected=ZERO, kalshi_ledger=ZERO, bank=amount,
                difference=amount, source_pair="kalshi_ledger_vs_bank",
                explanation=(
                    f"Bank {state}row of {_signed(amount)} on {r.date.isoformat()} ({r.description}) has no "
                    "matching ledger entry or venue settlement. The bank is the record for cash, so the "
                    "money moved; the books don't say why."
                ),
                likely_cause="unexplained_bank_row", action="ask_owner",
                question=f"What is the {usd(amount)} bank row on {r.date.isoformat()}?",
                system_of_record="bank", record_reason=RECORD_REASON["bank"], bank_origin=bank_origin,
            )
        )

    reconciled = [e for e in entries.values()]
    ledger_origin = "beancount_simulated" if any(e.simulated for e in reconciled) else "beancount"
    live = venue_origin == "kalshi_live" and bank_origin == "increase_live" and ledger_origin == "beancount"
    notes += _origin_notes(venue_origin, ledger_origin, bank_origin)
    result = ReconResult(
        business_id=business_id,
        as_of=as_of,
        simulated=not live,
        matches=matches,
        mismatches=mismatches,
        summary=ReconSummary(
            n_matched=len(matches),
            n_mismatched=len(mismatches),
            total_difference=sum((m.difference for m in mismatches), ZERO),
            n_in_transit=len(in_transit),
        ),
        in_transit=in_transit,
        sources=ReconSources(venue_origin=venue_origin, ledger_origin=ledger_origin, bank_origin=bank_origin,
                             live=live, notes=notes),
    )
    if log:
        _log(result, engine)
    return result


def _origin_notes(venue: str, ledger: str, bank: str) -> list[str]:
    return [
        {"simulated": "Venue: SIMULATED settlement derived from the real market result (R11).",
         "kalshi_demo": "Venue: Kalshi demo environment (real API, play money).",
         "kalshi_live": "Venue: Kalshi live portfolio."}[venue],
        {"beancount_simulated": "Ledger: Beancount books; settlement entries are SIMULATED.",
         "beancount": "Ledger: Beancount books."}[ledger],
        {"csv_simulated": "Bank: SIMULATED bank statement (CSV).",
         "increase_sandbox": "Bank: Increase sandbox (real bank API, not real money).",
         "increase_live": "Bank: Increase live account."}[bank],
    ]


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
                "n_in_transit": s.n_in_transit,
                "total_difference": s.total_difference,
                "simulated": result.simulated,
            },
            summary=(
                ("[SIMULATED] " if result.simulated else "")
                + f"Reconciled {result.business_id}: {s.n_matched} matched, {s.n_mismatched} mismatched"
                + (f", {s.n_in_transit} in transit" if s.n_in_transit else "")
                + (f". {first.explanation}" if first else ".")
            ),
        ),
        engine,
    )
