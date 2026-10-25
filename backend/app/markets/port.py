"""The one call the desk makes into markets: exposure -> sized, evaluated `Hedge`.

Two implementations behind one interface:

- `KalshiMarkets`: the real C3 pipeline (`app.markets.kalshi/match/sizing/rules`, PR #48):
  candidates -> deterministic pick -> size -> evaluate. Offline it reads `fixtures/kalshi_cache/`.
- `FixtureMarkets`: the example hedges in `fixtures/examples/hedge_*.json`, re-keyed to this
  business/week and re-judged with this business's thresholds and budget. Used until #48
  lands, and whenever `MARKETS_BACKEND=fixture`.

`get_markets()` picks one: `MARKETS_BACKEND=auto` (default) uses Kalshi when the module imports.
"""

import importlib.util
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Protocol

from app.config import FIXTURES_DIR, Thresholds, get_settings
from app.hedge_rules import apply_rules
from app.models import CHECK_ORDER, Agent, Check, Decision, Exposure, Hedge


class MarketsPort(Protocol):
    name: str

    async def hedge_for(
        self, exposure: Exposure, *, hedge_id: str, week_of: date, now: datetime, agent: Agent,
        remaining: Decimal, thresholds: Thresholds, ticker: str | None = None,
    ) -> Hedge: ...

    async def candidates(self, exposure: Exposure, now: datetime) -> list[dict]: ...


def no_market_hedge(
    exposure: Exposure, *, hedge_id: str, week_of: date, now: datetime, agent: Agent, remaining: Decimal
) -> Hedge:
    """Declined with `no_market`; the other decline checks are skipped (I3: shown, not hidden)."""
    checks = [Check(code="no_market", passed=False, metric={"n_candidates": 0})]
    checks += [Check(code=c, passed=None, metric={"skipped": "no_market"}) for c in CHECK_ORDER[1:-1]]
    checks.append(Check(code="over_budget", passed=True, metric={"premium": Decimal("0.00"), "remaining": remaining}))
    decision = Decision(id=f"dec_{hedge_id}", status="declined", checks=checks, reasons=["no_market"], summary=None)
    return Hedge(
        id=hedge_id, business_id=exposure.business_id, exposure_id=exposure.id, week_of=week_of,
        status="declined", ticker=None, market_title=None, market_url=None, close_time=None,
        side=exposure.hedge_side, match_reason=None, h=None, n_target=0, n_filled=0, n_unfilled=0,
        partial=False, resized=False, fills=None, avg_price=None, cost=None, fee=None, premium=None,
        fair=None, expected_cost=None, fee_unverified=False, payoff=None, headline=None,
        decision=decision, alternative=None, agent=agent, ledger_entry_ids=[], created_at=now,
        decided_by=None, decided_at=None,
    )


class FixtureMarkets:
    """Example hedges as the market answer. Clearly a stub: the sizing comes from the
    example file, not from this exposure's effect."""

    name = "fixture"

    def __init__(self, examples_dir=FIXTURES_DIR / "examples"):
        self._hedges = [
            Hedge.model_validate_json(p.read_text()) for p in sorted(examples_dir.glob("hedge_*.json"))
            if p.name != "hedge_lite.json"
        ]

    def _example(self, exposure: Exposure) -> Hedge | None:
        same_business = [h for h in self._hedges if h.business_id == exposure.business_id]
        for pool in (same_business, self._hedges):
            for h in pool:
                if h.exposure_id == exposure.id:
                    return h
        return None

    async def candidates(self, exposure: Exposure, now: datetime) -> list[dict]:
        """The example hedge's market as the only candidate (tool-facing row, agent #45)."""
        ex = self._example(exposure)
        if ex is None or ex.ticker is None:
            return []
        ask = ex.avg_price or Decimal("0.50")
        other = (Decimal(1) - ask + Decimal("0.01")).quantize(Decimal("0.01"))
        side = exposure.hedge_side
        return [{
            "ticker": ex.ticker, "series": ex.ticker.split("-")[0], "title": ex.market_title,
            "close_ts": ex.close_time.isoformat() if ex.close_time else None,
            "yes_ask": str(ask if side == "yes" else other), "no_ask": str(ask if side == "no" else other),
            "depth_yes": ex.n_filled if side == "yes" else 0, "depth_no": ex.n_filled if side == "no" else 0,
            "rules_primary": f"Fixture market {ex.ticker} (offline example).", "floor_strike": None,
        }]

    async def hedge_for(
        self, exposure: Exposure, *, hedge_id: str, week_of: date, now: datetime, agent: Agent,
        remaining: Decimal, thresholds: Thresholds, ticker: str | None = None,
    ) -> Hedge:
        ex = self._example(exposure)
        if ex is None:
            return no_market_hedge(exposure, hedge_id=hedge_id, week_of=week_of, now=now, agent=agent,
                                   remaining=remaining)
        shift = timedelta(days=(week_of - ex.week_of).days)
        data = ex.model_dump() | {
            "id": hedge_id, "business_id": exposure.business_id, "exposure_id": exposure.id,
            "week_of": week_of, "created_at": now, "agent": agent, "status": ex.decision.status,
            "close_time": ex.close_time + shift if ex.close_time else None,
            "ledger_entry_ids": [], "decided_by": None, "decided_at": None,
        }
        data["decision"] = ex.decision.model_dump() | {"id": f"dec_{hedge_id}", "summary": None}
        return apply_rules(Hedge.model_validate(data), thresholds, remaining)


