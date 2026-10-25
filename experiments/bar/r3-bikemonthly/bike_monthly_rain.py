"""Round 3: does MONTHLY bike demand track MONTHLY Central Park precipitation (KXRAINNYCM)?

Series (public, cached in the scratchpad r2-cache/, files prefixed r3bike_):
- jc:  Citi Bike Jersey City/Hoboken trips per month = rows in each s3://tripdata JC-YYYYMM zip
       (every month since 2015-09).
- dot: NYC DOT automated bike counters (NYC Open Data uczf-rk3c), daily totals per counter,
       turned into counter-months with >= 90% of days reported; y = log(mean daily count).
Weather: GHCN-Daily USW00094728 (Central Park), summed to a monthly total in inches, plus the
number of days >= 0.01 in. The NWS CLI monthly total that KXRAINNYCM settles on is this same
station's sum, so "> X in" on the GHCN sum is the settlement flag (up to mm->in rounding).

Models, fitted independently on train (2016-01..2021-12) and holdout (2022-01..2025-12), with
2020-03..2021-06 dropped (COVID):
    jc:  log(trips_m) = month-of-year + year FE + beta * x_m + e         (OLS, HC3, t on df_resid)
    dot: log(cnt_im)  = counter x year FE + month-of-year + beta * x_m   (cluster by month, t on G-1)
x in {precip inches, rain days, 1[precip > 3], 1[> 4], 1[> 5]}  ->  2 series x 5 = 10 tests,
BH at 10% on train p and holdout p separately.

Backtest (jc holdout months, $4/trip): buy YES "> X in" at train freq + 0.02 + 0.07 p(1-p),
contracts = |1 - exp(beta_train)| * trailing-12-month mean monthly revenue (known when bought).
Also a ladder hedge for the continuous model: YES on every strike k = 1..10 (sum ~ floor(P)),
each sized |beta_in| * trailing mean revenue, each priced at its own train freq + edge + fee.

Run from backend/: .venv/bin/python ../experiments/bar/r3-bikemonthly/bike_monthly_rain.py
"""

import io
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

import httpx
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
CACHE.mkdir(parents=True, exist_ok=True)
TRAIN = ("2016-01", "2021-12")
HOLD = ("2022-01", "2025-12")
COVID = ("2020-03", "2021-06")
USD_PER_TRIP = 4.00
BH_Q = 0.10
EDGE, FEE = 0.02, 0.07
STRIKES = (3, 4, 5)


# ---------- data ----------
def jc_monthly() -> pd.Series:
    out = CACHE / "r3bike_jc_monthly.csv"
    if out.exists():
        s = pd.read_csv(out, index_col=0)["trips"]
        s.index = pd.PeriodIndex(s.index, freq="M")
        return s
    xml = httpx.get("https://s3.amazonaws.com/tripdata/?list-type=2", timeout=60).text
    keys = sorted(set(re.findall(r"<Key>(JC-[^<]*\.zip)</Key>", xml)))
    counts: dict[str, int] = {}
    with httpx.Client(timeout=300) as c:
        for k in keys:
            ym = re.search(r"JC-(\d{6})", k).group(1)
            z = zipfile.ZipFile(io.BytesIO(c.get(f"https://s3.amazonaws.com/tripdata/{k}").content))
            n = 0
            for f in z.namelist():
                if f.endswith(".csv") and not f.startswith("__MACOSX"):
                    with z.open(f) as fh:
                        n += sum(1 for _ in fh) - 1  # minus header
            counts[f"{ym[:4]}-{ym[4:]}"] = counts.get(f"{ym[:4]}-{ym[4:]}", 0) + n
            print("jc", k, n, flush=True)
    s = pd.Series(counts, name="trips").sort_index()
    s.to_frame().to_csv(out)
    s.index = pd.PeriodIndex(s.index, freq="M")
    return s


def dot_daily() -> pd.DataFrame:
    out = CACHE / "r3bike_dot_daily.parquet"
    if out.exists():
        return pd.read_parquet(out)
    rows, off = [], 0
    with httpx.Client(timeout=600) as c:
        while True:
            q = {"$select": "id, date_trunc_ymd(date) as d, sum(counts) as n",
                 "$where": "date >= '2015-01-01' and date < '2026-01-01'",
                 "$group": "id, d", "$order": "id, d", "$limit": "50000", "$offset": str(off)}
            r = c.get("https://data.cityofnewyork.us/resource/uczf-rk3c.json", params=q)
            r.raise_for_status()
            page = r.json()
            rows += page
            print("dot rows", len(rows), flush=True)
            if len(page) < 50000:
                break
            off += 50000
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df["d"])
    df["n"] = df["n"].astype(float)
    df.to_parquet(out)
    return df


