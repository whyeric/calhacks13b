"""Walk-forward backtest over the holdout, spec §10 / issue #10 (with #13's real-priced tier).

For each Monday-start holdout week (partial edge weeks dropped):

    unhedged = Σ revenue
    for each hedgeable exposure that has a contract, each day it could occur:
        q   = previous day's Kalshi candle for that day's contract   ("real", G4)
              else p̂_trailing(prior 365 days of the settlement flag) + FALLBACK_MARKUP ("frequency", G2)
        N   = min(ceil(h·|β|), floor(|β|)),  h = min(1, |β_S|/|β|) ≤ 1          (I1, markets/sizing)
        rules 3 (overpriced), 4 (basis), 5 (too expensive) from markets/rules  (R3, G12)
        rules 2 (liquidity) and 6 (budget) are skipped: no historical depth; budget is policy
        pnl += (N if the contract settled in our favour else 0) − premium,  premium = q·N + fee
    hedged = unhedged + pnl

Decisions:
- D5 (default used): exposures are re-estimated monthly on an expanding window that ends the
  day before each month starts; the first holdout month uses the `exposures` passed in (the train
  fit). An exposure the gates drop stays out until a later refit passes them again. β_S (rule 4)
  and `fair` (rule 3, p̂ of the settlement flag) are re-estimated on the same window.
- Cadence (G5): rain/hot contracts every day; home_win only on home-game days, and its p̂ is the
  home win rate over home-game days (settlement_rates.json).
- Real prices: the side we buy, at the close of the candle that ends at midnight New York time on
  the settlement day (i.e. the previous day's last quote): YES = yes_ask close, NO = 1 − yes_bid
  close. A missing candle, or a one-sided book (ask 1.00 / bid 0), falls back to the frequency
  price for that day only. `priced_real_pct` is the share of priced contract-days (hedged or
  declined) that used a real candle, in [0, 1].
- Errors: `fit_exposures` uses HC3 (not HAC); with fewer than `min_support` (10) event days the
  exposure fails `thin_support` before any SE matters.
- `reduction_pct = 100·(1 − std_hedged/std_unhedged)` over weekly totals (ddof=1), 1 dp. It is
  reported as found, including when it is negative (hedging made income less steady).

Money is Decimal end to end: candle prices are parsed from strings, revenue enters once through
`exposure.money`, and no float reaches a premium or payout. Pure: no network, no DB, no files.
The markets modules are imported lazily because `app.markets` pulls in the HTTP client at import
time; only their pure functions are called.
"""

from __future__ import annotations

import bisect
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from app.config import FALLBACK_MARKUP, Thresholds, get_thresholds
from app.models import (
    CENT,
    BacktestResult,
    BasisStat,
    Exposure,
    PerExposure,
    WeekIncome,
    WeeklyRow,
)
from app.stats.exposure import ExposureResult, beta_settlement, fit_exposures
from app.stats.exposure import money as to_money

Side = Literal["yes", "no"]
Tier = Literal["real", "mixed", "frequency"]

ZERO = Decimal("0")
ONE = Decimal("1")
P4 = Decimal("0.0001")
PCT = Decimal("0.1")
MIN_PRICE, MAX_PRICE = Decimal("0.01"), Decimal("0.99")
INEFFECTIVE_BELOW = 10.0
NY = ZoneInfo("America/New_York")
NO_BASIS_NEEDED = {"home_win"}  # mirrors markets/rules: the business flag is the settlement flag


# ------------------------------------------------------------------ inputs


@dataclass(frozen=True)
class Quote:
    """Price to buy each side of one day's contract (Decimal; None = no usable quote)."""

    yes: Decimal | None
    no: Decimal | None
    volume: Decimal | None = None

    def for_side(self, side: Side) -> Decimal | None:
        return self.yes if side == "yes" else self.no


@dataclass(frozen=True)
class BacktestContract:
    """The contract an exposure hedges with, as columns of the feature table.

    `settle_col`: bool column, YES iff true (settle_rain, settle_hot, home_win).
    `universe_col`: days the contract exists (home_game for home_win); None = every day.
    `quotes`: real prices keyed by settlement date (see `quote_from_candles`).
    """

    event: str
    settle_col: str
    universe_col: str | None = None
    quotes: Mapping[date, Quote] = field(default_factory=dict)


