"""Tests for the weekly discovery enqueue script."""
import os
import sys
from unittest.mock import Mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.enqueue_discovery_teams import (
    DEFAULT_LIMIT,
    PRIORITY_DISCOVERY,
    enqueue_team,
    find_teams_to_enqueue,
)


def test_priority_constant_is_3():
    assert PRIORITY_DISCOVERY == 3


def test_default_limit_is_1000():
    assert DEFAULT_LIMIT == 1000


def test_find_teams_to_enqueue_dedups_team_ids():
    supabase = Mock()
    supabase.rpc.return_value.execute.return_value.data = [
        {"team_id_master": "t-1", "team_name": "A", "provider_team_id": "p-1"},
        {"team_id_master": "t-2", "team_name": "B", "provider_team_id": "p-2"},
        {"team_id_master": "t-1", "team_name": "A", "provider_team_id": "p-1"},  # dup
    ]
    teams = find_teams_to_enqueue(supabase, gotsport_provider_id="gp")
    team_ids = [t["team_id_master"] for t in teams]
    assert len(team_ids) == len(set(team_ids))


def test_enqueue_team_uses_priority_3_and_today_game_date():
    """Discovery uses today's date as a placeholder since game_date is NOT NULL."""
    from datetime import date

    supabase = Mock()
    supabase.rpc.return_value.execute.return_value.data = "test-id"
    enqueue_team(
        supabase,
        team_id_master="t-1",
        team_name="Team A",
        provider_id="gp",
        provider_team_id="p-1",
    )
    rpc_call = supabase.rpc.call_args
    assert rpc_call.args[0] == "enqueue_scrape_request"
    payload = rpc_call.args[1]
    assert payload["p_priority"] == 3
    assert payload["p_request_type"] == "discovery"
    assert payload["p_game_date"] == date.today().isoformat()
    assert payload["p_team_id_master"] == "t-1"
