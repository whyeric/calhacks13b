"""Does the bar's win effect exist only for high-stakes games?

Classifies every Knicks/Rangers game in the window (playoff vs regular, weekend vs weekday,
close vs blowout, home vs away) from ESPN scoreboards, then refits the fit_exposures design on
features.build("restaurant") train rows with class-split win flags. Summary numbers only.

Run from backend/: .venv/bin/python ../experiments/bar/stakes/stakes.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

import pandas as pd  # noqa: E402

from app.data import features, sports  # noqa: E402
from app.stats.exposure import Z90, build_design, event_flags, fit_ols  # noqa: E402

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/stakes_espn")
CLOSE = {"knicks": 5, "rangers": 1}  # close = margin <= this (NBA points, NHL goals)


def detail(client, team, d, opp):
    """(season_type, margin) for the game on NY date d vs opp, from ESPN."""
    for day in (d, d - timedelta(days=1), d + timedelta(days=1)):
        for ev in client.get(team.league, day).get("events", []):
            comp = ev["competitions"][0]
            sides = {c["team"]["id"]: c for c in comp["competitors"]}
            if team.espn_id not in sides:
                continue
            other = [c for k, c in sides.items() if k != team.espn_id][0]
            if other["team"]["abbreviation"] != opp:
                continue
            try:
                margin = abs(float(sides[team.espn_id]["score"]) - float(other["score"]))
            except (KeyError, ValueError, TypeError):
                margin = None
            return ev.get("season", {}).get("type"), margin
    return None, None


def schedule():
    client = sports.ScoreboardClient(cache_dir=CACHE)
    rows = []
    for key, team in sports.TEAMS.items():
        s = sports.read_schedule(key)
        s = s[s["home_win"].notna()]
        for r in s.itertuples():
            d = date.fromisoformat(r.date)
            st, m = detail(client, team, d, r.opponent)
            rows.append(dict(team=key, date=d, home=r.home, won=bool(r.home_win),
                             playoff=st == 3, margin=m, close=m is not None and m <= CLOSE[key]))
    g = pd.DataFrame(rows)
    print(f"ESPN calls {client.calls}; missing detail: {g['margin'].isna().sum()} of {len(g)}")
    return g


def day_flags(df, g, mask):
    days = set(g.loc[mask, "date"])
    return df["date"].map(lambda x: pd.Timestamp(x).date() in days)


def fit(train, extra, drop_home_win=True, label=""):
    flags = event_flags(train, {"hot": 85})
    if drop_home_win:
        flags.pop("home_win")
    flags.update(extra)
    X = build_design(train, flags)
    res = fit_ols(train["revenue"], X)
    out = []
    for name, f in extra.items():
        n = int(f.sum())
        if name not in res.params.index:
            out.append((label, name, None, None, None, n, "dropped (constant)"))
            continue
        b, se = res.params[name], res.bse[name]
        lo, hi = b - Z90 * se, b + Z90 * se
        sig = "yes" if (lo > 0 or hi < 0) else "no"
        out.append((label, name, b, lo, hi, n, sig + (" (anecdotal n<10)" if n < 10 else "")))
    return out


def main():
    df = features.build("restaurant")
    train = df[df["split"] == "train"].copy()
    g = schedule()
    wkend = g["date"].map(lambda d: d.weekday() >= 4)  # Fri/Sat/Sun
    W, H = g["won"], g["home"]
    print("games in window:", len(g), "| playoff:", int(g.playoff.sum()),
          "| train-window games:", int(g["date"].isin(set(pd.to_datetime(train["date"]).dt.date)).sum()))
    F = lambda m: day_flags(train, g, m)  # noqa: E731
    res = []
    # 0. baseline replication
    res += fit(train, {"home_win": train["home_win"].astype(bool)}, label="baseline")
    # 1. home wins split by stakes class (home_game control stays in)
    res += fit(train, {"home_win_playoff": F(H & W & g.playoff), "home_win_regular": F(H & W & ~g.playoff)}, label="playoff")
    res += fit(train, {"home_win_weekend": F(H & W & wkend), "home_win_weekday": F(H & W & ~wkend)}, label="weekend")
    res += fit(train, {"home_win_close": F(H & W & g.close), "home_win_blowout": F(H & W & ~g.close)}, label="margin")
    # 2. away games (separate test): away_game control + away_win
    res += fit(train, {"home_win": train["home_win"].astype(bool), "away_game": F(~H), "away_win": F(~H & W)},
               drop_home_win=True, label="away")
    # 3. any game (home or away) by stakes: game flag + win flag per class
    res += fit(train, {"any_game": F(g.index == g.index), "any_win_playoff": F(W & g.playoff),
                       "any_win_regular": F(W & ~g.playoff)}, label="any_game")
    res += fit(train, {"playoff_game": F(g.playoff), "regular_game_nonhome": F(~g.playoff & ~H)}, label="playoff_game")
    t = pd.DataFrame(res, columns=["spec", "term", "effect", "ci_lo", "ci_hi", "n_train", "significant"])
    pd.set_option("display.width", 200)
    print(t.to_string(index=False, float_format=lambda v: f"{v:,.0f}"))


if __name__ == "__main__":
    main()


def holdout_check():
    """Out-of-sample check of the one significant term: refit playoff_game on holdout rows only."""
    df = features.build("restaurant")
    g = schedule()
    for split in ("train", "holdout"):
        part = df[df["split"] == split].copy()
        print(split, fit(part, {"playoff_game": day_flags(part, g, g.playoff),
                                "regular_game_nonhome": day_flags(part, g, ~g.playoff & ~g.home)}, label=split))
    # which teams/rounds make up train playoff days
    tr = set(pd.to_datetime(df.loc[df["split"] == "train", "date"]).dt.date)
    p = g[g.playoff & g["date"].isin(tr)]
    print("train playoff games by team/home:", p.groupby(["team", "home"]).size().to_dict(), "wins:", int(p.won.sum()))
    ho = g[g.playoff & ~g["date"].isin(tr)]
    print("holdout playoff games by team/home:", ho.groupby(["team", "home"]).size().to_dict())
