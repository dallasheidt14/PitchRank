"""Automatic MatchBalance format-library generation and recommendation policy."""

from dataclasses import replace
from itertools import combinations, product

import pytest

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_flight_suggestions import (
    PRIMARY_SELECTED,
    PRIMARY_SELECTED_FOR_SUBSET,
    PROVISIONAL_EVIDENCE,
    SEARCH_INCOMPLETE,
    UNSUPPORTED_STRUCTURE,
    generate_candidate_structures,
    suggest_automatic_flights,
)
from src.tournaments.seeding_format_library import (
    load_format_library,
    resolve_format_profile,
    validate_format_library,
)
from src.tournaments.seeding_group_assessment import GroupTeam
from src.tournaments.seeding_plan_assessment import UnassignedEntrant
from src.tournaments.seeding_tiers import TierPolicy


def _prediction(
    *, absolute_goal_difference: float = 1.0, blowout: float = 0.10
) -> ComparePrediction:
    return ComparePrediction(
        predicted_winner="team_a",
        win_probability_a=0.60,
        win_probability_b=0.25,
        draw_probability=0.15,
        expected_score={"teamA": 2, "teamB": 1},
        expected_margin=0.4,
        expected_absolute_goal_difference=absolute_goal_difference,
        blowout_4plus_probability=blowout,
        confidence="high",
        confidence_score=0.80,
    )


def _matrix(ids: list[str]) -> dict[tuple[str, str], ComparePrediction]:
    return {pair: _prediction() for pair in combinations(ids, 2)}


def _teams(
    ids: list[str], *, limited: set[str] | None = None
) -> dict[str, GroupTeam]:
    limited = limited or set()
    return {
        entrant_id: GroupTeam(
            entrant_id=entrant_id,
            team_name=f"Team {entrant_id}",
            team_id_master=f"master-{entrant_id}",
            seed=index,
            power_score=0.90 - index / 100,
            limited_history=entrant_id in limited,
            evidence_game_count=4 if entrant_id in limited else 20,
        )
        for index, entrant_id in enumerate(ids, start=1)
    }


def _library_profile():
    library = load_format_library()
    return library, resolve_format_profile(library)


def _plan(suggestion, sizes: tuple[int, ...]):
    return next(
        item
        for item in suggestion.assessment.plans
        if item.flight_sizes == sizes
    )


def test_checked_in_format_library_is_versioned_and_valid():
    library, profile = _library_profile()
    validation = validate_format_library(library)

    assert library.schema_version == 1
    assert library.library_version == "1.0.0"
    assert validation.valid is True
    assert profile.profile_id == "matchbalance-default-v1"
    assert profile.recommendation_policy_id == (
        "matchbalance-compact-within-policy-v1"
    )
    assert library.source_documents[0].sha256 == (
        "0b1a0e2f794623b76673ba670a5c97b372088aee94111096a436292449a2fdc9"
    )
    assert all(
        sum(template.pool_sizes) == template.team_count
        for template in library.templates
    )
    assert tuple(
        sorted(
            {
                library.templates_by_id[item].team_count
                for item in profile.template_ids
            }
        )
    ) == (3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16)


def test_inconsistent_and_ambiguous_source_entries_never_enter_default_profile():
    library, profile = _library_profile()
    issue_status = {item.issue_id: item.status for item in library.source_issues}

    assert issue_status["weston-10-team-total-inconsistent"] == "blocked"
    assert issue_status["consolidated-five-team-bundled-alternative"] == "blocked"
    assert issue_status["consolidated-eight-team-bundled-advancement"] == (
        "blocked"
    )
    assert issue_status["arizona-large-count-mechanics-not-reproduced"] == (
        "reference_only"
    )
    reference_eleven = library.templates_by_id["mb-reference-usys-pc-11-v1"]
    assert reference_eleven.availability_status == "reference_only"
    assert reference_eleven.template_id not in profile.template_ids


