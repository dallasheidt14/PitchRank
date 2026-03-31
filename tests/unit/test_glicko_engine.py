from __future__ import annotations

import math

import pytest

from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import (
    _from_glicko2_scale,
    _to_glicko2_scale,
    game_outcome,
    glicko2_E,
    glicko2_g,
    glicko2_update,
)


class TestGlicko2Scale:
    def test_round_trip(self):
        """Converting to glicko2 scale and back gives original values."""
        mu, sigma = 1500.0, 350.0
        mu_g2, sigma_g2 = _to_glicko2_scale(mu, sigma)
        mu_back, sigma_back = _from_glicko2_scale(mu_g2, sigma_g2)
        assert abs(mu_back - mu) < 0.001
        assert abs(sigma_back - sigma) < 0.001

    def test_average_rating_is_zero(self):
        mu_g2, _ = _to_glicko2_scale(1500.0, 350.0)
        assert abs(mu_g2) < 0.001


class TestGlicko2G:
    def test_zero_phi_gives_one(self):
        assert glicko2_g(0.0001) == pytest.approx(1.0, abs=0.01)

    def test_large_phi_gives_less_than_one(self):
        assert glicko2_g(2.0) < 1.0

    def test_positive(self):
        assert glicko2_g(1.0) > 0


class TestGlicko2E:
    def test_equal_ratings(self):
        assert glicko2_E(0.0, 0.0, 1.0) == pytest.approx(0.5, abs=0.001)

    def test_higher_rating_favored(self):
        assert glicko2_E(1.0, 0.0, 1.0) > 0.5

    def test_lower_rating_unfavored(self):
        assert glicko2_E(0.0, 1.0, 1.0) < 0.5


class TestGlicko2Update:
    def test_win_increases_rating(self):
        """Winning against equal opponent should increase mu."""
        cfg = GlickoConfig()
        mu, sigma = 1500.0, 200.0
        opp_mu, opp_sigma = 1500.0, 200.0
        new_mu, new_sigma, new_vol = glicko2_update(
            mu, sigma, cfg.INITIAL_VOLATILITY,
            [(opp_mu, opp_sigma)], [1.0], [1.0], cfg.TAU,
        )
        assert new_mu > mu

    def test_loss_decreases_rating(self):
        mu, sigma = 1500.0, 200.0
        cfg = GlickoConfig()
        new_mu, _, _ = glicko2_update(
            mu, sigma, cfg.INITIAL_VOLATILITY,
            [(1500.0, 200.0)], [0.0], [1.0], cfg.TAU,
        )
        assert new_mu < mu

    def test_sigma_decreases_with_games(self):
        """Playing games should reduce uncertainty."""
        cfg = GlickoConfig()
        mu, sigma = 1500.0, 350.0
        new_mu, new_sigma, _ = glicko2_update(
            mu, sigma, cfg.INITIAL_VOLATILITY,
            [(1500.0, 200.0)], [0.5], [1.0], cfg.TAU,
        )
        assert new_sigma < sigma

    def test_no_games_increases_uncertainty(self):
        """No games played should increase sigma (uncertainty widens)."""
        cfg = GlickoConfig()
        mu, sigma = 1500.0, 200.0
        new_mu, new_sigma, _ = glicko2_update(
            mu, sigma, cfg.INITIAL_VOLATILITY, [], [], [], cfg.TAU
        )
        assert new_mu == pytest.approx(mu, abs=0.001)  # mu unchanged
        assert new_sigma > sigma  # sigma increases

    def test_glickman_example(self):
        """Verify against Glickman's paper example (approximately).

        Player: mu=1500, sigma=200, vol=0.06
        Plays 3 opponents: (1400,30,win), (1550,100,loss), (1700,300,loss)
        Expected new mu ~ 1464.06, new sigma ~ 151.52
        """
        cfg = GlickoConfig()
        new_mu, new_sigma, _ = glicko2_update(
            1500.0, 200.0, 0.06,
            [(1400.0, 30.0), (1550.0, 100.0), (1700.0, 300.0)],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 1.0],
            cfg.TAU,
        )
        assert abs(new_mu - 1464.06) < 5.0  # Allow some tolerance
        assert abs(new_sigma - 151.52) < 5.0


class TestGameOutcome:
    def test_draw(self):
        assert game_outcome(1, 1, 6) == 0.5

    def test_one_goal_win(self):
        result = game_outcome(2, 1, 6)
        assert 0.6 < result < 0.7  # ~0.64

    def test_three_goal_win(self):
        result = game_outcome(4, 1, 6)
        assert 0.75 < result < 0.90  # ~0.856

    def test_five_goal_win(self):
        result = game_outcome(6, 1, 6)
        assert 0.85 < result < 0.97  # ~0.960

    def test_loss_is_symmetric(self):
        win = game_outcome(3, 0, 6)
        loss = game_outcome(0, 3, 6)
        assert abs(win + loss - 1.0) < 0.001

    def test_max_gd_cap(self):
        """Goal diff > MAX_GD should be capped."""
        result_6 = game_outcome(7, 1, 6)
        result_10 = game_outcome(11, 1, 6)
        assert abs(result_6 - result_10) < 0.001  # Both capped at GD=6

    def test_zero_zero_draw(self):
        assert game_outcome(0, 0, 6) == 0.5
