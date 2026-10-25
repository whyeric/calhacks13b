"""The desk's memory across weeks: what happened to an exposure's earlier hedges.

Finance runs for months, so a decision in March should shape how the desk asks in June. Before
a hedge is stored, `owner_history` collects the same exposure's earlier hedges for the business
(the owner's approvals, rejections with their reasons, expiries, and how settled ones paid) from
the hedges table and the decision log. It is code, read-only and deterministic; the numbers come
from stored hedges and settlement entries, never from Claude (I2).

It changes how the desk asks, never what the rules decide: a hedge that passes every rule is
still proposed, and the owner still decides (I3, I4). When the owner rejected the last two
decided hedges for this exposure, `pattern` is "rejected_recently" and the proposal opens with
that reminder and the owner's last reason, so the owner isn't asked the same question blind.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.engine import Engine

from app import db
from app.models import Exposure, HistoryOutcome, OwnerHistory

MAX_RECENT = 5
ZERO = Decimal("0.00")
DECIDED = ("approved", "settled", "rejected")
EVENT_NAMES = {"rain": "rain", "hot": "hot-day", "home_win": "home-win", "playoff_home": "playoff"}


def _payout(hedge_id: str, business_id: str, engine: Engine | None) -> Decimal | None:
    for e in db.list_log(business_id, hedge_id=hedge_id, engine=engine):
        if e.kind == "settlement":
            return Decimal(str(e.numbers.get("payout", "0"))).quantize(ZERO)
        if e.kind == "expired":
            return ZERO
    return None


def owner_history(
    business_id: str, exposure_id: str, before_week: date, engine: Engine | None = None,
) -> OwnerHistory | None:
    """Earlier real hedges (sample-week examples excluded) for this exposure, newest first; None if none."""
    earlier = [
        h for h in db.list_hedges(business_id, None, None, engine)
        if h.exposure_id == exposure_id and h.week_of < before_week and not db.is_sample_hedge(h.id)
    ]
    if not earlier:
        return None
    earlier.sort(key=lambda h: (h.week_of, h.created_at), reverse=True)
    outcomes = [
        HistoryOutcome(
            hedge_id=h.id, week_of=h.week_of, status=h.status, premium=h.premium,
            payout=_payout(h.id, business_id, engine) if h.status == "settled" else None,
            note=h.decision_note,
        )
        for h in earlier
    ]
    spent = [h.premium for h in earlier if h.status in ("approved", "settled") and h.premium is not None]
    decided = [o for o in outcomes if o.status in DECIDED]
    pattern = "rejected_recently" if len(decided) >= 2 and all(o.status == "rejected" for o in decided[:2]) else None
    return OwnerHistory(
        n_earlier=len(earlier),
        n_approved=sum(o.status in ("approved", "settled") for o in outcomes),
        n_rejected=sum(o.status == "rejected" for o in outcomes),
        n_expired_unapproved=sum(o.status == "expired_unapproved" for o in outcomes),
        total_premium=sum(spent, ZERO),
        total_payout=sum((o.payout for o in outcomes if o.payout is not None), ZERO),
        recent=outcomes[:MAX_RECENT],
        pattern=pattern,
    )


def reminder(history: OwnerHistory | None, exposure: Exposure) -> str | None:
    """The sentence a proposal opens with when the owner's recent decisions say to ask differently."""
    if history is None or history.pattern != "rejected_recently":
        return None
    name = EVENT_NAMES.get(exposure.event, exposure.event)
    last = next((o.note for o in history.recent if o.status == "rejected" and o.note), None)
    text = f"You rejected the last two {name} hedges"
    text += f' (last reason: "{last}")' if last else ""
    return text + "; the rules pass again this week, so the desk asks once more, and you decide."
