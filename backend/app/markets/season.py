"""Season-level playoff hedge: NO on the Knicks' live season futures, sized by minimum variance.

Before the season there are no playoff series markets, but three season contracts are live:

    KXNBAPLAYOFF-27-NYK  the Knicks make the playoffs
    KXNBAEAST-27-NYK     the Knicks win the Eastern Conference
    KXNBA-27-NYK         the Knicks win the title

Each one's NO pays $1 in a state where the bar loses playoff home nights (missed playoffs, out
before the conference final ends, out in the Finals). `plan()` prices every playoff path with the
series model in `app.markets.playoffs` (per-game strength fitted to the futures mids, the NBA home
edge, home court unknown = 0.5), then solves the minimum-variance hedge of
`effect_usd x home games` over the three contracts. Each leg becomes one `Hedge` with the same
exposure id, sized and judged by the existing rules (`rules.evaluate`), so the Hedge contract does
not change:

- the leg's protected amount (`effect_usd` for the rules) is its dollar swing: effect_usd x
  (E[home games | YES] - E[home games | NO]); contracts are capped at that (I1, h = 1);
- `fair` is 1 - the YES mid (the market's own probability, no spread or fee);
- rule 4's r2 is the variance the whole season hedge removes in the model.

Money is Decimal; the float model statistics are quantized before they reach a contract.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable

from app.config import Thresholds
from app.models import Agent, BasisStat, Exposure, Headline, Hedge

from . import playoffs as pm
from .kalshi import DEFAULT_CACHE_DIR, KalshiClient, Orderbook, _cache_key, ask_levels, best_ask, best_bid, parse_orderbook
from .match import Candidate, Depth, depth_within
from .rules import evaluate
from .shapes import Sizing
from .summary import fallback_summary
from .sizing import money, order_fee, payoff_table, places4, to_hedge, walk_book

ONE = Decimal("1")
ZERO = Decimal("0")
LEAGUE = "nba"
FMT = "2-2-1-1-1"
P_HOME = 0.5  # home court unknown before the season (stated in the basis note)


@dataclass(frozen=True)
class Leg:
    key: str
    series: str
    ticker: str
    title: str  # plain-language market title shown on the hedge card
    pays_no: str  # plain-language state in which the NO pays
    label: str  # Hedge.leg_label
    payoff: Callable[[pm.Path], float]


LEGS: tuple[Leg, ...] = (
    Leg("playoffs", "KXNBAPLAYOFF", "KXNBAPLAYOFF-27-NYK", "Knicks make the 2027 NBA playoffs",
        "the Knicks miss the playoffs", "Knicks miss the playoffs", pm.made_playoffs),
    Leg("east", "KXNBAEAST", "KXNBAEAST-27-NYK", "Knicks win the 2027 Eastern Conference",
        "the Knicks don't win the East", "Knicks don't win the East", pm.advance(2)),
    Leg("title", "KXNBA", "KXNBA-27-NYK", "Knicks win the 2027 NBA title",
        "the Knicks don't win the title", "Knicks don't win the title", pm.advance(3)),
)


@dataclass
class Quote:
    leg: Leg
    market: dict
    series: dict
    book: Orderbook

    @property
    def yes_bid(self) -> Decimal | None:
        return best_bid(self.book, "yes")

    @property
    def yes_ask(self) -> Decimal | None:
        return best_ask(self.book, "yes")

    @property
    def mid(self) -> Decimal | None:
        if self.yes_bid is None or self.yes_ask is None:
            return None
        return (self.yes_bid + self.yes_ask) / 2


# ---------------------------------------------------------------- quotes


async def fetch_quotes(client: KalshiClient) -> list[Quote]:
    """Series, market and book for every leg. Offline, a missing file raises CacheMiss."""
    out = []
    for leg in LEGS:
        series = await client.get_series(leg.series)
        market = await client.get_market(leg.ticker)
        book = await client.get_orderbook(leg.ticker)
        out.append(Quote(leg, market, series, book))
    return out


def _cached(cache_dir: Path, path: str) -> tuple[dict, datetime] | None:
    f = Path(cache_dir) / f"{_cache_key(path, {})}.json"
    if not f.exists():
        return None
    entry = json.loads(f.read_text(), parse_float=Decimal)
    return entry["response"], datetime.fromisoformat(entry["fetched_at"])


def cached_quotes(cache_dir: Path = DEFAULT_CACHE_DIR) -> list[Quote] | None:
    """The same quotes read synchronously from the offline cache (for /analyze); None on any miss."""
    out = []
    for leg in LEGS:
        s, m, b = (_cached(cache_dir, p) for p in (
            f"/series/{leg.series}", f"/markets/{leg.ticker}", f"/markets/{leg.ticker}/orderbook"))
        if s is None or m is None or b is None:
            return None
        out.append(Quote(leg, m[0]["market"], s[0]["series"], parse_orderbook(leg.ticker, b[0], b[1])))
    return out


# ---------------------------------------------------------------- model


def _f(x: Decimal) -> float:
    return float(x)


def season_model(quotes: list[Quote]) -> tuple[list[pm.Path], list[pm.Contract]]:
    """Every playoff path priced from the futures mids, and the three contracts (YES ask/bid)."""
    mids = [q.mid for q in quotes]
    if any(m is None for m in mids):
        raise ValueError("a season future has no two-sided quote")
    p_make, p_conf, p_title = (_f(m) for m in mids)
    rounds = pm.preseason_rounds(p_make, p_conf, p_title, FMT, edge=pm.HOME_EDGE[LEAGUE], p_home=P_HOME)
    paths = pm.season_paths_with_qualifier(p_make, rounds)
    contracts = [pm.Contract(q.leg.ticker, q.leg.payoff, _f(q.yes_ask), _f(q.yes_bid)) for q in quotes]
    return paths, contracts


def expected_home_games(quotes: list[Quote]) -> float:
    paths, _ = season_model(quotes)
    return pm.expected(paths, lambda p: p.home_games)


@dataclass
class LegPlan:
    quote: Quote
    n_target: int  # NO contracts
    swing: Decimal  # $ the bar has riding on this stage
    fair: Decimal  # fair NO price = 1 - YES mid
    n_model: float  # unrounded min-variance size (NO contracts)


@dataclass
class SeasonPlan:
    legs: list[LegPlan]
    expected_home_games: float
    expected_uplift: Decimal  # effect_usd x E[home games]
    sd_before: Decimal
    sd_after: Decimal
    variance_removed: float


def plan(exposure: Exposure, quotes: list[Quote]) -> SeasonPlan:
    """Minimum-variance NO sizes over the season futures; legs that would buy YES are dropped."""
    u = _f(exposure.effect_usd)
    paths, contracts = season_model(quotes)
    keep = list(range(len(quotes)))
    while True:
        res = pm.min_variance_hedge(paths, [contracts[i] for i in keep], uplift=u)
        bad = [i for i, n in zip(keep, res.n) if n >= 0]
        if not bad or len(keep) == 1:
            break
        keep = [i for i in keep if i not in bad]
    legs = []
    for i, n in zip(keep, res.n):
        swing = Decimal(repr(u * pm.swing(paths, quotes[i].leg.payoff))).quantize(Decimal("0.01"), ROUND_HALF_UP)
        n_no = max(0.0, -float(n))
        cap = int(swing.to_integral_value(rounding=ROUND_FLOOR))
        legs.append(LegPlan(quote=quotes[i], n_target=min(int(round(n_no)), cap), swing=swing,
                            fair=ONE - quotes[i].mid, n_model=n_no))
    e_h = pm.expected(paths, lambda p: p.home_games)
    return SeasonPlan(
        legs=[lp for lp in legs if lp.n_target > 0], expected_home_games=e_h,
        expected_uplift=money(Decimal(repr(u * e_h))), sd_before=money(Decimal(repr(res.sd_before))),
        sd_after=money(Decimal(repr(res.sd_after))), variance_removed=res.variance_removed,
    )


# ---------------------------------------------------------------- one leg -> Hedge


def leg_exposure(exposure: Exposure, lp: LegPlan) -> dict[str, Any]:
    """What the rules and sizing see for one leg: the exposure with the leg's swing as its size."""
    return {"id": exposure.id, "business_id": exposure.business_id, "settlement_var": exposure.settlement_var,
            "effect_usd": lp.swing, "hedge_side": "no", "hedgeable": exposure.hedgeable, "reasons": []}


