from src.tournaments.seeding_optimizer import (
    DivisionSpec,
    MatchupCost,
    SeedableTeam,
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
