"""Complete-pair competitive-fit diagnostics for explicit MatchBalance groups.

This module assesses supplied membership only. It does not choose group sizes,
move teams, assign flights, or infer compatibility from seed adjacency or
PowerScore. Every unique within-group pairing is evaluated through the same
prediction validation and risk/cost helpers used by the seeding analysis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Mapping, Sequence

from src.tournaments import seeding_tiers
from src.tournaments.compare_predictor_bridge import ComparePrediction

ALL_WITHIN_LIMITS = "Every projected matchup is within policy limits"
SOME_EXCEED_LIMITS = "Some projected matchups exceed policy limits"
INCOMPLETE_PREDICTIONS = "Assessment incomplete because predictions are unavailable or invalid"
NO_WITHIN_GROUP_MATCHUP = "No within-group matchup to assess"

PREDICTION_AVAILABLE = "available"
PREDICTION_MISSING = "missing"
PREDICTION_INVALID = "invalid"

ESTABLISHED_HISTORY = "established"
LIMITED_HISTORY = "limited"
UNKNOWN_HISTORY = "unknown"


@dataclass(frozen=True)
class GroupTeam:
    """Frozen team identity, seed context, and history evidence for reporting."""

    entrant_id: str
    team_name: str
    team_id_master: str | None = None
    seed: int | None = None
    power_score: float | None = None
    limited_history: bool | None = None
    evidence_game_count: int | None = None
    evidence_flags: tuple[str, ...] = ()

    @property
    def history_quality(self) -> str:
        if self.limited_history is None:
            return UNKNOWN_HISTORY
        return LIMITED_HISTORY if self.limited_history else ESTABLISHED_HISTORY


@dataclass(frozen=True)
class GroupPairAssessment:
    """One unique matchup, including projected fit and separate evidence context."""

    first: GroupTeam
    second: GroupTeam
    prediction_status: str
    prediction_issue: str | None
    expected_signed_margin_toward_first: float | None
    expected_absolute_goal_difference: float | None
    blowout_probability: float | None
    matchup_cost: float | None
    within_expected_goal_difference_limit: bool | None
    within_blowout_probability_limit: bool | None
    within_both_limits: bool | None
    exceeds_expected_goal_difference_limit: bool | None
    exceeds_blowout_probability_limit: bool | None
    history_quality: str
    provisional_due_to_history: bool
    outcome_confidence: str | None
    outcome_confidence_score: float | None
    low_outcome_confidence: bool | None

    @property
    def entrant_ids(self) -> tuple[str, str]:
        return self.first.entrant_id, self.second.entrant_id


@dataclass(frozen=True)
class ProjectedFitAssessment:
    """All-pair projection result, independent of team-history limitations."""

    conclusion: str
    reason: str
    expected_unique_pairing_count: int
    available_unique_pairing_count: int
    missing_prediction_count: int
    invalid_prediction_count: int
    complete_prediction_coverage: bool
    within_both_limits_count: int
    within_both_limits_fraction_of_available: float | None
    within_both_limits_fraction_of_expected: float | None
    exceeding_either_limit_count: int
    exceeding_either_limit_fraction_of_available: float | None
    exceeding_either_limit_fraction_of_expected: float | None
    all_available_matchups_within_limits: bool | None
    all_pair_projected_fit_passed: bool | None
    average_expected_absolute_goal_difference: float | None
    maximum_expected_absolute_goal_difference: float | None
    average_blowout_probability: float | None
    maximum_blowout_probability: float | None
    average_matchup_cost: float | None
    maximum_matchup_cost: float | None
    worst_matchup: GroupPairAssessment | None
    maximum_expected_absolute_goal_difference_matchup: GroupPairAssessment | None
    maximum_blowout_probability_matchup: GroupPairAssessment | None
    over_limit_matchups: tuple[GroupPairAssessment, ...]


@dataclass(frozen=True)
class EvidenceCoverageAssessment:
    """History and prediction coverage, deliberately separate from projected fit."""

    established_history_teams: tuple[GroupTeam, ...]
    limited_history_teams: tuple[GroupTeam, ...]
    unknown_history_teams: tuple[GroupTeam, ...]
    all_team_history_metadata_available: bool
    pairings_involving_limited_or_unknown_history: tuple[GroupPairAssessment, ...]
    provisional_within_limit_pairings: tuple[GroupPairAssessment, ...]
    missing_prediction_pairings: tuple[GroupPairAssessment, ...]
    invalid_prediction_pairings: tuple[GroupPairAssessment, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class GroupAssessment:
    """Complete assessment for one explicit membership."""

    entrant_ids: tuple[str, ...]
    teams: tuple[GroupTeam, ...]
    policy: seeding_tiers.TierPolicy
    projected_fit: ProjectedFitAssessment
    evidence_coverage: EvidenceCoverageAssessment
    pairings: tuple[GroupPairAssessment, ...]


@dataclass(frozen=True)
class GroupAdditionAssessment:
    """Specific consequences of adding one team to an explicit group."""

    direction: str
    added_team: GroupTeam
    original_group: GroupAssessment
    expanded_group: GroupAssessment
    newly_introduced_matchups: tuple[GroupPairAssessment, ...]
    newly_over_limit_matchups: tuple[GroupPairAssessment, ...]
    newly_missing_or_invalid_matchups: tuple[GroupPairAssessment, ...]
    original_over_limit_matchups: tuple[GroupPairAssessment, ...]
    original_missing_or_invalid_matchups: tuple[GroupPairAssessment, ...]
    original_group_had_projected_failures: bool
    original_group_had_incomplete_predictions: bool
    average_expected_absolute_goal_difference_change: float | None
    maximum_expected_absolute_goal_difference_change: float | None
    average_blowout_probability_change: float | None
    maximum_blowout_probability_change: float | None
    average_matchup_cost_change: float | None
    maximum_matchup_cost_change: float | None
    added_evidence_limitations: tuple[str, ...]


@dataclass(frozen=True)
class ContiguousGroupCandidate:
    """One contiguous alternative in the supplied MatchBalance order."""

    requested_size: int
    start_order_position: int
    end_order_position: int
    assessment: GroupAssessment
    add_above: GroupAdditionAssessment | None
    add_below: GroupAdditionAssessment | None


@dataclass(frozen=True)
class ContiguousGroupScan:
    """All contiguous alternatives for explicit requested sizes."""

    ordered_ids: tuple[str, ...]
    requested_sizes: tuple[int, ...]
    available_sizes: tuple[int, ...]
    unavailable_sizes: tuple[int, ...]
    candidates: tuple[ContiguousGroupCandidate, ...]


def _team_order(team: GroupTeam) -> tuple[bool, int, str]:
    return team.seed is None, team.seed if team.seed is not None else 0, team.entrant_id


def _validate_teams(
    entrant_ids: Sequence[str], team_metadata: Mapping[str, GroupTeam]
) -> tuple[GroupTeam, ...]:
    ids = tuple(entrant_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("A group must contain each entrant ID at most once")
    teams = []
    for entrant_id in ids:
        if not entrant_id or entrant_id.strip() != entrant_id:
            raise ValueError("Every group entrant needs a non-empty ID without surrounding whitespace")
        if entrant_id not in team_metadata:
            raise ValueError(f"Missing group metadata for entrant {entrant_id}")
        team = team_metadata[entrant_id]
        if team.entrant_id != entrant_id:
            raise ValueError(f"Group metadata ID does not match entrant {entrant_id}")
        if team.seed is not None and (
            isinstance(team.seed, bool) or not isinstance(team.seed, int) or team.seed < 1
        ):
            raise ValueError(f"Invalid seed metadata for entrant {entrant_id}")
        if team.power_score is not None and (
            isinstance(team.power_score, bool) or not math.isfinite(team.power_score)
        ):
            raise ValueError(f"Invalid PowerScore metadata for entrant {entrant_id}")
        if team.limited_history not in (True, False, None):
            raise ValueError(f"Invalid limited-history metadata for entrant {entrant_id}")
        if team.evidence_game_count is not None and (
            isinstance(team.evidence_game_count, bool)
            or not isinstance(team.evidence_game_count, int)
            or team.evidence_game_count < 0
        ):
            raise ValueError(f"Invalid evidence game count for entrant {entrant_id}")
        if any(not isinstance(flag, str) or not flag for flag in team.evidence_flags):
            raise ValueError(f"Invalid evidence flag for entrant {entrant_id}")
        teams.append(team)
    return tuple(sorted(teams, key=_team_order))


def _pair_history_quality(first: GroupTeam, second: GroupTeam) -> str:
    qualities = {first.history_quality, second.history_quality}
    if UNKNOWN_HISTORY in qualities:
        return UNKNOWN_HISTORY
    if LIMITED_HISTORY in qualities:
        return LIMITED_HISTORY
    return ESTABLISHED_HISTORY


def _unavailable_pair(
    first: GroupTeam,
    second: GroupTeam,
    *,
    status: str,
    issue: str,
) -> GroupPairAssessment:
    quality = _pair_history_quality(first, second)
    return GroupPairAssessment(
        first=first,
        second=second,
        prediction_status=status,
        prediction_issue=issue,
        expected_signed_margin_toward_first=None,
        expected_absolute_goal_difference=None,
        blowout_probability=None,
        matchup_cost=None,
        within_expected_goal_difference_limit=None,
        within_blowout_probability_limit=None,
        within_both_limits=None,
        exceeds_expected_goal_difference_limit=None,
        exceeds_blowout_probability_limit=None,
        history_quality=quality,
        provisional_due_to_history=quality != ESTABLISHED_HISTORY,
        outcome_confidence=None,
        outcome_confidence_score=None,
        low_outcome_confidence=None,
    )


def _assess_pair(
    first: GroupTeam,
    second: GroupTeam,
    predictions: Mapping[tuple[str, str], ComparePrediction],
    policy: seeding_tiers.TierPolicy,
) -> GroupPairAssessment:
    forward = predictions.get((first.entrant_id, second.entrant_id))
    reverse = predictions.get((second.entrant_id, first.entrant_id))
    if forward is None and reverse is None:
        return _unavailable_pair(
            first,
            second,
            status=PREDICTION_MISSING,
            issue=(
                f"Missing Compare prediction for {first.entrant_id} vs {second.entrant_id}."
            ),
        )
    try:
        pairs = seeding_tiers._read_pairs(
            (first.entrant_id, second.entrant_id), predictions
        )
    except (AttributeError, TypeError, ValueError) as exc:
        return _unavailable_pair(
            first,
            second,
            status=PREDICTION_INVALID,
            issue=str(exc),
        )
    pair = pairs[seeding_tiers._pair_key(first.entrant_id, second.entrant_id)]
    within_goal = pair.absolute_goal_difference <= policy.max_expected_margin
    within_blowout = pair.blowout <= policy.max_blowout_probability
    within_both = seeding_tiers._risk(pair, policy) <= 1.0
    selected = forward if forward is not None else reverse
    confidence = getattr(selected, "confidence", None)
    confidence_score = getattr(selected, "confidence_score", None)
    quality = _pair_history_quality(first, second)
    return GroupPairAssessment(
        first=first,
        second=second,
        prediction_status=PREDICTION_AVAILABLE,
        prediction_issue=None,
        expected_signed_margin_toward_first=seeding_tiers._margin(
            pairs, first.entrant_id, second.entrant_id
        ),
        expected_absolute_goal_difference=pair.absolute_goal_difference,
        blowout_probability=pair.blowout,
        matchup_cost=seeding_tiers._matchup_cost(pair, policy),
        within_expected_goal_difference_limit=within_goal,
        within_blowout_probability_limit=within_blowout,
        within_both_limits=within_both,
        exceeds_expected_goal_difference_limit=not within_goal,
        exceeds_blowout_probability_limit=not within_blowout,
        history_quality=quality,
        provisional_due_to_history=quality != ESTABLISHED_HISTORY,
        outcome_confidence=confidence,
        outcome_confidence_score=(
            float(confidence_score) if confidence_score is not None else None
        ),
        low_outcome_confidence=confidence == "low",
    )


def _fraction(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _difference(current: float | None, previous: float | None) -> float | None:
    return current - previous if current is not None and previous is not None else None


def assess_group(
    entrant_ids: Sequence[str],
    predictions: Mapping[tuple[str, str], ComparePrediction],
    policy: seeding_tiers.TierPolicy,
    team_metadata: Mapping[str, GroupTeam],
) -> GroupAssessment:
    """Assess every unique matchup for the supplied membership.

    Missing and invalid predictions remain explicit and prevent a complete
    projected-fit pass. Limited or unknown team history does not change the
    prediction metrics; it is reported separately as evidence context.
    """
    teams = _validate_teams(entrant_ids, team_metadata)
    pairings = tuple(
        _assess_pair(first, second, predictions, policy)
        for first, second in combinations(teams, 2)
    )
    expected = len(teams) * (len(teams) - 1) // 2
    available = tuple(
        item for item in pairings if item.prediction_status == PREDICTION_AVAILABLE
    )
    missing = tuple(
        item for item in pairings if item.prediction_status == PREDICTION_MISSING
    )
    invalid = tuple(
        item for item in pairings if item.prediction_status == PREDICTION_INVALID
    )
    within = tuple(item for item in available if item.within_both_limits)
    over_limit = tuple(item for item in available if item.within_both_limits is False)
    complete = len(available) == expected

    if expected == 0:
        conclusion = NO_WITHIN_GROUP_MATCHUP
        reason = (
            "The group has fewer than two teams, so there is no within-group matchup to assess."
        )
        all_available_within: bool | None = None
        all_pair_passed: bool | None = None
    elif not complete:
        conclusion = INCOMPLETE_PREDICTIONS
        reason = (
            f"{len(missing)} of {expected} required prediction(s) are missing and "
            f"{len(invalid)} are invalid; unavailable information is not treated as safe."
        )
        if over_limit:
            reason += f" {len(over_limit)} available matchup(s) also exceed policy limits."
        all_available_within = not over_limit if available else None
        all_pair_passed = False
    elif over_limit:
        conclusion = SOME_EXCEED_LIMITS
        reason = (
            f"{len(over_limit)} of {expected} projected matchup(s) exceed at least one "
            "competitive-fit limit."
        )
        all_available_within = False
        all_pair_passed = False
    else:
        conclusion = ALL_WITHIN_LIMITS
        reason = (
            f"All {expected} required projected matchup(s) are present, valid, and within "
            "both competitive-fit limits."
        )
        all_available_within = True
        all_pair_passed = True

    if available:
        average_absolute = math.fsum(
            item.expected_absolute_goal_difference for item in available
            if item.expected_absolute_goal_difference is not None
        ) / len(available)
        average_blowout = math.fsum(
            item.blowout_probability for item in available
            if item.blowout_probability is not None
        ) / len(available)
        average_cost = math.fsum(
            item.matchup_cost for item in available if item.matchup_cost is not None
        ) / len(available)
        maximum_absolute_pair = max(
            available,
            key=lambda item: (
                item.expected_absolute_goal_difference,
                item.blowout_probability,
                item.entrant_ids,
            ),
        )
        maximum_blowout_pair = max(
            available,
            key=lambda item: (
                item.blowout_probability,
                item.expected_absolute_goal_difference,
                item.entrant_ids,
            ),
        )
        worst = max(
            available,
            key=lambda item: (
                item.matchup_cost,
                item.expected_absolute_goal_difference,
                item.blowout_probability,
                item.entrant_ids,
            ),
        )
    else:
        average_absolute = None
        average_blowout = None
        average_cost = None
        maximum_absolute_pair = None
        maximum_blowout_pair = None
        worst = None

    projected = ProjectedFitAssessment(
        conclusion=conclusion,
        reason=reason,
        expected_unique_pairing_count=expected,
        available_unique_pairing_count=len(available),
        missing_prediction_count=len(missing),
        invalid_prediction_count=len(invalid),
        complete_prediction_coverage=complete,
        within_both_limits_count=len(within),
        within_both_limits_fraction_of_available=_fraction(len(within), len(available)),
        within_both_limits_fraction_of_expected=_fraction(len(within), expected),
        exceeding_either_limit_count=len(over_limit),
        exceeding_either_limit_fraction_of_available=_fraction(
            len(over_limit), len(available)
        ),
        exceeding_either_limit_fraction_of_expected=_fraction(len(over_limit), expected),
        all_available_matchups_within_limits=all_available_within,
        all_pair_projected_fit_passed=all_pair_passed,
        average_expected_absolute_goal_difference=average_absolute,
        maximum_expected_absolute_goal_difference=(
            maximum_absolute_pair.expected_absolute_goal_difference
            if maximum_absolute_pair is not None
            else None
        ),
        average_blowout_probability=average_blowout,
        maximum_blowout_probability=(
            maximum_blowout_pair.blowout_probability
            if maximum_blowout_pair is not None
            else None
        ),
        average_matchup_cost=average_cost,
        maximum_matchup_cost=worst.matchup_cost if worst is not None else None,
        worst_matchup=worst,
        maximum_expected_absolute_goal_difference_matchup=maximum_absolute_pair,
        maximum_blowout_probability_matchup=maximum_blowout_pair,
        over_limit_matchups=over_limit,
    )

    established = tuple(
        team for team in teams if team.history_quality == ESTABLISHED_HISTORY
    )
    limited = tuple(team for team in teams if team.history_quality == LIMITED_HISTORY)
    unknown = tuple(team for team in teams if team.history_quality == UNKNOWN_HISTORY)
    evidence_pairings = tuple(
        item for item in pairings if item.history_quality != ESTABLISHED_HISTORY
    )
    provisional_within = tuple(
        item
        for item in available
        if item.within_both_limits and item.provisional_due_to_history
    )
    limitations = []
    if limited:
        limitations.append(
            f"{len(limited)} team(s) have the existing limited-history flag."
        )
    if unknown:
        limitations.append(
            f"{len(unknown)} team(s) have unknown history metadata."
        )
    if provisional_within:
        limitations.append(
            f"{len(provisional_within)} within-limit prediction(s) remain provisional because "
            "at least one participant has limited or unknown history."
        )
    if missing:
        limitations.append(f"{len(missing)} required prediction(s) are missing.")
    if invalid:
        limitations.append(f"{len(invalid)} required prediction(s) are invalid.")
    evidence = EvidenceCoverageAssessment(
        established_history_teams=established,
        limited_history_teams=limited,
        unknown_history_teams=unknown,
        all_team_history_metadata_available=not unknown,
        pairings_involving_limited_or_unknown_history=evidence_pairings,
        provisional_within_limit_pairings=provisional_within,
        missing_prediction_pairings=missing,
        invalid_prediction_pairings=invalid,
        limitations=tuple(limitations),
    )
    return GroupAssessment(
        entrant_ids=tuple(team.entrant_id for team in teams),
        teams=teams,
        policy=policy,
        projected_fit=projected,
        evidence_coverage=evidence,
        pairings=pairings,
    )


def assess_group_addition(
    entrant_ids: Sequence[str],
    added_entrant_id: str,
    predictions: Mapping[tuple[str, str], ComparePrediction],
    policy: seeding_tiers.TierPolicy,
    team_metadata: Mapping[str, GroupTeam],
    *,
    direction: str = "explicit",
) -> GroupAdditionAssessment:
    """Explain the exact matchups introduced by adding one supplied team."""
    if added_entrant_id in entrant_ids:
        raise ValueError("The added entrant is already a member of the group")
    original = assess_group(entrant_ids, predictions, policy, team_metadata)
    expanded = assess_group(
        (*entrant_ids, added_entrant_id), predictions, policy, team_metadata
    )
    new_pairings = tuple(
        item for item in expanded.pairings if added_entrant_id in item.entrant_ids
    )
    new_over_limit = tuple(
        item for item in new_pairings if item.within_both_limits is False
    )
    new_unavailable = tuple(
        item for item in new_pairings if item.prediction_status != PREDICTION_AVAILABLE
    )
    original_unavailable = tuple(
        item
        for item in original.pairings
        if item.prediction_status != PREDICTION_AVAILABLE
    )
    added_team = team_metadata[added_entrant_id]
    added_limitations = []
    if added_team.history_quality == LIMITED_HISTORY:
        added_limitations.append("The added team has the existing limited-history flag.")
    elif added_team.history_quality == UNKNOWN_HISTORY:
        added_limitations.append("The added team has unknown history metadata.")
    provisional_count = sum(item.provisional_due_to_history for item in new_pairings)
    if provisional_count:
        added_limitations.append(
            f"{provisional_count} newly introduced pairing(s) involve limited or unknown history."
        )
    if new_unavailable:
        added_limitations.append(
            f"{len(new_unavailable)} newly introduced prediction(s) are missing or invalid."
        )
    before = original.projected_fit
    after = expanded.projected_fit
    return GroupAdditionAssessment(
        direction=direction,
        added_team=added_team,
        original_group=original,
        expanded_group=expanded,
        newly_introduced_matchups=new_pairings,
        newly_over_limit_matchups=new_over_limit,
        newly_missing_or_invalid_matchups=new_unavailable,
        original_over_limit_matchups=before.over_limit_matchups,
        original_missing_or_invalid_matchups=original_unavailable,
        original_group_had_projected_failures=bool(before.over_limit_matchups),
        original_group_had_incomplete_predictions=not before.complete_prediction_coverage,
        average_expected_absolute_goal_difference_change=_difference(
            after.average_expected_absolute_goal_difference,
            before.average_expected_absolute_goal_difference,
        ),
        maximum_expected_absolute_goal_difference_change=_difference(
            after.maximum_expected_absolute_goal_difference,
            before.maximum_expected_absolute_goal_difference,
        ),
        average_blowout_probability_change=_difference(
            after.average_blowout_probability, before.average_blowout_probability
        ),
        maximum_blowout_probability_change=_difference(
            after.maximum_blowout_probability, before.maximum_blowout_probability
        ),
        average_matchup_cost_change=_difference(
            after.average_matchup_cost, before.average_matchup_cost
        ),
        maximum_matchup_cost_change=_difference(
            after.maximum_matchup_cost, before.maximum_matchup_cost
        ),
        added_evidence_limitations=tuple(added_limitations),
    )


def assess_contiguous_groups(
    ordered_ids: Sequence[str],
    requested_sizes: Sequence[int],
    predictions: Mapping[tuple[str, str], ComparePrediction],
    policy: seeding_tiers.TierPolicy,
    team_metadata: Mapping[str, GroupTeam],
) -> ContiguousGroupScan:
    """Assess every contiguous candidate for the explicitly requested sizes."""
    order = tuple(ordered_ids)
    if len(order) != len(set(order)):
        raise ValueError("The MatchBalance order must contain unique entrant IDs")
    _validate_teams(order, team_metadata)
    sizes = tuple(requested_sizes)
    if len(sizes) != len(set(sizes)):
        raise ValueError("Requested group sizes must be unique")
    if any(isinstance(size, bool) or not isinstance(size, int) or size < 1 for size in sizes):
        raise ValueError("Requested group sizes must be positive integers")
    available_sizes = tuple(size for size in sizes if size <= len(order))
    unavailable_sizes = tuple(size for size in sizes if size > len(order))
    candidates = []
    for size in available_sizes:
        for start in range(0, len(order) - size + 1):
            end = start + size
            members = order[start:end]
            assessment = assess_group(members, predictions, policy, team_metadata)
            add_above = (
                assess_group_addition(
                    members,
                    order[start - 1],
                    predictions,
                    policy,
                    team_metadata,
                    direction="above",
                )
                if start > 0
                else None
            )
            add_below = (
                assess_group_addition(
                    members,
                    order[end],
                    predictions,
                    policy,
                    team_metadata,
                    direction="below",
                )
                if end < len(order)
                else None
            )
            candidates.append(
                ContiguousGroupCandidate(
                    requested_size=size,
                    start_order_position=start + 1,
                    end_order_position=end,
                    assessment=assessment,
                    add_above=add_above,
                    add_below=add_below,
                )
            )
    return ContiguousGroupScan(
        ordered_ids=order,
        requested_sizes=sizes,
        available_sizes=available_sizes,
        unavailable_sizes=unavailable_sizes,
        candidates=tuple(candidates),
    )
