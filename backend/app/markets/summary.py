"""Deterministic fallback summaries (spec §11 fallback). No LLM calls.

One plain-English sentence per decline reason, built only from the decision's own check
metrics (and, for dropped exposures, the exposure's own fit). Used whenever
`decision.summary` is null; the agent may overwrite it with Claude's text.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.config import Thresholds, get_thresholds
from app.models import Decision, Exposure, Hedge

from .match import event_date

TEAMS = {"NYK": "Knicks", "NYR": "Rangers"}
EVENT_NOUN = {"rain": "rain", "hot": "hot", "home_win": "home-win"}
NO_MARKET_LABEL = {"rain": "NYC rain", "hot": "an NYC hot day", "home_win": "a Knicks or Rangers home win"}
MINUS = "−"


# ---- formatting: every number comes straight from a metric or exposure field


def _num(x: Decimal | int) -> str:
    return f"{int(x):,}"


def _usd(x: Decimal) -> str:
    return f"${Decimal(x):,.2f}"


def _usd_signed_whole(x: Decimal) -> str:
    whole = Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{MINUS if whole < 0 else '+'}${abs(whole):,}"


def _cents(price: Decimal) -> str:
    c = (Decimal(price) * 100).normalize()
    return f"{c:f}¢"


def _pct(ratio: Decimal) -> str:
    return f"{(Decimal(ratio) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)}%"


def _market_label(hedge: Hedge) -> str:
    """'NYC rain for Oct 25', 'an NYC high above 71°F on Oct 25', 'a Knicks home win on Oct 25'."""
    ticker = hedge.ticker or ""
    series, _, rest = ticker.partition("-")
    d = event_date({"event_ticker": ticker.rsplit("-", 1)[0]})
    on = f"{d:%b} {d.day}" if d else ""
    if series == "KXRAIN":
        return f"NYC rain for {on}"
    if series == "KXHIGHNY":
        strike = ticker.rsplit("-T", 1)[-1]
        return f"an NYC high above {strike}°F on {on}"
    if series in ("KXNBAGAME", "KXNHLGAME"):
        team = TEAMS.get(ticker.rsplit("-", 1)[-1], ticker.rsplit("-", 1)[-1])
        return f"a {team} home win on {on}"
    return hedge.market_title or ticker


def _event(hedge: Hedge) -> str:
    return hedge.exposure_id.removeprefix("exp_")


# ---- one clause per check code

UNSTABLE_NOUN = {"rain": "rain", "hot": "hot weather", "home_win": "a home win"}


def unstable_clause(m: dict, event: str) -> str:
    """'rain added $2,212 a day last year but only $303, not distinguishable from zero, in the most
    recent months, so the risk isn't reliable enough to insure'. Whole dollars from the metric."""
    noun = UNSTABLE_NOUN.get(event, event.replace("_", " "))
    train, recent = Decimal(str(m["effect_last_year_usd"])), Decimal(str(m["effect_recent_usd"]))
    verb = "added" if train > 0 else "cost"
    train_s = _usd_signed_whole(abs(train)).lstrip("+")
    if not m.get("sign_flipped"):
        recent_s = _usd_signed_whole(abs(recent)).lstrip("+")
        middle = f"only {recent_s}, not distinguishable from zero,"
    else:
        middle = f"went the other way ({_usd_signed_whole(recent)} a day)"
    return (f"{noun} {verb} {train_s} a day last year but {middle} in the most recent months, "
            "so the risk isn't reliable enough to insure")



def _clause(code: str, m: dict, hedge: Hedge) -> str:
    side = hedge.side.upper()
    if code == "unstable":
        return unstable_clause(m, _event(hedge))
    if code == "no_market":
        label = NO_MARKET_LABEL.get(_event(hedge), _event(hedge))
        return f"there is no open Kalshi market for {label} this week, so there is nothing to buy"
    label = _market_label(hedge)
    if code == "illiquid":
        if m["n_filled"] == 0:
            return (f"nobody is selling {side} on {label}, so 0 of {_num(m['n_target'])} "
                    "contracts could be bought")
        return (f"only {_num(m['n_filled'])} of {_num(m['n_target'])} {side} contracts on {label} "
                "are for sale near the best price, less than half the hedge")
    if code == "overpriced":
        return (f"{side} on {label} costs {_cents(m['avg_price'])} a contract, "
                f"{_cents(m['overpay'])} more than its historical fair price of {_cents(m['fair'])}")
    if code == "basis_too_loose":
        return (f"the days this contract pays and this business's own {EVENT_NOUN.get(_event(hedge), _event(hedge))} "
                f"days line up too loosely (R² {m['r2']}) for it to work as a hedge")
    if code == "too_expensive":
        return (f"the hedge is expected to cost {_usd(m['expected_cost'])} to remove a "
                f"{_usd(m['swing'])} swing, {_pct(m['ratio'])} of what it protects")
    if code == "over_budget":
        return (f"the {_usd(m['premium'])} premium is more than the {_usd(m['remaining'])} "
                "left in this week's budget")
    raise ValueError(f"no fallback sentence for check {code!r}")


def _join(lead: str, clauses: list[str]) -> str:
    first, *rest = clauses
    return " ".join([f"{lead}: {first}."] + [f"Also, {c}." for c in rest])


def fallback_summary(hedge: Hedge) -> str | None:
    """Sentences for a declined or pending decision; None for a proposed one."""
    d: Decision = hedge.decision
    if d.status == "proposed":
        return None
    metrics = {c.code: c.metric for c in d.checks}
    clauses = [_clause(code, metrics[code], hedge) for code in d.reasons]
    return _join("Declined" if d.status == "declined" else "Waiting for your approval", clauses)


def not_hedged_summary(exposure: Exposure | dict[str, Any], th: Thresholds | None = None) -> str:
    """Sentences for an exposure the stats gates dropped (shown as 'measured, not hedged')."""
    th = th or get_thresholds()
    e = exposure if isinstance(exposure, Exposure) else Exposure.model_validate(exposure)
    effect = _usd_signed_whole(e.effect_usd)
    clauses = []
    for reason in e.reasons:
        if reason == "not_significant":
            clauses.append(f"the measured effect ({effect}/day) isn't distinguishable from zero "
                           f"(90% CI {_usd_signed_whole(e.ci90[0])} to {_usd_signed_whole(e.ci90[1])})")
        elif reason == "below_size":
            clauses.append(f"the measured effect ({effect}/day) is smaller than the "
                           f"${_num(th.min_size_usd)}/day worth hedging")
        elif reason == "thin_support":
            clauses.append(f"only {_num(e.n_events_train)} {EVENT_NOUN.get(e.event, e.event)} days in the "
                           f"training year, fewer than the {th.min_support} needed to measure it")
    return _join("Not hedged", clauses)