def test_three_team_variant_records_least_advancing_team_game_minimum():
    library, profile = _library_profile()
    template = library.templates_by_id["mb-default-usys-pc-03-v1"]

    assert template.team_count == 3
    assert template.pool_sizes == (3,)
    assert template.minimum_guaranteed_games_per_team == 2
    assert template.maximum_possible_games_per_team == 3
    assert template.template_id in profile.template_ids


def test_generator_discovers_every_small_exact_cover_without_nearest_fallback():
    library, profile = _library_profile()

    six = generate_candidate_structures(6, library, profile)
    seven = generate_candidate_structures(7, library, profile)
    two = generate_candidate_structures(2, library, profile)

    assert six.structures == ((6,), (3, 3))
    assert six.total_distinct_structure_count == 2
    assert any(
        item.template_id == "mb-reference-usys-pc-11-v1"
        for item in six.excluded_templates
    )
    assert seven.structures == ((7,), (3, 4), (4, 3))
    assert seven.total_distinct_structure_count == 3
    assert two.unsupported is True
    assert two.structures == ()
    assert "No nearest-size template was substituted" in two.reason


def test_small_generation_matches_independent_exhaustive_oracle():
    library, profile = _library_profile()
    result = generate_candidate_structures(12, library, profile)
    sizes = (3, 4, 5, 6, 7, 8, 9, 10, 12)
    expected = {
        values
        for flight_count in range(1, 5)
        for values in product(sizes, repeat=flight_count)
        if sum(values) == 12
    }

    assert set(result.structures) == expected
    assert result.total_distinct_structure_count == len(expected)
    assert all(sum(item) == 12 and min(item) >= 3 for item in result.structures)


def test_one_profile_resolves_consistently_across_division_sizes():
    library, profile = _library_profile()

    six = generate_candidate_structures(6, library, profile)
    seven = generate_candidate_structures(7, library, profile)

    assert profile.profile_id == "matchbalance-default-v1"
    assert next(
        item.preferred_template_id
        for item in six.size_template_options
        if item.team_count == 6
    ) == "mb-default-usys-pc-06-v1"
    assert next(
        item.preferred_template_id
        for item in seven.size_template_options
        if item.team_count == 7
    ) == "mb-default-usys-pc-07-v1"


def test_event_wide_minimum_game_requirement_excludes_incompatible_variants():
    library, profile = _library_profile()
    profile = replace(profile, required_minimum_games_per_team=3)

    result = generate_candidate_structures(7, library, profile)

    assert result.unsupported is True
    excluded = {item.template_id: item.reason for item in result.excluded_templates}
    assert "mb-default-usys-pc-03-v1" in excluded
    assert "below the profile requirement of 3" in excluded[
        "mb-default-usys-pc-03-v1"
    ]
    assert "mb-default-usys-pc-07-v1" in excluded


def test_template_aliases_do_not_duplicate_membership_structures():
    library, profile = _library_profile()
    base = library.templates_by_id["mb-default-usys-pc-06-v1"]
    alias = replace(
        base,
        template_id="test-six-team-format-alternative",
        advancement_description="Another exact six-team operational variant.",
    )
    library = replace(library, templates=(*library.templates, alias))
    profile = replace(
        profile,
        template_ids=(*profile.template_ids, alias.template_id),
    )

    result = generate_candidate_structures(6, library, profile)
    size_six = next(
        item for item in result.size_template_options if item.team_count == 6
    )

    assert result.structures == ((6,), (3, 3))
    assert size_six.compatible_template_ids == (
        "mb-default-usys-pc-06-v1",
        "test-six-team-format-alternative",
    )


def test_larger_passing_flight_is_preferred_to_unnecessary_smaller_flights():
    library, profile = _library_profile()
    ids = list("abcdef")

    result = suggest_automatic_flights(
        ids,
        _matrix(ids),
        TierPolicy(),
        _teams(ids),
        library,
        profile,
    )

    assert result.status == PRIMARY_SELECTED
    assert result.primary_plan_id is not None
    assert _plan(result, (6,)).plan_id == result.primary_plan_id
    assert _plan(result, (3, 3)).all_pair_projected_fit_passed is True


