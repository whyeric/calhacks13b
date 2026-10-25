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
Venue = Literal["kalshi", "polymarket"]
Agent = Literal["claude", "fallback"]
# "controller" co-signs hedges above materiality and closes the books (segregation of duties):
# the owner can't co-sign or close, the controller can't approve, and the desk can do none of it.
Actor = Literal["desk", "owner", "controller", "system"]
CheckCode = Literal[
    "no_market", "illiquid", "overpriced", "basis_too_loose", "too_expensive", "unstable", "over_budget"
]
CHECK_ORDER: tuple[str, ...] = CheckCode.__args__
DecisionStatus = Literal["proposed", "declined", "pending_approval"]  # R4
HedgeStatus = Literal[  # R5
    "proposed", "pending_approval", "approved", "rejected", "declined", "expired_unapproved", "settled"
]
LogKind = Literal[
    "proposal", "decline", "approval", "rejection", "booking", "settlement", "expired",
    "reconciliation", "expired_unapproved", "nudge", "threshold_changed", "chat", "run_failed", "refusal",
    "cosign", "cosign_refused", "period_close",
    # Kalshi demo orders placed on the owner's approval (markets/trading.py)
    "order_placed", "order_filled", "order_partial", "order_failed", "order_skipped",
    "qbo_posted", "qbo_post_failed",  # QuickBooks write-back (integrations/quickbooks_sync.py)
]


# --- Exposures and model check (C2) ------------------------------------------


class Stability(Contract):
    """The same §5 model refit on the most recent window only (the holdout split).

    `stable` = the recent effect has the train effect's sign AND its 90% CI excludes 0. The
    `unstable` decline rule reads it (research hedgesim: taxi rain +$2,212 on train was +$303,
    CI crossing 0, on the recent window, and hedging it made income less steady).
    """

    effect_usd: Money
    ci90: tuple[Money, Money]
    n_days: int
    n_events: int
    start: date
    end: date
    same_sign: bool
    stable: bool

    @model_validator(mode="after")
    def _consistent(self) -> "Stability":
        if self.ci90[0] > self.ci90[1]:
            raise ValueError("ci90 must be [low, high]")
        excludes_zero = self.ci90[0] > 0 or self.ci90[1] < 0
        if self.stable != (self.same_sign and excludes_zero):
            raise ValueError("stable must equal same_sign and a recent CI that excludes 0")
        return self


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
    stability: Stability | None = None  # recent-window refit; None when there is no holdout
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
    # I6: true when the business's dollars are estimated (the restaurant: visits x assumed check)
    # or the exposure is a pooled estimate. Defaults keep older payloads valid.
    estimated: bool = False
    # Where the contract trades (markets/polymarket.py is the second venue). `fee_rate` is the
    # venue's taker rate in fee = rate x C x P x (1 - P); null means Kalshi's 0.07.
    venue: Venue = "kalshi"
    fee_rate: Price | None = None
    # Segregation of duties: a premium above the business's materiality threshold needs the
    # controller's co-sign before the owner's approval counts (`POST /hedges/{id}/cosign`).
    needs_controller: bool = False
    controller: "ControllerSignoff | None" = None
    # The owner's note on approve or reason on reject, kept for the desk's memory.
    decision_note: str | None = None
    # What happened to this exposure's earlier hedges (the desk's memory across weeks).
    owner_history: "OwnerHistory | None" = None
    # The venue order placed on the owner's approval (Kalshi demo, markets/trading.py): what was
    # actually filled, next to the approved figures the ledger booked. Null when no order was sent.
    venue_order: "VenueOrder | None" = None

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


class ControllerSignoff(Contract):
    """The controller's co-sign (or refusal) on a hedge above materiality."""

    decision: Literal["signed", "refused"]
    at: AwareDatetime
    note: str | None


