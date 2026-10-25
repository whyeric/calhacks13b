"""Planted-error benchmark for three-way reconciliation ("proof it works" with an answer key).

Builds a SIMULATED world in a throwaway SQLite database: 20 owner-approved hedges on
fictional markets (`SIM-…` tickers), settled, booked, and paid out to a generated bank
statement. Thirteen errors are planted in the Kalshi ledger and the bank statement, and five
traps look odd but are correct (a split deposit, a late deposit, an unreferenced deposit
that posts two days late, two hedges that expired worthless). Then the real `reconcile()`
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
    Spec("hdg_b12", 64, True, None, "Payout split across two deposits that add up", trap=True),
    Spec("hdg_b13", 39, True, None, "Deposit referenced correctly but posted 6 days late", trap=True),
    Spec("hdg_b14", 58, True, None, "Deposit with no reference, right amount, 2 days late", trap=True),
    Spec("hdg_b15", 25, False, None, "Expired worthless; no deposit expected", trap=True),
    Spec("hdg_b16", 44, False, None, "Expired worthless; no deposit expected", trap=True),
    Spec("hdg_b17", 50, True, None, "Clean"),
    Spec("hdg_b18", 61, True, None, "Clean"),
    Spec("hdg_b19", 72, True, None, "Clean"),
    Spec("hdg_b20", 90, True, None, "Clean"),
)

# Bank rows that belong to no hedge: (reference, days after START, amount, description).
UNEXPLAINED: tuple[tuple[str, int, str, str], ...] = (
    ("WIRE-7731", 9, "37.13", "Unknown incoming wire"),
    ("ACH-ADJ-0918", 17, "-12.50", "Unknown bank adjustment"),
)
TRAP_UNREFERENCED = "WIRE-0042"


def _world(tmp: Path, seed: int) -> tuple[object, Path, int]:
    """Build the simulated books in `tmp`; returns (engine, bank statement path, n bank rows)."""
    rng = random.Random(seed)
    engine = db.make_engine(f"sqlite:///{tmp / 'bench.db'}")
    db.create_schema(engine)
    ledger_dir = tmp / "ledgers"
    ledger_dir.mkdir()
    ledger.ensure_opening_deposit(BUSINESS, START - timedelta(days=1), engine)

    rows: list[tuple[str, str, str, str]] = [
        ((START - timedelta(days=1)).isoformat(), "SIMULATED transfer to Kalshi (opening deposit)",
         str(-OPENING), "opening_deposit"),
    ]
    for i, s in enumerate(SPECS):
        settled = START + timedelta(days=i)
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

        def deposit(amount: Decimal, ref: str = s.hid, on: str = day) -> None:
            rows.append((on, desc, str(ledger.cents(amount)), ref))

        cause = s.plant
        if cause == "ledger_payout_differs" and not s.won:
            db.put_ledger_entry(payout_entry(payout), engine)  # booked for a loser
        elif cause == "ledger_payout_differs":
            db.put_ledger_entry(payout_entry(payout - 1), engine)  # booked $1 short
            deposit(payout - 1)  # the bank agrees with the (wrong) ledger
        elif not s.won or cause == "missing_deposit":
            pass
        elif cause == "fee_deducted_from_deposit":
            deposit(payout - fee)
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
        else:
            deposit(payout)

    for ref, offset, amount, description in UNEXPLAINED:
        rows.append(((START + timedelta(days=offset)).isoformat(), f"SIMULATED {description}", amount, ref))

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(BANK_COLUMNS)
    w.writerows((d, desc, amt, "USD", ref, "true") for d, desc, amt, ref in sorted(rows))
    path = tmp / "bank_statement_bench.csv"
    path.write_text(buf.getvalue())
    return engine, path, len(rows)


def _ratio(a: int, b: int) -> float:
    return round(a / b, 4) if b else 1.0


def run(seed: int = SEED) -> ReconBenchmark:
    """Build the world, reconcile it with the real reconciler, score against the answer key."""
    with tempfile.TemporaryDirectory(prefix="recon_bench_") as d:
        engine, statement, n_rows = _world(Path(d), seed)
        try:
            result = reconcile(BUSINESS, statement=statement, engine=engine, log=False)
        finally:
            engine.dispose()

    found = {m.hedge_id: m.likely_cause for m in result.mismatches}
    key: list[tuple[str, str, str | None, str]] = [  # subject, kind, expected cause, description
        (s.hid, "trap" if s.trap else "planted", s.plant, s.description)
        for s in SPECS if s.plant is not None or s.trap
    ]
    key += [(ref, "planted", "unexplained_bank_row", desc) for ref, _, _, desc in UNEXPLAINED]

    cases = []
    for subject, kind, expected, description in key:
        got = found.get(subject)
        correct = got == expected if kind == "planted" else got is None
        cases.append(ReconBenchmarkCase(
            subject=subject, kind=kind, description=description, expected_cause=expected,
            found_cause=got, flagged=got is not None, correct=correct,
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
        print(f"  {mark} {c.kind:7} {c.subject:13} expected={c.expected_cause} found={c.found_cause}")
    for s in b.false_flags:
        print(f"  FALSE FLAG {s}")
    return 0 if b.n_cause_correct == b.n_planted and not b.false_flags else 1


if __name__ == "__main__":
    sys.exit(main())
