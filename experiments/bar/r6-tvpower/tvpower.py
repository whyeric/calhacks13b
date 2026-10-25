"""R6 tvpower: big-game outcomes (playoff games, OT, close margin, win) vs hourly PJM zone load.

Run from backend/:  .venv/bin/python ../experiments/bar/r6-tvpower/tvpower.py
Needs fetch.py's cache and the PJM CSVs extracted from ~/Downloads/archive (4).zip into r2-cache/r6tvpower_pjm/.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.holiday import USFederalHolidayCalendar
from statsmodels.stats.multitest import multipletests

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
P = "r6tvpower_"
OUT = Path(__file__).parent
ET = ZoneInfo("America/New_York")
Z = 1.645
LINES: list[str] = []

TEAMS = {"eagles": ("phl", "nfl", "21"), "phillies": ("phl", "mlb", "22"), "flyers": ("phl", "nhl", "15"),
         "sixers": ("phl", "nba", "20"), "steelers": ("pit", "nfl", "23"), "penguins": ("pit", "nhl", "16"),
         "pirates": ("pit", "mlb", "23"), "bears": ("chi", "nfl", "3"), "cubs": ("chi", "mlb", "16"),
         "whitesox": ("chi", "mlb", "4"), "blackhawks": ("chi", "nhl", "4"), "bulls": ("chi", "nba", "4")}
# zone -> (city whose games, temperature city, train years, holdout years)
ZONES = {"PJME": ("phl", "phl", range(2002, 2010), range(2010, 2019)),
         "DUQ": ("pit", "pit", range(2005, 2012), range(2012, 2019)),
         "COMED": ("chi", "chi", range(2011, 2015), range(2015, 2019))}
# placebo: far zone with its own temperature, fed the games of a different city
PLACEBO = {"AEP<-phl": ("AEP", "phl", "cmh"), "DOM<-pit": ("DOM", "pit", "ric"), "PJME<-chi": ("PJME", "chi", "phl")}
REG_H = {"nfl": 3.2, "mlb": 3.0, "nhl": 2.5, "nba": 2.25}      # regulation wall-clock length, h
REG_P = {"nfl": 4, "mlb": 9, "nhl": 3, "nba": 4}               # regulation periods
CLOSE = {"nfl": 7, "mlb": 1, "nhl": 1, "nba": 5}               # "close" final margin
POST_H = 2.0
FEATS = ["reg_in_nfl", "reg_in_mlb", "reg_in_nhl", "reg_in_nba", "po_in", "po_post", "ot", "close_late", "win_post"]
TREND = False
SB_DATES = ["2003-01-26", "2004-02-01", "2005-02-06", "2006-02-05", "2007-02-04", "2008-02-03", "2009-02-01",
            "2010-02-07", "2011-02-06", "2012-02-05", "2013-02-03", "2014-02-02", "2015-02-01", "2016-02-07",
            "2017-02-05", "2018-02-04"]
OUTCOME = ["po_in", "po_post", "ot", "close_late", "win_post"]


def say(*a) -> None:
    s = " ".join(str(x) for x in a)
    print(s)
    LINES.append(s)


# ------------------------------------------------------------------ games
def ext_hours(lg: str, periods: int, playoff: bool) -> float:
    """Wall-clock hours played beyond regulation."""
    extra = max(periods - REG_P[lg], 0)
    if extra == 0:
        return 0.0
    if lg == "nhl":
        return 0.6 * extra if playoff else 0.3  # playoff: 20-min periods + intermission; reg: 5-min OT + shootout
    return {"nfl": 0.4, "mlb": 0.33, "nba": 0.25}[lg] * extra


def games() -> pd.DataFrame:
    rows = []
    for team, (city, lg, tid) in TEAMS.items():
        for s in range(2002, 2019):
            for st in (2, 3):
                for ev in json.loads((CACHE / f"{P}espn_{team}_{s}_{st}.json").read_text()).get("events", []):
                    c = ev["competitions"][0]
                    stt = c.get("status", ev.get("status", {}))
                    if not stt.get("type", {}).get("completed", True):
                        continue
                    me = next(x for x in c["competitors"] if x["team"]["id"] == tid)
                    op = next(x for x in c["competitors"] if x["team"]["id"] != tid)
                    if me.get("winner") is None or not me.get("score"):
                        continue
                    start = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(ET)
                    per = int(stt.get("period") or REG_P[lg])
                    po = st == 3
                    margin = abs(me["score"]["value"] - op["score"]["value"])
                    rows.append({"city": city, "team": team, "lg": lg, "playoff": po,
                                 "start": start.replace(tzinfo=None), "periods": per,
                                 "ot": per > REG_P[lg], "ext_h": ext_hours(lg, per, po),
                                 "close": per > REG_P[lg] or margin <= CLOSE[lg], "win": bool(me["winner"]),
                                 "margin": margin, "name": ev.get("shortName", ""),
                                 "note": (c.get("notes") or [{}])[0].get("headline", "")})
    g = pd.DataFrame(rows).drop_duplicates(["team", "start"]).sort_values("start").reset_index(drop=True)
    return g


def overlap(hb: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Share of each hour [hb, hb+1h) covered by any of the intervals [a, b) (hours as float epoch-hours)."""
    out = np.zeros(len(hb))
    pos = {v: i for i, v in enumerate(hb)}
    for s, e in zip(a, b):
        h = np.floor(s)
        while h < e:
            i = pos.get(h)
            if i is not None:
                out[i] += max(0.0, min(e, h + 1) - max(s, h))
            h += 1
    return out


