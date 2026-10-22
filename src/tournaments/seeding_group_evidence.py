"""Strength-band evidence, separate from the risk of an individual matchup.

Within-band loss is sum(signed_margin ** 2) / team_count. For a consistent
strength model this is exactly its within-band sum of squared deviations.
The per-team policy divides once more by team count, measuring variance rather
than total spread. Replicating a distribution then cannot increase its incentive
to split. Legacy snapshots retain the total-spread objective.
One versioned cost per band prevents trivial fragmentation into tiny groups.
Neither PowerScore gaps nor a mandatory mismatch at the boundary enter it.
"""

from __future__ import annotations

import math
from dataclasses import asdict, replace
from fractions import Fraction
from itertools import combinations

from src.tournaments.seeding_group_assessment import assess_group
from src.tournaments.seeding_tiers import (
    NO_MEANINGFUL_SEPARATION,
    SUPPORTED_SEPARATION,
    UNCERTAIN_SEPARATION,
    BoundaryAssessment,
    StrengthBreak,
)


def grouping_costs(order, predictions, policy, metadata, split_penalty, *, normalization="total"):
    """Exact additive interval costs; unavailable intervals never become cheap."""
    if split_penalty is None:
        return None
    pairings = assess_group(order, predictions, policy, metadata).pairings
    margins = {frozenset(p.entrant_ids): p.expected_signed_margin_toward_first for p in pairings}
    squared = {key: Fraction(value) ** 2 for key, value in margins.items() if value is not None}
    costs = {}
    for start in range(len(order)):
        total = Fraction(0)
        complete = True
        for end in range(start + 1, len(order) + 1):
            for other in range(start, end - 1):
                value = squared.get(frozenset((order[other], order[end - 1])))
                if value is None:
                    complete = False
                else:
                    total += value
            denominator = (end - start) ** (2 if normalization == "per_team" else 1)
            costs[start, end] = (total / denominator + Fraction(split_penalty)
                                 if complete else math.inf)
    return costs


