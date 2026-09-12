from dataclasses import replace

import pytest

from scripts.backtest_reviewed_intake import _embedded_links
from src.tournaments.backtest_intake_state import BacktestSnapshot, DivisionReview, structure_hash
from src.tournaments.backtest_link_store import CollisionAcknowledgement, EventLinks, TeamLink
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


def _links(*, second_team_id: str = "canonical-b", second_method: str = "gotsport_id") -> EventLinks:
    return EventLinks(
        event_id="51783",
        links=(
            TeamLink("reg-a", "Alpha", "canonical-a", "gotsport_id", "2026-09-11T00:00:00+00:00"),
            TeamLink("reg-b", "Bravo", second_team_id, second_method, "2026-09-11T00:00:00+00:00"),
        ),
    )


def test_build_request_preserves_exact_pool_membership_and_source_results():
    request = build_cohort_backtest_requests(_snapshot(), event_links=_links())[0]

    assert request["age_group"] == "u14"
    assert request["assignment_policy"] == "competitive_balance_only"
    assert "constraints" not in request
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


def test_build_request_deduplicates_repeated_identified_fixture_rows():
    snapshot = _snapshot()
    duplicate = replace(snapshot.roster.divisions[0].fixtures[0])
    division = replace(
        snapshot.roster.divisions[0],
        fixtures=(snapshot.roster.divisions[0].fixtures[0], duplicate),
    )
    snapshot = replace(
        snapshot,
        roster=replace(snapshot.roster, divisions=(division,)),
        reviews=(replace(snapshot.reviews[0], structure_hash=structure_hash(division)),),
    )

    request = build_cohort_backtest_requests(snapshot, event_links=_links())[0]

    assert request["divisions"][0]["captured_fixture_count"] == 1
    assert len(request["actual_games_override"]) == 1


def test_build_request_blocks_unreviewed_format():
    snapshot = _snapshot()
    snapshot = replace(snapshot, reviews=(replace(snapshot.reviews[0], format_code=""),))

    with pytest.raises(BacktestRequestError, match="verified replay format"):
        build_cohort_backtest_requests(snapshot, event_links=_links())


def test_build_request_requires_exact_duplicate_mapping_acknowledgement():
    snapshot = _snapshot()
    colliding_links = _links(second_team_id="canonical-a")

    with pytest.raises(BacktestRequestError, match="without an acknowledgement"):
        build_cohort_backtest_requests(snapshot, event_links=colliding_links)

    acknowledged_links = replace(
        colliding_links,
        collision_acknowledgements=(
            CollisionAcknowledgement(
                "canonical-a",
                ("reg-a", "reg-b"),
                "Two registrations intentionally represent one squad",
                "2026-09-11T00:00:00+00:00",
            ),
        ),
    )
    request = build_cohort_backtest_requests(
        snapshot,
        event_links=acknowledged_links,
    )[0]
    assert len(request["entrants"]) == 2


def test_build_request_validates_duplicate_mapping_across_cohorts():
    snapshot = _snapshot()
    second_division = replace(
        snapshot.roster.divisions[0],
        group_id="group-2",
        division_label="Silver",
        age_group="u15",
        pools=(
            Pool(
                "pool-b",
                "Bracket B",
                (PoolMember("reg-c", "Charlie", 1), PoolMember("reg-d", "Delta", 2)),
            ),
        ),
        fixtures=(
            replace(
                snapshot.roster.divisions[0].fixtures[0],
                match_number="2",
                home_registration_id="reg-c",
                away_registration_id="reg-d",
            ),
        ),
    )
    roster = replace(
        snapshot.roster,
        teams=snapshot.roster.teams
        + (
            EventRosterTeam(2, "group-2", "Silver", "u15", "Male", "Charlie", "reg-c", "pid-c", "u15"),
            EventRosterTeam(3, "group-2", "Silver", "u15", "Male", "Delta", "reg-d", "pid-d", "u15"),
        ),
        divisions=snapshot.roster.divisions + (second_division,),
        divisions_found=2,
        divisions_walked=2,
    )
    second_review = DivisionReview(
        "group-2",
        structure_hash(second_division),
        checked=True,
        format_code="ROUND_ROBIN",
    )
    snapshot = replace(
        snapshot,
        roster=roster,
        resolved=snapshot.resolved
        + (
            ResolvedTeam(2, "gotsport_id", "canonical-a", "pid-c"),
            ResolvedTeam(3, "gotsport_id", "canonical-d", "pid-d"),
        ),
        reviews=snapshot.reviews + (second_review,),
    )
    links = replace(
        _links(),
        links=_links().links
        + (
            TeamLink("reg-c", "Charlie", "canonical-a", "operator", "2026-09-11T00:00:00+00:00"),
            TeamLink("reg-d", "Delta", "canonical-d", "operator", "2026-09-11T00:00:00+00:00"),
        ),
    )

    with pytest.raises(BacktestRequestError, match="without an acknowledgement"):
        build_cohort_backtest_requests(snapshot, event_links=links)


def test_build_request_uses_operator_link_instead_of_raw_resolution():
    request = build_cohort_backtest_requests(
        _snapshot(),
        event_links=_links(second_team_id="operator-choice", second_method="operator"),
    )[0]

    bravo = next(item for item in request["entrants"] if item["registration_id"] == "reg-b")
    assert bravo["canonical_team_id"] == "operator-choice"
    assert request["actual_games_override"][0]["away_team_master_id"] == "operator-choice"


def test_downloaded_intake_restores_embedded_link_decisions():
    links = _embedded_links(
        {
            "links": {
                "event_id": "51783",
                "links": [
                    {
                        "registration_id": "reg-a",
                        "event_team_name": "Alpha",
                        "team_id_master": "canonical-a",
                        "matched_by": "operator",
                        "linked_at": "2026-09-11T00:00:00+00:00",
                    }
                ],
                "removed_registration_ids": ["reg-b"],
                "not_found_registration_ids": [],
                "collision_acknowledgements": [],
            }
        },
        event_id="51783",
    )

    assert links.links[0].team_id_master == "canonical-a"
    assert links.removed_registration_ids == ("reg-b",)


def test_build_request_rejects_unconfirmed_and_not_found_decisions():
    with pytest.raises(BacktestRequestError, match="unconfirmed exact_name"):
        build_cohort_backtest_requests(
            _snapshot(),
            event_links=_links(second_method="exact_name"),
        )

    not_found = replace(
        _links(),
        links=(_links().links[0],),
        not_found_registration_ids=("reg-b",),
    )
    with pytest.raises(BacktestRequestError, match="marked not found"):
        build_cohort_backtest_requests(_snapshot(), event_links=not_found)


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

    request = build_cohort_backtest_requests(snapshot, event_links=_links())[0]
    assert request["age_group"] == "u10/u11"
    assert {entrant["event_age_group"] for entrant in request["entrants"]} == {"u10/u11"}