def test_risky_large_flight_does_not_beat_passing_smaller_flights():
    library, profile = _library_profile()
    ids = list("abcdef")
    predictions = _matrix(ids)
    predictions[("c", "d")] = _prediction(
        absolute_goal_difference=2.4, blowout=0.35
    )

    result = suggest_automatic_flights(
        ids,
        predictions,
        TierPolicy(),
        _teams(ids),
        library,
        profile,
    )

    assert _plan(result, (6,)).all_pair_projected_fit_passed is False
    assert _plan(result, (3, 3)).all_pair_projected_fit_passed is True
    assert result.primary_plan_id == _plan(result, (3, 3)).plan_id


def test_missing_prediction_cannot_make_a_large_plan_eligible():
    library, profile = _library_profile()
    ids = list("abcdef")
    predictions = _matrix(ids)
    del predictions[("c", "d")]

    result = suggest_automatic_flights(
        ids,
        predictions,
        TierPolicy(),
        _teams(ids),
        library,
        profile,
    )

    large = _plan(result, (6,))
    assert large.prediction_complete is False
    assert large.all_pair_projected_fit_passed is False
    assert result.primary_plan_id == _plan(result, (3, 3)).plan_id
    assert large.plan_id in result.incomplete_prediction_plan_ids


def test_limited_history_pass_remains_provisional():
    library, profile = _library_profile()
    ids = list("abcdef")

    result = suggest_automatic_flights(
        ids,
        _matrix(ids),
        TierPolicy(),
        _teams(ids, limited={"c"}),
        library,
        profile,
    )

    assert result.primary_plan_id == _plan(result, (6,)).plan_id
    assert result.primary_evidence_status == PROVISIONAL_EVIDENCE
    assert _plan(result, (6,)).limited_history_pairing_count == 5


def test_lower_risk_additional_flights_survive_primary_selection():
    library, profile = _library_profile()
    ids = list("abcdef")
    predictions = _matrix(ids)
    for first in ids[:3]:
        for second in ids[3:]:
            predictions[(first, second)] = _prediction(
                absolute_goal_difference=1.9, blowout=0.29
            )

    result = suggest_automatic_flights(
        ids,
        predictions,
        TierPolicy(),
        _teams(ids),
        library,
        profile,
    )

    assert result.primary_plan_id == _plan(result, (6,)).plan_id
    alternative = next(
        item for item in result.useful_alternatives if item.flight_sizes == (3, 3)
    )
    assert alternative.kind == "lower_raw_modeled_risk_with_additional_flights"
    assert alternative.additional_flight_count == 1
    assert alternative.worst_matchup_cost_delta < 0
    assert alternative.pair_weighted_average_matchup_cost_delta < 0
    assert len(alternative.reasons) == 3


def test_same_flight_count_worst_vs_average_tradeoff_survives_selection():
    library, profile = _library_profile()
    ids = list("abcdefgh")
    predictions = {
        pair: _prediction(absolute_goal_difference=0.5)
        for pair in combinations(ids, 2)
    }
    four_four_pairs = {
        *combinations(ids[:4], 2),
        *combinations(ids[4:], 2),
    }
    for pair in four_four_pairs:
        predictions[pair] = _prediction(absolute_goal_difference=1.5)
    predictions[("a", "e")] = _prediction(absolute_goal_difference=1.7)
    predictions[("d", "h")] = _prediction(absolute_goal_difference=1.8)
    predictions[("a", "h")] = _prediction(
        absolute_goal_difference=2.4, blowout=0.35
    )

    result = suggest_automatic_flights(
        ids,
        predictions,
        TierPolicy(),
        _teams(ids),
        library,
        profile,
    )

    assert result.primary_plan_id == _plan(result, (4, 4)).plan_id
    tradeoff = next(
        item for item in result.useful_alternatives if item.flight_sizes == (3, 5)
    )
    assert tradeoff.kind == "same_flight_count_worst_vs_average_tradeoff"
    assert tradeoff.additional_flight_count == 0
    assert tradeoff.worst_matchup_cost_delta > 0
    assert tradeoff.pair_weighted_average_matchup_cost_delta < 0


