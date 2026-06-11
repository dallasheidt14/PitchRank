import numpy as np
import pandas as pd

from src.rankings.data_adapter import supabase_to_v53e_format
from src.rankings.shared import normalize_gender


def test_normalize_gender_maps_labels():
    series = pd.Series(["Boys", "girl", " MALE ", "Female"])

    assert normalize_gender(series).tolist() == ["male", "female", "male", "female"]


def test_normalize_gender_keeps_nulls_null():
    series = pd.Series(["Boys", None, np.nan, "Girls"])

    result = normalize_gender(series)

    assert result.isna().tolist() == [False, True, True, False]
    # Nulls must not be stringified into phantom "nan"/"none" cohorts
    assert set(result.dropna()) == {"male", "female"}


def test_supabase_to_v53e_format_drops_null_gender_teams():
    games_df = pd.DataFrame(
        [
            {
                "id": "game-1",
                "game_date": "2026-04-01",
                "home_team_master_id": "team-known",
                "away_team_master_id": "team-nullgender",
                "home_score": 2,
                "away_score": 1,
            },
            {
                "id": "game-2",
                "game_date": "2026-04-02",
                "home_team_master_id": "team-known",
                "away_team_master_id": "team-known2",
                "home_score": 1,
                "away_score": 1,
            },
        ]
    )
    teams_df = pd.DataFrame(
        [
            {"team_id_master": "team-known", "age_group": "u12", "gender": "Male"},
            {"team_id_master": "team-known2", "age_group": "u12", "gender": "Boys"},
            {"team_id_master": "team-nullgender", "age_group": "u12", "gender": None},
        ]
    )

    result = supabase_to_v53e_format(games_df, teams_df)

    # The null-gender team's game is dropped entirely; no NaN cohort rows leak
    assert set(result["game_id"]) == {"game-2"}
    assert result["gender"].notna().all()
    assert set(result["gender"]) == {"male"}
