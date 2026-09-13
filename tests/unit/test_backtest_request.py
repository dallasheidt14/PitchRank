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
            "name": "group-1",
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
    assert {entrant["actual_division_key"] for entrant in request["entrants"]} == {"group-1"}
    assert {entrant["actual_pool_key"] for entrant in request["entrants"]} == {"group-1:pool-a"}
    assert request["actual_games_override"][0]["home_team_master_id"] == "canonical-a"


def test_build_request_can_select_one_reviewed_cohort():
    assert len(
        build_cohort_backtest_requests(
            _snapshot(),
            event_links=_links(),
            cohort_filter={("u14", "Male")},
        )
    ) == 1
    assert build_cohort_backtest_requests(
        _snapshot(),
        event_links=_links(),
        cohort_filter={("u15", "Male")},
    ) == ()


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


def test_build_request_uses_group_id_when_division_label_is_blank():
    snapshot = _snapshot()
    division = replace(snapshot.roster.divisions[0], division_label="")
    snapshot = replace(
        snapshot,
        roster=replace(snapshot.roster, divisions=(division,)),
        reviews=(replace(snapshot.reviews[0], structure_hash=structure_hash(division)),),
    )

    request = build_cohort_backtest_requests(snapshot, event_links=_links())[0]

    assert request["divisions"][0]["name"] == "group-1"
    assert request["divisions"][0]["actual_division_name"] == ""


def test_build_request_keeps_excluded_fixture_for_format_but_not_results():
    snapshot = _snapshot()
    fixture = replace(
        snapshot.roster.divisions[0].fixtures[0],
        result_status="forfeit",
    )
    division = replace(snapshot.roster.divisions[0], fixtures=(fixture,))
    snapshot = replace(
        snapshot,
        roster=replace(snapshot.roster, divisions=(division,)),
        reviews=(replace(snapshot.reviews[0], structure_hash=structure_hash(division)),),
    )

    request = build_cohort_backtest_requests(snapshot, event_links=_links())[0]

    assert request["divisions"][0]["captured_fixture_count"] == 1
    assert request["actual_games_override"] == []


def test_build_request_uses_source_entry_key_when_registration_id_is_missing():
    snapshot = _snapshot()
    source_key = "pool:group-1:pool-a:1"
    teams = (
        replace(snapshot.roster.teams[0], registration_id="", source_entry_key=source_key),
        snapshot.roster.teams[1],
    )
    pool = replace(
        snapshot.roster.divisions[0].pools[0],
        members=(
            replace(snapshot.roster.divisions[0].pools[0].members[0], registration_id=""),
            snapshot.roster.divisions[0].pools[0].members[1],
        ),
    )
    fixture = replace(
        snapshot.roster.divisions[0].fixtures[0],
        home_registration_id="",
        home_label="Alpha",
    )
    division = replace(snapshot.roster.divisions[0], pools=(pool,), fixtures=(fixture,))
    snapshot = replace(
        snapshot,
        roster=replace(snapshot.roster, teams=teams, divisions=(division,)),
        reviews=(replace(snapshot.reviews[0], structure_hash=structure_hash(division)),),
    )
    links = replace(
        _links(),
        links=(replace(_links().links[0], registration_id=source_key), _links().links[1]),
    )

    request = build_cohort_backtest_requests(snapshot, event_links=links)[0]

    alpha = next(item for item in request["entrants"] if item["event_team_name"] == "Alpha")
    assert alpha["registration_id"] == ""
    assert alpha["source_entry_key"] == source_key
    assert request["actual_games_override"][0]["home_team_master_id"] == "canonical-a"


def test_build_request_canonicalizes_saved_links_after_team_merge():
    request = build_cohort_backtest_requests(
        _snapshot(),
        event_links=_links(),
        resolve_team_id=lambda team_id: "survivor-a" if team_id == "canonical-a" else team_id,
    )[0]

    alpha = next(item for item in request["entrants"] if item["event_team_name"] == "Alpha")
    assert alpha["canonical_team_id"] == "survivor-a"
    assert alpha["ranking_source_team_id"] == "survivor-a"
    assert request["actual_games_override"][0]["home_team_master_id"] == "survivor-a"


