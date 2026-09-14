from types import SimpleNamespace

import pytest

from src.tournaments.schedule_simulator import (
    DEFAULT_TIEBREAK_ORDER,
    STANDARD_SCORING_POLICY,
    TIGER_TOURNAMENTS_SCORING_POLICY,
    TIGER_TOURNAMENTS_TIEBREAK_ORDER,
    _empty_standings,
    _rank_pool_teams,
    _simulate_match,
    _update_pool_standings,
    captured_division_schedule_template,
    explicit_division_schedule_template,
    infer_division_schedule_template,
    simulate_tournament_schedule,
)
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


def test_explicit_template_uses_format_code_instead_of_guessing_from_count():
    template = explicit_division_schedule_template(
        division_name="Super Elite",
        actual_division_name="BU14 Super Elite",
        pool_sizes=(4, 4),
        format_code="F_ONLY",
        actual_game_count=13,
    )

    assert template.playoff_format == "pool_winners_final"
    assert template.inference_notes == ()


def test_explicit_template_rejects_missing_or_unsupported_format():
    with pytest.raises(ValueError, match="explicit supported format code"):
        explicit_division_schedule_template(
            division_name="Super Elite",
            pool_sizes=(4, 4),
            format_code=None,
            actual_game_count=13,
        )


def test_explicit_template_rejects_captured_game_count_mismatch():
    with pytest.raises(ValueError, match="captured division contains 14"):
        explicit_division_schedule_template(
            division_name="Super Elite",
            pool_sizes=(4, 4),
            format_code="F_ONLY",
            actual_game_count=14,
        )


@pytest.mark.parametrize(
    ("pool_sizes", "format_code", "message"),
    [
        ((1,), "F_ONLY", "at least two teams in its pool"),
        ((1, 3), "SF_F", "at least two teams in each pool"),
        ((3, 1), "SF_F_3P", "at least two teams in each pool"),
    ],
)
def test_explicit_template_rejects_undersized_playoff_qualifier_pools(
    pool_sizes,
    format_code,
    message,
):
    with pytest.raises(ValueError, match=message):
        explicit_division_schedule_template(
            division_name="Gold",
            pool_sizes=pool_sizes,
            format_code=format_code,
            actual_game_count=None,
        )


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


def test_tiger_tiebreak_uses_head_to_head_before_goal_differential():
    teams = [_team(1, 0.7, 1), _team(2, 0.8, 2), _team(3, 0.6, 3)]
    standings = _empty_standings(teams)
    standings["team-1"].update(points=6, gd=1, gd_capped=1, head_to_head={"team-2": 3})
    standings["team-2"].update(points=6, gd=8, gd_capped=5, head_to_head={"team-1": 0})
    standings["team-3"].update(points=0)

    ranked = _rank_pool_teams(
        teams,
        standings,
        TIGER_TOURNAMENTS_TIEBREAK_ORDER,
        division_name="U12 Gold",
        scoring_policy=TIGER_TOURNAMENTS_SCORING_POLICY,
    )

    assert [team.team_id for team in ranked[:2]] == ["team-1", "team-2"]


def test_tiger_tiebreak_skips_head_to_head_for_three_way_non_crossover_tie():
    teams = [_team(1, 0.7, 1), _team(2, 0.8, 2), _team(3, 0.6, 3)]
    standings = _empty_standings(teams)
    standings["team-1"].update(points=3, gd_capped=1, head_to_head={"team-2": 3})
    standings["team-2"].update(points=3, gd_capped=4, head_to_head={"team-3": 3})
    standings["team-3"].update(points=3, gd_capped=2, head_to_head={"team-1": 3})

    ranked = _rank_pool_teams(
        teams,
        standings,
        TIGER_TOURNAMENTS_TIEBREAK_ORDER,
        division_name="U12 Gold",
        scoring_policy=TIGER_TOURNAMENTS_SCORING_POLICY,
    )

    assert [team.team_id for team in ranked] == ["team-2", "team-3", "team-1"]


