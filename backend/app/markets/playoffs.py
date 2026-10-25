"""Playoff home-game exposure and minimum-variance hedges with Kalshi advancement contracts.

Ported from experiments/bar/r5-markets/hedge.py (numpy only; floats are fine here because these
are model statistics, not money: callers quantize to Decimal before anything reaches a contract).
The season-level additions (a make-playoffs stage before round 1, `preseason_rounds`) are at the
end of the file.

Model
-----
A series is played between team A (holds home-court advantage) and team B. Each game is
an independent Bernoulli trial: A wins a game it hosts with prob sigma(theta + edge) and a
game B hosts with prob sigma(theta - edge), where theta is A's strength over B in logit
units and `edge` is the league's home edge. Given a series price, `implied_theta` inverts
the model, so per-game win probabilities come from the market.

A playoff run is a sequence of rounds; `season_paths` enumerates every path (round
reached, home court, exact series score) with its probability. Revenue = U x home games.

Hedge
-----
Any Kalshi contract on these outcomes is a payoff vector over paths (series winner,
series length, exact score, conference / league champion). `min_variance_hedge` solves
    n* = argmin Var(U*H + n.(X - price)) = -Cov(X)^-1 Cov(X, U*H),
which is the weighted least-squares projection of revenue on the contract payoffs. A
positive n buys YES at the ask; a negative n buys |n| NO at (1 - bid). Its cost is the
premium above fair value (the vig/spread) plus the Kalshi taker fee 0.07 p (1 - p).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import exp, log

import numpy as np

# Who hosts game i: True = the team with home-court advantage.
FORMATS: dict[str, tuple[bool, ...]] = {
    "2-2-1-1-1": (True, True, False, False, True, False, True),  # NBA, NHL best-of-7
    "2-3-2": (True, True, False, False, False, True, True),  # MLB LCS / World Series
    "2-2-1": (True, True, False, False, True),  # MLB Division Series, best-of-5
    "3-0": (True, True, True),  # MLB Wild Card, best-of-3 all at the higher seed
    "1": (True,),  # NFL single game at the higher seed
    "neutral": (None,),  # Super Bowl: neither team hosts
}

# Home edge in logit units: sigma(edge) = P(home team wins a game between equals).
# Rough long-run values (NBA ~57%, NHL ~54%, MLB ~53%, NFL ~56%).
HOME_EDGE = {"nba": 0.28, "nhl": 0.16, "mlb": 0.12, "nfl": 0.24}

FEE_RATE = 0.07


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + exp(-x))


def logit(p: float) -> float:
    return log(p / (1.0 - p))


def wins_needed(fmt: str) -> int:
    return len(FORMATS[fmt]) // 2 + 1


# ---------------------------------------------------------------- one series


def score_distribution(fmt: str, theta: float, edge: float = 0.0) -> dict[tuple[int, int], float]:
    """P(final score = (A wins, B wins)) for a series where A holds home court."""
    hosts = FORMATS[fmt]
    need = wins_needed(fmt)
    p_home, p_away = sigmoid(theta + edge), sigmoid(theta - edge)
    p_neutral = sigmoid(theta)
    states = {(0, 0): 1.0}
    final: dict[tuple[int, int], float] = {}
    while states:
        nxt: dict[tuple[int, int], float] = {}
        for (a, b), pr in states.items():
            host = hosts[a + b]
            p = p_neutral if host is None else (p_home if host else p_away)
            for s, q in (((a + 1, b), p), ((a, b + 1), 1 - p)):
                tgt = final if need in s else nxt
                tgt[s] = tgt.get(s, 0.0) + pr * q
        states = nxt
    return final


def series_win_prob(fmt: str, theta: float, edge: float = 0.0) -> float:
    need = wins_needed(fmt)
    return sum(p for (a, _), p in score_distribution(fmt, theta, edge).items() if a == need)


def implied_theta(price_a: float, fmt: str, edge: float = 0.0) -> float:
    """Strength theta such that P(A wins the series) equals the market price."""
    price_a = min(max(price_a, 1e-4), 1 - 1e-4)
    lo, hi = -12.0, 12.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if series_win_prob(fmt, mid, edge) < price_a:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def home_games(fmt: str, games: int, has_home_court: bool) -> int:
    """Games hosted by one side in a series that lasted `games` games."""
    hosts = FORMATS[fmt][:games]
    if hosts[0] is None:
        return 0
    top = sum(hosts)
    return top if has_home_court else games - top


def home_games_distribution(fmt: str, theta: float, has_home_court: bool, edge: float = 0.0) -> dict[int, float]:
    """Distribution of home games for one side; theta is the home-court team's strength."""
    out: dict[int, float] = {}
    for (a, b), p in score_distribution(fmt, theta, edge).items():
        h = home_games(fmt, a + b, has_home_court)
        out[h] = out.get(h, 0.0) + p
    return dict(sorted(out.items()))


