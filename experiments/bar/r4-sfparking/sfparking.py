"""Round 4: does SF parking meter REVENUE move with SFO weather or Warriors/Giants games?

Revenue: SFMTA Parking Meter Detailed Revenue Transactions (data.sf.gov imvp-dq3v, ~215M rows),
aggregated server-side with SoQL to daily sum(gross_paid_amt) by session start date:
  - city:   all meters
  - chase:  street blocks with a meter within 600 m of Chase Center (Warriors, opened 2019-09)
  - oracle: street blocks with a meter within 600 m of Oracle Park (Giants)
  (block lists from the Parking Meters inventory 8vzz-qzz9 via within_circle)
Weather: GHCN-Daily USW00023234 = SFO, which is CLISFO, the station KXHIGHTSFO (daily high) and
KXRAINSFOM (monthly rain) settle on. Kalshi lists no daily SF rain contract, only monthly.
Games: ESPN team schedules (regular + post season), Pacific local date of tip/first pitch.

Daily model, fitted independently on train and holdout (Sundays dropped, meters mostly free):
    log(rev_t) = year-month FE + DOW FE + holiday + beta * event_t + e,   HAC(7), t on df_resid
Train = 2017-01..2019-12 + 2022-01..2023-12 (COVID 2020-21 dropped); holdout = 2024-01..2026-09.
Data-gap filter: drop days with rev < 30% of their (year-month, DOW) median (transmission gaps).
Events (daily): rain >= 0.01 in, rain >= 0.25 in, tmax > 75F, tmax < 60F on all 3 series;
Warriors home game, Warriors home win (given home game), Giants home game, Giants home win.
Monthly: log(city monthly rev) = moy FE + year FE + beta * {precip in, rain days}.
BH at 10% on train p and holdout p over all tests.

Run from backend/: .venv/bin/python ../experiments/bar/r4-sfparking/sfparking.py
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

import httpx
import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.holiday import USFederalHolidayCalendar
from scipy import stats

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
CACHE.mkdir(parents=True, exist_ok=True)
REV = "https://data.sf.gov/resource/imvp-dq3v.json"
METERS = "https://data.sf.gov/resource/8vzz-qzz9.json"
VENUES = {"chase": (37.76797, -122.38749), "oracle": (37.77857, -122.38930)}
RADIUS_M = 600
TRAIN = [("2017-01-01", "2019-12-31"), ("2022-01-01", "2023-12-31")]
HOLD = [("2024-01-01", "2026-09-30")]
HOT_F, COLD_F = 75, 60
BH_Q, EDGE, FEE = 0.10, 0.02, 0.07
OUT = Path(__file__).parent


# ---------- data ----------
def soql(params: dict) -> list[dict]:
    for attempt in range(4):
        try:
            r = httpx.get(REV, params=params, timeout=600)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            if attempt == 3:
                raise
    return []


def daily_rev(name: str, where_extra: str = "") -> pd.Series:
    out = CACHE / f"r4sf_rev_{name}.csv"
    if out.exists():
        s = pd.read_csv(out, index_col=0, parse_dates=True)["rev"]
        return s
    quarters = pd.period_range("2017Q1", "2026Q3", freq="Q")

    def one(q):
        lo, hi = q.start_time.strftime("%Y-%m-%d"), (q.end_time.normalize()).strftime("%Y-%m-%dT23:59:59")
        w = f"session_start_dt between '{lo}' and '{hi}'" + (f" and ({where_extra})" if where_extra else "")
        rows = soql({"$select": "date_trunc_ymd(session_start_dt) as d, sum(gross_paid_amt) as rev",
                     "$where": w, "$group": "d", "$order": "d", "$limit": "50000"})
        print(name, q, len(rows), flush=True)
        return rows

    with ThreadPoolExecutor(4) as ex:
        rows = [r for chunk in ex.map(one, quarters) for r in chunk]
    s = pd.Series({pd.Timestamp(r["d"]): float(r["rev"]) for r in rows}, name="rev").sort_index()
    s.to_frame().to_csv(out)
    return s


def venue_blocks(lat: float, lon: float) -> list[str]:
    r = httpx.get(METERS, params={"$select": "street_name, street_num",
                                  "$where": f"within_circle(shape, {lat}, {lon}, {RADIUS_M})",
                                  "$limit": "10000"}, timeout=120)
    r.raise_for_status()
    return sorted({f"{m['street_name']} {int(float(m['street_num'])) // 100 * 100}" for m in r.json()})


def area_rev(name: str) -> pd.Series:
    blocks = venue_blocks(*VENUES[name])
    print(name, len(blocks), "blocks", flush=True)
    lst = ",".join("'" + b.replace("'", "''") + "'" for b in blocks)
    return daily_rev(name, f"street_block in ({lst})")


def sfo_weather() -> pd.DataFrame:
    out = CACHE / "r4sf_ghcn_sfo.csv"
    if not out.exists():
        url = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00023234.csv"
        out.write_bytes(httpx.get(url, timeout=300).content)
    w = pd.read_csv(out, usecols=["DATE", "PRCP", "TMAX"], parse_dates=["DATE"], low_memory=False)
    w = w.set_index("DATE").loc["2016-12-01":"2026-10-31"]
    p_in = w["PRCP"] / 10 / 25.4
    tmax_f = w["TMAX"] / 10 * 9 / 5 + 32
    return pd.DataFrame({"precip_in": p_in, "tmax_f": tmax_f.round()})


def team_games(league: str, team: str, seasons) -> pd.DataFrame:
    out = CACHE / f"r4sf_games_{team}.csv"
    if out.exists():
        return pd.read_csv(out, parse_dates=["date"])
    rows = []
    for season in seasons:
        for st in (2, 3):
            url = f"https://site.api.espn.com/apis/site/v2/sports/{league}/teams/{team}/schedule"
            d = httpx.get(url, params={"season": season, "seasontype": st}, timeout=60).json()
            for e in d.get("events", []):
                c = e["competitions"][0]
                me = next((t for t in c["competitors"] if t["team"]["abbreviation"].lower() == team), None)
                if me is None or me.get("homeAway") != "home":
                    continue
                if not c.get("status", {}).get("type", {}).get("completed", True):
                    continue
                local = pd.Timestamp(e["date"]).tz_convert("America/Los_Angeles")
                rows.append({"date": local.normalize().tz_localize(None), "win": bool(me.get("winner")),
                             "venue": c.get("venue", {}).get("fullName", "")})
    g = pd.DataFrame(rows).drop_duplicates("date")
    g.to_csv(out, index=False)
    return g


# ---------- model ----------
def in_periods(idx: pd.DatetimeIndex, periods) -> np.ndarray:
    m = np.zeros(len(idx), bool)
    for lo, hi in periods:
        m |= np.asarray((idx >= lo) & (idx <= hi))
    return m


def daily_frame(rev: pd.Series, wx: pd.DataFrame, gsw: pd.DataFrame, sfg: pd.DataFrame) -> pd.DataFrame:
    df = rev.to_frame()
    df = df[df.index.day_of_week != 6]
    df = df.join(wx, how="inner")
    hol = USFederalHolidayCalendar().holidays("2016-01-01", "2026-12-31")
    df["holiday"] = df.index.isin(hol).astype(float)
    df["ym"] = df.index.to_period("M").astype(str)
    df["dow"] = df.index.day_of_week
    med = df.groupby(["ym", "dow"])["rev"].transform("median")
    df["gap"] = df["rev"] < 0.3 * med
    df["rain"] = (df["precip_in"] >= 0.0095).astype(float)
    df["rain25"] = (df["precip_in"] >= 0.25).astype(float)
    df["hot"] = (df["tmax_f"] > HOT_F).astype(float)
    df["cold"] = (df["tmax_f"] < COLD_F).astype(float)
    for tag, g in (("gsw", gsw), ("sfg", sfg)):
        gi = g.set_index("date")
        df[f"{tag}_home"] = df.index.isin(gi.index).astype(float)
        df[f"{tag}_win"] = df.index.isin(gi.index[gi["win"]]).astype(float)
    return df


def fit(df: pd.DataFrame, x: str, controls=()):
    d = df[~df["gap"] & (df["rev"] > 0)].dropna(subset=[x, *controls])
    X = pd.get_dummies(d["ym"], prefix="ym", drop_first=True).astype(float)
    X = X.join(pd.get_dummies(d["dow"], prefix="dow", drop_first=True).astype(float))
    X["holiday"] = d["holiday"]
    for c in controls:
        X[c] = d[c]
    X[x] = d[x]
    X = X.loc[:, X.std() > 0]
    X.insert(0, "const", 1.0)
    res = sm.OLS(np.log(d["rev"]), X).fit(cov_type="HAC", cov_kwds={"maxlags": 7})
    b, se, dfr = res.params[x], res.bse[x], res.df_resid
    tc = stats.t.ppf(0.95, dfr)
    p = 2 * stats.t.sf(abs(b / se), dfr)
    base = d.loc[d[x] == 0, "rev"]
    return dict(beta=b, lo=b - tc * se, hi=b + tc * se, p=p, n=len(d), n_event=int(d[x].sum()),
                usd=(np.exp(b) - 1) * base.mean(), mean_rev=d["rev"].mean())


def monthly_frame(rev: pd.Series, wx: pd.DataFrame) -> pd.DataFrame:
    r = rev.copy()
    m = r.groupby(r.index.to_period("M")).agg(["sum", "size"])
    w = wx.groupby(wx.index.to_period("M")).agg(precip_in=("precip_in", "sum"),
                                                 rain_days=("precip_in", lambda s: (s >= 0.0095).sum()))
    m = m.join(w, how="inner")
    m = m[m["size"] >= 0.9 * m.index.days_in_month]  # complete months
    m["y"] = np.log(m["sum"])
    return m


def fit_monthly(m: pd.DataFrame, x: str):
    X = pd.get_dummies(m.index.month, prefix="moy", drop_first=True).astype(float)
    X = X.join(pd.get_dummies(m.index.year, prefix="yr", drop_first=True).astype(float))
    X.index = m.index
    X[x] = m[x]
    X = sm.add_constant(X.loc[:, X.std() > 0])
    res = sm.OLS(m["y"], X).fit(cov_type="HC3")
    b, se, dfr = res.params[x], res.bse[x], res.df_resid
    tc = stats.t.ppf(0.95, dfr)
    return dict(beta=b, lo=b - tc * se, hi=b + tc * se, p=2 * stats.t.sf(abs(b / se), dfr), n=len(m),
                n_event=None, usd=np.nan, mean_rev=m["sum"].mean())


def bh(p: np.ndarray) -> np.ndarray:
    n = len(p)
    o = np.argsort(p)
    adj = np.empty(n)
    prev = 1.0
    for rank, i in reversed(list(enumerate(o, start=1))):
        prev = min(prev, p[i] * n / rank)
        adj[i] = prev
    return adj


# ---------- hedge backtest ----------
def backtest(df: pd.DataFrame, x: str, beta: float, freq: float) -> dict:
    """Holdout days. Buy the side that pays when revenue is hit, sized |exp(beta)-1| * trailing
    60-day mean revenue (known the day before), priced at train freq + edge + fee."""
    d = df[in_periods(df.index, HOLD) & ~df["gap"]].copy()
    d["scale"] = df["rev"].rolling(60, min_periods=30).mean().shift(1).reindex(d.index)
    d = d.dropna(subset=["scale"])
    hit_when = 1.0 if beta < 0 else 0.0  # pays when event happens if event hurts revenue
    q = freq if hit_when else 1 - freq
    price = q + EDGE + FEE * q * (1 - q)
    pays = (d[x] == hit_when).astype(float)
    size = abs(np.exp(beta) - 1) * d["scale"]
    pnl = size * (pays - price)
    hedged = d["rev"] + pnl
    return dict(n=len(d), sd0=d["rev"].std(), sd1=hedged.std(), p5_0=d["rev"].quantile(0.05),
                p5_1=hedged.quantile(0.05), mean_cost=-pnl.mean())


def main():
    wx = sfo_weather()
    gsw = team_games("basketball/nba", "gs", range(2017, 2027))
    gsw = gsw[gsw["venue"].str.contains("Chase", na=False)]  # Oracle Arena (Oakland) before 2019-10
    sfg = team_games("baseball/mlb", "sf", range(2017, 2027))
    sfg = sfg[sfg["venue"].str.contains("Park", na=False)]
    series = {"city": daily_rev("city"), "chase": area_rev("chase"), "oracle": area_rev("oracle")}

    tests = []
    for s in series:
        for x in ("rain", "rain25", "hot", "cold"):
            tests.append((s, x, ()))
        tests.append((s, "gsw_home", ()))
        tests.append((s, "gsw_win", ("gsw_home",)))
        tests.append((s, "sfg_home", ()))
        tests.append((s, "sfg_win", ("sfg_home",)))

    rows, frames = [], {}
    for s, x, ctl in tests:
        df = frames.setdefault(s, daily_frame(series[s], wx, gsw, sfg))
        tr = fit(df[in_periods(df.index, TRAIN)], x, ctl)
        ho = fit(df[in_periods(df.index, HOLD)], x, ctl)
        rows.append({"series": s, "event": x, "tr": tr, "ho": ho})
    m = monthly_frame(series["city"], wx)
    for x in ("precip_in", "rain_days"):
        mtr = m[in_periods(m.index.to_timestamp(), TRAIN)]
        mho = m[in_periods(m.index.to_timestamp(), HOLD)]
        rows.append({"series": "city_monthly", "event": x, "tr": fit_monthly(mtr, x), "ho": fit_monthly(mho, x)})

    ptr = bh(np.array([r["tr"]["p"] for r in rows]))
    pho = bh(np.array([r["ho"]["p"] for r in rows]))
    lines = []
    hdr = (f"{'series':13s} {'event':9s} | {'train beta':>10s} {'90% CI':>17s} {'n_ev':>5s} {'p_bh':>6s} | "
           f"{'hold beta':>10s} {'90% CI':>17s} {'n_ev':>5s} {'p_bh':>6s} | verdict")
    lines.append(hdr)
    found = []
    for r, a, b in zip(rows, ptr, pho):
        tr, ho = r["tr"], r["ho"]
        ok = (tr["lo"] > 0 or tr["hi"] < 0) and (tr["n_event"] is None or tr["n_event"] >= 10) \
            and (ho["lo"] > 0 or ho["hi"] < 0) and np.sign(tr["beta"]) == np.sign(ho["beta"]) \
            and a <= BH_Q and b <= BH_Q
        # criterion 4: a home game is on the published schedule, so no Kalshi contract settles on it
        settleable = not r["event"].endswith("_home")
        v = ("FOUND" if settleable else "real, NOT settleable") if ok else "not found"
        if ok and settleable:
            found.append(r)
        ne = lambda d: "-" if d["n_event"] is None else str(d["n_event"])
        lines.append(f"{r['series']:13s} {r['event']:9s} | {tr['beta']:+10.4f} [{tr['lo']:+.4f},{tr['hi']:+.4f}] "
                     f"{ne(tr):>5s} {a:6.3f} | {ho['beta']:+10.4f} [{ho['lo']:+.4f},{ho['hi']:+.4f}] "
                     f"{ne(ho):>5s} {b:6.3f} | {v}")
    if not found:
        lines.append("\nNo settleable event passed every criterion, so no hedge backtest was run.")
    lines.append(f"\n{len(rows)} tests; BH at {BH_Q:.0%} on train p and holdout p separately.")
    lines.append("\nMean daily revenue (train, Mon-Sat): " + ", ".join(
        f"{s} ${rows[i*8]['tr']['mean_rev']:,.0f}" for i, s in enumerate(series)))
    lines.append("Dollar effects (holdout, vs non-event mean): " + "; ".join(
        f"{r['series']}/{r['event']} {r['ho']['usd']:+,.0f}" for r in rows if r["ho"]["n_event"]))

    for r in found:
        s, x = r["series"], r["event"]
        if s == "city_monthly":
            continue
        df = frames[s]
        tr_df = df[in_periods(df.index, TRAIN)]
        freq = tr_df[x].mean()
        bt = backtest(df, x, r["tr"]["beta"], freq)
        lines.append(f"\nBacktest {s}/{x} (holdout, train freq {freq:.3f}): n={bt['n']}, "
                     f"SD ${bt['sd0']:,.0f} -> ${bt['sd1']:,.0f} ({bt['sd1']/bt['sd0']-1:+.1%}), "
                     f"p5 ${bt['p5_0']:,.0f} -> ${bt['p5_1']:,.0f}, mean cost ${bt['mean_cost']:,.0f}/day")
    lines.append(f"\nSample: {sum(len(f) for f in frames.values())} series-days; gap days dropped: "
                 + ", ".join(f"{s} {int(f['gap'].sum())}" for s, f in frames.items()))
    txt = "\n".join(lines)
    print(txt)
    (OUT / "output.txt").write_text(txt + "\n")


if __name__ == "__main__":
    main()
