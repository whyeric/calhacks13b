"""R2-MTA: does Central Park weather or an MSG game move MTA daily ridership?

Run from backend/: .venv/bin/python ../experiments/bar/r2-mta/mta.py

Data (all public, cached in the scratchpad r2-cache/):
- MTA daily ridership by mode, data.ny.gov sayj-mze2 (successor of vxuj-8kew, which stops 2025-01-09).
- Central Park GHCN-D USW00094728 (NOAA NCEI access API): PRCP, TMAX, SNOW. This is the station
  and the daily climate record Kalshi KXRAIN / KXHIGHNY settle on, so the basis is the flag itself.
- Knicks / Rangers home games from the ESPN scoreboard via app.data.sports.fetch_games.

Model, per mode and per event (one event per fit): log(riders) on app.stats.exposure.build_design
(const, DOW, season k=1,2) + holiday + holiday week (Dec 24 - Jan 1) + linear trend + the event
flag, HAC (Newey-West, 7 lags) errors, z = 1.645. Train 2022-2023, holdout 2024-2025, fitted
independently. BH at 10% over all mode x event tests, separately on train and on holdout p-values.
"""

import json
import sys
from datetime import date
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import statsmodels.api as sm
from pandas.tseries.holiday import USFederalHolidayCalendar
from statsmodels.stats.multitest import multipletests

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from app.data import sports  # noqa: E402
from app.stats.exposure import Z90, build_design  # noqa: E402

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
OUT = Path(__file__).resolve().parent
START, END = date(2022, 1, 1), date(2025, 12, 31)
TRAIN = (date(2022, 1, 1), date(2023, 12, 31))
HOLD = (date(2024, 1, 1), date(2025, 12, 31))
MODES = ["Subway", "Bus", "LIRR", "MNR", "BT"]
# Rough average revenue per rider / crossing, only to put the effect in dollars (fare proxy).
FARE = {"Subway": 2.90, "Bus": 2.90, "LIRR": 7.00, "MNR": 9.00, "BT": 8.00}
HAC_LAGS = 7


def ridership() -> pd.DataFrame:
    path = CACHE / "mta_sayj.parquet"
    if not path.exists():
        r = httpx.get(
            "https://data.ny.gov/resource/sayj-mze2.json",
            params={"$where": f"date between '{START}' and '{END}T23:59:59'", "$limit": 50000},
            timeout=60,
        )
        r.raise_for_status()
        pd.DataFrame(r.json()).to_parquet(path)
    d = pd.read_parquet(path)
    d["date"] = pd.to_datetime(d["date"]).dt.date
    d["count"] = pd.to_numeric(d["count"])
    return d.pivot_table(index="date", columns="mode", values="count")[MODES]


def weather() -> pd.DataFrame:
    path = CACHE / "noaa_centralpark.json"
    if not path.exists():
        r = httpx.get(
            "https://www.ncei.noaa.gov/access/services/data/v1",
            params={"dataset": "daily-summaries", "stations": "USW00094728", "startDate": str(START),
                    "endDate": str(END), "dataTypes": "PRCP,TMAX,SNOW", "units": "standard", "format": "json"},
            timeout=120,
        )
        r.raise_for_status()
        path.write_text(r.text)
    w = pd.DataFrame(json.loads(path.read_text()))
    w["date"] = pd.to_datetime(w["DATE"]).dt.date
    for c in ("PRCP", "TMAX", "SNOW"):
        w[c] = pd.to_numeric(w[c].astype(str).str.strip().replace({"T": "0"}), errors="coerce")
    return w.set_index("date")[["PRCP", "TMAX", "SNOW"]]


def games() -> pd.DataFrame:
    path = CACHE / "msg_games_2022_2025.csv"
    if not path.exists():
        client = sports.ScoreboardClient(http=httpx.Client(timeout=20), cache_dir=CACHE / "espn")
        frames = []
        for key, team in sports.TEAMS.items():
            f = sports.daily_flags(sports.schedule_frame(sports.fetch_games(team, START, END, client)), START, END)
            frames.append(f.set_index("date").add_prefix(f"{key}_"))
        pd.concat(frames, axis=1).reset_index().to_csv(path, index=False)
    g = pd.read_csv(path)
    g["date"] = pd.to_datetime(g["date"]).dt.date
    g = g.set_index("date")
    return pd.DataFrame({
        "game": g["knicks_home_game"] | g["rangers_home_game"],
        "win": g["knicks_home_win"] | g["rangers_home_win"],
    })


