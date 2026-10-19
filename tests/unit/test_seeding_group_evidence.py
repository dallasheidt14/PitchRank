"""Whole groups can differ even when the two boundary opponents overlap."""

from dataclasses import replace
from itertools import combinations

import pytest

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_format_library import load_format_library, resolve_format_profile
from src.tournaments.seeding_flight_suggestions import suggest_automatic_flights
from src.tournaments.seeding_group_assessment import GroupTeam
from src.tournaments.seeding_group_evidence import apply_group_guidance, grouping_costs
from src.tournaments.seeding_partition_search import search_partitions
from src.tournaments.seeding_tier_guidance import build_tier_guidance
from src.tournaments.seeding_tiers import TierEntrant, TierPolicy, build_cheat_sheet_analysis


def example(strengths):
    entrants = [TierEntrant(str(i), f'Team {i}', .9 - i * .01, evidence_game_count=20)
                for i in range(len(strengths))]
    predictions = {}
    for i, j in combinations(range(len(strengths)), 2):
        margin = strengths[i] - strengths[j]
        # All games in this fixture pass the competitive limits, so safety does
        # not force any cut. Strength bands must come from the directional data.
        predictions[str(i), str(j)] = ComparePrediction(
            'team_a', .6, .2, .2, {'teamA': 2, 'teamB': 1}, margin,
            max(abs(margin), 1.0), .1, 'high', .9,
        )
    return entrants, predictions


def run(entrants, predictions, *, exact=False, profile_id=None, manual_order=None, holds=()):
    analysis = build_cheat_sheet_analysis(entrants, predictions, manual_order=manual_order, manual_holds=holds)
    library = load_format_library()
    if exact:
        library = replace(library, profiles=tuple(replace(p, max_candidate_structures=1) for p in library.profiles))
    guidance = build_tier_guidance(analysis, entrants, predictions, TierPolicy(), library, profile_id=profile_id)
    return apply_group_guidance(analysis, guidance)


@pytest.mark.parametrize('exact', [False, True])
def test_overlapping_boundary_teams_do_not_veto_cohesive_strength_bands(exact):
    entrants, predictions = example([1, .9, .8, .1, 0, -.7, -.8, -.9])
    old = run(entrants, predictions, profile_id='matchbalance-expanded-v5')
    new = run(entrants, predictions, exact=exact)
    assert old.tier_guidance['cuts'] == []
    assert new.tier_guidance['cuts'] == [4]
    assert [d['size'] for d in new.tier_guidance['divisions']] == [4, 4]
    assert [b.after_seed for b in new.breaks] == [4]
    assert new.tier_guidance['risky_pairings'] == []
    boundary = next(b for b in new.tier_guidance['group_boundaries'] if b['after_seed'] == 4)
    assert boundary['adjacent_teams_competitive']
    assert boundary['average_expected_margin'] == pytest.approx(1.3)
    assert boundary['average_expected_margin'] > boundary['within_group_average_margin']
    assert boundary['established_pairing_count'] == 16
    assert len(new.boundary_assessments) == 7
    assert new.ordered_ids == old.ordered_ids
    assert 'whole-group' in new.diagnostics[-1].lower()
    assert 'teams near the line may still be closely matched' in new.marker_for_seed(4)
    assert 'PowerScore difference' not in new.marker_for_seed(4)


def test_uniform_and_small_gradual_differences_do_not_create_extra_tiers():
    for strengths in ([0] * 12, [i * -.025 for i in range(12)]):
        entrants, predictions = example(strengths)
        result = run(entrants, predictions)
        assert result.tier_guidance['cuts'] == []
        assert not result.breaks


def test_group_cost_uses_all_pairs_and_does_not_count_repeated_fixture_directions():
    entrants, predictions = example([1, .9, .8, .1, 0, -.7, -.8, -.9])
    order = [e.entrant_id for e in entrants]
    metadata = {e.entrant_id: GroupTeam(e.entrant_id, e.team_name, limited_history=False) for e in entrants}
    costs = grouping_costs(order, predictions, TierPolicy(), metadata, 1.0)
    assert float(costs[0, 4]) == pytest.approx(1.5)
    assert costs[0, 4] + costs[4, 8] < costs[0, 8]
    reverse = {(b, a): replace(p, expected_margin=-p.expected_margin, win_probability_a=p.win_probability_b,
                               win_probability_b=p.win_probability_a)
               for (a, b), p in predictions.items()}
    assert grouping_costs(order, predictions | reverse, TierPolicy(), metadata, 1.0) == costs


@pytest.mark.parametrize('unknown', [None, True])
def test_unknown_or_limited_history_does_not_become_confirmed_group_evidence(unknown):
    entrants, predictions = example([1, .9, .8, .1, 0, -.7, -.8, -.9])
    result = run([replace(e, limited_history=unknown) for e in entrants], predictions)
    assert result.tier_guidance['cuts'] == [4]
    assert not result.breaks
    boundary = next(b for b in result.tier_guidance['group_boundaries'] if b['after_seed'] == 4)
    assert boundary['classification'] == 'Uncertain'
    assert boundary['established_pairing_count'] == 0
    assert result.tier_guidance['review_required']


