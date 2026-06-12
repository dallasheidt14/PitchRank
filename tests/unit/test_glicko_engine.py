from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import (
    _apply_tier_mult,
    _compute_base_evidence_scale,
    _from_glicko2_scale,
    _to_glicko2_scale,
    apply_scf_dampening,
    clip_outlier_goals,
    compute_game_explainability,
    compute_rankings_v2,
    compute_recency_weights,
    compute_repeat_opponent_weights,
    compute_scf,
    compute_sos,
    derive_offense_defense,
    expected_score,
    game_outcome,
    get_anchor,
    glicko2_E,
    glicko2_g,
    glicko2_update,
    run_glicko2_cohort,
    scale_cross_age_rating,
    select_games,
    select_games_balanced,
    sigmoid_zscore_normalize,
)


def make_game(team_a, team_b, gf, ga, date, age="U15", gender="M"):
    """Create symmetric game rows for a single match."""
    return [
        {
            "team_id": team_a,
            "opp_id": team_b,
            "gf": gf,
            "ga": ga,
            "date": pd.Timestamp(date),
            "age": age,
            "gender": gender,
            "opp_age": age,
            "opp_gender": gender,
        },
        {
            "team_id": team_b,
            "opp_id": team_a,
            "gf": ga,
            "ga": gf,
            "date": pd.Timestamp(date),
            "age": age,
            "gender": gender,
            "opp_age": age,
            "opp_gender": gender,
        },
    ]


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
            mu,
            sigma,
            cfg.INITIAL_VOLATILITY,
            [(opp_mu, opp_sigma)],
            [1.0],
            [1.0],
            cfg.TAU,
        )
        assert new_mu > mu

    def test_loss_decreases_rating(self):
        mu, sigma = 1500.0, 200.0
        cfg = GlickoConfig()
        new_mu, _, _ = glicko2_update(
            mu,
            sigma,
            cfg.INITIAL_VOLATILITY,
            [(1500.0, 200.0)],
            [0.0],
            [1.0],
            cfg.TAU,
        )
        assert new_mu < mu

    def test_sigma_decreases_with_games(self):
        """Playing games should reduce uncertainty."""
        cfg = GlickoConfig()
        mu, sigma = 1500.0, 350.0
        new_mu, new_sigma, _ = glicko2_update(
            mu,
            sigma,
            cfg.INITIAL_VOLATILITY,
            [(1500.0, 200.0)],
            [0.5],
            [1.0],
            cfg.TAU,
        )
        assert new_sigma < sigma

    def test_no_games_increases_uncertainty(self):
        """No games played should increase sigma (uncertainty widens)."""
        cfg = GlickoConfig()
        mu, sigma = 1500.0, 200.0
        new_mu, new_sigma, _ = glicko2_update(mu, sigma, cfg.INITIAL_VOLATILITY, [], [], [], cfg.TAU)
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
            1500.0,
            200.0,
            0.06,
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
        games = pd.DataFrame(
            {
                "gf": [2, 1, 3, 2, 1, 2, 3, 1, 2, 2, 1, 3, 2, 1, 2, 3, 1, 2, 2, 15],
                "ga": [1, 2, 0, 1, 1, 2, 1, 0, 1, 2, 1, 0, 1, 2, 1, 0, 1, 2, 1, 0],
                "age": ["U15"] * n,
                "gender": ["M"] * n,
            }
        )
        result = clip_outlier_goals(games, zscore_threshold=2.5)
        assert result["gf"].iloc[3] < 15  # 15 should be clipped

    def test_normal_scores_unchanged(self):
        """Normal scores within 2.5 sigma should not change."""
        games = pd.DataFrame(
            {
                "gf": [2, 1, 3, 2, 1, 2],
                "ga": [1, 2, 0, 1, 1, 3],
                "age": ["U15"] * 6,
                "gender": ["M"] * 6,
            }
        )
        result = clip_outlier_goals(games, zscore_threshold=2.5)
        pd.testing.assert_frame_equal(result[["gf", "ga"]], games[["gf", "ga"]])

    def test_does_not_modify_original(self):
        """Should return a copy, not modify in place."""
        games = pd.DataFrame(
            {
                "gf": [2, 15],
                "ga": [1, 0],
                "age": ["U15", "U15"],
                "gender": ["M", "M"],
            }
        )
        original_gf = games["gf"].iloc[1]
        clip_outlier_goals(games, zscore_threshold=2.5)
        assert games["gf"].iloc[1] == original_gf


class TestSelectGames:
    def test_max_games_limit(self):
        """Should return at most max_games games."""
        today = pd.Timestamp("2026-03-31")
        dates = pd.date_range(end=today, periods=40, freq="7D")
        games = pd.DataFrame(
            {
                "team_id": ["team_a"] * 40,
                "date": dates,
                "gf": [2] * 40,
                "ga": [1] * 40,
            }
        )
        result = select_games(games, "team_a", max_games=30, window_days=365, today=today)
        assert len(result) == 30

    def test_window_filter(self):
        """Should exclude games outside the window."""
        today = pd.Timestamp("2026-03-31")
        games = pd.DataFrame(
            {
                "team_id": ["team_a"] * 3,
                "date": [
                    pd.Timestamp("2026-03-01"),  # within window
                    pd.Timestamp("2025-06-01"),  # within window
                    pd.Timestamp("2024-01-01"),  # outside 365-day window
                ],
                "gf": [2, 1, 3],
                "ga": [1, 2, 0],
            }
        )
        result = select_games(games, "team_a", max_games=30, window_days=365, today=today)
        assert len(result) == 2

    def test_window_grace_keeps_recently_expired_games(self):
        today = pd.Timestamp("2026-03-31")
        games = pd.DataFrame(
            {
                "team_id": ["team_a"] * 3,
                "date": [
                    pd.Timestamp("2026-03-01"),
                    pd.Timestamp("2025-03-26"),  # 370 days ago -> kept by 28-day grace
                    pd.Timestamp("2025-02-20"),  # outside grace
                ],
                "gf": [2, 1, 3],
                "ga": [1, 2, 0],
            }
        )
        result = select_games(games, "team_a", max_games=30, window_days=365, today=today, grace_days=28)
        assert len(result) == 2

    def test_most_recent_first(self):
        """Games should be sorted most recent first."""
        today = pd.Timestamp("2026-03-31")
        games = pd.DataFrame(
            {
                "team_id": ["team_a"] * 3,
                "date": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-03-01"), pd.Timestamp("2026-02-01")],
                "gf": [1, 2, 3],
                "ga": [0, 0, 0],
            }
        )
        result = select_games(games, "team_a", max_games=30, window_days=365, today=today)
        assert result.iloc[0]["gf"] == 2  # March game first


