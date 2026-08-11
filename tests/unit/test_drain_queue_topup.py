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


def test_finalize_only_touches_claimed_queue_rows():
    """_finalize_queue_items iterates queue_map, so it ignores any log_buffer
    entry with no corresponding queue row.

    This pins the finalize helper's behavior only — it does not exercise
    drain_queue(), so it cannot verify that top-up teams never end up in
    queue_map. That call-site guarantee is checked separately by the manual
    dry-run in the plan's Task 4.
    """
    from scripts.drain_queue import _finalize_queue_items

    supabase = Mock()
    queue_map = {"t-queue": "req-1"}
    log_buffer = [
        {"team_id_master": "t-queue", "games_found": 3, "status": "success"},
        {"team_id_master": "t-topup", "games_found": 7, "status": "success"},
    ]

    _finalize_queue_items(supabase, queue_map, log_buffer)

    eq_calls = supabase.table.return_value.update.return_value.eq.call_args_list
    assert [c.args for c in eq_calls] == [("id", "req-1")]
    supabase.table.return_value.update.return_value.in_.assert_not_called()


def test_release_queue_items_batches_at_100():
    """PostgREST puts the id list in the query string, so an unbatched
    .in_() breaks the URI length limit at a few hundred UUIDs."""
    from scripts.drain_queue import _release_queue_items

    supabase = Mock()
    _release_queue_items(supabase, [f"req-{i}" for i in range(250)])

    in_calls = supabase.table.return_value.update.return_value.in_.call_args_list
    assert [len(c.args[1]) for c in in_calls] == [100, 100, 50]
    payload = supabase.table.return_value.update.call_args.args[0]
    assert payload == {"status": "pending", "processed_at": None}


def test_release_queue_items_survives_a_failing_batch():
    """A failed release must not mask the original error that triggered it."""
    from scripts.drain_queue import _release_queue_items

    supabase = Mock()
    supabase.table.return_value.update.return_value.in_.return_value.execute.side_effect = RuntimeError("boom")

    _release_queue_items(supabase, ["req-1"])  # must not raise


def _drain_with(dry_run, topup_error):
    """Drive drain_queue() far enough to exercise the claim->release window.

    Returns (outcome, release_call_count). No network: the scraper, the claim,
    the metadata fetch and the top-up are all stubbed.
    """
    import asyncio
    from unittest.mock import patch

    import scripts.drain_queue as d

    released = []
    supabase = Mock()

    def _table(_name):
        t = Mock()
        t.update.return_value.in_.return_value.execute.side_effect = lambda: released.append(1) or Mock()
        return t

    supabase.table.side_effect = _table
    claimed = [
        {
            "id": "req-1",
            "team_id_master": "t-1",
            "team_name": "A",
            "provider_id": "p",
            "provider_team_id": "1",
            "game_date": None,
            "priority": 1,
            "request_type": "x",
        }
    ]
    meta = {"t-1": {"age_group": "u12", "birth_year": 2014, "last_scraped_at": None}}
    topup = (lambda *a, **k: []) if topup_error is None else topup_error

    with (
        patch.object(d, "create_client", return_value=supabase),
        patch.object(d, "GotSportScraper") as gs,
        patch.object(d, "_claim_queue_items", return_value=claimed),
        patch.object(d, "_fetch_team_metadata", return_value=meta),
        patch.object(d, "_fetch_topup_teams", side_effect=topup),
    ):
        gs.return_value._get_provider_id.return_value = "pid"
        try:
            asyncio.run(d.drain_queue(limit=50, concurrency=1, dry_run=dry_run))
            return "completed", len(released)
        except RuntimeError:
            return "raised", len(released)


def test_dry_run_releases_claims_when_topup_fails():
    """Regression: a transient PostgREST error in the top-up used to propagate
    before the dry-run release, stranding the claimed rows in 'processing'
    where no reaper would ever recover them."""
    outcome, releases = _drain_with(dry_run=True, topup_error=RuntimeError("transient"))
    assert outcome == "raised"
    assert releases == 1


def test_real_run_does_not_release_claims_on_success():
    """The guard must be an except, not a finally: on the non-dry-run success
    path the rows stay 'processing' through the scrape so _finalize_queue_items
    can complete them."""
    outcome, releases = _drain_with(dry_run=False, topup_error=None)
    assert outcome == "completed"
    assert releases == 0


def test_real_run_releases_claims_when_topup_fails():
    outcome, releases = _drain_with(dry_run=False, topup_error=RuntimeError("transient"))
    assert outcome == "raised"
    assert releases == 1


def test_excluded_birth_years_is_dynamic():
    """Mirrors the SQL side's extract(year from now()) minus (21,20,9,8,7)."""
    import datetime as _dt

    from scripts.drain_queue import _excluded_birth_years

    assert _excluded_birth_years(_dt.date(2026, 8, 11)) == [2005, 2006, 2017, 2018, 2019]
    assert _excluded_birth_years(_dt.date(2027, 1, 1)) == [2006, 2007, 2018, 2019, 2020]
    # Defaults to today rather than a frozen list.
    assert _excluded_birth_years() == _excluded_birth_years(_dt.date.today())


def test_is_scrapeable_team_accepts_a_normal_team():
    from scripts.drain_queue import _is_scrapeable_team

    assert _is_scrapeable_team(
        {"team_name": "Real Team", "provider_team_id": "123", "age_group": "u12", "birth_year": 2014}
    )


def test_is_scrapeable_team_rejects_placeholder():
    from scripts.drain_queue import _is_scrapeable_team

    assert not _is_scrapeable_team(
        {"team_name": "unknown_123", "provider_team_id": "123", "age_group": "u12", "birth_year": 2014}
    )


def test_is_scrapeable_team_rejects_u8_and_u9_any_case():
    """age_group is stored lowercase but the SQL compares upper(trim(...))."""
    from scripts.drain_queue import _is_scrapeable_team

    for ag in ("u8", "U8", " u-9 ", "U-8", "u9"):
        assert not _is_scrapeable_team(
            {"team_name": "T", "provider_team_id": "1", "age_group": ag, "birth_year": 2014}
        ), ag


def test_is_scrapeable_team_rejects_out_of_range_birth_year():
    import datetime as _dt

    from scripts.drain_queue import _excluded_birth_years, _is_scrapeable_team

    for by in _excluded_birth_years(_dt.date.today()):
        assert not _is_scrapeable_team(
            {"team_name": "T", "provider_team_id": "1", "age_group": "u12", "birth_year": by}
        ), by


def test_is_scrapeable_team_tolerates_null_age_and_birth_year():
    """A None age_group must not raise — .get(k, "") only defaults a MISSING key."""
    from scripts.drain_queue import _is_scrapeable_team

    assert _is_scrapeable_team({"team_name": "T", "provider_team_id": "1", "age_group": None, "birth_year": None})