class HistoryOutcome(Contract):
    hedge_id: str
    week_of: Monday
    status: HedgeStatus
    premium: Money | None
    payout: Money | None  # settled hedges only; 0.00 when the contracts expired worthless
    note: str | None  # the owner's note or reason


class OwnerHistory(Contract):
    """The same exposure's earlier hedges for this business, newest first (at most 5 shown).

    `pattern` is set when the owner's recent decisions should change how the desk asks:
    "rejected_recently" when the last two decided hedges were both rejected."""

    n_earlier: int
    n_approved: int
    n_rejected: int
    n_expired_unapproved: int
    total_premium: Money  # approved/settled only
    total_payout: Money  # settled only
    recent: list[HistoryOutcome]
    pattern: Literal["rejected_recently"] | None


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
    # Three-way legs (additive; see "Three-way reconciliation" at the end of this module).
    venue: Money | None = None  # what the venue says it paid; null when no venue record was read
    venue_origin: "ReconVenueOrigin | None" = None
    bank_origin: "ReconBankOrigin | None" = None


SourcePair = Literal[
    "expected_vs_kalshi_ledger", "kalshi_ledger_vs_bank", "expected_vs_bank",
    # three-way pairs: the venue's own record against our books, and the venue's fee against ours
    "expected_vs_venue", "venue_vs_kalshi_ledger", "ledger_fee_vs_venue_fee",
]


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
    # Three-way legs and which source to trust for the disputed fact (additive).
    venue: Money | None = None
    venue_fee: Money | None = None  # fee the venue says it charged on this position
    ledger_fee: Money | None = None  # fee we booked (Expenses:Hedging:Fees on the premium entry)
    system_of_record: "ReconLeg | None" = None  # venue: what was paid; bank: cash received; ledger: what we booked
    record_reason: str | None = None  # why that source is trusted for this fact
    venue_origin: "ReconVenueOrigin | None" = None
    bank_origin: "ReconBankOrigin | None" = None

    @model_validator(mode="after")
    def _difference(self) -> "ReconMismatch":
        first, second = self.source_pair.split("_vs_")
        a, b = getattr(self, first), getattr(self, second)
        if a is None or b is None:
            raise ValueError(f"source_pair {self.source_pair} needs both {first} and {second}")
        if self.difference != b - a:
            raise ValueError("difference must be second source minus first")
        return self


class ReconSummary(Contract):
    n_matched: int
    n_mismatched: int
    total_difference: Money
    n_in_transit: int = 0  # deposits still inside the posting window: not errors


class ReconResult(Contract):
    """C5 shape everywhere (R9); the `reconcile` tool returns it unchanged."""

    business_id: str
    as_of: date
    simulated: bool  # true unless every leg (venue, ledger, bank) is a live system (I6)
    matches: list[ReconMatch]
    mismatches: list[ReconMismatch]
    summary: ReconSummary
    in_transit: list["ReconInTransit"] = []  # timing differences, reported but not errors
    sources: "ReconSources | None" = None  # where each leg was read from

    @model_validator(mode="after")
    def _summary(self) -> "ReconResult":
        s = self.summary
        if (s.n_matched, s.n_mismatched) != (len(self.matches), len(self.mismatches)):
            raise ValueError("summary counts must match the lists")
        if s.n_in_transit != len(self.in_transit):
            raise ValueError("n_in_transit must count in_transit")
        if s.total_difference != sum((m.difference for m in self.mismatches), Decimal("0")):
            raise ValueError("total_difference must sum the mismatches")
        if self.sources is not None and not self.simulated and not self.sources.live:
            raise ValueError("simulated must be true unless every leg is live")
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
    # Defaults keep older clients (that PUT only the fields above) valid.
    decline_unstable: bool = True
    rain_size_multiplier: float = Field(default=1.0, ge=1.0, le=1.4)
    # Premiums above this need the controller's co-sign; only the controller may change it.
    materiality_usd: Money = Decimal("200.00")


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
    estimated: bool = False  # I6: the business's dollars are estimated (Business.estimated)

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


