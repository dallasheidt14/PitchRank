from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# =========================
# Configuration (v53E – National Unified)
# =========================
@dataclass
class V53EConfig:
    # Layer 1
    WINDOW_DAYS: int = 365
    INACTIVE_HIDE_DAYS: int = 365

    # Layer 2
    MAX_GAMES_FOR_RANK: int = 30
    GOAL_DIFF_CAP: int = 6
    OUTLIER_GUARD_ZSCORE: float = 2.5  # per-team, per-game GF/GA clip

    # Layer 3 (recency)
    # Exponential decay: weight = exp(-RECENCY_DECAY_RATE * (rank - 1))
    # 0.05 = gentle decay (game 30 keeps ~23% weight)
    # 0.08 = moderate decay (game 30 keeps ~10% weight)  [default]
    # 0.10 = steeper decay (game 30 keeps ~6% weight)
    RECENCY_DECAY_RATE: float = 0.08

    # Layer 4 (defense ridge)
    RIDGE_GA: float = 0.25

    # Layer 5 (Adaptive K + team-level outlier guard)
    ADAPTIVE_K_ALPHA: float = 0.5
    ADAPTIVE_K_BETA: float = 0.6
    TEAM_OUTLIER_GUARD_ZSCORE: float = (
        3.0  # clip aggregated OFF/DEF extremes (tightened from 3.5 — fewer teams hit ceiling, reducing tie compression)
    )

    # Layer 6 (Performance)
    PERFORMANCE_K: float = 0.15  # Legacy: kept for backward compatibility, use PERF_* instead
    PERF_GAME_SCALE: float = 0.15  # Scales per-game performance residual
    PERF_BLEND_WEIGHT: float = (
        0.00  # Weight of perf_centered in final powerscore (was 0.15, set to 0.00 — stat-padding bias fix)
    )
    PERF_CAP: float = 0.15  # Symmetric cap on perf_centered [-cap, +cap] before blending (clips outlier overperformers)
    PERFORMANCE_DECAY_RATE: float = 0.08  # decay per recency index step
    PERFORMANCE_THRESHOLD: float = (
        0.5  # goals – lowered from 2.0 to fix asymmetric filtering bias against defensive teams
    )
    PERFORMANCE_GOAL_SCALE: float = 5.0  # goals per 1.0 power diff

    # Layer 7 (Bayesian shrink)
    SHRINK_TAU: float = 8.0

    # Layer 8 (SOS)
    UNRANKED_SOS_BASE: float = 0.35
    SOS_REPEAT_CAP: int = 4  # Restored to 4 — league teams playing same opponent 3-4x need full SOS credit

    # SOS trimming: reduce filler-game dilution by downweighting weakest opponents
    # Teams with many mandatory league games against weak opponents get penalized under
    # a pure weighted mean. Trimming reduces that dilution while protecting small samples.
    SOS_TRIM_BOTTOM_PCT: float = 0.25  # Fraction of weakest opponents to trim (0.0 = disabled)
    SOS_TRIM_MIN_GAMES: int = 8  # Don't trim teams with fewer games than this
    SOS_TRIM_MAX_GAMES: int = 6  # Cap: never trim more than this many games per team
    SOS_TRIM_MODE: str = "soft"  # "hard" = zero weight, "soft" = reduce weight
    SOS_TRIM_SOFT_WEIGHT: float = 0.15  # In soft mode, trimmed games keep this fraction of original weight

    SOS_ITERATIONS: int = 1  # Single-pass SOS (no transitive propagation)
    SOS_TRANSITIVITY_LAMBDA: float = 0.0  # Transitivity disabled (pure direct SOS)

    # Power-SOS Co-Calculation: Use opponent's FULL power score (including their SOS) for SOS calculation
    # This ensures that playing teams with tough schedules properly boosts your SOS
    # Set to 0 to disable (use old off/def-only approach), 2-3 iterations recommended
    SOS_POWER_ITERATIONS: int = 3  # Number of power-SOS refinement cycles (0 = disabled)
    SOS_POWER_DAMPING: float = 0.5  # Damping factor: weight on new vs previous SOS (lower = more conservative)
    SOS_POWER_MAX_BOOST: float = 0.03  # Max SOS increase from iteration vs pre-iteration baseline

    # SOS sample size weighting
    # NOTE: SOS_SAMPLE_SIZE_THRESHOLD is DEPRECATED - pre-percentile shrinkage was removed
    # because it caused games-played bias in sos_norm. Kept for backward compatibility only.
    SOS_SAMPLE_SIZE_THRESHOLD: int = 25  # DEPRECATED: no longer used
    OPPONENT_SAMPLE_SIZE_THRESHOLD: int = 20  # DEPRECATED: no longer used (opponent shrinkage removed)
    MIN_GAMES_FOR_TOP_SOS: int = 10  # Post-percentile shrinkage threshold (teams < this shrink toward anchor)
    SOS_SHRINKAGE_ANCHOR: float = 0.35  # Low-sample teams shrink toward this (0.35 = below-average, not neutral)
    # NOTE: SOS_TOP_CAP_FOR_LOW_SAMPLE is DEPRECATED - hard caps were replaced with soft shrinkage
    SOS_TOP_CAP_FOR_LOW_SAMPLE: float = 0.70  # DEPRECATED: no longer used

    # GP-SOS decorrelation: removes games-played bias from sos_norm for ranked teams
    # in age buckets where GP correlates with SOS (typically U16/U17).
    # When enabled, for any per-age-bucket where GP-SOS correlation exceeds the
    # threshold among unshrunk teams (>= MIN_GAMES_FOR_TOP_SOS), sos_norm is
    # residualized against GP via OLS to remove the linear relationship.
    # NOTE: Only teams with GP >= MIN_GAMES_FOR_TOP_SOS participate in both the
    # correlation measurement and OLS fit, to avoid measuring artificial correlation
    # introduced by low-sample shrinkage (which pulls GP < 10 teams toward 0.35).
    GP_SOS_DECORRELATION_ENABLED: bool = True
    GP_SOS_DECORRELATION_THRESHOLD: float = (
        0.15  # Correlation threshold to trigger (above 0.10 guardrail, conservative)
    )

    # NOTE: MIN_GAMES_FOR_SOS_RANK was removed — SOS rank eligibility is now
    # derived from team status ("Active"), which itself uses MIN_GAMES_PROVISIONAL.
    # This prevents the two gates from drifting apart.

    # Opponent-adjusted offense/defense (fixes double-counting)
    OPPONENT_ADJUST_ENABLED: bool = True
    OPPONENT_ADJUST_BASELINE: float = 0.5  # Reference strength for adjustment
    OPPONENT_ADJUST_CLIP_MIN: float = 0.25  # Min multiplier (widened to preserve signal from elite matchups)
    OPPONENT_ADJUST_CLIP_MAX: float = 2.0  # Max multiplier (widened — old 1.6 clipped wins vs top-10 opponents)

    # Layer 10 weights (tuned via weight simulator — SOS boosted for schedule-strength emphasis)
    OFF_WEIGHT: float = 0.20  # was 0.25
    DEF_WEIGHT: float = 0.20  # was 0.25
    SOS_WEIGHT: float = 0.60  # was 0.50

    # Provisional
    MIN_GAMES_PROVISIONAL: int = 6

    # Cross-age anchors (national unification)
    ANCHOR_PERCENTILE: float = 0.98

    # Normalization mode
    NORM_MODE: str = "percentile"  # or "zscore"

    # SOS Hybrid Normalization
    # Blends percentile rank (guarantees full [0,1] range) with sigmoid z-score
    # (preserves natural gaps at the tails). Pure percentile compresses the top teams
    # into a narrow band, wasting the 60% SOS weight. Hybrid re-introduces
    # differentiation where raw SOS actually differs.
    SOS_NORM_HYBRID_ENABLED: bool = True  # blend percentile + sigmoid z-score to preserve natural SOS gaps at the tails
    SOS_NORM_HYBRID_ZSCORE_BLEND: float = 0.30  # fraction of z-score in the blend (0=pure percentile, 1=pure zscore)

    # =========================
    # Regional Bubble Detection (Layer 8b)
    # =========================
    # Schedule Connectivity Factor (SCF) - measures how connected a team's schedule is
    # to the broader national network. Teams playing only in isolated regional bubbles
    # (e.g., Idaho Rush vs Idaho Juniors vs Missoula Surf) get SOS dampened toward neutral.
    #
    # The problem: Circular inflation occurs when teams only play each other:
    #   - Idaho Rush beats Idaho Juniors → Idaho Rush OFF ↑
    #   - Idaho Juniors beats Missoula Surf → Idaho Juniors OFF ↑
    #   - Missoula Surf beats Idaho Rush → Missoula Surf OFF ↑
    #   - All three inflate each other's SOS with NO anchor to national reality
    #
    # Solution: SCF measures schedule diversity. Low SCF → dampen SOS toward 0.5
    SCF_ENABLED: bool = True  # Enable Schedule Connectivity Factor
    SCF_MIN_UNIQUE_STATES: int = 2  # Minimum unique opponent states for full SOS credit
    SCF_DIVERSITY_DIVISOR: float = 3.0  # divisor for state diversity score
    SCF_FLOOR: float = 0.4  # Minimum SCF (even isolated teams get some SOS credit)
    SCF_NEUTRAL_SOS: float = 0.5  # SOS value to dampen toward for low-connectivity teams

    # Opponent Quality Override for SCF
    # If a team's opponents have high average pre-SCF power, boost SCF toward 1.0.
    # This prevents penalizing national-level leagues (e.g., MLS NEXT) whose teams may
    # play in regional conferences but face elite competition — NOT a bubble.
    SCF_QUALITY_OVERRIDE_ENABLED: bool = True
    SCF_QUALITY_PERCENTILE: float = 0.65  # Opponents avg power above this percentile → boost SCF
    SCF_QUALITY_BOOST_MIN: float = 0.85  # Minimum SCF after quality boost (overrides geographic calc)
    SCF_QUALITY_MIN_WIN_RATE: float = 0.50  # Must be a winning team (50%+ WR) to receive quality override

    # Isolation Penalty via Bridge Games
    # Bridge games = games against teams from outside your state cluster
    # If a team has few bridge games, their SOS is less reliable
    ISOLATION_PENALTY_ENABLED: bool = True
    MIN_BRIDGE_GAMES: int = 3  # Minimum games vs out-of-state opponents for full SOS
    ISOLATION_SOS_CAP: float = 0.60  # Max SOS for teams with no bridge games

    # Regional clustering (US geographic regions for better granularity)
    # Teams playing only within their region get lower SCF than teams playing nationally
    REGIONAL_CLUSTERING_ENABLED: bool = True

    # =========================
    # PageRank-Style SOS Dampening (Layer 8c)
    # =========================
    # Math safety net: Prevents SOS from drifting upward infinitely in isolated clusters.
    # Even if SCF isn't applied, this ensures iterations converge toward reality.
    #
    # Formula: SOS_new = (1 - alpha) * baseline + alpha * avg(opponent_strengths)
    # Where alpha is the dampening factor (like PageRank's damping factor)
    #
    # With alpha=0.85 (default), 15% of SOS is anchored to baseline, 85% from opponents.
    # This prevents isolated clusters from inflating beyond a certain point.
    PAGERANK_DAMPENING_ENABLED: bool = True
    PAGERANK_ALPHA: float = 0.85  # Dampening factor (0.85 = 15% baseline anchor)
    PAGERANK_BASELINE: float = 0.5  # Baseline SOS to anchor toward (neutral)

    # =========================
    # Connected Component SOS Normalization (Layer 8d)
    # =========================
    # When the game graph has disconnected subgraphs (e.g., ECNL and MLS NEXT HD
    # teams that never play each other), the Power-SOS iteration loop creates a
    # feedback loop that inflates one ecosystem and deflates the other.
    #
    # Fix: Detect connected components in the game graph and normalize SOS within
    # each component independently.  This ensures each ecosystem gets a fair
    # [0, 1] SOS distribution.  Small components get shrunk toward 0.5.
    COMPONENT_SOS_ENABLED: bool = True
    # Minimum component size (within cohort) for full SOS percentile range.
    # Components smaller than this get their sos_norm shrunk toward 0.5.
    # Set to roughly the size of the smallest "real" league in a cohort.
    MIN_COMPONENT_SIZE_FOR_FULL_SOS: int = 10


# =========================
# US State to Region mapping (for SCF calculation)
# =========================
STATE_TO_REGION = {
    # Pacific
    "CA": "pacific",
    "OR": "pacific",
    "WA": "pacific",
    "AK": "pacific",
    "HI": "pacific",
    # Mountain
    "MT": "mountain",
    "ID": "mountain",
    "WY": "mountain",
    "NV": "mountain",
    "UT": "mountain",
    "CO": "mountain",
    "AZ": "mountain",
    "NM": "mountain",
    # West North Central
    "ND": "west_north_central",
    "SD": "west_north_central",
    "NE": "west_north_central",
    "KS": "west_north_central",
    "MN": "west_north_central",
    "IA": "west_north_central",
    "MO": "west_north_central",
    # West South Central
    "TX": "west_south_central",
    "OK": "west_south_central",
    "AR": "west_south_central",
    "LA": "west_south_central",
    # East North Central
    "WI": "east_north_central",
    "MI": "east_north_central",
    "IL": "east_north_central",
    "IN": "east_north_central",
    "OH": "east_north_central",
    # East South Central
    "KY": "east_south_central",
    "TN": "east_south_central",
    "MS": "east_south_central",
    "AL": "east_south_central",
    # South Atlantic
    "WV": "south_atlantic",
    "VA": "south_atlantic",
    "MD": "south_atlantic",
    "DE": "south_atlantic",
    "DC": "south_atlantic",
    "NC": "south_atlantic",
    "SC": "south_atlantic",
    "GA": "south_atlantic",
    "FL": "south_atlantic",
    # Middle Atlantic
    "NY": "middle_atlantic",
    "PA": "middle_atlantic",
    "NJ": "middle_atlantic",
    # New England
    "CT": "new_england",
    "RI": "new_england",
    "MA": "new_england",
    "VT": "new_england",
    "NH": "new_england",
    "ME": "new_england",
}


