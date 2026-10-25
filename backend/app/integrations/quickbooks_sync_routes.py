"""Routes for the QuickBooks write-back (included by main.py with one `include_router` line).

GET /integrations/quickbooks/sync?business_id=  ->  QboSyncReport (read-only drift check)
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app import db
from app.integrations import quickbooks as qbo
from app.integrations import quickbooks_sync as qbo_sync
from app.models import ErrorBody, QboSyncReport

router = APIRouter()


def _error(status: int, code: str, message: str, detail: dict[str, Any] | None = None) -> JSONResponse:
    body = ErrorBody.model_validate({"error": {"code": code, "message": message, "detail": detail}})
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


@router.get("/integrations/quickbooks/sync", response_model=QboSyncReport,
            responses={404: {"model": ErrorBody}, 409: {"model": ErrorBody}, 502: {"model": ErrorBody}})
async def quickbooks_sync(business_id: str = Query(..., max_length=64)) -> Any:
    """Each of the business's ledger entries next to the QuickBooks JournalEntry that mirrors it,
    read back from QuickBooks (or the SYNTHETIC demo store): posted, missing (deleted there),
    amount_differs (edited there), failed (never got there) or not_posted. Beancount is the record;
    this only reads. 409 `not_connected` before QuickBooks is connected."""
    if db.get_business(business_id) is None:
        return _error(404, "business_not_found", f"No business with id {business_id!r}.", {"business_id": business_id})
    try:
        return await asyncio.to_thread(qbo_sync.sync_report, business_id)
    except qbo.QuickBooksError as e:
        return _error(e.status, e.code, e.message, e.detail)