# ---------------------------------------------------------------- a playoff run


@dataclass
class Round:
    """One round as seen from our team.

    p_win: probability our team wins the series (e.g. the Kalshi series price, or the
    ratio of consecutive futures prices). p_home: probability our team holds home court.
    """

    fmt: str
    p_win: float
    p_home: float = 1.0
    edge: float = 0.0
    name: str = ""


@dataclass
class Leg:
    reached: bool
    has_home: bool = False
    us: int = 0  # our series wins
    them: int = 0
    won: bool = False
    home: int = 0  # home games we hosted this round


@dataclass
class Path:
    prob: float
    legs: list[Leg] = field(default_factory=list)

    @property
    def home_games(self) -> int:
        return sum(l.home for l in self.legs)


def _round_outcomes(r: Round) -> list[tuple[float, Leg]]:
    need = wins_needed(r.fmt)
    out = []
    for has_home, ph in ((True, r.p_home), (False, 1 - r.p_home)):
        if ph <= 0:
            continue
        # Fit strength to the series price from our side, then express it for A.
        if has_home:
            theta = implied_theta(r.p_win, r.fmt, r.edge)
        else:
            theta = implied_theta(1 - r.p_win, r.fmt, r.edge)
        for (a, b), p in score_distribution(r.fmt, theta, r.edge).items():
            us, them = (a, b) if has_home else (b, a)
            out.append((ph * p, Leg(True, has_home, us, them, us == need, home_games(r.fmt, a + b, has_home))))
    return out


def season_paths(rounds: list[Round]) -> list[Path]:
    """Every way the run can go, with probabilities summing to 1."""
    paths = [Path(1.0)]
    for k, r in enumerate(rounds):
        nxt = []
        for path in paths:
            if k and not path.legs[-1].won:
                nxt.append(Path(path.prob, path.legs + [Leg(False)]))
                continue
            for p, leg in _round_outcomes(r):
                nxt.append(Path(path.prob * p, path.legs + [leg]))
        paths = nxt
    return paths


def season_home_games_distribution(rounds: list[Round]) -> dict[int, float]:
    out: dict[int, float] = {}
    for p in season_paths(rounds):
        out[p.home_games] = out.get(p.home_games, 0.0) + p.prob
    return dict(sorted(out.items()))


def rounds_from_futures(ladder: list[float], fmts: list[str], p_home: list[float], edge: float = 0.0) -> list[Round]:
    """Rounds from cumulative advancement prices, e.g. [P(win R1), P(win R2), P(conf), P(title)].

    P(win round k | reached it) = ladder[k] / ladder[k-1]."""
    rounds, prev = [], 1.0
    for k, (q, fmt, ph) in enumerate(zip(ladder, fmts, p_home)):
        cond = min(max(q / prev if prev > 0 else 0.0, 1e-4), 1 - 1e-4)
        rounds.append(Round(fmt, cond, ph, edge, f"R{k + 1}"))
        prev = q
    return rounds


