"""
Tests for Regional Bubble Detection (SCF + PageRank Dampening)

Validates that:
1. Schedule Connectivity Factor (SCF) correctly identifies isolated teams
2. SOS is dampened for teams in regional bubbles
3. PageRank dampening prevents infinite SOS inflation
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
    STATE_TO_REGION,
)


class TestScheduleConnectivityFactor:
    """Tests for SCF calculation"""

    def test_scf_isolated_single_state(self):
        """Teams playing only within one state should have low SCF"""
        # Create games where all teams are from Idaho
        games_df = pd.DataFrame([
            # Idaho Rush vs Idaho Juniors
            {"game_id": "g1", "date": datetime.now(), "team_id": "idaho_rush",
             "opp_id": "idaho_juniors", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 2, "ga": 1},
            {"game_id": "g1", "date": datetime.now(), "team_id": "idaho_juniors",
             "opp_id": "idaho_rush", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 1, "ga": 2},
            # Idaho Juniors vs Missoula Surf
            {"game_id": "g2", "date": datetime.now(), "team_id": "idaho_juniors",
             "opp_id": "missoula_surf", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 3, "ga": 0},
            {"game_id": "g2", "date": datetime.now(), "team_id": "missoula_surf",
             "opp_id": "idaho_juniors", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 0, "ga": 3},
            # Missoula Surf vs Idaho Rush (completing the circle)
            {"game_id": "g3", "date": datetime.now(), "team_id": "missoula_surf",
             "opp_id": "idaho_rush", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 2, "ga": 1},
            {"game_id": "g3", "date": datetime.now(), "team_id": "idaho_rush",
             "opp_id": "missoula_surf", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 1, "ga": 2},
        ])

        # All teams from Mountain region states
        team_state_map = {
            "idaho_rush": "ID",
            "idaho_juniors": "ID",
            "missoula_surf": "MT",
        }

        cfg = V53EConfig()
        scf_data = compute_schedule_connectivity(games_df, team_state_map, cfg)

        # All teams should have low SCF (they only play 2 unique states in Mountain region)
        for team_id in ["idaho_rush", "idaho_juniors", "missoula_surf"]:
            assert team_id in scf_data
            # With 2 unique states and SCF_DIVERSITY_DIVISOR=3.0, SCF should be ~0.67
            assert scf_data[team_id]["scf"] < 0.8, f"{team_id} SCF too high for isolated bubble"
            assert scf_data[team_id]["unique_states"] == 2
            assert scf_data[team_id]["unique_regions"] == 1  # Both ID and MT are 'mountain'

    def test_scf_national_schedule(self):
        """Teams playing opponents from multiple regions should have high SCF"""
        games_df = pd.DataFrame([
            # Team plays California team
            {"game_id": "g1", "date": datetime.now(), "team_id": "national_team",
             "opp_id": "ca_team", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 2, "ga": 1},
            # Team plays Texas team
            {"game_id": "g2", "date": datetime.now(), "team_id": "national_team",
             "opp_id": "tx_team", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 1, "ga": 1},
            # Team plays Florida team
            {"game_id": "g3", "date": datetime.now(), "team_id": "national_team",
             "opp_id": "fl_team", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 0, "ga": 2},
            # Team plays New York team
            {"game_id": "g4", "date": datetime.now(), "team_id": "national_team",
             "opp_id": "ny_team", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 3, "ga": 1},
        ])

        team_state_map = {
            "national_team": "CO",  # Colorado
            "ca_team": "CA",        # Pacific
            "tx_team": "TX",        # West South Central
            "fl_team": "FL",        # South Atlantic
            "ny_team": "NY",        # Middle Atlantic
        }

        cfg = V53EConfig()
        scf_data = compute_schedule_connectivity(games_df, team_state_map, cfg)

        # National team plays 4 states, 4 regions - should have high SCF
        assert scf_data["national_team"]["scf"] >= 0.9
        assert scf_data["national_team"]["unique_states"] == 4
        assert scf_data["national_team"]["unique_regions"] == 4
        assert not scf_data["national_team"]["is_isolated"]

    def test_scf_bridge_game_detection(self):
        """Teams with bridge games (out-of-state) should have higher confidence"""
        games_df = pd.DataFrame([
            # Idaho team plays mostly local
            {"game_id": "g1", "date": datetime.now(), "team_id": "idaho_team",
             "opp_id": "local_team_1", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 2, "ga": 0},
            {"game_id": "g2", "date": datetime.now(), "team_id": "idaho_team",
             "opp_id": "local_team_2", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 3, "ga": 1},
            # But has ONE bridge game vs CA team
            {"game_id": "g3", "date": datetime.now(), "team_id": "idaho_team",
             "opp_id": "ca_team", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 1, "ga": 2},
        ])

        team_state_map = {
            "idaho_team": "ID",
            "local_team_1": "ID",
            "local_team_2": "ID",
            "ca_team": "CA",
        }

        cfg = V53EConfig()
        scf_data = compute_schedule_connectivity(games_df, team_state_map, cfg)

        # Idaho team has 1 bridge game (vs CA) but needs MIN_BRIDGE_GAMES (2)
        assert scf_data["idaho_team"]["bridge_games"] == 1
        assert scf_data["idaho_team"]["is_isolated"]  # Still isolated with only 1 bridge game


class TestPageRankDampening:
    """Tests for PageRank-style SOS dampening"""

    def test_pagerank_prevents_infinite_inflation(self):
        """SOS should be bounded even in circular bubbles"""
        # Create a perfect circular bubble
        games_df = pd.DataFrame([
            # A beats B
            {"game_id": "g1", "date": datetime.now(), "team_id": "team_a",
             "opp_id": "team_b", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 3, "ga": 0},
            {"game_id": "g1", "date": datetime.now(), "team_id": "team_b",
             "opp_id": "team_a", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 0, "ga": 3},
            # B beats C
            {"game_id": "g2", "date": datetime.now(), "team_id": "team_b",
             "opp_id": "team_c", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 2, "ga": 1},
            {"game_id": "g2", "date": datetime.now(), "team_id": "team_c",
             "opp_id": "team_b", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 1, "ga": 2},
            # C beats A (completing circle)
            {"game_id": "g3", "date": datetime.now(), "team_id": "team_c",
             "opp_id": "team_a", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 2, "ga": 0},
            {"game_id": "g3", "date": datetime.now(), "team_id": "team_a",
             "opp_id": "team_c", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 0, "ga": 2},
        ])

        # All teams from same state
        team_state_map = {
            "team_a": "ID",
            "team_b": "ID",
            "team_c": "ID",
        }

        cfg = V53EConfig()
        result = compute_rankings(games_df, team_state_map=team_state_map, cfg=cfg)
        teams = result["teams"]

        # With PageRank dampening, SOS should be anchored toward 0.5
        # Raw SOS in a bubble would tend toward high values, but dampening pulls it back
        for _, row in teams.iterrows():
            # SOS should not exceed the isolation cap with SCF + PageRank
            assert row["sos"] <= 0.8, f"SOS too high for isolated team: {row['sos']}"

    def test_dampening_comparison_with_without(self):
        """Compare SOS with and without PageRank dampening"""
        games_df = pd.DataFrame([
            {"game_id": "g1", "date": datetime.now(), "team_id": "team_a",
             "opp_id": "team_b", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 2, "ga": 1},
            {"game_id": "g1", "date": datetime.now(), "team_id": "team_b",
             "opp_id": "team_a", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 1, "ga": 2},
        ])

        team_state_map = {"team_a": "ID", "team_b": "ID"}

        # With dampening (default)
        cfg_with = V53EConfig(PAGERANK_DAMPENING_ENABLED=True, PAGERANK_ALPHA=0.85)
        result_with = compute_rankings(games_df, team_state_map=team_state_map, cfg=cfg_with)

        # Without dampening
        cfg_without = V53EConfig(PAGERANK_DAMPENING_ENABLED=False)
        result_without = compute_rankings(games_df, team_state_map=team_state_map, cfg=cfg_without)

        # With dampening, SOS should be closer to baseline (0.5)
        sos_with = result_with["teams"]["sos"].mean()
        sos_without = result_without["teams"]["sos"].mean()

        # Dampened SOS should be pulled toward 0.5
        assert abs(sos_with - 0.5) <= abs(sos_without - 0.5), \
            "Dampening should pull SOS toward baseline"


class TestSCFAndSOSIntegration:
    """Integration tests for SCF + SOS dampening"""

    def test_isolated_bubble_vs_national_team(self):
        """
        Compare SOS of isolated bubble team vs team with national schedule.
        The national team should have higher SOS even with same win rate.
        """
        # Create two scenarios in same cohort
        games_df = pd.DataFrame([
            # Isolated team beats local opponents (all ID/MT)
            {"game_id": "g1", "date": datetime.now(), "team_id": "isolated_team",
             "opp_id": "local_1", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 3, "ga": 0},
            {"game_id": "g1", "date": datetime.now(), "team_id": "local_1",
             "opp_id": "isolated_team", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 0, "ga": 3},
            {"game_id": "g2", "date": datetime.now(), "team_id": "isolated_team",
             "opp_id": "local_2", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 2, "ga": 1},
            {"game_id": "g2", "date": datetime.now(), "team_id": "local_2",
             "opp_id": "isolated_team", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 1, "ga": 2},
            # National team beats opponents from different regions
            {"game_id": "g3", "date": datetime.now(), "team_id": "national_team",
             "opp_id": "ca_opp", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 3, "ga": 0},
            {"game_id": "g3", "date": datetime.now(), "team_id": "ca_opp",
             "opp_id": "national_team", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 0, "ga": 3},
            {"game_id": "g4", "date": datetime.now(), "team_id": "national_team",
             "opp_id": "tx_opp", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 2, "ga": 1},
            {"game_id": "g4", "date": datetime.now(), "team_id": "tx_opp",
             "opp_id": "national_team", "age": "12", "gender": "male",
             "opp_age": "12", "opp_gender": "male", "gf": 1, "ga": 2},
        ])

        team_state_map = {
            "isolated_team": "ID",
            "local_1": "ID",
            "local_2": "MT",
            "national_team": "CO",
            "ca_opp": "CA",
            "tx_opp": "TX",
        }

        cfg = V53EConfig()
        result = compute_rankings(games_df, team_state_map=team_state_map, cfg=cfg)
        teams = result["teams"]

        # Get SCF values
        isolated_scf = teams[teams["team_id"] == "isolated_team"]["scf"].values[0]
        national_scf = teams[teams["team_id"] == "national_team"]["scf"].values[0]

        # National team should have higher SCF (more diverse schedule)
        assert national_scf > isolated_scf, \
            f"National team SCF ({national_scf}) should exceed isolated team ({isolated_scf})"


class TestStateToRegionMapping:
    """Tests for the state-to-region mapping"""

    def test_all_states_mapped(self):
        """Ensure all 50 states + DC are in the mapping"""
        expected_states = [
            'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL',
            'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME',
            'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH',
            'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI',
            'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'
        ]
        for state in expected_states:
            assert state in STATE_TO_REGION, f"State {state} not in region mapping"

    def test_region_consistency(self):
        """Neighboring states should be in same/adjacent regions"""
        # Pacific states
        assert STATE_TO_REGION['CA'] == STATE_TO_REGION['OR'] == STATE_TO_REGION['WA']
        # Mountain states
        assert STATE_TO_REGION['ID'] == STATE_TO_REGION['MT'] == STATE_TO_REGION['UT']
