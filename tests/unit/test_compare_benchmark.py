from copy import deepcopy
from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from src.predictions.compare_benchmark import (
    BenchmarkConfig,
    apply_temperature,
    paired_event_interval,
    prepare_forecasts,
    run_benchmark,
    select_temperature,
    split_events,
)
from src.predictions.evaluation_reporting import compute_evaluation_summary


def fixture(index=0, *, game_date="2026-04-11", event="spring", version="frozen_v1", risk=0.1):
    return {
        "fixture_key": f"fixture-{index}", "actual_game_id": f"game-{index}",
        "source_event_id": event, "provider_code": "gotsport", "game_date": game_date,
        "heuristic_predicted_at": "2026-04-09T16:00:00+00:00", "evaluation_status": "settled",
        "heuristic_prediction_status": "completed", "heuristic_model_version": version,
        "home_team_master_id": "home", "away_team_master_id": "away",
        "actual_home_score": 4, "actual_away_score": 0, "actual_outcome": "team_a",
        "fixture_payload": {"home_row": {"age_group": "u14", "gender": "Boys"}},
        "heuristic_prediction": {"modelVersion": version, "response": {"prediction": {
            "winProbabilityA": 0.6, "drawProbability": 0.2, "winProbabilityB": 0.2,
            "expectedMargin": 1.1, "expectedScore": {"teamA": 2, "teamB": 1},
            "predictedWinner": "team_a", "blowout4PlusProbability": risk,
        }, "teamA": {"team_id_master": "home"}, "teamB": {"team_id_master": "away"}}, "shadowContext": {
            "predictorVersion": version, "resolvedTeamAIds": ["home"], "resolvedTeamBIds": ["away"],
            "teamAInput": {"age": 14, "games_played": 20, "power_score_final": 0.5},
            "teamBInput": {"age": 13, "games_played": 4, "power_score_final": 0.2},
        }},
    }


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("heuristic_predicted_at", "2026-04-11T00:00:00Z", "not_proven_before_game_day"),
    ("heuristic_predicted_at", "2026-04-12T00:00:00Z", "not_proven_before_game_day"),
    ("heuristic_predicted_at", "2026-04-10T20:00:00-07:00", "not_proven_before_game_day"),
    ("heuristic_predicted_at", "2026-04-09T00:00:00", "invalid_prediction_or_game_timestamp"),
    ("heuristic_predicted_at", None, "invalid_prediction_or_game_timestamp"),
    ("game_date", "bad", "invalid_prediction_or_game_timestamp"),
    ("game_date", "20260411", "invalid_prediction_or_game_timestamp"),
    ("evaluation_status", "pending_result", "not_completed_and_settled"),
    ("heuristic_prediction_status", "failed", "not_completed_and_settled"),
    ("actual_game_id", None, "missing_game_fixture_or_event_identity"),
    ("source_event_id", None, "missing_game_fixture_or_event_identity"),
    ("fixture_key", None, "missing_game_fixture_or_event_identity"),
    ("actual_home_score", None, "invalid_actual_scores"),
    ("actual_away_score", None, "invalid_actual_scores"),
    ("actual_home_score", -1, "invalid_actual_scores"),
    ("actual_away_score", 0.5, "invalid_actual_scores"),
    ("actual_home_score", True, "invalid_actual_scores"),
    ("actual_outcome", "draw", "conflicting_actual_outcome"),
])
def test_rejects_each_unverifiable_input(field, value, reason):
    row = fixture()
    row[field] = value
    frame, inventory = prepare_forecasts([row], "frozen_v1")
    assert frame.empty
    assert inventory["excluded"] == {reason: 1}