# ---------------------------------------------------------------- contracts


@dataclass
class Contract:
    """A Kalshi YES contract paying $1 on `payoff(path)`; ask/bid in dollars."""

    name: str
    payoff: callable
    ask: float
    bid: float | None = None

    def __post_init__(self) -> None:
        if self.bid is None:
            self.bid = self.ask


def advance(k: int) -> callable:
    """Wins round k (0-based): series winner / conference / league champion."""
    return lambda path: float(len(path.legs) > k and path.legs[k].won)


def games_at_least(k: int, g: int) -> callable:
    """Round k is played and lasts at least g games (KX*SERIESGAMES 'above g-0.5')."""
    return lambda path: float(len(path.legs) > k and path.legs[k].reached and path.legs[k].us + path.legs[k].them >= g)


def exact_score(k: int, us: int, them: int) -> callable:
    """Round k ends us-them from our side (KX*SERIESSCORE)."""
    return lambda path: float(
        len(path.legs) > k and path.legs[k].reached and (path.legs[k].us, path.legs[k].them) == (us, them)
    )


def fee(price: float) -> float:
    return FEE_RATE * price * (1 - price)


@dataclass
class HedgeResult:
    contracts: list[str]
    n: np.ndarray  # YES-equivalent contracts: + buy YES, - buy NO
    mean: float  # E[revenue] unhedged
    sd_before: float
    sd_after: float
    premium: float  # cash paid up front for the hedge
    expected_payout: float  # model-fair value of what was bought
    fees: float

    @property
    def variance_removed(self) -> float:
        return 1 - (self.sd_after / self.sd_before) ** 2 if self.sd_before > 0 else 0.0

    @property
    def cost(self) -> float:
        """Expected loss of the hedge: premium + fees - fair payout (the price of certainty)."""
        return self.premium + self.fees - self.expected_payout


def payoff_matrix(paths: list[Path], contracts: list[Contract]) -> np.ndarray:
    return np.array([[c.payoff(p) for c in contracts] for p in paths], dtype=float)


def min_variance_hedge(
    paths: list[Path], contracts: list[Contract], uplift: float = 1.0, target=None
) -> HedgeResult:
    """Minimum-variance position in `contracts` against revenue = uplift x target(path).

    target defaults to the path's home games."""
    w = np.array([p.prob for p in paths])
    w = w / w.sum()
    y = uplift * np.array([(target(p) if target else p.home_games) for p in paths], dtype=float)
    X = payoff_matrix(paths, contracts)
    ym, Xm = w @ y, w @ X
    yc, Xc = y - ym, X - Xm
    S = (Xc * w[:, None]).T @ Xc
    c = (Xc * w[:, None]).T @ yc
    n = -np.linalg.pinv(S, rcond=1e-10) @ c
    n[np.abs(n) < 1e-9] = 0.0
    resid = yc + Xc @ n
    ask = np.array([k.ask for k in contracts])
    bid = np.array([k.bid for k in contracts])
    buy_yes = n > 0
    px = np.where(buy_yes, ask, 1 - bid)  # price per contract actually bought
    fair = np.where(buy_yes, Xm, 1 - Xm)
    qty = np.abs(n)
    return HedgeResult(
        contracts=[k.name for k in contracts],
        n=n,
        mean=float(ym),
        sd_before=float(np.sqrt(w @ yc**2)),
        sd_after=float(np.sqrt(max(w @ resid**2, 0.0))),
        premium=float(qty @ px),
        expected_payout=float(qty @ fair),
        fees=float(qty @ np.array([fee(p) for p in px])),
    )


def hedge_pnl(result: HedgeResult, contracts: list[Contract], path: Path) -> float:
    """Realised cash P&L of the hedge on one outcome (payout - premium - fees)."""
    x = np.array([c.payoff(path) for c in contracts])
    n = result.n
    paid = np.where(n > 0, x, 1 - x)
    return float(np.abs(n) @ paid) - result.premium - result.fees


