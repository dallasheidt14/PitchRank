"""Complete-pair group-fit diagnostics for MatchBalance alternatives."""

from dataclasses import replace
from itertools import combinations

import pytest

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_group_assessment import (
    ALL_WITHIN_LIMITS,
    INCOMPLETE_PREDICTIONS,
    NO_WITHIN_GROUP_MATCHUP,
    PREDICTION_INVALID,
    PREDICTION_MISSING,
    SOME_EXCEED_LIMITS,
    GroupTeam,
    assess_contiguous_groups,
    assess_group,
    assess_group_addition,
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
    confidence: str = "high",
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
        confidence=confidence,
        confidence_score=0.80,
    )


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
            power_score=0.80 - index / 100,
            limited_history=(
                None if entrant_id in unknown else entrant_id in limited
            ),
            evidence_game_count=(
                None if entrant_id in unknown else 4 if entrant_id in limited else 20
            ),
        )
        for index, entrant_id in enumerate(ids, start=1)
    }


def _matrix(
    ids: list[str],
    *,
    absolute_goal_difference: float = 1.0,
    blowout: float = 0.10,
) -> dict[tuple[str, str], ComparePrediction]:
    return {
        pair: _prediction(
            absolute_goal_difference=absolute_goal_difference,
            blowout=blowout,
        )
        for pair in combinations(ids, 2)
    }


def test_every_unique_pair_is_checked_once_and_can_pass():
    ids = ["a", "b", "c", "d"]
    result = assess_group(ids, _matrix(ids), TierPolicy(), _teams(ids))

    assert result.projected_fit.conclusion == ALL_WITHIN_LIMITS
    assert result.projected_fit.all_pair_projected_fit_passed is True
    assert result.projected_fit.expected_unique_pairing_count == 6
    assert len(result.pairings) == 6
    assert {frozenset(item.entrant_ids) for item in result.pairings} == {
        frozenset(pair) for pair in combinations(ids, 2)
    }


def test_one_bad_pair_is_not_hidden_by_good_group_averages():
    ids = ["a", "b", "c", "d"]
    predictions = _matrix(ids, absolute_goal_difference=0.5, blowout=0.02)
    predictions[("a", "d")] = _prediction(
        margin=2.2,
        absolute_goal_difference=3.0,
        blowout=0.40,
    )

    result = assess_group(ids, predictions, TierPolicy(), _teams(ids))

    assert result.projected_fit.average_expected_absolute_goal_difference < 2.0
    assert result.projected_fit.average_blowout_probability < 0.30
    assert result.projected_fit.conclusion == SOME_EXCEED_LIMITS
    assert result.projected_fit.all_pair_projected_fit_passed is False
    assert [item.entrant_ids for item in result.projected_fit.over_limit_matchups] == [
        ("a", "d")
    ]


def test_adjacent_matches_can_pass_while_a_non_adjacent_match_fails():
    ids = ["a", "b", "c"]
    predictions = _matrix(ids)
    predictions[("a", "c")] = _prediction(
        margin=2.5,
        absolute_goal_difference=2.5,
        blowout=0.20,
    )

    result = assess_group(ids, predictions, TierPolicy(), _teams(ids))

    assert next(item for item in result.pairings if item.entrant_ids == ("a", "b")).within_both_limits
    assert next(item for item in result.pairings if item.entrant_ids == ("b", "c")).within_both_limits
    assert not next(item for item in result.pairings if item.entrant_ids == ("a", "c")).within_both_limits
    assert result.projected_fit.conclusion == SOME_EXCEED_LIMITS


def test_signed_margins_can_cancel_while_absolute_and_blowout_risk_fail():
    ids = ["a", "b", "c"]
    predictions = {
        ("a", "b"): _prediction(2.5, absolute_goal_difference=3.0, blowout=0.40),
        ("a", "c"): _prediction(-2.5, absolute_goal_difference=3.0, blowout=0.40),
        ("b", "c"): _prediction(0.0, absolute_goal_difference=0.5, blowout=0.05),
    }

    result = assess_group(ids, predictions, TierPolicy(), _teams(ids))

    assert sum(item.expected_signed_margin_toward_first for item in result.pairings) == 0
    assert result.projected_fit.exceeding_either_limit_count == 2
    assert result.projected_fit.all_pair_projected_fit_passed is False


@pytest.mark.parametrize(
    ("absolute_goal_difference", "blowout", "goal_passes", "blowout_passes"),
    [
        (2.0, 0.31, True, False),
        (2.01, 0.30, False, True),
    ],
)
def test_each_competitive_limit_can_fail_independently(
    absolute_goal_difference: float,
    blowout: float,
    goal_passes: bool,
    blowout_passes: bool,
):
    ids = ["a", "b"]
    result = assess_group(
        ids,
        {
            ("a", "b"): _prediction(
                margin=1.0,
                absolute_goal_difference=absolute_goal_difference,
                blowout=blowout,
            )
        },
        TierPolicy(),
        _teams(ids),
    )

    pair = result.pairings[0]
    assert pair.within_expected_goal_difference_limit is goal_passes
    assert pair.within_blowout_probability_limit is blowout_passes
    assert pair.within_both_limits is False