def dot_counter_months() -> pd.DataFrame:
    df = dot_daily()
    df = df[df["n"] > 0].copy()
    df["m"] = df["d"].dt.to_period("M")
    g = df.groupby(["id", "m"]).agg(ndays=("n", "size"), mean=("n", "mean")).reset_index()
    g = g[g["ndays"] >= 0.9 * g["m"].dt.days_in_month]
    g["y"] = np.log(g["mean"])
    return g


def central_park_monthly() -> pd.DataFrame:
    out = CACHE / "r3bike_ghcn.csv"
    if not out.exists():
        url = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00094728.csv"
        out.write_bytes(httpx.get(url, timeout=300).content)
    w = pd.read_csv(out, usecols=["DATE", "PRCP"], parse_dates=["DATE"], low_memory=False)
    w = w.set_index("DATE").loc["2015-01-01":"2026-09-30"]
    w["m"] = w.index.to_period("M")
    p_in = w["PRCP"] / 10 / 25.4  # tenths of mm -> inches
    m = pd.DataFrame({
        "precip_in": p_in.groupby(w["m"]).sum(),
        "rain_days": (p_in >= 0.0095).groupby(w["m"]).sum(),
        "n_obs": p_in.notna().groupby(w["m"]).sum(),
    })
    m["days"] = m.index.days_in_month
    for x in range(1, 11):
        m[f"gt{x}"] = (m["precip_in"] > x).astype(float)
    return m


def in_period(idx: pd.PeriodIndex, per) -> np.ndarray:
    lo, hi = pd.Period(per[0], "M"), pd.Period(per[1], "M")
    covid = (idx >= pd.Period(COVID[0], "M")) & (idx <= pd.Period(COVID[1], "M"))
    return np.asarray((idx >= lo) & (idx <= hi) & ~covid)


# ---------- models ----------
def fit_jc(df: pd.DataFrame, x: str):
    X = pd.get_dummies(df.index.month, prefix="moy", drop_first=True).astype(float)
    X = X.join(pd.get_dummies(df.index.year, prefix="yr", drop_first=True).astype(float))
    X.index = df.index
    X[x] = df[x]
    X = sm.add_constant(X)
    res = sm.OLS(np.log(df["trips"]), X).fit(cov_type="HC3")
    b, se, dfr = res.params[x], res.bse[x], res.df_resid
    tc = stats.t.ppf(0.95, dfr)
    p = 2 * stats.t.sf(abs(b / se), dfr)
    return dict(beta=b, lo=b - tc * se, hi=b + tc * se, p=p, n=len(df), df=int(dfr),
                n_event=int(df[x].sum()) if x.startswith("gt") else None, res=res)


def fit_dot(panel: pd.DataFrame, x: str):
    cy = panel["id"].astype(str) + "_" + panel["m"].dt.year.astype(str)
    X = pd.get_dummies(cy, prefix="cy", drop_first=True).astype(float)
    X = X.join(pd.get_dummies(panel["m"].dt.month, prefix="moy", drop_first=True).astype(float))
    X[x] = panel[x].values
    X = sm.add_constant(X)
    groups = pd.factorize(panel["m"])[0]
    res = sm.OLS(panel["y"].values, X.values).fit(cov_type="cluster", cov_kwds={"groups": groups})
    j = list(X.columns).index(x)
    G = len(np.unique(groups))
    b, se = res.params[j], res.bse[j]
    tc = stats.t.ppf(0.95, G - 1)
    p = 2 * stats.t.sf(abs(b / se), G - 1)
    nm = panel.drop_duplicates("m")
    return dict(beta=b, lo=b - tc * se, hi=b + tc * se, p=p, n=len(panel), df=G - 1,
                n_event=int(nm[x].sum()) if x.startswith("gt") else None, n_counters=panel["id"].nunique())


def bh(p: np.ndarray) -> np.ndarray:
    n = len(p)
    o = np.argsort(p)
    adj = np.empty(n)
    prev = 1.0
    for rank, i in reversed(list(enumerate(o, start=1))):
        prev = min(prev, p[i] * n / rank)
        adj[i] = prev
    return adj


