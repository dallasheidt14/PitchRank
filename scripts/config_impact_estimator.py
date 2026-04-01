#!/usr/bin/env python3
"""
Config Impact Estimator — estimate ranking changes from config tweaks WITHOUT full rerun.

Uses current rankings_full data and delta-based estimation to predict how config
changes (weights, thresholds, trimming, SCF, ML, shrinkage) would affect
power_score_true, sos_norm, and rank positions.

Usage:
    python scripts/config_impact_estimator.py scenarios --cohort u14 --gender Male
    python scripts/config_impact_estimator.py whatif <team_uuid> --target 5

Limitations:
    - SOS trim/SCF adjustments are heuristic (actual recomputation requires full pipeline)
    - ML threshold crossings estimated from current ml_norm delta
    - Rank changes are directionally correct but not exact
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.rankings.constants import AGE_TO_ANCHOR, SOS_ML_THRESHOLD_HIGH, SOS_ML_THRESHOLD_LOW

load_dotenv(Path(__file__).parent.parent / ".env.local")
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# ─── Full production config (mirrors V53EConfig + Layer13Config) ──────────────

PROD_CONFIG = {
    # Layer 2: Game processing
    "GOAL_DIFF_CAP": 6,
    "MAX_GAMES_FOR_RANK": 30,
    # Layer 3: Recency
    "RECENCY_DECAY_RATE": 0.08,
    # Layer 5: Adaptive K
    "ADAPTIVE_K_ALPHA": 0.5,
    "ADAPTIVE_K_BETA": 0.6,
    # Layer 6: Performance
    "PERF_BLEND_WEIGHT": 0.00,
    "PERF_CAP": 0.15,
    "PERF_GAME_SCALE": 0.15,
    "PERFORMANCE_DECAY_RATE": 0.08,
    "PERFORMANCE_THRESHOLD": 0.5,
    "PERFORMANCE_GOAL_SCALE": 5.0,
    # Layer 4: Defense ridge
    "RIDGE_GA": 0.25,
    # Layer 7: Bayesian shrinkage
    "SHRINK_TAU": 8.0,
    # Layer 8: SOS core
    "UNRANKED_SOS_BASE": 0.35,
    "SOS_REPEAT_CAP": 4,
    # SOS trimming
    "TRIM_PERCENT": 0.25,
    "TRIM_MIN_GAMES": 8,
    "TRIM_MAX_GAMES": 6,
    "TRIM_MODE": "soft",
    "TRIM_SOFT_WEIGHT": 0.15,
    # Power-SOS iteration
    "SOS_POWER_ITERATIONS": 3,
    "SOS_POWER_DAMPING": 0.5,
    "SOS_POWER_MAX_BOOST": 0.03,
    # SOS low-sample shrinkage
    "MIN_GAMES_FOR_TOP_SOS": 10,
    "SOS_SHRINKAGE_ANCHOR": 0.35,
    # GP-SOS decorrelation
    "GP_SOS_DECORRELATION_ENABLED": True,
    "GP_SOS_DECORRELATION_THRESHOLD": 0.15,
    # SOS normalization
    "SOS_NORM_HYBRID_ENABLED": True,
    "SOS_NORM_HYBRID_ZSCORE_BLEND": 0.30,
    # Layer 8b: SCF (Schedule Connectivity Factor)
    "SCF_ENABLED": True,
    "SCF_DIVERSITY_DIVISOR": 4.0,
    "SCF_FLOOR": 0.4,
    "SCF_NEUTRAL_SOS": 0.5,
    "SCF_QUALITY_OVERRIDE_ENABLED": True,
    "SCF_QUALITY_PERCENTILE": 0.65,
    "SCF_QUALITY_BOOST_MIN": 0.85,
    "SCF_QUALITY_MIN_WIN_RATE": 0.55,
    "MIN_BRIDGE_GAMES": 3,
    "ISOLATION_SOS_CAP": 0.60,
    # Layer 8c: PageRank dampening
    "PAGERANK_DAMPENING_ENABLED": True,
    "PAGERANK_ALPHA": 0.85,
    "PAGERANK_BASELINE": 0.5,
    # Layer 8d: Component normalization
    "COMPONENT_SOS_ENABLED": True,
    "MIN_COMPONENT_SIZE_FOR_FULL_SOS": 10,
    # Layer 10: Score weights
    "OFF_WEIGHT": 0.20,
    "DEF_WEIGHT": 0.20,
    "SOS_WEIGHT": 0.60,
    # Provisional
    "MIN_GAMES_PROVISIONAL": 6,
    # ML Layer 13
    "ML_ALPHA": 0.08,
    "ML_THRESHOLD_LOW": SOS_ML_THRESHOLD_LOW,  # 0.45
    "ML_THRESHOLD_HIGH": SOS_ML_THRESHOLD_HIGH,  # 0.60
    "ML_RECENCY_DECAY": 0.06,
    "ML_MIN_GAMES": 6,
    "ML_RESIDUAL_CLIP": 3.5,
    # Opponent adjustment
    "OPPONENT_ADJUST_ENABLED": True,
    "OPPONENT_ADJUST_BASELINE": 0.5,
    "OPPONENT_ADJUST_CLIP_MIN": 0.25,
    "OPPONENT_ADJUST_CLIP_MAX": 2.0,
}


# ─── Config scenarios ─────────────────────────────────────────────────────────


def default_scenarios() -> List[Dict]:
    """Built-in scenarios for common config explorations."""
    return [
        {"name": "Baseline (current production)", **PROD_CONFIG},
        # Weight rebalancing
        {
            "name": "SOS=0.50, OFF/DEF=0.25",
            **{**PROD_CONFIG, "SOS_WEIGHT": 0.50, "OFF_WEIGHT": 0.25, "DEF_WEIGHT": 0.25},
        },
        {
            "name": "SOS=0.55, OFF/DEF=0.225",
            **{**PROD_CONFIG, "SOS_WEIGHT": 0.55, "OFF_WEIGHT": 0.225, "DEF_WEIGHT": 0.225},
        },
        {
            "name": "SOS=0.65, OFF/DEF=0.175",
            **{**PROD_CONFIG, "SOS_WEIGHT": 0.65, "OFF_WEIGHT": 0.175, "DEF_WEIGHT": 0.175},
        },
        # Performance layer
        {"name": "Perf=5%", **{**PROD_CONFIG, "PERF_BLEND_WEIGHT": 0.05}},
        {"name": "Perf=10%", **{**PROD_CONFIG, "PERF_BLEND_WEIGHT": 0.10}},
        # ML tuning
        {"name": "ML alpha=0.04", **{**PROD_CONFIG, "ML_ALPHA": 0.04}},
        {"name": "ML alpha=0.12", **{**PROD_CONFIG, "ML_ALPHA": 0.12}},
        {"name": "ML alpha=0.15", **{**PROD_CONFIG, "ML_ALPHA": 0.15}},
        {"name": "ML band 0.40-0.55", **{**PROD_CONFIG, "ML_THRESHOLD_LOW": 0.40, "ML_THRESHOLD_HIGH": 0.55}},
        {"name": "ML band 0.50-0.65", **{**PROD_CONFIG, "ML_THRESHOLD_LOW": 0.50, "ML_THRESHOLD_HIGH": 0.65}},
        # SOS trimming
        {"name": "Trim 35% hard", **{**PROD_CONFIG, "TRIM_PERCENT": 0.35, "TRIM_SOFT_WEIGHT": 0.0}},
        {"name": "Trim 15% soft", **{**PROD_CONFIG, "TRIM_PERCENT": 0.15}},
        {"name": "No trim", **{**PROD_CONFIG, "TRIM_PERCENT": 0.0}},
        # SCF tuning
        {"name": "SCF WR gate=0.60", **{**PROD_CONFIG, "SCF_QUALITY_MIN_WIN_RATE": 0.60}},
        {"name": "SCF diversity=5", **{**PROD_CONFIG, "SCF_DIVERSITY_DIVISOR": 5.0}},
        {"name": "Isolation cap=0.50", **{**PROD_CONFIG, "ISOLATION_SOS_CAP": 0.50}},
        {"name": "Bridge games=5", **{**PROD_CONFIG, "MIN_BRIDGE_GAMES": 5}},
        # PageRank dampening
        {"name": "PageRank alpha=0.75", **{**PROD_CONFIG, "PAGERANK_ALPHA": 0.75}},
        {"name": "PageRank alpha=0.90", **{**PROD_CONFIG, "PAGERANK_ALPHA": 0.90}},
        # SOS shrinkage
        {"name": "SOS shrink anchor=0.40", **{**PROD_CONFIG, "SOS_SHRINKAGE_ANCHOR": 0.40}},
        {"name": "SOS shrink anchor=0.30", **{**PROD_CONFIG, "SOS_SHRINKAGE_ANCHOR": 0.30}},
        {"name": "Min games for SOS=8", **{**PROD_CONFIG, "MIN_GAMES_FOR_TOP_SOS": 8}},
        # Bayesian shrinkage
        {"name": "Shrink tau=6 (tighter)", **{**PROD_CONFIG, "SHRINK_TAU": 6.0}},
        {"name": "Shrink tau=12 (looser)", **{**PROD_CONFIG, "SHRINK_TAU": 12.0}},
        # Normalization
        {"name": "Z-score blend=0.20", **{**PROD_CONFIG, "SOS_NORM_HYBRID_ZSCORE_BLEND": 0.20}},
        {"name": "Z-score blend=0.40", **{**PROD_CONFIG, "SOS_NORM_HYBRID_ZSCORE_BLEND": 0.40}},
        {
            "name": "Pure percentile",
            **{**PROD_CONFIG, "SOS_NORM_HYBRID_ZSCORE_BLEND": 0.0, "SOS_NORM_HYBRID_ENABLED": False},
        },
    ]


# ─── Data loading ─────────────────────────────────────────────────────────────

FETCH_COLS = (
    "team_id, age_group, gender, state_code, status, "
    "games_played, wins, losses, draws, win_percentage, "
    "off_raw, sad_raw, off_shrunk, sad_shrunk, def_shrunk, off_norm, def_norm, "
    "sos, sos_norm, sos_raw, sos_norm_national, "
    "perf_centered, perf_raw, "
    "ml_overperf, ml_norm, "
    "powerscore_adj, powerscore_ml, powerscore_core, "
    "provisional_mult, anchor, sample_flag, "
    "power_score_true, power_score_final, "
    "rank_in_cohort, rank_in_cohort_ml, national_rank"
)


def _get_supabase():
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    return create_client(url, key)


def load_rankings(cohort_filter: Optional[str] = None, gender_filter: Optional[str] = None) -> pd.DataFrame:
    """Load current rankings from Supabase."""
    sb = _get_supabase()

    query = sb.table("rankings_full").select(FETCH_COLS).eq("status", "Active")
    if cohort_filter:
        query = query.eq("age_group", cohort_filter)
    if gender_filter:
        query = query.eq("gender", gender_filter)
    query = query.order("power_score_final", desc=True).limit(5000)

    result = query.execute()
    df = pd.DataFrame(result.data)
    logger.info(f"Loaded {len(df)} active teams from rankings_full")
    return df


def load_game_data(team_ids: List[str]) -> pd.DataFrame:
    """Load game-level data for SOS recomputation.

    Fetches games where any team in team_ids is home or away, with opponent
    base_strength derived from rankings_full off_norm/def_norm.
    Returns per-game rows with: team_id, opp_id, opp_base_strength, opp_state_code.
    """
    sb = _get_supabase()
    logger.info(f"Loading game data for {len(team_ids)} teams...")

    # Fetch games in batches (team can be home or away)
    all_games = []
    batch_size = 50
    for i in range(0, len(team_ids), batch_size):
        batch = team_ids[i : i + batch_size]
        for side, tid_col, opp_col in [
            ("home", "home_team_master_id", "away_team_master_id"),
            ("away", "away_team_master_id", "home_team_master_id"),
        ]:
            result = (
                sb.table("games")
                .select(f"game_date, {tid_col}, {opp_col}")
                .in_(tid_col, batch)
                .order("game_date", desc=True)
                .limit(5000)
                .execute()
            )
            for g in result.data or []:
                all_games.append(
                    {
                        "team_id": g[tid_col],
                        "opp_id": g[opp_col],
                        "date": g["game_date"],
                    }
                )

    if not all_games:
        return pd.DataFrame()

    games_df = pd.DataFrame(all_games).drop_duplicates(subset=["team_id", "opp_id", "date"])

    # Get opponent base_strength (0.5*off_norm + 0.5*def_norm) and state_code
    opp_ids = list(games_df["opp_id"].dropna().unique())
    opp_data = {}
    for i in range(0, len(opp_ids), 100):
        batch = opp_ids[i : i + 100]
        result = sb.table("rankings_full").select("team_id, off_norm, def_norm, status").in_("team_id", batch).execute()
        for r in result.data or []:
            off = r.get("off_norm") or 0.5
            defn = r.get("def_norm") or 0.5
            opp_data[r["team_id"]] = 0.5 * off + 0.5 * defn

    opp_states = {}
    for i in range(0, len(opp_ids), 100):
        batch = opp_ids[i : i + 100]
        result = sb.table("teams").select("team_id_master, state_code").in_("team_id_master", batch).execute()
        for r in result.data or []:
            opp_states[r["team_id_master"]] = r.get("state_code") or "UNKNOWN"

    games_df["opp_base_strength"] = games_df["opp_id"].map(opp_data).fillna(0.35)
    games_df["opp_state_code"] = games_df["opp_id"].map(opp_states).fillna("UNKNOWN")

    logger.info(f"Loaded {len(games_df)} game rows, {len(opp_data)} opponents with strength data")
    return games_df


# ─── Layer 1: Score approximation ────────────────────────────────────────────


def recompute_off_def_norms(df: pd.DataFrame, cfg: Dict) -> tuple:
    """Recompute off_norm and def_norm when Bayesian shrinkage (tau) or ridge changes.

    Uses off_raw, sad_raw, and gp from rankings_full to apply the shrinkage formula:
        off_shrunk = (off_raw * gp + mu_off * tau) / (gp + tau)
        sad_shrunk = (sad_raw * gp + mu_sad * tau) / (gp + tau)
        def_shrunk = 1 / (sad_shrunk + ridge_ga)
    Then percentile-normalizes within each cohort.

    Returns (off_norm, def_norm) as Series.
    """
    tau = cfg.get("SHRINK_TAU", 8.0)
    ridge_ga = cfg.get("RIDGE_GA", 0.25)
    prod_tau = PROD_CONFIG.get("SHRINK_TAU", 8.0)

    off_raw = df["off_raw"].fillna(0).astype(float)
    sad_raw = df["sad_raw"].fillna(0).astype(float)
    gp = df["games_played"].fillna(0).astype(float)

    # If tau hasn't changed, return current norms
    if tau == prod_tau:
        return df["off_norm"].fillna(0.5), df["def_norm"].fillna(0.5)

    # Recompute shrinkage per cohort (mu is cohort mean of raw values)
    off_shrunk = pd.Series(0.5, index=df.index)
    def_shrunk = pd.Series(0.5, index=df.index)

    for (age, gender), grp in df.groupby(["age_group", "gender"]):
        idx = grp.index
        mu_off = off_raw.loc[idx].mean()
        mu_sad = sad_raw.loc[idx].mean()
        g = gp.loc[idx]

        o_shrunk = (off_raw.loc[idx] * g + mu_off * tau) / (g + tau)
        s_shrunk = (sad_raw.loc[idx] * g + mu_sad * tau) / (g + tau)
        d_shrunk = 1.0 / (s_shrunk + ridge_ga)

        off_shrunk.loc[idx] = o_shrunk
        def_shrunk.loc[idx] = d_shrunk

    # Percentile-normalize within cohort
    off_norm = off_shrunk.copy()
    def_norm = def_shrunk.copy()
    for (age, gender), grp in df.groupby(["age_group", "gender"]):
        idx = grp.index
        if len(idx) > 1:
            off_norm.loc[idx] = off_shrunk.loc[idx].rank(method="average") / len(idx)
            def_norm.loc[idx] = def_shrunk.loc[idx].rank(method="average") / len(idx)
        else:
            off_norm.loc[idx] = 0.5
            def_norm.loc[idx] = 0.5

    return off_norm.clip(0.0, 1.0), def_norm.clip(0.0, 1.0)


def estimate_power_score(df: pd.DataFrame, cfg: Dict, games_df: Optional[pd.DataFrame] = None) -> pd.Series:
    """Estimate power_score_true from config and current data.

    Exact for: weights, ML, provisional, tau shrinkage.
    Near-exact (with games_df): SOS trim, SCF.
    Heuristic (without games_df): SOS trim, SCF.
    """
    w_off = cfg["OFF_WEIGHT"]
    w_def = cfg["DEF_WEIGHT"]
    w_sos = cfg["SOS_WEIGHT"]
    w_perf = cfg.get("PERF_BLEND_WEIGHT", 0.0)
    perf_cap = cfg.get("PERF_CAP", 0.15)

    perf = df["perf_centered"].fillna(0).clip(-perf_cap, perf_cap)

    # Recompute OFF/DEF norms if tau changed (exact)
    off_norm, def_norm = recompute_off_def_norms(df, cfg)

    # Adjust SOS (exact with games_df, heuristic without)
    sos_adj = estimate_sos_adjustment(df, cfg, games_df=games_df)

    max_theoretical = 1.0 + perf_cap * w_perf
    core = (w_off * off_norm + w_def * def_norm + w_sos * sos_adj + w_perf * perf) / max_theoretical
    core = core.clip(0.0, 1.0)

    # Provisional multiplier
    gp = df["games_played"].fillna(0)
    prov = (0.85 + (gp / 15.0) * 0.15).clip(0.85, 1.0)
    prov = np.where(gp >= 15, 1.0, prov)
    ps_adj = core * prov

    # ML blend
    ps_ml = estimate_ml_blend(df, pd.Series(ps_adj, index=df.index), sos_adj, cfg)

    return ps_ml.clip(0.0, 1.0)


# ─── Layer 2: SOS adjustment heuristics ───────────────────────────────────────


def estimate_sos_adjustment(df: pd.DataFrame, cfg: Dict, games_df: Optional[pd.DataFrame] = None) -> pd.Series:
    """Estimate how sos_norm would change from SOS-related config changes.

    If games_df is provided, uses actual game data for exact SOS trim and SCF
    computation. Otherwise falls back to heuristics.
    """
    sos = df["sos_norm"].fillna(0.5).copy()
    sos_raw = df["sos"].fillna(0.5).copy()
    gp = df["games_played"].fillna(0)
    wr = (df["wins"].fillna(0) / gp.clip(lower=1)).fillna(0)

    # --- Trim adjustment (exact if games_df available) ---
    if games_df is not None and not games_df.empty:
        sos = _adjust_for_trim_exact(df, sos, games_df, cfg)
    else:
        sos = _adjust_for_trim_heuristic(df, sos, cfg)

    # --- SCF dampening (exact if games_df available) ---
    if games_df is not None and not games_df.empty:
        sos = _adjust_for_scf_exact(df, sos, sos_raw, wr, games_df, cfg)
    else:
        sos = _adjust_for_scf_heuristic(df, sos, sos_raw, wr, cfg)

    # --- PageRank dampening ---
    sos = _adjust_for_pagerank(sos, sos_raw, cfg)

    # --- Low-sample shrinkage ---
    sos = _adjust_for_shrinkage(sos, gp, cfg)

    # --- Z-score blend ---
    sos = _adjust_for_zscore_blend(df, sos, cfg)

    return sos.clip(0.0, 1.0)


def _adjust_for_trim_exact(df: pd.DataFrame, sos: pd.Series, games_df: pd.DataFrame, cfg: Dict) -> pd.Series:
    """Recompute SOS with different trim settings using actual game data."""
    trim_pct = cfg.get("TRIM_PERCENT", 0.25)
    trim_soft = cfg.get("TRIM_SOFT_WEIGHT", 0.15)
    trim_min_games = cfg.get("TRIM_MIN_GAMES", 8)
    trim_max_games = cfg.get("TRIM_MAX_GAMES", 6)
    prod_trim = PROD_CONFIG["TRIM_PERCENT"]
    prod_soft = PROD_CONFIG["TRIM_SOFT_WEIGHT"]

    if trim_pct == prod_trim and trim_soft == prod_soft:
        return sos

    # For each team, compute trimmed weighted mean of opponent base_strength
    team_ids = set(df["team_id"].values)
    team_games = games_df[games_df["team_id"].isin(team_ids)].copy()

    if team_games.empty:
        return sos

    new_sos_map = {}
    for tid, grp in team_games.groupby("team_id"):
        strengths = grp["opp_base_strength"].values.copy()
        n = len(strengths)

        if trim_pct <= 0 or n < trim_min_games:
            new_sos_map[tid] = float(np.mean(strengths))
            continue

        # Sort ascending, trim bottom
        sorted_idx = np.argsort(strengths)
        n_trim = min(int(np.floor(n * trim_pct)), trim_max_games)
        weights = np.ones(n)

        if n_trim > 0:
            if trim_soft <= 0:  # hard trim
                weights[sorted_idx[:n_trim]] = 0.0
            else:
                weights[sorted_idx[:n_trim]] = trim_soft

        w_sum = weights.sum()
        if w_sum > 0:
            new_sos_map[tid] = float(np.average(strengths, weights=weights))
        else:
            new_sos_map[tid] = float(np.mean(strengths))

    # Convert raw SOS to percentile within cohort (approximate normalization)
    new_sos_series = df["team_id"].map(new_sos_map)
    filled = new_sos_series.fillna(sos)

    # Percentile-normalize within cohort
    normalized = filled.copy()
    for (age, gender), grp in df.groupby(["age_group", "gender"]):
        idx = grp.index
        vals = filled.loc[idx]
        if len(vals) > 1:
            normalized.loc[idx] = vals.rank(method="average") / len(vals)
        else:
            normalized.loc[idx] = 0.5

    return normalized.clip(0.0, 1.0)


def _adjust_for_trim_heuristic(df: pd.DataFrame, sos: pd.Series, cfg: Dict) -> pd.Series:
    """Fallback: estimate SOS trim impact using cohort-mean heuristic."""
    trim_pct = cfg.get("TRIM_PERCENT", 0.25)
    trim_soft = cfg.get("TRIM_SOFT_WEIGHT", 0.15)

    if trim_pct == PROD_CONFIG["TRIM_PERCENT"] and trim_soft == PROD_CONFIG["TRIM_SOFT_WEIGHT"]:
        return sos

    cohort_means = df.groupby(["age_group", "gender"])["sos_norm"].transform("mean")
    below_mean = (sos < cohort_means).astype(float)
    trim_delta = trim_pct - PROD_CONFIG["TRIM_PERCENT"]
    soft_delta = PROD_CONFIG["TRIM_SOFT_WEIGHT"] - trim_soft
    shift_factor = trim_delta * 0.3 + soft_delta * 0.1
    adjustment = shift_factor * (0.5 - below_mean) * 0.1
    return (sos + adjustment).clip(0.0, 1.0)


def _adjust_for_scf_exact(
    df: pd.DataFrame, sos: pd.Series, sos_raw: pd.Series, wr: pd.Series, games_df: pd.DataFrame, cfg: Dict
) -> pd.Series:
    """Compute SCF per team using actual opponent state data."""
    if not cfg.get("SCF_ENABLED", True):
        return sos

    scf_wr_threshold = cfg.get("SCF_QUALITY_MIN_WIN_RATE", 0.55)
    diversity_divisor = cfg.get("SCF_DIVERSITY_DIVISOR", 4.0)
    scf_floor = cfg.get("SCF_FLOOR", 0.4)
    neutral = cfg.get("SCF_NEUTRAL_SOS", 0.5)
    quality_boost_min = cfg.get("SCF_QUALITY_BOOST_MIN", 0.85)
    min_bridge = cfg.get("MIN_BRIDGE_GAMES", 3)
    isolation_cap = cfg.get("ISOLATION_SOS_CAP", 0.60)

    # Get each team's home state
    team_state = dict(zip(df["team_id"], df["state_code"].fillna("UNKNOWN")))

    # Compute per-team SCF from game data
    team_ids = set(df["team_id"].values)
    team_games = games_df[games_df["team_id"].isin(team_ids)]

    scf_adjustments = {}
    for tid, grp in team_games.groupby("team_id"):
        home_st = team_state.get(tid, "UNKNOWN")
        opp_states = grp["opp_state_code"].values
        unique_states = len(set(s for s in opp_states if s != "UNKNOWN"))
        bridge_count = sum(1 for s in opp_states if s != home_st and s != "UNKNOWN")

        # State diversity
        state_diversity = min(unique_states / diversity_divisor, 1.0)
        scf = max(scf_floor, min(1.0, state_diversity))

        # Quality override (requires WR gate)
        team_wr = wr.get(df.index[df["team_id"] == tid][0], 0.5) if (df["team_id"] == tid).any() else 0.5
        avg_opp_str = grp["opp_base_strength"].mean()
        # Use p65 of cohort as quality threshold
        cohort_mask = (
            (df["age_group"] == df.loc[df["team_id"] == tid, "age_group"].iloc[0])
            if (df["team_id"] == tid).any()
            else pd.Series(dtype=bool)
        )
        quality_threshold = 0.5  # fallback
        if cohort_mask.any():
            cohort_strengths = 0.5 * df.loc[cohort_mask, "off_norm"].fillna(0.5) + 0.5 * df.loc[
                cohort_mask, "def_norm"
            ].fillna(0.5)
            quality_threshold = cohort_strengths.quantile(0.65)

        quality_boosted = avg_opp_str >= quality_threshold and team_wr >= scf_wr_threshold
        if quality_boosted:
            scf = max(scf, quality_boost_min)

        # Isolation
        is_isolated = not quality_boosted and (bridge_count < min_bridge)

        scf_adjustments[tid] = {"scf": scf, "isolated": is_isolated}

    # Apply SCF dampening to sos_raw
    result = sos.copy()
    for tid, data in scf_adjustments.items():
        mask = df["team_id"] == tid
        if not mask.any():
            continue
        idx = mask.idxmax()
        raw = sos_raw.loc[idx]
        dampened = neutral + data["scf"] * (raw - neutral)
        if data["isolated"]:
            dampened = min(dampened, isolation_cap)
        result.loc[idx] = dampened

    return result.clip(0.0, 1.0)


def _adjust_for_scf_heuristic(
    df: pd.DataFrame, sos: pd.Series, sos_raw: pd.Series, wr: pd.Series, cfg: Dict
) -> pd.Series:
    """Fallback: estimate SCF impact using win rate threshold changes."""
    if not cfg.get("SCF_ENABLED", True):
        return sos

    scf_wr_threshold = cfg.get("SCF_QUALITY_MIN_WIN_RATE", 0.55)
    prod_wr_threshold = PROD_CONFIG["SCF_QUALITY_MIN_WIN_RATE"]
    isolation_cap = cfg.get("ISOLATION_SOS_CAP", 0.60)
    prod_isolation_cap = PROD_CONFIG["ISOLATION_SOS_CAP"]
    scf_floor = cfg.get("SCF_FLOOR", 0.4)
    neutral = cfg.get("SCF_NEUTRAL_SOS", 0.5)

    if scf_wr_threshold != prod_wr_threshold:
        if scf_wr_threshold > prod_wr_threshold:
            loses_override = (wr >= prod_wr_threshold) & (wr < scf_wr_threshold)
            dampened = neutral + scf_floor * (sos_raw - neutral)
            sos = sos.where(~loses_override, dampened.clip(0.0, 1.0))
        else:
            gains_override = (wr >= scf_wr_threshold) & (wr < prod_wr_threshold)
            sos = sos.where(~gains_override, sos_raw.clip(0.0, 1.0))

    if isolation_cap != prod_isolation_cap:
        near_old_cap = (sos >= prod_isolation_cap - 0.05) & (sos <= prod_isolation_cap + 0.02)
        if isolation_cap < prod_isolation_cap:
            sos = sos.where(~near_old_cap, sos.clip(upper=isolation_cap))

    return sos


def _adjust_for_pagerank(sos: pd.Series, sos_raw: pd.Series, cfg: Dict) -> pd.Series:
    """Estimate SOS impact from PageRank dampening changes."""
    alpha = cfg.get("PAGERANK_ALPHA", 0.85)
    baseline = cfg.get("PAGERANK_BASELINE", 0.5)
    prod_alpha = PROD_CONFIG["PAGERANK_ALPHA"]

    if alpha == prod_alpha:
        return sos

    # More dampening (lower alpha) pulls SOS toward baseline
    # Less dampening (higher alpha) lets raw SOS through
    alpha_delta = alpha - prod_alpha
    # Approximate: shift proportional to distance from baseline
    adjustment = alpha_delta * (sos_raw - baseline) * 0.3
    return (sos + adjustment).clip(0.0, 1.0)


def _adjust_for_shrinkage(sos: pd.Series, gp: pd.Series, cfg: Dict) -> pd.Series:
    """Estimate SOS impact from low-sample shrinkage parameter changes."""
    min_games = cfg.get("MIN_GAMES_FOR_TOP_SOS", 10)
    anchor = cfg.get("SOS_SHRINKAGE_ANCHOR", 0.35)
    prod_min_games = PROD_CONFIG["MIN_GAMES_FOR_TOP_SOS"]
    prod_anchor = PROD_CONFIG["SOS_SHRINKAGE_ANCHOR"]

    if min_games == prod_min_games and anchor == prod_anchor:
        return sos

    # Teams below the threshold get shrunk toward anchor
    low_sample = gp < min_games
    shrink_factor = (gp / max(min_games, 1)).clip(0.0, 1.0)
    shrunk = anchor + shrink_factor * (sos - anchor)

    # Only apply to low-sample teams
    return sos.where(~low_sample, shrunk).clip(0.0, 1.0)


def _adjust_for_zscore_blend(df: pd.DataFrame, sos: pd.Series, cfg: Dict) -> pd.Series:
    """Estimate SOS impact from hybrid normalization blend changes."""
    blend = cfg.get("SOS_NORM_HYBRID_ZSCORE_BLEND", 0.30)
    prod_blend = PROD_CONFIG["SOS_NORM_HYBRID_ZSCORE_BLEND"]

    if blend == prod_blend:
        return sos

    # Higher z-score blend preserves natural gaps (spreads out top/bottom)
    # Lower z-score blend compresses toward uniform distribution
    blend_delta = blend - prod_blend

    # Teams at extremes (far from 0.5) are most affected
    distance_from_center = (sos - 0.5).abs()
    adjustment = blend_delta * distance_from_center * 0.15
    return (sos + adjustment * np.sign(sos - 0.5)).clip(0.0, 1.0)


# ─── Layer 3: ML authority estimation ─────────────────────────────────────────


def estimate_ml_blend(df: pd.DataFrame, ps_adj: pd.Series, sos_adj: pd.Series, cfg: Dict) -> pd.Series:
    """Estimate ML-blended power score with potentially different thresholds/alpha."""
    ml_alpha = cfg.get("ML_ALPHA", 0.08)
    low = cfg.get("ML_THRESHOLD_LOW", SOS_ML_THRESHOLD_LOW)
    high = cfg.get("ML_THRESHOLD_HIGH", SOS_ML_THRESHOLD_HIGH)

    ml_scale = ((sos_adj - low) / max(high - low, 0.01)).clip(0.0, 1.0)
    ml_norm = df["ml_norm"].fillna(0.0)
    ps_ml = ps_adj + ml_norm * ml_alpha * ml_scale

    return ps_ml.clip(0.0, 1.0)


# ─── Layer 4: Rank estimation ─────────────────────────────────────────────────


def simulate_rank_changes(df: pd.DataFrame, new_scores: pd.Series) -> pd.DataFrame:
    """Compute estimated rank changes within each cohort."""
    result = df[["team_id", "age_group", "gender", "state_code", "rank_in_cohort_ml"]].copy()
    result["old_score"] = df["power_score_true"].fillna(df["powerscore_ml"])
    result["new_score"] = new_scores

    age_num = df["age_group"].str.extract(r"(\d+)").astype(float).iloc[:, 0]
    anchors = age_num.map(AGE_TO_ANCHOR).fillna(1.0)
    result["old_final"] = result["old_score"] * anchors
    result["new_final"] = result["new_score"] * anchors

    result["old_rank"] = (
        result.groupby(["age_group", "gender"])["old_final"].rank(ascending=False, method="min").astype(int)
    )
    result["new_rank"] = (
        result.groupby(["age_group", "gender"])["new_final"].rank(ascending=False, method="min").astype(int)
    )
    result["rank_delta"] = result["old_rank"] - result["new_rank"]
    result["score_delta"] = result["new_score"] - result["old_score"]

    return result


# ─── Sensitivity flags ────────────────────────────────────────────────────────


def flag_sensitive_teams(df: pd.DataFrame) -> pd.DataFrame:
    """Flag teams with high sensitivity to config changes."""
    flags = pd.DataFrame(index=df.index)
    sos = df["sos_norm"].fillna(0.5)
    gp = df["games_played"].fillna(0)
    wr = (df["wins"].fillna(0) / gp.clip(lower=1)).fillna(0)

    flags["near_ml_threshold"] = (sos >= 0.40) & (sos <= 0.65)
    flags["low_sample"] = gp < 10
    flags["sos_sensitive"] = (gp >= 8) & (gp <= 15)
    flags["scf_vulnerable"] = (wr >= 0.45) & (wr <= 0.60)  # Near WR gate threshold
    flags["high_sos"] = sos >= 0.85  # Might be bubble-inflated

    ps = df["power_score_true"].fillna(df["powerscore_ml"])
    for (age, gender), grp in df.groupby(["age_group", "gender"]):
        grp_ps = ps.loc[grp.index]
        neighbor_counts = grp_ps.apply(lambda x: ((grp_ps - x).abs() < 0.01).sum() - 1)
        flags.loc[grp.index, "dense_cluster"] = neighbor_counts > 3

    return flags


# ─── Output formatting ───────────────────────────────────────────────────────


def print_scenario_report(scenario_name: str, ranks: pd.DataFrame, df: pd.DataFrame, top_n: int = 20):
    """Print formatted report for a single scenario."""
    abs_delta = ranks["rank_delta"].abs()

    # Identify which config keys differ from production

    print(f"\n{'=' * 80}")
    print(f"  Scenario: {scenario_name}")
    print(f"{'=' * 80}")

    print("\n  Summary:")
    print(f"    Median rank change:  {abs_delta.median():.0f}")
    print(f"    p90 rank change:     {abs_delta.quantile(0.90):.0f}")
    print(f"    Max rank change:     {abs_delta.max():.0f}")
    print(f"    Teams moving >10:    {(abs_delta > 10).sum()}")
    print(f"    Teams moving >50:    {(abs_delta > 50).sum()}")
    print(f"    Avg score delta:     {ranks['score_delta'].mean():+.4f}")

    top = ranks.nlargest(top_n, "rank_delta", keep="first")
    bottom = ranks.nsmallest(top_n, "rank_delta", keep="first")
    movers = pd.concat([top, bottom]).drop_duplicates().sort_values("rank_delta", ascending=False)

    if len(movers) > 0:
        print(f"\n  Top Movers (up to {top_n} each direction):")
        print(f"  {'Team':<14} {'Age':<5} {'St':<4} {'Old#':<6} {'New#':<6} {'Delta':<7} {'ScorΔ':<8}")
        print(f"  {'-' * 55}")
        for _, r in movers.head(top_n * 2).iterrows():
            d = "+" if r["rank_delta"] > 0 else "-" if r["rank_delta"] < 0 else "="
            print(
                f"  {str(r['team_id'])[:13]:<14} {r['age_group']:<5} {str(r.get('state_code', '?'))[:3]:<4} "
                f"{r['old_rank']:<6} {r['new_rank']:<6} {d}{abs(r['rank_delta']):<6.0f} "
                f"{r['score_delta']:+.4f}"
            )

    cohort_stats = ranks.groupby(["age_group", "gender"]).agg(
        avg_delta=("rank_delta", lambda x: x.abs().mean()),
        p90_delta=("rank_delta", lambda x: x.abs().quantile(0.90)),
        max_delta=("rank_delta", lambda x: x.abs().max()),
        n_teams=("team_id", "count"),
    )
    print("\n  Cohort Stability:")
    print(f"  {'Cohort':<15} {'N':<6} {'AvgD':<8} {'p90D':<8} {'MaxD':<8}")
    print(f"  {'-' * 45}")
    for (age, gender), row in cohort_stats.iterrows():
        print(
            f"  {age} {gender[0]:<9} {row['n_teams']:<6.0f} {row['avg_delta']:<8.1f} "
            f"{row['p90_delta']:<8.0f} {row['max_delta']:<8.0f}"
        )


def detect_ml_crossings(df: pd.DataFrame, sos_adj: pd.Series, cfg: Dict):
    """Detect teams that would cross ML authority thresholds under new config."""
    low = cfg.get("ML_THRESHOLD_LOW", SOS_ML_THRESHOLD_LOW)
    high = cfg.get("ML_THRESHOLD_HIGH", SOS_ML_THRESHOLD_HIGH)
    sos_curr = df["sos_norm"].fillna(0.5)

    curr_scale = ((sos_curr - SOS_ML_THRESHOLD_LOW) / (SOS_ML_THRESHOLD_HIGH - SOS_ML_THRESHOLD_LOW)).clip(0.0, 1.0)
    new_scale = ((sos_adj - low) / max(high - low, 0.01)).clip(0.0, 1.0)

    gained = (new_scale - curr_scale > 0.1).sum()
    lost = (curr_scale - new_scale > 0.1).sum()

    if gained > 0 or lost > 0:
        print("\n  ML Threshold Crossings:")
        print(f"    Teams gaining ML authority (>10%): {gained}")
        print(f"    Teams losing ML authority (>10%):  {lost}")


# ─── Main runners ─────────────────────────────────────────────────────────────


def run_estimator(
    cohort: Optional[str] = None,
    gender: Optional[str] = None,
    scenarios: Optional[List[Dict]] = None,
    top_n: int = 20,
    skip_games: bool = False,
):
    """Run the config impact estimator across all teams."""
    df = load_rankings(cohort_filter=cohort, gender_filter=gender)
    if df.empty:
        logger.error("No data loaded")
        return

    # Load game data for exact SOS/SCF estimation
    games_df = None
    if not skip_games:
        games_df = load_game_data(df["team_id"].tolist())
    else:
        logger.info("Skipping game data load (--fast mode)")

    if scenarios is None:
        scenarios = default_scenarios()

    flags = flag_sensitive_teams(df)
    logger.info(
        f"Sensitivity: {flags['near_ml_threshold'].sum()} near ML, "
        f"{flags['scf_vulnerable'].sum()} SCF-vulnerable, "
        f"{flags['low_sample'].sum()} low-sample, "
        f"{flags['high_sos'].sum()} high-SOS"
    )

    for scenario in scenarios:
        name = scenario.get("name", "Unnamed")
        new_scores = estimate_power_score(df, scenario, games_df=games_df)
        ranks = simulate_rank_changes(df, new_scores)
        print_scenario_report(name, ranks, df, top_n=top_n)
        sos_adj = estimate_sos_adjustment(df, scenario, games_df=games_df)
        detect_ml_crossings(df, sos_adj, scenario)


def run_team_whatif(
    team_id: str,
    target_rank: Optional[int] = None,
    cohort: Optional[str] = None,
    gender: Optional[str] = None,
    skip_games: bool = False,
):
    """Team-focused what-if: sweep ALL config knobs for a specific team."""
    sb = _get_supabase()

    team_info = sb.table("rankings_full").select("team_id, age_group, gender").eq("team_id", team_id).execute()
    if not team_info.data:
        logger.error(f"Team {team_id} not found")
        return
    ti = team_info.data[0]
    cohort = cohort or ti["age_group"]
    gender = gender or ti["gender"]

    team_name_r = sb.table("teams").select("team_name").eq("team_id_master", team_id).limit(1).execute()
    team_name = team_name_r.data[0]["team_name"] if team_name_r.data else team_id[:12]

    df = load_rankings(cohort_filter=cohort, gender_filter=gender)
    if df.empty or not (df["team_id"] == team_id).any():
        logger.error(f"Team {team_id} not in loaded data")
        return

    # Load game data for exact estimation
    games_df = None
    if not skip_games:
        games_df = load_game_data(df["team_id"].tolist())
    else:
        logger.info("Skipping game data load (--fast mode)")

    team_row = df[df["team_id"] == team_id].iloc[0]

    print(f"\n{'=' * 85}")
    print(f"  Team What-If: {team_name}")
    print(f"  {team_id}")
    print(f"  Cohort: {cohort} {gender}")
    print(f"{'=' * 85}")
    print("\n  Current metrics:")
    print(
        f"    Record: {int(team_row.get('wins', 0))}-{int(team_row.get('losses', 0))}-{int(team_row.get('draws', 0))}  "
        f"GP={int(team_row.get('games_played', 0))}"
    )
    print(
        f"    OFF={team_row.get('off_norm', 0):.3f}  DEF={team_row.get('def_norm', 0):.3f}  "
        f"SOS={team_row.get('sos_norm', 0):.3f}"
    )
    print(
        f"    PS_adj={team_row.get('powerscore_adj', 0):.3f}  PS_ML={team_row.get('powerscore_ml', 0):.3f}  "
        f"Final={team_row.get('power_score_final', 0):.3f}"
    )
    print(
        f"    ML_norm={team_row.get('ml_norm', 0):.3f}  Perf={team_row.get('perf_centered', 0):.3f}  "
        f"Prov_mult={team_row.get('provisional_mult', 1):.3f}"
    )
    print(f"    Current rank: #{team_row.get('rank_in_cohort_ml', '?')}")
    if target_rank:
        print(f"    Target rank: #{target_rank}")

    # Build comprehensive sweep scenarios
    scenarios = default_scenarios()

    # Fine-grained SOS weight sweep
    for v in [0.35, 0.40, 0.45, 0.50, 0.55, 0.65, 0.70]:
        w = (1.0 - v) / 2
        scenarios.append({"name": f"SOS={v:.2f}", **{**PROD_CONFIG, "SOS_WEIGHT": v, "OFF_WEIGHT": w, "DEF_WEIGHT": w}})

    # ML alpha sweep
    for v in [0.02, 0.04, 0.06, 0.10, 0.15, 0.20, 0.25]:
        scenarios.append({"name": f"ML_a={v:.2f}", **{**PROD_CONFIG, "ML_ALPHA": v}})

    # SCF WR gate sweep
    for v in [0.40, 0.45, 0.50, 0.55, 0.60, 0.65]:
        scenarios.append({"name": f"SCF_WR={v:.2f}", **{**PROD_CONFIG, "SCF_QUALITY_MIN_WIN_RATE": v}})

    # Isolation cap sweep
    for v in [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]:
        scenarios.append({"name": f"IsoCap={v:.2f}", **{**PROD_CONFIG, "ISOLATION_SOS_CAP": v}})

    # Bridge games sweep
    for v in [1, 2, 3, 4, 5, 8, 10]:
        scenarios.append({"name": f"Bridge={v}", **{**PROD_CONFIG, "MIN_BRIDGE_GAMES": v}})

    # PageRank alpha sweep
    for v in [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]:
        scenarios.append({"name": f"PR_a={v:.2f}", **{**PROD_CONFIG, "PAGERANK_ALPHA": v}})

    # Perf weight sweep
    for v in [0.0, 0.03, 0.05, 0.08, 0.10, 0.15]:
        scenarios.append({"name": f"Perf={v:.2f}", **{**PROD_CONFIG, "PERF_BLEND_WEIGHT": v}})

    # SOS shrinkage anchor sweep
    for v in [0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
        scenarios.append({"name": f"ShrAnc={v:.2f}", **{**PROD_CONFIG, "SOS_SHRINKAGE_ANCHOR": v}})

    # Z-score blend sweep
    for v in [0.0, 0.10, 0.20, 0.30, 0.40, 0.50]:
        scenarios.append({"name": f"ZBlend={v:.2f}", **{**PROD_CONFIG, "SOS_NORM_HYBRID_ZSCORE_BLEND": v}})

    # Trim sweep
    for v in [0.0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]:
        scenarios.append({"name": f"Trim={v:.0%}", **{**PROD_CONFIG, "TRIM_PERCENT": v}})

    # Diversity divisor sweep
    for v in [2.0, 3.0, 4.0, 5.0, 6.0]:
        scenarios.append({"name": f"DivDiv={v:.0f}", **{**PROD_CONFIG, "SCF_DIVERSITY_DIVISOR": v}})

    # Deduplicate by name
    seen = set()
    unique_scenarios = []
    for s in scenarios:
        if s["name"] not in seen:
            seen.add(s["name"])
            unique_scenarios.append(s)

    print(f"\n  {'Scenario':<35} {'Est Rank':<10} {'RankD':<8} {'ScoreD':<10} {'Hit?':<5}")
    print(f"  {'-' * 70}")

    results = []
    for scenario in unique_scenarios:
        name = scenario.get("name", "?")
        new_scores = estimate_power_score(df, scenario, games_df=games_df)
        ranks = simulate_rank_changes(df, new_scores)

        team_rank_row = ranks[ranks["team_id"] == team_id]
        if team_rank_row.empty:
            continue
        tr = team_rank_row.iloc[0]
        new_rank = int(tr["new_rank"])
        delta = int(tr["rank_delta"])
        score_d = tr["score_delta"]
        hit = "Y" if target_rank and new_rank <= target_rank else ""

        results.append((name, new_rank, delta, score_d, hit))
        d = "+" if delta > 0 else "-" if delta < 0 else "="
        print(f"  {name:<35} #{new_rank:<9} {d}{abs(delta):<7} {score_d:+.4f}    {hit}")

    if target_rank:
        hits = [r for r in results if r[4] == "Y"]
        if hits:
            print(f"\n  {len(hits)} scenario(s) achieve rank #{target_rank} or better:")
            for name, rank, delta, score_d, _ in sorted(hits, key=lambda x: x[1]):
                print(f"    -> {name}: rank #{rank}")
        else:
            closest = min(results, key=lambda x: x[1])
            print(f"\n  No scenario achieves #{target_rank}. Closest: {closest[0]} -> #{closest[1]}")


def main():
    parser = argparse.ArgumentParser(description="Estimate ranking impact of config changes without full rerun")
    subparsers = parser.add_subparsers(dest="command")

    sp = subparsers.add_parser("scenarios", help="Compare config scenarios across all teams")
    sp.add_argument("--cohort", type=str, help="Filter to age group (e.g., u14)")
    sp.add_argument("--gender", type=str, help="Filter to gender (Male/Female)")
    sp.add_argument("--top", type=int, default=20, help="Number of top movers to show")
    sp.add_argument("--fast", action="store_true", help="Skip game data load (faster but less accurate SOS/SCF)")

    wp = subparsers.add_parser("whatif", help="What-if analysis for a specific team")
    wp.add_argument("team_id", type=str, help="Team UUID")
    wp.add_argument("--target", type=int, help="Target rank to achieve")
    wp.add_argument("--cohort", type=str, help="Override cohort")
    wp.add_argument("--gender", type=str, help="Override gender")
    wp.add_argument("--fast", action="store_true", help="Skip game data load (faster but less accurate SOS/SCF)")

    args = parser.parse_args()

    if args.command == "whatif":
        run_team_whatif(
            args.team_id,
            target_rank=args.target,
            cohort=args.cohort,
            gender=args.gender,
            skip_games=getattr(args, "fast", False),
        )
    else:
        run_estimator(
            cohort=getattr(args, "cohort", None),
            gender=getattr(args, "gender", None),
            top_n=getattr(args, "top", 20),
            skip_games=getattr(args, "fast", False),
        )


if __name__ == "__main__":
    main()
