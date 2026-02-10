"""
Unit tests for SOS (Strength of Schedule) calculations and validation
"""
import pytest
import pandas as pd
import numpy as np
from src.etl.v53e import V53EConfig, compute_rankings


class TestSOSConfiguration:
    """Test SOS configuration consistency"""

    def test_config_has_critical_sos_parameters(self):
        """Verify V53EConfig has all critical SOS parameters"""
        cfg = V53EConfig()

        # Verify critical SOS parameters exist
        assert hasattr(cfg, 'SOS_ITERATIONS')
        assert hasattr(cfg, 'SOS_TRANSITIVITY_LAMBDA')
        assert hasattr(cfg, 'SOS_REPEAT_CAP')
        assert hasattr(cfg, 'UNRANKED_SOS_BASE')

    def test_sos_iterations_is_one(self):
        """Verify single-pass SOS (no transitive propagation)"""
        cfg = V53EConfig()
        assert cfg.SOS_ITERATIONS == 1, "SOS should use 1 iteration (direct only, no transitive)"

    def test_sos_transitivity_lambda_is_zero(self):
        """Verify SOS transitivity is disabled (prevents closed-league inflation)"""
        cfg = V53EConfig()
        assert cfg.SOS_TRANSITIVITY_LAMBDA == 0.0, \
            "SOS_TRANSITIVITY_LAMBDA should be 0.0 (pure direct, no transitive)"

    def test_sos_repeat_cap_is_two(self):
        """Verify repeat cap limits to top 2 games per opponent (prevents regional rival dominance)"""
        cfg = V53EConfig()
        assert cfg.SOS_REPEAT_CAP == 2, "SOS repeat cap should be 2"

    def test_unranked_sos_base_valid(self):
        """Verify unranked opponent SOS base is reasonable"""
        cfg = V53EConfig()
        assert 0.0 <= cfg.UNRANKED_SOS_BASE <= 1.0, \
            "UNRANKED_SOS_BASE must be between 0 and 1"
        assert cfg.UNRANKED_SOS_BASE == 0.35, \
            "UNRANKED_SOS_BASE should be 0.35"


class TestPowerScoreWeights:
    """Test PowerScore component weights"""

    def test_weights_sum_to_one(self):
        """Verify OFF_WEIGHT + DEF_WEIGHT + SOS_WEIGHT = 1.0"""
        cfg = V53EConfig()

        total_weight = cfg.OFF_WEIGHT + cfg.DEF_WEIGHT + cfg.SOS_WEIGHT
        assert abs(total_weight - 1.0) < 0.0001, \
            f"PowerScore weights must sum to 1.0, got {total_weight}"

    def test_sos_weight_is_thirty_percent(self):
        """Verify SOS has 30% weight in PowerScore (reduced from 50% to avoid double-counting
        with opponent-adjusted OFF/DEF)"""
        cfg = V53EConfig()
        assert cfg.SOS_WEIGHT == 0.30, "SOS should have 30% weight"

    def test_off_def_weights_balanced(self):
        """Verify offense and defense have equal weights"""
        cfg = V53EConfig()
        assert cfg.OFF_WEIGHT == cfg.DEF_WEIGHT, \
            "Offense and defense should have equal weights"
        assert cfg.OFF_WEIGHT == 0.35, "Offense weight should be 35%"
        assert cfg.DEF_WEIGHT == 0.35, "Defense weight should be 35%"

    def test_off_def_have_highest_weight(self):
        """Verify OFF/DEF each have higher weight than SOS (since OFF/DEF are opponent-adjusted)"""
        cfg = V53EConfig()
        assert cfg.OFF_WEIGHT > cfg.SOS_WEIGHT, \
            "Offense weight should be greater than SOS weight"
        assert cfg.DEF_WEIGHT > cfg.SOS_WEIGHT, \
            "Defense weight should be greater than SOS weight"


