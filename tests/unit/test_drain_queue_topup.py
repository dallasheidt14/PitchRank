"""Tests for the teams-table top-up that fills out short queue batches."""

import os
import sys
from unittest.mock import Mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from postgrest.exceptions import APIError

from scripts.drain_queue import _fetch_topup_teams

TEAM_KEYS = {
    "team_id_master",
    "team_name",
    "provider_id",
    "provider_team_id",
    "age_group",
    "birth_year",
    "last_scraped_at",
}


def _team_row(team_id):
    """A row shaped like SETOF public.teams, with extra columns the helper drops."""
    return {
        "team_id_master": team_id,
        "team_name": f"Team {team_id}",
        "provider_id": "prov-1",
        "provider_team_id": f"pt-{team_id}",
        "age_group": "u12",
        "birth_year": 2014,
        "last_scraped_at": None,
        "state_code": "CA",  # extra column that must not leak through
    }


def _supabase_returning(rows):
    """Mock matching call_rpc_with_fallback's supabase.rpc(...).limit(...).execute().data chain."""
    supabase = Mock()
    supabase.rpc.return_value.limit.return_value.execute.return_value.data = rows
    return supabase


def test_no_rpc_call_when_batch_is_already_full():
    supabase = _supabase_returning([])
    assert _fetch_topup_teams(supabase, "prov-1", 0, {"t-1"}) == []
    assert _fetch_topup_teams(supabase, "prov-1", -5, {"t-1"}) == []
    supabase.rpc.assert_not_called()


def test_requests_shortfall_padded_by_exclusion_count():
    """920 claimed, 300 survive filtering, limit 4000 -> shortfall 3700, p_limit 4000."""
    supabase = _supabase_returning([])
    _fetch_topup_teams(supabase, "prov-1", 3700, {f"t-{i}" for i in range(300)})

    fn_name, params = supabase.rpc.call_args.args
    assert fn_name == "get_teams_to_scrape_limited"
    assert params["p_limit"] == 4000
    assert params["p_provider_id"] == "prov-1"
    assert params["p_include_recent"] is False
    assert params["p_null_only"] is False
    assert params["p_shard_index"] == 0
    assert params["p_shard_count"] == 1


def test_drops_overlap_with_claimed_batch_and_truncates_to_shortfall():
    supabase = _supabase_returning([_team_row(f"t-{i}") for i in range(5)])
    result = _fetch_topup_teams(supabase, "prov-1", 2, {"t-0", "t-1"})
    assert [t["team_id_master"] for t in result] == ["t-2", "t-3"]


def test_preserves_rpc_order():
    """The RPC orders last_scraped_at ASC NULLS FIRST; the helper must not reorder."""
    supabase = _supabase_returning([_team_row("t-9"), _team_row("t-4"), _team_row("t-7")])
    result = _fetch_topup_teams(supabase, "prov-1", 3, set())
    assert [t["team_id_master"] for t in result] == ["t-9", "t-4", "t-7"]


def test_returns_fewer_than_shortfall_when_supply_is_short():
    supabase = _supabase_returning([_team_row("t-0")])
    assert len(_fetch_topup_teams(supabase, "prov-1", 10, set())) == 1


def test_skips_rows_with_no_team_id_master():
    rows = [_team_row("t-0"), {**_team_row("t-1"), "team_id_master": None}, _team_row("t-2")]
    supabase = _supabase_returning(rows)
    result = _fetch_topup_teams(supabase, "prov-1", 5, set())
    assert [t["team_id_master"] for t in result] == ["t-0", "t-2"]


def test_returns_only_the_keys_the_scrape_path_reads():
    supabase = _supabase_returning([_team_row("t-0")])
    (team,) = _fetch_topup_teams(supabase, "prov-1", 1, set())
    assert set(team) == TEAM_KEYS


def test_missing_rpc_degrades_to_queue_only():
    """Rolling deploy where the migration has not landed must not crash a drain."""
    supabase = Mock()
    supabase.rpc.return_value.limit.return_value.execute.side_effect = APIError(
        {"code": "42883", "message": "function does not exist", "hint": "", "details": ""}
    )
    assert _fetch_topup_teams(supabase, "prov-1", 100, set()) == []


def test_other_api_errors_propagate():
    """Only 42883 is survivable; a real DB fault must not be silently swallowed."""
    supabase = Mock()
    supabase.rpc.return_value.limit.return_value.execute.side_effect = APIError(
        {"code": "42P01", "message": "relation does not exist", "hint": "", "details": ""}
    )
    try:
        _fetch_topup_teams(supabase, "prov-1", 100, set())
    except APIError:
        return
    raise AssertionError("expected APIError to propagate")


def test_none_data_is_treated_as_empty():
    """PostgREST can return data=None; the helper must not raise on it."""
    assert _fetch_topup_teams(_supabase_returning(None), "prov-1", 5, set()) == []
