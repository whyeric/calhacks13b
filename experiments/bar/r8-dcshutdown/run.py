"""R8 dcshutdown: do federal shutdowns empty downtown DC?  Capital Bikeshare event study.

Run from backend/:  .venv/bin/python ../experiments/bar/r8-dcshutdown/run.py
(after build.py has written r2-cache/r8dc_station_day.parquet; fetch_kalshi.py feeds hedge.py)

Station groups (fixed before fitting, by distance <400 m to hand-placed centroids):
  fed   Federal Triangle, L'Enfant Plaza / SW federal center (HHS, Education, USDA, DOE, HUD, FAA, NASA), DOL
  navy  Navy Yard (DOT HQ, Navy Yard; also heavily residential)
  fbot  Foggy Bottom (State, Interior, OPM, GSA; also GWU campus)
  kst   Farragut / McPherson / K St (mostly private-sector offices)
  res   U St, Logan, Columbia Heights, Adams Morgan, Petworth, Capitol Hill / Eastern Market, Lincoln Park
  mall  stations on the National Mall and memorials (museums close in a shutdown)
Outcome: daily station touches (trip starts + ends), summed over stations open the whole season
(touches in both September and February). Season = Sep 1 .. Feb 28/29.

Specs: A = DOW + year-month FE; B = DOW + ISO-week FE + season FE. Both add federal holidays,
the Dec 24-Jan 1 window, extra OPM closure days and DCA (USW00013743) weather. Separate dummies for
every shutdown, plus a 14-day lead and 7-day lag around each long one. HAC(10) errors.
Pre-COVID sample (seasons 2012..2019) identifies 2013 and 2018-19; post sample (2021..2025) 2025.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from pandas.tseries.holiday import USFederalHolidayCalendar
from statsmodels.stats.multitest import multipletests

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
OUT = Path(__file__).resolve().parent
Z = 1.645

CENT = {
    "fed": [(38.8940, -77.0280), (38.8850, -77.0220), (38.8850, -77.0150)],
    "navy": [(38.8755, -77.0040)],
    "fbot": [(38.8945, -77.0440)],
    "kst": [(38.9020, -77.0390), (38.9010, -77.0330)],
    "res": [(38.9170, -77.0320), (38.9280, -77.0330), (38.9215, -77.0425), (38.8840, -76.9960),
            (38.8900, -76.9890), (38.9420, -77.0250), (38.9095, -77.0300)],
}
MALL = ("^Jefferson Dr &", "Madison Dr", "Lincoln Memorial", "Henry Bacon", "Jefferson Memorial", "Ohio Dr",
        "MLK & FDR", "17th St & Independence", "Smithsonian", "National Mall")
GROUPS = ["fed", "navy", "fbot", "kst", "res", "mall"]

# Days a shutdown was in effect at 10:00 ET (OPM notice), last day before staff returned.
SHUT = {
    "s2013": ("2013-10-01", "2013-10-16"),
    "s2018a": ("2018-01-20", "2018-01-22"),
    "s2018": ("2018-12-22", "2019-01-25"),  # partial: ~25% of discretionary funding lapsed
    "s2025": ("2025-10-01", "2025-11-12"),
    "s2026a": ("2026-01-31", "2026-02-03"),
}
LONG = ("s2013", "s2018", "s2025")
OPM_EXTRA = ["2012-12-24", "2014-12-26", "2015-12-24", "2018-12-05", "2018-12-24", "2019-12-24",
             "2024-12-24", "2025-01-09", "2025-12-24", "2025-12-26"]
PRE, POST = list(range(2012, 2020)), list(range(2021, 2026))


# ------------------------------------------------------------------ data
def stations(df: pd.DataFrame) -> pd.Series:
    new = df[df.lat.notna()].groupby("name").agg(lat=("lat", "median"), lng=("lng", "median"))
    st = df.groupby("key").agg(name=("name", "last"))
    gb = pd.DataFrame(json.load(open(CACHE / "r8dc_gbfs_station_info.json"))["data"]["stations"]).set_index("short_name")
    st["lat"] = new.lat.reindex(st.name).values
    st["lng"] = new.lng.reindex(st.name).values
    st["lat"] = st.lat.fillna(gb.lat.reindex(st.index))
    st["lng"] = st.lng.fillna(gb.lon.reindex(st.index))
    grp = pd.Series(None, index=st.index, dtype=object)
    best = pd.Series(np.inf, index=st.index)
    for k, cs in CENT.items():
        for a, b in cs:
            d = np.hypot((st.lat - a) * 111000, (st.lng - b) * 111000 * np.cos(np.radians(38.9)))
            m = (d < 400) & (d < best)
            grp[m], best[m] = k, d[m]
    grp[st.name.str.contains("|".join(MALL), regex=True, na=False)] = "mall"
    grp[st.name.str.contains("DOL", na=False)] = "fed"
    return grp


def season_of(d: pd.Series) -> pd.Series:
    return np.where(d.dt.month >= 9, d.dt.year, d.dt.year - 1)


def daily(df: pd.DataFrame, grp: pd.Series, months=((9,), (2,)), window=lambda m: (m >= 9) | (m <= 2),
          season=season_of) -> pd.DataFrame:
    """Group x day touches (all-day and by band), over stations active in both edge months of the season."""
    df = df[window(df.date.dt.month)].copy()
    df["grp"] = grp.reindex(df.key).values
    df = df[df.grp.notna()]
    df["season"] = season(df.date)
    first, last = months
    act = df.groupby(["season", "key"]).date.agg(
        lambda s: s.dt.month.isin(first).any() and s.dt.month.isin(last).any())
    keep = act[act].reset_index()[["season", "key"]]
    df = df.merge(keep, on=["season", "key"])
    out = df.pivot_table(index="date", columns="grp", values="n", aggfunc="sum")
    for b in ("am", "lunch", "pm"):
        out = out.join(df[df.band == b].pivot_table(index="date", columns="grp", values="n", aggfunc="sum")
                       .add_suffix(f"_{b}"))
    nst = keep.merge(df[["key", "grp"]].drop_duplicates(), on="key").groupby(["season", "grp"]).size().unstack()
    return out, nst


def weather() -> pd.DataFrame:
    w = pd.read_csv(CACHE / "r8dc_noaa_dca.csv", usecols=["DATE", "PRCP", "SNOW", "SNWD", "TMAX", "TMIN"],
                    parse_dates=["DATE"]).set_index("DATE")
    return pd.DataFrame({"prcp": w.PRCP / 254, "snow": (w.SNOW.fillna(0) > 0).astype(int),
                         "snwd": (w.SNWD.fillna(0) > 0).astype(int), "tmax": w.TMAX / 10 * 9 / 5 + 32})


def design(idx: pd.DatetimeIndex) -> pd.DataFrame:
    X = pd.DataFrame(index=idx)
    X["dow"] = idx.dayofweek
    X["weekday"] = (idx.dayofweek < 5).astype(int)
    X["ym"] = idx.strftime("%Y-%m")
    X["wk"] = idx.isocalendar().week.values.astype(int)
    X["season"] = season_of(pd.Series(idx)).astype(int) if True else 0
    hol = USFederalHolidayCalendar().holidays(idx.min(), idx.max())
    X["hol"] = idx.isin(hol).astype(int)
    X["xmas"] = (((idx.month == 12) & (idx.day >= 24)) | ((idx.month == 1) & (idx.day == 1))).astype(int)
    X["opm"] = idx.isin(pd.to_datetime(OPM_EXTRA)).astype(int)
    X["fri_tg"] = idx.isin(hol[hol.month == 11] + pd.Timedelta(days=1)).astype(int) * (idx.month == 11)
    X = X.join(weather())
    X["rain"] = (X.prcp >= 0.1).astype(int)
    X["tmax2"] = (X.tmax - 50) ** 2
    for k, (a, b) in SHUT.items():
        X[k] = ((idx >= a) & (idx <= b)).astype(int)
        if k in LONG:
            X[f"{k}_lead"] = ((idx >= pd.Timestamp(a) - pd.Timedelta(days=14)) & (idx < a)).astype(int)
            X[f"{k}_lag"] = ((idx > b) & (idx <= pd.Timestamp(b) + pd.Timedelta(days=7))).astype(int)
    return X


CTRL = "C(dow) + hol + xmas + opm + fri_tg + prcp + rain + snow + snwd + tmax + tmax2"
FE = {"A": "C(ym)", "B": "C(wk) + C(season)"}


def fit(d: pd.DataFrame, y: str, spec: str, terms: list[str]):
    d = d.dropna(subset=[y] + terms)
    keep = [t for t in terms if d[t].sum() > 0]
    f = f"{y} ~ {' + '.join(keep)} + {CTRL} + {FE[spec]}"
    m = smf.ols(f, d).fit(cov_type="HAC", cov_kwds={"maxlags": 10})
    return m, len(d)


def row(m, n, term, **kw):
    b, se = m.params[term], m.bse[term]
    return dict(**kw, term=term, beta=b, pct=100 * (np.exp(b) - 1), lo=100 * (np.exp(b - Z * se) - 1),
                hi=100 * (np.exp(b + Z * se) - 1), p=m.pvalues[term], n=n, n_event=int(m.model.data.frame[term].sum()))


def dhs_lapse(raw: pd.DataFrame, grp: pd.Series) -> pd.DataFrame:
    """Basis-risk check: the DHS-only lapse of 2026-02-14..04-30 settles Kalshi 'at least partially shut
    down' contracts YES, but furloughs almost nobody downtown. Window Feb 1..Jun 30 of 2023..2026."""
    D, _ = daily(raw[raw.date.dt.year >= 2023], grp, months=((2,), (6,)), window=lambda m: (m >= 2) & (m <= 6),
                 season=lambda d: d.dt.year)
    X = design(D.index)
    X["season"] = X.index.year
    X["dhs"] = ((X.index >= "2026-02-14") & (X.index <= "2026-04-30")).astype(int)
    for c in D.columns:
        X[f"l_{c}"] = np.log(D[c].clip(lower=1))
    X["did"] = X.l_fed - X.l_res
    X["did_lunch"] = X.l_fed_lunch - X.l_res_lunch
    W = X[X.weekday == 1].copy()
    rows = []
    for y in ("did", "l_fed", "did_lunch", "l_res"):
        m, n = fit(W, y, "B", ["dhs", "s2026a"])
        pb = []
        for s in (2023, 2024, 2025):
            for fa in pd.date_range(f"{s}-02-01", f"{s}-04-15", freq="7D"):
                W["fake"] = ((W.index >= fa) & (W.index <= fa + pd.Timedelta(days=75))).astype(int)
                pb.append(fit(W, y, "B", ["dhs", "s2026a", "fake"])[0].params["fake"])
        pb = np.array(pb)
        q05, q95 = np.quantile(pb, [0.05, 0.95])
        b = m.params["dhs"]
        rows.append(dict(event="dhs2026", y=y, pct=100 * (np.exp(b) - 1), ri_lo=100 * (np.exp(b - q95) - 1),
                         ri_hi=100 * (np.exp(b - q05) - 1),
                         ri_p=(1 + (np.abs(pb) >= abs(b)).sum()) / (1 + len(pb)), n=n, n_placebo=len(pb)))
    return pd.DataFrame(rows)


