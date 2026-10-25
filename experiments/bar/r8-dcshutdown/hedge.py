"""R8 dcshutdown: size and backtest a Kalshi shutdown hedge for a downtown DC lunch spot.

Run from backend/:  .venv/bin/python ../experiments/bar/r8-dcshutdown/hedge.py
Needs r2-cache/r8dc_kalshi_{markets,candles}.json (fetch_kalshi.py) and results.csv (run.py).

Business (illustrative): weekday revenue REV, losing LOSS_PCT of it on every shutdown weekday (the
federal-cluster Capital Bikeshare drop, pass-through 1, an assumption). Prices are daily yes_ask closes;
every buy pays the Kalshi taker fee 0.07*p*(1-p) per contract.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path("/private/tmp/claude-501/-Users-main-calhacks13b/43b08917-9062-42af-af8e-5a2dba84245f/scratchpad/r2-cache")
OUT = Path(__file__).resolve().parent
REV = 4000.0  # $ per weekday (~$1M/yr)
R = pd.read_csv(OUT / "results.csv")
fed = R[(R["sample"].isin(["pre", "post"])) & (R.daytype == "weekday") & (R.y == "l_fed") & (R.spec == "B")
        & R.term.isin(["s2018", "s2025"])].set_index("term").pct
LOSS_PCT = -fed.mean() / 100  # mean of the two independent estimates
PER_WD = REV * LOSS_PCT
PER_CAL = PER_WD * 5 / 7  # loss per calendar day of shutdown

M = {m["ticker"]: m for m in json.load(open(CACHE / "r8dc_kalshi_markets.json"))}
C = json.load(open(CACHE / "r8dc_kalshi_candles.json"))


def fee(p: float) -> float:
    return 0.07 * p * (1 - p)


def ask(ticker: str) -> pd.Series:
    rows = {}
    for c in C.get(ticker, []):
        d = pd.Timestamp(c["end_period_ts"], unit="s", tz="UTC").tz_convert("America/New_York").date()
        a = (c.get("yes_ask") or {}).get("close", (c.get("yes_ask") or {}).get("close_dollars"))
        p = (c.get("price") or {}).get("close", (c.get("price") or {}).get("close_dollars"))
        v = float(a) if a not in (None, "") else (float(p) if p not in (None, "") else np.nan)
        rows[pd.Timestamp(d)] = v
    s = pd.Series(rows).sort_index()
    return s[(s > 0) & (s < 1)] if len(s) else s


def price_on(ticker: str, day: str) -> float:
    s = ask(ticker)
    s = s[s.index <= pd.Timestamp(day)]
    return float(s.iloc[-1]) if len(s) else np.nan


def won(ticker: str) -> int:
    return int(M[ticker].get("result") == "yes")


def weekdays(a: str, b: str) -> int:
    hol = pd.to_datetime(["2025-10-13", "2025-11-11"])
    d = pd.bdate_range(a, b)
    return int((~d.isin(hol)).sum())


def backtest_2025() -> pd.DataFrame:
    D = 43
    loss = PER_WD * weekdays("2025-10-01", "2025-11-12")
    out = []
    pre_strip = {0: 3, 3: 2, 5: 5, 10: 25, 35: 10}  # calendar-day widths, ladder listed by Sep 5, cap 45 days
    for day in ["2025-09-10", "2025-09-16", "2025-09-22", "2025-09-26", "2025-09-30"]:
        # (a) binary: N contracts of 'shut down on Oct 1', N = loss of a 21-day shutdown
        n = PER_CAL * 21
        t = "KXGOVSHUT-25OCT01" if pd.Timestamp(day) >= pd.Timestamp("2025-09-16") else "KXGOVSHUTLENGTH-26JAN01-0D"
        p = price_on(t, day)
        out.append(dict(buy=day, hedge=f"binary {t.split('-',1)[1]}", contracts=round(n), cost=n * (p + fee(p)),
                        payoff=n * won(t), price=p))
        # (b) duration strip on the strikes that existed before the deadline
        cost = pay = 0.0
        ps = []
        for k, w in pre_strip.items():
            tk = f"KXGOVSHUTLENGTH-26JAN01-{k}D"
            pk = price_on(tk, day)
            ps.append(f"{k}D@{pk:.2f}")
            cost += w * PER_CAL * (pk + fee(pk))
            pay += w * PER_CAL * won(tk)
        out.append(dict(buy=day, hedge="strip 0/3/5/10/35D", contracts=round(45 * PER_CAL), cost=cost, payoff=pay,
                        price=" ".join(ps)))
    # (c) buy duration after the shutdown began, over the strikes that have a price that day; contract k
    # covers calendar days (k, next strike], last one capped at 60 days.
    for day in ("2025-10-01", "2025-10-03", "2025-10-11"):
        prev = (pd.Timestamp(day) - pd.Timestamp("2025-10-01")).days
        ks = sorted(int(t.rsplit("-", 1)[1][:-1]) for t in M if t.startswith("KXGOVSHUTLENGTH-26JAN01-"))
        ks = [k for k in ks if k > prev and not np.isnan(price_on(f"KXGOVSHUTLENGTH-26JAN01-{k}D", day))]
        cost = pay = 0.0
        ps = []
        for i, k in enumerate(ks):
            w = (ks[i + 1] if i + 1 < len(ks) else 60) - k
            if w <= 0 or k >= 60:
                continue
            tk = f"KXGOVSHUTLENGTH-26JAN01-{k}D"
            pk = price_on(tk, day)
            ps.append(f"{k}D@{pk:.2f}")
            cost += w * PER_CAL * (pk + fee(pk))
            pay += w * PER_CAL * won(tk)
        out.append(dict(buy=day, hedge="in-shutdown strip", contracts=round((60 - min(ks)) * PER_CAL), cost=cost,
                        payoff=pay, price=" ".join(ps)))
    df = pd.DataFrame(out)
    df["net_hedge"] = df.payoff - df.cost
    df["loss"] = loss
    df["net_outcome"] = -loss + df.net_hedge
    return df


def deadline_program() -> pd.DataFrame:
    """Every 'shut down on <deadline>' contract Kalshi listed, bought 7 and 2 days before at the ask."""
    tick = [t for t in M if (t.startswith("GOVSHUT-") or t.startswith("KXGOVSHUT-") or
                              t.startswith("KXGOVTSHUTDOWN-")) and M[t].get("status") in ("finalized", "settled")]
    rows = []
    for t in sorted(tick, key=lambda t: M[t]["close_time"]):
        close = pd.Timestamp(M[t]["close_time"][:10])
        for lead in (7, 2):
            p = price_on(t, str((close - pd.Timedelta(days=lead)).date()))
            if np.isnan(p):
                continue
            rows.append(dict(market=t, deadline=close.date(), lead_days=lead, ask=p, result=M[t].get("result"),
                             vol=float(M[t].get("volume") or M[t].get("volume_fp") or 0)))
    df = pd.DataFrame(rows)
    # One market per funding fight: deadlines within 10 days of each other are the same fight; keep the
    # highest-volume market of each (and drop thin markets under 10k contracts).
    df = df[df.vol >= 10000].copy()
    dl = pd.to_datetime(df.drop_duplicates("market").set_index("market").deadline).sort_values()
    fight = (dl.diff().dt.days.fillna(99) > 10).cumsum()
    best = df.drop_duplicates("market").assign(fight=df.drop_duplicates("market").market.map(fight))
    keep = best.sort_values("vol").groupby("fight").market.last()
    return df[df.market.isin(keep)]


def simulate(n=200_000, seed=0) -> pd.DataFrame:
    """Q4 revenue of the lunch spot over one funding deadline, unhedged vs hedged at fair + $0.02 + fee."""
    rng = np.random.default_rng(seed)
    base = 62 * REV
    rows = []
    for p_shut in (0.1, 0.3, 0.5, 0.8):
        for med in (7, 21, 40):
            S = rng.random(n) < p_shut
            Dur = np.where(S, np.ceil(rng.lognormal(np.log(med), 0.8, n)).clip(1, 90), 0)
            loss = PER_CAL * Dur
            rev = base * (1 + rng.normal(0, 0.05, n)) - loss
            # binary: N = E[loss | shutdown]; strip: one contract per calendar day per $PER_CAL up to 60 days
            q = p_shut
            Nb = loss[S].mean() if S.any() else 0
            bin_cost = Nb * (min(q + 0.02, 0.99) + fee(q))
            hb = rev - bin_cost + Nb * S
            ks = np.arange(0, 60)
            fair = np.array([(Dur > k).mean() for k in ks])
            strip_cost = PER_CAL * np.sum(np.minimum(fair + 0.02, 0.99) + 0.07 * fair * (1 - fair))
            hs = rev - strip_cost + PER_CAL * np.minimum(Dur, 60)
            for name, x in (("none", rev), ("binary", hb), ("strip", hs)):
                rows.append(dict(p_shut=p_shut, median_days=med, hedge=name, mean=x.mean(), sd=x.std(),
                                 p5=np.quantile(x, 0.05), p1=np.quantile(x, 0.01)))
    df = pd.DataFrame(rows)
    nb = df[df.hedge == "none"].set_index(["p_shut", "median_days"])
    for c in ("sd", "p5", "mean"):
        df[f"{c}_vs_none"] = df.apply(lambda r: r[c] - nb.loc[(r.p_shut, r.median_days), c], axis=1)
    df["sd_cut_pct"] = df.apply(lambda r: 100 * (1 - r.sd / nb.loc[(r.p_shut, r.median_days), "sd"]), axis=1)
    return df


def timing() -> pd.DataFrame:
    tks = ["KXSHUTDOWNBY-25", "KXGOVSHUTLENGTH-26JAN01-0D", "KXGOVSHUT-25OCT01", "KXGOVSHUTLENGTH-26JAN01-10D",
           "KXGOVSHUTLENGTH-26JAN01-35D", "KXGOVSHUTLENGTH-26JAN01-40D", "KXGOVSHUTLENGTH-26JAN01-45D"]
    days = ["2025-08-01", "2025-09-02", "2025-09-10", "2025-09-16", "2025-09-19", "2025-09-22", "2025-09-26",
            "2025-09-30", "2025-10-01", "2025-10-08", "2025-10-15", "2025-10-22", "2025-10-29", "2025-11-05",
            "2025-11-10"]
    return pd.DataFrame({t: [price_on(t, d) for d in days] for t in tks}, index=days)


def main() -> None:
    pd.set_option("display.width", 250)
    print(f"loss per shutdown weekday {100*LOSS_PCT:.1f}% of ${REV:.0f} = ${PER_WD:.0f}; per calendar day ${PER_CAL:.0f}")
    B = backtest_2025()
    B.to_csv(OUT / "hedge_2025.csv", index=False)
    print(B.round(0).to_string())
    T = timing()
    T.to_csv(OUT / "prices_2025.csv")
    print(T.round(2).to_string())
    P = deadline_program()
    P.to_csv(OUT / "deadline_prices.csv", index=False)
    print(P.to_string())
    # Rolling binary program: before every listed deadline buy N = loss of a 21-day shutdown.
    # Realised losses: 2025 (29 weekdays), Jan 31-Feb 3 2026 (2 weekdays), DHS-only lapse 0 (measured ~0).
    N = PER_CAL * 21
    real = {"KXGOVSHUT-25OCT01": PER_WD * weekdays("2025-10-01", "2025-11-12"),
            "KXGOVSHUT-26JAN31": PER_WD * 2, "KXGOVTSHUTDOWN-26FEB14": 0.0}
    for lead in (7, 2):
        q = P[P.lead_days == lead]
        cost = (N * (q.ask + q.ask.map(fee))).sum()
        pay = N * (q.result == "yes").sum()
        loss = sum(real.values())
        print(f"program lead {lead}d: {len(q)} deadlines, cost ${cost:,.0f}, payoff ${pay:,.0f}, "
              f"losses ${loss:,.0f}, unhedged ${-loss:,.0f} -> hedged ${pay - cost - loss:,.0f}")
    S = simulate()
    S.to_csv(OUT / "hedge_sim.csv", index=False)
    print(S.round(2).to_string())


if __name__ == "__main__":
    main()
