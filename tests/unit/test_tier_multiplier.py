"""Tests for league tier multiplier system."""

import pytest
from src.rankings.constants import (
    LEAGUE_MULTIPLIER_MALE,
    LEAGUE_MULTIPLIER_FEMALE,
    UNAFFILIATED_MULTIPLIER_MALE,
    UNAFFILIATED_MULTIPLIER_FEMALE,
    get_tier_multiplier,
)


class TestLeagueMultiplierMaps:
    """Verify per-league multiplier mappings."""

    def test_mls_next_hd_male_is_1(self):
        assert LEAGUE_MULTIPLIER_MALE["MLS_NEXT_HD"] == 1.00

    def test_ecnl_male_is_098(self):
        assert LEAGUE_MULTIPLIER_MALE["ECNL"] == 0.98

    def test_mls_next_ad_male_is_098(self):
        assert LEAGUE_MULTIPLIER_MALE["MLS_NEXT_AD"] == 0.98

    def test_ecnl_rl_male_is_095(self):
        assert LEAGUE_MULTIPLIER_MALE["ECNL_RL"] == 0.95

    def test_dpl_male_is_093(self):
        assert LEAGUE_MULTIPLIER_MALE["DPL"] == 0.93

    def test_ea2_male_is_091(self):
        assert LEAGUE_MULTIPLIER_MALE["EA2"] == 0.91

    def test_ecnl_female_is_1(self):
        assert LEAGUE_MULTIPLIER_FEMALE["ECNL"] == 1.00

    def test_ga_female_is_098(self):
        assert LEAGUE_MULTIPLIER_FEMALE["GA"] == 0.98

    def test_ecnl_rl_female_is_094(self):
        assert LEAGUE_MULTIPLIER_FEMALE["ECNL_RL"] == 0.94

    def test_dpl_female_is_093(self):
        assert LEAGUE_MULTIPLIER_FEMALE["DPL"] == 0.93

    def test_unaffiliated_male_is_097(self):
        assert UNAFFILIATED_MULTIPLIER_MALE == 0.97

    def test_unaffiliated_female_is_097(self):
        assert UNAFFILIATED_MULTIPLIER_FEMALE == 0.97


class TestGetTierMultiplier:
    """Verify the lookup function."""

    def test_mls_next_hd_male_returns_1(self):
        assert get_tier_multiplier("MLS_NEXT_HD", "Male") == 1.00

    def test_ecnl_male_returns_098(self):
        assert get_tier_multiplier("ECNL", "Male") == 0.98

    def test_mls_next_ad_male_returns_098(self):
        assert get_tier_multiplier("MLS_NEXT_AD", "Male") == 0.98

    def test_ecnl_rl_male_returns_095(self):
        assert get_tier_multiplier("ECNL_RL", "Male") == 0.95

    def test_dpl_female_returns_093(self):
        assert get_tier_multiplier("DPL", "Female") == 0.93

    def test_ga_female_returns_098(self):
        assert get_tier_multiplier("GA", "Female") == 0.98

    def test_none_male_returns_097(self):
        assert get_tier_multiplier(None, "Male") == 0.97

    def test_none_female_returns_097(self):
        assert get_tier_multiplier(None, "Female") == 0.97

    def test_unknown_league_male_returns_097(self):
        assert get_tier_multiplier("SOME_RANDOM", "Male") == 0.97

    def test_u12_returns_no_discount(self):
        assert get_tier_multiplier("ECNL_RL", "Male", age=12) == 1.0

    def test_u10_returns_no_discount(self):
        assert get_tier_multiplier("DPL", "Female", age=10) == 1.0

    def test_u13_returns_discount(self):
        assert get_tier_multiplier("ECNL_RL", "Male", age=13) == 0.95

    def test_u14_returns_discount(self):
        assert get_tier_multiplier("ECNL_RL", "Male", age=14) == 0.95

    def test_none_age_still_applies_discount(self):
        assert get_tier_multiplier("ECNL_RL", "Male", age=None) == 0.95


# ---------------------------------------------------------------------------
# Integration tests: v53e engine with tier multiplier
# ---------------------------------------------------------------------------

import pandas as pd
from src.etl.v53e import V53EConfig, compute_rankings


from tests.conftest import make_game_pair


def _build_tier_test_league():
    """Two isolated mini-leagues with identical scores.
    League A (ECNL -- Tier 1): teams A1-A4
    League B (ECNL_RL -- Tier 2): teams B1-B4
    """
    today = pd.Timestamp("2026-03-01")
    rows = []
    gid = 0
    for prefix, teams in [("A", ["A1", "A2", "A3", "A4"]),
                           ("B", ["B1", "B2", "B3", "B4"])]:
        for i, home in enumerate(teams):
            for away in teams[i + 1:]:
                gid += 1
                date = today - pd.Timedelta(days=gid)
                if home == f"{prefix}1":
                    hs, as_ = 4, 0
                elif away == f"{prefix}1":
                    hs, as_ = 0, 4
                else:
                    hs, as_ = 2, 1
                rows.extend(make_game_pair(str(gid), date, home, away, hs, as_))
    return pd.DataFrame(rows)