@dataclass(frozen=True)
class BacktestConfig:
    thresholds: Thresholds = field(default_factory=get_thresholds)
    markup: Decimal = FALLBACK_MARKUP  # frequency tier: price = p̂_trailing + markup (G2)
    strikes: Mapping[str, float] | None = None  # {"hot": °F} for refits
    refit: bool = True  # D5: monthly expanding-window refit; False = frozen from train
    fees: bool = True  # Kalshi taker fee (markets/sizing); False only for idealised tests
    trailing_days: int = 365
    budget: Decimal | None = None  # ignored on purpose: rule 6 is skipped in the backtest


# ------------------------------------------------------------------ outputs


@dataclass(frozen=True)
class HedgeDay:
    """One priced contract-day: hedged (`declined == ()`) or declined by rules 3–5."""

    date: date
    exposure_id: str
    event: str
    side: Side
    beta: Decimal
    h: Decimal
    n: int
    price: Decimal
    fair: Decimal
    p_hat_trailing: Decimal
    priced_real: bool
    fee: Decimal
    premium: Decimal
    payout: Decimal
    settled_yes: bool
    declined: tuple[str, ...]

    @property
    def hedged(self) -> bool:
        return not self.declined

    @property
    def pnl(self) -> Decimal:
        return self.payout - self.premium if self.hedged else ZERO


@dataclass(frozen=True)
class MonthFit:
    """What the desk knew at `start`: fitted on rows dated before it."""

    start: date
    exposures: tuple[Exposure, ...]  # hedgeable
    dropped: tuple[Exposure, ...]
    basis: Mapping[str, BasisStat]
    p_hat: Mapping[str, Decimal]  # settlement-flag frequency on the window (rule 3 `fair`)
    n_window: int


@dataclass
class BacktestRun:
    result: BacktestResult
    days: list[HedgeDay]
    fits: list[MonthFit]
    declined_by_reason: dict[str, int]
    skipped: dict[str, int]  # exposure-days not priced: "no_contract", "not_hedgeable"


# ------------------------------------------------------------------ real prices


def _dec_price(v: Any) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, (float, bool)):
        raise TypeError(f"candle prices must be strings or Decimal, never {type(v).__name__}: {v!r}")
    return Decimal(str(v))


def _ny_midnight_ts(d: date) -> int:
    return int(datetime.combine(d, time(0), NY).timestamp())


def _block(c: Mapping, name: str) -> Any:
    """Close of a candle's `name` block, either in compact form (`yes_ask_close`) or as Kalshi
    serves it (`{"yes_ask": {"close": ..}}` historical, `{"close_dollars": ..}` live)."""
    if f"{name}_close" in c:
        return c[f"{name}_close"]
    b = c.get(name) or {}
    return b.get("close", b.get("close_dollars"))


def quote_from_candles(candles: list[Mapping], settle_date: date) -> Quote | None:
    """G4: the candle that ends at midnight New York time on `settle_date` (the previous day's
    close), so nothing from the settlement day itself is used. None when there is no such candle."""
    end = _ny_midnight_ts(settle_date)
    match = [c for c in candles if int(c["end_period_ts"]) == end]
    if not match:
        return None
    c = match[-1]
    ask, bid = _dec_price(_block(c, "yes_ask")), _dec_price(_block(c, "yes_bid"))
    vol = c.get("volume", c.get("volume_fp"))
    yes = ask if ask is not None and ZERO < ask < ONE else None
    no = ONE - bid if bid is not None and ZERO < bid < ONE else None
    if yes is None and no is None:
        return None
    return Quote(yes=yes, no=no, volume=None if vol is None else _dec_price(vol))


def quotes_from_history(history: Mapping) -> tuple[dict[date, Quote], dict[date, bool]]:
    """Parse a `fixtures/kalshi_history/<var>.json` payload (already loaded by the caller) into
    quotes by settlement date and the official settled results (YES = True)."""
    quotes: dict[date, Quote] = {}
    results: dict[date, bool] = {}
    for d_str, m in history.get("markets", {}).items():
        d = date.fromisoformat(d_str)
        results[d] = m["result"] == "yes"
        q = quote_from_candles(m.get("candles") or [], d)
        if q is not None:
            quotes[d] = q
    return quotes, results


