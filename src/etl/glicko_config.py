from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# =========================================================
# Configuration — Glicko-2 Ranking Engine
# =========================================================
@dataclass
class GlickoConfig:
    # Core Glicko-2
    INITIAL_MU: float = 1500.0
    INITIAL_SIGMA: float = 350.0
    INITIAL_VOLATILITY: float = 0.06
    TAU: float = 0.5  # Glicko-2 system constant

    # Game scoring
    MAX_GD: int = 6
    OUTLIER_GUARD_ZSCORE: float = 2.5

    # Window
    MAX_GAMES: int = 30
    WINDOW_DAYS: int = 365
    INACTIVE_DAYS: int = 180

    # Recency
    RECENCY_LAMBDA: float = 1.0

    # Convergence
    CONVERGENCE_THRESHOLD: float = 1.0
    MAX_ITERATIONS: int = 10

    # Cross-age
    ANCHOR_SCALE_FACTOR: float = 400.0
    MALE_ANCHORS: dict = field(default_factory=lambda: {
        10: 0.783, 11: 0.793, 12: 0.824, 13: 0.878,
        14: 0.928, 15: 0.935, 16: 0.962, 17: 0.965,
        18: 0.985, 19: 1.000,
    })
    FEMALE_ANCHORS: dict = field(default_factory=lambda: {
        10: 0.792, 11: 0.828, 12: 0.885, 13: 0.914,
        14: 0.957, 15: 0.962, 16: 0.984, 17: 0.996,
        18: 0.998, 19: 1.000,
    })

    # SOS
    SOS_REPEAT_CAP: int = 4
    SOS_TRIM_BOTTOM_PCT: float = 0.25
    SOS_TRIM_TOP_PCT: float = 0.15

    # SCF
    SCF_ENABLED: bool = True
    SCF_MIN_UNIQUE_STATES: int = 2
    SCF_DIVERSITY_DIVISOR: float = 4.0
    SCF_FLOOR: float = 0.4
    MIN_BRIDGE_GAMES: int = 3
    ISOLATION_SOS_CAP: float = 0.60

    # ML
    ML_ALPHA: float = 0.08

    # Provisional
    MIN_GAMES_PROVISIONAL: int = 6
