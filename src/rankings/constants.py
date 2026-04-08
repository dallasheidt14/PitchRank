"""Shared constants for ranking calculations."""

from __future__ import annotations

from src.etl.glicko_config import GlickoConfig

# Compute age → anchor mapping from gendered anchors (avg M/F).
# This ensures AGE_TO_ANCHOR stays in sync with GlickoConfig.MALE_ANCHORS
# and FEMALE_ANCHORS automatically — no manual updates needed.
_cfg = GlickoConfig()
AGE_TO_ANCHOR: dict[int, float] = {
    age: round((_cfg.MALE_ANCHORS[age] + _cfg.FEMALE_ANCHORS[age]) / 2, 3)
    for age in _cfg.MALE_ANCHORS
    if age in _cfg.FEMALE_ANCHORS
}
del _cfg

# SOS-conditioned ML scaling thresholds
# Below LOW, ML has no authority; above HIGH, ML has full authority
SOS_ML_THRESHOLD_LOW = 0.45
SOS_ML_THRESHOLD_HIGH = 0.60

# Negative ML corrections always apply at full authority.
# Weak schedule should never shield a team from being marked as overrated.
NEGATIVE_ML_FLOOR = 1.0

# ── League Tier System ──────────────────────────────────────────────────
# Per-league opponent strength multiplier applied during Glicko-2
# convergence and SOS calculation. Discounts opponent mu for teams
# in closed lower-tier ecosystems.

UNAFFILIATED_MULTIPLIER_MALE: float = 0.97
UNAFFILIATED_MULTIPLIER_FEMALE: float = 0.97

# Male: direct league -> multiplier
LEAGUE_MULTIPLIER_MALE: dict[str, float] = {
    "MLS_NEXT_HD": 1.00,
    "ECNL": 0.98,
    "MLS_NEXT_AD": 0.98,
    "ECNL_RL": 0.95,
    "DPL": 0.93,
    "NPL": 0.93,
    "EA": 0.93,
    "NL": 0.93,
    "EA2": 0.91,
}

# Female: direct league -> multiplier
LEAGUE_MULTIPLIER_FEMALE: dict[str, float] = {
    "ECNL": 1.00,
    "GA": 0.98,
    "ECNL_RL": 0.94,
    "DPL": 0.93,
    "NPL": 0.93,
    "EA": 0.93,
    "NL": 0.93,
    "ASPIRE": 0.93,
}

# Tier multipliers only apply for U13+ (ages 13-19).
TIER_MIN_AGE = 13


def get_tier_multiplier(league: str | None, gender: str, age: int | None = None) -> float:
    """Return the league multiplier for a given league and gender.

    Uses direct per-league multiplier maps (not tier-based).

    Args:
        league: League string (e.g., "ECNL_RL") or None for unaffiliated.
        gender: "Male" or "Female".
        age: Numeric age group. If below 13, returns 1.0.

    Returns:
        Multiplier (1.0 = no discount).
    """
    if age is not None and age < TIER_MIN_AGE:
        return 1.0
    if gender == "Female":
        if league is None:
            return UNAFFILIATED_MULTIPLIER_FEMALE
        return LEAGUE_MULTIPLIER_FEMALE.get(league, UNAFFILIATED_MULTIPLIER_FEMALE)
    else:
        if league is None:
            return UNAFFILIATED_MULTIPLIER_MALE
        return LEAGUE_MULTIPLIER_MALE.get(league, UNAFFILIATED_MULTIPLIER_MALE)
