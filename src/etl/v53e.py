
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, List
import logging
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
    INACTIVE_HIDE_DAYS: int = 180

    # Layer 2
    MAX_GAMES_FOR_RANK: int = 30
    GOAL_DIFF_CAP: int = 6
    OUTLIER_GUARD_ZSCORE: float = 2.5  # per-team, per-game GF/GA clip

    # Layer 3 (recency)
    RECENT_K: int = 15
    RECENT_SHARE: float = 0.65
    DAMPEN_TAIL_START: int = 26
    DAMPEN_TAIL_END: int = 30
    DAMPEN_TAIL_START_WEIGHT: float = 0.8
    DAMPEN_TAIL_END_WEIGHT: float = 0.4

    # Layer 4 (defense ridge)
    RIDGE_GA: float = 0.25

    # Layer 5 (Adaptive K + team-level outlier guard)
    ADAPTIVE_K_ALPHA: float = 0.5
    ADAPTIVE_K_BETA: float = 0.6
    TEAM_OUTLIER_GUARD_ZSCORE: float = 2.5  # clip aggregated OFF/DEF extremes

    # Layer 6 (Performance)
    PERFORMANCE_K: float = 0.15  # Legacy: kept for backward compatibility, use PERF_* instead
    PERF_GAME_SCALE: float = 0.15  # Scales per-game performance residual
    PERF_BLEND_WEIGHT: float = 0.15  # Weight of perf_centered in final powerscore
    PERFORMANCE_DECAY_RATE: float = 0.08   # decay per recency index step
    PERFORMANCE_THRESHOLD: float = 2.0     # goals
    PERFORMANCE_GOAL_SCALE: float = 5.0    # goals per 1.0 power diff

    # Layer 7 (Bayesian shrink)
    SHRINK_TAU: float = 8.0

    # Layer 8 (SOS)
    UNRANKED_SOS_BASE: float = 0.35
    SOS_REPEAT_CAP: int = 2  # Reduced from 4 to prevent regional rivals from dominating SOS
    SOS_ITERATIONS: int = 1  # Single-pass: direct opponent strength only (no transitive propagation)
    SOS_TRANSITIVITY_LAMBDA: float = 0.0  # Pure direct SOS — transitive propagation causes closed-league inflation

    # Power-SOS Co-Calculation: DISABLED — loop erases SCF + PageRank dampening
    # The loop recomputes SOS from abs_strength (same inputs as the initial pass) but
    # WITHOUT re-applying PageRank dampening, SCF, or isolation caps. After 5 iterations
    # the 80/20 blend washes away all anti-inflation corrections, causing isolated regional
    # bubble teams to show inflated SOS over nationally-scheduled teams.
    # Set to 0 until the loop is redesigned to re-apply corrections each iteration.
    SOS_POWER_ITERATIONS: int = 0  # DISABLED: was erasing SCF/PageRank (see comment above)
    SOS_POWER_DAMPING: float = 0.80  # Damping factor to prevent oscillation (0.5-0.9 recommended)

    # SOS sample size weighting
    # NOTE: SOS_SAMPLE_SIZE_THRESHOLD is DEPRECATED - pre-percentile shrinkage was removed
    # because it caused games-played bias in sos_norm. Kept for backward compatibility only.
    SOS_SAMPLE_SIZE_THRESHOLD: int = 25  # DEPRECATED: no longer used
    OPPONENT_SAMPLE_SIZE_THRESHOLD: int = 20  # DEPRECATED: no longer used (opponent shrinkage removed)
    MIN_GAMES_FOR_TOP_SOS: int = 10  # Post-percentile shrinkage threshold (teams < this shrink toward 0.5)
    # NOTE: SOS_TOP_CAP_FOR_LOW_SAMPLE is DEPRECATED - hard caps were replaced with soft shrinkage
    SOS_TOP_CAP_FOR_LOW_SAMPLE: float = 0.70  # DEPRECATED: no longer used

    # Minimum games to appear in SOS rankings (teams below this get NULL sos_rank)
    # This prevents teams with very few games from appearing as #1 SOS nationally
    # NOTE: This affects SOS RANKING only, not the SOS VALUE (sos_norm still computed for PowerScore)
    MIN_GAMES_FOR_SOS_RANK: int = 10

    # Opponent-adjusted offense/defense (fixes double-counting)
    OPPONENT_ADJUST_ENABLED: bool = True
    OPPONENT_ADJUST_BASELINE: float = 0.5  # Reference strength for adjustment
    OPPONENT_ADJUST_CLIP_MIN: float = 0.4  # Min multiplier (avoid extreme adjustments)
    OPPONENT_ADJUST_CLIP_MAX: float = 1.6  # Max multiplier (conservative bounds)

    # Layer 10 weights
    OFF_WEIGHT: float = 0.25
    DEF_WEIGHT: float = 0.25
    SOS_WEIGHT: float = 0.50

    # Provisional
    MIN_GAMES_PROVISIONAL: int = 5

    # Context multipliers
    TOURNAMENT_KO_MULT: float = 1.10
    SEMIS_FINALS_MULT: float = 1.05

    # Cross-age anchors (national unification)
    ANCHOR_PERCENTILE: float = 0.98

    # Normalization mode
    NORM_MODE: str = "zscore"  # or "percentile"

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

    # Isolation Penalty via Bridge Games
    # Bridge games = games against teams from outside your state cluster
    # If a team has few bridge games, their SOS is less reliable
    ISOLATION_PENALTY_ENABLED: bool = True
    MIN_BRIDGE_GAMES: int = 2  # Minimum games vs out-of-state opponents for full SOS
    ISOLATION_SOS_CAP: float = 0.70  # Max SOS for teams with no bridge games

    # Regional clustering (US geographic regions for better granularity)
    # Teams playing only within their region get lower SCF than teams playing nationally
    REGIONAL_CLUSTERING_ENABLED: bool = True

    # =========================
    # PageRank-Style SOS Dampening (Layer 8c)
    # =========================
    # Math safety net: Prevents SOS from drifting upward infinitely in isolated clusters.
    # DISABLED: Redundant when SCF is active — both compress SOS toward 0.5,
    # and stacking them causes double-dampening that over-penalizes in-state teams.
    # SCF handles bubble detection in a smarter, targeted way. PageRank adds a
    # blanket 15% compression on ALL teams including well-connected ones.
    # Re-enable only if SCF is disabled.
    PAGERANK_DAMPENING_ENABLED: bool = False
    PAGERANK_ALPHA: float = 0.85  # Dampening factor (0.85 = 15% baseline anchor)
    PAGERANK_BASELINE: float = 0.5  # Baseline SOS to anchor toward (neutral)


