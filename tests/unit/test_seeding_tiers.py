"""Tournament placement behavior, independent of PowerScore distances."""

from dataclasses import replace
from itertools import combinations
from types import SimpleNamespace

import pytest

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_tiers import TierEntrant, TierPolicy, build_cheat_sheet_analysis, build_tiers


def prediction(margin, blowout=0.1):
    return ComparePrediction(
        predicted_winner="team_a" if margin > 0 else "team_b" if margin < 0 else "draw",
        win_probability_a=0.45,
        win_probability_b=0.45,
        draw_probability=0.10,
        expected_score={"teamA": 2, "teamB": 2},
        expected_margin=margin,
        expected_absolute_goal_difference=max(abs(margin), 1.0),
        blowout_4plus_probability=blowout,
    )


def matrix(ids, strengths=None, *, blowout=0.1):
    strengths = strengths or {key: 0.0 for key in ids}
    return {(a, b): prediction(strengths[a] - strengths[b], blowout) for a, b in combinations(ids, 2)}


def entrants(ids):
    return [TierEntrant(key, f"Team {key}", 0.5) for key in ids]


def memberships(result):
    return [set(tier.entrant_ids) for tier in result.tiers]


def test_six_and_nine_teams_split_despite_close_displayed_powerscores():
    upper = [f"a{index}" for index in range(6)]
    lower = [f"b{index}" for index in range(9)]
    ids = upper + lower
    roster = [TierEntrant(key, key, 0.55 if key in upper else 0.53) for key in ids]
    predictions = matrix(ids, {key: 4.0 if key in upper else 0 for key in ids})
    predictions = {pair: replace(value, blowout_4plus_probability=0.65 if abs(value.expected_margin) > 3 else 0.1)
                   for pair, value in predictions.items()}

    result = build_tiers(roster, predictions)

    assert memberships(result) == [set(upper), set(lower)]
    assert result.boundaries == (
        "Tier 1 / Tier 2: Clear separation. Upper tier favored in 54/54 matchups, "
        "with an average expected edge of 4.00 goals; 54/54 exceed the within-tier limits.",
    )
    assert result.borderline == {}


def test_neighbor_similarity_cannot_chain_a_five_goal_mismatch():
    predictions = {("a", "b"): prediction(1), ("b", "c"): prediction(1), ("a", "c"): prediction(5)}
    result = build_tiers(entrants(["a", "b", "c"]), predictions)
    assert len(result.tiers) == 2
    assert not any({"a", "c"}.issubset(group) for group in memberships(result))
    assert result.borderline["b"] == (1,)


def test_only_the_published_boundary_team_can_move_down():
    roster = [
        TierEntrant("a", "Team a", 0.9),
        TierEntrant("b", "Team b", 0.8),
        TierEntrant("c", "Team c", 0.7),
        TierEntrant("d", "Team d", 0.6),
        TierEntrant("e", "Team e", 0.5),
    ]
    predictions = matrix(["a", "b", "c", "d", "e"])
    predictions.update({
        ("a", "d"): prediction(4), ("a", "e"): prediction(4),
        ("b", "d"): prediction(3), ("b", "e"): prediction(3),
        ("c", "d"): prediction(1), ("c", "e"): prediction(1),
    })

    result = build_tiers(roster, predictions, manual_groups=[["a", "b", "c"], ["d", "e"]])

    assert result.ordered_ids == ("a", "b", "c", "d", "e")
    assert result.borderline == {"c": (2,)}


def test_safe_interior_teams_are_not_boundary_options():
    roster = [
        TierEntrant("a", "Team a", 0.9),
        TierEntrant("b", "Team b", 0.8),
        TierEntrant("c", "Team c", 0.7),
        TierEntrant("d", "Team d", 0.6),
        TierEntrant("e", "Team e", 0.5),
    ]
    predictions = matrix(["a", "b", "c", "d", "e"])
    predictions.update({
        ("a", "d"): prediction(1), ("a", "e"): prediction(1),
        ("b", "d"): prediction(1), ("b", "e"): prediction(1),
        ("c", "d"): prediction(3), ("c", "e"): prediction(3),
    })

    result = build_tiers(roster, predictions, manual_groups=[["a", "b", "c"], ["d", "e"]])

    assert result.ordered_ids == ("a", "b", "c", "d", "e")
    assert result.borderline == {}


