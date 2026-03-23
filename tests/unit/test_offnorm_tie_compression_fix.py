"""
Tests for off_norm tie compression fix and SOS inflation prevention.

Validates that:
1. _percentile_norm tiebreaker correctly differentiates teams clipped to same ceiling
2. SOS hybrid normalization preserves natural gaps at the tails
3. Tighter clip threshold (3.0σ vs 3.5σ) reduces the number of teams hitting ceiling
4. Regional ECNL-RL teams don't outrank national ECNL teams
5. Weight rebalancing analysis (SOS 50% vs 60%)

Reproduces the Arkansas Rising bug: an ECNL-RL team ranked #1 U16 Female
because off_norm compression + circular SOS inflation in a regional bubble.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from copy import deepcopy

from src.etl.v53e import (
    V53EConfig,
    compute_rankings,
    _percentile_norm,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game_pair(game_id, date, home, away, home_score, away_score,
                    age="16", gender="female"):
    """Create both perspective rows for a single game."""
    return [
        {"game_id": game_id, "date": pd.Timestamp(date),
         "team_id": home, "opp_id": away, "age": age, "gender": gender,
         "opp_age": age, "opp_gender": gender, "gf": home_score, "ga": away_score},
        {"game_id": game_id, "date": pd.Timestamp(date),
         "team_id": away, "opp_id": home, "age": age, "gender": gender,
         "opp_age": age, "opp_gender": gender, "gf": away_score, "ga": home_score},
    ]


def _build_regional_bubble(bubble_teams, num_games_per_team=12, seed=42,
                            age="16", gender="female", base_date=None,
                            scoring_fn=None):
    """
    Build a closed regional bubble where teams only play each other.

    Args:
        bubble_teams: list of team IDs
        scoring_fn: optional callable(rng, home, away) -> (home_score, away_score)
                    defaults to random Poisson(1.5) scores
    """
    rng = np.random.RandomState(seed)
    base_date = base_date or datetime(2026, 1, 15)
    rows = []
    game_counter = 0
    n = len(bubble_teams)

    games_needed = (n * num_games_per_team) // 2 + n
    for _ in range(games_needed):
        hi, ai = rng.choice(n, size=2, replace=False)
        home, away = bubble_teams[hi], bubble_teams[ai]

        if scoring_fn:
            hs, aws = scoring_fn(rng, home, away)
        else:
            hs = int(rng.poisson(1.5))
            aws = int(rng.poisson(1.5))

        game_date = base_date - timedelta(days=int(rng.randint(1, 200)))
        rows.extend(_make_game_pair(
            f"g_{game_counter:04d}", game_date, home, away, hs, aws,
            age=age, gender=gender
        ))
        game_counter += 1

    return rows


def _build_national_league(national_teams, num_games_per_team=15, seed=99,
                           age="16", gender="female", base_date=None,
                           dominant_teams=None):
    """
    Build a national league with cross-region play.

    Args:
        dominant_teams: set of team IDs that tend to win (higher scoring)
    """
    rng = np.random.RandomState(seed)
    base_date = base_date or datetime(2026, 1, 15)
    rows = []
    game_counter = 5000  # offset to avoid collision with bubble game IDs
    n = len(national_teams)
    dominant_teams = dominant_teams or set()

    games_needed = (n * num_games_per_team) // 2 + n
    for _ in range(games_needed):
        hi, ai = rng.choice(n, size=2, replace=False)
        home, away = national_teams[hi], national_teams[ai]

        # Dominant teams score more
        home_lambda = 2.5 if home in dominant_teams else 1.3
        away_lambda = 2.5 if away in dominant_teams else 1.3

        hs = int(rng.poisson(home_lambda))
        aws = int(rng.poisson(away_lambda))

        game_date = base_date - timedelta(days=int(rng.randint(1, 200)))
        rows.extend(_make_game_pair(
            f"g_{game_counter:04d}", game_date, home, away, hs, aws,
            age=age, gender=gender
        ))
        game_counter += 1

    return rows


def _build_arkansas_rising_scenario():
    """
    Reproduce the Arkansas Rising bug scenario with realistic pool sizes:
    - 8 ECNL-RL teams in a regional bubble (AR/OK states, only play each other)
    - 30 ECNL national teams with cross-region play (the elite pool)
    - 40 NPL/filler teams (weaker, mostly play each other + some ECNL)
    - Total ~78 teams = realistic U16 Female cohort size

    Key dynamics:
    - ECNL teams are strongest (high goal scoring, beat NPL teams)
    - RL bubble leader dominates their bubble but the bubble is isolated
    - NPL teams are weakest, giving ECNL high SOS when they play them
    - RL teams have NO bridge games → pure isolated bubble
    """
    rl_teams = [f"rl_team_{i}" for i in range(8)]
    ecnl_teams = [f"ecnl_team_{i}" for i in range(30)]
    npl_teams = [f"npl_team_{i}" for i in range(40)]

    all_rows = []
    rng = np.random.RandomState(42)
    base_date = datetime(2026, 1, 15)
    gc = 0

    def add_game(home, away, hs, aws):
        nonlocal gc
        game_date = base_date - timedelta(days=int(rng.randint(1, 300)))
        all_rows.extend(_make_game_pair(f"g_{gc:05d}", game_date, home, away, hs, aws))
        gc += 1

    # --- 1) RL bubble: only play each other, rl_team_0 dominates ---
    for _ in range((8 * 14) // 2 + 8):
        hi, ai = rng.choice(len(rl_teams), size=2, replace=False)
        home, away = rl_teams[hi], rl_teams[ai]
        if home == "rl_team_0":
            hs, aws = int(rng.poisson(3.0)), int(rng.poisson(0.5))
        elif away == "rl_team_0":
            hs, aws = int(rng.poisson(0.5)), int(rng.poisson(3.0))
        else:
            hs, aws = int(rng.poisson(1.5)), int(rng.poisson(1.5))
        add_game(home, away, hs, aws)

    # --- 2) ECNL national league: cross-region, top teams dominant ---
    dominant_ecnl = set(ecnl_teams[:8])
    for _ in range((30 * 16) // 2 + 30):
        hi, ai = rng.choice(len(ecnl_teams), size=2, replace=False)
        home, away = ecnl_teams[hi], ecnl_teams[ai]
        h_lam = 2.8 if home in dominant_ecnl else 1.5
        a_lam = 2.8 if away in dominant_ecnl else 1.5
        add_game(home, away, int(rng.poisson(h_lam)), int(rng.poisson(a_lam)))

    # --- 3) NPL teams play each other (weaker pool) ---
    for _ in range((40 * 10) // 2 + 20):
        hi, ai = rng.choice(len(npl_teams), size=2, replace=False)
        add_game(npl_teams[hi], npl_teams[ai],
                 int(rng.poisson(1.2)), int(rng.poisson(1.2)))

    # --- 4) Bridge: ECNL teams play NPL teams (ECNL dominates) ---
    # This gives ECNL teams SOS credit for beating weaker opponents,
    # while NPL teams get SOS credit for playing strong ECNL opponents
    for i in range(40):
        ecnl_t = ecnl_teams[i % len(ecnl_teams)]
        npl_t = npl_teams[i % len(npl_teams)]
        add_game(ecnl_t, npl_t, int(rng.poisson(3.5)), int(rng.poisson(0.5)))

    # --- 5) A few cross-NPL-region games ---
    for i in range(15):
        n1, n2 = rng.choice(len(npl_teams), size=2, replace=False)
        add_game(npl_teams[n1], npl_teams[n2],
                 int(rng.poisson(1.0)), int(rng.poisson(1.0)))

    # NOTE: RL teams have ZERO bridge games — pure isolated bubble

    games_df = pd.DataFrame(all_rows)

    # State map for SCF
    team_state_map = {}
    for t in rl_teams:
        team_state_map[t] = "AR"  # All RL in Arkansas = same state = low diversity
    ecnl_states = ["CA", "TX", "FL", "GA", "NC", "NJ", "IL", "OH", "VA", "CO",
                   "WA", "AZ", "TN", "MA", "MD", "NY", "PA", "MI", "MN", "OR",
                   "CT", "SC", "AL", "KY", "MO", "WI", "IN", "IA", "NE", "KS"]
    for i, t in enumerate(ecnl_teams):
        team_state_map[t] = ecnl_states[i % len(ecnl_states)]
    npl_states = ["ID", "MT", "WY", "UT", "NV", "NM", "SD", "ND"]
    for i, t in enumerate(npl_teams):
        team_state_map[t] = npl_states[i % len(npl_states)]

    return games_df, rl_teams, ecnl_teams, npl_teams, team_state_map


# ===========================================================================
# Test 1: _percentile_norm tiebreaker fix
# ===========================================================================

class TestPercentileNormTiebreaker:
    """Verify the tiebreaker properly differentiates clipped teams."""

    def test_all_identical_primary_values_spread_by_tiebreaker(self):
        """When all primary values are identical (all clipped to same ceiling),
        tiebreaker should produce a full [0,1] spread, not a flat line."""
        n = 80
        # Simulate: all teams clipped to the same off_shrunk ceiling
        clipped = pd.Series([2.572] * n)
        # Pre-clip values vary significantly
        preclip = pd.Series(np.linspace(1.5, 5.0, n))

        result = _percentile_norm(clipped, tiebreaker=preclip)

        # Should produce distinct values spanning most of [0, 1]
        assert result.nunique() == n, \
            f"Expected {n} distinct values, got {result.nunique()}"

        spread = result.max() - result.min()
        assert spread > 0.9, \
            f"Tiebreaker spread too narrow: {spread:.4f} (need > 0.9)"

        # Ordering should follow tiebreaker (higher preclip → higher norm)
        assert result.corr(preclip) > 0.99, \
            "Tiebreaker ordering not preserved"

    def test_partial_ties_dont_reorder_non_tied(self):
        """Tiebreaker must not change the ordering of teams with different
        primary values — only break ties among equal primary values."""
        # 3 distinct groups: low, medium (tied), high
        primary = pd.Series([1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 3.0, 3.0, 3.0])
        tiebreaker = pd.Series([0.5, 1.5, 1.0, 2.5, 0.1, 1.8, 3.0, 2.0, 2.5])

        result = _percentile_norm(primary, tiebreaker=tiebreaker)

        # Group ordering must be preserved: all low < all medium < all high
        low_group = result.iloc[:3]
        med_group = result.iloc[3:6]
        high_group = result.iloc[6:9]

        assert low_group.max() < med_group.min(), \
            "Low group overlaps with medium group after tiebreaking"
        assert med_group.max() < high_group.min(), \
            "Medium group overlaps with high group after tiebreaking"

    def test_within_tied_group_tiebreaker_determines_order(self):
        """Within a group of tied primary values, the tiebreaker should
        determine the final ordering."""
        primary = pd.Series([5.0] * 10)
        tiebreaker = pd.Series([10, 9, 8, 7, 6, 5, 4, 3, 2, 1], dtype=float)

        result = _percentile_norm(primary, tiebreaker=tiebreaker)

        # Team with highest tiebreaker should get highest percentile
        assert result.iloc[0] == result.max(), \
            "Highest tiebreaker should get highest percentile"
        assert result.iloc[-1] == result.min(), \
            "Lowest tiebreaker should get lowest percentile"

    def test_no_tiebreaker_fallback(self):
        """Without tiebreaker, standard percentile ranking should work."""
        values = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = _percentile_norm(values)
        assert result.is_monotonic_increasing

    def test_old_epsilon_was_too_small(self):
        """Demonstrate that the old epsilon (x_std * 1e-10) fails to
        differentiate 80 teams clipped to the same value."""
        n = 80
        clipped = pd.Series([2.572] * n)
        preclip = pd.Series(np.linspace(1.5, 5.0, n))

        # Simulate old behavior: epsilon too small
        x_std = clipped.std(ddof=0)  # = 0 since all identical
        eps_old = x_std * 1e-10 if x_std > 0 else 1e-15
        composite_old = clipped + eps_old * preclip.rank(method="average", pct=True)
        result_old = composite_old.rank(method="average", pct=True)

        # Old method: when std=0, eps=1e-15, composite barely differs
        # All values should be nearly identical (within floating point)
        # The spread should be tiny
        spread_old = result_old.max() - result_old.min()

        # New method
        result_new = _percentile_norm(clipped, tiebreaker=preclip)
        spread_new = result_new.max() - result_new.min()

        assert spread_new > spread_old * 10, \
            f"New method spread ({spread_new:.4f}) should be much larger than old ({spread_old:.4f})"


# ===========================================================================
# Test 2: Full scenario — RL team should NOT outrank ECNL
# ===========================================================================

class TestArkansasRisingScenario:
    """End-to-end test reproducing the Arkansas Rising ranking bug."""

    @pytest.fixture
    def scenario(self):
        games_df, rl_teams, ecnl_teams, filler_teams, team_state_map = \
            _build_arkansas_rising_scenario()
        cfg = V53EConfig()  # Uses the fixed defaults
        result = compute_rankings(
            games_df, cfg=cfg, team_state_map=team_state_map
        )
        teams = result["teams"]
        return teams, rl_teams, ecnl_teams, filler_teams

    def test_top_ecnl_teams_outrank_rl_bubble(self, scenario):
        """Multiple ECNL teams should be ranked above the RL bubble leader."""
        teams, rl_teams, ecnl_teams, _ = scenario

        # Get the best RL team (rl_team_0 = Arkansas Rising analog)
        rl_leader = teams[teams["team_id"] == "rl_team_0"]
        if rl_leader.empty:
            pytest.skip("rl_team_0 not in results (possibly filtered by min games)")

        rl_power = rl_leader["powerscore_adj"].values[0]

        # Count ECNL teams that outrank the RL leader
        ecnl_df = teams[teams["team_id"].isin(ecnl_teams)]
        ecnl_above_rl = (ecnl_df["powerscore_adj"] > rl_power).sum()

        assert ecnl_above_rl >= 5, (
            f"Only {ecnl_above_rl} ECNL teams outrank RL leader "
            f"(RL power={rl_power:.4f}). Expected at least 5."
        )

    def test_rl_leader_not_rank_1(self, scenario):
        """The RL bubble leader should NOT be ranked #1 overall."""
        teams, rl_teams, _, _ = scenario

        # Sort by powerscore_adj descending
        ranked = teams.sort_values("powerscore_adj", ascending=False).reset_index(drop=True)
        top_team = ranked.iloc[0]["team_id"]

        assert top_team != "rl_team_0", (
            f"RL bubble leader is ranked #1 with powerscore_adj="
            f"{ranked.iloc[0]['powerscore_adj']:.4f}. "
            f"This indicates the fix didn't resolve the inflation."
        )

    def test_off_norm_spread_not_compressed(self, scenario):
        """off_norm should have meaningful spread in the top 20, not a flat plateau."""
        teams, _, _, _ = scenario

        top20 = teams.nlargest(20, "powerscore_adj")
        off_norm_spread = top20["off_norm"].max() - top20["off_norm"].min()

        assert off_norm_spread > 0.05, (
            f"off_norm spread in top 20 is only {off_norm_spread:.4f}. "
            f"Should be > 0.05 for meaningful differentiation. "
            f"Values: {sorted(top20['off_norm'].tolist(), reverse=True)[:10]}"
        )

    def test_rl_sos_dampened_by_scf(self, scenario):
        """RL teams in a regional bubble should have lower avg SOS than national ECNL."""
        teams, rl_teams, ecnl_teams, _ = scenario

        rl_sos = teams[teams["team_id"].isin(rl_teams)]["sos_norm"].mean()
        ecnl_sos = teams[teams["team_id"].isin(ecnl_teams)]["sos_norm"].mean()

        # RL teams playing only in their bubble should have lower average SOS
        # than ECNL teams with national schedules
        assert rl_sos < ecnl_sos, (
            f"RL bubble avg SOS ({rl_sos:.4f}) >= ECNL avg SOS ({ecnl_sos:.4f}). "
            f"SCF should dampen the regional bubble."
        )

    def test_rl_scf_is_low(self, scenario):
        """RL teams should have low SCF (regional bubble detected)."""
        teams, rl_teams, _, _ = scenario

        rl_df = teams[teams["team_id"].isin(rl_teams)]
        if "scf" in rl_df.columns:
            avg_scf = rl_df["scf"].mean()
            assert avg_scf < 0.7, (
                f"RL bubble avg SCF ({avg_scf:.4f}) should be < 0.7 (isolated)."
            )

    def test_no_off_shrunk_mass_clipping(self, scenario):
        """Should not have a huge cluster of teams at the same off_shrunk value."""
        teams, _, _, _ = scenario

        # Count teams sharing the most common off_shrunk value
        off_shrunk_counts = teams["off_shrunk"].round(6).value_counts()
        max_tied = off_shrunk_counts.iloc[0]
        total = len(teams)

        # No more than 20% of teams should share the same off_shrunk
        assert max_tied / total < 0.20, (
            f"{max_tied}/{total} teams ({max_tied/total:.0%}) share the same "
            f"off_shrunk value ({off_shrunk_counts.index[0]:.6f}). "
            f"Clip threshold may be too lenient."
        )


