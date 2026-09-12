import math

import pytest

from src.tournaments.seeding_optimizer import (
    AssignmentConstraints,
    DivisionSpec,
    FlightSpec,
    MatchupCost,
    SeedableTeam,
    build_seedable_teams,
    normalize_tournament_age_group,
    optimize_division_assignments,
    optimize_tournament_format,
    projected_matchup_cost,
)


def _team(index: int, power_score: float, rank_in_cohort: float) -> SeedableTeam:
    return SeedableTeam(
        team_id=f"team-{index}",
        team_name=f"Team {index}",
        age_group="u13",
        gender="Male",
        power_score=power_score,
        rank_in_cohort=rank_in_cohort,
        state_code="AZ",
    )


def test_projected_matchup_cost_increases_with_strength_gap():
    favorite = _team(1, 0.82, 3)
    close_opponent = _team(2, 0.80, 5)
    distant_opponent = _team(3, 0.48, 41)

    close_cost = projected_matchup_cost(favorite, close_opponent)
    distant_cost = projected_matchup_cost(favorite, distant_opponent)

    assert distant_cost.projected_margin > close_cost.projected_margin
    assert distant_cost.blowout_3plus_probability > close_cost.blowout_3plus_probability
    assert distant_cost.total_cost > close_cost.total_cost


def test_optimize_tournament_format_assigns_divisions_and_pools():
    teams = [
        _team(1, 0.95, 1),
        _team(2, 0.92, 2),
        _team(3, 0.89, 3),
        _team(4, 0.86, 4),
        _team(5, 0.72, 11),
        _team(6, 0.69, 12),
        _team(7, 0.66, 13),
        _team(8, 0.63, 14),
    ]
    divisions = [
        DivisionSpec(name="Gold", team_count=4, pool_sizes=(2, 2), advancement="pool_winners_to_final"),
        DivisionSpec(name="Silver", team_count=4, pool_sizes=(2, 2), advancement="pool_winners_to_final"),
    ]

    result = optimize_tournament_format(teams, divisions)

    assert len(result.divisions) == 2
    assert result.total_cost > 0.0

    gold = result.divisions[0]
    silver = result.divisions[1]

    assert {team.team_id for team in gold.teams} == {"team-1", "team-2", "team-3", "team-4"}
    assert {team.team_id for team in silver.teams} == {"team-5", "team-6", "team-7", "team-8"}
    assert gold.pool_sizes == (2, 2)
    assert silver.pool_sizes == (2, 2)
    assert len(gold.pools) == 2
    assert len(silver.pools) == 2
    assert sum(len(pool.teams) for pool in gold.pools) == 4
    assert sum(len(pool.teams) for pool in silver.pools) == 4
    assert gold.advancement == "pool_winners_to_final"


def test_optimize_tournament_format_validates_pool_sizes():
    teams = [_team(1, 0.70, 10), _team(2, 0.68, 11), _team(3, 0.66, 12), _team(4, 0.64, 13)]
    divisions = [DivisionSpec(name="Gold", team_count=4, pool_sizes=(3,), advancement="final_only")]

    try:
        optimize_tournament_format(teams, divisions)
    except ValueError as exc:
        assert "pool sizes sum" in str(exc)
    else:
        raise AssertionError("Expected optimize_tournament_format to reject mismatched pool sizes")


def test_optimize_tournament_format_uses_injected_matchup_cost_function():
    teams = [
        _team(1, 0.95, 1),
        _team(2, 0.90, 2),
        _team(3, 0.85, 3),
        _team(4, 0.80, 4),
    ]
    divisions = [DivisionSpec(name="Gold", team_count=2), DivisionSpec(name="Silver", team_count=2)]

    preferred_pairs = {frozenset({"team-1", "team-4"}), frozenset({"team-2", "team-3"})}

    def custom_cost(team_a: SeedableTeam, team_b: SeedableTeam) -> MatchupCost:
        is_preferred = frozenset({team_a.team_id, team_b.team_id}) in preferred_pairs
        return MatchupCost(
            projected_margin=0.4 if is_preferred else 4.2,
            competitive_probability=0.9 if is_preferred else 0.1,
            blowout_3plus_probability=0.05 if is_preferred else 0.95,
            blowout_5plus_probability=0.01 if is_preferred else 0.80,
            total_cost=0.5 if is_preferred else 12.0,
        )

    result = optimize_tournament_format(
        teams,
        divisions,
        matchup_cost_fn=custom_cost,
        matchup_proxy="custom_predictor_v1",
    )

    division_team_sets = {frozenset(team.team_id for team in division.teams) for division in result.divisions}

    assert division_team_sets == preferred_pairs
    assert result.matchup_proxy == "custom_predictor_v1"


