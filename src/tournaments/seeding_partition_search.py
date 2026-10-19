"""Exact contiguous partitions without enumerating every division arrangement."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from src.tournaments.seeding_format_preferences import interval_preference
from src.tournaments.seeding_group_assessment import assess_group
from src.tournaments.seeding_group_evidence import grouping_costs


class SearchLimitReached(Exception):
    pass


@dataclass(frozen=True)
class Interval:
    start: int
    end: int
    pairs: int
    cost_units: int
    worst: float
    risk: float
    violations: int


@dataclass(frozen=True)
class PartitionSearch:
    structures: tuple[tuple[int, ...], ...]
    primary: tuple[int, ...] | None
    compromise: tuple[int, ...] | None
    complete: bool
    alternatives_complete: bool
    visited_states: int


def search_partitions(
    order, predictions, policy, metadata, sizes, recommendation_policy, *, maximum_states=1000000,
    supported_boundaries=(), format_burdens=None,
) -> PartitionSearch:
    n = len(order)
    if len(set(order)) != n:
        raise ValueError("The selected order contains duplicate entrants.")
    band_costs = grouping_costs(order, predictions, policy, metadata, recommendation_policy.group_split_penalty)
    pairs = assess_group(order, predictions, policy, metadata).pairings
    by_pair = {frozenset(pair.entrant_ids): pair for pair in pairs}
    ratios = [pair.matchup_cost.as_integer_ratio() for pair in pairs if pair.matchup_cost is not None]
    scale = max((denominator for _, denominator in ratios), default=1)
    units = {
        frozenset(pair.entrant_ids): (lambda r: r[0] * (scale // r[1]))(pair.matchup_cost.as_integer_ratio())
        for pair in pairs
        if pair.matchup_cost is not None
    }
    outgoing: list[list[Interval]] = [[] for _ in range(n + 1)]
    for start in range(n):
        costs, worst, risk, violations, complete = 0, 0.0, 0.0, 0, True
        for end in range(start + 1, min(n, start + max(sizes)) + 1):
            for other in range(start, end - 1):
                key = frozenset((order[other], order[end - 1]))
                pair = by_pair[key]
                if pair.matchup_cost is None:
                    complete = False
                    continue
                costs += units[key]
                worst = max(worst, pair.matchup_cost)
                risk = max(
                    risk,
                    pair.expected_absolute_goal_difference / policy.max_expected_margin,
                    pair.blowout_probability / policy.max_blowout_probability,
                )
                violations += pair.within_both_limits is False
            if end - start in sizes and complete:
                outgoing[start].append(
                    Interval(start, end, (end - start) * (end - start - 1) // 2, costs, worst, risk, violations)
                )

    visited = 0

    def tick():
        nonlocal visited
        visited += 1
        if visited > maximum_states:
            raise SearchLimitReached

    def close(left, right):
        return math.isclose(
            left,
            right,
            rel_tol=recommendation_policy.numerical_tie_relative_tolerance,
            abs_tol=recommendation_policy.numerical_tie_absolute_tolerance,
        )

    def minimax(edges, metric):
        values = [dict() for _ in range(n + 1)]
        values[0][0] = 0.0
        for start in range(n):
            for count, value in values[start].items():
                for edge in edges[start]:
                    key = count + 1
                    cost = max(value, getattr(edge, metric))
                    if key not in values[edge.end]:
                        tick()
                    values[edge.end][key] = min(values[edge.end].get(key, math.inf), cost)
        return values[n]

    def best_average(edges, counts, *, tolerant):
        """Pair totals are states, so a division-average cannot replace pair weighting.

        Costs use exact integer units of the input floats. A second suffix pass
        recovers the earliest boundaries inside the final numerical tie window.
        """
        states = [dict() for _ in range(n + 1)]
        states[0][(0, 0)] = 0
        maximum_count = max(counts)
        for start in range(n):
            for (count, pair_count), cost in states[start].items():
                if count >= maximum_count:
                    continue
                for edge in edges[start]:
                    key = count + 1, pair_count + edge.pairs
                    updated = cost + edge.cost_units
                    previous = states[edge.end].get(key)
                    if previous is None:
                        tick()
                    if previous is None or updated < previous:
                        states[edge.end][key] = updated
        finalists = [(count, pair_count, cost) for (count, pair_count), cost in states[n].items() if count in counts]
        if not finalists:
            return None

        def average(cost, count):
            return (cost / scale) / count

        minimum = min(average(cost, pair_count) for _, pair_count, cost in finalists)

        def acceptable(cost, count):
            return close(average(cost, count), minimum) if tolerant else average(cost, count) == minimum

        finalists = [(count, pair_count) for count, pair_count, cost in finalists if acceptable(cost, pair_count)]
        minimum_count = min(count for count, _ in finalists)
        finalists = [item for item in finalists if item[0] == minimum_count]

        @lru_cache(maxsize=None)
        def suffix(start, count, pair_count):
            tick()
            if count == 0:
                return 0 if start == n and pair_count == 0 else None
            if start == n or pair_count < count:
                return None
            costs = []
            for edge in edges[start]:
                if edge.pairs <= pair_count:
                    rest = suffix(edge.end, count - 1, pair_count - edge.pairs)
                    if rest is not None:
                        costs.append(edge.cost_units + rest)
            return min(costs, default=None)

        recovered = []
        for target_count, target_pairs in finalists:
            start, count, pairs_left, spent, structure = 0, target_count, target_pairs, 0, []
            while count:
                for edge in edges[start]:
                    rest = suffix(edge.end, count - 1, pairs_left - edge.pairs)
                    if rest is not None and acceptable(spent + edge.cost_units + rest, target_pairs):
                        structure.append(edge.end - start)
                        start, count, pairs_left, spent = (
                            edge.end,
                            count - 1,
                            pairs_left - edge.pairs,
                            spent + edge.cost_units,
                        )
                        break
                else:
                    raise AssertionError("An optimal partition could not be reconstructed.")
            recovered.append(tuple(structure))
        return min(recovered)

    passing = [[edge for edge in row if edge.violations == 0] for row in outgoing]
    alternative_edges = None
    structures = set()
    primary = compromise = None
    complete = False
    try:
        # This is a whole-arrangement preference, before division count or cost.
        # Reuse interval evidence and the shared state budget for the fallback pass.
        minimum = recommendation_policy.preferred_minimum_division_size
        if recommendation_policy.evidence_first:
            # Lexicographic additive preferences have optimal substructure. Keep
            # every tied edge so worst risk and pair-weighted averages stay exact.
            def preferred_edges(*, include_cohesion=True):
                def preference(edge):
                    value = interval_preference(edge.start, edge.end, recommendation_policy,
                                                supported_boundaries, format_burdens, band_costs)
                    return value if include_cohesion else value[:-1]
                forward, backward = [None] * (n + 1), [None] * (n + 1)
                forward[0] = backward[n] = (0,) * (5 if include_cohesion else 4)
                def add(left, right):
                    return tuple(a + b for a, b in zip(left, right, strict=True))
                for start in range(n):
                    if forward[start] is None:
                        continue
                    for edge in passing[start]:
                        tick()
                        value = add(forward[start], preference(edge))
                        if forward[edge.end] is None or value < forward[edge.end]:
                            forward[edge.end] = value
                for start in reversed(range(n)):
                    values = [add(preference(edge), backward[edge.end]) for edge in passing[start]
                              if backward[edge.end] is not None]
                    backward[start] = min(values, default=None)
                return [[edge for edge in row if forward[edge.start] is not None
                         and backward[edge.end] is not None
                         and add(add(forward[edge.start], preference(edge)), backward[edge.end]) == forward[n]]
                        for row in passing]

            # A useful safer alternative may trade an extra tier for lower risk.
            if recommendation_policy.group_split_penalty is not None:
                alternative_edges = preferred_edges(include_cohesion=False)
            passing = preferred_edges()
            best_worst = minimax(passing, "worst")
        else:
            preferred = [[edge for edge in row if minimum is None or edge.end - edge.start >= minimum]
                         for row in passing]
            best_worst = minimax(preferred, "worst")
            if best_worst:
                passing = preferred
            elif minimum is not None:
                best_worst = minimax(passing, "worst")
        if best_worst:
            first_count = min(best_worst)
            threshold = best_worst[first_count]
            restricted = [
                [edge for edge in row if edge.worst < threshold or close(edge.worst, threshold)] for row in passing
            ]
            primary = best_average(restricted, {first_count}, tolerant=True)
            structures.add(primary)
        if primary is None or (recommendation_policy.practical_risk_tolerance and minimum
                               and min(primary) < minimum):
            risks = minimax(outgoing, "risk")
            if risks:
                threshold = min(risks.values())

                def minimize_additive(edges, metric):
                    forward, backward = [math.inf] * (n + 1), [math.inf] * (n + 1)
                    forward[0] = backward[n] = 0
                    for start in range(n):
                        for edge in edges[start]:
                            tick()
                            forward[edge.end] = min(forward[edge.end], forward[start] + metric(edge))
                    for start in reversed(range(n)):
                        backward[start] = min(
                            (metric(edge) + backward[edge.end] for edge in edges[start]), default=math.inf)
                    return [[edge for edge in row
                             if forward[edge.start] + metric(edge) + backward[edge.end] == forward[n]]
                            for row in edges]

                restricted = [[edge for edge in row if edge.risk <= threshold] for row in outgoing]
                baseline = minimize_additive(restricted, lambda edge: edge.violations)
                structures.add(best_average(baseline, set(risks), tolerant=False))
                tolerance = recommendation_policy.practical_risk_tolerance
                if tolerance and minimum:
                    restricted = [[edge for edge in row if edge.risk <= threshold + tolerance]
                                  for row in outgoing]
                    restricted = minimize_additive(restricted, lambda edge: int(edge.end - edge.start < minimum))
                    threshold = min(minimax(restricted, "risk").values())
                    restricted = [[edge for edge in row if edge.risk <= threshold] for row in restricted]
                restricted = minimize_additive(restricted, lambda edge: edge.violations)
                compromise = best_average(restricted, set(risks), tolerant=False)
                structures.add(compromise)
        complete = True
        # Summarize alternatives with minimum-worst and minimum-average representatives
        # for each division count; this is not the complete set of useful partitions.
        if alternative_edges is None:
            alternative_edges = passing
        alternative_worst = minimax(alternative_edges, "worst")
        for count, threshold in sorted(alternative_worst.items()):
            restricted = [
                [edge for edge in row if edge.worst < threshold or close(edge.worst, threshold)]
                for row in alternative_edges
            ]
            structures.add(best_average(restricted, {count}, tolerant=True))
            structures.add(best_average(alternative_edges, {count}, tolerant=True))
    except SearchLimitReached:
        pass
    structures.discard(None)
    return PartitionSearch(tuple(sorted(structures)), primary, compromise, complete, False, visited)
