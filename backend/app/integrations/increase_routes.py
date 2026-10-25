"""Increase bank routes (integrations/increase.py, docs/INCREASE.md). Included from main.py."""

from fastapi import APIRouter

from app.models import IncreaseStatus

router = APIRouter(prefix="/integrations/increase", tags=["integrations"])


@router.get("/status", response_model=IncreaseStatus)
def increase_status() -> IncreaseStatus:
    """Which bank the reconciler reads: demo (the simulated CSV), sandbox or live. No network call."""
    from app.integrations import increase

    return increase.status()