def features(g: pd.DataFrame, hours: pd.DatetimeIndex, shift_h: float = 0.0) -> pd.DataFrame:
    hb = ((hours - pd.Timestamp("2000-01-01")) / pd.Timedelta(hours=1)).to_numpy()
    st = ((g["start"] - pd.Timestamp("2000-01-01")) / pd.Timedelta(hours=1)).to_numpy() + shift_h
    reg_end = st + g["lg"].map(REG_H).to_numpy()
    act_end = reg_end + g["ext_h"].to_numpy()
    po, win, close = g["playoff"].to_numpy(), g["win"].to_numpy(), g["close"].to_numpy()
    f = pd.DataFrame(index=hours)
    for lg in REG_H:
        m = (~po) & (g["lg"].to_numpy() == lg)
        f[f"reg_in_{lg}"] = overlap(hb, st[m], reg_end[m])
    f["po_in"] = overlap(hb, st[po], reg_end[po])
    f["po_post"] = overlap(hb, reg_end[po], reg_end[po] + POST_H)
    f["ot"] = overlap(hb, reg_end, act_end)
    f["close_late"] = overlap(hb, reg_end[close] - 1, reg_end[close])
    f["win_post"] = overlap(hb, act_end[win], act_end[win] + POST_H)
    return f


# ------------------------------------------------------------------ load + weather
def load(zone: str) -> pd.Series:
    d = pd.read_csv(CACHE / f"{P}pjm" / f"{zone}_hourly.csv", parse_dates=["Datetime"])
    d["hb"] = d["Datetime"] - pd.Timedelta(hours=1)  # PJM stamps are hour-ending, EPT
    d = d.drop_duplicates("hb").set_index("hb").sort_index()
    return d[f"{zone}_MW"].rename("mw")


def temp(city: str) -> pd.Series:
    h = json.loads((CACHE / f"{P}temp_{city}.json").read_text())["hourly"]
    s = pd.Series(h["temperature_2m"], index=pd.to_datetime(h["time"]), name="t")
    return s[~s.index.duplicated()].astype(float)


def holidays(idx: pd.DatetimeIndex) -> np.ndarray:
    hol = set(USFederalHolidayCalendar().holidays("2002-01-01", "2019-01-01").date)
    hol |= {d + pd.Timedelta(days=1) for d in USFederalHolidayCalendar().holidays("2002-01-01", "2019-01-01")
            if d.month == 11 and d.day >= 22}  # day after Thanksgiving
    hol = {pd.Timestamp(x).date() for x in hol}
    hol |= {pd.Timestamp(f"{y}-12-{d}").date() for y in range(2002, 2019) for d in (24, 31)}
    return np.isin(idx.date, list(hol))