def test_eight_team_flight_is_assessed_as_one_complete_competitive_flight():
    library, profile = _library_profile()
    ids = list("abcdefgh")

    result = suggest_automatic_flights(
        ids,
        _matrix(ids),
        TierPolicy(),
        _teams(ids),
        library,
        profile,
    )
    eight = _plan(result, (8,))
    formats = next(
        item for item in result.format_options if item.plan_id == eight.plan_id
    )

    assert eight.required_unique_pairing_count == 28
    assert formats.flights[0].team_count == 8
    template = library.templates_by_id[formats.flights[0].preferred_template_id]
    assert template.pool_sizes == (4, 4)


def test_search_limit_is_explicit_and_prevents_global_primary_claim():
    library, profile = _library_profile()
    ids = [f"t{index}" for index in range(18)]

    result = suggest_automatic_flights(
        ids,
        _matrix(ids),
        TierPolicy(),
        _teams(ids),
        library,
        profile,
        max_candidate_structures=1,
    )

    assert result.generation.total_distinct_structure_count == 180
    assert result.generation.generated_structure_count == 1
    assert result.generation.search_complete is False
    assert result.status == SEARCH_INCOMPLETE
    assert result.primary_plan_id is None
    assert result.best_evaluated_plan_id is not None


def test_runtime_limit_cannot_exceed_event_profile_safeguard():
    library, profile = _library_profile()

    with pytest.raises(ValueError, match="computational safeguard"):
        generate_candidate_structures(
            18,
            library,
            profile,
            max_candidate_structures=profile.max_candidate_structures + 1,
        )


def test_unassigned_entrant_keeps_subset_semantics_visible():
    library, profile = _library_profile()
    ids = list("abcdefg")
    assigned = ids[:6]

    result = suggest_automatic_flights(
        assigned,
        _matrix(ids),
        TierPolicy(),
        _teams(ids),
        library,
        profile,
        accepted_entrant_ids=ids,
        unassigned_entrants=(UnassignedEntrant("g", "Saved manual hold."),),
    )

    assert result.status == PRIMARY_SELECTED_FOR_SUBSET
    primary = next(
        item
        for item in result.assessment.plans
        if item.plan_id == result.primary_plan_id
    )
    assert primary.accepted_field_coverage.plan_for_assigned_subset is True
    assert primary.accepted_field_coverage.every_accepted_entrant_accounted_for is True


def test_same_inputs_produce_identical_suggestion_objects():
    library, profile = _library_profile()
    ids = list("abcdefg")
    inputs = (ids, _matrix(ids), TierPolicy(), _teams(ids), library, profile)

    first = suggest_automatic_flights(*inputs)
    second = suggest_automatic_flights(*inputs)

    assert first == second


def test_unsupported_structure_is_explicit():
    library, profile = _library_profile()
    ids = ["a", "b"]

    result = suggest_automatic_flights(
        ids,
        _matrix(ids),
        TierPolicy(),
        _teams(ids),
        library,
        profile,
    )

    assert result.status == UNSUPPORTED_STRUCTURE
    assert result.assessment is None
    assert result.primary_plan_id is None


def test_repeated_membership_uses_one_group_assessment(monkeypatch):
    from src.tournaments import seeding_plan_assessment as module
    from src.tournaments.seeding_plan_assessment import (
        APPROVED_ALTERNATIVES,
        assess_permitted_plans,
        enumerate_arrangements,
    )

    ids = list("abcdefgh")
    original = module.assess_group
    calls: list[tuple[str, ...]] = []

    def counted(entrant_ids, predictions, policy, team_metadata):
        calls.append(tuple(entrant_ids))
        return original(entrant_ids, predictions, policy, team_metadata)

    monkeypatch.setattr(module, "assess_group", counted)
    enumeration = enumerate_arrangements(
        APPROVED_ALTERNATIVES,
        [[4, 4], [4, 2, 2]],
        8,
    )
    assess_permitted_plans(
        enumeration,
        ids,
        _matrix(ids),
        TierPolicy(),
        _teams(ids),
    )

    assert calls.count(("a", "b", "c", "d")) == 1
