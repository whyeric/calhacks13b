"""A live hedge quote for a FOUND downside in an uploaded revenue file (POST /research/quote).

The research report is stateless, so the quote re-runs the protocol on the same CSV and builds
the exposure from its own output (I2: every number comes from code). Then it is the desk's
pipeline unchanged: Kalshi and Polymarket candidates for the next 8 days, the deepest book on
the side we buy, sizing capped at the measured exposure (I1), and every decline rule (I3).

What differs from a desk run, and is said on the quote:
- Basis: the research flags are NOAA Central Park rain days, the station both venues settle on
  (Kalshi KXRAIN reads The Weather Company at Central Park since 2026-08-14; Polymarket reads
  the NWS climate report for Central Park), so rule 4 is taken as a full match (r² = 1).
- p̂ (rule 3's fair price) is the rain-day share of the train year in the file.
- `unstable` uses the holdout refit, the same way the desk does.
- The budget is the default weekly budget; nothing is stored, so there is nothing to approve.
  Approval and booking need the business saved first (the built-in businesses have both).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from app import clock
from app.config import get_settings, get_thresholds
from app.models import (
    BasisStat,
    Budget,
    Exposure,
    ResearchHypothesis,
    ResearchPeriod,
    ResearchQuote,
    Stability,
)

SETTLEMENT_VARS = {"rain": "rain"}  # research hypothesis -> desk settlement var
CENT = Decimal("0.01")
Z90 = Decimal("1.6449")
BASIS_NOTE = ("Research flags are NOAA Central Park rain days, the station both venues settle on, so the "
              "basis check treats them as a full match.")


class QuoteRefused(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def exposure_from(h: ResearchHypothesis) -> Exposure:
    """The desk's Exposure for one FOUND downside, from the report's own train and holdout fits."""
    if not h.sendable or h.id not in SETTLEMENT_VARS or h.train is None:
        raise QuoteRefused("not_sendable", f"{h.label} has no daily contract the desk can price.")
    t, ho = h.train, h.holdout
    lo, hi = t.ci90
    se = ((hi - lo) / (2 * Z90)).quantize(CENT)
    stability = None
    if ho is not None:
        same = (ho.effect_usd > 0) == (t.effect_usd > 0)
        stability = Stability(effect_usd=ho.effect_usd, ci90=ho.ci90, n_days=ho.n_days, n_events=ho.n_event_days,
                              start=ho.start, end=ho.end, same_sign=same, stable=same and ho.ci_excludes_zero)
    positive = t.effect_usd > 0
    var = SETTLEMENT_VARS[h.id]
    return Exposure(
        id=f"exp_upload_{h.id}", business_id="upload", event=var, effect_usd=t.effect_usd, ci90=t.ci90, se=se,
        p_value=t.p_value, n_events_train=t.n_event_days, direction="positive" if positive else "negative",
        hedge_side="no" if positive else "yes", settlement_var=var, hedgeable=True, reasons=[], strike=None,
        beta_settlement=t.effect_usd, stability=stability,
        basis_note=BASIS_NOTE,
    )


async def quote(h: ResearchHypothesis, now: datetime | None = None, window_days: int = 8) -> ResearchQuote:
    from app.markets import polymarket
    from app.markets.kalshi import CacheMiss, KalshiClient
    from app.markets.match import build_candidates, deterministic_pick
    from app.markets.port import no_market_hedge, venue_comparison
    from app.markets.rules import evaluate, resolve_h
    from app.markets.sizing import size_hedge, to_hedge

    now = now or clock.now()
    e = exposure_from(h)
    th = get_thresholds()
    settings = get_settings()
    budget_amt = settings.weekly_budget_default.quantize(CENT)
    week = clock.desk_week(now)
    budget = Budget(budget=budget_amt, spent=Decimal("0.00"), pending=Decimal("0.00"), remaining=budget_amt,
                    week_start=week)
    basis = BasisStat(r2=Decimal("1"), beta_s=e.effect_usd, se=e.se)
    p_hat = (Decimal(h.train.n_event_days) / Decimal(h.train.n_days)).quantize(Decimal("0.0001"))
    hid = f"quote_upload_{h.id}"
    today = now.astimezone(polymarket.NY_TZ).date()
    window = ResearchPeriod(start=today + timedelta(days=1), end=today + timedelta(days=window_days))
    sizing, pm_note = None, None
    try:
        async with KalshiClient(offline=settings.demo_offline) as k:
            cands = await build_candidates(k, e, now, window_days=window_days)
            pm_books: dict = {}
            if settings.polymarket_enabled:
                async with polymarket.PolymarketClient() as pm:
                    pm_cands, pm_books, pm_note = await polymarket.build_candidates(
                        pm, e.settlement_var, now, window_days=window_days)
                cands, pm_note = cands + pm_cands, pm_note or ""
            pick = deterministic_pick(cands, e.hedge_side)
            if pick is not None:
                ratio = resolve_h(basis, e.effect_usd, th) or Decimal(1)
                if pick.venue == "polymarket":
                    fees, book = pick, pm_books[pick.ticker]
                else:
                    fees, book = await k.get_series(pick.series_ticker), await k.get_orderbook(pick.ticker)
                sizing = size_hedge(e, pick, book, ratio, p_hat, fees, th.max_slip)
    except CacheMiss:
        hedge = no_market_hedge(e, hedge_id=hid, week_of=week, now=now, agent="fallback",
                                remaining=budget.remaining, thresholds=th, scanned_venues=True)
        return ResearchQuote(hypothesis_id=h.id, exposure=e, hedge=hedge, budget=budget, p_hat=p_hat,
                             window=window, basis_note=BASIS_NOTE)
    decision = evaluate(e, cands, sizing, basis, budget.remaining, th, decision_id=f"dec_{hid}", venue_note=pm_note)
    reason = venue_comparison(cands, sizing.ticker, e.hedge_side) if sizing is not None else None
    hedge = to_hedge(e, sizing, decision, hedge_id=hid, week_of=week, created_at=now, agent="fallback",
                     match_reason=reason)
    from app.agent import policy, prompts

    hedge = hedge.model_copy(update={"needs_controller": policy.needs_controller(hedge, th)})
    if hedge.decision.summary is None:  # templated from the hedge's own numbers (I2)
        text = prompts.template_summary(hedge, budget)
        hedge = hedge.model_copy(update={"decision": hedge.decision.model_copy(update={"summary": text})})
    return ResearchQuote(hypothesis_id=h.id, exposure=e, hedge=hedge, budget=budget, p_hat=p_hat, window=window,
                         basis_note=BASIS_NOTE)
