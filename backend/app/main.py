"""Hedge Desk API (C6, issue #15). Every route is typed by a contract model in `models.py`.

- Money/price/probability serialize as strings (models.Money / Price).
- Every non-2xx body is `{"error": {"code", "message", "detail"}}`, FastAPI 422s included.
- `/desk/run` answers 202 and runs `agent.desk.run_week` in a background task, one run per
  business at a time (409 `run_in_progress`); poll `GET /runs/{id}` (R15).
- Approve/reject are owner-only (403 `owner_only`, I4) from `proposed` or `pending_approval`
  (D1 default). Approve goes through `books.ledger.approve_hedge` (-> `book_approval`), which books before the hedge is stored,
  so a booking failure leaves the hedge unchanged (500 `ledger_write_failed`).
- No route updates or deletes a decision-log row; state changes append entries (I5).

Run: `uvicorn app.main:app --reload` from backend/ (`make dev`).
"""

import logging
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import BackgroundTasks, Body, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import analysis, clock, db
from app.config import get_settings
from app.hedge_rules import UNDECIDED, apply_rules
from app.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    ApproveRequest,
    BacktestResult,
    Business,
    ChatReply,
    ChatRequest,
    DeskRunRequest,
    ErrorBody,
    Health,
    Hedge,
    LedgerResponse,
    LogEntry,
    ReconBenchmark,
    ReconResult,
    RejectRequest,
    RunAccepted,
    RunStatus,
    Settings,
    ToolCall,
)

log = logging.getLogger("hedge_desk.api")

OPEN_STATUSES = ("proposed", "pending_approval")
DECIDABLE = OPEN_STATUSES  # D1 default: every passing hedge waits for the owner
LOG_DECISION_KINDS = ("proposal", "decline", "approval", "rejection", "expired_unapproved", "threshold_changed")


# --- Errors ------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: dict[str, Any] | None = None):
        self.status, self.code, self.message, self.detail = status, code, message, detail


def _error(status: int, code: str, message: str, detail: dict[str, Any] | None = None) -> JSONResponse:
    body = ErrorBody.model_validate({"error": {"code": code, "message": message, "detail": detail}})
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


ERRORS = {
    404: {"model": ErrorBody}, 409: {"model": ErrorBody}, 422: {"model": ErrorBody},
}


# --- App ---------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.create_schema()
    if not db.list_businesses():  # first start without `make seed`
        db.seed()  # sample week only when DEMO_SAMPLE_WEEK is on
    if not get_settings().demo_sample_week:
        dropped = db.remove_sample_hedges()
        if dropped:
            log.info("DEMO_SAMPLE_WEEK off: removed sample hedges %s", [h.id for h in dropped])
    if get_settings().backtest_on_startup:  # missing rows only; offline (fixtures + kalshi_history)
        import asyncio

        from app import backtest_job

        try:
            outcome = await asyncio.to_thread(backtest_job.ensure)
            log.info("backtest at startup: %s", outcome)
        except Exception:  # contained: the API starts without a backtest (409 backtest_not_ready)
            log.exception("backtest at startup failed")
    yield


app = FastAPI(title="Hedge Desk API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", "X-Owner-Token"],
)


@app.exception_handler(ApiError)
async def _api_error(_req: Request, exc: ApiError) -> JSONResponse:
    return _error(exc.status, exc.code, exc.message, exc.detail)


@app.exception_handler(RequestValidationError)
async def _validation_error(_req: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"loc": [str(p) for p in e.get("loc", ())], "msg": str(e.get("msg")), "type": str(e.get("type"))}
              for e in exc.errors()]
    return _error(422, "invalid_request", "The request body or parameters are not valid.", {"errors": errors})


