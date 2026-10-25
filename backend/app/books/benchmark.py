"""Planted-error benchmark for three-way reconciliation ("proof it works" with an answer key).

Builds a SIMULATED world in a throwaway SQLite database: 26 owner-approved hedges on
fictional markets (`SIM-…` tickers), settled, booked, and paid out to a generated bank
statement, with a simulated venue record of what Kalshi paid. Seventeen errors are planted
across the three sources (venue, ledger, bank): the bank short by the fee, duplicated (once as
two equal rows, once split across two rows), digits swapped, sign reversed, missing past the
posting window, a payout booked wrong, the venue paying less than we booked, the venue's fee
differing from ours, and unexplained bank rows. Seven traps look odd but are correct: a split
deposit, a late deposit, an unreferenced deposit two days late, two hedges that expired
worthless, and two deposits in transit (one not posted yet, one pending at the bank), which
must be reported `in_transit` rather than just left unflagged. Then the real `reconcile()`
runs on it, unchanged, and is scored against the answer key:

    recall          planted errors flagged / planted errors
    cause accuracy  planted errors flagged with the expected likely_cause / planted errors
    precision       flags on planted errors / all flags
    false flags     flags on anything the answer key says is fine

Deterministic: same seed, same world, same score. Nothing here touches the app database,
the demo ledgers or the network. Everything is labeled simulated (I6).

CLI: `python -m app.books.benchmark` (from backend/).
"""

from __future__ import annotations

import csv
import io
import random
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from app import db
from app.books import ledger
from app.books.reconcile import reconcile
from app.books.seed import build_hedge
from app.books.settlement import BANK_COLUMNS, book_settlement
from app.books.sources import CsvBankSource, SimulatedVenueSource
from app.models import LedgerEntry, Posting, ReconBenchmark, ReconBenchmarkCase

BUSINESS = "bench"
SEED = 7
START = date(2026, 9, 1)
OPENING = Decimal("500.00")


@dataclass(frozen=True)
class Spec:
    hid: str
    n: int
    won: bool
    plant: str | None  # expected likely_cause; None = must not be flagged
    description: str
    trap: bool = False
    day: int | None = None  # settlement day after START (default: its position in SPECS)
    status: str | None = None  # for traps: where the hedge must land ("matched" / "in_transit")


# The answer key. Hedge ids say what they are so a reader can audit the table.
SPECS: tuple[Spec, ...] = (
    Spec("hdg_b01", 60, True, "fee_deducted_from_deposit", "Deposit short by exactly the entry fee"),
    Spec("hdg_b02", 35, True, "fee_deducted_from_deposit", "Deposit short by exactly the entry fee"),
    Spec("hdg_b03", 40, True, "duplicate_deposit", "Same payout deposited twice"),
    Spec("hdg_b04", 45, True, "transposed_digits", "Deposit keyed as $54.00 instead of $45.00"),
    Spec("hdg_b05", 127, True, "transposed_digits", "Deposit keyed as $172.00 instead of $127.00"),
    Spec("hdg_b06", 52, True, "reversed_sign", "Deposit recorded as money going out"),
    Spec("hdg_b07", 71, True, "missing_deposit", "Payout never reached the bank"),
    Spec("hdg_b08", 33, True, "missing_deposit", "Payout never reached the bank"),
    Spec("hdg_b09", 48, False, "ledger_payout_differs", "Payout booked for a hedge that lost"),
    Spec("hdg_b10", 66, True, "ledger_payout_differs", "Payout booked $1.00 short in the Kalshi ledger"),
    Spec("hdg_b11", 80, True, "deposit_amount_differs", "Deposit $5.00 short, no fee explains it"),
    Spec("hdg_b12", 64, True, None, "Payout split across two deposits that add up", trap=True, status="matched"),
    Spec("hdg_b13", 39, True, None, "Deposit referenced correctly but posted 6 days late", trap=True,
         status="matched"),
    Spec("hdg_b14", 58, True, None, "Deposit with no reference, right amount, 2 days late", trap=True,
         status="matched"),
    Spec("hdg_b15", 25, False, None, "Expired worthless; no deposit expected", trap=True, status="matched"),
    Spec("hdg_b16", 44, False, None, "Expired worthless; no deposit expected", trap=True, status="matched"),
    Spec("hdg_b17", 50, True, None, "Clean"),
    Spec("hdg_b18", 61, True, None, "Clean"),
    Spec("hdg_b19", 72, True, None, "Clean"),
    Spec("hdg_b20", 90, True, None, "Clean"),
    # Three-way cases (venue vs ledger vs bank). The statement runs through day 25.
    Spec("hdg_b21", 55, True, None, "Settled on the statement date; deposit not posted yet (in transit)",
         trap=True, day=25, status="in_transit"),
    Spec("hdg_b22", 47, True, "missing_deposit", "No deposit 4 days after settlement: past the 3-day window",
         day=21),
    Spec("hdg_b23", 72, True, "venue_paid_differs_from_booked",
         "Kalshi paid $70.00 on 72 contracts we booked at $72.00; the bank got $70.00", day=22),
    Spec("hdg_b24", 50, True, "fee_differs_from_venue", "Kalshi's fee is $0.50 more than the fee we booked",
         day=23),
    Spec("hdg_b25", 64, True, "duplicate_deposit", "Paid in full, then paid again split across two rows",
         day=24),
    Spec("hdg_b26", 38, True, None, "Deposit pending at the bank 5 days after settlement (in transit)",
         trap=True, day=20, status="in_transit"),
)