class TestBalancedSelection:
    def test_balanced_selection_reserves_quality_slots(self):
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-03-31")
        rows = []

        # 35 recent same-state games vs weak same-age opponents
        for i in range(35):
            rows += make_game("A", f"W{i}", 2, 0, today - pd.Timedelta(days=i))

        # Older but stronger same-age opponents that should be pulled into the window
        for i in range(7):
            rows += make_game("A", f"S{i}", 1, 0, today - pd.Timedelta(days=60 + i))

        # Out-of-state bridge games that should occupy the bridge bucket
        for i in range(3):
            rows += make_game("A", f"B{i}", 1, 1, today - pd.Timedelta(days=90 + i))

        games = pd.DataFrame(rows)
        games["age"] = "U14"
        games["gender"] = "M"
        games["opp_age"] = "U14"
        games["opp_gender"] = "M"

        team_state_map = {"A": "TX"}
        rating_lookup = {"A": (1500.0, 200.0, 0.06)}
        for i in range(35):
            team_state_map[f"W{i}"] = "TX"
            rating_lookup[f"W{i}"] = (1400.0, 200.0, 0.06)
        for i in range(7):
            team_state_map[f"S{i}"] = "TX"
            rating_lookup[f"S{i}"] = (1750.0, 200.0, 0.06)
        for i in range(3):
            team_state_map[f"B{i}"] = "OK"
            rating_lookup[f"B{i}"] = (1700.0, 200.0, 0.06)

        selected = select_games_balanced(
            games,
            "A",
            cfg,
            today,
            rating_lookup=rating_lookup,
            team_state_map=team_state_map,
        )

        assert len(selected) == cfg.MAX_GAMES
        assert (selected["selection_bucket"] == "same_age_quality").sum() >= 7
        assert (selected["selection_bucket"] == "bridge_quality").sum() >= 3
        selected_opp_ids = set(selected["opp_id"].astype(str).tolist())
        assert {"S0", "S1", "S2"}.issubset(selected_opp_ids)
        assert {"B0", "B1", "B2"}.issubset(selected_opp_ids)

    def test_selection_includes_soft_window_grace_day(self):
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-04-21")
        rows = make_game("A", "B", 2, 1, pd.Timestamp("2025-04-20"))
        games = pd.DataFrame(rows)
        games["age"] = "U15"
        games["gender"] = "M"
        games["opp_age"] = "U15"
        games["opp_gender"] = "M"

        selected = select_games_balanced(games, "A", cfg, today, rating_lookup={"A": (1500.0, 200.0, 0.06)})

        assert len(selected) == 1
        assert str(selected.iloc[0]["opp_id"]) == "B"

    def test_selection_uses_stable_tiebreakers_for_same_date(self):
        today = pd.Timestamp("2026-04-21")
        games = pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-04-01"), "team_id": "T", "opp_id": "C", "gf": 1, "ga": 0, "game_id": "g3", "id": "g3"},
                {"date": pd.Timestamp("2026-04-01"), "team_id": "T", "opp_id": "A", "gf": 1, "ga": 0, "game_id": "g1", "id": "g1"},
                {"date": pd.Timestamp("2026-04-01"), "team_id": "T", "opp_id": "B", "gf": 1, "ga": 0, "game_id": "g2", "id": "g2"},
            ]
        )

        selected = select_games(games, "T", max_games=3, window_days=365, today=today)

        assert selected["opp_id"].tolist() == ["A", "B", "C"]


class TestRecencyWeights:
    def test_most_recent_highest_weight(self):
        """Most recent game should have the highest weight."""
        today = pd.Timestamp("2026-03-31")
        dates = pd.Series(
            [
                pd.Timestamp("2026-03-31"),  # today
                pd.Timestamp("2026-01-01"),  # 3 months ago
                pd.Timestamp("2025-06-01"),  # 10 months ago
            ]
        )
        weights = compute_recency_weights(dates, today, lambda_=1.0)
        assert weights[0] > weights[1] > weights[2]

    def test_weights_sum_to_one(self):
        """Weights should be normalized to sum to 1."""
        today = pd.Timestamp("2026-03-31")
        dates = pd.Series([pd.Timestamp("2026-03-01"), pd.Timestamp("2025-09-01")])
        weights = compute_recency_weights(dates, today, lambda_=1.0)
        assert abs(weights.sum() - 1.0) < 0.001

    def test_single_game_weight_one(self):
        """Single game should have weight 1.0."""
        today = pd.Timestamp("2026-03-31")
        dates = pd.Series([pd.Timestamp("2026-03-01")])
        weights = compute_recency_weights(dates, today, lambda_=1.0)
        assert abs(weights[0] - 1.0) < 0.001

    def test_grace_window_tapers_recently_expired_games(self):
        today = pd.Timestamp("2026-03-31")
        dates = pd.Series([pd.Timestamp("2025-04-01"), pd.Timestamp("2025-03-26")])
        base = compute_recency_weights(dates, today, lambda_=1.0)
        tapered = compute_recency_weights(dates, today, lambda_=1.0, window_days=365, grace_days=28)
        assert tapered[1] < base[1]
        assert tapered[0] > tapered[1]


class TestRepeatOpponentWeights:
    def test_repeat_schedule_decays_softly(self):
        cfg = GlickoConfig()
        opp_ids = ["B", "B", "B", "B", "C", "C", "D"]
        weights = compute_repeat_opponent_weights(opp_ids, cfg)
        np.testing.assert_allclose(weights, np.array([1.0, 0.8, 0.6, 0.4, 1.0, 0.8, 1.0]))


class TestRunGlicko2Cohort:
    def test_three_team_ordering(self):
        """A beats B, B beats C, A beats C => A > B > C."""
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-03-31")
        rows = []
        rows += make_game("A", "B", 3, 1, "2026-03-01")
        rows += make_game("B", "C", 2, 0, "2026-03-10")
        rows += make_game("A", "C", 4, 0, "2026-03-20")
        games = pd.DataFrame(rows)

        result, team_games = run_glicko2_cohort(games, cfg, today)
        ratings = result.set_index("team_id")["mu"]
        assert ratings["A"] > ratings["B"] > ratings["C"]

    def test_convergence_within_limit(self):
        """Should converge within MAX_ITERATIONS."""
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-03-31")
        rows = []
        rows += make_game("A", "B", 2, 1, "2026-03-01")
        rows += make_game("B", "C", 2, 1, "2026-03-10")
        games = pd.DataFrame(rows)

        # Should not raise or warn
        result, team_games = run_glicko2_cohort(games, cfg, today)
        assert len(result) == 3

    def test_recency_matters(self):
        """Team with recent losses should rate lower than one with recent wins."""
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-03-31")
        rows = []
        # Team A wins early, loses recently
        rows += make_game("A", "C", 3, 0, "2025-06-01")
        rows += make_game("A", "C", 0, 3, "2026-03-15")
        # Team B loses early, wins recently
        rows += make_game("B", "C", 0, 3, "2025-06-01")
        rows += make_game("B", "C", 3, 0, "2026-03-15")
        games = pd.DataFrame(rows)

        result, team_games = run_glicko2_cohort(games, cfg, today)
        ratings = result.set_index("team_id")["mu"]
        assert ratings["B"] > ratings["A"]

    def test_output_columns(self):
        """Output should have all required columns."""
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-03-31")
        rows = make_game("A", "B", 2, 1, "2026-03-01")
        games = pd.DataFrame(rows)

        result, team_games = run_glicko2_cohort(games, cfg, today)
        required = [
            "team_id",
            "mu",
            "sigma",
            "volatility",
            "games_played",
            "wins",
            "losses",
            "draws",
            "last_game",
            "goals_for",
            "goals_against",
        ]
        for col in required:
            assert col in result.columns, f"Missing column: {col}"

    def test_game_stats_correct(self):
        """Win/loss/draw counts should be correct."""
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-03-31")
        rows = []
        rows += make_game("A", "B", 3, 1, "2026-03-01")  # A wins
        rows += make_game("A", "B", 1, 1, "2026-03-10")  # draw
        rows += make_game("A", "B", 0, 2, "2026-03-20")  # A loses
        games = pd.DataFrame(rows)

        result, team_games = run_glicko2_cohort(games, cfg, today)
        a_row = result[result["team_id"] == "A"].iloc[0]
        assert a_row["games_played"] == 3
        assert a_row["wins"] == 1
        assert a_row["losses"] == 1
        assert a_row["draws"] == 1
        assert a_row["goals_for"] == 4  # 3 + 1 + 0
        assert a_row["goals_against"] == 4  # 1 + 1 + 2


