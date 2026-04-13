import json

import pandas as pd

from scripts import prepare_prospective_match_predictions as prospective
from scripts.predictor_python import Game as PredictorGame
from scripts.prepare_prospective_match_predictions import load_fixtures_from_jsonl


def test_load_fixtures_from_jsonl_dedupes_home_and_away_rows(tmp_path):
    fixtures_file = tmp_path / "fixtures.jsonl"
    rows = [
        {
            "provider": "gotsport",
            "team_id_source": "111",
            "opponent_id_source": "222",
            "team_name": "Home Team",
            "opponent_name": "Away Team",
            "home_away": "H",
            "game_date": "2026-04-15",
            "competition": "Spring Showcase",
            "division_name": "U12 Gold",
            "venue": "Field 1",
            "match_id": "555_111_222_2026-04-15",
            "source_url": "https://system.gotsport.com/org_event/events/555/schedules",
        },
        {
            "provider": "gotsport",
            "team_id_source": "222",
            "opponent_id_source": "111",
            "team_name": "Away Team",
            "opponent_name": "Home Team",
            "home_away": "A",
            "game_date": "2026-04-15",
            "competition": "Spring Showcase",
            "division_name": "U12 Gold",
            "venue": "Field 1",
            "match_id": "555_111_222_2026-04-15",
            "source_url": "https://system.gotsport.com/org_event/events/555/schedules",
        },
    ]
    fixtures_file.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    fixtures = load_fixtures_from_jsonl(fixtures_file, "artifact.jsonl")

    assert len(fixtures) == 1
    fixture = fixtures[0]
    assert fixture.source_event_id == "555"
    assert fixture.home_provider_team_id == "111"
    assert fixture.away_provider_team_id == "222"
    assert fixture.home_team_name == "Home Team"
    assert fixture.away_team_name == "Away Team"
    assert fixture.fixture_key.startswith("gotsport|555|2026-04-15")


def test_build_offline_prediction_uses_asof_snapshots_and_only_prior_games(monkeypatch):
    fixture = prospective.FixtureRecord(
        fixture_key="gotsport|555|2026-04-10|home|away|field-1|u12-gold",
        provider_code="gotsport",
        source_system="gotsport_event_schedule",
        source_artifact_path="artifact.jsonl",
        source_event_id="555",
        source_match_key="555_111_222_2026-04-10",
        game_date="2026-04-10",
        competition="Spring Showcase",
        division_name="U12 Gold",
        venue="Field 1",
        home_provider_team_id="111",
        away_provider_team_id="222",
        home_team_name="Home Team",
        away_team_name="Away Team",
        fixture_payload={},
    )
    snapshot_index = {
        "home-team": [
            {
                "team_id": "home-team",
                "snapshot_date": "2026-04-09",
                "snapshot_ts": pd.Timestamp("2026-04-09"),
                "age_group": "12",
                "gender": "Male",
                "status": "Active",
                "power_score_final": 0.55,
            },
            {
                "team_id": "home-team",
                "snapshot_date": "2026-04-11",
                "snapshot_ts": pd.Timestamp("2026-04-11"),
                "age_group": "12",
                "gender": "Male",
                "status": "Active",
                "power_score_final": 0.99,
            },
        ],
        "away-team": [
            {
                "team_id": "away-team",
                "snapshot_date": "2026-04-08",
                "snapshot_ts": pd.Timestamp("2026-04-08"),
                "age_group": "12",
                "gender": "Male",
                "status": "Active",
                "power_score_final": 0.44,
            },
            {
                "team_id": "away-team",
                "snapshot_date": "2026-04-12",
                "snapshot_ts": pd.Timestamp("2026-04-12"),
                "age_group": "12",
                "gender": "Male",
                "status": "Active",
                "power_score_final": 0.11,
            },
        ],
    }
    recent_games = [
        PredictorGame(
            id="prior-game",
            home_team_master_id="home-team",
            away_team_master_id="common-opponent",
            home_score=2,
            away_score=1,
            game_date="2026-04-09",
        ),
        PredictorGame(
            id="same-day-game",
            home_team_master_id="away-team",
            away_team_master_id="common-opponent",
            home_score=1,
            away_score=1,
            game_date="2026-04-10",
        ),
        PredictorGame(
            id="future-game",
            home_team_master_id="home-team",
            away_team_master_id="away-team",
            home_score=3,
            away_score=0,
            game_date="2026-04-11",
        ),
    ]
    captured = {}

    def fake_build_point_in_time_matchup_row(**kwargs):
        captured["team_a_snapshot"] = kwargs["team_a_snapshot"]
        captured["team_b_snapshot"] = kwargs["team_b_snapshot"]
        captured["prior_game_ids"] = [game.id for game in kwargs["all_games"]]
        return {"dummy_feature": 1.0}

    class FakeModel:
        def predict_frame(self, frame):
            captured["frame_columns"] = list(frame.columns)
            return pd.DataFrame(
                [
                    {
                        "predicted_outcome": "team_a",
                        "prob_team_a_win": 0.52,
                        "prob_draw": 0.24,
                        "prob_team_b_win": 0.24,
                        "expected_goals_a": 1.6,
                        "expected_goals_b": 1.1,
                        "predicted_score_a": 2,
                        "predicted_score_b": 1,
                        "predicted_margin": 0.5,
                        "probability_strategy": "poisson_draw_gate",
                        "blowout_3plus_probability": 0.1,
                        "blowout_5plus_probability": 0.02,
                        "predicted_blowout_3plus": 0,
                        "predicted_blowout_5plus": 0,
                        "stalemate_signal": 0.3,
                        "projected_total_goals": 2.7,
                        "poisson_prob_team_a_win": 0.5,
                        "poisson_prob_draw": 0.25,
                        "poisson_prob_team_b_win": 0.25,
                        "draw_model_probability": 0.24,
                    }
                ]
            )

    monkeypatch.setattr(prospective, "build_point_in_time_matchup_row", fake_build_point_in_time_matchup_row)

    payload = prospective._build_offline_prediction(
        fixture,
        home_team_id="home-team",
        away_team_id="away-team",
        team_names={"home-team": "Home Team", "away-team": "Away Team"},
        recent_games=recent_games,
        snapshot_index=snapshot_index,
        model=FakeModel(),
        calibrator=None,
        model_version="pitm_test_poisson_draw_gate",
    )

    assert captured["team_a_snapshot"]["snapshot_date"] == "2026-04-09"
    assert captured["team_b_snapshot"]["snapshot_date"] == "2026-04-08"
    assert captured["prior_game_ids"] == ["prior-game"]
    assert payload["modelVersion"] == "pitm_test_poisson_draw_gate"
    assert payload["prediction"]["predictedWinner"] == "team_a"