# Required team-centric columns (one row per team per game)
REQUIRED_COLUMNS = [
    "game_id",
    "date",
    "team_id",
    "opp_id",
    "age",
    "gender",
    "opp_age",
    "opp_gender",
    "gf",
    "ga",
]


# =========================
# Utilities
# =========================
def _require_columns(df: pd.DataFrame, cols: List[str]):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def _clip_outliers_series(s: pd.Series, z: float) -> pd.Series:
    s = s.astype(float)
    if len(s) < 3:
        return s
    sd = s.std(ddof=0)
    if sd == 0:
        return s
    mu = s.mean()
    return s.clip(mu - z * sd, mu + z * sd)


def _recency_weights(n: int, decay_rate: float = 0.05) -> List[float]:
    """
    Compute recency weights using exponential decay.

    For games ranked 1..n in recency (1 = most recent), assigns weight exp(-decay_rate * (rank - 1)).
    Normalizes weights so they sum to 1.0.

    Args:
        n: Number of games
        decay_rate: Controls how quickly weight drops off. Configurable via
                    V53EConfig.RECENCY_DECAY_RATE. Examples:
                    - 0.03 = very gentle (game 30 keeps ~41% weight)
                    - 0.05 = gentle (game 30 keeps ~23% weight)  [function default]
                    - 0.08 = moderate (game 30 keeps ~10% weight)  [V53EConfig default]
                    - 0.10 = steep (game 30 keeps ~6% weight)
    """
    if n <= 0:
        return []

    # Exponential decay: more recent games get higher weight
    weights = [np.exp(-decay_rate * i) for i in range(n)]

    # Normalize to sum to 1.0
    total = sum(weights)
    if total > 0:
        weights = [w / total for w in weights]

    return weights


def _percentile_norm(x: pd.Series, tiebreaker: pd.Series = None) -> pd.Series:
    """Percentile normalization with optional tie-breaking.

    When ``tiebreaker`` is provided (e.g. pre-clip raw values), ties in ``x``
    are broken by the tiebreaker so that teams clipped to the same ceiling
    still receive distinct percentile ranks.
    """
    if len(x) == 0:
        return x
    if tiebreaker is not None and len(tiebreaker) == len(x) and len(x) > 1:
        # Build a composite key: primary = clipped value, secondary = pre-clip value.
        # The epsilon must be large enough that tiebreaker differences produce
        # distinct composite values, but small enough that non-tied primary values
        # are never re-ordered.  We use half the minimum gap between distinct
        # primary values — this guarantees tiebreaker adjustments stay within the
        # gap and cannot swap the ordering of non-tied teams.
        sorted_unique = np.sort(x.unique())
        if len(sorted_unique) > 1:
            diffs = np.diff(sorted_unique)
            min_gap = diffs[diffs > 0].min() if (diffs > 0).any() else 1e-12
            eps = min_gap * 0.5
        else:
            # All values identical — tiebreaker IS the ranking
            eps = 1.0
        composite = x + eps * tiebreaker.rank(method="dense", pct=True)
        return composite.rank(method="average", pct=True).astype(float)
    return x.rank(method="average", pct=True).astype(float)


def _zscore_norm(x: pd.Series) -> pd.Series:
    if len(x) == 0:
        return x
    sd = x.std(ddof=0)
    if sd == 0:
        return pd.Series(np.zeros(len(x)), index=x.index)
    z = (x - x.mean()) / sd
    # squash to [0,1] for combinability
    return 1 / (1 + np.exp(-z))


def _hybrid_sos_norm(x: pd.Series, zscore_blend: float = 0.30) -> pd.Series:
    """Blend percentile rank with sigmoid z-score for SOS normalization.

    Pure percentile maps values to a uniform distribution — great for
    guaranteeing full [0,1] range, but it destroys natural gaps.  Among the
    top-30 teams whose raw SOS values cluster tightly, percentile compresses
    them into 0.85–1.00 making SOS a near-constant.

    Sigmoid z-score preserves natural gaps (large raw differences → large
    normalized differences) but can under-use the [0,1] range in small
    cohorts.

    The hybrid blends both:
        hybrid = (1 - α) * percentile + α * sigmoid_zscore

    With α=0.30 the full range is mostly preserved while natural gaps at the
    tails create real differentiation.
    """
    if len(x) <= 1:
        return pd.Series([0.5] * len(x), index=x.index)

    # Percentile component (same as existing)
    x_rounded = x.round(10)
    ranks = x_rounded.rank(method="average")
    pct = (ranks - 1) / (len(x) - 1)

    # Sigmoid z-score component (use rounded values to match percentile noise suppression)
    sd = x_rounded.std(ddof=0)
    if sd == 0 or sd != sd:  # zero or NaN
        return pct  # fall back to pure percentile
    z = (x_rounded - x_rounded.mean()) / sd
    sigmoid = 1.0 / (1.0 + np.exp(-z))

    # Blend
    hybrid = (1.0 - zscore_blend) * pct + zscore_blend * sigmoid

    # Re-scale to [0, 1] within group to guarantee full range (skip for pure percentile)
    if zscore_blend > 0:
        h_min, h_max = hybrid.min(), hybrid.max()
        if h_max - h_min > 1e-10:
            hybrid = (hybrid - h_min) / (h_max - h_min)
        else:
            hybrid = pd.Series([0.5] * len(hybrid), index=hybrid.index)

    return hybrid


def _normalize_by_cohort(df: pd.DataFrame, value_col: str, out_col: str, mode: str) -> pd.DataFrame:
    parts = []
    # Determine tiebreaker column (pre-clip raw values) if it exists
    tiebreaker_col = f"{value_col}_preclip"
    has_tiebreaker = tiebreaker_col in df.columns
    for (age, gender), grp in df.groupby(["age", "gender"], dropna=False):
        s = grp[value_col]
        if mode == "zscore":
            n = _zscore_norm(s)
        else:
            tb = grp[tiebreaker_col] if has_tiebreaker else None
            n = _percentile_norm(s, tiebreaker=tb)
        sub = grp.copy()
        sub[out_col] = n
        parts.append(sub)
    return pd.concat(parts, axis=0)


def _provisional_multiplier(gp: int, min_games: int) -> float:
    """Linear ramp from 0.85 to 1.0 between 0 games and max_games (15).

    Replaces the old step function (0.85 → 0.95 → 1.0) which created
    artificial rank jumps at exactly min_games and 15 games.
    Each additional game provides a proportional boost.
    """
    max_games = 15
    if gp >= max_games:
        return 1.0
    if gp <= 0:
        return 0.85
    # Linear ramp: 0.85 at gp=0, 1.0 at gp=max_games
    return 0.85 + (gp / max_games) * 0.15


def find_connected_components(
    g_sos: pd.DataFrame,
    team_ids: np.ndarray,
) -> Dict[str, int]:
    """
    Find connected components in the game graph using Union-Find.

    Two teams are in the same component if there is ANY path of games
    connecting them (including through cross-age/cross-gender opponents
    that act as bridge nodes).

    Args:
        g_sos: DataFrame with columns ['team_id', 'opp_id'] — the games
               used for SOS calculation.
        team_ids: Array of team IDs in the current cohort.

    Returns:
        Dict mapping each team_id (from team_ids) to a component_id (int).
        Teams in the same component share the same component_id.
    """
    # Union-Find with path compression and union by rank
    parent = {}
    rank = {}

    def _find(x):
        if x not in parent:
            parent[x] = x
            rank[x] = 0
        # Path compression: point directly to root
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a, b):
        ra, rb = _find(a), _find(b)
        if ra == rb:
            return
        # Union by rank
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1

    # Build edges from game data (each row is team_id -> opp_id)
    # Extract unique edges to avoid redundant unions
    edges = g_sos[["team_id", "opp_id"]].drop_duplicates()
    for t, o in zip(edges["team_id"].values, edges["opp_id"].values):
        _union(t, o)

    # Ensure all cohort teams have entries (even those with no games in g_sos)
    for tid in team_ids:
        if tid not in parent:
            parent[tid] = tid
            rank[tid] = 0

    # Map component roots to sequential integer IDs for clean groupby
    root_to_id = {}
    next_id = 0
    result = {}
    for tid in team_ids:
        root = _find(tid)
        if root not in root_to_id:
            root_to_id[root] = next_id
            next_id += 1
        result[tid] = root_to_id[root]

    return result


def compute_schedule_connectivity(
    games_df: pd.DataFrame,
    team_state_map: Dict[str, str],
    cfg: V53EConfig,
    strength_map: Optional[Dict[str, float]] = None,
    team_wr_map: Optional[Dict[str, float]] = None,
) -> Dict[str, Dict]:
    """
    Compute Schedule Connectivity Factor (SCF) for each team.

    SCF measures how connected a team's schedule is to the broader national network.
    Teams playing only in isolated regional bubbles (e.g., Idaho teams only playing
    other Idaho teams) get lower SCF, which dampens their SOS toward neutral.

    The problem this solves:
    - Idaho Rush beats Idaho Juniors → Idaho Rush OFF ↑
    - Idaho Juniors beats Missoula Surf → Idaho Juniors OFF ↑
    - Missoula Surf beats Idaho Rush → Missoula Surf OFF ↑
    - All inflate each other's SOS with NO anchor to national reality

    Quality override: If a team's opponents have high average power (e.g., MLS NEXT
    teams in regional conferences), they are NOT in a bubble — boost SCF toward 1.0.

    Args:
        strength_map: Optional dict of team_id -> power_score (pre-SCF). Used to
                      detect high-quality schedules that should bypass SCF penalty.
        team_wr_map: Optional dict of team_id -> win_rate (0-1). Used to gate the
                     quality override — teams must have a winning record to receive it.

    Returns:
        Dict[team_id, {
            'scf': float (0.4 to 1.0),
            'unique_states': int,
            'unique_regions': int,
            'bridge_games': int,
            'home_state': str,
            'is_isolated': bool,
            'quality_boosted': bool
        }]
    """
    result = {}

    if not cfg.SCF_ENABLED:
        # If disabled, return SCF=1.0 for all teams (no dampening)
        for team_id in games_df["team_id"].unique():
            result[team_id] = {
                "scf": 1.0,
                "unique_states": 0,
                "unique_regions": 0,
                "bridge_games": 0,
                "home_state": team_state_map.get(str(team_id), "UNKNOWN"),
                "is_isolated": False,
                "quality_boosted": False,
            }
        return result

    # Pre-compute quality threshold for opponent quality override
    quality_threshold = None
    if cfg.SCF_QUALITY_OVERRIDE_ENABLED and strength_map:
        all_strengths = [v for v in strength_map.values() if v > 0]
        if all_strengths:
            quality_threshold = float(np.percentile(all_strengths, cfg.SCF_QUALITY_PERCENTILE * 100))
            logger.info(
                f"🔗 SCF quality override: threshold={quality_threshold:.4f} "
                f"(p{cfg.SCF_QUALITY_PERCENTILE * 100:.0f} of {len(all_strengths)} teams)"
            )

    quality_boosted_count = 0

    # Group games by team to analyze each team's schedule
    for team_id, team_games in games_df.groupby("team_id"):
        team_id_str = str(team_id)
        home_state = team_state_map.get(team_id_str, "UNKNOWN")
        home_region = STATE_TO_REGION.get(home_state, "unknown")

        # Get all opponent states
        opp_ids = team_games["opp_id"].unique()
        opp_states = set()
        opp_regions = set()
        bridge_games = 0

        for opp_id in opp_ids:
            opp_state = team_state_map.get(str(opp_id), "UNKNOWN")
            opp_region = STATE_TO_REGION.get(opp_state, "unknown")

            if opp_state != "UNKNOWN":
                opp_states.add(opp_state)

            if opp_region != "unknown":
                opp_regions.add(opp_region)

            # Count bridge games (games vs teams from different states)
            if opp_state != home_state and opp_state != "UNKNOWN":
                # Count how many games against this out-of-state opponent
                games_vs_opp = len(team_games[team_games["opp_id"] == opp_id])
                bridge_games += games_vs_opp

        # Calculate SCF based on schedule diversity
        unique_states = len(opp_states)
        unique_regions = len(opp_regions)

        # Base SCF from state diversity
        state_diversity = min(unique_states / cfg.SCF_DIVERSITY_DIVISOR, 1.0)

        # Bonus for regional diversity (playing teams from different parts of country)
        if cfg.REGIONAL_CLUSTERING_ENABLED and unique_regions > 1:
            region_bonus = min((unique_regions - 1) * 0.1, 0.2)  # Up to 0.2 bonus
        else:
            region_bonus = 0.0

        # Calculate SCF with floor
        scf_raw = state_diversity + region_bonus
        scf = max(cfg.SCF_FLOOR, min(1.0, scf_raw))

        # Opponent Quality Override: if opponents are strong AND the team is competitive,
        # this is NOT a bubble. MLS NEXT teams play in regional conferences but face
        # elite competition. Geographic isolation ≠ quality isolation.
        # Win-rate gate: prevents closed-ecosystem teams with losing records from
        # gaming the override via circularly-inflated opponent base_strengths.
        quality_boosted = False
        if quality_threshold is not None and strength_map and len(opp_ids) >= 3:
            opp_strengths = [strength_map.get(str(oid), 0.0) for oid in opp_ids if str(oid) in strength_map]
            if opp_strengths:
                avg_opp_strength = float(np.mean(opp_strengths))
                team_wr = team_wr_map.get(team_id_str, 0.5) if team_wr_map else 0.5
                if avg_opp_strength >= quality_threshold and team_wr >= cfg.SCF_QUALITY_MIN_WIN_RATE:
                    scf = max(scf, cfg.SCF_QUALITY_BOOST_MIN)
                    quality_boosted = True
                    quality_boosted_count += 1

        # Determine if team is isolated (no bridge games or very few unique states)
        # Quality-boosted teams are NOT considered isolated
        is_isolated = not quality_boosted and (
            bridge_games < cfg.MIN_BRIDGE_GAMES or unique_states < cfg.SCF_MIN_UNIQUE_STATES
        )

        result[team_id_str] = {
            "scf": scf,
            "unique_states": unique_states,
            "unique_regions": unique_regions,
            "bridge_games": bridge_games,
            "home_state": home_state,
            "is_isolated": is_isolated,
            "quality_boosted": quality_boosted,
        }

    if quality_boosted_count > 0:
        logger.info(
            f"🔗 SCF quality override applied to {quality_boosted_count} teams "
            f"(opponents avg power >= p{cfg.SCF_QUALITY_PERCENTILE * 100:.0f})"
        )

    return result


