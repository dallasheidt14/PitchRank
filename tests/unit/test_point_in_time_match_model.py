import numpy as np
import pandas as pd

from src.predictions.point_in_time_match_model import (
    COMPETITIVE_MATCH_SELECTION_OBJECTIVE,
    PointInTimeMatchModel,
    _dixon_coles_rho,
    _poisson_draw_gate_mask,
    _poisson_outcome_probabilities,
    _poisson_score_matrix,
    _score_matrix_summary,
    build_point_in_time_matchup_row,
    build_point_in_time_dataset,
)


def _snapshot(snapshot_date: str, team_id: str, age_group: str = "14", gender: str = "Male", **overrides):
    base = {
        "snapshot_date": snapshot_date,
        "team_id": team_id,
        "age_group": age_group,
        "gender": gender,
        "status": "Active",
        "rank_in_cohort_final": 25,
        "power_score_final": 0.6,
        "sos_norm": 0.55,
        "offense_norm": 0.58,
        "defense_norm": 0.57,
        "glicko_rating": 1520,
        "glicko_rd": 80,
        "glicko_volatility": 0.06,
        "wins": 10,
        "losses": 2,
        "draws": 1,
        "games_played": 13,
        "win_percentage": 0.77,
        "same_age_games": 10,
        "same_age_game_share": 0.8,
        "same_age_unique_opponents": 8,
        "same_age_top100_opp_count": 2,
        "same_age_top500_opp_count": 5,
        "same_age_avg_opp_power_adj": 0.58,
        "repeat_opponent_share": 0.2,
        "positive_ml_evidence_scale": 0.7,
        "publication_cap_rank": 50,
        "publication_cap_score": 0.7,
    }
    base.update(overrides)
    return base


def test_build_point_in_time_dataset_is_chronological_and_mirrored():
    games_df = pd.DataFrame(
        [
            {
                "id": "g1",
                "game_date": "2026-04-02",
                "home_team_master_id": "a",
                "away_team_master_id": "c",
                "home_score": 3,
                "away_score": 1,
            },
            {
                "id": "g2",
                "game_date": "2026-04-03",
                "home_team_master_id": "b",
                "away_team_master_id": "c",
                "home_score": 1,
                "away_score": 1,
            },
            {
                "id": "g3",
                "game_date": "2026-04-04",
                "home_team_master_id": "a",
                "away_team_master_id": "b",
                "home_score": 2,
                "away_score": 0,
            },
        ]
    )

    snapshot_index = {
        "a": [_snapshot("2026-04-01", "a", power_score_final=0.63, glicko_rating=1550)],
        "b": [_snapshot("2026-04-01", "b", power_score_final=0.58, glicko_rating=1510)],
        "c": [_snapshot("2026-04-01", "c", power_score_final=0.54, glicko_rating=1490)],
    }

    result = build_point_in_time_dataset(
        games_df,
        snapshot_index=snapshot_index,
        team_names={"a": "Alpha", "b": "Bravo", "c": "Charlie"},
        include_mirrored_examples=True,
    )

    dataset = result.dataset
    assert result.summary["games_seen"] == 3
    assert result.summary["games_used"] == 3
    assert result.summary["examples_built"] == 6
    assert result.summary["class_counts"] == {"draw": 2, "team_a_win": 2, "team_b_win": 2}
    assert result.summary["class_rates"]["draw"] == 2 / 6
    assert len(dataset) == 6

    first_original = dataset[(dataset["game_id"] == "g1") & (dataset["example_orientation"] == "original")].iloc[0]
    assert first_original["team_a_recent_form"] == 0.0
    assert first_original["team_b_recent_form"] == 0.0
    assert first_original["common_opponent_shared"] == 0.0
    assert first_original["combined_draw_rate"] > 0.0
    assert first_original["projected_total_goals"] > 0.0
    assert 0.0 <= first_original["stalemate_signal"] <= 1.0

    g3_original = dataset[(dataset["game_id"] == "g3") & (dataset["example_orientation"] == "original")].iloc[0]
    g3_mirrored = dataset[(dataset["game_id"] == "g3") & (dataset["example_orientation"] == "mirrored")].iloc[0]

    assert g3_original["team_a_recent_form"] > g3_original["team_b_recent_form"]
    assert g3_original["common_opponent_shared"] == 1.0
    assert g3_original["common_opponent_advantage"] > 0.0
    assert g3_original["common_opponent_strength_weighted_margin_diff"] > 0.0
    assert g3_original["common_opponent_strength_weighted_goal_balance_diff"] > 0.0
    assert g3_original["common_opponent_consensus_signal"] > 0.0
    assert g3_original["actual_outcome"] == "team_a_win"
    assert g3_mirrored["actual_outcome"] == "team_b_win"
    assert g3_original["power_score_final_diff"] == -g3_mirrored["power_score_final_diff"]


