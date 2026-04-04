"""
Tests for league-aware SCF bubble detection in Glicko-2 engine.

Verifies that compute_scf() detects closed-league ecosystems (e.g., cross-state
ECNL_RL play) and dampens mu/SOS accordingly.
"""

import pandas as pd
import pytest

from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import compute_scf


def _make_games(team_id: str, opp_ids: list[str]) -> pd.DataFrame:
    """Build a simple games DataFrame for one team."""
    rows = []
    for i, opp in enumerate(opp_ids):
        rows.append({"team_id": team_id, "opp_id": opp, "gf": 3, "ga": 1})
        rows.append({"team_id": opp, "opp_id": team_id, "gf": 1, "ga": 3})
    return pd.DataFrame(rows)


class TestLeagueBubbleSCF:
    """Verify league diversity affects SCF."""

    def test_single_league_opponents_get_low_scf(self):
        """Team with all opponents in one league → league_scf = 0.5."""
        cfg = GlickoConfig()
        opps = [f"opp_{i}" for i in range(10)]
        games = _make_games("team_a", opps)

        team_state_map = {"team_a": "NE"}
        for i, opp in enumerate(opps):
            # Spread across 5 states to ensure state_scf is high
            team_state_map[opp] = ["CT", "MA", "NY", "PA", "NJ"][i % 5]

        ratings = {t: (1500.0, 200.0, 0.06) for t in ["team_a"] + opps}

        # All opponents in ECNL_RL
        tier_league_map = {opp: "ECNL_RL" for opp in opps}

        scf_data = compute_scf(games, team_state_map, ratings, cfg, tier_league_map=tier_league_map)
        team_scf = scf_data["team_a"]

        # All ECNL_RL → all "lower" family → 1 unique family
        assert team_scf["unique_leagues"] == 1
        assert team_scf["league_scf"] == cfg.SCF_LEAGUE_FLOOR  # 0.5
        assert team_scf["scf"] <= 0.5  # league_scf restricts overall
        assert team_scf["dominant_opp_league"] == "lower"
        assert team_scf["dominant_opp_league_share"] == 1.0

    def test_cross_family_opponents_get_high_scf(self):
        """Team with opponents from both top and lower families → league_scf = 1.0."""
        cfg = GlickoConfig()
        # Mix of top-tier (ECNL, GA) and lower-tier (DPL) → 2 families
        opps = ["opp_ecnl", "opp_ga", "opp_dpl", "opp_ecnl2", "opp_dpl2"]
        games = _make_games("team_a", opps)

        team_state_map = {"team_a": "AZ", "opp_ecnl": "CA", "opp_ga": "TX",
                          "opp_dpl": "FL", "opp_ecnl2": "NY", "opp_dpl2": "OH"}
        ratings = {t: (1500.0, 200.0, 0.06) for t in ["team_a"] + opps}
        tier_league_map = {"opp_ecnl": "ECNL", "opp_ga": "GA", "opp_dpl": "DPL",
                           "opp_ecnl2": "ECNL", "opp_dpl2": "DPL"}

        scf_data = compute_scf(games, team_state_map, ratings, cfg, tier_league_map=tier_league_map)
        team_scf = scf_data["team_a"]

        assert team_scf["unique_leagues"] == 2  # 2 families: top + lower
        assert team_scf["league_scf"] == 1.0

    def test_same_family_different_leagues_no_diversity(self):
        """ASPIRE + ECNL_RL + DPL + NL are all 'lower' family — NOT diverse."""
        cfg = GlickoConfig()
        opps = [f"opp_{i}" for i in range(8)]
        games = _make_games("team_a", opps)

        team_state_map = {"team_a": "TX"}
        for i, opp in enumerate(opps):
            team_state_map[opp] = ["CA", "FL", "NY", "OH", "GA", "IL", "PA", "NJ"][i]
        ratings = {t: (1500.0, 200.0, 0.06) for t in ["team_a"] + opps}

        # All lower-tier leagues — same family
        tier_league_map = {
            "opp_0": "ASPIRE", "opp_1": "ASPIRE", "opp_2": "ECNL_RL",
            "opp_3": "ECNL_RL", "opp_4": "DPL", "opp_5": "NL",
            "opp_6": "NPL", "opp_7": "EA",
        }

        scf_data = compute_scf(games, team_state_map, ratings, cfg, tier_league_map=tier_league_map)
        team_scf = scf_data["team_a"]

        assert team_scf["unique_leagues"] == 1  # all "lower" family
        assert team_scf["league_scf"] == cfg.SCF_LEAGUE_FLOOR  # 0.5

    def test_concentration_penalty_steep(self):
        """9 lower-tier + 1 top-tier → 90% concentration → steep penalty."""
        cfg = GlickoConfig()
        opps = [f"opp_{i}" for i in range(10)]
        games = _make_games("team_a", opps)

        team_state_map = {"team_a": "AZ"}
        for i, opp in enumerate(opps):
            team_state_map[opp] = ["CA", "TX", "FL", "NY", "GA"][i % 5]

        ratings = {t: (1500.0, 200.0, 0.06) for t in ["team_a"] + opps}

        # 9 ECNL_RL (lower) + 1 ECNL (top) → 90% lower-family concentration
        tier_league_map = {opp: "ECNL_RL" for opp in opps[:9]}
        tier_league_map[opps[9]] = "ECNL"

        scf_data = compute_scf(games, team_state_map, ratings, cfg, tier_league_map=tier_league_map)
        team_scf = scf_data["team_a"]

        assert team_scf["unique_leagues"] == 2  # 2 families
        assert team_scf["dominant_opp_league_share"] == 0.9
        # Concentration penalty: 1.0 - 2.0 * (0.9 - 0.65) = 1.0 - 0.50 = 0.50
        # league_count_scf: 2/2 = 1.0
        # league_scf = max(0.5, min(1.0, 0.50)) = 0.50
        assert team_scf["league_scf"] == pytest.approx(0.50, abs=0.01)

    def test_no_tier_league_map_backward_compatible(self):
        """Without tier_league_map, SCF is state-only (unchanged)."""
        cfg = GlickoConfig()
        opps = ["opp_1", "opp_2"]
        games = _make_games("team_a", opps)

        team_state_map = {"team_a": "AZ", "opp_1": "CA", "opp_2": "TX"}
        ratings = {t: (1500.0, 200.0, 0.06) for t in ["team_a", "opp_1", "opp_2"]}

        scf_with = compute_scf(games, team_state_map, ratings, cfg, tier_league_map={})
        scf_without = compute_scf(games, team_state_map, ratings, cfg, tier_league_map=None)

        assert scf_with["team_a"]["scf"] == scf_without["team_a"]["scf"]
        assert scf_without["team_a"]["league_scf"] == 1.0

    def test_null_league_opponents_dont_inflate_diversity(self):
        """Opponents with no league in tier_league_map don't count as a unique league."""
        cfg = GlickoConfig()
        opps = ["opp_rl_1", "opp_rl_2", "opp_unknown"]
        games = _make_games("team_a", opps)

        team_state_map = {"team_a": "AZ", "opp_rl_1": "CA", "opp_rl_2": "TX", "opp_unknown": "FL"}
        ratings = {t: (1500.0, 200.0, 0.06) for t in ["team_a"] + opps}

        # Only 2 opponents have known leagues, both ECNL_RL
        tier_league_map = {"opp_rl_1": "ECNL_RL", "opp_rl_2": "ECNL_RL"}

        scf_data = compute_scf(games, team_state_map, ratings, cfg, tier_league_map=tier_league_map)
        team_scf = scf_data["team_a"]

        # opp_unknown not in tier_league_map → excluded from league diversity
        assert team_scf["unique_leagues"] == 1
        assert team_scf["league_scf"] == cfg.SCF_LEAGUE_FLOOR  # 0.5

    def test_top_tier_concentration_no_penalty(self):
        """Team playing mostly top-tier opponents should NOT be penalized.

        Penn Fusion scenario: 13 ECNL + 3 GA = all "top" family.
        Concentration in top tier is NOT a bubble — it's the strongest schedule.
        """
        cfg = GlickoConfig()
        opps = [f"opp_{i}" for i in range(10)]
        games = _make_games("team_a", opps)

        team_state_map = {"team_a": "PA"}
        for i, opp in enumerate(opps):
            team_state_map[opp] = ["CA", "TX", "FL", "NY", "GA"][i % 5]

        ratings = {t: (1500.0, 200.0, 0.06) for t in ["team_a"] + opps}

        # 8 ECNL + 2 GA → all "top" family → 100% concentration but NO penalty
        tier_league_map = {opp: "ECNL" for opp in opps[:8]}
        tier_league_map[opps[8]] = "GA"
        tier_league_map[opps[9]] = "GA"

        scf_data = compute_scf(games, team_state_map, ratings, cfg, tier_league_map=tier_league_map)
        team_scf = scf_data["team_a"]

        assert team_scf["dominant_opp_league"] == "top"
        assert team_scf["league_scf"] == 1.0  # NO penalty for top-tier concentration

    def test_league_scf_restricts_state_scf(self):
        """When state_scf = 1.0 but league_scf = 0.5, final scf = 0.5."""
        cfg = GlickoConfig()
        opps = [f"opp_{i}" for i in range(8)]
        games = _make_games("team_a", opps)

        # 8 different states → state_scf = min(8/4, 1.0) = 1.0
        states = ["CT", "MA", "NY", "PA", "NJ", "OH", "IL", "MI"]
        team_state_map = {"team_a": "NE"}
        for opp, st in zip(opps, states):
            team_state_map[opp] = st

        ratings = {t: (1500.0, 200.0, 0.06) for t in ["team_a"] + opps}

        # All same league → league_scf = 0.5
        tier_league_map = {opp: "ECNL_RL" for opp in opps}

        scf_data = compute_scf(games, team_state_map, ratings, cfg, tier_league_map=tier_league_map)
        team_scf = scf_data["team_a"]

        assert team_scf["unique_states"] >= 4  # state_scf would be 1.0
        assert team_scf["league_scf"] == 0.5
        assert team_scf["scf"] == 0.5  # min(1.0, 0.5)
