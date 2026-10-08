"""Format arithmetic, automatic preferences, and exact partition search."""

import copy
import json
import random
import re
from dataclasses import replace
from itertools import combinations

import pytest

from scripts.build_matchbalance_format_catalog import SOURCE, build_catalog
from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_flight_suggestions import generate_candidate_structures, suggest_automatic_flights
from src.tournaments.seeding_format_library import load_format_library, parse_format_library, resolve_format_profile
from src.tournaments.seeding_format_mechanics import calculate_format_games
from src.tournaments.seeding_format_preferences import apply_preferences, effective_preferences
from src.tournaments.seeding_group_assessment import GroupTeam
from src.tournaments.seeding_partition_search import search_partitions
from src.tournaments.seeding_tiers import TierPolicy


@pytest.fixture(scope="module")
def library():
    return load_format_library()


@pytest.mark.parametrize(
    "slug,minimum,maximum,matches,repeats",
    [
        ("3-double", 4, 4, 6, 2),
        ("4-rr", 3, 3, 6, 1),
        ("5-partial", 3, 4, 8, 1),
        ("6-cross-final", 3, 4, 10, 2),
        ("8-full-cross", 4, 4, 16, 1),
        ("8-partial-cross", 3, 3, 12, 1),
        ("8-gold-silver", 4, 5, 18, 2),
        ("8-all-placement", 5, 5, 20, 2),
        ("8-knockout-placement", 3, 3, 12, 1),
        ("32-knockout", 1, 5, 31, 1),
        ("32-consolation", 2, 5, 46, 1),
        ("3-points", 3, 4, 5, 2),
        ("11-mixed", 2, 5, 18, 2),
        ("24-quarterfinals", 3, 6, 43, 2),
    ],
)
def test_calculated_guarantees(library, slug, minimum, maximum, matches, repeats):
    template = library.templates_by_id[f"mb-expanded-{slug}-v2"]
    result = calculate_format_games(template.team_count, template.playing_structure)
    assert (result.minimum_games, result.maximum_games, result.total_matches, result.maximum_pair_meetings) == (
        minimum,
        maximum,
        matches,
        repeats,
    )


def test_catalog_reproduces_checked_in_definitions_and_covers_source(library):
    expected = build_catalog()
    assert expected == json.loads(library.source_path.read_text(encoding="utf-8"))
    assert library.schema_version == 2
    assert resolve_format_profile(library).profile_id == "matchbalance-expanded-v2"
    entries, count = set(), None
    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"### (\d+\+?) teams", line)
        if heading:
            count = heading[1]
        elif line.startswith("## Master Summary Table"):
            break
        elif count and line.startswith("- **"):
            variant = re.match(r"- \*\*([A-Z])\.", line)
            entries.add(count + (variant[1] if variant else "A"))
    dispositions = {item["source_entry"] for item in library.source_coverage}
    assert entries == dispositions
    enabled = set(resolve_format_profile(library).template_ids)
    for item in library.source_coverage:
        assert item["reason"]
        assert set(item["template_ids"]) <= enabled
    assert {18, 20, 24, 32, 48, 66} <= {library.templates_by_id[key].team_count for key in enabled}


def test_duplicate_advancement_and_invented_guarantee_are_rejected(library):
    template = library.templates_by_id["mb-expanded-4-final-v2"]
    structure = copy.deepcopy(template.playing_structure)
    structure["stages"][-1]["inputs"] = ["pool1:1", "pool1:1"]
    with pytest.raises(ValueError, match="distinct"):
        calculate_format_games(4, structure)
    raw = build_catalog()
    next(t for t in raw["templates"] if t["template_id"] == template.template_id)["total_matches"] = 6
    with pytest.raises(ValueError, match="disagree"):
        parse_format_library(raw)


def test_preferences_are_optional_and_cohort_overrides_can_clear_a_limit(library):
    pack = {
        "format_preferences": {"minimum_games": 3},
        "cohort_format_preferences": {"u14|Male": {"minimum_games": None, "playoffs": "excluded"}},
    }
    assert effective_preferences(pack, "u12|Male") == {"minimum_games": 3}
    assert effective_preferences(pack, "u14|Male") == {"minimum_games": None, "playoffs": "excluded"}
    automatic = resolve_format_profile(library)
    result = generate_candidate_structures(3, library, automatic)
    assert result.size_template_options[0].preferred_template_id == "mb-expanded-3-points-v2"
    limited = apply_preferences(automatic, {"minimum_games": 3, "maximum_games": 3, "repeat_opponents": "prohibited"})
    assert generate_candidate_structures(3, library, limited).unsupported
    assert not generate_candidate_structures(4, library, limited).unsupported
    conflicting = apply_preferences(automatic, {"minimum_games": 5, "maximum_games": 3})
    result = generate_candidate_structures(8, library, conflicting)
    assert result.unsupported
    assert any("minimum required" in t.reason for t in result.excluded_templates)