def test_policy_limits_are_inclusive():
    ids = ["a", "b"]
    result = assess_group(
        ids,
        {
            ("a", "b"): _prediction(
                margin=2.0,
                absolute_goal_difference=2.0,
                blowout=0.30,
            )
        },
        TierPolicy(),
        _teams(ids),
    )

    assert result.pairings[0].within_both_limits is True
    assert result.projected_fit.all_pair_projected_fit_passed is True


def test_adding_a_team_preserves_and_identifies_existing_bad_pairs():
    ids = ["a", "b", "c", "d"]
    predictions = _matrix(ids)
    predictions[("a", "b")] = _prediction(
        margin=2.2,
        absolute_goal_difference=2.2,
        blowout=0.20,
    )
    addition = assess_group_addition(
        ids[:3], "d", predictions, TierPolicy(), _teams(ids), direction="below"
    )

    assert addition.original_group_had_projected_failures is True
    assert [item.entrant_ids for item in addition.original_over_limit_matchups] == [
        ("a", "b")
    ]
    assert ("a", "b") in {
        item.entrant_ids for item in addition.expanded_group.projected_fit.over_limit_matchups
    }
    assert not addition.newly_over_limit_matchups


def test_removing_a_team_removes_only_failures_that_involve_it():
    ids = ["a", "b", "c"]
    predictions = _matrix(ids)
    predictions[("a", "c")] = _prediction(
        margin=2.5,
        absolute_goal_difference=2.5,
        blowout=0.40,
    )

    full = assess_group(ids, predictions, TierPolicy(), _teams(ids))
    reduced = assess_group(ids[:2], predictions, TierPolicy(), _teams(ids))

    assert full.projected_fit.exceeding_either_limit_count == 1
    assert reduced.projected_fit.exceeding_either_limit_count == 0
    assert reduced.projected_fit.all_pair_projected_fit_passed is True


def test_limited_history_pair_can_project_within_limits_but_remains_provisional():
    ids = ["a", "b"]
    result = assess_group(
        ids,
        _matrix(ids),
        TierPolicy(),
        _teams(ids, limited={"b"}),
    )

    assert result.projected_fit.all_pair_projected_fit_passed is True
    assert result.pairings[0].provisional_due_to_history is True
    assert result.evidence_coverage.provisional_within_limit_pairings == result.pairings
    assert result.evidence_coverage.limitations


def test_missing_prediction_is_never_treated_as_safe():
    ids = ["a", "b", "c"]
    predictions = _matrix(ids)
    del predictions[("a", "c")]

    result = assess_group(ids, predictions, TierPolicy(), _teams(ids))

    assert result.projected_fit.conclusion == INCOMPLETE_PREDICTIONS
    assert result.projected_fit.all_pair_projected_fit_passed is False
    assert result.projected_fit.missing_prediction_count == 1
    assert next(
        item for item in result.pairings if item.entrant_ids == ("a", "c")
    ).prediction_status == PREDICTION_MISSING


def test_invalid_prediction_is_never_treated_as_safe():
    ids = ["a", "b"]
    invalid = _prediction(1.0, absolute_goal_difference=1.0, blowout=0.10)
    invalid = replace(invalid, blowout_4plus_probability=float("nan"))

    result = assess_group(
        ids,
        {("a", "b"): invalid},
        TierPolicy(),
        _teams(ids),
    )

    assert result.projected_fit.conclusion == INCOMPLETE_PREDICTIONS
    assert result.projected_fit.invalid_prediction_count == 1
    assert result.pairings[0].prediction_status == PREDICTION_INVALID


def test_forward_and_reverse_records_are_validated_but_counted_once():
    ids = ["a", "b"]
    forward = _prediction(1.0, absolute_goal_difference=1.2, blowout=0.10)
    reverse = replace(
        forward,
        expected_margin=-1.0,
        predicted_winner="team_b",
    )

    result = assess_group(
        ids,
        {("a", "b"): forward, ("b", "a"): reverse},
        TierPolicy(),
        _teams(ids),
    )

    assert len(result.pairings) == 1
    assert result.projected_fit.available_unique_pairing_count == 1


def test_inconsistent_reverse_record_marks_the_unique_pair_invalid():
    ids = ["a", "b"]
    forward = _prediction(1.0, absolute_goal_difference=1.2, blowout=0.10)
    reverse = replace(forward, expected_margin=-0.8)

    result = assess_group(
        ids,
        {("a", "b"): forward, ("b", "a"): reverse},
        TierPolicy(),
        _teams(ids),
    )

    assert len(result.pairings) == 1
    assert result.pairings[0].prediction_status == PREDICTION_INVALID
    assert result.projected_fit.all_pair_projected_fit_passed is False