def series_contracts(
    k: int, fmt: str, *, win: tuple[float, float] | None = None, games: dict[int, tuple[float, float]] | None = None,
    scores: dict[tuple[int, int], tuple[float, float]] | None = None,
) -> list[Contract]:
    """Kalshi contracts on round k. Prices are (ask, bid) for YES from our team's side."""
    out = []
    if win:
        out.append(Contract(f"R{k + 1} win", advance(k), *win))
    for g, (a, b) in sorted((games or {}).items()):
        out.append(Contract(f"R{k + 1} {g}+ games", games_at_least(k, g), a, b))
    for (u, t), (a, b) in sorted((scores or {}).items()):
        out.append(Contract(f"R{k + 1} {u}-{t}", exact_score(k, u, t), a, b))
    return out


def all_scores(fmt: str) -> list[tuple[int, int]]:
    need = wins_needed(fmt)
    return [(need, j) for j in range(need)] + [(j, need) for j in range(need)]





def paths_from_scores(fmt: str, has_home: bool, probs: dict[tuple[int, int], float]) -> list[Path]:
    """One-round paths from a priced exact-score ladder {(us, them): p}, e.g. KX*SERIESSCORE mids.

    Probabilities are renormalised so an overround (sum of mids > 1) does not leak in."""
    need = wins_needed(fmt)
    total = sum(probs.values())
    return [
        Path(p / total, [Leg(True, has_home, u, t, u == need, home_games(fmt, u + t, has_home))])
        for (u, t), p in probs.items()
        if p > 0
    ]


# ---------------------------------------------------------------- season level (before the playoffs)


def made_playoffs(path: Path) -> float:
    """KX*PLAYOFF: the team qualifies (a missed season is a path with no legs)."""
    return float(bool(path.legs))


def season_paths_with_qualifier(p_make: float, rounds: list[Round]) -> list[Path]:
    """`season_paths` preceded by the make-playoffs stage: miss with prob 1 - p_make (0 home games)."""
    p_make = min(max(p_make, 0.0), 1.0)
    made = [Path(p.prob * p_make, p.legs) for p in season_paths(rounds)] if p_make > 0 else []
    return ([Path(1.0 - p_make)] if p_make < 1 else []) + made


def preseason_rounds(
    p_make: float, p_conf: float, p_title: float, fmt: str = "2-2-1-1-1", *, edge: float = 0.0,
    p_home: float = 0.5, conf_rounds: int = 3,
) -> list[Round]:
    """Rounds conditional on making the playoffs, from season futures only.

    Before the season there are no series prices, so P(win the conference | made) is spread
    geometrically over the `conf_rounds` conference rounds, and the final is
    P(title) / P(conference). Home court is unknown and taken as `p_home` in every round.
    """
    if not 0 < p_title <= p_conf <= p_make <= 1:
        raise ValueError("need 0 < P(title) <= P(conference) <= P(make playoffs) <= 1")
    per_round = (p_conf / p_make) ** (1 / conf_rounds)
    ladder = [p_make * per_round ** (k + 1) for k in range(conf_rounds)] + [p_title]
    scaled = [q / p_make for q in ladder]
    return rounds_from_futures(scaled, [fmt] * (conf_rounds + 1), [p_home] * (conf_rounds + 1), edge)


def expected(paths: list[Path], f) -> float:
    w = np.array([p.prob for p in paths])
    return float(w @ np.array([f(p) for p in paths], dtype=float) / w.sum())


def swing(paths: list[Path], payoff, target=None) -> float:
    """E[target | contract pays] - E[target | it doesn't]: what the stage puts at stake."""
    t = target or (lambda p: p.home_games)
    yes = [p for p in paths if payoff(p) > 0.5]
    no = [p for p in paths if payoff(p) <= 0.5]
    if not yes or not no:
        return 0.0
    return expected(yes, t) - expected(no, t)
