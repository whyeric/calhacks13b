"""Knicks and Rangers home games and results at MSG from the ESPN scoreboard (spec §4.3).

One scoreboard call per (league, date), cached in memory and, when given, on disk (raw JSON in
gitignored `data/espn_cache/`). Game dates are the NY local date of the start time (ESPN gives UTC).
Preseason and all-star games are skipped. A game counts only when final; postponed, canceled and not-yet-played games give `home_game=False`.
Neutral-site games are not home games. `home_win` uses ESPN's `winner` flag, so NHL OT and shootout
wins count. `home_win` is False on non-game days (gap G6).

The tracked `fixtures/schedule_{team}.csv` (`date, home, opponent, home_win`; `home_win` empty when
not final) is the offline source and the fallback when ESPN fails; `games()` says which it used.

CLI (from backend/): `python -m app.data.sports` rebuilds both CSVs for the window plus demo week.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from app import config

log = logging.getLogger(__name__)

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/{league}/scoreboard"
NY = ZoneInfo(config.WEATHER_TZ)
CSV_COLUMNS = ["date", "home", "opponent", "home_win"]
DROPPED_STATUSES = {"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED", "STATUS_FORFEIT"}
DROPPED_SEASON_TYPES = {1, 4}  # ESPN: 1 preseason, 4 all-star/off-season; keeps regular, postseason, play-in
ESPN_CACHE_DIR = config.RAW_DATA_DIR / "espn_cache"
DEMO_WEEK = (date(2026, 10, 26), date(2026, 11, 1))


@dataclass(frozen=True)
class Team:
    key: str
    league: str  # ESPN sport/league path
    espn_id: str


TEAMS = {
    "knicks": Team("knicks", "basketball/nba", "18"),
    "rangers": Team("rangers", "hockey/nhl", "13"),
}


@dataclass(frozen=True)
class Game:
    date: date  # NY local date of the start time
    home: bool
    opponent: str
    final: bool
    won: bool | None  # None unless final


def parse_scoreboard(payload: dict, team: Team) -> list[Game]:
    """Games involving `team` in one scoreboard response."""
    games = []
    for event in payload.get("events", []):
        comp = (event.get("competitions") or [{}])[0]
        sides = {c["team"]["id"]: c for c in comp.get("competitors", [])}
        if team.espn_id not in sides:
            continue
        status = event.get("status", {}).get("type", {})
        if status.get("name") in DROPPED_STATUSES:
            continue
        if event.get("season", {}).get("type") in DROPPED_SEASON_TYPES:
            continue
        ours = sides[team.espn_id]
        other = next((c for tid, c in sides.items() if tid != team.espn_id), None)
        final = bool(status.get("completed")) and status.get("state", "post") == "post"
        start = datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(NY)
        games.append(
            Game(
                date=start.date(),
                home=ours.get("homeAway") == "home" and not comp.get("neutralSite", False),
                opponent=(other or {}).get("team", {}).get("abbreviation", ""),
                final=final,
                won=bool(ours.get("winner")) if final else None,
            )
        )
    return games


@dataclass
class ScoreboardClient:
    """ESPN scoreboard with one HTTP call per (league, date)."""

    http: httpx.Client | None = None
    cache_dir: Path | None = None
    calls: int = 0
    _mem: dict[tuple[str, date], dict] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def _disk(self, league: str, day: date) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / league.replace("/", "_") / f"{day:%Y%m%d}.json"

    def get(self, league: str, day: date) -> dict:
        key = (league, day)
        if key in self._mem:
            return self._mem[key]
        disk = self._disk(league, day)
        if disk is not None and disk.exists():
            payload = json.loads(disk.read_text())
        else:
            http = self.http or httpx.Client(timeout=20)
            try:
                resp = http.get(SCOREBOARD_URL.format(league=league), params={"dates": f"{day:%Y%m%d}"})
                resp.raise_for_status()
                payload = resp.json()
            finally:
                if self.http is None:
                    http.close()
            with self._lock:
                self.calls += 1
            if disk is not None and day < date.today():  # never cache a day that can still change
                disk.parent.mkdir(parents=True, exist_ok=True)
                disk.write_text(json.dumps(payload))
        self._mem[key] = payload
        return payload


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def fetch_games(team: Team, start: date, end: date, client: ScoreboardClient, workers: int = 8) -> list[Game]:
    """All games for `team` with NY dates in [start, end]. Queries one day either side for UTC spill."""
    days = _days(start - timedelta(days=1), end + timedelta(days=1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        payloads = list(pool.map(lambda d: client.get(team.league, d), days))
    seen: dict[tuple[date, str], Game] = {}
    for payload in payloads:
        for g in parse_scoreboard(payload, team):
            if start <= g.date <= end:
                seen[(g.date, g.opponent)] = g
    return sorted(seen.values(), key=lambda g: g.date)


def schedule_frame(games: list[Game]) -> pd.DataFrame:
    """Rows for `schedule_{team}.csv`."""
    return pd.DataFrame(
        [{"date": g.date.isoformat(), "home": g.home, "opponent": g.opponent, "home_win": g.won} for g in games],
        columns=CSV_COLUMNS,
    )


def daily_flags(games: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Per calendar day: `home_game` (final home game) and `home_win` (that game won).

    `games` has the CSV schema; `home_win` is NaN/None when not final.
    """
    g = games.copy()
    g["date"] = pd.to_datetime(g["date"]).dt.date
    final_home = g[g["home"].astype(bool) & g["home_win"].notna()]
    won = final_home["home_win"].map(lambda v: v is True or str(v).lower() == "true")
    out = pd.DataFrame({"date": _days(start, end)})
    out["home_game"] = out["date"].isin(set(final_home["date"]))
    out["home_win"] = out["date"].isin(set(final_home.loc[won, "date"]))
    return out