class CosignRequest(Contract):
    """POST /hedges/{id}/cosign. `approve=false` refuses: the owner can then only reject."""

    actor: str | None = None
    approve: bool = True
    note: str | None = None


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


# --- Reconciliation benchmark --------------------------------------------------
# GET /benchmarks/reconciliation: the real reconciler run on a SIMULATED world with planted
# errors and an answer key (app/books/benchmark.py). Scores are stats, so plain numbers.


class ReconBenchmarkCase(Contract):
    """One answer-key row. `planted` rows must be flagged with `expected_cause`; `trap` rows
    look odd but are correct, and must not be flagged (`expected_cause` is null)."""

    subject: str  # hedge id, or the bank row's reference for an unexplained row
    kind: Literal["planted", "trap"]
    description: str
    expected_cause: str | None
    found_cause: str | None  # the reconciler's likely_cause; null when not flagged
    flagged: bool
    correct: bool
    # Three-way additions: a trap may also require where the hedge lands (a deposit in transit
    # must be reported `in_transit`, not just left unflagged). `found_status` is where it landed.
    expected_status: Literal["matched", "in_transit"] | None = None
    found_status: Literal["matched", "in_transit", "mismatched", "absent"] | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "ReconBenchmarkCase":
        if (self.kind == "trap") != (self.expected_cause is None):
            raise ValueError("traps have no expected_cause; planted rows need one")
        if self.flagged != (self.found_cause is not None):
            raise ValueError("found_cause is set iff the row was flagged")
        if self.kind == "planted" and self.expected_status is not None:
            raise ValueError("expected_status is for traps only")
        want = (self.found_cause == self.expected_cause if self.kind == "planted"
                else not self.flagged and self.expected_status in (None, self.found_status))
        if self.correct != want:
            raise ValueError("correct must reflect the expected outcome")
        return self


class ReconBenchmark(Contract):
    seed: int
    simulated: Literal[True]
    n_hedges: int
    n_bank_rows: int
    n_planted: int
    n_caught: int  # planted rows flagged (any cause)
    n_cause_correct: int  # planted rows flagged with the expected cause
    n_traps: int
    n_false_flags: int  # flags on traps or on rows outside the answer key
    precision: float
    recall: float
    cause_accuracy: float
    cases: list[ReconBenchmarkCase]
    false_flags: list[str]  # subjects flagged that the answer key says are fine

    @model_validator(mode="after")
    def _counts(self) -> "ReconBenchmark":
        planted = [c for c in self.cases if c.kind == "planted"]
        if self.n_planted != len(planted) or self.n_traps != len(self.cases) - len(planted):
            raise ValueError("n_planted / n_traps must count the cases")
        if self.n_caught != sum(c.flagged for c in planted):
            raise ValueError("n_caught must count flagged planted cases")
        if self.n_cause_correct != sum(c.correct for c in planted):
            raise ValueError("n_cause_correct must count correct planted cases")
        if self.n_false_flags != len(self.false_flags):
            raise ValueError("n_false_flags must count false_flags")
        return self


# --- Controls: receipts and period close ---------------------------------------
# GET /hedges/{id}/receipt answers "why?" with the record, not with prose: the hedge and its
# checks, the exposure it came from, the thresholds in force now, and every log entry about it.
# POST /businesses/{id}/close locks the books through a date (controller only).


class DecisionReceipt(Contract):
    hedge: Hedge
    exposure: Exposure | None  # null when the analysis is no longer cached for the business
    thresholds: ThresholdSettings
    trail: list[LogEntry]  # oldest first
    approvals_required: list[Literal["owner", "controller"]]
    sources: list[str]  # where each input came from, in plain words


class TrialBalanceRow(Contract):
    account: str
    balance: Money