# What the venue reports where it disagrees with the market result / our books.
VENUE_OVERRIDES: dict[str, dict[str, Decimal]] = {"hdg_b23": {"revenue": Decimal("70.00")}}
VENUE_FEE_EXTRA: dict[str, Decimal] = {"hdg_b24": Decimal("0.50")}

# Bank rows that belong to no hedge: (reference, days after START, amount, description).
UNEXPLAINED: tuple[tuple[str, int, str, str], ...] = (
    ("WIRE-7731", 9, "37.13", "Unknown incoming wire"),
    ("ACH-ADJ-0918", 17, "-12.50", "Unknown bank adjustment"),
)
TRAP_UNREFERENCED = "WIRE-0042"


def _world(tmp: Path, seed: int) -> tuple[object, Path, int, SimulatedVenueSource]:
    """Build the simulated books in `tmp`; returns (engine, bank statement path, n bank rows, venue)."""
    rng = random.Random(seed)
    engine = db.make_engine(f"sqlite:///{tmp / 'bench.db'}")
    db.create_schema(engine)
    ledger_dir = tmp / "ledgers"
    ledger_dir.mkdir()
    ledger.ensure_opening_deposit(BUSINESS, START - timedelta(days=1), engine)

    rows: list[tuple[str, str, str, str, str]] = [
        ((START - timedelta(days=1)).isoformat(), "SIMULATED transfer to Kalshi (opening deposit)",
         str(-OPENING), "opening_deposit", "posted"),
    ]
    overrides = {h: dict(o) for h, o in VENUE_OVERRIDES.items()}
    for i, s in enumerate(SPECS):
        settled = START + timedelta(days=s.day if s.day is not None else i)
        price = Decimal(rng.randrange(30, 71)) / 100
        side = "yes" if i % 2 else "no"
        ticker = f"SIM-RAIN-{settled:%y%b%d}".upper()
        hedge = build_hedge({
            "id": s.hid, "business_id": BUSINESS, "ticker": ticker, "side": side, "n": s.n,
            "price": str(price), "approved_at": f"{settled - timedelta(days=1)}T15:00:00Z",
        })
        at = datetime.fromisoformat(f"{settled - timedelta(days=1)}T15:00:00+00:00")
        approved, _ = ledger.approve_hedge(hedge, "owner", at=at, engine=engine, ledger_dir=ledger_dir,
                                           simulated=True)
        result = side if s.won else ("no" if side == "yes" else "yes")
        book_settlement(approved, {"ticker": ticker, "result": result, "settled_on": settled.isoformat()},
                        engine=engine, ledger_dir=ledger_dir)
        payout = Decimal(s.n).quantize(ledger.CENT)
        fee = ledger.cents(approved.fee)
        meta = ledger.hedge_meta(approved)
        if s.hid in VENUE_FEE_EXTRA:
            overrides.setdefault(s.hid, {})["fee"] = fee + VENUE_FEE_EXTRA[s.hid]

        def payout_entry(amount: Decimal) -> LedgerEntry:
            return LedgerEntry(
                id=ledger.payout_entry_id(s.hid), business_id=BUSINESS, date=settled, kind="payout",
                narration=f"[SIMULATED] Payout: {ticker} {side.upper()} x {s.n}",
                postings=[Posting(account=ledger.CASH, amount=amount),
                          Posting(account=ledger.PAYOUTS, amount=-amount)],
                meta=meta, simulated=True,
            )

        day = (settled + timedelta(days=1)).isoformat()
        desc = f"SIMULATED Kalshi withdrawal {ticker}"

        def deposit(amount: Decimal, ref: str = s.hid, on: str = day, status: str = "posted") -> None:
            rows.append((on, desc, str(ledger.cents(amount)), ref, status))

        cause = s.plant
        if cause == "ledger_payout_differs" and not s.won:
            db.put_ledger_entry(payout_entry(payout), engine)  # booked for a loser
        elif cause == "ledger_payout_differs":
            db.put_ledger_entry(payout_entry(payout - 1), engine)  # booked $1 short
            deposit(payout - 1)  # the bank agrees with the (wrong) ledger
        elif not s.won or cause == "missing_deposit" or s.hid == "hdg_b21":
            pass  # b21: settled on the statement date, its deposit hasn't posted yet
        elif cause == "venue_paid_differs_from_booked":
            deposit(VENUE_OVERRIDES[s.hid]["revenue"])  # the bank got what the venue paid
        elif cause == "fee_deducted_from_deposit":
            deposit(payout - fee)
        elif cause == "duplicate_deposit" and s.hid == "hdg_b25":
            deposit(payout)
            deposit(Decimal("30.00"))  # the same payout again, split across two rows
            deposit(payout - 30)
        elif cause == "duplicate_deposit":
            deposit(payout)
            deposit(payout)
        elif cause == "transposed_digits":
            deposit(Decimal("54.00") if s.n == 45 else Decimal("172.00"))
        elif cause == "reversed_sign":
            deposit(-payout)
        elif cause == "deposit_amount_differs":
            deposit(payout - 5)
        elif s.hid == "hdg_b12":  # split deposit
            deposit(Decimal("30.00"))
            deposit(payout - 30)
        elif s.hid == "hdg_b13":  # referenced, 6 days late
            deposit(payout, on=(settled + timedelta(days=6)).isoformat())
        elif s.hid == "hdg_b14":  # unreferenced, 2 days late: matched on amount + date window
            deposit(payout, ref=TRAP_UNREFERENCED, on=(settled + timedelta(days=2)).isoformat())
        elif s.hid == "hdg_b26":  # the bank shows it pending (ACH not settled yet)
            deposit(payout, status="pending")
        else:
            deposit(payout)

    for ref, offset, amount, description in UNEXPLAINED:
        rows.append(((START + timedelta(days=offset)).isoformat(), f"SIMULATED {description}", amount, ref,
                     "posted"))

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow((*BANK_COLUMNS, "status"))
    w.writerows((d, desc, amt, "USD", ref, "true", st) for d, desc, amt, ref, st in sorted(rows))
    path = tmp / "bank_statement_bench.csv"
    path.write_text(buf.getvalue())
    return engine, path, len(rows), SimulatedVenueSource(engine, overrides)