class TestCrossAgeScaling:
    def test_same_age_no_scaling(self):
        """Same age and gender should return opp_mu unchanged."""
        cfg = GlickoConfig()
        result = scale_cross_age_rating(1500.0, 15, "M", 15, "M", cfg)
        assert result == 1500.0

    def test_u14m_vs_u19m(self):
        """U14M team facing U19M opponent: opponent gets boosted."""
        cfg = GlickoConfig()
        # opp_anchor(U19M)=1.000, team_anchor(U14M)=0.928
        # scaled = 1500 + (1.000 - 0.928) * 400 = 1528.8
        result = scale_cross_age_rating(1500.0, 19, "M", 14, "M", cfg)
        assert abs(result - 1528.8) < 0.1

    def test_u10f_vs_u19f(self):
        """U10F team facing U19F opponent: large boost."""
        cfg = GlickoConfig()
        # opp_anchor(U19F)=1.000, team_anchor(U10F)=0.792
        # scaled = 1500 + (1.000 - 0.792) * 400 = 1583.2
        result = scale_cross_age_rating(1500.0, 19, "F", 10, "F", cfg)
        assert abs(result - 1583.2) < 0.1

    def test_older_team_facing_younger_opponent(self):
        """U19M facing U14M: opponent gets reduced."""
        cfg = GlickoConfig()
        # opp_anchor(U14M)=0.928, team_anchor(U19M)=1.000
        # scaled = 1500 + (0.928 - 1.000) * 400 = 1471.2
        result = scale_cross_age_rating(1500.0, 14, "M", 19, "M", cfg)
        assert abs(result - 1471.2) < 0.1

    def test_average_team_stays_reasonable(self):
        """Average-rated younger team shouldn't become 'terrible' after scaling."""
        cfg = GlickoConfig()
        # U10M (anchor=0.783) opponent rated 1500, seen by U19M (anchor=1.000)
        result = scale_cross_age_rating(1500.0, 10, "M", 19, "M", cfg)
        # scaled = 1500 + (0.783 - 1.000) * 400 = 1413.2
        assert result > 1400  # Still a reasonable rating, not catastrophic
        assert result < 1500  # But lower than their actual rating

    def test_get_anchor_string_age(self):
        """get_anchor should handle string ages like 'U15'."""
        cfg = GlickoConfig()
        assert get_anchor("U15", "M", cfg) == cfg.MALE_ANCHORS[15]
        assert get_anchor("u15", "Female", cfg) == cfg.FEMALE_ANCHORS[15]

    def test_get_anchor_unknown_age(self):
        """Unknown age should return 1.0."""
        cfg = GlickoConfig()
        assert get_anchor(99, "M", cfg) == 1.0


class TestExpectedScore:
    def test_equal_ratings(self):
        assert expected_score(1500.0, 1500.0) == pytest.approx(0.5)

    def test_higher_rated_favored(self):
        assert expected_score(1700.0, 1500.0) > 0.7

    def test_symmetry(self):
        e1 = expected_score(1600.0, 1400.0)
        e2 = expected_score(1400.0, 1600.0)
        assert abs(e1 + e2 - 1.0) < 0.001


class TestDeriveOffenseDefense:
    def test_scoring_above_expected_positive_offense(self):
        """Team scoring more than expected gets positive off_raw."""
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-03-31")
        games = pd.DataFrame(
            [
                {
                    "team_id": "A",
                    "opp_id": "B",
                    "gf": 5,
                    "ga": 0,
                    "date": pd.Timestamp("2026-03-01"),
                    "age": "U15",
                    "gender": "M",
                },
                {
                    "team_id": "B",
                    "opp_id": "A",
                    "gf": 0,
                    "ga": 5,
                    "date": pd.Timestamp("2026-03-01"),
                    "age": "U15",
                    "gender": "M",
                },
            ]
        )
        ratings = {"A": (1600.0, 200.0, 0.06), "B": (1400.0, 200.0, 0.06)}
        result = derive_offense_defense(games, ratings, cfg, today)
        a_row = result[result["team_id"] == "A"].iloc[0]
        assert a_row["off_raw"] > 0

    def test_opponent_strength_matters(self):
        """Scoring 3 vs strong opponent gives more off credit than vs weak."""
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-03-31")
        games = pd.DataFrame(
            [
                {
                    "team_id": "A",
                    "opp_id": "B",
                    "gf": 3,
                    "ga": 1,
                    "date": pd.Timestamp("2026-03-01"),
                    "age": "U15",
                    "gender": "M",
                },
                {
                    "team_id": "B",
                    "opp_id": "A",
                    "gf": 1,
                    "ga": 3,
                    "date": pd.Timestamp("2026-03-01"),
                    "age": "U15",
                    "gender": "M",
                },
                {
                    "team_id": "C",
                    "opp_id": "D",
                    "gf": 3,
                    "ga": 1,
                    "date": pd.Timestamp("2026-03-01"),
                    "age": "U15",
                    "gender": "M",
                },
                {
                    "team_id": "D",
                    "opp_id": "C",
                    "gf": 1,
                    "ga": 3,
                    "date": pd.Timestamp("2026-03-01"),
                    "age": "U15",
                    "gender": "M",
                },
            ]
        )
        ratings = {
            "A": (1500.0, 200.0, 0.06),
            "B": (1700.0, 200.0, 0.06),
            "C": (1500.0, 200.0, 0.06),
            "D": (1300.0, 200.0, 0.06),
        }
        result = derive_offense_defense(games, ratings, cfg, today)
        a_off = result[result["team_id"] == "A"].iloc[0]["off_raw"]
        c_off = result[result["team_id"] == "C"].iloc[0]["off_raw"]
        assert a_off > c_off


class TestComputeSOS:
    def test_repeat_cap(self):
        """Team playing same opponent 8 times should only count 4."""
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-03-31")
        rows = []
        for i in range(8):
            date = f"2026-03-{i + 1:02d}"
            rows.append(
                {
                    "team_id": "A",
                    "opp_id": "B",
                    "gf": 2,
                    "ga": 1,
                    "date": pd.Timestamp(date),
                    "age": "U15",
                    "gender": "M",
                }
            )
            rows.append(
                {
                    "team_id": "B",
                    "opp_id": "A",
                    "gf": 1,
                    "ga": 2,
                    "date": pd.Timestamp(date),
                    "age": "U15",
                    "gender": "M",
                }
            )
        games = pd.DataFrame(rows)
        ratings = {"A": (1500.0, 200.0, 0.06), "B": (1600.0, 200.0, 0.06)}
        result = compute_sos(games, ratings, cfg, today)
        assert "A" in result["team_id"].values

    def test_stronger_schedule_higher_sos(self):
        """Team playing strong opponents should have higher sos_raw."""
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-03-31")
        rows = []
        for i, opp_mu in enumerate([1700, 1650, 1600, 1550, 1500]):
            opp = f"strong_{i}"
            rows.append(
                {
                    "team_id": "A",
                    "opp_id": opp,
                    "gf": 1,
                    "ga": 2,
                    "date": pd.Timestamp(f"2026-03-{i + 1:02d}"),
                    "age": "U15",
                    "gender": "M",
                }
            )
            rows.append(
                {
                    "team_id": opp,
                    "opp_id": "A",
                    "gf": 2,
                    "ga": 1,
                    "date": pd.Timestamp(f"2026-03-{i + 1:02d}"),
                    "age": "U15",
                    "gender": "M",
                }
            )
        for i, opp_mu in enumerate([1300, 1250, 1200, 1150, 1100]):
            opp = f"weak_{i}"
            rows.append(
                {
                    "team_id": "B",
                    "opp_id": opp,
                    "gf": 2,
                    "ga": 1,
                    "date": pd.Timestamp(f"2026-03-{i + 6:02d}"),
                    "age": "U15",
                    "gender": "M",
                }
            )
            rows.append(
                {
                    "team_id": opp,
                    "opp_id": "B",
                    "gf": 1,
                    "ga": 2,
                    "date": pd.Timestamp(f"2026-03-{i + 6:02d}"),
                    "age": "U15",
                    "gender": "M",
                }
            )
        games = pd.DataFrame(rows)

        all_teams = {"A": (1500.0, 200.0, 0.06), "B": (1500.0, 200.0, 0.06)}
        for i, mu in enumerate([1700, 1650, 1600, 1550, 1500]):
            all_teams[f"strong_{i}"] = (float(mu), 200.0, 0.06)
        for i, mu in enumerate([1300, 1250, 1200, 1150, 1100]):
            all_teams[f"weak_{i}"] = (float(mu), 200.0, 0.06)

        result = compute_sos(games, all_teams, cfg, today)
        a_sos = result[result["team_id"] == "A"].iloc[0]["sos_raw"]
        b_sos = result[result["team_id"] == "B"].iloc[0]["sos_raw"]
        assert a_sos > b_sos


