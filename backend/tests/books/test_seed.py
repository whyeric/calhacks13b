"""C5-A18 (+A1 on the seeded demo ledgers): seeding is offline and byte-reproducible."""

import pytest

from app import db
from app.books import ledger
from app.books.seed import seed_books

FILES = ("bank_statement.csv", "bank_statement_clean.csv", "bank_statement_restaurant.csv")


def _snapshot(ledger_dir, out):
    return {p.name: p.read_bytes() for p in [*ledger_dir.glob("*.beancount"), *(out / f for f in FILES)]}


def test_seed_reproducible(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    snaps = []
    for run in ("a", "b"):
        e = db.make_engine(f"sqlite:///{tmp_path / f'{run}.db'}")
        ld, out = tmp_path / f"l{run}", tmp_path / f"o{run}"
        ld.mkdir()
        out.mkdir()
        seed_books(e, ledger_dir=ld, out_dir=out)
        first = _snapshot(ld, out)
        seed_books(e, ledger_dir=ld, out_dir=out)  # rerun on the same db: no change
        assert _snapshot(ld, out) == first
        snaps.append(first)
        e.dispose()
    assert snaps[0] == snaps[1]
    assert set(snaps[0]) == {"taxi.beancount", "restaurant.beancount", *FILES}


def test_seeded_ledgers_pass_bean_check(engine, ledger_dir, tmp_path):  # C5-A1 on demo data
    pytest.importorskip("beancount")
    seed_books(engine, ledger_dir=ledger_dir, out_dir=tmp_path)
    for business in ("taxi", "restaurant"):
        entries = ledger.load_ledger(business, ledger_dir)
        assert entries


def test_committed_statements_match_seed(engine, ledger_dir, tmp_path):
    """The CSVs checked into fixtures/ are what the seed produces."""
    seed_books(engine, ledger_dir=ledger_dir, out_dir=tmp_path)
    for name in FILES:
        assert (tmp_path / name).read_bytes() == (db.FIXTURES_DIR / name).read_bytes(), name
