"""Layer 13: ML Predictive Adjustment for Rankings"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple

# Prefer XGBoost; fall back to RandomForest
try:
    from xgboost import XGBRegressor  # type: ignore
    _HAS_XGB = True
except Exception:
    from sklearn.ensemble import RandomForestRegressor  # type: ignore
    _HAS_XGB = False

# Import ML_CONFIG if available (may not exist in older configs)
try:
    from config.settings import ML_CONFIG
except ImportError:
    ML_CONFIG = None


# ----------------------------
# Config for Layer 13 (ML)
# ----------------------------
@dataclass
class Layer13Config:
    enabled: bool = True
    
    # data window and cohorting
    lookback_days: int = 365
    cohort_key_cols: Tuple[str, str] = ("age", "gender")
    
    # residual aggregation
    recency_decay_lambda: float = 0.06     # exp(-lambda * (recency-1)); short-term form focus
    min_team_games_for_residual: int = 6
    residual_clip_goals: float = 3.5       # guardrail on residual outliers
    min_training_rows: int = 30            # Minimum rows to enable ML (prevents leakage)
    
    # blend into PowerScore
    alpha: float = 0.15                    # Unified default: 0.15 is sweet spot (0.05–0.20 range)
    norm_mode: str = "percentile"          # or "zscore"
    
    # supabase
    table_name: str = "games"              # Supabase games table
    provider_filter: Optional[str] = None   # e.g., "gotsport"
    
    # core column names (Supabase format)
    date_col: str = "game_date"
    team_id_col: str = "team_id_master"
    opp_id_col: str = "opp_id_master"
    gf_col: str = "gf"
    ga_col: str = "ga"
    age_col: str = "age"
    gender_col: str = "gender"
    opp_age_col: str = "opp_age"
    opp_gender_col: str = "opp_gender"
    
    # model params
    xgb_params: Optional[Dict] = None
    rf_params: Optional[Dict] = None
    
    def __post_init__(self):
        # Load from ML_CONFIG if available
        if ML_CONFIG:
            self.enabled = ML_CONFIG.get('enabled', self.enabled)
            self.alpha = ML_CONFIG.get('alpha', self.alpha)
            self.recency_decay_lambda = ML_CONFIG.get('recency_decay_lambda', self.recency_decay_lambda)
            self.min_team_games_for_residual = ML_CONFIG.get('min_team_games_for_residual', self.min_team_games_for_residual)
            self.residual_clip_goals = ML_CONFIG.get('residual_clip_goals', self.residual_clip_goals)
            self.norm_mode = ML_CONFIG.get('norm_mode', self.norm_mode)
        
        if self.xgb_params is None:
            self.xgb_params = dict(
                n_estimators=220,
                max_depth=5,
                learning_rate=0.08,
                subsample=0.9,
                colsample_bytree=0.9,
                reg_lambda=1.0,
                objective="reg:squarederror",
                n_jobs=-1,
                tree_method="hist",
                random_state=42,
            )
        
        if self.rf_params is None:
            self.rf_params = dict(
                n_estimators=240,
                max_depth=18,
                min_samples_leaf=2,
                n_jobs=-1,
                random_state=42,
            )


# ----------------------------
# Ranking helper with SOS tiebreaker
# ----------------------------
def _rank_with_sos_tiebreaker(
    df: pd.DataFrame,
    cohort_cols: List[str],
    score_col: str,
    sos_col: str = "sos"
) -> pd.Series:
    """
    Calculate ranks with SOS as tiebreaker for teams with same score.

    Args:
        df: DataFrame with teams
        cohort_cols: Columns defining cohorts (e.g., ["age", "gender"])
        score_col: Column to rank by (e.g., "powerscore_ml")
        sos_col: Column to use as tiebreaker (default: "sos")

    Returns:
        Series of integer ranks (1-based, no ties)
    """
    if df.empty:
        return pd.Series(dtype=int)

    # If SOS column doesn't exist, fall back to original ranking
    if sos_col not in df.columns:
        return df.groupby(list(cohort_cols))[score_col].rank(
            ascending=False, method="min"
        ).astype(int)

    # Sort by cohort, then score DESC, then SOS DESC (tiebreaker)
    sort_cols = list(cohort_cols) + [score_col, sos_col]
    ascending = [True] * len(cohort_cols) + [False, False]

    df_sorted = df.sort_values(sort_cols, ascending=ascending).copy()

    # Assign unique ranks within each cohort
    df_sorted["_rank"] = df_sorted.groupby(list(cohort_cols)).cumcount() + 1

    # Return ranks in original order
    return df_sorted["_rank"].reindex(df.index).astype(int)


# ----------------------------
# Game residual extraction
# ----------------------------
def _extract_game_residuals(feats: pd.DataFrame, games_df: pd.DataFrame, cfg: Layer13Config) -> pd.DataFrame:
    """
    Extract per-game residuals from feats DataFrame and map to original game IDs.

    Since v53e format duplicates each game (home and away perspective), we filter to
    home team perspective only to get one residual per game.

    NOTE: Only returns home-team perspective residuals for per-game display.
    Per-team ML scores (ml_overperf, ml_norm) correctly aggregate both perspectives
    via _aggregate_team_residuals. For away-team display, the frontend should negate
    the home team's residual.

    The residual represents the home team's perspective (positive = home outperformed).

    Returns DataFrame with columns: game_id (UUID), ml_overperformance (float)
    """
    import logging
    logger = logging.getLogger(__name__)

    logger.info(f"[DEBUG _extract_game_residuals] Input feats: {len(feats)} rows, columns: {list(feats.columns)}")

    if feats.empty or 'residual' not in feats.columns:
        logger.warning("[DEBUG _extract_game_residuals] Feats empty or missing 'residual' column")
        return pd.DataFrame(columns=['game_id', 'ml_overperformance'])

    # Check if v53e format has the required fields (id, team_id, home_team_master_id)
    required_cols = {'id', 'team_id', 'home_team_master_id', 'residual'}
    if not required_cols.issubset(feats.columns):
        missing = required_cols - set(feats.columns)
        logger.warning(f"[DEBUG _extract_game_residuals] ❌ Missing required columns: {missing}")
        return pd.DataFrame(columns=['game_id', 'ml_overperformance'])

    # Filter to home team perspective only (where team_id == home_team_master_id)
    # Convert to string and normalize for comparison to handle UUID/string mismatches
    feats['team_id_str'] = feats['team_id'].astype(str).str.strip().str.lower()
    feats['home_team_master_id_str'] = feats['home_team_master_id'].astype(str).str.strip().str.lower()
    home_perspective = feats[feats['team_id_str'] == feats['home_team_master_id_str']].copy()
    logger.info(f"[DEBUG _extract_game_residuals] Home perspective after filter: {len(home_perspective)} rows")
    
    # Debug: show why rows might be filtered out
    if len(home_perspective) == 0 and len(feats) > 0:
        logger.warning(f"[DEBUG _extract_game_residuals] ⚠️ All rows filtered out! Sample team_id values: {feats['team_id_str'].head(5).tolist()}")
        logger.warning(f"[DEBUG _extract_game_residuals] Sample home_team_master_id values: {feats['home_team_master_id_str'].head(5).tolist()}")
        logger.warning(f"[DEBUG _extract_game_residuals] Matching count: {(feats['team_id_str'] == feats['home_team_master_id_str']).sum()}")
    
    if home_perspective.empty:
        logger.warning("[DEBUG _extract_game_residuals] Home perspective is empty after filtering")
        return pd.DataFrame(columns=['game_id', 'ml_overperformance'])

    # Extract game_id (UUID) and residual
    result_df = home_perspective[['id', 'residual']].copy()
    result_df = result_df.rename(columns={'id': 'game_id', 'residual': 'ml_overperformance'})

    # Ensure game_id is string UUID
    result_df['game_id'] = result_df['game_id'].astype(str)
    result_df['ml_overperformance'] = result_df['ml_overperformance'].astype(float)

    # Remove duplicates (shouldn't happen, but safety check)
    result_df = result_df.drop_duplicates(subset=['game_id'], keep='first')

    logger.info(f"[DEBUG _extract_game_residuals] ✅ Extracted {len(result_df)} game residuals")

    return result_df


# ----------------------------
# Public entry: apply ML layer
# ----------------------------
async def apply_predictive_adjustment(
    supabase_client,
    teams_df: pd.DataFrame,                # output["teams"] from compute_rankings()
    games_used_df: Optional[pd.DataFrame] = None,  # optional; if None, fetched from Supabase
    cfg: Optional[Layer13Config] = None,
    return_game_residuals: bool = False,   # If True, also return per-game residuals
) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns a copy of teams_df with:
      - ml_overperf (raw residual per team, goal units, recency-weighted)
      - ml_norm     (cohort-normalized residual, ~[-0.5,+0.5])
      - powerscore_ml
      - rank_in_cohort_ml

    If return_game_residuals=True, returns (teams_df, game_residuals_df) where
    game_residuals_df has columns: game_id, residual (from home team perspective)
    """
    cfg = cfg or Layer13Config()
    out = teams_df.copy()

    if not cfg.enabled or out.empty:
        # ensure columns exist for downstream consumers
        out["ml_overperf"] = 0.0
        out["ml_norm"] = 0.0
        out["powerscore_ml"] = out.get("powerscore_adj", out.get("powerscore_core", 0.0))
        # Clamp PowerScore within [0.0, 1.0] to preserve normalization bounds
        out["powerscore_ml"] = out["powerscore_ml"].clip(0.0, 1.0)
        out["rank_in_cohort_ml"] = _rank_with_sos_tiebreaker(out, cfg.cohort_key_cols, "powerscore_ml")
        if return_game_residuals:
            return out, pd.DataFrame(columns=['game_id', 'residual'])
        return out

    # 1) Acquire training data
    if games_used_df is None or games_used_df.empty:
        games_df = await _fetch_games_from_supabase(
            supabase_client=supabase_client,
            table_name=cfg.table_name,
            date_col=cfg.date_col,
            lookback_days=cfg.lookback_days,
            provider_filter=cfg.provider_filter,
        )
    else:
        games_df = games_used_df.copy()

    # Ensure required columns exist (check both v53e format and config format)
    # v53e format: date, team_id, opp_id, gf, ga, age, gender, opp_age, opp_gender
    # config format: game_date, team_id_master, opp_id_master, etc.
    required_pairs = [
        ('date', cfg.date_col),
        ('team_id', cfg.team_id_col),
        ('opp_id', cfg.opp_id_col),
        ('gf', cfg.gf_col),
        ('ga', cfg.ga_col),
        ('age', cfg.age_col),
        ('gender', cfg.gender_col),
        ('opp_age', cfg.opp_age_col),
        ('opp_gender', cfg.opp_gender_col),
    ]

    missing = []
    for v53e_name, config_name in required_pairs:
        if v53e_name not in games_df.columns and config_name not in games_df.columns:
            missing.append(f"{v53e_name}/{config_name}")

    if missing:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"⚠️ Missing required columns: {missing}. Cannot train ML model.")
        # If we can't train, return pass-through
        out["ml_overperf"] = 0.0
        out["ml_norm"] = 0.0
        out["powerscore_ml"] = out.get("powerscore_adj", out.get("powerscore_core", 0.0))
        # Clamp PowerScore within [0.0, 1.0] to preserve normalization bounds
        out["powerscore_ml"] = out["powerscore_ml"].clip(0.0, 1.0)
        out["rank_in_cohort_ml"] = _rank_with_sos_tiebreaker(out, cfg.cohort_key_cols, "powerscore_ml")
        if return_game_residuals:
            return out, pd.DataFrame(columns=['game_id', 'residual'])
        return out

    # 2) Build feature matrix from games + current powers
    base_power_col = "powerscore_adj" if "powerscore_adj" in out.columns else "powerscore_core"
    power_map = dict(zip(out["team_id"].astype(str), out[base_power_col].astype(float)))

    # Compute cohort means for missing PowerScores fallback (better than hardcoded 0.5)
    cohort_power_means = {}
    global_power_mean = out[base_power_col].mean() if not out.empty else 0.5
    if "age" in out.columns and "gender" in out.columns:
        for (age, gender), grp in out.groupby(["age", "gender"]):
            cohort_power_means[(str(age), str(gender).lower())] = grp[base_power_col].mean()

    feats = _build_features(games_df, power_map, cfg, cohort_power_means, global_power_mean)

    # Check for missing PowerScores and warn if >1%
    if not feats.empty and "team_power" in feats.columns:
        # Count games where team or opp had to use fallback
        teams_in_power_map = set(power_map.keys())
        team_id_col = 'team_id' if 'team_id' in games_df.columns else cfg.team_id_col
        opp_id_col = 'opp_id' if 'opp_id' in games_df.columns else cfg.opp_id_col
        missing_team = ~games_df[team_id_col].astype(str).isin(teams_in_power_map)
        missing_opp = ~games_df[opp_id_col].astype(str).isin(teams_in_power_map)
        missing_count = (missing_team | missing_opp).sum()
        missing_pct = (missing_count / len(games_df)) * 100 if len(games_df) > 0 else 0

        if missing_pct > 1.0:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"⚠️  {missing_pct:.1f}% of games ({missing_count:,}) involve teams with missing PowerScores. "
                f"Using cohort mean as fallback. ML accuracy may be degraded."
            )
    
    if feats.empty:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"⚠️ feats DataFrame is empty after _build_features. Input games_df had {len(games_df)} rows.")
        out["ml_overperf"] = 0.0
        out["ml_norm"] = 0.0
        out["powerscore_ml"] = out[base_power_col]
        # Clamp PowerScore within [0.0, 1.0] to preserve normalization bounds
        out["powerscore_ml"] = out["powerscore_ml"].clip(0.0, 1.0)
        out["rank_in_cohort_ml"] = _rank_with_sos_tiebreaker(out, cfg.cohort_key_cols, "powerscore_ml")
        if return_game_residuals:
            return out, pd.DataFrame(columns=['game_id', 'ml_overperformance'])
        return out

    # 3) Fit model and compute residuals (with ML leakage protection)
    # 30-day time-based split to prevent leakage
    if "date" in feats.columns and len(feats) > 0:
        cutoff_date = feats["date"].max() - pd.Timedelta(days=30)
        train_feats = feats[feats["date"] < cutoff_date].copy()

        # Disable ML if insufficient training data (prevents leakage)
        if len(train_feats) < cfg.min_training_rows:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"⚠️  Layer 13 disabled: only {len(train_feats)} training rows "
                f"(need ≥{cfg.min_training_rows}). Passing through base v53E scores."
            )
            out["ml_overperf"] = 0.0
            out["ml_norm"] = 0.0
            out["powerscore_ml"] = out.get("powerscore_adj", out.get("powerscore_core", 0.0))
            out["powerscore_ml"] = out["powerscore_ml"].clip(0.0, 1.0)
            out["rank_in_cohort_ml"] = _rank_with_sos_tiebreaker(out, cfg.cohort_key_cols, "powerscore_ml")
            if return_game_residuals:
                return out, pd.DataFrame(columns=['game_id', 'ml_overperformance'])
            return out
    else:
        # No date column or empty feats - disable ML
        import logging
        logger = logging.getLogger(__name__)
        logger.warning("⚠️  Layer 13 disabled: no date column in feats. Passing through base v53E scores.")
        out["ml_overperf"] = 0.0
        out["ml_norm"] = 0.0
        out["powerscore_ml"] = out.get("powerscore_adj", out.get("powerscore_core", 0.0))
        out["powerscore_ml"] = out["powerscore_ml"].clip(0.0, 1.0)
        out["rank_in_cohort_ml"] = _rank_with_sos_tiebreaker(out, cfg.cohort_key_cols, "powerscore_ml")
        if return_game_residuals:
            return out, pd.DataFrame(columns=['game_id', 'ml_overperformance'])
        return out
    
    feats = _fit_and_residualize(feats, train_feats, cfg)
    
    # 4) Aggregate residuals by (team, age, gender) with recency decay
    team_resid = _aggregate_team_residuals(feats, cfg)
    
    # 5) Merge & normalize within cohort
    out = out.merge(team_resid, on=["team_id", "age", "gender"], how="left")
    out["ml_overperf"] = out["ml_overperf"].fillna(0.0).clip(
        lower=-cfg.residual_clip_goals, upper=cfg.residual_clip_goals
    )
    out["ml_norm"] = _normalize_by_cohort(
        out, value_col="ml_overperf", out_col="__tmp__", mode=cfg.norm_mode,
        cohort_cols=list(cfg.cohort_key_cols)
    )["__tmp__"].values - 0.5
    
    # 6) Blend into PowerScore and rerank
    #
    # IMPORTANT: ml_norm ranges [-0.5, +0.5], so the theoretical max addition is
    # alpha * 0.5 = 0.075 (with default alpha=0.15). To prevent ceiling clipping
    # that would cluster top teams at 1.0, we normalize the blended score.
    #
    # Max theoretical = 1.0 + 0.5 * alpha = 1.075 (with alpha=0.15)
    MAX_ML_THEORETICAL = 1.0 + 0.5 * cfg.alpha

    out["powerscore_ml"] = (out[base_power_col] + cfg.alpha * out["ml_norm"]) / MAX_ML_THEORETICAL
    # Safety clamp (shouldn't trigger after normalization, but keeps bounds valid)
    out["powerscore_ml"] = out["powerscore_ml"].clip(0.0, 1.0)
    out["rank_in_cohort_ml"] = _rank_with_sos_tiebreaker(out, cfg.cohort_key_cols, "powerscore_ml")

    # 7) Extract per-game residuals if requested
    if return_game_residuals:
        import logging
        logger = logging.getLogger(__name__)
        logger.info("[DEBUG apply_predictive_adjustment] About to extract game residuals...")
        logger.info(f"[DEBUG apply_predictive_adjustment] feats shape: {feats.shape}, columns: {list(feats.columns)}")
        logger.info(f"[DEBUG apply_predictive_adjustment] feats has 'residual': {'residual' in feats.columns}")
        logger.info(f"[DEBUG apply_predictive_adjustment] feats has 'id': {'id' in feats.columns}")
        logger.info(f"[DEBUG apply_predictive_adjustment] feats has 'team_id': {'team_id' in feats.columns}")
        logger.info(f"[DEBUG apply_predictive_adjustment] feats has 'home_team_master_id': {'home_team_master_id' in feats.columns}")
        if not feats.empty and 'residual' in feats.columns:
            logger.info(f"[DEBUG apply_predictive_adjustment] Residual stats: min={feats['residual'].min():.3f}, max={feats['residual'].max():.3f}, mean={feats['residual'].mean():.3f}")
        game_residuals = _extract_game_residuals(feats, games_df, cfg)
        logger.info(f"[DEBUG apply_predictive_adjustment] Extracted game_residuals: shape={game_residuals.shape}, empty={game_residuals.empty}")
        if not game_residuals.empty:
            logger.info(f"[DEBUG apply_predictive_adjustment] Sample residuals: {game_residuals.head().to_dict()}")
        return out, game_residuals

    return out