@pytest.mark.parametrize(("key", "value", "reason"), [
    ("winProbabilityA", None, "invalid_outcome_probabilities"),
    ("drawProbability", float("nan"), "invalid_outcome_probabilities"),
    ("winProbabilityB", -0.1, "invalid_outcome_probabilities"),
    ("winProbabilityA", 0.7, "invalid_outcome_probabilities"),
    ("expectedMargin", None, "missing_outcome_or_margin"),
    ("predictedWinner", None, "missing_outcome_or_margin"),
    ("blowout4PlusProbability", 1.1, "invalid_four_goal_probability"),
])
def test_rejects_invalid_forecast_without_uniform_fallback(key, value, reason):
    row = fixture()
    row["heuristic_prediction"]["response"]["prediction"][key] = value
    frame, inventory = prepare_forecasts([row], "frozen_v1")
    assert frame.empty
    assert inventory["excluded"] == {reason: 1}


def test_versions_and_duplicate_games_are_not_pooled():
    original = fixture(1)
    duplicate = fixture(2)
    duplicate["actual_game_id"] = "game-1"
    duplicate["heuristic_predicted_at"] = "2026-04-10T15:00:00Z"
    conflict = fixture(3)
    conflict["heuristic_prediction"]["modelVersion"] = "wrong_version"
    frame, inventory = prepare_forecasts([duplicate, fixture(4, version="other"), original, conflict], "frozen_v1")
    assert frame["fixture_key"].tolist() == ["fixture-1"]
    assert inventory["excluded"] == {"other_model_version": 1, "conflicting_or_missing_payload_version": 1,
                                      "duplicate_actual_game": 1}


def test_missing_risk_is_not_zero_and_frozen_cohorts_are_used():
    rows = [fixture(1, risk=None), fixture(2, risk=0)]
    original = deepcopy(rows)
    frame, _ = prepare_forecasts(rows, "frozen_v1")
    assert pd.isna(frame.iloc[0]["blowout_4plus_probability"])
    assert frame.iloc[1]["blowout_4plus_probability"] == 0
    assert frame.iloc[0]["cohort"] == "u14|Male"
    assert frame.iloc[0]["history_band"] == "under_12_games"
    assert frame.iloc[0]["age_pair"] == "cross_age"
    assert frame.iloc[0]["power_gap_band"] == "0.15_plus"
    assert rows == original


def test_probability_rounding_is_normalized_once():
    row = fixture()
    row["heuristic_prediction"]["response"]["prediction"]["drawProbability"] += 1e-7
    frame, _ = prepare_forecasts([row], "frozen_v1")
    assert frame.iloc[0]["prob_team_a_win"] == pytest.approx(0.6 / 1.0000001)
    assert frame[["prob_team_a_win", "prob_draw", "prob_team_b_win"]].iloc[0].sum() == pytest.approx(1)


@pytest.mark.parametrize("version", [None, "other_predictor"])
def test_version_override_cannot_hide_the_canonical_predictor(version):
    row = fixture()
    row["heuristic_prediction"]["shadowContext"]["predictorVersion"] = version
    frame, inventory = prepare_forecasts([row], "frozen_v1")
    assert frame.empty
    assert inventory["excluded"] == {"conflicting_or_missing_predictor_version": 1}


@pytest.mark.parametrize("side", ["home", "away"])
@pytest.mark.parametrize("replacement", [None, "unrelated"])
def test_corrected_fixture_id_cannot_reuse_a_different_teams_forecast(side, replacement):
    row = fixture()
    row[f"{side}_team_master_id"] = replacement
    frame, inventory = prepare_forecasts([row], "frozen_v1")
    assert frame.empty
    assert inventory["excluded"] == {"conflicting_or_missing_prediction_team_identity": 1}


def test_frozen_aliases_preserve_valid_identity_but_not_swapped_sides():
    row = fixture()
    row["home_team_master_id"] = "home_alias"
    row["heuristic_prediction"]["shadowContext"]["resolvedTeamAIds"].append("home_alias")
    assert len(prepare_forecasts([row], "frozen_v1")[0]) == 1
    row["home_team_master_id"], row["away_team_master_id"] = row["away_team_master_id"], row["home_team_master_id"]
    assert prepare_forecasts([row], "frozen_v1")[0].empty