# ---------- pricing ----------
def kalshi_pricing() -> pd.DataFrame:
    out = CACHE / "r3bike_kxrainnycm_prices.csv"
    if out.exists():
        return pd.read_csv(out)
    base = "https://api.elections.kalshi.com/trade-api/v2"
    mk, cursor = [], None
    with httpx.Client(timeout=60) as c:
        while True:
            q = {"series_ticker": "KXRAINNYCM", "status": "settled", "limit": 1000}
            if cursor:
                q["cursor"] = cursor
            d = c.get(f"{base}/markets", params=q).json()
            mk += d.get("markets", [])
            cursor = d.get("cursor")
            if not cursor:
                break
        rows = []
        for m in mk:
            t_open = int(datetime.fromisoformat(m["open_time"].replace("Z", "+00:00")).timestamp())
            t_close = int(datetime.fromisoformat(m["close_time"].replace("Z", "+00:00")).timestamp())
            cs = c.get(f"{base}/series/KXRAINNYCM/markets/{m['ticker']}/candlesticks",
                       params={"start_ts": t_open, "end_ts": t_close, "period_interval": 1440}).json()
            cs = [k for k in cs.get("candlesticks", []) if k["price"].get("close_dollars")]
            first = cs[0] if cs else None
            rows.append(dict(
                ticker=m["ticker"], event=m["event_ticker"], strike=m.get("floor_strike"),
                result=m["result"], volume=float(m.get("volume_fp") or 0),
                last=float(m["last_price_dollars"]),
                day1_close=float(first["price"]["close_dollars"]) if first else np.nan,
                day1_ask=float(first["yes_ask"]["close_dollars"]) if first and first["yes_ask"].get("close_dollars") else np.nan,
                day1_ts=datetime.fromtimestamp(first["end_period_ts"], timezone.utc).date().isoformat() if first else None,
            ))
    df = pd.DataFrame(rows).sort_values(["event", "strike"])
    df.to_csv(out, index=False)
    return df


