"""Tests for the daily yesterday-game enqueue script."""
from datetime import date, timedelta
from unittest.mock import Mock, MagicMock
import os, sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.enqueue_yesterday_games import (
    find_teams_to_enqueue,
    enqueue_team,
    PRIORITY_YESTERDAY_GAME,
)


def test_priority_constant_is_2():
    assert PRIORITY_YESTERDAY_GAME == 2


def test_find_teams_to_enqueue_returns_distinct_team_ids():
    supabase = Mock()
    supabase.rpc.return_value.execute.return_value.data = [
        {"team_id_master": "t-1", "team_name": "A", "provider_team_id": "p-1"},
        {"team_id_master": "t-2", "team_name": "B", "provider_team_id": "p-2"},
        {"team_id_master": "t-1", "team_name": "A", "provider_team_id": "p-1"},  # dup
    ]
    teams = find_teams_to_enqueue(supabase, gotsport_provider_id="gp")
    team_ids = [t["team_id_master"] for t in teams]
    assert len(team_ids) == len(set(team_ids)), "Distinct team_ids only"


def test_enqueue_team_calls_rpc_with_priority_2():
    supabase = Mock()
    supabase.rpc.return_value.execute.return_value.data = "test-request-id"
    enqueue_team(
        supabase,
        team_id_master="t-1",
        team_name="Team A",
        provider_id="gp",
        provider_team_id="p-1",
        game_date="2026-05-19",
    )
    # Verify RPC was called with priority 2
    rpc_call = supabase.rpc.call_args
    assert rpc_call.args[0] == "enqueue_scrape_request"
    payload = rpc_call.args[1]
    assert payload["p_priority"] == 2
    assert payload["p_request_type"] == "yesterday_game"
    assert payload["p_team_id_master"] == "t-1"
    assert payload["p_team_name"] == "Team A"
    assert payload["p_provider_id"] == "gp"
    assert payload["p_provider_team_id"] == "p-1"
    assert payload["p_game_date"] == "2026-05-19"