# ===========================================================================
# Test 3: SOS hybrid normalization
# ===========================================================================

class TestSOSHybridNormalization:
    """Test that hybrid SOS norm preserves natural gaps vs pure percentile."""

    @pytest.fixture
    def scenario_with_hybrid(self):
        """Run scenario with SOS_NORM_HYBRID_ENABLED=True (current default)."""
        games_df, rl_teams, ecnl_teams, filler_teams, team_state_map = \
            _build_arkansas_rising_scenario()
        cfg = V53EConfig()  # SOS_NORM_HYBRID_ENABLED=True
        result = compute_rankings(games_df, cfg=cfg, team_state_map=team_state_map)
        return result["teams"]

    @pytest.fixture
    def scenario_without_hybrid(self):
        """Run scenario with SOS_NORM_HYBRID_ENABLED=False (old behavior)."""
        games_df, rl_teams, ecnl_teams, filler_teams, team_state_map = \
            _build_arkansas_rising_scenario()
        cfg = V53EConfig(SOS_NORM_HYBRID_ENABLED=False)
        result = compute_rankings(games_df, cfg=cfg, team_state_map=team_state_map)
        return result["teams"]

    def test_hybrid_sos_has_wider_spread(self, scenario_with_hybrid, scenario_without_hybrid):
        """Hybrid SOS should have more spread than pure percentile at the tails."""
        hybrid = scenario_with_hybrid
        pure = scenario_without_hybrid

        # Compare top 10 SOS spread
        hybrid_top10_spread = hybrid.nlargest(10, "sos_norm")["sos_norm"].std()
        pure_top10_spread = pure.nlargest(10, "sos_norm")["sos_norm"].std()

        # Hybrid should have equal or greater spread (sigmoid preserves gaps)
        # Allow some tolerance since both methods are valid
        assert hybrid_top10_spread >= pure_top10_spread * 0.8, (
            f"Hybrid top-10 SOS spread ({hybrid_top10_spread:.4f}) is much less "
            f"than pure percentile ({pure_top10_spread:.4f}). "
            f"Hybrid should preserve natural gaps."
        )