class TestSOSValueRanges:
    """Test SOS calculation output ranges"""

    @pytest.fixture
    def sample_games_df(self):
        """Create sample games data for testing"""
        # Create a small dataset with known teams
        data = {
            'game_id': ['g1', 'g2', 'g3', 'g4', 'g5', 'g6'],
            'date': pd.to_datetime(['2024-01-01'] * 6),
            'team_id': ['t1', 't1', 't2', 't2', 't3', 't3'],
            'opp_id': ['t2', 't3', 't1', 't3', 't1', 't2'],
            'age': [12, 12, 12, 12, 12, 12],
            'gender': ['M', 'M', 'M', 'M', 'M', 'M'],
            'opp_age': [12, 12, 12, 12, 12, 12],
            'opp_gender': ['M', 'M', 'M', 'M', 'M', 'M'],
            'gf': [3, 2, 1, 2, 1, 3],
            'ga': [1, 1, 3, 1, 2, 2],
        }
        return pd.DataFrame(data)

    def test_sos_raw_in_valid_range(self, sample_games_df):
        """Verify raw SOS values are between 0 and 1"""
        cfg = V53EConfig()
        result = compute_rankings(
            games_df=sample_games_df,
            cfg=cfg,
            today=pd.Timestamp('2024-06-01')
        )

        teams_df = result['teams']

        # Check that sos column exists
        assert 'sos' in teams_df.columns, "SOS column should exist in output"

        # Check all SOS values are in valid range
        sos_values = teams_df['sos'].dropna()
        assert len(sos_values) > 0, "Should have SOS values"
        assert (sos_values >= 0.0).all(), "All SOS values should be >= 0.0"
        assert (sos_values <= 1.0).all(), "All SOS values should be <= 1.0"

    def test_sos_norm_in_valid_range(self, sample_games_df):
        """Verify normalized SOS values are between 0 and 1"""
        cfg = V53EConfig()
        result = compute_rankings(
            games_df=sample_games_df,
            cfg=cfg,
            today=pd.Timestamp('2024-06-01')
        )

        teams_df = result['teams']

        # Check that sos_norm column exists
        assert 'sos_norm' in teams_df.columns, "SOS_NORM column should exist in output"

        # Check all SOS_NORM values are in valid range
        sos_norm_values = teams_df['sos_norm'].dropna()
        assert len(sos_norm_values) > 0, "Should have SOS_NORM values"
        assert (sos_norm_values >= 0.0).all(), "All SOS_NORM values should be >= 0.0"
        assert (sos_norm_values <= 1.0).all(), "All SOS_NORM values should be <= 1.0"

    def test_powerscore_uses_sos_norm(self, sample_games_df):
        """Verify PowerScore calculation uses sos_norm, not raw sos"""
        cfg = V53EConfig()
        result = compute_rankings(
            games_df=sample_games_df,
            cfg=cfg,
            today=pd.Timestamp('2024-06-01')
        )

        teams_df = result['teams']

        # Pick a team and verify the formula
        if len(teams_df) > 0:
            team = teams_df.iloc[0]

            # Calculate expected powerscore_core
            # Formula: OFF_WEIGHT*off_norm + DEF_WEIGHT*def_norm + SOS_WEIGHT*sos_norm + PERF_BLEND_WEIGHT*perf_centered
            expected_ps = (
                cfg.OFF_WEIGHT * team.get('off_norm', 0) +
                cfg.DEF_WEIGHT * team.get('def_norm', 0) +
                cfg.SOS_WEIGHT * team['sos_norm'] +  # Uses sos_norm!
                team.get('perf_centered', 0) * cfg.PERF_BLEND_WEIGHT  # Performance adjustment
            )

            actual_ps = team['powerscore_core']

            # Should match closely (allow small floating point differences)
            assert abs(expected_ps - actual_ps) < 0.01, \
                f"PowerScore formula mismatch: expected {expected_ps}, got {actual_ps}"


class TestSOSTransitivity:
    """Test SOS transitivity calculation"""

    def test_transitivity_weight_calculation(self):
        """Verify direct vs transitive weight split"""
        cfg = V53EConfig()

        lambda_val = cfg.SOS_TRANSITIVITY_LAMBDA
        direct_weight = 1 - lambda_val
        transitive_weight = lambda_val

        # Verify the weights sum to 1
        assert abs(direct_weight + transitive_weight - 1.0) < 0.0001, \
            "Direct + transitive weights should sum to 1.0"

        # Verify expected values for lambda=0.0 (transitive disabled)
        assert abs(direct_weight - 1.0) < 0.0001, \
            "Direct weight should be 100% when lambda=0.0"
        assert abs(transitive_weight - 0.0) < 0.0001, \
            "Transitive weight should be 0% when lambda=0.0"


class TestSOSDocumentation:
    """Test that configuration matches documentation"""

    def test_config_matches_documented_values(self):
        """Verify actual config matches SOS_FIELDS_EXPLANATION.md"""
        cfg = V53EConfig()

        # SOS_ITERATIONS = 1 (single-pass, no transitive)
        assert cfg.SOS_ITERATIONS == 1, \
            "SOS_ITERATIONS should be 1 (direct only)"

        # SOS_TRANSITIVITY_LAMBDA = 0.0 (disabled)
        assert cfg.SOS_TRANSITIVITY_LAMBDA == 0.0, \
            "SOS_TRANSITIVITY_LAMBDA should be 0.0 (disabled)"

        # From docs: SOS_REPEAT_CAP = 2 (reduced from 4 to prevent regional rival dominance)
        assert cfg.SOS_REPEAT_CAP == 2, \
            "SOS_REPEAT_CAP should be 2 as documented"

        # From docs: UNRANKED_SOS_BASE = 0.35
        assert cfg.UNRANKED_SOS_BASE == 0.35, \
            "UNRANKED_SOS_BASE should be 0.35 as documented"

        # SOS_WEIGHT = 0.30 (reduced from 50% since OFF/DEF are opponent-adjusted)
        assert cfg.SOS_WEIGHT == 0.30, \
            "SOS_WEIGHT should be 30%"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
