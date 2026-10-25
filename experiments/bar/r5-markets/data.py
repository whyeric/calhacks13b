"""Load the cached Kalshi markets/candles and ESPN games; build the realised series table."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import pandas as pd

from fetch_markets import CACHE

ET = timezone(timedelta(hours=-4))
# ESPN abbreviation -> Kalshi code.
ALIAS = {
    "nba": {"GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"},
    "nhl": {"LA": "LAK", "NJ": "NJD", "TB": "TBL", "SJ": "SJS", "UTAH": "UTA"},
    "mlb": {"CHW": "CWS", "ARI": "AZ"},
    "nfl": {"WSH": "WAS"},
}
EDGE = {"nba": 0.28, "nhl": 0.16, "mlb": 0.12, "nfl": 0.24}

# Kalshi series that price each round's winner, in priority order. Conference finals and
# finals are priced by the conference / league champion futures (only two teams remain).
WINNER_SERIES = {
    "nba": {"R1": ["KXNBASERIES"], "R2": ["KXNBASERIES"], "CF": ["KXNBAEAST", "KXNBAWEST"], "F": ["KXNBA"]},
    "nhl": {"R1": ["KXNHLSERIES"], "R2": ["KXNHLSERIES"], "CF": ["KXNHLEAST", "KXNHLWEST"], "F": ["KXNHL"]},
    "mlb": {"WC": ["KXMLBSERIES"], "DS": ["KXMLBSERIES"], "LCS": ["KXMLBSERIES", "KXMLBAL", "KXMLBNL"],
            "WS": ["KXMLBSERIES", "KXMLB"]},
}
GAMES_SERIES = {"nba": "KXNBASERIESGAMES", "nhl": "KXNHLSERIESGAMES", "mlb": "KXMLBSERIESGAMES"}
SCORE_SERIES = {"nba": ["KXNBASERIESSCORE", "KXNBAFINALSEXACT"], "nhl": ["KXNHLSERIESSCORE", "KXNHLFINALSEXACT"],
                "mlb": ["KXMLBSERIESSCORE", "KXMLBSERIESEXACT"]}
# Futures ladder: [conference/league champion, champion].
FUTURES = {"nba": (["KXNBAEAST", "KXNBAWEST"], "KXNBA"), "nhl": (["KXNHLEAST", "KXNHLWEST"], "KXNHL"),
           "mlb": (["KXMLBAL", "KXMLBNL"], "KXMLB")}
ROUNDS = {"nba": ["R1", "R2", "CF", "F"], "nhl": ["R1", "R2", "CF", "F"], "mlb": ["WC", "DS", "LCS", "WS"]}


def round_of(league: str, note: str) -> str:
    n = note.split(" - ")[0]
    if league in ("nba", "nhl"):
        if "1st Round" in n:
            return "R1"
        if "Semifinals" in n or "2nd Round" in n:
            return "R2"
        if n.startswith(("East Final", "West Final")):
            return "CF"
        return "F"
    for k in ("WC", "DS", "LCS"):
        if n.endswith(k):
            return k
    return "WS"


def fmt_of(league: str, rnd: str) -> str:
    if league in ("nba", "nhl"):
        return "2-2-1-1-1"
    return {"WC": "3-0", "DS": "2-2-1", "LCS": "2-3-2", "WS": "2-3-2"}[rnd]


@lru_cache(None)
def markets() -> dict:
    return json.loads((CACHE / "r5markets_markets.json").read_text())


def _norm_candle(c: dict) -> dict:
    """The live API suffixes fields with _fp / _dollars; the historical one does not."""
    out = {"end_period_ts": c["end_period_ts"],
           "open_interest": c.get("open_interest", c.get("open_interest_fp")),
           "volume": c.get("volume", c.get("volume_fp"))}
    for k in ("price", "yes_bid", "yes_ask"):
        out[k] = {kk.removesuffix("_dollars"): v for kk, v in (c.get(k) or {}).items()}
    return out


@lru_cache(None)
def candles() -> dict:
    raw = json.loads((CACHE / "r5markets_candles.json").read_text())
    return {t: [_norm_candle(c) for c in cs] for t, cs in raw.items()}


@lru_cache(None)
def market_index() -> dict[str, dict]:
    return {m["ticker"]: {**m, "_series": s} for s, b in markets().items() for m in b["markets"]}


def games() -> pd.DataFrame:
    g = pd.read_csv(CACHE / "r5markets_games.csv")
    g = g[~g.note.fillna("").str.contains("Play-In|Pro Bowl")].copy()
    for lg, al in ALIAS.items():
        m = g.league == lg
        g.loc[m, "home"] = g.loc[m, "home"].replace(al)
        g.loc[m, "away"] = g.loc[m, "away"].replace(al)
        g.loc[m, "winner"] = g.loc[m, "winner"].replace(al)
    g["season"] = g.date.str[:4].astype(int)
    g.loc[g.league == "nfl", "season"] = 2026  # Jan-Feb 2026 = the 2025-26 season ("-26" events)
    return g


def series_table() -> pd.DataFrame:
    """One row per series: home-court team `a`, other team `b`, length, winner, home games."""
    g = games()
    g = g[g.league.isin(["nba", "nhl", "mlb"])]
    rows = []
    for (lg, yr), gg in g.groupby(["league", "season"]):
        gg = gg.sort_values("date")
        keys = gg.apply(lambda r: frozenset((r.home, r.away)), axis=1)
        for key, s in gg.groupby(keys, sort=False):
            s = s.sort_values("date")
            rnd = round_of(lg, s.note.iloc[0])
            fmt = fmt_of(lg, rnd)
            from hedge import home_games, wins_needed
            a = s.home.iloc[0]
            b = next(iter(key - {a}))
            wa, wb = int((s.winner == a).sum()), int((s.winner == b).sum())
            need = wins_needed(fmt)
            done = max(wa, wb) == need
            n = wa + wb
            rows.append(dict(
                league=lg, season=yr, round=rnd, fmt=fmt, a=a, b=b, a_wins=wa, b_wins=wb, games=n,
                winner=(a if wa == need else b) if done else None, complete=done,
                a_home=home_games(fmt, n, True), b_home=home_games(fmt, n, False),
                a_home_obs=int((s.home == a).sum()), b_home_obs=int((s.home == b).sum()),
                game1=s.date.iloc[0], last=s.date.iloc[-1],
            ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- prices


def _f(x) -> float | None:
    return None if x in (None, "") else float(x)


def quote(ticker: str, cutoff: datetime) -> dict | None:
    """Last daily candle ending at or before `cutoff`: mid, ask, bid, last, volume so far."""
    cs = candles().get(ticker) or []
    ts = cutoff.timestamp()
    prior = [c for c in cs if c["end_period_ts"] <= ts]
    if not prior:
        return None
    c = prior[-1]
    bid, ask = _f(c.get("yes_bid", {}).get("close")), _f(c.get("yes_ask", {}).get("close"))
    last = _f(c.get("price", {}).get("close")) or _f(c.get("price", {}).get("previous"))
    if bid is None or ask is None or ask >= 0.999 or bid <= 0.0 or ask - bid > 0.2:
        if last is None:
            return None
        bid, ask = (bid if bid else max(last - 0.01, 0.0)), (ask if ask and ask < 0.999 else min(last + 0.01, 1.0))
    if bid > ask:  # crossed/stale book after settlement
        bid = ask = last if last is not None else 0.5 * (bid + ask)
    mid = 0.5 * (bid + ask)
    return dict(mid=mid, ask=ask, bid=bid, last=last, oi=_f(c.get("open_interest")),
                vol_cum=sum(_f(x["volume"]) or 0 for x in prior), date=datetime.fromtimestamp(c["end_period_ts"], ET))


def eve(day: str) -> datetime:
    """Midnight ET at the start of `day` (the daily candle that ends then covers the day before)."""
    return datetime.fromisoformat(day).replace(tzinfo=ET)


def season_code(season: int) -> str:
    return f"{season % 100:02d}"


def team_market(series_list: list[str], season: int, team: str, need_pair: str | None = None) -> dict | None:
    """The market for `team` in one of `series_list` for `season` (optionally an event naming both teams)."""
    yy = season_code(season)
    for s in series_list:
        for m in markets().get(s, {}).get("markets", []):
            ev = m["event_ticker"].split("-", 1)[1]
            if not ev.startswith(yy) or m["ticker"].rsplit("-", 1)[1] != team:
                continue
            if need_pair and need_pair not in ev:
                continue
            return {**m, "_series": s}
    return None


def pair_event(series: str, season: int, a: str, b: str) -> list[dict]:
    """Markets of the event in `series` naming both teams in its ticker."""
    yy = season_code(season)
    out = {}
    for m in markets().get(series, {}).get("markets", []):
        ev = m["event_ticker"].split("-", 1)[1]
        if ev.startswith(yy) and a in ev[2:] and b in ev[2:] and "APR" not in ev:
            out.setdefault(m["event_ticker"], []).append(m)
    if not out:
        return []
    # Prefer the event whose code is exactly the two teams plus an optional round tag.
    return sorted(out.values(), key=lambda ms: len(ms[0]["event_ticker"]))[0]
