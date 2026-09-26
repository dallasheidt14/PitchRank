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
from dataclasses import dataclass, field
from itertools import combinations
from statistics import median

from src.tournaments.compare_predictor_bridge import ComparePrediction

SEEDED = "Seeded"
NOT_FOUND = "Not found in PitchRank"
NO_CURRENT_RATING = "No current rating"
DATA_REVIEW = "Data review required"
PLACEMENT_STATUSES = (SEEDED, NOT_FOUND, NO_CURRENT_RATING, DATA_REVIEW)
REVIEW_STATUSES = frozenset(PLACEMENT_STATUSES) - {SEEDED}


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
    # The directional advantage required before a lower PowerScore seed enters
    # placement review. It is independent of competitive-fit limits.
    material_reversal_expected_goal_difference: float = field(default=1.0, kw_only=True)

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
    """A supported competitive difference between adjacent published seeds."""

    after_seed: int
    score_gap: float
    average_expected_margin: float
    supported_windows: tuple[int, ...]
    standout: bool = False
    standout_start_seed: int | None = None
    standout_end_seed: int | None = None


@dataclass(frozen=True)
class BoundaryWindow:
    """Internal evidence for one tested boundary, including rejected windows."""

    after_seed: int
    size: int
    upper_ids: tuple[str, ...]
    lower_ids: tuple[str, ...]
    favored_fraction: float
    over_limit_fraction: float
    average_expected_margin: float
    supported: bool


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
    """Review-only evidence for a possible move away from PowerScore order."""

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
    public sheet uses ``ordered_ids`` and supported strength observations.
    ``close_ranges`` and ``boundary_windows`` are internal evidence only.
    """

    ordered_ids: tuple[str, ...]
    review: Mapping[str, str]
    placement_status: Mapping[str, str]
    breaks: tuple[StrengthBreak, ...]
    close_ranges: tuple[CloseRange, ...]
    notes: tuple[str, ...]
    diagnostics: tuple[str, ...]
    boundary_windows: tuple[BoundaryWindow, ...] = ()
    standouts: tuple[StrengthBreak, ...] = ()
    limited_history: tuple[str, ...] = ()
    placement_checks: tuple[PlacementCheck, ...] = ()
    local_consensus_checks: tuple[LocalConsensusCheck, ...] = ()
    tiers: tuple[TierGroup, ...] = ()
    borderline: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    boundaries: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def marker_for_seed(self, seed: int) -> str:
        for item in self.breaks:
            if item.after_seed == seed:
                return f"Score step: {item.score_gap * 100:.1f} points between seeds {seed} and {seed + 1}."
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


def _separation_stats(
    upper: Sequence[str], lower: Sequence[str], pairs: Mapping[tuple[str, str], _Pair], policy: TierPolicy,
) -> tuple[bool, float, int, int]:
    margins = [_margin(pairs, first, second) for first in upper for second in lower]
    risky = sum(_risk(pairs[_pair_key(first, second)], policy) > 1 for first in upper for second in lower)
    favored = sum(value > 1e-8 for value in margins)
    average = math.fsum(margins) / len(margins) if margins else 0.0
    supported = bool(margins) and (
        favored / len(margins) >= 0.75
        and average > 1e-8
    )
    return supported, average, favored, risky


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
    supported = sum(value > 1e-8 for value in advantages) * 2 > len(advantages) and average > 1e-8
    return supported, support_fraction, average


def _local_consensus_checks(
    ordered: Sequence[str],
    by_id: Mapping[str, TierEntrant],
    pairs: Mapping[tuple[str, str], _Pair],
    placement_checks: Sequence[PlacementCheck],
    *,
    max_movement: int = 2,
) -> tuple[LocalConsensusCheck, ...]:
    """Evaluate material reversals without changing the PowerScore order.

    The pilot deliberately uses only direction, not a fitted strength score:
    the lower seed must look better against a strict majority of the same
    established-history neighbors, the average profile edge must be positive,
    and that conclusion must survive every available 5-7 team window plus
    leave-one-neighbor-out checks. Threshold calibration and constrained
    reordering remain separate validation work.
    """
    results: list[LocalConsensusCheck] = []
    for check in placement_checks:
        upper_index = check.upper_seed - 1
        lower_index = check.lower_seed - 1
        candidate = ordered[lower_index]
        baseline_team = ordered[upper_index]
        distance = check.lower_seed - check.upper_seed
        blockers: list[str] = []
        if distance > max_movement:
            blockers.append(f"The change spans more than the {max_movement}-seed pilot cap.")
        pair_has_reliable_evidence = not (
            by_id[candidate].limited_history or by_id[baseline_team].limited_history
        )
        if not pair_has_reliable_evidence:
            blockers.append("One of the compared teams has limited ranked history.")

        window_results: list[tuple[int, tuple[str, ...], bool, float, float, bool]] = []
        for size in (5, 6, 7):
            window = _pair_neighborhood(ordered, upper_index, lower_index, size)
            if window is None:
                continue
            references = tuple(
                entrant_id for entrant_id in window
                if entrant_id not in {candidate, baseline_team} and not by_id[entrant_id].limited_history
            )
            if len(references) < 3:
                continue
            supported, fraction, average = _profile_support(candidate, baseline_team, references, pairs)
            leave_one_out = all(
                _profile_support(
                    candidate,
                    baseline_team,
                    tuple(value for value in references if value != omitted),
                    pairs,
                )[0]
                for omitted in references
            )
            window_results.append((size, references, supported, fraction, average, leave_one_out))

        if not window_results:
            blockers.append("Fewer than three established-history neighbors are available for comparison.")
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
    return tuple(results)


def build_cheat_sheet_analysis(
    entrants: Sequence[TierEntrant],
    predictions: Mapping[tuple[str, str], ComparePrediction],
    policy: TierPolicy = TierPolicy(),
    *,
    legacy: TierAnalysis | None = None,
) -> CheatSheetAnalysis:
    """Build a format-neutral reference without assigning divisions or pools."""
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
    ordered = tuple(sorted((key for key in by_id if key not in review), key=lambda key: _display_key(by_id[key])))
    pairs = _read_pairs(ordered, predictions)
    statuses = {key: SEEDED for key in ordered}
    statuses.update({key: by_id[key].review_status for key in review})

    candidates: list[StrengthBreak] = []
    boundary_windows: list[BoundaryWindow] = []
    score_gaps = [
        (by_id[first].power_score or 0.0) - (by_id[second].power_score or 0.0)
        for first, second in zip(ordered, ordered[1:])
    ]
    # A display heuristic for conspicuous score steps, not a fitted predictor
    # threshold: at least two points and three times the other steps' median.
    # Exclude the candidate so a large gap cannot set its own rejection threshold.
    # Fixed-scale score bars still show gradual differences without forcing lines.
    for boundary in range(1, len(ordered)):
        window_results: list[tuple[int, bool, float, int, int]] = []
        for size in (3, 4, 5):
            window = _window_for_boundary(ordered, boundary, size)
            if window is None:
                continue
            supported, average, favored, risky = _separation_stats(*window, pairs, policy)
            window_results.append((size, supported, average, favored, risky))
            pair_count = len(window[0]) * len(window[1])
            boundary_windows.append(BoundaryWindow(
                after_seed=boundary, size=size, upper_ids=window[0], lower_ids=window[1],
                favored_fraction=favored / pair_count, over_limit_fraction=risky / pair_count,
                average_expected_margin=average, supported=supported,
            ))
        if not window_results or not all(item[1] for item in window_results):
            continue
        averages = [item[2] for item in window_results]
        score_gap = score_gaps[boundary - 1]
        other_gaps = score_gaps[:boundary - 1] + score_gaps[boundary:]
        minimum_score_step = max(0.02, 3 * median(other_gaps)) if other_gaps else 0.02
        if score_gap + 1e-12 < minimum_score_step:
            continue
        candidates.append(StrengthBreak(
            after_seed=boundary,
            score_gap=score_gap,
            average_expected_margin=math.fsum(averages) / len(averages),
            supported_windows=tuple(item[0] for item in window_results),
            standout=boundary <= 2 or len(ordered) - boundary <= 2,
            standout_start_seed=(1 if boundary <= 2 else boundary + 1)
            if boundary <= 2 or len(ordered) - boundary <= 2 else None,
            standout_end_seed=(boundary if boundary <= 2 else len(ordered))
            if boundary <= 2 or len(ordered) - boundary <= 2 else None,
        ))

    # Keep the strongest line when several nearby windows describe the same
    # gap. A standout at either end becomes a note rather than a divider.
    selected: list[StrengthBreak] = []
    def break_priority(item: StrengthBreak) -> tuple[float, float, int]:
        # Arithmetic noise in equal decimal score gaps must not outrank
        # the matchup evidence. Keep original precision in stored evidence.
        return (-round(item.score_gap, 12), -round(item.average_expected_margin, 12), item.after_seed)

    for candidate in sorted(candidates, key=break_priority):
        if any(abs(candidate.after_seed - item.after_seed) <= 2 for item in selected):
            continue
        selected.append(candidate)
    selected = sorted(sorted(selected, key=break_priority)[:3], key=lambda item: item.after_seed)
    breaks = tuple(item for item in selected if not item.standout)

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
    for item in sorted(selected, key=break_priority)[:3]:
        if item.standout:
            notes.append(
                f"Seed {item.after_seed} is {item.score_gap * 100:.1f} points above seed {item.after_seed + 1}."
            )
        else:
            notes.append(
                f"Score step: {item.score_gap * 100:.1f} points between seeds "
                f"{item.after_seed} and {item.after_seed + 1}."
            )

    placement_checks = tuple(
        PlacementCheck(upper + 1, lower + 1, -_margin(pairs, ordered[upper], ordered[lower]))
        for upper in range(len(ordered)) for lower in range(upper + 1, len(ordered))
        if (
            _margin(pairs, ordered[upper], ordered[lower])
            <= -policy.material_reversal_expected_goal_difference
        )
    )

    diagnostics: list[str] = []
    low_confidence = sum(pair.low_confidence for pair in pairs.values())
    if low_confidence:
        diagnostics.append(f"{low_confidence}/{len(pairs)} matchups have low outcome confidence.")
    reversals = sum(_margin(pairs, first, second) < -1e-8 for first, second in combinations(ordered, 2))
    if reversals:
        diagnostics.append(f"{reversals} matchup prediction(s) favor a lower published seed.")
    diagnostics.append(
        "Score steps require the greater of two points or three times the median "
        "of the other adjacent gaps. "
        "All available three-, four-, and five-team windows must favor the upper side "
        "in at least 75% of pairings, with a positive average advantage. "
        "These are display heuristics, not calibrated outcome guarantees."
    )

    return CheatSheetAnalysis(
        ordered_ids=ordered,
        review=review,
        placement_status=statuses,
        breaks=breaks,
        close_ranges=tuple(close_ranges),
        notes=tuple(notes),
        diagnostics=tuple(diagnostics),
        boundary_windows=tuple(boundary_windows),
        standouts=tuple(item for item in selected if item.standout),
        limited_history=tuple(key for key in ordered if by_id[key].limited_history),
        placement_checks=placement_checks,
        local_consensus_checks=_local_consensus_checks(ordered, by_id, pairs, placement_checks),
        tiers=legacy.tiers if legacy else (),
        borderline=legacy.borderline if legacy else {},
        boundaries=legacy.boundaries if legacy else (),
        warnings=legacy.warnings if legacy else (),
    )