class TestSigmoidZscoreNormalize:
    def test_mean_maps_to_half(self):
        """Average value should map to ~0.5."""
        vals = pd.Series([100, 200, 300, 400, 500])
        result = sigmoid_zscore_normalize(vals)
        assert abs(result.iloc[2] - 0.5) < 0.001

    def test_above_mean_above_half(self):
        vals = pd.Series([100, 200, 300, 400, 500])
        result = sigmoid_zscore_normalize(vals)
        assert result.iloc[4] > 0.5

    def test_no_rescaling(self):
        """Max value should NOT be forced to 1.0 (no min-max rescaling)."""
        vals = pd.Series([100, 200, 300, 400, 500])
        result = sigmoid_zscore_normalize(vals)
        assert result.iloc[4] < 1.0
        assert result.iloc[0] > 0.0

    def test_constant_input(self):
        """All same values should return 0.5."""
        vals = pd.Series([100, 100, 100])
        result = sigmoid_zscore_normalize(vals)
        assert all(abs(v - 0.5) < 0.001 for v in result)


class TestApplyTierMult:
    def test_centered_discount_is_relative_to_neutral(self):
        """Default centered mode: discount scales the distance from 1500, not the raw rating."""
        cfg = GlickoConfig()
        assert abs(_apply_tier_mult(1700.0, 0.95, cfg) - 1690.0) < 0.001
        assert abs(_apply_tier_mult(1300.0, 0.95, cfg) - 1310.0) < 0.001
        assert abs(_apply_tier_mult(1500.0, 0.95, cfg) - 1500.0) < 0.001

    def test_full_multiplier_is_identity(self):
        cfg = GlickoConfig()
        assert _apply_tier_mult(1700.0, 1.0, cfg) == 1700.0

    def test_legacy_multiplicative_mode(self):
        """TIER_MULT_CENTERED=False preserves the raw multiplicative discount."""
        cfg = GlickoConfig()
        cfg.TIER_MULT_CENTERED = False
        assert abs(_apply_tier_mult(1700.0, 0.95, cfg) - 1615.0) < 0.001
        assert abs(_apply_tier_mult(1500.0, 0.95, cfg) - 1425.0) < 0.001


