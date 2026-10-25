"""SQLite storage (SQLModel). One engine per URL, WAL mode, one short transaction per helper (G13).

Each row keeps the pydantic contract model as JSON in `data`, next to a few indexed key
columns for lookups. Decimals live inside that JSON as strings, so they never pass through
float. Helpers take and return contract models; callers never see the row classes.

The decision log is append-only: there is an `append_log` helper and nothing that updates
or deletes a log row.

CLI: `python -m app.db seed` (run from backend/, see Makefile) loads the fixtures; idempotent.
"""

import argparse
import dataclasses
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, create_engine, func, select

from app.config import BACKEND_DIR, Thresholds, get_settings, get_thresholds
from app.models import (
    Budget,
    Business,
    Hedge,
    LedgerEntry,
    LogEntry,
    RunStatus,
    Settings,
    ThresholdSettings,
)

FIXTURES_DIR = BACKEND_DIR / "fixtures"

# Hedges whose premium is committed but not yet spent: every passing hedge waits for the
# owner (D1), and over-budget ones wait too (D4).
PENDING_STATUSES = ("proposed", "pending_approval")
SPENT_STATUSES = ("approved", "settled")


# --- Tables ------------------------------------------------------------------


class BusinessRow(SQLModel, table=True):
    __tablename__ = "businesses"

    id: str = Field(primary_key=True)
    data: str


class HedgeRow(SQLModel, table=True):
    __tablename__ = "hedges"

    id: str = Field(primary_key=True)
    business_id: str = Field(index=True)
    status: str = Field(index=True)
    week_of: str = Field(index=True)  # ISO date (Monday)
    created_at: str = Field(index=True)  # ISO-8601 UTC
    data: str


class LogRow(SQLModel, table=True):
    __tablename__ = "log"

    seq: int | None = Field(default=None, primary_key=True)  # insertion order
    log_id: str = Field(unique=True, index=True)
    business_id: str = Field(index=True)
    kind: str = Field(index=True)
    hedge_id: str | None = Field(default=None, index=True)
    run_id: str | None = Field(default=None, index=True)
    created_at: str = Field(index=True)
    data: str


class LedgerRow(SQLModel, table=True):
    __tablename__ = "ledger_entries"

    id: str = Field(primary_key=True)
    business_id: str = Field(index=True)
    hedge_id: str | None = Field(default=None, index=True)
    date: str = Field(index=True)
    data: str


class RunRow(SQLModel, table=True):
    __tablename__ = "run"

    run_id: str = Field(primary_key=True)
    business_id: str = Field(index=True)
    status: str = Field(index=True)
    data: str


class AnalysisRow(SQLModel, table=True):
    """Cached analysis output per business and cache key (e.g. the strike)."""

    __tablename__ = "analysis"

    business_id: str = Field(primary_key=True)
    cache_key: str = Field(primary_key=True)
    created_at: str
    data: str  # any JSON; usually an AnalyzeResponse


class SettingsOverrideRow(SQLModel, table=True):
    """Per-business overrides over `config.Thresholds` / `WEEKLY_BUDGET_DEFAULT` (R14, G9)."""

    __tablename__ = "settings_overrides"

    business_id: str = Field(primary_key=True)
    data: str  # {"thresholds": {field: value, ...}, "weekly_budget": "300.00"}; all optional


# --- Engine and sessions -----------------------------------------------------


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def make_engine(url: str) -> Engine:
    """Engine for `url` with WAL on. Tests pass a temp-file URL."""
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _sqlite_pragmas)
    return engine


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


def create_schema(engine: Engine | None = None) -> None:
    SQLModel.metadata.create_all(engine or get_engine())


@contextmanager
def session(engine: Engine | None = None) -> Iterator[Session]:
    """One short transaction: commits on exit, rolls back on error."""
    with Session(engine or get_engine()) as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise


def _json(model: Any) -> str:
    return model.model_dump_json()


def _iso(model: Any, field: str) -> str:
    return model.model_dump(mode="json")[field]


# --- Businesses --------------------------------------------------------------


def put_business(b: Business, engine: Engine | None = None) -> None:
    with session(engine) as s:
        s.merge(BusinessRow(id=b.id, data=_json(b)))


def get_business(business_id: str, engine: Engine | None = None) -> Business | None:
    with session(engine) as s:
        row = s.get(BusinessRow, business_id)
        return Business.model_validate_json(row.data) if row else None


def list_businesses(engine: Engine | None = None) -> list[Business]:
    with session(engine) as s:
        rows = s.exec(select(BusinessRow).order_by(BusinessRow.id)).all()
        return [Business.model_validate_json(r.data) for r in rows]