def apply_scf_to_sos(team_df: pd.DataFrame, scf_data: Dict[str, Dict], cfg: V53EConfig) -> pd.DataFrame:
    """
    Apply Schedule Connectivity Factor to dampen SOS for isolated teams.

    For teams with low SCF (isolated regional bubbles):
    - SOS is dampened toward neutral (0.5)
    - This prevents circular inflation in isolated clusters

    Formula: sos_adjusted = neutral + SCF * (sos_raw - neutral)
    """
    if not cfg.SCF_ENABLED:
        return team_df

    team_df = team_df.copy()

    # Add SCF columns
    team_df["scf"] = team_df["team_id"].map(lambda tid: scf_data.get(str(tid), {}).get("scf", 1.0))
    team_df["bridge_games"] = team_df["team_id"].map(lambda tid: scf_data.get(str(tid), {}).get("bridge_games", 0))
    team_df["is_isolated"] = team_df["team_id"].map(lambda tid: scf_data.get(str(tid), {}).get("is_isolated", False))
    team_df["unique_opp_states"] = team_df["team_id"].map(
        lambda tid: scf_data.get(str(tid), {}).get("unique_states", 0)
    )

    # Store original SOS before adjustment
    team_df["sos_raw_before_scf"] = team_df["sos"].copy()

    # Apply SCF dampening to raw SOS
    # Formula: sos_adjusted = neutral + SCF * (sos_raw - neutral)
    neutral = cfg.SCF_NEUTRAL_SOS
    team_df["sos"] = neutral + team_df["scf"] * (team_df["sos"] - neutral)

    # Apply same SCF dampening to sos_orig for apples-to-apples diagnostic comparison
    if "sos_orig" in team_df.columns:
        team_df["sos_orig"] = neutral + team_df["scf"] * (team_df["sos_orig"] - neutral)

    # Track quality-boosted teams
    team_df["quality_boosted"] = team_df["team_id"].map(
        lambda tid: scf_data.get(str(tid), {}).get("quality_boosted", False)
    )

    # Apply isolation penalty cap if enabled — but NOT for quality-boosted teams
    if cfg.ISOLATION_PENALTY_ENABLED:
        # Teams with insufficient bridge games get SOS capped
        # Quality-boosted teams are exempt (they play elite opponents, not a bubble)
        isolation_mask = (team_df["bridge_games"] < cfg.MIN_BRIDGE_GAMES) & (~team_df["quality_boosted"])
        team_df.loc[isolation_mask, "sos"] = team_df.loc[isolation_mask, "sos"].clip(upper=cfg.ISOLATION_SOS_CAP)

    # Log statistics
    isolated_count = team_df["is_isolated"].sum()
    avg_scf = team_df["scf"].mean()
    low_scf_count = (team_df["scf"] < 0.7).sum()
    quality_boosted_count = team_df["quality_boosted"].sum()

    logger.info(
        f"🔗 Schedule Connectivity Factor applied: "
        f"avg_scf={avg_scf:.3f}, isolated_teams={isolated_count}, "
        f"low_scf_teams={low_scf_count}, quality_boosted={quality_boosted_count}"
    )

    # Log some examples of isolated teams (for debugging)
    if isolated_count > 0 and isolated_count <= 10:
        isolated_teams = team_df[team_df["is_isolated"]].head(5)
        for _, row in isolated_teams.iterrows():
            logger.info(
                f"  📍 Isolated: team={row['team_id'][:8]}... "
                f"scf={row['scf']:.2f}, bridge_games={row['bridge_games']}, "
                f"unique_states={row['unique_opp_states']}"
            )

    return team_df


def _adjust_for_opponent_strength(
    games: pd.DataFrame, strength_map: Dict[str, float], cfg: V53EConfig, baseline: Optional[float] = None
) -> pd.DataFrame:
    """
    Adjust goals for/against based on opponent strength to fix double-counting problem.

    For offense: Scoring against STRONG opponents gets MORE credit (multiplier > 1)
    For defense: Allowing goals to STRONG opponents gets LESS penalty (multiplier < 1)

    Args:
        games: DataFrame with columns [gf, ga, opp_id, w_game]
        strength_map: Dict mapping team_id to strength (0-1)
        cfg: Configuration
        baseline: Reference strength for adjustment (defaults to cfg.OPPONENT_ADJUST_BASELINE)

    Returns:
        DataFrame with additional columns [gf_adjusted, ga_adjusted]
    """
    g = games.copy()

    # Use provided baseline or fall back to config
    if baseline is None:
        baseline = cfg.OPPONENT_ADJUST_BASELINE

    # Get opponent strength for each game, floor at UNRANKED_SOS_BASE to prevent division by zero
    g["opp_strength"] = (
        g["opp_id"].map(lambda o: strength_map.get(o, cfg.UNRANKED_SOS_BASE)).clip(lower=cfg.UNRANKED_SOS_BASE)
    )

    # Calculate adjustment multipliers
    # Offense: score against strong opponent = more credit
    # multiplier = opp_strength / baseline
    # Example: opp_strength=0.8, baseline=0.7 → multiplier=1.14 (14% more credit)
    #          opp_strength=0.6, baseline=0.7 → multiplier=0.86 (14% less credit)
    g["off_multiplier"] = (g["opp_strength"] / baseline).clip(
        cfg.OPPONENT_ADJUST_CLIP_MIN, cfg.OPPONENT_ADJUST_CLIP_MAX
    )

    # Defense: allow goals to strong opponent = less penalty
    # multiplier = baseline / opp_strength
    # Example: opp_strength=0.8, baseline=0.7 → multiplier=0.875 (12.5% less penalty)
    #          opp_strength=0.6, baseline=0.7 → multiplier=1.17 (17% more penalty)
    g["def_multiplier"] = (baseline / g["opp_strength"]).clip(
        cfg.OPPONENT_ADJUST_CLIP_MIN, cfg.OPPONENT_ADJUST_CLIP_MAX
    )

    # Apply adjustments
    g["gf_adjusted"] = g["gf"] * g["off_multiplier"]
    g["ga_adjusted"] = g["ga"] * g["def_multiplier"]

    return g


