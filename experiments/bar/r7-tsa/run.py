"""R7 tsa: does the weekly national TSA throughput surprise move Midtown tourist-heavy visits?

Run from backend/:  .venv/bin/python ../experiments/bar/r7-tsa/run.py

Weekly (Mon-Sun, the KXTSAW week) Dewey basket sums: a tourist basket (10036/10019/10001/10018)
and a local basket (UES/UWS/West Village), balanced panel as in r2-aggregate. Regress
log(tourist/local), log(tourist) and log(local) (placebo) on a TSA surprise (A: log weekly TSA
under year-month FE; B: YoY log ratio vs 52 weeks earlier) with holiday controls (H1) or with
holiday weeks dropped (H2). HAC(4). Train weeks ending 2024-01-07..2025-03-30, independent
holdout 2025-04-06..2026-09-27. TSA daily screenings are scraped from tsa.gov; the KXTSAW
settlement (weekly average) is rebuilt from them and checked against Kalshi's settled values.

Only aggregates are written; no venue names, ids or addresses.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import httpx
import numpy as np
import pandas as pd
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app import config  # noqa: E402

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
OUT = Path(__file__).resolve().parent
GLOB = str(ROOT / "data/01a16ff2-6017-7e10-86ac-94bf02853813/*.parquet")
TRAIN_END, END = date(2025, 3, 30), date(2026, 9, 27)  # week-ending Sundays
Z = 1.645
TICKET = 35.0  # $/visit, hedge backtest only
TOURIST = ("10036", "10019", "10001", "10018")
LOCAL = ("10021", "10028", "10075", "10128", "10023", "10024", "10025", "10014")
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"


# ------------------------------------------------------------------ TSA
def tsa_daily() -> pd.Series:
    rows = {}
    for name in ("r7tsa_2023", "r7tsa_2024", "r7tsa_2025", "r7tsa_page"):
        p = CACHE / f"{name}.html"
        if not p.exists():
            yr = name.split("_")[1]
            url = "https://www.tsa.gov/travel/passenger-volumes" + ("" if yr == "page" else f"/{yr}")
            p.write_text(httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60).text)
        cells = re.findall(r'<td[^>]*>\s*([^<]*?)\s*</td>', p.read_text())
        for d, n in zip(cells[::2], cells[1::2]):
            rows[pd.to_datetime(d).date()] = int(n.replace(",", ""))
    s = pd.Series(rows).sort_index()
    return s


def tsa_weekly(d: pd.Series) -> pd.DataFrame:
    df = d.rename("n").to_frame()
    df.index = pd.to_datetime(df.index)
    wk = df.groupby(df.index.to_period("W-SUN")).agg(avg=("n", "mean"), days=("n", "size"))
    wk = wk[wk.days == 7]
    wk.index = wk.index.end_time.date
    wk.index = [pd.Timestamp(i).date() for i in wk.index]
    return wk


def kalshi_check(wk: pd.DataFrame) -> pd.DataFrame:
    """Settled KXTSAW markets -> (week, strike, result, expiration_value) vs our rebuilt average."""
    p = CACHE / "r7tsa_kalshi.json"
    if not p.exists():
        out, cur = [], None
        while True:
            q = {"series_ticker": "KXTSAW", "limit": 1000, "status": "settled", **({"cursor": cur} if cur else {})}
            r = httpx.get(f"{KALSHI}/markets", params=q, timeout=30).json()
            out += r["markets"]
            cur = r.get("cursor")
            if not cur or not r["markets"]:
                break
        p.write_text(json.dumps(out))
    ms = json.loads(p.read_text())
    rows = []
    for m in ms:
        wkend = pd.to_datetime(m["event_ticker"].split("-")[1], format="%y%b%d").date()
        ev = m["expiration_value"].replace(",", "")
        rows.append({"week": wkend, "strike": m["floor_strike"], "result": m["result"],
                     "kalshi_value": float(ev) if re.fullmatch(r"[\d.]+", ev) else np.nan})
    k = pd.DataFrame(rows)
    k["ours"] = k["week"].map(wk["avg"])
    k["ours_yes"] = np.where(k["ours"] > k["strike"], "yes", "no")
    return k


# ------------------------------------------------------------------ Dewey
def baskets() -> tuple[pd.DataFrame, dict]:
    con = duckdb.connect()
    con.execute(f"""
        create table w as select ID_STORE id, DATE_RANGE_START::date ws,
            lpad(trim(POSTAL_CODE::varchar), 5, '0') zip, from_json(VISITS_BY_DAY, '["INTEGER"]') v
        from '{GLOB}'""")
    con.execute("""create table st as select id, any_value(zip) zip, count(*) nwk,
                   avg((list_min(v) = list_max(v))::int) flat from w group by id""")
    nweeks = con.execute("select count(distinct ws) from w").fetchone()[0]
    con.execute(f"create table keep as select * from st where nwk = {nweeks} and flat < 0.05")
    meta = con.execute(f"""select sum((zip in {TOURIST})::int) tourist, sum((zip in {LOCAL})::int) local
                           from keep""").df().iloc[0].astype(int).to_dict()
    df = con.execute(f"""
        select w.ws, sum(case when k.zip in {TOURIST} then list_sum(w.v) end) tourist,
               sum(case when k.zip in {LOCAL} then list_sum(w.v) end) local
        from w join keep k using (id) group by w.ws order by w.ws""").df()
    df["week"] = (pd.to_datetime(df["ws"]) + pd.Timedelta(days=6)).dt.date
    return df.set_index("week")[["tourist", "local"]], meta


# ------------------------------------------------------------------ calendar
def easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mo = (h + l - 7 * m + 114) // 31
    return date(y, mo, (h + l - 7 * m + 114) % 31 + 1)


def holiday_flags(weeks: pd.Index) -> pd.DataFrame:
    hol = set(config.HOLIDAYS) | {date(2023, d.month, d.day) for d in config.HOLIDAYS if d.year == 2024}
    hol |= {date(2023, 11, 23), date(2023, 1, 16), date(2023, 2, 20), date(2023, 5, 29), date(2023, 9, 4)}
    rows = []
    for we in weeks:
        days = {we - timedelta(days=i) for i in range(7)}
        thx = any(d.month == 11 and 22 <= d.day <= 28 and d.weekday() == 3 for d in days)
        xmas = any((d.month == 12 and d.day >= 22) or (d.month == 1 and d.day <= 3) for d in days)
        eas = any(abs((d - easter(d.year)).days) <= 3 for d in days)
        fed = bool(days & hol)
        rows.append({"fed": fed, "thx": thx, "xmas": xmas, "easter": eas})
    h = pd.DataFrame(rows, index=weeks).astype(float)
    h["any"] = (h.sum(axis=1) > 0).astype(float)
    return h


# ------------------------------------------------------------------ model
def design(f: pd.DataFrame, x: pd.Series, surprise: str, hmode: str) -> pd.DataFrame:
    ym = pd.Series([w.strftime("%Y%m") for w in f.index], index=f.index)
    X = pd.get_dummies(ym, prefix="ym", drop_first=True).astype(float)
    X.insert(0, "const", 1.0)
    if hmode == "H1":
        for c in ("fed", "thx", "xmas", "easter"):
            X[f"h_{c}"] = f[c]
            if surprise == "yoy":
                X[f"hl_{c}"] = f[f"lag_{c}"]
    X["x"] = x
    X = X.loc[:, ~X.T.duplicated()]  # e.g. a holiday flagged in both this year and the comparison week
    return X.loc[:, (X.nunique() > 1) | (X.columns == "const")]


def fit(y, X):
    return sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 4}, use_t=False)


def sample(f: pd.DataFrame, split: str, surprise: str, hmode: str) -> pd.Series:
    m = (f.index <= TRAIN_END) if split == "train" else (f.index > TRAIN_END)
    m = pd.Series(m, index=f.index) & f["x_" + surprise].notna()
    if hmode == "H2":
        m &= f["any"] == 0
        if surprise == "yoy":
            m &= f["lag_any"] == 0
    return m


def bh(p: pd.Series) -> pd.Series:
    q = pd.Series(np.nan, index=p.index)
    v = p.dropna().sort_values()
    adj = (v * len(v) / np.arange(1, len(v) + 1))[::-1].cummin()[::-1].clip(upper=1)
    q[v.index] = adj
    return q


OUTCOMES = {"ratio": lambda f: np.log(f.tourist / f.local), "tourist": lambda f: np.log(f.tourist),
            "local_placebo": lambda f: np.log(f.local)}


def run() -> None:
    d = tsa_daily()
    wk = tsa_weekly(d)
    k = kalshi_check(wk)
    vis, meta = baskets()
    f = vis.join(wk["avg"].rename("tsa"), how="inner")
    f = f[f.index <= END]
    f["x_trend"] = np.log(f["tsa"])
    lag = wk["avg"].reindex([w - timedelta(days=364) for w in f.index]).values
    f["x_yoy"] = np.log(f["tsa"].values / lag)
    f = f.join(holiday_flags(f.index))
    lagh = holiday_flags(pd.Index([w - timedelta(days=364) for w in f.index]))
    for c in lagh.columns:
        f[f"lag_{c}"] = lagh[c].values
    f["x_lead_trend"] = f["x_trend"].shift(-1)

    rows = []
    for out, yfn in OUTCOMES.items():
        for sur in ("trend", "yoy"):
            for hm in ("H1", "H2"):
                r = {"outcome": out, "surprise": sur, "holiday": hm}
                for sp in ("train", "holdout"):
                    m = sample(f, sp, sur, hm)
                    res = fit(yfn(f[m]), design(f[m], f.loc[m, "x_" + sur], sur, hm))
                    b, se = res.params["x"], res.bse["x"]
                    r.update({f"{sp}_n": int(m.sum()), f"{sp}_beta": b, f"{sp}_lo": b - Z * se,
                              f"{sp}_hi": b + Z * se, f"{sp}_p": res.pvalues["x"],
                              f"{sp}_sd_x": f.loc[m, "x_" + sur].std()})
                rows.append(r)
    t = pd.DataFrame(rows)
    t["train_bh"] = bh(t["train_p"])
    sig = lambda sp: (t[f"{sp}_lo"] > 0) | (t[f"{sp}_hi"] < 0)
    t["found"] = sig("train") & sig("holdout") & (np.sign(t.train_beta) == np.sign(t.holdout_beta)) \
        & (t.train_bh <= 0.10) & (t.outcome != "local_placebo")
    t.to_csv(OUT / "results.csv", index=False, float_format="%.4g")
    pd.set_option("display.width", 250)
    print(meta, "weeks", len(f), "TSA days", len(d), d.index.min(), d.index.max())
    print("\nKalshi settlement check:\n", k.drop_duplicates("week")[["week", "kalshi_value", "ours"]].to_string())
    print("result agreement:", (k.result == k.ours_yes).mean(), "of", len(k))
    print("\nRESULTS (beta = elasticity of visits wrt weekly TSA):\n", t.round(4).to_string())
    falsify(f)
    pooled(f)
    basis_and_hedge(f, t)


def falsify(f: pd.DataFrame, n_perm: int = 200) -> None:
    """Permutation within year-month (train) and lead-surprise test for the main spec."""
    rng = np.random.default_rng(0)
    print("\nFALSIFICATION (ratio):")
    for sur in ("trend", "yoy"):
        m = sample(f, "train", sur, "H2")
        y, x = OUTCOMES["ratio"](f[m]), f.loc[m, "x_" + sur]
        real = fit(y, design(f[m], x, sur, "H2")).tvalues["x"]
        ym = pd.Series([w.strftime("%Y%m") for w in x.index], index=x.index)
        ts = [fit(y, design(f[m], x.groupby(ym).transform(lambda v: pd.Series(rng.permutation(v.values), index=v.index)),
                           sur, "H2")).tvalues["x"] for _ in range(n_perm)]
        print(f"  {sur} H2 train real t={real:+.2f}, perm |t| p95={np.quantile(np.abs(ts), .95):.2f}, "
              f"perm p={np.mean(np.abs(ts) >= abs(real)):.3f}")
    # Seasonality check: last year's same-week TSA is known in advance (so priced into any contract).
    # If it predicts the ratio as well as this year's level, the 'trend' effect is calendar, not surprise.
    for sp in ("train", "holdout"):
        m = sample(f, sp, "yoy", "H2")
        X = design(f[m], f.loc[m, "x_trend"] - f.loc[m, "x_yoy"], "yoy", "H2")
        r1 = fit(OUTCOMES["ratio"](f[m]), X)
        r2 = fit(OUTCOMES["ratio"](f[m]), X.assign(yoy=f.loc[m, "x_yoy"]))
        print(f"  seasonal {sp} n={m.sum()}: last-year level alone {r1.params['x']:+.3f} (p={r1.pvalues['x']:.3f}); "
              f"joint: last-year level {r2.params['x']:+.3f} (p={r2.pvalues['x']:.3f}), "
              f"yoy surprise {r2.params['yoy']:+.3f} (p={r2.pvalues['yoy']:.3f})")
    for sp in ("train", "holdout"):
        m = sample(f, sp, "trend", "H2") & f["x_lead_trend"].notna()
        X = design(f[m], f.loc[m, "x_trend"], "trend", "H2")
        X["lead"] = f.loc[m, "x_lead_trend"]
        r = fit(OUTCOMES["ratio"](f[m]), X)
        print(f"  lead test {sp}: current {r.params['x']:+.3f} (p={r.pvalues['x']:.3f}), "
              f"next-week {r.params['lead']:+.3f} (p={r.pvalues['lead']:.3f})")


def pooled(f: pd.DataFrame) -> None:
    """Descriptive, not a FOUND test: full sample and no FE but month-of-year + linear trend."""
    print("\nDESCRIPTIVE full-sample (not counted):")
    for sur in ("trend", "yoy"):
        for out in OUTCOMES:
            m = f["x_" + sur].notna() & (f["any"] == 0)
            r = fit(OUTCOMES[out](f[m]), design(f[m], f.loc[m, "x_" + sur], sur, "H2"))
            print(f"  {sur:5s} {out:14s} n={m.sum()} beta={r.params['x']:+.3f} "
                  f"[{r.params['x'] - Z * r.bse['x']:+.3f},{r.params['x'] + Z * r.bse['x']:+.3f}]")


def basis_and_hedge(f: pd.DataFrame, t: pd.DataFrame) -> None:
    """KXTSAW pays on the weekly level vs a strike. A contract bought at the start of the week is
    struck near the expected level; proxy 'expected' = same week last year x trailing 8-week YoY
    growth (known before the week). Flag = actual < expected (the 'NO above strike' payoff)."""
    w = f.copy()
    g = np.exp(w["x_yoy"].shift(1).rolling(8).mean())
    lag = w["tsa"] / np.exp(w["x_yoy"])
    w["strike"] = lag * g
    w["miss"] = (w["tsa"] < w["strike"]).astype(float)
    w["surp_fc"] = np.log(w["tsa"] / w["strike"])
    ok = w["strike"].notna()
    print("\nBASIS: corr(binary 'below forecast strike', trend surprise | ym FE) and with forecast surprise")
    for sp in ("train", "holdout"):
        m = ok & ((w.index <= TRAIN_END) if sp == "train" else (w.index > TRAIN_END))
        print(f"  {sp}: weeks={m.sum()} miss rate={w.loc[m, 'miss'].mean():.2f} "
              f"corr(miss, fc surprise)={np.corrcoef(w.loc[m, 'miss'], w.loc[m, 'surp_fc'])[0, 1]:+.2f} "
              f"corr(fc surprise, yoy)={np.corrcoef(w.loc[m, 'surp_fc'], w.loc[m, 'x_yoy'])[0, 1]:+.2f}")
    # ratio/tourist on the binary payoff itself (what the contract actually pays on)
    print("\nCONTRACT-FLAG regressions (H1 controls, log tourist and ratio on 1[TSA < forecast strike]):")
    for out in ("ratio", "tourist", "local_placebo"):
        s = []
        for sp in ("train", "holdout"):
            m = ok & ((w.index <= TRAIN_END) if sp == "train" else (w.index > TRAIN_END))
            r = fit(OUTCOMES[out](w[m]), design(w[m], w.loc[m, "miss"], "yoy", "H1"))
            s.append(f"{sp} {100 * r.params['x']:+.2f}% [{100 * (r.params['x'] - Z * r.bse['x']):+.2f},"
                     f"{100 * (r.params['x'] + Z * r.bse['x']):+.2f}] n={m.sum()}")
        print(f"  {out:14s}", " | ".join(s))
    # hedge backtest on the tourist basket in $ (visits x $35), train beta, holdout P&L
    tr = ok & (w.index <= TRAIN_END)
    ho = ok & (w.index > TRAIN_END)
    rev = w["tourist"] * TICKET
    b = fit(rev[tr], design(w[tr], w.loc[tr, "miss"], "yoy", "H1")).params["x"]
    p = (w.loc[tr, "miss"].mean() if b < 0 else 1 - w.loc[tr, "miss"].mean()) + 0.02
    pay = w.loc[ho, "miss"] if b < 0 else 1 - w.loc[ho, "miss"]
    pnl = abs(b) * (pay - p - 0.07 * p * (1 - p))
    Xh = design(w[ho], w.loc[ho, "miss"], "yoy", "H1").drop(columns="x")
    resid = rev[ho] - sm.OLS(rev[ho], Xh).fit().fittedvalues
    print(f"\nHEDGE (tourist basket $/week): train beta ${b:,.0f}, price {p:.2f}, holdout weeks {ho.sum()}, "
          f"SD {resid.std():,.0f} -> {(resid + pnl).std():,.0f}, p5 {resid.quantile(.05):,.0f} -> "
          f"{(resid + pnl).quantile(.05):,.0f}, mean cost/wk {pnl.mean():,.0f}")


if __name__ == "__main__":
    run()