# --- Hedges ------------------------------------------------------------------


def put_hedge(h: Hedge, engine: Engine | None = None) -> None:
    """Insert or replace a hedge (status changes go through here)."""
    with session(engine) as s:
        s.merge(
            HedgeRow(
                id=h.id,
                business_id=h.business_id,
                status=h.status,
                week_of=h.week_of.isoformat(),
                created_at=_iso(h, "created_at"),
                data=_json(h),
            )
        )


def get_hedge(hedge_id: str, engine: Engine | None = None) -> Hedge | None:
    with session(engine) as s:
        row = s.get(HedgeRow, hedge_id)
        return Hedge.model_validate_json(row.data) if row else None


def list_hedges(
    business_id: str | None = None,
    week_of: date | None = None,
    statuses: tuple[str, ...] | None = None,
    engine: Engine | None = None,
) -> list[Hedge]:
    q = select(HedgeRow)
    if business_id is not None:
        q = q.where(HedgeRow.business_id == business_id)
    if week_of is not None:
        q = q.where(HedgeRow.week_of == week_of.isoformat())
    if statuses is not None:
        q = q.where(HedgeRow.status.in_(statuses))
    with session(engine) as s:
        rows = s.exec(q.order_by(HedgeRow.created_at, HedgeRow.id)).all()
        return [Hedge.model_validate_json(r.data) for r in rows]


# --- Decision log (append-only) ----------------------------------------------


def append_log(entry: LogEntry, engine: Engine | None = None) -> bool:
    """Append one log entry. Returns False if `log_id` is already stored with the same
    content (so re-seeding is a no-op); raises ValueError if it differs. Never updates."""
    data = _json(entry)
    with session(engine) as s:
        existing = s.exec(select(LogRow).where(LogRow.log_id == entry.log_id)).first()
        if existing is not None:
            if existing.data != data:
                raise ValueError(f"log is append-only; {entry.log_id} already exists with other content")
            return False
        s.add(
            LogRow(
                log_id=entry.log_id,
                business_id=entry.business_id,
                kind=entry.kind,
                hedge_id=entry.hedge_id,
                run_id=entry.run_id,
                created_at=_iso(entry, "created_at"),
                data=data,
            )
        )
        return True


def list_log(
    business_id: str | None = None,
    hedge_id: str | None = None,
    engine: Engine | None = None,
) -> list[LogEntry]:
    """Log entries in chronological order (ties by insertion)."""
    q = select(LogRow)
    if business_id is not None:
        q = q.where(LogRow.business_id == business_id)
    if hedge_id is not None:
        q = q.where(LogRow.hedge_id == hedge_id)
    with session(engine) as s:
        rows = s.exec(q.order_by(LogRow.created_at, LogRow.seq)).all()
        return [LogEntry.model_validate_json(r.data) for r in rows]


# --- Ledger entries ----------------------------------------------------------


def put_ledger_entry(e: LedgerEntry, engine: Engine | None = None) -> None:
    with session(engine) as s:
        s.merge(
            LedgerRow(
                id=e.id,
                business_id=e.business_id,
                hedge_id=e.meta.hedge_id if e.meta else None,
                date=e.date.isoformat(),
                data=_json(e),
            )
        )


def list_ledger_entries(business_id: str, engine: Engine | None = None) -> list[LedgerEntry]:
    with session(engine) as s:
        q = select(LedgerRow).where(LedgerRow.business_id == business_id)
        rows = s.exec(q.order_by(LedgerRow.date, LedgerRow.id)).all()
        return [LedgerEntry.model_validate_json(r.data) for r in rows]


# --- Runs --------------------------------------------------------------------


def put_run(r: RunStatus, engine: Engine | None = None) -> None:
    with session(engine) as s:
        s.merge(RunRow(run_id=r.run_id, business_id=r.business_id, status=r.status, data=_json(r)))


def get_run(run_id: str, engine: Engine | None = None) -> RunStatus | None:
    with session(engine) as s:
        row = s.get(RunRow, run_id)
        return RunStatus.model_validate_json(row.data) if row else None


def active_run(business_id: str, engine: Engine | None = None) -> RunStatus | None:
    """The queued or running run for this business, if any (G13: one at a time, else 409)."""
    with session(engine) as s:
        q = select(RunRow).where(RunRow.business_id == business_id, RunRow.status.in_(("queued", "running")))
        row = s.exec(q).first()
        return RunStatus.model_validate_json(row.data) if row else None