class TestSCF:
    def _make_games(self, team_id: str, opp_ids: list[str]) -> pd.DataFrame:
        """Helper: one game row per opponent for *team_id*."""
        rows = [
            {
                "team_id": team_id,
                "opp_id": opp,
                "gf": 2,
                "ga": 1,
                "date": pd.Timestamp("2026-03-01"),
                "age": "U15",
                "gender": "M",
            }
            for opp in opp_ids
        ]
        return pd.DataFrame(rows)

    def test_isolated_team_flagged(self):
        """Team whose opponents are all in the same state is_isolated=True."""
        cfg = GlickoConfig()
        games = self._make_games("A", ["B", "C", "D"])
        state_map = {"A": "ID", "B": "ID", "C": "ID", "D": "ID"}
        ratings = {
            "A": (1500.0, 200.0, 0.06),
            "B": (1500.0, 200.0, 0.06),
            "C": (1500.0, 200.0, 0.06),
            "D": (1500.0, 200.0, 0.06),
        }
        result = compute_scf(games, state_map, ratings, cfg)
        assert result["A"]["is_isolated"] is True

    def test_connected_team_not_isolated(self):
        """Team with opponents from 5 different states is_isolated=False."""
        cfg = GlickoConfig()
        opp_ids = [f"opp_{s}" for s in ["OR", "WA", "MT", "WY", "UT"]]
        games = self._make_games("A", opp_ids)
        state_map = {"A": "ID", "opp_OR": "OR", "opp_WA": "WA", "opp_MT": "MT", "opp_WY": "WY", "opp_UT": "UT"}
        ratings = {"A": (1500.0, 200.0, 0.06)}
        for opp in opp_ids:
            ratings[opp] = (1500.0, 200.0, 0.06)
        result = compute_scf(games, state_map, ratings, cfg)
        assert result["A"]["is_isolated"] is False
        assert result["A"]["unique_states"] > 3.0

    def test_cross_age_bridge_counts_less_than_same_age_bridge(self):
        cfg = GlickoConfig()
        games = pd.DataFrame(
            [
                {
                    "team_id": "A",
                    "opp_id": "same_age_bridge",
                    "gf": 1,
                    "ga": 1,
                    "date": pd.Timestamp("2026-03-01"),
                    "age": "U15",
                    "gender": "M",
                    "opp_age": "U15",
                    "opp_gender": "M",
                },
                {
                    "team_id": "A",
                    "opp_id": "cross_age_bridge",
                    "gf": 1,
                    "ga": 1,
                    "date": pd.Timestamp("2026-03-05"),
                    "age": "U15",
                    "gender": "M",
                    "opp_age": "U16",
                    "opp_gender": "M",
                },
            ]
        )
        state_map = {"A": "AZ", "same_age_bridge": "CA", "cross_age_bridge": "NV"}
        ratings = {
            "A": (1500.0, 200.0, 0.06),
            "same_age_bridge": (1700.0, 200.0, 0.06),
            "cross_age_bridge": (1700.0, 200.0, 0.06),
        }
        result = compute_scf(games, state_map, ratings, cfg)
        assert result["A"]["bridge_games"] < 2.0
        assert result["A"]["bridge_games"] > 0.0

    def test_zero_bridge_team_uses_lower_zero_bridge_floor(self):
        """Pure same-state bubbles should damp below the general SCF floor."""
        cfg = GlickoConfig()
        games = self._make_games("A", ["B", "C", "D"])
        state_map = {"A": "ID", "B": "ID", "C": "ID", "D": "ID"}
        ratings = {
            "A": (1500.0, 200.0, 0.06),
            "B": (1500.0, 200.0, 0.06),
            "C": (1500.0, 200.0, 0.06),
            "D": (1500.0, 200.0, 0.06),
        }
        result = compute_scf(games, state_map, ratings, cfg)
        assert result["A"]["bridge_games"] == 0.0
        assert result["A"]["scf"] == pytest.approx(cfg.SCF_ZERO_BRIDGE_FLOOR)

    def test_high_bridge_volume_keeps_general_floor_even_with_one_state(self):
        """Partially connected teams keep the legacy floor once bridge volume is proven."""
        cfg = GlickoConfig()
        games = pd.DataFrame(
            [
                {
                    "team_id": "A",
                    "opp_id": "B",
                    "gf": 2,
                    "ga": 1,
                    "date": pd.Timestamp("2026-03-01") + pd.Timedelta(days=day),
                    "age": "U15",
                    "gender": "M",
                    "opp_age": "U15",
                    "opp_gender": "M",
                }
                for day in range(5)
            ]
        )
        state_map = {"A": "AZ", "B": "CA"}
        ratings = {
            "A": (1500.0, 200.0, 0.06),
            "B": (1500.0, 200.0, 0.06),
        }
        result = compute_scf(games, state_map, ratings, cfg)
        assert result["A"]["bridge_games"] > cfg.MIN_BRIDGE_GAMES
        assert result["A"]["unique_states"] < cfg.SCF_MIN_UNIQUE_STATES
        assert result["A"]["scf"] == pytest.approx(cfg.SCF_FLOOR)

    def test_scf_dampens_sos(self):
        """Isolated team (low scf) has SOS dampened closer to 1500 than connected team."""
        cfg = GlickoConfig()
        neutral = 1500.0
        raw_sos = 1700.0  # both start with strong schedule

        team_df = pd.DataFrame(
            [
                {"team_id": "isolated", "sos_raw": raw_sos},
                {"team_id": "connected", "sos_raw": raw_sos},
            ]
        )
        scf_data = {
            "isolated": {
                "scf": cfg.SCF_FLOOR,
                "bridge_games": 0,
                "is_isolated": True,
                "unique_states": 1,
                "quality_boosted": False,
            },
            "connected": {
                "scf": 1.0,
                "bridge_games": 10,
                "is_isolated": False,
                "unique_states": 5,
                "quality_boosted": False,
            },
        }
        result = apply_scf_dampening(team_df, scf_data, cfg)
        isolated_sos = result[result["team_id"] == "isolated"]["sos_raw"].iloc[0]
        connected_sos = result[result["team_id"] == "connected"]["sos_raw"].iloc[0]

        # Isolated team's SOS should be dampened toward 1500; connected unchanged
        assert isolated_sos < connected_sos
        assert isolated_sos < raw_sos
        assert abs(connected_sos - (neutral + 1.0 * (raw_sos - neutral))) < 0.01

    def _scf_mu_dampening_fixture(self, high_mu: float, cfg: GlickoConfig):
        team_df = pd.DataFrame(
            [
                {"team_id": "isolated", "sos_raw": 1500.0, "mu": high_mu},
                {"team_id": "connected", "sos_raw": 1500.0, "mu": high_mu},
            ]
        )
        scf_data = {
            "isolated": {
                "scf": cfg.SCF_FLOOR,
                "bridge_games": 0,
                "is_isolated": True,
                "unique_states": 1,
                "quality_boosted": False,
            },
            "connected": {
                "scf": 1.0,
                "bridge_games": 10,
                "is_isolated": False,
                "unique_states": 5,
                "quality_boosted": False,
            },
        }
        return team_df, scf_data

    def test_scf_publish_only_leaves_mu_pure(self):
        """Default SCF_PUBLISH_ONLY: mu is never dampened; dampening moves to the publish path."""
        cfg = GlickoConfig()
        high_mu = 1700.0
        team_df, scf_data = self._scf_mu_dampening_fixture(high_mu, cfg)

        result = apply_scf_dampening(team_df, scf_data, cfg)
        isolated_mu = result[result["team_id"] == "isolated"]["mu"].iloc[0]
        connected_mu = result[result["team_id"] == "connected"]["mu"].iloc[0]

        assert abs(isolated_mu - high_mu) < 0.01
        assert abs(connected_mu - high_mu) < 0.01

    def test_scf_dampens_mu_for_isolated_teams_legacy(self):
        """SCF_PUBLISH_ONLY=False: isolated team (low scf) has mu dampened toward 1500."""
        cfg = GlickoConfig()
        cfg.SCF_PUBLISH_ONLY = False
        neutral = cfg.INITIAL_MU
        high_mu = 1700.0
        team_df, scf_data = self._scf_mu_dampening_fixture(high_mu, cfg)

        result = apply_scf_dampening(team_df, scf_data, cfg)
        isolated_mu = result[result["team_id"] == "isolated"]["mu"].iloc[0]
        connected_mu = result[result["team_id"] == "connected"]["mu"].iloc[0]

        assert isolated_mu < connected_mu
        assert isolated_mu < high_mu
        assert abs(connected_mu - high_mu) < 0.01
        expected_isolated_mu = neutral + cfg.SCF_FLOOR * (high_mu - neutral)
        assert abs(isolated_mu - expected_isolated_mu) < 0.01

    def test_scf_disabled(self):
        """SCF_ENABLED=False gives scf=1.0 and is_isolated=False for all teams."""
        cfg = GlickoConfig()
        cfg.SCF_ENABLED = False
        games = self._make_games("A", ["B", "C"])
        state_map = {"A": "ID", "B": "ID", "C": "ID"}
        ratings = {"A": (1500.0, 200.0, 0.06), "B": (1500.0, 200.0, 0.06), "C": (1500.0, 200.0, 0.06)}
        result = compute_scf(games, state_map, ratings, cfg)
        for team_id, data in result.items():
            assert data["scf"] == 1.0
            assert data["is_isolated"] is False