def group_boundaries(order, divisions, predictions, policy, metadata):
    """Assess every cut against whole neighboring bands, not just two teams.

    At a selected cut, use both complete neighboring divisions. Inside a division,
    assess splitting that division. Keep these alternatives as operator evidence;
    only the selected partition supplies director separators.
    """
    pairings = assess_group(order, predictions, policy, metadata).pairings
    pairs = {frozenset(p.entrant_ids): p for p in pairings}
    intervals = [(d['start_seed'] - 1, d['end_seed']) for d in divisions] or [(0, len(order))]
    selected = {end for _, end in intervals[:-1]}
    results = []
    for cut in range(1, len(order)):
        if cut in selected:
            start = next(start for start, end in intervals if end == cut)
            end = next(end for start, end in intervals if start == cut)
        else:
            interval = next(((a, b) for a, b in intervals if a < cut < b), None)
            if interval is None:
                continue
            start, end = interval
        upper, lower = order[start:cut], order[cut:end]
        cross = [(a, b, pairs[frozenset((a, b))]) for a in upper for b in lower]
        within = [pairs[frozenset(pair)] for group in (upper, lower) for pair in combinations(group, 2)]
        available = [p for _, _, p in cross if p.expected_signed_margin_toward_first is not None]
        complete = len(available) == len(cross) and all(p.matchup_cost is not None for p in within)
        signed = [p.expected_signed_margin_toward_first * (1 if p.first.entrant_id == a else -1)
                  for a, _, p in cross if p.expected_signed_margin_toward_first is not None]
        established = sum(p.history_quality == 'established' for p in available)
        evidence = (complete and established >= policy.boundary_min_established_pairings
                    and len(cross) >= policy.boundary_min_pairings
                    and (len(cross) - established) / len(cross) <= policy.boundary_max_limited_pair_fraction)
        mean = math.fsum(signed) / len(signed) if signed else 0.0
        within_margins = [abs(p.expected_signed_margin_toward_first) for p in within
                          if p.expected_signed_margin_toward_first is not None]
        spread = math.fsum(within_margins) / len(within_margins) if within_margins else 0.0
        favored = sum(value > 1e-8 for value in signed) / len(signed) if signed else 0.0
        differentiated = (mean >= policy.boundary_min_average_signed_margin
                          and favored >= policy.boundary_min_favored_fraction and mean > spread)
        if not evidence:
            classification = UNCERTAIN_SEPARATION
            reason = 'More established game history or complete predictions are needed to confirm these strength bands.'
        elif differentiated:
            classification = SUPPORTED_SEPARATION
            reason = ('Results separate the groups more than teams within each group; '
                      'teams immediately across the line may still play a close game.')
        else:
            classification = NO_MEANINGFUL_SEPARATION
            reason = 'The whole-group comparison does not establish distinct strength bands at this position.'
        adjacent = pairs[frozenset((order[cut - 1], order[cut]))]
        adj_margin = adjacent.expected_signed_margin_toward_first
        if adj_margin is not None and adjacent.first.entrant_id != order[cut - 1]:
            adj_margin = -adj_margin
        known = [metadata[key] for key in (*upper, *lower) if metadata[key].limited_history is False]
        worst = max(available, key=lambda p: p.matchup_cost, default=None)
        def average(field):
            return math.fsum(getattr(p, field) for p in available) / len(available) if available else 0.0
        def maximum(field):
            return max((getattr(p, field) for p in available), default=0.0)
        upper_score, lower_score = metadata[order[cut - 1]].power_score or 0.0, metadata[order[cut]].power_score or 0.0
        assessment = BoundaryAssessment(
            after_seed=cut, upper_ids=tuple(upper), lower_ids=tuple(lower),
            pairing_count=len(cross), favored_fraction=favored, average_expected_margin=mean,
            average_expected_absolute_goal_difference=average('expected_absolute_goal_difference'),
            maximum_expected_absolute_goal_difference=maximum('expected_absolute_goal_difference'),
            average_blowout_probability=average('blowout_probability'),
            maximum_blowout_probability=maximum('blowout_probability'),
            over_limit_fraction=(sum(p.within_both_limits is False for p in available) / len(available)
                                 if available else 0.0),
            worst_pair=worst.entrant_ids if worst else None,
            established_team_count=len(known), limited_history_team_count=end - start - len(known),
            established_pairing_count=established, limited_history_pairing_count=len(cross) - established,
            low_confidence_pairing_count=sum(bool(p.low_outcome_confidence) for p in available),
            evidence_quality=('insufficient' if not evidence else
                              'established' if len(known) == end - start else 'mixed'),
            adjacent_pair_expected_margin=adj_margin or 0.0,
            adjacent_pair_expected_absolute_goal_difference=adjacent.expected_absolute_goal_difference or 0.0,
            adjacent_pair_blowout_probability=adjacent.blowout_probability or 0.0,
            adjacent_pair_over_limit=adjacent.within_both_limits is False,
            adjacent_pair_limited_history=adjacent.provisional_due_to_history,
            adjacent_pair_low_confidence=bool(adjacent.low_outcome_confidence),
            upper_power_score=upper_score, lower_power_score=lower_score, power_score_gap=upper_score - lower_score,
            tested_window_sizes=(end - start,), usable_window_sizes=(end - start,) if evidence else (),
            classification=classification, reason=reason,
        )
        results.append({**asdict(assessment), 'selected': cut in selected,
                        'within_group_average_margin': spread, 'prediction_complete': complete,
                        'adjacent_teams_competitive': adjacent.within_both_limits is True})
    return results


def apply_group_guidance(analysis, guidance):
    """Project effective group breaks without rewriting frozen baseline evidence.

    The legacy boundary snapshot belongs to the suggested order and is checked
    on reopen. Effective membership and preferences may change independently;
    their complete group evidence lives in tier_guidance instead.
    """
    if guidance.get('boundary_method') != 'whole_group_v1':
        return replace(analysis, tier_guidance=guidance)
    fields = BoundaryAssessment.__dataclass_fields__
    assessments = tuple(BoundaryAssessment(**{k: v for k, v in item.items() if k in fields})
                        for item in guidance['group_boundaries'])
    cuts = set(guidance['cuts'])
    breaks = tuple(StrengthBreak(a.after_seed, a.power_score_gap, a.average_expected_margin, ())
                   for a in assessments if a.after_seed in cuts and a.classification == SUPPORTED_SEPARATION)
    return replace(analysis, tier_guidance=guidance, breaks=breaks,
                   notes=tuple(f'Competitive Break: results support different strength bands after seed {b.after_seed}.'
                               for b in breaks),
                   diagnostics=tuple(note for note in analysis.diagnostics
                                     if not note.startswith('Every suggested-order boundary')) + (
                       'Whole-group comparisons assess separation against within-group variation. '
                       'Close boundary opponents are allowed; individual mismatch limits are checked separately.',))
