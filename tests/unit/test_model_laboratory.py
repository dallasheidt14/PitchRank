from __future__ import annotations

import pandas as pd

from src.predictions.model_laboratory import (
    DEFAULT_PROMOTION_BASELINE,
    build_feature_coverage_report,
    build_promotion_decisions,
    build_rolling_tournament_folds,
    evaluate_candidate_promotion,
    run_count_model_laboratory,
)


def _game(day: int, *, event_name: str = "") -> dict[str, object]:
    score_a = day % 5
    score_b = (day * 2) % 4
    return {
        "game_id": f"g{day}",
        "game_date": f"2026-01-{day:02d}",
        "event_name": event_name,
        "team_a_id": f"team-{day % 4}",
        "team_b_id": f"team-{(day + 1) % 4}",
        "team_a_is_female": 0.0,
        "team_b_is_female": 0.0,
        "team_a_games_played": float(day),
        "team_b_games_played": float(max(1, day - 1)),
        "age_group_numeric": 14.0,
        "example_orientation": "original",
        "actual_score_a": score_a,
        "actual_score_b": score_b,
        "actual_margin": score_a - score_b,
        "actual_outcome": (
            "team_a" if score_a > score_b else "team_b" if score_b > score_a else "draw"
        ),
    }


def test_rolling_folds_keep_overlapping_event_interval_out_of_training():
    frame = pd.DataFrame(
        [
            _game(day, event_name="Weekend Cup" if day in {4, 6} else "")
            for day in range(1, 11)
        ]
    )

    folds = build_rolling_tournament_folds(
        frame,
        min_train_groups=2,
        test_group_count=1,
        min_train_games=2,
    )

    assert folds
    assert all(fold.train_end_date < fold.test_start_date for fold in folds)
    event_fold = next(
        fold
        for fold in folds
        if any("2026-01-04" in group for group in fold.test_groups)
    )
    assert event_fold.test_games == 3


def test_feature_coverage_separates_ready_inputs_from_collection_backlog():
    frame = pd.DataFrame(
        {
            "team_a_days_since_last_game": [3.0, 7.0],
            "team_b_days_since_last_game": [4.0, 8.0],
            "team_a_games_last_7_days": [1.0, 2.0],
            "team_b_games_last_7_days": [1.0, 1.0],
        }
    )

    report = build_feature_coverage_report(frame)

    assert "recent_schedule_load" in report["ready_groups"]
    assert "match_duration" in report["collection_backlog"]
    duration = next(
        row for row in report["groups"] if row["feature_group"] == "match_duration"
    )
    assert duration["missing_columns"] == ["match_duration_minutes"]


def test_feature_coverage_recognizes_reviewed_optional_context():
    frame = pd.DataFrame(
        {
            "match_duration_minutes": [60.0],
            "players_per_side": [9.0],
            "team_a_roster_continuity": [0.8],
            "team_b_roster_continuity": [0.7],
            "event_strength": [0.6],
            "team_a_rest_minutes": [120.0],
            "team_b_rest_minutes": [90.0],
        }
    )

    report = build_feature_coverage_report(frame)

    for group in (
        "match_duration",
        "playing_format",
        "roster_continuity",
        "event_strength",
        "tournament_rest",
    ):
        assert group in report["ready_groups"]


def test_count_model_laboratory_compares_all_candidates_on_the_same_games():
    frame = pd.DataFrame([_game(day) for day in range(1, 13)])

    result = run_count_model_laboratory(
        frame,
        min_train_groups=5,
        min_train_games=5,
        max_folds=3,
    )

    assert len(result.folds) == 3
    assert not result.failures
    assert set(result.aggregate_metrics["candidate"]) == {
        "cohort_average_poisson",
        "historical_hierarchical_poisson",
        "historical_hierarchical_negative_binomial",
        "historical_hierarchical_bivariate_poisson",
    }
    assert result.aggregate_metrics["shared_examples"].nunique() == 1
    assert result.aggregate_metrics["shared_examples"].iloc[0] == 3
    assert set(result.segment_metrics["segment_type"]) == {
        "history_coverage_band",
        "matchup_gender",
    }


def _promotion_rows(*, omit_challenger_fold: str = "") -> pd.DataFrame:
    rows = []
    for fold in ("fold-001", "fold-002", "fold-003"):
        rows.append(
            {
                "candidate": "champion",
                "fold_id": fold,
                "shared_examples": 100,
                "log_loss": 1.0,
                "brier_score": 0.4,
                "margin_mae": 1.5,
                "blowout_4plus_brier": 0.25,
                "competitive_game_recall": 0.5,
                "competitive_game_precision": 0.5,
            }
        )
        if fold != omit_challenger_fold:
            rows.append(
                {
                    "candidate": "challenger",
                    "fold_id": fold,
                    "shared_examples": 100,
                    "log_loss": 0.9,
                    "brier_score": 0.35,
                    "margin_mae": 1.3,
                    "blowout_4plus_brier": 0.20,
                    "competitive_game_recall": 0.6,
                    "competitive_game_precision": 0.6,
                }
            )
    return pd.DataFrame(rows)


def test_promotion_gate_requires_repeated_noninferior_primary_improvement():
    decision = evaluate_candidate_promotion(
        _promotion_rows(),
        champion="champion",
        challenger="challenger",
    )

    assert decision["decision"] == "promote"
    assert decision["shared_games"] == 300
    assert decision["automatic_activation"] is False


def test_default_promotion_baseline_makes_learned_candidate_registrable():
    rows = _promotion_rows().replace(
        {
            "champion": DEFAULT_PROMOTION_BASELINE,
            "challenger": "matchbalance_learned",
        }
    )

    decisions = build_promotion_decisions(rows, minimum_shared_games=250)

    assert DEFAULT_PROMOTION_BASELINE not in decisions
    assert decisions["matchbalance_learned"]["decision"] == "promote"
    assert decisions["matchbalance_learned"]["champion"] == DEFAULT_PROMOTION_BASELINE


def test_promotion_gate_holds_candidate_with_missing_tournament_fold():
    decision = evaluate_candidate_promotion(
        _promotion_rows(omit_challenger_fold="fold-003"),
        champion="champion",
        challenger="challenger",
    )

    assert decision["decision"] == "hold"
    assert any("coverage" in reason.lower() for reason in decision["reasons"])


def test_promotion_gate_holds_overall_win_that_harms_a_large_segment():
    segment_metrics = pd.DataFrame(
        [
            {
                "candidate": "champion",
                "segment_type": "matchup_gender",
                "segment_value": "girls",
                "games": 100,
                "log_loss": 0.80,
                "margin_mae": 1.20,
                "blowout_4plus_brier": 0.20,
            },
            {
                "candidate": "challenger",
                "segment_type": "matchup_gender",
                "segment_value": "girls",
                "games": 100,
                "log_loss": 0.83,
                "margin_mae": 1.15,
                "blowout_4plus_brier": 0.19,
            },
        ]
    )

    decision = evaluate_candidate_promotion(
        _promotion_rows(),
        champion="champion",
        challenger="challenger",
        segment_metrics=segment_metrics,
    )

    assert decision["decision"] == "hold"
    assert decision["segment_regressions"][0]["metric"] == "log_loss"
