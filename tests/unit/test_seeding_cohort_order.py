from dataclasses import replace
from itertools import combinations

import pytest

from src.tournaments.seeding_cohort_order import cohort_expected_points_order
from src.tournaments.seeding_tiers import TierEntrant, build_cheat_sheet_analysis
from tests.unit.test_seeding_tiers import prediction


def field(ids):
    # Bottom PowerScore team has a modest, consistent edge, never a one-goal reversal.
    strengths = {key: (0.3 if key == ids[-1] else 0) for key in ids}
    return {(a, b): replace(prediction(strengths[a] - strengths[b]),
                           win_probability_a=0.45 + strengths[a] - strengths[b],
                           win_probability_b=0.45 - strengths[a] + strengths[b])
            for a, b in combinations(ids, 2)}


def test_whole_field_can_move_more_than_two_without_one_goal_trigger_or_history_lock():
    ids = tuple("abcdef")
    roster = [TierEntrant(key, key, 0.9 - index / 10, evidence_game_count=3 if key == "f" else 20, limited_history=key == "f")
              for index, key in enumerate(ids)]
    matrix = field(ids)
    old = build_cheat_sheet_analysis(roster, matrix)
    new = build_cheat_sheet_analysis(roster, matrix, ordering_method="cohort_expected_points_v1")
    assert old.suggested_order == ids
    assert new.suggested_order == ("f", "a", "b", "c", "d", "e")
    assert new.baseline_order == ids
    assert new.ordering_evidence["teams"]["f"]["limited_history"]
    assert new.ordering_evidence["teams"]["f"]["opponents_assessed"] == 5
    comparison = new.ordering_evidence["pairwise_comparison"]
    assert comparison["converged"]
    assert comparison["order"] == list(new.suggested_order)
    assert comparison["agrees_with_expected_points"]


def test_missing_evidence_fails_and_ties_preserve_baseline():
    ids = tuple("abc")
    with pytest.raises(ValueError, match="missing matchup"):
        cohort_expected_points_order(ids, {})
    pairs = {pair: prediction(0) for pair in combinations(ids, 2)}
    assert cohort_expected_points_order(ids, pairs)[0].order == ids
    assert cohort_expected_points_order(ids, dict(reversed(list(pairs.items()))))[0].order == ids


def test_manual_order_and_holds_do_not_erase_reconstructable_recommendation():
    ids = tuple("abcdef")
    roster = [TierEntrant(key, key, 0.9 - index / 10) for index, key in enumerate(ids)]
    analysis = build_cheat_sheet_analysis(roster, field(ids), ordering_method="cohort_expected_points_v1",
                                          manual_order=ids[:-1], manual_holds=("f",))
    assert analysis.ordered_ids == ids[:-1]
    assert analysis.suggested_order[0] == "f"
    assert analysis.baseline_order == ids


@pytest.mark.parametrize("count", [12, 32, 48, 66, 100])
def test_reordered_elite_four_feed_complete_practical_tier_search(count):
    from src.tournaments.seeding_format_library import load_format_library
    from src.tournaments.seeding_tier_guidance import build_tier_guidance
    from src.tournaments.seeding_tiers import TierPolicy

    ids = [str(index) for index in range(count)]
    elite = set(ids[-4:])
    roster = [TierEntrant(key, key, 0.9 - index / (count * 2), evidence_game_count=20)
              for index, key in enumerate(ids)]
    pairs = {}
    for a, b in combinations(ids, 2):
        margin = 3 * (int(a in elite) - int(b in elite))
        pairs[a, b] = replace(prediction(margin), win_probability_a=0.8 if margin > 0 else 0.1 if margin < 0 else 0.45,
                              win_probability_b=0.8 if margin < 0 else 0.1 if margin > 0 else 0.45)
    analysis = build_cheat_sheet_analysis(roster, pairs, ordering_method="cohort_expected_points_v1")
    assert set(analysis.suggested_order[:4]) == elite
    guidance = build_tier_guidance(analysis, roster, pairs, TierPolicy(), load_format_library())
    assert guidance["search_complete"]
    assert guidance["cuts"][0] == 4
    assert sum(item["size"] for item in guidance["divisions"]) == count