def test_missing_cross_group_prediction_never_supports_a_natural_break():
    entrants, predictions = example([1, .9, .8, .1, 0, -.7, -.8, -.9])
    analysis = build_cheat_sheet_analysis(entrants, predictions)
    del predictions['0', '7']
    guidance = build_tier_guidance(analysis, entrants, predictions, TierPolicy(), load_format_library())
    boundary = next(b for b in guidance['group_boundaries'] if b['after_seed'] == 4)
    assert not boundary['prediction_complete']
    assert boundary['classification'] == 'Uncertain'
    assert not guidance['divisions'][0]['natural_break_after']


def test_manual_membership_and_holds_recompute_the_group_comparison():
    entrants, predictions = example([1, .9, .8, .1, 0, -.7, -.8, -.9])
    result = run(entrants, predictions, manual_order=['4', '5', '6', '7', '0', '1', '2', '3'])
    assert not result.breaks  # An inverted manual order is not positive directional evidence.
    held = run(entrants, predictions, manual_order=['0', '1', '2', '3'], holds=['4', '5', '6', '7'])
    assert held.tier_guidance['cuts'] == []
    assert held.tier_guidance['assessed_count'] == 4
    assert held.tier_guidance['accepted_count'] == 8


def test_exact_search_safeguard_cannot_publish_a_group_recommendation():
    entrants, predictions = example([.8] * 8 + [-.8] * 8)
    library = load_format_library()
    recommendation = library.policies_by_id[resolve_format_profile(library).recommendation_policy_id]
    metadata = {e.entrant_id: GroupTeam(e.entrant_id, e.team_name, limited_history=False) for e in entrants}
    result = search_partitions([e.entrant_id for e in entrants], predictions, TierPolicy(), metadata,
                               (4, 8), recommendation, maximum_states=1)
    assert not result.complete
    assert result.primary is None


@pytest.mark.parametrize('seed', range(8))
def test_group_cohesion_search_matches_exhaustive_with_varied_directional_evidence(seed):
    import random
    rng = random.Random(seed)
    strengths = sorted((rng.uniform(-1, 1) for _ in range(18)), reverse=True)
    entrants, predictions = example(strengths)
    order = [e.entrant_id for e in entrants]
    metadata = {e.entrant_id: GroupTeam(e.entrant_id, e.team_name, limited_history=False) for e in entrants}
    library = load_format_library()
    profile = resolve_format_profile(library)
    exhaustive = suggest_automatic_flights(order, predictions, TierPolicy(), metadata, library, profile)
    exact = suggest_automatic_flights(order, predictions, TierPolicy(), metadata, library,
                                     replace(profile, max_candidate_structures=1))
    expected = next(p for p in exhaustive.assessment.plans if p.plan_id == exhaustive.primary_plan_id)
    actual = next(p for p in exact.assessment.plans if p.plan_id == exact.primary_plan_id)
    assert actual.flight_sizes == expected.flight_sizes
    assert actual.pair_weighted_average_matchup_cost == expected.pair_weighted_average_matchup_cost
    assert exact.generation.search_complete


@pytest.mark.parametrize('penalty', [True, 0, -1, float('inf'), float('nan'), '1'])
def test_group_penalty_requires_a_positive_finite_number(penalty):
    from scripts.build_matchbalance_format_catalog import build_catalog
    from src.tournaments.seeding_format_library import parse_format_library
    raw = build_catalog()
    raw['recommendation_policies'][-1]['group_split_penalty'] = penalty
    with pytest.raises(ValueError, match='[Gg]roup'):
        parse_format_library(raw)


@pytest.mark.parametrize('exact', [False, True])
def test_safer_practical_alternative_can_have_a_higher_group_penalty(exact):
    entrants, predictions = example([2.2 - i * .2 for i in range(12)])
    predictions = {k: replace(p, expected_absolute_goal_difference=max(abs(p.expected_margin),
                                                                     1 + abs(p.expected_margin) / 2))
                   for k, p in predictions.items()}
    result = run(entrants, predictions, exact=exact)
    assert [d['size'] for d in result.tier_guidance['divisions']] == [6, 6]
    assert any(tuple(a['flight_sizes']) == (4, 4, 4) for a in result.tier_guidance['alternatives'])


@pytest.mark.parametrize('exact', [False, True])
def test_same_count_alternative_can_improve_both_matchup_risk_metrics(exact):
    entrants, predictions = example([2.2 - i * .2 for i in range(12)])
    for i in range(4):
        for j in (4, 5):
            predictions[str(i), str(j)] = replace(predictions[str(i), str(j)],
                                                  expected_absolute_goal_difference=1.9)
    result = run(entrants, predictions, exact=exact)
    assert [d['size'] for d in result.tier_guidance['divisions']] == [6, 6]
    alternative = next(a for a in result.tier_guidance['alternatives'] if tuple(a['flight_sizes']) == (4, 8))
    assert alternative['additional_flight_count'] == 0
    assert alternative['worst_matchup_cost_delta'] < 0
    assert alternative['pair_weighted_average_matchup_cost_delta'] < 0