def controls(df: pd.DataFrame) -> pd.DataFrame:
    t = df["t"]
    hg = df.index.hour // 6
    c = {}
    for k in (35, 50, 60, 70, 80):
        hinge = np.maximum(t - k, 0)
        for gi in range(4):
            c[f"t{k}_h{gi}"] = hinge * (hg == gi)
    for gi in range(4):
        c[f"t_h{gi}"] = t * (hg == gi)
    dm = t.groupby(df.index.date).transform("mean")
    for k in (40, 55, 65, 75):
        c[f"dm{k}"] = np.maximum(dm - k, 0)
    c["dm"] = dm
    c["tlag3"] = t.shift(3).bfill()
    if TREND:  # robustness: day-of-month slope per hour (sunset drifts ~1 h within a spring month)
        for h in range(24):
            c[f"dom_{h}"] = df.index.day * (df.index.hour == h)
    hol = holidays(df.index)
    for h in range(24):
        c[f"hol_{h}"] = (hol & (df.index.hour == h)).astype(float)
    return pd.DataFrame(c, index=df.index)


def panel(zone: str, gcity: str, tcity: str, g: pd.DataFrame, years, shift: bool = False) -> pd.DataFrame:
    y = load(zone)
    y = y[y.index.year.isin(list(years))]
    df = pd.DataFrame({"y": 100 * np.log(y)}).join(temp(tcity), how="inner").dropna()
    df = df.join(features(g[g["city"] == gcity], df.index)).join(controls(df))
    if shift:
        sh = features(g[g["city"] == gcity], df.index, shift_h=-24.0)[OUTCOME].add_prefix("pre_")
        df = df.join(sh)
    df["mw"] = y.reindex(df.index)
    df["zone"] = zone
    df["cell"] = zone + "_" + df.index.strftime("%Y%m") + "_" + df.index.dayofweek.astype(str) + "_" + df.index.hour.astype(str)
    df["date"] = df.index.date
    return df


def fit(df: pd.DataFrame, feats: list[str]):
    ctrl = [c for c in df.columns if c.startswith(("t", "dm", "hol_", "dom_")) and c != "t"]
    X = df[feats + ctrl]
    # controls are zone-specific in pooled fits
    if df["zone"].nunique() > 1:
        X = pd.concat([X[feats]] + [X[ctrl].mul(df["zone"] == z, axis=0).add_suffix(f"_{z}")
                                     for z in df["zone"].unique()], axis=1)
    Xd = X - X.groupby(df["cell"].values).transform("mean")
    yd = df["y"] - df["y"].groupby(df["cell"].values).transform("mean")
    keep = Xd.columns[Xd.abs().sum() > 0]
    groups = pd.factorize(df["date"])[0]
    return sm.OLS(yd, Xd[keep]).fit(cov_type="cluster", cov_kwds={"groups": groups})


def row(res, f: str, df: pd.DataFrame) -> dict:
    b, se = res.params.get(f, np.nan), res.bse.get(f, np.nan)
    return {"b": b, "lo": b - Z * se, "hi": b + Z * se, "p": res.pvalues.get(f, np.nan),
            "n_ev_hours": float(df[f].sum()), "n_days": int(df.loc[df[f] > 0, "date"].nunique())}


