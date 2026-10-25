"""Season-level additions to the ported hedge math (make playoffs -> conference -> title)."""

import pytest

from app.markets import playoffs as h

BO7 = "2-2-1-1-1"


def test_qualifier_paths_sum_to_one_and_price_the_futures():
    rounds = h.preseason_rounds(0.87, 0.195, 0.075, BO7, edge=0.28)
    paths = h.season_paths_with_qualifier(0.87, rounds)
    assert sum(p.prob for p in paths) == pytest.approx(1)
    assert h.expected(paths, h.made_playoffs) == pytest.approx(0.87, abs=1e-6)
    assert h.expected(paths, h.advance(2)) == pytest.approx(0.195, abs=1e-4)
    assert h.expected(paths, h.advance(3)) == pytest.approx(0.075, abs=1e-4)
    assert all(p.home_games == 0 for p in paths if not p.legs)  # a missed season hosts nothing


def test_preseason_rounds_rejects_inconsistent_ladder():
    with pytest.raises(ValueError):
        h.preseason_rounds(0.5, 0.6, 0.1)


def test_swing_of_make_playoffs_is_expected_home_games_given_made():
    paths = h.season_paths_with_qualifier(0.8, h.preseason_rounds(0.8, 0.2, 0.08, BO7))
    made = [p for p in paths if p.legs]
    assert h.swing(paths, h.made_playoffs) == pytest.approx(h.expected(made, lambda p: p.home_games))


def test_season_hedge_buys_no_on_every_stage_and_removes_most_variance():
    paths = h.season_paths_with_qualifier(0.87, h.preseason_rounds(0.87, 0.195, 0.075, BO7, edge=0.28))
    cs = [h.Contract("make", h.made_playoffs, 0.90, 0.84), h.Contract("east", h.advance(2), 0.20, 0.19),
          h.Contract("title", h.advance(3), 0.08, 0.07)]
    r = h.min_variance_hedge(paths, cs, uplift=500.0)
    assert (r.n < 0).all()  # NO on each stage
    assert r.variance_removed > 0.5
    for c, n in zip(cs, r.n):  # never more contracts than the stage's dollar swing (I1 per leg)
        assert abs(n) <= 500.0 * h.swing(paths, c.payoff) + 1e-6