@app.exception_handler(StarletteHTTPException)
async def _http_error(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    return _error(exc.status_code, code, str(exc.detail), None)


@app.exception_handler(Exception)
async def _unhandled(_req: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return _error(500, "internal_error", "Something went wrong on the server.", {"type": type(exc).__name__})


# --- Helpers -----------------------------------------------------------------


def _business(business_id: str) -> Business:
    b = db.get_business(business_id)
    if b is None:
        raise ApiError(404, "business_not_found", f"No business with id {business_id!r}.", {"business_id": business_id})
    return b


def _hedge(hedge_id: str) -> Hedge:
    h = db.get_hedge(hedge_id)
    if h is None:
        raise ApiError(404, "hedge_not_found", f"No hedge with id {hedge_id!r}.", {"hedge_id": hedge_id})
    return h


def _labeled(h: Hedge, b: Business | None = None) -> Hedge:
    """I6: a hedge for a business with estimated dollars says so (older rows predate the field)."""
    b = b or db.get_business(h.business_id)
    if b is not None and b.estimated and not h.estimated:
        return h.model_copy(update={"estimated": True})
    return h


def _week(week_of: str | None) -> date:
    """G3: Monday ISO date; any other day snaps to its Monday; omitted = the desk week."""
    if week_of is None:
        return clock.desk_week()
    try:
        return clock.monday_of(date.fromisoformat(week_of))
    except ValueError:
        raise ApiError(422, "bad_week_of", "week_of must be an ISO date like 2026-10-26.", {"week_of": week_of})


def _log(entry: dict[str, Any]) -> LogEntry:
    e = LogEntry.model_validate({
        "log_id": f"log_{uuid.uuid4().hex[:12]}", "created_at": clock.now(), "agent": None, "hedge_id": None,
        "decision_id": None, "run_id": None, "status": None, "checks": [], "reasons": [], "numbers": {},
    } | entry)
    db.append_log(e)
    return e


def _hedge_numbers(h: Hedge) -> dict[str, Any]:
    return {k: getattr(h, k) for k in ("n_filled", "premium", "fee") if getattr(h, k) is not None}


def _expire_stale(hedges: list[Hedge]) -> list[Hedge]:
    """G10 (cut-list): an open hedge whose market closed unapproved becomes expired_unapproved."""
    now, out = clock.now(), []
    for h in hedges:
        if h.status in OPEN_STATUSES and h.close_time is not None and h.close_time <= now:
            h = Hedge.model_validate(h.model_dump() | {"status": "expired_unapproved", "alternative": None})
            db.put_hedge(h)
            _log({"business_id": h.business_id, "kind": "expired_unapproved", "actor": "system",
                  "hedge_id": h.id, "decision_id": h.decision.id, "status": h.status,
                  "summary": f"Expired unapproved: {h.id} closed before the owner decided."})
        out.append(h)
    return out


def _require_owner(actor: str | None, token: str | None, action: str) -> None:
    """I4: only exactly "owner" may approve or reject; optional X-Owner-Token (G1)."""
    if actor != "owner":
        raise ApiError(403, "owner_only", f"Only the owner can {action} a hedge; the desk never decides for you.",
                       {"actor": actor})
    expected = get_settings().owner_token
    if expected and token != expected:
        raise ApiError(403, "owner_only", f"Only the owner can {action} a hedge; the owner token is missing or wrong.",
                       {"actor": actor})


def _require_decidable(h: Hedge) -> None:
    if h.status not in DECIDABLE:
        raise ApiError(409, "invalid_state", f"Hedge {h.id} is {h.status}; only proposed or pending hedges can be decided.",
                       {"status": h.status, "allowed": list(DECIDABLE)})


# --- Health and businesses ---------------------------------------------------


@app.get("/health", response_model=Health)
def health() -> Health:
    s = get_settings()
    sample = db.sample_businesses() if s.demo_sample_week else []
    return Health(status="ok", offline=s.demo_offline, anthropic="configured" if s.use_claude else "fallback",
                  sample_week=bool(sample), sample_businesses=sample)


@app.get("/businesses", response_model=list[Business])
def businesses() -> list[Business]:
    week = clock.desk_week()
    return [b.model_copy(update={"budget": db.compute_budget(b.id, week)}) for b in db.list_businesses()]


# --- Analysis ----------------------------------------------------------------


@app.post("/businesses/{business_id}/analyze", response_model=AnalyzeResponse, responses=ERRORS)
def analyze(business_id: str, body: AnalyzeRequest | None = Body(None)) -> AnalyzeResponse:
    biz = _business(business_id)
    strike = body.strike if body else None
    try:
        res = analysis.analyze(business_id, strike)
    except analysis.AnalysisUnavailable as e:
        raise ApiError(409, "analysis_unavailable", f"No feature data for {business_id} yet.", {"reason": str(e)})
    return res if res.estimated or not biz.estimated else res.model_copy(update={"estimated": True})  # I6


@app.get("/businesses/{business_id}/backtest", response_model=BacktestResult, responses=ERRORS)
def backtest(business_id: str) -> BacktestResult:
    _business(business_id)
    raw = db.get_analysis(business_id, "backtest")
    if raw is None:
        raise ApiError(409, "backtest_not_ready", "The backtest has not been run for this business yet.")
    return BacktestResult.model_validate(raw)


# --- Desk runs ---------------------------------------------------------------

_run_lock = threading.Lock()


async def _run_desk(run_id: str, business_id: str, week_of: date) -> None:
    from app.agent import desk  # looked up at call time so tests can patch run_week

    run = db.get_run(run_id)
    run = run.model_copy(update={"status": "running", "started_at": clock.now()})
    db.put_run(run)
    # A real run replaces the sample week for this business/week instead of reusing its open
    # hedges (G14 reuse is for real hedges only), so the dashboard matches /analyze.
    # A failed run restores them, so the dashboard is never left empty by a crash.
    replaced = db.remove_sample_hedges(business_id, week_of)
    if replaced:
        log.info("desk run %s replaced sample week hedges %s for %s week of %s",
                 run_id, [h.id for h in replaced], business_id, week_of.isoformat())
    try:
        result = await desk.run_week(business_id, week_of, run_id=run_id)
        db.put_run(run.model_copy(update={"status": "done", "agent": result.agent, "finished_at": clock.now()}))
    except Exception as e:  # contained: the API stays up and the failure is logged (C6-A7)
        log.exception("desk run %s failed", run_id)
        if replaced and not db.list_hedges(business_id, week_of):  # the run wrote nothing real
            for h in replaced:
                db.put_hedge(h)
            log.info("desk run %s failed; restored sample week hedges for %s", run_id, business_id)
        err = f"{type(e).__name__}: {e}"[:500]
        db.put_run(run.model_copy(update={"status": "failed", "error": err, "finished_at": clock.now()}))
        _log({"business_id": business_id, "kind": "run_failed", "actor": "system", "run_id": run_id,
              "summary": f"Desk run failed ({type(e).__name__}); no hedges were changed by it."})


@app.post("/businesses/{business_id}/desk/run", status_code=202, response_model=RunAccepted, responses=ERRORS)
def desk_run(business_id: str, background: BackgroundTasks, body: DeskRunRequest | None = Body(None)) -> RunAccepted:
    _business(business_id)
    week = clock.monday_of(body.week_of) if body and body.week_of else clock.desk_week()
    with _run_lock:
        active = db.active_run(business_id)
        if active is not None:
            raise ApiError(409, "run_in_progress", f"A desk run is already {active.status} for {business_id}.",
                           {"run_id": active.run_id})
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        db.put_run(RunStatus(run_id=run_id, business_id=business_id, status="queued", agent=None,
                             started_at=None, finished_at=None, error=None))
    background.add_task(_run_desk, run_id, business_id, week)
    return RunAccepted(run_id=run_id, status="queued")


@app.get("/runs/{run_id}", response_model=RunStatus, responses=ERRORS)
def run_status(run_id: str) -> RunStatus:
    run = db.get_run(run_id)
    if run is None:
        raise ApiError(404, "run_not_found", f"No run with id {run_id!r}.", {"run_id": run_id})
    return run


# --- Hedges and decisions ----------------------------------------------------


@app.get("/businesses/{business_id}/hedges", response_model=list[Hedge], responses=ERRORS)
def hedges(business_id: str, week_of: str | None = Query(None, description="Monday ISO date; other days snap")) -> list[Hedge]:
    biz = _business(business_id)
    return [_labeled(h, biz) for h in _expire_stale(db.list_hedges(business_id, _week(week_of)))]


@app.get("/businesses/{business_id}/decisions", response_model=list[LogEntry], responses=ERRORS)
def decisions(
    business_id: str,
    limit: int = Query(50, ge=1, le=500),
    before: str | None = Query(None, description="log_id cursor: entries older than this one"),
) -> list[LogEntry]:
    _business(business_id)
    # newest first; sample-week entries about replaced sample hedges are hidden (still stored)
    entries = [e for e in reversed(db.list_log(business_id)) if not db.is_retired_sample_entry(e)]
    if before is not None:
        ids = [e.log_id for e in entries]
        if before not in ids:
            raise ApiError(422, "bad_cursor", "before must be a log_id from this business's log.", {"before": before})
        entries = entries[ids.index(before) + 1:]
    return entries[:limit]


@app.post("/hedges/{hedge_id}/approve", response_model=Hedge, responses=ERRORS | {403: {"model": ErrorBody}})
def approve(
    hedge_id: str,
    body: ApproveRequest | None = Body(None),
    x_owner_token: str | None = Header(None),
) -> Hedge:
    h = _hedge(hedge_id)
    _require_owner(body.actor if body else None, x_owner_token, "approve")
    _require_decidable(h)
    from app.books import ledger  # looked up at call time so tests can patch book_approval

    try:  # validates the approved Hedge, books it (+ `booking` log event), then stores it
        approved, _entries = ledger.approve_hedge(h, "owner", at=clock.now())
    except Exception as e:
        log.exception("booking %s failed", hedge_id)
        raise ApiError(500, "ledger_write_failed", "The ledger could not be written; the hedge is unchanged.",
                       {"type": type(e).__name__})
    approved = _labeled(approved)
    _log({"business_id": h.business_id, "kind": "approval", "actor": "owner", "hedge_id": h.id,
          "decision_id": h.decision.id, "status": "approved", "numbers": _hedge_numbers(approved),
          "summary": f"Owner approved {h.id}: {h.n_filled} {h.side.upper()} contracts for ${h.premium}."})
    return approved


@app.post("/hedges/{hedge_id}/reject", response_model=Hedge, responses=ERRORS | {403: {"model": ErrorBody}})
def reject(
    hedge_id: str,
    body: RejectRequest | None = Body(None),
    x_owner_token: str | None = Header(None),
) -> Hedge:
    h = _hedge(hedge_id)
    _require_owner(body.actor if body else None, x_owner_token, "reject")
    _require_decidable(h)
    rejected = Hedge.model_validate(h.model_dump() | {"status": "rejected", "decided_by": "owner",
                                                      "decided_at": clock.now(), "alternative": None})
    db.put_hedge(rejected)
    reason = f" Reason: {body.reason}" if body and body.reason else ""
    _log({"business_id": h.business_id, "kind": "rejection", "actor": "owner", "hedge_id": h.id,
          "decision_id": h.decision.id, "status": "rejected", "numbers": _hedge_numbers(h),
          "summary": f"Owner rejected {h.id}.{reason}"})
    return _labeled(rejected)


# --- Books -------------------------------------------------------------------


@app.get("/businesses/{business_id}/ledger", response_model=LedgerResponse, responses=ERRORS)
def ledger_view(business_id: str) -> LedgerResponse:
    """Entries plus the latest reconciliation: the one stored by POST /reconcile, else a
    fresh read-only run when anything has settled (R10)."""
    _business(business_id)
    from app.books import reconcile as recon

    raw = db.get_analysis(business_id, "reconciliation")
    result = ReconResult.model_validate(raw) if raw is not None else None
    if result is None and recon.has_settlements(business_id):
        result = recon.reconcile(business_id, log=False)
    return LedgerResponse(entries=db.list_ledger_entries(business_id), reconciliation=result, simulated=True)


@app.post("/businesses/{business_id}/reconcile", response_model=ReconResult, responses=ERRORS)
def reconcile(business_id: str, _body: dict | None = Body(None)) -> ReconResult:
    """Three-way reconciliation (C5, pure, no LLM); appends a `reconciliation` log event.
    409 `nothing_to_reconcile` until some approved hedge has settled."""
    _business(business_id)
    from app.books import reconcile as recon

    if not recon.has_settlements(business_id):
        raise ApiError(409, "nothing_to_reconcile", "No hedge has settled yet, so there is nothing to reconcile.")
    result = recon.reconcile(business_id)
    db.put_analysis(business_id, "reconciliation", result, clock.now().isoformat())
    return result


# --- Chat --------------------------------------------------------------------


@app.post("/businesses/{business_id}/chat", response_model=ChatReply, responses=ERRORS)
async def chat(business_id: str, body: ChatRequest) -> ChatReply:
    """Chat "why?" (#46): `agent.chat.chat` with read-only tools, the I2 validator on the reply
    and code-enforced guards; deterministic answer without ANTHROPIC_API_KEY. Not logged (G4).
    Never 5xx."""
    _business(business_id)
    from app.agent import chat as agent_chat  # looked up at call time so tests can patch it

    try:
        out = await agent_chat.chat(business_id, body.message)
        calls = [ToolCall(name=c["name"], input=c["input"], output=c["output"]) for c in out["tool_calls"]]
        return ChatReply(reply=out["reply"], tool_calls=calls)
    except Exception:
        log.exception("chat failed")
        return ChatReply(reply="The desk can't answer right now; the decision log has the details.", tool_calls=[])


# --- Approval timing sweep (#46, G8) -----------------------------------------
# Nudge once 3 h before close, expire at close (`agent.policy.sweep`). A 60 s loop wraps the
# app's lifespan here, so the startup code above stays untouched.

SWEEP_INTERVAL_S = 60.0


async def _sweep_loop(interval: float = SWEEP_INTERVAL_S) -> None:
    import asyncio

    from app.agent import policy

    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(policy.sweep, clock.now())
        except Exception:  # contained: a failed sweep never takes the API down
            log.exception("approval sweep failed")


def _with_sweep(inner):
    @asynccontextmanager
    async def lifespan_with_sweep(a: FastAPI):
        import asyncio

        async with inner(a) as state:
            task = asyncio.create_task(_sweep_loop())
            try:
                yield state
            finally:
                task.cancel()

    return lifespan_with_sweep


app.router.lifespan_context = _with_sweep(app.router.lifespan_context)


# --- Settings ----------------------------------------------------------------


@app.get("/businesses/{business_id}/settings", response_model=Settings, responses=ERRORS)
def get_settings_route(business_id: str) -> Settings:
    _business(business_id)
    return db.get_business_settings(business_id)


@app.put("/businesses/{business_id}/settings", response_model=Settings, responses=ERRORS)
def put_settings_route(business_id: str, body: Settings) -> Settings:
    """Store the overrides, then re-run the rules (no Claude) on this week's open hedges and
    log each status flip (R14)."""
    _business(business_id)
    db.put_business_settings(business_id, body)
    th = db.get_business_thresholds(business_id)
    week = clock.desk_week()
    for h in db.list_hedges(business_id, week, UNDECIDED):
        budget = db.compute_budget(business_id, week)
        own = h.premium if (h.status in OPEN_STATUSES and h.premium is not None) else Decimal("0")
        new = apply_rules(h, th, budget.remaining + own)
        if new == h:
            continue
        db.put_hedge(new)
        if new.status != h.status:
            _log({"business_id": business_id, "kind": "threshold_changed", "actor": "owner", "hedge_id": h.id,
                  "decision_id": h.decision.id, "status": new.status, "checks": new.decision.checks,
                  "reasons": new.decision.reasons,
                  "summary": f"Settings changed: {h.id} went from {h.status} to {new.status}."})
    return db.get_business_settings(business_id)


# --- Reconciliation benchmark ------------------------------------------------


@app.get("/benchmarks/reconciliation", response_model=ReconBenchmark)
def reconciliation_benchmark() -> ReconBenchmark:
    """The real reconciler scored on a SIMULATED world with planted errors and an answer key
    (`books.benchmark`). Deterministic, offline, never touches the app's books; memoized."""
    from app.books import benchmark

    return benchmark.cached()