def candidate(q: Quote) -> Candidate:
    m = q.market
    return Candidate(
        ticker=q.leg.ticker, series_ticker=q.series.get("ticker", q.leg.series), title=q.leg.title,
        close_time=datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")), status=m.get("status", ""),
        rules_primary=m.get("rules_primary") or "", floor_strike=None, settlement_var="playoff_home",
        fee_type=q.series.get("fee_type") or "", fee_multiplier=Decimal(str(q.series.get("fee_multiplier", 1))),
        yes_ask=q.yes_ask, no_ask=best_ask(q.book, "no"), yes_bid=q.yes_bid, no_bid=best_bid(q.book, "no"),
        depth_within_5c=Depth(yes=depth_within(q.book, "yes"), no=depth_within(q.book, "no")),
        fetched_at=q.book.fetched_at,
    )


def size_leg(exposure: Exposure, lp: LegPlan, th: Thresholds) -> tuple[Candidate, Sizing]:
    q, cand = lp.quote, candidate(lp.quote)
    fill = walk_book(ask_levels(q.book, "no"), lp.n_target, th.max_slip)
    multiplier = cand.fee_multiplier
    fee = order_fee(fill.fills, multiplier)
    cost = money(fill.cost)
    premium = cost + fee
    expected_cost = money(fee + max(ZERO, fill.cost - lp.fair * fill.n_filled))
    lex = leg_exposure(exposure, lp)
    payoff = payoff_table(lex, "no", fill.n_filled, premium)
    return cand, Sizing(
        ticker=cand.ticker, series_ticker=cand.series_ticker, market_title=cand.title, close_time=cand.close_time,
        side="no", h=ONE, resized=False, n_target=lp.n_target, n_filled=fill.n_filled, n_unfilled=fill.n_unfilled,
        partial=0 < fill.n_filled < lp.n_target, fills=fill.fills, avg_price=fill.avg_price, cost=cost, fee=fee,
        premium=premium, p_hat=ONE - lp.fair, fair=places4(lp.fair), expected_cost=expected_cost,
        fee_unverified=cand.fee_type not in ("quadratic", "quadratic_with_maker_fees") or multiplier != ONE,
        payoff=payoff,
        headline=Headline(unhedged_swing=money(lp.swing),
                          hedged_swing=abs(payoff[0].net_vs_base - payoff[1].net_vs_base), cost=premium),
    )


