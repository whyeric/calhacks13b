"""DEMO_AS_OF pins the demo clock (desk week, expiry, market matching) to the cached week."""

from datetime import date, datetime, timezone

from app import clock, config


def _now_with(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("DEMO_AS_OF", raising=False)
    else:
        monkeypatch.setenv("DEMO_AS_OF", value)
    config.get_settings.cache_clear()
    try:
        return clock.now()
    finally:
        config.get_settings.cache_clear()


def test_demo_as_of_starts_the_clock_there_and_keeps_moving(monkeypatch):
    t = _now_with(monkeypatch, "2026-10-24T19:00:00Z")
    pinned = datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc)
    assert pinned <= t < pinned.replace(hour=23)  # as-of plus the real time since process start
    assert clock.desk_week(t) == date(2026, 10, 26)
    assert _now_with(monkeypatch, "2026-10-24T19:00:00Z") >= t  # monotonic


def test_naive_as_of_is_utc_and_blank_is_the_real_clock(monkeypatch):
    assert _now_with(monkeypatch, "2026-10-24T19:00:00").tzinfo is not None
    real = _now_with(monkeypatch, "")
    assert abs((real - datetime.now(timezone.utc)).total_seconds()) < 5
    assert abs((_now_with(monkeypatch, None) - datetime.now(timezone.utc)).total_seconds()) < 5
