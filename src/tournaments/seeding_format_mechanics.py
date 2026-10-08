"""Count games through anonymous schedules and distinct qualification slots.

Active slots always partition the entrants: ranking consumes slots and replaces
them with distinct ranks; a playoff consumes two slots and returns winner/loser.
This prevents duplicate advancement without enumerating every possible score.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from typing import Any, Mapping


@dataclass(frozen=True)
class FormatGameCounts:
    minimum_games: int
    maximum_games: int
    total_matches: int
    maximum_pair_meetings: int
    preliminary_games_by_slot: tuple[int, ...]
    minimum_games_by_slot: tuple[int, ...]
    maximum_games_by_slot: tuple[int, ...]
    has_playoffs: bool


def _positive_int(value: Any, label: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer of at least {minimum}.")
    return value


def calculate_format_games(team_count: int, structure: Mapping) -> FormatGameCounts:
    _positive_int(team_count, "Team count", minimum=2)
    return _cached_format_games(team_count, json.dumps(structure, sort_keys=True, allow_nan=False))


@lru_cache(maxsize=256)
def _cached_format_games(team_count: int, serialized_structure: str) -> FormatGameCounts:
    structure = json.loads(serialized_structure)
    entrants = tuple(f"T{i + 1}" for i in range(team_count))
    counts = Counter({key: 0 for key in entrants})
    meetings: Counter = Counter()
    preliminary = structure.get("preliminary_matches", ())
    for pair in preliminary:
        if len(pair) != 2 or pair[0] == pair[1] or any(key not in counts for key in pair):
            raise ValueError("A preliminary match must name two distinct entrant slots.")
        counts.update(pair)
        meetings[tuple(sorted(pair))] += 1

    # Each bound is specific to an original entrant, even with uneven pool games.
    active = {key: {key: (counts[key], counts[key])} for key in entrants}
    ancestry: dict[str, set[str]] = {key: set() for key in entrants}
    used_names = set(entrants)
    events = []
    played_rounds: dict[str, set[str]] = {key: set() for key in entrants}
    match_count = len(preliminary)
    has_playoffs = False
    for stage in structure.get("stages", ()):
        kind = stage.get("kind")
        inputs = stage.get("inputs", ())
        outputs = stage.get("outputs", ())
        if not inputs or len(set(inputs)) != len(inputs) or any(key not in active for key in inputs):
            raise ValueError("Advancement must consume distinct, still-active slots.")
        if (
            len(outputs) != len(inputs)
            or len(set(outputs)) != len(outputs)
            or any(not isinstance(key, str) or not key or key in used_names for key in outputs)
        ):
            raise ValueError("Advancement outputs must be new, distinct slots preserving every entrant.")
        if kind not in {"rank", "match"}:
            raise ValueError(f"Unknown playing stage: {kind!r}.")
        if kind == "match" and len(inputs) != 2:
            raise ValueError("A playoff match needs exactly two inputs and winner/loser outputs.")
        merged: dict[str, tuple[int, int]] = {}
        for key in inputs:
            for entrant, (low, high) in active[key].items():
                previous = merged.get(entrant, (low, high))
                merged[entrant] = min(low, previous[0]), max(high, previous[1])
        ancestors = set().union(*(ancestry[key] for key in inputs))
        rounds = set().union(*(played_rounds[key] for key in inputs))
        if kind == "match":
            round_id = stage.get("round")
            if not isinstance(round_id, str) or not round_id or round_id in rounds:
                raise ValueError("A participant cannot play twice in the same playoff round.")
            events.append(
                (
                    set(active[inputs[0]]),
                    set(active[inputs[1]]),
                    set(ancestry[inputs[0]]),
                    set(ancestry[inputs[1]]),
                    tuple(outputs),
                )
            )
            merged = {key: (low + 1, high + 1) for key, (low, high) in merged.items()}
            rounds.add(round_id)
            match_count += 1
            has_playoffs = has_playoffs or stage.get("playoff", True)
        for key in inputs:
            del active[key]
        for key in outputs:
            active[key] = dict(merged)
            ancestry[key] = ancestors | ({key} if kind == "match" else set())
            played_rounds[key] = set(rounds)
        used_names.update(outputs)

    if len(active) != team_count:
        raise ValueError("The format lost or duplicated participant slots.")
    minimums, maximums = [], []
    for entrant in entrants:
        paths = [bounds[entrant] for bounds in active.values() if entrant in bounds]
        minimums.append(min(low for low, _ in paths))
        maximums.append(max(high for _, high in paths))
    if min(minimums) == 0:
        raise ValueError("An enabled format must give every entrant at least one match.")

    max_meetings = max(meetings.values(), default=0)
    for first, second in combinations(entrants, 2):
        possible = []
        for left, right, left_ancestors, right_ancestors, outputs in events:
            if not ((first in left and second in right) or (second in left and first in right)):
                continue
            repetitions = 1
            for previous_outputs, previous_count in possible:
                winner, loser = previous_outputs
                # Both participants must be able to reach opposite sides again.
                if (winner in left_ancestors and loser in right_ancestors) or (
                    loser in left_ancestors and winner in right_ancestors
                ):
                    repetitions = max(repetitions, previous_count + 1)
            possible.append((outputs, repetitions))
        max_meetings = max(
            max_meetings, meetings[tuple(sorted((first, second)))] + max((value for _, value in possible), default=0)
        )
    return FormatGameCounts(
        min(minimums),
        max(maximums),
        match_count,
        max_meetings,
        tuple(counts[key] for key in entrants),
        tuple(minimums),
        tuple(maximums),
        has_playoffs,
    )


def pool_slots(pool_sizes: list[int]) -> list[list[str]]:
    result, start = [], 1
    for size in pool_sizes:
        _positive_int(size, "Pool size", minimum=2)
        result.append([f"T{i}" for i in range(start, start + size)])
        start += size
    return result


def round_robin_matches(slots: list[str], meetings: int = 1) -> list[list[str]]:
    _positive_int(meetings, "Meetings")
    return [list(pair) for _ in range(meetings) for pair in combinations(slots, 2)]


def partial_matches(slots: list[str], games: int) -> list[list[str]]:
    """An exact degree schedule; odd appearances give the first slot one extra game."""
    n = len(slots)
    _positive_int(games, "Games")
    if games >= n:
        raise ValueError("A partial round robin cannot exceed the available opponents.")
    target = [games] * n
    if n * games % 2:
        target[0] += 1
    remaining = list(target)
    matches = []
    # Havel-Hakimi realizes the exact degree sequence without repeated opponents.
    while any(remaining):
        order = sorted(range(n), key=lambda i: (-remaining[i], i))
        first, *others = order
        degree = remaining[first]
        opponents = [i for i in others if remaining[i] > 0][:degree]
        if len(opponents) != degree:
            raise ValueError("The requested partial schedule is not realizable.")
        remaining[first] = 0
        for second in opponents:
            remaining[second] -= 1
            matches.append([slots[first], slots[second]])
    return matches


def rank_stage(stages: list, prefix: str, members: list[str]) -> list[str]:
    outputs = [f"{prefix}:{i + 1}" for i in range(len(members))]
    stages.append(
        {
            "kind": "rank",
            "inputs": members,
            "outputs": outputs,
            "ranking_rule": "Order by preliminary points per game, then goal difference per game, "
            "goals scored per game, and the original anonymous slot number.",
        }
    )
    return outputs


def knockout_stages(stages: list, qualifiers: list[str], prefix: str, *, placement: bool = False) -> None:
    """Standard seeded byes; optional classification games for every losing branch."""
    if len(qualifiers) < 2:
        raise ValueError("A knockout needs at least two qualifiers.")
    current = list(qualifiers)
    round_number = 0
    while len(current) > 1:
        round_number += 1
        capacity = 1 << (len(current) - 1).bit_length()
        byes = capacity - len(current)
        following = current[:byes]
        playing = current[byes:]
        losers = []
        for index in range(len(playing) // 2):
            match_id = f"{prefix}:r{round_number}:m{index + 1}"
            winner, loser = f"{match_id}:W", f"{match_id}:L"
            stages.append(
                {
                    "kind": "match",
                    "round": f"{prefix}:r{round_number}",
                    "inputs": [playing[index], playing[-index - 1]],
                    "outputs": [winner, loser],
                }
            )
            following.append(winner)
            losers.append(loser)
        if placement and len(losers) > 1:
            knockout_stages(stages, losers, f"{prefix}:place{round_number}", placement=True)
        current = following
