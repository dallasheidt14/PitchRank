from types import SimpleNamespace

import pandas as pd
import pytest

from scripts import backtest_tournament_cohort as cohort
from scripts import optimize_tournament_seeding as seeding_script
from src.tournaments.seeding_optimizer import SeedableTeam


def _seedable_pair() -> tuple[SeedableTeam, SeedableTeam]:
    return (
        SeedableTeam("entrant-a", "Alpha", "u14", "Male", 0.8),
        SeedableTeam("entrant-b", "Bravo", "u14", "Male", 0.4),
    )


def _predictor_entrant_rows() -> list[dict]:
    return [
        {
            "entrant_id": entrant_id,
            "ranking_source_team_id": source_id,
            "event_team_name": name,
            "power_score": power_score,
            "age_group": "u14",
            "source_age_group": "u14",
            "games_played": 20,
            "sos_norm": 0.5,
            "off_norm": 0.5,
            "def_norm": 0.5,
            "glicko_rating": 1500.0,
            "glicko_rd": 100.0,
            "glicko_volatility": 0.06,
        }
        for entrant_id, source_id, name, power_score in (
            ("entrant-a", "source-a", "Alpha", 0.8),
            ("entrant-b", "source-b", "Bravo", 0.4),
        )
    ]


def test_python_prediction_cache_preserves_requested_orientation(monkeypatch):
    def fake_predict_match(team_a, team_b, _games):
        alpha_is_a = team_a.team_id_master == "source-a"
        return SimpleNamespace(
            predicted_winner="team_a" if alpha_is_a else "team_b",
            expected_score={"teamA": 4 if alpha_is_a else 0, "teamB": 0 if alpha_is_a else 4},
            expected_margin=4.0 if alpha_is_a else -4.0,
            win_probability_a=0.9 if alpha_is_a else 0.1,
            win_probability_b=0.1 if alpha_is_a else 0.9,
        )

    monkeypatch.setattr(cohort, "predict_match", fake_predict_match)
    predict_fn, matchup_cost_fn = cohort._build_python_prediction_and_cost_functions(
        _predictor_entrant_rows(), []
    )
    alpha, bravo = _seedable_pair()

    forward = predict_fn(alpha, bravo)
    reverse = predict_fn(bravo, alpha)

    assert forward.predicted_winner == "team_a"
    assert forward.expected_score == {"teamA": 4, "teamB": 0}
    assert reverse.predicted_winner == "team_b"
    assert reverse.expected_score == {"teamA": 0, "teamB": 4}
    assert matchup_cost_fn(alpha, bravo) == matchup_cost_fn(bravo, alpha)


@pytest.mark.parametrize("first_order", [("entrant-a", "entrant-b"), ("entrant-b", "entrant-a")])
def test_point_in_time_prediction_cache_preserves_requested_orientation(monkeypatch, tmp_path, first_order):
    class FakeModel:
        probability_strategy = "poisson_draw_gate"
        selection_objective = "competitive_match_quality"

        def predict_frame(self, frame):
            alpha_is_a = frame.iloc[0]["team_a_id"] == "source-a"
            return pd.DataFrame(
                [
                    {
                        "predicted_outcome": "team_a_win" if alpha_is_a else "team_b_win",
                        "prob_team_a_win": 0.9 if alpha_is_a else 0.1,
                        "prob_draw": 0.0,
                        "prob_team_b_win": 0.1 if alpha_is_a else 0.9,
                        "expected_goals_a": 4.0 if alpha_is_a else 0.0,
                        "expected_goals_b": 0.0 if alpha_is_a else 4.0,
                        "predicted_margin": 4.0 if alpha_is_a else -4.0,
                        "blowout_3plus_probability": 0.8,
                        "blowout_5plus_probability": 0.2,
                    }
                ]
            )

        def relabel_evaluation_frame(self, frame):
            return frame

    monkeypatch.setattr(cohort.PointInTimeMatchModel, "load", lambda _path: FakeModel())
    monkeypatch.setattr(
        cohort,
        "build_point_in_time_matchup_row",
        lambda **kwargs: {"team_a_id": kwargs["team_a_id"], "team_b_id": kwargs["team_b_id"]},
    )
    artifact = tmp_path / "model.pkl"
    artifact.write_text("placeholder", encoding="utf-8")
    rows = _predictor_entrant_rows()
    snapshots = {
        row["ranking_source_team_id"]: {
            "snapshot_date": "2026-04-09",
            "power_score_final": row["power_score"],
        }
        for row in rows
    }
    predict_fn, matchup_cost_fn, _model = cohort._build_point_in_time_prediction_and_cost_functions(
        rows,
        [],
        prediction_date="2026-04-10",
        snapshot_index={},
        resolved_snapshots_by_source_id=snapshots,
        model_artifact=artifact,
    )
    teams = {team.team_id: team for team in _seedable_pair()}

    predict_fn(teams[first_order[0]], teams[first_order[1]])
    forward = predict_fn(teams["entrant-a"], teams["entrant-b"])
    reverse = predict_fn(teams["entrant-b"], teams["entrant-a"])

    assert forward.predicted_winner == "team_a"
    assert forward.expected_score == {"teamA": 4, "teamB": 0}
    assert reverse.predicted_winner == "team_b"
    assert reverse.expected_score == {"teamA": 0, "teamB": 4}
    assert matchup_cost_fn(teams["entrant-a"], teams["entrant-b"]) == matchup_cost_fn(
        teams["entrant-b"], teams["entrant-a"]
    )


def test_standalone_predictor_cost_uses_canonical_orientation(monkeypatch):
    seen: list[tuple[str, str]] = []

    def fake_predict_match(team_a, team_b, _games):
        seen.append((team_a.team_id_master, team_b.team_id_master))
        return SimpleNamespace(
            predicted_winner="team_a",
            expected_score={"teamA": 2, "teamB": 1},
            expected_margin=1.0,
            win_probability_a=0.6,
            win_probability_b=0.4,
        )

    monkeypatch.setattr(seeding_script, "predict_match", fake_predict_match)
    rows = [
        {
            "team_id": team_id,
            "team_name": name,
            "age_group": "u14",
            "games_played": 12,
            "power_score": score,
            "sos_norm": 0.5,
            "off_norm": 0.5,
            "def_norm": 0.5,
        }
        for team_id, name, score in (("team-a", "Alpha", 0.7), ("team-b", "Bravo", 0.6))
    ]
    cost_fn, _name = seeding_script._build_predictor_matchup_cost_fn(rows, [])
    alpha = SeedableTeam("team-a", "Alpha", "u14", "Male", 0.7)
    bravo = SeedableTeam("team-b", "Bravo", "u14", "Male", 0.6)

    reverse_cost = cost_fn(bravo, alpha)
    forward_cost = cost_fn(alpha, bravo)

    assert reverse_cost == forward_cost
    assert seen == [("team-a", "team-b")]