def default_contracts(quotes: Mapping[str, Mapping[date, Quote]] | None = None) -> dict[str, BacktestContract]:
    quotes = quotes or {}
    return {
        "rain": BacktestContract("rain", "settle_rain", None, quotes.get("rain", {})),
        "hot": BacktestContract("hot", "settle_hot", None, quotes.get("hot", {})),
        "home_win": BacktestContract("home_win", "home_win", "home_game", quotes.get("home_win", {})),
    }


# ------------------------------------------------------------------ helpers


def _markets():
    from app.markets import rules, sizing  # lazy: see module docstring

    return rules, sizing


def _p4(x: Decimal) -> Decimal:
    return x.quantize(P4, rounding=ROUND_HALF_UP)


def _freq(flag: pd.Series, universe: pd.Series) -> Decimal | None:
    n = int(universe.sum())
    return None if n == 0 else _p4(Decimal(int((flag & universe).sum())) / Decimal(n))


def _std(xs: list[Decimal]) -> Decimal:
    if len(xs) < 2:
        return ZERO
    mean = sum(xs, ZERO) / len(xs)
    var = sum(((x - mean) ** 2 for x in xs), ZERO) / (len(xs) - 1)
    return var.sqrt().quantize(CENT, rounding=ROUND_HALF_UP)


def reduction_pct(std_unhedged: Decimal, std_hedged: Decimal) -> float:
    """100·(1 − hedged/unhedged), 1 dp; 0.0 when there is no swing to reduce. May be negative."""
    if std_unhedged == 0:
        return 0.0
    return float((100 * (ONE - std_hedged / std_unhedged)).quantize(PCT, rounding=ROUND_HALF_UP))


def per_exposure_entry(red: float, premium: Decimal) -> PerExposure:
    return PerExposure(reduction_pct=red, total_premium=premium, ineffective=red < INEFFECTIVE_BELOW)


def full_weeks(days: list[date]) -> list[date]:
    """Monday starts of the weeks whose seven days are all in `days`."""
    have = set(days)
    mondays = sorted({d - timedelta(days=d.weekday()) for d in days})
    return [m for m in mondays if all(m + timedelta(days=i) in have for i in range(7))]


