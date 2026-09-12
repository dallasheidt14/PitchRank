from dataclasses import replace

import pytest

from src.tournaments.backtest_intake_state import BacktestSnapshot, DivisionReview, structure_hash
from src.tournaments.backtest_request import BacktestRequestError, build_cohort_backtest_requests
from src.tournaments.gotsport_event_roster import EventRoster, EventRosterTeam
from src.tournaments.gotsport_event_structure import Fixture, Pool, PoolMember, ScrapedDivision
from src.tournaments.roster_resolver import ResolvedTeam


def _snapshot() -> BacktestSnapshot:
    teams = (
        EventRosterTeam(0, "group-1", "Gold", "u14", "Male", "Alpha", "reg-a", "pid-a", "u14"),
        EventRosterTeam(1, "group-1", "Gold", "u14", "Male", "Bravo", "reg-b", "pid-b", "u14"),
    )
    division = ScrapedDivision(
        group_id="group-1",
        division_label="Gold",
        pools=(
            Pool(
                "pool-a",
                "Bracket A",
                (PoolMember("reg-a", "Alpha", 1), PoolMember("reg-b", "Bravo", 2)),
            ),
        ),
        fixtures=(
            Fixture(
                "1",
                "",
                "pool",
                "reg-a",
                "reg-b",
                2,
                1,
                "2025-05-10 10:00",
                "Field 1",
                result_status="played",
                date_label="2025-05-10",
                source_url="https://example.test/match/1",
            ),
        ),
        pools_readable=True,
        fixtures_readable=True,
        warnings=(),
        age_group="u14",
        gender="Male",
        published_age_group="u14",
        source_url="https://example.test/group-1",
    )
    roster = EventRoster(
        "51783",
        teams,
        (),
        divisions_found=1,
        divisions_walked=1,
        divisions=(division,),
        completed_event=True,
        event_name="Spring Cup",
        event_start_date="2025-05-10",
    )
    resolved = (
        ResolvedTeam(0, "gotsport_id", "canonical-a", "pid-a"),
        ResolvedTeam(1, "gotsport_id", "canonical-b", "pid-b"),
    )
    review = DivisionReview(
        "group-1",
        structure_hash(division),
        checked=True,
        format_code="ROUND_ROBIN",
    )
    return BacktestSnapshot(roster, resolved, "generation-1", "2026-09-11T00:00:00+00:00", reviews=(review,))


def test_build_request_preserves_exact_pool_membership_and_source_results():
    request = build_cohort_backtest_requests(_snapshot())[0]

    assert request["age_group"] == "u14"
    assert request["divisions"] == [
        {
            "name": "Gold",
            "actual_division_name": "Gold",
            "group_id": "group-1",
            "team_count": 2,
            "pool_sizes": [2],
            "advancement": "ROUND_ROBIN",
            "playoff_format": "none",
            "captured_fixture_count": 1,
        }
    ]
    assert {entrant["actual_pool_name"] for entrant in request["entrants"]} == {"Bracket A"}
    assert request["actual_games_override"][0]["home_team_master_id"] == "canonical-a"


def test_build_request_blocks_unreviewed_format():
    snapshot = _snapshot()
    snapshot = replace(snapshot, reviews=(replace(snapshot.reviews[0], format_code=""),))

    with pytest.raises(BacktestRequestError, match="verified replay format"):
        build_cohort_backtest_requests(snapshot)


def test_build_request_requires_exact_duplicate_mapping_acknowledgement():
    snapshot = _snapshot()
    snapshot = replace(
        snapshot,
        resolved=(
            snapshot.resolved[0],
            replace(snapshot.resolved[1], team_id_master="canonical-a"),
        ),
    )

    with pytest.raises(BacktestRequestError, match="without an acknowledgement"):
        build_cohort_backtest_requests(snapshot)

    request = build_cohort_backtest_requests(
        snapshot,
        collision_acknowledgements={"canonical-a": frozenset({"reg-a", "reg-b"})},
    )[0]
    assert len(request["entrants"]) == 2


def test_build_request_preserves_combined_tournament_cohort():
    snapshot = _snapshot()
    combined_division = replace(
        snapshot.roster.divisions[0],
        age_group="u10/u11",
        published_age_group="u10/u11",
    )
    combined_teams = tuple(
        replace(team, published_age_group="u10/u11") for team in snapshot.roster.teams
    )
    snapshot = replace(
        snapshot,
        roster=replace(snapshot.roster, teams=combined_teams, divisions=(combined_division,)),
        reviews=(
            replace(
                snapshot.reviews[0],
                structure_hash=structure_hash(combined_division),
            ),
        ),
    )

    request = build_cohort_backtest_requests(snapshot)[0]
    assert request["age_group"] == "u10/u11"
    assert {entrant["event_age_group"] for entrant in request["entrants"]} == {"u10/u11"}
