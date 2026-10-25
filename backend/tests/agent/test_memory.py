"""The desk's memory across weeks (agent/memory.py)."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app import db
from app.agent import memory
from app.models import Exposure, Hedge

EXAMPLES = db.FIXTURES_DIR / "examples"


def _hedge(hid: str, week: date, status: str, note: str | None = None) -> Hedge:
    data = json.loads((EXAMPLES / "hedge_proposed.json").read_text())
    decided = status in ("approved", "rejected", "settled")
    at = datetime.combine(week, datetime.min.time(), UTC) + timedelta(days=1)
    data.update(id=hid, business_id="taxi", exposure_id="exp_rain", week_of=week.isoformat(), status=status,
                created_at=at.isoformat(), decided_by="owner" if decided else None,
                decided_at=at.isoformat() if decided else None, decision_note=note,
                ledger_entry_ids=["le_x"] if status in ("approved", "settled") else [])
    return Hedge.model_validate(data)


def test_history_and_the_rejected_recently_pattern(tmp_path):
    engine = db.make_engine(f"sqlite:///{tmp_path / 'm.db'}")
    db.create_schema(engine)
    for h in (_hedge("hdg_a", date(2026, 9, 28), "approved"),
              _hedge("hdg_b", date(2026, 10, 5), "rejected", "too pricey"),
              _hedge("hdg_c", date(2026, 10, 12), "expired_unapproved"),
              _hedge("hdg_d", date(2026, 10, 19), "rejected", "I'll eat rain days in October"),
              _hedge("hdg_now", date(2026, 10, 26), "proposed")):  # this week: not history
        db.put_hedge(h, engine)
    hist = memory.owner_history("taxi", "exp_rain", date(2026, 10, 26), engine)
    assert hist.n_earlier == 4 and (hist.n_approved, hist.n_rejected, hist.n_expired_unapproved) == (1, 2, 1)
    assert [o.hedge_id for o in hist.recent] == ["hdg_d", "hdg_c", "hdg_b", "hdg_a"]
    assert hist.pattern == "rejected_recently"  # the last two *decided* were both rejections
    assert hist.total_premium == Decimal(_hedge("x", date(2026, 9, 28), "approved").premium)
    rain = Exposure.model_validate(json.loads((EXAMPLES / "exposure.json").read_text()) | {"event": "rain"})
    text = memory.reminder(hist, rain)
    assert text.startswith("You rejected the last two rain hedges") and "I'll eat rain days" in text


def test_no_history_no_reminder(tmp_path):
    engine = db.make_engine(f"sqlite:///{tmp_path / 'm.db'}")
    db.create_schema(engine)
    assert memory.owner_history("taxi", "exp_rain", date(2026, 10, 26), engine) is None
    assert memory.reminder(None, None) is None
