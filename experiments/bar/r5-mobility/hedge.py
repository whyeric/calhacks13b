"""Q2 exposure per round and Q3 hedge backtest for MSG-area mobility businesses (r5-mobility).

Series model. Best-of-7, 2-2-1-1-1: the home-court team hosts games 1, 2, 5, 7. A per-game win
probability q (+/- HOME_EDGE at home/away) is solved so that P(win series) equals the pre-series
Kalshi price (r5-markets series_quotes.csv, KXNBASERIES / KXNHLSERIES, 2025-26), or 0.5 where no
market existed (2022-24). Enumerating the 2^7 game paths gives the joint law of (series won, home
games played).

Exposure. Value of advancing out of round r = U x sum over later rounds k of
P(reach k | won r) x E[home games in k], with later rounds priced at 0.5 and a 50% chance of home
court (they are not known when round r starts). U is the $ uplift per playoff home game.

Hedge. Before each series buy N_r = (value of advancing out of r) / $1 of "opponent wins the series"
YES at the pre-series price + $0.01 half-spread + fee 0.07 p (1-p). It pays exactly when the
team's later home games vanish. Backtest over the 7 NY playoff team-seasons 2022-26, then a
simulation of 20,000 playoff runs from the same prices.
"""

from __future__ import annotations

import itertools
from functools import lru_cache

import numpy as np
import pandas as pd

HOME_EDGE = 0.04
HC_GAMES = (1, 1, 0, 0, 1, 0, 1)  # game i at the home-court team's arena
QUOTES = "/Users/main/calhacks13b/experiments/bar/r5-markets/series_quotes.csv"
ROUND = {"R1": 1, "R2": 2, "CF": 3, "F": 4}
ABBR = {"knicks": ("nba", "NYK"), "rangers": ("nhl", "NYR")}


@lru_cache(maxsize=None)
def _paths(q: float, hc: bool) -> tuple[tuple[bool, int, float], ...]:
    """(won, home games played, prob) for every distinct series outcome."""
    out: dict[tuple[bool, int], float] = {}
    for seq in itertools.product((1, 0), repeat=7):
        w = l = home = 0
        pr = 1.0
        for i, g in enumerate(seq):
            at_home = HC_GAMES[i] == (1 if hc else 0)
            p = q + HOME_EDGE if at_home else q - HOME_EDGE
            pr *= p if g else 1 - p
            home += at_home
            w, l = w + g, l + (1 - g)
            if w == 4 or l == 4:
                break
        # each truncated path is generated 2^(7-len) times; weight once
        n = w + l
        if seq[n:] != (1,) * (7 - n):
            continue
        out[(w == 4, home)] = out.get((w == 4, home), 0.0) + pr
    return tuple((k[0], k[1], v) for k, v in out.items())


def series_stats(q: float, hc: bool) -> tuple[float, float]:
    """(P win, E home games)."""
    ps = _paths(round(q, 4), hc)
    return sum(p for w, _, p in ps if w), sum(h * p for _, h, p in ps)


def solve_q(p_win: float, hc: bool) -> float:
    lo, hi = 0.05, 0.95
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if series_stats(mid, hc)[0] < p_win else (lo, mid)
    return (lo + hi) / 2


E_H_FUTURE = (series_stats(0.5, True)[1] + series_stats(0.5, False)[1]) / 2


def advance_value(r: int, u: float) -> float:
    """$ value of the home games in rounds after r, seen from the start of round r (later p = 0.5)."""
    return u * sum(0.5 ** (k - r - 1) * E_H_FUTURE for k in range(r + 1, 5))


def fee(p: float) -> float:
    return 0.07 * p * (1 - p)


def nyk_nyr_series(games: pd.DataFrame) -> pd.DataFrame:
    """One row per NY playoff series 2022-26: team, season, round, home court, won, home games, price."""
    q = pd.read_csv(QUOTES)
    post = games[games.stype == "post"]
    rows = []
    for (team, season, rnd), g in post.groupby(["team", "season", "round"]):
        g = g.sort_values("game_no")
        hc = bool(g.iloc[0].home)  # game 1 at MSG = home court
        won = int(g.won.sum()) == 4
        lg, ab = ABBR[team]
        m = q[(q.league == lg) & (q.season == season) & (q["round"].map(ROUND) == rnd)
              & ((q.a == ab) | (q.b == ab))]
        price = np.nan
        if len(m):
            m = m.iloc[0]
            price = m.p_a if m.a == ab else 1 - m.p_a
        rows.append({"team": team, "season": season, "round": int(rnd), "home_court": hc, "won": won,
                     "home_games": int(g.home.sum()), "p_win": price, "priced": len(m) > 0})
    return pd.DataFrame(rows)


def backtest(series: pd.DataFrame, u: float) -> pd.DataFrame:
    rows = []
    for (team, season), s in series.groupby(["team", "season"]):
        rev = u * s.home_games.sum()
        pnl = cost = 0.0
        for _, r in s.sort_values("round").iterrows():
            p = r.p_win if r.priced else 0.5
            n = advance_value(r["round"], u)
            px = min(1 - p + 0.01, 0.99)
            cost += n * (px + fee(px))
            pnl += n * (0 if r.won else 1)
        rows.append({"team": team, "season": season, "rounds": len(s), "home_games": int(s.home_games.sum()),
                     "priced": bool(s.priced.all()), "revenue": rev, "hedge_cost": cost, "hedge_payout": pnl,
                     "hedged": rev + pnl - cost})
    return pd.DataFrame(rows)


def simulate(p_rounds: list[float], hc_rounds: list[bool], u: float, n: int = 20000, seed: int = 0) -> dict:
    """Playoff runs from R1 with the given series prices; unhedged vs per-round hedged revenue."""
    rng = np.random.default_rng(seed)
    laws = []
    for p, hc in zip(p_rounds, hc_rounds):
        ps = _paths(round(solve_q(p, hc), 4), hc)
        laws.append(([(w, h) for w, h, _ in ps], np.array([x for *_, x in ps]) / sum(x for *_, x in ps)))
    rev, hed = np.zeros(n), np.zeros(n)
    for i in range(n):
        tot = cash = 0.0
        for r, (p, (outs, pr)) in enumerate(zip(p_rounds, laws), start=1):
            w, h = outs[rng.choice(len(outs), p=pr)]
            tot += u * h
            nr = advance_value(r, u)
            px = min(1 - p + 0.01, 0.99)
            cash += -nr * (px + fee(px)) + (0 if w else nr)
            if not w:
                break
        rev[i], hed[i] = tot, tot + cash
    return {"mean_unhedged": rev.mean(), "mean_hedged": hed.mean(), "sd_unhedged": rev.std(),
            "sd_hedged": hed.std(), "p5_unhedged": np.percentile(rev, 5), "p5_hedged": np.percentile(hed, 5)}


def home_game_law(p_rounds: list[float], hc_rounds: list[bool]) -> pd.Series:
    """Distribution of total playoff home games (given the team makes R1)."""
    alive = {0: 1.0}
    final: dict[int, float] = {}
    for p, hc in zip(p_rounds, hc_rounds):
        ps = _paths(round(solve_q(p, hc), 4), hc)
        nxt: dict[int, float] = {}
        for h0, a in alive.items():
            for w, h, x in ps:
                tgt = nxt if w else final
                tgt[h0 + h] = tgt.get(h0 + h, 0.0) + a * x
        alive = nxt
    for h, a in alive.items():
        final[h] = final.get(h, 0.0) + a
    return pd.Series(final).sort_index()