# =========================
# US State to Region mapping (for SCF calculation)
# =========================
STATE_TO_REGION = {
    # Pacific
    'CA': 'pacific', 'OR': 'pacific', 'WA': 'pacific', 'AK': 'pacific', 'HI': 'pacific',
    # Mountain
    'MT': 'mountain', 'ID': 'mountain', 'WY': 'mountain', 'NV': 'mountain',
    'UT': 'mountain', 'CO': 'mountain', 'AZ': 'mountain', 'NM': 'mountain',
    # West North Central
    'ND': 'west_north_central', 'SD': 'west_north_central', 'NE': 'west_north_central',
    'KS': 'west_north_central', 'MN': 'west_north_central', 'IA': 'west_north_central', 'MO': 'west_north_central',
    # West South Central
    'TX': 'west_south_central', 'OK': 'west_south_central', 'AR': 'west_south_central', 'LA': 'west_south_central',
    # East North Central
    'WI': 'east_north_central', 'MI': 'east_north_central', 'IL': 'east_north_central',
    'IN': 'east_north_central', 'OH': 'east_north_central',
    # East South Central
    'KY': 'east_south_central', 'TN': 'east_south_central', 'MS': 'east_south_central', 'AL': 'east_south_central',
    # South Atlantic
    'WV': 'south_atlantic', 'VA': 'south_atlantic', 'MD': 'south_atlantic', 'DE': 'south_atlantic',
    'DC': 'south_atlantic', 'NC': 'south_atlantic', 'SC': 'south_atlantic', 'GA': 'south_atlantic', 'FL': 'south_atlantic',
    # Middle Atlantic
    'NY': 'middle_atlantic', 'PA': 'middle_atlantic', 'NJ': 'middle_atlantic',
    # New England
    'CT': 'new_england', 'RI': 'new_england', 'MA': 'new_england',
    'VT': 'new_england', 'NH': 'new_england', 'ME': 'new_england',
}


