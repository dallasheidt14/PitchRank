"""Shared constants for ranking calculations."""

from __future__ import annotations

# Static age → anchor mapping for U10–U19
# Younger teams have lower max PowerScore, older teams can reach 1.0
AGE_TO_ANCHOR: dict[int, float] = {
    10: 0.400,
    11: 0.475,
    12: 0.550,
    13: 0.625,
    14: 0.700,
    15: 0.775,
    16: 0.850,
    17: 0.925,
    18: 1.000,  # Legacy: kept for safety if u18 data reaches v53e unmapped
    19: 1.000,  # U19 encompasses birth years 2007+2008 (formerly U18+U19)
}

# SOS-conditioned ML scaling thresholds
# Below LOW, ML has no authority; above HIGH, ML has full authority
SOS_ML_THRESHOLD_LOW = 0.45
SOS_ML_THRESHOLD_HIGH = 0.60
