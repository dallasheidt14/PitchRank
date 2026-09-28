"""Complete-flight assessment for explicit MatchBalance structures.

This module partitions one frozen order into consecutive flights and delegates
every within-flight matchup decision to ``assess_group``. It does not alter the
order, choose operational formats, relax policy, or search noncontiguous teams.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_group_assessment import (
    ESTABLISHED_HISTORY,
    LIMITED_HISTORY,
    PREDICTION_AVAILABLE,
    PREDICTION_INVALID,
    PREDICTION_MISSING,
    UNKNOWN_HISTORY,
    GroupAssessment,
    GroupPairAssessment,
    GroupTeam,
    assess_group,
)
from src.tournaments.seeding_tiers import TierPolicy

EXACT_ORDERED = "exact_ordered"
PERMITTED_SIZE_MULTISET = "permitted_size_multiset"
APPROVED_ALTERNATIVES = "approved_alternatives"
STRUCTURE_MODES = (EXACT_ORDERED, PERMITTED_SIZE_MULTISET, APPROVED_ALTERNATIVES)

EVERY_MATCHUP_WITHIN_POLICY = "Every required projected matchup is within policy limits"
SOME_MATCHUPS_EXCEED_POLICY = "Some required projected matchups exceed policy limits"
PREDICTION_ASSESSMENT_INCOMPLETE = "Prediction assessment is incomplete"


@dataclass(frozen=True)
class UnassignedEntrant:
    """An accepted entrant intentionally excluded from the selected order."""

    entrant_id: str
    reason: str


@dataclass(frozen=True)
class ArrangementEnumeration:
    """Deterministic result of one explicit permitted-structure request."""

    mode: str
    requested_structures: tuple[tuple[int, ...], ...]
    required_assigned_team_count: int
    arrangements: tuple[tuple[int, ...], ...]
    total_distinct_arrangement_count: int
    evaluated_arrangement_count: int
    max_arrangements: int
    search_complete: bool
    diagnostic: str | None


@dataclass(frozen=True)
class PlanStructuralAssessment:
    valid: bool
    selected_order_is_unique: bool
    every_flight_has_at_least_two_teams: bool
    requested_sizes_match_assigned_count: bool
    every_assigned_entrant_appears_once: bool
    issues: tuple[str, ...]


@dataclass(frozen=True)
class AcceptedFieldCoverage:
    accepted_entrant_ids: tuple[str, ...]
    assigned_entrant_ids: tuple[str, ...]
    unassigned_entrants: tuple[UnassignedEntrant, ...]
    unaccounted_entrant_ids: tuple[str, ...]
    every_accepted_entrant_accounted_for: bool
    full_accepted_field_coverage: bool
    plan_for_assigned_subset: bool
    reason: str


@dataclass(frozen=True)
class FlightAssessment:
    flight_number: int
    start_order_position: int
    end_order_position: int
    requested_size: int
    entrant_ids: tuple[str, ...]
    group: GroupAssessment


@dataclass(frozen=True)
class PlanViolation:
    flight_number: int
    pairing: GroupPairAssessment
    expected_goal_difference_excess: float
    blowout_probability_excess: float


@dataclass(frozen=True)
class TeamPlanExposure:
    team: GroupTeam
    selected_order_position: int
    flight_number: int
    potential_opponent_count: int
    available_prediction_count: int
    missing_prediction_count: int
    invalid_prediction_count: int
    over_limit_opponent_count: int
    limited_or_unknown_evidence_opponent_count: int
    worst_projected_matchup: GroupPairAssessment | None
    violating_matchups: tuple[PlanViolation, ...]


@dataclass(frozen=True)
class FlightPlanAssessment:
    plan_id: str
    flight_sizes: tuple[int, ...]
    selected_order: tuple[str, ...]
    structural: PlanStructuralAssessment
    accepted_field_coverage: AcceptedFieldCoverage
    flights: tuple[FlightAssessment, ...]
    required_unique_pairing_count: int
    available_unique_pairing_count: int
    missing_prediction_count: int
    invalid_prediction_count: int
    prediction_complete: bool
    prediction_conclusion: str
    prediction_reason: str
    violating_pairing_count: int
    known_violating_fraction_of_required_lower_bound: float | None
    violating_fraction_of_available_predictions: float | None
    all_pair_projected_fit_passed: bool
    pair_weighted_average_expected_absolute_goal_difference: float | None
    pair_weighted_average_blowout_probability: float | None
    pair_weighted_average_matchup_cost: float | None
    maximum_expected_absolute_goal_difference: float | None
    maximum_expected_absolute_goal_difference_matchup: GroupPairAssessment | None
    maximum_blowout_probability: float | None
    maximum_blowout_probability_matchup: GroupPairAssessment | None
    worst_matchup_cost: float | None
    worst_matchup: GroupPairAssessment | None
    established_history_pairing_count: int
    limited_history_pairing_count: int
    unknown_history_pairing_count: int
    evidence_limitations: tuple[str, ...]
    violations: tuple[PlanViolation, ...]
    missing_prediction_pairings: tuple[GroupPairAssessment, ...]
    invalid_prediction_pairings: tuple[GroupPairAssessment, ...]
    team_exposures: tuple[TeamPlanExposure, ...]


@dataclass(frozen=True)
class PlanDominance:
    plan_id: str
    comparison_eligible: bool
    comparison_ineligibility_reason: str | None
    dominated_by_plan_ids: tuple[str, ...]
    nondominated: bool | None


@dataclass(frozen=True)
class AlternativeComparison:
    flight_size_multiset: tuple[int, ...]
    plan_ids: tuple[str, ...]
    eligible_plan_ids: tuple[str, ...]
    nondominated_plan_ids: tuple[str, ...]
    dominance: tuple[PlanDominance, ...]
    only_one_permitted_arrangement: bool
    explanation: str


@dataclass(frozen=True)
class AllOpponentAssessment:
    team: GroupTeam
    possible_opponent_count: int
    available_prediction_count: int
    missing_prediction_count: int
    invalid_prediction_count: int
    within_policy_opponents: tuple[GroupTeam, ...]
    established_history_within_policy_opponents: tuple[GroupTeam, ...]
    limited_or_unknown_history_within_policy_opponents: tuple[GroupTeam, ...]
    complete_prediction_coverage: bool
    complete_predictions_establish_no_within_policy_opponent: bool
    explanation: str


@dataclass(frozen=True)
class FlightPlanSetAssessment:
    enumeration: ArrangementEnumeration
    selected_order: tuple[str, ...]
    accepted_entrant_ids: tuple[str, ...]
    unassigned_entrants: tuple[UnassignedEntrant, ...]
    plans: tuple[FlightPlanAssessment, ...]
    comparisons: tuple[AlternativeComparison, ...]
    all_opponent_assessments: tuple[AllOpponentAssessment, ...]
    no_all_pair_within_policy_plan_among_evaluated: bool
    no_all_pair_within_policy_plan_among_permitted: bool | None
    conclusion: str


def _validate_size_structure(
    sizes: Sequence[int], required_team_count: int
) -> tuple[int, ...]:
    result = tuple(sizes)
    if not result:
        raise ValueError("A flight structure must contain at least one flight")
    if any(
        isinstance(size, bool) or not isinstance(size, int) or size < 2
        for size in result
    ):
        raise ValueError("Every flight size must be an integer of at least two")
    if sum(result) != required_team_count:
        raise ValueError(
            f"Flight sizes assign {sum(result)} teams; the selected order contains "
            f"{required_team_count}."
        )
    return result


def _unique_permutations(values: tuple[int, ...]):
    counts = Counter(values)
    keys = tuple(sorted(counts))
    current: list[int] = []

    def visit():
        if len(current) == len(values):
            yield tuple(current)
            return
        for value in keys:
            if counts[value] == 0:
                continue
            counts[value] -= 1
            current.append(value)
            yield from visit()
            current.pop()
            counts[value] += 1

    yield from visit()


def _unique_permutation_count(values: tuple[int, ...]) -> int:
    count = math.factorial(len(values))
    for repetitions in Counter(values).values():
        count //= math.factorial(repetitions)
    return count


def enumerate_arrangements(
    mode: str,
    requested_structures: Sequence[Sequence[int]],
    required_assigned_team_count: int,
    *,
    max_arrangements: int = 10_000,
) -> ArrangementEnumeration:
    """Validate and deterministically enumerate only the declared structures."""
    if mode not in STRUCTURE_MODES:
        raise ValueError(f"Unknown flight-structure mode: {mode!r}")
    if (
        isinstance(required_assigned_team_count, bool)
        or not isinstance(required_assigned_team_count, int)
        or required_assigned_team_count < 2
    ):
        raise ValueError("The selected order must contain at least two teams")
    if (
        isinstance(max_arrangements, bool)
        or not isinstance(max_arrangements, int)
        or max_arrangements < 1
    ):
        raise ValueError("The arrangement limit must be a positive integer")
    structures = tuple(
        _validate_size_structure(item, required_assigned_team_count)
        for item in requested_structures
    )
    if not structures:
        raise ValueError("At least one permitted flight structure is required")

    if mode in (EXACT_ORDERED, PERMITTED_SIZE_MULTISET) and len(structures) != 1:
        raise ValueError(f"{mode} accepts exactly one requested size sequence")
    if mode == APPROVED_ALTERNATIVES and len(set(structures)) != len(structures):
        raise ValueError("Approved alternatives must not contain duplicate structures")

    if mode == EXACT_ORDERED:
        total = 1
        arrangements = structures
    elif mode == PERMITTED_SIZE_MULTISET:
        total = _unique_permutation_count(structures[0])
        arrangements = tuple(
            item
            for index, item in enumerate(_unique_permutations(structures[0]))
            if index < max_arrangements
        )
    else:
        total = len(structures)
        arrangements = structures[:max_arrangements]

    complete = total <= max_arrangements
    diagnostic = None
    if not complete:
        diagnostic = (
            f"The request permits {total} distinct arrangement(s), but the explicit "
            f"limit is {max_arrangements}; only {len(arrangements)} were evaluated."
        )
    return ArrangementEnumeration(
        mode=mode,
        requested_structures=structures,
        required_assigned_team_count=required_assigned_team_count,
        arrangements=arrangements,
        total_distinct_arrangement_count=total,
        evaluated_arrangement_count=len(arrangements),
        max_arrangements=max_arrangements,
        search_complete=complete,
        diagnostic=diagnostic,
    )


def _fraction(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _available_pairings(
    pairings: Sequence[GroupPairAssessment],
) -> tuple[GroupPairAssessment, ...]:
    return tuple(
        item for item in pairings if item.prediction_status == PREDICTION_AVAILABLE
    )


def _maximum_pair(
    pairings: Sequence[GroupPairAssessment], attribute: str
) -> GroupPairAssessment | None:
    if not pairings:
        return None
    return max(
        pairings,
        key=lambda item: (
            getattr(item, attribute),
            item.matchup_cost,
            item.entrant_ids,
        ),
    )


def _coverage(
    selected_order: tuple[str, ...],
    accepted_entrant_ids: Sequence[str],
    unassigned_entrants: Sequence[UnassignedEntrant],
) -> AcceptedFieldCoverage:
    accepted = tuple(accepted_entrant_ids)
    if len(accepted) != len(set(accepted)):
        raise ValueError("Accepted entrant IDs must be unique")
    if any(not entrant_id for entrant_id in accepted):
        raise ValueError("Accepted entrant IDs must be non-empty")
    if not set(selected_order).issubset(accepted):
        raise ValueError("The selected order contains an entrant outside the accepted field")
    unassigned = tuple(unassigned_entrants)
    unassigned_ids = tuple(item.entrant_id for item in unassigned)
    if len(unassigned_ids) != len(set(unassigned_ids)):
        raise ValueError("Each unassigned entrant may be listed only once")
    if any(not item.reason.strip() for item in unassigned):
        raise ValueError("Every unassigned entrant requires an explicit reason")
    if set(unassigned_ids) & set(selected_order):
        raise ValueError("An entrant cannot be both assigned and unassigned")
    if not set(unassigned_ids).issubset(accepted):
        raise ValueError("An unassigned entrant is outside the accepted field")
    unaccounted = tuple(
        entrant_id
        for entrant_id in accepted
        if entrant_id not in set(selected_order) | set(unassigned_ids)
    )
    accounted = not unaccounted
    full = accounted and not unassigned
    if not accounted:
        reason = (
            f"{len(unaccounted)} accepted entrant(s) are neither assigned nor explicitly "
            "unassigned."
        )
    elif unassigned:
        reason = (
            f"All accepted entrants are accounted for, but {len(unassigned)} remain "
            "explicitly unassigned; this is a plan for the assigned subset."
        )
    else:
        reason = "Every accepted entrant is assigned exactly once."
    return AcceptedFieldCoverage(
        accepted_entrant_ids=accepted,
        assigned_entrant_ids=selected_order,
        unassigned_entrants=unassigned,
        unaccounted_entrant_ids=unaccounted,
        every_accepted_entrant_accounted_for=accounted,
        full_accepted_field_coverage=full,
        plan_for_assigned_subset=accounted and bool(unassigned),
        reason=reason,
    )


def assess_flight_plan(
    selected_order: Sequence[str],
    flight_sizes: Sequence[int],
    predictions: Mapping[tuple[str, str], ComparePrediction],
    policy: TierPolicy,
    team_metadata: Mapping[str, GroupTeam],
    *,
    accepted_entrant_ids: Sequence[str] | None = None,
    unassigned_entrants: Sequence[UnassignedEntrant] = (),
    plan_id: str = "plan",
) -> FlightPlanAssessment:
    """Assess one explicit contiguous partition without changing membership."""
    order = tuple(selected_order)
    if len(order) != len(set(order)):
        raise ValueError("The selected order must contain unique entrant IDs")
    if any(entrant_id not in team_metadata for entrant_id in order):
        raise ValueError("Every assigned entrant requires frozen team metadata")
    sizes = _validate_size_structure(flight_sizes, len(order))
    accepted = tuple(accepted_entrant_ids) if accepted_entrant_ids is not None else (
        *order,
        *(item.entrant_id for item in unassigned_entrants),
    )
    if any(entrant_id not in team_metadata for entrant_id in accepted):
        raise ValueError("Every accepted entrant requires frozen team metadata")
    coverage = _coverage(order, accepted, unassigned_entrants)

    flights = []
    offset = 0
    for number, size in enumerate(sizes, start=1):
        members = order[offset : offset + size]
        group = assess_group(members, predictions, policy, team_metadata)
        flights.append(
            FlightAssessment(
                flight_number=number,
                start_order_position=offset + 1,
                end_order_position=offset + size,
                requested_size=size,
                entrant_ids=members,
                group=group,
            )
        )
        offset += size
    structural = PlanStructuralAssessment(
        valid=True,
        selected_order_is_unique=True,
        every_flight_has_at_least_two_teams=True,
        requested_sizes_match_assigned_count=True,
        every_assigned_entrant_appears_once=(
            tuple(item for flight in flights for item in flight.entrant_ids) == order
        ),
        issues=(),
    )
    if not structural.every_assigned_entrant_appears_once:  # pragma: no cover
        raise RuntimeError("Internal partitioning error")

    pairings = tuple(
        pairing for flight in flights for pairing in flight.group.pairings
    )
    expected = sum(
        flight.requested_size * (flight.requested_size - 1) // 2
        for flight in flights
    )
    available = _available_pairings(pairings)
    missing = tuple(
        item for item in pairings if item.prediction_status == PREDICTION_MISSING
    )
    invalid = tuple(
        item for item in pairings if item.prediction_status == PREDICTION_INVALID
    )
    violations_by_key: dict[tuple[str, str], PlanViolation] = {}
    flight_by_pair = {
        item.entrant_ids: flight.flight_number
        for flight in flights
        for item in flight.group.pairings
    }
    for pairing in available:
        if pairing.within_both_limits is not False:
            continue
        violations_by_key[pairing.entrant_ids] = PlanViolation(
            flight_number=flight_by_pair[pairing.entrant_ids],
            pairing=pairing,
            expected_goal_difference_excess=max(
                0.0,
                (pairing.expected_absolute_goal_difference or 0.0)
                - policy.max_expected_margin,
            ),
            blowout_probability_excess=max(
                0.0,
                (pairing.blowout_probability or 0.0)
                - policy.max_blowout_probability,
            ),
        )
    violations = tuple(violations_by_key.values())
    prediction_complete = len(available) == expected
    if not prediction_complete:
        conclusion = PREDICTION_ASSESSMENT_INCOMPLETE
        reason = (
            f"{len(missing)} of {expected} required prediction(s) are missing and "
            f"{len(invalid)} are invalid. {len(violations)} known violation(s) remain visible."
        )
    elif violations:
        conclusion = SOME_MATCHUPS_EXCEED_POLICY
        reason = (
            f"{len(violations)} of {expected} required projected matchup(s) exceed "
            "at least one competitive-fit limit."
        )
    else:
        conclusion = EVERY_MATCHUP_WITHIN_POLICY
        reason = (
            f"All {expected} required projected matchup(s) are present, valid, and "
            "within both competitive-fit limits."
        )

    maximum_goal_pair = _maximum_pair(
        available, "expected_absolute_goal_difference"
    )
    maximum_blowout_pair = _maximum_pair(available, "blowout_probability")
    worst_pair = _maximum_pair(available, "matchup_cost")
    if available:
        average_goal = math.fsum(
            item.expected_absolute_goal_difference or 0.0 for item in available
        ) / len(available)
        average_blowout = math.fsum(
            item.blowout_probability or 0.0 for item in available
        ) / len(available)
        average_cost = math.fsum(
            item.matchup_cost or 0.0 for item in available
        ) / len(available)
    else:
        average_goal = None
        average_blowout = None
        average_cost = None

    evidence_limitations = tuple(
        f"Flight {flight.flight_number}: {limitation}"
        for flight in flights
        for limitation in flight.group.evidence_coverage.limitations
    )
    order_position = {
        entrant_id: index for index, entrant_id in enumerate(order, start=1)
    }
    exposures = []
    for flight in flights:
        for entrant_id in flight.entrant_ids:
            relevant = tuple(
                item
                for item in flight.group.pairings
                if entrant_id in item.entrant_ids
            )
            relevant_available = _available_pairings(relevant)
            relevant_violations = tuple(
                violations_by_key[item.entrant_ids]
                for item in relevant_available
                if item.entrant_ids in violations_by_key
            )
            exposures.append(
                TeamPlanExposure(
                    team=team_metadata[entrant_id],
                    selected_order_position=order_position[entrant_id],
                    flight_number=flight.flight_number,
                    potential_opponent_count=len(flight.entrant_ids) - 1,
                    available_prediction_count=len(relevant_available),
                    missing_prediction_count=sum(
                        item.prediction_status == PREDICTION_MISSING
                        for item in relevant
                    ),
                    invalid_prediction_count=sum(
                        item.prediction_status == PREDICTION_INVALID
                        for item in relevant
                    ),
                    over_limit_opponent_count=len(relevant_violations),
                    limited_or_unknown_evidence_opponent_count=sum(
                        item.history_quality != ESTABLISHED_HISTORY
                        for item in relevant
                    ),
                    worst_projected_matchup=_maximum_pair(
                        relevant_available, "matchup_cost"
                    ),
                    violating_matchups=relevant_violations,
                )
            )
    return FlightPlanAssessment(
        plan_id=plan_id,
        flight_sizes=sizes,
        selected_order=order,
        structural=structural,
        accepted_field_coverage=coverage,
        flights=tuple(flights),
        required_unique_pairing_count=expected,
        available_unique_pairing_count=len(available),
        missing_prediction_count=len(missing),
        invalid_prediction_count=len(invalid),
        prediction_complete=prediction_complete,
        prediction_conclusion=conclusion,
        prediction_reason=reason,
        violating_pairing_count=len(violations),
        known_violating_fraction_of_required_lower_bound=_fraction(
            len(violations), expected
        ),
        violating_fraction_of_available_predictions=_fraction(
            len(violations), len(available)
        ),
        all_pair_projected_fit_passed=prediction_complete and not violations,
        pair_weighted_average_expected_absolute_goal_difference=average_goal,
        pair_weighted_average_blowout_probability=average_blowout,
        pair_weighted_average_matchup_cost=average_cost,
        maximum_expected_absolute_goal_difference=(
            maximum_goal_pair.expected_absolute_goal_difference
            if maximum_goal_pair is not None
            else None
        ),
        maximum_expected_absolute_goal_difference_matchup=maximum_goal_pair,
        maximum_blowout_probability=(
            maximum_blowout_pair.blowout_probability
            if maximum_blowout_pair is not None
            else None
        ),
        maximum_blowout_probability_matchup=maximum_blowout_pair,
        worst_matchup_cost=(
            worst_pair.matchup_cost if worst_pair is not None else None
        ),
        worst_matchup=worst_pair,
        established_history_pairing_count=sum(
            item.history_quality == ESTABLISHED_HISTORY for item in pairings
        ),
        limited_history_pairing_count=sum(
            item.history_quality == LIMITED_HISTORY for item in pairings
        ),
        unknown_history_pairing_count=sum(
            item.history_quality == UNKNOWN_HISTORY for item in pairings
        ),
        evidence_limitations=evidence_limitations,
        violations=violations,
        missing_prediction_pairings=missing,
        invalid_prediction_pairings=invalid,
        team_exposures=tuple(exposures),
    )


def _metric_no_worse(first: float, second: float) -> bool:
    return first < second or math.isclose(first, second, rel_tol=1e-12, abs_tol=1e-12)


def _metric_better(first: float, second: float) -> bool:
    return first < second and not math.isclose(
        first, second, rel_tol=1e-12, abs_tol=1e-12
    )


def _dominates(first: FlightPlanAssessment, second: FlightPlanAssessment) -> bool:
    first_metrics = (
        float(first.violating_pairing_count),
        float(first.worst_matchup_cost or 0.0),
        float(first.pair_weighted_average_matchup_cost or 0.0),
    )
    second_metrics = (
        float(second.violating_pairing_count),
        float(second.worst_matchup_cost or 0.0),
        float(second.pair_weighted_average_matchup_cost or 0.0),
    )
    return all(
        _metric_no_worse(left, right)
        for left, right in zip(first_metrics, second_metrics, strict=True)
    ) and any(
        _metric_better(left, right)
        for left, right in zip(first_metrics, second_metrics, strict=True)
    )


def compare_alternatives(
    plans: Sequence[FlightPlanAssessment],
) -> tuple[AlternativeComparison, ...]:
    """Find nondominated plans only within the same size multiset."""
    groups: dict[tuple[int, ...], list[FlightPlanAssessment]] = {}
    for plan in plans:
        groups.setdefault(tuple(sorted(plan.flight_sizes)), []).append(plan)
    comparisons = []
    for multiset in sorted(groups):
        members = groups[multiset]
        eligible = tuple(
            item
            for item in members
            if item.prediction_complete and item.structural.valid
        )
        dominance_rows = []
        nondominated_ids = []
        for plan in members:
            if plan not in eligible:
                reason = (
                    "Prediction coverage is incomplete, so known violations cannot be "
                    "used to rank this plan against complete alternatives."
                )
                dominance_rows.append(
                    PlanDominance(plan.plan_id, False, reason, (), None)
                )
                continue
            dominated_by = tuple(
                other.plan_id
                for other in eligible
                if other.plan_id != plan.plan_id and _dominates(other, plan)
            )
            nondominated = not dominated_by
            if nondominated:
                nondominated_ids.append(plan.plan_id)
            dominance_rows.append(
                PlanDominance(plan.plan_id, True, None, dominated_by, nondominated)
            )
        only_one = len(members) == 1
        if only_one:
            explanation = (
                "Only one permitted arrangement exists for this structure; it was assessed, "
                "not selected by an optimizer."
            )
        elif not eligible:
            explanation = (
                "No arrangement has complete predictions, so no numerical dominance claim "
                "is made."
            )
        else:
            explanation = (
                "Nondominated alternatives are no worse on violation count, worst matchup "
                "cost, and pair-weighted average cost simultaneously. Ties are not treated "
                "as competitive superiority."
            )
        comparisons.append(
            AlternativeComparison(
                flight_size_multiset=multiset,
                plan_ids=tuple(item.plan_id for item in members),
                eligible_plan_ids=tuple(item.plan_id for item in eligible),
                nondominated_plan_ids=tuple(nondominated_ids),
                dominance=tuple(dominance_rows),
                only_one_permitted_arrangement=only_one,
                explanation=explanation,
            )
        )
    return tuple(comparisons)


def assess_all_opponents(
    entrant_ids: Sequence[str],
    predictions: Mapping[tuple[str, str], ComparePrediction],
    policy: TierPolicy,
    team_metadata: Mapping[str, GroupTeam],
) -> tuple[AllOpponentAssessment, ...]:
    """Identify complete-prediction cases with no within-policy opponent."""
    ids = tuple(entrant_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("All-opponent entrant IDs must be unique")
    if any(entrant_id not in team_metadata for entrant_id in ids):
        raise ValueError("Every accepted entrant requires frozen team metadata")
    complete = assess_group(ids, predictions, policy, team_metadata)
    result = []
    for entrant_id in ids:
        pairings = tuple(
            item for item in complete.pairings if entrant_id in item.entrant_ids
        )
        available = _available_pairings(pairings)
        missing = sum(
            item.prediction_status == PREDICTION_MISSING for item in pairings
        )
        invalid = sum(
            item.prediction_status == PREDICTION_INVALID for item in pairings
        )
        within = tuple(item for item in available if item.within_both_limits)
        opponents = tuple(
            item.second if item.first.entrant_id == entrant_id else item.first
            for item in within
        )
        established = tuple(
            opponent
            for item, opponent in zip(within, opponents, strict=True)
            if item.history_quality == ESTABLISHED_HISTORY
        )
        limited = tuple(
            opponent
            for item, opponent in zip(within, opponents, strict=True)
            if item.history_quality != ESTABLISHED_HISTORY
        )
        prediction_complete = len(available) == len(pairings)
        no_opponent = prediction_complete and not within
        if no_opponent:
            explanation = (
                "Complete frozen predictions show that every possible opponent exceeds at "
                "least one competitive-fit limit; any multi-team flight containing this "
                "entrant must contain a projected violation."
            )
        elif not prediction_complete:
            explanation = (
                "Missing or invalid predictions prevent a complete all-opponent conclusion."
            )
        else:
            explanation = (
                f"{len(within)} of {len(pairings)} possible opponent(s) meet both limits."
            )
        result.append(
            AllOpponentAssessment(
                team=team_metadata[entrant_id],
                possible_opponent_count=len(pairings),
                available_prediction_count=len(available),
                missing_prediction_count=missing,
                invalid_prediction_count=invalid,
                within_policy_opponents=opponents,
                established_history_within_policy_opponents=established,
                limited_or_unknown_history_within_policy_opponents=limited,
                complete_prediction_coverage=prediction_complete,
                complete_predictions_establish_no_within_policy_opponent=no_opponent,
                explanation=explanation,
            )
        )
    return tuple(result)


def assess_permitted_plans(
    enumeration: ArrangementEnumeration,
    selected_order: Sequence[str],
    predictions: Mapping[tuple[str, str], ComparePrediction],
    policy: TierPolicy,
    team_metadata: Mapping[str, GroupTeam],
    *,
    accepted_entrant_ids: Sequence[str] | None = None,
    unassigned_entrants: Sequence[UnassignedEntrant] = (),
) -> FlightPlanSetAssessment:
    """Assess every enumerated arrangement and compare like structures only."""
    order = tuple(selected_order)
    if len(order) != enumeration.required_assigned_team_count:
        raise ValueError("The structure request does not match the selected order")
    accepted = tuple(accepted_entrant_ids) if accepted_entrant_ids is not None else (
        *order,
        *(item.entrant_id for item in unassigned_entrants),
    )
    plans = tuple(
        assess_flight_plan(
            order,
            sizes,
            predictions,
            policy,
            team_metadata,
            accepted_entrant_ids=accepted,
            unassigned_entrants=unassigned_entrants,
            plan_id=f"plan-{index:03d}-{'-'.join(str(size) for size in sizes)}",
        )
        for index, sizes in enumerate(enumeration.arrangements, start=1)
    )
    no_pass = not any(item.all_pair_projected_fit_passed for item in plans)
    if enumeration.search_complete:
        no_permitted: bool | None = no_pass
        if no_pass:
            conclusion = "No all-pair within-policy plan among the permitted arrangements."
        else:
            conclusion = (
                f"{sum(item.all_pair_projected_fit_passed for item in plans)} of "
                f"{len(plans)} permitted arrangement(s) pass the all-pair projected-fit test."
            )
    else:
        no_permitted = None
        conclusion = (
            "The arrangement search is incomplete at the declared limit; no conclusion is "
            "made about every permitted arrangement."
        )
    return FlightPlanSetAssessment(
        enumeration=enumeration,
        selected_order=order,
        accepted_entrant_ids=accepted,
        unassigned_entrants=tuple(unassigned_entrants),
        plans=plans,
        comparisons=compare_alternatives(plans),
        all_opponent_assessments=assess_all_opponents(
            accepted, predictions, policy, team_metadata
        ),
        no_all_pair_within_policy_plan_among_evaluated=no_pass,
        no_all_pair_within_policy_plan_among_permitted=no_permitted,
        conclusion=conclusion,
    )