class TestV53ETierMultiplier:
    def test_tier2_team_has_lower_sos_than_tier1_equivalent(self):
        """B1 (Tier 2) should have lower SOS than A1 (Tier 1) with identical records."""
        cfg = V53EConfig()
        games = _build_tier_test_league()
        tier_league_map = {}
        for t in ["A1", "A2", "A3", "A4"]:
            tier_league_map[t] = "ECNL"
        for t in ["B1", "B2", "B3", "B4"]:
            tier_league_map[t] = "ECNL_RL"

        result = compute_rankings(games, cfg=cfg, tier_league_map=tier_league_map)
        teams = result["teams"]
        a1 = teams[teams["team_id"] == "A1"].iloc[0]
        b1 = teams[teams["team_id"] == "B1"].iloc[0]
        assert b1["sos"] < a1["sos"], (
            f"B1 SOS ({b1['sos']:.4f}) should be lower than A1 SOS ({a1['sos']:.4f})"
        )

    def test_no_tier_map_means_no_change(self):
        """Without tier_league_map (None), SOS should be unaffected."""
        cfg = V53EConfig()
        games = _build_tier_test_league()
        result_a = compute_rankings(games, cfg=cfg)
        result_b = compute_rankings(games, cfg=cfg, tier_league_map=None)
        teams_a = result_a["teams"].set_index("team_id")
        teams_b = result_b["teams"].set_index("team_id")
        for tid in ["A1", "B1"]:
            assert abs(teams_a.loc[tid, "sos"] - teams_b.loc[tid, "sos"]) < 1e-9


# ---------------------------------------------------------------------------
# Integration tests: Glicko-2 engine compute_sos with tier multiplier
# ---------------------------------------------------------------------------

from src.etl.glicko_engine import compute_sos
from src.etl.glicko_config import GlickoConfig
import numpy as np


class TestGlickoTierMultiplier:
    def test_tier2_opponents_reduce_sos(self):
        """SOS should be lower when opponents are Tier 2."""
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-03-01")
        games_rows = []
        for i, opp in enumerate(["T2", "T3", "T4"]):
            date = today - pd.Timedelta(days=i + 1)
            games_rows.append({"team_id": "T1", "opp_id": opp, "gf": 3, "ga": 1,
                               "date": date, "age": 14, "gender": "male"})
            games_rows.append({"team_id": opp, "opp_id": "T1", "gf": 1, "ga": 3,
                               "date": date, "age": 14, "gender": "male"})
        games_df = pd.DataFrame(games_rows)
        ratings = {
            "T1": (1600.0, 200.0, 0.06),
            "T2": (1550.0, 200.0, 0.06),
            "T3": (1500.0, 200.0, 0.06),
            "T4": (1450.0, 200.0, 0.06),
        }

        sos_no_tier = compute_sos(games_df, ratings, cfg, today)
        t1_sos_no = sos_no_tier[sos_no_tier["team_id"] == "T1"]["sos_raw"].iloc[0]

        tier_league_map = {"T2": "ECNL_RL", "T3": "ECNL_RL", "T4": "ECNL_RL"}
        sos_with_tier = compute_sos(games_df, ratings, cfg, today,
                                     tier_league_map=tier_league_map, cohort_gender="Male")
        t1_sos_with = sos_with_tier[sos_with_tier["team_id"] == "T1"]["sos_raw"].iloc[0]

        assert t1_sos_with < t1_sos_no, (
            f"SOS with Tier 2 opponents ({t1_sos_with:.1f}) should be lower than "
            f"without tier adjustment ({t1_sos_no:.1f})"
        )

    def test_no_tier_map_is_backward_compatible(self):
        """compute_sos without tier args should produce identical results."""
        cfg = GlickoConfig()
        today = pd.Timestamp("2026-03-01")
        games_rows = []
        for i, opp in enumerate(["T2", "T3"]):
            date = today - pd.Timedelta(days=i + 1)
            games_rows.append({"team_id": "T1", "opp_id": opp, "gf": 2, "ga": 1,
                               "date": date, "age": 14, "gender": "male"})
            games_rows.append({"team_id": opp, "opp_id": "T1", "gf": 1, "ga": 2,
                               "date": date, "age": 14, "gender": "male"})
        games_df = pd.DataFrame(games_rows)
        ratings = {"T1": (1500.0, 200.0, 0.06), "T2": (1500.0, 200.0, 0.06),
                   "T3": (1500.0, 200.0, 0.06)}

        sos_default = compute_sos(games_df, ratings, cfg, today)
        sos_none = compute_sos(games_df, ratings, cfg, today, tier_league_map=None)

        t1_default = sos_default[sos_default["team_id"] == "T1"]["sos_raw"].iloc[0]
        t1_none = sos_none[sos_none["team_id"] == "T1"]["sos_raw"].iloc[0]
        assert abs(t1_default - t1_none) < 1e-9
