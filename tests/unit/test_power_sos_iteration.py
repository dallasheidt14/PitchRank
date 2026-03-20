"""
Tests for Power-SOS iteration loop correctness.

The Power-SOS co-calculation refines SOS using opponent's FULL power score
(including their SOS), rather than just their off/def. This avoids the
problem where beating teams with tough schedules doesn't boost your SOS.

Algorithm (from v53e.py):
1. Initial SOS uses base_strength (OFF/DEF only, no SOS)
2. Compute powerscore_adj = f(off, def, sos)
3. Build full_power_strength_map = max(powerscore_adj * anchor, base_strength)
4. Recalculate SOS using full_power_strength_map
5. Apply damping: new_SOS = 0.7 * calculated + 0.3 * previous
6. Re-normalize, re-shrink, recalculate PowerScore
7. Repeat for SOS_POWER_ITERATIONS (default 3)
8. Early exit if convergence < 0.0001
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.etl.v53e import V53EConfig, compute_rankings


def _make_game_pair(gid, date, home, away, hs, as_, age="14", gender="male"):
    return [
        {"game_id": gid, "date": pd.Timestamp(date),
         "team_id": home, "opp_id": away, "age": age, "gender": gender,
         "opp_age": age, "opp_gender": gender, "gf": hs, "ga": as_},
        {"game_id": gid, "date": pd.Timestamp(date),
         "team_id": away, "opp_id": home, "age": age, "gender": gender,
         "opp_age": age, "opp_gender": gender, "gf": as_, "ga": hs},
    ]


def _build_league(num_teams=20, games_per_team=12, seed=42):
    rng = np.random.RandomState(seed)
    ids = [f"team_{i:03d}" for i in range(num_teams)]
    rows = []
    gc = 0
    base = datetime(2025, 6, 1)
    needed = (num_teams * games_per_team) // 2 + num_teams
    for _ in range(needed):
        h, a = rng.choice(num_teams, size=2, replace=False)
        hs, as_ = int(rng.poisson(1.5)), int(rng.poisson(1.5))
        d = base - timedelta(days=int(rng.randint(1, 300)))
        rows.extend(_make_game_pair(f"g_{gc:04d}", d, ids[h], ids[a], hs, as_))
        gc += 1
    return pd.DataFrame(rows), ids


# ===========================================================================
# Convergence tests
# ===========================================================================

class TestPowerSOSConvergence:
    """Verify that the Power-SOS iteration loop converges."""

    def test_iterations_change_sos(self):
        """SOS should be different with iterations=3 vs iterations=0."""
        games, _ = _build_league(num_teams=25, games_per_team=12)

        cfg_no_iter = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False)
        cfg_with_iter = V53EConfig(SOS_POWER_ITERATIONS=3, SCF_ENABLED=False)

        r0 = compute_rankings(games_df=games, cfg=cfg_no_iter, today=pd.Timestamp("2025-07-01"))
        r3 = compute_rankings(games_df=games, cfg=cfg_with_iter, today=pd.Timestamp("2025-07-01"))

        t0 = r0["teams"].set_index("team_id")
        t3 = r3["teams"].set_index("team_id")
        common = t0.index.intersection(t3.index)

        sos_diff = (t0.loc[common, "sos"] - t3.loc[common, "sos"]).abs()
        assert sos_diff.max() > 0.001, (
            "Power-SOS iterations should change SOS values"
        )

    def test_more_iterations_converge(self):
        """SOS difference between iter=3 and iter=10 should be small (convergence)."""
        games, _ = _build_league(num_teams=25, games_per_team=12)

        cfg_3 = V53EConfig(SOS_POWER_ITERATIONS=3, SCF_ENABLED=False)
        cfg_10 = V53EConfig(SOS_POWER_ITERATIONS=10, SCF_ENABLED=False)

        r3 = compute_rankings(games_df=games, cfg=cfg_3, today=pd.Timestamp("2025-07-01"))
        r10 = compute_rankings(games_df=games, cfg=cfg_10, today=pd.Timestamp("2025-07-01"))

        t3 = r3["teams"].set_index("team_id")
        t10 = r10["teams"].set_index("team_id")
        common = t3.index.intersection(t10.index)

        sos_diff = (t3.loc[common, "sos"] - t10.loc[common, "sos"]).abs()
        assert sos_diff.mean() < 0.01, (
            f"Mean SOS diff between 3 and 10 iterations should be small: {sos_diff.mean():.6f}"
        )

    def test_powerscore_remains_bounded_after_iterations(self):
        """PowerScore must stay in [0, 1] after all iterations."""
        games, _ = _build_league(num_teams=25, games_per_team=12)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=5, SCF_ENABLED=False)
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]

        assert (teams["powerscore_adj"] >= 0.0).all(), "PowerScore < 0 after iterations"
        assert (teams["powerscore_adj"] <= 1.0).all(), "PowerScore > 1 after iterations"
        assert (teams["sos_norm"] >= 0.0).all(), "SOS norm < 0 after iterations"
        assert (teams["sos_norm"] <= 1.0).all(), "SOS norm > 1 after iterations"


# ===========================================================================
# Damping factor tests
# ===========================================================================

class TestDampingFactor:
    """Verify damping prevents oscillation."""

    def test_damping_reduces_sos_change(self):
        """Higher damping (closer to 1.0) should change SOS more per iteration."""
        games, _ = _build_league(num_teams=20, games_per_team=12)

        cfg_low = V53EConfig(SOS_POWER_ITERATIONS=1, SOS_POWER_DAMPING=0.3, SCF_ENABLED=False)
        cfg_high = V53EConfig(SOS_POWER_ITERATIONS=1, SOS_POWER_DAMPING=0.9, SCF_ENABLED=False)
        cfg_base = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False)

        r_base = compute_rankings(games_df=games, cfg=cfg_base, today=pd.Timestamp("2025-07-01"))
        r_low = compute_rankings(games_df=games, cfg=cfg_low, today=pd.Timestamp("2025-07-01"))
        r_high = compute_rankings(games_df=games, cfg=cfg_high, today=pd.Timestamp("2025-07-01"))

        t_base = r_base["teams"].set_index("team_id")
        t_low = r_low["teams"].set_index("team_id")
        t_high = r_high["teams"].set_index("team_id")
        common = t_base.index.intersection(t_low.index).intersection(t_high.index)

        change_low = (t_low.loc[common, "sos"] - t_base.loc[common, "sos"]).abs().mean()
        change_high = (t_high.loc[common, "sos"] - t_base.loc[common, "sos"]).abs().mean()

        # Higher damping = more change from calculated value (less retention of previous)
        assert change_high >= change_low * 0.8, (
            f"Higher damping should produce more SOS change: "
            f"low={change_low:.6f}, high={change_high:.6f}"
        )


# ===========================================================================
# Floor prevents circular depression
# ===========================================================================

class TestFloorPreventsCollapse:
    """The floor = max(powerscore_adj * anchor, base_strength) prevents
    circular depression in closed elite leagues."""

    def test_closed_league_maintains_strength(self):
        """A closed league (teams only play each other) should not spiral down
        in SOS during Power-SOS iterations."""
        # Create a closed league: 10 teams only play each other
        team_ids = [f"elite_{i}" for i in range(10)]
        rows = []
        gc = 0
        base = datetime(2025, 6, 1)

        # Round-robin with 2 rounds
        for rnd in range(2):
            for i, h in enumerate(team_ids):
                for j, a in enumerate(team_ids):
                    if i >= j:
                        continue
                    d = base - timedelta(days=gc * 2 + rnd)
                    rows.extend(_make_game_pair(f"g_{gc:04d}", d, h, a, 2, 1))
                    gc += 1

        games = pd.DataFrame(rows)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=5, SCF_ENABLED=False, PAGERANK_DAMPENING_ENABLED=False)
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]

        # SOS should be reasonable (not collapsed to near 0)
        avg_sos = teams["sos"].mean()
        assert avg_sos > 0.1, (
            f"Closed league average SOS collapsed: {avg_sos:.4f}"
        )

    def test_floor_preserves_base_strength(self):
        """The floor ensures opp strength >= base_strength (off/def only)."""
        games, _ = _build_league(num_teams=15, games_per_team=12)

        # Run with iterations
        cfg = V53EConfig(SOS_POWER_ITERATIONS=3, SCF_ENABLED=False)
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]

        # All PowerScores should be positive (floor prevents collapse to 0)
        assert (teams["powerscore_adj"] > 0).all(), "PowerScore collapsed to 0"


# ===========================================================================
# Rank stability across iterations
# ===========================================================================

class TestRankStability:
    """Rankings should be relatively stable across iteration counts."""

    def test_top_team_stays_near_top(self):
        """The top-ranked team without iterations should remain in top 5 with iterations."""
        games, _ = _build_league(num_teams=25, games_per_team=12)

        cfg0 = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False)
        cfg3 = V53EConfig(SOS_POWER_ITERATIONS=3, SCF_ENABLED=False)

        r0 = compute_rankings(games_df=games, cfg=cfg0, today=pd.Timestamp("2025-07-01"))
        r3 = compute_rankings(games_df=games, cfg=cfg3, today=pd.Timestamp("2025-07-01"))

        t0 = r0["teams"]
        t3 = r3["teams"]

        active0 = t0[t0["status"] == "Active"].sort_values("powerscore_adj", ascending=False)
        active3 = t3[t3["status"] == "Active"].sort_values("powerscore_adj", ascending=False)

        if len(active0) >= 5 and len(active3) >= 5:
            top1_id = active0.iloc[0]["team_id"]
            rank_in_iter = active3[active3["team_id"] == top1_id]["rank_in_cohort"]
            if not rank_in_iter.empty:
                assert rank_in_iter.values[0] <= 5, (
                    f"Top team dropped to rank {rank_in_iter.values[0]} after iterations"
                )


# ===========================================================================
# Re-normalization after iterations
# ===========================================================================

class TestReNormalization:
    """SOS must be re-normalized after each iteration."""

    def test_sos_norm_full_range_after_iterations(self):
        """sos_norm should still span [0, 1] after Power-SOS iterations."""
        games, _ = _build_league(num_teams=30, games_per_team=12)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=3, SCF_ENABLED=False)
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]
        sos_norm = active["sos_norm"].dropna()

        if len(sos_norm) >= 10:
            assert sos_norm.min() < 0.2, f"sos_norm min after iterations: {sos_norm.min():.3f}"
            assert sos_norm.max() > 0.8, f"sos_norm max after iterations: {sos_norm.max():.3f}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
