"""Automatic, profile-constrained MatchBalance flight suggestions.

This module keeps four concerns separate:

* the format library says which exact flight sizes and pool variants exist;
* the generator finds exact covers of the fixed selected order;
* the existing complete-plan evaluator supplies matchup evidence;
* a named MatchBalance product policy selects or declines a primary suggestion.

It never changes PowerScore, seed order, boundary classifications, or policy limits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_format_library import (
    FormatLibrary,
    FormatProfile,
    FormatTemplate,
    MatchBalanceRecommendationPolicy,
    profile_templates,
)
from src.tournaments.seeding_group_assessment import GroupTeam
from src.tournaments.seeding_plan_assessment import (
    APPROVED_ALTERNATIVES,
    FlightPlanAssessment,
    FlightPlanSetAssessment,
    UnassignedEntrant,
    assess_permitted_plans,
    enumerate_arrangements,
)
from src.tournaments.seeding_tiers import TierPolicy

PRIMARY_SELECTED = "primary_suggestion_selected"
PRIMARY_SELECTED_FOR_SUBSET = "primary_suggestion_for_assigned_subset"
UNSUPPORTED_STRUCTURE = "unsupported_structure"
SEARCH_INCOMPLETE = "search_incomplete_review_required"
NO_WITHIN_POLICY_PLAN = "no_complete_within_policy_arrangement"
INCOMPLETE_PREDICTIONS = "incomplete_predictions_review_required"

ESTABLISHED_EVIDENCE = "established_evidence"
PROVISIONAL_EVIDENCE = "provisional_due_to_history"
NO_PRIMARY_EVIDENCE = "not_applicable_without_primary_suggestion"


@dataclass(frozen=True)
class SizeTemplateOptions:
    team_count: int
    compatible_template_ids: tuple[str, ...]
    preferred_template_id: str


@dataclass(frozen=True)
class ExcludedTemplate:
    template_id: str
    team_count: int
    reason: str


@dataclass(frozen=True)
class CandidateStructureGeneration:
    assigned_team_count: int
    supported_flight_sizes: tuple[int, ...]
    size_template_options: tuple[SizeTemplateOptions, ...]
    excluded_templates: tuple[ExcludedTemplate, ...]
    structures: tuple[tuple[int, ...], ...]
    total_distinct_structure_count: int
    generated_structure_count: int
    max_candidate_structures: int
    search_complete: bool
    unsupported: bool
    reason: str


@dataclass(frozen=True)
class FlightFormatOptions:
    flight_number: int
    start_order_position: int
    end_order_position: int
    team_count: int
    entrant_ids: tuple[str, ...]
    preferred_template_id: str
    compatible_template_ids: tuple[str, ...]


@dataclass(frozen=True)
class PlanFormatOptions:
    plan_id: str
    flights: tuple[FlightFormatOptions, ...]


@dataclass(frozen=True)
class RecommendationAlternative:
    plan_id: str
    flight_sizes: tuple[int, ...]
    kind: str
    additional_flight_count: int
    worst_matchup_cost_delta: float
    pair_weighted_average_matchup_cost_delta: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class AutomaticFlightSuggestion:
    profile: FormatProfile
    recommendation_policy: MatchBalanceRecommendationPolicy
    generation: CandidateStructureGeneration
    assessment: FlightPlanSetAssessment | None
    status: str
    primary_plan_id: str | None
    best_evaluated_plan_id: str | None
    primary_evidence_status: str
    selection_reason: str
    format_options: tuple[PlanFormatOptions, ...]
    useful_alternatives: tuple[RecommendationAlternative, ...]
    compromise_plan_ids: tuple[str, ...]
    incomplete_prediction_plan_ids: tuple[str, ...]
    operational_feasibility_note: str


def _compatible_templates(
    library: FormatLibrary, profile: FormatProfile
) -> tuple[tuple[FormatTemplate, ...], tuple[ExcludedTemplate, ...]]:
    compatible: list[FormatTemplate] = []
    excluded: list[ExcludedTemplate] = []
    profile_template_ids = set(profile.template_ids)
    for template in library.templates:
        if template.template_id in profile_template_ids:
            continue
        excluded.append(
            ExcludedTemplate(
                template.template_id,
                template.team_count,
                template.blocked_reason
                or "The template is not enabled by the effective event-wide profile.",
            )
        )
    required_games = profile.required_minimum_games_per_team
    for template in profile_templates(library, profile):
        if required_games is None:
            compatible.append(template)
            continue
        guaranteed = template.minimum_guaranteed_games_per_team
        if guaranteed is None:
            excluded.append(
                ExcludedTemplate(
                    template.template_id,
                    template.team_count,
                    "The profile requires a known minimum-game guarantee, but this "
                    "template's guarantee is unknown.",
                )
            )
        elif guaranteed < required_games:
            excluded.append(
                ExcludedTemplate(
                    template.template_id,
                    template.team_count,
                    f"The template guarantees {guaranteed} game(s), below the "
                    f"profile requirement of {required_games}.",
                )
            )
        else:
            compatible.append(template)
    return tuple(compatible), tuple(excluded)


def _ordered_composition_count(total: int, sizes: tuple[int, ...]) -> int:
    counts = [0] * (total + 1)
    counts[0] = 1
    for subtotal in range(1, total + 1):
        counts[subtotal] = sum(
            counts[subtotal - size] for size in sizes if size <= subtotal
        )
    return counts[total]


def _generate_for_flight_count(
    total: int,
    sizes: tuple[int, ...],
    flight_count: int,
    limit: int,
) -> tuple[tuple[int, ...], ...]:
    result: list[tuple[int, ...]] = []
    current: list[int] = []
    minimum = min(sizes)
    maximum = max(sizes)

    def visit(remaining: int, remaining_flights: int) -> None:
        if len(result) >= limit:
            return
        if remaining_flights == 0:
            if remaining == 0:
                result.append(tuple(current))
            return
        if remaining < remaining_flights * minimum:
            return
        if remaining > remaining_flights * maximum:
            return
        for size in sizes:
            if size > remaining:
                break
            current.append(size)
            visit(remaining - size, remaining_flights - 1)
            current.pop()
            if len(result) >= limit:
                return

    visit(total, flight_count)
    return tuple(result)


def generate_candidate_structures(
    assigned_team_count: int,
    library: FormatLibrary,
    profile: FormatProfile,
    *,
    max_candidate_structures: int | None = None,
) -> CandidateStructureGeneration:
    """Generate every permitted ordered exact cover, bounded explicitly."""
    if (
        isinstance(assigned_team_count, bool)
        or not isinstance(assigned_team_count, int)
        or assigned_team_count < 2
    ):
        raise ValueError("Automatic flight generation needs at least two assigned teams")
    limit = (
        profile.max_candidate_structures
        if max_candidate_structures is None
        else max_candidate_structures
    )
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("The automatic candidate limit must be a positive integer")
    if limit > profile.max_candidate_structures:
        raise ValueError(
            "The requested candidate limit exceeds the effective profile's "
            "computational safeguard"
        )

    compatible, excluded = _compatible_templates(library, profile)
    templates_by_size: dict[int, list[FormatTemplate]] = {}
    for template in compatible:
        templates_by_size.setdefault(template.team_count, []).append(template)
    sizes = tuple(sorted(templates_by_size))
    size_options = []
    for size in sizes:
        template_ids = tuple(item.template_id for item in templates_by_size[size])
        preferred = profile.preferred_template_ids_by_team_count.get(size)
        if preferred not in template_ids:
            preferred = template_ids[0]
        size_options.append(SizeTemplateOptions(size, template_ids, preferred))

    total = _ordered_composition_count(assigned_team_count, sizes) if sizes else 0
    if total == 0:
        supported = ", ".join(str(item) for item in sizes) or "none"
        return CandidateStructureGeneration(
            assigned_team_count=assigned_team_count,
            supported_flight_sizes=sizes,
            size_template_options=tuple(size_options),
            excluded_templates=excluded,
            structures=(),
            total_distinct_structure_count=0,
            generated_structure_count=0,
            max_candidate_structures=limit,
            search_complete=True,
            unsupported=True,
            reason=(
                f"No exact cover of {assigned_team_count} assigned teams exists using "
                f"the effective profile's supported flight sizes: {supported}. No "
                "nearest-size template was substituted."
            ),
        )

    structures: list[tuple[int, ...]] = []
    min_flights = math.ceil(assigned_team_count / max(sizes))
    max_flights = assigned_team_count // min(sizes)
    for flight_count in range(min_flights, max_flights + 1):
        remaining_limit = limit - len(structures)
        if remaining_limit <= 0:
            break
        structures.extend(
            _generate_for_flight_count(
                assigned_team_count,
                sizes,
                flight_count,
                remaining_limit,
            )
        )
    complete = len(structures) == total
    if complete:
        reason = (
            f"Generated all {total} permitted ordered exact-cover structure(s) for "
            f"{assigned_team_count} assigned teams."
        )
    else:
        reason = (
            f"The profile permits {total} ordered exact-cover structure(s), but the "
            f"explicit limit is {limit}; only {len(structures)} were generated."
        )
    return CandidateStructureGeneration(
        assigned_team_count=assigned_team_count,
        supported_flight_sizes=sizes,
        size_template_options=tuple(size_options),
        excluded_templates=excluded,
        structures=tuple(structures),
        total_distinct_structure_count=total,
        generated_structure_count=len(structures),
        max_candidate_structures=limit,
        search_complete=complete,
        unsupported=False,
        reason=reason,
    )


def _plan_boundary_key(plan: FlightPlanAssessment) -> tuple[int, ...]:
    return tuple(flight.end_order_position for flight in plan.flights[:-1])


def _plan_format_key(
    plan: FlightPlanAssessment, options_by_size: Mapping[int, SizeTemplateOptions]
) -> tuple[str, ...]:
    return tuple(
        options_by_size[flight.requested_size].preferred_template_id
        for flight in plan.flights
    )


def _metric(plan: FlightPlanAssessment, attribute: str) -> float:
    value = getattr(plan, attribute)
    return math.inf if value is None else float(value)


def _isclose(
    first: float,
    second: float,
    policy: MatchBalanceRecommendationPolicy,
) -> bool:
    return math.isclose(
        first,
        second,
        rel_tol=policy.numerical_tie_relative_tolerance,
        abs_tol=policy.numerical_tie_absolute_tolerance,
    )


def _strictly_lower(
    first: float,
    second: float,
    policy: MatchBalanceRecommendationPolicy,
) -> bool:
    return first < second and not _isclose(first, second, policy)


def _select_by_default_policy(
    plans: Sequence[FlightPlanAssessment],
    policy: MatchBalanceRecommendationPolicy,
    options_by_size: Mapping[int, SizeTemplateOptions],
) -> FlightPlanAssessment | None:
    candidates = tuple(plans)
    if not candidates:
        return None
    minimum_flights = min(len(item.flights) for item in candidates)
    candidates = tuple(
        item for item in candidates if len(item.flights) == minimum_flights
    )
    minimum_worst = min(_metric(item, "worst_matchup_cost") for item in candidates)
    candidates = tuple(
        item
        for item in candidates
        if _isclose(_metric(item, "worst_matchup_cost"), minimum_worst, policy)
    )
    minimum_average = min(
        _metric(item, "pair_weighted_average_matchup_cost")
        for item in candidates
    )
    candidates = tuple(
        item
        for item in candidates
        if _isclose(
            _metric(item, "pair_weighted_average_matchup_cost"),
            minimum_average,
            policy,
        )
    )
    return min(
        candidates,
        key=lambda item: (
            _plan_boundary_key(item),
            _plan_format_key(item, options_by_size),
            item.plan_id,
        ),
    )


def _format_options(
    assessment: FlightPlanSetAssessment,
    generation: CandidateStructureGeneration,
) -> tuple[PlanFormatOptions, ...]:
    options_by_size = {
        item.team_count: item for item in generation.size_template_options
    }
    result = []
    for plan in assessment.plans:
        result.append(
            PlanFormatOptions(
                plan_id=plan.plan_id,
                flights=tuple(
                    FlightFormatOptions(
                        flight_number=flight.flight_number,
                        start_order_position=flight.start_order_position,
                        end_order_position=flight.end_order_position,
                        team_count=flight.requested_size,
                        entrant_ids=flight.entrant_ids,
                        preferred_template_id=options_by_size[
                            flight.requested_size
                        ].preferred_template_id,
                        compatible_template_ids=options_by_size[
                            flight.requested_size
                        ].compatible_template_ids,
                    )
                    for flight in plan.flights
                ),
            )
        )
    return tuple(result)


def _dominates_compromise(
    first: FlightPlanAssessment,
    second: FlightPlanAssessment,
    policy: MatchBalanceRecommendationPolicy,
) -> bool:
    first_metrics = (
        float(len(first.flights)),
        float(first.violating_pairing_count),
        _metric(first, "worst_matchup_cost"),
        _metric(first, "pair_weighted_average_matchup_cost"),
    )
    second_metrics = (
        float(len(second.flights)),
        float(second.violating_pairing_count),
        _metric(second, "worst_matchup_cost"),
        _metric(second, "pair_weighted_average_matchup_cost"),
    )
    no_worse = all(
        left < right or _isclose(left, right, policy)
        for left, right in zip(first_metrics, second_metrics, strict=True)
    )
    better = any(
        _strictly_lower(left, right, policy)
        for left, right in zip(first_metrics, second_metrics, strict=True)
    )
    return no_worse and better


def _compromise_plan_ids(
    plans: Sequence[FlightPlanAssessment],
    policy: MatchBalanceRecommendationPolicy,
) -> tuple[str, ...]:
    complete = tuple(
        item for item in plans if item.structural.valid and item.prediction_complete
    )
    return tuple(
        item.plan_id
        for item in complete
        if not any(
            other.plan_id != item.plan_id
            and _dominates_compromise(other, item, policy)
            for other in complete
        )
    )


def _useful_alternatives(
    primary: FlightPlanAssessment,
    eligible: Sequence[FlightPlanAssessment],
    policy: MatchBalanceRecommendationPolicy,
) -> tuple[RecommendationAlternative, ...]:
    result = []
    primary_worst = _metric(primary, "worst_matchup_cost")
    primary_average = _metric(primary, "pair_weighted_average_matchup_cost")
    for plan in eligible:
        if plan.plan_id == primary.plan_id:
            continue
        plan_worst = _metric(plan, "worst_matchup_cost")
        plan_average = _metric(plan, "pair_weighted_average_matchup_cost")
        additional_flights = len(plan.flights) - len(primary.flights)
        worst_is_lower = _strictly_lower(plan_worst, primary_worst, policy)
        average_is_lower = _strictly_lower(
            plan_average, primary_average, policy
        )
        reasons: list[str] = []
        kind: str | None = None
        if additional_flights > 0 and (worst_is_lower or average_is_lower):
            kind = "lower_raw_modeled_risk_with_additional_flights"
            if worst_is_lower:
                reasons.append(
                    "Adds competitive flights and has a lower raw worst matchup "
                    "cost."
                )
            if average_is_lower:
                reasons.append(
                    "Adds competitive flights and has a lower raw pair-weighted "
                    "average matchup cost."
                )
        elif (
            additional_flights == 0
            and average_is_lower
            and _strictly_lower(primary_worst, plan_worst, policy)
        ):
            kind = "same_flight_count_worst_vs_average_tradeoff"
            reasons.append(
                "Uses the same number of flights with a lower raw average cost but "
                "a higher worst matchup cost."
            )
        if kind is not None:
            reasons.append(
                "Raw cost differences are preserved for review; this label does "
                "not claim a materially superior competitive outcome."
            )
            result.append(
                RecommendationAlternative(
                    plan_id=plan.plan_id,
                    flight_sizes=plan.flight_sizes,
                    kind=kind,
                    additional_flight_count=additional_flights,
                    worst_matchup_cost_delta=plan_worst - primary_worst,
                    pair_weighted_average_matchup_cost_delta=(
                        plan_average - primary_average
                    ),
                    reasons=tuple(reasons),
                )
            )
    return tuple(result)


def suggest_automatic_flights(
    selected_order: Sequence[str],
    predictions: Mapping[tuple[str, str], ComparePrediction],
    competitive_policy: TierPolicy,
    team_metadata: Mapping[str, GroupTeam],
    library: FormatLibrary,
    profile: FormatProfile,
    *,
    accepted_entrant_ids: Sequence[str] | None = None,
    unassigned_entrants: Sequence[UnassignedEntrant] = (),
    max_candidate_structures: int | None = None,
) -> AutomaticFlightSuggestion:
    """Generate, assess, and explain an automatic fixed-order suggestion."""
    order = tuple(selected_order)
    generation = generate_candidate_structures(
        len(order),
        library,
        profile,
        max_candidate_structures=max_candidate_structures,
    )
    recommendation_policy = library.policies_by_id[
        profile.recommendation_policy_id
    ]
    operational_note = (
        "Team-count compatibility and projected matchup fit do not establish field, "
        "time, referee, or schedule feasibility."
    )
    if generation.unsupported:
        return AutomaticFlightSuggestion(
            profile=profile,
            recommendation_policy=recommendation_policy,
            generation=generation,
            assessment=None,
            status=UNSUPPORTED_STRUCTURE,
            primary_plan_id=None,
            best_evaluated_plan_id=None,
            primary_evidence_status=NO_PRIMARY_EVIDENCE,
            selection_reason=generation.reason,
            format_options=(),
            useful_alternatives=(),
            compromise_plan_ids=(),
            incomplete_prediction_plan_ids=(),
            operational_feasibility_note=operational_note,
        )

    enumeration = enumerate_arrangements(
        APPROVED_ALTERNATIVES,
        generation.structures,
        len(order),
        max_arrangements=len(generation.structures),
    )
    assessment = assess_permitted_plans(
        enumeration,
        order,
        predictions,
        competitive_policy,
        team_metadata,
        accepted_entrant_ids=accepted_entrant_ids,
        unassigned_entrants=unassigned_entrants,
    )
    format_options = _format_options(assessment, generation)
    options_by_size = {
        item.team_count: item for item in generation.size_template_options
    }
    eligible = tuple(
        item
        for item in assessment.plans
        if item.structural.valid and item.all_pair_projected_fit_passed
    )
    best_evaluated = _select_by_default_policy(
        eligible, recommendation_policy, options_by_size
    )
    incomplete = tuple(
        item.plan_id for item in assessment.plans if not item.prediction_complete
    )

    if not generation.search_complete:
        return AutomaticFlightSuggestion(
            profile=profile,
            recommendation_policy=recommendation_policy,
            generation=generation,
            assessment=assessment,
            status=SEARCH_INCOMPLETE,
            primary_plan_id=None,
            best_evaluated_plan_id=(
                best_evaluated.plan_id if best_evaluated is not None else None
            ),
            primary_evidence_status=NO_PRIMARY_EVIDENCE,
            selection_reason=(
                "The bounded search is incomplete. A best evaluated plan may be "
                "reported, but the default policy does not call it the primary or "
                "globally best suggestion."
            ),
            format_options=format_options,
            useful_alternatives=(),
            compromise_plan_ids=_compromise_plan_ids(
                assessment.plans, recommendation_policy
            ),
            incomplete_prediction_plan_ids=incomplete,
            operational_feasibility_note=operational_note,
        )

    if best_evaluated is not None:
        coverage = best_evaluated.accepted_field_coverage
        status = (
            PRIMARY_SELECTED
            if coverage.full_accepted_field_coverage
            else PRIMARY_SELECTED_FOR_SUBSET
        )
        evidence_status = (
            PROVISIONAL_EVIDENCE
            if best_evaluated.limited_history_pairing_count
            or best_evaluated.unknown_history_pairing_count
            or best_evaluated.evidence_limitations
            else ESTABLISHED_EVIDENCE
        )
        subset_note = ""
        if not coverage.full_accepted_field_coverage:
            subset_note = (
                " The result covers only the assigned subset; explicitly unassigned "
                "entrants remain outside the proposed flights."
            )
        return AutomaticFlightSuggestion(
            profile=profile,
            recommendation_policy=recommendation_policy,
            generation=generation,
            assessment=assessment,
            status=status,
            primary_plan_id=best_evaluated.plan_id,
            best_evaluated_plan_id=best_evaluated.plan_id,
            primary_evidence_status=evidence_status,
            selection_reason=(
                "Selected under the MatchBalance default recommendation policy: "
                "complete predictions, no projected matchup violations, then fewest "
                "competitive flights, lower worst matchup cost, lower pair-weighted "
                "average matchup cost, and deterministic ties."
                + subset_note
            ),
            format_options=format_options,
            useful_alternatives=_useful_alternatives(
                best_evaluated, eligible, recommendation_policy
            ),
            compromise_plan_ids=(),
            incomplete_prediction_plan_ids=incomplete,
            operational_feasibility_note=operational_note,
        )

    complete_plans = tuple(
        item for item in assessment.plans if item.prediction_complete
    )
    if complete_plans:
        status = NO_WITHIN_POLICY_PLAN
        reason = (
            "No complete within-policy arrangement among the evaluated, "
            "profile-supported candidates. Limits were not relaxed, no entrant was "
            "dropped, and the result does not claim that no possible schedule could "
            "work. Operator review is required."
        )
    else:
        status = INCOMPLETE_PREDICTIONS
        reason = (
            "No candidate has complete required predictions, so missing evidence "
            "cannot improve or support an automatic recommendation. Operator review "
            "is required."
        )
    return AutomaticFlightSuggestion(
        profile=profile,
        recommendation_policy=recommendation_policy,
        generation=generation,
        assessment=assessment,
        status=status,
        primary_plan_id=None,
        best_evaluated_plan_id=None,
        primary_evidence_status=NO_PRIMARY_EVIDENCE,
        selection_reason=reason,
        format_options=format_options,
        useful_alternatives=(),
        compromise_plan_ids=_compromise_plan_ids(
            assessment.plans, recommendation_policy
        ),
        incomplete_prediction_plan_ids=incomplete,
        operational_feasibility_note=operational_note,
    )