# ------------------------------------------------------------------ main
def main() -> None:
    g = games()
    g.drop(columns=["name"]).to_csv(OUT / "games.csv", index=False)
    say(f"games: {len(g)} ({int(g['playoff'].sum())} playoff), by city:",
        g.groupby(["city", "playoff"]).size().to_dict())

    # ---- main fits: per zone + pooled, train and holdout fitted independently
    rows, pan = [], {}
    for per in ("train", "holdout"):
        parts = []
        for zone, (gc, tc, tr, ho) in ZONES.items():
            df = panel(zone, gc, tc, g, tr if per == "train" else ho)
            pan[(zone, per)] = df
            parts.append(df)
            res = fit(df, FEATS)
            for f in FEATS:
                rows.append({"zone": zone, "period": per, "feat": f, **row(res, f, df)})
        pooled = pd.concat(parts)
        res = fit(pooled, FEATS)
        for f in FEATS:
            rows.append({"zone": "pooled", "period": per, "feat": f, **row(res, f, pooled)})
        del pooled
    r = pd.DataFrame(rows)
    r = r[r["b"].notna()]  # DUQ has no NBA team
    tr = r[r.period == "train"].copy()
    tr["q"] = multipletests(tr["p"], alpha=0.10, method="fdr_bh")[1]
    m = tr.merge(r[r.period == "holdout"], on=["zone", "feat"], suffixes=("", "_ho"))
    m["found"] = ((m["q"] < 0.10) & (m["n_days"] >= 10) & (np.sign(m["b"]) == np.sign(m["b_ho"]))
                  & ((m["lo_ho"] > 0) | (m["hi_ho"] < 0)))
    m.to_csv(OUT / "results.csv", index=False)
    say(f"\nMAIN: {len(tr)} train tests, BH 10%. effect = % load per full game-hour (100·log MW)")
    for _, x in m.iterrows():
        say(f"{x.zone:7s} {x.feat:11s} tr {x.b:+6.2f} [{x.lo:+6.2f},{x.hi:+6.2f}] d={x.n_days:4d} q={x.q:.3f} | "
            f"ho {x.b_ho:+6.2f} [{x.lo_ho:+6.2f},{x.hi_ho:+6.2f}] d={x.n_days_ho:4d} {'FOUND' if x.found else ''}")

    # ---- placebo (a): far zone, same games, full period
    say("\nPLACEBO far zone (full period, games of another city; should be ~0 unless national audience):")
    prow = []
    for name, (zone, gc, tc) in PLACEBO.items():
        yrs = range(2011, 2019) if gc == "chi" else (range(2005, 2019) if gc == "pit" else range(2005, 2019))
        df = panel(zone, gc, tc, g, yrs)
        own_zone = {"phl": "PJME", "pit": "DUQ", "chi": "COMED"}[gc]
        own = panel(own_zone, gc, gc, g, yrs)
        r_pl, r_own = fit(df, FEATS), fit(own, FEATS)
        for f in FEATS:
            a, b = row(r_pl, f, df), row(r_own, f, own)
            prow.append({"placebo": name, "feat": f, **{k + "_pl": v for k, v in a.items()},
                         **{k + "_own": v for k, v in b.items()}})
            say(f"{name:10s} {f:11s} placebo {a['b']:+6.2f} [{a['lo']:+6.2f},{a['hi']:+6.2f}]   own zone same yrs "
                f"{b['b']:+6.2f} [{b['lo']:+6.2f},{b['hi']:+6.2f}]")
    pd.DataFrame(prow).to_csv(OUT / "placebo_farzone.csv", index=False)

    # ---- placebo (b): outcome features shifted -24 h, fitted alongside the real ones
    say("\nPLACEBO day-before (outcome features shifted -24 h; full period, own zone):")
    for zone, (gc, tc, tr_, ho) in ZONES.items():
        df = panel(zone, gc, tc, g, list(tr_) + list(ho), shift=True)
        res = fit(df, FEATS + ["pre_" + f for f in OUTCOME])
        for f in OUTCOME:
            a, b = row(res, "pre_" + f, df), row(res, f, df)
            say(f"{zone:6s} {f:11s} day-before {a['b']:+6.2f} [{a['lo']:+6.2f},{a['hi']:+6.2f}]  real {b['b']:+6.2f} "
                f"[{b['lo']:+6.2f},{b['hi']:+6.2f}]")

    # ---- robustness: add a within-month day-of-month slope per hour, rerun the day-before placebo
    global TREND
    TREND = True
    say("\nROBUSTNESS (adds day-of-month × hour slope; full period, own zone): real vs day-before")
    for zone, (gc, tc, tr_, ho) in ZONES.items():
        df = panel(zone, gc, tc, g, list(tr_) + list(ho), shift=True)
        res = fit(df, FEATS + ["pre_" + f for f in OUTCOME])
        for f in OUTCOME:
            a, b = row(res, "pre_" + f, df), row(res, f, df)
            say(f"{zone:6s} {f:11s} real {b['b']:+6.2f} [{b['lo']:+6.2f},{b['hi']:+6.2f}]  day-before {a['b']:+6.2f} "
                f"[{a['lo']:+6.2f},{a['hi']:+6.2f}]")
    for name, (zone, gc, tc) in PLACEBO.items():
        yrs = range(2011, 2019) if gc == "chi" else range(2005, 2019)
        df = panel(zone, gc, tc, g, yrs)
        res = fit(df, FEATS)
        say(f"{name:10s} far-zone po_in {row(res, 'po_in', df)['b']:+5.2f} [{row(res, 'po_in', df)['lo']:+5.2f},"
            f"{row(res, 'po_in', df)['hi']:+5.2f}]  po_post {row(res, 'po_post', df)['b']:+5.2f} "
            f"[{row(res, 'po_post', df)['lo']:+5.2f},{row(res, 'po_post', df)['hi']:+5.2f}]  reg_in_nhl "
            f"{row(res, 'reg_in_nhl', df)['b']:+5.2f}  reg_in_mlb {row(res, 'reg_in_mlb', df)['b']:+5.2f}")
    TREND = False

    # ---- per-game event residuals for the biggest games (full-period fit without game features)
    say("\nBIG GAMES: mean residual (% load) over game hours / 2 h after, vs no-game model (full period):")
    for zone, (gc, tc, tr_, ho) in ZONES.items():
        df = panel(zone, gc, tc, g, list(tr_) + list(ho))
        res = fit(df, [f for f in FEATS if f.startswith("reg_in")])
        Xc = [c for c in res.params.index]
        Xd = df[Xc] - df[Xc].groupby(df["cell"].values).transform("mean")
        resid = (df["y"] - df["y"].groupby(df["cell"].values).transform("mean")) - Xd @ res.params
        gg = g[(g.city == gc) & g.playoff & g.start.dt.year.isin(list(tr_) + list(ho))].copy()
        gg["notes"] = gg["note"].str.upper()
        big = gg[gg["notes"].str.contains("SUPER BOWL|STANLEY CUP|WORLD SERIES|NBA FINALS|^NFC CHAMP|^AFC CHAMP|GAME 7")]
        for _, x in big.iterrows():
            s = x.start.floor("h")
            e = s + pd.Timedelta(hours=REG_H[x.lg] + x.ext_h)
            ins = resid[(resid.index >= s) & (resid.index < e)].mean()
            post = resid[(resid.index >= e) & (resid.index < e + pd.Timedelta(hours=2))].mean()
            mw = df["mw"][(df.index >= s) & (df.index < e)].mean()
            say(f"{zone:6s} {x.start:%Y-%m-%d %H:%M} {x.team:10s} {x.note[:34]:34s} win={int(x.win)} ot={int(x.ot)} "
                f"in {ins:+5.1f}%  post {post:+5.1f}%  (~{mw * ins / 100:+6.0f} MW)")

    # ---- Super Bowl Sunday 18-22h in every zone: local team playing or not (is the dip local or national?)
    say("\nSUPER BOWL 18:00-22:00 ET mean residual (% load), every zone, by whether a local team played:")
    sb = pd.to_datetime(SB_DATES)
    local = {"PJME": {"2005-02-06", "2018-02-04"}, "DUQ": {"2006-02-05", "2009-02-01", "2011-02-06"}, "COMED": set()}
    for zone, tc, gc, yrs in (("PJME", "phl", "phl", range(2003, 2019)), ("DUQ", "pit", "pit", range(2006, 2019)),
                              ("COMED", "chi", "chi", range(2011, 2019)), ("AEP", "cmh", "phl", range(2005, 2019)),
                              ("DOM", "ric", "pit", range(2006, 2019))):
        df = panel(zone, gc, tc, g, yrs)
        res = fit(df, [f for f in FEATS if f.startswith("reg_in")])
        Xd = df[res.params.index] - df[res.params.index].groupby(df["cell"].values).transform("mean")
        resid = (df["y"] - df["y"].groupby(df["cell"].values).transform("mean")) - Xd @ res.params
        vals = {d: resid[(resid.index >= d + pd.Timedelta(hours=18)) & (resid.index < d + pd.Timedelta(hours=22))].mean()
                for d in sb if d.year in yrs}
        loc = [v for d, v in vals.items() if str(d.date()) in local.get(zone, set())]
        oth = [v for d, v in vals.items() if str(d.date()) not in local.get(zone, set())]
        sd = resid[(resid.index.hour >= 18) & (resid.index.hour < 22)].groupby(resid.index[(resid.index.hour >= 18) & (resid.index.hour < 22)].date).mean().std()
        say(f"{zone:6s} local-team SBs: {np.round(loc, 1).tolist()}  other SBs: mean {np.mean(oth):+.2f}% "
            f"(n={len(oth)}, se {np.std(oth, ddof=1) / np.sqrt(len(oth)):.2f})  | SD of any evening's residual {sd:.2f}%")

    # ---- EXPLORATORY (post hoc, after seeing the big-game table): NFL playoff games only, own vs far zone
    say("\nEXPLORATORY post hoc: NFL playoff game hours, mean residual own zone vs far zone (not in the BH family)")
    for gc, own, far, ftc, yrs in (("pit", "DUQ", "DOM", "ric", range(2006, 2019)), ("phl", "PJME", "AEP", "cmh", range(2005, 2019)),
                                   ("pit", "DUQ", "PJME", "phl", range(2006, 2019))):
        out = {}
        for zone, tc in ((own, gc), (far, ftc)):
            df = panel(zone, gc, tc, g, yrs)
            res = fit(df, [f for f in FEATS if f.startswith("reg_in")])
            Xd = df[res.params.index] - df[res.params.index].groupby(df["cell"].values).transform("mean")
            resid = (df["y"] - df["y"].groupby(df["cell"].values).transform("mean")) - Xd @ res.params
            gg = g[(g.city == gc) & g.playoff & (g.lg == "nfl") & g.start.dt.year.isin(list(yrs))]
            out[zone] = np.array([resid[(resid.index >= x.start.floor("h")) &
                                        (resid.index < x.start.floor("h") + pd.Timedelta(hours=4))].mean()
                                  for _, x in gg.iterrows()])
        a, b = out[own], out[far]
        d = a - b
        say(f"{gc} NFL playoff games n={len(a)}: own {own} {a.mean():+.2f}% (se {a.std(ddof=1) / np.sqrt(len(a)):.2f}), "
            f"far {far} {b.mean():+.2f}% (se {b.std(ddof=1) / np.sqrt(len(b)):.2f}), own−far {d.mean():+.2f}% "
            f"(se {d.std(ddof=1) / np.sqrt(len(d)):.2f}); own<0 in {int((a < 0).sum())}/{len(a)}")

    # ---- dollars: MWh per event for the pooled holdout betas
    say("\nDOLLARS (holdout betas × zone mean MW in those hours × hours, at $40/MWh):")
    for zone in ZONES:
        df = pan[(zone, "holdout")]
        for f in OUTCOME:
            x = m[(m.zone == zone) & (m.feat == f)].iloc[0]
            mw = df.loc[df[f] > 0, "mw"].mean()
            hrs = {"po_in": None, "po_post": POST_H, "ot": None, "close_late": 1.0, "win_post": POST_H}[f]
            hrs = hrs if hrs is not None else df[f].sum() / max(df.loc[df[f] > 0, "date"].nunique(), 1)
            mwh = x.b_ho / 100 * mw * hrs
            say(f"{zone:6s} {f:11s} beta_ho {x.b_ho:+5.2f}% × {mw:7.0f} MW × {hrs:4.2f} h = {mwh:+7.1f} MWh "
                f"= ${mwh * 40:+9,.0f} per event  [90% CI ${x.lo_ho / 100 * mw * hrs * 40:+,.0f} .. "
                f"${x.hi_ho / 100 * mw * hrs * 40:+,.0f}]")

    (OUT / "output.txt").write_text("\n".join(LINES) + "\n")


if __name__ == "__main__":
    main()
