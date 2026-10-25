"""R7 fidi: do stock-market moves and Fed/CPI surprises move after-work traffic at FiDi bars?

Run from backend/:  .venv/bin/python ../experiments/bar/r7-fidi/run.py   (after fetch.py)

Chain (stated before fitting): a big S&P 500 move or a Fed/CPI surprise changes Wall Street's
mood and hours (late nights on crash days, celebrating on rally days), which changes after-work
visits to bars and full-service restaurants in the Financial District and Midtown East. A
residential basket (Upper West / Upper East Side) is the placebo: it should show nothing.

Visits: raw Dewey weekly patterns -> daily, balanced panel (stores present every week, <5% flat
weeks), summed per ZIP basket over NAICS 722410 (drinking places) + 722511 (full-service).
Model: log(visits) ~ DOW + year-month FE + holiday + rain (GHCN Central Park >= 0.01 in, >= 0.5 in)
+ tmax, tmax^2 + event terms, HAC(7), z = 1.645. Train 2024-01-01..2025-03-31, holdout
2025-04-01..2026-09-27, refit independently. BH at 10% over every train test.

Only basket aggregates are written; no venue names, ids, addresses or per-venue series.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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
START, TRAIN_END, END = date(2024, 1, 1), date(2025, 3, 31), date(2026, 9, 27)
Z = 1.645
CHECK = 35.0  # assumed $ per Dewey visit (as in earlier rounds)
BIG = 1.5     # |S&P daily return| threshold, %
ET = ZoneInfo("America/New_York")
SEED = 7

BASKETS = {
    "fidi": ("10004", "10005", "10006", "10038", "10280"),
    "mideast": ("10017", "10022"),
    "resid_placebo": ("10025", "10028"),
}
NAICS = ("722410", "722511")

# Model families; every term in TERMS is one train test per basket.
MODELS = {
    "move": ["big_up", "big_down", "big_up_next", "big_down_next"],
    "macro": ["fomc_surp", "fomc_nosurp", "cpi_surp", "cpi_nosurp"],
    "weekday": ["big_mon_wed", "big_thu_fri"],
    "cont": ["ret", "absret", "dvix"],
}


# ------------------------------------------------------------------ visits
def visits() -> tuple[pd.DataFrame, dict]:
    con = duckdb.connect()
    con.execute(f"""
        create table w as select ID_STORE id, DATE_RANGE_START::date ws, NAICS_CODE naics,
            POSTAL_CODE zip, from_json(VISITS_BY_DAY, '["INTEGER"]') v
        from '{GLOB}' where NAICS_CODE in {NAICS}""")
    con.execute("""
        create table st as select id, any_value(zip) zip, count(*) nwk,
            avg((list_min(v) = list_max(v))::int) flat from w group by id""")
    nweeks = con.execute("select count(distinct ws) from w").fetchone()[0]
    con.execute(f"create table keep as select * from st where nwk = {nweeks} and flat < 0.05")
    case = " ".join(f"when zip in {z} then '{k}'" for k, z in BASKETS.items())
    con.execute(f"create table kb as select id, case {case} end b from keep")
    n = dict(con.execute("select b, count(*) from kb where b is not null group by b").fetchall())
    df = con.execute("""
        select w.ws + (i - 1)::int as date, kb.b, sum(w.v[i]) x
        from w join kb using (id), range(1, 8) r(i) where kb.b is not null group by 1, 2""").df()
    df = df.pivot(index="date", columns="b", values="x").reset_index()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[(df.date >= START) & (df.date <= END)].reset_index(drop=True), n


# ------------------------------------------------------------------ markets
def fred(sid: str) -> pd.Series:
    d = pd.read_csv(CACHE / f"r7fidi_fred_{sid}.csv")
    d.columns = ["date", sid]
    d[sid] = pd.to_numeric(d[sid], errors="coerce")
    d = d.dropna()
    return d.set_index(pd.to_datetime(d["date"]).dt.date)[sid]


def _px(c: dict, side: str) -> float | None:
    v = c.get(side, {})
    x = v.get("close", v.get("close_dollars"))
    return float(x) if x not in (None, "") else None


def pre_price(m: dict) -> float | None:
    """Mid of the last hourly candle at least 30 min before the market closed."""
    cut = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")).timestamp() - 1800
    for c in sorted(m["_candles"], key=lambda c: -c["end_period_ts"]):
        if c["end_period_ts"] > cut:
            continue
        b, a = _px(c, "yes_bid"), _px(c, "yes_ask")
        if b is not None and a is not None and a - b <= 0.15:   # skip empty books (0 / 1 quotes)
            return (b + a) / 2
    return None


def macro_events() -> pd.DataFrame:
    rows = []
    # FOMC: the winning decision's pre-close price; surprise if it was < 0.75.
    ev = defaultdict(list)
    for m in json.loads((CACHE / "r7fidi_KXFEDDECISION.json").read_text()):
        ev[m["event_ticker"]].append(m)
    seen = set()
    for e, ms in sorted(ev.items(), key=lambda x: x[1][0]["close_time"]):
        d = datetime.fromisoformat(ms[0]["close_time"].replace("Z", "+00:00")).astimezone(ET).date()
        win = [m for m in ms if m["result"] == "yes"]
        p = pre_price(win[0]) if win else None
        if (d.year, d.month) in seen or p is None:   # drops the duplicate FEDDECISION-24JAN listing
            continue
        seen.add((d.year, d.month))
        rows.append({"kind": "fomc", "date": d, "event": e, "outcome": win[0]["ticker"].rsplit("-", 1)[1],
                     "p_outcome": p, "surprise": p < 0.75, "signed": np.nan})
    # CPI: implied median from the 'greater than k' ladder vs the released single-decimal value.
    ev = defaultdict(list)
    for m in json.loads((CACHE / "r7fidi_KXCPI.json").read_text()):
        if m.get("strike_type") == "greater":
            ev[m["event_ticker"]].append(m)
    for e, ms in ev.items():
        d = datetime.fromisoformat(ms[0]["close_time"].replace("Z", "+00:00")).astimezone(ET).date()
        lad = sorted((float(m["floor_strike"]), pre_price(m)) for m in ms)
        lad = [(k, p) for k, p in lad if p is not None]
        lad = list(zip([k for k, _ in lad], np.minimum.accumulate([p for _, p in lad])))  # P(X>k) falls in k
        actual = float(str(ms[0]["expiration_value"]).rstrip("%"))
        above = [k for k, p in lad if p >= 0.5]
        if not lad or not above:
            continue
        med = round(max(above) + 0.1, 1)
        mean = lad[0][0] + 0.1 * sum(p for _, p in lad)   # E[X] on the 0.1 grid, floor at lowest strike
        rows.append({"kind": "cpi", "date": d, "event": e, "outcome": actual, "p_outcome": med,
                     "surprise": abs(actual - med) >= 0.1 - 1e-9, "signed": actual - mean})
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def market_flags(dates: pd.Series, ev: pd.DataFrame) -> pd.DataFrame:
    spx, vix = fred("SP500"), fred("VIXCLS")
    ret = (100 * np.log(spx).diff()).dropna()
    dvix = vix.diff().dropna()
    f = pd.DataFrame({"date": dates})
    f["ret"] = f["date"].map(ret).fillna(0.0)        # 0 on non-trading days
    f["trading"] = f["date"].isin(set(ret.index)).astype(float)
    f["absret"] = f["ret"].abs()
    f["dvix"] = f["date"].map(dvix).fillna(0.0)
    f["big_up"] = (f["ret"] > BIG).astype(float)
    f["big_down"] = (f["ret"] < -BIG).astype(float)
    prev = f["date"] - timedelta(days=1)
    f["big_up_next"] = prev.map(lambda d: float(ret.get(d, 0) > BIG))
    f["big_down_next"] = prev.map(lambda d: float(ret.get(d, 0) < -BIG))
    big = (f["absret"] > BIG).astype(float)
    dow = pd.to_datetime(f["date"]).dt.day_of_week
    f["big_mon_wed"] = big * (dow <= 2)
    f["big_thu_fri"] = big * (dow >= 3)
    for kind in ("fomc", "cpi"):
        e = ev[ev.kind == kind]
        f[f"{kind}_surp"] = f["date"].isin(set(e.loc[e.surprise, "date"])).astype(float)
        f[f"{kind}_nosurp"] = f["date"].isin(set(e.loc[~e.surprise, "date"])).astype(float)
    return f


def weather() -> pd.DataFrame:
    w = pd.concat(pd.read_csv(CACHE / f"ghcn_{y}.csv") for y in (2024, 2025, 2026))
    w["date"] = pd.to_datetime(w["DATE"]).dt.date
    return w.set_index("date")[["PRCP", "TMAX"]]


# ------------------------------------------------------------------ fits
def design(f: pd.DataFrame, terms: list[str]) -> pd.DataFrame:
    ts = pd.to_datetime(f["date"])
    X = pd.get_dummies(ts.dt.day_of_week, prefix="dow", drop_first=True).astype(float)
    X = X.join(pd.get_dummies(ts.dt.strftime("%Y%m"), prefix="ym", drop_first=True).astype(float))
    X.insert(0, "const", 1.0)
    X["holiday"] = f["date"].isin(config.HOLIDAYS).astype(float)
    X["rain"] = (f["PRCP"] >= 0.01).astype(float)
    X["heavy"] = (f["PRCP"] >= 0.5).astype(float)
    t = (f["TMAX"] - 65) / 10
    X["tmax"], X["tmax2"] = t, t ** 2
    X["trading"] = f["trading"]   # weekday market holidays (Good Friday etc.)
    for c in terms:
        X[c] = f[c].astype(float)
    X.index = f.index
    return X.loc[:, (X.nunique() > 1) | (X.columns == "const")]


def fit(y, X):
    return sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 7}, use_t=False)


def bh(p: pd.Series) -> pd.Series:
    q = pd.Series(np.nan, index=p.index)
    v = p.dropna().sort_values()
    m = len(v)
    q[v.index] = (v * m / np.arange(1, m + 1))[::-1].cummin()[::-1].clip(upper=1)
    return q


def coefs(f: pd.DataFrame, s: str, mask, terms: list[str]):
    y = np.log(f.loc[mask, s].astype(float))
    res = fit(y, design(f[mask], terms))
    out = {}
    for c in terms:
        if c in res.params:
            b, se = res.params[c], res.bse[c]
            n = int((f.loc[mask, c] != 0).sum()) if c not in ("ret", "absret", "dvix") else int(mask.sum())
            out[c] = (100 * b, 100 * (b - Z * se), 100 * (b + Z * se), res.pvalues[c], n)
    return out, res


def permutation_placebo(f, s, mask, term, model_terms, nperm=300):
    """Shuffle the event days among trading days (same count) and refit: share with |beta| >= observed."""
    rng = np.random.default_rng(SEED)
    obs = coefs(f, s, mask, model_terms)[0][term][0]
    pool = f.index[mask & (f["trading"] == 1)]
    k = int(f.loc[mask, term].sum())
    hits = 0
    for _ in range(nperm):
        g = f.copy()
        g.loc[mask, term] = 0.0
        g.loc[rng.choice(pool, k, replace=False), term] = 1.0
        hits += abs(coefs(g, s, mask, model_terms)[0][term][0]) >= abs(obs)
    return hits / nperm


# ------------------------------------------------------------------ main
def run() -> None:
    agg, nst = visits()
    ev = macro_events()
    ev.to_csv(OUT / "macro_events.csv", index=False, float_format="%.3g")
    f = agg.merge(market_flags(agg["date"], ev), on="date").set_index("date").join(weather()).reset_index()
    assert f[["PRCP", "TMAX"]].notna().all().all(), "weather gaps"
    f["split"] = np.where(f["date"] <= TRAIN_END, "train", "holdout")
    print("stores per basket:", nst)
    print(ev.groupby(["kind", ev.date.map(lambda d: "train" if d <= TRAIN_END else "holdout"), "surprise"]).size())

    rows = []
    for s in BASKETS:
        for split in ("train", "holdout"):
            m = f["split"] == split
            for model, terms in MODELS.items():
                for term, (pct, lo, hi, p, n) in coefs(f, s, m, terms)[0].items():
                    rows.append({"basket": s, "model": model, "term": term, "split": split, "n": n,
                                 "pct": pct, "lo": lo, "hi": hi, "p": p})
    t = pd.DataFrame(rows)
    tr = t.split == "train"
    t["bh_train"] = np.nan
    t.loc[tr, "bh_train"] = bh(t.loc[tr, "p"])
    t.to_csv(OUT / "results.csv", index=False, float_format="%.4g")
    print(f"\ntrain tests: {tr.sum()}")

    piv = t.pivot_table(index=["basket", "model", "term"], columns="split",
                        values=["pct", "lo", "hi", "n", "bh_train", "p"], aggfunc="first")
    verdict = []
    for (s, model, term), r in piv.iterrows():
        sig_tr = r[("lo", "train")] > 0 or r[("hi", "train")] < 0
        sig_ho = (r[("lo", "holdout")] > 0 or r[("hi", "holdout")] < 0) and \
            np.sign(r[("pct", "holdout")]) == np.sign(r[("pct", "train")])
        enough = r[("n", "train")] >= 10
        found = bool(sig_tr and enough and sig_ho and r[("bh_train", "train")] <= 0.10)
        verdict.append({"basket": s, "model": model, "term": term,
                        "train": f"{r[('pct','train')]:+.2f} [{r[('lo','train')]:+.2f}, {r[('hi','train')]:+.2f}] ({int(r[('n','train')])})",
                        "holdout": f"{r[('pct','holdout')]:+.2f} [{r[('lo','holdout')]:+.2f}, {r[('hi','holdout')]:+.2f}] ({int(r[('n','holdout')])})",
                        "p_train": r[("p", "train")], "bh_train": r[("bh_train", "train")],
                        "train_sig": sig_tr, "holdout_rep": sig_ho, "FOUND": found})
    v = pd.DataFrame(verdict)
    order = {k: i for i, k in enumerate(BASKETS)}
    v = v.sort_values(["basket", "model"], key=lambda c: c.map(order) if c.name == "basket" else c)
    v.to_csv(OUT / "verdict.csv", index=False, float_format="%.3g")
    pd.set_option("display.width", 250)
    print(v.to_string(index=False))

    # Falsification for every term that is significant in train in a business basket:
    # shuffled event days (permutation) and the residential placebo basket.
    perm = []
    for _, r in v[v.train_sig & (v.basket != "resid_placebo") & (v.model != "cont")].iterrows():
        for split in ("train", "holdout"):
            m = f["split"] == split
            perm.append({"basket": r.basket, "term": r.term, "split": split,
                         "perm_p": permutation_placebo(f, r.basket, m, r.term, MODELS[r.model])})
    if perm:
        pd.DataFrame(perm).to_csv(OUT / "permutation.csv", index=False, float_format="%.3g")
        print(pd.DataFrame(perm).to_string(index=False))

    # Difference-in-differences: FiDi minus residential, so city-wide shocks cancel.
    f["fidi_minus_resid"] = np.log(f["fidi"].astype(float)) - np.log(f["resid_placebo"].astype(float))
    did = []
    for split in ("train", "holdout"):
        m = f["split"] == split
        y = f.loc[m, "fidi_minus_resid"]
        for model, terms in MODELS.items():
            res = fit(y, design(f[m], terms))
            for c in terms:
                if c in res.params:
                    b, se = res.params[c], res.bse[c]
                    did.append({"model": model, "term": c, "split": split, "pct": 100 * b,
                                "lo": 100 * (b - Z * se), "hi": 100 * (b + Z * se), "p": res.pvalues[c]})
    d = pd.DataFrame(did)
    d.to_csv(OUT / "did.csv", index=False, float_format="%.4g")
    print("\nFiDi - residential (secondary, not in BH count):")
    print(d.round(3).to_string(index=False))

    # Event-day counts and the scale of a FiDi bar's daily revenue for any hedge sizing.
    big = f.assign(big=f.absret > BIG).groupby("split")[["big_up", "big_down"]].sum()
    print("\nbig-move days:\n", big)
    per_store = (f.groupby("split")["fidi"].mean() / nst["fidi"]).round(1)
    print("mean daily visits per FiDi store:", per_store.to_dict(), "->", (per_store * CHECK).round(0).to_dict(), "$/day")


if __name__ == "__main__":
    run()
