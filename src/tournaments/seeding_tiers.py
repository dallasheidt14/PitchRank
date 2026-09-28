"""Explainable tournament tiers from the canonical Compare matchup predictions.

Limits here are an operator's placement policy, not fitted accuracy claims.
Every pair in an automatic tier must pass both limits. Outcome confidence is
reported separately: predicting the winner of an even game can be uncertain
even when both teams have plenty of evidence.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import combinations

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_suggested_order import (
    OrderingConflict,
    TeamMovement,
    resolve_suggested_order,
)

SEEDED = "Seeded"
NOT_FOUND = "Not found in PitchRank"
NO_CURRENT_RATING = "No current rating"
DATA_REVIEW = "Data review required"
PLACEMENT_STATUSES = (SEEDED, NOT_FOUND, NO_CURRENT_RATING, DATA_REVIEW)
REVIEW_STATUSES = frozenset(PLACEMENT_STATUSES) - {SEEDED}
SUPPORTED_SEPARATION = "Supported separation"
NO_MEANINGFUL_SEPARATION = "No meaningful separation"
UNCERTAIN_SEPARATION = "Uncertain"
BOUNDARY_CLASSIFICATIONS = (
    SUPPORTED_SEPARATION,
    NO_MEANINGFUL_SEPARATION,
    UNCERTAIN_SEPARATION,
)


@dataclass(frozen=True)
class TierEntrant:
    entrant_id: str
    team_name: str
    power_score: float | None = None
    review_reason: str | None = None
    limited_history: bool = False
    review_status: str = DATA_REVIEW
    evidence_game_count: int | None = None


@dataclass(frozen=True)
class TierPolicy:
    # The stored key is retained for saved-pack compatibility. It defines when
    # a matchup is competitive enough for the same group, independently of
    # which team is favored.
    max_expected_margin: float = 2.0
    max_blowout_probability: float = 0.30
    blowout_cost_weight: float = 2.0
    # A stricter, separately tunable label for adjacent teams. This is not the
    # same claim as merely being competitive enough for the same group.
    very_close_expected_goal_difference: float = field(default=1.0, kw_only=True)
    # The directional advantage required before a lower PowerScore seed can be
    # considered for local-consensus movement. It is independent of fit limits.
    material_reversal_expected_goal_difference: float = field(default=1.0, kw_only=True)
    max_automatic_seed_movement: int = field(default=2, kw_only=True)
    local_consensus_window_sizes: tuple[int, ...] = field(default=(5, 6, 7), kw_only=True)
    local_consensus_min_shared_opponents: int = field(default=3, kw_only=True)
    local_consensus_support_threshold: float = field(default=0.5, kw_only=True)
    # Competitive-separation evidence is independent of the PowerScore step.
    # Defaults preserve the existing local windows and the older tier
    # diagnostic's direction, risk, and average-margin requirements.
    boundary_window_sizes: tuple[int, ...] = field(default=(3, 4, 5), kw_only=True)
    boundary_min_pairings: int = field(default=2, kw_only=True)
    boundary_min_established_pairings: int = field(default=2, kw_only=True)
    boundary_min_favored_fraction: float = field(default=0.75, kw_only=True)
    boundary_min_average_signed_margin: float = field(default=1.0, kw_only=True)
    boundary_min_over_limit_fraction: float = field(default=0.5, kw_only=True)
    boundary_max_limited_pair_fraction: float = field(default=0.5, kw_only=True)

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_expected_margin) or self.max_expected_margin <= 0:
            raise ValueError("Maximum expected absolute goal difference must be finite and greater than zero")
        if not math.isfinite(self.max_blowout_probability) or not 0 < self.max_blowout_probability <= 1:
            raise ValueError("Maximum four-goal blowout probability must be greater than zero and at most one")
        if not math.isfinite(self.blowout_cost_weight) or self.blowout_cost_weight < 0:
            raise ValueError("Blowout cost weight must be finite and non-negative")
        if (
            not math.isfinite(self.very_close_expected_goal_difference)
            or self.very_close_expected_goal_difference <= 0
        ):
            raise ValueError("Very-close expected goal difference must be finite and greater than zero")
        if self.very_close_expected_goal_difference > self.max_expected_margin:
            raise ValueError("Very-close expected goal difference cannot exceed the competitive limit")
        if (
            not math.isfinite(self.material_reversal_expected_goal_difference)
            or self.material_reversal_expected_goal_difference <= 0
        ):
            raise ValueError("Material-reversal expected goal difference must be finite and greater than zero")
        if (
            isinstance(self.max_automatic_seed_movement, bool)
            or not isinstance(self.max_automatic_seed_movement, int)
            or self.max_automatic_seed_movement < 0
        ):
            raise ValueError("Maximum automatic seed movement must be a non-negative integer")
        windows = tuple(self.local_consensus_window_sizes)
        if not windows or any(isinstance(value, bool) or not isinstance(value, int) or value < 2 for value in windows):
            raise ValueError("Local-consensus window sizes must be integers of at least two")
        if len(set(windows)) != len(windows):
            raise ValueError("Local-consensus window sizes must be unique")
        object.__setattr__(self, "local_consensus_window_sizes", windows)
        if (
            isinstance(self.local_consensus_min_shared_opponents, bool)
            or not isinstance(self.local_consensus_min_shared_opponents, int)
            or self.local_consensus_min_shared_opponents < 1
        ):
            raise ValueError("Local consensus needs at least one shared opponent")
        if (
            not math.isfinite(self.local_consensus_support_threshold)
            or not 0 <= self.local_consensus_support_threshold < 1
        ):
            raise ValueError("Local-consensus support threshold must be at least zero and less than one")
        boundary_windows = tuple(self.boundary_window_sizes)
        if (
            not boundary_windows
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 3
                for value in boundary_windows
            )
        ):
            raise ValueError("Boundary window sizes must be integers of at least three")
        if len(set(boundary_windows)) != len(boundary_windows):
            raise ValueError("Boundary window sizes must be unique")
        object.__setattr__(self, "boundary_window_sizes", boundary_windows)
        for value, label in (
            (self.boundary_min_pairings, "Boundary minimum pairings"),
            (self.boundary_min_established_pairings, "Boundary minimum established pairings"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{label} must be a positive integer")
        for value, label in (
            (self.boundary_min_favored_fraction, "Boundary favored fraction"),
            (self.boundary_min_over_limit_fraction, "Boundary over-limit fraction"),
            (self.boundary_max_limited_pair_fraction, "Boundary limited-history fraction"),
        ):
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{label} must be between zero and one")
        if self.boundary_min_favored_fraction <= 0:
            raise ValueError("Boundary favored fraction must be greater than zero")
        if self.boundary_min_over_limit_fraction <= 0:
            raise ValueError("Boundary over-limit fraction must be greater than zero")
        if (
            not math.isfinite(self.boundary_min_average_signed_margin)
            or self.boundary_min_average_signed_margin <= 0
        ):
            raise ValueError("Boundary average signed margin must be finite and greater than zero")


@dataclass(frozen=True)
class TierGroup:
    number: int
    entrant_ids: tuple[str, ...]
    max_expected_absolute_goal_difference: float
    max_blowout_probability: float
    worst_pair: tuple[str, str] | None


@dataclass(frozen=True)
class TierAnalysis:
    tiers: tuple[TierGroup, ...]
    review: Mapping[str, str]
    borderline: Mapping[str, tuple[int, ...]]
    boundaries: tuple[str, ...]
    ordered_ids: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class StrengthBreak:
    """A presentation projection of a supported boundary assessment."""

    after_seed: int
    score_gap: float
    average_expected_margin: float
    supported_windows: tuple[int, ...]
    standout: bool = False
    standout_start_seed: int | None = None
    standout_end_seed: int | None = None


@dataclass(frozen=True)
class BoundaryWindow:
    """Internal evidence for one configured local window at a boundary."""

    after_seed: int
    size: int
    upper_ids: tuple[str, ...]
    lower_ids: tuple[str, ...]
    pairing_count: int
    favored_fraction: float
    over_limit_fraction: float
    average_expected_margin: float
    average_expected_absolute_goal_difference: float
    maximum_expected_absolute_goal_difference: float
    average_blowout_probability: float
    maximum_blowout_probability: float
    worst_pair: tuple[str, str] | None
    established_team_count: int
    limited_history_team_count: int
    established_pairing_count: int
    limited_history_pairing_count: int
    low_confidence_pairing_count: int
    evidence_quality: str
    evidence_sufficient: bool
    direction_supported: bool
    risk_supported: bool
    supported: bool


@dataclass(frozen=True)
class BoundaryAssessment:
    """Complete, deterministic analysis for one adjacent suggested-order line."""

    after_seed: int
    upper_ids: tuple[str, ...]
    lower_ids: tuple[str, ...]
    pairing_count: int
    favored_fraction: float
    average_expected_margin: float
    average_expected_absolute_goal_difference: float
    maximum_expected_absolute_goal_difference: float
    average_blowout_probability: float
    maximum_blowout_probability: float
    over_limit_fraction: float
    worst_pair: tuple[str, str] | None
    established_team_count: int
    limited_history_team_count: int
    established_pairing_count: int
    limited_history_pairing_count: int
    low_confidence_pairing_count: int
    evidence_quality: str
    adjacent_pair_expected_margin: float
    adjacent_pair_expected_absolute_goal_difference: float
    adjacent_pair_blowout_probability: float
    adjacent_pair_over_limit: bool
    adjacent_pair_limited_history: bool
    adjacent_pair_low_confidence: bool
    upper_power_score: float
    lower_power_score: float
    power_score_gap: float
    tested_window_sizes: tuple[int, ...]
    usable_window_sizes: tuple[int, ...]
    classification: str
    reason: str


@dataclass(frozen=True)
class CloseRange:
    """Internal range passing matchup limits, not a claim of equal strength."""

    start_seed: int
    end_seed: int
    entrant_ids: tuple[str, ...]
    average_matchup_cost: float
    max_expected_absolute_goal_difference: float
    max_blowout_probability: float
    worst_pair: tuple[str, str]


@dataclass(frozen=True)
class PlacementCheck:
    """A material disagreement for the operator, never a director warning."""

    upper_seed: int
    lower_seed: int
    lower_expected_advantage: float


@dataclass(frozen=True)
class LocalConsensusCheck:
    """PowerScore-anchored evidence for a possible MatchBalance move."""

    entrant_id: str
    compared_with_id: str
    baseline_seed: int
    compared_with_seed: int
    proposed_seed: int | None
    direct_expected_advantage: float
    neighborhood_ids: tuple[str, ...]
    support_fraction: float
    average_profile_advantage: float
    tested_window_sizes: tuple[int, ...]
    minimum_game_count: int | None
    evidence_quality: str
    stable: bool
    supported: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class CheatSheetAnalysis:
    """Format-neutral competitive reference for a cohort.

    ``tiers``, ``borderline``, and ``boundaries`` are retained only so older
    saved packs and operator diagnostics can be read during the migration. The
    public sheet uses ``ordered_ids`` and a prioritized projection of supported
    boundaries. ``boundary_assessments`` is the complete analytical result;
    ``close_ranges`` drives subtle customer annotations and ``boundary_windows``
    preserves the underlying local-window evidence.
    """

    ordered_ids: tuple[str, ...]
    review: Mapping[str, str]
    placement_status: Mapping[str, str]
    breaks: tuple[StrengthBreak, ...]
    close_ranges: tuple[CloseRange, ...]
    notes: tuple[str, ...]
    diagnostics: tuple[str, ...]
    boundary_windows: tuple[BoundaryWindow, ...] = ()
    boundary_assessments: tuple[BoundaryAssessment, ...] = ()
    standouts: tuple[StrengthBreak, ...] = ()
    limited_history: tuple[str, ...] = ()
    placement_checks: tuple[PlacementCheck, ...] = ()
    local_consensus_checks: tuple[LocalConsensusCheck, ...] = ()
    tiers: tuple[TierGroup, ...] = ()
    borderline: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    boundaries: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    baseline_order: tuple[str, ...] = ()
    suggested_order: tuple[str, ...] = ()
    manual_override: bool = False
    manual_holds: tuple[str, ...] = ()
    movements: tuple[TeamMovement, ...] = ()
    ordering_conflicts: tuple[OrderingConflict, ...] = ()

    @property
    def supported_boundaries(self) -> tuple[BoundaryAssessment, ...]:
        return tuple(
            item for item in self.boundary_assessments
            if item.classification == SUPPORTED_SEPARATION
        )

    @property
    def uncertain_boundaries(self) -> tuple[BoundaryAssessment, ...]:
        return tuple(
            item for item in self.boundary_assessments
            if item.classification == UNCERTAIN_SEPARATION
        )

    @property
    def non_separating_boundaries(self) -> tuple[BoundaryAssessment, ...]:
        return tuple(
            item for item in self.boundary_assessments
            if item.classification == NO_MEANINGFUL_SEPARATION
        )

    def marker_for_seed(self, seed: int) -> str:
        for item in self.breaks:
            if item.after_seed == seed:
                return (
                    "Competitive Break: projected matchup quality worsens between "
                    f"seeds {seed} and {seed + 1}; PowerScore difference "
                    f"{abs(item.score_gap) * 100:.1f} points."
                )
        return ""


@dataclass(frozen=True)
class _Pair:
    margin: float
    absolute_goal_difference: float
    blowout: float
    low_confidence: bool


def _display_key(entrant: TierEntrant) -> tuple[float, str, str]:
    score = entrant.power_score if entrant.power_score is not None else -1.0
    return (-score, entrant.team_name.casefold(), entrant.entrant_id)


def _pair_key(first: str, second: str) -> tuple[str, str]:
    return (first, second) if first < second else (second, first)


def _read_pairs(
    ids: Sequence[str], predictions: Mapping[tuple[str, str], ComparePrediction]
) -> dict[tuple[str, str], _Pair]:
    pairs: dict[tuple[str, str], _Pair] = {}
    for first, second in combinations(sorted(ids), 2):
        forward = predictions.get((first, second))
        reverse = predictions.get((second, first))
        prediction = forward if forward is not None else reverse
        if prediction is None:
            raise ValueError(
                f"Missing Compare prediction for {first} vs {second}; rebuild the cohort matchups before tiering"
            )
        for candidate in (forward, reverse):
            if candidate is None:
                continue
            if not math.isfinite(candidate.expected_margin):
                raise ValueError(f"Non-finite expected margin for {first} vs {second}")
            if (
                not math.isfinite(candidate.expected_absolute_goal_difference)
                or candidate.expected_absolute_goal_difference < 0
                or candidate.expected_absolute_goal_difference + 1e-8 < abs(candidate.expected_margin)
            ):
                raise ValueError(f"Invalid expected absolute goal difference for {first} vs {second}")
            if (
                not math.isfinite(candidate.blowout_4plus_probability)
                or not 0 <= candidate.blowout_4plus_probability <= 1
            ):
                raise ValueError(f"Invalid four-goal blowout probability for {first} vs {second}")
        if forward is not None and reverse is not None:
            if not math.isclose(forward.expected_margin, -reverse.expected_margin, abs_tol=1e-8) or not math.isclose(
                forward.blowout_4plus_probability, reverse.blowout_4plus_probability, abs_tol=1e-8
            ) or not math.isclose(
                forward.expected_absolute_goal_difference,
                reverse.expected_absolute_goal_difference,
                abs_tol=1e-8,
            ):
                raise ValueError(f"Inconsistent forward/reverse Compare predictions for {first} vs {second}")
        pairs[(first, second)] = _Pair(
            margin=prediction.expected_margin if forward is not None else -prediction.expected_margin,
            absolute_goal_difference=prediction.expected_absolute_goal_difference,
            blowout=prediction.blowout_4plus_probability,
            low_confidence=getattr(prediction, "confidence", None) == "low",
        )
    return pairs


def _margin(pairs: Mapping[tuple[str, str], _Pair], first: str, second: str) -> float:
    pair = pairs[_pair_key(first, second)]
    return pair.margin if first < second else -pair.margin


def _risk(pair: _Pair, policy: TierPolicy) -> float:
    return max(
        pair.absolute_goal_difference / policy.max_expected_margin,
        pair.blowout / policy.max_blowout_probability,
    )


def _matchup_cost(pair: _Pair, policy: TierPolicy) -> float:
    """Policy-weighted competitive-fit cost, independent of favored direction."""
    return pair.absolute_goal_difference + policy.blowout_cost_weight * pair.blowout


def _automatic_groups(
    ordered: Sequence[str],
    pairs: Mapping[tuple[str, str], _Pair],
    policy: TierPolicy,
    strength: Mapping[str, float],
) -> list[tuple[str, ...]]:
    """Minimum complete-link bands, with boundaries at published score breaks.

    Interval risk and safety are built in O(n²), followed by an O(n²) dynamic
    program. Among safe partitions with the same minimum tier count, maximize
    the total adjacent PowerScore gap at the boundaries, then minimize
    total within-tier pair risk. The gap chooses between fully checked bands;
    it never replaces the every-pair safety requirement. A deterministic
    boundary tuple breaks any remaining ties.
    """
    count = len(ordered)
    safe: dict[tuple[int, int], bool] = {}
    cost: dict[tuple[int, int], float] = {}
    for end in range(1, count + 1):
        extra_cost = 0.0
        extra_safe = True
        for start in range(end - 1, -1, -1):
            if start < end - 1:
                pair_risk = _risk(pairs[_pair_key(ordered[start], ordered[end - 1])], policy)
                extra_cost += pair_risk * pair_risk
                extra_safe = extra_safe and pair_risk <= 1.0
            safe[(start, end)] = extra_safe and safe.get((start, end - 1), True)
            cost[(start, end)] = extra_cost + cost.get((start, end - 1), 0.0)

    best: list[tuple[int, float, float, tuple[int, ...]]] = [(0, 0.0, 0.0, ())]
    for end in range(1, count + 1):
        candidates = []
        for start in range(end):
            if safe[(start, end)]:
                previous = best[start]
                boundary_gap = strength[ordered[start - 1]] - strength[ordered[start]] if start else 0.0
                candidates.append(
                    (
                        previous[0] + 1,
                        previous[1] - boundary_gap,
                        previous[2] + cost[(start, end)],
                        (*previous[3], end),
                    )
                )
        best.append(min(candidates))
    result = []
    start = 0
    for end in best[-1][3]:
        result.append(tuple(ordered[start:end]))
        start = end
    return result


def _manual_groups(
    groups: Sequence[Sequence[str]], eligible_ids: Sequence[str]
) -> list[tuple[str, ...]]:
    result = [tuple(group) for group in groups]
    if any(not group for group in result):
        raise ValueError("Manual tiers cannot contain an empty tier")
    flattened = [entrant_id for group in result for entrant_id in group]
    if Counter(flattened) != Counter(eligible_ids):
        raise ValueError("Manual tiers must contain every eligible entrant exactly once and no review-only entrants")
    return result


def build_tiers(
    entrants: Sequence[TierEntrant],
    predictions: Mapping[tuple[str, str], ComparePrediction],
    policy: TierPolicy = TierPolicy(),
    manual_groups: Sequence[Sequence[str]] | None = None,
) -> TierAnalysis:
    """Propose or inspect tiers without changing rankings, predictions, or data.

    ``review_reason`` is supplied by the evidence-loading layer. Such entrants
    remain explicitly listed for placement review, rather than being treated as
    the weakest teams. All other entrants require a prediction for every peer.
    Manual groups may exceed the policy, but the returned warnings state that.
    PowerScore is the published seed order. Automatic tiers are contiguous
    blocks of that order, while Compare checks every within-tier matchup and
    chooses the clearest safe boundaries. ``ordered_ids`` is the displayed order.

    "Clear separation" requires the upper tier to be favored in at least 75%
    of cross-tier pairs, at least 50% to exceed a within-tier limit, and the
    average signed margin to reach half the margin limit. Other boundaries
    explicitly describe overlap or a ranking/matchup order conflict; a partition
    alone is not evidence of a gap.
    """
    by_id: dict[str, TierEntrant] = {}
    for entrant in entrants:
        if not entrant.entrant_id or entrant.entrant_id.strip() != entrant.entrant_id:
            raise ValueError("Every entrant needs a non-empty ID without surrounding whitespace")
        if entrant.entrant_id in by_id:
            raise ValueError(f"Duplicate entrant ID: {entrant.entrant_id}")
        if entrant.power_score is not None and not math.isfinite(entrant.power_score):
            raise ValueError(f"Non-finite PowerScore for {entrant.entrant_id}")
        by_id[entrant.entrant_id] = entrant
    review = {key: str(value.review_reason) for key, value in sorted(by_id.items()) if value.review_reason}
    eligible = [key for key in sorted(by_id) if key not in review]
    pairs = _read_pairs(eligible, predictions)
    seed_strength = {
        key: by_id[key].power_score if by_id[key].power_score is not None else -1.0
        for key in eligible
    }
    ordered = sorted(eligible, key=lambda key: _display_key(by_id[key]))
    if manual_groups is None:
        groups = _automatic_groups(ordered, pairs, policy, seed_strength)
    else:
        # The supplied order is the operator's Tier column. A notes-only save
        # must preserve suggested seeds even when Compare favors a lower seed.
        groups = _manual_groups(manual_groups, eligible)
    groups = [tuple(sorted(group, key=lambda key: _display_key(by_id[key]))) for group in groups]
    tiers = []
    warnings = []
    for number, group in enumerate(groups, 1):
        group_pairs = sorted(_pair_key(first, second) for first, second in combinations(group, 2))
        worst = max(group_pairs, key=lambda key: _risk(pairs[key], policy)) if group_pairs else None
        max_margin = max((pairs[key].absolute_goal_difference for key in group_pairs), default=0.0)
        max_blowout = max((pairs[key].blowout for key in group_pairs), default=0.0)
        tiers.append(TierGroup(number, group, max_margin, max_blowout, worst))
        if worst is not None and _risk(pairs[worst], policy) > 1:
            warnings.append(
                f"Tier {number} exceeds the matchup limits: up to {max_margin:.2f} "
                "expected absolute goal difference and "
                f"{max_blowout:.0%} chance of a four-goal margin. Review "
                f"{by_id[worst[0]].team_name} vs {by_id[worst[1]].team_name}."
            )
        if len(group) == 1:
            warnings.append(f"Tier {number} has one team; there is no within-tier matchup to assess.")

    borderline: dict[str, list[int]] = {}
    boundaries = []
    for index in range(len(groups) - 1):
        upper, lower = groups[index], groups[index + 1]
        margins = [_margin(pairs, first, second) for first in upper for second in lower]
        favored = sum(margin > 1e-8 for margin in margins)
        risky = sum(_risk(pairs[_pair_key(first, second)], policy) > 1 for first in upper for second in lower)
        average = math.fsum(margins) / len(margins)
        clear = (
            favored / len(margins) >= 0.75
            and risky / len(margins) >= 0.5
            and average >= policy.max_expected_margin / 2
        )
        if average < -1e-8:
            label = "Ranking/matchup order conflict; review the boundary"
        else:
            label = "Clear separation" if clear else "Overlapping matchups; review the boundary"
        boundaries.append(
            f"Tier {index + 1} / Tier {index + 2}: {label}. Upper tier favored in {favored}/{len(margins)} "
            f"matchups, with an average expected edge of {average:.2f} goals; "
            f"{risky}/{len(margins)} exceed the within-tier limits."
        )
        # A director can only move the two teams that touch the published seed
        # boundary: the last seed in the upper tier or the first seed in the
        # lower tier. Testing every member here produced mathematically safe but
        # operationally nonsensical advice such as moving seed 1 below seed 3.
        for members, neighbors, entrant_id, number in (
            (upper, lower, upper[-1], index + 2),
            (lower, upper, lower[0], index + 1),
        ):
            if len(members) == 1:
                continue
            remaining = tuple(key for key in members if key != entrant_id)
            destination = (*neighbors, entrant_id)
            remaining_safe = all(
                _risk(pairs[_pair_key(a, b)], policy) <= 1 for a, b in combinations(remaining, 2)
            )
            destination_safe = all(
                _risk(pairs[_pair_key(a, b)], policy) <= 1 for a, b in combinations(destination, 2)
            )
            if remaining_safe and destination_safe:
                borderline.setdefault(entrant_id, []).append(number)
    # Matchup cycles can skip a neighboring tier. Inspect every cross-tier
    # pairing so an apparent A > B > C hierarchy cannot conceal C beating A.
    for upper_index, lower_index in combinations(range(len(groups)), 2):
        if any(
            _margin(pairs, first, second) < -1e-8
            for first in groups[upper_index]
            for second in groups[lower_index]
        ):
            warnings.append(
                f"Tiers {upper_index + 1} and {lower_index + 1} have a strength-order exception: "
                "at least one lower-tier team is favored against an upper-tier team."
            )
    low_confidence = sum(pair.low_confidence for pair in pairs.values())
    if low_confidence:
        warnings.append(
            f"{low_confidence}/{len(pairs)} matchups have low outcome confidence. "
            "This can reflect closely matched teams; it is separate from missing team evidence."
        )
    return TierAnalysis(
        tiers=tuple(tiers),
        review=review,
        borderline={key: tuple(values) for key, values in sorted(borderline.items())},
        boundaries=tuple(boundaries),
        ordered_ids=tuple(key for group in groups for key in group),
        warnings=tuple(warnings),
    )


def _window_for_boundary(
    ordered: Sequence[str], boundary: int, size: int,
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """Return a deterministic neighboring window split at ``boundary``.

    ``boundary`` is the number of seeds above the line. A window is available
    only when it contains at least one seed on both sides.
    """
    count = len(ordered)
    if count < size or not 0 < boundary < count:
        return None
    start = max(0, min(boundary - size // 2, count - size))
    if not start < boundary < start + size:
        return None
    return tuple(ordered[start:boundary]), tuple(ordered[boundary:start + size])


def _boundary_window_sizes(ordered: Sequence[str], policy: TierPolicy) -> tuple[int, ...]:
    """Use configured local windows, with a deterministic small-cohort fallback."""
    available = tuple(size for size in policy.boundary_window_sizes if size <= len(ordered))
    if available or len(ordered) < 2:
        return available
    return (len(ordered),)


def _boundary_window_assessment(
    *,
    boundary: int,
    size: int,
    upper: tuple[str, ...],
    lower: tuple[str, ...],
    by_id: Mapping[str, TierEntrant],
    pairs: Mapping[tuple[str, str], _Pair],
    policy: TierPolicy,
) -> BoundaryWindow:
    matchups = [
        (first, second, pairs[_pair_key(first, second)], _margin(pairs, first, second))
        for first in upper
        for second in lower
    ]
    pairing_count = len(matchups)
    favored = sum(margin > 1e-8 for _, _, _, margin in matchups)
    over_limit = sum(_risk(pair, policy) > 1 for _, _, pair, _ in matchups)
    limited_ids = {
        entrant_id for entrant_id in (*upper, *lower)
        if by_id[entrant_id].limited_history
    }
    limited_pairing_count = sum(
        first in limited_ids or second in limited_ids
        for first, second, _, _ in matchups
    )
    established_pairing_count = pairing_count - limited_pairing_count
    limited_fraction = limited_pairing_count / pairing_count if pairing_count else 1.0
    evidence_sufficient = (
        pairing_count >= policy.boundary_min_pairings
        and established_pairing_count >= policy.boundary_min_established_pairings
        and limited_fraction <= policy.boundary_max_limited_pair_fraction
    )
    if pairing_count < policy.boundary_min_pairings:
        evidence_quality = "insufficient"
    elif limited_fraction > policy.boundary_max_limited_pair_fraction:
        evidence_quality = "limited-history-dominated"
    elif established_pairing_count < policy.boundary_min_established_pairings:
        evidence_quality = "insufficient"
    elif limited_pairing_count:
        evidence_quality = "mixed"
    else:
        evidence_quality = "established"

    average_margin = (
        math.fsum(margin for _, _, _, margin in matchups) / pairing_count
        if pairing_count else 0.0
    )
    favored_fraction = favored / pairing_count if pairing_count else 0.0
    over_limit_fraction = over_limit / pairing_count if pairing_count else 0.0
    direction_supported = (
        favored_fraction >= policy.boundary_min_favored_fraction
        and average_margin >= policy.boundary_min_average_signed_margin
    )
    risk_supported = over_limit_fraction >= policy.boundary_min_over_limit_fraction
    worst = max(
        sorted(matchups, key=lambda item: (item[0], item[1])),
        key=lambda item: (
            _risk(item[2], policy),
            _matchup_cost(item[2], policy),
            item[2].absolute_goal_difference,
            item[2].blowout,
        ),
        default=None,
    )
    return BoundaryWindow(
        after_seed=boundary,
        size=size,
        upper_ids=upper,
        lower_ids=lower,
        pairing_count=pairing_count,
        favored_fraction=favored_fraction,
        over_limit_fraction=over_limit_fraction,
        average_expected_margin=average_margin,
        average_expected_absolute_goal_difference=(
            math.fsum(pair.absolute_goal_difference for _, _, pair, _ in matchups) / pairing_count
            if pairing_count else 0.0
        ),
        maximum_expected_absolute_goal_difference=max(
            (pair.absolute_goal_difference for _, _, pair, _ in matchups), default=0.0,
        ),
        average_blowout_probability=(
            math.fsum(pair.blowout for _, _, pair, _ in matchups) / pairing_count
            if pairing_count else 0.0
        ),
        maximum_blowout_probability=max(
            (pair.blowout for _, _, pair, _ in matchups), default=0.0,
        ),
        worst_pair=(worst[0], worst[1]) if worst else None,
        established_team_count=len((*upper, *lower)) - len(limited_ids),
        limited_history_team_count=len(limited_ids),
        established_pairing_count=established_pairing_count,
        limited_history_pairing_count=limited_pairing_count,
        low_confidence_pairing_count=sum(pair.low_confidence for _, _, pair, _ in matchups),
        evidence_quality=evidence_quality,
        evidence_sufficient=evidence_sufficient,
        direction_supported=direction_supported,
        risk_supported=risk_supported,
        supported=evidence_sufficient and direction_supported and risk_supported,
    )


def _classify_boundary(
    windows: Sequence[BoundaryWindow], policy: TierPolicy, adjacent_pair: _Pair,
) -> tuple[str, str, tuple[int, ...]]:
    usable = tuple(item for item in windows if item.evidence_sufficient)
    usable_sizes = tuple(item.size for item in usable)
    if not usable:
        return (
            UNCERTAIN_SEPARATION,
            "Too few established cross-boundary pairings are available, or limited-history "
            "pairings dominate every local window.",
            usable_sizes,
        )
    usable_summary = f"{len(usable)}/{len(windows)} evidence-sufficient local window(s)"
    if _risk(adjacent_pair, policy) <= 1:
        if any(item.risk_supported for item in usable):
            return (
                UNCERTAIN_SEPARATION,
                "The immediate matchup remains within both competitive limits, but broader local "
                "windows show substantial risk; the boundary location is conflicting.",
                usable_sizes,
            )
        return (
            NO_MEANINGFUL_SEPARATION,
            f"The teams immediately across the line remain within both competitive limits; "
            f"{usable_summary} provide supporting context.",
            usable_sizes,
        )
    if all(item.supported for item in usable):
        return (
            SUPPORTED_SEPARATION,
            f"{usable_summary} meet both the directional and competitive-risk thresholds.",
            usable_sizes,
        )
    if all(not item.risk_supported for item in usable):
        return (
            NO_MEANINGFUL_SEPARATION,
            f"{usable_summary} keep the fraction failing the competitive limits below "
            f"{policy.boundary_min_over_limit_fraction:.0%}; crossing the boundary remains "
            "competitively reasonable.",
            usable_sizes,
        )
    if any(item.risk_supported for item in usable) and not all(
        item.risk_supported for item in usable
    ):
        reason = "Usable local windows disagree on whether cross-boundary competitive risk is substantial."
    else:
        reason = (
            "Cross-boundary competitive risk is substantial, but directional support or average "
            "signed separation is too weak or conflicting."
        )
    return UNCERTAIN_SEPARATION, reason, usable_sizes


def _build_boundary_assessments(
    ordered: Sequence[str],
    by_id: Mapping[str, TierEntrant],
    pairs: Mapping[tuple[str, str], _Pair],
    policy: TierPolicy,
) -> tuple[tuple[BoundaryAssessment, ...], tuple[BoundaryWindow, ...]]:
    assessments: list[BoundaryAssessment] = []
    all_windows: list[BoundaryWindow] = []
    window_sizes = _boundary_window_sizes(ordered, policy)
    for boundary in range(1, len(ordered)):
        windows: list[BoundaryWindow] = []
        for size in window_sizes:
            split = _window_for_boundary(ordered, boundary, size)
            if split is None:
                continue
            window = _boundary_window_assessment(
                boundary=boundary,
                size=size,
                upper=split[0],
                lower=split[1],
                by_id=by_id,
                pairs=pairs,
                policy=policy,
            )
            windows.append(window)
            all_windows.append(window)
        if not windows:
            raise AssertionError(f"Boundary {boundary} has no deterministic local window")
        primary = max(windows, key=lambda item: item.size)
        upper_boundary_id = ordered[boundary - 1]
        lower_boundary_id = ordered[boundary]
        adjacent_pair = pairs[_pair_key(upper_boundary_id, lower_boundary_id)]
        adjacent_margin = _margin(pairs, upper_boundary_id, lower_boundary_id)
        classification, reason, usable_sizes = _classify_boundary(
            windows, policy, adjacent_pair,
        )
        upper_score = by_id[upper_boundary_id].power_score
        lower_score = by_id[lower_boundary_id].power_score
        upper_power_score = float(upper_score) if upper_score is not None else 0.0
        lower_power_score = float(lower_score) if lower_score is not None else 0.0
        assessments.append(BoundaryAssessment(
            after_seed=boundary,
            upper_ids=primary.upper_ids,
            lower_ids=primary.lower_ids,
            pairing_count=primary.pairing_count,
            favored_fraction=primary.favored_fraction,
            average_expected_margin=primary.average_expected_margin,
            average_expected_absolute_goal_difference=(
                primary.average_expected_absolute_goal_difference
            ),
            maximum_expected_absolute_goal_difference=(
                primary.maximum_expected_absolute_goal_difference
            ),
            average_blowout_probability=primary.average_blowout_probability,
            maximum_blowout_probability=primary.maximum_blowout_probability,
            over_limit_fraction=primary.over_limit_fraction,
            worst_pair=primary.worst_pair,
            established_team_count=primary.established_team_count,
            limited_history_team_count=primary.limited_history_team_count,
            established_pairing_count=primary.established_pairing_count,
            limited_history_pairing_count=primary.limited_history_pairing_count,
            low_confidence_pairing_count=primary.low_confidence_pairing_count,
            evidence_quality=primary.evidence_quality,
            adjacent_pair_expected_margin=adjacent_margin,
            adjacent_pair_expected_absolute_goal_difference=(
                adjacent_pair.absolute_goal_difference
            ),
            adjacent_pair_blowout_probability=adjacent_pair.blowout,
            adjacent_pair_over_limit=_risk(adjacent_pair, policy) > 1,
            adjacent_pair_limited_history=(
                by_id[upper_boundary_id].limited_history
                or by_id[lower_boundary_id].limited_history
            ),
            adjacent_pair_low_confidence=adjacent_pair.low_confidence,
            upper_power_score=upper_power_score,
            lower_power_score=lower_power_score,
            power_score_gap=upper_power_score - lower_power_score,
            tested_window_sizes=tuple(item.size for item in windows),
            usable_window_sizes=usable_sizes,
            classification=classification,
            reason=reason,
        ))
    return tuple(assessments), tuple(all_windows)


def _pair_neighborhood(
    ordered: Sequence[str], upper_index: int, lower_index: int, size: int,
) -> tuple[str, ...] | None:
    """Return one baseline-anchored window containing both comparison teams."""
    if len(ordered) < size or size < 2 or lower_index - upper_index >= size:
        return None
    midpoint = (upper_index + lower_index) / 2
    start = round(midpoint - (size - 1) / 2)
    start = max(0, min(start, len(ordered) - size))
    if not start <= upper_index < lower_index < start + size:
        return None
    return tuple(ordered[start:start + size])


def _profile_support(
    candidate: str,
    baseline_team: str,
    references: Sequence[str],
    pairs: Mapping[tuple[str, str], _Pair],
    support_threshold: float,
) -> tuple[bool, float, float]:
    """Compare two teams against identical opponents from the baseline neighborhood."""
    advantages = [
        _margin(pairs, candidate, opponent) - _margin(pairs, baseline_team, opponent)
        for opponent in references
    ]
    if not advantages:
        return False, 0.0, 0.0
    support_fraction = sum(value > 1e-8 for value in advantages) / len(advantages)
    average = math.fsum(advantages) / len(advantages)
    # A strict majority plus a positive average prevents one large comparison
    # from turning a mostly contrary neighborhood into apparent consensus.
    supported = support_fraction > support_threshold and average > 1e-8
    return supported, support_fraction, average


def _local_consensus_checks(
    ordered: Sequence[str],
    by_id: Mapping[str, TierEntrant],
    pairs: Mapping[tuple[str, str], _Pair],
    placement_checks: Sequence[PlacementCheck],
    policy: TierPolicy,
) -> tuple[LocalConsensusCheck, ...]:
    """Evaluate material reversals against the frozen PowerScore order.

    The pilot deliberately uses only direction, not a fitted strength score:
    the lower seed must look better against a strict majority of the same
    established-history neighbors, the average profile edge must be positive,
    and that conclusion must survive every available configured window plus
    leave-one-neighbor-out checks. Historical validation of the resulting
    suggestions remains separate work.
    """
    results: list[LocalConsensusCheck] = []
    for check in placement_checks:
        upper_index = check.upper_seed - 1
        lower_index = check.lower_seed - 1
        candidate = ordered[lower_index]
        baseline_team = ordered[upper_index]
        distance = check.lower_seed - check.upper_seed
        blockers: list[str] = []
        if distance > policy.max_automatic_seed_movement:
            blockers.append(
                f"The change spans more than the {policy.max_automatic_seed_movement}-seed movement cap."
            )
        pair_has_reliable_evidence = not (
            by_id[candidate].limited_history or by_id[baseline_team].limited_history
        )
        if not pair_has_reliable_evidence:
            blockers.append("One of the compared teams has limited ranked history.")

        window_results: list[tuple[int, tuple[str, ...], bool, float, float, bool]] = []
        for size in policy.local_consensus_window_sizes:
            window = _pair_neighborhood(ordered, upper_index, lower_index, size)
            if window is None:
                continue
            references = tuple(
                entrant_id for entrant_id in window
                if entrant_id not in {candidate, baseline_team} and not by_id[entrant_id].limited_history
            )
            if len(references) < policy.local_consensus_min_shared_opponents:
                continue
            supported, fraction, average = _profile_support(
                candidate, baseline_team, references, pairs, policy.local_consensus_support_threshold,
            )
            leave_one_out = all(
                _profile_support(
                    candidate,
                    baseline_team,
                    tuple(value for value in references if value != omitted),
                    pairs,
                    policy.local_consensus_support_threshold,
                )[0]
                for omitted in references
            )
            window_results.append((size, references, supported, fraction, average, leave_one_out))

        if not window_results:
            blockers.append(
                "Too few established-history neighbors are available for the configured comparison."
            )
            primary_references: tuple[str, ...] = ()
            support_fraction = 0.0
            average_profile_advantage = 0.0
        else:
            primary = max(window_results, key=lambda item: item[0])
            primary_references = primary[1]
            support_fraction = primary[3]
            average_profile_advantage = primary[4]
            if not all(item[2] for item in window_results):
                blockers.append("The shared-neighborhood comparisons do not consistently support the change.")
            if not all(item[5] for item in window_results):
                blockers.append("The recommendation depends on one unusually influential neighbor.")

        stable = bool(window_results) and all(item[2] and item[5] for item in window_results)
        evidence_ids = {candidate, baseline_team, *primary_references}
        game_counts = [
            by_id[entrant_id].evidence_game_count
            for entrant_id in evidence_ids
            if by_id[entrant_id].evidence_game_count is not None
        ]
        evidence_quality = "established" if pair_has_reliable_evidence else "limited"
        supported = not blockers
        results.append(LocalConsensusCheck(
            entrant_id=candidate,
            compared_with_id=baseline_team,
            baseline_seed=check.lower_seed,
            compared_with_seed=check.upper_seed,
            proposed_seed=check.upper_seed if supported else None,
            direct_expected_advantage=check.lower_expected_advantage,
            neighborhood_ids=primary_references,
            support_fraction=support_fraction,
            average_profile_advantage=average_profile_advantage,
            tested_window_sizes=tuple(item[0] for item in window_results),
            minimum_game_count=min(game_counts) if game_counts else None,
            evidence_quality=evidence_quality,
            stable=stable,
            supported=supported,
            blockers=tuple(blockers),
        ))
    # A two-seed proposal must also earn a supported adjacent proposal over the
    # intervening team. Process shorter moves first so a longer destination can
    # rely only on already-validated crossed-seed evidence.
    validated: dict[int, LocalConsensusCheck] = {}
    supported_by_target: dict[tuple[str, int], LocalConsensusCheck] = {}
    for index, result in sorted(
        enumerate(results),
        key=lambda item: item[1].baseline_seed - item[1].compared_with_seed,
    ):
        crossed_seeds = range(result.compared_with_seed + 1, result.baseline_seed)
        if result.supported and not all(
            supported_by_target.get((result.entrant_id, seed), None)
            and supported_by_target[(result.entrant_id, seed)].supported
            for seed in crossed_seeds
        ):
            result = replace(
                result,
                proposed_seed=None,
                supported=False,
                blockers=(*result.blockers, "The proposed move is not supported over every crossed seed."),
            )
        validated[index] = result
        supported_by_target[(result.entrant_id, result.compared_with_seed)] = result
    return tuple(validated[index] for index in range(len(results)))


def build_cheat_sheet_analysis(
    entrants: Sequence[TierEntrant],
    predictions: Mapping[tuple[str, str], ComparePrediction],
    policy: TierPolicy = TierPolicy(),
    *,
    legacy: TierAnalysis | None = None,
    manual_order: Sequence[str] | None = None,
    manual_holds: Sequence[str] = (),
) -> CheatSheetAnalysis:
    """Build a recommendation without altering PowerScore or publishing a ranking."""
    by_id: dict[str, TierEntrant] = {}
    for entrant in entrants:
        if not entrant.entrant_id or entrant.entrant_id.strip() != entrant.entrant_id:
            raise ValueError("Every entrant needs a non-empty ID without surrounding whitespace")
        if entrant.entrant_id in by_id:
            raise ValueError(f"Duplicate entrant ID: {entrant.entrant_id}")
        if entrant.power_score is not None and not math.isfinite(entrant.power_score):
            raise ValueError(f"Non-finite PowerScore for {entrant.entrant_id}")
        if (
            entrant.evidence_game_count is not None
            and (
                isinstance(entrant.evidence_game_count, bool)
                or not isinstance(entrant.evidence_game_count, int)
                or entrant.evidence_game_count < 0
            )
        ):
            raise ValueError(f"Invalid evidence game count for {entrant.entrant_id}")
        if entrant.review_status not in REVIEW_STATUSES:
            raise ValueError(f"Unknown placement status for {entrant.entrant_id}")
        by_id[entrant.entrant_id] = entrant
    review = {key: str(value.review_reason) for key, value in sorted(by_id.items()) if value.review_reason}
    baseline_order = tuple(
        sorted((key for key in by_id if key not in review), key=lambda key: _display_key(by_id[key]))
    )
    pairs = _read_pairs(baseline_order, predictions)
    statuses = {key: SEEDED for key in baseline_order}
    statuses.update({key: by_id[key].review_status for key in review})

    placement_checks = tuple(
        PlacementCheck(upper + 1, lower + 1, -_margin(pairs, baseline_order[upper], baseline_order[lower]))
        for upper in range(len(baseline_order)) for lower in range(upper + 1, len(baseline_order))
        if (
            _margin(pairs, baseline_order[upper], baseline_order[lower])
            <= -policy.material_reversal_expected_goal_difference
        )
    )
    consensus_checks = _local_consensus_checks(
        baseline_order, by_id, pairs, placement_checks, policy,
    )
    supported_relationships = tuple(
        (item.entrant_id, item.compared_with_id)
        for item in consensus_checks
        if item.supported
    )
    order_result = resolve_suggested_order(
        baseline_order,
        supported_relationships,
        immovable_ids=(key for key in baseline_order if by_id[key].limited_history),
        max_movement=policy.max_automatic_seed_movement,
    )
    suggested_order = order_result.order
    ordered = suggested_order

    boundary_assessments, boundary_windows = _build_boundary_assessments(
        ordered, by_id, pairs, policy,
    )
    assessments_by_seed = {item.after_seed: item for item in boundary_assessments}
    windows_by_seed = {
        boundary: tuple(item for item in boundary_windows if item.after_seed == boundary)
        for boundary in range(1, len(ordered))
    }
    candidates = [
        StrengthBreak(
            after_seed=item.after_seed,
            score_gap=item.power_score_gap,
            average_expected_margin=item.average_expected_margin,
            supported_windows=tuple(
                window.size for window in windows_by_seed[item.after_seed]
                if window.supported
            ),
        )
        for item in boundary_assessments
        if item.classification == SUPPORTED_SEPARATION
    ]

    # The complete analysis above is authoritative. The current customer sheet
    # may still prioritize three lines, but proximity and PowerScore magnitude
    # never remove or reclassify an analytical finding.
    def break_priority(item: StrengthBreak) -> tuple[float, float, float, float, float, int]:
        assessment = assessments_by_seed[item.after_seed]
        return (
            -round(assessment.over_limit_fraction, 12),
            -round(assessment.average_expected_absolute_goal_difference, 12),
            -round(assessment.maximum_expected_absolute_goal_difference, 12),
            -round(assessment.average_blowout_probability, 12),
            -round(assessment.average_expected_margin, 12),
            item.after_seed,
        )

    selected = sorted(sorted(candidates, key=break_priority)[:3], key=lambda item: item.after_seed)
    breaks = tuple(selected)

    close_candidates: list[CloseRange] = []
    for length in range(2, min(5, len(ordered)) + 1):
        for start in range(0, len(ordered) - length + 1):
            members = tuple(ordered[start:start + length])
            member_pairs = [pairs[_pair_key(first, second)] for first, second in combinations(members, 2)]
            if not member_pairs or any(_risk(pair, policy) > 1 for pair in member_pairs):
                continue
            if any(
                pairs[_pair_key(members[index], members[index + 1])].absolute_goal_difference
                > policy.very_close_expected_goal_difference
                for index in range(length - 1)
            ):
                continue
            worst_pair = max(
                combinations(members, 2),
                key=lambda pair: _matchup_cost(pairs[_pair_key(*pair)], policy),
            )
            close_candidates.append(CloseRange(
                start_seed=start + 1,
                end_seed=start + length,
                entrant_ids=members,
                average_matchup_cost=math.fsum(_matchup_cost(pair, policy) for pair in member_pairs)
                / len(member_pairs),
                max_expected_absolute_goal_difference=max(pair.absolute_goal_difference for pair in member_pairs),
                max_blowout_probability=max(pair.blowout for pair in member_pairs),
                worst_pair=_pair_key(*worst_pair),
            ))
    close_ranges: list[CloseRange] = []
    for item in sorted(close_candidates, key=lambda value: (-(value.end_seed - value.start_seed), value.start_seed)):
        if any(
            item.start_seed >= existing.start_seed and item.end_seed <= existing.end_seed
            for existing in close_ranges
        ):
            continue
        close_ranges.append(item)
    close_ranges.sort(key=lambda item: item.start_seed)

    notes: list[str] = []
    for item in selected:
        notes.append(
            "Competitive Break: projected matchup quality worsens between "
            f"seeds {item.after_seed} and {item.after_seed + 1}; PowerScore difference "
            f"{abs(item.score_gap) * 100:.1f} points."
        )

    effective_order = suggested_order
    effective_breaks = breaks
    effective_close_ranges = tuple(close_ranges)
    holds = tuple(manual_holds)
    if manual_order is not None:
        effective_order = tuple(manual_order)
        if len(set(effective_order)) != len(effective_order) or not set(effective_order).issubset(by_id):
            raise ValueError("Manual seed order must contain unique entrants from this cohort")
        if len(set(holds)) != len(holds) or not set(holds).issubset(baseline_order):
            raise ValueError("Manual seed holds must contain unique automatically eligible entrants")
        if set(effective_order) & set(holds):
            raise ValueError("A team cannot have a manual seed and be held for manual placement")
        if set(baseline_order) != (set(effective_order) & set(baseline_order)) | set(holds):
            raise ValueError(
                "Every automatically eligible team needs a unique manual seed or an explicit hold"
            )

        effective_positions = {entrant_id: seed for seed, entrant_id in enumerate(effective_order, 1)}
        retained_breaks = []
        for item in breaks:
            upper_id = suggested_order[item.after_seed - 1]
            lower_id = suggested_order[item.after_seed]
            upper_seed = effective_positions.get(upper_id)
            lower_seed = effective_positions.get(lower_id)
            if upper_seed is not None and lower_seed == upper_seed + 1:
                retained_breaks.append(replace(item, after_seed=upper_seed))
        retained_close = []
        for item in close_ranges:
            members = item.entrant_ids
            for start in range(len(effective_order) - len(members) + 1):
                if effective_order[start:start + len(members)] == members:
                    retained_close.append(replace(item, start_seed=start + 1, end_seed=start + len(members)))
                    break
        effective_breaks = tuple(retained_breaks)
        effective_close_ranges = tuple(retained_close)
        notes = []

    diagnostics: list[str] = []
    low_confidence = sum(pair.low_confidence for pair in pairs.values())
    if low_confidence:
        diagnostics.append(f"{low_confidence}/{len(pairs)} matchups have low outcome confidence.")
    reversals = sum(
        _margin(pairs, first, second) < -1e-8
        for first, second in combinations(baseline_order, 2)
    )
    if reversals:
        diagnostics.append(f"{reversals} matchup prediction(s) favor a lower published seed.")
    diagnostics.append(
        "Every suggested-order boundary is classified independently. Evidence-sufficient "
        f"windows require at least {policy.boundary_min_pairings} pairings, including "
        f"{policy.boundary_min_established_pairings} established-history pairings, with no more "
        f"than {policy.boundary_max_limited_pair_fraction:.0%} limited-history pairings. "
        f"Supported separation requires at least {policy.boundary_min_favored_fraction:.0%} "
        f"upper-side favor, {policy.boundary_min_average_signed_margin:.2f} average signed goals, "
        f"and {policy.boundary_min_over_limit_fraction:.0%} of pairings outside the normal "
        "competitive limits. PowerScore is context, not a gate."
    )
    if order_result.conflicts:
        diagnostics.append(
            f"{len(order_result.conflicts)} supported ordering relationship(s) could not be applied safely."
        )

    return CheatSheetAnalysis(
        ordered_ids=effective_order,
        review=review,
        placement_status=statuses,
        breaks=effective_breaks,
        close_ranges=effective_close_ranges,
        notes=tuple(notes),
        diagnostics=tuple(diagnostics),
        boundary_windows=tuple(boundary_windows),
        boundary_assessments=boundary_assessments,
        standouts=(),
        limited_history=tuple(key for key in baseline_order if by_id[key].limited_history),
        placement_checks=placement_checks,
        local_consensus_checks=consensus_checks,
        tiers=legacy.tiers if legacy else (),
        borderline=legacy.borderline if legacy else {},
        boundaries=legacy.boundaries if legacy else (),
        warnings=legacy.warnings if legacy else (),
        baseline_order=baseline_order,
        suggested_order=suggested_order,
        manual_override=manual_order is not None,
        manual_holds=holds,
        movements=order_result.movements,
        ordering_conflicts=order_result.conflicts,
    )