def test_only_the_published_boundary_team_can_move_up():
    roster = [
        TierEntrant("a", "Team a", 0.9),
        TierEntrant("b", "Team b", 0.8),
        TierEntrant("c", "Team c", 0.7),
        TierEntrant("d", "Team d", 0.6),
        TierEntrant("e", "Team e", 0.5),
    ]
    predictions = matrix(["a", "b", "c", "d", "e"])
    predictions.update({
        ("a", "c"): prediction(1), ("b", "c"): prediction(1),
        ("a", "d"): prediction(3), ("b", "d"): prediction(3),
        ("a", "e"): prediction(3), ("b", "e"): prediction(3),
    })

    result = build_tiers(roster, predictions, manual_groups=[["a", "b"], ["c", "d", "e"]])

    assert result.ordered_ids == ("a", "b", "c", "d", "e")
    assert result.borderline == {"c": (1,)}


def test_singleton_tier_is_not_removed_by_a_boundary_move():
    roster = [TierEntrant("a", "Team a", 0.9), TierEntrant("b", "Team b", 0.8),
              TierEntrant("c", "Team c", 0.7)]
    result = build_tiers(
        roster,
        matrix(["a", "b", "c"]),
        manual_groups=[["a"], ["b", "c"]],
    )

    assert "a" not in result.borderline
    assert result.borderline == {"b": (1,)}


def test_group_average_cannot_hide_one_overmatched_team():
    ids = [f"a{index}" for index in range(8)] + ["weak"]
    result = build_tiers(entrants(ids), matrix(ids, {key: 0 if key == "weak" else 5 for key in ids}))
    assert memberships(result) == [set(ids[:-1]), {"weak"}]
    assert result.tiers[1].worst_pair is None
    assert "there is no within-tier matchup to assess" in result.warnings[0]


def test_blowout_risk_can_reject_even_expected_margin():
    result = build_tiers(entrants(["a", "b"]), {("a", "b"): prediction(0, 0.4)})
    assert len(result.tiers) == 2
    assert "Overlapping matchups" in result.boundaries[0]
    assert "Clear separation" not in result.boundaries[0]


def test_margin_and_probability_limits_are_independent_and_inclusive():
    roster = entrants(["a", "b"])
    assert len(build_tiers(roster, {("a", "b"): prediction(2.0, 0.30)}).tiers) == 1
    assert len(build_tiers(roster, {("a", "b"): prediction(2.0001, 0.10)}).tiers) == 2
    assert len(build_tiers(roster, {("a", "b"): prediction(0.1, 0.3001)}).tiers) == 2


def test_operator_limits_change_placement_without_changing_prediction():
    predictions = {("a", "b"): prediction(2.2, 0.31)}
    roster = entrants(["a", "b"])
    assert len(build_tiers(roster, predictions).tiers) == 2
    assert len(build_tiers(roster, predictions, TierPolicy(2.5, 0.35)).tiers) == 1
    assert predictions[("a", "b")].expected_margin == 2.2


def test_low_outcome_confidence_does_not_exclude_well_matched_teams():
    value = SimpleNamespace(expected_margin=0.1, blowout_4plus_probability=0.1, confidence="low")
    result = build_tiers(entrants(["a", "b"]), {("a", "b"): value})
    assert memberships(result) == [{"a", "b"}]
    assert result.review == {}
    assert result.warnings == (
        "1/1 matchups have low outcome confidence. This can reflect closely matched teams; "
        "it is separate from missing team evidence.",
    )


def test_review_entrants_are_retained_explicitly_not_treated_as_weakest():
    roster = [TierEntrant("unknown", "Unknown", review_reason="No published ranking"),
              TierEntrant("sparse", "Sparse", 0.9, "Only two scored games"), TierEntrant("known", "Known", 0.4)]
    result = build_tiers(roster, {})
    assert memberships(result) == [{"known"}]
    assert result.ordered_ids == ("known",)
    assert result.review == {"sparse": "Only two scored games", "unknown": "No published ranking"}


def test_powerscore_remains_the_seed_order_when_compare_disagrees():
    roster = [TierEntrant("a", "Higher score", 0.7), TierEntrant("b", "Stronger prediction", 0.5)]
    result = build_tiers(roster, {("a", "b"): prediction(-4, 0.7)})
    assert result.ordered_ids == ("a", "b")
    assert result.boundaries == (
        "Tier 1 / Tier 2: Ranking/matchup order conflict; review the boundary. Upper tier favored in 0/1 "
        "matchups, with an average expected edge of -4.00 goals; 1/1 exceed the within-tier limits.",
    )
    assert result.borderline == {}
    assert any("strength-order exception" in warning for warning in result.warnings)