def test_tiger_tiebreak_uses_head_to_head_for_three_way_crossover_tie():
    teams = [_team(1, 0.7, 1), _team(2, 0.8, 2), _team(3, 0.6, 3)]
    standings = _empty_standings(teams)
    standings["team-1"].update(
        points=6,
        gd_capped=1,
        head_to_head={"team-2": 3, "team-3": 3},
    )
    standings["team-2"].update(
        points=6,
        gd_capped=4,
        head_to_head={"team-1": 0, "team-3": 3},
    )
    standings["team-3"].update(
        points=6,
        gd_capped=8,
        head_to_head={"team-1": 0, "team-2": 0},
    )

    ranked = _rank_pool_teams(
        teams,
        standings,
        TIGER_TOURNAMENTS_TIEBREAK_ORDER,
        division_name="opaque-group-id",
        scoring_policy=TIGER_TOURNAMENTS_SCORING_POLICY,
        three_team_head_to_head=True,
    )

    assert [team.team_id for team in ranked] == ["team-1", "team-2", "team-3"]


def test_calibrated_expected_margin_drives_the_standings_score():
    home = _team(1, 0.8, 1)
    away = _team(2, 0.4, 2)

    def calibrated_prediction(_home, _away):
        return SimpleNamespace(
            predicted_winner="team_a",
            expected_score={"teamA": 5, "teamB": 1},
            expected_margin=1.2,
            expected_absolute_goal_difference=1.8,
        )

    match = _simulate_match(
        division_name="Gold",
        stage="Pool",
        pool_name="A",
        home_team=home,
        away_team=away,
        predict_fn=calibrated_prediction,
    )
    standings = _empty_standings((home, away))
    _update_pool_standings(standings, match, home, away)

    assert (match.home_score, match.away_score) == (2, 1)
    assert match.expected_goal_differential == pytest.approx(1.8)
    assert standings[home.team_id]["gd"] == 1
    assert standings[away.team_id]["gd"] == -1


def test_predicted_draw_uses_zero_margin_for_score_and_projection():
    home = _team(1, 0.8, 1)
    away = _team(2, 0.4, 2)

    match = _simulate_match(
        division_name="Gold",
        stage="Pool",
        pool_name="A",
        home_team=home,
        away_team=away,
        predict_fn=lambda *_args: SimpleNamespace(
            predicted_winner="draw",
            expected_score={"teamA": 3, "teamB": 1},
            expected_margin=2.4,
            expected_absolute_goal_difference=1.4,
        ),
    )

    assert match.home_score == match.away_score == 2
    assert match.goal_differential == 0
    assert match.expected_goal_differential == pytest.approx(1.4)


def test_tiger_tiebreak_uses_capped_goal_metrics_then_fewest_goals_conceded():
    teams = [_team(1, 0.7, 1), _team(2, 0.8, 2)]
    standings = _empty_standings(teams)
    standings["team-1"].update(
        points=6,
        gd=11,
        gd_capped=8,
        gf=14,
        gf_capped=10,
        ga=3,
        head_to_head={"team-2": 1},
    )
    standings["team-2"].update(
        points=6,
        gd=9,
        gd_capped=8,
        gf=12,
        gf_capped=10,
        ga=2,
        head_to_head={"team-1": 1},
    )

    ranked = _rank_pool_teams(
        teams,
        standings,
        TIGER_TOURNAMENTS_TIEBREAK_ORDER,
        division_name="U12 Gold",
        scoring_policy=TIGER_TOURNAMENTS_SCORING_POLICY,
    )

    assert [team.team_id for team in ranked] == ["team-2", "team-1"]