@pytest.mark.parametrize("slug,rank,pools", [("24-final16", 3, 6), ("48-final16", 2, 12), ("48-final32", 3, 12)])
def test_wildcard_eligibility_is_limited_to_the_documented_pool_rank(library, slug, rank, pools):
    template = library.templates_by_id[f"mb-expanded-{slug}-v2"]
    wildcard = next(stage for stage in template.playing_structure["stages"] if stage["outputs"][0] == "wildcard:1")
    assert wildcard["inputs"] == [f"pool{i + 1}:{rank}" for i in range(pools)]


@pytest.mark.parametrize("slug,championship", [("4-final", "standings_only"), ("4-rr", "final")])
def test_playoff_declaration_must_match_the_validated_structure(slug, championship):
    raw = build_catalog()
    template = next(t for t in raw["templates"] if t["template_id"] == f"mb-expanded-{slug}-v2")
    template["championship_type"] = championship
    with pytest.raises(ValueError, match="Playoff declaration"):
        parse_format_library(raw)


def test_enabled_v2_template_cannot_omit_its_playing_structure():
    raw = build_catalog()
    template = next(t for t in raw["templates"] if t["template_id"] == "mb-expanded-4-rr-v2")
    template.pop("playing_structure")
    template["minimum_guaranteed_games_per_team"] = 10
    template["maximum_possible_games_per_team"] = 10
    with pytest.raises(ValueError, match="require an explicit playing structure"):
        parse_format_library(raw)


def test_game_count_cache_uses_structure_contents_and_team_count(library):
    from src.tournaments.seeding_format_mechanics import _cached_format_games

    structure = copy.deepcopy(library.templates_by_id["mb-expanded-4-rr-v2"].playing_structure)
    _cached_format_games.cache_clear()
    before = calculate_format_games(4, structure)
    assert calculate_format_games(4, copy.deepcopy(structure)) == before
    assert _cached_format_games.cache_info().hits == 1
    structure["preliminary_matches"].append(["T1", "T2"])
    after = calculate_format_games(4, structure)
    assert after.total_matches == before.total_matches + 1
    assert after.maximum_pair_meetings == 2
    with pytest.raises(ValueError, match="every entrant"):
        calculate_format_games(5, structure)


def matrix(n, seed=0, *, unsafe=False, equal=False):
    rng = random.Random(seed)
    ids = [f"team-{i}" for i in range(n)]
    teams = {
        key: GroupTeam(key, key, seed=i + 1, power_score=0.9 - i / 200, limited_history=False, evidence_game_count=20)
        for i, key in enumerate(ids)
    }
    predictions = {}
    for pair in combinations(ids, 2):
        margin = 3 + rng.random() if unsafe else (1.0 if equal else 0.5 + rng.random() * 1.4)
        predictions[pair] = ComparePrediction(
            predicted_winner="team_a",
            win_probability_a=0.6,
            win_probability_b=0.25,
            draw_probability=0.15,
            expected_score={"teamA": 2, "teamB": 1},
            expected_margin=0.4,
            expected_absolute_goal_difference=margin,
            blowout_4plus_probability=0.1,
            confidence="high",
            confidence_score=0.8,
        )
    return ids, teams, predictions


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("unsafe", [False, True])
def test_exact_search_matches_exhaustive_oracle(library, seed, unsafe):
    ids, teams, predictions = matrix(14, seed, unsafe=unsafe)
    profile = resolve_format_profile(library)
    profile = replace(
        profile,
        template_ids=tuple(key for key in profile.template_ids if library.templates_by_id[key].team_count in {3, 4, 5}),
    )
    exhaustive = suggest_automatic_flights(ids, predictions, TierPolicy(), teams, library, profile)
    optimized = search_partitions(ids, predictions, TierPolicy(), teams, (3, 4, 5), exhaustive.recommendation_policy)
    assert optimized.complete
    if unsafe:

        def risk(plan):
            return max(
                max(pair.expected_absolute_goal_difference / 2, pair.blowout_probability / 0.3)
                for flight in plan.flights
                for pair in flight.group.pairings
            )

        expected = min(
            exhaustive.assessment.plans,
            key=lambda p: (
                risk(p),
                p.violating_pairing_count,
                p.pair_weighted_average_matchup_cost,
                len(p.flights),
                p.flight_sizes,
            ),
        )
        assert optimized.compromise == expected.flight_sizes
    else:
        expected = next(plan for plan in exhaustive.assessment.plans if plan.plan_id == exhaustive.primary_plan_id)
        assert optimized.primary == expected.flight_sizes