class PeriodCloseRequest(Contract):
    actor: str | None = None
    through: date
    # Close despite open reconciliation mismatches; they are carried as exceptions.
    acknowledge_exceptions: bool = False
    note: str | None = None


class PeriodClose(Contract):
    """The books are locked through `through`: later bookings dated on or before it are
    moved to the next open day and say which closed period they belong to."""

    business_id: str
    through: date
    previous_through: date | None
    closed_at: AwareDatetime
    closed_by: Literal["controller"]
    n_entries: int  # ledger entries in (previous_through, through]
    trial_balance: list[TrialBalanceRow]  # balances as of `through`
    exceptions: list[str]  # reconciliation mismatches carried into the close
    open_hedges: int  # proposed/pending hedges at close (they have no ledger entries yet)
    simulated: bool  # any entry in the period is simulated (I6)
    note: str | None

    @model_validator(mode="after")
    def _balanced(self) -> "PeriodClose":
        if sum((r.balance for r in self.trial_balance), Decimal("0")) != 0:
            raise ValueError("a trial balance sums to zero")
        if self.previous_through is not None and self.previous_through >= self.through:
            raise ValueError("a close moves the lock date forward")
        return self


class PeriodCloses(Contract):
    """GET /businesses/{id}/closes: newest first, and the date the books are locked through."""

    locked_through: date | None
    closes: list[PeriodClose]


# --- Research (live upload) ---------------------------------------------------
# POST /research (stats/research.py): the protocol run live on an uploaded CSV. Stateless.

ResearchReason = Literal[
    "thin_support", "not_significant", "failed_bh", "placebo_fired", "did_not_replicate", "sign_flipped"
]


class ResearchEstimate(Contract):
    """One fit of one flag on one period. `pct` is exp(b) − 1 in percent (a stat); the dollars
    are that share of the period's mean daily revenue (`mean_revenue`)."""

    pct: float
    effect_usd: Money
    ci90: tuple[Money, Money]
    ci_excludes_zero: bool
    p_value: float
    n_event_days: int
    n_days: int
    start: date
    end: date
    mean_revenue: Money

    @model_validator(mode="after")
    def _consistent(self) -> "ResearchEstimate":
        if self.ci90[0] > self.ci90[1]:
            raise ValueError("ci90 must be [low, high]")
        return self


class ResearchHypothesis(Contract):
    id: str
    label: str
    rule: str
    mechanism: str  # pre-registered, written before the fit
    train: ResearchEstimate | None  # None when the flag can't be fitted (no event days)
    holdout: ResearchEstimate | None
    placebo_p: float | None
    bh_q: float
    verdict: Literal["FOUND", "NOT FOUND"]
    reasons: list[ResearchReason]
    direction: Literal["positive", "negative"] | None
    upside: bool  # FOUND and positive: no protection needed
    venue: str  # where (if anywhere) a contract settles on this event
    sendable: bool  # FOUND downside the desk can price

    @model_validator(mode="after")
    def _verdict(self) -> "ResearchHypothesis":
        if (self.verdict == "FOUND") == bool(self.reasons):
            raise ValueError("FOUND has no reasons; NOT FOUND has at least one")
        if self.sendable and (self.verdict != "FOUND" or self.direction != "negative"):
            raise ValueError("only a FOUND downside is sendable")
        return self


class ResearchPeriod(Contract):
    start: date
    end: date


class ResearchReport(Contract):
    """POST /research. Every figure comes from `stats.research.run`; `summary` is templated."""

    name: str | None
    n_rows: int
    n_days: int  # rows used: inside the weather record, revenue > 0
    n_closed_days: int  # zero-revenue days, left out
    n_outside_window: int
    first: date
    last: date
    train: ResearchPeriod
    holdout: ResearchPeriod
    station: str
    protocol: list[str]
    notes: list[str]  # the file's own `#` lines (e.g. "SYNTHETIC demo data"), shown verbatim (I6)
    hypotheses: list[ResearchHypothesis]
    summary: str
    plot_max_usd: Money  # largest |CI end| across rows: forest-plot geometry only


