"""Require a useful reason for each extra strength division.

Neighboring divisions may have close boundary opponents. A cut is justified by
whole-group separation, by evidence that the combined division cannot pass, or
by a material schedule burden or the absence of a compatible combined format.
Cosmetic format preferences never justify a cut. This is a placement policy, not a claim
of validated prediction accuracy.
"""

import math
from functools import lru_cache

from src.tournaments.seeding_group_assessment import assess_group


def boundary_justifications(order, predictions, policy, metadata, supported_sizes, format_burdens=None):
    """Return cached O(1) whole-neighbor comparisons using pair prefix sums."""
    n = len(order)
    positions = {entrant: i for i, entrant in enumerate(order)}
    fields = ('signed', 'absolute', 'favored', 'missing', 'violations')
    matrices = {field: [[0.0] * (n + 1) for _ in range(n + 1)] for field in fields}
    for pair in assess_group(order, predictions, policy, metadata).pairings:
        i, j = sorted(positions[entrant] for entrant in pair.entrant_ids)
        margin = pair.expected_signed_margin_toward_first
        if margin is not None and pair.first.entrant_id != order[i]:
            margin = -margin
        values = (margin or 0.0, abs(margin or 0.0), int(margin is not None and margin > 1e-8),
                  int(margin is None or pair.matchup_cost is None), int(pair.within_both_limits is False))
        for field, value in zip(fields, values, strict=True):
            matrices[field][i + 1][j + 1] = value
    for matrix in matrices.values():
        for i in range(1, n + 1):
            for j in range(1, n + 1):
                matrix[i][j] += matrix[i - 1][j] + matrix[i][j - 1] - matrix[i - 1][j - 1]

    def total(field, a, b, c, d):
        matrix = matrices[field]
        return matrix[b][d] - matrix[a][d] - matrix[b][c] + matrix[a][c]

    @lru_cache(maxsize=None)
    def evaluate(start, cut, end):
        count = (cut - start) * (end - cut)
        missing = round(total('missing', start, end, start, end))
        violations = round(total('violations', start, end, start, end))
        mean = total('signed', start, cut, cut, end) / count
        favored = total('favored', start, cut, cut, end) / count
        within_count = (cut - start) * (cut - start - 1) // 2 + (end - cut) * (end - cut - 1) // 2
        spread = (total('absolute', start, cut, start, cut)
                  + total('absolute', cut, end, cut, end)) / max(1, within_count)
        separated = (not missing and mean >= policy.boundary_min_average_signed_margin
                     and favored >= policy.boundary_min_favored_fraction and mean > spread)
        compatible = end - start in supported_sizes
        burdens = format_burdens or {}
        combined = burdens.get(end - start, (0, 0, 0))
        upper = burdens.get(cut - start, (0, 0, 0))
        lower = burdens.get(end - cut, (0, 0, 0))
        schedule_burden = compatible and any(combined[i] > 0 and upper[i] == lower[i] == 0 for i in (0, 1))
        reason = ('whole_group_separation' if separated else 'combined_matchup_limits' if violations
                  else 'incomplete_combined_evidence' if missing else 'combined_format_unavailable'
                  if not compatible else 'combined_schedule_burden' if schedule_burden else 'no_material_benefit')
        return {
            'justified': reason != 'no_material_benefit', 'reason': reason,
            'combined_size': end - start, 'combined_format_available': compatible,
            'combined_missing_pairings': missing, 'combined_violating_pairings': violations,
            'average_directional_advantage': mean, 'within_group_average_advantage': spread,
        }

    return evaluate


def partition_is_justified(sizes, evaluate):
    start = 0
    for upper, lower in zip(sizes, sizes[1:]):
        if not evaluate(start, start + upper, start + upper + lower)['justified']:
            return False
        start += upper
    return True


def format_only_break_count(sizes, evaluate):
    start, count = 0, 0
    for upper, lower in zip(sizes, sizes[1:]):
        count += evaluate(start, start + upper, start + upper + lower)['reason'] == 'combined_format_unavailable'
        start += upper
    return count


