from pathlib import Path

import pandas as pd

from scripts import backtest_tournament_cohort as cohort
from scripts.predictor_python import Game as PredictorGame
from src.tournaments.seeding_optimizer import SeedableTeam


def test_snapshot_as_of_date_returns_latest_prior_snapshot():
    snapshots = [
        {"snapshot_date": "2026-04-08", "snapshot_ts": pd.Timestamp("2026-04-08"), "power_score_final": 0.51},
        {"snapshot_date": "2026-04-10", "snapshot_ts": pd.Timestamp("2026-04-10"), "power_score_final": 0.63},
        {"snapshot_date": "2026-04-12", "snapshot_ts": pd.Timestamp("2026-04-12"), "power_score_final": 0.77},
    ]

    selected = cohort._snapshot_as_of_date(snapshots, "2026-04-11")

    assert selected is not None
    assert selected["snapshot_date"] == "2026-04-10"
    assert selected["power_score_final"] == 0.63


def test_build_point_in_time_prediction_and_cost_functions_uses_asof_snapshots(monkeypatch, tmp_path):
    entrant_rows = [
        {
            "entrant_id": "entrant-a",
            "ranking_source_team_id": "team-a-source",
            "event_team_name": "Alpha",
        },
        {
            "entrant_id": "entrant-b",
            "ranking_source_team_id": "team-b-source",
            "event_team_name": "Bravo",
        },
    ]
    snapshot_index = {
        "team-a-source": [
            {
                "snapshot_date": "2026-04-09",
                "snapshot_ts": pd.Timestamp("2026-04-09"),
                "age_group": "14",
                "gender": "Male",
                "status": "Active",
                "power_score_final": 0.61,
            },
            {
                "snapshot_date": "2026-04-12",
                "snapshot_ts": pd.Timestamp("2026-04-12"),
                "age_group": "14",
                "gender": "Male",
                "status": "Active",
                "power_score_final": 0.99,
            },
        ],
        "team-b-source": [
            {
                "snapshot_date": "2026-04-08",
                "snapshot_ts": pd.Timestamp("2026-04-08"),
                "age_group": "14",
                "gender": "Male",
                "status": "Active",
                "power_score_final": 0.48,
            },
            {
                "snapshot_date": "2026-04-11",
                "snapshot_ts": pd.Timestamp("2026-04-11"),
                "age_group": "14",
                "gender": "Male",
                "status": "Active",
                "power_score_final": 0.20,
            },
        ],
    }
    all_games = [
        PredictorGame(
            id="prior-game",
            home_team_master_id="team-a-source",
            away_team_master_id="common-opponent",
            home_score=2,
            away_score=1,
            game_date="2026-04-08",
        ),
        PredictorGame(
            id="same-day-game",
            home_team_master_id="team-b-source",
            away_team_master_id="common-opponent",
            home_score=1,
            away_score=0,
            game_date="2026-04-10",
        ),
        PredictorGame(
            id="future-game",
            home_team_master_id="team-a-source",
            away_team_master_id="team-b-source",
            home_score=0,
            away_score=3,
            game_date="2026-04-11",
        ),
    ]
    captured: dict[str, object] = {}

    def fake_build_point_in_time_matchup_row(**kwargs):
        captured["team_a_snapshot_date"] = kwargs["team_a_snapshot"]["snapshot_date"]
        captured["team_b_snapshot_date"] = kwargs["team_b_snapshot"]["snapshot_date"]
        captured["prior_game_ids"] = [game.id for game in kwargs["all_games"]]
        captured["game_date"] = kwargs["game_date"]
        return {"dummy_feature": 1.0}

    class FakeModel:
        probability_strategy = "poisson_draw_gate"
        selection_objective = "competitive_match_quality"

        def predict_frame(self, frame):
            captured["frame_columns"] = list(frame.columns)
            return pd.DataFrame(
                [
                    {
                        "predicted_outcome": "team_a_win",
                        "prob_team_a_win": 0.57,
                        "prob_draw": 0.21,
                        "prob_team_b_win": 0.22,
                        "expected_goals_a": 1.8,
                        "expected_goals_b": 0.9,
                        "predicted_margin": 0.9,
                        "blowout_3plus_probability": 0.18,
                        "blowout_5plus_probability": 0.04,
                        "probability_strategy": "poisson_draw_gate",
                    }
                ]
            )

        def relabel_evaluation_frame(self, frame):
            return frame

    monkeypatch.setattr(cohort, "build_point_in_time_matchup_row", fake_build_point_in_time_matchup_row)
    monkeypatch.setattr(cohort.PointInTimeMatchModel, "load", lambda artifact_path: FakeModel())

    artifact_path = tmp_path / "fake_point_in_time_match_model.pkl"
    artifact_path.write_text("placeholder", encoding="utf-8")
    predict_fn, matchup_cost_fn, loaded_model = cohort._build_point_in_time_prediction_and_cost_functions(
        entrant_rows,
        all_games,
        prediction_date="2026-04-10",
        snapshot_index=snapshot_index,
        model_artifact=artifact_path,
    )

    assert loaded_model.probability_strategy == "poisson_draw_gate"

    team_a = SeedableTeam(
        team_id="entrant-a",
        team_name="Alpha",
        age_group="u14",
        gender="Male",
        power_score=0.61,
    )
    team_b = SeedableTeam(
        team_id="entrant-b",
        team_name="Bravo",
        age_group="u14",
        gender="Male",
        power_score=0.48,
    )
    prediction = predict_fn(team_a, team_b)
    cost = matchup_cost_fn(team_a, team_b)

    assert captured["team_a_snapshot_date"] == "2026-04-09"
    assert captured["team_b_snapshot_date"] == "2026-04-08"
    assert captured["prior_game_ids"] == ["prior-game"]
    assert captured["game_date"] == "2026-04-10"
    assert captured["frame_columns"] == ["dummy_feature"]
    assert prediction.predicted_winner == "team_a"
    assert prediction.expected_score == {"teamA": 2, "teamB": 1}
    assert prediction.source == "point_in_time:fake_point_in_time_match_model"
    assert round(cost.projected_margin, 2) == 1.0
    assert round(cost.blowout_3plus_probability, 2) == 0.18
    assert round(cost.blowout_5plus_probability, 2) == 0.04


