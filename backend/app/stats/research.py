"""Live research protocol on an uploaded daily-revenue CSV (docs/UPLOAD_AND_RESEARCH.md §3).

Pure and deterministic; no LLM, nothing stored. The hypotheses and their mechanisms are fixed
here before any data is seen (pre-registered); the code, not a model, applies every verdict.

Protocol, per hypothesis (one flag at a time):
- Model: log(revenue) ~ day of week + year-month fixed effects + holiday + flag, HC3 errors;
  `knicks_win` also controls `knicks_home`. 90% intervals (z = 1.645).
- Train = the file's first year; holdout = the rest, fitted independently (nothing tuned on it).
- Benjamini–Hochberg at 10% across the train p-values of every hypothesis in the run.
- Placebo: the same flag shifted 7 days later, fitted on train; it must come back quiet (p ≥ 0.10).
- FOUND iff ≥ 10 train event days, the train CI excludes 0, it survives BH, the placebo is quiet,
  and the holdout has the same sign with its own CI excluding 0.

Dollars: the % effect (exp(b) − 1) times the period's mean daily revenue, so "$ per day at the
period average". Weather is NOAA GHCN-Daily USW00094728 (Central Park), the station Kalshi's NYC
contracts settle on; Knicks games come from `fixtures/schedule_knicks.csv`, and game hypotheses
are fitted only on dates the schedule covers.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

import numpy as np
import pandas as pd
import statsmodels.api as sm

from app import config
from app.config import FIXTURES_DIR
from app.models import ResearchEstimate, ResearchHypothesis, ResearchPeriod, ResearchReport

Z90 = 1.645
Q_BH = 0.10
PLACEBO_ALPHA = 0.10
PLACEBO_SHIFT_DAYS = 7
MIN_EVENT_DAYS = 10
MIN_DAYS = 540
MAX_BYTES = 5_000_000
CENT = Decimal("0.01")

WEATHER_FILE = FIXTURES_DIR / "ghcn_USW00094728.csv"
KNICKS_FILE = FIXTURES_DIR / "schedule_knicks.csv"
STATION = "NOAA GHCN-Daily USW00094728 (Central Park)"


class ResearchInputError(ValueError):
    """A CSV the protocol can't run on. `code` is the 422 error code."""

    def __init__(self, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


@dataclass(frozen=True)
class Hypothesis:
    id: str
    label: str
    rule: str
    mechanism: str
    venue: str
    plural: str  # for the templated summary
    game: bool = False


# Pre-registered: mechanisms are written before the data is fitted, never after.
HYPOTHESES: tuple[Hypothesis, ...] = (
    Hypothesis("rain", "Rain day", "Central Park precipitation ≥ 0.01 in",
               "Customers stay in when it rains.",
               "Kalshi KXRAIN (NYC, Central Park) · Polymarket “Where will it rain” (NYC, NWS Central Park report)",
               "rain days"),
    Hypothesis("cold", "Cold day <40°F", "Central Park high below 40°F",
               "Few people come out in the cold.",
               "KXHIGHNY strikes sit near the forecast; a fixed <40°F strike is rarely listed", "cold days (<40°F)"),
    Hypothesis("warm", "Warm day >80°F", "Central Park high above 80°F",
               "Nice weather brings casual customers.",
               "KXHIGHNY (Central Park) · Polymarket NYC high settles at LaGuardia, a different station",
               "warm days (>80°F)"),
    Hypothesis("hot", "Hot day >90°F", "Central Park high above 90°F",
               "Extreme heat might keep customers indoors.",
               "KXHIGHNY (Central Park) · Polymarket NYC high settles at LaGuardia, a different station",
               "hot days (>90°F)"),
    Hypothesis("knicks_home", "Knicks home game", "Knicks play at Madison Square Garden",
               "Game crowds near MSG might change traffic.",
               "None: games are scheduled, so there is nothing uncertain to hedge", "Knicks home games",
               game=True),
    Hypothesis("knicks_win", "Knicks win", "Knicks win a home game (home games controlled)",
               "Celebrations might bring extra customers.",
               "Kalshi KXNBAGAME · Polymarket NBA moneyline", "Knicks wins", game=True),
)
SENDABLE = {"rain"}  # FOUND downside with a daily contract the desk can price

PROTOCOL = (
    "Training year, then unseen data fitted independently",
    "Day-of-week + month controls",
    "90% intervals",
    f"Placebo: flags shifted {PLACEBO_SHIFT_DAYS} days",
    f"Corrected for {len(HYPOTHESES)} tests (BH 10%)",
    f"At least {MIN_EVENT_DAYS} event days",
)


# --- Inputs ---------------------------------------------------------------------


@lru_cache
def weather() -> pd.DataFrame:
    w = pd.read_csv(WEATHER_FILE, dtype={"PRCP": str, "TMAX": str})
    out = pd.DataFrame({
        "date": pd.to_datetime(w["DATE"]).dt.date,
        "prcp": pd.to_numeric(w["PRCP"], errors="coerce"),
        "tmax": pd.to_numeric(w["TMAX"], errors="coerce"),
    }).dropna()
    return out.set_index("date")


@lru_cache
def knicks() -> tuple[frozenset[date], frozenset[date], date, date]:
    """(home game days, home win days, first and last schedule date)."""
    k = pd.read_csv(KNICKS_FILE)
    k["date"] = pd.to_datetime(k["date"]).dt.date
    home = k[k["home"].astype(str) == "True"]
    wins = home[home["home_win"].astype(str) == "True"]
    return frozenset(home["date"]), frozenset(wins["date"]), k["date"].min(), k["date"].max()


_MONEY_JUNK = re.compile(r"[$,\s]")


def parse_csv(raw: bytes) -> tuple[pd.DataFrame, list[str]]:
    """`date,revenue` rows (any header that names a date and a revenue column; else the first two
    columns). `#` lines are notes, returned verbatim (they often label synthetic data, I6)."""
    if len(raw) > MAX_BYTES:
        raise ResearchInputError("bad_csv", "The file is larger than 5 MB.", {"bytes": len(raw)})
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ResearchInputError("bad_csv", "The file isn't UTF-8 text.")
    notes = [ln.lstrip("#").strip() for ln in text.splitlines() if ln.strip().startswith("#")]
    body = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    rows = list(csv.reader(body))
    if len(rows) < 2:
        raise ResearchInputError("bad_csv", "The file needs a date,revenue header and one row per day.")
    header = [h.strip().lower() for h in rows[0]]
    di = next((i for i, h in enumerate(header) if h in ("date", "day", "ds")), None)
    ri = next((i for i, h in enumerate(header) if h in ("revenue", "sales", "amount", "total", "y")), None)
    if di is None or ri is None:
        if len(header) < 2:
            raise ResearchInputError("bad_csv", "The file needs two columns: date and revenue.")
        di, ri = 0, 1
    dates, revenue, bad = [], [], []
    for n, r in enumerate(rows[1:], start=2):
        try:
            d = date.fromisoformat(r[di].strip().strip('"'))
            v = float(_MONEY_JUNK.sub("", r[ri].strip().strip('"')))
            if not math.isfinite(v):
                raise ValueError
        except (ValueError, IndexError):
            bad.append(n)
            continue
        dates.append(d)
        revenue.append(v)
    if not dates or len(bad) > max(5, len(rows) // 20):
        raise ResearchInputError("bad_csv", "Rows need an ISO date (2024-01-31) and a number.",
                                 {"bad_lines": bad[:10]})
    df = pd.DataFrame({"date": dates, "revenue": revenue})
    dupes = df["date"][df["date"].duplicated()]
    if len(dupes):
        raise ResearchInputError("duplicate_dates", "Each date may appear once.",
                                 {"dates": sorted({d.isoformat() for d in dupes})[:10]})
    neg = df["date"][df["revenue"] < 0]
    if len(neg):
        raise ResearchInputError("negative_revenue", "Revenue can't be negative.",
                                 {"dates": [d.isoformat() for d in neg[:10]]})
    return df.sort_values("date").reset_index(drop=True), notes


# --- Model -------------------------------------------------------------------------


def _design(f: pd.DataFrame, flag: str, controls: tuple[str, ...]) -> pd.DataFrame:
    X = pd.DataFrame({"const": 1.0}, index=f.index)
    dow = pd.to_datetime(f["date"]).dt.day_of_week
    for d in range(1, 7):
        X[f"dow_{d}"] = (dow == d).astype(float)
    ym = pd.to_datetime(f["date"]).dt.strftime("%Y%m")
    X = X.join(pd.get_dummies(ym, prefix="ym", drop_first=True).astype(float))
    X["holiday"] = f["date"].isin(config.HOLIDAYS).astype(float)
    for c in controls:
        X[c] = f[c].astype(float)
    X["flag"] = f[flag].astype(float)
    return X.loc[:, (X.nunique() > 1) | (X.columns == "const")]


def _fit(f: pd.DataFrame, flag: str, controls: tuple[str, ...] = ()) -> tuple[float, float, float] | None:
    """(b, se, p) on log revenue, or None when the flag has no variation or can't be identified."""
    n_ev = int(f[flag].sum())
    if n_ev < 2 or n_ev >= len(f) - 1:
        return None
    X = _design(f, flag, controls)
    if "flag" not in X.columns:
        return None
    r = sm.OLS(np.log(f["revenue"].to_numpy()), X).fit(cov_type="HC3")
    b, se, p = float(r.params["flag"]), float(r.bse["flag"]), float(r.pvalues["flag"])
    if not all(math.isfinite(x) for x in (b, se, p)):
        return None
    return b, se, p


def _money(x: float) -> Decimal:
    return Decimal(repr(x)).quantize(CENT, rounding=ROUND_HALF_UP)


def _estimate(f: pd.DataFrame, flag: str, controls: tuple[str, ...]) -> ResearchEstimate | None:
    fit = _fit(f, flag, controls)
    if fit is None:
        return None
    b, se, p = fit
    mean = float(f["revenue"].mean())
    pct = math.expm1(b)
    lo, hi = math.expm1(b - Z90 * se), math.expm1(b + Z90 * se)
    return ResearchEstimate(
        pct=round(pct * 100, 1), effect_usd=_money(pct * mean), ci90=(_money(lo * mean), _money(hi * mean)),
        ci_excludes_zero=lo > 0 or hi < 0, p_value=round(p, 4), n_event_days=int(f[flag].sum()),
        n_days=len(f), start=f["date"].iloc[0], end=f["date"].iloc[-1], mean_revenue=_money(mean),
    )


def bh_qvalues(p: list[float]) -> list[float]:
    """Benjamini–Hochberg adjusted p-values (q), in input order."""
    m = len(p)
    order = sorted(range(m), key=lambda i: p[i])
    q = [1.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, p[i] * m / rank)
        q[i] = min(1.0, running)
    return q


def _frame(df: pd.DataFrame) -> pd.DataFrame:
    w = weather()
    f = df[df["date"].isin(w.index)].copy()
    f["prcp"] = f["date"].map(w["prcp"])
    f["tmax"] = f["date"].map(w["tmax"])
    f["rain"] = f["prcp"] >= 0.01
    f["cold"] = f["tmax"] < 40
    f["warm"] = f["tmax"] > 80
    f["hot"] = f["tmax"] > 90
    home, wins, _, _ = knicks()
    f["knicks_home"] = f["date"].isin(home)
    f["knicks_win"] = f["date"].isin(wins)
    return f.reset_index(drop=True)


def _placebo(f: pd.DataFrame, flag: str) -> pd.Series:
    """The flag moved PLACEBO_SHIFT_DAYS later by calendar date (days off the file read False)."""
    on = set(f.loc[f[flag], "date"])
    return f["date"].map(lambda d: (d - timedelta(days=PLACEBO_SHIFT_DAYS)) in on)


# --- Report ------------------------------------------------------------------------


def _summary(rows: list[ResearchHypothesis]) -> str:
    """Templated from the verdicts; carries no figures (I2)."""
    by_id = {h.id: h for h in HYPOTHESES}
    hurt = [by_id[r.id].plural for r in rows if r.verdict == "FOUND" and r.direction == "negative"]
    helps = [by_id[r.id].plural for r in rows if r.verdict == "FOUND" and r.direction == "positive"]
    none = [by_id[r.id].plural for r in rows if r.verdict == "NOT FOUND"]

    def join(xs: list[str]) -> str:
        s = xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]
        return s[0].upper() + s[1:]

    parts = []
    if hurt:
        parts.append(f"{join(hurt)} reliably cost you money")
    if helps:
        parts.append(f"{join(helps)} reliably help" if not hurt else f"{join(helps)[0].lower()}{join(helps)[1:]} help")
    text = "; ".join(parts) + "." if parts else "Nothing we tested holds up on unseen data."
    if none:
        text += f" {join(none)} make no difference we can measure."
    if any(r.sendable for r in rows):
        text += " The desk can price protection for rain days on Kalshi and Polymarket."
    return text


def run(raw: bytes, name: str | None = None) -> ResearchReport:
    df, notes = parse_csv(raw)
    w = weather()
    n_rows = len(df)
    first, last = df["date"].iloc[0], df["date"].iloc[-1]
    inside = df[df["date"].isin(w.index)]
    if inside.empty:
        raise ResearchInputError(
            "out_of_window", "None of the dates overlap the weather record we have.",
            {"file": [first.isoformat(), last.isoformat()],
             "weather": [min(w.index).isoformat(), max(w.index).isoformat()]})
    closed = int((inside["revenue"] == 0).sum())
    used = inside[inside["revenue"] > 0]
    if len(used) < MIN_DAYS:
        raise ResearchInputError(
            "too_short", f"Need at least {MIN_DAYS} open days inside the weather record; found {len(used)}.",
            {"days": len(used), "min_days": MIN_DAYS})
    f = _frame(used)
    start = f["date"].iloc[0]
    try:  # train = the first year of the file
        cutoff = start.replace(year=start.year + 1)
    except ValueError:  # 29 Feb
        cutoff = date(start.year + 1, 3, 1)
    train_all, hold_all = f[f["date"] < cutoff], f[f["date"] >= cutoff]
    _, _, g0, g1 = knicks()

    fits = []
    for h in HYPOTHESES:
        tr, ho = train_all, hold_all
        if h.game:
            tr = tr[(tr["date"] >= g0) & (tr["date"] <= g1)].reset_index(drop=True)
            ho = ho[(ho["date"] >= g0) & (ho["date"] <= g1)].reset_index(drop=True)
        controls = ("knicks_home",) if h.id == "knicks_win" else ()
        train = _estimate(tr, h.id, controls)
        holdout = _estimate(ho, h.id, controls)
        tp = tr.assign(placebo=_placebo(tr, h.id)) if len(tr) else tr
        pf = _fit(tp, "placebo", controls) if len(tr) else None
        fits.append((h, tr, train, holdout, None if pf is None else round(pf[2], 4)))

    q = bh_qvalues([t.p_value if t is not None else 1.0 for _, _, t, _, _ in fits])
    rows: list[ResearchHypothesis] = []
    for (h, tr, train, holdout, placebo_p), qv in zip(fits, q):
        reasons: list[str] = []
        n_ev = int(tr[h.id].sum()) if len(tr) else 0
        if n_ev < MIN_EVENT_DAYS:
            reasons.append("thin_support")
        if train is None or not train.ci_excludes_zero:
            reasons.append("not_significant")
        elif qv > Q_BH:
            reasons.append("failed_bh")
        if placebo_p is not None and placebo_p < PLACEBO_ALPHA:
            reasons.append("placebo_fired")
        if train is not None and train.ci_excludes_zero:
            if holdout is None or holdout.n_event_days < MIN_EVENT_DAYS:
                reasons.append("did_not_replicate")
            elif (holdout.effect_usd > 0) != (train.effect_usd > 0):
                reasons.append("sign_flipped")
            elif not holdout.ci_excludes_zero:
                reasons.append("did_not_replicate")
        verdict = "NOT FOUND" if reasons else "FOUND"
        direction = None if train is None else ("positive" if train.effect_usd > 0 else "negative")
        rows.append(ResearchHypothesis(
            id=h.id, label=h.label, rule=h.rule, mechanism=h.mechanism, train=train, holdout=holdout,
            placebo_p=placebo_p, bh_q=round(qv, 4), verdict=verdict, reasons=reasons, direction=direction,
            upside=verdict == "FOUND" and direction == "positive", venue=h.venue,
            sendable=verdict == "FOUND" and direction == "negative" and h.id in SENDABLE,
        ))

    ends = [abs(x) for r in rows for e in (r.train, r.holdout) if e is not None for x in e.ci90]
    return ResearchReport(
        name=name, n_rows=n_rows, n_days=len(f), n_closed_days=closed, n_outside_window=n_rows - len(inside),
        first=first, last=last,
        train=ResearchPeriod(start=train_all["date"].iloc[0], end=train_all["date"].iloc[-1]),
        holdout=ResearchPeriod(start=hold_all["date"].iloc[0], end=hold_all["date"].iloc[-1]),
        station=STATION, protocol=list(PROTOCOL), notes=notes, hypotheses=rows, summary=_summary(rows),
        plot_max_usd=max(ends, default=Decimal("1.00")),
    )
