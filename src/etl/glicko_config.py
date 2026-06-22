from __future__ import annotations

import logging
import os
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
    WINDOW_GRACE_DAYS: int = 28
    INACTIVE_DAYS: int = 180
    BALANCED_SELECTION_ENABLED: bool = True
    BALANCED_SELECTION_RECENT_GAMES: int = 20
    BALANCED_SELECTION_SAME_AGE_QUALITY_GAMES: int = 7
    BALANCED_SELECTION_BRIDGE_GAMES: int = 3
    BALANCED_SELECTION_CROSS_AGE_BRIDGE_MULT: float = 0.6

    # Recency
    RECENCY_LAMBDA: float = 1.0

    # Repeat-opponent decay inside the core Glicko update.
    # The first meeting gets full weight; repeated meetings retain authority
    # but progressively less, which reduces closed-loop inflation without
    # zeroing out rematches entirely.
    REPEAT_OPPONENT_DECAY_ENABLED: bool = True
    REPEAT_OPPONENT_WEIGHTS: list[float] = field(default_factory=lambda: [1.0, 0.8, 0.6, 0.4])

    # Convergence
    CONVERGENCE_THRESHOLD: float = 1.0
    MAX_ITERATIONS: int = 30

    # Cross-age
    ANCHOR_SCALE_FACTOR: float = 400.0
    MALE_ANCHORS: dict = field(
        default_factory=lambda: {
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
    )
    FEMALE_ANCHORS: dict = field(
        default_factory=lambda: {
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
    )

    # SOS
    SOS_REPEAT_CAP: int = 4
    SOS_TRIM_BOTTOM_PCT: float = 0.25
    SOS_TRIM_TOP_PCT: float = 0.15

    # SCF
    SCF_ENABLED: bool = field(
        default_factory=lambda: os.getenv("SCF_ENABLED", "true").strip().lower() not in ("0", "false", "no")
    )
    # Apply SCF dampening only to the published score, never to mu.
    # Dampened mu corrupts every downstream use of ratings (opponent credit, SOS,
    # cross-age global map); publish-only SCF won log-loss in every backtested
    # cohort/cutoff cell while keeping isolated teams out of the top ranks.
    # ROLLBACK 2026-06-15: disabled. The first published run on this flag (#885)
    # scrambled standings — u14F non-playing teams moved a median of 387 ranks —
    # because undampened mu fed Layer-13 and the self-referential same-age evidence
    # gates. Re-enable only behind end-to-end publish-path validation
    # (scripts/ranking_stability_check.py).
    SCF_PUBLISH_ONLY: bool = False
    SCF_MIN_UNIQUE_STATES: int = 2
    SCF_DIVERSITY_DIVISOR: float = field(default_factory=lambda: float(os.getenv("SCF_DIVERSITY_DIVISOR", "4.0")))
    SCF_FLOOR: float = field(default_factory=lambda: float(os.getenv("SCF_FLOOR", "0.4")))
    SCF_ZERO_BRIDGE_FLOOR: float = 0.1
    MIN_BRIDGE_GAMES: int = 3
    ISOLATION_SOS_CAP: float = 0.60
    SCF_QUALITY_WEIGHT_ENABLED: bool = True
    SCF_BRIDGE_QUALITY_MIDPOINT: float = 1500.0
    SCF_BRIDGE_QUALITY_SCALE: float = 125.0
    SCF_BRIDGE_QUALITY_FLOOR: float = 0.25
    SCF_CROSS_AGE_BRIDGE_MULT: float = 0.6
    SCF_DISABLE_LEAGUE_BELOW_AGE: int = 13

    # League-aware SCF: detect closed-league bubbles
    # Diversity is measured by league FAMILY, not exact league string.
    # Top-tier (ECNL, GA, MLS_NEXT_HD) vs lower-tier (everything else).
    SCF_LEAGUE_DIVERSITY_DIVISOR: float = 2.0  # Opponents from 2+ league families → max league_scf
    SCF_LEAGUE_FLOOR: float = 0.5  # Minimum league_scf
    SCF_LEAGUE_CONCENTRATION_THRESHOLD: float = 0.65  # >65% same family → penalty kicks in
    SCF_LEAGUE_CONCENTRATION_SCALE: float = 2.0  # Steepness: penalty = scale * (share - threshold)
    SCF_MIN_UNIQUE_LEAGUES: int = 2  # Below this unique families → league-isolated

    # Tier multiplier application. Centered keeps the intended discount relative to
    # the 1500 neutral rating (effective_mu = 1500 + (mu - 1500) * mult) instead of
    # scaling the raw rating, which over-discounts strong lower-league opponents.
    # ROLLBACK 2026-06-15: disabled alongside SCF_PUBLISH_ONLY to fully restore
    # pre-#885 behavior during incident containment.
    TIER_MULT_CENTERED: bool = False

    # Evidence-gate reference freeze (Step 1 publish-path hardening, post-#885).
    # When True, the same-age evidence gates rank opponents by their PRIOR published
    # rank (ranking_history.rank_in_cohort_final) instead of the current run's
    # powerscore_adj, so an engine-input change can no longer reshuffle the rank-driven
    # gates within the run that introduces it (the self-referential amplifier behind
    # #885). Opponent POWER stays on the live powerscore_adj scale the fixed thresholds
    # are tuned against; teams absent from the prior snapshot fall back to their
    # current-run rank. Default False = exact pre-hardening behavior. Re-enable only
    # behind the stability harness (scripts/ranking_stability_check.py).
    EVIDENCE_GATE_FROZEN_REF: bool = False

    # SOS post-hoc adjustment (asymmetric scaling of mu before normalization)
    # Weak schedules get a larger shrinkage than strong schedules get a reward.
    # This is intentional: it reins in inflated ratings from soft schedules
    # without double-counting opponent quality inside the core Glicko update.
    SOS_ADJ_ENABLED: bool = True
    SOS_ADJ_WEAK_THRESHOLD: float = 0.45      # Dead zone lower edge (sos_norm scale)
    SOS_ADJ_STRONG_THRESHOLD: float = 0.60     # Dead zone upper edge (sos_norm scale)
    SOS_ADJ_WEAK_MAX: float = 0.16             # Max 16% penalty for weakest SOS
    SOS_ADJ_STRONG_MAX: float = 0.03           # Max 3% reward for strongest SOS
    BASE_EVIDENCE_SHRINK_ENABLED: bool = True
    BASE_EVIDENCE_SHRINK_MAX: float = 0.08
    BASE_EVIDENCE_SHRINK_STRONG: float = 0.05
    BASE_EVIDENCE_SHRINK_MODERATE: float = 0.035
    BASE_EVIDENCE_SHRINK_LIGHT: float = 0.02
    BASE_EVIDENCE_SHRINK_QUALITY: float = 0.025
    BASE_EVIDENCE_SHRINK_LOW_CONNECTIVITY_BONUS: float = 0.015
    BASE_EVIDENCE_SHRINK_REPEAT_BONUS: float = 0.01
    BASE_EVIDENCE_SHRINK_STRONG_MAX_TOP500: int = 2
    BASE_EVIDENCE_SHRINK_MODERATE_MAX_TOP500: int = 4
    BASE_EVIDENCE_SHRINK_LIGHT_MAX_TOP500: int = 3
    BASE_EVIDENCE_SHRINK_QUALITY_MAX_TOP500: int = 5
    BASE_EVIDENCE_SHRINK_QUALITY_MAX_TOP500_NON_LOSS: int = 4
    BASE_EVIDENCE_SHRINK_MAX_TOP1000_NON_LOSS: int = 2
    BASE_EVIDENCE_SHRINK_AVG_RANK_STRONG: float = 900.0
    BASE_EVIDENCE_SHRINK_AVG_RANK_MODERATE: float = 650.0
    BASE_EVIDENCE_SHRINK_AVG_RANK_LIGHT: float = 550.0
    BASE_EVIDENCE_SHRINK_AVG_RANK_QUALITY: float = 700.0
    BASE_EVIDENCE_SHRINK_LOW_SCF: float = 0.60
    BASE_EVIDENCE_SHRINK_REPEAT_SHARE: float = 0.45
    BASE_EVIDENCE_STALE_NO_RECENT_DAYS: int = 75
    BASE_EVIDENCE_STALE_MAX_GAMES_LAST_60: int = 0
    BASE_EVIDENCE_STALE_NO_RECENT_BONUS: float = 0.02
    BASE_EVIDENCE_STALE_LOW_ACTIVITY_DAYS: int = 90
    BASE_EVIDENCE_STALE_MAX_GAMES_LAST_120: int = 4
    BASE_EVIDENCE_STALE_LOW_ACTIVITY_BONUS: float = 0.025

    # ML
    ML_ALPHA: float = 0.08

    # Provisional/publication floor
    MIN_GAMES_PROVISIONAL: int = 12
