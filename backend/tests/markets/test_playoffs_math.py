"""Ported from experiments/bar/r5-markets/test_hedge.py (37 tests), plus the season-level helpers."""
import math

import pytest

from app.markets import playoffs as h

BO7 = "2-2-1-1-1"


def test_bo7_length_distribution_coin_flip():
    d = h.score_distribution(BO7, 0.0)
    by_len = {}
    for (a, b), p in d.items():
        by_len[a + b] = by_len.get(a + b, 0) + p
    assert by_len == pytest.approx({4: 1 / 8, 5: 1 / 4, 6: 5 / 16, 7: 5 / 16})
    assert sum(d.values()) == pytest.approx(1)
    assert len(d) == 8


def test_series_prob_known_value():
    # p = 0.6 per game, best of 7: 0.710208
    assert h.series_win_prob(BO7, h.logit(0.6)) == pytest.approx(0.710208, abs=1e-6)
    assert h.series_win_prob(BO7, 0.0, edge=0.0) == pytest.approx(0.5)
    # Home court is worth something with a home edge.
    assert h.series_win_prob(BO7, 0.0, edge=0.3) > 0.5


@pytest.mark.parametrize("fmt", ["2-2-1-1-1", "2-3-2", "2-2-1", "3-0", "1"])
@pytest.mark.parametrize("price", [0.08, 0.35, 0.5, 0.77, 0.95])
def test_implied_theta_roundtrip(fmt, price):
    th = h.implied_theta(price, fmt, edge=0.2)
    assert h.series_win_prob(fmt, th, edge=0.2) == pytest.approx(price, abs=1e-6)


def test_home_game_counts():
    assert [h.home_games(BO7, n, True) for n in (4, 5, 6, 7)] == [2, 3, 3, 4]
    assert [h.home_games(BO7, n, False) for n in (4, 5, 6, 7)] == [2, 2, 3, 3]
    assert [h.home_games("2-3-2", n, True) for n in (4, 5, 6, 7)] == [2, 2, 3, 4]
    assert [h.home_games("2-3-2", n, False) for n in (4, 5, 6, 7)] == [2, 3, 3, 3]
    assert [h.home_games("3-0", n, False) for n in (2, 3)] == [0, 0]
    assert h.home_games("neutral", 1, True) == 0


def test_expected_home_games_coin_flip():
    d = h.home_games_distribution(BO7, 0.0, True)
    assert d == pytest.approx({2: 1 / 8, 3: 1 / 4 + 5 / 16, 4: 5 / 16})
    d2 = h.home_games_distribution(BO7, 0.0, False)
    assert d2 == pytest.approx({2: 3 / 8, 3: 5 / 8})


def test_season_paths_sum_to_one_and_reach_probs():
    rounds = [h.Round(BO7, 0.7, 1.0), h.Round(BO7, 0.5, 0.5), h.Round(BO7, 0.4, 0.0)]
    paths = h.season_paths(rounds)
    assert sum(p.prob for p in paths) == pytest.approx(1)
    win = lambda k: sum(p.prob * h.advance(k)(p) for p in paths)
    assert win(0) == pytest.approx(0.7, abs=1e-6)
    assert win(1) == pytest.approx(0.35, abs=1e-6)
    assert win(2) == pytest.approx(0.14, abs=1e-6)


def test_rounds_from_futures():
    rs = h.rounds_from_futures([0.6, 0.3, 0.15], [BO7] * 3, [1, 1, 1])
    assert [r.p_win for r in rs] == pytest.approx([0.6, 0.5, 0.5])


def test_single_binary_hedge_is_exact():
    # Revenue = U if A wins round 1 only via a 1-game round: n = -U, zero residual.
    paths = h.season_paths([h.Round("1", 0.3, 1.0)])
    c = [h.Contract("win", h.advance(0), 0.3)]
    r = h.min_variance_hedge(paths, c, uplift=500.0, target=lambda p: h.advance(0)(p))
    assert r.n[0] == pytest.approx(-500.0)
    assert r.sd_after == pytest.approx(0, abs=1e-9)
    assert r.cost == pytest.approx(500 * h.fee(0.7))  # fair price, so only the fee


def test_exact_score_and_length_ladders_span_in_series_home_games():
    paths = h.season_paths([h.Round(BO7, 0.62, 1.0, 0.28)])
    scores = h.series_contracts(0, BO7, scores={s: (0.1, 0.1) for s in h.all_scores(BO7)[:-1]})
    r = h.min_variance_hedge(paths, scores)
    assert r.sd_before > 0 and r.sd_after == pytest.approx(0, abs=1e-9)
    games = h.series_contracts(0, BO7, games={g: (0.5, 0.5) for g in (5, 6, 7)})
    r2 = h.min_variance_hedge(paths, games)
    assert r2.sd_after == pytest.approx(0, abs=1e-9)
    # With home court: H = 2 + 1{5+} + 1{7}, so the hedge sells one 5+ and one 7.
    assert r2.n == pytest.approx([-1.0, 0.0, -1.0], abs=1e-6)


def test_winner_contract_is_useless_for_in_series_games_between_equals():
    paths = h.season_paths([h.Round(BO7, 0.5, 1.0, 0.0)])
    r = h.min_variance_hedge(paths, h.series_contracts(0, BO7, win=(0.5, 0.5)))
    assert r.n[0] == pytest.approx(0, abs=1e-9)
    assert r.variance_removed == pytest.approx(0, abs=1e-9)


def test_vig_shows_up_as_cost():
    paths = h.season_paths([h.Round("1", 0.5, 1.0)])
    fair = h.min_variance_hedge(paths, [h.Contract("w", h.advance(0), 0.5, 0.5)], target=h.advance(0))
    wide = h.min_variance_hedge(paths, [h.Contract("w", h.advance(0), 0.55, 0.45)], target=h.advance(0))
    assert wide.cost - fair.cost == pytest.approx(0.05, abs=1e-3)


def test_hedge_pnl_offsets_revenue():
    paths = h.season_paths([h.Round(BO7, 0.55, 1.0, 0.28)])
    cs = h.series_contracts(0, BO7, games={g: (0.6, 0.6) for g in (5, 6, 7)})
    r = h.min_variance_hedge(paths, cs)
    totals = {round(p.home_games + h.hedge_pnl(r, cs, p), 9) for p in paths}
    assert len(totals) == 1  # fully locked in


def test_paths_from_scores_matches_model():
    th = h.implied_theta(0.6, BO7, 0.28)
    d = h.score_distribution(BO7, th, 0.28)  # A = us, holding home court
    paths = h.paths_from_scores(BO7, True, {k: 2 * v for k, v in d.items()})
    model = h.season_paths([h.Round(BO7, 0.6, 1.0, 0.28)])
    e = lambda ps: sum(p.prob * p.home_games for p in ps)
    assert e(paths) == pytest.approx(e(model))
    assert sum(p.prob for p in paths) == pytest.approx(1)