# ===========================================================================
# Test 4: Clip threshold comparison (3.0σ vs 3.5σ)
# ===========================================================================

class TestClipThreshold:
    """Compare clipping at 3.0σ vs 3.5σ."""

    def _count_clipped(self, teams_df):
        """Count teams at the off_shrunk ceiling."""
        off_shrunk = teams_df["off_shrunk"].round(8)
        counts = off_shrunk.value_counts()
        max_count = counts.iloc[0] if len(counts) > 0 else 0
        return max_count

    def test_tighter_clip_reduces_ceiling_cluster(self):
        """3.0σ clip should have fewer teams at the ceiling than 3.5σ."""
        games_df, _, _, _, team_state_map = _build_arkansas_rising_scenario()

        # Run with 3.0σ (current fix)
        cfg_30 = V53EConfig(TEAM_OUTLIER_GUARD_ZSCORE=3.0)
        result_30 = compute_rankings(games_df, cfg=cfg_30, team_state_map=team_state_map)

        # Run with 3.5σ (old)
        cfg_35 = V53EConfig(TEAM_OUTLIER_GUARD_ZSCORE=3.5)
        result_35 = compute_rankings(games_df, cfg=cfg_35, team_state_map=team_state_map)

        clipped_30 = self._count_clipped(result_30["teams"])
        clipped_35 = self._count_clipped(result_35["teams"])

        assert clipped_30 <= clipped_35, (
            f"Tighter clip (3.0σ) has MORE clipped teams ({clipped_30}) "
            f"than looser clip (3.5σ) ({clipped_35}). Something is wrong."
        )