def test_build_point_in_time_dataset_skips_games_without_snapshot():
    games_df = pd.DataFrame(
        [
            {
                "id": "g1",
                "game_date": "2026-04-02",
                "home_team_master_id": "a",
                "away_team_master_id": "b",
                "home_score": 2,
                "away_score": 1,
            }
        ]
    )

    snapshot_index = {
        "a": [_snapshot("2026-04-01", "a")],
    }

    result = build_point_in_time_dataset(games_df, snapshot_index=snapshot_index, include_mirrored_examples=True)
    assert result.dataset.empty
    assert result.summary["skipped_missing_snapshot"] == 1


def test_build_point_in_time_dataset_tracks_draw_oriented_signals():
    games_df = pd.DataFrame(
        [
            {
                "id": "g1",
                "game_date": "2026-04-02",
                "home_team_master_id": "a",
                "away_team_master_id": "b",
                "home_score": 1,
                "away_score": 1,
            }
        ]
    )

    snapshot_index = {
        "a": [
            _snapshot(
                "2026-04-01",
                "a",
                draws=5,
                games_played=12,
                exp_goals_for=1.0,
                exp_goals_against=0.9,
                exp_margin=0.1,
                exp_win_rate=0.52,
            )
        ],
        "b": [
            _snapshot(
                "2026-04-01",
                "b",
                draws=4,
                games_played=12,
                exp_goals_for=0.95,
                exp_goals_against=0.95,
                exp_margin=0.05,
                exp_win_rate=0.51,
            )
        ],
    }

    result = build_point_in_time_dataset(games_df, snapshot_index=snapshot_index, include_mirrored_examples=False)
    row = result.dataset.iloc[0]

    assert row["actual_outcome"] == "draw"
    assert row["team_a_draw_rate"] > 0.3
    assert row["team_b_draw_rate"] > 0.3
    assert row["low_total_goal_signal"] > 0.0
    assert row["goal_balance_signal"] > 0.0
    assert row["snapshot_strength_closeness"] > 0.0
    assert row["expected_draw_environment"] > 0.0
    assert row["common_opponent_same_age_rate"] == 0.0
    assert row["common_opponent_strength_weighted_shared"] == 0.0
    assert 0.0 <= row["stalemate_signal"] <= 1.0


def test_build_point_in_time_matchup_row_supports_inference_without_actual_scores():
    team_a_snapshot = _snapshot(
        "2026-04-01",
        "a",
        age_group="10",
        draws=5,
        games_played=12,
        exp_goals_for=1.0,
        exp_goals_against=0.9,
        exp_margin=0.1,
        exp_win_rate=0.52,
    )
    team_b_snapshot = _snapshot(
        "2026-04-01",
        "b",
        age_group="10",
        draws=4,
        games_played=12,
        exp_goals_for=0.95,
        exp_goals_against=0.95,
        exp_margin=0.05,
        exp_win_rate=0.51,
    )
    all_games = []

    row = build_point_in_time_matchup_row(
        team_a_id="a",
        team_b_id="b",
        team_a_snapshot=team_a_snapshot,
        team_b_snapshot=team_b_snapshot,
        all_games=all_games,
        game_date="2026-04-09",
        team_names={"a": "Alpha", "b": "Bravo"},
        game_id="shadow-1",
    )

    assert row["game_id"] == "shadow-1"
    assert row["team_a_name"] == "Alpha"
    assert row["team_b_name"] == "Bravo"
    assert row["actual_outcome"] == "draw"
    assert np.isnan(row["actual_margin"])
    assert row["age_group_numeric"] == 10
    assert row["combined_prior_game_count"] == 0.0
    assert row["common_opponent_strength_weighted_shared"] == 0.0
    assert 0.0 <= row["stalemate_signal"] <= 1.0


