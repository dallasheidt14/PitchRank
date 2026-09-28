"""Complete flight-plan evaluation over the frozen MatchBalance order."""

from dataclasses import replace
from itertools import combinations, permutations

import pytest

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_group_assessment import GroupTeam
from src.tournaments.seeding_plan_assessment import (
    APPROVED_ALTERNATIVES,
    EXACT_ORDERED,
    PERMITTED_SIZE_MULTISET,
    PREDICTION_ASSESSMENT_INCOMPLETE,
    SOME_MATCHUPS_EXCEED_POLICY,
    UnassignedEntrant,
    assess_all_opponents,
    assess_flight_plan,
    assess_permitted_plans,
    enumerate_arrangements,
)
from src.tournaments.seeding_tiers import (
    TierEntrant,
    TierPolicy,
    build_cheat_sheet_analysis,
)


def _prediction(
    margin: float = 0.4,
    *,
    absolute_goal_difference: float = 1.0,
    blowout: float = 0.10,
) -> ComparePrediction:
    return ComparePrediction(
        predicted_winner="team_a" if margin > 0 else "team_b" if margin < 0 else "draw",
        win_probability_a=0.60 if margin > 0 else 0.25,
        win_probability_b=0.25 if margin > 0 else 0.60,
        draw_probability=0.15,
        expected_score={"teamA": 2, "teamB": 1},
        expected_margin=margin,
        expected_absolute_goal_difference=absolute_goal_difference,
        blowout_4plus_probability=blowout,
        confidence="high",
        confidence_score=0.80,
    )


def _matrix(ids: list[str]) -> dict[tuple[str, str], ComparePrediction]:
    return {pair: _prediction() for pair in combinations(ids, 2)}


def _teams(
    ids: list[str],
    *,
    limited: set[str] | None = None,
    unknown: set[str] | None = None,
) -> dict[str, GroupTeam]:
    limited = limited or set()
    unknown = unknown or set()
    return {
        entrant_id: GroupTeam(
            entrant_id=entrant_id,
            team_name=f"Team {entrant_id}",
            team_id_master=f"master-{entrant_id}",
            seed=index,
            power_score=0.90 - index / 100,
            limited_history=(
                None if entrant_id in unknown else entrant_id in limited
            ),
            evidence_game_count=(
                None if entrant_id in unknown else 4 if entrant_id in limited else 20
            ),
        )
        for index, entrant_id in enumerate(ids, start=1)
    }


def _enumeration(
    sizes: list[int], team_count: int, mode: str = EXACT_ORDERED
):
    return enumerate_arrangements(mode, [sizes], team_count)


def test_exact_ordered_sizes_produce_expected_contiguous_memberships():
    ids = list("abcdefgh")
    result = assess_permitted_plans(
        _enumeration([3, 5], len(ids)),
        ids,
        _matrix(ids),
        TierPolicy(),
        _teams(ids),
    )

    assert len(result.plans) == 1
    assert [flight.entrant_ids for flight in result.plans[0].flights] == [
        ("a", "b", "c"),
        ("d", "e", "f", "g", "h"),
    ]
    assert result.comparisons[0].only_one_permitted_arrangement is True


def test_repeated_sizes_produce_every_unique_permutation_once():
    result = enumerate_arrangements(
        PERMITTED_SIZE_MULTISET,
        [[6, 5, 5]],
        16,
    )

    assert result.arrangements == ((5, 5, 6), (5, 6, 5), (6, 5, 5))
    assert result.total_distinct_arrangement_count == 3
    assert result.search_complete is True


def test_multiset_enumeration_matches_exhaustive_small_case():
    sizes = (4, 3, 3, 2)
    expected = tuple(sorted(set(permutations(sizes))))

    result = enumerate_arrangements(
        PERMITTED_SIZE_MULTISET,
        [sizes],
        sum(sizes),
    )

    assert result.arrangements == expected


def test_explicit_search_limit_is_reported_as_incomplete():
    result = enumerate_arrangements(
        PERMITTED_SIZE_MULTISET,
        [[2, 3, 4, 5]],
        14,
        max_arrangements=5,
    )

    assert result.total_distinct_arrangement_count == 24
    assert result.evaluated_arrangement_count == 5
    assert result.search_complete is False
    assert "only 5 were evaluated" in result.diagnostic