# ===========================================================================
# Test 5: Weight rebalancing analysis (SOS 50% vs 60%)
# ===========================================================================

class TestWeightRebalancing:
    """
    Compare OFF=0.25/DEF=0.25/SOS=0.50 vs OFF=0.20/DEF=0.20/SOS=0.60.

    Tests whether reducing SOS weight to 50% helps prevent regional bubble
    teams from outranking national teams.
    """

    @pytest.fixture
    def scenario_sos60(self):
        """Current weights: OFF=0.20, DEF=0.20, SOS=0.60."""
        games_df, rl_teams, ecnl_teams, filler_teams, team_state_map = \
            _build_arkansas_rising_scenario()
        cfg = V53EConfig()  # defaults: OFF=0.20, DEF=0.20, SOS=0.60
        result = compute_rankings(games_df, cfg=cfg, team_state_map=team_state_map)
        return result["teams"], rl_teams, ecnl_teams

    @pytest.fixture
    def scenario_sos50(self):
        """Proposed weights: OFF=0.25, DEF=0.25, SOS=0.50."""
        games_df, rl_teams, ecnl_teams, filler_teams, team_state_map = \
            _build_arkansas_rising_scenario()
        cfg = V53EConfig(OFF_WEIGHT=0.25, DEF_WEIGHT=0.25, SOS_WEIGHT=0.50)
        result = compute_rankings(games_df, cfg=cfg, team_state_map=team_state_map)
        return result["teams"], rl_teams, ecnl_teams

    def test_sos50_rl_leader_rank(self, scenario_sos50):
        """With SOS=50%, RL leader should not be #1."""
        teams, rl_teams, ecnl_teams = scenario_sos50
        ranked = teams.sort_values("powerscore_adj", ascending=False).reset_index(drop=True)
        top_team = ranked.iloc[0]["team_id"]

        assert top_team != "rl_team_0", (
            f"RL leader still #1 even with SOS=50%. powerscore={ranked.iloc[0]['powerscore_adj']:.4f}"
        )

    def test_sos60_rl_leader_rank(self, scenario_sos60):
        """With SOS=60% + our fixes, RL leader should ALSO not be #1."""
        teams, rl_teams, ecnl_teams = scenario_sos60
        ranked = teams.sort_values("powerscore_adj", ascending=False).reset_index(drop=True)
        top_team = ranked.iloc[0]["team_id"]

        assert top_team != "rl_team_0", (
            f"RL leader is #1 with SOS=60% + fixes. powerscore={ranked.iloc[0]['powerscore_adj']:.4f}. "
            f"The off_norm/SOS fixes may be insufficient."
        )

    def test_compare_rl_rank_improvement(self, scenario_sos60, scenario_sos50):
        """Compare where RL leader ranks under both weight schemes."""
        teams60, rl_teams, ecnl_teams = scenario_sos60
        teams50, _, _ = scenario_sos50

        def get_rl_rank(teams_df):
            ranked = teams_df.sort_values("powerscore_adj", ascending=False).reset_index(drop=True)
            rl_rows = ranked[ranked["team_id"] == "rl_team_0"]
            if rl_rows.empty:
                return len(ranked)  # not found = last
            return rl_rows.index[0] + 1  # 1-based rank

        rank_60 = get_rl_rank(teams60)
        rank_50 = get_rl_rank(teams50)

        # Report for diagnostic purposes (not a hard assertion since both should work)
        print(f"\n--- Weight Rebalancing Analysis ---")
        print(f"RL leader rank with SOS=60% (current + fixes): #{rank_60}")
        print(f"RL leader rank with SOS=50% (proposed):        #{rank_50}")
        print(f"Improvement from weight change: {rank_60 - rank_50:+d} positions")

        # Both should have RL leader below top 3 at minimum
        assert rank_60 > 3, f"SOS=60%: RL leader at #{rank_60}, should be > 3"
        assert rank_50 > 3, f"SOS=50%: RL leader at #{rank_50}, should be > 3"

    def test_sos60_ecnl_dominance_preserved(self, scenario_sos60):
        """Top 10 should be dominated by ECNL teams, not RL or NPL."""
        teams, rl_teams, ecnl_teams = scenario_sos60
        top10 = teams.nlargest(10, "powerscore_adj")
        ecnl_in_top10 = top10["team_id"].isin(ecnl_teams).sum()

        assert ecnl_in_top10 >= 7, (
            f"Only {ecnl_in_top10}/10 ECNL teams in top 10 (SOS=60%). "
            f"Top 10: {top10[['team_id', 'powerscore_adj']].to_dict('records')}"
        )

    def test_sos50_ecnl_dominance_preserved(self, scenario_sos50):
        """Top 10 should be dominated by ECNL teams, not RL or NPL."""
        teams, rl_teams, ecnl_teams = scenario_sos50
        top10 = teams.nlargest(10, "powerscore_adj")
        ecnl_in_top10 = top10["team_id"].isin(ecnl_teams).sum()

        assert ecnl_in_top10 >= 7, (
            f"Only {ecnl_in_top10}/10 ECNL teams in top 10 (SOS=50%). "
            f"Top 10: {top10[['team_id', 'powerscore_adj']].to_dict('records')}"
        )

    def test_weight_rebalancing_variance_decomposition(self, scenario_sos60, scenario_sos50):
        """
        Analyze how much each component (OFF, DEF, SOS) contributes to
        final powerscore variance under both weight schemes.
        """
        for label, (teams, _, _), weights in [
            ("SOS=60%", scenario_sos60, (0.20, 0.20, 0.60)),
            ("SOS=50%", scenario_sos50, (0.25, 0.25, 0.50)),
        ]:
            off_w, def_w, sos_w = weights
            off_contrib = (off_w * teams["off_norm"]).var()
            def_contrib = (def_w * teams["def_norm"]).var()
            sos_contrib = (sos_w * teams["sos_norm"]).var()
            total = off_contrib + def_contrib + sos_contrib

            if total > 0:
                off_pct = off_contrib / total * 100
                def_pct = def_contrib / total * 100
                sos_pct = sos_contrib / total * 100
            else:
                off_pct = def_pct = sos_pct = 33.3

            print(f"\n--- Variance Decomposition ({label}) ---")
            print(f"  OFF: {off_pct:.1f}%  DEF: {def_pct:.1f}%  SOS: {sos_pct:.1f}%")

            # SOS should not account for more than 90% of variance
            assert sos_pct < 90, (
                f"SOS accounts for {sos_pct:.1f}% of powerscore variance ({label}). "
                f"It's over-dominating the ranking."
            )


