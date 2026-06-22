"""Tests for the daily active-teams enqueue script."""

import os
import sys
from datetime import date
from unittest.mock import Mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.enqueue_active_teams import (
    DEFAULT_COOLDOWN_HOURS,
    DEFAULT_LIMIT,
    DEFAULT_WINDOW_DAYS,
    PRIORITY_ACTIVE_TEAM,
    enqueue_team,
    find_teams_to_enqueue,
)


def test_priority_constant_is_2():
    assert PRIORITY_ACTIVE_TEAM == 2


def test_default_limit_is_2000():
    assert DEFAULT_LIMIT == 2000


def test_default_window_and_cooldown():
    assert DEFAULT_WINDOW_DAYS == 3
    assert DEFAULT_COOLDOWN_HOURS == 20


def test_find_teams_to_enqueue_dedups_team_ids():
    supabase = Mock()
    supabase.rpc.return_value.execute.return_value.data = [
        {"team_id_master": "t-1", "team_name": "A", "provider_team_id": "p-1"},
        {"team_id_master": "t-2", "team_name": "B", "provider_team_id": "p-2"},
        {"team_id_master": "t-1", "team_name": "A", "provider_team_id": "p-1"},
    ]
    teams = find_teams_to_enqueue(supabase, gotsport_provider_id="gp")
    team_ids = [t["team_id_master"] for t in teams]
    assert len(team_ids) == len(set(team_ids))


def test_find_teams_passes_window_and_cooldown_params():
    supabase = Mock()
    supabase.rpc.return_value.execute.return_value.data = []
    find_teams_to_enqueue(supabase, gotsport_provider_id="gp", window_days=7, cooldown_hours=24, limit=500)
    rpc_call = supabase.rpc.call_args
    assert rpc_call.args[0] == "find_recently_active_teams"
    payload = rpc_call.args[1]
    assert payload["p_provider_id"] == "gp"
    assert payload["p_active_window_days"] == 7
    assert payload["p_cooldown_hours"] == 24
    assert payload["p_row_limit"] == 500


def test_enqueue_team_uses_priority_2_and_active_team_type():
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
    assert payload["p_priority"] == 2
    assert payload["p_request_type"] == "active_team"
    assert payload["p_game_date"] == date.today().isoformat()
    assert payload["p_team_id_master"] == "t-1"
    assert payload["p_team_name"] == "Team A"
    assert payload["p_provider_id"] == "gp"
    assert payload["p_provider_team_id"] == "p-1"
