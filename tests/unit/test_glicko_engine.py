from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import (
    _from_glicko2_scale,
    _to_glicko2_scale,
    clip_outlier_goals,
    compute_recency_weights,
    game_outcome,
    glicko2_E,
    glicko2_g,
    glicko2_update,
    run_glicko2_cohort,
    select_games,
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


class TestClipOutlierGoals:
    def test_extreme_score_clipped(self):
        """A 15-0 game should get GF clipped."""
        n = 20
        games = pd.DataFrame({
            'gf': [2, 1, 3, 2, 1, 2, 3, 1, 2, 2, 1, 3, 2, 1, 2, 3, 1, 2, 2, 15],
            'ga': [1, 2, 0, 1, 1, 2, 1, 0, 1, 2, 1, 0, 1, 2, 1, 0, 1, 2, 1, 0],
            'age': ['U15'] * n,
            'gender': ['M'] * n,
        })
        result = clip_outlier_goals(games, zscore_threshold=2.5)
        assert result['gf'].iloc[3] < 15  # 15 should be clipped

    def test_normal_scores_unchanged(self):
        """Normal scores within 2.5 sigma should not change."""
        games = pd.DataFrame({
            'gf': [2, 1, 3, 2, 1, 2],
            'ga': [1, 2, 0, 1, 1, 3],
            'age': ['U15'] * 6,
            'gender': ['M'] * 6,
        })
        result = clip_outlier_goals(games, zscore_threshold=2.5)
        pd.testing.assert_frame_equal(result[['gf', 'ga']], games[['gf', 'ga']])

    def test_does_not_modify_original(self):
        """Should return a copy, not modify in place."""
        games = pd.DataFrame({
            'gf': [2, 15], 'ga': [1, 0],
            'age': ['U15', 'U15'], 'gender': ['M', 'M'],
        })
        original_gf = games['gf'].iloc[1]
        clip_outlier_goals(games, zscore_threshold=2.5)
        assert games['gf'].iloc[1] == original_gf


class TestSelectGames:
    def test_max_games_limit(self):
        """Should return at most max_games games."""
        today = pd.Timestamp('2026-03-31')
        dates = pd.date_range(end=today, periods=40, freq='7D')
        games = pd.DataFrame({
            'team_id': ['team_a'] * 40,
            'date': dates,
            'gf': [2] * 40,
            'ga': [1] * 40,
        })
        result = select_games(games, 'team_a', max_games=30, window_days=365, today=today)
        assert len(result) == 30

    def test_window_filter(self):
        """Should exclude games outside the window."""
        today = pd.Timestamp('2026-03-31')
        games = pd.DataFrame({
            'team_id': ['team_a'] * 3,
            'date': [
                pd.Timestamp('2026-03-01'),  # within window
                pd.Timestamp('2025-06-01'),  # within window
                pd.Timestamp('2024-01-01'),  # outside 365-day window
            ],
            'gf': [2, 1, 3],
            'ga': [1, 2, 0],
        })
        result = select_games(games, 'team_a', max_games=30, window_days=365, today=today)
        assert len(result) == 2

    def test_most_recent_first(self):
        """Games should be sorted most recent first."""
        today = pd.Timestamp('2026-03-31')
        games = pd.DataFrame({
            'team_id': ['team_a'] * 3,
            'date': [pd.Timestamp('2026-01-01'), pd.Timestamp('2026-03-01'), pd.Timestamp('2026-02-01')],
            'gf': [1, 2, 3], 'ga': [0, 0, 0],
        })
        result = select_games(games, 'team_a', max_games=30, window_days=365, today=today)
        assert result.iloc[0]['gf'] == 2  # March game first


class TestRecencyWeights:
    def test_most_recent_highest_weight(self):
        """Most recent game should have the highest weight."""
        today = pd.Timestamp('2026-03-31')
        dates = pd.Series([
            pd.Timestamp('2026-03-31'),  # today
            pd.Timestamp('2026-01-01'),  # 3 months ago
            pd.Timestamp('2025-06-01'),  # 10 months ago
        ])
        weights = compute_recency_weights(dates, today, lambda_=1.0)
        assert weights[0] > weights[1] > weights[2]

    def test_weights_sum_to_one(self):
        """Weights should be normalized to sum to 1."""
        today = pd.Timestamp('2026-03-31')
        dates = pd.Series([pd.Timestamp('2026-03-01'), pd.Timestamp('2025-09-01')])
        weights = compute_recency_weights(dates, today, lambda_=1.0)
        assert abs(weights.sum() - 1.0) < 0.001

    def test_single_game_weight_one(self):
        """Single game should have weight 1.0."""
        today = pd.Timestamp('2026-03-31')
        dates = pd.Series([pd.Timestamp('2026-03-01')])
        weights = compute_recency_weights(dates, today, lambda_=1.0)
        assert abs(weights[0] - 1.0) < 0.001


class TestRunGlicko2Cohort:
    def _make_game(self, team_a, team_b, gf, ga, date, age='U15', gender='M'):
        """Helper to create symmetric game rows."""
        return [
            {'team_id': team_a, 'opp_id': team_b, 'gf': gf, 'ga': ga,
             'date': pd.Timestamp(date), 'age': age, 'gender': gender,
             'opp_age': age, 'opp_gender': gender},
            {'team_id': team_b, 'opp_id': team_a, 'gf': ga, 'ga': gf,
             'date': pd.Timestamp(date), 'age': age, 'gender': gender,
             'opp_age': age, 'opp_gender': gender},
        ]

    def test_three_team_ordering(self):
        """A beats B, B beats C, A beats C => A > B > C."""
        cfg = GlickoConfig()
        today = pd.Timestamp('2026-03-31')
        rows = []
        rows += self._make_game('A', 'B', 3, 1, '2026-03-01')
        rows += self._make_game('B', 'C', 2, 0, '2026-03-10')
        rows += self._make_game('A', 'C', 4, 0, '2026-03-20')
        games = pd.DataFrame(rows)

        result = run_glicko2_cohort(games, cfg, today)
        ratings = result.set_index('team_id')['mu']
        assert ratings['A'] > ratings['B'] > ratings['C']

    def test_convergence_within_limit(self):
        """Should converge within MAX_ITERATIONS."""
        cfg = GlickoConfig()
        today = pd.Timestamp('2026-03-31')
        rows = []
        rows += self._make_game('A', 'B', 2, 1, '2026-03-01')
        rows += self._make_game('B', 'C', 2, 1, '2026-03-10')
        games = pd.DataFrame(rows)

        # Should not raise or warn
        result = run_glicko2_cohort(games, cfg, today)
        assert len(result) == 3

    def test_recency_matters(self):
        """Team with recent losses should rate lower than one with recent wins."""
        cfg = GlickoConfig()
        today = pd.Timestamp('2026-03-31')
        rows = []
        # Team A wins early, loses recently
        rows += self._make_game('A', 'C', 3, 0, '2025-06-01')
        rows += self._make_game('A', 'C', 0, 3, '2026-03-15')
        # Team B loses early, wins recently
        rows += self._make_game('B', 'C', 0, 3, '2025-06-01')
        rows += self._make_game('B', 'C', 3, 0, '2026-03-15')
        games = pd.DataFrame(rows)

        result = run_glicko2_cohort(games, cfg, today)
        ratings = result.set_index('team_id')['mu']
        assert ratings['B'] > ratings['A']

    def test_output_columns(self):
        """Output should have all required columns."""
        cfg = GlickoConfig()
        today = pd.Timestamp('2026-03-31')
        rows = self._make_game('A', 'B', 2, 1, '2026-03-01')
        games = pd.DataFrame(rows)

        result = run_glicko2_cohort(games, cfg, today)
        required = ['team_id', 'mu', 'sigma', 'volatility', 'games_played',
                     'wins', 'losses', 'draws', 'last_game', 'goals_for', 'goals_against']
        for col in required:
            assert col in result.columns, f"Missing column: {col}"

    def test_game_stats_correct(self):
        """Win/loss/draw counts should be correct."""
        cfg = GlickoConfig()
        today = pd.Timestamp('2026-03-31')
        rows = []
        rows += self._make_game('A', 'B', 3, 1, '2026-03-01')  # A wins
        rows += self._make_game('A', 'B', 1, 1, '2026-03-10')  # draw
        rows += self._make_game('A', 'B', 0, 2, '2026-03-20')  # A loses
        games = pd.DataFrame(rows)

        result = run_glicko2_cohort(games, cfg, today)
        a_row = result[result['team_id'] == 'A'].iloc[0]
        assert a_row['games_played'] == 3
        assert a_row['wins'] == 1
        assert a_row['losses'] == 1
        assert a_row['draws'] == 1
        assert a_row['goals_for'] == 4  # 3 + 1 + 0
        assert a_row['goals_against'] == 4  # 1 + 1 + 2