# ===========================================================================
# Test 6: PowerScore bounds and consistency
# ===========================================================================

class TestPowerScoreBounds:
    """Ensure the fix doesn't break basic PowerScore invariants."""

    @pytest.fixture
    def teams(self):
        games_df, _, _, _, team_state_map = _build_arkansas_rising_scenario()
        cfg = V53EConfig()
        result = compute_rankings(games_df, cfg=cfg, team_state_map=team_state_map)
        return result["teams"]

    def test_powerscore_in_bounds(self, teams):
        """All PowerScores should be in [0, 1]."""
        assert teams["powerscore_adj"].min() >= 0.0
        assert teams["powerscore_adj"].max() <= 1.0

    def test_off_norm_in_bounds(self, teams):
        """All off_norm should be in [0, 1]."""
        assert teams["off_norm"].min() >= 0.0
        assert teams["off_norm"].max() <= 1.0

    def test_def_norm_in_bounds(self, teams):
        """All def_norm should be in [0, 1]."""
        assert teams["def_norm"].min() >= 0.0
        assert teams["def_norm"].max() <= 1.0

    def test_sos_norm_in_bounds(self, teams):
        """All sos_norm should be in [0, 1]."""
        assert teams["sos_norm"].min() >= 0.0
        assert teams["sos_norm"].max() <= 1.0

    def test_no_nan_in_scores(self, teams):
        """No NaN values in critical score columns."""
        for col in ["powerscore_adj", "off_norm", "def_norm", "sos_norm"]:
            assert not teams[col].isna().any(), f"NaN found in {col}"
