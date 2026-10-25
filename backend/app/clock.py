"""One clock for the app, so tests can pin "now" (`monkeypatch.setattr(clock, "now", ...)`).

Call it as `clock.now()`, never `from app.clock import now`, or the patch won't reach you.
"""

from datetime import date, datetime, timedelta, timezone


def now() -> datetime:
    return datetime.now(timezone.utc)


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def desk_week(at: datetime | None = None) -> date:
    """The week the desk works on: this Monday on weekdays; on Saturday and Sunday the
    coming Monday, because a weekend run plans the next week (G3 "current week")."""
    d = (at or now()).date()
    return monday_of(d) + timedelta(days=7) if d.weekday() >= 5 else monday_of(d)
