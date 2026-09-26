"""The MatchBalance order stays bounded, deterministic, and PowerScore-anchored."""

from itertools import permutations

from src.tournaments.seeding_suggested_order import resolve_suggested_order

BASELINE = ("a", "b", "c", "d", "e", "f")


def test_supported_adjacent_move_records_cause_and_displacement():
    result = resolve_suggested_order(BASELINE, (("c", "b"),))

    assert result.order == ("a", "c", "b", "d", "e", "f")
    by_id = {item.entrant_id: item for item in result.movements}
    assert by_id["c"].relationships_causing_move == (("c", "b"),)
    assert by_id["c"].cause == "supported_relationship"
    assert by_id["b"].cause == "displaced_by_supported_move"
    assert by_id["b"].displaced_only


def test_two_seed_move_requires_support_over_every_crossed_seed():
    complete = resolve_suggested_order(BASELINE, (("c", "a"), ("c", "b")))
    incomplete = resolve_suggested_order(BASELINE, (("c", "a"),))

    assert complete.order[:3] == ("c", "a", "b")
    assert incomplete.order == BASELINE
    assert incomplete.unsatisfied_relationships == (("c", "a"),)


def test_independent_moves_are_applied_together():
    result = resolve_suggested_order(BASELINE, (("c", "b"), ("e", "d")))

    assert result.order == ("a", "c", "b", "e", "d", "f")
    assert result.satisfied_relationships == (("c", "b"), ("e", "d"))


def test_cycles_and_conflicts_keep_the_maximum_safe_subset_deterministically():
    relationships = (("b", "a"), ("c", "b"), ("a", "c"))
    expected = resolve_suggested_order(("a", "b", "c"), relationships)

    assert len(expected.satisfied_relationships) == 2
    assert len(expected.unsatisfied_relationships) == 1
    assert expected.conflicts
    for proposal_order in permutations(relationships):
        assert resolve_suggested_order(("a", "b", "c"), proposal_order) == expected


def test_movement_cap_and_immovable_teams_preserve_safer_baseline_order():
    capped = resolve_suggested_order(BASELINE, (("d", "a"), ("d", "b"), ("d", "c")))
    limited = resolve_suggested_order(BASELINE, (("c", "b"),), immovable_ids=("c",))

    assert capped.order == ("a", "d", "b", "c", "e", "f")
    assert capped.unsatisfied_relationships == (("d", "a"),)
    assert limited.order == BASELINE
    assert "limited-history" in limited.conflicts[0].reason


def test_powerscore_baseline_input_is_never_mutated():
    baseline = list(BASELINE)

    resolve_suggested_order(baseline, (("c", "b"),))

    assert baseline == list(BASELINE)


def test_optimizer_matches_exhaustive_lexicographic_objective():
    baseline = ("a", "b", "c", "d", "e")
    relationship_sets = (
        (("c", "b"), ("e", "d")),
        (("b", "a"), ("c", "b"), ("a", "c")),
        (("c", "a"), ("c", "b"), ("d", "b"), ("d", "c")),
    )
    original = {entrant_id: index for index, entrant_id in enumerate(baseline)}
    for relationships in relationship_sets:
        supported = set(relationships)
        valid = []
        for order in permutations(baseline):
            positions = {entrant_id: index for index, entrant_id in enumerate(order)}
            if any(abs(positions[item] - original[item]) > 2 for item in baseline):
                continue
            if any(
                original[passing] > original[crossed]
                and positions[passing] < positions[crossed]
                and (passing, crossed) not in supported
                for passing in baseline
                for crossed in baseline
            ):
                continue
            satisfied = sum(positions[winner] < positions[loser] for winner, loser in relationships)
            movement = sum(abs(positions[item] - original[item]) for item in baseline)
            permutation_key = tuple(original[item] for item in order)
            valid.append(((-satisfied, movement, permutation_key), order))

        expected = min(valid)[1]
        assert resolve_suggested_order(baseline, relationships).order == expected
