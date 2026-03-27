"""Shared utility functions for ranking calculations."""

from __future__ import annotations

import pandas as pd

from src.rankings.constants import SOS_ML_THRESHOLD_HIGH, SOS_ML_THRESHOLD_LOW


def sos_ml_blend(ps_adj: float, ps_ml: float, sos_norm: float) -> float:
    """Blend ML-adjusted PowerScore with baseline using SOS-conditioned scaling.

    Returns a score in [0, 1] where ML authority scales linearly from 0 to 1
    as sos_norm moves from SOS_ML_THRESHOLD_LOW to SOS_ML_THRESHOLD_HIGH.
    """
    ml_scale = max(0.0, min(1.0, (sos_norm - SOS_ML_THRESHOLD_LOW) / (SOS_ML_THRESHOLD_HIGH - SOS_ML_THRESHOLD_LOW)))
    ml_delta = ps_ml - ps_adj
    return max(0.0, min(1.0, ps_adj + ml_delta * ml_scale))


def normalize_gender(series: pd.Series) -> pd.Series:
    """Normalize gender labels: boys/girls → male/female."""
    return (
        series.astype(str)
        .str.lower()
        .str.strip()
        .replace(
            {
                "boys": "male",
                "boy": "male",
                "girls": "female",
                "girl": "female",
            }
        )
    )
