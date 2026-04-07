"""Shared utility functions for ranking calculations."""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from src.rankings.constants import SOS_ML_THRESHOLD_HIGH, SOS_ML_THRESHOLD_LOW


def sos_ml_blend(ps_adj: float, ps_ml: float, sos_norm: float) -> float:
    """Blend ML-adjusted PowerScore with baseline using SOS-conditioned scaling.

    Returns a score in [0, 1] where ML authority scales linearly from 0 to 1
    as sos_norm moves from SOS_ML_THRESHOLD_LOW to SOS_ML_THRESHOLD_HIGH.

    Negative ML corrections (overrated teams) always apply at full authority.
    Positive corrections (inflation) are fully gated by SOS.
    """
    ml_scale = max(0.0, min(1.0, (sos_norm - SOS_ML_THRESHOLD_LOW) / (SOS_ML_THRESHOLD_HIGH - SOS_ML_THRESHOLD_LOW)))
    ml_delta = ps_ml - ps_adj
    effective_scale = ml_scale if ml_delta >= 0 else 1.0
    return max(0.0, min(1.0, ps_adj + ml_delta * effective_scale))


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


# --------------------------------------------------------------------
#  Cohort normalization (shared between v53e and ML layer)
# --------------------------------------------------------------------


def _percentile_norm(x: pd.Series, tiebreaker: Optional[pd.Series] = None) -> pd.Series:
    """Percentile normalization with optional tie-breaking.

    When ``tiebreaker`` is provided (e.g. pre-clip raw values), ties in ``x``
    are broken by the tiebreaker so that teams clipped to the same ceiling
    still receive distinct percentile ranks.
    """
    if len(x) == 0:
        return x
    if len(x) < 2:
        return pd.Series([0.5] * len(x), index=x.index)
    if tiebreaker is not None and len(tiebreaker) == len(x):
        sorted_unique = np.sort(x.unique())
        if len(sorted_unique) > 1:
            diffs = np.diff(sorted_unique)
            min_gap = diffs[diffs > 0].min() if (diffs > 0).any() else 1e-12
            eps = min_gap * 0.5
        else:
            eps = 1.0
        composite = x + eps * tiebreaker.rank(method="dense", pct=True)
        return composite.rank(method="average", pct=True).astype(float)
    return x.rank(method="average", pct=True).astype(float)


def _zscore_norm(x: pd.Series) -> pd.Series:
    """Sigmoid z-score normalization to [0, 1]."""
    if len(x) == 0:
        return x
    if len(x) < 2:
        return pd.Series([0.5] * len(x), index=x.index)
    sd = x.std(ddof=0)
    if sd == 0:
        return pd.Series([0.5] * len(x), index=x.index)
    z = (x - x.mean()) / sd
    return 1 / (1 + np.exp(-z))


def normalize_by_cohort(
    df: pd.DataFrame,
    *,
    value_col: str,
    out_col: str,
    mode: str,
    cohort_cols: Optional[List[str]] = None,
    tiebreaker_col: Optional[str] = None,
) -> pd.DataFrame:
    """Normalize values within demographic cohorts.

    Shared implementation used by the ML layer (``layer13_predictive_adjustment``).

    Args:
        df: Input DataFrame.
        value_col: Column containing values to normalize.
        out_col: Name for the new normalized column.
        mode: ``"zscore"`` for sigmoid z-score, anything else for percentile rank.
        cohort_cols: Columns defining cohorts (default ``["age", "gender"]``).
        tiebreaker_col: Optional column for breaking percentile ties
            (e.g. pre-clip raw values). Ignored in zscore mode.
    """
    if cohort_cols is None:
        cohort_cols = ["age", "gender"]

    has_tiebreaker = tiebreaker_col is not None and tiebreaker_col in df.columns
    parts = []
    for _, grp in df.groupby(cohort_cols, dropna=False):
        g = grp.copy()
        s = g[value_col].astype(float)
        if mode == "zscore":
            g[out_col] = _zscore_norm(s)
        else:
            tb = g[tiebreaker_col] if has_tiebreaker else None
            g[out_col] = _percentile_norm(s, tiebreaker=tb)
        parts.append(g)
    return pd.concat(parts, axis=0)