def _month_starts(first: date, last: date) -> list[date]:
    out, d = [first], date(first.year, first.month, 1)
    while True:
        d = date(d.year + d.month // 12, d.month % 12 + 1, 1)
        if d > last:
            return out
        out.append(d)


def _exposure_list(exposures: ExposureResult | list[Exposure] | Any) -> tuple[list[Exposure], list[Exposure]]:
    if isinstance(exposures, ExposureResult):
        return list(exposures.exposures), list(exposures.dropped)
    items = list(exposures)
    return [e for e in items if e.hedgeable], [e for e in items if not e.hedgeable]


def _tier(pct: float) -> Tier:
    return "real" if pct == 1.0 else "frequency" if pct == 0.0 else "mixed"


# ------------------------------------------------------------------ the backtest


def run_backtest(
    df: pd.DataFrame,
    contracts: Mapping[str, BacktestContract] | None,
    exposures: ExposureResult | list[Exposure],
    cfg: BacktestConfig | None = None,
) -> BacktestResult:
    return simulate(df, contracts, exposures, cfg).result


def simulate(
    df: pd.DataFrame,
    contracts: Mapping[str, BacktestContract] | None,
    exposures: ExposureResult | list[Exposure],
    cfg: BacktestConfig | None = None,
) -> BacktestRun:
    """`run_backtest` plus the per-day trace (prices, N, h, declines) and the monthly fits."""
    rules, sizing = _markets()
    cfg = cfg or BacktestConfig()
    th = cfg.thresholds
    contracts = default_contracts() if contracts is None else dict(contracts)

    df = df.sort_values("date").reset_index(drop=True)
    dates = pd.Series(pd.to_datetime(df["date"]).dt.date, index=df.index)
    hold = df["split"] == "holdout"
    if not hold.any():
        raise ValueError("backtest needs holdout rows")
    hold_days = list(dates[hold])
    weeks = full_weeks(hold_days)
    if not weeks:
        raise ValueError("no full Monday-start week in the holdout")
    business_id = df.attrs.get("business_id", "unknown")

    # Settlement flags, universes and trailing p̂ (prior `trailing_days`, today excluded).
    ts_index = pd.DatetimeIndex(pd.to_datetime(dates))
    flags: dict[str, pd.Series] = {}
    univ: dict[str, pd.Series] = {}
    trail: dict[str, tuple[pd.Series, pd.Series]] = {}
    for ev, c in contracts.items():
        if c.settle_col not in df.columns:
            continue
        s = df[c.settle_col].astype(bool)
        u = df[c.universe_col].astype(bool) if c.universe_col else pd.Series(True, index=df.index)
        flags[ev], univ[ev] = s, u
        win = f"{cfg.trailing_days}D"
        hits = pd.Series((s & u).astype(int).to_numpy(), index=ts_index).rolling(win, closed="left").sum()
        cnt = pd.Series(u.astype(int).to_numpy(), index=ts_index).rolling(win, closed="left").sum()
        trail[ev] = (hits.fillna(0).to_numpy(), cnt.fillna(0).to_numpy())

    # Monthly fits (D5). Month 0 = the train fit handed in.
    starts = _month_starts(hold_days[0], hold_days[-1])
    first_exps, first_dropped = _exposure_list(exposures)
    fits: list[MonthFit] = []
    for i, start in enumerate(starts):
        if fits and not cfg.refit:
            fits.append(replace(fits[0], start=start))
            continue
        window = df[dates < start].copy()
        if i == 0:
            exps, dropped = first_exps, first_dropped
        else:
            window["split"] = "train"
            window.attrs["business_id"] = business_id
            res = fit_exposures(window, dict(cfg.strikes or {}), business_id=business_id, thresholds=th)
            exps, dropped = list(res.exposures), list(res.dropped)
        basis, p_hat = {}, {}
        for ev in flags:
            w_idx = window.index
            p = _freq(flags[ev].loc[w_idx], univ[ev].loc[w_idx])
            if p is not None:
                p_hat[ev] = p
            if ev not in NO_BASIS_NEEDED and any(e.event == ev for e in exps):
                basis[ev] = beta_settlement(
                    window.assign(split="train"), flags[ev].loc[w_idx], event=ev, strikes=dict(cfg.strikes or {})
                )
        fits.append(MonthFit(start, tuple(exps), tuple(dropped), basis, p_hat, len(window)))

    # Walk the days of the full weeks.
    week_of = {m + timedelta(days=i): m for m in weeks for i in range(7)}
    pos = {d: i for i, d in enumerate(dates)}
    revenue = {d: to_money(r) for d, r in zip(dates, df["revenue"])}
    days: list[HedgeDay] = []
    skipped: Counter = Counter()
    for d in sorted(week_of):
        i = pos[d]
        fit = fits[bisect.bisect_right(starts, d) - 1]
        for e in fit.exposures:
            c = contracts.get(e.event)
            if c is None or e.event not in flags:
                skipped["no_contract"] += 1
                continue
            if not bool(univ[e.event].iloc[i]):
                continue
            if e.event not in fit.p_hat:
                skipped["no_contract"] += 1
                continue
            side: Side = e.hedge_side
            beta = Decimal(e.effect_usd)
            if e.event in NO_BASIS_NEEDED:
                h, basis_check = ONE, None
            else:
                b = fit.basis[e.event]
                h = rules.resolve_h(b, beta, th)
                basis_check = rules.check_basis(b, beta, th)
            h_size = ONE if h is None else h
            n = sizing.target_contracts(beta, h_size)
            if n <= 0:
                continue

            hits, cnt = trail[e.event]
            p_tr = _p4(Decimal(int(hits[i])) / Decimal(int(cnt[i]))) if cnt[i] > 0 else fit.p_hat[e.event]
            q = c.quotes.get(d)
            real = q.for_side(side) if q is not None else None
            if real is not None:
                price, priced_real = real, True
            else:
                base = p_tr if side == "yes" else ONE - p_tr
                price, priced_real = min(MAX_PRICE, max(MIN_PRICE, _p4(base + cfg.markup))), False
            fair = sizing.fair_for_side(fit.p_hat[e.event], side)
            fee = sizing.taker_fee(n, price) if cfg.fees else ZERO
            premium = sizing.money(price * n) + fee
            expected_cost = sizing.money(fee + max(ZERO, price * n - fair * n))
            checks = [
                rules.check_overpriced(price, fair, th, side=side),
                basis_check,
                rules.check_too_expensive(expected_cost, beta, th),
            ]
            declined = tuple(ch.code for ch in checks if ch is not None and ch.passed is False)
            settled_yes = bool(flags[e.event].iloc[i])
            pays = settled_yes if side == "yes" else not settled_yes
            days.append(HedgeDay(
                date=d, exposure_id=e.id, event=e.event, side=side, beta=beta, h=h_size, n=n,
                price=price, fair=fair, p_hat_trailing=p_tr, priced_real=priced_real, fee=fee,
                premium=premium, payout=Decimal(n) if pays else ZERO, settled_yes=settled_yes,
                declined=declined,
            ))
        for e in fit.dropped:
            if e.event in contracts:
                skipped["not_hedgeable"] += 1

    result = _summarize(df, dates, weeks, revenue, days)
    reasons = Counter(code for hd in days for code in hd.declined)
    return BacktestRun(result=result, days=days, fits=fits, declined_by_reason=dict(sorted(reasons.items())),
                       skipped=dict(skipped))


def _summarize(df, dates, weeks, revenue, days: list[HedgeDay]) -> BacktestResult:
    week_days = {m: [m + timedelta(days=i) for i in range(7)] for m in weeks}
    unhedged = {m: sum((revenue[d] for d in ds), ZERO) for m, ds in week_days.items()}

    def weekly_pnl(subset: list[HedgeDay]) -> tuple[dict[date, Decimal], dict[date, Decimal]]:
        pnl = {m: ZERO for m in weeks}
        prem = {m: ZERO for m in weeks}
        for hd in subset:
            if hd.hedged:
                m = hd.date - timedelta(days=hd.date.weekday())
                pnl[m] += hd.pnl
                prem[m] += hd.premium
        return pnl, prem

    pnl, prem = weekly_pnl(days)
    hedged = {m: unhedged[m] + pnl[m] for m in weeks}
    std_u = _std([unhedged[m] for m in weeks])
    std_h = _std([hedged[m] for m in weeks])

    per_exposure: dict[str, PerExposure] = {}
    for eid in sorted({hd.exposure_id for hd in days}):
        p_e, pr_e = weekly_pnl([hd for hd in days if hd.exposure_id == eid])
        red = reduction_pct(std_u, _std([unhedged[m] + p_e[m] for m in weeks]))
        per_exposure[eid] = per_exposure_entry(red, sum(pr_e.values(), ZERO))

    worst = min(weeks, key=lambda m: (unhedged[m], m))
    n_priced = len(days)
    real_pct = 0.0 if n_priced == 0 else float(_p4(Decimal(sum(hd.priced_real for hd in days)) / Decimal(n_priced)))
    return BacktestResult(
        std_unhedged=std_u,
        std_hedged=std_h,
        reduction_pct=reduction_pct(std_u, std_h),
        worst_week_unhedged=WeekIncome(week_start=worst, income=unhedged[worst]),
        worst_week_hedged=WeekIncome(week_start=worst, income=hedged[worst]),
        total_premium=sum(prem.values(), ZERO),
        n_hedges=sum(hd.hedged for hd in days),
        n_declined=sum(not hd.hedged for hd in days),
        priced_real_pct=real_pct,
        per_exposure=per_exposure,
        weekly=[WeeklyRow(week_start=m, unhedged=unhedged[m], hedged=hedged[m], premium=prem[m]) for m in weeks],
        pricing_tier=_tier(real_pct),
        estimated=bool(df["estimated"].any()) if "estimated" in df.columns else False,
    )