def holidays() -> set[date]:
    fed = USFederalHolidayCalendar().holidays(str(START), str(END))
    extra = set()
    for y in range(START.year, END.year + 1):
        thanks = [d for d in fed if d.year == y and d.month == 11 and d.day >= 22]
        extra |= {(t + pd.Timedelta(days=1)).date() for t in thanks}  # day after Thanksgiving
        extra |= {date(y, 12, 24), date(y, 12, 31)}
    return {d.date() for d in fed} | extra


def frame() -> pd.DataFrame:
    df = ridership().join(weather(), how="inner").join(games(), how="left").fillna({"game": False, "win": False})
    df = df.reset_index().rename(columns={"index": "date"})
    ts = pd.to_datetime(df["date"])
    hol = holidays()
    df["dow"], df["doy"] = ts.dt.day_of_week, ts.dt.day_of_year
    df["is_holiday"] = df["date"].isin(hol)
    df["msg_event"] = False  # build_design controls; the game is tested as a flag instead
    df["home_game"] = False
    df["hol_week"] = ((ts.dt.month == 12) & (ts.dt.day >= 24)) | ((ts.dt.month == 1) & (ts.dt.day == 1))
    return df


def event_flags(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "rain>=0.01in": df["PRCP"] >= 0.01,  # KXRAIN settlement
        "rain>=1mm": df["PRCP"] >= 0.04,
        "rain>=5mm": df["PRCP"] >= 0.20,
        "hot>85F": df["TMAX"] > 85,  # KXHIGHNY strict >
        "hot>90F": df["TMAX"] > 90,
        "cold<32F": df["TMAX"] < 32,
        "snow>=0.1in": df["SNOW"] >= 0.1,
        "msg_game": df["game"].astype(bool),
        "msg_home_win": df["win"].astype(bool),
    }


def design(d: pd.DataFrame, name: str, flag: pd.Series, t0: pd.Timestamp) -> pd.DataFrame:
    X = build_design(d, {name: flag})
    X["hol_week"] = d["hol_week"].astype(float)
    X["trend"] = (pd.to_datetime(d["date"]) - t0).dt.days / 365.25
    return X


def fit(d: pd.DataFrame, mode: str, name: str, flag: pd.Series):
    y = np.log(d[mode].astype(float))
    ok = y.notna() & np.isfinite(y)
    d, y, flag = d[ok], y[ok], flag[ok]
    X = design(d, name, flag, pd.Timestamp(d["date"].min()))
    if name not in X.columns:
        return None
    res = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS}, use_t=False)
    b, se, p = res.params[name], res.bse[name], res.pvalues[name]
    level = float(d[mode].mean())
    return {"b": b, "se": se, "p": p, "n_ev": int(flag.sum()), "n": len(d), "level": level, "res": res, "X": X}


def in_period(df: pd.DataFrame, period: tuple[date, date]) -> pd.DataFrame:
    return df[(df["date"] >= period[0]) & (df["date"] <= period[1])].reset_index(drop=True)


def backtest(tr: pd.DataFrame, ho: pd.DataFrame, mode: str, name: str, r_train: dict) -> dict:
    """Hedge on holdout using the train fit only. Income = deseasonalised fare revenue, i.e. holdout
    revenue minus the train model's prediction without the event term. Buy the side that pays when
    the event hurts, at train frequency + $0.02 plus fee 0.07 p (1-p), sized |beta_$|/$1."""
    flag_tr = event_flags(tr)[name]
    flag_ho = event_flags(ho)[name].astype(float).to_numpy()
    beta_usd = (np.exp(r_train["b"]) - 1) * r_train["level"] * FARE[mode]
    p_event = float(flag_tr.mean())
    pays_on_event = beta_usd < 0
    p = (p_event if pays_on_event else 1 - p_event) + 0.02
    price = p + 0.07 * p * (1 - p)
    contracts = abs(beta_usd)
    payoff = (flag_ho if pays_on_event else 1 - flag_ho) - price
    # Holdout income: refit only the nuisance part on holdout (no event) so the residual keeps the event effect.
    Xh = design(ho, name, event_flags(ho)[name], pd.Timestamp(ho["date"].min())).drop(columns=[name])
    y = ho[mode].astype(float) * FARE[mode]
    resid = y - sm.OLS(y, Xh).fit().fittedvalues
    hedged = resid + contracts * payoff
    return {
        "beta_usd": beta_usd, "contracts": contracts, "price": price,
        "sd_unhedged": resid.std(), "sd_hedged": hedged.std(),
        "p5_unhedged": np.percentile(resid, 5), "p5_hedged": np.percentile(hedged, 5),
        "mean_cost": float(hedged.mean() - resid.mean()),
    }