def test_every_automatic_tier_preserves_monotonic_powerscore_order():
    ids = ["a", "b", "c", "d", "e"]
    roster = [
        TierEntrant(key, f"Team {key}", score)
        for key, score in zip(ids, [0.9, 0.8, 0.7, 0.6, 0.5], strict=True)
    ]
    result = build_tiers(roster, matrix(ids, {key: index for index, key in enumerate(ids)}))

    assert result.ordered_ids == tuple(ids)
    assert [next(team.power_score for team in roster if team.entrant_id == key) for key in result.ordered_ids] == [
        0.9, 0.8, 0.7, 0.6, 0.5,
    ]


def test_powerscore_orders_teams_within_the_same_tier():
    roster = [TierEntrant("a", "Higher score", 0.7), TierEntrant("b", "Stronger prediction", 0.5)]
    result = build_tiers(roster, {("a", "b"): prediction(-1, 0.1)})
    assert result.ordered_ids == ("a", "b")


def test_shuffling_entrants_and_pair_orientation_is_deterministic():
    roster = entrants(["a", "b", "c", "d"])
    predictions = matrix(["a", "b", "c", "d"], {"a": 5, "b": 4, "c": 1, "d": 0})
    reversed_predictions = {(b, a): replace(value, expected_margin=-value.expected_margin)
                            for (a, b), value in reversed(list(predictions.items()))}
    assert build_tiers(roster, predictions) == build_tiers(list(reversed(roster)), reversed_predictions)


def test_minimum_groups_avoids_greedy_chaining_and_fixed_sizes():
    ids = ["a", "b", "c", "d", "e"]
    strengths = {"a": 4, "b": 3, "c": 2, "d": 1, "e": 0}
    result = build_tiers(entrants(ids), matrix(ids, strengths))
    assert len(result.tiers) == 2
    assert sorted(len(tier.entrant_ids) for tier in result.tiers) == [2, 3]
    assert all(tier.max_expected_margin <= 2 for tier in result.tiers)


def test_safe_partition_uses_the_clearest_strength_break():
    ids = ["a", "b", "c", "d"]
    roster = [
        TierEntrant(key, f"Team {key}", score)
        for key, score in zip(ids, [0.9, 0.8, 0.85, 0.3], strict=True)
    ]
    predictions = {
        ("a", "b"): prediction(0.2),
        ("a", "c"): prediction(0.4),
        ("a", "d"): prediction(3.0),
        ("b", "c"): prediction(0.2),
        ("b", "d"): prediction(3.0),
        ("c", "d"): prediction(0.2),
    }

    result = build_tiers(roster, predictions)

    assert memberships(result) == [{"a", "b", "c"}, {"d"}]
    assert result.ordered_ids == ("a", "c", "b", "d")


def test_manual_unsafe_merge_reports_risk_and_named_pair():
    result = build_tiers(entrants(["a", "b"]), {("a", "b"): prediction(4, 0.6)}, manual_groups=[["a", "b"]])
    assert memberships(result) == [{"a", "b"}]
    assert result.tiers[0].max_expected_margin == 4
    assert result.tiers[0].max_blowout_probability == 0.6
    assert result.tiers[0].worst_pair == ("a", "b")
    assert result.warnings == (
        "Tier 1 exceeds the matchup limits: up to 4.00 expected goals and 60% chance of a four-goal margin. "
        "Review Team a vs Team b.",
    )


def test_manual_tiers_preserve_the_operators_explicit_order():
    result = build_tiers(entrants(["a", "b"]), {("a", "b"): prediction(4)}, manual_groups=[["b"], ["a"]])
    assert result.ordered_ids == ("b", "a")
    assert [tier.number for tier in result.tiers] == [1, 2]
    assert any("strength-order exception" in warning for warning in result.warnings)


