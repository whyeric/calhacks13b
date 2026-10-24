"""C6-A23: db create and seed idempotent; Decimal columns round-trip exactly."""

import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from app import db
from app.config import get_thresholds
from app.models import Hedge, LedgerEntry, LogEntry, Settings

EXAMPLES = db.FIXTURES_DIR / "examples"


@pytest.fixture
def engine(tmp_path):
    e = db.make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema(e)
    yield e
    e.dispose()


def _example(name: str):
    return json.loads((EXAMPLES / name).read_text())


def test_wal_mode_on(engine):
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_seed_twice_identical_row_counts(engine):
    first = db.seed(engine)
    second = db.seed(engine)
    assert first == second
    assert first["businesses"] == 2
    assert first["hedges"] == len(_example("week_seed.json"))
    assert first["log"] == len(_example("decisions_seed.json"))


def test_seeded_objects_match_fixtures(engine):
    db.seed(engine)
    for raw in _example("week_seed.json"):
        stored = db.get_hedge(raw["id"], engine)
        assert json.loads(stored.model_dump_json()) == raw
    assert [e.log_id for e in db.list_log(engine=engine)] == [
        e["log_id"] for e in sorted(_example("decisions_seed.json"), key=lambda e: e["created_at"])
    ]
    assert {b.id for b in db.list_businesses(engine)} == {"taxi", "restaurant"}


def test_hedge_decimals_round_trip_exactly(engine):
    raw = _example("hedge_proposed.json")
    raw["avg_price"] = "0.62"
    raw["fee"] = "0.01"
    raw["cost"] = "93.00"
    raw["premium"] = "93.01"
    for row in raw["payoff"]:
        row["premium"] = "-93.01"
        row["net_vs_base"] = str(Decimal(row["revenue_vs_base"]) + Decimal(row["contract_payout"]) - Decimal("93.01"))
    raw["headline"]["cost"] = "93.01"
    h = Hedge.model_validate(raw)
    db.put_hedge(h, engine)
    got = db.get_hedge(h.id, engine)
    assert got == h
    assert got.avg_price == Decimal("0.62") and str(got.avg_price) == "0.62"
    assert got.fee == Decimal("0.01")
    assert got.premium == got.cost + got.fee == Decimal("93.01")
    # stored as text, never a float
    with engine.connect() as conn:
        data = conn.execute(text("SELECT data FROM hedges WHERE id = :id"), {"id": h.id}).scalar()
    stored = json.loads(data)
    assert stored["avg_price"] == "0.62" and stored["fee"] == "0.01" and stored["premium"] == "93.01"


def test_ledger_entry_round_trip(engine):
    e = LedgerEntry.model_validate(_example("ledger_entry.json"))
    db.put_ledger_entry(e, engine)
    db.put_ledger_entry(e, engine)
    assert db.list_ledger_entries(e.business_id, engine) == [e]
    assert db.row_counts(engine)["ledger_entries"] == 1


def test_log_is_append_only(engine):
    entry = LogEntry.model_validate(_example("decisions_seed.json")[0])
    assert db.append_log(entry, engine) is True
    assert db.append_log(entry, engine) is False  # same content: no duplicate
    changed = entry.model_copy(update={"summary": entry.summary + " (edited)"})
    with pytest.raises(ValueError, match="append-only"):
        db.append_log(changed, engine)
    assert db.list_log(engine=engine) == [entry]
    assert not any(hasattr(db, n) for n in ("update_log", "delete_log", "put_log"))


def test_settings_overrides_layer_over_defaults(engine):
    defaults = db.get_business_settings("taxi", engine)
    assert defaults.weekly_budget == Decimal("250.00")
    assert db.get_business_thresholds("taxi", engine) == get_thresholds()

    s = Settings.model_validate(_example("settings.json"))
    s = s.model_copy(update={"weekly_budget": Decimal("300.00")})
    s.thresholds.overpay_max = Decimal("0.10")
    db.put_business_settings("taxi", s, engine)
    t = db.get_business_thresholds("taxi", engine)
    assert t.overpay_max == Decimal("0.10") and isinstance(t.overpay_max, Decimal)
    assert db.get_weekly_budget("taxi", engine) == Decimal("300.00")
    assert db.get_business_settings("taxi", engine) == s
    assert db.get_business_thresholds("restaurant", engine) == get_thresholds()

    db.clear_business_settings("taxi", engine)
    assert db.get_business_settings("taxi", engine) == defaults


def test_budget_pending_counts_proposed_and_pending_approval(engine):
    db.seed(engine)
    b = db.compute_budget("taxi", date(2026, 10, 26), engine)
    # hdg_01 proposed 66.47 + hdg_02 pending_approval 942.80
    assert b.pending == Decimal("1009.27")
    assert b.spent == Decimal("0.00")
    assert b.remaining == Decimal("250") - Decimal("1009.27")
    r = db.compute_budget("restaurant", date(2026, 10, 26), engine)
    assert r.pending == Decimal("219.75")  # declined hdg_03 not counted


def test_runs_and_analysis_cache(engine):
    from app.models import RunStatus

    run = RunStatus.model_validate(_example("run_status.json"))
    db.put_run(run, engine)
    assert db.get_run(run.run_id, engine) == run
    db.put_analysis("taxi", "default", {"r2_holdout": 0.41, "x": "0.62"}, "2026-10-24T15:00:00Z", engine)
    assert db.get_analysis("taxi", "default", engine) == {"r2_holdout": 0.41, "x": "0.62"}
    assert db.get_analysis("taxi", "missing", engine) is None
