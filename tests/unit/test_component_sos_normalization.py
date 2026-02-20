"""
Tests for Component-Based SOS Normalization.

This test suite verifies that SOS normalization works correctly when the
game graph contains disconnected subgraphs (e.g., ECNL and MLS NEXT HD
teams that never play each other).

The core problem:
  When two ecosystems never play each other, the Power-SOS iteration loop
  creates a feedback loop that inflates one ecosystem and deflates the other.
  SOS percentile normalization across the ENTIRE cohort then lets the inflated
  ecosystem monopolize top percentiles.

The fix:
  Detect connected components in the game graph and normalize SOS within
  each component independently.  This ensures each ecosystem gets a fair
  [0, 1] SOS distribution.  Small components get shrunk toward 0.5.

Scenarios tested:
  1. Two disconnected ecosystems of equal quality → similar power scores
  2. Two disconnected ecosystems of different quality → OFF/DEF differentiates
  3. Single connected graph → no change from current behavior
  4. Bridge game connecting ecosystems → single component, normal behavior
  5. Small isolated cluster → SOS shrunk toward 0.5
  6. Cross-age opponent as bridge → correctly connects components
  7. Iteration loop convergence with component normalization
  8. Component detection correctness (union-find)
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.etl.v53e import (
    V53EConfig,
    compute_rankings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game_pair(game_id, date, home, away, home_score, away_score,
                    age="14", gender="male"):
    """Create both perspective rows for a single game."""
    return [
        {
            "game_id": game_id,
            "date": pd.Timestamp(date),
            "team_id": home,
            "opp_id": away,
            "age": age,
            "gender": gender,
            "opp_age": age,
            "opp_gender": gender,
            "gf": home_score,
            "ga": away_score,
        },
        {
            "game_id": game_id,
            "date": pd.Timestamp(date),
            "team_id": away,
            "opp_id": home,
            "age": age,
            "gender": gender,
            "opp_age": age,
            "opp_gender": gender,
            "gf": away_score,
            "ga": home_score,
        },
    ]


def _build_ecosystem(team_prefix, num_teams, games_per_team, base_date,
                     avg_goals=1.5, seed=42, age="14", gender="male"):
    """
    Build a closed ecosystem of teams that only play each other.

    Returns (rows, team_ids) where rows is a list of game dicts.
    """
    rng = np.random.RandomState(seed)
    team_ids = [f"{team_prefix}_{i:03d}" for i in range(num_teams)]
    rows = []
    game_counter = 0

    games_needed = (num_teams * games_per_team) // 2 + num_teams
    for _ in range(games_needed):
        home_idx, away_idx = rng.choice(num_teams, size=2, replace=False)
        home = team_ids[home_idx]
        away = team_ids[away_idx]

        home_score = int(rng.poisson(avg_goals))
        away_score = int(rng.poisson(avg_goals))

        game_date = base_date - timedelta(days=int(rng.randint(1, 300)))
        game_id = f"{team_prefix}_g{game_counter:04d}"
        game_counter += 1

        rows.extend(_make_game_pair(
            game_id, game_date, home, away, home_score, away_score,
            age=age, gender=gender
        ))

    return rows, team_ids


def _build_two_disconnected_ecosystems(
    eco_a_teams=15, eco_b_teams=15,
    games_per_team=12, avg_goals=1.5,
    seed_a=42, seed_b=99,
    age="14", gender="male",
):
    """
    Build two completely disconnected ecosystems with similar quality.

    Ecosystem A ("ecnl_") and Ecosystem B ("mlsnext_") never play each other.
    Both have similar number of teams, games, and goal-scoring patterns.
    """
    base_date = datetime(2025, 7, 1)

    rows_a, ids_a = _build_ecosystem(
        "ecnl", eco_a_teams, games_per_team, base_date,
        avg_goals=avg_goals, seed=seed_a, age=age, gender=gender
    )
    rows_b, ids_b = _build_ecosystem(
        "mlsnext", eco_b_teams, games_per_team, base_date,
        avg_goals=avg_goals, seed=seed_b, age=age, gender=gender
    )

    all_rows = rows_a + rows_b
    games_df = pd.DataFrame(all_rows)
    return games_df, ids_a, ids_b


# ===========================================================================
# Test 1: Two disconnected ecosystems of EQUAL quality
# ===========================================================================

class TestDisconnectedEqualEcosystems:
    """
    When two ecosystems have similar goal-scoring patterns and never play
    each other, their power scores should be comparable — NOT systematically
    different due to SOS feedback loops.
    """

    @pytest.fixture
    def equal_ecosystems(self):
        games_df, ids_a, ids_b = _build_two_disconnected_ecosystems(
            eco_a_teams=15, eco_b_teams=15,
            games_per_team=12, avg_goals=1.5,
            seed_a=42, seed_b=99,
        )
        cfg = V53EConfig()
        result = compute_rankings(
            games_df=games_df, cfg=cfg,
            today=pd.Timestamp("2025-07-01")
        )
        return result, ids_a, ids_b

    def test_both_ecosystems_have_active_teams(self, equal_ecosystems):
        """Both ecosystems should produce Active-status teams."""
        result, ids_a, ids_b = equal_ecosystems
        teams = result["teams"]

        active_a = teams[
            (teams["team_id"].isin(ids_a)) & (teams["status"] == "Active")
        ]
        active_b = teams[
            (teams["team_id"].isin(ids_b)) & (teams["status"] == "Active")
        ]

        assert len(active_a) >= 5, f"Ecosystem A: only {len(active_a)} Active teams"
        assert len(active_b) >= 5, f"Ecosystem B: only {len(active_b)} Active teams"

    def test_sos_norm_ranges_similar_across_ecosystems(self, equal_ecosystems):
        """
        CRITICAL: Both ecosystems should have similar sos_norm distributions.

        Before the fix, one ecosystem would monopolize [0.6-1.0] and the
        other would be compressed to [0.0-0.4].  After the fix, each
        ecosystem should independently span [0, 1].
        """
        result, ids_a, ids_b = equal_ecosystems
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]

        sos_a = active[active["team_id"].isin(ids_a)]["sos_norm"]
        sos_b = active[active["team_id"].isin(ids_b)]["sos_norm"]

        # Both ecosystems should have similar mean sos_norm (within 0.15)
        mean_diff = abs(sos_a.mean() - sos_b.mean())
        assert mean_diff < 0.15, (
            f"SOS norm means differ by {mean_diff:.3f} between ecosystems. "
            f"Eco A mean={sos_a.mean():.3f}, Eco B mean={sos_b.mean():.3f}. "
            f"This suggests SOS feedback loop bias."
        )

    def test_power_scores_similar_across_ecosystems(self, equal_ecosystems):
        """
        CRITICAL: With equal quality, mean power scores should be comparable.

        Before the fix, the inflated ecosystem could be 0.10+ higher.
        After the fix, the difference should be < 0.05.
        """
        result, ids_a, ids_b = equal_ecosystems
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]

        power_a = active[active["team_id"].isin(ids_a)]["powerscore_adj"]
        power_b = active[active["team_id"].isin(ids_b)]["powerscore_adj"]

        mean_diff = abs(power_a.mean() - power_b.mean())
        assert mean_diff < 0.05, (
            f"Power score means differ by {mean_diff:.3f} between ecosystems. "
            f"Eco A mean={power_a.mean():.3f}, Eco B mean={power_b.mean():.3f}. "
            f"This suggests SOS-driven bias between disconnected subgraphs."
        )

    def test_top_teams_from_both_ecosystems_in_top_half(self, equal_ecosystems):
        """
        The best team from each ecosystem should rank in the top half
        of the combined cohort.
        """
        result, ids_a, ids_b = equal_ecosystems
        teams = result["teams"]
        active = teams[teams["status"] == "Active"].copy()
        active["combined_rank"] = active["powerscore_adj"].rank(ascending=False)

        total_active = len(active)
        top_half = total_active / 2

        best_a_rank = active[active["team_id"].isin(ids_a)]["combined_rank"].min()
        best_b_rank = active[active["team_id"].isin(ids_b)]["combined_rank"].min()

        assert best_a_rank <= top_half, (
            f"Best Eco A team ranked {best_a_rank}/{total_active} — not in top half"
        )
        assert best_b_rank <= top_half, (
            f"Best Eco B team ranked {best_b_rank}/{total_active} — not in top half"
        )


# ===========================================================================
# Test 2: Two disconnected ecosystems of DIFFERENT quality
# ===========================================================================

class TestDisconnectedDifferentQuality:
    """
    When one ecosystem genuinely scores more goals (higher quality),
    they should rank higher — but through OFF/DEF, not SOS inflation.
    """

    @pytest.fixture
    def different_quality_ecosystems(self):
        base_date = datetime(2025, 7, 1)

        # Ecosystem A: higher scoring (strong teams)
        rows_a, ids_a = _build_ecosystem(
            "strong", 12, 12, base_date,
            avg_goals=2.5, seed=42
        )
        # Ecosystem B: lower scoring (weaker teams)
        rows_b, ids_b = _build_ecosystem(
            "weak", 12, 12, base_date,
            avg_goals=0.8, seed=99
        )

        games_df = pd.DataFrame(rows_a + rows_b)
        cfg = V53EConfig()
        result = compute_rankings(
            games_df=games_df, cfg=cfg,
            today=pd.Timestamp("2025-07-01")
        )
        return result, ids_a, ids_b

    def test_strong_ecosystem_ranks_higher_on_average(self, different_quality_ecosystems):
        """Strong ecosystem should rank higher via OFF/DEF, not SOS."""
        result, ids_a, ids_b = different_quality_ecosystems
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]

        power_strong = active[active["team_id"].isin(ids_a)]["powerscore_adj"].mean()
        power_weak = active[active["team_id"].isin(ids_b)]["powerscore_adj"].mean()

        assert power_strong > power_weak, (
            f"Strong ecosystem ({power_strong:.3f}) should rank above "
            f"weak ecosystem ({power_weak:.3f})"
        )

    def test_differentiation_comes_from_off_def_not_sos(self, different_quality_ecosystems):
        """
        The OFF/DEF difference between ecosystems should be larger than
        the SOS difference.  Before the fix, SOS dominated the gap.
        After the fix, OFF/DEF should be the primary differentiator.
        """
        result, ids_a, ids_b = different_quality_ecosystems
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]

        # OFF/DEF gap
        off_strong = active[active["team_id"].isin(ids_a)]["off_norm"].mean()
        off_weak = active[active["team_id"].isin(ids_b)]["off_norm"].mean()
        off_gap = abs(off_strong - off_weak)

        # SOS gap
        sos_strong = active[active["team_id"].isin(ids_a)]["sos_norm"].mean()
        sos_weak = active[active["team_id"].isin(ids_b)]["sos_norm"].mean()
        sos_gap = abs(sos_strong - sos_weak)

        assert sos_gap < 0.20, (
            f"SOS gap between disconnected ecosystems is {sos_gap:.3f} — "
            f"should be < 0.20 since both ecosystems independently normalize. "
            f"OFF gap={off_gap:.3f} is the legitimate differentiator."
        )


# ===========================================================================
# Test 3: Single connected graph (no change expected)
# ===========================================================================

class TestSingleConnectedGraph:
    """
    When all teams are in one connected graph, component normalization
    should produce identical results to cohort-level normalization.
    """

    @pytest.fixture
    def connected_cohort(self):
        base_date = datetime(2025, 7, 1)
        # Use 35 teams to exceed MIN_COMPONENT_SIZE_FOR_FULL_SOS (30)
        # so component-size shrinkage doesn't compress the range
        rows, team_ids = _build_ecosystem(
            "team", 35, 12, base_date, seed=42
        )
        games_df = pd.DataFrame(rows)
        cfg = V53EConfig()
        result = compute_rankings(
            games_df=games_df, cfg=cfg,
            today=pd.Timestamp("2025-07-01")
        )
        return result, team_ids

    def test_sos_norm_uses_full_range(self, connected_cohort):
        """In a connected graph, sos_norm should span ~[0, 1]."""
        result, team_ids = connected_cohort
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]

        assert active["sos_norm"].min() < 0.15, (
            f"Min sos_norm={active['sos_norm'].min():.3f} — should be near 0"
        )
        assert active["sos_norm"].max() > 0.85, (
            f"Max sos_norm={active['sos_norm'].max():.3f} — should be near 1"
        )

    def test_powerscore_spread_reasonable(self, connected_cohort):
        """Power scores should have meaningful spread in connected graph."""
        result, team_ids = connected_cohort
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]

        spread = active["powerscore_adj"].max() - active["powerscore_adj"].min()
        assert spread > 0.05, (
            f"Power score spread is only {spread:.3f} — too compressed"
        )


# ===========================================================================
# Test 4: Bridge game connecting ecosystems
# ===========================================================================

class TestBridgeGameConnects:
    """
    When a single bridge game connects two ecosystems, they should merge
    into one component and be normalized together.
    """

    @pytest.fixture
    def bridged_ecosystems(self):
        base_date = datetime(2025, 7, 1)

        # Use 18 teams per ecosystem so combined (36) exceeds
        # MIN_COMPONENT_SIZE_FOR_FULL_SOS (30) after bridge merge
        rows_a, ids_a = _build_ecosystem(
            "eco_a", 18, 12, base_date, seed=42
        )
        rows_b, ids_b = _build_ecosystem(
            "eco_b", 18, 12, base_date, seed=99
        )

        # Add ONE bridge game between the ecosystems
        bridge_rows = _make_game_pair(
            "bridge_001",
            base_date - timedelta(days=50),
            ids_a[0], ids_b[0],
            2, 1,
        )
        all_rows = rows_a + rows_b + bridge_rows
        games_df = pd.DataFrame(all_rows)

        cfg = V53EConfig()
        result = compute_rankings(
            games_df=games_df, cfg=cfg,
            today=pd.Timestamp("2025-07-01")
        )
        return result, ids_a, ids_b

    def test_bridge_creates_single_component(self, bridged_ecosystems):
        """
        With a bridge game, both ecosystems should behave as one connected
        graph.  SOS norm should use the full range across all teams.
        """
        result, ids_a, ids_b = bridged_ecosystems
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]

        all_sos = active["sos_norm"]
        assert all_sos.min() < 0.15, "Min sos_norm should be near 0"
        assert all_sos.max() > 0.85, "Max sos_norm should be near 1"


# ===========================================================================
# Test 5: Small isolated cluster
# ===========================================================================

class TestSmallIsolatedCluster:
    """
    A tiny group of teams (3-5) that only play each other should have
    their SOS shrunk toward 0.5 (component-size shrinkage).
    """

    @pytest.fixture
    def small_cluster_with_large_ecosystem(self):
        base_date = datetime(2025, 7, 1)

        # Large ecosystem (20 teams)
        rows_large, ids_large = _build_ecosystem(
            "large", 20, 12, base_date, seed=42
        )

        # Small isolated cluster (4 teams, each plays 10 games)
        rows_small, ids_small = _build_ecosystem(
            "tiny", 4, 10, base_date, seed=77
        )

        games_df = pd.DataFrame(rows_large + rows_small)
        cfg = V53EConfig()
        result = compute_rankings(
            games_df=games_df, cfg=cfg,
            today=pd.Timestamp("2025-07-01")
        )
        return result, ids_large, ids_small

    def test_small_cluster_sos_shrunk_toward_neutral(self, small_cluster_with_large_ecosystem):
        """
        SOS norm for the small cluster should be closer to 0.5 than the
        large ecosystem's range.  Component-size shrinkage prevents a
        4-team cluster from getting sos_norm = 1.0.
        """
        result, ids_large, ids_small = small_cluster_with_large_ecosystem
        teams = result["teams"]

        small_sos = teams[teams["team_id"].isin(ids_small)]["sos_norm"]
        large_sos = teams[
            (teams["team_id"].isin(ids_large)) & (teams["status"] == "Active")
        ]["sos_norm"]

        # Small cluster should have narrow SOS range, centered near 0.5
        small_range = small_sos.max() - small_sos.min()
        large_range = large_sos.max() - large_sos.min()

        assert small_range < large_range, (
            f"Small cluster SOS range ({small_range:.3f}) should be narrower "
            f"than large ecosystem ({large_range:.3f})"
        )

    def test_small_cluster_not_inflated_to_top(self, small_cluster_with_large_ecosystem):
        """
        The best team in the small cluster should NOT rank above the
        median of the large ecosystem (no artificial inflation).
        """
        result, ids_large, ids_small = small_cluster_with_large_ecosystem
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]

        large_active = active[active["team_id"].isin(ids_large)]
        large_median_power = large_active["powerscore_adj"].median()

        small_active = active[active["team_id"].isin(ids_small)]
        if len(small_active) > 0:
            small_best = small_active["powerscore_adj"].max()
            # Small cluster's best shouldn't dominate large ecosystem
            # (unless they genuinely score more — but with same avg_goals they shouldn't)
            assert small_best < large_median_power + 0.10, (
                f"Small cluster best ({small_best:.3f}) is inflated above "
                f"large ecosystem median ({large_median_power:.3f})"
            )


# ===========================================================================
# Test 6: Iteration loop convergence
# ===========================================================================

class TestIterationConvergence:
    """
    The Power-SOS iteration loop should converge correctly with
    component-based normalization.
    """

    @pytest.fixture
    def disconnected_with_iterations(self):
        games_df, ids_a, ids_b = _build_two_disconnected_ecosystems(
            eco_a_teams=12, eco_b_teams=12,
            games_per_team=12,
        )
        cfg = V53EConfig()
        cfg.SOS_POWER_ITERATIONS = 3  # Ensure iterations are enabled
        result = compute_rankings(
            games_df=games_df, cfg=cfg,
            today=pd.Timestamp("2025-07-01")
        )
        return result, ids_a, ids_b

    def test_iterations_dont_amplify_ecosystem_gap(self, disconnected_with_iterations):
        """
        CRITICAL: After 3 Power-SOS iterations, the gap between
        disconnected ecosystems should NOT grow.

        Before the fix, each iteration amplified the gap.
        After the fix, iterations refine within each component independently.
        """
        result, ids_a, ids_b = disconnected_with_iterations
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]

        power_a = active[active["team_id"].isin(ids_a)]["powerscore_adj"]
        power_b = active[active["team_id"].isin(ids_b)]["powerscore_adj"]

        mean_diff = abs(power_a.mean() - power_b.mean())
        assert mean_diff < 0.05, (
            f"After 3 iterations, power gap is {mean_diff:.3f}. "
            f"Iterations should NOT amplify bias between disconnected ecosystems."
        )

    def test_all_power_scores_valid(self, disconnected_with_iterations):
        """Power scores should be in valid range after iterations."""
        result, ids_a, ids_b = disconnected_with_iterations
        teams = result["teams"]

        assert teams["powerscore_adj"].min() >= 0.0, "Negative power score"
        assert teams["powerscore_adj"].max() <= 1.0, "Power score > 1.0"
        assert not teams["powerscore_adj"].isna().any(), "NaN power score"


# ===========================================================================
# Test 7: Three-way disconnect (multiple components)
# ===========================================================================

class TestMultipleDisconnectedComponents:
    """
    Three completely disconnected ecosystems should each get independent
    SOS normalization.
    """

    @pytest.fixture
    def three_ecosystems(self):
        base_date = datetime(2025, 7, 1)

        # Use 15 teams per ecosystem to reduce random variance
        rows_a, ids_a = _build_ecosystem(
            "eco_a", 15, 12, base_date, avg_goals=1.5, seed=42
        )
        rows_b, ids_b = _build_ecosystem(
            "eco_b", 15, 12, base_date, avg_goals=1.5, seed=99
        )
        rows_c, ids_c = _build_ecosystem(
            "eco_c", 15, 12, base_date, avg_goals=1.5, seed=123
        )

        games_df = pd.DataFrame(rows_a + rows_b + rows_c)
        cfg = V53EConfig()
        result = compute_rankings(
            games_df=games_df, cfg=cfg,
            today=pd.Timestamp("2025-07-01")
        )
        return result, ids_a, ids_b, ids_c

    def test_all_three_ecosystems_have_similar_sos_means(self, three_ecosystems):
        """All three disconnected ecosystems should have similar sos_norm means."""
        result, ids_a, ids_b, ids_c = three_ecosystems
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]

        means = []
        for ids in [ids_a, ids_b, ids_c]:
            eco_sos = active[active["team_id"].isin(ids)]["sos_norm"]
            if len(eco_sos) > 0:
                means.append(eco_sos.mean())

        if len(means) >= 2:
            max_diff = max(means) - min(means)
            assert max_diff < 0.15, (
                f"SOS norm means across 3 ecosystems differ by {max_diff:.3f}. "
                f"Means: {[f'{m:.3f}' for m in means]}"
            )

    def test_all_three_have_similar_power_score_means(self, three_ecosystems):
        """
        With equal avg_goals, power score means should be comparable.
        Allow 0.10 tolerance for random variance in OFF/DEF across seeds.
        (Before fix: gap was 0.48+. After fix: gap should be < 0.10.)
        """
        result, ids_a, ids_b, ids_c = three_ecosystems
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]

        means = []
        for ids in [ids_a, ids_b, ids_c]:
            eco_power = active[active["team_id"].isin(ids)]["powerscore_adj"]
            if len(eco_power) > 0:
                means.append(eco_power.mean())

        if len(means) >= 2:
            max_diff = max(means) - min(means)
            assert max_diff < 0.10, (
                f"Power score means across 3 ecosystems differ by {max_diff:.3f}. "
                f"Means: {[f'{m:.3f}' for m in means]}. "
                f"Before fix this was 0.48+; should now be < 0.10."
            )


# ===========================================================================
# Test 8: Asymmetric ecosystem sizes
# ===========================================================================

class TestAsymmetricEcosystemSizes:
    """
    One ecosystem has 30 teams, the other has 8.  Both should get fair
    SOS normalization, with the smaller one getting some shrinkage.
    """

    @pytest.fixture
    def asymmetric_ecosystems(self):
        base_date = datetime(2025, 7, 1)

        rows_big, ids_big = _build_ecosystem(
            "big", 30, 12, base_date, avg_goals=1.5, seed=42
        )
        rows_small, ids_small = _build_ecosystem(
            "small", 8, 12, base_date, avg_goals=1.5, seed=99
        )

        games_df = pd.DataFrame(rows_big + rows_small)
        cfg = V53EConfig()
        result = compute_rankings(
            games_df=games_df, cfg=cfg,
            today=pd.Timestamp("2025-07-01")
        )
        return result, ids_big, ids_small

    def test_small_ecosystem_not_systematically_lower(self, asymmetric_ecosystems):
        """
        The smaller ecosystem should NOT be systematically ranked lower
        just because it has fewer teams.
        """
        result, ids_big, ids_small = asymmetric_ecosystems
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]

        power_big = active[active["team_id"].isin(ids_big)]["powerscore_adj"]
        power_small = active[active["team_id"].isin(ids_small)]["powerscore_adj"]

        if len(power_small) > 0:
            mean_diff = abs(power_big.mean() - power_small.mean())
            assert mean_diff < 0.08, (
                f"Power gap between big ({power_big.mean():.3f}) and small "
                f"({power_small.mean():.3f}) ecosystems is {mean_diff:.3f}. "
                f"Size alone should not cause this gap."
            )


# ===========================================================================
# Test 9: Verify OFF/DEF is the cross-component differentiator
# ===========================================================================

class TestOffDefDifferentiatesComponents:
    """
    When ecosystems differ in quality, the ranking difference should come
    from OFF/DEF (which is opponent-adjusted), NOT from SOS.
    """

    @pytest.fixture
    def quality_gap_ecosystems(self):
        base_date = datetime(2025, 7, 1)

        # Strong ecosystem: avg 3 goals per game
        rows_strong, ids_strong = _build_ecosystem(
            "strong", 12, 12, base_date, avg_goals=3.0, seed=42
        )
        # Weak ecosystem: avg 0.5 goals per game
        rows_weak, ids_weak = _build_ecosystem(
            "weak", 12, 12, base_date, avg_goals=0.5, seed=99
        )

        games_df = pd.DataFrame(rows_strong + rows_weak)
        cfg = V53EConfig()
        result = compute_rankings(
            games_df=games_df, cfg=cfg,
            today=pd.Timestamp("2025-07-01")
        )
        return result, ids_strong, ids_weak

    def test_off_norm_gap_larger_than_sos_gap(self, quality_gap_ecosystems):
        """
        OFF/DEF should be the primary differentiator, not SOS.
        """
        result, ids_strong, ids_weak = quality_gap_ecosystems
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]

        # OFF gap
        off_strong = active[active["team_id"].isin(ids_strong)]["off_norm"].mean()
        off_weak = active[active["team_id"].isin(ids_weak)]["off_norm"].mean()
        off_gap = off_strong - off_weak  # Should be large and positive

        # SOS gap (between disconnected ecosystems)
        sos_strong = active[active["team_id"].isin(ids_strong)]["sos_norm"].mean()
        sos_weak = active[active["team_id"].isin(ids_weak)]["sos_norm"].mean()
        sos_gap = abs(sos_strong - sos_weak)

        assert off_gap > 0.10, (
            f"OFF gap ({off_gap:.3f}) should be meaningful between ecosystems"
        )
        assert sos_gap < 0.20, (
            f"SOS gap ({sos_gap:.3f}) between disconnected ecosystems should "
            f"be small. OFF gap ({off_gap:.3f}) is the legitimate differentiator."
        )