def main() -> None:
    df = frame()
    tr, ho = in_period(df, TRAIN), in_period(df, HOLD)
    print(f"rows train={len(tr)} holdout={len(ho)}; missing PRCP={df['PRCP'].isna().sum()} TMAX={df['TMAX'].isna().sum()}")
    rows = []
    for mode in MODES:
        for name in event_flags(df):
            a = fit(tr, mode, name, event_flags(tr)[name])
            h = fit(ho, mode, name, event_flags(ho)[name])
            if a is None or h is None:
                continue
            rows.append({
                "mode": mode, "event": name,
                "tr_pct": 100 * a["b"], "tr_lo": 100 * (a["b"] - Z90 * a["se"]), "tr_hi": 100 * (a["b"] + Z90 * a["se"]),
                "tr_p": a["p"], "tr_nev": a["n_ev"],
                "ho_pct": 100 * h["b"], "ho_lo": 100 * (h["b"] - Z90 * h["se"]), "ho_hi": 100 * (h["b"] + Z90 * h["se"]),
                "ho_p": h["p"], "ho_nev": h["n_ev"],
                "tr_riders": (np.exp(a["b"]) - 1) * a["level"], "ho_riders": (np.exp(h["b"]) - 1) * h["level"],
                "_a": a,
            })
    t = pd.DataFrame(rows)
    t["tr_q"] = multipletests(t["tr_p"], method="fdr_bh")[1]
    t["ho_q"] = multipletests(t["ho_p"], method="fdr_bh")[1]
    sig = lambda lo, hi: (lo > 0) | (hi < 0)  # noqa: E731
    t["found"] = (
        sig(t["tr_lo"], t["tr_hi"]) & (t["tr_nev"] >= 10) & sig(t["ho_lo"], t["ho_hi"])
        & (np.sign(t["tr_pct"]) == np.sign(t["ho_pct"])) & (t["tr_q"] <= 0.10) & (t["ho_q"] <= 0.10)
    )
    print(f"tests: {len(t)} (modes {len(MODES)} x events {len(event_flags(df))})")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 100)
    cols = ["mode", "event", "tr_nev", "tr_pct", "tr_lo", "tr_hi", "tr_q", "ho_nev", "ho_pct", "ho_lo", "ho_hi", "ho_q", "tr_riders", "ho_riders", "found"]
    print(t[cols].round(3).to_string(index=False))
    t[cols].to_csv(OUT / "results.csv", index=False)

    print("\nhedge backtest (holdout, train-fit sizing), FOUND rows:")
    bt = []
    for _, r in t[t["found"]].iterrows():
        b = backtest(tr, ho, r["mode"], r["event"], r["_a"])
        bt.append({"mode": r["mode"], "event": r["event"], **b})
    if bt:
        b = pd.DataFrame(bt)
        print(b.round(2).to_string(index=False))
        b.to_csv(OUT / "backtest.csv", index=False)


if __name__ == "__main__" and "--robust" not in sys.argv:
    main()


def robustness() -> None:
    """Rain >= 0.01 in without the extreme storms (PRCP > 1.5 in), and NOAA vs Open-Meteo flag agreement."""
    df = frame()
    for label, period in (("train", TRAIN), ("holdout", HOLD)):
        d = in_period(df, period)
        d = d[d["PRCP"] <= 1.5].reset_index(drop=True)
        for mode in MODES:
            r = fit(d, mode, "rain>=0.01in", d["PRCP"] >= 0.01)
            print(f"no-storm {label:7s} {mode:6s} {100*r['b']:6.2f}% [{100*(r['b']-Z90*r['se']):6.2f}, {100*(r['b']+Z90*r['se']):6.2f}] n={r['n']}")
    om = pd.read_parquet(Path(__file__).resolve().parents[3] / "backend/fixtures/weather_station.parquet")
    om["date"] = pd.to_datetime(om["date"]).dt.date
    j = om.set_index("date").join(df.set_index("date")[["PRCP", "TMAX"]], how="inner")
    a, b = j["precipitation_sum"] >= 0.01, j["PRCP"] >= 0.01
    print(f"Open-Meteo vs NOAA, {len(j)} overlapping days: rain flag agreement {(a == b).mean():.3f}, "
          f"phi {np.corrcoef(a, b)[0, 1]:.3f}; tmax corr {j['temperature_2m_max'].corr(j['TMAX']):.3f}")


if __name__ == "__main__" and "--robust" in sys.argv:
    robustness()
