"""Derived predictive priors for ranking snapshots and exports.

These priors are team-level expectations against a neutral cohort opponent.
They are intentionally conservative fallbacks so offline snapshots, exported
rankings, and future models can use the same predictive fields even when the
underlying ranking pipeline did not explicitly populate them.
"""

from __future__ import annotations

import math
from typing import Optional

import pandas as pd

LEAGUE_AVG_TOTAL_GOALS = 3.1
GLICKO_BASELINE = 1500.0
GLICKO_SCALE = 400.0
PREDICTIVE_MARGIN_SCALE = 1.05
PREDICTIVE_MARGIN_CLIP = 2.75
PREDICTIVE_WIN_DIVISOR = 1.1


def _safe_float(value: object, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except TypeError:
        pass

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _safe_games_played(row: pd.Series) -> int:
    games_played = _safe_float(row.get("games_played"))
    if games_played is None:
        games_played = _safe_float(row.get("gp"), 0.0)
    return int(games_played or 0.0)


def _derive_win_rate(row: pd.Series) -> float:
    win_percentage = _safe_float(row.get("win_percentage"))
    if win_percentage is not None:
        return _clamp(win_percentage / 100.0, 0.0, 1.0)

    wins = _safe_float(row.get("wins"), 0.0) or 0.0
    draws = _safe_float(row.get("draws"), 0.0) or 0.0
    games_played = max(0, _safe_games_played(row))
    if games_played <= 0:
        return 0.5
    return _clamp((wins + (0.5 * draws)) / games_played, 0.0, 1.0)


def _compute_evidence_reliability(row: pd.Series) -> float:
    evidence_values = [
        row.get("same_age_games"),
        row.get("same_age_game_share"),
        row.get("same_age_unique_opponents"),
        row.get("same_age_top100_opp_count"),
        row.get("same_age_top500_opp_count"),
        row.get("same_age_avg_opp_power_adj"),
        row.get("repeat_opponent_share"),
        row.get("positive_ml_evidence_scale"),
        row.get("publication_cap_rank"),
        row.get("publication_cap_score"),
    ]
    if not any(value is not None and not pd.isna(value) for value in evidence_values):
        return 1.0

    reliability = 1.0
    same_age_games = max(0.0, _safe_float(row.get("same_age_games"), 0.0) or 0.0)
    same_age_share = _clamp(_safe_float(row.get("same_age_game_share"), 0.0) or 0.0, 0.0, 1.0)
    same_age_opponents = max(0.0, _safe_float(row.get("same_age_unique_opponents"), 0.0) or 0.0)
    top100 = max(0.0, _safe_float(row.get("same_age_top100_opp_count"), 0.0) or 0.0)
    top500 = max(0.0, _safe_float(row.get("same_age_top500_opp_count"), 0.0) or 0.0)
    avg_opp_power = _safe_float(row.get("same_age_avg_opp_power_adj"))
    repeat_share = _clamp(_safe_float(row.get("repeat_opponent_share"), 0.0) or 0.0, 0.0, 1.0)
    ml_evidence_scale = _clamp(_safe_float(row.get("positive_ml_evidence_scale"), 1.0) or 1.0, 0.0, 1.1)

    reliability += min(same_age_games / 8.0, 1.0) * 0.03
    reliability += same_age_share * 0.06
    reliability += min(same_age_opponents / 6.0, 1.0) * 0.05
    reliability += min(top100 / 3.0, 1.0) * 0.06
    reliability += min(top500 / 6.0, 1.0) * 0.04
    if avg_opp_power is not None:
        reliability += _clamp(avg_opp_power - 0.5, -0.06, 0.06)
    reliability -= repeat_share * 0.12
    reliability *= _clamp(0.82 + ml_evidence_scale * 0.18, 0.82, 1.02)

    power_score_final = _safe_float(row.get("power_score_final"))
    publication_cap_score = _safe_float(row.get("publication_cap_score"))
    if power_score_final is not None and publication_cap_score is not None:
        reliability -= _clamp((power_score_final - publication_cap_score) * 1.2, 0.0, 0.1)

    publication_cap_rank = _safe_float(row.get("publication_cap_rank"))
    if publication_cap_rank is not None:
        if publication_cap_rank <= 100:
            reliability -= 0.06
        elif publication_cap_rank <= 200:
            reliability -= 0.04
        else:
            reliability -= 0.02

    return _clamp(reliability, 0.72, 1.08)


def _compute_expected_goals(
    offense_norm: Optional[float],
    defense_norm: Optional[float],
    exp_margin: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    if offense_norm is None or defense_norm is None or exp_margin is None:
        return None, None

    expected_total_goals = LEAGUE_AVG_TOTAL_GOALS * ((offense_norm + defense_norm) / 2.0)
    exp_goals_for = expected_total_goals / (1.0 + math.exp(-exp_margin))
    exp_goals_against = expected_total_goals - exp_goals_for
    return exp_goals_for, exp_goals_against


def _derive_margin_components(row: pd.Series) -> float:
    reliability = _compute_evidence_reliability(row)
    power_score = _safe_float(row.get("power_score_final"), 0.5) or 0.5
    sos_norm = _safe_float(row.get("sos_norm"), 0.5) or 0.5

    offense_norm = _safe_float(row.get("offense_norm"))
    if offense_norm is None:
        offense_norm = _safe_float(row.get("off_norm"), 0.5) or 0.5

    defense_norm = _safe_float(row.get("defense_norm"))
    if defense_norm is None:
        defense_norm = _safe_float(row.get("def_norm"), 0.5) or 0.5

    glicko_rating = _safe_float(row.get("glicko_rating"))
    if glicko_rating is None:
        glicko_rating = _safe_float(row.get("mu"))
    glicko_rd = _safe_float(row.get("glicko_rd"))
    if glicko_rd is None:
        glicko_rd = _safe_float(row.get("sigma"), 350.0)

    games_played = _safe_games_played(row)
    win_rate = _derive_win_rate(row)

    power_signal = _clamp((power_score - 0.5) * 2.4, -0.75, 0.75)
    sos_signal = _clamp((sos_norm - 0.5) * 0.35, -0.18, 0.18)

    style_signal = _clamp(
        ((offense_norm - defense_norm) * 0.9) + ((((offense_norm + defense_norm) / 2.0) - 0.5) * 0.35),
        -0.35,
        0.35,
    )
    record_signal = _clamp((win_rate - 0.5) * min(1.0, games_played / 12.0) * 0.35, -0.22, 0.22)

    glicko_signal = 0.0
    if glicko_rating is not None:
        reliability_from_rd = 1.0
        if glicko_rd is not None:
            reliability_from_rd = _clamp(1.0 - (glicko_rd / 350.0), 0.15, 1.0)
        glicko_signal = _clamp(((glicko_rating - GLICKO_BASELINE) / GLICKO_SCALE) * reliability_from_rd, -0.55, 0.55)

    combined_signal = (
        power_signal
        + (0.65 * glicko_signal)
        + sos_signal
        + (0.55 * style_signal)
        + record_signal
    )
    return _clamp(
        combined_signal * PREDICTIVE_MARGIN_SCALE * reliability,
        -PREDICTIVE_MARGIN_CLIP,
        PREDICTIVE_MARGIN_CLIP,
    )


def ensure_predictive_priors(rankings_df: pd.DataFrame) -> pd.DataFrame:
    """Populate predictive prior fields when they are missing.

    Existing non-null values are preserved. Missing expected goals are derived
    from the final margin and normalized offense/defense values.
    """
    if rankings_df.empty:
        return rankings_df.copy()

    enriched_df = rankings_df.copy()

    if "offense_norm" not in enriched_df.columns and "off_norm" in enriched_df.columns:
        enriched_df["offense_norm"] = enriched_df["off_norm"]
    if "defense_norm" not in enriched_df.columns and "def_norm" in enriched_df.columns:
        enriched_df["defense_norm"] = enriched_df["def_norm"]

    derived_margin = enriched_df.apply(_derive_margin_components, axis=1)
    if "exp_margin" not in enriched_df.columns:
        enriched_df["exp_margin"] = derived_margin
    else:
        enriched_df["exp_margin"] = enriched_df["exp_margin"].where(enriched_df["exp_margin"].notna(), derived_margin)

    derived_win_rate = enriched_df["exp_margin"].apply(
        lambda margin: _clamp(1.0 / (1.0 + math.exp(-(float(margin) / PREDICTIVE_WIN_DIVISOR))), 0.01, 0.99)
        if margin is not None and not pd.isna(margin)
        else None
    )
    if "exp_win_rate" not in enriched_df.columns:
        enriched_df["exp_win_rate"] = derived_win_rate
    else:
        enriched_df["exp_win_rate"] = enriched_df["exp_win_rate"].where(
            enriched_df["exp_win_rate"].notna(),
            derived_win_rate,
        )

    derived_goals = enriched_df.apply(
        lambda row: _compute_expected_goals(
            _safe_float(row.get("offense_norm")),
            _safe_float(row.get("defense_norm")),
            _safe_float(row.get("exp_margin")),
        ),
        axis=1,
    )
    derived_goals_for = derived_goals.apply(lambda values: values[0])
    derived_goals_against = derived_goals.apply(lambda values: values[1])

    if "exp_goals_for" not in enriched_df.columns:
        enriched_df["exp_goals_for"] = derived_goals_for
    else:
        enriched_df["exp_goals_for"] = enriched_df["exp_goals_for"].where(
            enriched_df["exp_goals_for"].notna(),
            derived_goals_for,
        )

    if "exp_goals_against" not in enriched_df.columns:
        enriched_df["exp_goals_against"] = derived_goals_against
    else:
        enriched_df["exp_goals_against"] = enriched_df["exp_goals_against"].where(
            enriched_df["exp_goals_against"].notna(),
            derived_goals_against,
        )

    return enriched_df