class ResearchQuote(Contract):
    """POST /research/quote: a FOUND downside priced live on Kalshi and Polymarket (markets/quote.py).
    A quote, not a proposal: nothing is stored, so there is nothing to approve or book."""

    hypothesis_id: str
    exposure: Exposure
    hedge: Hedge
    budget: Budget
    p_hat: Price  # the event's train-year frequency, rule 3's fair price
    window: ResearchPeriod  # days the quote looked for a market
    basis_note: str


# --- QuickBooks Online integration ---------------------------------------------
# /integrations/quickbooks/* (integrations/quickbooks.py): the books replace the CSV upload as the
# research input, and add forward-looking commitments. `synthetic` is true in demo mode (I6).

# A quantity (units on hand): up to 4 dp, serialized as given ("24", "12.5").
Quantity = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    AfterValidator(_max_places(4)),
    PlainSerializer(lambda v: format(v, "f"), return_type=str, when_used="json"),
]


class QuickBooksStatus(Contract):
    mode: Literal["demo", "live"]
    connected: bool
    company_name: str | None
    realm_id: str | None
    connected_at: AwareDatetime | None
    synthetic: bool  # demo mode: the SYNTHETIC Hudson Bike Co. company, not real books


class QuickBooksConnect(Contract):
    """POST /integrations/quickbooks/connect. Demo connects at once (`authorize_url` null); live
    returns Intuit's consent URL and stays unconnected until the callback."""

    status: QuickBooksStatus
    authorize_url: str | None


class CommitmentLine(Contract):
    id: str
    kind: Literal["purchase_order", "bill", "estimate"]
    counterparty: str
    description: str
    amount: Money  # PO total, bill's unpaid balance, or estimate total
    due_date: date | None
    status: str  # QBO's own status ("Open", "Pending", "Accepted"; bills "Unpaid"/"Partially paid")


class InventoryLine(Contract):
    id: str
    name: str
    sku: str | None
    qty_on_hand: Quantity
    unit_cost: Money
    value: Money  # qty_on_hand x unit_cost


class Commitments(Contract):
    """GET /integrations/quickbooks/commitments: what the business is committed to, not what it spent."""

    as_of: date
    synthetic: bool
    purchase_orders: list[CommitmentLine]
    bills: list[CommitmentLine]
    estimates: list[CommitmentLine]
    inventory: list[InventoryLine]
    committed_spend: Money  # open PO totals + unpaid bill balances
    expected_revenue: Money  # pending/accepted estimates
    inventory_value: Money

    @model_validator(mode="after")
    def _totals(self) -> "Commitments":
        if self.committed_spend != sum((x.amount for x in self.purchase_orders + self.bills), Decimal("0")):
            raise ValueError("committed_spend is the sum of open POs and unpaid bills")
        if self.expected_revenue != sum((x.amount for x in self.estimates), Decimal("0")):
            raise ValueError("expected_revenue is the sum of pending estimates")
        if self.inventory_value != sum((x.value for x in self.inventory), Decimal("0")):
            raise ValueError("inventory_value is the sum of inventory values")
        return self


class QuickBooksResearch(Contract):
    """POST /integrations/quickbooks/research: the research protocol on revenue pulled from the books."""

    report: ResearchReport
    revenue_source: str
    days: int  # days with revenue in the books
    first_day: date
    last_day: date
    commitments: Commitments
    synthetic: bool


# --- Three-way reconciliation (venue / ledger / bank) ------------------------------
# books/reconcile.py reads the venue (what the exchange paid) and the bank (what cash arrived)
# through books/sources.py; the ledger is our Beancount books. Each fact has one system of record:
# the venue for what was paid and the fee it charged, the bank for cash received, the ledger for
# what we booked. `origin` labels say which legs are live and which are simulated (I6).

