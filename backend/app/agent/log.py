"""Append-only decision log and the I2 number validator (spec §1 I2/I5, CONTRACTS R8/R18).

API:
- `append(entry) -> log_id`: validates `entry.summary` against `entry.numbers` (the I2
  allowed-number set) and appends through `db.append_log`. Raises `UnsupportedNumbers`
  instead of writing a number no tool produced. There is no update or delete function.
- `list(business_id, limit=None, hedge_id=None)`: entries newest first.
- `validate_summary(summary, allowed) -> list[offending_token]`.
- `allowed_numbers(*sources) -> dict`: flattens tool outputs (checks, Hedge sizing, Budget,
  ReconResult) into the flat `numbers` dict stored on the entry (`numbers_source`, G3).
- `sanitize(summary, allowed) -> (text, offending)`: replaces unsupported tokens with
  "[unverified]" for callers that must show something (chat).

Validator scope (G1/G2): currency, percent, cent and bare numbers are checked; numbers that
are part of a ticker, id, date, year or compound word ("12-call") are exempt, as are
spelled-out numbers. A token passes if it equals an allowed number (absolute value) after
x100 (probability to percent, dollars to cents) and round-half-up to the displayed precision.
A rounded match needs at least two significant digits on display ("0.36" for 0.3647 passes,
"0.4" does not); exact matches always pass.

Immutability (G12): `install_guards` adds SQLite triggers that abort UPDATE/DELETE on the
`log` table; `append` installs them on first use per engine.
"""

from __future__ import annotations

import builtins
import re
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app import db
from app.models import LogEntry

UNVERIFIED = "[unverified]"

_MONTHS = (
    "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|"
    "august|september|october|november|december|mon|tue|wed|thu|fri|sat|sun"
)
_TOKEN = re.compile(
    r"(?P<pre>[-−]?\$\s?[-−]?)?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
    r"(?P<post>\s?%|\s?¢|\s(?:percent|cents?)\b)?",
    re.IGNORECASE,
)
_MONTH_BEFORE = re.compile(rf"\b(?:{_MONTHS})\.?\s+$", re.IGNORECASE)


class UnsupportedNumbers(ValueError):
    """A summary carries numbers that no tool result supports (I2)."""

    def __init__(self, offending: builtins.list[str]):
        super().__init__(f"unsupported_numbers: {offending}")
        self.offending = offending


# --- Allowed-number set -------------------------------------------------------


def _as_number(v: Any) -> Decimal | int | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, Decimal):
        return v if v.is_finite() else None
    if isinstance(v, float):
        d = Decimal(repr(v))
        return d if d.is_finite() else None
    if isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v.strip()):
        return Decimal(v.strip())
    return None


def allowed_numbers(*sources: Any) -> dict[str, Decimal | int]:
    """Flatten tool outputs into `{path: number}` (the entry's `numbers`, R18).

    Accepts pydantic models, dicts, lists and plain numbers. Strings count only when they are
    plain decimals ("1240.00"); ids, tickers and dates are skipped.
    """
    out: dict[str, Decimal | int] = {}

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, BaseModel):
            obj = obj.model_dump(mode="python")
        if isinstance(obj, Mapping):
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else str(k))
            return
        if isinstance(obj, (builtins.list, tuple)):
            for i, v in enumerate(obj):
                walk(v, f"{path}.{i}" if path else str(i))
            return
        n = _as_number(obj)
        if n is not None:
            key = path or "n"
            while key in out and out[key] != n:
                key += "_"
            out[key] = n

    for i, src in enumerate(sources):
        walk(src, "" if len(sources) == 1 else f"s{i}")
    return out


def _values(allowed: Any) -> builtins.list[Decimal]:
    if isinstance(allowed, Mapping) or isinstance(allowed, BaseModel):
        nums = allowed_numbers(allowed).values()
    else:
        nums = [_as_number(a) for a in allowed]
    return [abs(Decimal(n)) for n in nums if n is not None]


# --- Validator ----------------------------------------------------------------


def _exempt(s: str, start: int, end: int) -> bool:
    """Digits that belong to a ticker, id, date, year, ordinal or compound word."""
    before = s[start - 1] if start > 0 else " "
    before2 = s[start - 2] if start > 1 else " "
    after = s[end] if end < len(s) else " "
    after2 = s[end + 1] if end + 1 < len(s) else " "
    if before.isalnum() or before == "_" or before in "/:#":
        return True
    if before == "-" and (before2.isalnum() or before2 == "_"):
        return True  # KXHIGHNY-26OCT25, 2026-10-28
    if after.isalpha() or after == "_":
        return True  # 26OCT, 1st, 12h
    if after in "-/:" and (after2.isalnum()):
        return True  # 12-call, 2026-10, 10/28, 15:00
    if _MONTH_BEFORE.search(s[:start]):
        return True  # Oct 28, Saturday 26
    return False


