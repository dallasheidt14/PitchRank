
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
    SOS_REPEAT_CAP: int = 4
    SOS_ITERATIONS: int = 3
    SOS_TRANSITIVITY_LAMBDA: float = 0.20  # Balanced transitivity weight (80% direct, 20% transitive)

    # SOS sample size weighting
    SOS_SAMPLE_SIZE_THRESHOLD: int = 25  # Teams with fewer games shrink toward cohort mean
    OPPONENT_SAMPLE_SIZE_THRESHOLD: int = 20  # Opponents with fewer games shrink toward cohort mean
    MIN_GAMES_FOR_TOP_SOS: int = 10  # Teams with fewer games get capped sos_norm
    SOS_TOP_CAP_FOR_LOW_SAMPLE: float = 0.70  # Max sos_norm for low-sample teams

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


def _adjust_for_opponent_strength(
    games: pd.DataFrame,
    strength_map: Dict[str, float],
    cfg: V53EConfig,
    baseline: Optional[float] = None
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

    # Get opponent strength for each game
    g["opp_strength"] = g["opp_id"].map(
        lambda o: strength_map.get(o, cfg.UNRANKED_SOS_BASE)
    )

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

    team["abs_strength"] = (team["power_presos"] / team["anchor"]).clip(0.0, 1.5)

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
        g_adjusted = _adjust_for_opponent_strength(g, strength_map, cfg, baseline=baseline)

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
        team["abs_strength"] = (team["power_presos"] / team["anchor"]).clip(0.0, 1.5)
        strength_map = dict(zip(team["team_id"], team["abs_strength"]))
        power_map = dict(zip(team["team_id"], team["power_presos"]))

        logger.info("✅ Opponent-adjusted offense/defense applied successfully")

    # -------------------------
    # Layer 5: Adaptive K per game (by abs strength gap)
    # -------------------------
    def adaptive_k(row) -> float:
        gap = abs(strength_map.get(row["team_id"], 0.5) - strength_map.get(row["opp_id"], 0.5))
        return cfg.ADAPTIVE_K_ALPHA * (1.0 + cfg.ADAPTIVE_K_BETA * gap)

    g["k_adapt"] = g.apply(adaptive_k, axis=1)

    # -------------------------
    # Layer 8: SOS (weights + repeat-cap + iterations)
    # -------------------------
    g["w_sos"] = g["w_game"] * g["k_adapt"]

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

    # Calculate cohort average strength for shrinkage
    # Using (age, gender) as cohort key
    cohort_avg_strength = {}
    for (age, gender), grp in team.groupby(["age", "gender"]):
        # Base power uses only OFF and DEF (50% each)
        grp_base_power = 0.5 * grp["off_norm"] + 0.5 * grp["def_norm"]
        cohort_avg_strength[(age, gender)] = float(grp_base_power.mean())

    # Map team_id to cohort for quick lookup
    team_cohort_map = dict(zip(
        team["team_id"],
        list(zip(team["age"], team["gender"]))
    ))

    # Calculate BASE strength for each team (OFF/DEF only, normalized to avoid drift)
    # This represents opponent quality independent of their schedule
    # Apply sample size weighting: shrink toward cohort mean for low-game opponents
    base_strength_map = {}
    for tid in team["team_id"]:
        # Base power uses only OFF and DEF (50% each of the non-SOS weight)
        base_power = (
            0.5 * team_off_norm_map.get(tid, 0.5) +
            0.5 * team_def_norm_map.get(tid, 0.5)
        )
        raw_strength = float(np.clip(base_power, 0.0, 1.0))

        # Apply sample size weighting for opponent strength
        opp_gp = team_gp_map.get(tid, 0)
        opp_weight = min(1.0, opp_gp / cfg.OPPONENT_SAMPLE_SIZE_THRESHOLD)

        cohort_key = team_cohort_map.get(tid)
        cohort_avg = cohort_avg_strength.get(cohort_key, 0.5) if cohort_key else 0.5

        # Blend: raw_strength * weight + cohort_avg * (1 - weight)
        base_strength_map[tid] = raw_strength * opp_weight + cohort_avg * (1 - opp_weight)

    # Use base strength for initial SOS calculation (Pass 1)
    # This represents how good opponents are at OFF/DEF
    # For cross-age/cross-gender opponents, use global_strength_map if available
    def get_opponent_strength(opp_id):
        # Try local cohort first (same age/gender)
        if opp_id in base_strength_map:
            return base_strength_map[opp_id]
        # Fall back to global map (cross-age/cross-gender)
        if global_strength_map and opp_id in global_strength_map:
            return global_strength_map[opp_id]
        # Unknown opponent
        return cfg.UNRANKED_SOS_BASE

    g_sos["opp_strength"] = g_sos["opp_id"].map(get_opponent_strength)

    direct = (
        g_sos.groupby("team_id", group_keys=False).apply(
            lambda d: _avg_weighted(d, "opp_strength", "w_sos")
        ).rename("sos_direct").reset_index()
    )
    sos_curr = direct.rename(columns={"sos_direct": "sos"}).copy()

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
            if global_strength_map and opp_id in global_strength_map:
                return global_strength_map[opp_id]
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

    # Sample size weighting: shrink SOS toward cohort mean for low-sample teams
    # This prevents teams with few games from having inflated/deflated SOS
    cohort_avg_sos = team.groupby(["age", "gender"])["sos"].transform("mean")
    sos_weight = (team["gp"] / cfg.SOS_SAMPLE_SIZE_THRESHOLD).clip(0, 1)
    team["sos"] = team["sos"] * sos_weight + cohort_avg_sos * (1 - sos_weight)

    logger.info(
        f"📊 SOS after sample-size shrinkage: mean={team['sos'].mean():.4f}, "
        f"std={team['sos'].std():.4f}, "
        f"range=[{team['sos'].min():.4f}, {team['sos'].max():.4f}]"
    )

    # Normalize SOS within cohort
    team = _normalize_by_cohort(team, "sos", "sos_norm", cfg.NORM_MODE)

    # Low sample handling: smooth shrink toward 0.5 for teams with insufficient games
    # This prevents teams with few games from having extreme SOS values (high or low)
    # while avoiding hard caps that create discontinuities.
    team["sample_flag"] = np.where(
        team["gp"] < cfg.MIN_GAMES_FOR_TOP_SOS,
        "LOW_SAMPLE",
        "OK"
    )

    # Soft shrinkage: blend toward neutral (0.5) based on sample size
    # shrink_factor = 0.0 for 0 games (fully shrunk to 0.5)
    # shrink_factor = 1.0 for MIN_GAMES_FOR_TOP_SOS+ games (no shrinkage)
    low_sample_mask = team["gp"] < cfg.MIN_GAMES_FOR_TOP_SOS
    gp_clipped = team["gp"].clip(lower=0)
    shrink_factor = (gp_clipped / cfg.MIN_GAMES_FOR_TOP_SOS).clip(0.0, 1.0)

    # Apply shrinkage: sos_norm = 0.5 + shrink_factor * (sos_norm - 0.5)
    team.loc[low_sample_mask, "sos_norm"] = (
        0.5 + shrink_factor[low_sample_mask] * (team.loc[low_sample_mask, "sos_norm"] - 0.5)
    )

    low_sample_count = low_sample_mask.sum()
    if low_sample_count > 0:
        logger.info(
            f"🏷️  Low sample handling: {low_sample_count} teams with soft SOS shrinkage toward 0.5"
        )

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
    team["powerscore_core"] = (
        cfg.OFF_WEIGHT * team["off_norm"]
        + cfg.DEF_WEIGHT * team["def_norm"]
        + cfg.SOS_WEIGHT * team["sos_norm"]
        + team["perf_centered"] * cfg.PERF_BLEND_WEIGHT
    )

    team["provisional_mult"] = team["gp"].apply(
        lambda gp: _provisional_multiplier(int(gp), cfg.MIN_GAMES_PROVISIONAL)
    )
    team["powerscore_adj"] = team["powerscore_core"] * team["provisional_mult"]

    # NOTE: Anchor-based scaling is now applied globally in compute_all_cohorts()
    # after all cohorts are combined. This ensures proper cross-age scaling.

    # -------------------------
    # Layer 11: Rank & status
    # -------------------------
    team["days_since_last"] = (pd.Timestamp(today) - pd.to_datetime(team["last_game"])).dt.days
    # Filter teams based on games in last 180 days (must have at least 5 games in last 180 days)
    team["status"] = np.where(
        team["gp_last_180"] < cfg.MIN_GAMES_PROVISIONAL, "Not Enough Ranked Games", "Active"
    )

    # Initialize rank_in_cohort as NULL for all teams
    team["rank_in_cohort"] = None

    # Only rank teams with "Active" status to avoid gaps in ranking numbers
    # Filter active teams, sort, rank, then merge back using team_id as key
    active_mask = team["status"] == "Active"
    active_teams = team[active_mask].copy()
    
    if not active_teams.empty:
        # Sort active teams for ranking
        active_teams = active_teams.sort_values(["gender", "age", "powerscore_adj"], ascending=[True, True, False]).reset_index(drop=True)
        # Calculate ranks for active teams only
        active_teams["rank_in_cohort"] = active_teams.groupby(["age", "gender"])["powerscore_adj"].rank(
            ascending=False, method="min"
        ).astype(int)
        
        # Merge ranks back into full team DataFrame using team_id as key
        rank_map = dict(zip(active_teams["team_id"], active_teams["rank_in_cohort"]))
        team.loc[active_mask, "rank_in_cohort"] = team.loc[active_mask, "team_id"].map(rank_map)
    
    # Sort full team DataFrame for consistent output order
    team = team.sort_values(["gender", "age", "powerscore_adj"], ascending=[True, True, False]).reset_index(drop=True)

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
    teams = team[keep_cols].copy()

    return {"teams": teams, "games_used": games_used}
