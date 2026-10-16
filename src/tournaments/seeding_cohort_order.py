"""Deterministic field-wide ordering from frozen matchup probabilities.

This is a tournament-specific recommendation, not a published team rating.
Uncertainty measures sensitivity to the comparison field, not a confidence
interval inferred from treating correlated predictions as independent games.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_suggested_order import SuggestedOrderResult, TeamMovement

COHORT_ORDER_VERSION = "cohort_expected_points_v1"


def cohort_expected_points_order(
    baseline: Sequence[str], predictions: Mapping[tuple[str, str], ComparePrediction],
    *, limited_history: Sequence[str] = (),
) -> tuple[SuggestedOrderResult, dict]:
    """Use each opponent once; ties preserve the independently saved baseline."""
    ids = tuple(baseline)
    if len(ids) != len(set(ids)):
        raise ValueError("Cohort order requires unique entrant IDs")
    base = {value: index for index, value in enumerate(ids)}
    points: dict[tuple[str, str], float] = {}
    for a in ids:
        for b in ids:
            if a == b:
                continue
            forward = predictions.get((a, b))
            reverse = predictions.get((b, a))
            if forward is None and reverse is None:
                raise ValueError(f"Incomplete cohort evidence: missing matchup {a} / {b}")
            pair = forward or reverse
            win = pair.win_probability_a if forward else pair.win_probability_b
            value = win + pair.draw_probability / 2
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Invalid expected points in cohort evidence")
            points[a, b] = value
    totals = {a: math.fsum(points[a, b] for b in ids if b != a) for a in ids}
    def rank(values):
        return tuple(sorted(ids, key=lambda a: (-round(values[a], 12), base[a])))
    values = {a: totals[a] / max(1, len(ids) - 1) for a in ids}
    ordered = rank(values)
    positions = {a: [index + 1] for index, a in enumerate(ordered)}
    # A field sensitivity check, not resampling synthetic matchup outcomes.
    if len(ids) > 2:
        for omitted in ids:
            variant = rank({a: (totals[a] - points.get((a, omitted), 0))
                            / (len(ids) - 1 if a == omitted else len(ids) - 2) for a in ids})
            for index, a in enumerate(variant):
                positions[a].append(index + 1)
    details = {}
    for a in ids:
        low, high = min(positions[a]), max(positions[a])
        uncertainty = []
        if a in limited_history:
            uncertainty.append("Limited playing history; placement needs review")
        if high > low:
            uncertainty.append(f"Field sensitivity: seeds {low}–{high}")
        favored = sum(points[a, b] > 0.5 + 1e-12 for b in ids if b != a)
        details[a] = {
            "expected_points": values[a], "opponents_assessed": max(0, len(ids) - 1),
            "favored_against": favored, "field_sensitivity_seeds": [low, high],
            "limited_history": a in limited_history,
            "reason": f"Projected edge against {favored} of {max(0, len(ids)-1)} assessed opponents.",
            "cautions": uncertainty,
        }
    movements = tuple(TeamMovement(
        a, base[a] + 1, index + 1, base[a] - index, "cohort_expected_points", False, (), (), (),
    ) for index, a in enumerate(ordered) if base[a] != index)
    return SuggestedOrderResult(
        ordered, movements, (), (), (), sum(abs(m.movement_delta) for m in movements),
    ), {"version": COHORT_ORDER_VERSION, "status": "complete", "teams": details,
        "pairwise_comparison": _regularized_pairwise(ids, points, ordered),
        "explanation": "Order compares each team with the entire assessed field. PowerScore breaks exact ties."}


def _regularized_pairwise(ids, points, expected_order):
    """Fit a zero-centered Bradley-Terry diagnostic to the same frozen probabilities.

    On a complete equally weighted field its order agrees with expected points;
    this comparison checks the formulation, not independent predictive evidence.
    """
    strength = {a: 0.0 for a in ids}
    ridge = 1.0
    step = 1 / max(1, len(ids) / 2 + ridge)
    converged = False
    iteration = 0
    for iteration in range(500):
        gradient = {a: ridge * strength[a] + math.fsum(
            1 / (1 + math.exp(strength[b] - strength[a])) - points[a, b] for b in ids if b != a
        ) for a in ids}
        if max((abs(value) for value in gradient.values()), default=0) < 1e-9:
            converged = True
            break
        strength = {a: strength[a] - step * gradient[a] for a in ids}
    baseline = {a: index for index, a in enumerate(ids)}
    order = sorted(ids, key=lambda a: (-round(strength[a], 9), baseline[a]))
    return {"version": "regularized_pairwise_v1", "ridge": ridge, "prior": "equal_zero",
            "converged": converged, "iterations": iteration + 1, "order": order,
            "agrees_with_expected_points": order == list(expected_order), "strength": strength}