def test_captured_graph_replays_cross_pool_games_and_actual_advancement_path():
    teams = [_team(index, 0.95 - index * 0.08, index) for index in range(1, 7)]
    result = optimize_tournament_format(
        teams,
        [DivisionSpec(name="Crossover", team_count=6, pool_sizes=(3, 3))],
        matchup_cost_fn=_cost,
    )
    fixtures = []
    for home_slot in range(3):
        for away_slot in range(3):
            fixtures.append(
                {
                    "stage": "Cross-pool",
                    "counts_for_standings": True,
                    "home": {"kind": "pool_slot", "pool_index": 0, "slot_index": home_slot},
                    "away": {"kind": "pool_slot", "pool_index": 1, "slot_index": away_slot},
                }
            )
    fixtures.extend(
        [
            {
                "stage": "Semi-Finals A",
                "home": {"kind": "pool_rank", "pool_index": 0, "rank": 0},
                "away": {"kind": "pool_rank", "pool_index": 1, "rank": 1},
            },
            {
                "stage": "Semi-Finals B",
                "home": {"kind": "pool_rank", "pool_index": 1, "rank": 0},
                "away": {"kind": "pool_rank", "pool_index": 0, "rank": 1},
            },
            {
                "stage": "Final",
                "home": {"kind": "match_winner", "match_index": 9},
                "away": {"kind": "match_winner", "match_index": 10},
            },
        ]
    )
    template = captured_division_schedule_template(
        division_name="Crossover",
        actual_division_name="U14 Crossover",
        pool_sizes=(3, 3),
        fixture_slots=fixtures,
        tiebreak_order=DEFAULT_TIEBREAK_ORDER,
        tiebreak_source_urls=("https://example.test/tiebreak",),
        scoring_policy=STANDARD_SCORING_POLICY,
    )

    def cross_prediction(team_a, team_b):
        stronger_a = team_a.power_score > team_b.power_score
        margin = max(1, round(abs(team_a.power_score - team_b.power_score) * 10))
        return SimpleNamespace(
            predicted_winner="team_a" if stronger_a else "team_b",
            expected_score={
                "teamA": margin if stronger_a else 0,
                "teamB": 0 if stronger_a else margin,
            },
        )

    simulation = simulate_tournament_schedule(
        result.divisions,
        {"Crossover": template},
        cross_prediction,
    )

    assert simulation.match_count == 12
    assert [match.stage for match in simulation.divisions[0].matches].count("Cross-pool") == 9
    assert simulation.divisions[0].matches[-1].stage == "Final"
    assert simulation.divisions[0].template.tiebreak_source_urls == (
        "https://example.test/tiebreak",
    )


def test_captured_graph_skips_fixture_that_was_not_played():
    teams = [_team(index, 0.95 - index * 0.1, index) for index in range(1, 5)]
    result = optimize_tournament_format(
        teams,
        [DivisionSpec(name="Gold", team_count=4, pool_sizes=(4,))],
        matchup_cost_fn=_cost,
    )
    template = captured_division_schedule_template(
        division_name="Gold",
        actual_division_name="U14 Gold",
        pool_sizes=(4,),
        fixture_slots=(
            {
                "stage": "Pool",
                "include_in_projection": False,
                "counts_for_standings": False,
                "home": {"kind": "pool_slot", "pool_index": 0, "slot_index": 0},
                "away": {"kind": "pool_slot", "pool_index": 0, "slot_index": 1},
            },
            {
                "stage": "Pool",
                "include_in_projection": True,
                "counts_for_standings": True,
                "home": {"kind": "pool_slot", "pool_index": 0, "slot_index": 2},
                "away": {"kind": "pool_slot", "pool_index": 0, "slot_index": 3},
            },
        ),
        tiebreak_order=DEFAULT_TIEBREAK_ORDER,
        scoring_policy=STANDARD_SCORING_POLICY,
    )

    simulation = simulate_tournament_schedule(
        result.divisions,
        {"Gold": template},
        _prediction,
    )

    assert template.actual_game_count == 1
    assert simulation.match_count == 1
    played_ids = {
        simulation.divisions[0].matches[0].home_team_id,
        simulation.divisions[0].matches[0].away_team_id,
    }
    expected_ids = {
        result.divisions[0].pools[0].teams[2].team_id,
        result.divisions[0].pools[0].teams[3].team_id,
    }
    assert played_ids == expected_ids


def test_captured_graph_rejects_advancement_from_a_fixture_that_was_not_played():
    with pytest.raises(ValueError, match="references a match that was not played"):
        captured_division_schedule_template(
            division_name="Gold",
            actual_division_name="U14 Gold",
            pool_sizes=(4,),
            fixture_slots=(
                {
                    "stage": "Semi-Final",
                    "include_in_projection": False,
                    "home": {"kind": "pool_slot", "pool_index": 0, "slot_index": 0},
                    "away": {"kind": "pool_slot", "pool_index": 0, "slot_index": 1},
                },
                {
                    "stage": "Final",
                    "home": {"kind": "match_winner", "match_index": 0},
                    "away": {"kind": "pool_slot", "pool_index": 0, "slot_index": 2},
                },
            ),
            scoring_policy=STANDARD_SCORING_POLICY,
        )


