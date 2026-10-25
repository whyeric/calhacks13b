"""R7 boxoffice: do restaurants/bars next to big Manhattan multiplexes fill on big box-office weekends?

Run from backend/:  .venv/bin/python ../experiments/bar/r7-boxoffice/run.py
(needs fetch_weekends.py and kalshi_scan.py to have run; both cache to r2-cache/r7boxoffice_*)

Mechanism (stated before fitting): a blockbuster opens bigger than expected -> more people go to
the big Manhattan multiplexes that weekend -> restaurants and bars within ~300 m of those
multiplexes get more pre/post-show visits, relative to otherwise-similar venues >= 1 km from any
cinema. A Kalshi contract would settle on A (opening-weekend domestic gross vs a strike).

Design. Weekend unit (Fri+Sat+Sun). y = log(near-basket visits) - log(control-basket visits), with
control restricted to the same NAICS codes (bars 722410, full-service 722511, limited 722513) and
reweighted to the near basket's NAICS mix. y ~ year-month FE + holiday-weekend + rain-days + event,
HAC(4). Events: log total weekend gross (all films), log gross of the weekend's new openers,
mega-opening (> $100M 3-day) dummy. Placebo: the same events shifted to the weekend BEFORE
(lead). Secondary: the same test on Mon-Thu after the weekend (spillover, not a placebo).
Train 2024-01-05..2025-09-28, holdout 2025-10-03..2026-09-27, refit independently.

Only aggregates are written; no venue names, ids, addresses or per-venue series.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app import config  # noqa: E402

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
OUT = Path(__file__).resolve().parent
GLOB = str(ROOT / "data/01a16ff2-6017-7e10-86ac-94bf02853813/*.parquet")
START, TRAIN_END, END = date(2024, 1, 5), date(2025, 9, 28), date(2026, 9, 27)
Z = 1.645
CHECK = 35.0
MEGA = 100e6
NEAR_KM, FAR_KM = 0.3, 1.0
NAICS = ("722410", "722511", "722513")

# Target multiplexes (public locations, approximate entrance lat/lon).
MULTIPLEX = {
    "amc_empire25": (40.7566, -73.9890),
    "regal_timessq": (40.7571, -73.9889),
    "amc_lincolnsq": (40.7752, -73.9817),
    "regal_unionsq": (40.7339, -73.9908),
    "amc_34th": (40.7524, -73.9958),
    "amc_84th": (40.7869, -73.9786),
}
# Every other Manhattan cinema we know of: the control basket must be >= 1 km from all of them too.
OTHER_CINEMAS = [
    (40.7431, -73.9768), (40.7385, -73.9899), (40.7185, -73.9883), (40.7150, -74.0157),
    (40.7080, -74.0090), (40.7255, -73.9971), (40.7311, -74.0021), (40.7310, -73.9864),
    (40.8087, -73.9504), (40.7792, -73.9530), (40.7448, -73.9978), (40.7724, -73.9935),
    (40.7641, -73.9740), (40.7210, -73.9880), (40.7620, -73.9660), (40.7780, -73.9550),
]


def hav(lat, lon):
    return (f"6371 * 2 * asin(sqrt(pow(sin(radians(lat - {lat}) / 2), 2) + cos(radians(lat)) * "
            f"cos(radians({lat})) * pow(sin(radians(lon - ({lon})) / 2), 2)))")


# ------------------------------------------------------------------ visits
def baskets() -> tuple[pd.DataFrame, dict]:
    con = duckdb.connect()
    con.execute(f"""
        create table w as select ID_STORE id, DATE_RANGE_START::date ws, NAICS_CODE naics,
            LATITUDE lat, LONGITUDE lon, from_json(VISITS_BY_DAY, '["INTEGER"]') v
        from '{GLOB}' where NAICS_CODE in {NAICS}""")
    con.execute("""create table st as select id, any_value(naics) naics, avg(lat) lat, avg(lon) lon,
            count(*) nwk, avg((list_min(v) = list_max(v))::int) flat from w group by id""")
    nweeks = con.execute("select count(distinct ws) from w").fetchone()[0]
    near = "least(" + ", ".join(hav(*c) for c in MULTIPLEX.values()) + ")"
    allc = "least(" + ", ".join(hav(*c) for c in list(MULTIPLEX.values()) + OTHER_CINEMAS) + ")"
    con.execute(f"""create table keep as select id, naics, {near} km_near, {allc} km_any
        from st where nwk = {nweeks} and flat < 0.05""")
    con.execute(f"""create table grp as select id, naics,
        case when km_near <= {NEAR_KM} then 'near' when km_any >= {FAR_KM} then 'ctrl' end g
        from keep where km_near <= {NEAR_KM} or km_any >= {FAR_KM}""")
    n = con.execute("select g, naics, count(*) n from grp group by all order by all").df()
    df = con.execute("""
        with d as (select w.id, w.ws + (i - 1)::int as date, w.v[i] x from w join grp using (id), range(1, 8) r(i))
        select date, g, naics, sum(x) visits from d join grp using (id) group by all""").df()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[(df.date >= START - timedelta(7)) & (df.date <= END + timedelta(7))], n


def weekend_panel(df: pd.DataFrame, n: pd.DataFrame) -> pd.DataFrame:
    """Per weekend (Friday key): near and NAICS-reweighted control visits for Fri-Sun and Mon-Thu after."""
    d = df.copy()
    ts = pd.to_datetime(d["date"])
    dow = ts.dt.day_of_week
    # Fri/Sat/Sun belong to the weekend whose Friday is date - (dow-4); Mon-Thu after belong to previous Friday
    off = np.where(dow >= 4, dow - 4, dow + 3)
    d["fri"] = (ts - pd.to_timedelta(off, unit="D")).dt.date
    d["part"] = np.where(dow >= 4, "wkd", "post")
    cnt = n.pivot(index="naics", columns="g", values="n")
    share = cnt["near"] / cnt["near"].sum()
    p = d.pivot_table(index=["fri", "part", "naics"], columns="g", values="visits", aggfunc="sum").reset_index()
    p["ctrl_pc"] = p["ctrl"] / p["naics"].map(cnt["ctrl"])
    p["near_pc"] = p["near"] / p["naics"].map(cnt["near"])
    out = []
    for (fri, part), g in p.groupby(["fri", "part"]):
        g = g.set_index("naics")
        row = {"fri": fri, "part": part, "near": g["near_pc"].mul(share).sum(),
               "ctrl": g["ctrl_pc"].mul(share).sum(), "ndays": None}
        for k in NAICS:
            row[f"near_{k}"], row[f"ctrl_{k}"] = g.loc[k, "near_pc"], g.loc[k, "ctrl_pc"]
        out.append(row)
    w = pd.DataFrame(out)
    days = d.groupby(["fri", "part"]).date.nunique().rename("nd").reset_index()
    w = w.merge(days, on=["fri", "part"]).drop(columns="ndays")
    full = w[((w.part == "wkd") & (w.nd == 3)) | ((w.part == "post") & (w.nd == 4))]
    return full


# ------------------------------------------------------------------ box office
def box_office() -> pd.DataFrame:
    b = pd.read_parquet(CACHE / "r7boxoffice_weekends.parquet")
    b["new"] = b["prev"].str.contains("new", case=False) & (b["days"] <= 5)
    g = b.groupby("weekend").agg(total=("gross", "sum"), top1=("gross", "max"))
    g["new_gross"] = b[b.new].groupby("weekend").gross.sum()
    g["top_open"] = b[b.new].groupby("weekend").gross.max()
    g = g.fillna(0)
    top = b[b.new].sort_values("gross").groupby("weekend").tail(1).set_index("weekend")
    g["top_open_title"] = top["title"]
    g["mega"] = g["top_open"] > MEGA
    g.index = pd.to_datetime(g.index).date
    g.index.name = "fri"
    return g.reset_index()


def weather() -> pd.Series:
    w = pd.concat(pd.read_csv(CACHE / f"ghcn_{y}.csv") for y in (2024, 2025, 2026))
    w["date"] = pd.to_datetime(w["DATE"]).dt.date
    return w.set_index("date")["PRCP"]


# ------------------------------------------------------------------ fits
def design(f: pd.DataFrame, ev: list[str]) -> pd.DataFrame:
    ts = pd.to_datetime(f["fri"])
    X = pd.get_dummies(ts.dt.strftime("%Y%m"), prefix="ym", drop_first=True).astype(float)
    X.insert(0, "const", 1.0)
    X["holiday"] = f["holiday"].astype(float)
    X["rain_days"] = f["rain_days"].astype(float)
    for c in ev:
        X[c] = f[c].astype(float)
    X.index = f.index
    return X.loc[:, (X.nunique() > 1) | (X.columns == "const")]


def fit(y, X):
    return sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 4}, use_t=False)


def bh(p: pd.Series) -> pd.Series:
    q = pd.Series(np.nan, index=p.index)
    v = p.dropna().sort_values()
    m = len(v)
    q[v.index] = (v * m / np.arange(1, m + 1))[::-1].cummin()[::-1].clip(upper=1)
    return q


EVENTS = {  # name -> (column, scale label)
    "log_total": "log total weekend gross (per +100% = x ln2)",
    "log_new": "log gross of new openers",
    "mega": "mega opening > $100M",
}


def kalshi() -> list[dict]:
    p = CACHE / "r7boxoffice_events.json"
    hits = json.loads(p.read_text()) if p.exists() else []
    # the keyword scan matches "gross" in names (Grosseto, GMV...); keep only real box-office titles
    return [e for e in hits if "box office" in e["title"].lower() or "domestic gross" in e["title"].lower()]


def run() -> None:
    raw, n = baskets()
    print(n.to_string())
    n.to_csv(OUT / "basket_counts.csv", index=False)
    w = weekend_panel(raw, n)
    bo = box_office()
    prcp = weather()
    w = w.merge(bo, on="fri", how="inner")
    w["log_total"] = np.log(w["total"])
    w["log_new"] = np.log1p(w["new_gross"])
    w["mega"] = w["mega"].astype(float)
    # placebo leads: next weekend's event assigned to this weekend (= the weekend BEFORE an opening)
    bo_i = bo.set_index("fri")
    nxt = [f + timedelta(7) for f in w["fri"]]
    w["lead_log_total"] = np.log(bo_i["total"].reindex(nxt).values)
    w["lead_log_new"] = np.log1p(bo_i["new_gross"].reindex(nxt).values)
    w["lead_mega"] = bo_i["mega"].reindex(nxt).astype(float).values
    hol = set(config.HOLIDAYS)
    w["holiday"] = [any((f + timedelta(k)) in hol for k in range(-1, 4)) for f in w["fri"]]
    w["rain_days"] = [sum(prcp.get(f + timedelta(k + (0 if p == "wkd" else 3)), 0) >= 0.01
                          for k in range(3 if p == "wkd" else 4)) for f, p in zip(w["fri"], w["part"])]
    w = w[(w.fri >= START) & (w.fri <= END)].dropna(subset=["lead_log_total"]).reset_index(drop=True)
    w["split"] = np.where(w["fri"] <= TRAIN_END, "train", "holdout")
    w["y_did"] = np.log(w["near"]) - np.log(w["ctrl"])
    w["y_near"] = np.log(w["near"])
    w["y_ctrl"] = np.log(w["ctrl"])
    for k in NAICS:
        w[f"y_did_{k}"] = np.log(w[f"near_{k}"]) - np.log(w[f"ctrl_{k}"])

    wk = w[w.part == "wkd"]
    megas = wk[wk.mega == 1][["fri", "split", "top_open_title", "top_open", "total"]]
    print(megas.to_string())
    megas.assign(top_open=lambda d: (d.top_open / 1e6).round(1), total=lambda d: (d.total / 1e6).round(1)) \
        .to_csv(OUT / "mega_weekends.csv", index=False)
    pub = wk[["fri", "split", "total", "new_gross", "top_open", "top_open_title", "mega"]]
    pub.to_csv(OUT / "boxoffice_weekends.csv", index=False)

    rows = []
    specs = [  # (label, part, outcome, kind)
        ("main_did", "wkd", "y_did", "test"),
        ("near_only", "wkd", "y_near", "test"),
        ("did_bars", "wkd", "y_did_722410", "test"),
        ("did_fullsvc", "wkd", "y_did_722511", "test"),
        ("did_limited", "wkd", "y_did_722513", "test"),
        ("placebo_lead_did", "wkd", "y_did", "placebo_lead"),
        ("monthu_after_did", "post", "y_did", "test"),
        ("ctrl_only", "wkd", "y_ctrl", "test"),
    ]
    for label, part, yc, kind in specs:
        for ev in EVENTS:
            col = f"lead_{ev}" if kind == "placebo_lead" else ev
            for split in ("train", "holdout", "all"):
                f = w[(w.part == part) & ((w.split == split) if split != "all" else True)].reset_index(drop=True)
                X = design(f, [col] + ([ev] if kind == "placebo_lead" else []))
                if col not in X:
                    continue
                res = fit(f[yc], X)
                b, se = res.params[col], res.bse[col]
                scale = 100 * (np.log(2) if ev != "mega" else 1)  # % per doubling for logs
                nev = int((f[ev] == 1).sum()) if ev == "mega" else len(f)
                rows.append({"spec": label, "event": ev, "split": split, "n_weekends": len(f), "n_event": nev,
                             "pct": scale * b, "lo": scale * (b - Z * se), "hi": scale * (b + Z * se),
                             "p": res.pvalues[col]})
    t = pd.DataFrame(rows)
    tr = t[t.split == "train"].index
    t["bh_train"] = np.nan
    t.loc[tr, "bh_train"] = bh(t.loc[tr, "p"])
    t.to_csv(OUT / "results.csv", index=False, float_format="%.4g")
    pd.set_option("display.width", 250)
    print(f"\ntrain tests (BH family): {len(tr)}")
    print(t.round(3).to_string())

    piv = t.pivot_table(index=["spec", "event"], columns="split", values=["pct", "lo", "hi", "n_event", "bh_train"], aggfunc="first")
    ver = []
    for (s, ev), r in piv.iterrows():
        sig_tr = r[("lo", "train")] > 0 or r[("hi", "train")] < 0
        sig_ho = (r[("lo", "holdout")] > 0 or r[("hi", "holdout")] < 0) and np.sign(r[("pct", "holdout")]) == np.sign(r[("pct", "train")])
        enough = r[("n_event", "train")] >= 10
        ver.append({"spec": s, "event": ev, "train": f"{r[('pct','train')]:+.2f} [{r[('lo','train')]:+.2f}, {r[('hi','train')]:+.2f}]",
                    "n_ev_train": int(r[("n_event", "train")]), "bh": round(r[("bh_train", "train")], 3),
                    "holdout": f"{r[('pct','holdout')]:+.2f} [{r[('lo','holdout')]:+.2f}, {r[('hi','holdout')]:+.2f}]",
                    "n_ev_hold": int(r[("n_event", "holdout")]),
                    "found": bool(sig_tr and enough and sig_ho and r[("bh_train", "train")] <= 0.10)})
    v = pd.DataFrame(ver)
    v.to_csv(OUT / "verdict.csv", index=False)
    print("\nVERDICT\n", v.to_string())

    # event-study around each mega opening: DiD at weekends -2..+2, demeaned by year-month
    es = []
    wk = wk.sort_values("fri").reset_index(drop=True)
    wk["resid"] = wk["y_did"] - wk.groupby(pd.to_datetime(wk["fri"]).dt.strftime("%Y%m"))["y_did"].transform("mean")
    idx = {f: i for i, f in enumerate(wk["fri"])}
    for f0 in wk.loc[wk.mega == 1, "fri"]:
        for k in range(-2, 3):
            j = idx.get(f0 + timedelta(7 * k))
            if j is not None:
                es.append({"mega_fri": f0, "k": k, "resid_pct": 100 * wk.loc[j, "resid"]})
    es = pd.DataFrame(es)
    es_s = es.groupby("k").resid_pct.agg(["mean", "sem", "count"]).reset_index()
    es_s.to_csv(OUT / "event_study.csv", index=False, float_format="%.3f")
    print("\nEVENT STUDY (DiD resid %, by weekends from mega opening)\n", es_s.round(2).to_string())

    # baseline weekend $ for a typical near venue (aggregate mean only)
    base = wk["near"].mean()
    print(f"\nnear basket mean Fri-Sun visits per venue: {base:.1f} -> ${base * CHECK:,.0f}")

    hits = kalshi()
    print(f"\nKalshi box-office events found: {len(hits)}")
    for e in hits:
        print(" ", e["event_ticker"], e["series_ticker"], e["title"])


if __name__ == "__main__":
    run()
