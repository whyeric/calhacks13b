"""Next-day spillover timing experiment for the MSG bar (see RESULTS.md).

Run from backend/: .venv/bin/python ../experiments/bar/timing/timing.py
Fetches ESPN tip-off times for MSG home dates (network), caches them in the scratchpad.
"""
import json
import os
import tempfile
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from app.data import features, sports  # noqa: E402
from app.stats.exposure import Z90, build_design, fit_ols  # noqa: E402

CACHE = Path(os.environ.get("TIMING_CACHE", str(Path(tempfile.gettempdir()) / "timing_tipoffs.json")))


def tipoffs(dates: list[str]) -> dict[str, float]:
    """date -> NY local start hour (decimal) of the MSG home game (earliest if two)."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    need = [d for d in dates if d not in cache]

    def one(d):
        hours = []
        for team in sports.TEAMS.values():
            r = httpx.get(sports.SCOREBOARD_URL.format(league=team.league),
                          params={"dates": d.replace("-", "")}, timeout=20)
            for ev in r.json().get("events", []):
                comp = ev["competitions"][0]
                home = [c for c in comp["competitors"] if c.get("homeAway") == "home"]
                if home and home[0]["team"]["id"] == team.espn_id:
                    t = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(sports.NY)
                    if t.date().isoformat() == d:
                        hours.append(t.hour + t.minute / 60)
        return d, (min(hours) if hours else None)

    with ThreadPoolExecutor(8) as ex:
        for d, h in ex.map(one, need):
            cache[d] = h
    CACHE.write_text(json.dumps(cache))
    return {d: cache[d] for d in dates}


def shift(s: pd.Series, k: int) -> pd.Series:
    """Value k days earlier (k>0 = lag) by calendar date, False when missing."""
    out = s.copy()
    out.index = out.index + pd.Timedelta(days=k)
    return out.reindex(s.index).fillna(False).astype(bool)


def fit(df, y, flags):
    X = build_design(df, flags)
    res = fit_ols(y, X)
    rows = []
    for name, f in flags.items():
        if name not in res.params.index:
            rows.append((name, np.nan, np.nan, np.nan, int(f.sum()), "dropped"))
            continue
        b, se, p = res.params[name], res.bse[name], res.pvalues[name]
        lo, hi = b - Z90 * se, b + Z90 * se
        rows.append((name, b, lo, hi, int(f.sum()), "yes" if (lo > 0 or hi < 0) else "no"))
    return pd.DataFrame(rows, columns=["flag", "effect", "lo90", "hi90", "n", "sig90"]), res


def show(title, tab):
    print(f"\n## {title}")
    print(tab.to_string(index=False, float_format=lambda v: f"{v:,.1f}"))


def main():
    df = features.build("restaurant").copy()
    df.index = pd.to_datetime(df["date"])
    assert (df.index.to_series().diff().dropna() == pd.Timedelta(days=1)).all()

    hw, hg = df["home_win"].astype(bool), df["home_game"].astype(bool)
    df_flags = {
        "home_win": hw,
        "win_day_after": shift(hw, 1),    # today is the day after a home win
        "win_day_before": shift(hw, -1),  # lead / placebo: a home win tomorrow
        "game_day_after": shift(hg, 1),   # control: day after any home game
    }
    df_flags["game_day_before"] = shift(hg, -1)

    hours = tipoffs([d.date().isoformat() for d in df.index[hg]])
    h = pd.Series({pd.Timestamp(k): v for k, v in hours.items()}).reindex(df.index)
    early = hg & (h < 19).fillna(False)
    late = hg & (h >= 19).fillna(False)
    print("tip-off hours on home dates:", pd.Series(list(hours.values())).describe().round(2).to_dict())
    print("home games early/late/unknown:", int(early.sum()), int(late.sum()), int(hg.sum() - early.sum() - late.sum()))

    train = df[df["split"] == "train"]
    for label, d in (("train (first 365d, as fit_exposures)", train), ("full window (700d)", df)):
        sub = lambda fl: {k: v.reindex(d.index) for k, v in fl.items()}  # noqa: E731
        base = sub({"home_win": hw, "rain": df["rain"].astype(bool), "hot": df["tmax"] > 85})
        tab, res = fit(d, d["revenue"], base)
        show(f"BAR {label}: baseline fit_exposures design (R2 {res.rsquared:.3f})", tab)
        spec = dict(base, **sub(df_flags))
        tab, res = fit(d, d["revenue"], spec)
        show(f"BAR {label}: + lag/lead flags (R2 {res.rsquared:.3f})", tab)
        split = dict(base)
        split.pop("home_win")
        split.update(sub({
            "win_early": hw & early, "win_late": hw & late,
            "win_after_early": shift(hw & early, 1), "win_after_late": shift(hw & late, 1),
            "game_day_after": shift(hg, 1),
        }))
        tab, res = fit(d, d["revenue"], split)
        show(f"BAR {label}: early (<7pm) vs late tip-off (R2 {res.rsquared:.3f})", tab)

    # MSG arena visits: same-day vs next-day on game nights. features' msg_event uses MSG
    # spikes, so use a plain design here with home_game as the regressor of interest.
    msg = pd.read_parquet(Path(__file__).resolve().parents[3] / "backend/fixtures/msg_visits_daily.parquet")
    msg.index = pd.to_datetime(msg["date"])
    m = df[["dow", "doy", "is_holiday"]].join(msg["visits"], how="inner")
    m["msg_event"] = False
    m["home_game"] = False  # controls zeroed; the game flags go in as `flags`
    g = hg.reindex(m.index)
    w = hw.reindex(m.index)
    mf = {"game_day": g, "game_day_after": shift(hg, 1).reindex(m.index),
          "game_day_before": shift(hg, -1).reindex(m.index)}
    tab, res = fit(m, m["visits"], mf)
    show(f"MSG arena visits/day, full window (R2 {res.rsquared:.3f}); mean {m['visits'].mean():,.0f}", tab)
    mf2 = {"loss_day": g & ~w, "win_day": w, "win_day_after": shift(hw, 1).reindex(m.index),
           "loss_day_after": shift(hg & ~hw, 1).reindex(m.index)}
    tab, _ = fit(m, m["visits"], mf2)
    show("MSG arena visits/day: win vs loss, same day vs day after", tab)
    for nm, e in (("early", early), ("late", late)):
        tab, _ = fit(m, m["visits"], {f"game_{nm}": e.reindex(m.index),
                                      f"after_{nm}": shift(e, 1).reindex(m.index)})
        show(f"MSG arena visits/day: {nm} tip-off same day vs day after", tab)


if __name__ == "__main__":
    main()