ReconLeg = Literal["venue", "ledger", "bank"]
ReconVenueOrigin = Literal["simulated", "kalshi_demo", "kalshi_live"]
ReconBankOrigin = Literal["csv_simulated", "increase_sandbox", "increase_live"]


class ReconInTransit(Contract):
    """A payout the venue paid and we booked whose deposit hasn't posted yet, still inside the
    posting window (or pending at the bank). A timing difference, not an error."""

    hedge_id: str
    ticker: str
    expected: Money
    venue: Money | None
    kalshi_ledger: Money
    bank_pending: Money  # amount the bank shows as pending (0.00 when nothing is visible yet)
    settled_on: date
    days_outstanding: int
    window_days: int
    explanation: str
    venue_origin: ReconVenueOrigin | None = None
    bank_origin: ReconBankOrigin | None = None


class ReconSources(Contract):
    venue_origin: ReconVenueOrigin
    ledger_origin: Literal["beancount_simulated", "beancount"]  # simulated while settlements are
    bank_origin: ReconBankOrigin
    live: bool  # every leg is a live system (Kalshi live, real books, Increase production)
    notes: list[str] = []


class IncreaseStatus(Contract):
    """GET /integrations/increase/status (integrations/increase.py). Reads no network: `last_sync`
    is the last time reconciliation read the bank in this process."""

    mode: Literal["demo", "sandbox", "live"]  # demo = the simulated bank CSV
    environment: Literal["sandbox", "production"]
    accounts: dict[str, str]  # business id ("*" = every business) -> Increase account id
    bank_origin: ReconBankOrigin
    simulated: bool  # true unless mode is live (sandbox money is not real money, I6)
    last_sync: AwareDatetime | None
    last_rows: int | None
    last_error: str | None


# Shared models that must each have an example in fixtures/examples/ (C6-A3).
CONTRACT_MODELS: dict[str, type[Contract]] = {
    m.__name__: m
    for m in (
        Exposure, BasisStat, ModelCheck, Budget, Business, Check, Decision, Hedge, HedgeLite,
        LogEntry, BacktestResult, LedgerEntry, ReconResult, LedgerResponse, Settings,
        AnalyzeRequest, AnalyzeResponse, DeskRunRequest, RunAccepted, RunStatus,
        ApproveRequest, RejectRequest, ChatRequest, ChatReply, Health, ErrorBody,
        ReconBenchmark, CosignRequest, DecisionReceipt, PeriodCloseRequest, PeriodClose, PeriodCloses,
        ResearchReport, ResearchQuote,
        QuickBooksStatus, QuickBooksConnect, CommitmentLine, InventoryLine, Commitments, QuickBooksResearch,
    )
}
CONTRACT_MODELS["IncreaseStatus"] = IncreaseStatus  # Increase bank (three-way reconciliation block)


# --- Kalshi demo trading (markets/trading.py, docs/KALSHI_DEMO.md) -------------------------

OrderOutcome = Literal["filled", "partial", "failed", "skipped"]


