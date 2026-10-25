"""Planted-error benchmark (proof it works): the real reconciler against an answer key, plus
one unit test per likely_cause and the traps that must not be flagged."""

import shutil
from decimal import Decimal

import pytest

from app.books import benchmark, reconcile as recon_mod
from app.books.reconcile import _mismatch, _transposed, reconcile
from app.books.seed import seed_books
from app.models import ReconBenchmark

D = Decimal


# --- The benchmark --------------------------------------------------------------------


def test_benchmark_catches_every_planted_error_with_no_false_flags():
    b = benchmark.run()
    assert b.simulated is True
    assert b.n_hedges == 20 and b.n_planted == 13 and b.n_traps == 5
    misses = [(c.subject, c.expected_cause, c.found_cause) for c in b.cases if not c.correct]
    assert misses == [] and b.false_flags == []
    assert (b.recall, b.precision, b.cause_accuracy) == (1.0, 1.0, 1.0)
    assert b.n_caught == b.n_cause_correct == 13 and b.n_false_flags == 0


def test_benchmark_covers_every_cause():
    causes = {c.expected_cause for c in benchmark.run().cases if c.kind == "planted"}
    assert causes == {
        "fee_deducted_from_deposit", "duplicate_deposit", "transposed_digits", "reversed_sign",
        "missing_deposit", "ledger_payout_differs", "deposit_amount_differs", "unexplained_bank_row",
    }


def test_benchmark_is_deterministic_and_round_trips():
    a, b = benchmark.run(), benchmark.run()
    assert a.model_dump_json() == b.model_dump_json()
    ReconBenchmark.model_validate_json(a.model_dump_json())


def test_benchmark_can_fail(monkeypatch):
    """The key is not tuned to pass: an exact-date fallback (the old matcher) false-flags the
    unreferenced late deposit and reports its hedge as missing."""
    monkeypatch.setattr(recon_mod, "MATCH_WINDOW_DAYS", 0)
    b = benchmark.run()
    assert "WIRE-0042" in b.false_flags
    trap = next(c for c in b.cases if c.subject == "hdg_b14")
    assert not trap.correct and trap.found_cause == "missing_deposit"
    assert b.precision < 1.0


# --- One unit test per cause ------------------------------------------------------------


@pytest.mark.parametrize("exp,kal,bank,fee,rows,cause", [
    (D("60.00"), D("60.00"), D("59.11"), D("0.89"), [D("59.11")], "fee_deducted_from_deposit"),
    (D("40.00"), D("40.00"), D("80.00"), D("0.70"), [D("40.00"), D("40.00")], "duplicate_deposit"),
    (D("45.00"), D("45.00"), D("54.00"), D("0.80"), [D("54.00")], "transposed_digits"),
    (D("127.00"), D("127.00"), D("172.00"), D("1.50"), [D("172.00")], "transposed_digits"),
    (D("52.00"), D("52.00"), D("-52.00"), D("0.90"), [D("-52.00")], "reversed_sign"),
    (D("71.00"), D("71.00"), D("0.00"), D("1.00"), [], "missing_deposit"),
    (D("0.00"), D("48.00"), D("0.00"), D("0.80"), [], "ledger_payout_differs"),
    (D("66.00"), D("65.00"), D("65.00"), D("1.10"), [D("65.00")], "ledger_payout_differs"),
    (D("80.00"), D("80.00"), D("75.00"), D("1.20"), [D("75.00")], "deposit_amount_differs"),
])
def test_each_cause(exp, kal, bank, fee, rows, cause):
    m = _mismatch("hdg_x", "SIM-X", exp, kal, bank, fee, rows)
    assert m.likely_cause == cause
    assert m.action == "ask_owner" and m.question.endswith("?") and m.explanation


def test_transposition_needs_a_true_swap():
    assert _transposed(D("45.00"), D("54.00"))
    assert not _transposed(D("45.00"), D("63.00"))  # multiple of 9, not a swap
    assert not _transposed(D("45.00"), D("45.00"))
    assert not _transposed(D("80.00"), D("75.00"))


# --- Traps on the seeded demo books ---------------------------------------------------


@pytest.fixture
def seeded(engine, ledger_dir, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    seed_books(engine, ledger_dir=ledger_dir, out_dir=out)
    return out


def test_split_deposit_matches(engine, seeded, tmp_path):
    csv = tmp_path / "split.csv"
    text = (seeded / "bank_statement_clean.csv").read_text()
    text = text.replace(",45.00,USD,hdg_s03,true\n", ",20.00,USD,hdg_s03,true\n")
    text += "2026-10-24,SIMULATED Kalshi withdrawal (rest),25.00,USD,hdg_s03,true\n"
    csv.write_text(text)
    r = reconcile("taxi", statement=csv, engine=engine, log=False)
    assert r.mismatches == [] and r.summary.n_matched == 3


def test_unreferenced_deposit_within_window_matches(engine, seeded, tmp_path):
    csv = tmp_path / "late.csv"
    text = (seeded / "bank_statement_clean.csv").read_text()
    text = text.replace("2026-10-23,SIMULATED Kalshi withdrawal KXHIGHNY-26OCT22-T70,45.00,USD,hdg_s03",
                        "2026-10-25,SIMULATED Kalshi withdrawal KXHIGHNY-26OCT22-T70,45.00,USD,WIRE-9")
    csv.write_text(text)
    assert "WIRE-9" in text
    r = reconcile("taxi", statement=csv, engine=engine, log=False)
    assert r.mismatches == []


def test_unreferenced_deposit_outside_window_is_flagged(engine, seeded, tmp_path):
    csv = tmp_path / "very_late.csv"
    text = (seeded / "bank_statement_clean.csv").read_text()
    text = text.replace("2026-10-23,SIMULATED Kalshi withdrawal KXHIGHNY-26OCT22-T70,45.00,USD,hdg_s03",
                        "2026-10-30,SIMULATED Kalshi withdrawal KXHIGHNY-26OCT22-T70,45.00,USD,WIRE-9")
    csv.write_text(text)
    r = reconcile("taxi", statement=csv, engine=engine, log=False)
    assert {m.likely_cause for m in r.mismatches} == {"missing_deposit", "unexplained_bank_row"}


def test_duplicate_on_seeded_books(engine, seeded, tmp_path):
    csv = tmp_path / "dup.csv"
    shutil.copy(seeded / "bank_statement_clean.csv", csv)
    with csv.open("a") as f:
        f.write("2026-10-24,SIMULATED Kalshi withdrawal KXHIGHNY-26OCT22-T70,45.00,USD,hdg_s03,true\n")
    r = reconcile("taxi", statement=csv, engine=engine, log=False)
    assert [(m.hedge_id, m.likely_cause, m.difference) for m in r.mismatches] == [
        ("hdg_s03", "duplicate_deposit", D("45.00"))
    ]
