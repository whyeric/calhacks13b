"""The weekly desk loop (spec §11) with the deterministic fallback (spec §15, G5/G6/G11/G13/G14).

Entry point used by the API routes (#15, PR #57):

    from app.agent.desk import run_week
    run: DeskRun = await run_week(business_id, week_of, run_id=run_id,
                                  client=None, now=None, engine=None, markets=None, model=None)

- `business_id`: "taxi" | "restaurant".
- `week_of`: any date in the target week; snapped to its Monday.
- `run_id` (keyword): the id the route already handed out (RunAccepted).
- `client`: Anthropic-compatible object (`client.messages.create(**kw)`, sync or async).
  None -> `anthropic.AsyncAnthropic` when ANTHROPIC_API_KEY and ANTHROPIC_MODEL are set,
  otherwise the run is deterministic (`agent: "fallback"`).
- `now`: aware datetime (default `app.clock.now()`); `engine`: SQLAlchemy engine (tests);
  `markets`: an `app.markets.port.MarketsPort` (default `get_markets()`); `model`: overrides
  settings.anthropic_model (tests only; the app always uses the setting, never a literal).

Returns `DeskRun{run_id, agent, hedges, log_ids, summary, business_id, week_of, capped,
skipped_existing, fallback_reasons, already_running, trace}`. `agent` is "claude" only if every
entry this run wrote was Claude's. The route owns RunStatus rows; this function doesn't write them.
Raises on failure (e.g. `analysis.AnalysisUnavailable`); the route records it.

Order: get_exposures (code) -> per hedgeable exposure one bounded Claude turn (search_markets ->
match_market -> size_hedge -> evaluate_hedge -> log_decision, at most
`Thresholds.max_tool_calls` tool calls) -> templated week summary. Whatever Claude leaves undone
(API error after retries, the 90 s deadline, the cap, a second I2 rejection) is finished by the
deterministic path for that exposure (most liquid candidate, templated summary, `agent:
"fallback"`), so every hedge gets exactly one log entry (I5). Claude chooses and explains; it
never produces a number (principle 1). `run_weekly_desk(business_id, *, client=None, now=None)`
is the spec-named wrapper.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.engine import Engine

from app import clock, db
from app.agent import log, policy, prompts
from app.agent.tools import TOOL_SCHEMAS, DeskContext, HedgeState
from app.config import get_settings
from app.markets.port import MarketsPort, get_markets
from app.models import Agent, Hedge

logger = logging.getLogger(__name__)

CALL_TIMEOUT_S = 20.0  # G6
MAX_RETRIES = 2
RUN_DEADLINE_S = 90.0
MAX_TOKENS = 1024
OPEN_STATUSES = ("proposed", "pending_approval", "approved", "settled")
CAPPED_NOTE = "(The desk stopped at its tool-call limit; this entry was finished by the fallback.)"

_locks: dict[str, asyncio.Lock] = {}
_active: dict[str, str] = {}


@dataclass
class DeskRun:
    """Same leading fields as the #57 stub (run_id, agent, hedges, log_ids, summary); the rest is extra."""

    run_id: str
    agent: Agent
    hedges: list[Hedge] = field(default_factory=list)
    log_ids: list[str] = field(default_factory=list)
    summary: str = ""
    business_id: str = ""
    week_of: date | None = None
    capped: list[str] = field(default_factory=list)  # exposure ids whose Claude turn hit the cap
    skipped_existing: list[str] = field(default_factory=list)  # open hedge already this week (G14)
    fallback_reasons: dict[str, str] = field(default_factory=dict)  # exposure id -> why the fallback ran
    already_running: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)  # tool calls: name, input, output, agent


class ClaudeUnavailable(Exception):
    pass


def _retryable() -> tuple[type[BaseException], ...]:
    errs: list[type[BaseException]] = [asyncio.TimeoutError, TimeoutError, ConnectionError]
    try:
        import httpx

        errs += [httpx.TimeoutException, httpx.TransportError]
    except ImportError:
        pass
    try:
        import anthropic

        errs += [anthropic.APITimeoutError, anthropic.APIConnectionError, anthropic.RateLimitError,
                 anthropic.InternalServerError]
    except ImportError:
        pass
    return tuple(errs)


