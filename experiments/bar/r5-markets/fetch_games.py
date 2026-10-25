"""Every 2025-2026 NBA / NHL / MLB / NFL postseason game from ESPN's public scoreboard.

Output: r2-cache/r5markets_games.csv, one row per game:
league, date, home, away, home_score, away_score, winner, note (ESPN series headline).

    backend/.venv/bin/python experiments/bar/r5-markets/fetch_games.py
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import httpx
import pandas as pd

from fetch_markets import CACHE

URL = "https://site.api.espn.com/apis/site/v2/sports/{}/scoreboard"
WINDOWS = {
    "nba": ("basketball/nba", [(date(2025, 4, 15), date(2025, 6, 25)), (date(2026, 4, 14), date(2026, 6, 25))]),
    "nhl": ("hockey/nhl", [(date(2025, 4, 18), date(2025, 6, 25)), (date(2026, 4, 17), date(2026, 6, 25))]),
    "mlb": ("baseball/mlb", [(date(2025, 9, 29), date(2025, 11, 5)), (date(2026, 9, 28), date(2026, 11, 10))]),
    "nfl": ("football/nfl", [(date(2026, 1, 9), date(2026, 2, 10))]),
}


def day(league_path: str, d: date) -> list[dict]:
    for _ in range(4):
        try:
            r = httpx.get(URL.format(league_path), params={"dates": f"{d:%Y%m%d}", "seasontype": 3}, timeout=30)
            r.raise_for_status()
            break
        except httpx.HTTPError:
            continue
    else:
        return []
    rows = []
    for ev in r.json().get("events", []):
        if ev.get("season", {}).get("type") != 3:
            continue
        comp = ev["competitions"][0]
        if not comp.get("status", {}).get("type", {}).get("completed"):
            continue
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        h, a = sides["home"], sides["away"]
        when = datetime.fromisoformat(comp["date"].replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=-4)))
        rows.append({
            "date": when.date().isoformat(),
            "home": h["team"]["abbreviation"], "away": a["team"]["abbreviation"],
            "home_score": int(h.get("score", 0)), "away_score": int(a.get("score", 0)),
            "winner": h["team"]["abbreviation"] if h.get("winner") else a["team"]["abbreviation"],
            "neutral": bool(comp.get("neutralSite")),
            "note": "; ".join(n.get("headline", "") for n in comp.get("notes", [])),
            "event_id": ev["id"],
        })
    return rows


def main() -> None:
    jobs = []
    for lg, (path, wins) in WINDOWS.items():
        for a, b in wins:
            d = a
            while d <= b:
                jobs.append((lg, path, d))
                d += timedelta(days=1)
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda j: [{"league": j[0], **r} for r in day(j[1], j[2])], jobs))
    df = pd.DataFrame([r for rs in res for r in rs]).drop_duplicates("event_id").sort_values(["league", "date"])
    df.to_csv(CACHE / "r5markets_games.csv", index=False)
    print(df.groupby("league").size())


if __name__ == "__main__":
    main()