# Required team-centric columns (one row per team per game)
REQUIRED_COLUMNS = [
    "game_id", "date",
    "team_id", "opp_id",
    "age", "gender",
    "opp_age", "opp_gender",
    "gf", "ga",
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


def _recency_weights(n: int, k: int, recent_share: float,
                     tail_start: int, tail_end: int,
                     w_start: float, w_end: float) -> List[float]:
    """
    Compute recency weights using exponential decay.

    For games ranked 1..n in recency (1 = most recent), assigns weight exp(-decay_rate * (rank - 1)).
    Normalizes weights so they sum to 1.0.

    Note: k, recent_share, tail_start, tail_end, w_start, w_end are kept in signature
    for backward compatibility but are no longer used. Exponential decay provides
    smoother, more intuitive weighting where each game's weight depends only on its
    recency, not on how many other games exist.
    """
    if n <= 0:
        return []

    # Exponential decay: more recent games get higher weight
    # decay_rate controls how quickly weight drops off (0.05 = gentle decay)
    decay_rate = 0.05

    # Compute raw exponential weights for each position (1 = most recent)
    weights = [np.exp(-decay_rate * i) for i in range(n)]

    # Normalize to sum to 1.0
    total = sum(weights)
    if total > 0:
        weights = [w / total for w in weights]

    return weights


def _percentile_norm(x: pd.Series) -> pd.Series:
    if len(x) == 0:
        return x
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


def _normalize_by_cohort(df: pd.DataFrame, value_col: str, out_col: str, mode: str) -> pd.DataFrame:
    parts = []
    for (age, gender), grp in df.groupby(["age", "gender"], dropna=False):
        s = grp[value_col]
        n = _zscore_norm(s) if mode == "zscore" else _percentile_norm(s)
        sub = grp.copy()
        sub[out_col] = n
        parts.append(sub)
    return pd.concat(parts, axis=0)


def _provisional_multiplier(gp: int, min_games: int) -> float:
    if gp < min_games:
        return 0.85
    if gp < 15:
        return 0.95
    return 1.0


def compute_schedule_connectivity(
    games_df: pd.DataFrame,
    team_state_map: Dict[str, str],
    cfg: V53EConfig
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

    Returns:
        Dict[team_id, {
            'scf': float (0.4 to 1.0),
            'unique_states': int,
            'unique_regions': int,
            'bridge_games': int,
            'home_state': str,
            'is_isolated': bool
        }]
    """
    result = {}

    if not cfg.SCF_ENABLED:
        # If disabled, return SCF=1.0 for all teams (no dampening)
        for team_id in games_df['team_id'].unique():
            result[team_id] = {
                'scf': 1.0,
                'unique_states': 0,
                'unique_regions': 0,
                'bridge_games': 0,
                'home_state': team_state_map.get(str(team_id), 'UNKNOWN'),
                'is_isolated': False
            }
        return result

    # Group games by team to analyze each team's schedule
    for team_id, team_games in games_df.groupby('team_id'):
        team_id_str = str(team_id)
        home_state = team_state_map.get(team_id_str, 'UNKNOWN')
        home_region = STATE_TO_REGION.get(home_state, 'unknown')

        # Get all opponent states
        opp_ids = team_games['opp_id'].unique()
        opp_states = set()
        opp_regions = set()
        bridge_games = 0

        for opp_id in opp_ids:
            opp_state = team_state_map.get(str(opp_id), 'UNKNOWN')
            opp_region = STATE_TO_REGION.get(opp_state, 'unknown')

            if opp_state != 'UNKNOWN':
                opp_states.add(opp_state)

            if opp_region != 'unknown':
                opp_regions.add(opp_region)

            # Count bridge games (games vs teams from different states)
            if opp_state != home_state and opp_state != 'UNKNOWN':
                # Count how many games against this out-of-state opponent
                games_vs_opp = len(team_games[team_games['opp_id'] == opp_id])
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

        # Determine if team is isolated (no bridge games or very few unique states)
        is_isolated = (
            bridge_games < cfg.MIN_BRIDGE_GAMES or
            unique_states < cfg.SCF_MIN_UNIQUE_STATES
        )

        result[team_id_str] = {
            'scf': scf,
            'unique_states': unique_states,
            'unique_regions': unique_regions,
            'bridge_games': bridge_games,
            'home_state': home_state,
            'is_isolated': is_isolated
        }

    return result


def apply_scf_to_sos(
    team_df: pd.DataFrame,
    scf_data: Dict[str, Dict],
    cfg: V53EConfig
) -> pd.DataFrame:
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
    team_df['scf'] = team_df['team_id'].map(
        lambda tid: scf_data.get(str(tid), {}).get('scf', 1.0)
    )
    team_df['bridge_games'] = team_df['team_id'].map(
        lambda tid: scf_data.get(str(tid), {}).get('bridge_games', 0)
    )
    team_df['is_isolated'] = team_df['team_id'].map(
        lambda tid: scf_data.get(str(tid), {}).get('is_isolated', False)
    )
    team_df['unique_opp_states'] = team_df['team_id'].map(
        lambda tid: scf_data.get(str(tid), {}).get('unique_states', 0)
    )

    # Store original SOS before adjustment
    team_df['sos_raw_before_scf'] = team_df['sos'].copy()

    # Apply SCF dampening to raw SOS
    # Formula: sos_adjusted = neutral + SCF * (sos_raw - neutral)
    neutral = cfg.SCF_NEUTRAL_SOS
    team_df['sos'] = neutral + team_df['scf'] * (team_df['sos'] - neutral)

    # Apply isolation penalty cap if enabled
    if cfg.ISOLATION_PENALTY_ENABLED:
        # Teams with insufficient bridge games get SOS capped
        isolation_mask = team_df['bridge_games'] < cfg.MIN_BRIDGE_GAMES
        team_df.loc[isolation_mask, 'sos'] = team_df.loc[isolation_mask, 'sos'].clip(
            upper=cfg.ISOLATION_SOS_CAP
        )

    # Log statistics
    isolated_count = team_df['is_isolated'].sum()
    avg_scf = team_df['scf'].mean()
    low_scf_count = (team_df['scf'] < 0.7).sum()

    logger.info(
        f"🔗 Schedule Connectivity Factor applied: "
        f"avg_scf={avg_scf:.3f}, isolated_teams={isolated_count}, "
        f"low_scf_teams={low_scf_count}"
    )

    # Log some examples of isolated teams (for debugging)
    if isolated_count > 0 and isolated_count <= 10:
        isolated_teams = team_df[team_df['is_isolated']].head(5)
        for _, row in isolated_teams.iterrows():
            logger.info(
                f"  📍 Isolated: team={row['team_id'][:8]}... "
                f"scf={row['scf']:.2f}, bridge_games={row['bridge_games']}, "
                f"unique_states={row['unique_opp_states']}"
            )

    return team_df


def _adjust_for_opponent_strength(
    games: pd.DataFrame,
    strength_map: Dict[str, float],
    cfg: V53EConfig,
    baseline: Optional[float] = None,
    global_strength_map: Optional[Dict[str, float]] = None,
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
        global_strength_map: Optional dict of team_id -> abs_strength from all cohorts.
                            Used for cross-age/cross-gender opponent lookups.

    Returns:
        DataFrame with additional columns [gf_adjusted, ga_adjusted]
    """
    g = games.copy()

    # Use provided baseline or fall back to config
    if baseline is None:
        baseline = cfg.OPPONENT_ADJUST_BASELINE

    # Get opponent strength for each game
    # Try local cohort first, then cross-age global map, then fallback
    def _lookup_opp_strength(opp_id):
        if opp_id in strength_map:
            return strength_map[opp_id]
        if global_strength_map:
            opp_id_str = str(opp_id)
            if opp_id_str in global_strength_map:
                return global_strength_map[opp_id_str]
        return cfg.UNRANKED_SOS_BASE

    g["opp_strength"] = g["opp_id"].map(_lookup_opp_strength)

    # Calculate adjustment multipliers
    # Offense: score against strong opponent = more credit
    # multiplier = opp_strength / baseline
    # Example: opp_strength=0.8, baseline=0.7 → multiplier=1.14 (14% more credit)
    #          opp_strength=0.6, baseline=0.7 → multiplier=0.86 (14% less credit)
    g["off_multiplier"] = (g["opp_strength"] / baseline).clip(
        cfg.OPPONENT_ADJUST_CLIP_MIN,
        cfg.OPPONENT_ADJUST_CLIP_MAX
    )

    # Defense: allow goals to strong opponent = less penalty
    # multiplier = baseline / opp_strength
    # Example: opp_strength=0.8, baseline=0.7 → multiplier=0.875 (12.5% less penalty)
    #          opp_strength=0.6, baseline=0.7 → multiplier=1.17 (17% more penalty)
    g["def_multiplier"] = (baseline / g["opp_strength"]).clip(
        cfg.OPPONENT_ADJUST_CLIP_MIN,
        cfg.OPPONENT_ADJUST_CLIP_MAX
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
) -> Dict[str, pd.DataFrame]:
    """
    Returns:
      {
        "teams": DataFrame[one row per (team_id, age, gender)],
        "games_used": DataFrame[rows used in SOS after repeat-cap]
      }

    Args:
        games_df: Games in v53e format (one row per team per game)
        today: Reference date for rankings
        cfg: V53E configuration
        global_strength_map: Optional dict of team_id -> abs_strength from all cohorts
                            Used for cross-age/cross-gender opponent lookups in SOS
        team_state_map: Optional dict of team_id -> state_code for Schedule Connectivity
                       Factor (SCF) calculation. If not provided, SCF is disabled.
    """
    cfg = cfg or V53EConfig()
    
    # Error handling: check for required columns
    try:
        _require_columns(games_df, REQUIRED_COLUMNS)
    except ValueError:
        # Return empty DataFrames if columns are missing
        return {"teams": pd.DataFrame(), "games_used": pd.DataFrame()}

    g = games_df.copy()
    g["date"] = pd.to_datetime(g["date"], errors="coerce")
    if today is None:
        today = pd.Timestamp(pd.Timestamp.utcnow().date())

    # -------------------------
    # Layer 1: window filter
    # -------------------------
    cutoff = today - pd.Timedelta(days=cfg.WINDOW_DAYS)
    g = g[g["date"] >= cutoff].copy()

    # -------------------------
    # Layer 2: per-team GF/GA outlier guard + GD cap
    # -------------------------
    def clip_team_games(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["gf"] = _clip_outliers_series(out["gf"], cfg.OUTLIER_GUARD_ZSCORE)
        out["ga"] = _clip_outliers_series(out["ga"], cfg.OUTLIER_GUARD_ZSCORE)
        return out

    g = g.groupby("team_id").apply(clip_team_games).reset_index(drop=True)
    g["gd"] = (g["gf"] - g["ga"]).clip(-cfg.GOAL_DIFF_CAP, cfg.GOAL_DIFF_CAP)

    # keep last N games per team (by date)
    g = g.sort_values(["team_id", "date"], ascending=[True, False])
    g["rank_recency"] = g.groupby("team_id")["date"].rank(ascending=False, method="first")
    g = g[g["rank_recency"] <= cfg.MAX_GAMES_FOR_RANK].copy()

    # -------------------------
    # Layer 3: Recency weights
    # -------------------------
    def apply_recency(df: pd.DataFrame) -> pd.DataFrame:
        n = len(df)
        w = _recency_weights(
            n, cfg.RECENT_K, cfg.RECENT_SHARE,
            cfg.DAMPEN_TAIL_START, cfg.DAMPEN_TAIL_END,
            cfg.DAMPEN_TAIL_START_WEIGHT, cfg.DAMPEN_TAIL_END_WEIGHT
        )
        out = df.copy()
        out["w_base"] = w
        return out

    g = g.groupby("team_id").apply(apply_recency).reset_index(drop=True)

    # -------------------------
    # Context multipliers (tournament/KO)
    # -------------------------
    def context_mult(row) -> float:
        mult = 1.0
        it = str(row.get("is_tournament", "")).lower()
        ko = str(row.get("is_knockout", "")).lower()
        if it in ("1", "true", "yes"):
            mult *= cfg.TOURNAMENT_KO_MULT
        if ko in ("1", "true", "yes"):
            mult *= cfg.SEMIS_FINALS_MULT
        return mult

    g["w_context"] = g.apply(context_mult, axis=1)
    g["w_game"] = g["w_base"] * g["w_context"]

    # -------------------------
    # OFF/SAD aggregation (vectorized)
    # -------------------------
    # Vectorized aggregation: compute weighted averages and simple aggregations
    g["gf_weighted"] = g["gf"] * g["w_game"]
    g["ga_weighted"] = g["ga"] * g["w_game"]
    
    # Aggregate using vectorized operations
    team = g.groupby(["team_id", "age", "gender"], as_index=False).agg({
        "gf_weighted": "sum",
        "ga_weighted": "sum",
        "w_game": "sum",  # w_sum for weighted average calculation
        "date": "max",    # last_game
    }).rename(columns={"date": "last_game"})
    
    # Calculate weighted averages (vectorized)
    w_sum = team["w_game"]
    team["off_raw"] = np.where(
        w_sum > 0,
        team["gf_weighted"] / w_sum,
        0.0
    ).astype(float)
    team["sad_raw"] = np.where(
        w_sum > 0,
        team["ga_weighted"] / w_sum,
        0.0
    ).astype(float)
    
    # Add gp (game count) using vectorized count
    gp_counts = g.groupby(["team_id", "age", "gender"], as_index=False).size().rename(columns={"size": "gp"})
    team = team.merge(gp_counts, on=["team_id", "age", "gender"], how="left")

    # Calculate games in last 180 days for activity filter
    inactive_cutoff = today - pd.Timedelta(days=cfg.INACTIVE_HIDE_DAYS)
    g_recent = g[g["date"] >= inactive_cutoff].copy()
    gp_recent_counts = g_recent.groupby(["team_id", "age", "gender"], as_index=False).size().rename(columns={"size": "gp_last_180"})
    team = team.merge(gp_recent_counts, on=["team_id", "age", "gender"], how="left")
    team["gp_last_180"] = team["gp_last_180"].fillna(0).astype(int)

    # Drop intermediate columns
    team = team.drop(columns=["gf_weighted", "ga_weighted", "w_game"])

    # -------------------------
    # Layer 4: ridge defense
    # -------------------------
    team["def_raw"] = 1.0 / (team["sad_raw"] + cfg.RIDGE_GA)

    # -------------------------
    # Layer 7: shrink within cohort
    # -------------------------
    def shrink_grp(df: pd.DataFrame) -> pd.DataFrame:
        mu_off = df["off_raw"].mean()
        mu_sad = df["sad_raw"].mean()
        out = df.copy()
        out["off_shrunk"] = (out["off_raw"] * out["gp"] + mu_off * cfg.SHRINK_TAU) / (out["gp"] + cfg.SHRINK_TAU)
        out["sad_shrunk"] = (out["sad_raw"] * out["gp"] + mu_sad * cfg.SHRINK_TAU) / (out["gp"] + cfg.SHRINK_TAU)
        out["def_shrunk"] = 1.0 / (out["sad_shrunk"] + cfg.RIDGE_GA)
        return out

    team = team.groupby(["age", "gender"]).apply(shrink_grp).reset_index(drop=True)

    # -------------------------
    # Layer 5: team-level outlier guard (OFF/DEF)
    # -------------------------
    def clip_team_level(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for col in ["off_shrunk", "def_shrunk"]:
            s = out[col]
            if len(s) >= 3 and s.std(ddof=0) > 0:
                mu, sd = s.mean(), s.std(ddof=0)
                out[col] = s.clip(mu - cfg.TEAM_OUTLIER_GUARD_ZSCORE * sd,
                                  mu + cfg.TEAM_OUTLIER_GUARD_ZSCORE * sd)
        return out

    team = team.groupby(["age", "gender"]).apply(clip_team_level).reset_index(drop=True)

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
    team["power_presos"] = (
        0.5 * team["off_norm"]
        + 0.5 * team["def_norm"]
    )

    # Static age → anchor mapping for U10–U18
    # This ensures consistent scaling across ages regardless of cohort splitting
    # Younger teams have lower max PowerScore, older teams can reach 1.0
    AGE_TO_ANCHOR = {
        10: 0.400,
        11: 0.475,
        12: 0.550,
        13: 0.625,
        14: 0.700,
        15: 0.775,
        16: 0.850,
        17: 0.925,
        18: 1.000,
        19: 1.000,  # U19 same as U18
    }

    def compute_anchor(age_val):
        """Map age to static anchor value"""
        try:
            age_numeric = int(float(age_val))
            return AGE_TO_ANCHOR.get(age_numeric, 0.70)  # Default to median if out of range
        except (ValueError, TypeError):
            return 0.70  # Default for invalid age

    team["anchor"] = team["age"].apply(compute_anchor)

    logger.info("✅ Static anchor mapping applied (U10=0.40 → U18=1.00)")

    team["abs_strength"] = (team["power_presos"] * team["anchor"]).clip(0.0, 1.0)

    strength_map = dict(zip(team["team_id"], team["abs_strength"]))
    power_map = dict(zip(team["team_id"], team["power_presos"]))

    # -------------------------
    # Opponent-Adjusted Offense/Defense (if enabled)
    # -------------------------
    if cfg.OPPONENT_ADJUST_ENABLED:
        logger.info("🔄 Applying opponent-adjusted offense/defense to fix double-counting...")

        # Calculate the actual mean strength to use as baseline (instead of hardcoded 0.5)
        strength_values = list(strength_map.values())
        actual_mean_strength = np.mean(strength_values) if strength_values else 0.5
        logger.info(f"📊 Strength distribution: mean={actual_mean_strength:.3f}, "
                   f"min={min(strength_values):.3f}, max={max(strength_values):.3f}")

        # Use actual mean as baseline for opponent adjustment
        baseline = actual_mean_strength

        # Adjust games for opponent strength
        # Pass global_strength_map so cross-age opponents get real strength instead of 0.35
        g_adjusted = _adjust_for_opponent_strength(
            g, strength_map, cfg, baseline=baseline,
            global_strength_map=global_strength_map,
        )

        # Re-aggregate with adjusted values
        g_adjusted["gf_weighted_adj"] = g_adjusted["gf_adjusted"] * g_adjusted["w_game"]
        g_adjusted["ga_weighted_adj"] = g_adjusted["ga_adjusted"] * g_adjusted["w_game"]

        team_adj = g_adjusted.groupby(["team_id", "age", "gender"], as_index=False).agg({
            "gf_weighted_adj": "sum",
            "ga_weighted_adj": "sum",
            "w_game": "sum",
        })

        # Calculate adjusted weighted averages
        w_sum = team_adj["w_game"]
        team_adj["off_raw"] = np.where(
            w_sum > 0,
            team_adj["gf_weighted_adj"] / w_sum,
            0.0
        ).astype(float)
        team_adj["sad_raw"] = np.where(
            w_sum > 0,
            team_adj["ga_weighted_adj"] / w_sum,
            0.0
        ).astype(float)

        # Merge back to team DataFrame (replace old off_raw, sad_raw)
        team = team.drop(columns=["off_raw", "sad_raw"])
        team = team.merge(
            team_adj[["team_id", "age", "gender", "off_raw", "sad_raw"]],
            on=["team_id", "age", "gender"],
            how="left"
        )

        # Re-apply defense ridge
        team["def_raw"] = 1.0 / (team["sad_raw"] + cfg.RIDGE_GA)

        # Re-apply Bayesian shrinkage
        def shrink_grp_adj(df: pd.DataFrame) -> pd.DataFrame:
            mu_off = df["off_raw"].mean()
            mu_sad = df["sad_raw"].mean()
            out = df.copy()
            out["off_shrunk"] = (out["off_raw"] * out["gp"] + mu_off * cfg.SHRINK_TAU) / (out["gp"] + cfg.SHRINK_TAU)
            out["sad_shrunk"] = (out["sad_raw"] * out["gp"] + mu_sad * cfg.SHRINK_TAU) / (out["gp"] + cfg.SHRINK_TAU)
            out["def_shrunk"] = 1.0 / (out["sad_shrunk"] + cfg.RIDGE_GA)
            return out

        team = team.groupby(["age", "gender"]).apply(shrink_grp_adj).reset_index(drop=True)

        # Re-apply outlier clipping
        def clip_team_level_adj(df: pd.DataFrame) -> pd.DataFrame:
            out = df.copy()
            for col in ["off_shrunk", "def_shrunk"]:
                s = out[col]
                if len(s) >= 3 and s.std(ddof=0) > 0:
                    mu, sd = s.mean(), s.std(ddof=0)
                    out[col] = s.clip(mu - cfg.TEAM_OUTLIER_GUARD_ZSCORE * sd,
                                      mu + cfg.TEAM_OUTLIER_GUARD_ZSCORE * sd)
            return out

        team = team.groupby(["age", "gender"]).apply(clip_team_level_adj).reset_index(drop=True)

        # Re-normalize
        team = _normalize_by_cohort(team, "off_shrunk", "off_norm", cfg.NORM_MODE)
        team = _normalize_by_cohort(team, "def_shrunk", "def_norm", cfg.NORM_MODE)

        # Recalculate power_presos with adjusted OFF/DEF (50% each, no SOS to avoid circularity)
        team["power_presos"] = (
            0.5 * team["off_norm"]
            + 0.5 * team["def_norm"]
        )

        # Update strength_map and power_map with adjusted power
        team["abs_strength"] = (team["power_presos"] * team["anchor"]).clip(0.0, 1.0)
        strength_map = dict(zip(team["team_id"], team["abs_strength"]))
        power_map = dict(zip(team["team_id"], team["power_presos"]))

        logger.info("✅ Opponent-adjusted offense/defense applied successfully")

    # -------------------------
    # Layer 5: Adaptive K per game (by abs strength gap)
    # -------------------------
    def _lookup_strength(tid):
        """Look up team strength from local cohort, then global cross-age map."""
        if tid in strength_map:
            return strength_map[tid]
        if global_strength_map:
            tid_str = str(tid)
            if tid_str in global_strength_map:
                return global_strength_map[tid_str]
        return 0.5  # neutral fallback for adaptive K

    def adaptive_k(row) -> float:
        gap = abs(_lookup_strength(row["team_id"]) - _lookup_strength(row["opp_id"]))
        return cfg.ADAPTIVE_K_ALPHA * (1.0 + cfg.ADAPTIVE_K_BETA * gap)

    g["k_adapt"] = g.apply(adaptive_k, axis=1)

    # -------------------------
    # Layer 8: SOS (weights + repeat-cap + iterations)
    # -------------------------
    # SOS weight uses recency only (w_game), NOT adaptive K.
    # Adaptive K over-weights games with large strength gaps, which systematically
    # inflates SOS for weak teams (their strong opponents get high gap weight) and
    # deflates SOS for strong teams (their strong opponents get low gap weight).
    # SOS should measure average opponent strength with recency weighting only.
    g["w_sos"] = g["w_game"]

    g = g.sort_values(["team_id", "opp_id", "w_sos"], ascending=[True, True, False])
    g["repeat_rank"] = g.groupby(["team_id", "opp_id"])["w_sos"].rank(ascending=False, method="first")
    g_sos = g[g["repeat_rank"] <= cfg.SOS_REPEAT_CAP].copy()

    # Helper function for weighted averages
    def _avg_weighted(df: pd.DataFrame, col: str, wcol: str) -> float:
        w = df[wcol].values
        s = w.sum()
        if s <= 0:
            return 0.5
        return float(np.average(df[col].values, weights=w))

    # Create lookup maps for base strength calculation (OFF/DEF only, no SOS component)
    # This avoids feedback loops in the iterative algorithm
    team_off_norm_map = dict(zip(team["team_id"], team["off_norm"]))
    team_def_norm_map = dict(zip(team["team_id"], team["def_norm"]))
    team_gp_map = dict(zip(team["team_id"], team["gp"]))
    team_anchor_map = dict(zip(team["team_id"], team["anchor"]))  # Need anchor for scale matching

    # Calculate cohort average strength for shrinkage
    # Using (age, gender) as cohort key
    cohort_avg_strength = {}
    for (age, gender), grp in team.groupby(["age", "gender"]):
        # Base power uses only OFF and DEF (50% each), scaled by anchor
        # This matches the scale of global_strength_map (which uses abs_strength = power_presos * anchor)
        grp_base_power = 0.5 * grp["off_norm"] + 0.5 * grp["def_norm"]
        grp_anchor = grp["anchor"]
        cohort_avg_strength[(age, gender)] = float((grp_base_power * grp_anchor).mean())

    # Map team_id to cohort for quick lookup
    team_cohort_map = dict(zip(
        team["team_id"],
        list(zip(team["age"], team["gender"]))
    ))

    # Calculate BASE strength for each team (OFF/DEF only, normalized to avoid drift)
    # This represents opponent quality independent of their schedule
    # IMPORTANT: Apply anchor to match scale with global_strength_map (which uses abs_strength)
    # NOTE: Opponent-strength shrinkage was REMOVED - it injected games-played bias into SOS.
    # Teams playing opponents with more games got artificially higher SOS.
    base_strength_map = {}
    for tid in team["team_id"]:
        # Base power uses only OFF and DEF (50% each of the non-SOS weight)
        base_power = (
            0.5 * team_off_norm_map.get(tid, 0.5) +
            0.5 * team_def_norm_map.get(tid, 0.5)
        )
        # Apply anchor to match global_strength_map scale
        # Raw strength is already anchored and bounded [0, 1]
        anchor = team_anchor_map.get(tid, 0.7)
        base_strength_map[tid] = float(np.clip(base_power * anchor, 0.0, 1.0))

    # Use base strength for initial SOS calculation (Pass 1)
    # This represents how good opponents are at OFF/DEF
    # For cross-age/cross-gender opponents, use global_strength_map if available

    # Diagnostic: track cross-age lookups and default credit assignments
    cross_age_found = 0
    cross_age_missing = 0
    default_credit_opponents = []  # Track which opponent IDs got default credit

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
        # Unknown opponent - track for diagnostics
        cross_age_missing += 1
        default_credit_opponents.append(opp_id)
        return cfg.UNRANKED_SOS_BASE

    g_sos["opp_strength"] = g_sos["opp_id"].map(get_opponent_strength)

    # Log cross-age lookup stats
    total_opp_lookups = len(g_sos)
    local_found = total_opp_lookups - cross_age_found - cross_age_missing
    logger.info(
        f"🔍 SOS opponent lookups: total={total_opp_lookups}, "
        f"local_cohort={local_found}, cross_age_found={cross_age_found}, "
        f"default_credit={cross_age_missing} "
        f"(global_map_size={len(global_strength_map) if global_strength_map else 0})"
    )
    if cross_age_missing > 0:
        unique_default = len(set(default_credit_opponents))
        logger.warning(
            f"⚠️  {cross_age_missing} opponent lookups ({unique_default} unique teams) "
            f"fell back to UNRANKED_SOS_BASE={cfg.UNRANKED_SOS_BASE}. "
            f"These opponents are not in any cohort's strength map."
        )
        # Log which teams are most affected by default credit opponents
        if unique_default <= 20:
            for opp_id in sorted(set(default_credit_opponents)):
                count = default_credit_opponents.count(opp_id)
                logger.warning(f"  📍 Default credit opponent: {str(opp_id)[:12]}... ({count} games)")

    # Log cohort-level SOS stats for diagnostics
    avg_base_strength = np.mean(list(base_strength_map.values())) if base_strength_map else 0.0
    logger.info(
        f"📊 Base strength map: n={len(base_strength_map)}, "
        f"avg={avg_base_strength:.4f}, "
        f"UNRANKED_SOS_BASE={cfg.UNRANKED_SOS_BASE}"
    )

    direct = (
        g_sos.groupby("team_id", group_keys=False).apply(
            lambda d: _avg_weighted(d, "opp_strength", "w_sos")
        ).rename("sos_direct").reset_index()
    )
    sos_curr = direct.rename(columns={"sos_direct": "sos"}).copy()

    # PageRank-style dampening on initial SOS (Pass 1)
    # This anchors even the first pass toward baseline, preventing inflated bubbles
    if cfg.PAGERANK_DAMPENING_ENABLED:
        sos_curr["sos"] = (
            (1 - cfg.PAGERANK_ALPHA) * cfg.PAGERANK_BASELINE
            + cfg.PAGERANK_ALPHA * sos_curr["sos"]
        )
        logger.info(
            f"📌 PageRank dampening applied: alpha={cfg.PAGERANK_ALPHA}, baseline={cfg.PAGERANK_BASELINE}"
        )

    # Log initial SOS (Pass 1: Direct)
    logger.info(
        f"🔄 SOS Pass 1 (Direct): mean={sos_curr['sos'].mean():.4f}, "
        f"std={sos_curr['sos'].std():.4f}, "
        f"min={sos_curr['sos'].min():.4f}, "
        f"max={sos_curr['sos'].max():.4f}"
    )

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
        trans = (
            g_sos.groupby("team_id", group_keys=False).apply(
                lambda d: _avg_weighted(d, "opp_sos", "w_sos")
            ).rename("sos_trans").reset_index()
        )

        # Blend direct (opponent OFF/DEF - fixed) and transitive (opponent SOS - iterates)
        # Direct stays fixed to prevent upward drift, transitive propagates schedule info
        merged = direct.merge(trans, on="team_id", how="outer").fillna(0.5)
        merged["sos"] = (
            (1 - cfg.SOS_TRANSITIVITY_LAMBDA) * merged["sos_direct"]
            + cfg.SOS_TRANSITIVITY_LAMBDA * merged["sos_trans"]
        )

        # PageRank-style dampening: anchor SOS toward baseline to prevent infinite drift
        # Formula: SOS_final = (1 - alpha) * baseline + alpha * SOS_calculated
        # This ensures isolated clusters can't inflate SOS beyond a certain point
        if cfg.PAGERANK_DAMPENING_ENABLED:
            merged["sos"] = (
                (1 - cfg.PAGERANK_ALPHA) * cfg.PAGERANK_BASELINE
                + cfg.PAGERANK_ALPHA * merged["sos"]
            )

        # SOS stability guard: clip values between 0.0 and 1.0
        merged["sos"] = merged["sos"].clip(0.0, 1.0)
        sos_curr = merged[["team_id", "sos"]]

        # Calculate convergence: mean absolute change from previous iteration
        sos_changes = [abs(sos_curr[sos_curr["team_id"] == tid]["sos"].iloc[0] - prev_sos_map.get(tid, 0.5))
                      for tid in sos_curr["team_id"] if tid in prev_sos_map]
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

    # -------------------------
    # Layer 8b: Schedule Connectivity Factor (SCF) - Regional Bubble Detection
    # -------------------------
    # Apply SCF to dampen SOS for teams in isolated regional bubbles.
    # This prevents circular inflation where teams like Idaho Rush, Idaho Juniors,
    # and Missoula Surf inflate each other's SOS without any national anchor.
    if cfg.SCF_ENABLED and team_state_map is not None:
        logger.info("🔗 Computing Schedule Connectivity Factor (SCF) for regional bubble detection...")

        # Compute SCF for each team based on their schedule diversity
        scf_data = compute_schedule_connectivity(
            games_df=g,  # Use the filtered games DataFrame
            team_state_map=team_state_map,
            cfg=cfg
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
            "⚠️  SCF enabled but team_state_map not provided. "
            "Regional bubble detection disabled for this run."
        )

    # NOTE: Pre-percentile SOS shrinkage was REMOVED (was buggy)
    # The old code shrunk raw SOS toward cohort mean before percentile normalization,
    # which injected games-played bias into sos_norm (teams with more games got
    # artificially higher sos_norm even with weak opponents).
    # Sample-size uncertainty is now handled AFTER percentile normalization (see below).

    # SOS Normalization: Per-cohort percentile ranking
    #
    # IMPORTANT: We normalize SOS within each cohort (age + gender) to ensure
    # SOS has the full [0, 1] range within each ranking group. This guarantees
    # that SOS contributes its intended 50% weight to PowerScore differentiation.
    #
    # Previous approach (global scaling) caused SOS compression where some cohorts
    # had sos_norm ranges like [0.3, 0.5] instead of [0, 1], effectively reducing
    # SOS contribution to ~10% instead of 50%.
    logger.info("🔄 Computing per-cohort SOS normalization (percentile within age+gender)")

    # Percentile rank within each cohort - ensures full [0, 1] range per cohort
    # Teams are ranked against peers in the same age group and gender
    def percentile_within_cohort(x):
        if len(x) <= 1:
            return pd.Series([0.5] * len(x), index=x.index)
        # rank(pct=True) gives values from 1/n to 1.0
        # We want 0.0 to 1.0, so we adjust
        ranks = x.rank(method='average')
        return (ranks - 1) / (len(x) - 1) if len(x) > 1 else pd.Series([0.5], index=x.index)

    team['sos_norm'] = team.groupby(['age', 'gender'])['sos'].transform(percentile_within_cohort)

    # Handle edge cases (NaN from single-team cohorts)
    team['sos_norm'] = team['sos_norm'].fillna(0.5)

    # Ensure values are clipped to [0, 1]
    team['sos_norm'] = team['sos_norm'].clip(0.0, 1.0)

    # Log SOS norms by cohort to verify full range
    logger.info("📊 SOS norms by cohort (should show ~0.0-1.0 range in each):")
    for (age, gender), grp in team.groupby(['age', 'gender']):
        if len(grp) >= 5:
            logger.info(f"    {age} {gender}: min={grp['sos_norm'].min():.3f}, "
                       f"max={grp['sos_norm'].max():.3f}, "
                       f"mean={grp['sos_norm'].mean():.3f}, n={len(grp)}")

    # Low sample handling: smooth shrink toward 0.5 for teams with insufficient games
    # This prevents teams with few games from having extreme SOS values (high or low)
    # while avoiding hard caps that create discontinuities.
    team["sample_flag"] = np.where(
        team["gp"] < cfg.MIN_GAMES_FOR_TOP_SOS,
        "LOW_SAMPLE",
        "OK"
    )

    # Soft shrinkage: blend toward neutral (0.5) based on sample size
    # Using QUADRATIC shrinkage for more aggressive dampening of low-sample teams:
    # - 0 games: shrink_factor = 0.0 (fully shrunk to 0.5)
    # - 5 games: shrink_factor = 0.25 (only 25% of raw SOS retained)
    # - 8 games: shrink_factor = 0.64 (64% of raw SOS retained)
    # - 10+ games: shrink_factor = 1.0 (no shrinkage)
    low_sample_mask = team["gp"] < cfg.MIN_GAMES_FOR_TOP_SOS
    gp_clipped = team["gp"].clip(lower=0)
    shrink_factor = ((gp_clipped / cfg.MIN_GAMES_FOR_TOP_SOS) ** 2).clip(0.0, 1.0)

    # Apply shrinkage: sos_norm = 0.5 + shrink_factor * (sos_norm - 0.5)
    team.loc[low_sample_mask, "sos_norm"] = (
        0.5 + shrink_factor[low_sample_mask] * (team.loc[low_sample_mask, "sos_norm"] - 0.5)
    )

    low_sample_count = low_sample_mask.sum()
    if low_sample_count > 0:
        logger.info(
            f"🏷️  Low sample handling: {low_sample_count} teams with soft SOS shrinkage toward 0.5"
        )

    # Correlation guardrail: detect if games-played is leaking into sos_norm
    # This check ensures the pre-percentile shrinkage bug doesn't silently return.
    # A correlation > 0.10 indicates systematic bias where more games → higher sos_norm.
    gp_sos_corr = team[["gp", "sos_norm"]].corr().iloc[0, 1]
    if abs(gp_sos_corr) > 0.10:
        logger.warning(
            f"⚠️  GP-SOS correlation detected: {gp_sos_corr:.3f} (threshold: ±0.10). "
            f"This may indicate games-played bias in SOS calculation."
        )
    else:
        logger.info(f"✅ GP-SOS correlation check passed: {gp_sos_corr:.3f} (within ±0.10)")

    # -------------------------
    # Layer 6: Performance
    # -------------------------
    g_perf = g.copy()
    g_perf["team_power"] = g_perf["team_id"].map(lambda t: power_map.get(t, 0.5))
    g_perf["opp_power"]  = g_perf["opp_id"].map(lambda t: power_map.get(t, 0.5))
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
        cfg.PERF_GAME_SCALE
        * g_perf["perf_delta"]
        * g_perf["recency_decay"]
        * g_perf["k_adapt"]
        * g_perf["w_game"]
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

    # -------------------------
    # Layer 10: Core PowerScore + Provisional
    # -------------------------
    # Uses PERF_BLEND_WEIGHT to control how much performance adjustment affects final score
    #
    # IMPORTANT: perf_centered ranges [-0.5, +0.5], so the theoretical max of the raw sum
    # is 1.0 + 0.5 * PERF_BLEND_WEIGHT = 1.075. We normalize by this max to ensure
    # powerscore_core stays in [0, 1] range. This prevents ceiling clipping that would
    # cause multiple top teams to have identical power scores.
    #
    # Without normalization: 10-20 top teams per cohort all get clipped to 1.0
    # With normalization: full differentiation preserved among top teams

    MAX_POWERSCORE_THEORETICAL = 1.0 + 0.5 * cfg.PERF_BLEND_WEIGHT  # = 1.075 with default config

    team["powerscore_core"] = (
        cfg.OFF_WEIGHT * team["off_norm"]
        + cfg.DEF_WEIGHT * team["def_norm"]
        + cfg.SOS_WEIGHT * team["sos_norm"]
        + team["perf_centered"] * cfg.PERF_BLEND_WEIGHT
    ) / MAX_POWERSCORE_THEORETICAL

    team["provisional_mult"] = team["gp"].apply(
        lambda gp: _provisional_multiplier(int(gp), cfg.MIN_GAMES_PROVISIONAL)
    )
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
        anchors = team["anchor"].values
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

        for power_iter in range(cfg.SOS_POWER_ITERATIONS):
            # Store previous values for convergence tracking
            prev_sos = team["sos"].values.copy()
            prev_power = team["powerscore_adj"].values.copy()

            # Step 1: Build opponent strength map from abs_strength (OFF/DEF only)
            # Uses the pre-computed abs_strength (= power_presos * anchor, clipped 0-1)
            # instead of powerscore_adj (which includes SOS) to break the circular
            # feedback loop where closed-league teams mutually inflate each other's
            # SOS through iterations. abs_strength already captures quality of wins
            # via the opponent adjustment layer. Static across iterations = single-pass
            # SOS (no transitive propagation), which prevents bubble inflation.
            full_power_strength_map = dict(zip(team_ids, team["abs_strength"].values))

            # Step 2: Vectorized opponent strength lookup
            def lookup_strength(opp_id):
                if opp_id in full_power_strength_map:
                    return full_power_strength_map[opp_id]
                opp_id_str = str(opp_id)
                if global_strength_map and opp_id_str in global_strength_map:
                    return global_strength_map[opp_id_str]
                return cfg.UNRANKED_SOS_BASE

            # Use numpy vectorize for faster lookup (still has overhead but cleaner)
            opp_strengths = np.array([lookup_strength(oid) for oid in opp_ids_array])
            g_sos["opp_full_strength"] = opp_strengths

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

            # Step 5: Re-normalize SOS within cohort
            team['sos_norm'] = team.groupby(['age', 'gender'])['sos'].transform(percentile_within_cohort)
            team['sos_norm'] = team['sos_norm'].fillna(0.5).clip(0.0, 1.0)

            # Step 6: Apply low-sample shrinkage (vectorized) - QUADRATIC for aggressive dampening
            low_sample_mask = gps < cfg.MIN_GAMES_FOR_TOP_SOS
            shrink_factor = np.clip((gps / cfg.MIN_GAMES_FOR_TOP_SOS) ** 2, 0.0, 1.0)
            sos_norm_values = team['sos_norm'].values
            sos_norm_values[low_sample_mask] = (
                0.5 + shrink_factor[low_sample_mask] * (sos_norm_values[low_sample_mask] - 0.5)
            )
            team['sos_norm'] = sos_norm_values

            # Step 7: Recalculate power score with new SOS (vectorized)
            sos_norm_arr = team['sos_norm'].values
            powerscore_core = (
                w_off * off_norms
                + w_def * def_norms
                + w_sos * sos_norm_arr
                + perf_centereds * w_perf
            ) / MAX_POWERSCORE_THEORETICAL

            team["powerscore_core"] = powerscore_core
            team["powerscore_adj"] = powerscore_core * provisional_mults

            # Step 8: Calculate convergence metrics
            sos_change = np.abs(team["sos"].values - prev_sos).mean()
            power_change = np.abs(team["powerscore_adj"].values - prev_power).mean()

            logger.info(
                f"  📊 Power-SOS iteration {power_iter + 1}/{cfg.SOS_POWER_ITERATIONS}: "
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
    team["days_since_last"] = (
        pd.Timestamp(today) - pd.to_datetime(team["last_game"], errors='coerce')
    ).dt.days
    
    # Filter teams based on games in last 180 days
    # Status priority:
    # 1. "Inactive" - No games in last 180 days (gp_last_180 == 0) OR last_game is NULL OR days_since_last >= 180
    #    Note: Use >= to match the gp_last_180 calculation which uses >= cutoff (includes games exactly 180 days ago)
    # 2. "Not Enough Ranked Games" - Has games in last 180 days but < MIN_GAMES_PROVISIONAL (5 games)
    # 3. "Active" - Has >= MIN_GAMES_PROVISIONAL games in last 180 days
    team["status"] = np.where(
        (team["gp_last_180"] == 0) | 
        (team["last_game"].isna()) | 
        (team["days_since_last"].fillna(999) >= cfg.INACTIVE_HIDE_DAYS),
        "Inactive",
        np.where(
            team["gp_last_180"] < cfg.MIN_GAMES_PROVISIONAL,
            "Not Enough Ranked Games",
            "Active"
        )
    )

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
            ["gender", "age", "powerscore_adj", "sos"],
            ascending=[True, True, False, False]
        ).reset_index(drop=True)

        # Calculate unique ranks based on sort order (no ties)
        # Teams with same PowerScore but different SOS get different ranks
        active_teams["rank_in_cohort"] = active_teams.groupby(["age", "gender"]).cumcount() + 1

        # Merge ranks back into full team DataFrame using team_id as key
        rank_map = dict(zip(active_teams["team_id"], active_teams["rank_in_cohort"]))
        team.loc[active_mask, "rank_in_cohort"] = team.loc[active_mask, "team_id"].map(rank_map)

    # Sort full team DataFrame for consistent output order (with SOS tiebreaker)
    team = team.sort_values(["gender", "age", "powerscore_adj", "sos"], ascending=[True, True, False, False]).reset_index(drop=True)

    # outputs
    games_used_cols = [
        "game_id", "date", "team_id", "opp_id",
        "age", "gender", "opp_age", "opp_gender",
        "gf", "ga", "gd",
        "w_base", "w_context", "k_adapt", "w_game", "w_sos", "rank_recency"
    ]
    # For transparency, return all used games (pre repeat-cap) or the capped set.
    # Here we return the capped set that actually fed SOS.
    games_used = (
        g[g["repeat_rank"] <= cfg.SOS_REPEAT_CAP][games_used_cols].copy()
        if "repeat_rank" in g.columns else g[games_used_cols].copy()
    )

    keep_cols = [
        "team_id", "age", "gender", "gp", "gp_last_180", "last_game", "status", "rank_in_cohort",
        "off_raw", "sad_raw", "off_shrunk", "sad_shrunk", "def_shrunk",
        "off_norm", "def_norm",
        "sos", "sos_norm", "sample_flag",
        "power_presos", "anchor", "abs_strength",
        "perf_raw", "perf_centered",
        "powerscore_core", "provisional_mult", "powerscore_adj"
    ]
    # Add SCF columns if they exist (from regional bubble detection)
    scf_cols = ["scf", "bridge_games", "is_isolated", "unique_opp_states"]
    for col in scf_cols:
        if col in team.columns:
            keep_cols.append(col)
    teams = team[keep_cols].copy()

    # === Restore legacy frontend fields ===
    # Map powerscore_adj to power_score_final
    teams["power_score_final"] = teams["powerscore_adj"]

    # Map rank_in_cohort to rank_in_cohort_final (convert to float, handle None)
    # Use pd.to_numeric to handle None values properly (converts None to NaN, which becomes NULL in DB)
    teams["rank_in_cohort_final"] = pd.to_numeric(teams["rank_in_cohort"], errors='coerce')

    # State rank must be computed — fallback to cohort rank for now
    # (State information is not available in v53e output, will be computed later in pipeline)
    teams["rank_in_state_final"] = teams["rank_in_cohort_final"]

    # SOS rankings: compute ranks within each (age, gender) cohort
    # Only teams with >= MIN_GAMES_FOR_SOS_RANK games get SOS rankings
    # Teams below threshold get NULL sos_rank (prevents 3-game teams from being #1 SOS)
    min_games_for_sos_rank = cfg.MIN_GAMES_FOR_SOS_RANK

    # Create mask for teams eligible for SOS ranking
    sos_rank_eligible = teams["gp"] >= min_games_for_sos_rank

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
        f"📊 SOS Ranking: {total_count - excluded_count:,} teams eligible (>= {min_games_for_sos_rank} games), "
        f"{excluded_count:,} teams excluded (< {min_games_for_sos_rank} games)"
    )

    # State rank: fallback to national rank if state unavailable
    # (State information is not available in v53e output, will be computed later in pipeline)
    teams["sos_rank_state"] = teams["sos_rank_national"].copy()

    # Map offense/defense norm fields
    teams["offense_norm"] = teams["off_norm"]
    teams["defense_norm"] = teams["def_norm"]

    # For data freshness
    teams["last_calculated"] = pd.Timestamp.utcnow()

    # Games played summary for the frontend
    teams["games_played"] = teams["gp"]
    teams["wins"] = None
    teams["losses"] = None
    teams["draws"] = None
    teams["total_games_played"] = teams["gp"]
    teams["total_wins"] = None
    teams["total_losses"] = None
    teams["total_draws"] = None
    teams["win_percentage"] = None

    return {"teams": teams, "games_used": games_used}
