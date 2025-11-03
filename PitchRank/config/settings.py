"""PitchRank Configuration Settings - Scalable Version"""
from pathlib import Path
from dotenv import load_dotenv
import os
from datetime import datetime

# Load environment variables
load_dotenv()

# Project Info
PROJECT_NAME = "PitchRank"
VERSION = "2.0.0"

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
    }
}

# Current season
CURRENT_SEASON = {
    'name': 'Spring 2025',
    'code': 'spring2025',
    'start_date': '2025-01-01',
    'end_date': '2025-06-30'
}

# Age Groups with metadata
AGE_GROUPS = {
    'u10': {'birth_year': 2016, 'anchor_score': 0.40},
    'u11': {'birth_year': 2015, 'anchor_score': 0.44},
    'u12': {'birth_year': 2014, 'anchor_score': 0.49},
    'u13': {'birth_year': 2013, 'anchor_score': 0.55},
    'u14': {'birth_year': 2012, 'anchor_score': 0.62},
    'u15': {'birth_year': 2011, 'anchor_score': 0.70},
    'u16': {'birth_year': 2010, 'anchor_score': 0.79},
    'u17': {'birth_year': 2009, 'anchor_score': 0.89},
    'u18': {'birth_year': 2008, 'anchor_score': 1.00}
}

# Ranking Configuration
RANKING_CONFIG = {
    'window_days': int(os.getenv("RANKING_WINDOW_DAYS", 365)),
    'max_games': int(os.getenv("MAX_GAMES_PER_TEAM", 30)),
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
    'min_games_for_ranking': 5
}

# Matching Configuration
MATCHING_CONFIG = {
    'fuzzy_threshold': 0.7,
    'auto_approve_threshold': 0.9,
    'review_threshold': 0.85,
    'max_age_diff': 2
}

# ETL Configuration
ETL_CONFIG = {
    'batch_size': 500,
    'max_retries': 3,
    'retry_delay': 5,
    'incremental_days': 7,
    'validation_enabled': True
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