@pytest.mark.parametrize("invalid_count", [0, -1, 1.5, True, "2"])
def test_optimize_division_assignments_rejects_invalid_core_capacities(invalid_count):
    teams = [_team(1, 0.7, 1), _team(2, 0.6, 2)]

    with pytest.raises(ValueError, match="positive integer"):
        optimize_division_assignments(teams, [FlightSpec("Gold", invalid_count), FlightSpec("Silver", 2)])


def test_optimize_tournament_format_rejects_duplicate_entrant_ids():
    duplicate = _team(1, 0.7, 1)

    with pytest.raises(ValueError, match="entrant IDs must be unique"):
        optimize_tournament_format([duplicate, duplicate], [DivisionSpec("Gold", 2)])


@pytest.mark.parametrize("invalid_score", [-0.01, 1.01, math.nan, math.inf, -math.inf, None, "unknown", True])
def test_optimize_tournament_format_rejects_invalid_power_scores(invalid_score):
    invalid_team = SeedableTeam("invalid", "Invalid", "u13", "Male", invalid_score)

    with pytest.raises(ValueError, match="finite power_score between 0 and 1"):
        optimize_tournament_format([invalid_team], [DivisionSpec("Gold", 1)])


@pytest.mark.parametrize("invalid_id", ["", "  ", None, 42])
def test_optimize_tournament_format_rejects_invalid_entrant_ids(invalid_id):
    invalid_team = SeedableTeam(invalid_id, "Invalid", "u13", "Male", 0.5)

    with pytest.raises(ValueError, match="non-empty"):
        optimize_tournament_format([invalid_team], [DivisionSpec("Gold", 1)])


def test_optimize_tournament_format_rejects_duplicate_and_empty_division_names():
    teams = [_team(1, 0.7, 1), _team(2, 0.6, 2)]

    with pytest.raises(ValueError, match="Flight names must be unique"):
        optimize_tournament_format(teams, [DivisionSpec("Gold", 1), DivisionSpec("Gold", 1)])
    with pytest.raises(ValueError, match="non-empty name"):
        optimize_tournament_format(teams, [DivisionSpec("", 1), DivisionSpec("Silver", 1)])


def test_optimize_tournament_format_preserves_each_entrant_once_across_uneven_pools():
    teams = [_team(index, 0.9 - index * 0.03, index) for index in range(1, 8)]

    result = optimize_tournament_format(
        teams,
        [DivisionSpec("Gold", 7, pool_sizes=(4, 3))],
    )

    division = result.divisions[0]
    assert [len(pool.teams) for pool in division.pools] == [4, 3]
    assert sorted(team.team_id for pool in division.pools for team in pool.teams) == sorted(
        team.team_id for team in teams
    )


def test_distinct_registrations_can_share_external_canonical_identity():
    teams = [
        SeedableTeam("registration-a", "Alpha First Entry", "u13", "Male", 0.7),
        SeedableTeam("registration-b", "Alpha Second Entry", "u13", "Male", 0.7),
    ]

    result = optimize_tournament_format(teams, [DivisionSpec("Gold", 2)])

    assert {team.team_id for team in result.divisions[0].teams} == {"registration-a", "registration-b"}


def test_build_seedable_teams_rejects_missing_strength_instead_of_dropping_team():
    with pytest.raises(ValueError, match="No power_score found"):
        build_seedable_teams(
            [
                {
                    "team_id": "team-1",
                    "team_name": "Team 1",
                    "age_group": "u13",
                    "gender": "Male",
                    "power_score": None,
                }
            ]
        )


def test_combined_tournament_cohort_is_preserved_without_u18_fold():
    assert normalize_tournament_age_group("U10/U11 Girls") == "u10/u11"
    assert normalize_tournament_age_group("U17/U18 Boys") == "u17/u18"


