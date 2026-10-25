"""Shared contract models (spec §5, §7–§11; docs/CONTRACTS.md wins over chunk docs).

Money, price and probability fields are `Decimal` in Python and strings in JSON
(money always 2 dp, prices/probabilities/ratios up to 4 dp). They never accept a
float. Statistics (`p_value`, `r2_*`, `coverage`, `reduction_pct`,
`priced_real_pct`) stay plain numbers (CONTRACTS R1).

Every model in `CONTRACT_MODELS` has an example in `backend/fixtures/examples/`.
Changing a field here means updating that example and its test in the same PR.
"""

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StrictBool,
    StrictInt,
    model_validator,
)

# --- Decimal field types -----------------------------------------------------

CENT = Decimal("0.01")
DECIMAL_STR = r"^-?\d+(\.\d+)?$"


def _reject_float(v: Any) -> Any:
    if isinstance(v, float):
        raise ValueError("money/price/probability must be a str or Decimal, never a float")
    return v


def _max_places(places: int):
    def check(v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("must be finite")
        if v.as_tuple().exponent < -places:
            raise ValueError(f"at most {places} decimal places; quantize before building the model")
        return v

    return check


# Money: always serialized with exactly 2 dp ("250.00").
Money = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    AfterValidator(_max_places(2)),
    PlainSerializer(lambda v: str(v.quantize(CENT)), return_type=str, when_used="json"),
]

# Price, probability or ratio: up to 4 dp, serialized as given ("0.62", "0.4260").
Price = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    AfterValidator(_max_places(4)),
    PlainSerializer(lambda v: format(v, "f"), return_type=str, when_used="json"),
]


def _metric_values(v: Any) -> Any:
    """Check metrics are mixed (`n_filled: 150`, `avg_price: "0.62"`, `partial: true`).

    Numeric strings become Decimal so callers compare numbers, not text; floats are refused.
    """
    if not isinstance(v, dict):
        return v
    out = {}
    for key, val in v.items():
        if isinstance(val, float):
            raise ValueError(f"metric {key!r} is a float; use a Decimal string")
        if isinstance(val, str) and re.fullmatch(DECIMAL_STR, val):
            val = Decimal(val)
        out[key] = val
    return out


MetricValue = StrictBool | StrictInt | Decimal | str | None
Metrics = Annotated[dict[str, MetricValue], BeforeValidator(_metric_values)]


def _monday(d: date) -> date:
    if d.weekday() != 0:
        raise ValueError("week dates are Monday-start")
    return d


