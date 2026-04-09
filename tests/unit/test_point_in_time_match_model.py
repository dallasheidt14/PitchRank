import pandas as pd

from src.predictions.point_in_time_match_model import build_point_in_time_dataset, select_probability_strategy


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
    assert 0.0 <= row["stalemate_signal"] <= 1.0


def test_select_probability_strategy_prefers_draw_viable_option():
    strategy_metrics = {
        "hybrid": {
            "winner_accuracy": 0.575,
            "draw_recall": 0.18,
            "draw_precision": 0.19,
            "log_loss": 0.919,
            "predicted_draw_rate": 0.134,
        },
        "poisson_draw_gate": {
            "winner_accuracy": 0.592,
            "draw_recall": 0.089,
            "draw_precision": 0.192,
            "log_loss": 0.902,
            "predicted_draw_rate": 0.065,
        },
        "poisson_primary": {
            "winner_accuracy": 0.600,
            "draw_recall": 0.047,
            "draw_precision": 0.199,
            "log_loss": 0.900,
            "predicted_draw_rate": 0.033,
        },
    }

    selection = select_probability_strategy(
        strategy_metrics=strategy_metrics,
        actual_draw_rate=0.141,
        requested_strategy="auto",
    )

    assert selection["selected_strategy"] == "poisson_draw_gate"
    assert "poisson_primary" in selection["rejected_strategies"]
    assert selection["strategy_scores"]["poisson_draw_gate"] > selection["strategy_scores"]["poisson_primary"]