def default_client() -> Any | None:
    s = get_settings()
    if not s.use_claude:
        return None
    import anthropic

    return anthropic.AsyncAnthropic(api_key=s.anthropic_api_key, max_retries=0, timeout=CALL_TIMEOUT_S)


def _block_dict(b: Any) -> dict[str, Any]:
    get = (lambda k: b.get(k)) if isinstance(b, dict) else (lambda k: getattr(b, k, None))
    t = get("type")
    if t == "tool_use":
        return {"type": "tool_use", "id": get("id"), "name": get("name"), "input": get("input") or {}}
    if t == "text":
        return {"type": "text", "text": get("text") or ""}
    return {"type": t}


class _Claude:
    """Model calls with G6 timeouts, bounded retries and the whole-run deadline."""

    def __init__(self, client: Any, model: str, monotonic: Callable[[], float],
                 sleep: Callable[[float], Awaitable[None]], deadline: float):
        self.client, self.model, self.monotonic, self.sleep = client, model, monotonic, sleep
        self.deadline = deadline
        self.retryable = _retryable()

    async def create(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        last: BaseException | None = None
        for attempt in range(MAX_RETRIES + 1):
            if self.monotonic() >= self.deadline:
                raise ClaudeUnavailable("run deadline reached")
            try:
                res = self.client.messages.create(
                    model=self.model, max_tokens=MAX_TOKENS, system=prompts.SYSTEM, tools=TOOL_SCHEMAS,
                    messages=messages,
                )
                if inspect.isawaitable(res):
                    res = await asyncio.wait_for(res, CALL_TIMEOUT_S)
                content = res.get("content") if isinstance(res, dict) else res.content
                return [_block_dict(b) for b in content]
            except self.retryable as e:
                last = e
                if attempt < MAX_RETRIES:
                    await self.sleep(0.5 * (2 ** attempt))
            except Exception as e:  # 4xx, bad response shape: not worth retrying
                raise ClaudeUnavailable(type(e).__name__) from e
        raise ClaudeUnavailable(f"{type(last).__name__} after {MAX_RETRIES} retries")


async def _claude_turn(ctx: DeskContext, claude: _Claude, exposure_id: str, cap: int) -> tuple[bool, int]:
    """One bounded turn for one exposure. Returns (capped, tool_calls_executed)."""
    e = ctx.exposures[exposure_id]
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompts.exposure_turn(e)}]
    calls = 0
    hid = ctx.hedge_id(exposure_id)
    while True:
        content = await claude.create(messages)
        uses = [b for b in content if b["type"] == "tool_use"]
        if not uses:
            return False, calls
        results = []
        for b in uses:
            if calls >= cap:
                return True, calls
            out = await ctx.execute(b["name"], b["input"])
            calls += 1
            results.append({"type": "tool_result", "tool_use_id": b["id"], "content": json.dumps(out)})
        messages += [{"role": "assistant", "content": content}, {"role": "user", "content": results}]
        st = ctx.states.get(hid)
        if st is not None and st.logged:
            return False, calls  # this exposure is done; don't spend more calls


def _liquidity_key(c: dict[str, Any], side: str, n_want: int) -> tuple:
    """G11: highest fillable fraction, then tightest spread, then ticker."""
    depth = int(c.get(f"depth_{side}") or 0)
    ask, bid = c.get(f"{side}_ask"), c.get(f"{side}_bid")
    spread = Decimal(ask) - Decimal(bid) if ask and bid else Decimal(1)
    return (-min(Decimal(1), Decimal(depth) / n_want), spread, c["ticker"])


