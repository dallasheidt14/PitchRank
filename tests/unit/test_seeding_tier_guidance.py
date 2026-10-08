"""Practical breaks follow cohort evidence while preserving the ranked list."""

from dataclasses import replace
from itertools import combinations

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_format_library import load_format_library, resolve_format_profile
from src.tournaments.seeding_flight_suggestions import generate_candidate_structures
from src.tournaments.seeding_tier_guidance import build_tier_guidance
from src.tournaments.seeding_tiers import TierEntrant, TierPolicy, build_cheat_sheet_analysis


def prediction(margin=0.2, absolute=0.8, blowout=0.02):
    return ComparePrediction("team_a", .6, .25, .15, {"teamA": 2, "teamB": 1},
                             margin, absolute, blowout, "high", .9)


def cohort(count, risk):
    entrants = [TierEntrant(str(i), f"Team {i + 1}", .9 - i * .025,
                           evidence_game_count=20) for i in range(count)]
    pairs = {(str(a), str(b)): risk(a, b) for a, b in combinations(range(count), 2)}
    analysis = build_cheat_sheet_analysis(entrants, pairs)
    return entrants, pairs, analysis


def test_four_elite_teams_get_a_four_team_top_tier():
    entrants, pairs, analysis = cohort(12, lambda a, b: prediction(3, 3.2, .4)
                                     if a < 4 <= b else prediction())
    result = build_tier_guidance(analysis, entrants, pairs, TierPolicy(), load_format_library())
    assert result["cuts"] == [4]
    assert [item["size"] for item in result["divisions"]] == [4, 8]
    assert result["divisions"][0]["entrant_ids"] == ["0", "1", "2", "3"]
    assert analysis.ordered_ids == tuple(str(i) for i in range(12))


def test_eighteen_team_example_has_distinct_strength_divisions_and_pools():
    library = load_format_library()
    generated = generate_candidate_structures(18, library, resolve_format_profile(library))
    assert generated.search_complete
    assert (8, 4, 6) in generated.structures
    entrants, pairs, analysis = cohort(18, lambda a, b: prediction(3, 3.2, .4)
                                     if (a < 8 <= b or a < 12 <= b) else prediction())
    result = build_tier_guidance(analysis, entrants, pairs, TierPolicy(), library,
                                 tier_names=["Gold", "Silver", "Bronze"])
    assert result["cuts"] == [8, 12]
    assert [item["pool_sizes"] for item in result["divisions"]] == [[4, 4], [4], [3, 3]]
    assert [item["label"] for item in result["divisions"]] == ["Gold", "Silver", "Bronze"]


def test_gradual_strength_decline_gets_practical_breaks_without_claiming_natural_gap():
    entrants, pairs, analysis = cohort(12, lambda a, b: prediction((b-a)*.35, .6+(b-a)*.35, .05+(b-a)*.025))
    result = build_tier_guidance(analysis, entrants, pairs, TierPolicy(), load_format_library())
    assert result["cuts"]
    assert not analysis.breaks
    assert not any(item["natural_break_after"] for item in result["divisions"])


def test_compromise_is_review_required_and_reports_worst_remaining_pair():
    entrants, pairs, analysis = cohort(8, lambda a, b: prediction(3, 3, .4))
    result = build_tier_guidance(analysis, entrants, pairs, TierPolicy(), load_format_library())
    assert result["status"] == "review_required_compromise"
    assert result["review_required"]
    assert result["cuts"]
    assert any("Worst remaining mismatch" in text for text in result["warnings"])
    assert len(analysis.breaks) == 7  # No customer-display cap.


def test_compromise_minimizes_worst_normalized_risk_before_other_preferences():
    entrants, pairs, analysis = cohort(8, lambda a, b: prediction(1, 5 if a < 4 <= b else 2.2, .1))
    result = build_tier_guidance(analysis, entrants, pairs, TierPolicy(), load_format_library())
    assert result["status"] == "review_required_compromise"
    assert [item["size"] for item in result["divisions"]] == [4, 4]
    assert max(pair["expected_absolute_goal_difference"] for pair in result["risky_pairings"]) == 2.2


def test_unknown_history_keeps_a_passing_split_provisional():
    entrants, pairs, analysis = cohort(4, lambda a, b: prediction())
    entrants[0] = replace(entrants[0], limited_history=None)
    result = build_tier_guidance(analysis, entrants, pairs, TierPolicy(), load_format_library())
    assert result["divisions"]
    assert result["review_required"]
    assert any("unknown playing history" in text for text in result["warnings"])