# ----------------------------
# Supabase data fetch
# ----------------------------
async def _fetch_games_from_supabase(
    supabase_client,
    *,
    table_name: str,
    date_col: str,
    lookback_days: int,
    provider_filter: Optional[str],
) -> pd.DataFrame:
    """Fetch games from Supabase and convert to v53e format for ML"""
    from src.rankings.data_adapter import fetch_games_for_rankings
    
    # Use data adapter to fetch and convert
    games_df = await fetch_games_for_rankings(
        supabase_client=supabase_client,
        lookback_days=lookback_days,
        provider_filter=provider_filter
    )
    
    if games_df.empty:
        return pd.DataFrame()
    
    # v53e format already has: date, team_id, opp_id, gf, ga, age, gender, opp_age, opp_gender
    # ML layer expects these column names, so we're good
    # Just ensure date column matches
    if date_col != 'date' and 'date' in games_df.columns:
        games_df = games_df.rename(columns={'date': date_col})
    
    return games_df


# ----------------------------
# Feature engineering & model
# ----------------------------
def _build_features(
    games: pd.DataFrame,
    power_map: Dict[str, float],
    cfg: Layer13Config,
    cohort_power_means: Optional[Dict[Tuple[str, str], float]] = None,
    global_power_mean: float = 0.5
) -> pd.DataFrame:
    """Build feature matrix for ML model

    Args:
        games: Games DataFrame in v53e format
        power_map: Dict of team_id -> PowerScore
        cfg: Layer13Config
        cohort_power_means: Dict of (age, gender) -> mean PowerScore for cohort
        global_power_mean: Fallback mean if cohort mean not available
    """
    f = games.copy()
    
    # v53e format uses: team_id, opp_id, gf, ga, age, gender, opp_age, opp_gender, date
    # Map to expected column names (v53e format is already correct)
    team_id_col = 'team_id' if 'team_id' in f.columns else (cfg.team_id_col if cfg.team_id_col in f.columns else 'team_id_master')
    opp_id_col = 'opp_id' if 'opp_id' in f.columns else (cfg.opp_id_col if cfg.opp_id_col in f.columns else 'opp_id_master')
    gf_col = 'gf' if 'gf' in f.columns else cfg.gf_col
    ga_col = 'ga' if 'ga' in f.columns else cfg.ga_col
    age_col = 'age' if 'age' in f.columns else cfg.age_col
    gender_col = 'gender' if 'gender' in f.columns else cfg.gender_col
    opp_age_col = 'opp_age' if 'opp_age' in f.columns else cfg.opp_age_col
    opp_gender_col = 'opp_gender' if 'opp_gender' in f.columns else cfg.opp_gender_col
    date_col = 'date' if 'date' in f.columns else cfg.date_col
    
    f["goal_margin"] = (f[gf_col] - f[ga_col]).astype(float)

    # Use cohort mean as fallback for missing PowerScores (not hardcoded 0.5)
    def get_team_power(row):
        team_id = str(row[team_id_col])
        if team_id in power_map:
            return power_map[team_id]
        # Fallback to cohort mean, then global mean
        if cohort_power_means:
            cohort_key = (str(row[age_col]), str(row[gender_col]).lower())
            if cohort_key in cohort_power_means:
                return cohort_power_means[cohort_key]
        return global_power_mean

    def get_opp_power(row):
        opp_id = str(row[opp_id_col])
        if opp_id in power_map:
            return power_map[opp_id]
        # Fallback to opponent's cohort mean, then global mean
        if cohort_power_means:
            cohort_key = (str(row[opp_age_col]), str(row[opp_gender_col]).lower())
            if cohort_key in cohort_power_means:
                return cohort_power_means[cohort_key]
        return global_power_mean

    f["team_power"] = f.apply(get_team_power, axis=1).astype(float)
    f["opp_power"] = f.apply(get_opp_power, axis=1).astype(float)
    f["power_diff"] = f["team_power"] - f["opp_power"]
    
    # age gap
    def _gap(a, b):
        try:
            return abs(int(float(a)) - int(float(b)))
        except Exception:
            return 0
    
    f["age_gap"] = f.apply(lambda r: _gap(r[age_col], r[opp_age_col]), axis=1)
    
    # basic cross-gender flag
    f["cross_gender"] = (f[gender_col].astype(str).str.lower()
                         != f[opp_gender_col].astype(str).str.lower()).astype(int)
    
    # recency rank per team to allow decay
    f = f.sort_values([team_id_col, date_col], ascending=[True, False])
    f["rank_recency"] = f.groupby(team_id_col)[date_col].rank(ascending=False, method="first")
    
    needed = [
        date_col, team_id_col, opp_id_col, age_col, gender_col,
        "goal_margin", "team_power", "opp_power", "power_diff", "age_gap", "cross_gender", "rank_recency"
    ]

    # Include additional columns if present (needed for extracting per-game residuals)
    for col in ['game_id', 'id', 'home_team_master_id']:
        if col in f.columns:
            needed.append(col)

    # Debug logging
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[DEBUG _build_features] Input columns: {list(f.columns)}")
    logger.info(f"[DEBUG _build_features] Has 'id': {'id' in f.columns}, Has 'home_team_master_id': {'home_team_master_id' in f.columns}")
    logger.info(f"[_build_features] Needed columns: {needed}")

    # Only keep columns that exist
    needed = [col for col in needed if col in f.columns]
    f = f[needed].dropna(subset=["goal_margin", "team_power", "opp_power"])

    logger.info(f"[DEBUG _build_features] Output columns: {list(f.columns)}, rows: {len(f)}")

    return f.reset_index(drop=True)


