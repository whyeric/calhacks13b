"""Regenerate fixtures/kalshi_series_catalog.json: which Kalshi contract settles each research event.

    cd backend && .venv/bin/python -m scripts.fetch_series_catalog            # network, read-only
    cd backend && .venv/bin/python -m scripts.fetch_series_catalog --dry-run  # print, don't write

Every catalog event in the research engine (contract section B) maps to the Kalshi series that would
settle it, or to null plus a reason. This script checks each mapping against the live public API
(https://api.elections.kalshi.com/trade-api/v2: /series, /events, /markets, /historical/markets).
The hand-written part is the SPECS below: which series, which market filter, the strike, the basis
note. The fetched part is what the API says now: series title, frequency, settlement sources,
contract terms URL, the rule text of the latest relevant market, strike types, open markets, settled
volume, first/last listed dates, and the measured lead between a market opening and the day it
covers. For KXHIGHNY the script also counts, over every settled day it can reach, how often the
exact strike (> K, or < K for cold) was listed. That ladder is recentred on the forecast every day.

The JSON is only ever read offline. tests/markets/test_series_catalog.py validates its schema and
never touches the network.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

BASE = "https://api.elections.kalshi.com/trade-api/v2"
OUT = Path(__file__).resolve().parents[1] / "fixtures" / "kalshi_series_catalog.json"
THROTTLE_S = 0.08
MAX_PAGES = 40  # per endpoint per series; KXRAIN lists ~50 cities a day
RECENT_EVENTS = 30  # settled events used for typical volume
NY, CT = ZoneInfo("America/New_York"), ZoneInfo("America/Chicago")
MONTHS = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}

# ---------------------------------------------------------------------------------------------
# Hand-written mapping. `instruments[].filter` is a substring the market ticker must contain.
# `role`: primary = the contract to buy; alternative = settles a related outcome; legacy = retired,
# kept for history/backtests. `strike` documents which markets of the series match the event.
# ---------------------------------------------------------------------------------------------

_WX_NYC_TWC = "The Weather Company (weather.com/kalshi), station CLINYC = NYC Central Park"
_HIGH_RULE = ("strict: YES iff the daily max at CLINYC is > K °F (integer readings, so > K means >= K+1). "
              "Lower tail is strict < K. Brackets 'B{x}.5' are inclusive two-degree ranges")

SPECS: list[dict] = [
    {
        "id": "rain", "aliases": ["rain_001"], "family": "weather",
        "label": "Rain day, 0.01 in or more at Central Park",
        "event_definition": "Central Park daily precipitation >= 0.01 in",
        "instruments": [
            {"series": "KXRAIN", "role": "primary", "filter": "-NYC", "strike": "> 0 in"},
            {"series": "KXRAINNYC", "role": "legacy", "filter": "", "strike": "> 0 in (T0)"},
            {"series": "KXRAINNYCM", "role": "alternative", "filter": "", "strike": "monthly total > X in"},
        ],
        "settlement_station": _WX_NYC_TWC,
        "strike_semantics": "strict > 0 in; trace (T) and missing count as 0, so YES iff >= 0.01 in",
        "cadence": "daily",
        "buy_ahead": "One day only. Each date's market lists at ~05:10 ET the day before (about 19 h before "
                     "midnight). There is no way to buy a given day's rain weeks out; KXRAINNYCM (monthly total, "
                     "NWS CLI) lists about 4-5 days before the month.",
        "basis_note": "Exact for the >= 0.01 in flag, but the series and source changed: KXRAINNYC (2021-09 to "
                      "2026-07-15) settled on NWS CLI Central Park and counted Trace as YES; KXRAIN-*-NYC (from "
                      "2026-07-15) settles on The Weather Company's CLINYC value and counts Trace as 0. Use KXRAIN.",
    },
    {
        "id": "rain_5mm", "aliases": [], "family": "weather",
        "label": "Heavy rain day, 5 mm (0.20 in) or more",
        "event_definition": "Central Park daily precipitation >= 0.197 in",
        "instruments": [
            {"series": "KXRAINNYCM", "role": "alternative", "filter": "", "strike": "monthly total > X in, X=1..10"},
        ],
        "null_reason": "no_contract: no daily NYC rain contract lists a strike above 0 in. KXRAIN-*-NYC is a single "
                       "> 0 market per day; the only NYC amount ladder is monthly (KXRAINNYCM).",
        "settlement_station": "none daily; KXRAINNYCM settles on NWS CLI Central Park monthly total",
        "strike_semantics": "n/a (no daily strike)",
        "cadence": "daily event; nearest contract monthly",
        "buy_ahead": "n/a",
        "basis_note": "Untestable as a hedge. A monthly-total contract only loosely tracks heavy-rain days.",
    },
    *[
        {
            "id": f"hot_{k}", "aliases": [], "family": "weather",
            "label": f"Hot day, high above {k}°F",
            "event_definition": f"Central Park daily max > {k} °F",
            "instruments": [
                {"series": "KXHIGHNY", "role": "primary", "filter": "", "strike": f"> {k}", "threshold": k,
                 "direction": "above"},
            ],
            "settlement_station": _WX_NYC_TWC,
            "strike_semantics": _HIGH_RULE,
            "cadence": "daily",
            "buy_ahead": "One day only. Each date lists at 10:00 ET the day before with 6 strikes centred on the "
                         f"forecast, so an exact > {k} strike exists only when {k} falls on that day's ladder.",
            "basis_note": "Same station as the flag (Central Park). Settled on NWS CLI until 2026-08-13 and on "
                          "The Weather Company from 2026-08-14. The exact strike is listed on only a minority of "
                          "event days (see strike_availability); otherwise the nearest edge is 1-2 °F off.",
        }
        for k in (80, 85, 90)
    ],
    {
        "id": "cold_40", "aliases": [], "family": "weather",
        "label": "Cold day, high below 40°F",
        "event_definition": "Central Park daily max < 40 °F",
        "instruments": [
            {"series": "KXHIGHNY", "role": "primary", "filter": "", "strike": "< 40", "threshold": 40,
             "direction": "below"},
        ],
        "settlement_station": _WX_NYC_TWC,
        "strike_semantics": _HIGH_RULE + "; 'tmax < 40' is the lower-tail 'T40' market or the NO side of '> 39'",
        "cadence": "daily",
        "buy_ahead": "One day only, 10:00 ET the day before. The lower strikes follow the forecast, so a < 40 "
                     "strike is listed only on cold-forecast days.",
        "basis_note": "Same series as hot. Exact on days the 39/40 boundary is on the ladder.",
    },
    {
        "id": "snow", "aliases": ["snow_01"], "family": "weather",
        "label": "Snow day, 0.1 in or more",
        "event_definition": "Central Park daily snowfall >= 0.1 in",
        "instruments": [
            {"series": "KXSNOWSTORM", "role": "primary", "filter": "NYC", "strike": "storm-window total > X in"},
            {"series": "KXNYCSNOWM", "role": "alternative", "filter": "", "strike": "monthly total > X in"},
            {"series": "KXSNOWNYM", "role": "legacy", "filter": "", "strike": "monthly total > X in"},
            {"series": "KXSNOWNY", "role": "legacy", "filter": "", "strike": "daily > 0 in"},
        ],
        "settlement_station": "KXSNOWSTORM: NWS Daily Climate Report CLI NYC (Central Park); "
                              "KXNYCSNOWM: NWS CLI for Dec 2025-Mar 2026, The Weather Company 'NYC' from Dec 2026",
        "strike_semantics": "strict > X inches over the storm window (KXSNOWSTORM) or calendar month (KXNYCSNOWM)",
        "cadence": "event-driven (KXSNOWSTORM, listed once a storm is forecast); monthly (KXNYCSNOWM)",
        "buy_ahead": "Not as a standing hedge. KXSNOWSTORM lists only once a storm is forecast, about a day before "
                     "the window. KXNYCSNOWM lists days to ~2 months before the month (Dec 2026 opened "
                     "2026-10-02) but settles on a monthly total. "
                     "No daily snow contract has listed since KXSNOWNY in Feb 2022.",
        "basis_note": "Weak for a per-day flag: the storm contract covers a multi-day window and the lowest strike "
                      "is ~2 in, not 0.1 in.",
    },
    {
        "id": "home_game", "aliases": [], "family": "sports",
        "label": "Home game night at MSG (Knicks or Rangers)",
        "event_definition": "Knicks or Rangers regular-season or playoff home game that day",
        "instruments": [],
        "null_reason": "no_contract: the regular-season schedule is fixed in advance, so there is nothing to settle. "
                       "Informational only.",
        "settlement_station": "n/a",
        "strike_semantics": "n/a",
        "cadence": "season (schedule published in summer)",
        "buy_ahead": "n/a",
        "basis_note": "Known risk, not hedgeable; plan it in the budget.",
    },
    {
        "id": "home_win", "aliases": [], "family": "sports",
        "label": "Home team wins at MSG",
        "event_definition": "Knicks or Rangers win a home game",
        "instruments": [
            {"series": "KXNBAGAME", "role": "primary", "filter": "NYK", "strike": "team wins (YES on -NYK)",
             "team": "NYK", "home_only": True},
            {"series": "KXNHLGAME", "role": "primary", "filter": "NYR", "strike": "team wins (YES on -NYR)",
             "team": "NYR", "home_only": True},
        ],
        "settlement_station": "Governing league (NBA.com / NHL.com) and ESPN final score",
        "strike_semantics": "binary: YES iff the named team wins the game 'originally scheduled for' that date "
                            "(NHL includes OT/shootout)",
        "cadence": "per game",
        "buy_ahead": "Days, not weeks. In the 2026-27 season games list ~5 days (NBA) / ~3 days (NHL) before the "
                     "game date; earlier seasons were ~1.5-2 days. Trades to the final.",
        "basis_note": "Exact: the contract is the outcome. Event code puts the home team second ({AWAY}{HOME}).",
    },
    {
        "id": "playoff_home", "aliases": [], "family": "sports",
        "label": "Playoff home game at MSG",
        "event_definition": "Knicks or Rangers host a playoff game that day",
        "instruments": [
            {"series": "KXNBAPLAYOFF", "role": "primary", "filter": "NYK", "strike": "team makes playoffs"},
            {"series": "KXNHLPLAYOFF", "role": "primary", "filter": "NYR", "strike": "team makes playoffs"},
            {"series": "KXNBASERIES", "role": "primary", "filter": "NYK", "strike": "team wins the series"},
            {"series": "KXNHLSERIES", "role": "primary", "filter": "NYR", "strike": "team wins the series"},
            {"series": "KXNBASERIESGAMES", "role": "alternative", "filter": "NYK", "strike": "> g-0.5 games played"},
            {"series": "KXNHLSERIESGAMES", "role": "alternative", "filter": "NYR", "strike": "> g-0.5 games played"},
        ],
        "settlement_station": "Governing league (NBA.com / NHL.com), ESPN, Fox Sports",
        "strike_semantics": "binary qualify / series winner; series-length ladder 'above g-0.5 games' (>= g)",
        "cadence": "season (KX*PLAYOFF) and per playoff series (KX*SERIES, KX*SERIESGAMES)",
        "buy_ahead": "Yes, well ahead. KXNBAPLAYOFF lists right after the prior Finals (2026-27 opened 2026-06-15), "
                     "KXNHLPLAYOFF in August (2026-08-18). Series markets list only 1-5 days before game 1 "
                     "(median 1.5 NBA, 2 NHL; see series_lead_days).",
        "basis_note": "Playoff home games are a deterministic function of making the playoffs, advancing and "
                      "series length. Winner contracts hedge later rounds; the length ladder hedges this round's "
                      "home games 5-7 (thin in the NHL).",
    },
    {
        "id": "away_playoff", "aliases": [], "family": "sports",
        "label": "Away playoff night (watch-party night)",
        "event_definition": "Knicks or Rangers play a playoff game away",
        "instruments": [
            {"series": "KXNBASERIES", "role": "primary", "filter": "NYK", "strike": "team wins the series"},
            {"series": "KXNHLSERIES", "role": "primary", "filter": "NYR", "strike": "team wins the series"},
            {"series": "KXNBASERIESGAMES", "role": "alternative", "filter": "NYK", "strike": "> g-0.5 games played"},
            {"series": "KXNHLSERIESGAMES", "role": "alternative", "filter": "NYR", "strike": "> g-0.5 games played"},
        ],
        "settlement_station": "Governing league, ESPN",
        "strike_semantics": "series winner (binary); series-length ladder 'above g-0.5 games'",
        "cadence": "per playoff series",
        "buy_ahead": "1-5 days before game 1 of each series, once the matchup is set (median 1.5 NBA, 2 NHL).",
        "basis_note": "Indirect. The away-game count in a series is fixed by its length and home court, so the "
                      "length ladder is the closer fit; the winner contract only covers later rounds.",
    },
    {
        "id": "weekend_rain", "aliases": [], "family": "calendar",
        "label": "Rain on a weekend day",
        "event_definition": "Saturday or Sunday with Central Park precipitation >= 0.01 in",
        "instruments": [
            {"series": "KXRAIN", "role": "alternative", "filter": "-NYC", "strike": "> 0 in, bought only for Sat/Sun"},
        ],
        "null_reason": "no_contract: there is no weekend-rain contract. The interaction can only be approximated by "
                       "buying KXRAIN-<date>-NYC on Saturdays and Sundays, each one day ahead.",
        "settlement_station": _WX_NYC_TWC + " (via the daily KXRAIN market)",
        "strike_semantics": "strict > 0 in on each weekend date",
        "cadence": "daily (weekend dates only)",
        "buy_ahead": "Friday morning for Saturday, Saturday morning for Sunday.",
        "basis_note": "The weekday-only part of the effect is not tradeable separately.",
    },
    {
        "id": "dc_shutdown", "aliases": [], "family": "calendar",
        "label": "Federal government shutdown (downtown DC)",
        "event_definition": "Federal government at least partially shut down on a date / for N days",
        "instruments": [
            {"series": "KXGOVTSHUTDOWN", "role": "primary", "filter": "", "strike": "shut down at 10:00 ET on date"},
            {"series": "KXGOVTSHUTLENGTH", "role": "alternative", "filter": "", "strike": "lasts >= N days"},
            {"series": "KXGOVSHUT", "role": "legacy", "filter": "", "strike": "OPM shutdown notice by date"},
            {"series": "KXGOVSHUTLENGTH", "role": "legacy", "filter": "", "strike": "days of shutdown"},
        ],
        "settlement_station": "OMB and OPM operating status (opm.gov current status)",
        "strike_semantics": "binary: 'at least partially shut down due to a lapse of appropriations at 10:00 AM ET'; "
                            "length ladder is >= N days",
        "cadence": "event-driven (one market per funding deadline)",
        "buy_ahead": "Yes, weeks to months ahead: each deadline market lists 1 week to ~4 months before the "
                     "deadline (KXGOVTSHUTDOWN-26DEC12 opened 2026-09-22).",
        "basis_note": "The event is the settlement (r8-dcshutdown). Caveat: a partial (e.g. DHS-only) lapse settles "
                      "YES with little downtown effect.",
    },
    *[
        {
            "id": f"tx_heat_{city}", "aliases": [], "family": "weather",
            "label": f"Texas heat, {name} high above 95°F",
            "event_definition": f"{name} daily max > 95 °F (also > 100 °F)",
            "instruments": [
                {"series": series, "role": "primary", "filter": "", "strike": "> 95", "threshold": 95,
                 "direction": "above"},
            ],
            "settlement_station": f"The Weather Company (weather.com/kalshi), station {station}",
            "strike_semantics": "strict: YES iff the daily max is > K °F; 6 strikes per day centred on the forecast",
            "cadence": "daily",
            "buy_ahead": "One day only: lists at 09:00 CT the day before.",
            "basis_note": "NWS CLI until 2026-08-13, The Weather Company from 2026-08-14; GHCN TMAX at the same "
                          "station reproduced 100% of settled markets 2026-08-17..10-20 (r4-ercot). The day-ahead "
                          "price reflects the forecast, so it hedges forecast error only.",
        }
        for city, name, series, station in [
            ("austin", "Austin", "KXHIGHAUS", "CLIAUS (Austin-Bergstrom)"),
            ("houston", "Houston", "KXHIGHTHOU", "CLIHOU (Houston Hobby)"),
            ("dallas", "Dallas", "KXHIGHTDAL", "CLIDFW (DFW Airport)"),
            ("san_antonio", "San Antonio", "KXHIGHTSATX", "CLISAT (San Antonio Intl)"),
        ]
    ],
    {
        "id": "gas_price", "aliases": [], "family": "calendar",
        "label": "US gas price (AAA national average)",
        "event_definition": "AAA US average regular gas price above $X on a date",
        "instruments": [
            {"series": "KXAAAGASM", "role": "primary", "filter": "", "strike": "> $X at month end"},
            {"series": "KXAAAGASW", "role": "alternative", "filter": "", "strike": "> $X on Monday"},
            {"series": "KXAAAGASD", "role": "alternative", "filter": "", "strike": "> $X daily"},
        ],
        "settlement_station": "AAA national average regular (gasprices.aaa.com)",
        "strike_semantics": "strict: 'strictly greater than $X'; ladders $0.01-0.10 apart",
        "cadence": "monthly (KXAAAGASM), weekly (KXAAAGASW), daily (KXAAAGASD)",
        "buy_ahead": "Yes: monthly lists ~1 month ahead, weekly ~1 week ahead.",
        "basis_note": "National price; local price basis R^2 ~0.6-0.9 monthly (r6-gas). Hedges a fuel bill, "
                      "not demand (sign unstable).",
    },
]

# ---------------------------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------------------------


class Api:
    def __init__(self) -> None:
        self.c = httpx.Client(base_url=BASE, timeout=30, headers={"User-Agent": "hedge-desk-catalog"})

    def get(self, path: str, **params) -> dict:
        for attempt in range(5):
            r = self.c.get(path, params=params)
            time.sleep(THROTTLE_S)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code == 404:
                return {}
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return {}

    def paged(self, path: str, key: str, **params) -> list[dict]:
        out, cursor = [], None
        for _ in range(MAX_PAGES):
            d = self.get(path, limit=1000 if key == "markets" else 200, **params, **({"cursor": cursor} if cursor else {}))
            out += d.get(key, [])
            cursor = d.get("cursor")
            if not cursor or not d.get(key):
                break
        return out


def _ts(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _event_date(event_ticker: str) -> date | None:
    """`KXHIGHNY-26OCT25` / `KXNBAGAME-26OCT24GSWPHX` -> 2026-10-25. None if no YYMONDD code."""
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", event_ticker)
    if not m or m.group(2) not in MONTHS:
        return None
    return date(2000 + int(m.group(1)), MONTHS[m.group(2)], int(m.group(3)))


_RULE_DATE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? (\d{1,2}), (\d{4})")


def _covered_date(m: dict) -> date | None:
    """First day the market covers: YYMONDD in the event ticker, else the first date in the rule text
    (storm windows), else YYMON in the ticker (monthly series -> the 1st)."""
    d = _event_date(m["event_ticker"])
    if d:
        return d
    r = _RULE_DATE.search(m.get("rules_primary") or "")
    if r:
        return date(int(r.group(3)), MONTHS[r.group(1).upper()], int(r.group(2)))
    y = re.search(r"-(\d{2})([A-Z]{3})(?![A-Z0-9])", m["event_ticker"])
    if y and y.group(2) in MONTHS:
        return date(2000 + int(y.group(1)), MONTHS[y.group(2)], 1)
    return None


_SOURCES = [
    ("The Weather Company", ("Weather Company", "weather.com")),
    ("NWS Climatological Report (CLI)", ("Climatological Report", "Daily Climate Report", "National Weather Service")),
    ("NOAA", ("National Oceanic", "NOAA")),
    ("AAA", ("AAA",)),
    ("OPM/OMB", ("Office of Personnel Management", "lapse of appropriations", "lapse in appropriations")),
]


def _rule_source(m: dict) -> str | None:
    text = (m.get("rules_primary") or "") + " " + (m.get("rules_secondary") or "")
    for name, keys in _SOURCES:
        if any(k in text for k in keys):
            return name
    return None


def source_history(markets: list[dict]) -> list[dict]:
    """Which data source the rule text names, by covered date. Catches mid-life settlement switches."""
    spans: dict[str, list[date]] = {}
    for m in markets:
        src, d = _rule_source(m), _covered_date(m)
        if src and d:
            spans.setdefault(src, []).append(d)
    return sorted(({"source": k, "first": _iso(min(v)), "last": _iso(max(v)), "n_markets": len(v)}
                   for k, v in spans.items()), key=lambda r: r["first"])


def _iso(d) -> str | None:
    return None if d is None else d.isoformat()


def _round(x: float | None, n: int = 1):
    return None if x is None else round(x, n)


def fetch_series(api: Api, series: str, filt: str) -> dict:
    """Everything the catalog records about one series, restricted to markets whose ticker has `filt`."""
    meta = api.get(f"/series/{series}").get("series") or {}
    if not meta:
        return {"series": series, "exists": False}
    keep = (lambda m: filt in m["ticker"]) if filt else (lambda m: True)
    open_m = [m for m in api.paged("/markets", "markets", series_ticker=series, status="open") if keep(m)]
    settled = [m for m in api.paged("/markets", "markets", series_ticker=series, status="settled") if keep(m)]
    hist = [m for m in api.paged("/historical/markets", "markets", series_ticker=series) if keep(m)]
    seen, allm = set(), []
    for m in open_m + settled + hist:
        if m["ticker"] not in seen:
            seen.add(m["ticker"])
            allm.append(m)
    done = [m for m in allm if m.get("result") in ("yes", "no")]
    latest = max(allm, key=lambda m: m.get("open_time") or "", default=None)

    by_event: dict[str, list[dict]] = defaultdict(list)
    for m in done:
        by_event[m["event_ticker"]].append(m)
    recent = sorted(by_event, key=lambda e: max(x.get("close_time") or "" for x in by_event[e]))[-RECENT_EVENTS:]
    ev_vol = [sum(_num(x.get("volume_fp", x.get("volume"))) for x in by_event[e]) for e in recent]
    mk_vol = [_num(x.get("volume_fp", x.get("volume"))) for e in recent for x in by_event[e]]

    tz = CT if series in ("KXHIGHAUS", "KXHIGHTHOU", "KXHIGHTDAL", "KXHIGHTSATX") else NY
    lead_by_event: dict[str, tuple[date, float]] = {}
    for m in allm:
        d, ot = _covered_date(m), _ts(m.get("open_time"))
        if d and ot:
            h = (datetime(d.year, d.month, d.day, tzinfo=tz) - ot).total_seconds() / 3600
            prev = lead_by_event.get(m["event_ticker"])
            lead_by_event[m["event_ticker"]] = (d, max(h, prev[1]) if prev else h)  # earliest listing per event
    leads = [h for _, h in lead_by_event.values()]
    recent_leads = [h for _, h in sorted(lead_by_event.values())[-RECENT_EVENTS:]]
    dates = [_ts(m.get("close_time")) for m in allm if m.get("close_time")]
    opens = [_ts(m.get("open_time")) for m in allm if m.get("open_time")]
    now_opens = [_ts(m.get("open_time")) for m in open_m if m.get("open_time")]
    spreads = [
        _num(m.get("yes_ask_dollars")) - _num(m.get("yes_bid_dollars")) for m in open_m
        if _num(m.get("yes_bid_dollars")) > 0 and _num(m.get("yes_ask_dollars")) < 1
    ]
    return {
        "series": series,
        "exists": True,
        "title": meta.get("title"),
        "api_frequency": meta.get("frequency"),
        "category": meta.get("category"),
        "settlement_sources": [{"name": s.get("name"), "url": s.get("url")} for s in meta.get("settlement_sources") or []],
        "contract_url": meta.get("contract_url"),
        "rules_primary": (latest or {}).get("rules_primary"),
        "rules_secondary": ((latest or {}).get("rules_secondary") or "")[:600] or None,
        "latest_market": (latest or {}).get("ticker"),
        "strike_types": sorted({m.get("strike_type") for m in allm if m.get("strike_type")}),
        "open_now": bool(open_m),
        "n_open_markets": len(open_m),
        "open_markets_sample": sorted(m["ticker"] for m in open_m)[:6],
        "open_median_spread_usd": _round(statistics.median(spreads), 3) if spreads else None,
        "n_settled_markets_seen": len(done),
        "n_settled_events_seen": len(by_event),
        "first_open": _iso(min(opens).date()) if opens else None,
        "open_markets_listed_since": _iso(min(now_opens).date()) if now_opens else None,
        "first_close": _iso(min(dates).date()) if dates else None,
        "last_close": _iso(max(dates).date()) if dates else None,
        "recent_settled_events": len(recent),
        "median_volume_per_event": _round(statistics.median(ev_vol)) if ev_vol else None,
        "median_volume_per_market": _round(statistics.median(mk_vol)) if mk_vol else None,
        "median_lead_hours": _round(statistics.median(leads)) if leads else None,
        "median_lead_hours_recent": _round(statistics.median(recent_leads)) if recent_leads else None,
        "lead_hours_range": [_round(min(leads)), _round(max(leads))] if leads else None,
        "open_volume_total": _round(sum(_num(m.get("volume_fp")) for m in open_m)),
        "open_interest_total": _round(sum(_num(m.get("open_interest_fp")) for m in open_m)),
        "rule_source_history": source_history(allm),
        "_markets": allm,  # dropped before writing
    }


def strike_availability(markets: list[dict], k: int, direction: str) -> dict:
    """Over settled KXHIGH* days: how often could you buy exactly 'tmax > k' (or 'tmax < k')?

    The boundary between k and k+1 (above) or k-1 and k (below) must be an edge of some listed market.
    Edges: 'greater' floor f -> f/f+1; 'less' cap c -> c-1/c; 'between' [a,b] -> a-1/a and b/b+1.
    """
    lo = k if direction == "above" else k - 1  # the edge is lo/lo+1
    days: dict[str, dict] = {}
    for m in markets:
        if m.get("result") not in ("yes", "no"):
            continue
        e = days.setdefault(m["event_ticker"], {"edges": set(), "tmax": None})
        st, f, c = m.get("strike_type"), m.get("floor_strike"), m.get("cap_strike")
        if st == "greater" and f is not None:
            e["edges"].add(int(f))
        elif st == "less" and c is not None:
            e["edges"].add(int(c) - 1)
        elif st == "between" and f is not None and c is not None:
            e["edges"].update({int(f) - 1, int(c)})
        try:
            e["tmax"] = float(m.get("expiration_value"))
        except (TypeError, ValueError):
            pass
    n = len(days)
    avail = [d for d in days.values() if lo in d["edges"]]
    hit = [d for d in days.values() if d["tmax"] is not None and (d["tmax"] > k if direction == "above" else d["tmax"] < k)]
    hit_avail = [d for d in hit if lo in d["edges"]]
    near = [d for d in hit if d["edges"] & {lo - 1, lo, lo + 1}]
    dts = [_event_date(t) for t in days]
    dts = [d for d in dts if d]
    return {
        "condition": f"tmax {'>' if direction == 'above' else '<'} {k}",
        "days_checked": n,
        "window": [_iso(min(dts)), _iso(max(dts))] if dts else None,
        "days_exact_strike_listed": len(avail),
        "share_exact_strike_listed": _round(len(avail) / n, 3) if n else None,
        "event_days": len(hit),
        "event_days_with_exact_strike": len(hit_avail),
        "event_days_with_strike_within_1F": len(near),
    }


def series_lead_days(api: Api, series_markets: list[dict], game_series: str, team: str) -> dict:
    """Days from each playoff-series market opening to its game 1 (game dates from the game series' events).
    Summary over every series in the league, plus the rows for `team`."""
    games = api.paged("/events", "events", series_ticker=game_series)
    out, seen = [], set()
    for m in sorted(series_markets, key=lambda m: m.get("open_time") or ""):
        ev = m["event_ticker"]
        if ev in seen:
            continue
        seen.add(ev)
        # 26ATLNYKR1 / 25DETNYK / 26VGKCARFIN -> the two team codes concatenated (codes are 2-3 letters)
        body = re.sub(r"(R\d|ECF|WCF|CF|SCF|FIN|F)$", "", ev.split("-", 1)[1][2:])
        ot = _ts(m.get("open_time"))
        cands = []
        for g in games:
            d = _event_date(g["event_ticker"])
            gcode = g["event_ticker"].split("-", 1)[1][7:]  # GSWPHX / LANYR
            swaps = {gcode[i:] + gcode[:i] for i in (2, 3, 4) if 2 <= i <= len(gcode) - 2}
            if d and ot and (body == gcode or body in swaps) and 0 <= (d - ot.date()).days <= 14:
                cands.append(d)
        g1 = min(cands) if cands else None
        out.append({"event": ev, "market_open": _iso(ot.date()) if ot else None, "game1": _iso(g1),
                    "lead_days": (g1 - ot.date()).days if g1 and ot else None})
    lead = [r["lead_days"] for r in out if r["lead_days"] is not None]
    return {
        "n_series": len(out), "n_with_game1": len(lead),
        "median": statistics.median(lead) if lead else None,
        "range": [min(lead), max(lead)] if lead else None,
        "team": team, "team_series": sorted((r for r in out if team in r["event"]), key=lambda r: r["event"]),
    }


def build(api: Api) -> dict:
    cache: dict[tuple[str, str], dict] = {}
    entries = []
    for spec in SPECS:
        insts = []
        for inst in spec["instruments"]:
            key = (inst["series"], inst["filter"])
            if key not in cache:
                print(f"  fetching {inst['series']} filter={inst['filter']!r}")
                cache[key] = fetch_series(api, *key)
            info = {k: v for k, v in cache[key].items() if k != "_markets"}
            rec = {**inst, **info}
            mk = cache[key].get("_markets", [])
            if "threshold" in inst:
                rec["strike_availability"] = strike_availability(mk, inst["threshold"], inst["direction"])
            if inst.get("home_only"):
                home = [m for m in mk if m["event_ticker"].endswith(inst["team"])]
                vols = [_num(m.get("volume_fp")) for m in home if m.get("result") in ("yes", "no")
                        and m["ticker"].endswith(inst["team"])]
                rec["home_games_seen"] = len({m["event_ticker"] for m in home})
                rec["median_volume_home_team_market"] = _round(statistics.median(vols[-RECENT_EVENTS:])) if vols else None
            wkey = (inst["series"], "")
            if inst["filter"] and not mk:
                if wkey not in cache:
                    print(f"  fetching {inst['series']} series-wide (filter matched nothing)")
                    cache[wkey] = fetch_series(api, *wkey)
                rec["filter_matched_nothing"] = True
                rec["series_wide"] = {k: v for k, v in cache[wkey].items()
                                      if k not in ("_markets", "rules_secondary", "open_markets_sample")}
            if inst["series"] in ("KXNBASERIES", "KXNHLSERIES"):
                gs = "KXNBAGAME" if inst["series"] == "KXNBASERIES" else "KXNHLGAME"
                if wkey not in cache:
                    cache[wkey] = fetch_series(api, *wkey)
                rec["series_lead_days"] = series_lead_days(api, cache[wkey]["_markets"], gs, inst["filter"])
            insts.append(rec)
        primary = [i for i in insts if i["role"] == "primary" and i.get("exists")]
        entry = {k: v for k, v in spec.items() if k != "instruments"}
        entry["kalshi_series"] = [i["series"] for i in primary] or None
        entry["primary_title"] = primary[0]["title"] if primary else None
        entry["open_now"] = any(i.get("open_now") for i in primary)
        entry.setdefault("null_reason", None)
        entry["instruments"] = insts
        entries.append(entry)
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "api_base": BASE,
        "generator": "backend/scripts/fetch_series_catalog.py",
        "notes": [
            "Volumes are contracts ($1 notional). Typical volume = median over the most recent settled events seen.",
            "median_lead_hours = market open_time to local midnight starting the covered date (positive = before).",
            "/historical/markets holds markets settled before the archive cutoff (2026-08-25); /markets holds the rest.",
            "Settled history is capped at MAX_PAGES pages per endpoint, so first_close can be later than the true first listing for very large series (KXRAIN, KXNBAGAME).",
        ],
        "events": entries,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    out = build(Api())
    text = json.dumps(out, indent=1, ensure_ascii=False) + "\n"
    if args.dry_run:
        print(text[:4000])
        return
    OUT.write_text(text)
    print(f"wrote {OUT} ({len(out['events'])} events)")


if __name__ == "__main__":
    main()
