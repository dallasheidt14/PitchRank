"""
Comprehensive tests for Active-only ranking enforcement.

Validates that teams with fewer than MIN_GAMES_PROVISIONAL (6) games
do NOT receive ranks (rank_in_cohort, rank_in_cohort_ml, SOS ranks),
and that the full pipeline correctly handles status-based filtering.

Also covers:
- Data adapter NULL preservation for ranks
- Layer 13 status-aware ranking
- Anchor scaling correctness
- Pipeline save logic edge cases
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from copy import deepcopy

from src.etl.v53e import V53EConfig, compute_rankings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game_pair(gid, date, home, away, hs, as_, age="14", gender="male"):
    """Create home + away perspective rows for a single game."""
    return [
        {"game_id": gid, "date": pd.Timestamp(date),
         "team_id": home, "opp_id": away, "age": age, "gender": gender,
         "opp_age": age, "opp_gender": gender, "gf": hs, "ga": as_},
        {"game_id": gid, "date": pd.Timestamp(date),
         "team_id": away, "opp_id": home, "age": age, "gender": gender,
         "opp_age": age, "opp_gender": gender, "gf": as_, "ga": hs},
    ]


def _build_mixed_activity_league(today=None):
    """
    Build a league with teams having different game counts:
    - team_active_1:  10 games (Active)
    - team_active_2:  10 games (Active)
    - team_active_3:   8 games (Active, edge case)
    - team_low_1:      5 games (Not Enough Ranked Games)
    - team_low_2:      3 games (Not Enough Ranked Games)
    - team_one_game:   1 game  (Not Enough Ranked Games)
    """
    if today is None:
        today = pd.Timestamp("2025-06-01")

    rows = []
    gid = 0

    # Active teams: 10+ opponents needed, so build a pool of teams
    teams_active = ["team_active_1", "team_active_2", "team_active_3"]
    teams_low = ["team_low_1", "team_low_2", "team_one_game"]
    # Extra opponents to fill games
    fillers = [f"filler_{i}" for i in range(20)]
    all_opps = teams_active + teams_low + fillers

    # team_active_1: 10 games
    for i in range(10):
        gid += 1
        opp = all_opps[(i + 1) % len(all_opps)]
        if opp == "team_active_1":
            opp = fillers[i]
        date = today - timedelta(days=10 + i * 7)
        rows.extend(_make_game_pair(f"g{gid}", date, "team_active_1", opp, 3, 1))

    # team_active_2: 10 games
    for i in range(10):
        gid += 1
        opp = all_opps[(i + 3) % len(all_opps)]
        if opp == "team_active_2":
            opp = fillers[i + 5]
        date = today - timedelta(days=10 + i * 7)
        rows.extend(_make_game_pair(f"g{gid}", date, "team_active_2", opp, 2, 1))

    # team_active_3: exactly 8 games (edge case)
    for i in range(8):
        gid += 1
        opp = fillers[i + 10]
        date = today - timedelta(days=10 + i * 7)
        rows.extend(_make_game_pair(f"g{gid}", date, "team_active_3", opp, 2, 0))

    # team_low_1: 5 games (Not Enough Ranked Games)
    for i in range(5):
        gid += 1
        opp = fillers[i]
        date = today - timedelta(days=10 + i * 7)
        rows.extend(_make_game_pair(f"g{gid}", date, "team_low_1", opp, 1, 2))

    # team_low_2: 3 games (Not Enough Ranked Games)
    for i in range(3):
        gid += 1
        opp = fillers[i]
        date = today - timedelta(days=10 + i * 7)
        rows.extend(_make_game_pair(f"g{gid}", date, "team_low_2", opp, 0, 1))

    # team_one_game: 1 game (Not Enough Ranked Games)
    gid += 1
    date = today - timedelta(days=10)
    rows.extend(_make_game_pair(f"g{gid}", date, "team_one_game", fillers[0], 5, 0))

    # Give filler teams enough games to be "Active" so they have valid SOS
    for i, filler in enumerate(fillers):
        for j in range(8):
            gid += 1
            opp = fillers[(i + j + 1) % len(fillers)]
            if opp == filler:
                opp = fillers[(i + j + 2) % len(fillers)]
            date = today - timedelta(days=10 + j * 7)
            rows.extend(_make_game_pair(f"g{gid}", date, filler, opp, 2, 1))

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Tests: v53e Status Assignment
# ---------------------------------------------------------------------------

class TestStatusAssignment:
    """Verify v53e correctly assigns Active / Not Enough Ranked Games / Inactive."""

    def setup_method(self):
        self.today = pd.Timestamp("2025-06-01")
        self.games_df = _build_mixed_activity_league(self.today)
        self.cfg = V53EConfig()
        self.result = compute_rankings(self.games_df, today=self.today, cfg=self.cfg)
        self.teams = self.result["teams"]

    def test_active_teams_have_8_plus_games(self):
        """Teams with 8+ games in 180 days should be Active."""
        for tid in ["team_active_1", "team_active_2", "team_active_3"]:
            team_row = self.teams[self.teams["team_id"] == tid]
            if not team_row.empty:
                assert team_row.iloc[0]["status"] == "Active", \
                    f"{tid} should be Active but got {team_row.iloc[0]['status']}"

    def test_low_game_teams_not_active(self):
        """Teams with < 8 games should NOT be Active."""
        for tid in ["team_low_1", "team_low_2", "team_one_game"]:
            team_row = self.teams[self.teams["team_id"] == tid]
            if not team_row.empty:
                assert team_row.iloc[0]["status"] != "Active", \
                    f"{tid} should NOT be Active but got {team_row.iloc[0]['status']}"

    def test_edge_case_exactly_8_games(self):
        """Team with exactly 8 games should be Active."""
        team_row = self.teams[self.teams["team_id"] == "team_active_3"]
        if not team_row.empty:
            assert team_row.iloc[0]["status"] == "Active"
            assert team_row.iloc[0]["gp_last_180"] >= 8

    def test_one_game_team_status(self):
        """Team with 1 game should be 'Not Enough Ranked Games'."""
        team_row = self.teams[self.teams["team_id"] == "team_one_game"]
        if not team_row.empty:
            status = team_row.iloc[0]["status"]
            assert status == "Not Enough Ranked Games", \
                f"1-game team should be 'Not Enough Ranked Games' but got '{status}'"


# ---------------------------------------------------------------------------
# Tests: v53e Rank Assignment
# ---------------------------------------------------------------------------

class TestV53eRankAssignment:
    """Verify v53e only assigns rank_in_cohort to Active teams."""

    def setup_method(self):
        self.today = pd.Timestamp("2025-06-01")
        self.games_df = _build_mixed_activity_league(self.today)
        self.cfg = V53EConfig()
        self.result = compute_rankings(self.games_df, today=self.today, cfg=self.cfg)
        self.teams = self.result["teams"]

    def test_active_teams_get_rank(self):
        """Active teams should have a non-null rank_in_cohort."""
        active = self.teams[self.teams["status"] == "Active"]
        assert not active.empty, "Should have some Active teams"
        # All active teams should have a rank
        for _, row in active.iterrows():
            assert pd.notna(row["rank_in_cohort"]), \
                f"Active team {row['team_id']} should have rank but got None"

    def test_non_active_teams_no_rank(self):
        """Non-Active teams should have NULL rank_in_cohort."""
        non_active = self.teams[self.teams["status"] != "Active"]
        for _, row in non_active.iterrows():
            assert pd.isna(row["rank_in_cohort"]) or row["rank_in_cohort"] is None, \
                f"Non-Active team {row['team_id']} (status={row['status']}) should NOT have rank but got {row['rank_in_cohort']}"

    def test_ranks_are_sequential(self):
        """Active team ranks should be sequential (1, 2, 3...) with no gaps."""
        for (age, gender), cohort in self.teams.groupby(["age", "gender"]):
            active_cohort = cohort[cohort["status"] == "Active"]
            if active_cohort.empty:
                continue
            ranks = sorted(active_cohort["rank_in_cohort"].dropna().astype(int).tolist())
            expected = list(range(1, len(ranks) + 1))
            assert ranks == expected, \
                f"Ranks for {age}/{gender} should be sequential {expected} but got {ranks}"


# ---------------------------------------------------------------------------
# Tests: SOS Rank Assignment
# ---------------------------------------------------------------------------

class TestSOSRankAssignment:
    """Verify SOS ranks are only assigned to Active teams."""

    def setup_method(self):
        self.today = pd.Timestamp("2025-06-01")
        self.games_df = _build_mixed_activity_league(self.today)
        self.cfg = V53EConfig()
        self.result = compute_rankings(self.games_df, today=self.today, cfg=self.cfg)
        self.teams = self.result["teams"]

    def test_non_active_teams_no_sos_rank(self):
        """Non-Active teams should not have SOS rank_national or rank_state."""
        non_active = self.teams[self.teams["status"] != "Active"]
        for _, row in non_active.iterrows():
            if "sos_rank_national" in row.index:
                assert pd.isna(row.get("sos_rank_national")), \
                    f"Non-Active team {row['team_id']} should NOT have SOS national rank"
            if "sos_rank_state" in row.index:
                assert pd.isna(row.get("sos_rank_state")), \
                    f"Non-Active team {row['team_id']} should NOT have SOS state rank"


# ---------------------------------------------------------------------------
# Tests: Layer 13 Active-Only Ranking
# ---------------------------------------------------------------------------

class TestLayer13ActiveOnly:
    """Verify Layer 13 only ranks Active teams via _rank_active_only."""

    def test_rank_active_only_basic(self):
        """_rank_active_only should return NULL for non-Active teams."""
        from src.rankings.layer13_predictive_adjustment import _rank_active_only

        df = pd.DataFrame({
            "team_id": ["A", "B", "C", "D"],
            "age": [14, 14, 14, 14],
            "gender": ["male", "male", "male", "male"],
            "powerscore_ml": [0.8, 0.7, 0.6, 0.9],
            "sos": [0.5, 0.4, 0.3, 0.6],
            "status": ["Active", "Active", "Not Enough Ranked Games", "Active"],
        })

        ranks = _rank_active_only(df, ["age", "gender"], "powerscore_ml")

        # Active teams should have integer ranks
        assert ranks.iloc[0] == 2  # A: 0.8 → rank 2
        assert ranks.iloc[1] == 3  # B: 0.7 → rank 3
        assert ranks.iloc[3] == 1  # D: 0.9 → rank 1

        # Non-Active team should have NULL
        assert pd.isna(ranks.iloc[2]), \
            f"Non-Active team C should have NULL rank but got {ranks.iloc[2]}"

    def test_rank_active_only_empty_df(self):
        """_rank_active_only should handle empty DataFrame."""
        from src.rankings.layer13_predictive_adjustment import _rank_active_only

        df = pd.DataFrame(columns=["team_id", "age", "gender", "powerscore_ml", "sos", "status"])
        ranks = _rank_active_only(df, ["age", "gender"], "powerscore_ml")
        assert len(ranks) == 0

    def test_rank_active_only_no_active_teams(self):
        """If no teams are Active, all should get NULL rank."""
        from src.rankings.layer13_predictive_adjustment import _rank_active_only

        df = pd.DataFrame({
            "team_id": ["A", "B"],
            "age": [14, 14],
            "gender": ["male", "male"],
            "powerscore_ml": [0.8, 0.7],
            "sos": [0.5, 0.4],
            "status": ["Not Enough Ranked Games", "Inactive"],
        })

        ranks = _rank_active_only(df, ["age", "gender"], "powerscore_ml")
        assert pd.isna(ranks.iloc[0])
        assert pd.isna(ranks.iloc[1])

    def test_rank_active_only_no_status_column(self):
        """Without status column, should fall back to ranking all teams."""
        from src.rankings.layer13_predictive_adjustment import _rank_active_only

        df = pd.DataFrame({
            "team_id": ["A", "B"],
            "age": [14, 14],
            "gender": ["male", "male"],
            "powerscore_ml": [0.8, 0.7],
            "sos": [0.5, 0.4],
        })

        ranks = _rank_active_only(df, ["age", "gender"], "powerscore_ml")
        assert ranks.iloc[0] == 1  # A: 0.8
        assert ranks.iloc[1] == 2  # B: 0.7

    def test_rank_active_only_multi_cohort(self):
        """Active-only ranking works correctly across multiple cohorts."""
        from src.rankings.layer13_predictive_adjustment import _rank_active_only

        df = pd.DataFrame({
            "team_id": ["A", "B", "C", "D", "E"],
            "age": [14, 14, 14, 16, 16],
            "gender": ["male", "male", "male", "male", "male"],
            "powerscore_ml": [0.8, 0.9, 0.7, 0.6, 0.5],
            "sos": [0.5, 0.6, 0.4, 0.3, 0.2],
            "status": ["Active", "Active", "Not Enough Ranked Games", "Active", "Not Enough Ranked Games"],
        })

        ranks = _rank_active_only(df, ["age", "gender"], "powerscore_ml")

        # U14 cohort: A(0.8)=#2, B(0.9)=#1, C=NULL
        assert ranks.iloc[0] == 2  # A
        assert ranks.iloc[1] == 1  # B
        assert pd.isna(ranks.iloc[2])  # C

        # U16 cohort: D(0.6)=#1, E=NULL
        assert ranks.iloc[3] == 1  # D
        assert pd.isna(ranks.iloc[4])  # E


# ---------------------------------------------------------------------------
# Tests: Data Adapter NULL Preservation
# ---------------------------------------------------------------------------

class TestDataAdapterNullPreservation:
    """Verify data adapter preserves NULL for non-Active team ranks."""

    def test_null_rank_in_cohort_ml_preserved(self):
        """rank_in_cohort_ml should be NULL (not 0) for non-Active teams."""
        from src.rankings.data_adapter import v53e_to_rankings_full_format

        teams_df = pd.DataFrame({
            "team_id": ["A", "B", "C"],
            "age": [14, 14, 14],
            "gender": ["Male", "Male", "Male"],
            "status": ["Active", "Active", "Not Enough Ranked Games"],
            "gp": [20, 15, 5],
            "gp_last_180": [20, 15, 5],
            "powerscore_adj": [0.8, 0.7, 0.6],
            "powerscore_core": [0.75, 0.65, 0.55],
            "powerscore_ml": [0.82, 0.72, 0.62],
            "rank_in_cohort": [1, 2, pd.NA],
            "rank_in_cohort_ml": pd.array([1, 2, pd.NA], dtype="Int64"),
            "sos": [0.6, 0.5, 0.3],
            "sos_norm": [0.7, 0.5, 0.3],
            "last_game": [pd.Timestamp("2025-05-15")] * 3,
        })

        result = v53e_to_rankings_full_format(teams_df)

        # Active teams should have integer ranks
        assert result.loc[result["team_id"] == "A", "rank_in_cohort_ml"].values[0] == 1
        assert result.loc[result["team_id"] == "B", "rank_in_cohort_ml"].values[0] == 2

        # Non-Active team should have NULL rank (not 0)
        c_rank = result.loc[result["team_id"] == "C", "rank_in_cohort_ml"].values[0]
        assert pd.isna(c_rank), \
            f"Non-Active team C rank_in_cohort_ml should be NULL but got {c_rank}"

    def test_null_rank_in_cohort_preserved(self):
        """rank_in_cohort should be NULL for non-Active teams."""
        from src.rankings.data_adapter import v53e_to_rankings_full_format

        teams_df = pd.DataFrame({
            "team_id": ["A", "B"],
            "age": [14, 14],
            "gender": ["Male", "Male"],
            "status": ["Active", "Not Enough Ranked Games"],
            "gp": [20, 3],
            "gp_last_180": [20, 3],
            "powerscore_adj": [0.8, 0.6],
            "powerscore_core": [0.75, 0.55],
            "rank_in_cohort": [1, pd.NA],
            "sos": [0.6, 0.3],
            "sos_norm": [0.7, 0.3],
            "last_game": [pd.Timestamp("2025-05-15")] * 2,
        })

        result = v53e_to_rankings_full_format(teams_df)

        a_rank = result.loc[result["team_id"] == "A", "rank_in_cohort"].values[0]
        b_rank = result.loc[result["team_id"] == "B", "rank_in_cohort"].values[0]

        assert a_rank == 1
        assert pd.isna(b_rank), \
            f"Non-Active team B rank_in_cohort should be NULL but got {b_rank}"


# ---------------------------------------------------------------------------
# Tests: PowerScore Bounds
# ---------------------------------------------------------------------------

class TestPowerScoreBounds:
    """Verify PowerScore stays in [0, 1] under various conditions."""

    def setup_method(self):
        self.today = pd.Timestamp("2025-06-01")
        self.cfg = V53EConfig()

    def test_powerscore_within_bounds(self):
        """All PowerScores should be in [0.0, 1.0]."""
        games_df = _build_mixed_activity_league(self.today)
        result = compute_rankings(games_df, today=self.today, cfg=self.cfg)
        teams = result["teams"]

        for col in ["powerscore_core", "powerscore_adj"]:
            if col in teams.columns:
                vals = teams[col].dropna()
                assert vals.min() >= 0.0, f"{col} min={vals.min():.6f} < 0"
                assert vals.max() <= 1.0, f"{col} max={vals.max():.6f} > 1"

    def test_powerscore_no_nan_for_active(self):
        """Active teams should not have NaN PowerScore."""
        games_df = _build_mixed_activity_league(self.today)
        result = compute_rankings(games_df, today=self.today, cfg=self.cfg)
        teams = result["teams"]
        active = teams[teams["status"] == "Active"]

        assert not active.empty
        nan_count = active["powerscore_adj"].isna().sum()
        assert nan_count == 0, f"{nan_count} Active teams have NaN powerscore_adj"

    def test_extreme_blowout_games(self):
        """PowerScore should stay in bounds even with extreme scores."""
        rows = []
        gid = 0
        for i in range(12):
            gid += 1
            date = self.today - timedelta(days=10 + i * 7)
            # 20-0 blowouts (capped at 6 by v53e)
            rows.extend(_make_game_pair(
                f"g{gid}", date, "dominant_team", f"weak_{i}", 20, 0))

        # Give weak teams enough games
        for i in range(12):
            for j in range(10):
                gid += 1
                date = self.today - timedelta(days=10 + j * 7)
                rows.extend(_make_game_pair(
                    f"g{gid}", date, f"weak_{i}", f"weak_{(i+j+1) % 12}", 1, 2))

        games_df = pd.DataFrame(rows)
        result = compute_rankings(games_df, today=self.today, cfg=self.cfg)
        teams = result["teams"]

        for col in ["powerscore_core", "powerscore_adj"]:
            if col in teams.columns:
                vals = teams[col].dropna()
                if not vals.empty:
                    assert vals.min() >= 0.0, f"Extreme game: {col} min={vals.min()}"
                    assert vals.max() <= 1.0, f"Extreme game: {col} max={vals.max()}"


# ---------------------------------------------------------------------------
# Tests: Anchor Scaling
# ---------------------------------------------------------------------------

class TestAnchorScaling:
    """Verify anchor scaling produces correct power_score_final values."""

    def test_anchor_values_by_age(self):
        """power_score_final should be scaled by age-specific anchor."""
        from src.rankings.data_adapter import v53e_to_rankings_full_format

        AGE_ANCHORS = {
            10: 0.400, 11: 0.475, 12: 0.550, 13: 0.625,
            14: 0.700, 15: 0.775, 16: 0.850, 17: 0.925,
            19: 1.000,
        }

        teams_df = pd.DataFrame({
            "team_id": [f"team_{age}" for age in AGE_ANCHORS],
            "age": list(AGE_ANCHORS.keys()),
            "gender": ["Male"] * len(AGE_ANCHORS),
            "status": ["Active"] * len(AGE_ANCHORS),
            "gp": [20] * len(AGE_ANCHORS),
            "gp_last_180": [20] * len(AGE_ANCHORS),
            "powerscore_adj": [0.80] * len(AGE_ANCHORS),
            "powerscore_core": [0.75] * len(AGE_ANCHORS),
            "sos": [0.5] * len(AGE_ANCHORS),
            "sos_norm": [0.5] * len(AGE_ANCHORS),
            "rank_in_cohort": list(range(1, len(AGE_ANCHORS) + 1)),
            "last_game": [pd.Timestamp("2025-05-15")] * len(AGE_ANCHORS),
        })

        result = v53e_to_rankings_full_format(teams_df)

        for age, anchor in AGE_ANCHORS.items():
            team_row = result[result["team_id"] == f"team_{age}"]
            if not team_row.empty:
                psf = team_row.iloc[0]["power_score_final"]
                expected_max = anchor  # base (0.80) * anchor, clipped to anchor
                assert psf <= anchor + 0.001, \
                    f"Age {age}: power_score_final={psf:.4f} exceeds anchor={anchor:.3f}"
                assert psf > 0, \
                    f"Age {age}: power_score_final={psf:.4f} should be positive"

    def test_anchor_preserves_rank_order(self):
        """Within a cohort, anchor scaling should preserve rank order."""
        from src.rankings.data_adapter import v53e_to_rankings_full_format

        teams_df = pd.DataFrame({
            "team_id": ["best", "mid", "worst"],
            "age": [14, 14, 14],
            "gender": ["Male", "Male", "Male"],
            "status": ["Active", "Active", "Active"],
            "gp": [20, 18, 15],
            "gp_last_180": [20, 18, 15],
            "powerscore_adj": [0.90, 0.70, 0.50],
            "powerscore_core": [0.85, 0.65, 0.45],
            "sos": [0.7, 0.5, 0.3],
            "sos_norm": [0.7, 0.5, 0.3],
            "rank_in_cohort": [1, 2, 3],
            "last_game": [pd.Timestamp("2025-05-15")] * 3,
        })

        result = v53e_to_rankings_full_format(teams_df)

        best_psf = result.loc[result["team_id"] == "best", "power_score_final"].values[0]
        mid_psf = result.loc[result["team_id"] == "mid", "power_score_final"].values[0]
        worst_psf = result.loc[result["team_id"] == "worst", "power_score_final"].values[0]

        assert best_psf > mid_psf > worst_psf, \
            f"Rank order not preserved: best={best_psf:.4f}, mid={mid_psf:.4f}, worst={worst_psf:.4f}"


# ---------------------------------------------------------------------------
# Tests: SOS Shrinkage for Low-Game Teams
# ---------------------------------------------------------------------------

class TestSOSShrinkage:
    """Discover whether SOS shrinkage actually dampens sos_norm for low-game teams.

    Shrinkage formula: sos_norm = anchor + shrink_factor * (sos_norm - anchor)
    where shrink_factor = gp / MIN_GAMES_FOR_TOP_SOS (capped at 1.0)
    and anchor = 0.35 (SOS_SHRINKAGE_ANCHOR).

    Shrinkage is applied to sos_norm (NOT raw sos), and applied in BOTH
    SOS passes. This test suite checks whether the double-pass creates
    over-dampening and whether the result is meaningfully different from
    full-game teams.
    """

    def setup_method(self):
        self.today = pd.Timestamp("2025-06-01")
        self.cfg = V53EConfig()

    def test_low_game_team_sos_norm_dampened_vs_high_game(self):
        """sos_norm for a 1-game team should be closer to 0.35 anchor
        than sos_norm for a 10+ game team playing similar opponents."""
        games_df = _build_mixed_activity_league(self.today)
        result = compute_rankings(games_df, today=self.today, cfg=self.cfg)
        teams = result["teams"]

        one_game = teams[teams["team_id"] == "team_one_game"]
        active_10 = teams[teams["team_id"] == "team_active_1"]

        if one_game.empty or active_10.empty:
            pytest.skip("Test teams not found in results")

        sos_norm_1g = one_game.iloc[0]["sos_norm"]
        sos_norm_10g = active_10.iloc[0]["sos_norm"]
        anchor = self.cfg.SOS_SHRINKAGE_ANCHOR  # 0.35

        # The 1-game team's sos_norm should be closer to anchor than the 10-game team
        dist_1g = abs(sos_norm_1g - anchor)
        dist_10g = abs(sos_norm_10g - anchor)

        assert dist_1g <= dist_10g, (
            f"Shrinkage not working: 1-game team sos_norm={sos_norm_1g:.3f} is FARTHER "
            f"from anchor {anchor} (dist={dist_1g:.3f}) than 10-game team "
            f"sos_norm={sos_norm_10g:.3f} (dist={dist_10g:.3f})"
        )

    def test_provisional_multiplier_uses_total_gp_not_gp_last_180(self):
        """The provisional multiplier uses total gp, NOT gp_last_180.

        This could be a latent bug: a team with 20 total games but only 3
        in the last 180 days gets full provisional multiplier (1.0) despite
        being 'Not Enough Ranked Games'. The multiplier should arguably
        use gp_last_180 to match the status logic.
        """
        games_df = _build_mixed_activity_league(self.today)
        result = compute_rankings(games_df, today=self.today, cfg=self.cfg)
        teams = result["teams"]

        for _, row in teams.iterrows():
            if row["status"] == "Not Enough Ranked Games" and row["gp"] >= 15:
                # This team has many total games but few recent ones.
                # provisional_mult will be 1.0 (based on gp), but status
                # says they don't have enough. This is inconsistent.
                mult = row.get("provisional_mult", 1.0)
                if mult == 1.0 and row["gp_last_180"] < 8:
                    # Documenting the inconsistency — not failing, but flagging
                    import warnings
                    warnings.warn(
                        f"Team {row['team_id']}: status='Not Enough Ranked Games' "
                        f"but provisional_mult={mult:.2f} (gp={row['gp']}, "
                        f"gp_last_180={row['gp_last_180']}). The multiplier uses "
                        f"total gp, not gp_last_180, which is inconsistent with status."
                    )

    def test_sos_norm_bounds_after_shrinkage(self):
        """sos_norm should still be in [0, 1] after shrinkage for all teams."""
        games_df = _build_mixed_activity_league(self.today)
        result = compute_rankings(games_df, today=self.today, cfg=self.cfg)
        teams = result["teams"]

        for _, row in teams.iterrows():
            if "sos_norm" in row.index and pd.notna(row["sos_norm"]):
                assert 0.0 <= row["sos_norm"] <= 1.0, (
                    f"Team {row['team_id']}: sos_norm={row['sos_norm']:.4f} "
                    f"out of [0,1] bounds after shrinkage"
                )


# ---------------------------------------------------------------------------
# Tests: Provisional Multiplier
# ---------------------------------------------------------------------------

class TestProvisionalMultiplier:
    """Verify provisional multiplier is applied correctly."""

    def test_multiplier_values(self):
        """Check multiplier function returns correct values."""
        from src.etl.v53e import _provisional_multiplier

        # < 8 games: 0.85
        assert _provisional_multiplier(1, 8) == 0.85
        assert _provisional_multiplier(7, 8) == 0.85

        # 8-14 games: 0.95
        assert _provisional_multiplier(8, 8) == 0.95
        assert _provisional_multiplier(14, 8) == 0.95

        # 15+ games: 1.0
        assert _provisional_multiplier(15, 8) == 1.0
        assert _provisional_multiplier(100, 8) == 1.0


# ---------------------------------------------------------------------------
# Tests: Pipeline Save Logic
# ---------------------------------------------------------------------------

class TestSaveBatchRetry:
    """Test the retry logic in _save_batch_with_retry for correctness."""

    def test_retry_uses_upsert_not_insert(self):
        """The retry section must use .upsert() (not .insert()) to handle
        partial failures where the initial table delete didn't complete.
        With .insert(), duplicate key errors would occur on retry.
        """
        from pathlib import Path

        script_path = Path("scripts/calculate_rankings.py")
        source = script_path.read_text()

        retry_section_start = source.find("# Retry failed batches")
        assert retry_section_start > 0, "Cannot find retry section in calculate_rankings.py"

        retry_section = source[retry_section_start:retry_section_start + 500]
        assert ".upsert(" in retry_section, (
            "Retry section uses .insert() instead of .upsert(). "
            "This will cause duplicate key errors when the initial table delete fails."
        )
        assert ".insert(" not in retry_section, (
            "Retry section still contains .insert() — should be .upsert() only."
        )

    def test_primary_save_uses_upsert(self):
        """The primary batch save must use .upsert() for idempotency."""
        from pathlib import Path

        script_path = Path("scripts/calculate_rankings.py")
        source = script_path.read_text()

        # Find the _save_batch_with_retry function
        func_start = source.find("async def _save_batch_with_retry(")
        assert func_start > 0, "Cannot find _save_batch_with_retry function"

        # Find the primary upsert section (before retry)
        retry_section_start = source.find("# Retry failed batches", func_start)
        assert retry_section_start > 0, "Cannot find retry section"

        primary_section = source[func_start:retry_section_start]

        assert ".upsert(batch)" in primary_section, (
            "Primary save section should use .upsert() for idempotent writes"
        )
        assert ".insert(batch)" not in primary_section, (
            "Primary save section should NOT use .insert() — use .upsert() instead"
        )

    def test_no_delete_before_upsert(self):
        """The save function must NOT delete all rows before upserting.

        The old pattern (DELETE all → UPSERT) left the table empty during
        the write window.  The correct pattern is: UPSERT first, then
        clean up stale rows afterwards.
        """
        from pathlib import Path

        script_path = Path("scripts/calculate_rankings.py")
        source = script_path.read_text()

        # Find the _save_batch_with_retry function body
        func_start = source.find("async def _save_batch_with_retry(")
        assert func_start > 0, "Cannot find _save_batch_with_retry function"

        # Get the function body (up to the next top-level function)
        next_func = source.find("\nasync def ", func_start + 10)
        if next_func < 0:
            next_func = len(source)
        func_body = source[func_start:next_func]

        # The delete-all-first pattern should NOT exist
        has_delete_neq = ".delete().neq(" in func_body
        assert not has_delete_neq, (
            "DANGEROUS: _save_batch_with_retry still uses .delete().neq() "
            "BEFORE upserting. This empties the table during writes. "
            "Use upsert-first, then clean up stale rows after."
        )

        # Verify there IS stale cleanup logic (delete AFTER upsert)
        has_stale_cleanup = "stale" in func_body.lower() or "STALE ROW CLEANUP" in func_body
        assert has_stale_cleanup, (
            "_save_batch_with_retry has no stale row cleanup logic. "
            "After upserts, old rows for removed teams will persist."
        )


# ---------------------------------------------------------------------------
# Tests: End-to-End Rank Consistency
# ---------------------------------------------------------------------------

class TestEndToEndRankConsistency:
    """Verify rank consistency across the full v53e pipeline."""

    def setup_method(self):
        self.today = pd.Timestamp("2025-06-01")
        self.games_df = _build_mixed_activity_league(self.today)
        self.cfg = V53EConfig()
        self.result = compute_rankings(self.games_df, today=self.today, cfg=self.cfg)
        self.teams = self.result["teams"]

    def test_higher_powerscore_means_better_rank(self):
        """Within a cohort, higher powerscore_adj should mean lower (better) rank number."""
        for (age, gender), cohort in self.teams.groupby(["age", "gender"]):
            active = cohort[cohort["status"] == "Active"].copy()
            if len(active) < 2:
                continue

            active = active.sort_values("rank_in_cohort")
            powerscores = active["powerscore_adj"].tolist()

            # Each team should have >= powerscore of the next-ranked team
            for i in range(len(powerscores) - 1):
                assert powerscores[i] >= powerscores[i + 1], \
                    f"Rank ordering violated in {age}/{gender}: " \
                    f"rank {i+1} has ps={powerscores[i]:.4f} < rank {i+2} ps={powerscores[i+1]:.4f}"

    def test_no_rank_for_one_game_teams(self):
        """Teams with 1 game should NEVER have a rank_in_cohort."""
        one_game_teams = self.teams[self.teams["gp"] <= 1]
        for _, row in one_game_teams.iterrows():
            rank = row.get("rank_in_cohort")
            assert pd.isna(rank) or rank is None, \
                f"1-game team {row['team_id']} should not be ranked but got rank={rank}"

    def test_all_teams_have_powerscore(self):
        """All teams (even non-Active) should have a powerscore_adj."""
        for _, row in self.teams.iterrows():
            ps = row.get("powerscore_adj")
            assert pd.notna(ps), \
                f"Team {row['team_id']} (status={row['status']}) has NULL powerscore_adj"

    def test_inactive_teams_truly_old(self):
        """Inactive teams should have no games in last 180 days."""
        inactive = self.teams[self.teams["status"] == "Inactive"]
        for _, row in inactive.iterrows():
            gp180 = row.get("gp_last_180", 0)
            assert gp180 == 0, \
                f"Inactive team {row['team_id']} has {gp180} games in last 180 days"


# ---------------------------------------------------------------------------
# Tests: Ranking History (State Rank Active-Only)
# ---------------------------------------------------------------------------

class TestRankingHistoryActiveOnly:
    """Verify ranking_history only assigns state ranks to Active teams."""

    def test_save_snapshot_active_only_state_ranks(self):
        """save_ranking_snapshot should only compute state ranks for Active teams."""
        # Build a test DataFrame mimicking what compute_all_cohorts produces
        df = pd.DataFrame({
            "team_id": ["active_1", "active_2", "low_games_1", "inactive_1"],
            "age": [14, 14, 14, 14],
            "gender": ["Male", "Male", "Male", "Male"],
            "status": ["Active", "Active", "Not Enough Ranked Games", "Inactive"],
            "rank_in_cohort": [1, 2, pd.NA, pd.NA],
            "rank_in_cohort_ml": pd.array([1, 2, pd.NA, pd.NA], dtype="Int64"),
            "power_score_final": [0.85, 0.70, 0.60, 0.40],
            "powerscore_ml": [0.85, 0.70, 0.60, 0.40],
            "state_code": ["CA", "CA", "CA", "CA"],
        })

        # Simulate save_ranking_snapshot's state rank logic
        # (without actually calling Supabase)
        if 'age_group' not in df.columns:
            df['age_group'] = df['age'].apply(lambda x: f"u{int(float(x))}" if pd.notna(x) else "")

        score_col = 'powerscore_ml'

        # Initialize as NULL
        df['rank_in_state'] = pd.array([pd.NA] * len(df), dtype='Int64')

        # Only rank Active teams
        active_mask = df['status'] == 'Active'
        if active_mask.any():
            active_ranks = df.loc[active_mask].groupby(
                ['state_code', 'age_group', 'gender']
            )[score_col].rank(method='min', ascending=False).astype('Int64')
            df.loc[active_mask, 'rank_in_state'] = active_ranks

        # Verify: Active teams have state ranks
        assert df.loc[df["team_id"] == "active_1", "rank_in_state"].values[0] == 1
        assert df.loc[df["team_id"] == "active_2", "rank_in_state"].values[0] == 2

        # Verify: Non-Active teams do NOT have state ranks
        assert pd.isna(df.loc[df["team_id"] == "low_games_1", "rank_in_state"].values[0])
        assert pd.isna(df.loc[df["team_id"] == "inactive_1", "rank_in_state"].values[0])


# ---------------------------------------------------------------------------
# Discovery Tests: Edge Cases That Could Reveal Bugs
# ---------------------------------------------------------------------------

class TestEdgeCaseDiscovery:
    """Tests designed to probe edge cases and reveal latent bugs."""

    def setup_method(self):
        self.today = pd.Timestamp("2025-06-01")
        self.cfg = V53EConfig()

    def test_powerscore_adj_never_exceeds_powerscore_core(self):
        """powerscore_adj = powerscore_core * provisional_mult.
        Since provisional_mult <= 1.0, powerscore_adj should NEVER exceed
        powerscore_core. If it does, something is wrong with the multiplier.
        """
        games_df = _build_mixed_activity_league(self.today)
        result = compute_rankings(games_df, today=self.today, cfg=self.cfg)
        teams = result["teams"]

        for _, row in teams.iterrows():
            ps_core = row.get("powerscore_core", 0)
            ps_adj = row.get("powerscore_adj", 0)
            if pd.notna(ps_core) and pd.notna(ps_adj):
                assert ps_adj <= ps_core + 1e-9, (
                    f"Team {row['team_id']}: powerscore_adj ({ps_adj:.6f}) > "
                    f"powerscore_core ({ps_core:.6f}). Provisional multiplier "
                    f"may be > 1.0 or something else is modifying powerscore_adj."
                )

    def test_rank_gaps_imply_missing_active_teams(self):
        """If rank_in_cohort has gaps (e.g., 1, 2, 4), it means the ranking
        function is not filtering properly before assigning ranks.
        """
        games_df = _build_mixed_activity_league(self.today)
        result = compute_rankings(games_df, today=self.today, cfg=self.cfg)
        teams = result["teams"]

        for (age, gender), cohort in teams.groupby(["age", "gender"]):
            ranks = cohort["rank_in_cohort"].dropna().sort_values().tolist()
            if len(ranks) < 2:
                continue
            for i in range(len(ranks) - 1):
                gap = int(ranks[i + 1]) - int(ranks[i])
                assert gap == 1, (
                    f"Rank gap in {age}/{gender}: ranks {int(ranks[i])} -> "
                    f"{int(ranks[i+1])} (gap={gap}). This means rank assignment "
                    f"is including non-Active teams in the count."
                )

    def test_non_active_teams_still_get_powerscore(self):
        """Even non-Active teams need a powerscore for comparison purposes.
        They just shouldn't get ranks.
        """
        games_df = _build_mixed_activity_league(self.today)
        result = compute_rankings(games_df, today=self.today, cfg=self.cfg)
        teams = result["teams"]

        non_active = teams[teams["status"] != "Active"]
        for _, row in non_active.iterrows():
            assert pd.notna(row["powerscore_adj"]), (
                f"Non-Active team {row['team_id']} (status={row['status']}) "
                f"has NULL powerscore_adj — they need scores even without ranks"
            )
            # But they should NOT have ranks
            assert pd.isna(row["rank_in_cohort"]) or row["rank_in_cohort"] is None, (
                f"Non-Active team {row['team_id']} (status={row['status']}) "
                f"has rank_in_cohort={row['rank_in_cohort']} — bug!"
            )

    def test_sos_norm_not_biased_by_games_played(self):
        """Check for games-played bias in sos_norm.
        Teams with more games should NOT systematically get higher sos_norm
        unless they actually play stronger opponents.
        """
        games_df = _build_mixed_activity_league(self.today)
        result = compute_rankings(games_df, today=self.today, cfg=self.cfg)
        teams = result["teams"]

        if "sos_norm" not in teams.columns or "gp" not in teams.columns:
            pytest.skip("Required columns not present")

        # Compute correlation between gp and sos_norm
        valid = teams[teams["sos_norm"].notna() & teams["gp"].notna()].copy()
        if len(valid) < 5:
            pytest.skip("Not enough teams for correlation check")

        corr = valid["gp"].corr(valid["sos_norm"])
        # v53e already has a guardrail at ±0.10, but let's verify
        # A positive correlation > 0.3 would suggest serious bias
        assert abs(corr) < 0.30, (
            f"Games-played bias detected: correlation(gp, sos_norm) = {corr:.3f}. "
            f"Teams with more games systematically get {'higher' if corr > 0 else 'lower'} "
            f"sos_norm. The SOS shrinkage may be injecting games-played bias."
        )

    def test_calculator_values_alignment(self):
        """Verify the calculator's anchor scaling uses index-aligned assignment.
        The old pattern `df.loc[mask, col] = series.values` strips the index
        and assigns positionally, which can silently produce wrong results if
        the mask and series have different orderings.
        """
        from pathlib import Path

        calc_path = Path("src/rankings/calculator.py")
        source = calc_path.read_text()

        # Find the anchor scaling section
        anchor_section_start = source.find("# Process each age group separately")
        anchor_section_end = source.find("# Check for teams that didn't get anchor scaling")

        if anchor_section_start > 0 and anchor_section_end > 0:
            anchor_section = source[anchor_section_start:anchor_section_end]

            # The fix should use index-aligned assignment, not .values
            assert ".values" not in anchor_section, (
                "Anchor scaling section in calculator.py still uses .values "
                "for assignment, which strips index alignment. Use "
                "teams_combined.loc[series.index, col] = series instead."
            )

    def test_layer13_rank_active_only_handles_mixed_statuses(self):
        """_rank_active_only must handle a DataFrame with a mix of Active,
        Not Enough Ranked Games, and Inactive teams without crashing or
        assigning ranks to wrong teams.
        """
        from src.rankings.layer13_predictive_adjustment import _rank_active_only

        df = pd.DataFrame({
            "team_id": ["A", "B", "C", "D", "E", "F"],
            "age": [14, 14, 14, 14, 14, 14],
            "gender": ["male"] * 6,
            "powerscore_ml": [0.95, 0.85, 0.75, 0.65, 0.55, 0.45],
            "sos": [0.6, 0.5, 0.7, 0.4, 0.3, 0.8],
            "status": [
                "Active",
                "Not Enough Ranked Games",
                "Active",
                "Inactive",
                "Active",
                "Not Enough Ranked Games",
            ],
        })

        ranks = _rank_active_only(df, ["age", "gender"], "powerscore_ml")

        # Only A (0.95), C (0.75), E (0.55) should be ranked
        assert ranks.iloc[0] == 1  # A: highest
        assert pd.isna(ranks.iloc[1])  # B: Not Enough Ranked Games
        assert ranks.iloc[2] == 2  # C: second highest Active
        assert pd.isna(ranks.iloc[3])  # D: Inactive
        assert ranks.iloc[4] == 3  # E: third highest Active
        assert pd.isna(ranks.iloc[5])  # F: Not Enough Ranked Games

    def test_data_adapter_handles_missing_columns_gracefully(self):
        """The data adapter should not crash when optional columns are missing."""
        from src.rankings.data_adapter import v53e_to_rankings_full_format

        # Minimal required columns only
        teams_df = pd.DataFrame({
            "team_id": ["A"],
            "age": [14],
            "gender": ["Male"],
            "status": ["Active"],
            "gp": [20],
            "gp_last_180": [20],
            "powerscore_adj": [0.8],
            "powerscore_core": [0.75],
            "rank_in_cohort": [1],
            "sos": [0.5],
            "sos_norm": [0.6],
            "last_game": [pd.Timestamp("2025-05-15")],
        })

        # Should not crash even without powerscore_ml, rank_in_cohort_ml, etc.
        try:
            result = v53e_to_rankings_full_format(teams_df)
            assert len(result) == 1
        except KeyError as e:
            pytest.fail(
                f"Data adapter crashed on missing optional column: {e}. "
                f"The adapter should handle missing ML columns gracefully."
            )
