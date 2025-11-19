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
    recency_decay_lambda: float = 0.06     # exp(-lambda * (recency-1))
    min_team_games_for_residual: int = 6
    residual_clip_goals: float = 3.5       # guardrail on residual outliers
    
    # blend into PowerScore
    alpha: float = 0.12                    # 0.05–0.20 recommended
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
# Game residual extraction
# ----------------------------
def _extract_game_residuals(feats: pd.DataFrame, games_df: pd.DataFrame, cfg: Layer13Config) -> pd.DataFrame:
    """
    Extract per-game residuals from feats DataFrame and map to original game IDs.

    Since v53e format duplicates each game (home and away perspective), we filter to
    home team perspective only to get one residual per game.

    The residual represents the home team's perspective (positive = home outperformed).
    For display, the frontend should interpret this from each team's viewpoint.

    Returns DataFrame with columns: game_id (UUID), ml_overperformance (float)
    """
    import logging
    logger = logging.getLogger(__name__)

    print(f"[DEBUG _extract_game_residuals] Input feats: {len(feats)} rows, columns: {list(feats.columns)}")
    logger.info(f"[_extract_game_residuals] Input feats: {len(feats)} rows, columns: {list(feats.columns)}")

    if feats.empty or 'residual' not in feats.columns:
        print(f"[DEBUG _extract_game_residuals] ❌ Feats empty or missing 'residual' column")
        logger.warning(f"[_extract_game_residuals] Feats empty or missing 'residual' column")
        return pd.DataFrame(columns=['game_id', 'ml_overperformance'])

    # Check if v53e format has the required fields (id, team_id, home_team_master_id)
    required_cols = {'id', 'team_id', 'home_team_master_id', 'residual'}
    if not required_cols.issubset(feats.columns):
        missing = required_cols - set(feats.columns)
        print(f"[DEBUG _extract_game_residuals] ❌ Missing required columns: {missing}")
        logger.warning(f"[_extract_game_residuals] Missing required columns: {missing}")
        return pd.DataFrame(columns=['game_id', 'ml_overperformance'])

    # Filter to home team perspective only (where team_id == home_team_master_id)
    home_perspective = feats[feats['team_id'] == feats['home_team_master_id']].copy()
    print(f"[DEBUG _extract_game_residuals] Home perspective after filter: {len(home_perspective)} rows")
    logger.info(f"[_extract_game_residuals] Home perspective: {len(home_perspective)} rows")

    if home_perspective.empty:
        print(f"[DEBUG _extract_game_residuals] ❌ Home perspective is empty after filtering")
        logger.warning(f"[_extract_game_residuals] Home perspective is empty after filtering")
        return pd.DataFrame(columns=['game_id', 'ml_overperformance'])

    # Extract game_id (UUID) and residual
    result_df = home_perspective[['id', 'residual']].copy()
    result_df = result_df.rename(columns={'id': 'game_id', 'residual': 'ml_overperformance'})

    # Ensure game_id is string UUID
    result_df['game_id'] = result_df['game_id'].astype(str)
    result_df['ml_overperformance'] = result_df['ml_overperformance'].astype(float)

    # Remove duplicates (shouldn't happen, but safety check)
    result_df = result_df.drop_duplicates(subset=['game_id'], keep='first')

    print(f"[DEBUG _extract_game_residuals] ✅ Extracted {len(result_df)} game residuals")
    logger.info(f"[_extract_game_residuals] Extracted {len(result_df)} game residuals")

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

    print(f"[DEBUG apply_predictive_adjustment] START - games_used_df: {len(games_used_df) if games_used_df is not None else 'None'} rows")
    print(f"[DEBUG apply_predictive_adjustment] Config enabled: {cfg.enabled}")

    if not cfg.enabled or out.empty:
        # ensure columns exist for downstream consumers
        out["ml_overperf"] = 0.0
        out["ml_norm"] = 0.0
        out["powerscore_ml"] = out.get("powerscore_adj", out.get("powerscore_core", 0.0))
        # Clamp PowerScore within [0.0, 1.0] to preserve normalization bounds
        out["powerscore_ml"] = out["powerscore_ml"].clip(0.0, 1.0)
        out["rank_in_cohort_ml"] = (
            out.groupby(list(cfg.cohort_key_cols))["powerscore_ml"]
               .rank(ascending=False, method="min")
        ).astype(int)
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

    print(f"[DEBUG apply_predictive_adjustment] games_df columns: {list(games_df.columns)}")
    print(f"[DEBUG apply_predictive_adjustment] games_df has 'id': {'id' in games_df.columns}")
    print(f"[DEBUG apply_predictive_adjustment] games_df has 'home_team_master_id': {'home_team_master_id' in games_df.columns}")

    # Ensure required columns exist
    required = {
        cfg.date_col, cfg.team_id_col, cfg.opp_id_col, cfg.gf_col, cfg.ga_col,
        cfg.age_col, cfg.gender_col, cfg.opp_age_col, cfg.opp_gender_col
    }
    missing = required - set(games_df.columns)
    if missing:
        print(f"[DEBUG apply_predictive_adjustment] ❌ EARLY EXIT - Missing required columns: {missing}")
        # If we can't train, return pass-through
        out["ml_overperf"] = 0.0
        out["ml_norm"] = 0.0
        out["powerscore_ml"] = out.get("powerscore_adj", out.get("powerscore_core", 0.0))
        # Clamp PowerScore within [0.0, 1.0] to preserve normalization bounds
        out["powerscore_ml"] = out["powerscore_ml"].clip(0.0, 1.0)
        out["rank_in_cohort_ml"] = (
            out.groupby(list(cfg.cohort_key_cols))["powerscore_ml"]
               .rank(ascending=False, method="min")
        ).astype(int)
        if return_game_residuals:
            return out, pd.DataFrame(columns=['game_id', 'residual'])
        return out
    
    # 2) Build feature matrix from games + current powers
    base_power_col = "powerscore_adj" if "powerscore_adj" in out.columns else "powerscore_core"
    power_map = dict(zip(out["team_id"], out[base_power_col].astype(float)))
    feats = _build_features(games_df, power_map, cfg)
    
    if feats.empty:
        out["ml_overperf"] = 0.0
        out["ml_norm"] = 0.0
        out["powerscore_ml"] = out[base_power_col]
        # Clamp PowerScore within [0.0, 1.0] to preserve normalization bounds
        out["powerscore_ml"] = out["powerscore_ml"].clip(0.0, 1.0)
        out["rank_in_cohort_ml"] = (
            out.groupby(list(cfg.cohort_key_cols))["powerscore_ml"]
               .rank(ascending=False, method="min")
        ).astype(int)
        if return_game_residuals:
            return out, pd.DataFrame(columns=['game_id', 'residual'])
        return out
    
    # 3) Fit model and compute residuals (with ML leakage protection)
    # 30-day time-based split to prevent leakage
    if "date" in feats.columns and len(feats) > 0:
        cutoff_date = feats["date"].max() - pd.Timedelta(days=30)
        train_feats = feats[feats["date"] < cutoff_date].copy()
        
        # Fall back to full feats if no training data
        if train_feats.empty or len(train_feats) < 10:
            train_feats = feats.copy()
    else:
        # No date column or empty feats - use full feats
        train_feats = feats.copy()
    
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
    out["powerscore_ml"] = out[base_power_col] + cfg.alpha * out["ml_norm"]
    # Clamp PowerScore within [0.0, 1.0] to preserve normalization bounds
    out["powerscore_ml"] = out["powerscore_ml"].clip(0.0, 1.0)
    out["rank_in_cohort_ml"] = (
        out.groupby(list(cfg.cohort_key_cols))["powerscore_ml"]
           .rank(ascending=False, method="min")
    ).astype(int)

    # 7) Extract per-game residuals if requested
    if return_game_residuals:
        game_residuals = _extract_game_residuals(feats, games_df, cfg)
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
def _build_features(games: pd.DataFrame, power_map: Dict[str, float], cfg: Layer13Config) -> pd.DataFrame:
    """Build feature matrix for ML model"""
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
    f["team_power"] = f[team_id_col].astype(str).map(lambda t: power_map.get(str(t), 0.5))
    f["opp_power"] = f[opp_id_col].astype(str).map(lambda t: power_map.get(str(t), 0.5))
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
    print(f"[DEBUG _build_features] Input columns: {list(f.columns)}")
    print(f"[DEBUG _build_features] Has 'id': {'id' in f.columns}, Has 'home_team_master_id': {'home_team_master_id' in f.columns}")
    logger.info(f"[_build_features] Input columns: {list(f.columns)}")
    logger.info(f"[_build_features] Needed columns: {needed}")
    logger.info(f"[_build_features] Has 'id': {'id' in f.columns}, Has 'home_team_master_id': {'home_team_master_id' in f.columns}")

    # Only keep columns that exist
    needed = [col for col in needed if col in f.columns]
    f = f[needed].dropna(subset=["goal_margin", "team_power", "opp_power"])

    print(f"[DEBUG _build_features] Output columns: {list(f.columns)}, rows: {len(f)}")
    logger.info(f"[_build_features] Output columns: {list(f.columns)}, rows: {len(f)}")

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
    
    def _wavg(d: pd.DataFrame) -> float:
        w = d["recency_w"].values
        s = float(w.sum())
        if s <= 0:
            return 0.0
        return float(np.average(d["residual"].values, weights=w))
    
    # Get team_id and age/gender columns (v53e format uses team_id, age, gender)
    team_id_col = 'team_id' if 'team_id' in df.columns else ('team_id_master' if 'team_id_master' in df.columns else cfg.team_id_col)
    age_col = 'age' if 'age' in df.columns else cfg.age_col
    gender_col = 'gender' if 'gender' in df.columns else cfg.gender_col
    
    agg = (
        df.groupby([team_id_col, age_col, gender_col], as_index=False)
          .apply(lambda d: pd.Series({"ml_overperf": _wavg(d)}))
          .reset_index(drop=True)
    )
    
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