class VenueOrder(Contract):
    """The order placed on the venue when the owner approved a hedge (`Hedge.venue_order`).

    Booking stays at the approved figures; this records what the venue actually did, so
    reconciliation can flag a fill that differs from what was booked. Prices are in the hedge's
    own side (a NO hedge's `avg_price` is the NO price), whatever book side carried the order.
    `mode` "kalshi_demo" is Kalshi's demo exchange: fake money, labeled as such (I6)."""

    mode: Literal["kalshi_demo"]
    status: OrderOutcome
    client_order_id: str  # uuid5 of the hedge id (trading.client_order_id): retries are idempotent
    order_id: str | None  # the venue's id; null when nothing was accepted
    ticker: str | None  # the market the order was sent to (a demo stand-in when `stand_in`)
    production_ticker: str | None  # the hedge's own market
    stand_in: bool  # true: a configured demo stand-in, not the production contract
    side: Side
    book_side: Literal["bid", "ask"] | None  # Kalshi V2 quotes YES: bid = buy YES, ask = buy NO
    time_in_force: Literal["immediate_or_cancel", "fill_or_kill"]
    requested: int  # <= the hedge's filled contracts (I1)
    limit_price: Price | None  # <= the hedge's worst quoted level
    filled: int
    avg_price: Price | None
    cost: Money | None  # filled x avg_price
    fee: Money | None
    differs_from_booked: bool  # filled count or average price differs from the approved hedge
    reason: str | None
    at: AwareDatetime

    @model_validator(mode="after")
    def _consistent(self) -> "VenueOrder":
        if not 0 <= self.filled <= self.requested:
            raise ValueError("filled must be between 0 and requested")
        want = ("failed", "skipped") if self.filled == 0 else ("filled",) if self.filled == self.requested else ("partial",)
        if self.status not in want:
            raise ValueError(f"status {self.status!r} does not match {self.filled} of {self.requested} filled")
        if (self.filled > 0) != (self.avg_price is not None):
            raise ValueError("avg_price is set iff something filled")
        return self


class KalshiStatus(Contract):
    """GET /integrations/kalshi/status: whether approvals place demo orders, and why not."""

    mode: Literal["off", "demo"]
    reason: str | None  # why the mode is off
    trading_enabled: bool
    offline: bool
    key_id_present: bool
    private_key_present: bool
    base_url: str
    host_allowed: bool  # the base URL is a Kalshi demo host
    reachable: bool | None  # null when no authenticated call was attempted
    balance: Money | None  # demo balance (fake money), when reachable
    error: str | None


CONTRACT_MODELS.update({m.__name__: m for m in (VenueOrder, KalshiStatus)})


Hedge.model_rebuild()


# --- QuickBooks write-back and drift check (integrations/quickbooks_sync.py) ---------------
# GET /integrations/quickbooks/sync: each desk ledger entry next to the QuickBooks JournalEntry
# that mirrors it, read back from QuickBooks. Beancount is the system of record.

QboSyncStatus = Literal["posted", "missing", "amount_differs", "failed", "not_posted"]


class QboSyncLine(Contract):
    entry_id: str  # our ledger entry id
    kind: Literal["premium", "payout", "withdrawal", "opening_deposit"]
    date: date
    amount: Money  # total debits in our ledger (= total credits)
    simulated: bool  # the ledger entry itself is simulated (I6)
    doc_number: str  # the JournalEntry's DocNumber: our entry id, hashed to QBO's 21 characters if longer
    qbo_id: str | None  # JournalEntry Id in QuickBooks (or the demo store)
    qbo_amount: Money | None  # total debits on the JournalEntry as read back; null if not found
    status: QboSyncStatus
    detail: str  # why, in words: what differs, what failed, or why it was never posted


class QboSyncReport(Contract):
    business_id: str
    checked_at: AwareDatetime
    mode: Literal["demo", "live"]
    realm_id: str
    company_name: str | None
    synthetic: bool  # demo mode: the JournalEntries live in the SYNTHETIC demo store, not QuickBooks
    system_of_record: Literal["beancount"]
    explanation: str
    lines: list[QboSyncLine]
    counts: dict[QboSyncStatus, int]

    @model_validator(mode="after")
    def _counts(self) -> "QboSyncReport":
        want = {s: 0 for s in QboSyncStatus.__args__}
        for line in self.lines:
            want[line.status] += 1
        if self.counts != want:
            raise ValueError("counts tally the lines by status, every status listed")
        return self


CONTRACT_MODELS.update({m.__name__: m for m in (QboSyncLine, QboSyncReport)})

for _m in (ReconMatch, ReconMismatch, ReconResult, LedgerResponse):
    _m.model_rebuild()