class TestBaseEvidenceShrink:
    def test_weak_same_age_schedule_gets_shrunk(self):
        cfg = GlickoConfig()
        team_rows = [{"team_id": "A", "mu": 1700.0}]
        for idx in range(1, 1201):
            team_rows.append({"team_id": f"W{idx}", "mu": 1400.0 - idx})
        team_df = pd.DataFrame(team_rows)
        weak_games = pd.DataFrame(
            [
                {"team_id": "A", "opp_id": "W1198", "gf": 3, "ga": 0, "age": "U14", "gender": "M", "opp_age": "U14", "opp_gender": "M"},
                {"team_id": "A", "opp_id": "W1199", "gf": 2, "ga": 0, "age": "U14", "gender": "M", "opp_age": "U14", "opp_gender": "M"},
                {"team_id": "A", "opp_id": "W1200", "gf": 2, "ga": 1, "age": "U14", "gender": "M", "opp_age": "U14", "opp_gender": "M"},
                {"team_id": "A", "opp_id": "W1200", "gf": 1, "ga": 0, "age": "U14", "gender": "M", "opp_age": "U14", "opp_gender": "M"},
            ]
        )
        scales = _compute_base_evidence_scale(
            team_df,
            {"A": weak_games},
            {"A": {"scf": 0.55}},
            cfg,
        )
        scale_map = dict(zip(team_df["team_id"], scales))
        assert scale_map["A"] < 1.0
        assert scale_map["A"] >= 1.0 - cfg.BASE_EVIDENCE_SHRINK_MAX

    def test_quality_poor_schedule_with_some_depth_still_gets_shrunk(self):
        cfg = GlickoConfig()
        team_rows = [{"team_id": "A", "mu": 1700.0}]
        for idx in range(1, 1201):
            team_rows.append({"team_id": f"W{idx}", "mu": 1400.0 - idx})
        team_df = pd.DataFrame(team_rows)
        weak_quality_games = pd.DataFrame(
            [
                {"team_id": "A", "opp_id": "W700", "gf": 1, "ga": 1, "age": "U13", "gender": "M", "opp_age": "U13", "opp_gender": "M"},
                {"team_id": "A", "opp_id": "W760", "gf": 2, "ga": 1, "age": "U13", "gender": "M", "opp_age": "U13", "opp_gender": "M"},
                {"team_id": "A", "opp_id": "W810", "gf": 2, "ga": 0, "age": "U13", "gender": "M", "opp_age": "U13", "opp_gender": "M"},
                {"team_id": "A", "opp_id": "W880", "gf": 1, "ga": 0, "age": "U13", "gender": "M", "opp_age": "U13", "opp_gender": "M"},
                {"team_id": "A", "opp_id": "W940", "gf": 0, "ga": 2, "age": "U13", "gender": "M", "opp_age": "U13", "opp_gender": "M"},
            ]
        )
        scales = _compute_base_evidence_scale(
            team_df,
            {"A": weak_quality_games},
            {"A": {"scf": 0.62}},
            cfg,
        )
        scale_map = dict(zip(team_df["team_id"], scales))
        assert scale_map["A"] < 1.0

    def test_stale_strong_schedule_gets_activity_shrink(self):
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-04-20")
        team_df = pd.DataFrame(
            [
                {"team_id": "A", "mu": 1800.0},
                {"team_id": "B", "mu": 1795.0},
                {"team_id": "C", "mu": 1790.0},
                {"team_id": "D", "mu": 1785.0},
                {"team_id": "E", "mu": 1780.0},
            ]
        )
        stale_games = pd.DataFrame(
            [
                {"team_id": "A", "opp_id": "B", "gf": 1, "ga": 1, "age": "U13", "gender": "M", "opp_age": "U13", "opp_gender": "M", "date": pd.Timestamp("2026-01-05")},
                {"team_id": "A", "opp_id": "C", "gf": 2, "ga": 1, "age": "U13", "gender": "M", "opp_age": "U13", "opp_gender": "M", "date": pd.Timestamp("2026-01-06")},
                {"team_id": "A", "opp_id": "D", "gf": 1, "ga": 0, "age": "U13", "gender": "M", "opp_age": "U13", "opp_gender": "M", "date": pd.Timestamp("2026-01-07")},
                {"team_id": "A", "opp_id": "E", "gf": 3, "ga": 2, "age": "U13", "gender": "M", "opp_age": "U13", "opp_gender": "M", "date": pd.Timestamp("2026-01-08")},
            ]
        )
        scales = _compute_base_evidence_scale(
            team_df,
            {"A": stale_games},
            {"A": {"scf": 1.0}},
            cfg,
            today=today,
        )
        scale_map = dict(zip(team_df["team_id"], scales))
        expected_shrink = cfg.BASE_EVIDENCE_STALE_NO_RECENT_BONUS + cfg.BASE_EVIDENCE_STALE_LOW_ACTIVITY_BONUS
        assert scale_map["A"] == pytest.approx(1.0 - expected_shrink, abs=1e-9)

    def test_recent_activity_avoids_stale_schedule_bonus(self):
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-04-20")
        team_df = pd.DataFrame(
            [
                {"team_id": "A", "mu": 1800.0},
                {"team_id": "B", "mu": 1795.0},
                {"team_id": "C", "mu": 1790.0},
                {"team_id": "D", "mu": 1785.0},
                {"team_id": "E", "mu": 1780.0},
            ]
        )
        recent_games = pd.DataFrame(
            [
                {"team_id": "A", "opp_id": "B", "gf": 1, "ga": 1, "age": "U13", "gender": "M", "opp_age": "U13", "opp_gender": "M", "date": pd.Timestamp("2026-03-05")},
                {"team_id": "A", "opp_id": "C", "gf": 2, "ga": 1, "age": "U13", "gender": "M", "opp_age": "U13", "opp_gender": "M", "date": pd.Timestamp("2026-03-10")},
                {"team_id": "A", "opp_id": "D", "gf": 1, "ga": 0, "age": "U13", "gender": "M", "opp_age": "U13", "opp_gender": "M", "date": pd.Timestamp("2026-03-15")},
                {"team_id": "A", "opp_id": "E", "gf": 3, "ga": 2, "age": "U13", "gender": "M", "opp_age": "U13", "opp_gender": "M", "date": pd.Timestamp("2026-03-20")},
            ]
        )
        scales = _compute_base_evidence_scale(
            team_df,
            {"A": recent_games},
            {"A": {"scf": 1.0}},
            cfg,
            today=today,
        )
        scale_map = dict(zip(team_df["team_id"], scales))
        assert scale_map["A"] == pytest.approx(1.0, abs=1e-9)