def _ratio(a: int, b: int) -> float:
    return round(a / b, 4) if b else 1.0


def run(seed: int = SEED) -> ReconBenchmark:
    """Build the world, reconcile it with the real reconciler, score against the answer key."""
    with tempfile.TemporaryDirectory(prefix="recon_bench_") as d:
        engine, statement, n_rows, venue = _world(Path(d), seed)
        try:
            result = reconcile(BUSINESS, engine=engine, log=False, bank=CsvBankSource(statement), venue=venue)
        finally:
            engine.dispose()

    found = {m.hedge_id: m.likely_cause for m in result.mismatches}
    landed = {m.hedge_id: "matched" for m in result.matches}
    landed |= {t.hedge_id: "in_transit" for t in result.in_transit}
    landed |= {m.hedge_id: "mismatched" for m in result.mismatches}
    key: list[tuple[str, str, str | None, str, str | None]] = [  # subject, kind, cause, description, status
        (s.hid, "trap" if s.trap else "planted", s.plant, s.description, s.status if s.trap else None)
        for s in SPECS if s.plant is not None or s.trap
    ]
    key += [(ref, "planted", "unexplained_bank_row", desc, None) for ref, _, _, desc in UNEXPLAINED]

    cases = []
    for subject, kind, expected, description, status in key:
        got = found.get(subject)
        where = landed.get(subject, "absent")
        correct = got == expected if kind == "planted" else got is None and status in (None, where)
        cases.append(ReconBenchmarkCase(
            subject=subject, kind=kind, description=description, expected_cause=expected,
            found_cause=got, flagged=got is not None, correct=correct, expected_status=status, found_status=where,
        ))
    planted = {c.subject for c in cases if c.kind == "planted"}
    false_flags = sorted(s for s in found if s not in planted)
    caught = sum(c.flagged for c in cases if c.kind == "planted")
    return ReconBenchmark(
        seed=seed, simulated=True, n_hedges=len(SPECS), n_bank_rows=n_rows,
        n_planted=len(planted), n_caught=caught,
        n_cause_correct=sum(c.correct for c in cases if c.kind == "planted"),
        n_traps=sum(c.kind == "trap" for c in cases), n_false_flags=len(false_flags),
        precision=_ratio(caught, len(found)), recall=_ratio(caught, len(planted)),
        cause_accuracy=_ratio(sum(c.correct for c in cases if c.kind == "planted"), len(planted)),
        cases=cases, false_flags=false_flags,
    )


@lru_cache(maxsize=4)
def cached(seed: int = SEED) -> ReconBenchmark:
    """`run` memoized per process (the world and the reconciler are deterministic)."""
    return run(seed)


def main() -> int:
    b = run()
    print(f"[SIMULATED] reconciliation benchmark (seed {b.seed}): caught {b.n_caught} of {b.n_planted} "
          f"planted errors, {b.n_cause_correct} with the right cause, {b.n_false_flags} false flags "
          f"({b.n_traps} traps).")
    for c in b.cases:
        mark = "ok  " if c.correct else "MISS"
        print(f"  {mark} {c.kind:7} {c.subject:13} expected={c.expected_cause or c.expected_status} "
              f"found={c.found_cause or c.found_status}")
    for s in b.false_flags:
        print(f"  FALSE FLAG {s}")
    traps_ok = all(c.correct for c in b.cases if c.kind == "trap")
    return 0 if b.n_cause_correct == b.n_planted and not b.false_flags and traps_ok else 1


if __name__ == "__main__":
    sys.exit(main())
