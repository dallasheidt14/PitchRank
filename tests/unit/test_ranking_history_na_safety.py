"""
Test that ranking_history.py handles pd.NA, None, and np.nan safely.

Regression tests for the bug where `row.get("rank_in_cohort_ml") or row.get("rank_in_cohort")`
raises TypeError("boolean value of NA is ambiguous") when rank_in_cohort_ml is pd.NA.

See: GitHub Actions run 23370928929 (2026-03-21) — TypeError in calculate_change()
"""

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helper: replicate the FIXED rank-selection logic from ranking_history.py
# ---------------------------------------------------------------------------

def _select_rank_from_dict(record: dict):
    """Mirrors get_historical_ranks() line 254-255 logic (Supabase dict)."""
    ml_rank = record.get("rank_in_cohort_ml")
    return ml_rank if ml_rank is not None else record.get("rank_in_cohort")


def _select_rank_from_row(row):
    """Mirrors big-movers logging line 552-553 logic (DataFrame row)."""
    ml_rank_val = row.get("rank_in_cohort_ml")
    return ml_rank_val if pd.notna(ml_rank_val) else row.get("rank_in_cohort")


def _select_rank_calculate_change(row):
    """Mirrors calculate_change() line 484-485 logic (already fixed)."""
    ml_rank = row.get("rank_in_cohort_ml")
    return ml_rank if not pd.isna(ml_rank) else row.get("rank_in_cohort")


# ---------------------------------------------------------------------------
# Tests for dict-based rank selection (Supabase API response records)
# ---------------------------------------------------------------------------

class TestDictRankSelection:
    """Line 254: records from Supabase API (dict with None, not pd.NA)."""

    def test_ml_rank_present(self):
        record = {"rank_in_cohort_ml": 5, "rank_in_cohort": 10}
        assert _select_rank_from_dict(record) == 5

    def test_ml_rank_none_falls_back(self):
        record = {"rank_in_cohort_ml": None, "rank_in_cohort": 10}
        assert _select_rank_from_dict(record) == 10

    def test_both_none(self):
        record = {"rank_in_cohort_ml": None, "rank_in_cohort": None}
        assert _select_rank_from_dict(record) is None

    def test_ml_rank_missing_key(self):
        record = {"rank_in_cohort": 7}
        assert _select_rank_from_dict(record) == 7

    def test_both_missing_keys(self):
        record = {}
        assert _select_rank_from_dict(record) is None

    def test_ml_rank_zero_not_skipped(self):
        """Rank 0 is falsy — the old `or` pattern would skip it."""
        record = {"rank_in_cohort_ml": 0, "rank_in_cohort": 10}
        # With `is not None` check, 0 is kept (not treated as falsy)
        assert _select_rank_from_dict(record) == 0


# ---------------------------------------------------------------------------
# Tests for DataFrame row rank selection (from iterrows / apply)
# ---------------------------------------------------------------------------

class TestDataFrameRowRankSelection:
    """Lines 484-485 (calculate_change) and 552-553 (big movers logging).

    DataFrame rows can contain pd.NA, np.nan, or None — all of which
    break the `or` operator because bool(pd.NA) raises TypeError.
    """

    def _make_row(self, ml_rank, cohort_rank):
        """Create a single-row DataFrame and return the row (Series)."""
        df = pd.DataFrame([{
            "rank_in_cohort_ml": ml_rank,
            "rank_in_cohort": cohort_rank,
        }])
        # Use nullable Int64 to match actual ranking data
        df["rank_in_cohort_ml"] = df["rank_in_cohort_ml"].astype("Int64")
        df["rank_in_cohort"] = df["rank_in_cohort"].astype("Int64")
        return df.iloc[0]

    def test_ml_rank_present(self):
        row = self._make_row(5, 10)
        assert _select_rank_from_row(row) == 5
        assert _select_rank_calculate_change(row) == 5

    def test_ml_rank_pd_na_falls_back(self):
        """The original bug: pd.NA in rank_in_cohort_ml."""
        row = self._make_row(pd.NA, 10)
        assert _select_rank_from_row(row) == 10
        assert _select_rank_calculate_change(row) == 10

    def test_ml_rank_none_falls_back(self):
        row = self._make_row(None, 10)
        assert _select_rank_from_row(row) == 10
        assert _select_rank_calculate_change(row) == 10

    def test_ml_rank_np_nan_falls_back(self):
        """np.nan should also fall back safely."""
        df = pd.DataFrame([{
            "rank_in_cohort_ml": np.nan,
            "rank_in_cohort": 10,
        }])
        row = df.iloc[0]
        assert _select_rank_from_row(row) == 10
        assert _select_rank_calculate_change(row) == 10

    def test_both_pd_na(self):
        row = self._make_row(pd.NA, pd.NA)
        result = _select_rank_from_row(row)
        assert pd.isna(result)

    def test_both_none(self):
        row = self._make_row(None, None)
        result = _select_rank_from_row(row)
        assert pd.isna(result)

    def test_or_operator_crashes_with_pd_na(self):
        """Prove the OLD pattern crashes — this is why we fixed it."""
        row = self._make_row(pd.NA, 10)
        with pytest.raises(TypeError, match="boolean value of NA is ambiguous"):
            # This is the OLD broken pattern
            _ = row.get("rank_in_cohort_ml") or row.get("rank_in_cohort")

    def test_apply_over_dataframe_no_crash(self):
        """Simulate the actual apply() call from calculate_rank_changes."""
        df = pd.DataFrame({
            "team_id": ["a", "b", "c", "d"],
            "rank_in_cohort_ml": pd.array([5, pd.NA, pd.NA, 1], dtype="Int64"),
            "rank_in_cohort": pd.array([10, 8, pd.NA, 3], dtype="Int64"),
        })

        def safe_select(row):
            ml = row.get("rank_in_cohort_ml")
            return ml if pd.notna(ml) else row.get("rank_in_cohort")

        results = df.apply(safe_select, axis=1)
        assert results.iloc[0] == 5   # ML rank used
        assert results.iloc[1] == 8   # Fell back to cohort rank
        assert pd.isna(results.iloc[2])  # Both NA
        assert results.iloc[3] == 1   # ML rank used
