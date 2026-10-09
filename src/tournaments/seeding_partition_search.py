"""Exact contiguous partitions without enumerating every division arrangement."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from src.tournaments.seeding_group_assessment import assess_group


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
    order, predictions, policy, metadata, sizes, recommendation_policy, *, maximum_states=1000000
) -> PartitionSearch:
    n = len(order)
    if len(set(order)) != n:
        raise ValueError("The selected order contains duplicate entrants.")
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
    structures = set()
    primary = compromise = None
    complete = False
    try:
        best_worst = minimax(passing, "worst")
        if best_worst:
            first_count = min(best_worst)
            threshold = best_worst[first_count]
            restricted = [
                [edge for edge in row if edge.worst < threshold or close(edge.worst, threshold)] for row in passing
            ]
            primary = best_average(restricted, {first_count}, tolerant=True)
            structures.add(primary)
        else:
            risks = minimax(outgoing, "risk")
            if risks:
                threshold = min(risks.values())
                restricted = [[edge for edge in row if edge.risk <= threshold] for row in outgoing]
                forward, backward = [math.inf] * (n + 1), [math.inf] * (n + 1)
                forward[0] = backward[n] = 0
                for start in range(n):
                    for edge in restricted[start]:
                        forward[edge.end] = min(forward[edge.end], forward[start] + edge.violations)
                for start in reversed(range(n)):
                    backward[start] = min(
                        (edge.violations + backward[edge.end] for edge in restricted[start]), default=math.inf
                    )
                restricted = [
                    [edge for edge in row if forward[edge.start] + edge.violations + backward[edge.end] == forward[n]]
                    for row in restricted
                ]
                compromise = best_average(restricted, set(risks), tolerant=False)
                structures.add(compromise)
        complete = True
        # Summarize alternatives with minimum-worst and minimum-average representatives
        # for each division count; this is not the complete set of useful partitions.
        for count, threshold in sorted(best_worst.items()):
            restricted = [
                [edge for edge in row if edge.worst < threshold or close(edge.worst, threshold)] for row in passing
            ]
            structures.add(best_average(restricted, {count}, tolerant=True))
            structures.add(best_average(passing, {count}, tolerant=True))
    except SearchLimitReached:
        pass
    structures.discard(None)
    return PartitionSearch(tuple(sorted(structures)), primary, compromise, complete, False, visited)