# =========================
# Main: compute_rankings
# =========================
def compute_rankings(
    games_df: pd.DataFrame,
    today: Optional[pd.Timestamp] = None,
    cfg: Optional[V53EConfig] = None,
    global_strength_map: Optional[Dict[str, float]] = None,
    team_state_map: Optional[Dict[str, str]] = None,
    pass_label: Optional[str] = None,
    pre_sos_state: Optional[Dict] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Returns:
      {
        "teams": DataFrame[one row per (team_id, age, gender)],
        "games_used": DataFrame[rows used in SOS after repeat-cap],
        "pre_sos_state": Dict of intermediate state (for two-pass optimization)
      }

    Args:
        games_df: Games in v53e format (one row per team per game)
        today: Reference date for rankings
        cfg: V53E configuration
        global_strength_map: Optional dict of team_id -> abs_strength from all cohorts
                            Used for cross-age/cross-gender opponent lookups in SOS
        team_state_map: Optional dict of team_id -> state_code for Schedule Connectivity
                       Factor (SCF) calculation. If not provided, SCF is disabled.
        pre_sos_state: Optional cached state from Pass 1 to skip layers 1-5 in Pass 2
    """
    cfg = cfg or V53EConfig()

    # Error handling: check for required columns
    try:
        _require_columns(games_df, REQUIRED_COLUMNS)
    except ValueError:
        # Return empty DataFrames if columns are missing
        return {"teams": pd.DataFrame(), "games_used": pd.DataFrame(), "pre_sos_state": None}

    # Shared helper used by both pre-SOS layers and SOS layers
    def apply_recency(df: pd.DataFrame) -> pd.DataFrame:
        n = len(df)
        w = _recency_weights(n, decay_rate=cfg.RECENCY_DECAY_RATE)
        out = df.copy()
        out["w_base"] = w
        return out

    # Two-pass optimization: if pre_sos_state is provided, skip layers 1-5
    # and jump directly to SOS calculation with the new global_strength_map.
    _current_pre_sos_state = None
    if pre_sos_state is not None:
        logger.info("⚡ Restoring pre-SOS state (skipping layers 1-5)")
        team = pre_sos_state["team"]
        g = pre_sos_state["g"]
        g_365 = pre_sos_state["g_365"]
        strength_map = pre_sos_state["strength_map"]
        power_map = pre_sos_state["power_map"]
        strength_series = pd.Series(strength_map)
        today = pre_sos_state["today"]
    else:
        g = games_df.copy()
        g["date"] = pd.to_datetime(g["date"], errors="coerce")
        if today is None:
            today = pd.Timestamp(pd.Timestamp.now("UTC").date())

        # Defensive check: NaN age/gender would silently bypass cohort groupby operations
        # (groupby defaults to dropna=True). The import filter in data_adapter.py should
        # prevent this, but if it fails, catch it early rather than producing wrong rankings.
        for col in ("age", "gender"):
            nan_count = g[col].isna().sum() if col in g.columns else 0
            if nan_count > 0:
                logger.warning(
                    f"⚠️ {nan_count:,} games have NaN '{col}' — these will be excluded from "
                    f"cohort-level normalization. Check import pipeline for missing metadata."
                )

        # -------------------------
        # Layer 1: window filter
        # -------------------------
        cutoff = today - pd.Timedelta(days=cfg.WINDOW_DAYS)
        g = g[g["date"] >= cutoff].copy()

        # Flag game outcomes before outlier clipping modifies gf/ga
        g["is_win"] = (g["gf"] > g["ga"]).astype(int)
        g["is_loss"] = (g["gf"] < g["ga"]).astype(int)
        g["is_draw"] = (g["gf"] == g["ga"]).astype(int)

        # -------------------------
        # Layer 2: per-team GF/GA outlier guard + GD cap
        # -------------------------
        def clip_team_games(df: pd.DataFrame) -> pd.DataFrame:
            out = df.copy()
            out["gf"] = _clip_outliers_series(out["gf"], cfg.OUTLIER_GUARD_ZSCORE)
            out["ga"] = _clip_outliers_series(out["ga"], cfg.OUTLIER_GUARD_ZSCORE)
            return out

        clipped_groups = [clip_team_games(grp) for _, grp in g.groupby("team_id")]
        if not clipped_groups:
            return {"teams": pd.DataFrame(), "games_used": pd.DataFrame(), "pre_sos_state": None}
        g = pd.concat(clipped_groups).reset_index(drop=True)
        # Cap individual gf/ga per game (consistent with GOAL_DIFF_CAP).
        # Without this, an 8-0 blowout contributes 8 goals of offensive output
        # even though gd is capped at 6. This inflates offense for teams
        # beating up on weak opponents.
        g["gf"] = g["gf"].clip(upper=cfg.GOAL_DIFF_CAP)
        g["ga"] = g["ga"].clip(upper=cfg.GOAL_DIFF_CAP)
        g["gd"] = (g["gf"] - g["ga"]).clip(-cfg.GOAL_DIFF_CAP, cfg.GOAL_DIFF_CAP)

        # Save ALL 365-day games before the 30-game filter.
        # SOS uses the full window so that short scheduling clusters
        # (e.g. 3-4 weak opponents in a row) don't dominate the sample.
        g = g.sort_values(["team_id", "date"], ascending=[True, False])
        g["rank_recency"] = g.groupby("team_id")["date"].rank(ascending=False, method="first")
        g_365 = g.copy()  # Full 365-day set for SOS (before 30-game trim)

        # keep last N games per team (by date) for OFF/DEF calculations
        g = g[g["rank_recency"] <= cfg.MAX_GAMES_FOR_RANK].copy()

        # -------------------------
        # Layer 3: Recency weights
        # -------------------------
        g = pd.concat([apply_recency(grp) for _, grp in g.groupby("team_id")]).reset_index(drop=True)

        g["w_game"] = g["w_base"]

        # -------------------------
        # OFF/SAD aggregation (vectorized)
        # -------------------------
        # Vectorized aggregation: compute weighted averages and simple aggregations
        g["gf_weighted"] = g["gf"] * g["w_game"]
        g["ga_weighted"] = g["ga"] * g["w_game"]

        # Aggregate using vectorized operations
        team = (
            g.groupby(["team_id", "age", "gender"], as_index=False)
            .agg(
                {
                    "gf_weighted": "sum",
                    "ga_weighted": "sum",
                    "w_game": "sum",  # w_sum for weighted average calculation
                    "date": "max",  # last_game
                }
            )
            .rename(columns={"date": "last_game"})
        )

        # Calculate weighted averages (vectorized)
        w_sum = team["w_game"]
        team["off_raw"] = np.where(w_sum > 0, team["gf_weighted"] / w_sum, 0.0).astype(float)
        team["sad_raw"] = np.where(w_sum > 0, team["ga_weighted"] / w_sum, 0.0).astype(float)

        # Add gp (game count) using vectorized count
        gp_counts = g.groupby(["team_id", "age", "gender"], as_index=False).size().rename(columns={"size": "gp"})
        team = team.merge(gp_counts, on=["team_id", "age", "gender"], how="left")

        # Compute W/L/D counts per team (flags were set before outlier clipping)
        wld_counts = g.groupby(["team_id", "age", "gender"], as_index=False).agg(
            wins=("is_win", "sum"),
            losses=("is_loss", "sum"),
            draws=("is_draw", "sum"),
        )
        team = team.merge(wld_counts, on=["team_id", "age", "gender"], how="left")

        # Calculate games in activity window (INACTIVE_HIDE_DAYS) for status filtering
        inactive_cutoff = today - pd.Timedelta(days=cfg.INACTIVE_HIDE_DAYS)
        g_recent = g[g["date"] >= inactive_cutoff].copy()
        gp_recent_counts = (
            g_recent.groupby(["team_id", "age", "gender"], as_index=False)
            .size()
            .rename(columns={"size": "gp_last_window"})
        )
        team = team.merge(gp_recent_counts, on=["team_id", "age", "gender"], how="left")
        team["gp_last_window"] = team["gp_last_window"].fillna(0).astype(int)

        # Drop intermediate columns
        team = team.drop(columns=["gf_weighted", "ga_weighted", "w_game"])

        # -------------------------
        # Layer 4: ridge defense
        # -------------------------
        team["def_raw"] = 1.0 / (team["sad_raw"] + cfg.RIDGE_GA)

        # -------------------------
        # Layer 7: shrink within cohort
        # -------------------------
        # Shared helpers for shrinkage + clipping (used in initial pass and opponent-adjust pass)
        def _shrink_cohort(df: pd.DataFrame) -> pd.DataFrame:
            mu_off = df["off_raw"].mean()
            mu_sad = df["sad_raw"].mean()
            out = df.copy()
            out["off_shrunk"] = (out["off_raw"] * out["gp"] + mu_off * cfg.SHRINK_TAU) / (out["gp"] + cfg.SHRINK_TAU)
            out["sad_shrunk"] = (out["sad_raw"] * out["gp"] + mu_sad * cfg.SHRINK_TAU) / (out["gp"] + cfg.SHRINK_TAU)
            out["def_shrunk"] = 1.0 / (out["sad_shrunk"] + cfg.RIDGE_GA)
            return out

        def _clip_cohort(df: pd.DataFrame) -> pd.DataFrame:
            out = df.copy()
            for col in ["off_shrunk", "def_shrunk"]:
                s = out[col]
                if len(s) >= 3 and s.std(ddof=0) > 0:
                    mu, sd = s.mean(), s.std(ddof=0)
                    # Save pre-clip values for tie-breaking in normalization
                    out[f"{col}_preclip"] = s
                    out[col] = s.clip(mu - cfg.TEAM_OUTLIER_GUARD_ZSCORE * sd, mu + cfg.TEAM_OUTLIER_GUARD_ZSCORE * sd)
            return out

        team = pd.concat([_shrink_cohort(grp) for _, grp in team.groupby(["age", "gender"])]).reset_index(drop=True)

        # -------------------------
        # Layer 5: team-level outlier guard (OFF/DEF)
        # -------------------------
        team = pd.concat([_clip_cohort(grp) for _, grp in team.groupby(["age", "gender"])]).reset_index(drop=True)

        # -------------------------
        # Layer 9: normalize OFF/DEF
        # -------------------------
        team = _normalize_by_cohort(team, "off_shrunk", "off_norm", cfg.NORM_MODE)
        team = _normalize_by_cohort(team, "def_shrunk", "def_norm", cfg.NORM_MODE)

        # -------------------------
        # Pre-SOS power & anchors (national unification)
        # -------------------------
        # power_presos uses only OFF/DEF (50% each) to avoid circular dependency with SOS.
        # This provides a stable base strength for opponent adjustment and cross-age SOS lookups.
        team["power_presos"] = 0.5 * team["off_norm"] + 0.5 * team["def_norm"]

        from src.rankings.constants import AGE_TO_ANCHOR

        def compute_anchor(age_val):
            """Map age to static anchor value"""
            try:
                age_numeric = int(float(age_val))
                anchor = AGE_TO_ANCHOR.get(age_numeric)
                if anchor is None:
                    logger.warning(f"⚠️ Age {age_numeric} outside supported range (10-19) — using fallback anchor 0.70")
                    return 0.70
                return anchor
            except (ValueError, TypeError):
                logger.warning(f"⚠️ Invalid age value '{age_val}' — using fallback anchor 0.70")
                return 0.70

        team["anchor"] = team["age"].apply(compute_anchor)

        logger.info("✅ Static anchor mapping applied (U10=0.40 → U18=1.00)")

        # True competitive strength (no anchor scaling — anchor is applied only at final scoring)
        team["abs_strength"] = team["power_presos"].clip(cfg.UNRANKED_SOS_BASE, 1.0)

        strength_map = dict(zip(team["team_id"], team["abs_strength"]))
        power_map = dict(zip(team["team_id"], team["power_presos"]))

        # -------------------------
        # Opponent-Adjusted Offense/Defense (if enabled)
        # -------------------------
        if cfg.OPPONENT_ADJUST_ENABLED:
            logger.info("🔄 Applying opponent-adjusted offense/defense to fix double-counting...")

            # Calculate the actual mean strength to use as baseline (instead of hardcoded 0.5)
            # Floor at UNRANKED_SOS_BASE to prevent division by zero in opponent adjustment
            strength_values = list(strength_map.values())
            actual_mean_strength = max(np.mean(strength_values) if strength_values else 0.5, cfg.UNRANKED_SOS_BASE)
            logger.info(
                f"📊 Strength distribution: mean={actual_mean_strength:.3f}, "
                f"min={min(strength_values):.3f}, max={max(strength_values):.3f}"
            )

            # Use actual mean as baseline for opponent adjustment
            baseline = actual_mean_strength

            # Adjust games for opponent strength
            g_adjusted = _adjust_for_opponent_strength(g, strength_map, cfg, baseline=baseline)

            # Re-aggregate with adjusted values
            g_adjusted["gf_weighted_adj"] = g_adjusted["gf_adjusted"] * g_adjusted["w_game"]
            g_adjusted["ga_weighted_adj"] = g_adjusted["ga_adjusted"] * g_adjusted["w_game"]

            team_adj = g_adjusted.groupby(["team_id", "age", "gender"], as_index=False).agg(
                {
                    "gf_weighted_adj": "sum",
                    "ga_weighted_adj": "sum",
                    "w_game": "sum",
                }
            )

            # Calculate adjusted weighted averages
            w_sum = team_adj["w_game"]
            team_adj["off_raw"] = np.where(w_sum > 0, team_adj["gf_weighted_adj"] / w_sum, 0.0).astype(float)
            team_adj["sad_raw"] = np.where(w_sum > 0, team_adj["ga_weighted_adj"] / w_sum, 0.0).astype(float)

            # Merge back to team DataFrame (replace old off_raw, sad_raw)
            team = team.drop(columns=["off_raw", "sad_raw"])
            team = team.merge(
                team_adj[["team_id", "age", "gender", "off_raw", "sad_raw"]],
                on=["team_id", "age", "gender"],
                how="left",
            )

            # Re-apply defense ridge
            team["def_raw"] = 1.0 / (team["sad_raw"] + cfg.RIDGE_GA)

            # Re-apply Bayesian shrinkage (using shared helper)
            team = pd.concat([_shrink_cohort(grp) for _, grp in team.groupby(["age", "gender"])]).reset_index(drop=True)

            # Re-apply outlier clipping (using shared helper)
            team = pd.concat([_clip_cohort(grp) for _, grp in team.groupby(["age", "gender"])]).reset_index(drop=True)

            # Re-normalize
            team = _normalize_by_cohort(team, "off_shrunk", "off_norm", cfg.NORM_MODE)
            team = _normalize_by_cohort(team, "def_shrunk", "def_norm", cfg.NORM_MODE)

            # Recalculate power_presos with adjusted OFF/DEF (50% each, no SOS to avoid circularity)
            team["power_presos"] = 0.5 * team["off_norm"] + 0.5 * team["def_norm"]

            # Update strength_map and power_map with adjusted power (no anchor scaling)
            team["abs_strength"] = team["power_presos"].clip(cfg.UNRANKED_SOS_BASE, 1.0)
            strength_map = dict(zip(team["team_id"], team["abs_strength"]))
            power_map = dict(zip(team["team_id"], team["power_presos"]))

            logger.info("✅ Opponent-adjusted offense/defense applied successfully")

            # Diagnostic: opponent-adjusted OFF/DEF distribution (for anchor-isolation validation)
            logger.info("📊 Opponent-adjusted OFF/DEF distribution:")
            for (age, gender), grp in team.groupby(["age", "gender"]):
                logger.info(
                    f"  {age} {gender}: off_raw mean={grp['off_raw'].mean():.4f} std={grp['off_raw'].std():.4f}, "
                    f"sad_raw mean={grp['sad_raw'].mean():.4f} std={grp['sad_raw'].std():.4f}"
                )

        # -------------------------
        # Layer 5: Adaptive K per game (by abs strength gap)
        # -------------------------
        strength_series = pd.Series(strength_map)
        team_str_g = g["team_id"].map(strength_series).fillna(0.5).values
        opp_str_g = g["opp_id"].map(strength_series).fillna(0.5).values
        g["k_adapt"] = cfg.ADAPTIVE_K_ALPHA * (1.0 + cfg.ADAPTIVE_K_BETA * np.abs(team_str_g - opp_str_g))

        # Cache pre-SOS state for Pass 2 reuse (avoids recomputing layers 1-5)
        _current_pre_sos_state = {
            "team": team.copy(),
            "g": g.copy(),
            "g_365": g_365.copy(),
            "strength_map": dict(strength_map),
            "power_map": dict(power_map),
            "today": today,
        }

    # -------------------------
    # Layer 8: SOS (weights + repeat-cap + iterations)
    # -------------------------
    # SOS uses the FULL 365-day game window (g_365) instead of the 30-game
    # OFF/DEF window.  This ensures that a short run of weak opponents
    # (e.g. 3-4 games) is diluted by the much larger 365-day sample rather
    # than over-represented in a 30-game window.
    #
    # Pipeline for g_365:
    #   recency weights → w_game → adaptive K → w_sos
    g_365 = pd.concat([apply_recency(grp) for _, grp in g_365.groupby("team_id")]).reset_index(drop=True)
    g_365["w_game"] = g_365["w_base"]
    team_str_365 = g_365["team_id"].map(strength_series).fillna(0.5).values
    opp_str_365 = g_365["opp_id"].map(strength_series).fillna(0.5).values
    g_365["k_adapt"] = cfg.ADAPTIVE_K_ALPHA * (1.0 + cfg.ADAPTIVE_K_BETA * np.abs(team_str_365 - opp_str_365))
    g_365["w_sos"] = g_365["w_game"] * g_365["k_adapt"]

    # Diagnostic: adaptive_k distribution per cohort (for anchor-isolation validation)
    if "age" in team.columns and "gender" in team.columns:
        _cohort_map = dict(zip(team["team_id"], zip(team["age"], team["gender"])))
        _diag = g_365[["team_id", "k_adapt"]].copy()
        _diag["cohort"] = _diag["team_id"].map(_cohort_map)
        _diag = _diag.dropna(subset=["cohort"])
        logger.info("📊 adaptive_k distribution (365-day SOS games):")
        for cohort, grp in sorted(_diag.groupby("cohort"), key=lambda x: x[0]):
            k_arr = grp["k_adapt"].values
            logger.info(
                f"  {cohort[0]} {cohort[1]}: mean={k_arr.mean():.4f}, p90={np.percentile(k_arr, 90):.4f}, "
                f"max={k_arr.max():.4f}, n={len(k_arr)}"
            )

    logger.info(f"📊 SOS 365-day window: {len(g_365)} game-rows (vs {len(g)} in 30-game OFF/DEF window)")

    g_365 = g_365.sort_values(["team_id", "opp_id", "w_sos"], ascending=[True, True, False])
    g_365["repeat_rank"] = g_365.groupby(["team_id", "opp_id"])["w_sos"].rank(ascending=False, method="first")
    g_sos = g_365[g_365["repeat_rank"] <= cfg.SOS_REPEAT_CAP].copy()

    # Also compute w_sos on the 30-game set (used by performance layer)
    g["w_sos"] = g["w_game"] * g["k_adapt"]

    # -------------------------
    # Layer 8d: Connected Component Detection
    # -------------------------
    # Detect disconnected subgraphs in the game graph so that SOS
    # percentile normalization is done WITHIN each component, not across
    # the entire cohort.  This prevents the Power-SOS iteration loop from
    # creating feedback-loop bias between ecosystems that never play each
    # other (e.g., ECNL vs MLS NEXT HD).
    if cfg.COMPONENT_SOS_ENABLED:
        component_map = find_connected_components(
            g_sos=g_sos,
            team_ids=team["team_id"].values,
        )
        team["component_id"] = team["team_id"].map(component_map).fillna(-1).astype(int)

        # Compute component size WITHIN this cohort (for shrinkage decisions)
        team["component_size"] = team.groupby(["age", "gender", "component_id"])["team_id"].transform("count")

        # Log component statistics
        n_components = team["component_id"].nunique()
        component_sizes = team.groupby("component_id")["team_id"].count()
        if n_components > 1:
            top5 = sorted(component_sizes.values, reverse=True)[:5]
            logger.info(f"🔗 {n_components} connected components (top 5 sizes: {top5})")
        else:
            logger.debug(f"🔗 Fully connected graph ({len(team)} teams, 1 component)")
    else:
        # Disabled: all teams in one pseudo-component
        team["component_id"] = 0
        team["component_size"] = len(team)

    # Helper function for weighted averages
    def _avg_weighted(df: pd.DataFrame, col: str, wcol: str) -> float:
        w = df[wcol].values
        s = w.sum()
        if s <= 0:
            return 0.5
        return float(np.average(df[col].values, weights=w))

    def _apply_sos_trim(g_sos: pd.DataFrame, strength_col: str) -> int:
        """Downweight each team's weakest opponents for SOS calculation.

        Supports hard mode (zero weight) and soft mode (reduced weight).
        Respects SOS_TRIM_MIN_GAMES and SOS_TRIM_MAX_GAMES guards.
        Returns the number of games trimmed.
        """
        if cfg.SOS_TRIM_BOTTOM_PCT <= 0:
            return 0

        team_counts = g_sos.groupby("team_id")[strength_col].transform("count")
        # Skip teams below minimum games threshold
        eligible = team_counts >= cfg.SOS_TRIM_MIN_GAMES

        # Rank opponents by strength ascending within each team (weakest = rank 1)
        g_sos["_str_rank"] = g_sos.groupby("team_id")[strength_col].rank(method="first", ascending=True)

        # Compute per-team trim count: min(floor(count * pct), max_games)
        n_trim_raw = np.floor(team_counts * cfg.SOS_TRIM_BOTTOM_PCT).astype(int)
        n_trim = np.minimum(n_trim_raw, cfg.SOS_TRIM_MAX_GAMES)

        # Build trim mask: eligible teams, rank within trim cutoff
        trim_mask = eligible & (g_sos["_str_rank"] <= n_trim)
        n_trimmed = int(trim_mask.sum())

        if n_trimmed > 0:
            if cfg.SOS_TRIM_MODE == "hard":
                g_sos.loc[trim_mask, "w_sos"] = 0.0
            else:
                # Soft mode: reduce weight to a fraction of original
                g_sos.loc[trim_mask, "w_sos"] *= cfg.SOS_TRIM_SOFT_WEIGHT

        g_sos.drop(columns=["_str_rank"], inplace=True)
        return n_trimmed

    # Create lookup maps for base strength calculation (OFF/DEF only, no SOS component)
    # This avoids feedback loops in the iterative algorithm
    team_off_norm_map = dict(zip(team["team_id"], team["off_norm"]))
    team_def_norm_map = dict(zip(team["team_id"], team["def_norm"]))
    team_gp_map = dict(zip(team["team_id"], team["gp"]))

    # Calculate cohort average strength for shrinkage (true competitive strength, no anchor)
    cohort_avg_strength = {}
    for (age, gender), grp in team.groupby(["age", "gender"]):
        grp_base_power = 0.5 * grp["off_norm"] + 0.5 * grp["def_norm"]
        cohort_avg_strength[(age, gender)] = float(grp_base_power.mean())

    # Map team_id to cohort for quick lookup
    team_cohort_map = dict(zip(team["team_id"], list(zip(team["age"], team["gender"]))))

    # Calculate BASE strength for each team (OFF/DEF only, true competitive strength)
    # This represents opponent quality independent of their schedule (no anchor scaling).
    # NOTE: Opponent-strength shrinkage was REMOVED - it injected games-played bias into SOS.
    # Teams playing opponents with more games got artificially higher SOS.
    base_strength_map = {}
    for tid in team["team_id"]:
        base_power = 0.5 * team_off_norm_map.get(tid, 0.5) + 0.5 * team_def_norm_map.get(tid, 0.5)
        base_strength_map[tid] = float(np.clip(base_power, 0.0, 1.0))

    # Use base strength for initial SOS calculation (Pass 1)
    # This represents how good opponents are at OFF/DEF
    # For cross-age/cross-gender opponents, use global_strength_map if available

    # Diagnostic: track cross-age lookups
    cross_age_found = 0
    cross_age_missing = 0

    def get_opponent_strength(opp_id):
        nonlocal cross_age_found, cross_age_missing
        # Try local cohort first (same age/gender)
        if opp_id in base_strength_map:
            return base_strength_map[opp_id]
        # Fall back to global map (cross-age/cross-gender)
        # global_strength_map uses string keys, so convert opp_id to string
        opp_id_str = str(opp_id)
        if global_strength_map and opp_id_str in global_strength_map:
            cross_age_found += 1
            return global_strength_map[opp_id_str]
        # Unknown opponent
        cross_age_missing += 1
        return cfg.UNRANKED_SOS_BASE

    g_sos["opp_strength"] = g_sos["opp_id"].map(get_opponent_strength)

    # Log cross-age lookup stats
    _pass_tag = f"[{pass_label}] " if pass_label else ""
    logger.info(
        f"🔍 {_pass_tag}Cross-age SOS lookups: global_map_size={len(global_strength_map) if global_strength_map else 0}, "
        f"found={cross_age_found}, missing={cross_age_missing}"
    )

    # Diagnostic: cross-age inflation guardrail — log teams with highest cross-age exposure
    if cross_age_found > 0:
        cross_age_mask = ~g_sos["opp_id"].isin(base_strength_map)
        cross_age_by_team = cross_age_mask.groupby(g_sos["team_id"]).sum()
        top_exposed = cross_age_by_team.nlargest(10)
        logger.info(f"📊 {_pass_tag}Top 10 teams by cross-age game count: {dict(top_exposed)}")

    # Vectorized weighted mean — avoids groupby.apply returning scalar (deprecated pandas pattern)
    # Step A: Compute original (untrimmed) SOS for diagnostic comparison
    # NOTE: w_sos is still untrimmed at this point — trim happens in Step B
    _ws_orig = g_sos["opp_strength"] * g_sos["w_sos"]
    _wsum_orig = g_sos.groupby("team_id")["w_sos"].sum()
    _vsum_orig = g_sos.assign(_ws=_ws_orig).groupby("team_id")["_ws"].sum()
    sos_orig_series = (_vsum_orig / _wsum_orig.replace(0, np.nan)).fillna(0.5).rename("sos_orig")

    # Step B: Apply SOS trim and compute trimmed SOS
    g_sos["w_sos_orig"] = g_sos["w_sos"].copy()
    n_trimmed = _apply_sos_trim(g_sos, "opp_strength")
    if n_trimmed > 0:
        logger.info(
            f"✂️  SOS trim (Pass 1): {n_trimmed} games downweighted "
            f"(mode={cfg.SOS_TRIM_MODE}, bottom {cfg.SOS_TRIM_BOTTOM_PCT:.0%}, "
            f"min_games={cfg.SOS_TRIM_MIN_GAMES}, max_trim={cfg.SOS_TRIM_MAX_GAMES})"
        )

    _ws = g_sos["opp_strength"] * g_sos["w_sos"]
    _wsum = g_sos.groupby("team_id")["w_sos"].sum()
    _vsum = g_sos.assign(_ws=_ws).groupby("team_id")["_ws"].sum()
    direct = (_vsum / _wsum.replace(0, np.nan)).fillna(0.5).rename("sos_direct").reset_index()
    sos_curr = direct.rename(columns={"sos_direct": "sos"}).copy()

    # Merge sos_orig into sos_curr for diagnostic tracking
    sos_curr = sos_curr.merge(sos_orig_series.reset_index(), on="team_id", how="left")

    # PageRank-style dampening on initial SOS (Pass 1)
    # This anchors even the first pass toward baseline, preventing inflated bubbles
    if cfg.PAGERANK_DAMPENING_ENABLED:
        sos_curr["sos"] = (1 - cfg.PAGERANK_ALPHA) * cfg.PAGERANK_BASELINE + cfg.PAGERANK_ALPHA * sos_curr["sos"]
        # Apply same dampening to sos_orig for apples-to-apples diagnostic comparison
        if "sos_orig" in sos_curr.columns:
            sos_curr["sos_orig"] = (1 - cfg.PAGERANK_ALPHA) * cfg.PAGERANK_BASELINE + cfg.PAGERANK_ALPHA * sos_curr[
                "sos_orig"
            ]
        logger.info(f"📌 PageRank dampening applied: alpha={cfg.PAGERANK_ALPHA}, baseline={cfg.PAGERANK_BASELINE}")

    # Log initial SOS (Pass 1: Direct)
    logger.info(
        f"🔄 SOS Pass 1 (Direct): mean={sos_curr['sos'].mean():.4f}, "
        f"std={sos_curr['sos'].std():.4f}, "
        f"min={sos_curr['sos'].min():.4f}, "
        f"max={sos_curr['sos'].max():.4f}"
    )

    # Preserve sos_orig before iterative loop (which may reassign sos_curr without it)
    _sos_orig_map = dict(zip(sos_curr["team_id"], sos_curr.get("sos_orig", sos_curr["sos"])))

    # True iterative SOS: Propagate schedule difficulty through opponent SOS
    # Direct component (opponent OFF/DEF) stays FIXED to prevent convergence drift
    # Transitive component (opponent SOS) propagates schedule difficulty
    for iteration_idx in range(max(0, cfg.SOS_ITERATIONS - 1)):
        # Store previous SOS for convergence tracking
        prev_sos_map = dict(zip(sos_curr["team_id"], sos_curr["sos"]))

        # Get current SOS values for all teams
        opp_sos_map = dict(zip(sos_curr["team_id"], sos_curr["sos"]))

        # Calculate transitive SOS (opponent's SOS - this propagates schedule difficulty)
        # Use same fallback pattern: local SOS → global strength → unranked
        def get_opponent_sos(opp_id):
            if opp_id in opp_sos_map:
                return opp_sos_map[opp_id]
            # For cross-age opponents not in SOS map, use their global strength as proxy
            # global_strength_map uses string keys, so convert opp_id to string
            opp_id_str = str(opp_id)
            if global_strength_map and opp_id_str in global_strength_map:
                return global_strength_map[opp_id_str]
            return cfg.UNRANKED_SOS_BASE

        g_sos["opp_sos"] = g_sos["opp_id"].map(get_opponent_sos)
        # Vectorized weighted mean for transitive SOS (avoids deprecated groupby.apply scalar pattern)
        _ws_t = g_sos["opp_sos"] * g_sos["w_sos"]
        _wsum_t = g_sos.groupby("team_id")["w_sos"].sum()
        _vsum_t = g_sos.assign(_ws_t=_ws_t).groupby("team_id")["_ws_t"].sum()
        trans = (_vsum_t / _wsum_t.replace(0, np.nan)).fillna(0.5).rename("sos_trans").reset_index()

        # Blend direct (opponent OFF/DEF - fixed) and transitive (opponent SOS - iterates)
        # Direct stays fixed to prevent upward drift, transitive propagates schedule info
        merged = direct.merge(trans, on="team_id", how="outer").fillna(0.5)
        merged["sos"] = (1 - cfg.SOS_TRANSITIVITY_LAMBDA) * merged["sos_direct"] + cfg.SOS_TRANSITIVITY_LAMBDA * merged[
            "sos_trans"
        ]

        # PageRank-style dampening: anchor SOS toward baseline to prevent infinite drift
        # Formula: SOS_final = (1 - alpha) * baseline + alpha * SOS_calculated
        # This ensures isolated clusters can't inflate SOS beyond a certain point
        if cfg.PAGERANK_DAMPENING_ENABLED:
            merged["sos"] = (1 - cfg.PAGERANK_ALPHA) * cfg.PAGERANK_BASELINE + cfg.PAGERANK_ALPHA * merged["sos"]

        # SOS stability guard: clip values between 0.0 and 1.0
        merged["sos"] = merged["sos"].clip(0.0, 1.0)
        sos_curr = merged[["team_id", "sos"]]

        # Calculate convergence: mean absolute change from previous iteration
        sos_changes = [
            abs(sos_curr[sos_curr["team_id"] == tid]["sos"].iloc[0] - prev_sos_map.get(tid, 0.5))
            for tid in sos_curr["team_id"]
            if tid in prev_sos_map
        ]
        mean_change = np.mean(sos_changes) if sos_changes else 0.0

        # Log convergence metrics with change tracking
        logger.info(
            f"🔄 SOS Pass {iteration_idx + 2} (Iterative): mean={sos_curr['sos'].mean():.4f}, "
            f"std={sos_curr['sos'].std():.4f}, "
            f"min={sos_curr['sos'].min():.4f}, "
            f"max={sos_curr['sos'].max():.4f}, "
            f"mean_change={mean_change:.6f}, "
            f"lambda={cfg.SOS_TRANSITIVITY_LAMBDA}"
        )

    # Log final SOS statistics
    logger.info(
        f"✅ SOS calculation complete: "
        f"mean={sos_curr['sos'].mean():.4f}, "
        f"std={sos_curr['sos'].std():.4f}, "
        f"range=[{sos_curr['sos'].min():.4f}, {sos_curr['sos'].max():.4f}]"
    )

    team = team.merge(sos_curr, on="team_id", how="left").fillna({"sos": 0.5})
    # Restore sos_orig from preserved map (survives iterative loop reassignment of sos_curr)
    if cfg.SOS_TRIM_BOTTOM_PCT > 0:
        team["sos_orig"] = team["team_id"].map(_sos_orig_map).fillna(team["sos"])

    # -------------------------
    # Layer 8b: Schedule Connectivity Factor (SCF) - Regional Bubble Detection
    # -------------------------
    # Apply SCF to dampen SOS for teams in isolated regional bubbles.
    # This prevents circular inflation where teams like Idaho Rush, Idaho Juniors,
    # and Missoula Surf inflate each other's SOS without any national anchor.
    if cfg.SCF_ENABLED and team_state_map is not None:
        logger.info("🔗 Computing Schedule Connectivity Factor (SCF) for regional bubble detection...")

        # Compute SCF for each team based on their schedule diversity
        # Pass base_strength_map so quality override can detect elite schedules
        # (e.g., MLS NEXT teams in regional conferences are NOT bubbles)
        # Pass team_wr_map so quality override requires a winning record (prevents
        # closed-ecosystem teams with losing records from gaming the override)
        team_wr_map = dict(
            zip(
                team["team_id"].astype(str),
                (team["wins"] / team["gp"].clip(lower=1)).fillna(0).values,
            )
        )
        scf_data = compute_schedule_connectivity(
            games_df=g_sos,  # Use full 365-day SOS window (not 30-game recency window)
            team_state_map=team_state_map,
            cfg=cfg,
            strength_map=base_strength_map,
            team_wr_map=team_wr_map,
        )

        # Apply SCF dampening to raw SOS
        team = apply_scf_to_sos(team, scf_data, cfg)

        # Log before/after comparison for diagnostics
        logger.info(
            f"📊 SOS after SCF adjustment: "
            f"mean={team['sos'].mean():.4f}, "
            f"std={team['sos'].std():.4f}, "
            f"range=[{team['sos'].min():.4f}, {team['sos'].max():.4f}]"
        )
    elif cfg.SCF_ENABLED and team_state_map is None:
        logger.warning(
            "⚠️  SCF enabled but team_state_map not provided. Regional bubble detection disabled for this run."
        )

    # NOTE: Pre-percentile SOS shrinkage was REMOVED (was buggy)
    # The old code shrunk raw SOS toward cohort mean before percentile normalization,
    # which injected games-played bias into sos_norm (teams with more games got
    # artificially higher sos_norm even with weak opponents).
    # Sample-size uncertainty is now handled AFTER percentile normalization (see below).

    # SOS Normalization: Per-cohort percentile ranking
    #
    # IMPORTANT: We normalize SOS within each connected component (within the
    # cohort) to ensure SOS has the full [0, 1] range within each ranking group.
    # This guarantees that SOS contributes its intended 50% weight to PowerScore
    # differentiation WITHOUT creating feedback-loop bias between disconnected
    # ecosystems (e.g., ECNL vs MLS NEXT HD).
    #
    # When COMPONENT_SOS_ENABLED=True, the groupby includes component_id so that
    # each disconnected subgraph is normalized independently.  For fully connected
    # graphs (single component), this is equivalent to the old cohort-level
    # normalization.
    #
    # Previous approach (global scaling) caused SOS compression where some cohorts
    # had sos_norm ranges like [0.3, 0.5] instead of [0, 1], effectively reducing
    # SOS contribution to ~10% instead of 50%.

    # Groupby columns for normalization
    global_group_cols = ["age", "gender"]
    component_group_cols = ["age", "gender", "component_id"] if cfg.COMPONENT_SOS_ENABLED else global_group_cols
    # Keep sos_group_cols pointing to component-level for backward compat with downstream code
    sos_group_cols = component_group_cols

    # Percentile rank within each group - ensures full [0, 1] range per group
    def percentile_within_group(x):
        if len(x) <= 1:
            return pd.Series([0.5] * len(x), index=x.index)
        # Round to 10 decimal places before ranking to prevent floating-point
        # noise (diffs < 1e-10) from creating false differentiation.
        # Without this, teams with identical raw SOS (differing only at machine
        # epsilon) get spread across the full [0, 1] range, creating up to 0.40
        # PowerScore gaps from pure noise.
        x_rounded = x.round(10)
        ranks = x_rounded.rank(method="average")
        return (ranks - 1) / (len(x) - 1) if len(x) > 1 else pd.Series([0.5], index=x.index)

    # Select normalization function: hybrid (percentile+zscore blend) or pure percentile
    if cfg.SOS_NORM_HYBRID_ENABLED:
        _sos_norm_fn = lambda x: _hybrid_sos_norm(x, zscore_blend=cfg.SOS_NORM_HYBRID_ZSCORE_BLEND)
        logger.info(f"🔀 Using HYBRID SOS normalization (zscore_blend={cfg.SOS_NORM_HYBRID_ZSCORE_BLEND:.0%})")
    else:
        _sos_norm_fn = percentile_within_group

    def _apply_hybrid_norm(team_df, sos_col="sos", target_col="sos_norm"):
        """Apply hybrid global+component normalization to a SOS column.

        Computes both global (age+gender) and component-level normalization,
        then blends using alpha = clip(log10(component_size) / 2, 0.35, 1.0).
        Alpha represents trust in global normalization. Large components lean
        on global; tiny components still get a 35% global floor.
        """
        # Global normalization: within [age, gender]
        norm_global = team_df.groupby(global_group_cols)[sos_col].transform(_sos_norm_fn)
        norm_global = norm_global.fillna(0.5).clip(0.0, 1.0)

        if cfg.COMPONENT_SOS_ENABLED and "component_size" in team_df.columns:
            # Component normalization: within [age, gender, component_id]
            norm_component = team_df.groupby(component_group_cols)[sos_col].transform(_sos_norm_fn)
            norm_component = norm_component.fillna(0.5).clip(0.0, 1.0)

            # Alpha: trust in global, log-scaled with floor
            alpha = np.clip(np.log10(team_df["component_size"].clip(lower=2).values) / 2.0, 0.35, 1.0)

            # Blend
            team_df[target_col] = alpha * norm_global.values + (1 - alpha) * norm_component.values
        else:
            norm_component = norm_global
            alpha = np.ones(len(team_df))
            team_df[target_col] = norm_global

        team_df[target_col] = team_df[target_col].fillna(0.5).clip(0.0, 1.0)
        return norm_global, norm_component, alpha

    # Apply hybrid normalization
    logger.info("🔄 Computing hybrid global+component SOS normalization")
    norm_global, norm_component, alpha = _apply_hybrid_norm(team)

    # Keep diagnostic columns for this testing cycle
    team["sos_norm_global"] = norm_global
    team["sos_norm_component"] = norm_component
    team["_sos_alpha"] = alpha

    # Log SOS norms summary (per-cohort detail at DEBUG)
    logger.info(
        f"📊 SOS norms: overall min={team['sos_norm'].min():.3f}, max={team['sos_norm'].max():.3f}, mean={team['sos_norm'].mean():.3f}"
    )
    for (age, gender), grp in team.groupby(["age", "gender"]):
        if len(grp) >= 5:
            logger.debug(
                f"  SOS {age} {gender}: min={grp['sos_norm'].min():.3f}, "
                f"max={grp['sos_norm'].max():.3f}, "
                f"mean={grp['sos_norm'].mean():.3f}, n={len(grp)}"
            )

    # ── Three-way normalization comparison diagnostic ──
    if "sos_norm_global" in team.columns and "sos_norm_component" in team.columns:
        from collections import defaultdict

        logger.info("📊 Normalization method comparison (global vs component vs hybrid):")

        # Alpha distribution
        alpha_vals = team["_sos_alpha"]
        logger.info(
            f"  Alpha distribution: p10={alpha_vals.quantile(0.1):.2f}, "
            f"p25={alpha_vals.quantile(0.25):.2f}, p50={alpha_vals.quantile(0.5):.2f}, "
            f"p75={alpha_vals.quantile(0.75):.2f}, p90={alpha_vals.quantile(0.9):.2f}"
        )

        # Per-cohort cross-component variance for all three methods
        for (age_val, gender_val), grp in team.groupby(["age", "gender"]):
            if len(grp) < 50:
                continue
            methods = {
                "global": grp["sos_norm_global"],
                "component": grp["sos_norm_component"],
                "hybrid": grp["sos_norm"],
            }
            # Bin by raw SOS (0.01 bins), compute sos_norm range within each bin
            sos_bins = (grp["sos"] * 100).round() / 100
            result_parts = []
            for method_name, norm_col in methods.items():
                bins_dict = defaultdict(list)
                for s_bin, n_val in zip(sos_bins.values, norm_col.values):
                    if not (np.isnan(s_bin) or np.isnan(n_val)):
                        bins_dict[s_bin].append(n_val)
                ranges = [max(v) - min(v) for v in bins_dict.values() if len(v) >= 5]
                if ranges:
                    result_parts.append(f"{method_name}: mean={np.mean(ranges):.3f}, max={max(ranges):.3f}")
            if result_parts:
                logger.info(f"  {age_val} {gender_val} (n={len(grp)}): {' | '.join(result_parts)}")

        # Pairwise correlation
        corr_gc = team[["sos_norm_global", "sos_norm_component"]].corr().iloc[0, 1]
        corr_gh = team[["sos_norm_global", "sos_norm"]].corr().iloc[0, 1]
        corr_ch = team[["sos_norm_component", "sos_norm"]].corr().iloc[0, 1]
        logger.info(
            f"  Correlations: global-component={corr_gc:.3f}, global-hybrid={corr_gh:.3f}, component-hybrid={corr_ch:.3f}"
        )

    # Low sample handling: smooth shrink toward 0.5 for teams with insufficient games
    # This prevents teams with few games from having extreme SOS values (high or low)
    # while avoiding hard caps that create discontinuities.
    team["sample_flag"] = np.where(team["gp"] < cfg.MIN_GAMES_FOR_TOP_SOS, "LOW_SAMPLE", "OK")

    # Soft shrinkage: blend toward anchor based on sample size
    # Using LINEAR shrinkage for proportional dampening of low-sample teams:
    # - 0 games: shrink_factor = 0.0 (fully shrunk to anchor)
    # - 5 games: shrink_factor = 0.50 (50% of raw SOS retained)
    # - 8 games: shrink_factor = 0.80 (80% of raw SOS retained)
    # - 10+ games: shrink_factor = 1.0 (no shrinkage)
    # Anchor is 0.35 (below-average) to prevent low-GP teams from getting
    # a free "neutral schedule" assumption.
    low_sample_mask = team["gp"] < cfg.MIN_GAMES_FOR_TOP_SOS
    gp_clipped = team["gp"].clip(lower=0)
    shrink_factor = (gp_clipped / cfg.MIN_GAMES_FOR_TOP_SOS).clip(0.0, 1.0)
    anchor = cfg.SOS_SHRINKAGE_ANCHOR

    # Apply shrinkage: sos_norm = anchor + shrink_factor * (sos_norm - anchor)
    team.loc[low_sample_mask, "sos_norm"] = anchor + shrink_factor[low_sample_mask] * (
        team.loc[low_sample_mask, "sos_norm"] - anchor
    )

    low_sample_count = low_sample_mask.sum()
    if low_sample_count > 0:
        logger.info(f"🏷️  Low sample handling: {low_sample_count} teams with soft SOS shrinkage toward {anchor}")

    # Correlation guardrail + GP-SOS decorrelation
    # Detects if games-played is leaking into sos_norm, and for age buckets
    # where it is, residualizes out the GP effect among ranked teams.
    if len(team) < 3:
        logger.info(f"✅ GP-SOS correlation check skipped: only {len(team)} team(s)")
    else:
        gp_sos_corr = team[["gp", "sos_norm"]].corr().iloc[0, 1]
        if pd.isna(gp_sos_corr):
            logger.warning("⚠️  GP-SOS correlation is NaN (possible zero variance). Skipping check.")
        elif abs(gp_sos_corr) > 0.10:
            logger.warning(
                f"⚠️  GP-SOS correlation detected: {gp_sos_corr:.3f} (threshold: ±0.10). "
                f"This may indicate games-played bias in SOS calculation."
            )
        else:
            logger.info(f"✅ GP-SOS correlation check passed: {gp_sos_corr:.3f} (within ±0.10)")

        # Per-age-bucket GP-SOS correlation breakdown + decorrelation
        decorrelation_applied = 0
        if "age" in team.columns:
            age_col_numeric = pd.to_numeric(team["age"], errors="coerce")
            for age_val in sorted(age_col_numeric.dropna().unique()):
                age_mask = age_col_numeric == age_val
                unshrunk_mask = age_mask & (team["gp"] >= cfg.MIN_GAMES_FOR_TOP_SOS)
                age_subset = team.loc[unshrunk_mask, ["gp", "sos_norm"]].dropna()
                if len(age_subset) < 10:
                    continue
                age_corr = age_subset.corr().iloc[0, 1]
                if pd.isna(age_corr):
                    continue
                median_gp = age_subset["gp"].median()

                if abs(age_corr) > 0.10:
                    logger.warning(
                        f"  ⚠️ Age {int(age_val)}: GP-SOS corr={age_corr:.3f} "
                        f"(n={len(age_subset)}, median_gp={median_gp:.0f})"
                    )
                else:
                    logger.debug(
                        f"  Age {int(age_val)}: GP-SOS corr={age_corr:.3f} "
                        f"(n={len(age_subset)}, median_gp={median_gp:.0f})"
                    )

                # GP-SOS decorrelation: only for unshrunk teams in biased age buckets
                # Uses MIN_GAMES_FOR_TOP_SOS (not MIN_GAMES_PROVISIONAL) to exclude
                # teams whose sos_norm was altered by low-sample shrinkage.
                if cfg.GP_SOS_DECORRELATION_ENABLED and abs(age_corr) > cfg.GP_SOS_DECORRELATION_THRESHOLD:
                    # Target: unshrunk teams in this age bucket
                    ranked_mask = age_mask & (team["gp"] >= cfg.MIN_GAMES_FOR_TOP_SOS)
                    ranked_idx = team.index[ranked_mask]
                    if len(ranked_idx) < 10:
                        continue

                    # Residualize sos_norm against GP via OLS within ranked teams
                    # sos_norm_adj = sos_norm - beta * (gp - gp_mean)
                    # This removes the linear GP→SOS relationship while preserving
                    # the mean sos_norm and all non-GP-related variation.
                    gp_ranked = team.loc[ranked_idx, "gp"].astype(float).values
                    sos_ranked = team.loc[ranked_idx, "sos_norm"].astype(float).values
                    gp_mean = gp_ranked.mean()
                    gp_centered = gp_ranked - gp_mean

                    # OLS slope: beta = cov(gp, sos) / var(gp)
                    gp_var = np.var(gp_centered)
                    if gp_var > 0:
                        beta = np.cov(gp_centered, sos_ranked)[0, 1] / gp_var
                        sos_adjusted = sos_ranked - beta * gp_centered
                        # Re-clip to [0, 1] since residualization can push outside bounds
                        sos_adjusted = np.clip(sos_adjusted, 0.0, 1.0)
                        team.loc[ranked_idx, "sos_norm"] = sos_adjusted

                        # Verify the fix worked
                        new_corr = np.corrcoef(gp_ranked, sos_adjusted)[0, 1]
                        decorrelation_applied += 1
                        logger.info(
                            f"  ✅ Age {int(age_val)}: GP-SOS decorrelated for {len(ranked_idx)} ranked teams "
                            f"(beta={beta:.4f}, corr {age_corr:.3f} → {new_corr:.3f})"
                        )

        if decorrelation_applied > 0:
            logger.info(f"📊 GP-SOS decorrelation applied to {decorrelation_applied} age bucket(s)")

    # -------------------------
    # Layer 6: Performance
    # -------------------------
    g_perf = g.copy()
    g_perf["team_power"] = g_perf["team_id"].map(lambda t: power_map.get(t, 0.5))
    g_perf["opp_power"] = g_perf["opp_id"].map(lambda t: power_map.get(t, 0.5))
    g_perf["exp_margin"] = cfg.PERFORMANCE_GOAL_SCALE * (g_perf["team_power"] - g_perf["opp_power"])
    g_perf["perf_delta"] = (g_perf["gd"] - g_perf["exp_margin"]).astype(float)

    # threshold noise
    small = g_perf["perf_delta"].abs() < cfg.PERFORMANCE_THRESHOLD
    g_perf.loc[small, "perf_delta"] = 0.0

    # recency decay using rank_recency (1 is most recent)
    g_perf["recency_decay"] = np.exp(-cfg.PERFORMANCE_DECAY_RATE * (g_perf["rank_recency"] - 1.0))

    # per-game performance contribution (symmetric)
    # Uses PERF_GAME_SCALE to scale individual game residuals
    g_perf["perf_contrib"] = (
        cfg.PERF_GAME_SCALE * g_perf["perf_delta"] * g_perf["recency_decay"] * g_perf["k_adapt"] * g_perf["w_game"]
    )

    perf_team = (
        g_perf.groupby(["team_id", "age", "gender"], as_index=False)["perf_contrib"]
        .sum()
        .rename(columns={"perf_contrib": "perf_raw"})
    )
    team = team.merge(perf_team, on=["team_id", "age", "gender"], how="left").fillna({"perf_raw": 0.0})

    # percentile 0..1, then center to [-0.5, +0.5]
    team["perf_centered"] = team.groupby(["age", "gender"])["perf_raw"].transform(
        lambda s: s.rank(method="average", pct=True) - 0.5
    )

    # Apply PERF_CAP: clip perf_centered to [-cap, +cap] to limit outlier influence.
    # This prevents teams from gaining outsized boost by running up scores against
    # weak opponents. Mid-range teams (perf close to 0) are unaffected.
    team["perf_centered"] = team["perf_centered"].clip(-cfg.PERF_CAP, cfg.PERF_CAP)

    # -------------------------
    # SOS Trim Diagnostics
    # -------------------------
    if cfg.SOS_TRIM_BOTTOM_PCT > 0 and "sos_orig" in team.columns:
        sos_shift = team["sos"] - team["sos_orig"]
        teams_trimmed = (sos_shift.abs() > 1e-6).sum()

        # Normalize sos_orig through the same hybrid normalization for downstream comparison
        _apply_hybrid_norm(team, sos_col="sos_orig", target_col="sos_norm_orig")

        # Hybrid metric for comparison (not used in scoring)
        team["sos_hybrid"] = 0.7 * team["sos"] + 0.3 * team["sos_orig"]

        # 1. Cohort-level before/after
        logger.info(
            f"📊 SOS Trim Diagnostics: {teams_trimmed}/{len(team)} teams affected, "
            f"raw shift: mean={sos_shift.mean():+.4f}, median={sos_shift.median():+.4f}"
        )

        # 2. GP-SOS correlation before/after
        gp_sos_corr_orig = team[["gp", "sos_orig"]].corr().iloc[0, 1]
        gp_sos_corr_trim = team[["gp", "sos"]].corr().iloc[0, 1]
        logger.info(f"  GP-SOS correlation: orig={gp_sos_corr_orig:.3f} -> trimmed={gp_sos_corr_trim:.3f}")

        # 3. GP bucket analysis
        gp_buckets = pd.cut(team["gp"], bins=[0, 9, 14, 19, 29, 999], labels=["1-9", "10-14", "15-19", "20-29", "30+"])
        bucket_shifts = sos_shift.groupby(gp_buckets, observed=True)
        for bucket, grp in bucket_shifts:
            if len(grp) > 0:
                logger.info(f"  GP {bucket}: n={len(grp)}, avg_shift={grp.mean():+.4f}")

        # 4. Trim count distribution (how many games trimmed per team)
        if "w_sos_orig" in g_sos.columns:
            is_trimmed = (g_sos["w_sos"] < g_sos["w_sos_orig"] - 1e-9).groupby(g_sos["team_id"]).sum()
            trimmed_nonzero = is_trimmed[is_trimmed > 0]
            if len(trimmed_nonzero) > 0:
                pcts = trimmed_nonzero.quantile([0.25, 0.50, 0.75, 0.90])
                logger.info(
                    f"  Trim distribution (n={len(trimmed_nonzero)} teams): "
                    f"p25={pcts[0.25]:.0f}, p50={pcts[0.50]:.0f}, "
                    f"p75={pcts[0.75]:.0f}, p90={pcts[0.90]:.0f}, "
                    f"max_cap_hits={int((is_trimmed >= cfg.SOS_TRIM_MAX_GAMES).sum())}"
                )

        # 5. Top opponent exposure (avg top-5 and top-10 opp strength)
        if "opp_strength" in g_sos.columns:
            # Rank opponents by strength descending within each team (vectorized, no groupby.apply)
            _opp_desc_rank = g_sos.groupby("team_id")["opp_strength"].rank(method="first", ascending=False)
            top_n_stats = []
            for n in [5, 10]:
                top_n_mask = _opp_desc_rank <= n
                top_n_avg = g_sos.loc[top_n_mask].groupby("team_id")["opp_strength"].mean()
                top_n_stats.append(f"top-{n} avg={top_n_avg.mean():.3f}")
            logger.info(f"  Top opponent exposure: {', '.join(top_n_stats)}")

        # 6. Biggest movers (top 10 up, top 10 down)
        team_shifts = pd.DataFrame(
            {
                "team_id": team["team_id"],
                "shift": sos_shift,
                "sos": team["sos"],
                "sos_orig": team["sos_orig"],
                "gp": team["gp"],
            }
        )
        top_up = team_shifts.nlargest(10, "shift")
        top_down = team_shifts.nsmallest(10, "shift")
        logger.info("  Top 10 SOS gainers:")
        for _, r in top_up.iterrows():
            logger.info(
                f"    {r['team_id'][:12]} | GP:{r['gp']:>2.0f} | {r['sos_orig']:.4f} -> {r['sos']:.4f} ({r['shift']:+.4f})"
            )
        logger.info("  Top 10 SOS losers:")
        for _, r in top_down.iterrows():
            logger.info(
                f"    {r['team_id'][:12]} | GP:{r['gp']:>2.0f} | {r['sos_orig']:.4f} -> {r['sos']:.4f} ({r['shift']:+.4f})"
            )

        # 7. sos_norm before/after comparison
        norm_shift = team["sos_norm"] - team["sos_norm_orig"]
        logger.info(
            f"  sos_norm shift: mean={norm_shift.mean():+.4f}, std={norm_shift.std():.4f}, "
            f"range=[{norm_shift.min():+.4f}, {norm_shift.max():+.4f}]"
        )

    # -------------------------
    # Layer 10: Core PowerScore + Provisional
    # -------------------------
    # Uses PERF_BLEND_WEIGHT to control how much performance adjustment affects final score.
    # With PERF_BLEND_WEIGHT=0.00 (default since v54), perf_centered is still computed
    # and stored for diagnostics but does not affect the final score.
    #
    # The theoretical max of the raw sum is 1.0 + PERF_CAP * PERF_BLEND_WEIGHT.
    # We normalize by this max to ensure powerscore_core stays in [0, 1] range.

    MAX_POWERSCORE_THEORETICAL = 1.0 + cfg.PERF_CAP * cfg.PERF_BLEND_WEIGHT

    team["powerscore_core"] = (
        cfg.OFF_WEIGHT * team["off_norm"]
        + cfg.DEF_WEIGHT * team["def_norm"]
        + cfg.SOS_WEIGHT * team["sos_norm"]
        + team["perf_centered"] * cfg.PERF_BLEND_WEIGHT
    ) / MAX_POWERSCORE_THEORETICAL

    team["provisional_mult"] = team["gp"].apply(lambda gp: _provisional_multiplier(int(gp), cfg.MIN_GAMES_PROVISIONAL))
    team["powerscore_adj"] = team["powerscore_core"] * team["provisional_mult"]

    # -------------------------
    # Power-SOS Co-Calculation: Use opponent's FULL power for SOS
    # -------------------------
    # This iteratively refines SOS using opponent's full power score (including their SOS),
    # rather than just their off/def. This ensures that playing teams with tough schedules
    # properly boosts your SOS.
    #
    # Algorithm:
    # 1. Initial pass already calculated SOS using off/def only (base_strength_map)
    # 2. Now we have initial powerscore_adj which includes that SOS
    # 3. Rebuild strength map using full power (includes SOS)
    # 4. Recalculate SOS using full power strength map
    # 5. Recalculate power score with new SOS
    # 6. Repeat until convergence

    if cfg.SOS_POWER_ITERATIONS > 0:
        logger.info(f"🔄 Starting Power-SOS co-calculation ({cfg.SOS_POWER_ITERATIONS} iterations)...")

        # Pre-compute static values outside loop
        team_ids = team["team_id"].values
        provisional_mults = team["provisional_mult"].values
        off_norms = team["off_norm"].values
        def_norms = team["def_norm"].values
        perf_centereds = team["perf_centered"].values
        gps = team["gp"].values

        # Pre-compute weights for power score formula
        w_off = cfg.OFF_WEIGHT
        w_def = cfg.DEF_WEIGHT
        w_sos = cfg.SOS_WEIGHT
        w_perf = cfg.PERF_BLEND_WEIGHT

        # Build opponent lookup from g_sos once (game-level data doesn't change)
        opp_ids_array = g_sos["opp_id"].values
        team_ids_sos = g_sos["team_id"].values
        w_sos_array = g_sos["w_sos"].values

        # Capture pre-iteration SOS baseline for boost capping
        sos_baseline = team["sos"].values.copy()

        for power_iter in range(cfg.SOS_POWER_ITERATIONS):
            # Store previous values for convergence tracking
            prev_sos = team["sos"].values.copy()
            prev_power = team["powerscore_adj"].values.copy()

            # Step 1: Build FULL power strength map with OFF/DEF floor
            # The floor prevents circular depression in closed elite leagues (e.g., MLS NEXT HD).
            # Without it, the loop spirals: depressed SOS → lower power → lower opponent strength
            # → even lower SOS. The floor says: "a team's contribution to opponents' SOS
            # cannot drop below their raw OFF/DEF quality (base_strength)."
            # Impact: +0.24 for closed elite leagues (correct fix), +0.03 for bubbles (negligible).
            # True competitive strength (no anchor scaling — anchor applied only at final scoring)
            full_power_values = team["powerscore_adj"].values.clip(0.0, 1.0)
            base_strength_values = (
                pd.Series(team_ids).map(pd.Series(base_strength_map)).fillna(cfg.UNRANKED_SOS_BASE).values
            )
            floored_power_values = np.maximum(full_power_values, base_strength_values)
            full_power_strength_map = dict(zip(team_ids, floored_power_values))

            # Diagnostic: Power-SOS iteration distribution (for anchor-isolation validation)
            logger.info(
                f"  Iteration {power_iter}: full_power mean={full_power_values.mean():.4f}, "
                f"std={np.std(full_power_values):.4f}, "
                f"sos_delta={np.abs(team['sos'].values - prev_sos).mean():.6f}"
            )

            # Step 2: Vectorized opponent strength lookup via pandas Series.map
            full_power_series = pd.Series(full_power_strength_map)
            opp_strengths = pd.Series(opp_ids_array).map(full_power_series)
            if global_strength_map:
                global_series = pd.Series(global_strength_map)
                # For missing values, try string key lookup in global map
                missing_mask = opp_strengths.isna()
                if missing_mask.any():
                    str_keys = pd.Series(opp_ids_array)[missing_mask].astype(str)
                    opp_strengths.loc[missing_mask] = str_keys.map(global_series)
            opp_strengths = opp_strengths.fillna(cfg.UNRANKED_SOS_BASE).values
            g_sos["opp_full_strength"] = opp_strengths

            # Step 2b: Restore original weights and re-trim with updated strengths
            # Safety invariant: always start from w_sos_orig to prevent double-trimming
            if cfg.SOS_TRIM_BOTTOM_PCT > 0 and "w_sos_orig" in g_sos.columns:
                g_sos["w_sos"] = g_sos["w_sos_orig"].copy()
                _apply_sos_trim(g_sos, "opp_full_strength")

            # Step 3: Recalculate SOS using full opponent strength (vectorized groupby)
            sos_full = (
                g_sos.groupby("team_id", group_keys=False)
                .apply(lambda d: _avg_weighted(d, "opp_full_strength", "w_sos"), include_groups=False)
                .rename("sos")
                .reset_index()
            )

            # Step 4: Update team SOS with damping to prevent oscillation
            # new_sos = damping * calculated_sos + (1 - damping) * previous_sos
            sos_map = dict(zip(sos_full["team_id"], sos_full["sos"]))
            new_sos = team["team_id"].map(sos_map).fillna(0.5)
            team["sos"] = cfg.SOS_POWER_DAMPING * new_sos + (1 - cfg.SOS_POWER_DAMPING) * prev_sos

            # Step 4b: Cap iteration boost relative to pre-iteration baseline
            # Prevents regional bubbles where tight clusters inflate each other's SOS
            if cfg.SOS_POWER_MAX_BOOST > 0:
                sos_values = team["sos"].values
                max_allowed = sos_baseline + cfg.SOS_POWER_MAX_BOOST
                capped_count = int((sos_values > max_allowed).sum())
                team["sos"] = np.minimum(sos_values, max_allowed)
                if capped_count > 0:
                    logger.debug(
                        f"  Power-SOS iter {power_iter + 1}: capped {capped_count} teams "
                        f"at +{cfg.SOS_POWER_MAX_BOOST:.3f} boost"
                    )

            # Step 5: Re-normalize SOS using hybrid global+component blend
            # Same approach as initial normalization to maintain consistency.
            _apply_hybrid_norm(team)

            # Step 6: Apply low-sample shrinkage (vectorized) - LINEAR toward anchor
            # NOTE: This is NOT compounding — each iteration recalculates sos_norm fresh
            # from scratch (step 5 above), so this shrinks a fresh value each time.
            low_sample_mask = gps < cfg.MIN_GAMES_FOR_TOP_SOS
            shrink_factor = np.clip(gps / cfg.MIN_GAMES_FOR_TOP_SOS, 0.0, 1.0)
            sos_norm_values = team["sos_norm"].values.copy()
            anchor = cfg.SOS_SHRINKAGE_ANCHOR
            sos_norm_values[low_sample_mask] = anchor + shrink_factor[low_sample_mask] * (
                sos_norm_values[low_sample_mask] - anchor
            )
            team["sos_norm"] = sos_norm_values

            # Step 6b: GP-SOS decorrelation (same as initial pass)
            # Re-apply per iteration since sos_norm is recalculated fresh each time.
            if cfg.GP_SOS_DECORRELATION_ENABLED and "age" in team.columns:
                age_col_iter = pd.to_numeric(team["age"], errors="coerce")
                for age_val in age_col_iter.dropna().unique():
                    age_mask = age_col_iter == age_val
                    ranked_mask = age_mask & (team["gp"] >= cfg.MIN_GAMES_FOR_TOP_SOS)
                    ranked_idx = team.index[ranked_mask]
                    if len(ranked_idx) < 10:
                        continue
                    gp_r = team.loc[ranked_idx, "gp"].astype(float).values
                    sos_r = team.loc[ranked_idx, "sos_norm"].astype(float).values
                    age_corr = np.corrcoef(gp_r, sos_r)[0, 1]
                    if pd.isna(age_corr) or abs(age_corr) <= cfg.GP_SOS_DECORRELATION_THRESHOLD:
                        continue
                    gp_c = gp_r - gp_r.mean()
                    gp_var = np.var(gp_c)
                    if gp_var > 0:
                        beta = np.cov(gp_c, sos_r)[0, 1] / gp_var
                        team.loc[ranked_idx, "sos_norm"] = np.clip(sos_r - beta * gp_c, 0.0, 1.0)

            # Step 7: Recalculate power score with new SOS (vectorized)
            sos_norm_arr = team["sos_norm"].values
            powerscore_core = (
                w_off * off_norms + w_def * def_norms + w_sos * sos_norm_arr + perf_centereds * w_perf
            ) / MAX_POWERSCORE_THEORETICAL

            team["powerscore_core"] = powerscore_core
            team["powerscore_adj"] = powerscore_core * provisional_mults

            # Step 8: Calculate convergence metrics
            sos_change = np.abs(team["sos"].values - prev_sos).mean()
            power_change = np.abs(team["powerscore_adj"].values - prev_power).mean()

            _iter_log = logger.info if power_iter == cfg.SOS_POWER_ITERATIONS - 1 else logger.debug
            _iter_log(
                f"  Power-SOS iter {power_iter + 1}/{cfg.SOS_POWER_ITERATIONS}: "
                f"sos_change={sos_change:.6f}, power_change={power_change:.6f}, "
                f"sos_range=[{team['sos'].min():.4f}, {team['sos'].max():.4f}]"
            )

            # Early termination if converged
            if sos_change < 0.0001 and power_change < 0.0001:
                logger.info(f"  ✅ Power-SOS converged after {power_iter + 1} iterations")
                break

        logger.info(
            f"✅ Power-SOS co-calculation complete: "
            f"final_sos_range=[{team['sos'].min():.4f}, {team['sos'].max():.4f}], "
            f"final_power_range=[{team['powerscore_adj'].min():.4f}, {team['powerscore_adj'].max():.4f}]"
        )

    # NOTE: Anchor-based scaling is now applied globally in compute_all_cohorts()
    # after all cohorts are combined. This ensures proper cross-age scaling.

    # -------------------------
    # Layer 11: Rank & status
    # -------------------------
    # Calculate days since last game (handle NULL last_game)
    team["days_since_last"] = (pd.Timestamp(today) - pd.to_datetime(team["last_game"], errors="coerce")).dt.days

    # Filter teams based on games in activity window (INACTIVE_HIDE_DAYS, aligned with WINDOW_DAYS=365)
    # Status priority:
    # 1. "Inactive" - No games in activity window (gp_last_window == 0) OR last_game is NULL OR days_since_last >= INACTIVE_HIDE_DAYS
    #    Note: Use >= to match the gp_last_window calculation which uses >= cutoff (includes games exactly at boundary)
    # 2. "Not Enough Ranked Games" - Has games in activity window but < MIN_GAMES_PROVISIONAL (6 games)
    # 3. "Active" - Has >= MIN_GAMES_PROVISIONAL games in activity window
    team["status"] = np.where(
        (team["gp_last_window"] == 0)
        | (team["last_game"].isna())
        | (team["days_since_last"].fillna(999) >= cfg.INACTIVE_HIDE_DAYS),
        "Inactive",
        np.where(team["gp_last_window"] < cfg.MIN_GAMES_PROVISIONAL, "Not Enough Ranked Games", "Active"),
    )

    # Log status distribution summary
    status_counts = team["status"].value_counts().to_dict()
    logger.info(f"📊 Team status distribution: {status_counts}")
    nan_ps = team["powerscore_adj"].isna().sum()
    if nan_ps > 0:
        logger.warning(f"⚠️ {nan_ps} teams have NaN powerscore_adj")

    # Initialize rank_in_cohort as NULL for all teams
    team["rank_in_cohort"] = None

    # Only rank teams with "Active" status to avoid gaps in ranking numbers
    # Filter active teams, sort, rank, then merge back using team_id as key
    active_mask = team["status"] == "Active"
    active_teams = team[active_mask].copy()

    if not active_teams.empty:
        # Sort active teams for ranking: powerscore DESC, then SOS DESC (tiebreaker)
        # This ensures teams with same PowerScore are differentiated by schedule strength
        active_teams = active_teams.sort_values(
            ["gender", "age", "powerscore_adj", "sos"], ascending=[True, True, False, False]
        ).reset_index(drop=True)

        # Calculate unique ranks based on sort order (no ties)
        # Teams with same PowerScore but different SOS get different ranks
        active_teams["rank_in_cohort"] = active_teams.groupby(["age", "gender"]).cumcount() + 1

        # Merge ranks back into full team DataFrame using team_id as key
        rank_map = dict(zip(active_teams["team_id"], active_teams["rank_in_cohort"]))
        team.loc[active_mask, "rank_in_cohort"] = team.loc[active_mask, "team_id"].map(rank_map)

    # Sort full team DataFrame for consistent output order (with SOS tiebreaker)
    team = team.sort_values(
        ["gender", "age", "powerscore_adj", "sos"], ascending=[True, True, False, False]
    ).reset_index(drop=True)

    # outputs
    games_used_cols = [
        "game_id",
        "date",
        "team_id",
        "opp_id",
        "age",
        "gender",
        "opp_age",
        "opp_gender",
        "gf",
        "ga",
        "gd",
        "w_base",
        "k_adapt",
        "w_game",
        "w_sos",
        "rank_recency",
    ]
    # Return the 365-day SOS games (after repeat-cap) that actually fed SOS.
    games_used = g_sos[[c for c in games_used_cols if c in g_sos.columns]].copy()

    keep_cols = [
        "team_id",
        "age",
        "gender",
        "gp",
        "gp_last_window",
        "last_game",
        "status",
        "rank_in_cohort",
        "wins",
        "losses",
        "draws",
        "off_raw",
        "sad_raw",
        "off_shrunk",
        "sad_shrunk",
        "def_shrunk",
        "off_norm",
        "def_norm",
        "sos",
        "sos_norm",
        "sample_flag",
        "power_presos",
        "anchor",
        "abs_strength",
        "perf_raw",
        "perf_centered",
        "powerscore_core",
        "provisional_mult",
        "powerscore_adj",
    ]
    # Add SCF columns if they exist (from regional bubble detection)
    scf_cols = ["scf", "bridge_games", "is_isolated", "unique_opp_states", "quality_boosted"]
    for col in scf_cols:
        if col in team.columns:
            keep_cols.append(col)
    teams = team[keep_cols].copy()

    # === Clamp PowerScore to [0.0, 1.0] (spec requirement) ===
    teams["powerscore_adj"] = teams["powerscore_adj"].clip(0.0, 1.0)
    if "powerscore_core" in teams.columns:
        teams["powerscore_core"] = teams["powerscore_core"].clip(0.0, 1.0)

    # === Restore legacy frontend fields ===
    # Map powerscore_adj to power_score_final
    teams["power_score_final"] = teams["powerscore_adj"]

    # Map rank_in_cohort to rank_in_cohort_final (convert to float, handle None)
    # Use pd.to_numeric to handle None values properly (converts None to NaN, which becomes NULL in DB)
    teams["rank_in_cohort_final"] = pd.to_numeric(teams["rank_in_cohort"], errors="coerce")

    # State rank must be computed — fallback to cohort rank for now
    # (State information is not available in v53e output, will be computed later in pipeline)
    teams["rank_in_state_final"] = teams["rank_in_cohort_final"]

    # SOS rankings: compute ranks within each (age, gender) cohort
    # Only "Active" teams get SOS rankings — this is derived from MIN_GAMES_PROVISIONAL
    # so the two gates can never drift apart.
    # Create mask for teams eligible for SOS ranking
    sos_rank_eligible = teams["status"] == "Active"

    # Initialize sos_rank_national as None (will be filled only for eligible teams)
    teams["sos_rank_national"] = pd.Series([None] * len(teams), dtype="Int64")

    # Compute SOS rank only for eligible teams within each cohort
    for (age, gender), cohort_df in teams.groupby(["age", "gender"]):
        eligible_mask = sos_rank_eligible & (teams["age"] == age) & (teams["gender"] == gender)
        eligible_idx = teams.loc[eligible_mask].index

        if len(eligible_idx) > 0:
            # Rank only among eligible teams (those with enough games)
            eligible_sos_values = teams.loc[eligible_idx, "sos_norm"]
            ranks = eligible_sos_values.rank(ascending=False, method="min")
            teams.loc[eligible_idx, "sos_rank_national"] = ranks.astype("Int64")

    # Log how many teams are excluded from SOS ranking
    excluded_count = (~sos_rank_eligible).sum()
    total_count = len(teams)
    logger.info(
        f"📊 SOS Ranking: {total_count - excluded_count:,} Active teams eligible, "
        f"{excluded_count:,} non-Active teams excluded"
    )

    # State rank: fallback to national rank if state unavailable
    # (State information is not available in v53e output, will be computed later in pipeline)
    teams["sos_rank_state"] = teams["sos_rank_national"].copy()

    # Map offense/defense norm fields
    teams["offense_norm"] = teams["off_norm"]
    teams["defense_norm"] = teams["def_norm"]

    # For data freshness
    teams["last_calculated"] = pd.Timestamp.now("UTC")

    # Games played summary for the frontend
    teams["games_played"] = teams["gp"]
    teams["wins"] = teams["wins"].fillna(0).astype(int)
    teams["losses"] = teams["losses"].fillna(0).astype(int)
    teams["draws"] = teams["draws"].fillna(0).astype(int)
    teams["total_games_played"] = teams["gp"]
    teams["total_wins"] = teams["wins"]
    teams["total_losses"] = teams["losses"]
    teams["total_draws"] = teams["draws"]
    teams["win_percentage"] = np.where(
        teams["gp"] > 0,
        (teams["wins"] / teams["gp"] * 100).round(1),
        0.0,
    )

    return {
        "teams": teams,
        "games_used": games_used,
        "pre_sos_state": _current_pre_sos_state,
    }