def test_poisson_outcome_probabilities_raise_draw_in_balanced_low_goal_games():
    low_balanced = _poisson_outcome_probabilities(np.array([0.8]), np.array([0.8]))[0]
    high_balanced = _poisson_outcome_probabilities(np.array([1.8]), np.array([1.8]))[0]
    lopsided = _poisson_outcome_probabilities(np.array([2.2]), np.array([0.7]))[0]

    assert np.isclose(low_balanced.sum(), 1.0)
    assert low_balanced[1] > high_balanced[1]
    assert low_balanced[1] > lopsided[1]


def test_poisson_draw_gate_mask_requires_low_total_close_stalemate_profile():
    mask = _poisson_draw_gate_mask(
        draw_probability=np.array([0.27, 0.27, 0.23, 0.27]),
        projected_total_goals=np.array([2.1, 2.4, 2.1, 2.1]),
        stalemate_signal=np.array([0.62, 0.62, 0.62, 0.54]),
        expected_goal_gap_abs=np.array([0.32, 0.32, 0.32, 0.32]),
    )

    assert mask.tolist() == [True, False, False, False]


def test_low_score_correlation_increases_balanced_draw_mass():
    expected_goals_a = np.array([0.9])
    expected_goals_b = np.array([0.9])
    neutral_matrix = _poisson_score_matrix(expected_goals_a, expected_goals_b, rho=np.array([0.0]))
    correlated_rho = _dixon_coles_rho(
        draw_model_probability=np.array([0.31]),
        stalemate_signal=np.array([0.84]),
        projected_total_goals=np.array([1.8]),
        expected_goal_gap_abs=np.array([0.0]),
    )
    correlated_matrix = _poisson_score_matrix(expected_goals_a, expected_goals_b, rho=correlated_rho)
    neutral_summary = _score_matrix_summary(neutral_matrix)
    correlated_summary = _score_matrix_summary(correlated_matrix)

    assert correlated_summary["draw_probability"][0] > neutral_summary["draw_probability"][0]
    assert correlated_matrix[0, 0, 0] > neutral_matrix[0, 0, 0]


def test_score_matrix_summary_tracks_blowout_risk_for_lopsided_matchups():
    balanced_summary = _score_matrix_summary(
        _poisson_score_matrix(np.array([1.4]), np.array([1.2]), rho=np.array([0.0]))
    )
    lopsided_summary = _score_matrix_summary(
        _poisson_score_matrix(np.array([2.8]), np.array([0.6]), rho=np.array([0.0]))
    )

    assert lopsided_summary["blowout_3plus_probability"][0] > balanced_summary["blowout_3plus_probability"][0]
    assert lopsided_summary["blowout_5plus_probability"][0] > balanced_summary["blowout_5plus_probability"][0]


def test_blowout_threshold_selection_and_label_nesting():
    model = PointInTimeMatchModel(model_dir="models/test_point_in_time_match_model")
    probabilities = np.array([0.82, 0.74, 0.61, 0.49, 0.33, 0.21, 0.08])
    targets = np.array([1, 1, 1, 1, 0, 0, 0])
    threshold = model._select_blowout_threshold(
        probabilities=probabilities,
        targets=targets,
        beta=1.6,
    )

    predicted_rate = float(np.mean(probabilities >= threshold))
    actual_rate = float(np.mean(targets == 1))

    assert 0.21 <= threshold <= 0.61
    assert abs(predicted_rate - actual_rate) <= 0.15

    model.blowout_probability_thresholds = {3: 0.40, 5: 0.25}
    predicted_3plus, predicted_5plus = model._blowout_prediction_labels(
        blowout_3plus_probability=np.array([0.55, 0.35, 0.22]),
        blowout_5plus_probability=np.array([0.31, 0.18, 0.28]),
    )

    assert predicted_5plus.tolist() == [1, 0, 1]
    assert predicted_3plus.tolist() == [1, 0, 1]


