"""Conservative, PowerScore-anchored MatchBalance seed ordering.

This module does not rank teams or alter PowerScores.  It chooses among orders
that stay close to a frozen PowerScore baseline, and it permits an inversion
only when local-consensus evidence explicitly supports the passing team over
the crossed team.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

Relationship = tuple[str, str]


@dataclass(frozen=True)
class OrderingConflict:
    winner_id: str
    loser_id: str
    reason: str


@dataclass(frozen=True)
class TeamMovement:
    entrant_id: str
    original_seed: int
    suggested_seed: int
    movement_delta: int
    cause: str
    displaced_only: bool
    relationships_causing_move: tuple[Relationship, ...]
    satisfied_relationships: tuple[Relationship, ...]
    unsatisfied_relationships: tuple[Relationship, ...]


@dataclass(frozen=True)
class SuggestedOrderResult:
    order: tuple[str, ...]
    movements: tuple[TeamMovement, ...]
    satisfied_relationships: tuple[Relationship, ...]
    unsatisfied_relationships: tuple[Relationship, ...]
    conflicts: tuple[OrderingConflict, ...]
    total_movement: int


def _validate_inputs(
    baseline_order: Sequence[str],
    relationships: Iterable[Relationship],
    immovable_ids: Iterable[str],
    max_movement: int,
) -> tuple[tuple[str, ...], tuple[Relationship, ...], frozenset[str]]:
    baseline = tuple(baseline_order)
    if len(set(baseline)) != len(baseline) or any(not value for value in baseline):
        raise ValueError("The PowerScore baseline must contain unique, non-empty entrant IDs")
    if isinstance(max_movement, bool) or not isinstance(max_movement, int) or max_movement < 0:
        raise ValueError("Maximum automatic movement must be a non-negative integer")
    known = set(baseline)
    normalized = tuple(sorted(set(tuple(item) for item in relationships)))
    for relationship in normalized:
        if len(relationship) != 2 or relationship[0] == relationship[1]:
            raise ValueError("Supported relationships must name two different entrants")
        if not set(relationship).issubset(known):
            raise ValueError("Supported relationships must reference the PowerScore baseline")
    immovable = frozenset(immovable_ids)
    if not immovable.issubset(known):
        raise ValueError("Immovable entrants must reference the PowerScore baseline")
    return baseline, normalized, immovable


def resolve_suggested_order(
    baseline_order: Sequence[str],
    supported_relationships: Iterable[Relationship],
    *,
    immovable_ids: Iterable[str] = (),
    max_movement: int = 2,
) -> SuggestedOrderResult:
    """Return the optimal safe order under the configured movement constraints.

    A relationship is ``(winner, loser)``.  The exact objective is: maximize
    satisfied relationships, minimize total displacement, then prefer the
    original PowerScore-relative sequence.  Proposal iteration order is never
    part of the result.
    """
    baseline, relationships, immovable = _validate_inputs(
        baseline_order,
        supported_relationships,
        immovable_ids,
        max_movement,
    )
    count = len(baseline)
    index = {entrant_id: position for position, entrant_id in enumerate(baseline)}
    supported = frozenset(relationships)

    # mask -> (satisfied relationship count, total movement, baseline-index order)
    states: dict[int, tuple[int, int, tuple[int, ...]]] = {0: (0, 0, ())}
    for position in range(count):
        next_states: dict[int, tuple[int, int, tuple[int, ...]]] = {}
        lower = max(0, position - max_movement)
        upper = min(count - 1, position + max_movement)
        for mask, (score, movement, permutation) in states.items():
            for candidate in range(lower, upper + 1):
                bit = 1 << candidate
                if mask & bit:
                    continue
                entrant_id = baseline[candidate]
                if entrant_id in immovable and candidate != position:
                    continue
                fixed_here = baseline[position] in immovable
                if fixed_here and candidate != position:
                    continue

                # Every baseline inversion needs explicit support for the team
                # moving upward over each still-unplaced earlier seed.
                if any(
                    not mask & (1 << crossed) and (entrant_id, baseline[crossed]) not in supported
                    for crossed in range(candidate)
                ):
                    continue

                new_mask = mask | bit
                overdue_before = position + 1 - max_movement
                if any(not new_mask & (1 << overdue) for overdue in range(max(0, overdue_before))):
                    continue

                added = sum(
                    1 for placed in range(count) if mask & (1 << placed) and (baseline[placed], entrant_id) in supported
                )
                candidate_state = (
                    score + added,
                    movement + abs(candidate - position),
                    (*permutation, candidate),
                )
                current = next_states.get(new_mask)
                if current is None or (-candidate_state[0], candidate_state[1], candidate_state[2]) < (
                    -current[0],
                    current[1],
                    current[2],
                ):
                    next_states[new_mask] = candidate_state
        states = next_states

    complete = states.get((1 << count) - 1)
    if complete is None:
        # The baseline is always valid for sound inputs.  This fail-safe keeps a
        # future policy/configuration defect from manufacturing an order.
        order = baseline
        total_movement = 0
    else:
        order = tuple(baseline[value] for value in complete[2])
        total_movement = complete[1]

    final_position = {entrant_id: position for position, entrant_id in enumerate(order)}
    satisfied = tuple(
        relationship
        for relationship in relationships
        if final_position[relationship[0]] < final_position[relationship[1]]
    )
    unsatisfied = tuple(relationship for relationship in relationships if relationship not in satisfied)
    conflicts = []
    for winner, loser in unsatisfied:
        if winner in immovable or loser in immovable:
            reason = "A limited-history team is fixed to its original PowerScore seed."
        elif abs(index[winner] - index[loser]) > max_movement:
            reason = "The relationship exceeds the configured automatic movement cap."
        else:
            reason = "It conflicts with a safer combination of supported relationships and movement constraints."
        conflicts.append(OrderingConflict(winner, loser, reason))

    movements = []
    for entrant_id in baseline:
        original = index[entrant_id]
        suggested = final_position[entrant_id]
        causing = tuple(
            relationship
            for relationship in satisfied
            if (
                relationship[0] == entrant_id
                and index[relationship[0]] > index[relationship[1]]
                and final_position[relationship[0]] < final_position[relationship[1]]
            )
            or (
                relationship[1] == entrant_id
                and index[relationship[0]] > index[relationship[1]]
                and final_position[relationship[0]] < final_position[relationship[1]]
            )
        )
        related_satisfied = tuple(item for item in satisfied if entrant_id in item)
        related_unsatisfied = tuple(item for item in unsatisfied if entrant_id in item)
        if suggested < original:
            cause = "supported_relationship"
            displaced_only = False
        elif suggested > original:
            cause = "displaced_by_supported_move"
            displaced_only = not any(item[0] == entrant_id for item in causing)
        else:
            cause = "unchanged"
            displaced_only = False
        movements.append(
            TeamMovement(
                entrant_id=entrant_id,
                original_seed=original + 1,
                suggested_seed=suggested + 1,
                movement_delta=original - suggested,
                cause=cause,
                displaced_only=displaced_only,
                relationships_causing_move=causing if suggested != original else (),
                satisfied_relationships=related_satisfied,
                unsatisfied_relationships=related_unsatisfied,
            )
        )

    return SuggestedOrderResult(
        order=order,
        movements=tuple(movements),
        satisfied_relationships=satisfied,
        unsatisfied_relationships=unsatisfied,
        conflicts=tuple(conflicts),
        total_movement=total_movement,
    )