def test_captured_graph_selects_wildcards_across_the_whole_division():
    teams = [_team(index, 1.0 - index * 0.1, index) for index in range(1, 7)]
    result = optimize_tournament_format(
        teams,
        [DivisionSpec(name="Wildcard", team_count=6, pool_sizes=(3, 3))],
        matchup_cost_fn=_cost,
    )
    fixtures = [
        {
            "stage": "Cross-pool",
            "counts_for_standings": True,
            "home": {"kind": "pool_slot", "pool_index": 0, "slot_index": home_slot},
            "away": {"kind": "pool_slot", "pool_index": 1, "slot_index": away_slot},
        }
        for home_slot in range(3)
        for away_slot in range(3)
    ]
    fixtures.append(
        {
            "stage": "Final- Wildcard 1 v Wildcard 2",
            "home": {"kind": "division_rank", "rank": 0},
            "away": {"kind": "division_rank", "rank": 1},
        }
    )
    template = captured_division_schedule_template(
        division_name="Wildcard",
        actual_division_name="U14 Wildcard",
        pool_sizes=(3, 3),
        fixture_slots=fixtures,
        tiebreak_order=DEFAULT_TIEBREAK_ORDER,
        tiebreak_source_urls=("https://example.test/tiebreak",),
        scoring_policy=STANDARD_SCORING_POLICY,
    )

    def ranked_prediction(team_a, team_b):
        stronger_a = team_a.power_score > team_b.power_score
        margin = max(1, round(abs(team_a.power_score - team_b.power_score) * 10))
        return SimpleNamespace(
            predicted_winner="team_a" if stronger_a else "team_b",
            expected_score={
                "teamA": margin if stronger_a else 0,
                "teamB": 0 if stronger_a else margin,
            },
        )

    simulation = simulate_tournament_schedule(
        result.divisions,
        {"Wildcard": template},
        ranked_prediction,
    )

    final = simulation.divisions[0].matches[-1]
    assert {final.home_team_id, final.away_team_id} == {"team-1", "team-2"}
    assert {"team-1", "team-2"}.issubset(
        {team.team_id for team in result.divisions[0].pools[0].teams}
    )


def test_captured_graph_blocks_a_tied_qualifier_without_verified_tiebreaks():
    teams = [_team(index, 0.9, index) for index in range(1, 5)]
    result = optimize_tournament_format(
        teams,
        [DivisionSpec(name="Gold", team_count=4, pool_sizes=(4,))],
        matchup_cost_fn=_cost,
    )
    fixtures = [
        {
            "stage": "Pool",
            "counts_for_standings": True,
            "home": {"kind": "pool_slot", "pool_index": 0, "slot_index": 0},
            "away": {"kind": "pool_slot", "pool_index": 0, "slot_index": 1},
        },
        {
            "stage": "Final",
            "home": {"kind": "pool_rank", "pool_index": 0, "rank": 0},
            "away": {"kind": "pool_slot", "pool_index": 0, "slot_index": 2},
        },
    ]
    template = captured_division_schedule_template(
        division_name="Gold",
        actual_division_name="U14 Gold",
        pool_sizes=(4,),
        fixture_slots=fixtures,
        tiebreak_source_urls=("https://example.test/tiebreak",),
        scoring_policy=STANDARD_SCORING_POLICY,
    )

    with pytest.raises(ValueError, match="no verified tournament tiebreak order"):
        simulate_tournament_schedule(result.divisions, {"Gold": template}, _prediction)


