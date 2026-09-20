import pytest

from scripts.evaluate_prospective_match_predictions import _extract_prediction_payload, _fetch_rows


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


@pytest.mark.parametrize("key", ["blowout4PlusProbability", "blowoutProbability4Plus"])
@pytest.mark.parametrize("value", [0.0, 0.25, None])
def test_extract_four_goal_risk_preserves_zero_and_absence(key, value):
    row = {"heuristic_prediction": {"response": {"prediction": {key: value}}}}
    assert _extract_prediction_payload(row, "heuristic")["blowout_4plus_probability"] == value


def test_fetch_pages_have_a_unique_tiebreaker_and_read_prediction_times():
    records = [{"id": i} for i in range(1001)]
    executions = []

    class Query:
        def __init__(self):
            self.orders = []

        def select(self, fields):
            self.fields = fields
            return self

        def eq(self, key, value):
            assert (key, value) == ("evaluation_status", "settled")
            return self

        def order(self, field, **kwargs):
            self.orders.append(field)
            return self

        def range(self, start, end):
            self.bounds = start, end
            return self

        def execute(self):
            assert self.orders == ["game_date", "id"]
            assert "heuristic_predicted_at" in self.fields.split(", ")
            assert "home_team_master_id" in self.fields.split(", ")
            assert "away_team_master_id" in self.fields.split(", ")
            executions.append(self.bounds)
            start, end = self.bounds
            return type("Result", (), {"data": records[start:end + 1]})()

    class Client:
        def table(self, name):
            assert name == "prospective_match_predictions"
            return Query()

    assert _fetch_rows(Client(), None) == records
    assert executions == [(0, 999), (1000, 1999)]
