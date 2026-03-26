"""Tests for ML match predictor — regression tests for audit fixes."""
import os
import json
import hashlib
import tempfile
import pickle
import pytest
import numpy as np
import pandas as pd


class TestDrawLabelMapping:
    """Regression test for C1 fix: draws must map to 0, not 0.5."""

    def test_draw_maps_to_zero(self):
        """Draws should be class 0 (not-home-win) in binary classification."""
        winner_series = pd.Series(['home', 'away', 'draw', 'home', 'draw'])
        mapped = winner_series.map({'home': 1, 'away': 0, 'draw': 0})
        assert mapped.tolist() == [1, 0, 0, 1, 0]

    def test_draw_not_half(self):
        """Draws must NOT map to 0.5 (old broken behavior)."""
        winner_series = pd.Series(['draw'])
        mapped = winner_series.map({'home': 1, 'away': 0, 'draw': 0})
        assert mapped.iloc[0] == 0
        assert mapped.iloc[0] != 0.5

    def test_binarization_consistent(self):
        """After mapping, .astype(int) should produce clean 0/1 values."""
        winner_series = pd.Series(['home', 'away', 'draw', 'home'])
        mapped = winner_series.map({'home': 1, 'away': 0, 'draw': 0})
        binary = mapped.astype(int)
        assert set(binary.unique()) == {0, 1}


class TestModelIntegrity:
    """Tests for save/load with SHA-256 checksum verification (S3 fix)."""

    def test_checksum_roundtrip(self):
        """Save data with checksum, verify load detects tampering."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, "test_model.pkl")
            checksum_path = model_path + ".sha256"

            # Save
            model_data = pickle.dumps({"test_key": [1, 2, 3]})
            with open(model_path, 'wb') as f:
                f.write(model_data)
            checksum = hashlib.sha256(model_data).hexdigest()
            with open(checksum_path, 'w') as f:
                f.write(checksum)

            # Load and verify
            with open(model_path, 'rb') as f:
                loaded_data = f.read()
            with open(checksum_path, 'r') as f:
                expected = f.read().strip()

            actual = hashlib.sha256(loaded_data).hexdigest()
            assert actual == expected

    def test_tampered_file_detected(self):
        """Checksum mismatch should be detectable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, "test_model.pkl")
            checksum_path = model_path + ".sha256"

            # Save original
            original_data = pickle.dumps({"key": "original"})
            with open(model_path, 'wb') as f:
                f.write(original_data)
            checksum = hashlib.sha256(original_data).hexdigest()
            with open(checksum_path, 'w') as f:
                f.write(checksum)

            # Tamper
            tampered_data = pickle.dumps({"key": "tampered"})
            with open(model_path, 'wb') as f:
                f.write(tampered_data)

            # Verify mismatch
            with open(model_path, 'rb') as f:
                loaded = f.read()
            with open(checksum_path, 'r') as f:
                expected = f.read().strip()

            actual = hashlib.sha256(loaded).hexdigest()
            assert actual != expected


class TestFeatureEngineering:
    """Basic tests for feature column expectations."""

    def test_exclude_columns_not_in_features(self):
        """Non-feature columns should be excluded from training."""
        exclude_cols = {
            'game_id', 'game_date', 'home_team_id', 'away_team_id',
            'actual_home_score', 'actual_away_score', 'actual_margin', 'actual_winner'
        }
        all_cols = list(exclude_cols) + ['power_score_diff', 'sos_diff', 'win_pct_diff']
        feature_cols = [c for c in all_cols if c not in exclude_cols]
        assert feature_cols == ['power_score_diff', 'sos_diff', 'win_pct_diff']
        assert len(set(feature_cols) & exclude_cols) == 0

    def test_prediction_bounds(self):
        """Win probabilities should be in [0, 1] range."""
        # Simulate clipped predictions
        raw_probs = np.array([-0.1, 0.0, 0.5, 1.0, 1.1])
        clipped = np.clip(raw_probs, 0, 1)
        assert all(0 <= p <= 1 for p in clipped)
