"""
Integration guard: game_uid is symmetric on (team_a, team_b, game_date) and
independent of scores. This is the precondition for scheduled rows UPDATING
to played rows in dedup.
"""
from datetime import date, timedelta
from unittest.mock import Mock
import pytest

from src.etl.enhanced_pipeline import EnhancedETLPipeline


@pytest.fixture
def mock_supabase():
    supabase = Mock()
    provider_result = Mock()
    provider_result.data = {'id': 'test-provider-uuid'}
    supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = provider_result
    supabase.table.return_value.select.return_value.in_.return_value.execute.return_value.data = []
    return supabase


@pytest.mark.asyncio
async def test_game_uid_identical_for_scheduled_and_played(mock_supabase):
    pipeline = EnhancedETLPipeline(mock_supabase, 'gotsport', dry_run=True)
    game_date = (date.today() + timedelta(days=3)).isoformat()

    scheduled = {
        "team_id": "team-a",
        "opponent_id": "team-b",
        "game_date": game_date,
        "goals_for": None,
        "goals_against": None,
        "home_away": "H",
        "provider": "gotsport",
    }
    played = {
        "team_id": "team-a",
        "opponent_id": "team-b",
        "game_date": game_date,
        "goals_for": 2,
        "goals_against": 1,
        "home_away": "H",
        "provider": "gotsport",
    }

    valid_sched, _, _ = await pipeline._validate_and_dedup([scheduled], run_validation=False)
    valid_played, _, _ = await pipeline._validate_and_dedup([played], run_validation=False)

    assert len(valid_sched) == 1
    assert len(valid_played) == 1
    assert valid_sched[0].get("game_uid") is not None
    assert valid_sched[0].get("game_uid") == valid_played[0].get("game_uid")