async def _fallback_exposure(ctx: DeskContext, exposure_id: str, note: str | None = None) -> None:
    """Deterministic path for one exposure; reuses whatever Claude already completed."""
    hid = ctx.hedge_id(exposure_id)
    prev_agent, ctx.agent = ctx.agent, "fallback"
    try:
        if exposure_id not in ctx.candidates:
            await ctx.search_markets(exposure_id)
        st = ctx.states.get(hid)
        if st is None or st.hedge is None:  # candidates exist: pick, size
            e = ctx.exposures[exposure_id]
            cands = ctx.candidates[exposure_id]
            pick = min(cands, key=lambda c: _liquidity_key(c, e.hedge_side, max(1, int(abs(e.effect_usd)))))
            ticker = ctx.matched.get(exposure_id, (pick["ticker"],))[0]
            ctx.match_market(exposure_id, ticker, "Deepest book within five cents on the side we buy.")
            await ctx.size_hedge(exposure_id, ticker)
        st = ctx.states[hid]
        if not st.evaluated:
            await ctx.evaluate_hedge(hid)
        if not st.logged:
            ctx.write_log(st, prompts.template_summary(st.hedge, st.budget), agent="fallback", note=note)
    finally:
        ctx.agent = prev_agent


MULTI_LEG_EVENTS = {"playoff_home"}


async def _season_quotes(markets: MarketsPort):
    """Season futures from the markets port when it has them, else the offline Kalshi cache."""
    from app.markets import season
    from app.markets.kalshi import KalshiClient

    fn = getattr(markets, "season_quotes", None)
    if fn is not None:
        return await fn()
    async with KalshiClient(offline=True) as k:
        return await season.fetch_quotes(k)


async def _season_exposure(ctx: DeskContext, exposure_id: str) -> list[Hedge]:
    """The season playoff hedge: one sized, rule-checked Hedge per futures leg, deterministic.

    Code sizes (min-variance over the season futures) and judges (the existing six rules) every
    leg; each gets a templated summary built from its own checks, logged once (I2, I5)."""
    from app.markets import season
    from app.markets.kalshi import CacheMiss, KalshiError
    from app.markets.port import no_market_hedge

    e = ctx.exposures[exposure_id]
    prev_agent, ctx.agent = ctx.agent, "fallback"
    hedges: list[Hedge] = []
    try:
        try:
            sp = season.plan(e, await _season_quotes(ctx.markets))
        except (CacheMiss, KalshiError, ValueError) as err:
            logger.warning("season futures unavailable for %s: %s", exposure_id, err)
            sp = None
        if sp is None or not sp.legs:
            hid = ctx.leg_hedge_id(exposure_id, "none")
            b = ctx.budget_excluding(hid)
            st = ctx._store(e, no_market_hedge(e, hedge_id=hid, week_of=ctx.week_of, now=ctx.now,
                                               agent="fallback", remaining=b.remaining), b)
            ctx.write_log(st, prompts.template_summary(st.hedge, st.budget), agent="fallback")
            return [st.hedge]
        # Cheapest premium first, so the budget goes to as many legs as it can cover.
        for lp in sorted(sp.legs, key=lambda lp: lp.n_target * (season.best_ask(lp.quote.book, "no") or 1)):
            hid = ctx.leg_hedge_id(exposure_id, lp.quote.leg.key)
            b = ctx.budget_excluding(hid)  # earlier legs are stored, so they already count as pending
            hedge = season.leg_hedge(e, sp, lp, hedge_id=hid, week_of=ctx.week_of, now=ctx.now, agent="fallback",
                                     remaining=b.remaining, thresholds=ctx.thresholds)
            st = ctx._store(e, hedge, b)
            ctx.write_log(st, season.leg_summary(st.hedge, lp), agent="fallback")
            hedges.append(st.hedge)
            ctx.trace.append({"name": "season_hedge", "input": {"exposure_id": exposure_id, "ticker": lp.quote.leg.ticker},
                              "output": st.hedge.model_dump(mode="json", include={"id", "ticker", "n_filled", "premium", "status"}),
                              "agent": "fallback"})
        hedges = season.with_group_total(hedges)
        for h in hedges:
            db.put_hedge(h, ctx.engine)
            ctx.states[h.id].hedge = h
        return hedges
    finally:
        ctx.agent = prev_agent