def test_draw_prediction_labels_use_age_specific_policy():
    model = PointInTimeMatchModel(model_dir="models/test_point_in_time_match_model")
    model.draw_decision_policy = {
        "default": {
            "min_draw_probability": 0.25,
            "max_draw_gap": 0.02,
            "max_total_goals": 2.2,
            "min_stalemate_signal": 0.6,
        },
        "by_age": {
            10: {
                "min_draw_probability": 0.24,
                "max_draw_gap": 0.18,
                "max_total_goals": 2.3,
                "min_stalemate_signal": 0.58,
            }
        },
    }
    probabilities = np.array(
        [
            [0.44, 0.26, 0.30],
            [0.44, 0.26, 0.30],
            [0.40, 0.18, 0.42],
        ]
    )
    dataset_df = pd.DataFrame(
        {
            "age_group_numeric": [10, 16, 10],
            "projected_total_goals": [2.1, 2.1, 2.1],
            "stalemate_signal": [0.64, 0.64, 0.64],
        }
    )

    predicted_labels = model._draw_prediction_labels(probabilities, dataset_df=dataset_df)

    assert predicted_labels.tolist() == [1, 0, 2]


def test_blowout_prediction_labels_use_age_specific_thresholds():
    model = PointInTimeMatchModel(model_dir="models/test_point_in_time_match_model")
    model.blowout_probability_thresholds = {3: 0.40, 5: 0.25}
    model.blowout_probability_thresholds_by_age = {
        3: {10: 0.55, 16: 0.25},
        5: {10: 0.35, 16: 0.18},
    }
    predicted_3plus, predicted_5plus = model._blowout_prediction_labels(
        blowout_3plus_probability=np.array([0.50, 0.50, 0.30]),
        blowout_5plus_probability=np.array([0.30, 0.20, 0.28]),
        age_group_numeric=np.array([10, 16, 12]),
    )

    assert predicted_3plus.tolist() == [0, 1, 1]
    assert predicted_5plus.tolist() == [0, 1, 1]


def test_relabel_evaluation_frame_reapplies_draw_and_blowout_policy():
    model = PointInTimeMatchModel(model_dir="models/test_point_in_time_match_model")
    model.draw_decision_policy = {
        "default": {
            "min_draw_probability": 0.25,
            "max_draw_gap": 0.02,
            "max_total_goals": 2.2,
            "min_stalemate_signal": 0.6,
        },
        "by_age": {
            10: {
                "min_draw_probability": 0.24,
                "max_draw_gap": 0.18,
                "max_total_goals": 2.3,
                "min_stalemate_signal": 0.58,
            }
        },
    }
    model.blowout_probability_thresholds = {3: 0.40, 5: 0.25}
    model.blowout_probability_thresholds_by_age = {
        3: {10: 0.55, 16: 0.25},
        5: {10: 0.35, 16: 0.18},
    }
    evaluation_frame = pd.DataFrame(
        {
            "actual_outcome": ["draw", "team_b"],
            "predicted_outcome": ["team_a", "team_a"],
            "prob_team_a_win": [0.44, 0.35],
            "prob_draw": [0.26, 0.15],
            "prob_team_b_win": [0.30, 0.50],
            "age_group": ["u10", "u16"],
            "projected_total_goals": [2.1, 3.2],
            "stalemate_signal": [0.64, 0.40],
            "blowout_3plus_probability": [0.50, 0.50],
            "blowout_5plus_probability": [0.30, 0.20],
        }
    )

    relabeled = model.relabel_evaluation_frame(evaluation_frame)

    assert relabeled["predicted_outcome"].tolist() == ["draw", "team_b"]
    assert relabeled["predicted_blowout_3plus"].astype(int).tolist() == [0, 1]
    assert relabeled["predicted_blowout_5plus"].astype(int).tolist() == [0, 1]


