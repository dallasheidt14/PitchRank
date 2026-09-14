"""The importer must treat a blank provider id as absent at every guard.

That covers the validator, the alias-cache preload, the perspective transform and the insert.
At insert, a present blank must not be refilled from the other team's id, which would make a
self-game no blank check can see.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.etl.enhanced_pipeline import EnhancedETLPipeline
from src.utils.enhanced_validators import EnhancedDataValidator


class _Insert:
    def __init__(self, db, rows):
        self._db = db
        self._rows = rows

    def execute(self):
        self._db.written.extend(self._rows if isinstance(self._rows, list) else [self._rows])
        return SimpleNamespace(data=[])


class _GamesTable:
    def __init__(self, db):
        self._db = db

    def insert(self, rows, **_k):
        return _Insert(self._db, rows)


class _DB:
    """Records a games insert only when it is executed."""

    def __init__(self):
        self.written = []

    def table(self, name):
        assert name == "games", name
        return _GamesTable(self)


@pytest.fixture
def mock_supabase():
    supabase = Mock()
    provider_result = Mock()
    provider_result.data = {"id": "test-provider-uuid"}
    supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
        provider_result
    )
    return supabase


@pytest.mark.parametrize(
    ("team_id", "opponent_id", "expected_home", "expected_away"),
    [("601496", "None", "", "601496"), ("None", "601496", "601496", "")],
)
def test_transform_cleans_a_placeholder_id(mock_supabase, team_id, opponent_id, expected_home, expected_away):
    pipeline = EnhancedETLPipeline(mock_supabase, "gotsport", dry_run=True)

    transformed = pipeline._transform_game_perspective(
        {
            "team_id": team_id,
            "opponent_id": opponent_id,
            "home_away": "A",
            "goals_for": 1,
            "goals_against": 0,
            "game_date": "2026-09-01",
        }
    )

    assert transformed["home_provider_id"] == expected_home
    assert transformed["away_provider_id"] == expected_away


def test_alias_preload_skips_a_placeholder_alias(mock_supabase):
    pipeline = EnhancedETLPipeline(mock_supabase, "gotsport", dry_run=True)
    aliases = [
        {"provider_team_id": "None", "team_id_master": "sink", "match_method": "direct_id", "review_status": "approved"},
        {"provider_team_id": "601496", "team_id_master": "real", "match_method": "direct_id", "review_status": "approved"},
    ]

    with patch("src.etl.enhanced_pipeline.call_rpc_with_fallback", return_value=aliases):
        pipeline._ensure_initialized()

    assert "None" not in pipeline.alias_cache
    assert pipeline.alias_cache["601496"]["team_id_master"] == "real"


@pytest.mark.asyncio
async def test_bulk_insert_writes_only_the_game_with_both_ids():
    db = _DB()
    pipeline = EnhancedETLPipeline(db, "gotsport", dry_run=True)
    base = {"home_score": 1, "away_score": 0, "home_team_master_id": "real", "away_team_master_id": None}
    home_perspective = {
        **base,
        "game_uid": "gotsport:2026-09-01::601496",
        "game_date": "2026-09-01",
        "home_provider_id": "601496",
        "away_provider_id": "None",
        "team_id": "601496",
        "opponent_id": "None",
    }
    away_perspective = {
        **base,
        "game_uid": "gotsport:2026-09-02::601496",
        "game_date": "2026-09-02",
        "home_provider_id": "",
        "away_provider_id": "601496",
        "team_id": "601496",
        "opponent_id": "None",
    }
    home_blank = {
        **base,
        "game_uid": "gotsport:2026-09-04::601496",
        "game_date": "2026-09-04",
        "home_provider_id": "None",
        "away_provider_id": "601496",
        "team_id": "601496",
        "opponent_id": "None",
    }
    own_id_blank_away = {
        **base,
        "game_uid": "gotsport:2026-09-05::98765",
        "game_date": "2026-09-05",
        "home_provider_id": "98765",
        "away_provider_id": "",
        "team_id": "",
        "opponent_id": "98765",
    }
    valid = {
        **base,
        "game_uid": "gotsport:2026-09-03:601496:98765",
        "game_date": "2026-09-03",
        "home_provider_id": "601496",
        "away_provider_id": "98765",
        "team_id": "601496",
        "opponent_id": "98765",
    }

    await pipeline._bulk_insert_games([home_perspective, away_perspective, home_blank, own_id_blank_away, valid])

    assert [r["game_uid"] for r in db.written] == ["gotsport:2026-09-03:601496:98765"]
    assert [r for r in db.written if r["home_provider_id"] == r["away_provider_id"]] == []


@pytest.mark.parametrize(
    ("team_id", "opponent_id", "expected_error"),
    [
        ("601496", "None", "Missing required field: opponent_id"),
        ("None", "601496", "Missing required field: team_id"),
    ],
)
def test_validator_rejects_a_placeholder_id(team_id, opponent_id, expected_error):
    is_valid, errors = EnhancedDataValidator().validate_game(
        {
            "team_id": team_id,
            "opponent_id": opponent_id,
            "home_away": "H",
            "goals_for": 1,
            "goals_against": 0,
            "game_date": "2026-09-01",
        }
    )

    assert is_valid is False
    assert errors == [expected_error]


@pytest.mark.parametrize(
    ("home_id", "away_id", "expected_error"),
    [
        ("None", "601496", "Missing required field: home_team_id or home_provider_id"),
        ("601496", "null", "Missing required field: away_team_id or away_provider_id"),
    ],
)
def test_validator_rejects_a_placeholder_id_in_home_away_layout(home_id, away_id, expected_error):
    is_valid, errors = EnhancedDataValidator().validate_game(
        {
            "home_team_id": home_id,
            "away_team_id": away_id,
            "home_score": 1,
            "away_score": 0,
            "game_date": "2026-09-01",
        }
    )

    assert is_valid is False
    assert errors == [expected_error]