def test_compromise_counts_only_violating_pairs_in_mixed_evidence(library):
    ids, teams, predictions = matrix(8, equal=True)
    for left, right in ((0, 1), (6, 7), (4, 5)):
        pair = ids[left], ids[right]
        predictions[pair] = replace(predictions[pair], expected_absolute_goal_difference=3)
    profile = resolve_format_profile(library)
    profile = replace(
        profile,
        template_ids=tuple(key for key in profile.template_ids if library.templates_by_id[key].team_count in {3, 4, 5}),
    )
    exhaustive = suggest_automatic_flights(ids, predictions, TierPolicy(), teams, library, profile)
    exact = suggest_automatic_flights(
        ids, predictions, TierPolicy(), teams, library, replace(profile, max_candidate_structures=1)
    )
    assert exact.generation.optimal_compromise_structure == (5, 3)
    for result in (exhaustive, exact):
        best = min(
            result.assessment.plans,
            key=lambda p: (
                p.violating_pairing_count,
                p.pair_weighted_average_matchup_cost,
                len(p.flights),
                p.flight_sizes,
            ),
        )
        assert best.flight_sizes == (5, 3)
        assert best.violating_pairing_count == 2
    assert next(p for p in exhaustive.assessment.plans if p.flight_sizes == (4, 4)).violating_pairing_count == 3


@pytest.mark.parametrize("n", [32, 48, 66, 100])
def test_large_cohort_uses_exact_search(library, n):
    ids, teams, predictions = matrix(n, equal=True)
    result = suggest_automatic_flights(ids, predictions, TierPolicy(), teams, library, resolve_format_profile(library))
    assert result.generation.total_distinct_structure_count > 10000
    assert result.generation.search_method == "exact_dynamic_programming"
    assert result.generation.search_complete
    assert result.primary_plan_id
    chosen = next(p for p in result.assessment.plans if p.plan_id == result.primary_plan_id)
    assert sum(chosen.flight_sizes) == n
    assert chosen.all_pair_projected_fit_passed
    assert result.generation.generated_structure_count < 10000


def test_state_safeguard_and_missing_predictions_do_not_produce_a_primary(library):
    ids, teams, predictions = matrix(32, equal=True)
    profile = replace(resolve_format_profile(library), maximum_search_states=1)
    result = suggest_automatic_flights(ids, predictions, TierPolicy(), teams, library, profile)
    assert not result.generation.search_complete
    assert result.primary_plan_id is None
    predictions.clear()
    result = suggest_automatic_flights(ids, predictions, TierPolicy(), teams, library, resolve_format_profile(library))
    assert result.primary_plan_id is None
    assert result.generation.optimal_compromise_structure is None


@pytest.mark.parametrize("delta", [0.0, 1e-13, 1e-10, 1e-8])
def test_exact_search_preserves_numerical_ties_and_missing_cross_tier_pairs(library, delta):
    ids, teams, predictions = matrix(13, equal=True)
    profile = resolve_format_profile(library)
    profile = replace(
        profile,
        template_ids=tuple(key for key in profile.template_ids if library.templates_by_id[key].team_count in {3, 4, 5}),
    )
    for i, pair in enumerate(predictions):
        predictions[pair] = replace(predictions[pair], expected_absolute_goal_difference=1 + (i % 3) * delta)
    predictions.pop((ids[0], ids[-1]))  # Unneeded across all supported tier boundaries.
    exhaustive = suggest_automatic_flights(ids, predictions, TierPolicy(), teams, library, profile)
    exact = suggest_automatic_flights(
        ids, predictions, TierPolicy(), teams, library, replace(profile, max_candidate_structures=1)
    )
    expected = next(p for p in exhaustive.assessment.plans if p.plan_id == exhaustive.primary_plan_id)
    chosen = next(p for p in exact.assessment.plans if p.plan_id == exact.primary_plan_id)
    assert chosen.flight_sizes == expected.flight_sizes
    assert chosen.pair_weighted_average_matchup_cost == expected.pair_weighted_average_matchup_cost
    assert exact.generation.search_complete
    assert not exact.assessment.enumeration.search_complete  # Displayed alternatives are shortened.


def test_format_choice_does_not_weight_repeated_fixtures_or_change_strength_boundaries(library):
    ids, teams, predictions = matrix(8, equal=True)
    profile = resolve_format_profile(library)
    first = suggest_automatic_flights(ids, predictions, TierPolicy(), teams, library, profile)
    second = suggest_automatic_flights(
        ids,
        predictions,
        TierPolicy(),
        teams,
        library,
        apply_preferences(profile, {"playoffs": "required", "minimum_games": 4}),
    )
    plans = [
        next(p for p in result.assessment.plans if p.plan_id == result.primary_plan_id) for result in (first, second)
    ]
    assert plans[0] == plans[1]
    assert plans[0].required_unique_pairing_count == 28
    assert first.format_options != second.format_options