@pytest.mark.parametrize(
    ("mode", "structures", "team_count", "message"),
    [
        (EXACT_ORDERED, [[2, 0, 2]], 4, "at least two"),
        (EXACT_ORDERED, [[2, 1, 2]], 5, "at least two"),
        (EXACT_ORDERED, [[2, 2]], 5, "assign 4 teams"),
        (APPROVED_ALTERNATIVES, [[2, 2], [2, 2]], 4, "duplicate"),
    ],
)
def test_invalid_sizes_totals_and_duplicate_alternatives_are_rejected(
    mode: str,
    structures: list[list[int]],
    team_count: int,
    message: str,
):
    with pytest.raises(ValueError, match=message):
        enumerate_arrangements(mode, structures, team_count)


def test_every_assigned_entrant_appears_exactly_once():
    ids = list("abcdef")
    plan = assess_flight_plan(
        ids,
        [2, 4],
        _matrix(ids),
        TierPolicy(),
        _teams(ids),
    )

    assigned = [item for flight in plan.flights for item in flight.entrant_ids]
    assert assigned == ids
    assert len(set(assigned)) == len(ids)
    assert plan.structural.every_assigned_entrant_appears_once is True


def test_duplicate_order_cannot_create_overlapping_flights():
    ids = ["a", "b", "c", "d"]
    with pytest.raises(ValueError, match="unique entrant IDs"):
        assess_flight_plan(
            ["a", "b", "b", "d"],
            [2, 2],
            _matrix(ids),
            TierPolicy(),
            _teams(ids),
        )


def test_explicit_hold_is_accounted_for_but_prevents_full_field_claim():
    ids = list("abcde")
    plan = assess_flight_plan(
        ids[:4],
        [2, 2],
        _matrix(ids),
        TierPolicy(),
        _teams(ids),
        accepted_entrant_ids=ids,
        unassigned_entrants=[UnassignedEntrant("e", "Manual placement hold")],
    )

    coverage = plan.accepted_field_coverage
    assert coverage.every_accepted_entrant_accounted_for is True
    assert coverage.full_accepted_field_coverage is False
    assert coverage.plan_for_assigned_subset is True
    assert coverage.unassigned_entrants[0].reason == "Manual placement hold"


def test_unaccounted_entrant_is_exposed_in_coverage():
    ids = list("abcde")
    plan = assess_flight_plan(
        ids[:4],
        [2, 2],
        _matrix(ids),
        TierPolicy(),
        _teams(ids),
        accepted_entrant_ids=ids,
    )

    assert plan.accepted_field_coverage.every_accepted_entrant_accounted_for is False
    assert plan.accepted_field_coverage.unaccounted_entrant_ids == ("e",)


def test_all_groups_passing_produces_complete_plan_pass():
    ids = list("abcdef")
    plan = assess_flight_plan(
        ids,
        [3, 3],
        _matrix(ids),
        TierPolicy(),
        _teams(ids),
    )

    assert plan.required_unique_pairing_count == 6
    assert plan.available_unique_pairing_count == 6
    assert plan.violating_pairing_count == 0
    assert plan.all_pair_projected_fit_passed is True


def test_one_severe_pair_cannot_disappear_inside_good_averages():
    ids = list("abcdef")
    predictions = _matrix(ids)
    predictions[("a", "c")] = _prediction(
        margin=3.5,
        absolute_goal_difference=4.0,
        blowout=0.55,
    )
    plan = assess_flight_plan(
        ids,
        [3, 3],
        predictions,
        TierPolicy(),
        _teams(ids),
    )

    assert plan.pair_weighted_average_expected_absolute_goal_difference < 2.0
    assert plan.violating_pairing_count == 1
    assert plan.all_pair_projected_fit_passed is False
    assert plan.prediction_conclusion == SOME_MATCHUPS_EXCEED_POLICY
    assert plan.violations[0].expected_goal_difference_excess == 2.0
    assert plan.violations[0].blowout_probability_excess == pytest.approx(0.25)
    exposure = next(item for item in plan.team_exposures if item.team.entrant_id == "a")
    assert exposure.over_limit_opponent_count == 1