def test_missing_frozen_identity_and_overlapping_aliases_are_rejected():
    row = fixture()
    row["heuristic_prediction"]["response"]["teamA"] = {}
    assert prepare_forecasts([row], "frozen_v1")[0].empty
    row = fixture()
    row["heuristic_prediction"]["shadowContext"]["resolvedTeamAIds"].append("away")
    assert prepare_forecasts([row], "frozen_v1")[0].empty


def test_split_removes_entire_overlapping_event():
    frame, _ = prepare_forecasts([
        fixture(1, event="overlap"), fixture(2, event="train"),
        fixture(3, event="overlap", game_date="2026-04-19"), fixture(4, event="test", game_date="2026-04-19"),
    ], "frozen_v1")
    config = BenchmarkConfig("frozen_v1", "2026-04-12", "2026-04-17", "2026-04-19")
    train, test, overlap = split_events(frame, config)
    assert train["actual_game_id"].tolist() == ["game-2"]
    assert test["actual_game_id"].tolist() == ["game-4"]
    assert overlap == ["gotsport:overlap"]


def test_temperature_changes_only_probabilities_and_is_side_symmetric():
    frame, _ = prepare_forecasts([fixture()], "frozen_v1")
    sharpened = apply_temperature(frame, 0.5)
    assert sharpened.iloc[0]["prob_team_a_win"] == pytest.approx(9 / 11)
    assert sharpened.iloc[0]["prob_draw"] == pytest.approx(1 / 11)
    columns = ["prob_team_a_win", "prob_draw", "prob_team_b_win"]
    pd.testing.assert_frame_equal(frame.drop(columns=columns), sharpened.drop(columns=columns))
    swapped = frame.copy()
    swapped["prob_team_a_win"], swapped["prob_team_b_win"] = frame["prob_team_b_win"], frame["prob_team_a_win"]
    reverse = apply_temperature(swapped, 0.5)
    assert reverse.iloc[0]["prob_team_b_win"] == pytest.approx(sharpened.iloc[0]["prob_team_a_win"])
    pd.testing.assert_frame_equal(apply_temperature(frame, 1), frame)


def test_selection_uses_development_only_and_cluster_interval_is_paired():
    frame, _ = prepare_forecasts([fixture(i, event=f"event-{i}") for i in range(6)], "frozen_v1")
    selected, _ = select_temperature(frame, (0.5, 1, 2))
    assert selected == 0.5
    interval = paired_event_interval(frame, apply_temperature(frame, 0.5), samples=100, seed=1)
    assert interval[1] < 0
    assert interval == pytest.approx([-np.log(9 / 11) + np.log(0.6)] * 2)
    with pytest.raises(ValueError, match="identical games"):
        paired_event_interval(frame, frame.iloc[::-1], samples=100, seed=1)


def test_event_interval_preserves_unequal_clusters_and_opposing_effects(monkeypatch):
    rows = [fixture(i, event="large") for i in range(30)]
    for i in range(2):
        row = fixture(30+i, event=f"small-{i}")
        row.update(actual_home_score=0, actual_away_score=4, actual_outcome="team_b")
        rows.append(row)
    frame, _ = prepare_forecasts(rows, "frozen_v1")
    candidate = apply_temperature(frame, 0.5)
    interval = paired_event_interval(frame, candidate, samples=1000, seed=1)
    # Entire-event draws can contain only the large improvement or only small regressions.
    assert interval == pytest.approx([-np.log(9 / 11) + np.log(0.6), -np.log(1 / 11) + np.log(0.2)])

    class MixedEventDraws:
        def integers(self, low, high, size):
            return np.tile([0, 1, 2], (size[0], 1))

    monkeypatch.setattr(np.random, "default_rng", lambda seed: MixedEventDraws())
    expected = (30 * (-np.log(9 / 11) + np.log(0.6)) + 2 * (-np.log(1 / 11) + np.log(0.2))) / 32
    assert paired_event_interval(frame, candidate, samples=100, seed=1) == pytest.approx([expected, expected])