def main() -> None:
    w = central_park_monthly()
    assert (w.loc[:"2025-12", "n_obs"] == w.loc[:"2025-12", "days"]).all(), "missing GHCN days"
    jc = jc_monthly().rename("trips").to_frame().join(w, how="inner")
    jc = jc[jc["trips"] > 0]
    print(f"jc months available: {jc.index.min()}..{jc.index.max()} ({len(jc)})")

    cm = dot_counter_months()
    cm = cm.join(w, on="m", how="inner")

    xs = ["precip_in", "rain_days"] + [f"gt{x}" for x in STRIKES]
    rows = []
    fits = {}
    for x in xs:
        for per_name, per in (("train", TRAIN), ("hold", HOLD)):
            d = jc[in_period(jc.index, per)]
            f = fit_jc(d, x)
            fits[("jc", x, per_name)] = f
            rows.append(dict(series="jc", x=x, period=per_name, **{k: v for k, v in f.items() if k != "res"}))
            pmask = in_period(pd.PeriodIndex(cm["m"]), per)
            d2 = cm[pmask]
            f2 = fit_dot(d2, x)
            fits[("dot", x, per_name)] = f2
            rows.append(dict(series="dot", x=x, period=per_name, **f2))
    R = pd.DataFrame(rows)
    for per_name in ("train", "hold"):
        m = R["period"] == per_name
        R.loc[m, "p_bh"] = bh(R.loc[m, "p"].values)
    pd.set_option("display.width", 200)
    print(R.drop(columns=[c for c in ["n_counters"] if c not in R]).to_string())

    wide = R.pivot_table(index=["series", "x"], columns="period",
                         values=["beta", "lo", "hi", "p_bh", "n", "n_event", "df"], aggfunc="first")
    verdicts = {}
    for (s, x), r in wide.iterrows():
        tr_ok = (r[("lo", "train")] > 0 or r[("hi", "train")] < 0) and r[("p_bh", "train")] < BH_Q
        ho_ok = (r[("lo", "hold")] > 0 or r[("hi", "hold")] < 0) and r[("p_bh", "hold")] < BH_Q
        same = np.sign(r[("beta", "train")]) == np.sign(r[("beta", "hold")])
        ev_ok = True
        if x.startswith("gt"):
            ev_ok = r[("n_event", "train")] >= 10 and r[("n_event", "hold")] >= 10
        verdicts[(s, x)] = "FOUND" if (tr_ok and ho_ok and same and ev_ok) else "NOT FOUND"
    print(verdicts)

    # event-month counts / train freq for every strike
    trw = w[in_period(w.index, TRAIN)]
    how = w[in_period(w.index, HOLD)]
    freq = {k: trw[f"gt{k}"].mean() for k in range(1, 11)}
    print("train freq:", {k: round(v, 3) for k, v in freq.items()})
    print("holdout freq:", {k: round(how[f"gt{k}"].mean(), 3) for k in range(1, 11)})
    # all-months-since-1991 climatology for comparison with market prices
    clim = central_park_monthly_long()

    # ---------- backtest on jc holdout ----------
    rev = jc["trips"] * USD_PER_TRIP
    trail = rev.rolling(12, min_periods=6).mean().shift(1)  # known before the month
    ho_idx = jc.index[in_period(jc.index, HOLD)]
    bt = pd.DataFrame({"rev": rev.loc[ho_idx], "trail": trail.loc[ho_idx]})
    yoy = rev - rev.shift(12)
    bt["yoy"] = yoy.reindex(ho_idx)
    out = {}

    def price(p):
        return p + EDGE + FEE * (p + EDGE) * (1 - p - EDGE)

    for k in STRIKES:
        b = fits[("jc", f"gt{k}", "train")]["beta"]
        q = np.abs(1 - np.exp(b)) * bt["trail"]
        pay = w.loc[ho_idx, f"gt{k}"]
        pnl = q * (pay - price(freq[k]))
        out[f"YES >{k} in"] = pnl
    b_in = fits[("jc", "precip_in", "train")]["beta"]
    lad = 0
    for k in range(1, 11):
        q = np.abs(1 - np.exp(b_in)) * bt["trail"]
        lad = lad + q * (w.loc[ho_idx, f"gt{k}"] - price(freq[k]))
    out["ladder 1..10"] = lad
    brows = [dict(hedge="none", sd_rev=bt["rev"].std(), sd_yoy=bt["yoy"].std(),
                  worst_yoy=bt["yoy"].min(), worst_month=str(bt["yoy"].idxmin()), mean_pnl=0.0,
                  p05_yoy=bt["yoy"].quantile(0.05))]
    for name, pnl in out.items():
        h = bt["rev"] + pnl
        hy = bt["yoy"] + pnl
        brows.append(dict(hedge=name, sd_rev=h.std(), sd_yoy=hy.std(), worst_yoy=hy.min(),
                          worst_month=str(hy.idxmin()), mean_pnl=pnl.mean(),
                          p05_yoy=hy.quantile(0.05)))
    B = pd.DataFrame(brows)
    print(B.to_string())
    print("holdout months in backtest:", len(bt), "mean rev", round(bt["rev"].mean()))

    # residual SD reduction in the model sense: share of the de-seasonalised variance precip explains
    for s_ in ("train", "hold"):
        res = fits[("jc", "precip_in", s_)]["res"]
        print(s_, "R2 full", round(res.rsquared, 4))

    P = kalshi_pricing()
    P["train_freq"] = P["strike"].map(lambda k: freq.get(int(k), np.nan))
    P["clim_freq"] = P.apply(lambda r: clim.get((r["event"][-3:], int(r["strike"])), np.nan), axis=1)
    print(P.to_string())

    R.to_csv(Path(__file__).with_name("r3bike_results.csv"), index=False)
    B.to_csv(Path(__file__).with_name("r3bike_backtest.csv"), index=False)
    P.to_csv(Path(__file__).with_name("r3bike_kalshi_prices.csv"), index=False)


MON = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
       "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}


def central_park_monthly_long() -> dict:
    """Same-calendar-month frequency of "> k in" over 1991-2025, for comparing market prices."""
    w = pd.read_csv(CACHE / "r3bike_ghcn.csv", usecols=["DATE", "PRCP"], parse_dates=["DATE"], low_memory=False)
    w = w.set_index("DATE").loc["1991-01-01":"2025-12-31"]
    m = (w["PRCP"] / 254).groupby(w.index.to_period("M")).sum()
    out = {}
    for name, mo in MON.items():
        s = m[m.index.month == mo]
        for k in range(1, 11):
            out[(name, k)] = float((s > k).mean())
    return out


if __name__ == "__main__":
    main()