def test_override_point_in_time_probability_strategy_swaps_policy():
    class FakeModel:
        probability_strategy = "hybrid"
        requested_probability_strategy = "auto"
        draw_decision_policy = {"default": {"min_draw_probability": 0.16}, "by_age": {14: {"min_draw_probability": 0.2}}}

        @staticmethod
        def _default_draw_decision_policy():
            return {
                "min_draw_probability": 0.25,
                "max_draw_gap": 0.02,
                "max_total_goals": 2.2,
                "min_stalemate_signal": 0.6,
            }

    model = FakeModel()

    overridden = cohort._override_point_in_time_probability_strategy(model, "poisson_draw_gate")

    assert overridden == "poisson_draw_gate"
    assert model.requested_probability_strategy == "poisson_draw_gate"
    assert model.probability_strategy == "poisson_draw_gate"
    assert model.draw_decision_policy == {
        "default": {
            "min_draw_probability": 0.25,
            "max_draw_gap": 0.02,
            "max_total_goals": 2.2,
            "min_stalemate_signal": 0.6,
        },
        "by_age": {},
    }


def test_resolve_point_in_time_probability_strategy_override_defaults_to_draw_gate():
    override = cohort._resolve_point_in_time_probability_strategy_override(None, None)

    assert override == "poisson_draw_gate"


def test_resolve_point_in_time_probability_strategy_override_prefers_cli_then_payload():
    assert (
        cohort._resolve_point_in_time_probability_strategy_override(
            "hybrid",
            "poisson_primary",
        )
        == "hybrid"
    )
    assert (
        cohort._resolve_point_in_time_probability_strategy_override(
            None,
            "poisson_primary",
        )
        == "poisson_primary"
    )


def test_normalize_actual_games_override_filters_divisions_and_coerces_scores():
    rows = [
        {
            "id": "game-1",
            "division_name": "BU10 Premier",
            "game_date": "2026-03-20",
            "home_team_master_id": "team-a",
            "away_team_master_id": "team-b",
            "home_score": "1",
            "away_score": 2,
        },
        {
            "id": "game-2",
            "division_name": "BU10 Super Elite",
            "game_date": "2026-03-20",
            "home_team_master_id": "team-c",
            "away_team_master_id": "team-d",
            "home_score": 0,
            "away_score": 0,
        },
    ]

    normalized = cohort._normalize_actual_games_override(rows, {"BU10 Premier"})

    assert normalized == [
        {
            "id": "game-1",
            "division_name": "BU10 Premier",
            "game_date": "2026-03-20",
            "home_team_master_id": "team-a",
            "away_team_master_id": "team-b",
            "home_score": 1,
            "away_score": 2,
        }
    ]


def test_build_entrant_row_keeps_event_cohort_for_play_up_team():
    notes: list[str] = []

    entrant_row = cohort._build_entrant_row(
        {
            "entrant_id": "entrant-1",
            "canonical_team_id": "canonical-team",
            "event_team_name": "Dynamos SC 2016 SC",
            "provider_team_id": "126693",
            "actual_division_name": "Platinum",
        },
        {
            "team_name": "Dynamos SC 2016 SC",
            "club_name": "Dynamos SC",
            "state_code": "AZ",
            "is_deprecated": False,
        },
        {
            "team_id": "canonical-team",
            "age_group": "u10",
            "gender": "Male",
            "status": "Active",
            "games_played": 14,
            "power_score_true": 0.61,
            "rank_in_cohort_final": 7,
        },
        cohort_age_group="u11",
        cohort_gender="Male",
        notes=notes,
    )

    assert entrant_row["age_group"] == "u11"
    assert entrant_row["gender"] == "Male"
    assert entrant_row["source_age_group"] == "u10"
    assert entrant_row["source_gender"] == "Male"
    assert any("playing up from u10 into u11" in note for note in notes)


def test_build_predictor_team_ranking_prefers_source_age_group():
    ranking = cohort._build_predictor_team_ranking(
        {
            "team_id": "source-team",
            "team_name": "Dynamos SC 2016 SC",
            "power_score": 0.61,
            "age_group": "u11",
            "source_age_group": "u10",
            "games_played": 12,
            "sos_norm": 0.52,
            "off_norm": 0.55,
            "def_norm": 0.50,
            "glicko_rating": None,
            "glicko_rd": None,
            "glicko_volatility": None,
        }
    )

    assert ranking.age == 10