def _sig_digits(num: str) -> int:
    digits = num.replace(",", "").replace(".", "").lstrip("0")
    return len(digits)


def _matches(value: Decimal, places: int, sig: int, kind: str, allowed: builtins.list[Decimal]) -> bool:
    q = Decimal(1).scaleb(-places)
    for a in allowed:
        if kind in ("pct", "cents"):
            cands = (a * 100, a)
        elif kind == "usd":
            cands = (a,)
        else:
            cands = (a, a * 100)
        for c in cands:
            if c == value:
                return True
            if sig >= 2 and c.quantize(q, rounding=ROUND_HALF_UP) == value:
                return True
    return False


def _scan(summary: str) -> builtins.list[tuple[int, int, str, Decimal, int, int, str]]:
    found = []
    for m in _TOKEN.finditer(summary):
        num = m.group("num")
        pre = (m.group("pre") or "").replace(" ", "")
        post = (m.group("post") or "").strip().lower()
        if not pre and _exempt(summary, m.start("num"), m.end("num")):
            continue
        if not pre and not post and re.fullmatch(r"(19|20)\d{2}", num):
            continue  # a year
        kind = "usd" if "$" in pre else "pct" if post in ("%", "percent") else "cents" if post else "bare"
        try:
            value = Decimal(num.replace(",", ""))
        except InvalidOperation:
            continue
        places = len(num.split(".")[1]) if "." in num else 0
        token = summary[m.start():m.end()].strip()
        found.append((m.start(), m.end(), token, value, places, _sig_digits(num), kind))
    return found


def validate_summary(summary: str | None, allowed: Any) -> builtins.list[str]:
    """Figure tokens in `summary` that no allowed number supports (empty list = passes I2)."""
    if not summary:
        return []
    vals = _values(allowed)
    return [tok for _, _, tok, v, places, sig, kind in _scan(summary) if not _matches(v, places, sig, kind, vals)]


def sanitize(summary: str, allowed: Any) -> tuple[str, builtins.list[str]]:
    """Replace unsupported figure tokens with "[unverified]"; returns (text, offending)."""
    vals = _values(allowed)
    out, last, bad = [], 0, []
    for start, end, tok, v, places, sig, kind in _scan(summary):
        if not _matches(v, places, sig, kind, vals):
            out.append(summary[last:start])
            out.append(UNVERIFIED + (" " if summary[start:end].endswith(" ") else ""))
            last = end
            bad.append(tok)
    out.append(summary[last:])
    return "".join(out), bad


# --- Append-only storage ------------------------------------------------------

_GUARDED: set[int] = set()

_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS log_no_update BEFORE UPDATE ON log "
    "BEGIN SELECT RAISE(ABORT, 'decision log is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS log_no_delete BEFORE DELETE ON log "
    "BEGIN SELECT RAISE(ABORT, 'decision log is append-only'); END",
)


def install_guards(engine: Engine | None = None) -> None:
    """SQLite triggers that forbid UPDATE/DELETE on the log table (G12). Idempotent."""
    eng = engine or db.get_engine()
    if id(eng) in _GUARDED:
        return
    db.create_schema(eng)
    if eng.dialect.name == "sqlite":
        with eng.begin() as conn:
            for stmt in _TRIGGERS:
                conn.execute(text(stmt))
    _GUARDED.add(id(eng))


def new_log_id() -> str:
    return "log_" + uuid.uuid4().hex[:12]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def append(entry: LogEntry | Mapping[str, Any], engine: Engine | None = None) -> str:
    """Validate I2 and append. Returns the log_id. Never updates or deletes."""
    if not isinstance(entry, LogEntry):
        data = dict(entry)
        data.setdefault("log_id", new_log_id())
        data.setdefault("created_at", utcnow())
        entry = LogEntry.model_validate(data)
    offending = validate_summary(entry.summary, entry.numbers)
    if offending:
        raise UnsupportedNumbers(offending)
    install_guards(engine)
    db.append_log(entry, engine)
    return entry.log_id


def list_entries(
    business_id: str, limit: int | None = None, hedge_id: str | None = None, engine: Engine | None = None
) -> builtins.list[LogEntry]:
    """Entries for a business, newest first."""
    rows = db.list_log(business_id, hedge_id=hedge_id, engine=engine)[::-1]
    return rows[:limit] if limit is not None else rows


list = list_entries  # noqa: A001  (spec API name: log.list)

__all__ = [
    "UnsupportedNumbers", "allowed_numbers", "append", "install_guards", "list", "list_entries",
    "new_log_id", "sanitize", "validate_summary",
]
