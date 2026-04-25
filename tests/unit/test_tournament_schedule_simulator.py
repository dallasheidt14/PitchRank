from types import SimpleNamespace

from src.tournaments.schedule_simulator import infer_division_schedule_template, simulate_tournament_schedule
from src.tournaments.seeding_optimizer import DivisionSpec, MatchupCost, SeedableTeam, optimize_tournament_format


def _team(index: int, power_score: float, rank_in_cohort: float) -> SeedableTeam:
    return SeedableTeam(
        team_id=f"team-{index}",
        team_name=f"Team {index}",
        age_group="u14",
        gender="Male",
        power_score=power_score,
        rank_in_cohort=rank_in_cohort,
        state_code="AZ",
    )


def _prediction(team_a: SeedableTeam, team_b: SeedableTeam):
    if team_a.power_score > team_b.power_score:
        winner = "team_a"
        score_a = 2
        score_b = 1
    elif team_b.power_score > team_a.power_score:
        winner = "team_b"
        score_a = 1
        score_b = 2
    else:
        winner = "draw"
        score_a = 1
        score_b = 1

    return SimpleNamespace(
        predicted_winner=winner,
        expected_score={"teamA": score_a, "teamB": score_b},
    )


def _cost(team_a: SeedableTeam, team_b: SeedableTeam) -> MatchupCost:
    gap = abs(team_a.power_score - team_b.power_score)
    return MatchupCost(
        projected_margin=gap,
        competitive_probability=1.0 - min(1.0, gap),
        blowout_3plus_probability=0.0,
        blowout_5plus_probability=0.0,
        total_cost=gap,
    )


def test_infer_division_schedule_template_matches_known_formats():
    eight_team = infer_division_schedule_template(
        division_name="Super Elite",
        actual_division_name="BU14 Super Elite",
        pool_sizes=(4, 4),
        actual_game_count=13,
    )
    six_team = infer_division_schedule_template(
        division_name="Super Pro",
        actual_division_name="BU14 Super Pro",
        pool_sizes=(3, 3),
        actual_game_count=10,
    )

    assert eight_team.playoff_format == "pool_winners_final"
    assert six_team.playoff_format == "cross_semis_final_third"


def test_simulate_tournament_schedule_replays_two_pools_of_four_with_final():
    teams = [_team(index, 0.90 - index * 0.03, index) for index in range(1, 9)]
    result = optimize_tournament_format(
        teams,
        [DivisionSpec(name="Super Elite", team_count=8, pool_sizes=(4, 4))],
        matchup_cost_fn=_cost,
    )
    templates = {
        "Super Elite": infer_division_schedule_template(
            division_name="Super Elite",
            actual_division_name="BU14 Super Elite",
            pool_sizes=(4, 4),
            actual_game_count=13,
        )
    }

    simulation = simulate_tournament_schedule(result.divisions, templates, _prediction)

    assert simulation.match_count == 13
    assert len(simulation.divisions) == 1
    assert simulation.divisions[0].match_count == 13


def test_simulate_tournament_schedule_replays_two_pools_of_three_with_semis():
    teams = [_team(index, 0.90 - index * 0.04, index) for index in range(1, 7)]
    result = optimize_tournament_format(
        teams,
        [DivisionSpec(name="Super Pro", team_count=6, pool_sizes=(3, 3))],
        matchup_cost_fn=_cost,
    )
    templates = {
        "Super Pro": infer_division_schedule_template(
            division_name="Super Pro",
            actual_division_name="BU14 Super Pro",
            pool_sizes=(3, 3),
            actual_game_count=10,
        )
    }

    simulation = simulate_tournament_schedule(result.divisions, templates, _prediction)

    assert simulation.match_count == 10
    assert len(simulation.divisions) == 1
    assert simulation.divisions[0].match_count == 10