def basis(sp: SeasonPlan, lp: LegPlan) -> BasisStat:
    # Settlement is deterministic in the playoff outcome; r2 is the model variance the season hedge removes.
    r2 = Decimal(repr(max(0.0, sp.variance_removed))).quantize(Decimal("0.0001"), ROUND_HALF_UP)
    return BasisStat(r2=r2, beta_s=money(lp.swing), se=Decimal("0.00"))


def leg_hedge(
    exposure: Exposure, sp: SeasonPlan, lp: LegPlan, *, hedge_id: str, week_of: date, now: datetime,
    agent: Agent, remaining: Decimal, thresholds: Thresholds,
) -> Hedge:
    """Sized, evaluated Hedge for one leg (all six checks, existing rules)."""
    cand, sizing = size_leg(exposure, lp, thresholds)
    lex = leg_exposure(exposure, lp)
    decision = evaluate(lex, [cand], sizing, basis(sp, lp), remaining, thresholds, decision_id=f"dec_{hedge_id}")
    reason = (f"NO pays when {lp.quote.leg.pays_no}, the state in which the bar loses its playoff home nights; "
              "sized with the other season legs to minimise the swing in playoff revenue.")
    hedge = to_hedge(lex, sizing, decision, hedge_id=hedge_id, week_of=week_of, created_at=now, agent=agent,
                     match_reason=reason)
    return hedge.model_copy(update={"leg_label": lp.quote.leg.label})


def with_group_total(hedges: list[Hedge]) -> list[Hedge]:
    """Stamp the legs' summed premium on every leg (`group_total_premium`)."""
    total = sum((h.premium or ZERO for h in hedges), ZERO)
    return [Hedge.model_validate({**h.model_dump(), "group_total_premium": total}) for h in hedges]


def status_sentence(hedge: Hedge) -> str:
    """The decision in one sentence, from the hedge's own checks (summary.py wording)."""
    d = hedge.decision
    if d.status == "proposed":
        return "Proposed: it fits this week's budget, and it waits for your approval."
    ob = next(c.metric for c in d.checks if c.code == "over_budget")
    if d.status == "pending_approval" and Decimal(str(ob["remaining"])) <= 0:
        return (f"Waiting for your approval: the ${Decimal(str(ob['premium'])):,.2f} premium doesn't fit, because "
                "the other season legs already use this week's budget.")
    return fallback_summary(hedge) or d.status


def leg_summary(hedge: Hedge, lp: LegPlan) -> str:
    """Plain-language summary for one leg. Every figure is a field of this hedge or its checks (I2)."""
    status = status_sentence(hedge)
    if hedge.n_filled == 0 or hedge.avg_price is None or hedge.premium is None:
        return status
    leg = lp.quote.leg
    return (f"Season playoff hedge: {hedge.n_filled:,} NO "
            f"contracts on {leg.ticker} at {(hedge.avg_price * 100).normalize():f}¢ for ${hedge.premium:,.2f}. "
            f"They pay ${hedge.n_filled:,} if {leg.pays_no}, a stage worth ${lp.swing:,.2f} of playoff nights "
            f"to the bar. {status}")


__all__ = ["LEGS", "LegPlan", "Quote", "SeasonPlan", "cached_quotes", "expected_home_games", "fetch_quotes",
           "leg_hedge", "leg_summary", "plan", "status_sentence", "with_group_total"]
