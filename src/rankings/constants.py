"""Shared constants for ranking calculations."""

from __future__ import annotations

# Static age → anchor mapping for U10–U19
# Younger teams have lower max PowerScore, older teams can reach 1.0
AGE_TO_ANCHOR: dict[int, float] = {
    10: 0.788,  # Calibrated from empirical cross-age competition data (avg M/F)
    11: 0.811,  # Old values (U10=0.40, U14=0.70) over-penalized younger ages by ~2x
    12: 0.855,
    13: 0.896,
    14: 0.943,
    15: 0.949,
    16: 0.973,
    17: 0.981,
    18: 0.992,
    19: 1.000,  # U19 encompasses birth years 2007+2008 (formerly U18+U19)
}

# Calibrated age anchors for Glicko-2 engine (empirical, from cross-age competition data)
MALE_AGE_ANCHORS: dict[int, float] = {
    10: 0.783,
    11: 0.793,
    12: 0.824,
    13: 0.878,
    14: 0.928,
    15: 0.935,
    16: 0.962,
    17: 0.965,
    18: 0.985,
    19: 1.000,
}

FEMALE_AGE_ANCHORS: dict[int, float] = {
    10: 0.792,
    11: 0.828,
    12: 0.885,
    13: 0.914,
    14: 0.957,
    15: 0.962,
    16: 0.984,
    17: 0.996,
    18: 0.998,
    19: 1.000,
}

# SOS-conditioned ML scaling thresholds
# Below LOW, ML has no authority; above HIGH, ML has full authority
SOS_ML_THRESHOLD_LOW = 0.45
SOS_ML_THRESHOLD_HIGH = 0.60

# Asymmetric ML gate: minimum authority for negative ML corrections.
# Positive corrections are fully gated by SOS; negative corrections
# (marking overrated teams down) get at least this much authority.
NEGATIVE_ML_FLOOR = 0.5

# ── League Tier System ──────────────────────────────────────────────────
# Tier-based opponent strength multiplier for SOS calculation.
# Teams in closed lower-tier ecosystems have inflated ratings because they
# only play within their tier. This discount reduces opponent strength
# proportional to the tier gap.

TIER_MULTIPLIERS: dict[int, float] = {
    1: 1.00,  # Baseline — no adjustment
    2: 0.85,  # Discount Tier 2 opponent strength by 15%
    3: 0.70,  # Discount Tier 3 opponent strength by 30%
}

UNAFFILIATED_MULTIPLIER: float = 1.00  # No penalty for unaffiliated teams

# Male tier mapping (MLS NEXT HD/AD + ECNL/ECNL RL)
LEAGUE_TO_TIER_MALE: dict[str, int] = {
    "ECNL": 1,
    "MLS_NEXT_HD": 1,
    "ECNL_RL": 2,
    "MLS_NEXT_AD": 2,
    "DPL": 2,
    "NPL": 3,
    "EA": 3,
    "NL": 3,
}

# Female tier mapping (ECNL/GA + ECNL RL, no MLS NEXT)
LEAGUE_TO_TIER_FEMALE: dict[str, int] = {
    "ECNL": 1,
    "GA": 1,
    "ECNL_RL": 2,
    "DPL": 2,
    "NPL": 3,
    "EA": 3,
    "NL": 3,
    "ASPIRE": 3,
}


# Tier multipliers only apply for U13+ (ages 13-19).
# ECNL, MLS NEXT, GA, DPL, etc. don't exist below U13.
TIER_MIN_AGE = 13


def get_tier_multiplier(league: str | None, gender: str, age: int | None = None) -> float:
    """Return the tier multiplier for a given league and gender.

    Args:
        league: League string (e.g., "ECNL_RL") or None for unaffiliated.
        gender: "Male" or "Female" — determines which tier mapping to use.
        age: Numeric age group (e.g., 14 for U14). If below TIER_MIN_AGE (13),
             returns 1.0 — tier system doesn't apply to younger age groups.

    Returns:
        Tier multiplier (1.0 for Tier 1 / unaffiliated / U12 and below,
        0.85 for Tier 2, 0.70 for Tier 3).
    """
    if league is None:
        return UNAFFILIATED_MULTIPLIER
    if age is not None and age < TIER_MIN_AGE:
        return UNAFFILIATED_MULTIPLIER
    tier_map = LEAGUE_TO_TIER_FEMALE if gender == "Female" else LEAGUE_TO_TIER_MALE
    tier = tier_map.get(league)
    if tier is None:
        return UNAFFILIATED_MULTIPLIER
    return TIER_MULTIPLIERS.get(tier, UNAFFILIATED_MULTIPLIER)