def test_overlapping_passing_groups_do_not_imply_their_union_passes():
    ids = ["a", "b", "c", "d"]
    predictions = _matrix(ids)
    predictions[("a", "d")] = _prediction(
        margin=3.0,
        absolute_goal_difference=3.0,
        blowout=0.40,
    )

    left = assess_group(ids[:3], predictions, TierPolicy(), _teams(ids))
    right = assess_group(ids[1:], predictions, TierPolicy(), _teams(ids))
    union = assess_group(ids, predictions, TierPolicy(), _teams(ids))

    assert left.projected_fit.all_pair_projected_fit_passed is True
    assert right.projected_fit.all_pair_projected_fit_passed is True
    assert union.projected_fit.all_pair_projected_fit_passed is False


def test_bridge_team_can_belong_to_multiple_acceptable_candidates():
    ids = ["a", "bridge", "c"]
    predictions = {
        ("a", "bridge"): _prediction(0.5, absolute_goal_difference=1.0, blowout=0.10),
        ("a", "c"): _prediction(2.5, absolute_goal_difference=2.5, blowout=0.35),
        ("bridge", "c"): _prediction(0.5, absolute_goal_difference=1.0, blowout=0.10),
    }

    left = assess_group(ids[:2], predictions, TierPolicy(), _teams(ids))
    right = assess_group(ids[1:], predictions, TierPolicy(), _teams(ids))

    assert left.projected_fit.all_pair_projected_fit_passed is True
    assert right.projected_fit.all_pair_projected_fit_passed is True


def test_singleton_is_no_matchup_not_perfect_fit():
    result = assess_group(["a"], {}, TierPolicy(), _teams(["a"]))

    assert result.projected_fit.conclusion == NO_WITHIN_GROUP_MATCHUP
    assert result.projected_fit.expected_unique_pairing_count == 0
    assert result.projected_fit.all_pair_projected_fit_passed is None


def test_membership_input_order_does_not_change_results():
    ids = ["a", "b", "c"]
    teams = _teams(ids)
    predictions = _matrix(ids)

    forward = assess_group(ids, predictions, TierPolicy(), teams)
    reverse = assess_group(list(reversed(ids)), predictions, TierPolicy(), teams)

    assert forward == reverse


def test_contiguous_scan_uses_only_requested_sizes_and_reports_additions():
    ids = ["a", "b", "c", "d", "e", "f"]
    scan = assess_contiguous_groups(
        ids,
        [4, 5, 8],
        _matrix(ids),
        TierPolicy(),
        _teams(ids),
    )

    assert scan.requested_sizes == (4, 5, 8)
    assert scan.available_sizes == (4, 5)
    assert scan.unavailable_sizes == (8,)
    assert [(item.requested_size, item.start_order_position) for item in scan.candidates] == [
        (4, 1),
        (4, 2),
        (4, 3),
        (5, 1),
        (5, 2),
    ]
    middle = scan.candidates[1]
    assert middle.add_above is not None
    assert middle.add_below is not None
    assert len(middle.add_above.newly_introduced_matchups) == 4
    assert len(middle.add_below.newly_introduced_matchups) == 4


def test_metric_maxima_and_policy_weighted_worst_pair_are_reported_separately():
    ids = ["a", "b", "c"]
    policy = TierPolicy(blowout_cost_weight=10.0)
    predictions = {
        ("a", "b"): _prediction(1.9, absolute_goal_difference=1.9, blowout=0.01),
        ("a", "c"): _prediction(1.0, absolute_goal_difference=1.0, blowout=0.29),
        ("b", "c"): _prediction(1.2, absolute_goal_difference=1.2, blowout=0.25),
    }

    result = assess_group(ids, predictions, policy, _teams(ids))

    assert result.projected_fit.maximum_expected_absolute_goal_difference_matchup.entrant_ids == (
        "a",
        "b",
    )
    assert result.projected_fit.maximum_blowout_probability_matchup.entrant_ids == (
        "a",
        "c",
    )
    assert result.projected_fit.worst_matchup.entrant_ids == ("a", "c")


def test_group_assessment_does_not_mutate_seed_or_boundary_analysis():
    ids = ["a", "b", "c", "d", "e"]
    predictions = _matrix(ids)
    entrants = [
        TierEntrant(
            entrant_id=entrant_id,
            team_name=f"Team {entrant_id}",
            power_score=0.80 - index / 100,
        )
        for index, entrant_id in enumerate(ids)
    ]
    manual_order = ["a", "c", "b", "d", "e"]
    before = build_cheat_sheet_analysis(
        entrants,
        predictions,
        TierPolicy(),
        manual_order=manual_order,
    )

    assess_group(ids[:4], predictions, TierPolicy(), _teams(ids))

    after = build_cheat_sheet_analysis(
        entrants,
        predictions,
        TierPolicy(),
        manual_order=manual_order,
    )
    assert after == before
    assert after.baseline_order == tuple(ids)
    assert after.ordered_ids == tuple(manual_order)
    assert after.manual_override is True
