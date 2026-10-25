"""C5-A15: every simulated artifact is labeled (I6)."""

import csv

import pytest

from app import db
from app.books import ledger
from app.books.reconcile import reconcile
from app.books.seed import seed_books
from app.models import LedgerResponse


@pytest.fixture
def seeded(engine, ledger_dir, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    seed_books(engine, ledger_dir=ledger_dir, out_dir=out)
    return out


def test_simulated_labeled(engine, ledger_dir, seeded):
    for business in ("taxi", "restaurant"):
        entries = db.list_ledger_entries(business, engine)
        for e in entries:
            if e.kind in ("payout", "withdrawal", "opening_deposit"):
                assert e.simulated and e.narration.startswith("[SIMULATED]")
        text = ledger.ledger_path(business, ledger_dir).read_text()
        for block in text.split("\n\n"):
            if "[SIMULATED]" in block and " * " in block:
                assert 'simulated: "true"' in block
        resp = LedgerResponse(entries=entries, reconciliation=None, simulated=True)
        assert resp.model_dump(mode="json")["simulated"] is True
    for name in ("bank_statement.csv", "bank_statement_clean.csv", "bank_statement_restaurant.csv"):
        with (seeded / name).open() as f:
            rows = list(csv.DictReader(f))
        assert rows and all(r["simulated"] == "true" for r in rows)
        assert all(r["description"].startswith("SIMULATED") for r in rows)
    assert reconcile("taxi", statement=seeded / "bank_statement.csv", engine=engine).simulated is True
