"""Unit tests for ``src.tournaments.seeding_enqueue``.

Pins what gets queued and what does not. The RPC is injected, so nothing here
reaches Supabase, and the dry-run path is asserted to make no call at all
rather than merely to report zero.
"""

from __future__ import annotations

from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_enqueue import (
    SEEDING_REQUEST_PRIORITY,
    enqueue_resolved_teams,
)

PASTE = (
    "Male U14\nClub\tTeam\tState\n"
    "Barcelona Soccer Club\tBarcelona SC 13B Aztecas\tTX\n"
    "Tyler FC\tTyler FC 15B*\tTX\n"
    "Del Rio Furia Soccer League\tDYNAMO 13\tTX"
)


def _rows():
    return parse_roster(PASTE).rows


def _resolved():
    return (
        ResolvedTeam(source_index=0, status="gotsport_id", team_id_master="master-1", provider_team_id="534748"),
        ResolvedTeam(source_index=1, status="unresolved"),
        ResolvedTeam(source_index=2, status="exact_name", team_id_master="master-3"),
    )


def _lookup(team_id_master):
    """Stands in for the database backfill of a GotSport id."""
    return {"master-2": "222", "master-3": "333"}.get(team_id_master)


class _RecordingRpc:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, payload):
        self.calls.append(payload)


def test_only_resolved_teams_are_queued():
    rpc = _RecordingRpc()

    result = enqueue_resolved_teams(_rows(), _resolved(), {}, enqueue=rpc, lookup_provider_team_id=_lookup)

    assert [call["p_team_id_master"] for call in rpc.calls] == ["master-1", "master-3"]
    assert result.queued == 2
    assert result.skipped == 1


def test_an_override_makes_its_row_queueable():
    rpc = _RecordingRpc()
    overrides = {1: {"team_id_master": "master-2", "team_name": "Tyler FC 2015"}}

    result = enqueue_resolved_teams(_rows(), _resolved(), overrides, enqueue=rpc, lookup_provider_team_id=_lookup)

    assert sorted(call["p_team_id_master"] for call in rpc.calls) == ["master-1", "master-2", "master-3"]
    assert result.queued == 3
    assert result.skipped == 0


def test_the_same_team_is_only_queued_once():
    rpc = _RecordingRpc()
    duplicated = tuple(
        ResolvedTeam(source_index=index, status="gotsport_id", team_id_master="master-1", provider_team_id="534748")
        for index in range(3)
    )

    result = enqueue_resolved_teams(_rows(), duplicated, {}, enqueue=rpc)

    assert len(rpc.calls) == 1
    assert result.queued == 1


def test_a_dry_run_makes_no_call_at_all():
    rpc = _RecordingRpc()

    result = enqueue_resolved_teams(
        _rows(), _resolved(), {}, enqueue=rpc, lookup_provider_team_id=_lookup, dry_run=True
    )

    assert rpc.calls == []
    assert result.queued == 0
    assert result.would_queue == 2


def test_queued_rows_carry_the_roster_team_name_and_provider_id():
    rpc = _RecordingRpc()

    enqueue_resolved_teams(_rows(), _resolved(), {}, enqueue=rpc, lookup_provider_team_id=_lookup)

    first = rpc.calls[0]
    assert first["p_team_name"] == "Barcelona SC 13B Aztecas"
    assert first["p_provider_team_id"] == "534748"
    assert first["p_priority"] == SEEDING_REQUEST_PRIORITY


def test_a_failing_call_is_counted_without_stopping_the_rest():
    def flaky(payload):
        if payload["p_team_id_master"] == "master-1":
            raise RuntimeError("boom")

    result = enqueue_resolved_teams(_rows(), _resolved(), {}, enqueue=flaky, lookup_provider_team_id=_lookup)

    assert result.queued == 1
    assert result.failed == 1
    assert "master-1" in result.failures[0]


# -------- provider ids ----------------------------------------------------


def test_a_team_without_a_provider_id_has_one_looked_up():
    """The drainer rejects a request with no provider_team_id, so never queue one.

    ``process_missing_games`` raises ``Missing required field: provider_team_id``,
    which turns a queued row into a guaranteed failure rather than a scrape.
    """
    rpc = _RecordingRpc()

    enqueue_resolved_teams(
        _rows(),
        _resolved(),
        {},
        enqueue=rpc,
        lookup_provider_team_id=lambda tid: "999" if tid == "master-3" else None,
    )

    by_team = {call["p_team_id_master"]: call for call in rpc.calls}
    assert by_team["master-1"]["p_provider_team_id"] == "534748"
    assert by_team["master-3"]["p_provider_team_id"] == "999"


def test_the_lookup_is_skipped_when_the_resolver_already_supplied_an_id():
    rpc = _RecordingRpc()
    asked: list[str] = []

    def lookup(team_id_master):
        asked.append(team_id_master)
        return "999"

    enqueue_resolved_teams(
        _rows(),
        (ResolvedTeam(source_index=0, status="gotsport_id", team_id_master="master-1", provider_team_id="534748"),),
        {},
        enqueue=rpc,
        lookup_provider_team_id=lookup,
    )

    assert asked == []


def test_a_team_with_no_provider_id_anywhere_is_not_queued():
    rpc = _RecordingRpc()

    result = enqueue_resolved_teams(
        _rows(),
        (ResolvedTeam(source_index=0, status="exact_name", team_id_master="master-1"),),
        {},
        enqueue=rpc,
        lookup_provider_team_id=lambda tid: None,
    )

    assert rpc.calls == []
    assert result.queued == 0
    assert result.skipped == 1