class KalshiMarkets:
    """The real C3 pipeline (needs `app.markets.kalshi` from PR #48)."""

    name = "kalshi"

    def _basis_and_phat(self, exposure: Exposure):
        from app.data import features
        from app.stats.exposure import beta_settlement

        df = features.build(exposure.business_id)
        if exposure.event == "home_win":
            return None, Decimal(repr(features.event_frequency(df, "home_win"))).quantize(Decimal("0.0001"))
        df = features.add_settlement(df, strike=exposure.strike)
        col = f"settle_{exposure.event}"
        basis = beta_settlement(df, df[col], event=exposure.event,
                                strikes={"hot": exposure.strike} if exposure.strike is not None else None)
        p_hat = Decimal(repr(features.event_frequency(df, col))).quantize(Decimal("0.0001"))
        return basis, p_hat

    async def candidates(self, exposure: Exposure, now: datetime) -> list[dict]:
        """Tool-facing candidate rows for Claude's pick (agent #45)."""
        from app.markets.kalshi import KalshiClient
        from app.markets.match import build_candidates

        async with KalshiClient(offline=get_settings().demo_offline) as k:
            cands = await build_candidates(k, exposure, now)

        def p(x):
            return None if x is None else str(x)

        return [{
            "ticker": c.ticker, "series": c.series_ticker, "title": c.title, "close_ts": c.close_time.isoformat(),
            "yes_ask": p(c.yes_ask), "no_ask": p(c.no_ask), "yes_bid": p(c.yes_bid), "no_bid": p(c.no_bid),
            "depth_yes": c.depth_within_5c.yes, "depth_no": c.depth_within_5c.no,
            "rules_primary": c.rules_primary, "floor_strike": p(c.floor_strike),
        } for c in cands]

    async def hedge_for(
        self, exposure: Exposure, *, hedge_id: str, week_of: date, now: datetime, agent: Agent,
        remaining: Decimal, thresholds: Thresholds, ticker: str | None = None,
    ) -> Hedge:
        from app.markets.kalshi import CacheMiss, KalshiClient
        from app.markets.match import build_candidates, deterministic_pick
        from app.markets.rules import evaluate, resolve_h
        from app.markets.sizing import size_hedge, to_hedge

        basis, p_hat = self._basis_and_phat(exposure)
        sizing = None
        try:
            async with KalshiClient(offline=get_settings().demo_offline) as k:
                cands = await build_candidates(k, exposure, now)
                chosen = [c for c in cands if c.ticker == ticker]  # Claude's validated pick, if any
                pick = chosen[0] if chosen else deterministic_pick(cands, exposure.hedge_side)
                if pick is not None:
                    h = resolve_h(basis, exposure.effect_usd, thresholds) or Decimal(1)
                    series = await k.get_series(pick.series_ticker)
                    book = await k.get_orderbook(pick.ticker)
                    sizing = size_hedge(exposure, pick, book, h, p_hat, series, thresholds.max_slip)
        except CacheMiss:
            return no_market_hedge(exposure, hedge_id=hedge_id, week_of=week_of, now=now, agent=agent,
                                   remaining=remaining)
        decision = evaluate(exposure, cands, sizing, basis, remaining, thresholds, decision_id=f"dec_{hedge_id}")
        return to_hedge(exposure, sizing, decision, hedge_id=hedge_id, week_of=week_of, created_at=now, agent=agent)


def kalshi_available() -> bool:
    return all(importlib.util.find_spec(f"app.markets.{m}") is not None for m in ("kalshi", "match", "sizing", "rules"))


@lru_cache
def _fixture() -> FixtureMarkets:
    return FixtureMarkets()


def get_markets() -> MarketsPort:
    backend = get_settings().markets_backend
    if backend == "kalshi" or (backend == "auto" and kalshi_available()):
        return KalshiMarkets()
    return _fixture()


__all__ = ["MarketsPort", "FixtureMarkets", "KalshiMarkets", "get_markets", "no_market_hedge"]