def test_extreme_probability_interval_matches_the_reported_loss_difference():
    rows = [fixture(i, event=str(i)) for i in range(3)]
    for row in rows:
        row["heuristic_prediction"]["response"]["prediction"].update(
            winProbabilityA=1e-16, drawProbability=0.4, winProbabilityB=0.6-1e-16
        )
    frame, _ = prepare_forecasts(rows, "frozen_v1")
    candidate = apply_temperature(frame, 2)
    expected = compute_evaluation_summary(candidate)["log_loss"] - compute_evaluation_summary(frame)["log_loss"]
    assert paired_event_interval(frame, candidate, samples=100, seed=1) == pytest.approx([expected, expected])


def test_future_results_cannot_select_temperature_or_trigger_deployment(tmp_path):
    development = [fixture(i, event=f"train-{i}") for i in range(6)]
    holdout = [fixture(i+10, event=f"test-{i}", game_date="2026-04-19") for i in range(6)]
    config = BenchmarkConfig("frozen_v1", "2026-04-12", "2026-04-17", "2026-04-19",
                             minimum_games=5, minimum_events=2, bootstrap_samples=100)
    first = run_benchmark(development + holdout, config, tmp_path / "first", current_model_version="current_v6")
    for row in holdout:
        row.update(actual_home_score=0, actual_away_score=4, actual_outcome="team_b")
    second = run_benchmark(development + holdout, config, tmp_path / "second", current_model_version="current_v6")
    assert first["selected_temperature"] == second["selected_temperature"] == 0.5
    assert first["candidate_improves_holdout"] is True
    assert second["candidate_improves_holdout"] is False
    assert first["status"] == second["status"] == "research_only"
    assert "Historical source version differs from the current Compare predictor." in first["blockers"]
    assert first["production_changed"] is False
    assert first["baseline"]["winner_accuracy"] == first["candidate"]["winner_accuracy"]
    json.loads((tmp_path / "first/benchmark.json").read_text())
    with pytest.raises(FileExistsError):
        run_benchmark(development, config, tmp_path / "first", current_model_version="current_v6")


def test_shadow_candidate_requires_complete_four_goal_evidence(tmp_path):
    rows = [fixture(i, event=f"train-{i}") for i in range(6)]
    rows += [fixture(i+10, event=f"test-{i}", game_date="2026-04-19") for i in range(6)]
    config = BenchmarkConfig("frozen_v1", "2026-04-12", "2026-04-17", "2026-04-19",
                             minimum_games=5, minimum_events=2, bootstrap_samples=100)
    report = run_benchmark(rows, config, tmp_path / "complete", current_model_version="frozen_v1")
    assert report["status"] == "candidate_for_shadow_validation"
    assert report["blockers"] == []
    rows[-1]["heuristic_prediction"]["response"]["prediction"].pop("blowout4PlusProbability")
    report = run_benchmark(rows, config, tmp_path / "missing", current_model_version="frozen_v1")
    assert report["status"] == "research_only"
    assert report["blockers"] == ["Holdout does not contain complete four-goal risk forecasts."]
    assert report["production_changed"] is False


def test_missing_current_version_produces_coverage_report(tmp_path):
    config = BenchmarkConfig("current_v6", "2026-04-12", "2026-04-17", "2026-04-19")
    report = run_benchmark([fixture()], config, tmp_path / "empty", current_model_version="current_v6")
    assert report["status"] == "insufficient_data"
    assert report["inventory"]["source_versions"] == {"frozen_v1": 1}
    assert report["holdout"]["four_goal_probability_games"] == 0
    assert "selected_temperature" not in report


def test_window_and_temperature_validation():
    config = BenchmarkConfig("v1", "2026-04-12", "2026-04-17", "2026-04-19")
    for bad in (replace(config, train_end="2026-04-17"), replace(config, test_end="2026-04-16"),
                replace(config, temperatures=(float("inf"),)), replace(config, temperatures=(0,)),
                replace(config, model_version=""), replace(config, train_end="20260412")):
        with pytest.raises(ValueError):
            bad.validate()
