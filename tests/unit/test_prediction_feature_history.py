from __future__ import annotations

import math

import pandas as pd

from src.rankings.prediction_feature_history import (
    LEAGUE_AVG_TOTAL_GOALS,
    build_prediction_feature_snapshot_records,
)


def test_build_prediction_feature_snapshot_records_normalizes_live_predictor_fields():
    snapshot_date = pd.Timestamp("2026-04-07").date()
    rankings_df = pd.DataFrame(
        [
            {
                "team_id": "team-1",
                "age": 14,
                "gender": "Boys",
                "state_code": "AZ",
                "status": "Active",
                "rank_in_cohort_final": 8,
                "power_score_final": 0.81,
                "sos_norm": 0.63,
                "off_norm": 0.71,
                "def_norm": 0.66,
                "mu": 1580.0,
                "sigma": 54.0,
                "volatility": 0.06,
                "wins": 12,
                "losses": 3,
                "draws": 5,
                "gp": 20,
                "exp_margin": 0.45,
                "last_calculated": pd.Timestamp("2026-04-07T16:45:00Z"),
            }
        ]
    )

    records = build_prediction_feature_snapshot_records(rankings_df, snapshot_date=snapshot_date)

    assert len(records) == 1
    record = records[0]

    assert record["snapshot_date"] == "2026-04-07"
    assert record["team_id"] == "team-1"
    assert record["age_group"] == "u14"
    assert record["gender"] == "Male"
    assert record["state_code"] == "AZ"
    assert record["rank_in_cohort_final"] == 8
    assert record["offense_norm"] == 0.71
    assert record["defense_norm"] == 0.66
    assert record["glicko_rating"] == 1580.0
    assert record["glicko_rd"] == 54.0
    assert record["glicko_volatility"] == 0.06
    assert record["games_played"] == 20
    assert record["wins"] == 12
    assert record["losses"] == 3
    assert record["draws"] == 5
    assert math.isclose(record["win_percentage"], 72.5, rel_tol=1e-9)
    assert record["last_calculated"] == "2026-04-07T16:45:00+00:00"

    expected_total = LEAGUE_AVG_TOTAL_GOALS * ((0.71 + 0.66) / 2.0)
    expected_goals_for = expected_total / (1.0 + math.exp(-0.45))
    expected_goals_against = expected_total - expected_goals_for
    assert math.isclose(record["exp_goals_for"], expected_goals_for, rel_tol=1e-9)
    assert math.isclose(record["exp_goals_against"], expected_goals_against, rel_tol=1e-9)


def test_build_prediction_feature_snapshot_records_skips_blank_team_ids_and_preserves_explicit_age_group():
    rankings_df = pd.DataFrame(
        [
            {
                "team_id": None,
                "age": 13,
                "gender": "Girls",
            },
            {
                "team_id": "team-2",
                "age_group": "U19",
                "gender": "Female",
                "games_played": 0,
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "exp_goals_for": 1.4,
                "exp_goals_against": 0.9,
            },
        ]
    )

    records = build_prediction_feature_snapshot_records(rankings_df, snapshot_date=pd.Timestamp("2026-04-08").date())

    assert len(records) == 1
    record = records[0]
    assert record["team_id"] == "team-2"
    assert record["age_group"] == "u19"
    assert record["gender"] == "Female"
    assert record["win_percentage"] is None
    assert record["exp_goals_for"] == 1.4
    assert record["exp_goals_against"] == 0.9