def main() -> None:
    raw = pd.read_parquet(CACHE / "r8dc_station_day.parquet")
    raw["date"] = pd.to_datetime(raw.date)
    grp = stations(raw)
    D, nst = daily(raw, grp)
    print("stations per season (balanced):\n", nst.to_string())
    D = D[D.index.map(lambda t: season_of(pd.Series([t]))[0]).isin(PRE + POST)]
    X = design(D.index)
    for c in D.columns:
        X[f"l_{c}"] = np.log(D[c].clip(lower=1))
    for suf in ("", "_am", "_lunch", "_pm"):
        X[f"did{suf}"] = X[f"l_fed{suf}"] - X[f"l_res{suf}"]
        X[f"didk{suf}"] = X[f"l_kst{suf}"] - X[f"l_res{suf}"]
    X.to_parquet(CACHE / "r8dc_design.parquet")

    rows = []
    samples = {"pre": X[X.season.isin(PRE)], "post": X[X.season.isin(POST)]}
    events = {"pre": ["s2013", "s2018a", "s2018"], "post": ["s2025", "s2026a"]}
    outcomes = ["did", "l_fed", "l_res", "l_mall", "l_kst", "didk", "l_navy", "l_fbot",
                "did_am", "did_lunch", "did_pm", "l_fed_lunch", "l_fed_am", "l_fed_pm"]
    for sname, S in samples.items():
        ev = events[sname]
        terms = ev + [f"{k}_{t}" for k in ev if k in LONG for t in ("lead", "lag")]
        for daytype, sub in (("weekday", S[S.weekday == 1]), ("weekend", S[S.weekday == 0])):
            for y in outcomes:
                if daytype == "weekend" and y not in ("did", "l_fed", "l_res", "l_mall"):
                    continue
                for spec in ("A", "B"):
                    m, n = fit(sub, y, spec, terms)
                    for t in terms:
                        if t in m.params:
                            rows.append(row(m, n, t, sample=sname, daytype=daytype, y=y, spec=spec))
    R = pd.DataFrame(rows)

    # Placebo 2: fake shutdowns at the real calendar dates in each control season (weekdays, spec B).
    prow = []
    for sname, real in (("pre", "s2018"), ("post", "s2025"), ("pre", "s2013")):
        S = samples[sname]
        S = S[S.weekday == 1].copy()
        a, b = (pd.Timestamp(x) for x in SHUT[real])
        ev = events[sname]
        for s in sorted(S.season.unique()):
            if s == season_of(pd.Series([a]))[0]:
                continue
            shift = s - season_of(pd.Series([a]))[0]
            fa, fb = a + pd.DateOffset(years=int(shift)), b + pd.DateOffset(years=int(shift))
            if any((fa <= pd.Timestamp(SHUT[k][1])) and (fb >= pd.Timestamp(SHUT[k][0])) for k in SHUT):
                continue
            S["fake"] = ((S.index >= fa) & (S.index <= fb)).astype(int)
            for y in ("did", "l_fed", "did_lunch"):
                m, n = fit(S, y, "B", ev + ["fake"])
                prow.append(row(m, n, "fake", sample=sname, daytype="weekday", y=y, spec="B",
                                placebo_of=real, fake_season=int(s)))
    P = pd.DataFrame(prow)

    # Randomization inference: HAC CIs are too narrow for a 3-6 week block (fake same-date windows above
    # come out "significant" about half the time). Slide a fake window of the real length across every
    # control season (start every 7 days, Sep 1..end of Feb, no overlap with a real shutdown), refit,
    # and use the placebo distribution of beta as the null. RI 90% CI = beta - [q95, q05] of placebos.
    RI_Y = ["did", "l_fed", "did_lunch", "l_fed_lunch", "did_am", "did_pm", "l_kst", "l_res", "l_mall"]
    ri_rows, null = [], []
    for sname, real in (("pre", "s2013"), ("pre", "s2018"), ("post", "s2025")):
        a, b = (pd.Timestamp(x) for x in SHUT[real])
        L = b - a
        for daytype, S in (("weekday", samples[sname][samples[sname].weekday == 1]),
                           ("weekend", samples[sname][samples[sname].weekday == 0])):
            S = S.copy()
            ys = RI_Y if daytype == "weekday" else ["did", "l_fed"]
            ev = events[sname]
            starts = []
            for s in sorted(S.season.unique()):
                if s == season_of(pd.Series([a]))[0]:
                    continue
                for fa in pd.date_range(f"{s}-09-01", f"{s + 1}-02-28", freq="7D"):
                    fb = fa + L
                    if fb > pd.Timestamp(f"{s + 1}-02-28"):
                        break
                    if not any(fa <= pd.Timestamp(SHUT[k][1]) and fb >= pd.Timestamp(SHUT[k][0]) for k in SHUT):
                        starts.append((fa, fb))
            for y in ys:
                real_b = R[(R["sample"] == sname) & (R.daytype == daytype) & (R.y == y) & (R.spec == "B")
                           & (R.term == real)].beta.iloc[0]
                pb = []
                for fa, fb in starts:
                    S["fake"] = ((S.index >= fa) & (S.index <= fb)).astype(int)
                    m, _ = fit(S, y, "B", ev + ["fake"])
                    pb.append(m.params["fake"])
                pb = np.array(pb)
                null += [dict(event=real, daytype=daytype, y=y, fake_start=fa.date(), beta=v)
                         for (fa, _), v in zip(starts, pb)]
                q05, q95 = np.quantile(pb, [0.05, 0.95])
                ri_rows.append(dict(event=real, daytype=daytype, y=y, pct=100 * (np.exp(real_b) - 1),
                                    ri_lo=100 * (np.exp(real_b - q95) - 1), ri_hi=100 * (np.exp(real_b - q05) - 1),
                                    ri_p=(1 + (np.abs(pb) >= abs(real_b)).sum()) / (1 + len(pb)),
                                    ri_p_one=(1 + (pb <= real_b).sum()) / (1 + len(pb)),
                                    null_sd=100 * pb.std(), n_placebo=len(pb)))
    RI = pd.DataFrame(ri_rows)
    famri = (RI.daytype == "weekday") & ~RI.y.isin(["l_res", "l_mall"])
    RI["bh_q"] = np.nan
    RI.loc[famri, "bh_q"] = multipletests(RI.loc[famri, "ri_p"], method="fdr_bh")[1]
    RI.to_csv(OUT / "results_ri.csv", index=False)
    pd.DataFrame(null).to_csv(CACHE / "r8dc_ri_null.csv", index=False)
    print(RI.round(3).to_string())
    print("RI BH family size", int(famri.sum()))

    # BH over every non-placebo shutdown coefficient on weekdays (leads/lags and placebo outcomes excluded).
    fam = (R.daytype == "weekday") & R.term.isin(["s2013", "s2018", "s2025"]) & ~R.y.isin(["l_res", "l_mall"])
    R["bh_q"] = np.nan
    R.loc[fam, "bh_q"] = multipletests(R.loc[fam, "p"], method="fdr_bh")[1]
    R.to_csv(OUT / "results.csv", index=False)
    P.to_csv(OUT / "placebo_fake_dates.csv", index=False)
    pd.set_option("display.width", 250)
    cols = ["sample", "daytype", "y", "spec", "term", "pct", "lo", "hi", "p", "n", "n_event", "bh_q"]
    print(R[R.term.isin(["s2013", "s2018", "s2025", "s2026a", "s2018a"]) & (R.spec == "B")][cols].round(3).to_string())
    print(R[R.term.str.contains("lead|lag")][cols].round(3).to_string())
    print("BH family size", int(fam.sum()))
    print(P.groupby(["placebo_of", "y"]).pct.describe().round(2).to_string())
    print(P[["placebo_of", "y", "fake_season", "pct", "lo", "hi", "p"]].round(3).to_string())
    H = dhs_lapse(raw, grp)
    H.to_csv(OUT / "results_dhs.csv", index=False)
    print(H.round(3).to_string())


if __name__ == "__main__":
    main()
