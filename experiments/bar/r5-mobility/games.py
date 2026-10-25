"""Knicks and Rangers games 2022-01..2026-06 from cached ESPN scoreboards (regular season, play-in, playoffs).

One row per game: NY-local date and start, home (at MSG, not neutral), season type, playoff round
(1 = first round .. 4 = finals), game number in the series, result.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
DIRS = [CACHE / "espn", CACHE / "r5playoffmobility_espn"]
TEAMS = {"knicks": ("basketball_nba", "18"), "rangers": ("hockey_nhl", "13")}
ROUND = {"RD16": 1, "QTR": 2, "SEMI": 3, "FINAL": 4}
NY = ZoneInfo("America/New_York")


def load() -> pd.DataFrame:
    rows, seen = [], set()
    for team, (league, tid) in TEAMS.items():
        files = sorted(f for d in DIRS for f in (d / league).glob("*.json"))
        for f in files:
            for e in json.loads(f.read_text()).get("events", []):
                if e["id"] in seen:
                    continue
                c = e["competitions"][0]
                sides = {x["team"]["id"]: x for x in c["competitors"]}
                st = e["status"]["type"]
                if tid not in sides or not st.get("completed") or e["season"]["type"] not in (2, 3, 5):
                    continue
                seen.add(e["id"])
                ours = sides[tid]
                start = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(NY)
                head = " ".join(n.get("headline", "") for n in c.get("notes", []))
                g = re.search(r"Game (\d)", head)
                stype = e["season"]["type"]
                rows.append({
                    "date": pd.Timestamp(start.date()), "start": start.replace(tzinfo=None), "team": team,
                    "home": ours["homeAway"] == "home" and not c.get("neutralSite", False),
                    "msg": c.get("venue", {}).get("fullName") == "Madison Square Garden",
                    "stype": {2: "reg", 3: "post", 5: "playin"}[stype],
                    "round": ROUND.get(c.get("type", {}).get("abbreviation")) if stype == 3 else None,
                    "game_no": int(g.group(1)) if (g and stype == 3) else None,
                    "won": bool(ours.get("winner")),
                    "opp": next(x["team"]["abbreviation"] for k, x in sides.items() if k != tid),
                    "season": e["season"]["year"],
                })
    df = pd.DataFrame(rows).sort_values("start").reset_index(drop=True)
    return df


if __name__ == "__main__":
    d = load()
    print(d.groupby(["team", "season", "stype", "home"]).size().unstack([2, 3]).fillna(0).astype(int))
    print(d[d.stype == "post"].to_string())