def test_missing_predictions_never_pass_and_known_violations_remain_visible():
    ids = list("abcd")
    predictions = _matrix(ids)
    predictions[("a", "b")] = _prediction(
        margin=3.0,
        absolute_goal_difference=3.0,
        blowout=0.40,
    )
    del predictions[("c", "d")]
    plan = assess_flight_plan(
        ids,
        [2, 2],
        predictions,
        TierPolicy(),
        _teams(ids),
    )

    assert plan.prediction_complete is False
    assert plan.prediction_conclusion == PREDICTION_ASSESSMENT_INCOMPLETE
    assert plan.all_pair_projected_fit_passed is False
    assert plan.missing_prediction_count == 1
    assert plan.violating_pairing_count == 1
    assert plan.violating_fraction_of_available_predictions == 1.0
    assert plan.known_violating_fraction_of_required_lower_bound == 0.5
    assert "1 known violation" in plan.prediction_reason


def test_invalid_prediction_never_passes():
    ids = ["a", "b"]
    invalid = replace(_prediction(), blowout_4plus_probability=float("nan"))
    plan = assess_flight_plan(
        ids,
        [2],
        {("a", "b"): invalid},
        TierPolicy(),
        _teams(ids),
    )

    assert plan.invalid_prediction_count == 1
    assert plan.prediction_complete is False
    assert plan.all_pair_projected_fit_passed is False


def test_limited_and_unknown_evidence_survive_plan_aggregation():
    ids = list("abcd")
    plan = assess_flight_plan(
        ids,
        [4],
        _matrix(ids),
        TierPolicy(),
        _teams(ids, limited={"c"}, unknown={"d"}),
    )

    assert plan.established_history_pairing_count == 1
    assert plan.limited_history_pairing_count == 2
    assert plan.unknown_history_pairing_count == 3
    assert plan.evidence_limitations
    exposure = next(item for item in plan.team_exposures if item.team.entrant_id == "a")
    assert exposure.limited_or_unknown_evidence_opponent_count == 2


def test_plan_averages_are_weighted_by_unique_pair_count():
    ids = list("abcdef")
    predictions = _matrix(ids)
    predictions[("a", "b")] = _prediction(
        margin=1.0,
        absolute_goal_difference=2.0,
        blowout=0.20,
    )
    plan = assess_flight_plan(
        ids,
        [2, 4],
        predictions,
        TierPolicy(),
        _teams(ids),
    )

    assert plan.required_unique_pairing_count == 7
    assert plan.pair_weighted_average_expected_absolute_goal_difference == pytest.approx(
        8 / 7
    )
    assert plan.pair_weighted_average_blowout_probability == pytest.approx(0.8 / 7)


def test_tradeoff_plans_are_both_nondominated_and_comparison_is_deterministic():
    ids = list("abcdef")
    predictions = _matrix(ids)
    predictions[("c", "e")] = _prediction(
        margin=4.0,
        absolute_goal_difference=4.0,
        blowout=0.20,
    )
    for pair in (("a", "c"), ("a", "d")):
        predictions[pair] = _prediction(
            margin=2.5,
            absolute_goal_difference=2.5,
            blowout=0.20,
        )
    enumeration = enumerate_arrangements(
        PERMITTED_SIZE_MULTISET,
        [[2, 4]],
        len(ids),
    )

    first = assess_permitted_plans(
        enumeration,
        ids,
        predictions,
        TierPolicy(),
        _teams(ids),
    )
    second = assess_permitted_plans(
        enumeration,
        ids,
        predictions,
        TierPolicy(),
        _teams(ids),
    )

    assert first == second
    assert [plan.violating_pairing_count for plan in first.plans] == [1, 2]
    assert first.plans[0].worst_matchup_cost > first.plans[1].worst_matchup_cost
    assert first.comparisons[0].nondominated_plan_ids == tuple(
        plan.plan_id for plan in first.plans
    )