def test_auto_probability_strategy_prefers_viable_draw_aware_candidate():
    model = PointInTimeMatchModel(model_dir="models/test_point_in_time_match_model")
    strategy_metrics = {
        "hybrid": {
            "winner_accuracy": 0.6014,
            "log_loss": 0.9197,
            "brier_score": 0.5373,
            "draw_recall": 0.0616,
            "predicted_draw_rate": 0.0434,
            "exact_score_accuracy": 0.0675,
            "score_within_one_goal_rate": 0.4382,
            "total_goals_mae": 2.2796,
            "blowout_3plus_brier": 0.2199,
            "blowout_5plus_brier": 0.1253,
        },
        "poisson_draw_gate": {
            "winner_accuracy": 0.5956,
            "log_loss": 0.9017,
            "brier_score": 0.5257,
            "draw_recall": 0.0893,
            "predicted_draw_rate": 0.0655,
            "exact_score_accuracy": 0.0683,
            "score_within_one_goal_rate": 0.4439,
            "total_goals_mae": 2.2037,
            "blowout_3plus_brier": 0.2200,
            "blowout_5plus_brier": 0.1254,
        },
        "poisson_primary": {
            "winner_accuracy": 0.6079,
            "log_loss": 0.8997,
            "brier_score": 0.5244,
            "draw_recall": 0.0056,
            "predicted_draw_rate": 0.0036,
            "exact_score_accuracy": 0.0683,
            "score_within_one_goal_rate": 0.4439,
            "total_goals_mae": 2.2037,
            "blowout_3plus_brier": 0.2200,
            "blowout_5plus_brier": 0.1254,
        },
    }

    selected_strategy, selection_details = model._select_probability_strategy(
        strategy_metrics=strategy_metrics,
        actual_draw_rate=0.1408,
    )

    assert selected_strategy == "poisson_draw_gate"
    assert "poisson_primary" not in selection_details["candidate_strategies"]
    assert "poisson_primary" in selection_details["rejected_strategies"]


def test_selection_objective_can_prioritize_competitive_match_quality():
    permissive_constraints = {
        "min_draw_recall": 0.0,
        "max_draw_rate_gap": 1.0,
        "winner_accuracy_tolerance": 1.0,
        "log_loss_tolerance": 1.0,
    }
    strategy_metrics = {
        "hybrid": {
            "winner_accuracy": 0.61,
            "log_loss": 0.90,
            "brier_score": 0.18,
            "draw_recall": 0.10,
            "predicted_draw_rate": 0.11,
            "exact_score_accuracy": 0.06,
            "score_within_one_goal_rate": 0.43,
            "total_goals_mae": 1.35,
            "margin_mae": 1.18,
            "competitive_game_recall": 0.29,
            "competitive_game_precision": 0.31,
            "blowout_3plus_brier": 0.13,
            "blowout_5plus_brier": 0.06,
        },
        "poisson_primary": {
            "winner_accuracy": 0.58,
            "log_loss": 0.93,
            "brier_score": 0.20,
            "draw_recall": 0.11,
            "predicted_draw_rate": 0.11,
            "exact_score_accuracy": 0.08,
            "score_within_one_goal_rate": 0.60,
            "total_goals_mae": 1.04,
            "margin_mae": 0.81,
            "competitive_game_recall": 0.63,
            "competitive_game_precision": 0.58,
            "blowout_3plus_brier": 0.08,
            "blowout_5plus_brier": 0.03,
        },
        "poisson_draw_gate": {
            "winner_accuracy": 0.59,
            "log_loss": 0.92,
            "brier_score": 0.19,
            "draw_recall": 0.18,
            "predicted_draw_rate": 0.17,
            "exact_score_accuracy": 0.07,
            "score_within_one_goal_rate": 0.52,
            "total_goals_mae": 1.16,
            "margin_mae": 0.93,
            "competitive_game_recall": 0.51,
            "competitive_game_precision": 0.49,
            "blowout_3plus_brier": 0.10,
            "blowout_5plus_brier": 0.05,
        },
    }

    balanced_model = PointInTimeMatchModel(model_dir="models/test_point_in_time_match_model")
    balanced_choice, _ = balanced_model._select_probability_strategy(
        strategy_metrics={name: dict(values) for name, values in strategy_metrics.items()},
        actual_draw_rate=0.12,
        constraints=permissive_constraints,
    )

    competitive_model = PointInTimeMatchModel(model_dir="models/test_point_in_time_match_model")
    competitive_model.selection_objective = COMPETITIVE_MATCH_SELECTION_OBJECTIVE
    competitive_choice, details = competitive_model._select_probability_strategy(
        strategy_metrics={name: dict(values) for name, values in strategy_metrics.items()},
        actual_draw_rate=0.12,
        constraints=permissive_constraints,
    )

    assert balanced_choice == "hybrid"
    assert competitive_choice == "poisson_primary"
    assert details["selection_objective"] == COMPETITIVE_MATCH_SELECTION_OBJECTIVE