def test_build_request_infers_an_unambiguous_replay_format():
    snapshot = _snapshot()
    snapshot = replace(snapshot, reviews=(replace(snapshot.reviews[0], format_code=""),))

    request = build_cohort_backtest_requests(snapshot, event_links=_links())[0]

    assert request["divisions"][0]["advancement"] == "ROUND_ROBIN"


def test_build_request_requires_normalized_event_start_date():
    snapshot = _snapshot()

    with pytest.raises(BacktestRequestError, match="normalized event start date"):
        build_cohort_backtest_requests(
            replace(snapshot, roster=replace(snapshot.roster, event_start_date=None)),
            event_links=_links(),
        )


def test_build_request_requires_exact_duplicate_mapping_acknowledgement():
    snapshot = _snapshot()
    colliding_links = _links(second_team_id="canonical-a")

    with pytest.raises(BacktestRequestError, match="without an acknowledgement"):
        build_cohort_backtest_requests(snapshot, event_links=colliding_links)
    with pytest.raises(BacktestRequestError, match="without an acknowledgement"):
        build_cohort_backtest_requests(
            snapshot,
            event_links=colliding_links,
            cohort_filter={("u14", "Male")},
        )

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
    requests = build_cohort_backtest_requests(
        snapshot,
        event_links=links,
        cohort_filter={("u14", "Male")},
    )
    assert len(requests) == 1
    assert requests[0]["age_group"] == "u14"


def test_build_request_rejects_repeated_registration_within_cohort():
    snapshot = _snapshot()
    second_division = replace(
        snapshot.roster.divisions[0],
        group_id="group-2",
        division_label="Silver",
        pools=(
            Pool(
                "pool-b",
                "Bracket B",
                (PoolMember("reg-a", "Alpha", 1), PoolMember("reg-c", "Charlie", 2)),
            ),
        ),
        fixtures=(
            replace(
                snapshot.roster.divisions[0].fixtures[0],
                match_number="2",
                home_registration_id="reg-a",
                away_registration_id="reg-c",
            ),
        ),
    )
    roster = replace(
        snapshot.roster,
        teams=snapshot.roster.teams
        + (
            EventRosterTeam(2, "group-2", "Silver", "u14", "Male", "Alpha", "reg-a", "pid-a", "u14"),
            EventRosterTeam(3, "group-2", "Silver", "u14", "Male", "Charlie", "reg-c", "pid-c", "u14"),
        ),
        divisions=snapshot.roster.divisions + (second_division,),
        divisions_found=2,
        divisions_walked=2,
    )
    snapshot = replace(
        snapshot,
        roster=roster,
        resolved=snapshot.resolved
        + (
            ResolvedTeam(2, "gotsport_id", "canonical-a", "pid-a"),
            ResolvedTeam(3, "gotsport_id", "canonical-c", "pid-c"),
        ),
        reviews=snapshot.reviews
        + (
            DivisionReview(
                "group-2",
                structure_hash(second_division),
                checked=True,
                format_code="ROUND_ROBIN",
            ),
        ),
    )
    links = replace(
        _links(),
        links=_links().links
        + (
            TeamLink(
                "reg-c",
                "Charlie",
                "canonical-c",
                "operator",
                "2026-09-11T00:00:00+00:00",
            ),
        ),
    )

    with pytest.raises(BacktestRequestError, match="appears more than once"):
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


def test_build_request_rejects_unconfirmed_and_keeps_reviewed_not_found_entrant():
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
    request = build_cohort_backtest_requests(_snapshot(), event_links=not_found)[0]
    bravo = next(item for item in request["entrants"] if item["registration_id"] == "reg-b")
    assert bravo["canonical_team_id"] == "not-found:51783:reg-b"
    assert bravo["ranking_source_team_id"] == ""
    assert bravo["rating_fallback"] == "division_then_cohort_median_surrogate"


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
