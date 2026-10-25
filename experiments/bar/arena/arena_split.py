"""Does a Knicks/Rangers *win* move foot traffic at all? Arena visits first, then the bar.

Run from backend/: .venv/bin/python ../experiments/bar/arena/arena_split.py
Prints summary tables only (no daily series written).
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

import numpy as np
import pandas as pd
import statsmodels.api as sm

from app import config
from app.data import features, sports
from app.stats.exposure import Z90

FIX = config.FIXTURES_DIR


def team_flags(start, stop) -> pd.DataFrame:
    out = pd.DataFrame({"date": pd.date_range(start, stop, freq="D").date}).set_index("date")
    for team in ("knicks", "rangers"):
        sched = sports.read_schedule(team, FIX)
        sched["date"] = pd.to_datetime(sched["date"]).dt.date
        sched = sched[(sched["date"] >= start) & (sched["date"] <= stop)]
        home, away = sched[sched["home"]], sched[~sched["home"]]
        out[f"{team}_home_game"] = out.index.isin(home["date"])
        out[f"{team}_home_win"] = out.index.isin(home.loc[home["home_win"].astype(bool), "date"])
        out[f"{team}_away_game"] = out.index.isin(away["date"])
        out[f"{team}_away_win"] = out.index.isin(away.loc[away["home_win"].astype(bool), "date"])
    return out.reset_index()


def design(df: pd.DataFrame, flags: list[str], season: str = "fourier") -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    X["const"] = 1.0
    for d in range(1, 7):
        X[f"dow_{d}"] = (df["dow"] == d).astype(float)
    if season == "fourier":
        w = 2 * np.pi * df["doy"].astype(float) / 365.25
        for k in (1, 2):
            X[f"sin{k}"], X[f"cos{k}"] = np.sin(k * w), np.cos(k * w)
    else:  # year-month fixed effects
        ym = pd.to_datetime(df["date"]).dt.to_period("M").astype(str)
        X = X.join(pd.get_dummies(ym, prefix="m", drop_first=True).astype(float))
    for c in ["is_holiday", *flags]:
        X[c] = df[c].astype(float)
    return X.loc[:, (X.nunique() > 1) | (X.columns == "const")]


def fit(df, y, flags, season="fourier"):
    X = design(df, flags, season)
    return sm.OLS(df[y].astype(float), X).fit(cov_type="HC3"), X


def row(res, X, name, label, unit=1.0):
    if name not in res.params:
        return None
    b, se, p = res.params[name] * unit, res.bse[name] * unit, res.pvalues[name]
    return dict(spec=label, term=name, effect=round(b, 1), lo=round(b - Z90 * se, 1), hi=round(b + Z90 * se, 1),
                p=round(p, 3), n=int(X[name].sum()), sig="yes" if p < 0.10 else "no")


def main():
    pd.set_option("display.width", 200, "display.max_rows", 200)
    start, stop = config.WINDOW_START, config.WINDOW_END
    msg = pd.read_parquet(FIX / "msg_visits_daily.parquet")
    msg["date"] = pd.to_datetime(msg["date"]).dt.date
    base = features.build("restaurant")  # bar revenue + calendar + weather, window-clipped
    df = base.merge(msg, on="date", how="left").merge(team_flags(start, stop), on="date", how="left")
    assert df["visits"].notna().all()
    df["other_event"] = df["spike"] & ~df["home_game"]  # non-game MSG spike (concert etc.)
    df["any_away"] = df["knicks_away_game"] | df["rangers_away_game"]
    df["bar_visits"] = df["revenue"] / 35.0

    teams = ["knicks", "rangers"]
    split_flags = [f"{t}_{k}" for t in teams for k in ("home_game", "home_win")]
    rows = []
    for y, unit, tag in (("visits", 1.0, "arena visits"), ("revenue", 1.0, "bar $")):
        for season in ("fourier", "monthFE"):
            for sample in ("all", "train"):
                d = df if sample == "all" else df[df["split"] == "train"].reset_index(drop=True)
                res, X = fit(d, y, [*split_flags, "other_event"], season)
                for t in [*split_flags, "other_event"]:
                    r = row(res, X, t, f"{tag} | {season} | {sample}")
                    if r:
                        r["R2"] = round(res.rsquared, 3)
                        rows.append(r)
        # pooled (as in the app) for reference
        res, X = fit(df, y, ["home_game", "home_win", "other_event"])
        for t in ("home_game", "home_win", "other_event"):
            r = row(res, X, t, f"{tag} | pooled | all"); r["R2"] = round(res.rsquared, 3); rows.append(r)
        # with away games (bar might show away games on TV)
        res, X = fit(df, y, [*split_flags, "other_event", "knicks_away_game", "knicks_away_win",
                             "rangers_away_game", "rangers_away_win"])
        for t in ("knicks_home_win", "rangers_home_win", "knicks_away_game", "knicks_away_win",
                  "rangers_away_game", "rangers_away_win"):
            r = row(res, X, t, f"{tag} | +away | all"); r["R2"] = round(res.rsquared, 3); rows.append(r)
    out = pd.DataFrame(rows)
    print(out.to_string(index=False))

    # Penn Station dilution: how commuter-shaped is the arena POI?
    print("\n== Penn dilution ==")
    plain = df[~df["home_game"] & ~df["spike"] & ~df["is_holiday"]]
    by_dow = plain.groupby("dow")["visits"].mean()
    print("plain-day mean visits by DOW (Mon=0):", by_dow.round(0).to_dict())
    print("weekday/weekend ratio:", round(by_dow[:5].mean() / by_dow[5:].mean(), 3))
    hol = df[df["is_holiday"] & ~df["home_game"]]["visits"].mean()
    print("holiday mean vs plain weekday mean:", round(hol), round(by_dow[:5].mean()))
    print("plain-day mean, sd, CV:", round(plain["visits"].mean()), round(plain["visits"].std()),
          round(plain["visits"].std() / plain["visits"].mean(), 3))
    for spec, fl in (("DOW+season+holiday only", []), ("+ games + other_event", [*split_flags, "other_event"])):
        res, _ = fit(df, "visits", fl)
        print(f"R2 arena {spec}: {res.rsquared:.3f}")
    # paired: same DOW, game vs no-game, % uplift
    res, X = fit(df, "visits", [*split_flags, "other_event"])
    for t in split_flags + ["other_event"]:
        print(f"{t}: {res.params[t]:+.0f} visits = {100*res.params[t]/plain['visits'].mean():+.1f}% of plain-day mean")
    # Correlation of bar with arena residual-free
    print("corr(bar visits, arena visits) all days:", round(df["bar_visits"].corr(df["visits"]), 3))
    print("corr on plain days:", round(plain["revenue"].corr(plain["visits"]), 3))
    # Game counts
    for t in teams:
        hg = df[f"{t}_home_game"]
        print(f"{t}: home games {hg.sum()} (train {(hg & (df.split=='train')).sum()}), "
              f"home wins {df[f'{t}_home_win'].sum()} (train {(df[f'{t}_home_win'] & (df.split=='train')).sum()})")
    print("other_event days:", int(df["other_event"].sum()), "| spike on game days:", int((df.spike & df.home_game).sum()),
          "of", int(df.home_game.sum()))
    # Arena: win vs loss raw residual means (DOW+season+holiday+other_event), per team
    res0, _ = fit(df, "visits", ["other_event"])
    df["resid"] = df["visits"] - res0.fittedvalues
    for t in teams:
        g = df[df[f"{t}_home_game"]]
        w, l = g[g[f"{t}_home_win"]]["resid"], g[~g[f"{t}_home_win"]]["resid"]
        print(f"{t} arena resid: win {w.mean():+.0f} (n={len(w)}), loss {l.mean():+.0f} (n={len(l)})")


if __name__ == "__main__":
    main()
