"""PitchRank Configuration Settings - Scalable Version"""
from pathlib import Path
from dotenv import load_dotenv
import os
from datetime import datetime

# Load environment variables
load_dotenv()

# Project Info
PROJECT_NAME = "PitchRank"
VERSION = "2.0.2-queue-fix"

# Build identification
BUILD_ID = datetime.now().strftime("%Y%m%d_%H%M%S")

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
SAMPLES_DIR = DATA_DIR / "samples"
MAPPINGS_DIR = DATA_DIR / "mappings"
CACHE_DIR = DATA_DIR / "cache"

# Create directories
for dir_path in [RAW_DATA_DIR, PROCESSED_DATA_DIR, SAMPLES_DIR, MAPPINGS_DIR, CACHE_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# Database
# Environment detection: local vs production
USE_LOCAL_SUPABASE = os.getenv("USE_LOCAL_SUPABASE", "false").lower() == "true"

if USE_LOCAL_SUPABASE:
    # Local Supabase instance (for development/testing)
    SUPABASE_URL = os.getenv("SUPABASE_URL", "http://localhost:54321")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
else:
    # Production Supabase instance
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Providers
PROVIDERS = {
    'gotsport': {
        'code': 'gotsport',
        'name': 'GotSport',
        'base_url': 'https://www.gotsport.com',
        'adapter': 'src.scrapers.gotsport'
    },
    'tgs': {
        'code': 'tgs',
        'name': 'Total Global Sports',
        'base_url': 'https://www.totalglobalsports.com',
        'adapter': 'src.scrapers.tgs'
    },
    'usclub': {
        'code': 'usclub',
        'name': 'US Club Soccer',
        'base_url': 'https://www.usclubsoccer.org',
        'adapter': 'src.scrapers.usclub'
    },
    'sincsports': {
        'code': 'sincsports',
        'name': 'SincSports',
        'base_url': 'https://soccer.sincsports.com',
        'adapter': 'src.scrapers.sincsports'
    },
    'athleteone': {
        'code': 'athleteone',
        'name': 'AthleteOne / TGS',
        'base_url': 'https://api.athleteone.com',
        'adapter': 'src.scrapers.athleteone'
    }
}

# Age Groups with metadata
# NOTE: anchor_score values are aligned with v53e.py AGE_TO_ANCHOR mapping
# These provide linear progression from U10 (0.40) to U18 (1.00)
AGE_GROUPS = {
    'u10': {'birth_year': 2016, 'anchor_score': 0.400},
    'u11': {'birth_year': 2015, 'anchor_score': 0.475},
    'u12': {'birth_year': 2014, 'anchor_score': 0.550},
    'u13': {'birth_year': 2013, 'anchor_score': 0.625},
    'u14': {'birth_year': 2012, 'anchor_score': 0.700},
    'u15': {'birth_year': 2011, 'anchor_score': 0.775},
    'u16': {'birth_year': 2010, 'anchor_score': 0.850},
    'u17': {'birth_year': 2009, 'anchor_score': 0.925},
    'u18': {'birth_year': 2008, 'anchor_score': 1.000}
}

# Ranking Configuration (aligned with v53e V53EConfig)
RANKING_CONFIG = {
    # Layer 1
    'window_days': int(os.getenv("RANKING_WINDOW_DAYS", 365)),  # V53EConfig.WINDOW_DAYS
    'inactive_hide_days': int(os.getenv("INACTIVE_HIDE_DAYS", 180)),  # V53EConfig.INACTIVE_HIDE_DAYS
    
    # Layer 2
    'max_games': int(os.getenv("MAX_GAMES_PER_TEAM", 30)),  # V53EConfig.MAX_GAMES_FOR_RANK
    'goal_diff_cap': int(os.getenv("GOAL_DIFF_CAP", 6)),  # V53EConfig.GOAL_DIFF_CAP
    'outlier_guard_zscore': float(os.getenv("OUTLIER_GUARD_ZSCORE", 2.5)),  # V53EConfig.OUTLIER_GUARD_ZSCORE
    
    # Layer 3 (recency)
    'recent_k': int(os.getenv("RECENT_K", 15)),  # V53EConfig.RECENT_K
    'recent_share': float(os.getenv("RECENT_SHARE", 0.65)),  # V53EConfig.RECENT_SHARE
    'dampen_tail_start': int(os.getenv("DAMPEN_TAIL_START", 26)),  # V53EConfig.DAMPEN_TAIL_START
    'dampen_tail_end': int(os.getenv("DAMPEN_TAIL_END", 30)),  # V53EConfig.DAMPEN_TAIL_END
    'dampen_tail_start_weight': float(os.getenv("DAMPEN_TAIL_START_WEIGHT", 0.8)),  # V53EConfig.DAMPEN_TAIL_START_WEIGHT
    'dampen_tail_end_weight': float(os.getenv("DAMPEN_TAIL_END_WEIGHT", 0.4)),  # V53EConfig.DAMPEN_TAIL_END_WEIGHT
    
    # Layer 4 (defense ridge)
    'ridge_ga': float(os.getenv("RIDGE_GA", 0.25)),  # V53EConfig.RIDGE_GA
    
    # Layer 5 (Adaptive K)
    'adaptive_k_alpha': float(os.getenv("ADAPTIVE_K_ALPHA", 0.5)),  # V53EConfig.ADAPTIVE_K_ALPHA
    'adaptive_k_beta': float(os.getenv("ADAPTIVE_K_BETA", 0.6)),  # V53EConfig.ADAPTIVE_K_BETA
    'team_outlier_guard_zscore': float(os.getenv("TEAM_OUTLIER_GUARD_ZSCORE", 2.5)),  # V53EConfig.TEAM_OUTLIER_GUARD_ZSCORE
    
    # Layer 6 (Performance)
    'performance_k': float(os.getenv("PERFORMANCE_K", 0.15)),  # V53EConfig.PERFORMANCE_K (legacy, use perf_* instead)
    'perf_game_scale': float(os.getenv("PERF_GAME_SCALE", 0.15)),  # V53EConfig.PERF_GAME_SCALE - scales per-game residual
    'perf_blend_weight': float(os.getenv("PERF_BLEND_WEIGHT", 0.15)),  # V53EConfig.PERF_BLEND_WEIGHT - weight in powerscore
    'performance_decay_rate': float(os.getenv("PERFORMANCE_DECAY_RATE", 0.08)),  # V53EConfig.PERFORMANCE_DECAY_RATE
    'performance_threshold': float(os.getenv("PERFORMANCE_THRESHOLD", 2.0)),  # V53EConfig.PERFORMANCE_THRESHOLD
    'performance_goal_scale': float(os.getenv("PERFORMANCE_GOAL_SCALE", 5.0)),  # V53EConfig.PERFORMANCE_GOAL_SCALE
    
    # Layer 7 (Bayesian shrink)
    'shrink_tau': float(os.getenv("SHRINK_TAU", 8.0)),  # V53EConfig.SHRINK_TAU
    
    # Layer 8 (SOS)
    'unranked_sos_base': float(os.getenv("UNRANKED_SOS_BASE", 0.35)),  # V53EConfig.UNRANKED_SOS_BASE
    'sos_repeat_cap': int(os.getenv("SOS_REPEAT_CAP", 4)),  # V53EConfig.SOS_REPEAT_CAP
    'sos_iterations': int(os.getenv("SOS_ITERATIONS", 3)),  # V53EConfig.SOS_ITERATIONS
    'sos_transitivity_lambda': float(os.getenv("SOS_TRANSITIVITY_LAMBDA", 0.20)),  # V53EConfig.SOS_TRANSITIVITY_LAMBDA

    # Opponent-adjusted offense/defense (fixes double-counting problem)
    'opponent_adjust_enabled': os.getenv("OPPONENT_ADJUST_ENABLED", "true").lower() in ("true", "1", "yes"),  # V53EConfig.OPPONENT_ADJUST_ENABLED
    'opponent_adjust_baseline': float(os.getenv("OPPONENT_ADJUST_BASELINE", 0.5)),  # V53EConfig.OPPONENT_ADJUST_BASELINE
    'opponent_adjust_clip_min': float(os.getenv("OPPONENT_ADJUST_CLIP_MIN", 0.4)),  # V53EConfig.OPPONENT_ADJUST_CLIP_MIN
    'opponent_adjust_clip_max': float(os.getenv("OPPONENT_ADJUST_CLIP_MAX", 1.6)),  # V53EConfig.OPPONENT_ADJUST_CLIP_MAX

    # Layer 10 weights
    'off_weight': float(os.getenv("OFF_WEIGHT", 0.25)),  # V53EConfig.OFF_WEIGHT
    'def_weight': float(os.getenv("DEF_WEIGHT", 0.25)),  # V53EConfig.DEF_WEIGHT
    'sos_weight': float(os.getenv("SOS_WEIGHT", 0.50)),  # V53EConfig.SOS_WEIGHT
    
    # Provisional
    'min_games_for_ranking': int(os.getenv("MIN_GAMES_FOR_RANKING", 5)),  # V53EConfig.MIN_GAMES_PROVISIONAL
    
    # Context multipliers
    'tournament_ko_mult': float(os.getenv("TOURNAMENT_KO_MULT", 1.10)),  # V53EConfig.TOURNAMENT_KO_MULT
    'semis_finals_mult': float(os.getenv("SEMIS_FINALS_MULT", 1.05)),  # V53EConfig.SEMIS_FINALS_MULT
    
    # Cross-age anchors
    'anchor_percentile': float(os.getenv("ANCHOR_PERCENTILE", 0.98)),  # V53EConfig.ANCHOR_PERCENTILE
    
    # Normalization mode
    'norm_mode': os.getenv("NORM_MODE", "percentile"),  # V53EConfig.NORM_MODE
    
    # Legacy fields (for backward compatibility)
    'recent_games': 15,
    'middle_games': 10,
    'oldest_games': 5,
    'recent_weight': 0.50,
    'middle_weight': 0.35,
    'oldest_weight': 0.15,
    'default_opponent_strength': 0.35,
    'win_points': 1.0,
    'draw_points': 0.35,
    'loss_points': 0.0,
}

# Matching Configuration
MATCHING_CONFIG = {
    'fuzzy_threshold': 0.75,
    'auto_approve_threshold': 0.9,
    'review_threshold': 0.75,
    'max_age_diff': 2,
    'weights': {
        'team': 0.65,
        'club': 0.25,
        'age': 0.05,
        'location': 0.05
    },
    'club_boost_identical': 0.05,
    'club_min_similarity': 0.8
}

# ETL Configuration
ETL_CONFIG = {
    'batch_size': 500,
    'max_retries': 3,
    'retry_delay': 5,
    'incremental_days': 7,
    'validation_enabled': True
}

# ML Layer Configuration (Layer 13)
ML_CONFIG = {
    'enabled': os.getenv("ML_LAYER_ENABLED", "true").lower() == "true",
    'alpha': float(os.getenv("ML_ALPHA", 0.12)),  # Blend weight for ML adjustment
    'recency_decay_lambda': float(os.getenv("ML_RECENCY_DECAY_LAMBDA", 0.06)),
    'min_team_games_for_residual': int(os.getenv("ML_MIN_TEAM_GAMES", 6)),
    'residual_clip_goals': float(os.getenv("ML_RESIDUAL_CLIP", 3.5)),
    'norm_mode': os.getenv("ML_NORM_MODE", "percentile"),  # "percentile" or "zscore"
    'lookback_days': int(os.getenv("ML_LOOKBACK_DAYS", 365)),
    'xgb_params': {
        'n_estimators': int(os.getenv("ML_XGB_N_ESTIMATORS", 220)),
        'max_depth': int(os.getenv("ML_XGB_MAX_DEPTH", 5)),
        'learning_rate': float(os.getenv("ML_XGB_LEARNING_RATE", 0.08)),
        'subsample': float(os.getenv("ML_XGB_SUBSAMPLE", 0.9)),
        'colsample_bytree': float(os.getenv("ML_XGB_COLSAMPLE_BYTREE", 0.9)),
        'reg_lambda': float(os.getenv("ML_XGB_REG_LAMBDA", 1.0)),
        'n_jobs': int(os.getenv("ML_XGB_N_JOBS", -1)),
        'random_state': 42,
    },
    'rf_params': {
        'n_estimators': int(os.getenv("ML_RF_N_ESTIMATORS", 240)),
        'max_depth': int(os.getenv("ML_RF_MAX_DEPTH", 18)),
        'min_samples_leaf': int(os.getenv("ML_RF_MIN_SAMPLES_LEAF", 2)),
        'n_jobs': int(os.getenv("ML_RF_N_JOBS", -1)),
        'random_state': 42,
    },
}

# Data Adapter Configuration (Supabase ↔ v53e mapping)
DATA_ADAPTER_CONFIG = {
    'games_table': 'games',
    'teams_table': 'teams',
    'column_mappings': {
        # Supabase → v53e
        'game_date': 'date',
        'home_team_master_id': 'team_id',  # for home perspective
        'away_team_master_id': 'opp_id',    # for home perspective
        'home_score': 'gf',
        'away_score': 'ga',
        'age_group': 'age',  # converted via age_group_to_age()
        'gender': 'gender',  # kept as-is
    },
    'age_group_conversion': {
        # Maps 'u10' → '10', 'u11' → '11', etc.
        'enabled': True,
    },
    'perspective_based': True,  # Each game appears twice (home/away perspectives)
}

# Cache Configuration
CACHE_CONFIG = {
    'ttl_seconds': 3600,  # 1 hour
    'max_size_mb': 100
}

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Performance flags
USE_CACHE = os.getenv("USE_CACHE", "true").lower() == "true"
PARALLEL_PROCESSING = os.getenv("PARALLEL_PROCESSING", "true").lower() == "true"
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"