Monday = Annotated[date, AfterValidator(_monday)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Enums -------------------------------------------------------------------

Event = Literal["rain", "hot", "home_win", "playoff_home"]
Side = Literal["yes", "no"]
Agent = Literal["claude", "fallback"]
Actor = Literal["desk", "owner", "system"]
CheckCode = Literal["no_market", "illiquid", "overpriced", "basis_too_loose", "too_expensive", "over_budget"]
CHECK_ORDER: tuple[str, ...] = CheckCode.__args__
DecisionStatus = Literal["proposed", "declined", "pending_approval"]  # R4
HedgeStatus = Literal[  # R5
    "proposed", "pending_approval", "approved", "rejected", "declined", "expired_unapproved", "settled"
]
LogKind = Literal[
    "proposal", "decline", "approval", "rejection", "booking", "settlement", "expired",
    "reconciliation", "expired_unapproved", "nudge", "threshold_changed", "chat", "run_failed", "refusal",
]


# --- Exposures and model check (C2) ------------------------------------------


class Exposure(Contract):
    """Spec §5. Dropped exposures are the same object with `hedgeable: false` and reasons."""

    id: str
    business_id: str
    event: Event
    effect_usd: Money
    ci90: tuple[Money, Money]
    se: Money
    p_value: float
    n_events_train: int
    direction: Literal["positive", "negative"]
    hedge_side: Side
    settlement_var: Event
    hedgeable: bool
    reasons: list[Literal["below_size", "not_significant", "thin_support"]]
    strike: float | None  # temperature strike in °F, `hot` only
    beta_settlement: Money | None
    # `playoff_home` (and any class-rated exposure): `effect_usd` is $ per event, not per day.
    # `expected_count` is the market-implied expected count this season (e.g. playoff home
    # games); `estimated` marks a pooled estimate applied to this business (I6), and
    # `basis_note` says where the number comes from. Defaults keep older payloads valid.
    expected_count: float | None = None
    estimated: bool = False
    basis_note: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "Exposure":
        if self.hedgeable == bool(self.reasons):
            raise ValueError("hedgeable exposures have no reasons; dropped ones need at least one")
        positive = self.effect_usd > 0
        if self.direction != ("positive" if positive else "negative"):
            raise ValueError("direction must follow the sign of effect_usd")
        if self.hedge_side != ("no" if positive else "yes"):
            raise ValueError("hedge_side is 'no' for a positive effect, 'yes' for a negative one")
        if self.ci90[0] > self.ci90[1]:
            raise ValueError("ci90 must be [low, high]")
        return self


class BasisStat(Contract):
    """Rule 4 input from C2 (R2)."""

    r2: Price
    beta_s: Money
    se: Money


class ModelCheckExample(Contract):
    seed: int
    recovered: Money
    ci90: tuple[Money, Money]
    contains_truth: bool


class ModelCheck(Contract):
    """Planted-effect check, spec §5.1 (R6 shape)."""

    planted_usd: Money
    frac: float
    n_seeds: int
    example: ModelCheckExample
    coverage: float
    mean_recovered: Money
    target: float


# --- Budget and business ------------------------------------------------------


class Budget(Contract):
    """R7. `remaining = budget − spent − pending` (D4); negative when over-committed."""

    budget: Money
    spent: Money
    remaining: Money
    pending: Money
    week_start: Monday

    @model_validator(mode="after")
    def _remaining(self) -> "Budget":
        if self.remaining != self.budget - self.spent - self.pending:
            raise ValueError("remaining must equal budget - spent - pending")
        return self


class Business(Contract):
    id: str
    name: str
    kind: Literal["taxi", "restaurant"]
    data_label: Literal["real", "estimated"]
    estimated: bool
    revenue_source: str
    zone_id: int | None  # TLC taxi zone (taxi only)
    avg_check_usd: Money | None  # restaurant only
    avg_check_label: Literal["assumed", "menu"] | None
    budget: Budget

    @model_validator(mode="after")
    def _labels(self) -> "Business":
        if self.estimated != (self.data_label == "estimated"):
            raise ValueError("estimated must match data_label")
        if (self.avg_check_usd is None) != (self.avg_check_label is None):
            raise ValueError("avg_check_usd and avg_check_label go together")
        return self


# --- Decisions and hedges (C3) ------------------------------------------------


class Check(Contract):
    """One decline rule. `passed` is null when skipped (e.g. no market to evaluate)."""

    code: CheckCode
    passed: bool | None
    metric: Metrics


class Decision(Contract):
    """Spec §8. Only `summary` is written by Claude.

    `reasons` lists the failed decline checks (1–5) in table order; if none failed it is
    `["over_budget"]` when the budget check failed (that pauses, it doesn't decline).
    """

    id: str
    status: DecisionStatus
    checks: list[Check]
    reasons: list[CheckCode]
    summary: str | None

    @model_validator(mode="after")
    def _consistent(self) -> "Decision":
        codes = [c.code for c in self.checks]
        if codes != sorted(set(codes), key=CHECK_ORDER.index):
            raise ValueError("checks must be unique and in table order")
        failed = [c.code for c in self.checks if c.passed is False]
        declines = [c for c in failed if c != "over_budget"]
        expected = declines or failed
        if self.reasons != expected:
            raise ValueError(f"reasons must be {expected}")
        status = "declined" if declines else "pending_approval" if failed else "proposed"
        if self.status != status:
            raise ValueError(f"status must be {status!r} for these checks")
        return self


class Level(Contract):
    price: Price
    count: int


class PayoffRow(Contract):
    outcome: Literal["event", "no_event"]
    revenue_vs_base: Money
    contract_payout: Money
    premium: Money  # negative: always a cost
    net_vs_base: Money

    @model_validator(mode="after")
    def _net(self) -> "PayoffRow":
        if self.net_vs_base != self.revenue_vs_base + self.contract_payout + self.premium:
            raise ValueError("net_vs_base must equal revenue_vs_base + contract_payout + premium")
        return self


class Headline(Contract):
    """'Unhedged swing $X · hedged swing $Y · cost $Z'. Cost is the premium (R16)."""

    unhedged_swing: Money
    hedged_swing: Money
    cost: Money


def _check_sizing(h: "HedgeLite | Hedge") -> None:
    if h.n_filled > h.n_target:
        raise ValueError("n_filled cannot exceed n_target")
    if None not in (h.cost, h.fee, h.premium) and h.premium != h.cost + h.fee:
        raise ValueError("premium must equal cost + fee")
    if h.headline and h.premium is not None and h.headline.cost != h.premium:
        raise ValueError("headline.cost is the premium")
    if h.payoff is not None:
        if [r.outcome for r in h.payoff] != ["event", "no_event"]:
            raise ValueError("payoff has exactly two rows: event, no_event")
        if h.premium is not None and any(r.premium != -h.premium for r in h.payoff):
            raise ValueError("every payoff row carries -premium")


class HedgeLite(Contract):
    """Within-budget alternative for an over-budget hedge (G8)."""

    h: Price
    n_target: int
    n_filled: int
    avg_price: Price
    cost: Money
    fee: Money
    premium: Money
    payoff: list[PayoffRow]
    headline: Headline

    @model_validator(mode="after")
    def _sizing(self) -> "HedgeLite":
        _check_sizing(self)
        return self


class Hedge(Contract):
    """A sized hedge with its embedded decision. Declined hedges keep the attempted sizing;
    with no market, the market and sizing fields are null and only `decision` matters."""

    id: str
    business_id: str
    exposure_id: str
    week_of: Monday
    status: HedgeStatus
    ticker: str | None
    market_title: str | None
    market_url: str | None
    close_time: AwareDatetime | None
    side: Side
    match_reason: str | None
    h: Price | None
    n_target: int
    n_filled: int
    n_unfilled: int
    partial: bool  # illiquid check filled between 50% and 100% (R4)
    resized: bool  # rule 4 set h below 1
    fills: list[Level] | None
    avg_price: Price | None
    cost: Money | None
    fee: Money | None
    premium: Money | None
    fair: Price | None
    expected_cost: Money | None
    fee_unverified: bool
    payoff: list[PayoffRow] | None
    headline: Headline | None
    decision: Decision
    alternative: HedgeLite | None
    agent: Agent
    ledger_entry_ids: list[str]
    created_at: AwareDatetime
    decided_by: Literal["owner"] | None
    decided_at: AwareDatetime | None
    # Multi-leg exposures (the season playoff hedge): every leg is its own Hedge with the same
    # exposure_id. `leg_label` names the state the leg pays in ("Knicks miss the playoffs");
    # `group_total_premium` is the sum of the legs' premiums, identical on every leg. Both are
    # null on single-contract hedges.
    leg_label: str | None = None
    group_total_premium: Money | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "Hedge":
        _check_sizing(self)
        if self.n_filled + self.n_unfilled != self.n_target:
            raise ValueError("n_filled + n_unfilled must equal n_target")
        if self.fills is not None and sum(f.count for f in self.fills) != self.n_filled:
            raise ValueError("fills must add up to n_filled")
        if (self.status == "declined") != (self.decision.status == "declined"):
            raise ValueError("hedge is declined iff its decision is declined")
        if self.status in ("proposed", "pending_approval") and self.status != self.decision.status:
            raise ValueError("an undecided hedge carries its decision's status")
        if self.alternative is not None and self.decision.status != "pending_approval":
            raise ValueError("only over-budget hedges carry an alternative")
        booked = self.status in ("approved", "settled")
        if booked != bool(self.ledger_entry_ids):
            raise ValueError("approved/settled hedges have ledger entries; others have none")
        decided = self.status in ("approved", "rejected", "settled")
        if decided != (self.decided_by is not None) or decided != (self.decided_at is not None):
            raise ValueError("decided_by/decided_at are set iff the owner approved or rejected")
        return self


# --- Decision log (C4) --------------------------------------------------------


class LogEntry(Contract):
    """Append-only decision log row (R8, G4). `agent` is null for entries no model wrote
    (owner actions, system bookings). `numbers` is the I2 allowed-number set (R18)."""

    log_id: str
    business_id: str
    kind: LogKind
    created_at: AwareDatetime
    actor: Actor
    agent: Agent | None
    hedge_id: str | None
    decision_id: str | None
    run_id: str | None
    status: HedgeStatus | None
    checks: list[Check]
    reasons: list[CheckCode]
    numbers: Metrics
    summary: str


# --- Backtest (C2) ------------------------------------------------------------


class WeekIncome(Contract):
    week_start: Monday
    income: Money


class WeeklyRow(Contract):
    week_start: Monday
    unhedged: Money
    hedged: Money
    premium: Money


class PerExposure(Contract):
    reduction_pct: float
    total_premium: Money
    ineffective: bool  # under 10% reduction (spec §10)

    @model_validator(mode="after")
    def _ineffective(self) -> "PerExposure":
        if self.ineffective != (self.reduction_pct < 10):
            raise ValueError("ineffective iff reduction_pct < 10")
        return self


class BacktestResult(Contract):
    std_unhedged: Money
    std_hedged: Money
    reduction_pct: float
    worst_week_unhedged: WeekIncome
    worst_week_hedged: WeekIncome
    total_premium: Money
    n_hedges: int
    n_declined: int
    priced_real_pct: float
    per_exposure: dict[str, PerExposure]
    weekly: list[WeeklyRow]
    pricing_tier: Literal["real", "mixed", "frequency"]
    estimated: bool


# --- Books (C5) ---------------------------------------------------------------


class Posting(Contract):
    account: str  # Beancount account, e.g. "Expenses:Hedging:Premiums"
    amount: Money


class LedgerMeta(Contract):
    hedge_id: str
    ticker: str
    decision_id: str
    approved_by: Literal["owner"]


class LedgerEntry(Contract):
    id: str
    business_id: str
    date: date
    kind: Literal["premium", "payout", "withdrawal", "opening_deposit"]
    narration: str
    postings: list[Posting]
    meta: LedgerMeta | None  # required on hedge-related entries
    simulated: bool

    @model_validator(mode="after")
    def _balanced(self) -> "LedgerEntry":
        if sum(p.amount for p in self.postings) != 0:
            raise ValueError("postings must balance to zero")
        if self.kind in ("premium", "payout") and self.meta is None:
            raise ValueError("hedge-related entries carry hedge_id, ticker, decision_id, approved_by")
        return self


class ReconMatch(Contract):
    hedge_id: str
    ticker: str
    expected: Money
    kalshi_ledger: Money
    bank: Money


SourcePair = Literal["expected_vs_kalshi_ledger", "kalshi_ledger_vs_bank", "expected_vs_bank"]


class ReconMismatch(Contract):
    hedge_id: str
    ticker: str
    expected: Money
    kalshi_ledger: Money
    bank: Money
    difference: Money  # second source minus first, per source_pair
    source_pair: SourcePair
    explanation: str
    likely_cause: str
    action: Literal["ask_owner"]
    question: str

    @model_validator(mode="after")
    def _difference(self) -> "ReconMismatch":
        first, second = self.source_pair.split("_vs_")
        if self.difference != getattr(self, second) - getattr(self, first):
            raise ValueError("difference must be second source minus first")
        return self


class ReconSummary(Contract):
    n_matched: int
    n_mismatched: int
    total_difference: Money


class ReconResult(Contract):
    """C5 shape everywhere (R9); the `reconcile` tool returns it unchanged."""

    business_id: str
    as_of: date
    simulated: Literal[True]
    matches: list[ReconMatch]
    mismatches: list[ReconMismatch]
    summary: ReconSummary

    @model_validator(mode="after")
    def _summary(self) -> "ReconResult":
        s = self.summary
        if (s.n_matched, s.n_mismatched) != (len(self.matches), len(self.mismatches)):
            raise ValueError("summary counts must match the lists")
        if s.total_difference != sum((m.difference for m in self.mismatches), Decimal("0")):
            raise ValueError("total_difference must sum the mismatches")
        return self


class LedgerResponse(Contract):
    """GET /businesses/{id}/ledger (R10)."""

    entries: list[LedgerEntry]
    reconciliation: ReconResult | None
    simulated: Literal[True]


# --- API bodies (C6) ----------------------------------------------------------


class ThresholdSettings(Contract):
    """Mirrors `config.Thresholds` field for field."""

    min_size_usd: Money
    min_support: int
    overpay_max: Price
    cost_ratio_max: Price
    fill_decline: Price
    fill_full: Price
    max_slip: Price
    basis_r2_min: float
    max_tool_calls: int


class Settings(Contract):
    """GET/PUT /businesses/{id}/settings (R14)."""

    thresholds: ThresholdSettings
    weekly_budget: Money


class AnalyzeRequest(Contract):
    strike: float | None = None


class AnalyzeResponse(Contract):
    exposures: list[Exposure]
    dropped: list[Exposure]
    model_check: ModelCheck
    r2_holdout: float | None  # null when the feature table has no holdout rows

    @model_validator(mode="after")
    def _split(self) -> "AnalyzeResponse":
        if not all(e.hedgeable for e in self.exposures) or any(e.hedgeable for e in self.dropped):
            raise ValueError("exposures are hedgeable; dropped are not")
        return self


class DeskRunRequest(Contract):
    week_of: date | None = None  # snapped to its Monday by the route (G3)


class RunAccepted(Contract):
    """202 body of POST /businesses/{id}/desk/run."""

    run_id: str
    status: Literal["queued"]


class RunStatus(Contract):
    """GET /runs/{run_id} (R15)."""

    run_id: str
    business_id: str
    status: Literal["queued", "running", "done", "failed"]
    agent: Agent | None
    started_at: AwareDatetime | None
    finished_at: AwareDatetime | None
    error: str | None


# actor is a plain string so the route can answer 403 owner_only (not 422) for "desk" etc.
class ApproveRequest(Contract):
    actor: str | None = None
    note: str | None = None


class RejectRequest(Contract):
    actor: str | None = None
    reason: str | None = None


class ChatRequest(Contract):
    message: str = Field(min_length=1, max_length=2000)


class ToolCall(Contract):
    name: str
    input: dict[str, Any]
    output: Any


class ChatReply(Contract):
    reply: str
    tool_calls: list[ToolCall]


class Health(Contract):
    status: Literal["ok"]
    offline: bool
    anthropic: Literal["configured", "fallback"]
    # DEMO_SAMPLE_WEEK: true while example hedges from fixtures/examples/week_seed.json are still
    # stored (label them "sample week", I6). A desk run replaces a business's sample hedges, so
    # `sample_businesses` lists the businesses still showing sample data.
    sample_week: bool
    sample_businesses: list[str]


class ErrorDetail(Contract):
    code: str
    message: str
    detail: dict[str, Any] | None


class ErrorBody(Contract):
    """Body of every non-2xx response."""

    error: ErrorDetail


# Shared models that must each have an example in fixtures/examples/ (C6-A3).
CONTRACT_MODELS: dict[str, type[Contract]] = {
    m.__name__: m
    for m in (
        Exposure, BasisStat, ModelCheck, Budget, Business, Check, Decision, Hedge, HedgeLite,
        LogEntry, BacktestResult, LedgerEntry, ReconResult, LedgerResponse, Settings,
        AnalyzeRequest, AnalyzeResponse, DeskRunRequest, RunAccepted, RunStatus,
        ApproveRequest, RejectRequest, ChatRequest, ChatReply, Health, ErrorBody,
    )
}
