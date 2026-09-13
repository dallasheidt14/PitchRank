from scripts.evaluate_prospective_match_predictions import (
    _extract_prediction_payload,
    _prediction_is_strictly_prospective,
    evaluate_rows,
)


def test_extract_prediction_payload_handles_heuristic_and_offline_shapes():
    row = {
        "fixture_key": "fixture-1",
        "game_date": "2026-04-15",
        "competition": "Spring Showcase",
        "division_name": "U12 Gold",
        "actual_home_score": 2,
        "actual_away_score": 1,
        "fixture_payload": {
            "home_row": {
                "age_group": "u12",
            }
        },
        "heuristic_model_version": "heuristic_v3_shadow_ready",
        "heuristic_prediction": {
            "modelVersion": "heuristic_v3_shadow_ready",
            "response": {
                "prediction": {
                    "predictedWinner": "team_a",
                    "winProbabilityA": 0.58,
                    "drawProbability": 0.22,
                    "winProbabilityB": 0.20,
                    "expectedScore": {"teamA": 2, "teamB": 1},
                    "expectedMargin": 0.8,
                }
            },
        },
        "offline_model_version": "pitm_v1",
        "offline_prediction": {
            "modelVersion": "pitm_v1",
            "prediction": {
                "predictedWinner": "draw",
                "winProbabilityA": 0.31,
                "drawProbability": 0.39,
                "winProbabilityB": 0.30,
                "expectedScore": {"teamA": 1, "teamB": 1},
                "expectedMargin": 0.0,
                "blowoutProbability3Plus": 0.04,
                "predictedBlowout3Plus": False,
            },
        },
    }

    heuristic = _extract_prediction_payload(row, "heuristic")
    offline = _extract_prediction_payload(row, "offline")

    assert heuristic is not None
    assert heuristic["predicted_outcome"] == "team_a"
    assert heuristic["actual_outcome"] == "team_a"
    assert heuristic["predicted_score_a"] == 2
    assert heuristic["age_group"] == "u12"

    assert offline is not None
    assert offline["predicted_outcome"] == "draw"
    assert offline["prob_draw"] == 0.39
    assert offline["predicted_blowout_3plus"] is False


def test_prospective_evaluation_requires_prediction_before_game_date():
    row = {
        "game_date": "2026-04-15",
        "heuristic_predicted_at": "2026-04-14T23:59:59Z",
        "offline_predicted_at": "2026-04-15T00:00:00Z",
    }

    assert _prediction_is_strictly_prospective(row, "heuristic")
    assert not _prediction_is_strictly_prospective(row, "offline")


def _settled_row(fixture_key: str, heuristic_version: str, offline_version: str):
    prediction = {
        "predictedWinner": "team_a",
        "winProbabilityA": 0.6,
        "drawProbability": 0.2,
        "winProbabilityB": 0.2,
        "expectedScore": {"teamA": 2, "teamB": 1},
        "expectedMargin": 1.0,
    }
    return {
        "fixture_key": fixture_key,
        "game_date": "2026-04-15",
        "competition": "Cup",
        "division_name": "U12 Gold",
        "fixture_payload": {"home_row": {"age_group": "u12"}},
        "actual_home_score": 2,
        "actual_away_score": 1,
        "heuristic_prediction_status": "completed",
        "offline_prediction_status": "completed",
        "heuristic_model_version": heuristic_version,
        "offline_model_version": offline_version,
        "heuristic_predicted_at": "2026-04-14T10:00:00Z",
        "offline_predicted_at": "2026-04-14T11:00:00Z",
        "heuristic_prediction": {
            "modelVersion": heuristic_version,
            "response": {"prediction": prediction},
        },
        "offline_prediction": {
            "modelVersion": offline_version,
            "prediction": prediction,
        },
    }


def test_prospective_evaluation_uses_one_version_pair_and_shared_fixtures(tmp_path):
    rows = [
        _settled_row("fixture-1", "heuristic-a", "offline-a"),
        _settled_row("fixture-2", "heuristic-a", "offline-a"),
        _settled_row("fixture-3", "heuristic-b", "offline-b"),
    ]

    summary = evaluate_rows(rows, tmp_path)

    assert summary["selected_version_pair"] == {
        "heuristic": "heuristic-a",
        "offline": "offline-a",
    }
    assert summary["heuristic_rows"] == summary["offline_rows"] == 2
    assert summary["head_to_head"]["fixtures_with_both_predictions"] == 2