def csv_path(team: str, fixtures_dir: Path = config.FIXTURES_DIR) -> Path:
    return fixtures_dir / f"schedule_{team}.csv"


def read_schedule(team: str, fixtures_dir: Path = config.FIXTURES_DIR) -> pd.DataFrame:
    path = csv_path(team, fixtures_dir)
    if not path.exists():
        raise FileNotFoundError(f"schedule fixture missing: {path} (run `python -m app.data.sports`)")
    df = pd.read_csv(path, dtype={"date": str, "opponent": str}, keep_default_na=False)
    df["home"] = df["home"].astype(str).str.lower() == "true"
    df["home_win"] = df["home_win"].map(lambda v: None if v == "" else str(v).lower() == "true")
    return df[CSV_COLUMNS]


def games(
    team: str,
    start: date = config.WINDOW_START,
    end: date = config.WINDOW_END,
    *,
    client: ScoreboardClient | None = None,
    offline: bool | None = None,
    fixtures_dir: Path = config.FIXTURES_DIR,
) -> tuple[pd.DataFrame, dict]:
    """Daily `date, home_game, home_win` for one team plus metadata `{source, fallback, error}`.

    Offline (or no client given) reads the CSV. Online, ESPN failures fall back to the CSV.
    """
    if offline is None:
        offline = config.get_settings().demo_offline
    if offline or client is None:
        df = daily_flags(read_schedule(team, fixtures_dir), start, end)
        return df, {"source": "csv", "fallback": False, "error": None}
    try:
        g = fetch_games(TEAMS[team], start, end, client)
        return daily_flags(schedule_frame(g), start, end), {"source": "espn", "fallback": False, "error": None}
    except (httpx.HTTPError, ValueError, KeyError) as e:
        log.warning("ESPN failed for %s, using CSV: %s", team, e)
        df = daily_flags(read_schedule(team, fixtures_dir), start, end)
        return df, {"source": "csv", "fallback": True, "error": str(e)}


def msg_games(start: date, end: date, *, fixtures_dir: Path = config.FIXTURES_DIR, **kw) -> tuple[pd.DataFrame, dict]:
    """Knicks or Rangers at MSG: `home_game` any final home game that day, `home_win` any won."""
    frames, meta = [], {}
    for team in TEAMS:
        df, meta[team] = games(team, start, end, fixtures_dir=fixtures_dir, **kw)
        frames.append(df.set_index("date"))
    out = (frames[0] | frames[1]).reset_index()
    return out, meta


def build(fixtures_dir: Path = config.FIXTURES_DIR) -> dict[str, int]:
    """Rebuild both schedule CSVs for the window plus the demo week (network)."""
    client = ScoreboardClient(http=httpx.Client(timeout=20), cache_dir=ESPN_CACHE_DIR)
    counts = {}
    for key, team in TEAMS.items():
        g = fetch_games(team, config.WINDOW_START, config.WINDOW_END, client)
        g += fetch_games(team, *DEMO_WEEK, client)
        frame = schedule_frame(g)
        frame.to_csv(csv_path(key, fixtures_dir), index=False)
        counts[key] = len(frame)
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(build())