def test_optimizer_separates_same_club_and_same_coach_in_early_pools():
    teams = [
        SeedableTeam("a", "A", "u14", "Male", 0.90, club_name="Club X", coach_names=("Coach One",)),
        SeedableTeam("b", "B", "u14", "Male", 0.85, club_name="Club X", coach_names=("Coach Two",)),
        SeedableTeam("c", "C", "u14", "Male", 0.80, club_name="Club Y", coach_names=("Coach One",)),
        SeedableTeam("d", "D", "u14", "Male", 0.75, club_name="Club Z", coach_names=("Coach Three",)),
    ]

    result = optimize_tournament_format(
        teams,
        [DivisionSpec("Gold", 4, pool_sizes=(2, 2))],
        constraints=AssignmentConstraints(avoid_same_club_early=True, avoid_same_coach_early=True),
    )

    for pool in result.divisions[0].pools:
        assert len({team.club_name for team in pool.teams}) == len(pool.teams)
        coach_sets = [set(team.coach_names) for team in pool.teams]
        assert not coach_sets[0] & coach_sets[1]


def test_optimizer_moves_teams_between_divisions_to_make_pool_constraints_feasible():
    teams = [
        SeedableTeam("x1", "X1", "u14", "Male", 0.95, club_name="Club X"),
        SeedableTeam("x2", "X2", "u14", "Male", 0.94, club_name="Club X"),
        SeedableTeam("x3", "X3", "u14", "Male", 0.93, club_name="Club X"),
        SeedableTeam("a", "A", "u14", "Male", 0.92, club_name="Club A"),
        SeedableTeam("b", "B", "u14", "Male", 0.50, club_name="Club B"),
        SeedableTeam("c", "C", "u14", "Male", 0.49, club_name="Club C"),
        SeedableTeam("d", "D", "u14", "Male", 0.48, club_name="Club D"),
        SeedableTeam("e", "E", "u14", "Male", 0.47, club_name="Club E"),
    ]

    result = optimize_tournament_format(
        teams,
        [
            DivisionSpec("Gold", 4, pool_sizes=(2, 2)),
            DivisionSpec("Silver", 4, pool_sizes=(2, 2)),
        ],
        constraints=AssignmentConstraints(avoid_same_club_early=True),
    )

    for division in result.divisions:
        assert sum(team.club_name == "Club X" for team in division.teams) <= 2
        for pool in division.pools:
            assert len({team.club_name for team in pool.teams}) == len(pool.teams)


def test_optimizer_enforces_prior_rematch_constraint():
    teams = [
        SeedableTeam("a", "A", "u14", "Male", 0.90, canonical_team_id="ca", prior_opponent_ids=frozenset({"cb"})),
        SeedableTeam("b", "B", "u14", "Male", 0.85, canonical_team_id="cb"),
        SeedableTeam("c", "C", "u14", "Male", 0.80, canonical_team_id="cc"),
        SeedableTeam("d", "D", "u14", "Male", 0.75, canonical_team_id="cd"),
    ]

    result = optimize_tournament_format(
        teams,
        [DivisionSpec("Gold", 4, pool_sizes=(2, 2))],
        constraints=AssignmentConstraints(avoid_prior_rematches=True),
    )

    pool_pairs = [{team.canonical_team_id for team in pool.teams} for pool in result.divisions[0].pools]
    assert {"ca", "cb"} not in pool_pairs


def test_optimizer_fails_when_hard_constraint_is_impossible():
    teams = [
        SeedableTeam("a", "A", "u14", "Male", 0.9, club_name="Club X"),
        SeedableTeam("b", "B", "u14", "Male", 0.8, club_name="Club X"),
    ]

    with pytest.raises(ValueError, match="same_club:a:b"):
        optimize_tournament_format(
            teams,
            [DivisionSpec("Gold", 2, pool_sizes=(2,))],
            constraints=AssignmentConstraints(avoid_same_club_early=True),
        )


@pytest.mark.parametrize("invalid_id", [None, "", "  ", 42])
def test_build_seedable_teams_rejects_invalid_entrant_ids(invalid_id):
    with pytest.raises(ValueError, match="non-empty string team_id"):
        build_seedable_teams(
            [
                {
                    "team_id": invalid_id,
                    "team_name": "Team 1",
                    "age_group": "u13",
                    "gender": "Male",
                    "power_score": 0.5,
                }
            ]
        )
