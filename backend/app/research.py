"""POST /research: the hypothesis-testing protocol run live on an uploaded daily-revenue CSV.

Contract: docs/RESEARCH_CONTRACT.md. Protocol: docs/UPLOAD_AND_RESEARCH.md §3.

Pure and offline: reads only the fixtures below (NOAA Central Park GHCN-Daily, the Knicks
schedule, the Kalshi series catalog), no network, no LLM, no writes.

Per hypothesis and period (train = first usable date + 1 year, exclusive; unseen = the rest,
fitted independently):

    log(revenue) ~ C(day of week) + C(year-month) + us_federal_holiday + flag [+ knicks_home]

OLS with HC3 errors and normal inference, 90% CIs. Benjamini-Hochberg at 10% across the six
train p-values. Placebo = the flag shifted 7 days later, fitted on train with the same
controls; quiet iff p >= 0.10.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.holiday import USFederalHolidayCalendar

from app.models import CENT, ResearchResponse, ResearchRow, ResearchSide

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GHCN_CSV = FIXTURES / "ghcn_USW00094728.csv"
KNICKS_CSV = FIXTURES / "schedule_knicks.csv"
CATALOG_JSON = FIXTURES / "kalshi_series_catalog.json"

MAX_BYTES = 5 * 1024 * 1024
MIN_DAYS = 540
WINDOW = (date(2024, 1, 1), date(2026, 9, 30))
ALPHA_CI = 0.10  # 90% intervals
BH_Q = 0.10
PLACEBO_P = 0.10
MIN_EVENT_DAYS = 10
PLACEBO_SHIFT_DAYS = 7
MINUS = "−"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ResearchError(Exception):
    """A 422 from the contract's validation table."""

    def __init__(self, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.detail = code, message, detail


# --- Hypotheses (fixed before fitting) ---------------------------------------


@dataclass(frozen=True)
class Hypothesis:
    id: str
    label: str
    mechanism: str
    catalog_id: str  # row in kalshi_series_catalog.json
    knicks: bool = False
    # Summary phrasing: subject noun phrase, and whether it takes a plural verb.
    noun: str = ""
    plural: bool = False


HYPOTHESES: tuple[Hypothesis, ...] = (
    Hypothesis("rain", "Rain day", "Riders skip rentals when it rains.", "rain", noun="rain"),
    Hypothesis("cold", "Cold day <40°F", "Few people ride in the cold.", "cold_40", noun="cold"),
    Hypothesis("warm", "Warm day >80°F", "Nice weather brings casual riders.", "hot_80",
               noun="warm days", plural=True),
    Hypothesis("hot", "Hot day >90°F", "Extreme heat might keep riders indoors.", "hot_90",
               noun="hot days", plural=True),
    Hypothesis("knicks_home", "Knicks home game", "Game crowds near MSG might rent bikes.", "home_game",
               knicks=True, noun="Knicks home games", plural=True),
    Hypothesis("knicks_win", "Knicks win", "Celebrations might bring extra riders.", "home_win",
               knicks=True, noun="Knicks wins", plural=True),
)

NOTES = {
    "thin_support": "Too few event days in the training year",
    "not_significant": "Not distinguishable from zero",
    "failed_bh": "Not significant after correcting for 6 tests",
    "placebo_fired": "The week-shifted placebo fired too",
    "sign_flipped": "Unseen data points the other way",
    "did_not_replicate": "Didn't hold up on unseen data",
}

FIXED_CHIPS = [
    "Day-of-week + month controls",
    "90% intervals",
    "Placebo: flags shifted 7 days",
    "Corrected for 6 tests",
    "At least 10 event days",
]


# --- Fixtures ----------------------------------------------------------------


@lru_cache(maxsize=1)
def weather() -> pd.DataFrame:
    """NOAA Central Park daily PRCP (in) and TMAX (°F), indexed by date."""
    df = pd.read_csv(GHCN_CSV, dtype={"PRCP": float, "TMAX": float})
    df.index = pd.to_datetime(df["DATE"]).dt.date
    return df[["PRCP", "TMAX"]]


@lru_cache(maxsize=1)
def knicks() -> pd.DataFrame:
    """Knicks schedule: `home` and `home_win` (home & home team won) by date."""
    df = pd.read_csv(KNICKS_CSV, dtype=str, keep_default_na=False)
    out = pd.DataFrame(index=pd.to_datetime(df["date"]).dt.date)
    out["home"] = (df["home"].str.lower() == "true").to_numpy()
    out["win"] = out["home"] & (df["home_win"].str.lower() == "true").to_numpy()
    return out.groupby(level=0).max()


@lru_cache(maxsize=1)
def _catalog() -> dict[str, dict]:
    return {e["id"]: e for e in json.loads(CATALOG_JSON.read_text())["events"]}


@lru_cache(maxsize=1)
def _holidays() -> frozenset[date]:
    days = USFederalHolidayCalendar().holidays(start="2023-01-01", end="2027-12-31")
    return frozenset(d.date() for d in days)


def _flag_on(hid: str, d: date) -> bool:
    """The flag's value on calendar date `d` (False outside the record)."""
    if hid in ("knicks_home", "knicks_win"):
        k = knicks()
        if d not in k.index:
            return False
        return bool(k.at[d, "home" if hid == "knicks_home" else "win"])
    w = weather()
    if d not in w.index:
        return False
    prcp, tmax = w.at[d, "PRCP"], w.at[d, "TMAX"]
    if hid == "rain":
        return bool(prcp >= 0.01)
    if hid == "cold":
        return bool(tmax < 40)
    if hid == "warm":
        return bool(tmax > 80)
    if hid == "hot":
        return bool(tmax > 90)
    raise KeyError(hid)


# --- Kalshi mapping -----------------------------------------------------------


def _primary(entry: dict) -> list[dict]:
    return [i for i in entry.get("instruments", []) if i.get("role") == "primary" and i.get("exists")]


def kalshi_label(h: Hypothesis) -> str:
    """Short instrument label derived from the catalog row."""
    entry = _catalog()[h.catalog_id]
    prim = _primary(entry)
    if h.knicks:
        prim = [i for i in prim if "NYK" in (i.get("filter") or "")]  # Knicks only, not Rangers
    if not prim:
        reason = (entry.get("null_reason") or "").lower()
        return "None (games are scheduled)" if "schedule" in reason else "None"
    inst = prim[0]
    series = inst["series"]
    strike = (inst.get("strike") or "").strip()
    if (inst.get("filter") or "") == "-NYC" and h.id == "rain":
        station = entry.get("settlement_station", "").split("(")[0].strip()
        return f"{series} · NYC daily rain (Central Park, {station})"
    if strike.startswith("<"):
        return f"{series} low strikes"
    return series


def kalshi_sendable_instrument(h: Hypothesis) -> bool:
    """A daily, fixed-strike instrument that settles exactly on the flag: the catalog's primary
    instrument is daily and its basis note says the contract is exact for the flag (not only on
    days the strike happens to be on a forecast-centred ladder)."""
    entry = _catalog()[h.catalog_id]
    prim = _primary(entry)
    if h.knicks or not prim:
        return False
    daily = prim[0].get("api_frequency") == "daily" and entry.get("cadence") == "daily"
    exact = (entry.get("basis_note") or "").startswith("Exact")
    return daily and exact


# --- CSV parsing / validation -------------------------------------------------


def _parse_revenue(raw: str) -> Decimal:
    s = raw.strip().strip('"').strip("'").strip().replace(",", "").replace("$", "")
    if not s:
        raise InvalidOperation
    v = Decimal(s)
    if not v.is_finite():
        raise InvalidOperation
    return v


def parse_csv(data: bytes | None) -> pd.Series:
    """Validate an upload; returns usable (non-zero) revenue as a float Series indexed by date.
    Raises ResearchError in the contract's order."""
    if not data:
        raise ResearchError("bad_csv", "The file is empty. Upload a CSV with date and revenue columns.")
    if len(data) > MAX_BYTES:
        raise ResearchError("bad_csv", "The file is larger than 5 MB.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ResearchError("bad_csv", "The file isn't UTF-8 text. Save it as a UTF-8 CSV and try again.") from None

    header: list[str] | None = None
    rows: list[tuple[int, date, Decimal]] = []
    di = ri = -1
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = next(csv.reader([line]))
        if header is None:
            header = [f.strip().strip('"').lower() for f in fields]
            if "date" not in header or "revenue" not in header:
                raise ResearchError("bad_csv", "The first row must be a header with date and revenue columns.")
            di, ri = header.index("date"), header.index("revenue")
            continue
        try:
            ds = fields[di].strip().strip('"')
            if not _DATE_RE.match(ds):
                raise ValueError
            d = date.fromisoformat(ds)
            rev = _parse_revenue(fields[ri])
        except (IndexError, ValueError, InvalidOperation):
            raise ResearchError("bad_csv", f"Line {lineno} doesn't have a valid date (YYYY-MM-DD) and revenue.",
                                {"line": lineno}) from None
        rows.append((lineno, d, rev))
    if header is None:
        raise ResearchError("bad_csv", "The file has no header row with date and revenue columns.")
    if not rows:
        raise ResearchError("bad_csv", "The file has a header but no data rows.")

    seen: set[date] = set()
    dups: list[str] = []
    for _, d, _ in rows:
        if d in seen and d.isoformat() not in dups:
            dups.append(d.isoformat())
        seen.add(d)
    if dups:
        raise ResearchError("duplicate_dates", f"Some dates appear more than once, e.g. {dups[0]}. Keep one row per day.",
                            {"dates": dups[:5]})

    neg = [d.isoformat() for _, d, v in rows if v < 0]
    if neg:
        raise ResearchError("negative_revenue", f"Revenue can't be negative (first on {neg[0]}).", {"dates": neg[:5]})

    out = [d.isoformat() for _, d, _ in sorted(rows, key=lambda r: r[1]) if not (WINDOW[0] <= d <= WINDOW[1])]
    if out:
        raise ResearchError(
            "out_of_window",
            f"Dates must fall between {WINDOW[0].isoformat()} and {WINDOW[1].isoformat()}, "
            f"the span of the weather record (first outside: {out[0]}).",
            {"dates": out[:5], "window": [WINDOW[0].isoformat(), WINDOW[1].isoformat()]},
        )

    usable = sorted((d, float(v)) for _, d, v in rows if v != 0)
    if len(usable) < MIN_DAYS:
        raise ResearchError(
            "too_short",
            f"The file has {len(usable)} days with revenue; the research needs at least {MIN_DAYS} (about 18 months).",
            {"days": len(usable), "min_days": MIN_DAYS},
        )
    return pd.Series([v for _, v in usable], index=[d for d, _ in usable], name="revenue")


# --- Fitting -----------------------------------------------------------------


@dataclass
class Fit:
    n_days: int  # event days in the fitted sample
    beta: float | None = None  # None = not estimable
    lo: float | None = None
    hi: float | None = None
    p: float = 1.0
    mean_rev: float = 0.0

    @property
    def ok(self) -> bool:
        return self.beta is not None


def _design(dates: list[date], flag: np.ndarray, extra: dict[str, np.ndarray]) -> pd.DataFrame:
    idx = pd.to_datetime(pd.Series(dates))
    X = pd.DataFrame(index=range(len(dates)))
    dow = pd.get_dummies(idx.dt.day_of_week, prefix="dow", drop_first=True, dtype=float)
    ym = pd.get_dummies(idx.dt.strftime("%Y-%m"), prefix="ym", drop_first=True, dtype=float)
    X = pd.concat([X, dow, ym], axis=1)
    hol = np.array([d in _holidays() for d in dates], dtype=float)
    if hol.any():
        X["holiday"] = hol
    for k, v in extra.items():
        X[k] = v.astype(float)
    X["flag"] = flag.astype(float)
    return sm.add_constant(X, has_constant="add")


def fit_flag(rev: pd.Series, flag: np.ndarray, extra: dict[str, np.ndarray] | None = None) -> Fit:
    """log revenue on the controls + `flag`; HC3, normal inference, 90% CI on the flag."""
    n_event = int(flag.sum())
    fit = Fit(n_days=n_event, mean_rev=float(rev.mean()) if len(rev) else 0.0)
    if n_event < 2 or n_event == len(flag):
        return fit
    X = _design(list(rev.index), flag, extra or {})
    if np.linalg.matrix_rank(X.to_numpy()) < X.shape[1]:
        return fit
    res = sm.OLS(np.log(rev.to_numpy()), X).fit(cov_type="HC3", use_t=False)
    b, p = float(res.params["flag"]), float(res.pvalues["flag"])
    lo, hi = (float(x) for x in res.conf_int(alpha=ALPHA_CI).loc["flag"])
    if not all(math.isfinite(x) for x in (b, p, lo, hi)):
        return fit
    fit.beta, fit.lo, fit.hi, fit.p = b, lo, hi, p
    return fit


def _flags(h: Hypothesis, dates: list[date], shift: int = 0) -> np.ndarray:
    return np.array([_flag_on(h.id, d - timedelta(days=shift)) for d in dates], dtype=bool)


def _fit_period(h: Hypothesis, rev: pd.Series, shift: int = 0) -> Fit:
    """Fit hypothesis `h` on one period. Knicks hypotheses only on schedule-covered dates; the
    dollar effect still scales by the whole period's mean daily revenue (contract)."""
    period_mean = float(rev.mean())
    if h.knicks:
        rev = rev[[d >= knicks().index.min() for d in rev.index]]
    dates = list(rev.index)
    extra = {}
    if h.id == "knicks_win":
        extra["knicks_home"] = _flags(HYPOTHESES[4], dates)
    fit = fit_flag(rev, _flags(h, dates, shift), extra)
    fit.mean_rev = period_mean
    return fit


def bh_reject(pvals: list[float], q: float = BH_Q) -> list[bool]:
    """Benjamini-Hochberg step-up at level q."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    k_max = 0
    for rank, i in enumerate(order, start=1):
        if pvals[i] <= rank / m * q:
            k_max = rank
    rejected = [False] * m
    for rank, i in enumerate(order, start=1):
        rejected[i] = rank <= k_max
    return rejected


# --- Formatting --------------------------------------------------------------


def _q(x: float, unit: Decimal = CENT) -> Decimal:
    return Decimal(repr(float(x))).quantize(unit, rounding=ROUND_HALF_UP)


def _signed(d: Decimal, body: str) -> str:
    if d < 0:
        return f"{MINUS}{body}"
    return f"+{body}"


def fmt_usd(d: Decimal) -> str:
    return _signed(d, f"${abs(d):,.2f}")


def fmt_pct(d: Decimal) -> str:
    return _signed(d, f"{abs(d):.1f}%")


def fmt_p(p: float) -> str:
    return "<0.01" if p < 0.005 else f"{_q(p, CENT)}"


def _side(fit: Fit) -> ResearchSide:
    days = f"{fit.n_days} days"
    if not fit.ok:
        return ResearchSide(text="Not estimable", ci="—", days=days,
                            plot=(Decimal("0.00"), Decimal("0.00"), Decimal("0.00")))
    pct = _q((math.exp(fit.beta) - 1) * 100, Decimal("0.1"))
    eff, lo, hi = (_q((math.exp(x) - 1) * fit.mean_rev) for x in (fit.beta, fit.lo, fit.hi))
    return ResearchSide(
        text=f"{fmt_pct(pct)} · {fmt_usd(eff)}/day",
        ci=f"90% CI {fmt_usd(lo)} to {fmt_usd(hi)}",
        days=days,
        plot=(eff, lo, hi),
    )


# --- Summary -----------------------------------------------------------------


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _clause(hs: list[Hypothesis], singular: str, plural: str) -> str:
    verb = plural if len(hs) > 1 or hs[0].plural else singular
    return f"{_join([h.noun for h in hs])} {verb}"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def summary(found_down: list[Hypothesis], found_up: list[Hypothesis], not_found: list[Hypothesis],
            sendable: list[Hypothesis]) -> str:
    parts: list[str] = []
    first = []
    if found_down:
        first.append(_clause(found_down, "reliably costs you money", "reliably cost you money"))
    if found_up:
        first.append(_clause(found_up, "helps", "help"))
    if first:
        parts.append(_cap("; ".join(first)) + ".")
    if not_found:
        if found_down or found_up:
            parts.append(_cap(_clause(not_found, "makes no measurable difference",
                                      "make no measurable difference")) + ".")
        else:
            parts.append("None of the six ideas held up: rain, cold, warm days, hot days, Knicks home games "
                         "and Knicks wins make no measurable difference.")
    if sendable:
        names = _join([("rain days" if h.id == "rain" else f"{h.label.lower()}s") for h in sendable])
        parts.append(f"The desk can protect {names} with Kalshi's daily NYC rain contract."
                     if [h.id for h in sendable] == ["rain"] else
                     f"The desk can protect {names} with a matching Kalshi contract.")
    elif found_down:
        parts.append("No Kalshi contract settles on exactly these days yet, so there is nothing to send to the desk.")
    return " ".join(parts)


# --- Protocol ----------------------------------------------------------------


def _chips(train: pd.Series, unseen: pd.Series, first: date, train_end: date) -> list[str]:
    if first.month == 1 and first.day == 1 and train_end == date(first.year + 1, 1, 1):
        chips = [f"Training year: {first.year}"]
    else:
        chips = [f"Training: {first.isoformat()} to {(train_end - timedelta(days=1)).isoformat()}"]
    if len(unseen):
        y0, y1 = unseen.index[0].year, unseen.index[-1].year
        chips.append(f"Unseen: {y0}" if y0 == y1 else f"Unseen: {y0}–{str(y1)[-2:]}")
    return chips + FIXED_CHIPS


def run(rev: pd.Series) -> ResearchResponse:
    """The full protocol on usable (non-zero, validated) revenue indexed by date."""
    first, last = rev.index[0], rev.index[-1]
    try:
        train_end = first.replace(year=first.year + 1)
    except ValueError:  # Feb 29
        train_end = date(first.year + 1, 3, 1)
    train = rev[[d < train_end for d in rev.index]]
    unseen = rev[[d >= train_end for d in rev.index]]

    fits_train = [_fit_period(h, train) for h in HYPOTHESES]
    fits_unseen = [_fit_period(h, unseen) for h in HYPOTHESES]
    placebos = [_fit_period(h, train, shift=PLACEBO_SHIFT_DAYS) for h in HYPOTHESES]
    survives = bh_reject([f.p if f.ok else 1.0 for f in fits_train])

    rows: list[ResearchRow] = []
    found_down, found_up, not_found, sendables = [], [], [], []
    for h, ft, fu, fp, bh in zip(HYPOTHESES, fits_train, fits_unseen, placebos, survives):
        reason = None
        if ft.n_days < MIN_EVENT_DAYS:
            reason = "thin_support"
        elif not ft.ok or ft.lo <= 0 <= ft.hi:
            reason = "not_significant"
        elif not bh:
            reason = "failed_bh"
        elif fp.ok and fp.p < PLACEBO_P:
            reason = "placebo_fired"
        elif fu.ok and (fu.beta > 0) != (ft.beta > 0):
            reason = "sign_flipped"
        elif not fu.ok or fu.lo <= 0 <= fu.hi:
            reason = "did_not_replicate"
        found = reason is None
        downside = found and ft.beta < 0
        sendable = downside and kalshi_sendable_instrument(h)
        if not found:
            note = NOTES[reason]
            not_found.append(h)
        elif not downside:
            note = "upside, no protection needed"
            found_up.append(h)
        else:
            note = "hedgeable" if sendable else None
            found_down.append(h)
        if sendable:
            sendables.append(h)
        p_txt = fmt_p(fp.p)
        placebo = f"Not significant (p {p_txt})" if (not fp.ok or fp.p >= PLACEBO_P) else f"Significant (p {p_txt})"
        rows.append(ResearchRow(
            id=h.id, label=h.label, mechanism=h.mechanism,
            train=_side(ft), unseen=_side(fu), placebo=placebo,
            verdict="FOUND" if found else "NOT FOUND", verdictNote=note,
            kalshi=kalshi_label(h), sendable=sendable,
        ))

    return ResearchResponse(
        summary=summary(found_down, found_up, not_found, sendables),
        protocol_chips=_chips(train, unseen, first, train_end),
        n_days=len(rev), first=first, last=last, rows=rows, source="live",
    )


def research_csv(data: bytes | None) -> ResearchResponse:
    return run(parse_csv(data))