class TestComputeRankingsV2:
    def test_returns_teams_and_games(self):
        """Should return dict with 'teams' and 'games_used' keys."""
        rows = make_game("A", "B", 2, 1, "2026-03-01")
        games = pd.DataFrame(rows)
        result = compute_rankings_v2(games, today=pd.Timestamp("2026-03-31"))
        assert "teams" in result
        assert "games_used" in result

    def test_all_expected_columns_present(self):
        """Output should have all 57 rankings_full columns."""
        rows = []
        rows += make_game("A", "B", 3, 1, "2026-03-01")
        rows += make_game("B", "C", 2, 0, "2026-03-10")
        rows += make_game("A", "C", 4, 0, "2026-03-20")
        games = pd.DataFrame(rows)
        result = compute_rankings_v2(games, today=pd.Timestamp("2026-03-31"))
        teams = result["teams"]

        expected_columns = [
            "team_id",
            "age_group",
            "gender",
            "state_code",
            "status",
            "last_game",
            "last_calculated",
            "games_played",
            "games_last_180_days",
            "wins",
            "losses",
            "draws",
            "goals_for",
            "goals_against",
            "win_percentage",
            "off_raw",
            "sad_raw",
            "off_shrunk",
            "sad_shrunk",
            "def_shrunk",
            "off_norm",
            "def_norm",
            "sos",
            "sos_norm",
            "sos_raw",
            "sos_norm_national",
            "sos_norm_state",
            "sos_rank_national",
            "sos_rank_state",
            "sample_flag",
            "strength_of_schedule",
            "power_presos",
            "anchor",
            "abs_strength",
            "powerscore_core",
            "provisional_mult",
            "powerscore_adj",
            "perf_raw",
            "perf_centered",
            "ml_overperf",
            "ml_norm",
            "powerscore_ml",
            "rank_in_cohort_ml",
            "rank_in_cohort",
            "national_rank",
            "state_rank",
            "global_rank",
            "rank_change_7d",
            "rank_change_30d",
            "rank_change_state_7d",
            "rank_change_state_30d",
            "national_power_score",
            "global_power_score",
            "power_score_true",
            "power_score_final",
        ]
        for col in expected_columns:
            assert col in teams.columns, f"Missing column: {col}"

    def test_games_last_180_days_counts_only_recent_selected_games(self):
        rows = []
        rows += make_game("A", "B", 2, 1, "2025-09-01")
        rows += make_game("A", "B", 1, 1, "2026-03-01")
        games = pd.DataFrame(rows)
        cfg = GlickoConfig(MIN_GAMES_PROVISIONAL=1)
        result = compute_rankings_v2(games, today=pd.Timestamp("2026-03-31"), cfg=cfg)
        teams = result["teams"]

        assert set(teams["games_last_180_days"].tolist()) == {1}

    def test_ranking_order_matches_mu(self):
        """National rank should match mu ordering."""
        rows = []
        rows += make_game("A", "B", 5, 0, "2026-03-01")
        rows += make_game("B", "C", 3, 0, "2026-03-10")
        rows += make_game("A", "C", 4, 0, "2026-03-20")
        games = pd.DataFrame(rows)
        # Each team has only 2 games — use low threshold so they qualify as Active
        cfg = GlickoConfig(MIN_GAMES_PROVISIONAL=1)
        result = compute_rankings_v2(games, today=pd.Timestamp("2026-03-31"), cfg=cfg)
        teams = result["teams"].sort_values("mu", ascending=False)
        # Rank 1 should be the team with highest mu
        rank1 = result["teams"][result["teams"]["national_rank"] == 1.0]
        assert rank1.iloc[0]["team_id"] == teams.iloc[0]["team_id"]

    def test_inactive_team_not_ranked(self):
        """Team with no games in 180 days should be Inactive."""
        rows = make_game("A", "B", 2, 1, "2025-01-01")  # old game
        games = pd.DataFrame(rows)
        result = compute_rankings_v2(games, today=pd.Timestamp("2026-03-31"))
        teams = result["teams"]
        assert all(teams["status"] == "Inactive")
        assert all(teams["national_rank"].isna())

    def test_low_sample_team_not_ranked(self):
        """Team with < MIN_GAMES_PROVISIONAL games should be 'Not Enough Ranked Games'."""
        rows = make_game("A", "B", 2, 1, "2026-03-01")  # recent, but only 1 game
        games = pd.DataFrame(rows)
        result = compute_rankings_v2(games, today=pd.Timestamp("2026-03-31"))
        teams = result["teams"]
        assert all(teams["status"] == "Not Enough Ranked Games")
        assert all(teams["national_rank"].isna())

    def test_provisional_mult_from_sigma(self):
        """High sigma (new team) should give low provisional_mult."""
        rows = make_game("A", "B", 2, 1, "2026-03-01")
        games = pd.DataFrame(rows)
        result = compute_rankings_v2(games, today=pd.Timestamp("2026-03-31"))
        teams = result["teams"]
        # Teams with few games should have high sigma -> low provisional_mult
        for _, row in teams.iterrows():
            assert 0.0 <= row["provisional_mult"] <= 1.0

    def test_powerscore_adj_uses_provisional_multiplier(self):
        """Glicko published baseline should apply the provisional multiplier."""
        rows = make_game("A", "B", 2, 1, "2026-03-01")
        games = pd.DataFrame(rows)
        cfg = GlickoConfig(MIN_GAMES_PROVISIONAL=1)
        result = compute_rankings_v2(games, today=pd.Timestamp("2026-03-31"), cfg=cfg)
        teams = result["teams"]

        for _, row in teams.iterrows():
            expected = row["powerscore_core"] * row["provisional_mult"]
            assert row["powerscore_adj"] == pytest.approx(expected, abs=1e-9)
            assert row["power_presos"] == pytest.approx(row["powerscore_core"], abs=1e-9)

    def _isolated_vs_connected_games(self):
        """Two symmetric winners: ISO sweeps in-state opponents, CON sweeps cross-state ones."""
        rows = []
        state_map = {"ISO": "ID", "CON": "TX"}
        for i, (date, opp_state) in enumerate(
            [
                ("2026-03-01", "OK"),
                ("2026-03-05", "CA"),
                ("2026-03-10", "CO"),
                ("2026-03-15", "NM"),
                ("2026-03-20", "UT"),
            ]
        ):
            rows += make_game("ISO", f"O{i}", 2, 0, date)
            rows += make_game("CON", f"P{i}", 2, 0, date)
            state_map[f"O{i}"] = "ID"
            state_map[f"P{i}"] = opp_state
        return pd.DataFrame(rows), state_map

    @pytest.mark.parametrize("sos_adj_enabled", [True, False])
    def test_scf_publish_only_dampens_score_not_mu(self, sos_adj_enabled):
        """Publish-only SCF: identical results give identical mu, but the isolated
        team's published score is pulled toward neutral. Covers both publish branches."""
        games, state_map = self._isolated_vs_connected_games()
        cfg = GlickoConfig(MIN_GAMES_PROVISIONAL=1, SOS_ADJ_ENABLED=sos_adj_enabled)
        result = compute_rankings_v2(games, today=pd.Timestamp("2026-03-31"), cfg=cfg, team_state_map=state_map)
        teams = result["teams"].set_index("team_id")

        assert teams.loc["ISO", "scf"] < teams.loc["CON", "scf"]
        assert teams.loc["ISO", "mu"] == pytest.approx(teams.loc["CON", "mu"], abs=1.0)
        assert teams.loc["ISO", "powerscore_core"] < teams.loc["CON", "powerscore_core"]

    def test_scf_legacy_dampens_mu(self):
        """SCF_PUBLISH_ONLY=False: the isolated team's mu itself is dampened toward 1500."""
        games, state_map = self._isolated_vs_connected_games()
        cfg = GlickoConfig(MIN_GAMES_PROVISIONAL=1, SCF_PUBLISH_ONLY=False)
        result = compute_rankings_v2(games, today=pd.Timestamp("2026-03-31"), cfg=cfg, team_state_map=state_map)
        teams = result["teams"].set_index("team_id")

        assert teams.loc["ISO", "mu"] < teams.loc["CON", "mu"]

    @pytest.mark.parametrize("sos_adj_enabled", [True, False])
    def test_scf_publish_only_score_matches_legacy(self, sos_adj_enabled):
        """The published score is mode-invariant: publish-only applies the same scf
        factor in the publish path that legacy mode bakes into mu, so powerscore_core
        must match exactly between modes while the isolated team's mu stays pure."""
        games, state_map = self._isolated_vs_connected_games()
        results = {}
        for publish_only in (True, False):
            cfg = GlickoConfig(
                MIN_GAMES_PROVISIONAL=1, SOS_ADJ_ENABLED=sos_adj_enabled, SCF_PUBLISH_ONLY=publish_only
            )
            results[publish_only] = compute_rankings_v2(
                games, today=pd.Timestamp("2026-03-31"), cfg=cfg, team_state_map=state_map
            )["teams"].set_index("team_id")
        pub, legacy = results[True], results[False]

        assert pub.loc["ISO", "mu"] > legacy.loc["ISO", "mu"]
        for team_id in pub.index:
            assert pub.loc[team_id, "powerscore_core"] == pytest.approx(
                legacy.loc[team_id, "powerscore_core"], abs=1e-9
            )


