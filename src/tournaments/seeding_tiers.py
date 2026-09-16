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
from dataclasses import dataclass
from itertools import combinations

from src.tournaments.compare_predictor_bridge import ComparePrediction


@dataclass(frozen=True)
class TierEntrant:
    entrant_id: str
    team_name: str
    power_score: float | None = None
    review_reason: str | None = None


@dataclass(frozen=True)
class TierPolicy:
    max_expected_margin: float = 2.0
    max_blowout_probability: float = 0.30

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_expected_margin) or self.max_expected_margin <= 0:
            raise ValueError("Maximum expected margin must be finite and greater than zero")
        if not math.isfinite(self.max_blowout_probability) or not 0 < self.max_blowout_probability <= 1:
            raise ValueError("Maximum four-goal blowout probability must be greater than zero and at most one")


@dataclass(frozen=True)
class TierGroup:
    number: int
    entrant_ids: tuple[str, ...]
    max_expected_margin: float
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
class _Pair:
    margin: float
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
                not math.isfinite(candidate.blowout_4plus_probability)
                or not 0 <= candidate.blowout_4plus_probability <= 1
            ):
                raise ValueError(f"Invalid four-goal blowout probability for {first} vs {second}")
        if forward is not None and reverse is not None:
            if not math.isclose(forward.expected_margin, -reverse.expected_margin, abs_tol=1e-8) or not math.isclose(
                forward.blowout_4plus_probability, reverse.blowout_4plus_probability, abs_tol=1e-8
            ):
                raise ValueError(f"Inconsistent forward/reverse Compare predictions for {first} vs {second}")
        pairs[(first, second)] = _Pair(
            margin=prediction.expected_margin if forward is not None else -prediction.expected_margin,
            blowout=prediction.blowout_4plus_probability,
            low_confidence=getattr(prediction, "confidence", None) == "low",
        )
    return pairs


def _margin(pairs: Mapping[tuple[str, str], _Pair], first: str, second: str) -> float:
    pair = pairs[_pair_key(first, second)]
    return pair.margin if first < second else -pair.margin


def _risk(pair: _Pair, policy: TierPolicy) -> float:
    return max(abs(pair.margin) / policy.max_expected_margin, pair.blowout / policy.max_blowout_probability)


def _automatic_groups(
    ordered: Sequence[str],
    pairs: Mapping[tuple[str, str], _Pair],
    policy: TierPolicy,
    strength: Mapping[str, float],
) -> list[tuple[str, ...]]:
    """Minimum complete-link bands, with boundaries at natural strength breaks.

    Interval risk and safety are built in O(n²), followed by an O(n²) dynamic
    program. Among safe partitions with the same minimum tier count, maximize
    the total adjacent all-field strength gap at the boundaries, then minimize
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
    Groups are numbered by matchup strength; PowerScore orders rows *within*
    each tier for a familiar cheat sheet. ``ordered_ids`` is that displayed order.

    "Clear separation" requires the upper tier to be favored in at least 75%
    of cross-tier pairs, at least 50% to exceed a within-tier limit, and the
    average signed margin to reach half the margin limit. Other boundaries
    explicitly describe overlap; a partition alone is not evidence of a gap.
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
    strength = {
        key: math.fsum(_margin(pairs, key, other) for other in eligible if key != other) / max(1, len(eligible) - 1)
        for key in eligible
    }
    ordered = sorted(eligible, key=lambda key: (-strength[key], *_display_key(by_id[key])))
    groups = (
        _automatic_groups(ordered, pairs, policy, strength)
        if manual_groups is None
        else _manual_groups(manual_groups, eligible)
    )
    # Mixed manual assignments may overlap in strength, but their numbered
    # tiers must still have a consistent strongest-to-weakest field ordering.
    groups.sort(key=lambda group: (-math.fsum(strength[key] for key in group) / len(group), tuple(sorted(group))))
    groups = [tuple(sorted(group, key=lambda key: _display_key(by_id[key]))) for group in groups]
    tiers = []
    warnings = []
    for number, group in enumerate(groups, 1):
        group_pairs = sorted(_pair_key(first, second) for first, second in combinations(group, 2))
        worst = max(group_pairs, key=lambda key: _risk(pairs[key], policy)) if group_pairs else None
        max_margin = max((abs(pairs[key].margin) for key in group_pairs), default=0.0)
        max_blowout = max((pairs[key].blowout for key in group_pairs), default=0.0)
        tiers.append(TierGroup(number, group, max_margin, max_blowout, worst))
        if worst is not None and _risk(pairs[worst], policy) > 1:
            warnings.append(
                f"Tier {number} exceeds the matchup limits: up to {max_margin:.2f} expected goals and "
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