def test_incomplete_plan_cannot_rank_ahead_on_known_violation_count():
    ids = list("abcdef")
    predictions = _matrix(ids)
    del predictions[("a", "b")]
    enumeration = enumerate_arrangements(
        PERMITTED_SIZE_MULTISET,
        [[2, 4]],
        len(ids),
    )
    result = assess_permitted_plans(
        enumeration,
        ids,
        predictions,
        TierPolicy(),
        _teams(ids),
    )

    comparison = result.comparisons[0]
    incomplete = next(item for item in result.plans if not item.prediction_complete)
    row = next(item for item in comparison.dominance if item.plan_id == incomplete.plan_id)
    assert row.comparison_eligible is False
    assert row.nondominated is None


def test_different_structure_multisets_are_compared_separately():
    ids = list("abcdefgh")
    enumeration = enumerate_arrangements(
        APPROVED_ALTERNATIVES,
        [[8], [4, 4]],
        len(ids),
    )
    result = assess_permitted_plans(
        enumeration,
        ids,
        _matrix(ids),
        TierPolicy(),
        _teams(ids),
    )

    assert [item.flight_size_multiset for item in result.comparisons] == [
        (4, 4),
        (8,),
    ]
    assert all(item.only_one_permitted_arrangement for item in result.comparisons)


def test_outlier_is_kept_and_complete_predictions_explain_unavoidable_violation():
    ids = list("abcd")
    predictions = _matrix(ids)
    for other in "bcd":
        predictions[("a", other)] = _prediction(
            margin=3.0,
            absolute_goal_difference=3.0,
            blowout=0.40,
        )
    enumeration = _enumeration([2, 2], len(ids))
    result = assess_permitted_plans(
        enumeration,
        ids,
        predictions,
        TierPolicy(),
        _teams(ids),
    )

    assert "a" in result.plans[0].selected_order
    outlier = next(
        item for item in result.all_opponent_assessments if item.team.entrant_id == "a"
    )
    assert outlier.complete_predictions_establish_no_within_policy_opponent is True
    assert not outlier.within_policy_opponents
    assert result.no_all_pair_within_policy_plan_among_permitted is True


def test_missing_all_opponent_prediction_prevents_unavoidable_claim():
    ids = list("abc")
    predictions = _matrix(ids)
    predictions[("a", "b")] = _prediction(
        margin=3.0,
        absolute_goal_difference=3.0,
        blowout=0.40,
    )
    del predictions[("a", "c")]

    outlier = next(
        item
        for item in assess_all_opponents(
            ids, predictions, TierPolicy(), _teams(ids)
        )
        if item.team.entrant_id == "a"
    )

    assert outlier.complete_prediction_coverage is False
    assert outlier.complete_predictions_establish_no_within_policy_opponent is False


def test_manual_effective_order_and_hold_are_read_only_inputs():
    ids = list("abcde")
    predictions = _matrix(ids)
    entrants = [
        TierEntrant(
            entrant_id=entrant_id,
            team_name=f"Team {entrant_id}",
            power_score=0.90 - index / 100,
        )
        for index, entrant_id in enumerate(ids)
    ]
    manual_order = ["a", "c", "b", "d"]
    before = build_cheat_sheet_analysis(
        entrants,
        predictions,
        TierPolicy(),
        manual_order=manual_order,
        manual_holds=["e"],
    )

    plan = assess_flight_plan(
        before.ordered_ids,
        [2, 2],
        predictions,
        TierPolicy(),
        _teams(ids),
        accepted_entrant_ids=ids,
        unassigned_entrants=[UnassignedEntrant("e", "Saved manual hold")],
    )
    after = build_cheat_sheet_analysis(
        entrants,
        predictions,
        TierPolicy(),
        manual_order=manual_order,
        manual_holds=["e"],
    )

    assert plan.selected_order == tuple(manual_order)
    assert plan.accepted_field_coverage.plan_for_assigned_subset is True
    assert after == before
    assert after.baseline_order == tuple(ids)
    assert after.suggested_order == tuple(ids)
    assert after.manual_holds == ("e",)
    assert after.boundary_assessments == before.boundary_assessments