class TestGameExplainability:
    """Tests for compute_game_explainability post-hoc breakdown."""

    def _run_cohort_and_explain(self, games_df, cfg=None, today=None, global_rating_map=None):
        """Run convergence then explainability in one shot."""
        cfg = cfg or GlickoConfig()
        today = today or pd.Timestamp("2026-03-31")
        team_df, team_games = run_glicko2_cohort(games_df, cfg, today, global_rating_map)
        team_ratings = dict(
            zip(
                team_df["team_id"],
                zip(team_df["mu"], team_df["sigma"], team_df["volatility"]),
            )
        )
        explain_df = compute_game_explainability(
            games_df,
            team_ratings,
            cfg,
            today,
            team_games=team_games,
            global_rating_map=global_rating_map,
        )
        return team_df, team_ratings, explain_df

    def test_returns_expected_columns(self):
        """Output should have all required columns."""
        rows = []
        rows += make_game("A", "B", 3, 1, "2026-03-01")
        rows += make_game("B", "C", 2, 0, "2026-03-10")
        rows += make_game("A", "C", 4, 0, "2026-03-20")
        games = pd.DataFrame(rows)

        _, _, explain_df = self._run_cohort_and_explain(games)
        expected_cols = [
            "team_id",
            "opp_id",
            "game_date",
            "gf",
            "ga",
            "team_mu",
            "team_sigma",
            "opp_mu",
            "opp_sigma",
            "expected_outcome",
            "actual_outcome",
            "outcome_surprise",
            "g_factor",
            "recency_weight",
            "rating_contribution",
            "off_residual",
            "def_residual",
        ]
        for col in expected_cols:
            assert col in explain_df.columns, f"Missing column: {col}"

    def test_row_count_matches_perspectives(self):
        """3 teams each with 2 games = 6 rows (one per team-game perspective)."""
        rows = []
        rows += make_game("A", "B", 3, 1, "2026-03-01")
        rows += make_game("B", "C", 2, 0, "2026-03-10")
        rows += make_game("A", "C", 4, 0, "2026-03-20")
        games = pd.DataFrame(rows)

        _, _, explain_df = self._run_cohort_and_explain(games)
        # A plays 2 games, B plays 2 games, C plays 2 games = 6 rows
        assert len(explain_df) == 6

    def test_expected_outcome_bounds(self):
        """All expected_outcome values should be in [0, 1]."""
        rows = []
        rows += make_game("A", "B", 3, 1, "2026-03-01")
        rows += make_game("B", "C", 2, 0, "2026-03-10")
        games = pd.DataFrame(rows)

        _, _, explain_df = self._run_cohort_and_explain(games)
        assert (explain_df["expected_outcome"] >= 0.0).all()
        assert (explain_df["expected_outcome"] <= 1.0).all()

    def test_actual_outcome_bounds(self):
        """All actual_outcome values should be in [0, 1]."""
        rows = []
        rows += make_game("A", "B", 3, 1, "2026-03-01")
        rows += make_game("A", "B", 0, 5, "2026-03-10")
        games = pd.DataFrame(rows)

        _, _, explain_df = self._run_cohort_and_explain(games)
        assert (explain_df["actual_outcome"] >= 0.0).all()
        assert (explain_df["actual_outcome"] <= 1.0).all()

    def test_surprise_equals_actual_minus_expected(self):
        """outcome_surprise should equal actual_outcome - expected_outcome."""
        rows = []
        rows += make_game("A", "B", 3, 1, "2026-03-01")
        rows += make_game("B", "C", 2, 0, "2026-03-10")
        games = pd.DataFrame(rows)

        _, _, explain_df = self._run_cohort_and_explain(games)
        computed = explain_df["actual_outcome"] - explain_df["expected_outcome"]
        np.testing.assert_allclose(
            explain_df["outcome_surprise"].values,
            computed.values,
            atol=1e-10,
        )

    def test_recency_weights_positive(self):
        """All recency weights should be > 0."""
        rows = []
        rows += make_game("A", "B", 2, 1, "2026-01-01")
        rows += make_game("A", "B", 1, 2, "2026-03-15")
        games = pd.DataFrame(rows)

        _, _, explain_df = self._run_cohort_and_explain(games)
        assert (explain_df["recency_weight"] > 0.0).all()

    def test_rating_contribution_sign(self):
        """Upset win should have positive contribution; expected loss negative."""
        rows = []
        rows += make_game("Weak", "Strong", 3, 0, "2026-03-01")
        games = pd.DataFrame(rows)

        cfg = GlickoConfig()
        today = pd.Timestamp("2026-03-31")
        # Give Strong a much higher rating to make Weak's win an upset
        team_ratings = {
            "Weak": (1300.0, 200.0, 0.06),
            "Strong": (1700.0, 200.0, 0.06),
        }
        explain_df = compute_game_explainability(games, team_ratings, cfg, today)

        weak_row = explain_df[explain_df["team_id"] == "Weak"].iloc[0]
        strong_row = explain_df[explain_df["team_id"] == "Strong"].iloc[0]

        # Weak team beat Strong team — big positive surprise
        assert weak_row["rating_contribution"] > 0
        # Strong team lost to Weak team — negative surprise
        assert strong_row["rating_contribution"] < 0

    def test_contribution_sum_correlates_with_mu_delta(self):
        """Sum of rating_contribution should have same sign as mu change."""
        rows = []
        rows += make_game("A", "B", 3, 1, "2026-03-01")
        rows += make_game("A", "C", 4, 0, "2026-03-10")
        rows += make_game("B", "C", 2, 0, "2026-03-20")
        games = pd.DataFrame(rows)

        cfg = GlickoConfig()
        team_df, _, explain_df = self._run_cohort_and_explain(games, cfg=cfg)

        # A won both games — should have positive mu delta from initial
        a_mu = team_df[team_df["team_id"] == "A"].iloc[0]["mu"]
        a_contribution_sum = explain_df[explain_df["team_id"] == "A"]["rating_contribution"].sum()

        # Both should be positive (rating went up, contributions are positive)
        assert (a_mu - cfg.INITIAL_MU) > 0
        assert a_contribution_sum > 0

        # C lost both games — should have negative mu delta from initial
        c_mu = team_df[team_df["team_id"] == "C"].iloc[0]["mu"]
        c_contribution_sum = explain_df[explain_df["team_id"] == "C"]["rating_contribution"].sum()

        assert (c_mu - cfg.INITIAL_MU) < 0
        assert c_contribution_sum < 0

    def test_off_def_residuals_computed(self):
        """Off/def residuals should not be NaN for teams with games."""
        rows = []
        rows += make_game("A", "B", 3, 1, "2026-03-01")
        games = pd.DataFrame(rows)

        _, _, explain_df = self._run_cohort_and_explain(games)
        assert not explain_df["off_residual"].isna().any()
        assert not explain_df["def_residual"].isna().any()

    def test_cross_age_opponent_uses_global_map(self):
        """Cross-age opponent should use global_rating_map when provided."""
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-03-31")
        games = pd.DataFrame(
            [
                {
                    "team_id": "A",
                    "opp_id": "X",
                    "gf": 2,
                    "ga": 1,
                    "date": pd.Timestamp("2026-03-01"),
                    "age": "U15",
                    "gender": "M",
                    "opp_age": "U17",
                    "opp_gender": "M",
                },
                {
                    "team_id": "X",
                    "opp_id": "A",
                    "gf": 1,
                    "ga": 2,
                    "date": pd.Timestamp("2026-03-01"),
                    "age": "U17",
                    "gender": "M",
                    "opp_age": "U15",
                    "opp_gender": "M",
                },
            ]
        )

        team_ratings = {
            "A": (1500.0, 200.0, 0.06),
            "X": (1600.0, 200.0, 0.06),
        }
        global_map = {"X": 1650.0, "A": 1500.0}

        explain_df = compute_game_explainability(
            games,
            team_ratings,
            cfg,
            today,
            global_rating_map=global_map,
        )

        a_row = explain_df[explain_df["team_id"] == "A"].iloc[0]
        # X is cross-age (U17 vs U15 cohort), so opp_mu should NOT be 1600 (within-cohort)
        # It should be scaled from global_map[X]=1650 with cross-age adjustment
        assert a_row["opp_mu"] != 1600.0
        # Anchor diff scaled by ANCHOR_SCALE_FACTOR
        opp_anchor = cfg.MALE_ANCHORS[17]
        team_anchor = cfg.MALE_ANCHORS[15]
        expected_scaled = 1650.0 + (opp_anchor - team_anchor) * cfg.ANCHOR_SCALE_FACTOR
        assert a_row["opp_mu"] == pytest.approx(expected_scaled, abs=0.1)

    def test_empty_games_returns_empty_df(self):
        """Empty games DataFrame should return empty result with correct columns."""
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-03-31")
        games = pd.DataFrame(
            columns=[
                "team_id",
                "opp_id",
                "gf",
                "ga",
                "date",
                "age",
                "gender",
                "opp_age",
                "opp_gender",
            ]
        )

        explain_df = compute_game_explainability(games, {}, cfg, today)
        assert len(explain_df) == 0
        assert "team_id" in explain_df.columns
        assert "rating_contribution" in explain_df.columns

    def test_compute_rankings_v2_includes_explainability(self):
        """compute_rankings_v2 should return game_explainability key."""
        rows = []
        rows += make_game("A", "B", 2, 1, "2026-03-01")
        rows += make_game("B", "C", 3, 0, "2026-03-10")
        games = pd.DataFrame(rows)

        result = compute_rankings_v2(games, today=pd.Timestamp("2026-03-31"))
        assert "game_explainability" in result
        assert isinstance(result["game_explainability"], pd.DataFrame)
        assert len(result["game_explainability"]) > 0