# --- Analysis cache ----------------------------------------------------------


def put_analysis(
    business_id: str, cache_key: str, payload: Any, created_at: str, engine: Engine | None = None
) -> None:
    """Cache a JSON-able payload (a pydantic model or plain data)."""
    data = payload.model_dump_json() if hasattr(payload, "model_dump_json") else json.dumps(payload)
    with session(engine) as s:
        s.merge(AnalysisRow(business_id=business_id, cache_key=cache_key, created_at=created_at, data=data))


def get_analysis(business_id: str, cache_key: str, engine: Engine | None = None) -> Any | None:
    """Cached payload as parsed JSON; validate with the model you stored."""
    with session(engine) as s:
        row = s.get(AnalysisRow, (business_id, cache_key))
        return json.loads(row.data) if row else None


# --- Settings overrides (R14, G9) --------------------------------------------


def _overrides(business_id: str, engine: Engine | None) -> dict[str, Any]:
    with session(engine) as s:
        row = s.get(SettingsOverrideRow, business_id)
        return json.loads(row.data) if row else {}


def get_business_thresholds(business_id: str, engine: Engine | None = None) -> Thresholds:
    """`config.Thresholds` defaults with this business's overrides applied."""
    over = _overrides(business_id, engine).get("thresholds", {})
    defaults = get_thresholds()
    typed = {
        f.name: Decimal(over[f.name]) if isinstance(getattr(defaults, f.name), Decimal) else over[f.name]
        for f in dataclasses.fields(Thresholds)
        if f.name in over
    }
    return dataclasses.replace(defaults, **typed)


def get_weekly_budget(business_id: str, engine: Engine | None = None) -> Decimal:
    over = _overrides(business_id, engine).get("weekly_budget")
    return Decimal(over) if over is not None else get_settings().weekly_budget_default


def get_business_settings(business_id: str, engine: Engine | None = None) -> Settings:
    t = get_business_thresholds(business_id, engine)
    return Settings(
        thresholds=ThresholdSettings(**dataclasses.asdict(t)),
        weekly_budget=get_weekly_budget(business_id, engine).quantize(Decimal("0.01")),
    )


def put_business_settings(business_id: str, settings: Settings, engine: Engine | None = None) -> None:
    """Store the full settings as this business's override layer."""
    data = settings.model_dump(mode="json")
    with session(engine) as s:
        s.merge(SettingsOverrideRow(business_id=business_id, data=json.dumps(data)))


def clear_business_settings(business_id: str, engine: Engine | None = None) -> None:
    """Drop overrides so the business falls back to config defaults."""
    with session(engine) as s:
        row = s.get(SettingsOverrideRow, business_id)
        if row is not None:
            s.delete(row)


# --- Budget ------------------------------------------------------------------


def compute_budget(business_id: str, week_start: date, engine: Engine | None = None) -> Budget:
    """R7 budget for one week, from stored hedges.

    `spent` sums premiums of approved/settled hedges. `pending` sums premiums of hedges
    awaiting the owner, in status `proposed` or `pending_approval` (D1: every passing hedge
    waits for approval; D4: over-budget ones wait too). `remaining = budget - spent - pending`.
    """
    def total(statuses: tuple[str, ...]) -> Decimal:
        hedges = list_hedges(business_id, week_start, statuses, engine)
        return sum((h.premium for h in hedges if h.premium is not None), Decimal("0.00"))

    budget = get_weekly_budget(business_id, engine)
    spent, pending = total(SPENT_STATUSES), total(PENDING_STATUSES)
    return Budget(
        budget=budget, spent=spent, pending=pending, remaining=budget - spent - pending, week_start=week_start
    )


# --- Seed --------------------------------------------------------------------


# The "sample week" (DEMO_SAMPLE_WEEK): example hedges and their log entries, identified by the
# ids in these fixture files. Real desk runs write `hdg_{business}_{week}_{event}` ids and
# `log_<hex>` ids, so the two never collide.
SAMPLE_HEDGES_FILE = "week_seed.json"
SAMPLE_LOG_FILE = "decisions_seed.json"
# Sample hedges the owner already approved carry ledger entries; those are never dropped.
KEEP_SAMPLE_STATUSES = SPENT_STATUSES


def _sample_hedges(fixtures_dir: Path = FIXTURES_DIR) -> list[Hedge]:
    return TypeAdapter(list[Hedge]).validate_json((fixtures_dir / "examples" / SAMPLE_HEDGES_FILE).read_text())


