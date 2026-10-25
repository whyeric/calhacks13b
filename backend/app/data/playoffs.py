"""Knicks and Rangers games with playoff flags, from the ESPN team-schedule endpoint.

`fixtures/msg_games_playoffs.csv` (tracked, small, public) has one row per completed game:

    date, team, season, playoff, home, round, opponent, won

`date` is the NY local date of the start time. `season` is the year the playoffs end (ESPN's
convention). `home` means the game was played at Madison Square Garden. `round` is ESPN's note
headline ("East 1st Round", ...), empty in the regular season.

Offline, `read_games()` reads the CSV. `fetch()` (network) rebuilds it; run it through
`scripts/fetch_playoffs.py`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd

from app import config
from app.data.sports import NY, TEAMS

SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/{league}/teams/{team_id}/schedule"
FIXTURE = "msg_games_playoffs.csv"
COLUMNS = ["date", "team", "season", "playoff", "home", "round", "opponent", "won"]
SEASONS = (2024, 2025, 2026)  # ESPN season = the year the playoffs end; Dewey starts 2024-01
REGULAR, POSTSEASON = 2, 3


def parse_schedule(payload: dict, team_key: str, season: int, playoff: bool) -> list[dict]:
    """Completed games for one team in one ESPN schedule response."""
    team = TEAMS[team_key]
    rows = []
    for ev in payload.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        status = comp.get("status", ev.get("status", {})).get("type", {})
        if not status.get("completed", False):
            continue
        sides = comp.get("competitors", [])
        me = next((c for c in sides if str(c.get("team", {}).get("id")) == team.espn_id), None)
        other = next((c for c in sides if str(c.get("team", {}).get("id")) != team.espn_id), None)
        if me is None or me.get("winner") is None:
            continue
        start = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(NY)
        venue = comp.get("venue", {}).get("fullName", "")
        home = me.get("homeAway") == "home" and not comp.get("neutralSite", False) and "Madison Square" in venue
        note = (comp.get("notes") or [{}])[0].get("headline", "") if playoff else ""
        rows.append({
            "date": start.date().isoformat(), "team": team_key, "season": season, "playoff": playoff,
            "home": home, "round": note.split(" - ")[0], "won": bool(me["winner"]),
            "opponent": (other or {}).get("team", {}).get("abbreviation", ""),
        })
    return rows


def fetch(
    seasons: tuple[int, ...] = SEASONS, *, fixtures_dir: Path = config.FIXTURES_DIR,
    client: httpx.Client | None = None,
) -> pd.DataFrame:
    """Rebuild the fixture from ESPN (network). Returns the frame it wrote."""
    http = client or httpx.Client(timeout=30)
    rows: list[dict] = []
    try:
        for key, team in TEAMS.items():
            for season in seasons:
                for st in (REGULAR, POSTSEASON):
                    r = http.get(SCHEDULE_URL.format(league=team.league, team_id=team.espn_id),
                                 params={"season": season, "seasontype": st})
                    if r.status_code == 404:
                        continue
                    r.raise_for_status()
                    rows += parse_schedule(r.json(), key, season, st == POSTSEASON)
    finally:
        if client is None:
            http.close()
    df = pd.DataFrame(rows, columns=COLUMNS).drop_duplicates(["date", "team"]).sort_values(["date", "team"])
    df.to_csv(fixtures_dir / FIXTURE, index=False)
    return df


def read_games(fixtures_dir: Path = config.FIXTURES_DIR) -> pd.DataFrame:
    path = fixtures_dir / FIXTURE
    if not path.exists():
        raise FileNotFoundError(f"playoff schedule fixture missing: {path} (run scripts/fetch_playoffs.py)")
    df = pd.read_csv(path, dtype={"date": str, "round": str, "opponent": str}, keep_default_na=False)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    for col in ("playoff", "home", "won"):
        df[col] = df[col].astype(str).str.lower() == "true"
    return df[COLUMNS]


__all__ = ["COLUMNS", "FIXTURE", "fetch", "parse_schedule", "read_games"]


if __name__ == "__main__":
    out = fetch()
    print(out.groupby(["team", "season", "playoff"])["home"].sum())
