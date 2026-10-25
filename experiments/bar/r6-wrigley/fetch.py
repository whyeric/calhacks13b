"""Fetch public inputs for r6-wrigley: ESPN schedules (Cubs, White Sox, Blackhawks, Bulls)
and NOAA GHCN daily weather at Chicago Midway. Cached in the scratchpad r2-cache (r6wrigley_*).

    backend/.venv/bin/python experiments/bar/r6-wrigley/fetch.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import httpx
import pandas as pd

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/"
             "43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
TEAMS = [("baseball/mlb", "chc", range(2014, 2018)), ("baseball/mlb", "chw", range(2014, 2018)),
         ("hockey/nhl", "chi", range(2014, 2019)), ("basketball/nba", "chi", range(2014, 2019))]


def games() -> pd.DataFrame:
    out = CACHE / "r6wrigley_games.csv"
    if out.exists():
        return pd.read_csv(out, parse_dates=["start"])
    rows = []
    for league, team, seasons in TEAMS:
        for season in seasons:
            for st in (2, 3):
                url = f"https://site.api.espn.com/apis/site/v2/sports/{league}/teams/{team}/schedule"
                d = httpx.get(url, params={"season": season, "seasontype": st}, timeout=60).json()
                for e in d.get("events", []):
                    c = e["competitions"][0]
                    me = next((t for t in c["competitors"]
                               if t["team"]["abbreviation"].lower() == team), None)
                    if me is None:
                        continue
                    opp = next((t for t in c["competitors"] if t is not me), None)
                    local = pd.Timestamp(e["date"]).tz_convert("America/Chicago").tz_localize(None)
                    rows.append({"league": league.split("/")[1], "team": team, "season": season,
                                 "stype": st, "start": local, "home": me.get("homeAway") == "home",
                                 "win": bool(me.get("winner")),
                                 "opp": opp["team"]["abbreviation"] if opp else "",
                                 "venue": c.get("venue", {}).get("fullName", ""),
                                 "note": "; ".join(n.get("headline", "") for n in c.get("notes", []))})
    g = pd.DataFrame(rows).drop_duplicates(["league", "team", "start"])
    g.to_csv(out, index=False)
    return g


def weather() -> pd.DataFrame:
    out = CACHE / "r6wrigley_ghcn_midway.csv"
    if not out.exists():
        url = ("https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/"
               "access/USW00014819.csv")
        d = pd.read_csv(io.StringIO(httpx.get(url, timeout=120).text), low_memory=False)
        d = d[["DATE", "PRCP", "TMAX", "TMIN", "SNOW"]]
        d = d[(d.DATE >= "2013-01-01") & (d.DATE <= "2018-12-31")]
        d.to_csv(out, index=False)
    return pd.read_csv(out, parse_dates=["DATE"])


def aggregate(raw_csv: str) -> None:
    """Divvy data_raw.csv (unzipped from ~/Downloads/archive (2).zip into r2-cache) -> station x hour
    starts/ends with casual counts. Delete the extracted CSV afterwards."""
    import duckdb
    con = duckdb.connect()
    con.execute(f"""create table t as select cast(starttime as timestamp) st, cast(stoptime as timestamp) et,
        usertype, from_station_id fs, to_station_id ts, from_station_name fn, latitude_start la,
        longitude_start lo from read_csv_auto('{raw_csv}')""")
    cust = "sum(case when usertype = 'Customer' then 1 else 0 end) cust, count(*) n"
    con.execute(f"copy (select fs sid, date_trunc('hour', st) h, {cust} from t group by 1, 2) "
                f"to '{CACHE / 'r6wrigley_starts.parquet'}'")
    con.execute(f"copy (select ts sid, date_trunc('hour', et) h, {cust} from t group by 1, 2) "
                f"to '{CACHE / 'r6wrigley_ends.parquet'}'")
    con.execute(f"copy (select fs sid, any_value(fn) name, median(la) lat, median(lo) lon from t group by 1) "
                f"to '{CACHE / 'r6wrigley_stations.parquet'}'")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        aggregate(sys.argv[1])
    g = games()
    print(g.groupby(["team", "league", "season", "stype", "home"]).size().unstack().to_string())
    print(g[(g.stype == 3) & g.home].to_string())
    w = weather()
    print(w.describe())
