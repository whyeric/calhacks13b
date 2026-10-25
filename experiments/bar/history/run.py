"""Experiment: does a longer history (2024-01-01 onward) make the bar's home_win / rain effect measurable?

Run from backend/:  .venv/bin/python ../experiments/bar/history/run.py
Network: Open-Meteo archive + ESPN scoreboard; caches go to the session scratchpad (env EXP_CACHE),
never to backend/fixtures or data/. Prints summary numbers only.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402
import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.data import dewey, features, sports, weather  # noqa: E402
from app.stats import exposure as ex  # noqa: E402

CACHE = Path(os.environ.get("EXP_CACHE", "/tmp/exp_bar_history_cache"))
START = config.DEWEY_START  # 2024-01-01
STRIKES = {"hot": 85}
PLAYOFF_TYPES = {3, 5}  # ESPN season.type: 3 postseason, 5 play-in


def revenue() -> pd.DataFrame:
    """The chosen bar's daily revenue, as built by dewey.py into fixtures/restaurant_daily.parquet."""
    r = pd.read_parquet(config.FIXTURES_DIR / features.RESTAURANT_FIXTURE)
    assert (r["place_id"] == dewey.CHOSEN_PLACE_ID).all()
    r["date"] = pd.to_datetime(r["date"]).dt.date
    return r.rename(columns={"revenue_est": "revenue"})[["date", "revenue"]]


def msg_games_with_type(start: date, end: date) -> pd.DataFrame:
    """Per day: home_game, home_win, home_win_playoff (Knicks or Rangers at MSG), from ESPN."""
    client = sports.ScoreboardClient(http=httpx.Client(timeout=20), cache_dir=CACHE / "espn")
    rows = []
    for team in sports.TEAMS.values():
        for g in sports.fetch_games(team, start, end, client):
            if not (g.home and g.final):
                continue
            # season type of that game: look it up in the cached payloads around the NY date
            stype = None
            for d in (g.date, g.date + pd.Timedelta(days=1)):
                for ev in client.get(team.league, d).get("events", []):
                    comp = ev["competitions"][0]
                    ids = {c["team"]["id"] for c in comp["competitors"]}
                    ny = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(sports.NY).date()
                    if team.espn_id in ids and ny == g.date:
                        stype = ev.get("season", {}).get("type")
            rows.append({"date": g.date, "team": team.key, "won": bool(g.won), "playoff": stype in PLAYOFF_TYPES})
    gm = pd.DataFrame(rows)
    out = pd.DataFrame({"date": pd.date_range(start, end, freq="D").date})
    out["home_game"] = out["date"].isin(set(gm["date"]))
    out["home_win"] = out["date"].isin(set(gm.loc[gm["won"], "date"]))
    out["home_win_playoff"] = out["date"].isin(set(gm.loc[gm["won"] & gm["playoff"], "date"]))
    out.attrs["games"] = gm
    return out


def table() -> tuple[pd.DataFrame, pd.DataFrame, int]:
    rev = revenue()
    stop = rev["date"].max()
    w = weather.load_weather(*config.MSG_LATLON, START, stop, cache_dir=CACHE, offline=False)
    wf = weather.flags(w)
    games = msg_games_with_type(START, stop)
    df = pd.DataFrame({"date": pd.date_range(START, stop, freq="D").date})
    df = df.merge(rev, on="date", how="left").merge(games, on="date", how="left").merge(wf, on="date", how="left")
    missing = df["revenue"].isna().sum()
    df = df.dropna(subset=["revenue"]).reset_index(drop=True)
    df = df.join(features.calendar(df["date"]))
    spikes = features._spikes(config.FIXTURES_DIR)
    df["msg_event"] = df["home_game"] | df["date"].map(spikes).fillna(False).astype(bool)
    df["estimated"] = True
    return features.split(df), games.attrs["games"], int(missing)


def fmt_exp(e) -> str:
    sig = "yes" if not (e.ci90[0] <= 0 <= e.ci90[1]) else "no"
    return (f"| {e.event} | {e.effect_usd} | [{e.ci90[0]}, {e.ci90[1]}] | {e.n_events_train} | {sig} | "
            f"{'yes' if e.hedgeable else 'no: ' + ','.join(e.reasons)} |")


def report(name: str, res) -> None:
    print(f"\n### {name}\nn_train={res.n_train} n_holdout={res.n_holdout} "
          f"R2 train={res.r2_train:.3f} holdout={'-' if res.r2_holdout is None else f'{res.r2_holdout:.3f}'}")
    print("| event | effect $ | 90% CI | n train | significant | hedgeable |\n|---|---|---|---|---|---|")
    for e in sorted(res.exposures + res.dropped, key=lambda e: ex.EVENTS.index(e.event)):
        print(fmt_exp(e))


def split_fit(train: pd.DataFrame, label: str) -> None:
    """(c) home_win split into playoff vs regular-season wins, same design otherwise."""
    flags = ex.event_flags(train, STRIKES)
    hw = flags.pop("home_win")
    po = train["home_win_playoff"].astype(bool)
    flags = {"home_win_regular": hw & ~po, "home_win_playoff": po, **flags}
    X = ex.build_design(train, flags)
    res = ex.fit_ols(train["revenue"], X)
    print(f"\n### (c) playoff split, {label}  n={len(train)}\n| flag | effect $ | 90% CI | n | significant |\n|---|---|---|---|---|")
    for k, f in flags.items():
        b, se, _ = ex._coef(res, k)
        lo, hi = b - ex.Z90 * se, b + ex.Z90 * se
        print(f"| {k} | {b:.2f} | [{lo:.2f}, {hi:.2f}] | {int(f.sum())} | {'yes' if lo > 0 or hi < 0 else 'no'} |")


def main() -> None:
    df, gm, missing = table()
    print(f"rows {len(df)} {df['date'].min()}..{df['date'].max()} (missing revenue days dropped: "
          f"{missing}); train {df['date'].iloc[0]}..{df.loc[df.split=='train','date'].max()}")
    g = gm.assign(season=lambda x: x["playoff"].map({True: "playoff", False: "regular"}))
    print("home games by team/season type:\n", g.groupby(["team", "season"]).agg(games=("won", "size"), wins=("won", "sum")).to_string())
    pre = gm[gm["date"] < config.WINDOW_START]
    print(f"home games before 2024-10-01: {len(pre)} ({int(pre['won'].sum())} wins, {int(pre['playoff'].sum())} playoff)")

    # baseline: the shared-window table, for reference
    base = features.build("restaurant")
    report("baseline: shared window 2024-10-01.., train 365d", ex.fit_exposures(base, STRIKES, business_id="bar"))

    report("(a) 2024-01-01.., train first 365d", ex.fit_exposures(df, STRIKES, business_id="bar"))
    report("(b) all data as train", ex.fit_exposures(df.assign(split="train"), STRIKES, business_id="bar"))

    split_fit(df[df["split"] == "train"], "train first 365d")
    split_fit(df, "all data")


if __name__ == "__main__":
    main()