def _sample_log(fixtures_dir: Path = FIXTURES_DIR) -> list[LogEntry]:
    return TypeAdapter(list[LogEntry]).validate_json((fixtures_dir / "examples" / SAMPLE_LOG_FILE).read_text())


@lru_cache
def sample_hedge_ids(fixtures_dir: Path = FIXTURES_DIR) -> frozenset[str]:
    return frozenset(h.id for h in _sample_hedges(fixtures_dir))


@lru_cache
def sample_log_ids(fixtures_dir: Path = FIXTURES_DIR) -> frozenset[str]:
    return frozenset(e.log_id for e in _sample_log(fixtures_dir))


def is_sample_hedge(hedge_id: str) -> bool:
    return hedge_id in sample_hedge_ids()


def list_sample_hedges(
    business_id: str | None = None, week_of: date | None = None, engine: Engine | None = None
) -> list[Hedge]:
    """Stored hedges that came from the sample week fixture."""
    return [h for h in list_hedges(business_id, week_of, engine=engine) if is_sample_hedge(h.id)]


def sample_businesses(engine: Engine | None = None) -> list[str]:
    """Businesses that still have sample hedges stored (sorted)."""
    return sorted({h.business_id for h in list_sample_hedges(engine=engine)})


def remove_sample_hedges(
    business_id: str | None = None, week_of: date | None = None, engine: Engine | None = None
) -> list[Hedge]:
    """Delete stored sample hedges (all, or one business/week) so a real desk run starts clean.
    Owner-approved/settled ones stay (they have ledger entries). Returns the removed hedges
    (pass them to `put_hedge` to restore). The decision log is untouched (append-only);
    `is_retired_sample_entry` hides the sample entries about removed hedges."""
    drop = [h for h in list_sample_hedges(business_id, week_of, engine) if h.status not in KEEP_SAMPLE_STATUSES]
    if drop:
        with session(engine) as s:
            for h in drop:
                row = s.get(HedgeRow, h.id)
                if row is not None:
                    s.delete(row)
    return drop


def is_retired_sample_entry(entry: LogEntry, engine: Engine | None = None) -> bool:
    """A sample log entry about a sample hedge that a real run has since replaced."""
    return (
        entry.log_id in sample_log_ids()
        and entry.hedge_id is not None
        and is_sample_hedge(entry.hedge_id)
        and get_hedge(entry.hedge_id, engine) is None
    )


def seed(
    engine: Engine | None = None, fixtures_dir: Path = FIXTURES_DIR, sample_week: bool | None = None
) -> dict[str, int]:
    """Load business fixtures and, in sample mode (default: DEMO_SAMPLE_WEEK), the sample week's
    hedges and decision log. Idempotent: businesses/hedges upsert by id, log entries are skipped
    when their log_id exists. A business/week that already has real (non-sample) hedges does not
    get its sample hedges back. Without sample mode only log entries not about a sample hedge
    (the ledger history that `app.books.seed` books) are loaded."""
    if sample_week is None:
        sample_week = get_settings().demo_sample_week
    create_schema(engine)
    for path in sorted((fixtures_dir / "businesses").glob("*.json")):
        put_business(Business.model_validate_json(path.read_text()), engine)
    hedges = _sample_hedges(fixtures_dir)
    week_hedge_ids = {h.id for h in hedges}
    if sample_week:
        real = {(h.business_id, h.week_of) for h in list_hedges(engine=engine) if h.id not in week_hedge_ids}
        for h in hedges:
            if (h.business_id, h.week_of) not in real:
                put_hedge(h, engine)
    for e in _sample_log(fixtures_dir):
        if sample_week or e.hedge_id not in week_hedge_ids:
            append_log(e, engine)
    return row_counts(engine)


def row_counts(engine: Engine | None = None) -> dict[str, int]:
    with session(engine) as s:
        return {
            table.__tablename__: s.exec(select(func.count()).select_from(table)).one()
            for table in (BusinessRow, HedgeRow, LogRow, LedgerRow, RunRow, AnalysisRow, SettingsOverrideRow)
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.db")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_seed = sub.add_parser("seed", help="create schema and load fixtures (idempotent)")
    p_seed.add_argument("--url", help="database URL (default: DATABASE_URL)")
    p_seed.add_argument("--no-sample-week", dest="sample_week", action="store_false", default=None,
                        help="skip the sample week hedges (default: DEMO_SAMPLE_WEEK)")
    args = parser.parse_args(argv)

    if args.cmd == "seed":
        engine = make_engine(args.url) if args.url else get_engine()
        counts = seed(engine, sample_week=args.sample_week)
        print("seeded " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
