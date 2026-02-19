"""
Tests for PowerScore and SOS accuracy.

Covers:
- T1: Power-SOS co-calculation loop (SCF preservation)
- T2: Realistic fixtures with 8+ games per team (Active status)
- T3: Rank/score ordering consistency
- Self-play filtering
- Adaptive K in SOS weights
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.etl.v53e import (
    V53EConfig,
    compute_rankings,
    compute_schedule_connectivity,
    apply_scf_to_sos,
)


# ---------------------------------------------------------------------------
# Helpers: Build realistic game fixtures
# ---------------------------------------------------------------------------

def _make_game_row(game_id, date, team_id, opp_id, gf, ga,
                   age="14", gender="male"):
    """Create a single perspective row in v53e format."""
    return {
        "game_id": game_id,
        "date": pd.Timestamp(date),
        "team_id": team_id,
        "opp_id": opp_id,
        "age": age,
        "gender": gender,
        "opp_age": age,
        "opp_gender": gender,
        "gf": gf,
        "ga": ga,
    }


def _make_game_pair(game_id, date, home, away, home_score, away_score,
                    age="14", gender="male"):
    """Create both perspective rows for a single game."""
    return [
        _make_game_row(game_id, date, home, away, home_score, away_score,
                       age, gender),
        _make_game_row(game_id, date, away, home, away_score, home_score,
                       age, gender),
    ]


def _build_realistic_cohort(num_teams=10, games_per_team=12, age="14",
                            gender="male", seed=42):
    """
    Build a realistic cohort with enough games for Active status.

    Creates round-robin-style games where each team plays ~games_per_team
    games against random opponents within the cohort.
    """
    rng = np.random.RandomState(seed)
    team_ids = [f"team_{i:03d}" for i in range(num_teams)]
    rows = []
    game_counter = 0
    base_date = datetime(2025, 6, 1)

    # Create enough games so each team has >= games_per_team
    games_needed = (num_teams * games_per_team) // 2 + num_teams
    for _ in range(games_needed):
        # Pick two different random teams
        home_idx, away_idx = rng.choice(num_teams, size=2, replace=False)
        home = team_ids[home_idx]
        away = team_ids[away_idx]

        # Random scores (realistic: 0-5 goals)
        home_score = int(rng.poisson(1.5))
        away_score = int(rng.poisson(1.5))

        game_date = base_date - timedelta(days=int(rng.randint(1, 300)))
        game_id = f"g_{game_counter:04d}"
        game_counter += 1

        rows.extend(_make_game_pair(
            game_id, game_date, home, away, home_score, away_score,
            age=age, gender=gender
        ))

    return pd.DataFrame(rows), team_ids


def _build_bubble_vs_national(age="14", gender="male"):
    """
    Build a scenario with:
    - 5 isolated bubble teams (all from Idaho, only play each other)
    - 5 national teams (from different states, play each other)
    - Each team has 10+ games for Active status.
    """
    rows = []
    game_counter = 0
    base_date = datetime(2025, 6, 1)

    bubble_teams = [f"bubble_{i}" for i in range(5)]
    national_teams = [f"national_{i}" for i in range(5)]

    # Bubble games: round-robin × 3 (each pair plays 3 times)
    for rep in range(3):
        for i in range(5):
            for j in range(i + 1, 5):
                game_date = base_date - timedelta(days=10 + rep * 30 + i + j)
                gid = f"bg_{game_counter:04d}"
                game_counter += 1
                # Bubble teams are evenly matched
                rows.extend(_make_game_pair(
                    gid, game_date, bubble_teams[i], bubble_teams[j],
                    2, 1, age=age, gender=gender
                ))

    # National games: round-robin × 3
    for rep in range(3):
        for i in range(5):
            for j in range(i + 1, 5):
                game_date = base_date - timedelta(days=10 + rep * 30 + i + j)
                gid = f"ng_{game_counter:04d}"
                game_counter += 1
                # National teams are evenly matched
                rows.extend(_make_game_pair(
                    gid, game_date, national_teams[i], national_teams[j],
                    2, 1, age=age, gender=gender
                ))

    team_state_map = {}
    for t in bubble_teams:
        team_state_map[t] = "ID"
    team_state_map["national_0"] = "CA"
    team_state_map["national_1"] = "TX"
    team_state_map["national_2"] = "FL"
    team_state_map["national_3"] = "NY"
    team_state_map["national_4"] = "IL"

    return pd.DataFrame(rows), bubble_teams, national_teams, team_state_map


# ===========================================================================
# T1: Power-SOS Co-Calculation Loop — SCF Preservation
# ===========================================================================

class TestPowerSOSLoopSCF:
    """Tests that SCF is preserved through Power-SOS iterations."""

    def test_scf_effect_preserved_after_power_sos_iterations(self):
        """
        The core bug: SCF dampening is applied before the Power-SOS loop,
        but the loop recalculates SOS without reapplying SCF, diluting it
        to ~3% after 3 iterations.

        This test verifies that:
        1. Bubble teams get lower SCF than national teams
        2. SCF creates a meaningful SOS gap between the groups
        3. The gap is preserved through Power-SOS iterations (not diluted)
        """
        games_df, bubble_teams, national_teams, team_state_map = \
            _build_bubble_vs_national()

        cfg = V53EConfig(
            SOS_POWER_ITERATIONS=3,
            SOS_POWER_DAMPING=0.7,
            SCF_ENABLED=True,
            PAGERANK_DAMPENING_ENABLED=True,
        )

        result = compute_rankings(
            games_df=games_df,
            cfg=cfg,
            team_state_map=team_state_map,
            today=pd.Timestamp("2025-07-01"),
        )
        teams = result["teams"]

        # 1. Bubble teams should have LOWER SCF (isolated in one state)
        bubble_scf = teams[teams["team_id"].isin(bubble_teams)]["scf"].mean()
        national_scf = teams[teams["team_id"].isin(national_teams)]["scf"].mean()
        assert bubble_scf < national_scf, (
            f"Bubble teams (avg SCF={bubble_scf:.3f}) should have lower SCF "
            f"than national teams (avg SCF={national_scf:.3f})"
        )

        # 2. SCF should create a meaningful SOS gap between the groups
        # Both groups play structurally identical schedules, so without SCF
        # their SOS would be similar. SCF pulls bubble teams' SOS toward neutral.
        bubble_sos = teams[teams["team_id"].isin(bubble_teams)]["sos"].mean()
        national_sos = teams[teams["team_id"].isin(national_teams)]["sos"].mean()
        sos_gap = abs(bubble_sos - national_sos)
        assert sos_gap > 0.05, (
            f"SCF should create a meaningful SOS gap: "
            f"bubble_sos={bubble_sos:.4f}, national_sos={national_sos:.4f}, "
            f"gap={sos_gap:.4f} (expected > 0.05)"
        )

    def test_scf_columns_present_after_power_sos(self):
        """Verify SCF metadata columns survive the Power-SOS loop."""
        games_df, bubble_teams, national_teams, team_state_map = \
            _build_bubble_vs_national()

        cfg = V53EConfig(SOS_POWER_ITERATIONS=3)
        result = compute_rankings(
            games_df=games_df,
            cfg=cfg,
            team_state_map=team_state_map,
            today=pd.Timestamp("2025-07-01"),
        )
        teams = result["teams"]

        for col in ["scf", "bridge_games", "is_isolated"]:
            assert col in teams.columns, f"Missing SCF column: {col}"

    def test_power_sos_convergence(self):
        """Power-SOS loop should converge (SOS stabilizes)."""
        games_df, team_ids = _build_realistic_cohort(num_teams=15,
                                                     games_per_team=14)

        # Run with 0 iterations (baseline)
        cfg_0 = V53EConfig(SOS_POWER_ITERATIONS=0)
        result_0 = compute_rankings(games_df=games_df, cfg=cfg_0,
                                    today=pd.Timestamp("2025-07-01"))

        # Run with 3 iterations
        cfg_3 = V53EConfig(SOS_POWER_ITERATIONS=3)
        result_3 = compute_rankings(games_df=games_df, cfg=cfg_3,
                                    today=pd.Timestamp("2025-07-01"))

        # Run with 6 iterations (should converge to similar result as 3)
        cfg_6 = V53EConfig(SOS_POWER_ITERATIONS=6)
        result_6 = compute_rankings(games_df=games_df, cfg=cfg_6,
                                    today=pd.Timestamp("2025-07-01"))

        teams_3 = result_3["teams"].set_index("team_id")
        teams_6 = result_6["teams"].set_index("team_id")

        # SOS should be close between 3 and 6 iterations (converged)
        common_ids = teams_3.index.intersection(teams_6.index)
        if len(common_ids) > 0:
            sos_diff = (teams_3.loc[common_ids, "sos"]
                        - teams_6.loc[common_ids, "sos"]).abs().mean()
            assert sos_diff < 0.02, (
                f"Power-SOS should converge: mean SOS diff between "
                f"3 and 6 iterations = {sos_diff:.4f} (expected < 0.02)"
            )


# ===========================================================================
# T2: Realistic Fixtures — Active Teams
# ===========================================================================

class TestRealisticCohort:
    """Tests using realistic fixtures with enough games for Active status."""

    @pytest.fixture
    def realistic_cohort(self):
        games_df, team_ids = _build_realistic_cohort(
            num_teams=10, games_per_team=12
        )
        cfg = V53EConfig()
        result = compute_rankings(
            games_df=games_df, cfg=cfg,
            today=pd.Timestamp("2025-07-01")
        )
        return result, team_ids, cfg

    def test_active_teams_exist(self, realistic_cohort):
        """With 12+ games per team, most should be Active."""
        result, team_ids, cfg = realistic_cohort
        teams = result["teams"]
        active_count = (teams["status"] == "Active").sum()
        assert active_count >= 5, (
            f"Expected at least 5 Active teams with 12 games each, "
            f"got {active_count}. Status distribution: "
            f"{teams['status'].value_counts().to_dict()}"
        )

    def test_active_teams_have_ranks(self, realistic_cohort):
        """Active teams should have non-null ranks."""
        result, team_ids, cfg = realistic_cohort
        teams = result["teams"]
        active_teams = teams[teams["status"] == "Active"]
        if not active_teams.empty:
            null_ranks = active_teams["rank_in_cohort"].isna().sum()
            assert null_ranks == 0, (
                f"{null_ranks} Active teams have null rank_in_cohort"
            )

    def test_powerscore_in_valid_range(self, realistic_cohort):
        """All PowerScore values should be in [0, 1]."""
        result, team_ids, cfg = realistic_cohort
        teams = result["teams"]
        for col in ["powerscore_core", "powerscore_adj"]:
            if col in teams.columns:
                vals = teams[col].dropna()
                assert (vals >= 0.0).all(), f"{col} has values < 0"
                assert (vals <= 1.0).all(), f"{col} has values > 1"

    def test_sos_norm_full_range_within_cohort(self, realistic_cohort):
        """sos_norm should span close to [0, 1] within a cohort."""
        result, team_ids, cfg = realistic_cohort
        teams = result["teams"]
        sos_norm = teams["sos_norm"].dropna()
        if len(sos_norm) >= 5:
            assert sos_norm.min() < 0.2, (
                f"sos_norm min={sos_norm.min():.3f}, expected < 0.2"
            )
            assert sos_norm.max() > 0.8, (
                f"sos_norm max={sos_norm.max():.3f}, expected > 0.8"
            )

    def test_powerscore_formula_consistency(self, realistic_cohort):
        """Verify PowerScore matches the documented formula."""
        result, team_ids, cfg = realistic_cohort
        teams = result["teams"]

        MAX_PS = 1.0 + 0.5 * cfg.PERF_BLEND_WEIGHT

        for _, row in teams.head(5).iterrows():
            expected = (
                cfg.OFF_WEIGHT * row["off_norm"]
                + cfg.DEF_WEIGHT * row["def_norm"]
                + cfg.SOS_WEIGHT * row["sos_norm"]
                + row["perf_centered"] * cfg.PERF_BLEND_WEIGHT
            ) / MAX_PS

            actual = row["powerscore_core"]
            assert abs(expected - actual) < 0.001, (
                f"PowerScore formula mismatch for {row['team_id']}: "
                f"expected={expected:.4f}, actual={actual:.4f}"
            )


# ===========================================================================
# T3: Rank/Score Ordering Consistency
# ===========================================================================

class TestRankScoreConsistency:
    """Tests that ranks agree with score ordering."""

    def test_rank_matches_powerscore_adj_order(self):
        """rank_in_cohort should follow powerscore_adj descending."""
        games_df, team_ids = _build_realistic_cohort(
            num_teams=12, games_per_team=12
        )
        cfg = V53EConfig()
        result = compute_rankings(
            games_df=games_df, cfg=cfg,
            today=pd.Timestamp("2025-07-01")
        )
        teams = result["teams"]

        # Check per cohort
        for (age, gender), cohort in teams.groupby(["age", "gender"]):
            active = cohort[cohort["status"] == "Active"].copy()
            if len(active) < 3:
                continue

            # Sort by rank
            active = active.sort_values("rank_in_cohort")
            ranks = active["rank_in_cohort"].tolist()
            scores = active["powerscore_adj"].tolist()

            # Ranks should be 1, 2, 3, ... (no gaps)
            expected_ranks = list(range(1, len(ranks) + 1))
            assert ranks == expected_ranks, (
                f"Ranks should be sequential: got {ranks[:10]}"
            )

            # Scores should be non-increasing (higher rank = higher score)
            for i in range(len(scores) - 1):
                assert scores[i] >= scores[i + 1] - 0.0001, (
                    f"Score ordering violated at rank {i+1}: "
                    f"score={scores[i]:.4f} < next={scores[i+1]:.4f}"
                )

    def test_sos_tiebreaker_breaks_ties(self):
        """Teams with same PowerScore should be differentiated by SOS."""
        games_df, team_ids = _build_realistic_cohort(
            num_teams=12, games_per_team=12
        )
        cfg = V53EConfig()
        result = compute_rankings(
            games_df=games_df, cfg=cfg,
            today=pd.Timestamp("2025-07-01")
        )
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]

        if not active.empty:
            # Every Active team should have a unique rank
            ranks = active["rank_in_cohort"].dropna()
            assert ranks.is_unique, (
                f"Duplicate ranks found: "
                f"{ranks[ranks.duplicated()].tolist()}"
            )


# ===========================================================================
# Self-Play Detection
# ===========================================================================

class TestSelfPlayFiltering:
    """Tests that self-play games (team vs itself) are handled."""

    def test_self_play_game_detection(self):
        """A game where team_id == opp_id should not corrupt SOS."""
        rows = []
        base_date = datetime(2025, 6, 1)

        # Normal games for team_a (10 games)
        for i in range(10):
            gid = f"normal_{i}"
            opp = f"opp_{i}"
            game_date = base_date - timedelta(days=i * 10)
            rows.extend(_make_game_pair(gid, game_date, "team_a", opp, 2, 1))
            # Give opponents some games too
            rows.extend(_make_game_pair(
                f"opp_game_{i}", game_date - timedelta(days=1),
                opp, f"opp_other_{i}", 1, 1
            ))

        # Self-play game (data error)
        rows.extend([
            _make_game_row("self_g", base_date, "team_a", "team_a", 3, 1),
            _make_game_row("self_g", base_date, "team_a", "team_a", 1, 3),
        ])

        games_df = pd.DataFrame(rows)
        cfg = V53EConfig()
        result = compute_rankings(
            games_df=games_df, cfg=cfg,
            today=pd.Timestamp("2025-07-01")
        )

        teams = result["teams"]
        team_a = teams[teams["team_id"] == "team_a"]

        if not team_a.empty:
            sos = team_a["sos"].values[0]
            # SOS should still be reasonable (0-1) even with self-play
            assert 0.0 <= sos <= 1.0, f"SOS out of range: {sos}"


# ===========================================================================
# Adaptive K in SOS Weights
# ===========================================================================

class TestAdaptiveKInSOS:
    """Tests for adaptive K behavior in SOS weighting."""

    def test_adaptive_k_affects_sos_weights(self):
        """Verify that adaptive K changes SOS weights based on strength gap."""
        games_df, team_ids = _build_realistic_cohort(
            num_teams=8, games_per_team=10
        )

        # With adaptive K (default)
        cfg_with_k = V53EConfig()
        result_with = compute_rankings(
            games_df=games_df, cfg=cfg_with_k,
            today=pd.Timestamp("2025-07-01")
        )

        # Without adaptive K (set alpha to make k_adapt = constant)
        cfg_without_k = V53EConfig(ADAPTIVE_K_ALPHA=0.5, ADAPTIVE_K_BETA=0.0)
        result_without = compute_rankings(
            games_df=games_df, cfg=cfg_without_k,
            today=pd.Timestamp("2025-07-01")
        )

        teams_with = result_with["teams"].set_index("team_id")
        teams_without = result_without["teams"].set_index("team_id")

        common = teams_with.index.intersection(teams_without.index)
        if len(common) > 0:
            sos_diff = (teams_with.loc[common, "sos"]
                        - teams_without.loc[common, "sos"]).abs()
            # SOS should be different when adaptive K is active vs constant
            # (unless all teams have identical strength, which is unlikely)
            assert sos_diff.max() > 0.001, (
                "Adaptive K should affect SOS values, but differences are "
                f"negligible: max_diff={sos_diff.max():.6f}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