def test_saving_unchanged_suggested_groups_preserves_powerscore_order():
    roster = [TierEntrant("a", "Higher score", 0.7), TierEntrant("b", "Stronger prediction", 0.5)]
    predictions = {("a", "b"): prediction(-4, 0.7)}
    suggested = build_tiers(roster, predictions)

    saved = build_tiers(roster, predictions, manual_groups=[tier.entrant_ids for tier in suggested.tiers])

    assert saved == suggested
    assert saved.ordered_ids == ("a", "b")


def test_manual_nonhierarchical_assignment_reports_order_exception():
    ids = ["a", "b", "c", "d"]
    result = build_tiers(entrants(ids), matrix(ids, {"a": 6, "b": 4, "c": 1, "d": 0}),
                         manual_groups=[["a", "d"], ["b", "c"]])
    assert any("strength-order exception" in warning for warning in result.warnings)
    assert result.borderline == {}


def test_matchup_cycle_reports_an_order_exception_across_nonadjacent_tiers():
    predictions = {("a", "b"): prediction(4), ("b", "c"): prediction(4), ("a", "c"): prediction(-4)}
    result = build_tiers(entrants(["a", "b", "c"]), predictions)
    assert memberships(result) == [{"a"}, {"b"}, {"c"}]
    assert any("Tiers 1 and 3 have a strength-order exception" in warning for warning in result.warnings)


@pytest.mark.parametrize("groups", [[["a"]], [["a", "a", "b"]], [["a", "b", "c"]], [[], ["a", "b"]]])
def test_manual_assignment_must_partition_every_eligible_entrant(groups):
    with pytest.raises(ValueError, match="Manual tiers"):
        build_tiers(entrants(["a", "b"]), {("a", "b"): prediction(0)}, manual_groups=groups)


def test_missing_peer_fails_actionably_instead_of_appearing_safe():
    with pytest.raises(ValueError, match="Missing Compare prediction for a vs c; rebuild"):
        build_tiers(entrants(["a", "b", "c"]), {("a", "b"): prediction(0)})


@pytest.mark.parametrize(
    "margin,blowout", [(float("nan"), 0.1), (float("inf"), 0.1), (0, float("nan")), (0, -0.1), (0, 1.1)]
)
def test_invalid_prediction_values_fail(margin, blowout):
    with pytest.raises(ValueError):
        build_tiers(entrants(["a", "b"]), {("a", "b"): prediction(margin, blowout)})


def test_inconsistent_reverse_margin_fails():
    with pytest.raises(ValueError, match="Inconsistent forward/reverse"):
        build_tiers(entrants(["a", "b"]), {("a", "b"): prediction(2), ("b", "a"): prediction(2)})


def test_inconsistent_reverse_blowout_fails():
    with pytest.raises(ValueError, match="Inconsistent forward/reverse"):
        build_tiers(entrants(["a", "b"]), {("a", "b"): prediction(2, 0.1), ("b", "a"): prediction(-2, 0.2)})


@pytest.mark.parametrize("margin,blowout", [(0, 0.3), (-1, 0.3), (float("inf"), 0.3), (float("nan"), 0.3),
                                           (2, 0), (2, -0.1), (2, 1.1), (2, float("nan"))])
def test_policy_must_be_finite_and_in_valid_range(margin, blowout):
    with pytest.raises(ValueError):
        TierPolicy(margin, blowout)


def test_empty_and_review_only_cohorts_do_not_invent_tiers():
    result = build_tiers([], {})
    assert result.tiers == ()
    assert result.warnings == ()
    review = build_tiers([TierEntrant("a", "A", review_reason="Unresolved")], {})
    assert review.tiers == ()
    assert review.review == {"a": "Unresolved"}


def test_duplicate_id_and_nonfinite_powerscore_fail():
    with pytest.raises(ValueError, match="Duplicate entrant ID"):
        build_tiers(entrants(["a", "a"]), {})
    with pytest.raises(ValueError, match="Non-finite PowerScore"):
        build_tiers([TierEntrant("a", "A", float("nan"))], {})


def test_cheat_sheet_carries_each_entrant_status_and_rejects_an_unknown_one():
    roster = [TierEntrant("a", "A", 0.5),
              TierEntrant("b", "B", None, "No rating yet", review_status="No current rating")]
    assert build_cheat_sheet_analysis(roster, {}).placement_status == {"a": "Seeded", "b": "No current rating"}
    with pytest.raises(ValueError, match="Unknown placement status"):
        build_cheat_sheet_analysis([replace(roster[1], review_status="Seeded")], {})