def _fit_and_residualize(feats: pd.DataFrame, train_feats: pd.DataFrame, cfg: Layer13Config) -> pd.DataFrame:
    """Fit ML model on training data and calculate residuals on full feats"""
    # Fit model on training data only (to prevent leakage)
    X_train = train_feats[["team_power", "opp_power", "power_diff", "age_gap", "cross_gender"]].astype(float).values
    y_train = train_feats["goal_margin"].astype(float).values
    
    if _HAS_XGB:
        model = XGBRegressor(**cfg.xgb_params)
        model.fit(X_train, y_train)
    else:
        model = RandomForestRegressor(**cfg.rf_params)
        model.fit(X_train, y_train)
    
    # Compute residuals on full feats DataFrame (for all games)
    X_full = feats[["team_power", "opp_power", "power_diff", "age_gap", "cross_gender"]].astype(float).values
    y_pred = model.predict(X_full)
    
    out = feats.copy()
    out["pred_margin"] = y_pred.astype(float)
    out["residual"] = (out["goal_margin"] - out["pred_margin"]).astype(float)
    
    return out


def _aggregate_team_residuals(feats: pd.DataFrame, cfg: Layer13Config) -> pd.DataFrame:
    """Aggregate residuals per team with recency weighting"""
    df = feats.copy()
    df["recency_w"] = np.exp(-cfg.recency_decay_lambda * (df["rank_recency"].astype(float) - 1.0))

    # Get team_id and age/gender columns (v53e format uses team_id, age, gender)
    team_id_col = 'team_id' if 'team_id' in df.columns else ('team_id_master' if 'team_id_master' in df.columns else cfg.team_id_col)
    age_col = 'age' if 'age' in df.columns else cfg.age_col
    gender_col = 'gender' if 'gender' in df.columns else cfg.gender_col

    # Compute weighted average per group (avoiding deprecated .apply pattern)
    def compute_group_wavg(group_df):
        w = group_df["recency_w"].values
        s = float(w.sum())
        if s <= 0:
            return 0.0
        return float(np.average(group_df["residual"].values, weights=w))

    # Use pd.concat + list comprehension (pandas 3.0 compat: groupby().apply() drops group keys)
    agg = pd.concat([
        pd.DataFrame({
            team_id_col: [grp[team_id_col].iloc[0]],
            age_col: [grp[age_col].iloc[0]],
            gender_col: [grp[gender_col].iloc[0]],
            "ml_overperf": [compute_group_wavg(grp)]
        })
        for _, grp in df.groupby([team_id_col, age_col, gender_col])
    ]).reset_index(drop=True)
    
    # require a minimum number of games to avoid yo-yo
    counts = df.groupby([team_id_col, age_col, gender_col], as_index=False)["residual"].count() \
               .rename(columns={"residual": "game_count"})
    merged = agg.merge(counts, on=[team_id_col, age_col, gender_col], how="left")
    merged.loc[merged["game_count"] < cfg.min_team_games_for_residual, "ml_overperf"] = 0.0
    
    # Ensure team_id column name for merging (v53e uses 'team_id')
    if team_id_col != 'team_id':
        merged = merged.rename(columns={team_id_col: 'team_id'})
    
    return merged[["team_id", "age", "gender", "ml_overperf"]]


def _normalize_by_cohort(
    df: pd.DataFrame,
    *,
    value_col: str,
    out_col: str,
    mode: str,
    cohort_cols: List[str],
) -> pd.DataFrame:
    """Normalize values within cohorts (age, gender)"""
    parts = []
    for _, grp in df.groupby(cohort_cols, dropna=False):
        g = grp.copy()
        s = g[value_col].astype(float)
        if mode == "zscore":
            sd = s.std(ddof=0)
            if sd == 0 or len(s) < 2:
                g[out_col] = 0.5
            else:
                z = (s - s.mean()) / sd
                g[out_col] = 1.0 / (1.0 + np.exp(-z))  # sigmoid
        else:
            g[out_col] = s.rank(method="average", pct=True).astype(float) if len(s) else 0.5
        parts.append(g)
    return pd.concat(parts, axis=0)

