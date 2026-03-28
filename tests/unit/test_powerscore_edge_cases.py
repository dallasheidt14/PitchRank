"""
PowerScore edge case tests.

Covers:
- NaN / Infinity handling in inputs
- Bounds clamping [0.0, 1.0]
- Extreme goal differentials
- Single-team cohorts
- All-identical scores
- Zero games after window filter
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.etl.v53e import V53EConfig, compute_rankings, _provisional_multiplier


def _make_game_pair(gid, date, home, away, hs, as_, age="14", gender="male"):
    return [
        {
            "game_id": gid,
            "date": pd.Timestamp(date),
            "team_id": home,
            "opp_id": away,
            "age": age,
            "gender": gender,
            "opp_age": age,
            "opp_gender": gender,
            "gf": hs,
            "ga": as_,
        },
        {
            "game_id": gid,
            "date": pd.Timestamp(date),
            "team_id": away,
            "opp_id": home,
            "age": age,
            "gender": gender,
            "opp_age": age,
            "opp_gender": gender,
            "gf": as_,
            "ga": hs,
        },
    ]


def _round_robin(team_ids, base_date, score_fn=None, n_rounds=2):
    """Build round-robin games. score_fn(home_idx, away_idx) -> (hs, as_)."""
    rows = []
    gc = 0
    if score_fn is None:
        score_fn = lambda h, a: (2, 1)
    for rnd in range(n_rounds):
        for i, h in enumerate(team_ids):
            for j, a in enumerate(team_ids):
                if i >= j:
                    continue
                hs, as_ = score_fn(i, j)
                d = base_date - timedelta(days=gc * 3 + rnd)
                rows.extend(_make_game_pair(f"g_{gc:04d}", d, h, a, hs, as_))
                gc += 1
    return pd.DataFrame(rows)


# ===========================================================================
# Bounds and clamping
# ===========================================================================


class TestPowerScoreBounds:
    """PowerScore must always be in [0.0, 1.0]."""

    def test_dominant_team_does_not_exceed_one(self):
        """A team winning every game by a large margin should still be ≤ 1.0."""
        team_ids = [f"t{i}" for i in range(12)]
        base = datetime(2025, 6, 1)
        # t0 wins every game 6-0, others play close
        rows = []
        gc = 0
        for i in range(1, len(team_ids)):
            for rep in range(3):
                d = base - timedelta(days=gc)
                rows.extend(_make_game_pair(f"g_{gc:04d}", d, team_ids[0], team_ids[i], 6, 0))
                gc += 1
        # Others play each other
        for i in range(1, len(team_ids)):
            for j in range(i + 1, min(i + 4, len(team_ids))):
                for rep in range(2):
                    d = base - timedelta(days=gc)
                    rows.extend(_make_game_pair(f"g_{gc:04d}", d, team_ids[i], team_ids[j], 1, 1))
                    gc += 1

        games = pd.DataFrame(rows)
        cfg = V53EConfig()
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]

        assert (teams["powerscore_core"] <= 1.0).all(), "powerscore_core > 1.0"
        assert (teams["powerscore_adj"] <= 1.0).all(), "powerscore_adj > 1.0"
        assert (teams["powerscore_core"] >= 0.0).all(), "powerscore_core < 0.0"
        assert (teams["powerscore_adj"] >= 0.0).all(), "powerscore_adj < 0.0"

    def test_worst_team_does_not_go_below_zero(self):
        """A team losing every game 0-6 should still be ≥ 0.0."""
        team_ids = [f"t{i}" for i in range(12)]
        base = datetime(2025, 6, 1)
        rows = []
        gc = 0
        # t0 loses every game
        for i in range(1, len(team_ids)):
            for rep in range(3):
                d = base - timedelta(days=gc)
                rows.extend(_make_game_pair(f"g_{gc:04d}", d, team_ids[0], team_ids[i], 0, 6))
                gc += 1
        # Others play each other
        for i in range(1, len(team_ids)):
            for j in range(i + 1, min(i + 4, len(team_ids))):
                for rep in range(2):
                    d = base - timedelta(days=gc)
                    rows.extend(_make_game_pair(f"g_{gc:04d}", d, team_ids[i], team_ids[j], 2, 1))
                    gc += 1

        games = pd.DataFrame(rows)
        cfg = V53EConfig()
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]

        assert (teams["powerscore_core"] >= 0.0).all()
        assert (teams["powerscore_adj"] >= 0.0).all()


# ===========================================================================
# Goal differential capping
# ===========================================================================


class TestGoalDiffCap:
    """Verify GOAL_DIFF_CAP limits extreme scores."""

    def test_blowout_capped(self):
        """A 10-0 game should be treated as 6-0 (GOAL_DIFF_CAP=6)."""
        team_ids = [f"t{i}" for i in range(10)]
        base = datetime(2025, 6, 1)
        rows = []
        gc = 0

        # t0 vs t1: 10-0 blowout
        for rep in range(5):
            d = base - timedelta(days=rep * 5)
            rows.extend(_make_game_pair(f"g_{gc:04d}", d, "t0", "t1", 10, 0))
            gc += 1

        # t0 vs t2: 6-0 (exact cap)
        for rep in range(5):
            d = base - timedelta(days=rep * 5 + 1)
            rows.extend(_make_game_pair(f"g_{gc:04d}", d, "t0", "t2", 6, 0))
            gc += 1

        # Fill out remaining games
        for i in range(len(team_ids)):
            for j in range(i + 1, min(i + 4, len(team_ids))):
                for rep in range(2):
                    d = base - timedelta(days=gc)
                    rows.extend(_make_game_pair(f"g_{gc:04d}", d, team_ids[i], team_ids[j], 2, 1))
                    gc += 1

        games = pd.DataFrame(rows)
        cfg = V53EConfig()
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))

        # The games_used should have gf capped at 6
        gu = result["games_used"]
        assert (gu["gf"] <= cfg.GOAL_DIFF_CAP).all(), "gf not capped in games_used"
        assert (gu["ga"] <= cfg.GOAL_DIFF_CAP).all(), "ga not capped in games_used"


# ===========================================================================
# Single-team and degenerate cohorts
# ===========================================================================


class TestDegenerateCohorts:
    """Handle edge cases with very few teams."""

    def test_single_team_cohort(self):
        """A single team (with a cross-cohort opponent) should not crash."""
        rows = []
        gc = 0
        base = datetime(2025, 6, 1)
        # One team in age 14, playing opponents in age 15
        for i in range(10):
            d = base - timedelta(days=i * 5)
            rows.append(
                {
                    "game_id": f"g_{gc:04d}",
                    "date": pd.Timestamp(d),
                    "team_id": "solo_14",
                    "opp_id": f"opp15_{i}",
                    "age": "14",
                    "gender": "male",
                    "opp_age": "15",
                    "opp_gender": "male",
                    "gf": 2,
                    "ga": 1,
                }
            )
            rows.append(
                {
                    "game_id": f"g_{gc:04d}",
                    "date": pd.Timestamp(d),
                    "team_id": f"opp15_{i}",
                    "opp_id": "solo_14",
                    "age": "15",
                    "gender": "male",
                    "opp_age": "14",
                    "opp_gender": "male",
                    "gf": 1,
                    "ga": 2,
                }
            )
            gc += 1

        # Give opp15 teams games against each other
        opp15 = [f"opp15_{i}" for i in range(10)]
        for i in range(len(opp15)):
            for j in range(i + 1, min(i + 3, len(opp15))):
                d = base - timedelta(days=gc)
                rows.extend(_make_game_pair(f"g_{gc:04d}", d, opp15[i], opp15[j], 1, 1, age="15"))
                gc += 1

        games = pd.DataFrame(rows)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False)
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]

        solo = teams[teams["team_id"] == "solo_14"]
        assert len(solo) == 1
        ps = solo["powerscore_adj"].values[0]
        assert 0.0 <= ps <= 1.0, f"Single-team PowerScore out of range: {ps}"
        # SOS norm for single-team cohort should be 0.5
        assert abs(solo["sos_norm"].values[0] - 0.5) < 0.01

    def test_all_identical_scores(self):
        """All games ending 1-1 should produce nearly identical PowerScores.

        BUG CAUGHT: Floating-point noise in raw SOS (diffs ~1e-17) was being
        amplified by percentile normalization into sos_norm spread of 0.11-0.78,
        creating a 0.40 PowerScore gap from pure machine-epsilon noise.
        Fix: round raw SOS to 10 decimal places before percentile ranking.
        """
        team_ids = [f"t{i}" for i in range(10)]
        base = datetime(2025, 6, 1)
        games = _round_robin(team_ids, base, lambda h, a: (1, 1), n_rounds=3)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False)
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]

        # All PowerScores should be valid
        assert (teams["powerscore_adj"] >= 0.0).all()
        assert (teams["powerscore_adj"] <= 1.0).all()

        # With identical results, raw SOS should be identical (same opponents)
        sos_raw_spread = teams["sos"].max() - teams["sos"].min()
        assert sos_raw_spread < 0.001, (
            f"Raw SOS should be near-identical for equal-result teams, got spread={sos_raw_spread:.6f}"
        )

        # sos_norm should not amplify machine-epsilon noise.
        # All teams should get sos_norm = 0.5 (tied, using rank method='average')
        sos_norm_spread = teams["sos_norm"].max() - teams["sos_norm"].min()
        assert sos_norm_spread < 0.05, (
            f"sos_norm amplified noise: spread={sos_norm_spread:.4f} "
            f"(should be ~0 for identical SOS teams). "
            f"sos_norm values: {sorted(teams['sos_norm'].unique())}"
        )

        # Therefore PowerScore spread should be minimal
        ps_range = teams["powerscore_adj"].max() - teams["powerscore_adj"].min()
        assert ps_range < 0.10, f"Identical-score teams have {ps_range:.4f} PowerScore spread (noise amplification bug)"


# ===========================================================================
# Empty and expired data
# ===========================================================================


class TestEmptyData:
    """Handle empty or expired game data."""

    def test_empty_games_returns_empty(self):
        """Empty input should return empty output without crashing.

        BUG CAUGHT: pd.concat on empty groupby raised ValueError instead of
        returning empty results gracefully.
        Fix: early-return when no groups produced by outlier-guard groupby.
        """
        games = pd.DataFrame(
            columns=["game_id", "date", "team_id", "opp_id", "age", "gender", "opp_age", "opp_gender", "gf", "ga"]
        )
        cfg = V53EConfig()
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        assert len(result["teams"]) == 0

    def test_all_games_outside_window(self):
        """Games older than WINDOW_DAYS should produce empty results.

        BUG CAUGHT: Same pd.concat crash as empty input when all games
        are outside the 365-day window.
        """
        team_ids = [f"t{i}" for i in range(6)]
        old_date = datetime(2024, 5, 1)
        games = _round_robin(team_ids, old_date, n_rounds=3)
        cfg = V53EConfig()
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]
        assert len(teams) == 0 or (teams["status"] != "Active").all()

    def test_missing_required_columns(self):
        """Missing required columns should return empty results gracefully."""
        bad_df = pd.DataFrame({"team_id": ["t1"], "score": [5]})
        cfg = V53EConfig()
        result = compute_rankings(games_df=bad_df, cfg=cfg)
        assert len(result["teams"]) == 0


# ===========================================================================
# NaN handling in intermediate calculations
# ===========================================================================


class TestNaNHandling:
    """Verify NaN values don't propagate to final PowerScore."""

    def test_no_nan_in_final_output(self):
        """Final powerscore_adj should never contain NaN."""
        team_ids = [f"t{i}" for i in range(15)]
        base = datetime(2025, 6, 1)
        games = _round_robin(team_ids, base, lambda h, a: (h % 4, a % 3), n_rounds=2)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False)
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]

        assert teams["powerscore_core"].notna().all(), "NaN in powerscore_core"
        assert teams["powerscore_adj"].notna().all(), "NaN in powerscore_adj"
        assert teams["sos_norm"].notna().all(), "NaN in sos_norm"
        assert teams["off_norm"].notna().all(), "NaN in off_norm"
        assert teams["def_norm"].notna().all(), "NaN in def_norm"

    def test_sos_default_for_unranked_opponents(self):
        """Teams playing only unranked opponents should get SOS near UNRANKED_SOS_BASE."""
        rows = []
        gc = 0
        base = datetime(2025, 6, 1)
        # One ranked team plays 10 games against unknown opponents
        for i in range(10):
            d = base - timedelta(days=i * 5)
            rows.extend(_make_game_pair(f"g_{gc:04d}", d, "ranked_team", f"unknown_{i}", 3, 0))
            gc += 1

        games = pd.DataFrame(rows)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False, PAGERANK_DAMPENING_ENABLED=False)
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]

        ranked = teams[teams["team_id"] == "ranked_team"]
        if not ranked.empty:
            sos = ranked["sos"].values[0]
            # SOS should be near UNRANKED_SOS_BASE (0.35) since opponents are unranked
            assert abs(sos - cfg.UNRANKED_SOS_BASE) < 0.20, (
                f"SOS against unranked opponents should be near {cfg.UNRANKED_SOS_BASE}, got {sos:.4f}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
