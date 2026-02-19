"""
Tests for PowerScore and SOS accuracy.

Covers:
- T2: Realistic fixtures with 8+ games per team (Active status)
- T3: Rank/score ordering consistency
- Self-play filtering
- Adaptive K in SOS weights
- T6: SOS 365-day window (wider sample dilutes scheduling clusters)
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


# ===========================================================================
# T2: Realistic Fixtures -- Active Teams
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


# ===========================================================================
# T6: SOS 365-Day Window -- Wider sample dilutes scheduling clusters
# ===========================================================================

class TestSOS365DayWindow:
    """
    Verify that SOS uses the full 365-day game window (not the 30-game
    OFF/DEF window).  A short cluster of weak opponents should have less
    impact when diluted by 365 days of games.
    """

    @staticmethod
    def _build_dilution_scenario(age="14", gender="male"):
        """
        Build a scenario where "deep_team" plays 40 games against 20
        UNIQUE opponents (2 games each).  The key: 10 of those opponents
        are ONLY encountered in older games (rank_recency 21-40).

        With a 30-game OFF/DEF cap, only ~15 opponents appear in the
        recent 30 games.  With the 365-day SOS window, all 20 opponents
        contribute to SOS -- including the "old-only" opponents.

        All opponents have 10+ games for ranking.
        """
        rows = []
        gc = 0
        base = datetime(2025, 7, 1)

        # 20 unique opponents that deep_team plays
        recent_opps = [f"opp_recent_{i}" for i in range(10)]  # in games 1-20
        old_opps = [f"opp_old_{i}" for i in range(10)]        # in games 21-40
        all_opps = recent_opps + old_opps

        # --- Opponent inter-play so they all get ranked (10+ games each) ---
        # Round-robin subset: each opponent plays 5-6 other opponents
        for i, opp in enumerate(all_opps):
            for j in range(5):
                partner = all_opps[(i + j + 1) % len(all_opps)]
                d = base - timedelta(days=30 + i * 7 + j * 3)
                gid = f"op_{gc:04d}"; gc += 1
                rows.extend(_make_game_pair(
                    gid, d, opp, partner, 2, 1,
                    age=age, gender=gender,
                ))

        # --- deep_team: 2 games each against 10 recent opponents ---
        for k, opp in enumerate(recent_opps):
            for rep in range(2):
                d = base - timedelta(days=5 + k * 2 + rep)  # days 5-24
                gid = f"dr_{gc:04d}"; gc += 1
                rows.extend(_make_game_pair(
                    gid, d, "deep_team", opp, 3, 1,
                    age=age, gender=gender,
                ))

        # --- deep_team: 2 games each against 10 OLD-ONLY opponents ---
        # These are at rank_recency 21-40, beyond the 30-game OFF/DEF cap
        for k, opp in enumerate(old_opps):
            for rep in range(2):
                d = base - timedelta(days=100 + k * 8 + rep)  # days 100-180
                gid = f"do_{gc:04d}"; gc += 1
                rows.extend(_make_game_pair(
                    gid, d, "deep_team", opp, 2, 1,
                    age=age, gender=gender,
                ))

        return pd.DataFrame(rows)

    def test_sos_includes_old_only_opponents(self):
        """
        deep_team plays 10 opponents only in older games (rank_recency
        21-40).  The 365-day SOS window should include these opponents.
        With a 30-game cap, they would be excluded entirely.
        """
        games = self._build_dilution_scenario()
        cfg = V53EConfig(
            SOS_POWER_ITERATIONS=0,
            SCF_ENABLED=False,
            PAGERANK_DAMPENING_ENABLED=False,
        )

        result = compute_rankings(
            games_df=games,
            cfg=cfg,
            today=pd.Timestamp("2025-07-01"),
        )

        gu = result["games_used"]
        deep_sos = gu[gu["team_id"] == "deep_team"]
        assert len(deep_sos) > 0, "deep_team must appear in SOS games_used"

        # The "opp_old_*" opponents should appear in SOS games_used,
        # proving the 365-day window includes opponents beyond game 30.
        old_opponent_games = deep_sos[
            deep_sos["opp_id"].str.startswith("opp_old_")
        ]
        assert len(old_opponent_games) > 0, (
            "SOS should include old-only opponents (opp_old_*) from beyond "
            f"the 30-game cap. deep_team SOS games: {len(deep_sos)}, "
            f"unique opps: {deep_sos['opp_id'].unique().tolist()}"
        )

        # Verify these opponents have rank_recency > 30 (they're old games)
        if "rank_recency" in old_opponent_games.columns:
            max_rank = old_opponent_games["rank_recency"].max()
            assert max_rank > cfg.MAX_GAMES_FOR_RANK, (
                f"Old-only opponents should have rank_recency > "
                f"{cfg.MAX_GAMES_FOR_RANK}, got max={max_rank}"
            )

    def test_sos_game_count_exceeds_30_game_cap(self):
        """
        deep_team has 40 total games (20 unique opponents x 2 each).
        With SOS_REPEAT_CAP=2, all 40 games pass the cap.  The 365-day
        SOS window should include all of them, exceeding the 30-game
        OFF/DEF limit.
        """
        games = self._build_dilution_scenario()
        cfg = V53EConfig(
            SOS_POWER_ITERATIONS=0,
            SCF_ENABLED=False,
            PAGERANK_DAMPENING_ENABLED=False,
        )

        result = compute_rankings(
            games_df=games,
            cfg=cfg,
            today=pd.Timestamp("2025-07-01"),
        )

        gu = result["games_used"]
        deep_sos = gu[gu["team_id"] == "deep_team"]

        # deep_team should have more SOS games than the 30-game OFF/DEF cap
        assert len(deep_sos) > cfg.MAX_GAMES_FOR_RANK, (
            f"SOS should include >{cfg.MAX_GAMES_FOR_RANK} games for "
            f"deep_team (365-day window), got {len(deep_sos)}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