def select_justified_partition(outgoing, evaluate, preference, close, scale, tick):
    """Exact DAG search retaining the previous division as part of each state.

    Restrict to the best additive preference and division count, then minimize
    worst matchup cost and pair-weighted average. Recover deterministic ties
    with suffix costs, including paths inside the final numerical tie window.
    All phases share the caller's computational safeguard.
    """
    n = len(outgoing) - 1
    source = (0, 0)
    nodes = {source: None}
    successors = {source: []}
    ending = {0: [source]}
    for end in range(1, n + 1):
        for start in range(end):
            for interval in outgoing[start]:
                if interval.end != end:
                    continue
                node = (start, end)
                parents = []
                for parent in ending.get(start, ()):
                    tick()
                    if parent == source or evaluate(parent[0], start, end)['justified']:
                        parents.append(parent)
                if parents:
                    nodes[node] = interval
                    successors[node] = []
                    ending.setdefault(end, []).append(node)
                    for parent in parents:
                        successors[parent].append(node)
    finals = set(ending.get(n, ()))
    if not finals:
        return None
    interval_weights = {node: (*preference(interval), 1) for node, interval in nodes.items() if interval is not None}
    zero = (0,) * (len(next(iter(interval_weights.values()))) + 1)

    def weight(parent, target):
        format_only = (parent != source and
                       evaluate(parent[0], target[0], target[1])['reason'] == 'combined_format_unavailable')
        value = interval_weights[target]
        return (*value[:4], int(format_only), *value[4:])

    def add(left, right):
        return tuple(a + b for a, b in zip(left, right, strict=True))

    forward = {source: zero}
    for node in nodes:
        for target in successors[node]:
            tick()
            cost = add(forward[node], weight(node, target))
            forward[target] = min(forward.get(target, cost), cost)
    optimum = min(forward[node] for node in finals)
    backward = {node: zero for node in finals}
    for node in reversed(nodes):
        if node not in finals:
            values = [add(weight(node, target), backward[target]) for target in successors[node] if target in backward]
            if values:
                backward[node] = min(values)
    edges = {node: [target for target in targets if target in backward
                   and add(add(forward[node], weight(node, target)), backward[target]) == optimum]
             for node, targets in successors.items()}
    worst = {source: 0.0}
    for node in nodes:
        if node not in worst:
            continue
        for target in edges[node]:
            tick()
            value = max(worst[node], nodes[target].worst)
            worst[target] = min(worst.get(target, math.inf), value)
    threshold = min(worst[node] for node in finals if node in worst)
    edges = {node: sorted(target for target in targets
                         if nodes[target].worst < threshold or close(nodes[target].worst, threshold))
             for node, targets in edges.items()}
    costs = {node: {} for node in nodes}
    costs[source][0] = 0
    for node in nodes:
        for pair_count, cost in costs[node].items():
            for target in edges[node]:
                tick()
                interval = nodes[target]
                count, value = pair_count + interval.pairs, cost + interval.cost_units
                costs[target][count] = min(costs[target].get(count, value), value)
    minimum = min((cost / scale) / count for node in finals for count, cost in costs[node].items())

    @lru_cache(maxsize=None)
    def suffix(node, count):
        tick()
        if node in finals:
            return 0 if count == 0 else None
        values = []
        for target in edges[node]:
            interval = nodes[target]
            if interval.pairs <= count:
                rest = suffix(target, count - interval.pairs)
                if rest is not None:
                    values.append(interval.cost_units + rest)
        return min(values, default=None)

    recovered = []
    targets = {count for node in finals for count, cost in costs[node].items()
               if close((cost / scale) / count, minimum)}
    for target_count in targets:
        node, left, spent, sizes = source, target_count, 0, []
        while node not in finals:
            for target in edges[node]:
                interval = nodes[target]
                rest = suffix(target, left - interval.pairs) if left >= interval.pairs else None
                if rest is not None and close(((spent + interval.cost_units + rest) / scale) / target_count, minimum):
                    sizes.append(interval.end - interval.start)
                    node, left, spent = target, left - interval.pairs, spent + interval.cost_units
                    break
            else:
                raise AssertionError('A justified partition could not be reconstructed.')
        recovered.append(tuple(sizes))
    return min(recovered)