async def run_week(
    business_id: str,
    week_of: date,
    *,
    run_id: str,
    client: Any = None,
    now: datetime | None = None,
    engine: Engine | None = None,
    markets: MarketsPort | None = None,
    model: str | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> DeskRun:
    """Run the weekly desk for one business and week. See the module docstring."""
    now = now or clock.now()
    week = policy.week_start(week_of)
    lock = _locks.setdefault(business_id, asyncio.Lock())
    if lock.locked():  # G14: a concurrent second call returns the running run's id
        return DeskRun(run_id=_active.get(business_id, run_id), agent="fallback", business_id=business_id,
                       week_of=week, summary="A desk run is already in progress.", already_running=True)
    async with lock:
        _active[business_id] = run_id
        try:
            return await _run(business_id, week, run_id, client, now, engine, markets, model, monotonic, sleep)
        finally:
            _active.pop(business_id, None)


async def _run(business_id, week, run_id, client, now, engine, markets, model, monotonic, sleep) -> DeskRun:
    settings = get_settings()
    model = model or settings.anthropic_model
    if client is None and settings.use_claude:
        client = default_client()
    use_claude = client is not None and bool(model)
    log.install_guards(engine)
    try:  # approval timing (C4-A24/A25): nudge/expire before this run looks at open hedges
        policy.sweep(now, business_id=business_id, engine=engine)
    except Exception:
        logger.exception("approval sweep failed for %s", business_id)

    ctx = DeskContext(business_id=business_id, week_of=week, run_id=run_id, now=now,
                      markets=markets or get_markets(), thresholds=db.get_business_thresholds(business_id, engine),
                      engine=engine, agent="claude" if use_claude else "fallback")
    ctx.get_exposures()
    claude = _Claude(client, model, monotonic, sleep, monotonic() + RUN_DEADLINE_S) if use_claude else None
    cap = ctx.thresholds.max_tool_calls

    open_hedges = db.list_hedges(business_id, week, OPEN_STATUSES, engine)
    existing = {h.exposure_id: h for h in open_hedges}
    run = DeskRun(run_id=run_id, agent="claude", business_id=business_id, week_of=week)
    for exposure_id in ctx.exposures:
        if ctx.exposures[exposure_id].event in MULTI_LEG_EVENTS:  # one hedge per contract leg
            legs = [h for h in open_hedges if h.exposure_id == exposure_id]
            if legs:  # G14 for every leg at once
                run.skipped_existing.append(exposure_id)
                run.hedges.extend(legs)
            else:
                run.fallback_reasons[exposure_id] = "season_hedge"
                run.hedges.extend(await _season_exposure(ctx, exposure_id))
            continue
        if exposure_id in existing:  # G14: same-week rerun reuses the open hedge
            run.skipped_existing.append(exposure_id)
            run.hedges.append(existing[exposure_id])
            continue
        note = None
        if claude is not None:
            try:
                capped, _ = await _claude_turn(ctx, claude, exposure_id, cap)
                if capped:
                    run.capped.append(exposure_id)
                    run.fallback_reasons[exposure_id] = "capped"
                    note = CAPPED_NOTE
            except ClaudeUnavailable as e:
                logger.warning("claude unavailable for %s/%s: %s; falling back", business_id, exposure_id, e)
                run.fallback_reasons[exposure_id] = str(e)
                claude = None  # G6: fallback for the remainder of the run
        st = ctx.states.get(ctx.hedge_id(exposure_id))
        if st is None or not st.logged:
            run.fallback_reasons.setdefault(exposure_id, "no_claude" if claude is None else "unfinished")
            await _fallback_exposure(ctx, exposure_id, note)
        run.hedges.append(ctx.states[ctx.hedge_id(exposure_id)].hedge)

    text, counts = prompts.week_summary(run.hedges)
    run.summary, _ = log.sanitize(text, counts)
    run.log_ids = list(ctx.log_ids)
    agents = {st.agent for st in ctx.states.values() if st.logged}
    run.agent = "claude" if agents == {"claude"} else "fallback"
    run.trace = ctx.trace
    return run


async def run_weekly_desk(business_id: str, *, client: Any = None, now: datetime | None = None,
                          **kw: Any) -> DeskRun:
    """Spec §11 name: the desk week of `now`, a fresh run id."""
    now = now or clock.now()
    return await run_week(business_id, clock.desk_week(now), run_id="run_" + uuid.uuid4().hex[:10],
                          client=client, now=now, **kw)


from app.agent.chat import chat  # noqa: E402  (spec §11 second entry point; lives in chat.py)

__all__ = ["DeskRun", "HedgeState", "chat", "run_week", "run_weekly_desk"]