def test_cached_guidance_is_isolated_and_invalidates_on_semantic_changes(monkeypatch):
    from src.tournaments import seeding_tier_guidance as guidance

    guidance._cached_guidance.cache_clear()
    original = guidance.suggest_automatic_flights
    calls = []
    def count(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(guidance, "suggest_automatic_flights", count)
    entrants, pairs, analysis = cohort(8, lambda a, b: prediction())
    library = load_format_library()
    first = build_tier_guidance(analysis, entrants, pairs, TierPolicy(), library)
    first["divisions"].clear()
    assert build_tier_guidance(analysis, entrants, pairs, TierPolicy(), library)["divisions"]
    assert len(calls) == 1
    build_tier_guidance(analysis, entrants, pairs, TierPolicy(max_expected_margin=1.8), library)
    build_tier_guidance(analysis, entrants, pairs, TierPolicy(), library, tier_names=["Gold"])
    held = build_cheat_sheet_analysis(entrants, pairs, manual_order=[str(i) for i in range(4)],
                                      manual_holds=[str(i) for i in range(4, 8)])
    build_tier_guidance(held, entrants, pairs, TierPolicy(), library)
    assert len(calls) == 4


def test_alternative_keeps_the_higher_worst_matchup_tradeoff_on_the_director_sheet():
    from src.tournaments.seeding_content import build_director_cohort
    from src.tournaments.seeding_sheet import CohortSheet, SheetTeam

    entrants, pairs, analysis = cohort(8, lambda a, b: prediction(
        .2, 1.5 if (a < 4 and b < 4) or (a >= 4 and b >= 4) else .5, .02))
    pairs[("0", "4")] = prediction(.2, 1.7, .02)
    pairs[("3", "7")] = prediction(.2, 1.8, .02)
    pairs[("0", "7")] = prediction(.2, 2.4, .35)
    guidance = build_tier_guidance(analysis, entrants, pairs, TierPolicy(), load_format_library())
    assert guidance["alternative_sizes"] == [5, 3]
    assert guidance["alternative"]["worst_matchup_cost_delta"] > 0
    assert guidance["alternative"]["pair_weighted_average_matchup_cost_delta"] < 0
    teams = tuple(SheetTeam(item.team_name, "", item.power_score, entrant_id=item.entrant_id) for item in entrants)
    sheet = CohortSheet("u14", "Male", teams, (), tier_analysis=replace(analysis, tier_guidance=guidance))
    note = next(text for text in build_director_cohort(sheet).notes if text.startswith("Alternative split"))
    assert "higher worst matchup cost" in note
    assert "lower average matchup cost" in note


def test_missing_predictions_cannot_win_and_unplaced_entries_stay_visible():
    entrants, pairs, analysis = cohort(4, lambda a, b: prediction())
    entrants.append(TierEntrant("unmatched", "Unknown entrant", None, review_reason="Not found"))
    pairs.pop(("0", "1"))
    result = build_tier_guidance(analysis, entrants, pairs, TierPolicy(), load_format_library())
    assert result["divisions"] == []
    assert result["accepted_count"] == 5
    assert result["assessed_count"] == 4
    assert result["review_required"]


def test_manual_order_and_holds_recompute_guidance_from_effective_membership():
    entrants, pairs, analysis = cohort(8, lambda a, b: prediction(3, 3.2, .4)
                                     if a < 4 <= b else prediction())
    manual = build_cheat_sheet_analysis(entrants, pairs, manual_order=[str(i) for i in range(4, 8)],
                                       manual_holds=["0", "1", "2", "3"])
    result = build_tier_guidance(manual, entrants, pairs, TierPolicy(), load_format_library())
    assert result["divisions"][0]["entrant_ids"] == ["4", "5", "6", "7"]
    assert result["cuts"] == []
    assert result["review_required"]
    assert manual.baseline_order == analysis.baseline_order


def test_incomplete_search_never_promotes_evaluated_candidate():
    entrants, pairs, analysis = cohort(18, lambda a, b: prediction())
    library = load_format_library()
    library = replace(library, profiles=(replace(resolve_format_profile(library), max_candidate_structures=1),))
    result = build_tier_guidance(analysis, entrants, pairs, TierPolicy(), library)
    assert not result["search_complete"]
    assert result["cuts"] == []
    assert result["review_required"]