def test_tiger_captured_graph_projects_the_published_penalty_tiebreak():
    teams = [_team(1, 0.8, 1), _team(2, 0.4, 2), _team(3, 0.6, 3)]
    result = optimize_tournament_format(
        teams,
        [DivisionSpec(name="Gold", team_count=3, pool_sizes=(3,))],
        matchup_cost_fn=_cost,
    )
    pool_teams = result.divisions[0].pools[0].teams
    fixtures = [
        {
            "stage": "Pool",
            "counts_for_standings": True,
            "home": {"kind": "pool_slot", "pool_index": 0, "slot_index": 0},
            "away": {"kind": "pool_slot", "pool_index": 0, "slot_index": 1},
        },
        {
            "stage": "Final",
            "home": {"kind": "pool_rank", "pool_index": 0, "rank": 0},
            "away": {"kind": "pool_slot", "pool_index": 0, "slot_index": 2},
        },
    ]

    def draw_prediction(home, away):
        home_stronger = home.power_score > away.power_score
        return SimpleNamespace(
            predicted_winner="draw",
            expected_score={"teamA": 1, "teamB": 1},
            win_probability_a=0.4 if home_stronger else 0.2,
            win_probability_b=0.2 if home_stronger else 0.4,
        )

    template = captured_division_schedule_template(
        division_name="Gold",
        actual_division_name="U17 Boys Gold",
        pool_sizes=(3,),
        fixture_slots=fixtures,
        tiebreak_order=TIGER_TOURNAMENTS_TIEBREAK_ORDER,
        tiebreak_source_urls=("https://tigertournaments.com/resources-2/",),
        scoring_policy=TIGER_TOURNAMENTS_SCORING_POLICY,
    )

    simulation = simulate_tournament_schedule(
        result.divisions,
        {"Gold": template},
        draw_prediction,
    )

    tied = pool_teams[:2]
    expected_qualifier = max(tied, key=lambda team: team.power_score)
    final = simulation.divisions[0].matches[-1]
    assert final.home_team_id == expected_qualifier.team_id
    assert simulation.divisions[0].qualification_tiebreaks == (
        {
            "qualifier_rank": 1,
            "basis": "published_penalty_kicks_projected_from_pre_event_model",
            "tied_team_ids": sorted(team.team_id for team in tied),
            "projected_order": [
                team.team_id for team in sorted(tied, key=lambda team: -team.power_score)
            ],
        },
    )


def test_captured_graph_resolves_knockout_draws_without_home_side_bias():
    teams = [_team(index, 0.95 - index * 0.1, index) for index in range(1, 5)]
    result = optimize_tournament_format(
        teams,
        [DivisionSpec(name="Gold", team_count=4, pool_sizes=(4,))],
        matchup_cost_fn=_cost,
    )
    pool_teams = result.divisions[0].pools[0].teams
    fixtures = [
        {
            "stage": "Semi A",
            "home": {"kind": "pool_slot", "pool_index": 0, "slot_index": 0},
            "away": {"kind": "pool_slot", "pool_index": 0, "slot_index": 1},
        },
        {
            "stage": "Semi B",
            "home": {"kind": "pool_slot", "pool_index": 0, "slot_index": 2},
            "away": {"kind": "pool_slot", "pool_index": 0, "slot_index": 3},
        },
        {
            "stage": "Final",
            "home": {"kind": "match_winner", "match_index": 0},
            "away": {"kind": "match_winner", "match_index": 1},
        },
    ]

    def draw_prediction(home, away):
        home_stronger = home.power_score > away.power_score
        return SimpleNamespace(
            predicted_winner="draw",
            expected_score={"teamA": 1, "teamB": 1},
            win_probability_a=0.4 if home_stronger else 0.2,
            win_probability_b=0.2 if home_stronger else 0.4,
            blowout_4plus_probability=0.01,
        )

    template = captured_division_schedule_template(
        division_name="Gold",
        actual_division_name="U14 Gold",
        pool_sizes=(4,),
        fixture_slots=fixtures,
        scoring_policy=STANDARD_SCORING_POLICY,
    )
    simulation = simulate_tournament_schedule(
        result.divisions,
        {"Gold": template},
        draw_prediction,
    )

    expected_finalists = {
        max(pool_teams[:2], key=lambda team: team.power_score).team_id,
        max(pool_teams[2:], key=lambda team: team.power_score).team_id,
    }
    final = simulation.divisions[0].matches[-1]
    assert {final.home_team_id, final.away_team_id} == expected_finalists
    assert simulation.divisions[0].matches[0].advancement_basis == "regulation_win_probability"
