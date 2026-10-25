"""One clock for the app, so tests can pin "now" (`monkeypatch.setattr(clock, "now", ...)`).

Call it as `clock.now()`, never `from app.clock import now`, or the patch won't reach you.

`DEMO_AS_OF` (config) pins the demo: `now()` is that instant at process start plus the real
time elapsed since, so timestamps still move forward (log order, expiry) while the desk week
and market matching stay on the cached demo week.
"""

from datetime import date, datetime, timedelta, timezone

_STARTED = datetime.now(timezone.utc)


def now() -> datetime:
    real = datetime.now(timezone.utc)
    from app.config import get_settings  # lazy: config imports nothing from here

    as_of = get_settings().demo_as_of
    return real if as_of is None else as_of + (real - _STARTED)


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def desk_week(at: datetime | None = None) -> date:
    """The week the desk works on: this Monday on weekdays; on Saturday and Sunday the
    coming Monday, because a weekend run plans the next week (G3 "current week")."""
    d = (at or now()).date()
    return monday_of(d) + timedelta(days=7) if d.weekday() >= 5 else monday_of(d)
