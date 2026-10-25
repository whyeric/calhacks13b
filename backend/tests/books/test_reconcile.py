"""C5-A10..A14, A17 (recon half): three-way reconciliation on the seeded demo books."""

import shutil
from decimal import Decimal

import pytest

from app import db
from app.books.reconcile import reconcile
from app.books.seed import seed_books
from app.models import ReconResult


@pytest.fixture
def seeded(engine, ledger_dir, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    seed_books(engine, ledger_dir=ledger_dir, out_dir=out)
    return out


def test_planted_mismatch_flagged(engine, seeded):  # C5-A10
    r = reconcile("taxi", statement=seeded / "bank_statement.csv", engine=engine)
    assert len(r.mismatches) == 1
    m = r.mismatches[0]
    assert m.hedge_id == "hdg_s01"
    assert m.difference == Decimal("-0.89")  # minus the hedge's fee, to the cent
    assert (m.kalshi_ledger, m.bank) == (Decimal("60.00"), Decimal("59.11"))
    assert m.source_pair == "kalshi_ledger_vs_bank"
    assert m.likely_cause == "fee_deducted_from_deposit"
    assert "$0.89" in m.explanation and "fee" in m.explanation
    assert m.action == "ask_owner" and m.question.endswith("?")
    assert r.summary.total_difference == Decimal("-0.89")
    ReconResult.model_validate_json(r.model_dump_json())  # R9 shape round-trips


def test_zero_false_positives_clean(engine, seeded):  # C5-A11
    r = reconcile("taxi", statement=seeded / "bank_statement_clean.csv", engine=engine)
    assert r.mismatches == []
    assert r.summary.n_matched == 3  # every settled taxi hedge
    rr = reconcile("restaurant", statement=seeded / "bank_statement_restaurant.csv", engine=engine)
    assert rr.mismatches == [] and rr.summary.n_matched == 2


def test_recon_deterministic_and_pure(engine, seeded, ledger_dir):  # C5-A12
    csv = seeded / "bank_statement.csv"
    before = (csv.read_bytes(), (ledger_dir / "taxi.beancount").read_bytes(), db.list_ledger_entries("taxi", engine))
    a = reconcile("taxi", statement=csv, engine=engine)
    b = reconcile("taxi", statement=csv, engine=engine)
    assert a.model_dump_json() == b.model_dump_json()
    after = (csv.read_bytes(), (ledger_dir / "taxi.beancount").read_bytes(), db.list_ledger_entries("taxi", engine))
    assert before == after


def test_expired_not_flagged(engine, seeded):  # C5-A13
    r = reconcile("taxi", statement=seeded / "bank_statement.csv", engine=engine)
    expired = [m for m in r.matches if m.hedge_id == "hdg_s02"]
    assert len(expired) == 1
    assert (expired[0].expected, expired[0].kalshi_ledger, expired[0].bank) == (Decimal("0.00"),) * 3


def test_unmatched_bank_row_flagged(engine, seeded, tmp_path):  # C5-A14
    csv = tmp_path / "extra.csv"
    shutil.copy(seeded / "bank_statement_clean.csv", csv)
    with csv.open("a") as f:
        f.write("2026-10-24,SIMULATED unknown deposit,12.34,USD,ref_unknown,true\n")
    r = reconcile("taxi", statement=csv, engine=engine, log=False)
    assert len(r.mismatches) == 1
    m = r.mismatches[0]
    assert m.likely_cause == "unexplained_bank_row" and m.bank == Decimal("12.34")
    assert "$12.34" in m.explanation


def test_fallback_match_on_date_and_amount(engine, seeded, tmp_path):
    csv = tmp_path / "noref.csv"
    text = (seeded / "bank_statement_clean.csv").read_text().replace(",hdg_s03,", ",WIRE-0001,")
    csv.write_text(text)
    r = reconcile("taxi", statement=csv, engine=engine, log=False)
    assert r.mismatches == [] and r.summary.n_matched == 3


def test_log_events_in_order(engine, seeded):  # C5-A17
    reconcile("taxi", statement=seeded / "bank_statement.csv", engine=engine)
    reconcile("taxi", statement=seeded / "bank_statement.csv", engine=engine)  # no duplicate log
    logs = db.list_log("taxi", engine=engine)
    for hid in ("hdg_s01", "hdg_s02", "hdg_s03"):
        kinds = [e.kind for e in logs if e.hedge_id == hid and e.kind != "reconciliation"]
        assert kinds[0] == "booking" and kinds[1] in ("settlement", "expired")
    recon = [e for e in logs if e.kind == "reconciliation"]
    assert len(recon) == 1 and logs[-1].kind == "reconciliation"
    assert recon[0].hedge_id == "hdg_s01"
