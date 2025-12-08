"""PitchRank Settings Dashboard - Comprehensive Parameter Viewer"""
import streamlit as st
import pandas as pd
import os
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import time
from supabase import create_client
from config.settings import (
    RANKING_CONFIG,
    ML_CONFIG,
    MATCHING_CONFIG,
    ETL_CONFIG,
    AGE_GROUPS,
    VERSION,
    PROJECT_NAME,
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)

# Page configuration
st.set_page_config(
    page_title=f"{PROJECT_NAME} Settings Dashboard",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Title and version
st.title(f"⚽ {PROJECT_NAME} Settings Dashboard")
st.caption(f"Version {VERSION} | Comprehensive Parameter Viewer")

# Database connection helper
@st.cache_resource
def get_database():
    """Get cached database connection"""
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return None
    try:
        return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    except Exception as e:
        st.error(f"Failed to connect to database: {e}")
        return None


def execute_with_retry(query_func, max_retries=3, base_delay=1.0):
    """
    Execute a database query with exponential backoff retry logic.

    Args:
        query_func: A callable that returns a Supabase query builder with .execute()
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds (doubles each retry)

    Returns:
        The query result on success

    Raises:
        The last exception if all retries fail
    """
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            return query_func().execute()
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
            else:
                raise last_exception

# Sidebar navigation
st.sidebar.title("Navigation")
section = st.sidebar.radio(
    "Select Section",
    [
        "🎯 Ranking Engine & ML",
        "🔍 Matching Configuration",
        "⚙️ ETL & Data Processing",
        "👥 Age Groups",
        "🔧 Environment Variables",
        "🔎 Unknown Teams Mapper",
        "📋 Modular11 Team Review",
        "📈 Database Import Stats",
        "🗺️ State Coverage",
        "🔀 Team Merge Manager"
    ]
)

# Helper function to display parameter table
def display_params_table(params_dict, section_name):
    """Display parameters in a clean table format"""
    if not params_dict:
        st.warning(f"No parameters found for {section_name}")
        return

    df = pd.DataFrame([
        {"Parameter": k, "Value": v}
        for k, v in params_dict.items()
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

# Helper function to create parameter description
def param_info(name, value, description, unit=""):
    """Display parameter with description"""
    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(f"**{name}**")
        st.caption(description)
    with col2:
        if unit:
            st.metric(label="", value=f"{value} {unit}")
        else:
            st.metric(label="", value=value)

# Helper functions for fuzzy matching
def normalize_team_name(name: str) -> str:
    """Normalize team name for comparison"""
    if not name:
        return ''
    import string
    name = name.lower().strip()
    name = name.translate(str.maketrans('', '', string.punctuation))
    return ' '.join(name.split())

def calculate_similarity(str1: str, str2: str) -> float:
    """Calculate string similarity"""
    str1 = normalize_team_name(str1)
    str2 = normalize_team_name(str2)
    if str1 == str2:
        return 1.0
    return SequenceMatcher(None, str1, str2).ratio()

# ============================================================================
# RANKING ENGINE & ML SECTION (Combined)
# ============================================================================
if section == "🎯 Ranking Engine & ML":
    st.header("Ranking Engine & Machine Learning")
    st.markdown("V53E ranking parameters and ML layer configuration")

    # Key metrics overview
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Window Days", RANKING_CONFIG['window_days'])
        st.caption("Game history timeframe")

    with col2:
        st.metric("SOS Transitivity λ", RANKING_CONFIG['sos_transitivity_lambda'])
        st.caption("Opponent of opponent weight")

    with col3:
        st.metric("Recent Share", RANKING_CONFIG['recent_share'])
        st.caption("Weight on recent games")

    with col4:
        st.metric("ML Alpha", ML_CONFIG['alpha'])
        st.caption("ML layer contribution")

    st.divider()

    # Component weights validation
    st.subheader("⚖️ Component Weights")

    off_weight = RANKING_CONFIG['off_weight']
    def_weight = RANKING_CONFIG['def_weight']
    sos_weight = RANKING_CONFIG['sos_weight']
    total_weight = off_weight + def_weight + sos_weight

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Offense", off_weight)
    with col2:
        st.metric("Defense", def_weight)
    with col3:
        st.metric("SOS", sos_weight)
    with col4:
        if abs(total_weight - 1.0) < 0.001:
            st.metric("Total", total_weight, delta="✓ Valid")
        else:
            st.metric("Total", total_weight, delta="⚠️ Should be 1.0")

    st.divider()

    # V53E Ranking Engine Parameters
    st.subheader("🎯 V53E Ranking Engine (24 Parameters)")

    # Layer 1: Time Window & Visibility
    with st.expander("**Layer 1: Time Window & Visibility**", expanded=True):
        param_info(
            "WINDOW_DAYS",
            RANKING_CONFIG['window_days'],
            "Number of days of game history to consider",
            "days"
        )
        param_info(
            "INACTIVE_HIDE_DAYS",
            RANKING_CONFIG['inactive_hide_days'],
            "Hide teams inactive for this many days",
            "days"
        )

    # Layer 2: Game Limits & Outlier Protection
    with st.expander("**Layer 2: Game Limits & Outlier Protection**", expanded=False):
        param_info(
            "MAX_GAMES_FOR_RANK",
            RANKING_CONFIG['max_games'],
            "Maximum games per team to consider",
            "games"
        )
        param_info(
            "GOAL_DIFF_CAP",
            RANKING_CONFIG['goal_diff_cap'],
            "Cap goal differential to prevent blowout bias",
            "goals"
        )
        param_info(
            "OUTLIER_GUARD_ZSCORE",
            RANKING_CONFIG['outlier_guard_zscore'],
            "Z-score threshold for outlier detection",
            "σ"
        )

    # Layer 3: Recency Weighting
    with st.expander("**Layer 3: Recency Weighting**", expanded=False):
        param_info(
            "RECENT_K",
            RANKING_CONFIG['recent_k'],
            "Number of most recent games to emphasize",
            "games"
        )
        param_info(
            "RECENT_SHARE",
            RANKING_CONFIG['recent_share'],
            "Weight given to recent games (vs older games)"
        )
        param_info(
            "DAMPEN_TAIL_START",
            RANKING_CONFIG['dampen_tail_start'],
            "Game number where tail dampening begins",
            "game #"
        )
        param_info(
            "DAMPEN_TAIL_END",
            RANKING_CONFIG['dampen_tail_end'],
            "Game number where tail dampening ends",
            "game #"
        )
        param_info(
            "DAMPEN_TAIL_START_WEIGHT",
            RANKING_CONFIG['dampen_tail_start_weight'],
            "Weight at start of tail dampening"
        )
        param_info(
            "DAMPEN_TAIL_END_WEIGHT",
            RANKING_CONFIG['dampen_tail_end_weight'],
            "Weight at end of tail dampening"
        )

    # Layer 4: Defense Ridge
    with st.expander("**Layer 4: Defense Ridge Regularization**", expanded=False):
        param_info(
            "RIDGE_GA",
            RANKING_CONFIG['ridge_ga'],
            "Ridge penalty for defensive ratings to prevent overfitting"
        )

    # Layer 5: Adaptive K-Factor
    with st.expander("**Layer 5: Adaptive K-Factor**", expanded=False):
        param_info(
            "ADAPTIVE_K_ALPHA",
            RANKING_CONFIG['adaptive_k_alpha'],
            "Alpha parameter for adaptive K calculation"
        )
        param_info(
            "ADAPTIVE_K_BETA",
            RANKING_CONFIG['adaptive_k_beta'],
            "Beta parameter for adaptive K calculation"
        )
        param_info(
            "TEAM_OUTLIER_GUARD_ZSCORE",
            RANKING_CONFIG['team_outlier_guard_zscore'],
            "Z-score threshold for team-level outlier detection",
            "σ"
        )

    # Layer 6: Performance Adjustment
    with st.expander("**Layer 6: Performance Adjustment**", expanded=False):
        param_info(
            "PERFORMANCE_K",
            RANKING_CONFIG['performance_k'],
            "Weight of performance adjustment"
        )
        param_info(
            "PERFORMANCE_DECAY_RATE",
            RANKING_CONFIG['performance_decay_rate'],
            "Decay rate for performance adjustment over time"
        )
        param_info(
            "PERFORMANCE_THRESHOLD",
            RANKING_CONFIG['performance_threshold'],
            "Threshold for significant performance adjustment",
            "σ"
        )
        param_info(
            "PERFORMANCE_GOAL_SCALE",
            RANKING_CONFIG['performance_goal_scale'],
            "Scaling factor for goal-based performance"
        )

    # Layer 7: Bayesian Shrinkage
    with st.expander("**Layer 7: Bayesian Shrinkage**", expanded=False):
        param_info(
            "SHRINK_TAU",
            RANKING_CONFIG['shrink_tau'],
            "Bayesian shrinkage strength. Higher = more conservative estimates"
        )

    # Layer 8: Strength of Schedule (SOS)
    with st.expander("**Layer 8: Strength of Schedule**", expanded=False):
        param_info(
            "UNRANKED_SOS_BASE",
            RANKING_CONFIG['unranked_sos_base'],
            "Base SOS value for unranked opponents"
        )
        param_info(
            "SOS_REPEAT_CAP",
            RANKING_CONFIG['sos_repeat_cap'],
            "Maximum times same opponent counts toward SOS",
            "games"
        )
        param_info(
            "SOS_ITERATIONS",
            RANKING_CONFIG['sos_iterations'],
            "Number of SOS calculation iterations",
            "iterations"
        )
        param_info(
            "SOS_TRANSITIVITY_LAMBDA",
            RANKING_CONFIG['sos_transitivity_lambda'],
            "Transitivity weight: 0.20 = 80% direct + 20% indirect opponents"
        )

    # Layer 9: Opponent Adjustment
    with st.expander("**Layer 9: Opponent-Adjusted Offense/Defense**", expanded=False):
        param_info(
            "OPPONENT_ADJUST_ENABLED",
            RANKING_CONFIG['opponent_adjust_enabled'],
            "Enable opponent-adjusted offense/defense to prevent double-counting"
        )
        param_info(
            "OPPONENT_ADJUST_BASELINE",
            RANKING_CONFIG['opponent_adjust_baseline'],
            "Baseline opponent strength for adjustments"
        )
        param_info(
            "OPPONENT_ADJUST_CLIP_MIN",
            RANKING_CONFIG['opponent_adjust_clip_min'],
            "Minimum clip value for opponent adjustment"
        )
        param_info(
            "OPPONENT_ADJUST_CLIP_MAX",
            RANKING_CONFIG['opponent_adjust_clip_max'],
            "Maximum clip value for opponent adjustment"
        )

    # Layer 10: Component Weights
    with st.expander("**Layer 10: Component Weights**", expanded=False):
        st.markdown("These weights combine offense, defense, and SOS into final power score.")

        param_info(
            "OFF_WEIGHT",
            RANKING_CONFIG['off_weight'],
            "Weight for offensive component"
        )
        param_info(
            "DEF_WEIGHT",
            RANKING_CONFIG['def_weight'],
            "Weight for defensive component"
        )
        param_info(
            "SOS_WEIGHT",
            RANKING_CONFIG['sos_weight'],
            "Weight for strength of schedule component"
        )

        total = RANKING_CONFIG['off_weight'] + RANKING_CONFIG['def_weight'] + RANKING_CONFIG['sos_weight']
        if abs(total - 1.0) < 0.001:
            st.success(f"✓ Weights sum to {total:.3f}")
        else:
            st.error(f"⚠️ Weights sum to {total:.3f} (should be 1.0)")

    # Additional Parameters
    with st.expander("**Additional Parameters**", expanded=False):
        param_info(
            "MIN_GAMES_FOR_RANKING",
            RANKING_CONFIG['min_games_for_ranking'],
            "Minimum games required for ranking (provisional otherwise)",
            "games"
        )
        param_info(
            "TOURNAMENT_KO_MULT",
            RANKING_CONFIG['tournament_ko_mult'],
            "Multiplier for knockout tournament games"
        )
        param_info(
            "SEMIS_FINALS_MULT",
            RANKING_CONFIG['semis_finals_mult'],
            "Multiplier for semifinals and finals"
        )
        param_info(
            "ANCHOR_PERCENTILE",
            RANKING_CONFIG['anchor_percentile'],
            "Percentile for cross-age group anchoring"
        )
        param_info(
            "NORM_MODE",
            RANKING_CONFIG['norm_mode'],
            "Normalization mode: 'percentile' or 'zscore'"
        )

    # ML Layer Section (Layer 13)
    st.divider()
    st.subheader("🤖 Machine Learning Layer (Layer 13)")

    # ML Layer Status
    col1, col2 = st.columns(2)
    with col1:
        if ML_CONFIG['enabled']:
            st.success("✓ ML Layer Enabled")
        else:
            st.warning("⚠️ ML Layer Disabled")
    with col2:
        st.metric("ML Alpha (Blend Weight)", ML_CONFIG['alpha'])

    # Core ML Parameters in expander
    with st.expander("**Core ML Parameters**", expanded=False):
        param_info(
            "ML_ALPHA",
            ML_CONFIG['alpha'],
            "Blend weight for ML adjustment: 0 = no ML, 1 = full ML"
        )
        param_info(
            "RECENCY_DECAY_LAMBDA",
            ML_CONFIG['recency_decay_lambda'],
            "Exponential decay rate for game recency"
        )
        param_info(
            "MIN_TEAM_GAMES_FOR_RESIDUAL",
            ML_CONFIG['min_team_games_for_residual'],
            "Minimum games required to calculate game residuals",
            "games"
        )
        param_info(
            "RESIDUAL_CLIP_GOALS",
            ML_CONFIG['residual_clip_goals'],
            "Clip residuals to prevent extreme outlier influence",
            "goals"
        )
        param_info(
            "NORM_MODE",
            ML_CONFIG['norm_mode'],
            "Normalization mode for ML features"
        )
        param_info(
            "LOOKBACK_DAYS",
            ML_CONFIG['lookback_days'],
            "Historical data window for ML training",
            "days"
        )

    # XGBoost Parameters in expander
    with st.expander("**XGBoost Hyperparameters**", expanded=False):
        xgb_df = pd.DataFrame([
            {"Parameter": k, "Value": v}
            for k, v in ML_CONFIG['xgb_params'].items()
        ])
        st.dataframe(xgb_df, use_container_width=True, hide_index=True)

    # Random Forest Parameters in expander
    with st.expander("**Random Forest Hyperparameters**", expanded=False):
        rf_df = pd.DataFrame([
            {"Parameter": k, "Value": v}
            for k, v in ML_CONFIG['rf_params'].items()
        ])
        st.dataframe(rf_df, use_container_width=True, hide_index=True)

# ============================================================================
# MATCHING CONFIGURATION SECTION
# ============================================================================
elif section == "🔍 Matching Configuration":
    st.header("Team Name Fuzzy Matching")
    st.markdown("Configuration for team name matching and deduplication")

    # Threshold visualization
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Auto-Approve Threshold",
            MATCHING_CONFIG['auto_approve_threshold'],
        )
        st.caption("≥ 0.9: Automatic match")

    with col2:
        st.metric(
            "Review Threshold",
            MATCHING_CONFIG['review_threshold'],
        )
        st.caption("0.75-0.9: Manual review")

    with col3:
        st.metric(
            "Fuzzy Threshold",
            MATCHING_CONFIG['fuzzy_threshold'],
        )
        st.caption("< 0.75: Reject")

    st.divider()

    # Component weights
    st.subheader("Component Weights")
    weights = MATCHING_CONFIG['weights']

    weights_df = pd.DataFrame([
        {"Component": k.title(), "Weight": v}
        for k, v in weights.items()
    ])

    col1, col2 = st.columns([2, 1])
    with col1:
        st.dataframe(weights_df, use_container_width=True, hide_index=True)
    with col2:
        total_weight = sum(weights.values())
        if abs(total_weight - 1.0) < 0.001:
            st.success(f"✓ Total: {total_weight:.3f}")
        else:
            st.error(f"⚠️ Total: {total_weight:.3f}")

    st.divider()

    # Additional settings
    st.subheader("Additional Settings")

    param_info(
        "MAX_AGE_DIFF",
        MATCHING_CONFIG['max_age_diff'],
        "Maximum age group difference for matching",
        "years"
    )
    param_info(
        "CLUB_BOOST_IDENTICAL",
        MATCHING_CONFIG['club_boost_identical'],
        "Score boost when club names match exactly"
    )
    param_info(
        "CLUB_MIN_SIMILARITY",
        MATCHING_CONFIG['club_min_similarity'],
        "Minimum club name similarity to apply boost"
    )

# ============================================================================
# ETL & DATA PROCESSING SECTION
# ============================================================================
elif section == "⚙️ ETL & Data Processing":
    st.header("ETL & Data Processing")
    st.markdown("Batch processing, caching, and data pipeline settings")

    # ETL Configuration
    st.subheader("ETL Configuration")

    param_info(
        "BATCH_SIZE",
        ETL_CONFIG['batch_size'],
        "Number of records processed per batch",
        "records"
    )
    param_info(
        "MAX_RETRIES",
        ETL_CONFIG['max_retries'],
        "Maximum retry attempts for failed operations",
        "retries"
    )
    param_info(
        "RETRY_DELAY",
        ETL_CONFIG['retry_delay'],
        "Delay between retry attempts",
        "seconds"
    )
    param_info(
        "INCREMENTAL_DAYS",
        ETL_CONFIG['incremental_days'],
        "Days to look back for incremental updates",
        "days"
    )
    param_info(
        "VALIDATION_ENABLED",
        ETL_CONFIG['validation_enabled'],
        "Enable data validation during ETL"
    )

    st.divider()

    # Import config from settings
    from config.settings import CACHE_CONFIG, USE_CACHE, PARALLEL_PROCESSING, DEBUG_MODE

    st.subheader("Cache Configuration")

    col1, col2 = st.columns(2)
    with col1:
        if USE_CACHE:
            st.success("✓ Cache Enabled")
        else:
            st.warning("⚠️ Cache Disabled")
    with col2:
        st.metric("TTL", f"{CACHE_CONFIG['ttl_seconds']} sec")

    param_info(
        "MAX_CACHE_SIZE",
        CACHE_CONFIG['max_size_mb'],
        "Maximum cache size",
        "MB"
    )

    st.divider()

    # Performance Flags
    st.subheader("Performance Flags")

    col1, col2 = st.columns(2)
    with col1:
        if PARALLEL_PROCESSING:
            st.success("✓ Parallel Processing Enabled")
        else:
            st.info("○ Parallel Processing Disabled")
    with col2:
        if DEBUG_MODE:
            st.warning("⚠️ Debug Mode Enabled")
        else:
            st.success("✓ Debug Mode Disabled")

# ============================================================================
# AGE GROUPS SECTION
# ============================================================================
elif section == "👥 Age Groups":
    st.header("Age Groups Configuration")
    st.markdown("Birth years and anchor scores for cross-age normalization")

    # Age groups table
    age_df = pd.DataFrame([
        {
            "Age Group": age.upper(),
            "Birth Year": data['birth_year'],
            "Anchor Score": data['anchor_score']
        }
        for age, data in AGE_GROUPS.items()
    ])

    col1, col2 = st.columns([2, 3])

    with col1:
        st.dataframe(age_df, use_container_width=True, hide_index=True)

    with col2:
        st.subheader("Anchor Score Progression")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(
            [data['birth_year'] for data in AGE_GROUPS.values()],
            [data['anchor_score'] for data in AGE_GROUPS.values()],
            marker='o',
            linewidth=2,
            markersize=8,
            color='#1f77b4'
        )
        ax.set_xlabel('Birth Year', fontsize=12)
        ax.set_ylabel('Anchor Score', fontsize=12)
        ax.set_title('Cross-Age Normalization Curve', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.invert_xaxis()  # Older birth years on the right

        st.pyplot(fig)

    st.divider()

    st.info("""
    **How Anchor Scores Work:**

    Anchor scores normalize team strengths across different age groups, allowing fair comparisons.

    - **U10 (0.40)**: Youngest age group, lowest anchor
    - **U18 (1.00)**: Oldest age group, highest anchor (reference)
    - Teams are scaled relative to these anchors using percentile matching
    - Higher anchor = higher expected team strength for that age
    """)

# ============================================================================
# ENVIRONMENT VARIABLES SECTION
# ============================================================================
elif section == "🔧 Environment Variables":
    st.header("Environment Variables Reference")
    st.markdown("Complete list of configurable environment variables")

    st.info("""
    Set these in your `.env` file or export them in your shell:
    ```bash
    export VARIABLE_NAME=value
    ```
    """)

    # Ranking Engine Variables
    with st.expander("**Ranking Engine Variables**", expanded=True):
        env_vars = [
            ("RANKING_WINDOW_DAYS", RANKING_CONFIG['window_days'], "Time window for game history"),
            ("INACTIVE_HIDE_DAYS", RANKING_CONFIG['inactive_hide_days'], "Days before hiding inactive teams"),
            ("MAX_GAMES_PER_TEAM", RANKING_CONFIG['max_games'], "Maximum games per team"),
            ("GOAL_DIFF_CAP", RANKING_CONFIG['goal_diff_cap'], "Goal differential cap"),
            ("OUTLIER_GUARD_ZSCORE", RANKING_CONFIG['outlier_guard_zscore'], "Outlier detection threshold"),
            ("RECENT_K", RANKING_CONFIG['recent_k'], "Number of recent games"),
            ("RECENT_SHARE", RANKING_CONFIG['recent_share'], "Weight for recent games"),
            ("RIDGE_GA", RANKING_CONFIG['ridge_ga'], "Defense ridge penalty"),
            ("ADAPTIVE_K_ALPHA", RANKING_CONFIG['adaptive_k_alpha'], "Adaptive K alpha"),
            ("ADAPTIVE_K_BETA", RANKING_CONFIG['adaptive_k_beta'], "Adaptive K beta"),
            ("PERFORMANCE_K", RANKING_CONFIG['performance_k'], "Performance adjustment weight"),
            ("SHRINK_TAU", RANKING_CONFIG['shrink_tau'], "Bayesian shrinkage strength"),
            ("SOS_ITERATIONS", RANKING_CONFIG['sos_iterations'], "SOS calculation iterations"),
            ("SOS_TRANSITIVITY_LAMBDA", RANKING_CONFIG['sos_transitivity_lambda'], "SOS transitivity weight"),
            ("OFF_WEIGHT", RANKING_CONFIG['off_weight'], "Offense component weight"),
            ("DEF_WEIGHT", RANKING_CONFIG['def_weight'], "Defense component weight"),
            ("SOS_WEIGHT", RANKING_CONFIG['sos_weight'], "SOS component weight"),
        ]

        env_df = pd.DataFrame(env_vars, columns=["Variable", "Current Value", "Description"])
        st.dataframe(env_df, use_container_width=True, hide_index=True)

    # ML Variables
    with st.expander("**Machine Learning Variables**", expanded=False):
        ml_vars = [
            ("ML_LAYER_ENABLED", ML_CONFIG['enabled'], "Enable/disable ML layer"),
            ("ML_ALPHA", ML_CONFIG['alpha'], "ML blend weight"),
            ("ML_RECENCY_DECAY_LAMBDA", ML_CONFIG['recency_decay_lambda'], "Recency decay rate"),
            ("ML_MIN_TEAM_GAMES", ML_CONFIG['min_team_games_for_residual'], "Min games for residuals"),
            ("ML_RESIDUAL_CLIP", ML_CONFIG['residual_clip_goals'], "Residual clipping threshold"),
            ("ML_LOOKBACK_DAYS", ML_CONFIG['lookback_days'], "Training data lookback"),
            ("ML_XGB_N_ESTIMATORS", ML_CONFIG['xgb_params']['n_estimators'], "XGBoost trees"),
            ("ML_XGB_MAX_DEPTH", ML_CONFIG['xgb_params']['max_depth'], "XGBoost max depth"),
            ("ML_XGB_LEARNING_RATE", ML_CONFIG['xgb_params']['learning_rate'], "XGBoost learning rate"),
            ("ML_RF_N_ESTIMATORS", ML_CONFIG['rf_params']['n_estimators'], "Random Forest trees"),
            ("ML_RF_MAX_DEPTH", ML_CONFIG['rf_params']['max_depth'], "Random Forest max depth"),
        ]

        ml_df = pd.DataFrame(ml_vars, columns=["Variable", "Current Value", "Description"])
        st.dataframe(ml_df, use_container_width=True, hide_index=True)

    # Example .env file
    with st.expander("**Example .env File**", expanded=False):
        env_example = f"""# PitchRank Configuration
# Copy this to .env and customize

# Ranking Engine
RANKING_WINDOW_DAYS={RANKING_CONFIG['window_days']}
RECENT_SHARE={RANKING_CONFIG['recent_share']}
SOS_TRANSITIVITY_LAMBDA={RANKING_CONFIG['sos_transitivity_lambda']}
SHRINK_TAU={RANKING_CONFIG['shrink_tau']}
OFF_WEIGHT={RANKING_CONFIG['off_weight']}
DEF_WEIGHT={RANKING_CONFIG['def_weight']}
SOS_WEIGHT={RANKING_CONFIG['sos_weight']}

# Machine Learning
ML_LAYER_ENABLED=true
ML_ALPHA={ML_CONFIG['alpha']}
ML_RECENCY_DECAY_LAMBDA={ML_CONFIG['recency_decay_lambda']}

# Database
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
"""
        st.code(env_example, language="bash")

# ============================================================================
# UNKNOWN TEAMS MAPPER SECTION
# ============================================================================
elif section == "🔎 Unknown Teams Mapper":
    st.header("🔎 Unknown Teams Mapper")
    st.markdown("**Simple workflow:** Find unmapped teams → Search for matches → Create mapping")

    db = get_database()

    if not db:
        st.error("Database connection not configured. Please set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in your .env file.")
    else:
        # Step 1: Get list of unmapped provider team IDs
        st.subheader("Step 1: Find Unmapped Teams")

        try:
            # Get games with null master IDs (only use columns that exist in games table)
            # Use retry logic to handle transient connection errors
            null_games = execute_with_retry(
                lambda: db.table('games').select(
                    'home_provider_id, away_provider_id, home_team_master_id, away_team_master_id, '
                    'game_date, provider_id'
                ).or_('home_team_master_id.is.null,away_team_master_id.is.null').order(
                    'game_date', desc=True
                ).limit(500)
            )

            if null_games.data:
                # Extract unique unmapped provider IDs
                unmapped_teams = {}
                for game in null_games.data:
                    if not game.get('home_team_master_id') and game.get('home_provider_id'):
                        pid = str(game['home_provider_id'])
                        if pid not in unmapped_teams:
                            unmapped_teams[pid] = {
                                'provider_id': pid,
                                'provider': game.get('provider_id', ''),
                                'game_count': 0
                            }
                        unmapped_teams[pid]['game_count'] += 1
                    
                    if not game.get('away_team_master_id') and game.get('away_provider_id'):
                        pid = str(game['away_provider_id'])
                        if pid not in unmapped_teams:
                            unmapped_teams[pid] = {
                                'provider_id': pid,
                                'provider': game.get('provider_id', ''),
                                'game_count': 0
                            }
                        unmapped_teams[pid]['game_count'] += 1

                if unmapped_teams:
                    total_games = sum(t['game_count'] for t in unmapped_teams.values())
                    st.info(f"Found **{len(unmapped_teams)}** unmapped teams affecting **{total_games}** games")

                    # Sort by game count
                    sorted_teams = sorted(unmapped_teams.values(), key=lambda x: x['game_count'], reverse=True)
                    
                    # Batch lookup: Get all team names and age groups in a single query
                    # This replaces the N+1 query pattern that caused connection exhaustion
                    provider_ids = [team['provider_id'] for team in sorted_teams]
                    team_lookup_map = {}

                    # Query in batches of 500 to stay within PostgREST limits
                    batch_size = 500
                    for i in range(0, len(provider_ids), batch_size):
                        batch_ids = provider_ids[i:i + batch_size]
                        try:
                            batch_result = execute_with_retry(
                                lambda ids=batch_ids: db.table('teams').select(
                                    'provider_team_id, team_name, age_group'
                                ).in_('provider_team_id', ids)
                            )
                            if batch_result.data:
                                for row in batch_result.data:
                                    pid = str(row.get('provider_team_id', ''))
                                    team_lookup_map[pid] = {
                                        'team_name': row.get('team_name', ''),
                                        'age_group': row.get('age_group', '')
                                    }
                        except Exception as e:
                            st.warning(f"Failed to fetch team details for batch {i//batch_size + 1}: {e}")

                    # Apply lookup results to sorted_teams
                    for team in sorted_teams:
                        if team['provider_id'] in team_lookup_map:
                            team['team_name'] = team_lookup_map[team['provider_id']].get(
                                'team_name', f"ID: {team['provider_id']}"
                            ) or f"ID: {team['provider_id']}"
                            team['age_group'] = team_lookup_map[team['provider_id']].get('age_group', '')
                        else:
                            team['team_name'] = f"ID: {team['provider_id']}"
                            team['age_group'] = ''

                    # Display as table with more info
                    unmapped_df = pd.DataFrame([
                        {
                            'Team Name': t['team_name'],
                            'Provider ID': t['provider_id'],
                            'Age Group': t['age_group'],
                            'Games': t['game_count']
                        }
                        for t in sorted_teams
                    ])
                    st.dataframe(unmapped_df, use_container_width=True, hide_index=True)
                    
                    # Keep sorted_ids for backwards compatibility with Step 2
                    sorted_ids = [(t['provider_id'], t['game_count']) for t in sorted_teams]
                    unmapped_ids = {t['provider_id']: t['game_count'] for t in sorted_teams}

                    st.divider()

                    # Step 2: Select a team to map
                    st.subheader("Step 2: Select Team to Map")
                    st.markdown("*Select an unmapped team from the list above to find a matching master team*")

                    # Add search/filter box
                    search_filter = st.text_input(
                        "🔍 Search by Team Name or ID:",
                        placeholder="Type team name or provider ID...",
                        help="Filter the list below by team name or provider ID"
                    )

                    # Filter the list based on search (now searches team names too)
                    if search_filter:
                        search_lower = search_filter.lower()
                        filtered_teams = [
                            t for t in sorted_teams 
                            if search_lower in str(t['provider_id']).lower() or 
                               search_lower in str(t['team_name']).lower()
                        ]
                        if not filtered_teams:
                            st.warning(f"No teams found matching '{search_filter}'")
                            st.stop()
                    else:
                        filtered_teams = sorted_teams

                    st.caption(f"Showing {len(filtered_teams)} of {len(sorted_teams)} unmapped teams")

                    # Create lookup dict for display
                    team_display = {t['provider_id']: t for t in filtered_teams}
                    
                    selected_provider_id = st.selectbox(
                        "Select team to map:",
                        options=[t['provider_id'] for t in filtered_teams],
                        format_func=lambda x: f"{team_display[x]['team_name']} ({team_display[x]['age_group']}) - {team_display[x]['game_count']} games"
                    )

                    if selected_provider_id:
                        selected_team = team_display[selected_provider_id]
                        
                        st.success(f"**Selected:** {selected_team['team_name']} ({selected_team['age_group']})")
                        st.write(f"Provider ID: `{selected_provider_id}` | Games affected: **{selected_team['game_count']}**")

                        # Try to get more details from teams table
                        team_lookup = db.table('teams').select(
                            'team_name, club_name, age_group, gender, state_code'
                        ).eq('provider_team_id', selected_provider_id).execute()

                        if team_lookup.data and len(team_lookup.data) > 0:
                            team_info = team_lookup.data[0]
                            st.write(f"Club: {team_info.get('club_name', 'N/A')} | State: {team_info.get('state_code', 'N/A')}")
                            search_name_default = team_info['team_name']
                            search_age_default = team_info['age_group']
                            search_gender_default = team_info['gender']
                        else:
                            # Use info from games table
                            search_name_default = selected_team['team_name']
                            search_age_default = selected_team['age_group']
                            search_gender_default = ""

                        st.divider()

                        # Step 3: Search for matches
                        st.subheader("Step 3: Find Master Team Match")

                        col1, col2, col3, col4 = st.columns([2, 2, 1, 1])

                        with col1:
                            search_name = st.text_input(
                                "Team Name to Search",
                                value=search_name_default,
                                placeholder="Enter team name..."
                            )
                        with col2:
                            search_club = st.text_input(
                                "Club Name (optional)",
                                value="",
                                placeholder="Enter club name..."
                            )
                        with col3:
                            age_options = [""] + list(AGE_GROUPS.keys())
                            default_age_idx = age_options.index(search_age_default) if search_age_default in age_options else 0
                            search_age = st.selectbox("Age Group", age_options, index=default_age_idx)
                        with col4:
                            gender_options = ["", "Male", "Female"]
                            default_gender_idx = gender_options.index(search_gender_default) if search_gender_default in gender_options else 0
                            search_gender = st.selectbox("Gender", gender_options, index=default_gender_idx)

                        if st.button("🔍 Search for Matches", type="primary") and (search_name or search_club):
                            with st.spinner("Searching..."):
                                # Build query
                                query = db.table('teams').select('team_id_master, team_name, club_name, age_group, gender, state_code')

                                if search_age:
                                    query = query.eq('age_group', search_age)
                                if search_gender:
                                    query = query.eq('gender', search_gender)

                                result = query.limit(500).execute()

                                if result.data:
                                    # Calculate similarity scores
                                    matches = []
                                    for team in result.data:
                                        # Calculate team name similarity
                                        name_similarity = calculate_similarity(search_name, team['team_name']) if search_name else 0
                                        
                                        # Calculate club name similarity
                                        club_similarity = 0
                                        if search_club and team.get('club_name'):
                                            club_similarity = calculate_similarity(search_club, team['club_name'])
                                        
                                        # Use best of team name or club name match
                                        # If both are provided, weight them
                                        if search_name and search_club:
                                            similarity = max(name_similarity, club_similarity, (name_similarity + club_similarity) / 2)
                                        elif search_club:
                                            similarity = club_similarity
                                        else:
                                            similarity = name_similarity
                                        
                                        if similarity >= 0.3:  # 30%+ similarity
                                            matches.append({
                                                'team_id_master': team['team_id_master'],
                                                'team_name': team['team_name'],
                                                'club_name': team.get('club_name', ''),
                                                'age_group': team['age_group'],
                                                'gender': team['gender'],
                                                'state': team.get('state_code', ''),
                                                'similarity': round(similarity * 100, 1)
                                            })

                                    # Sort by similarity
                                    matches.sort(key=lambda x: x['similarity'], reverse=True)

                                    if matches:
                                        st.success(f"Found {len(matches)} potential matches")

                                        # Display top matches with action buttons
                                        for i, match in enumerate(matches[:10]):  # Show top 10
                                            with st.container():
                                                col1, col2 = st.columns([4, 1])

                                                with col1:
                                                    similarity_color = "green" if match['similarity'] >= 80 else "orange" if match['similarity'] >= 60 else "red"
                                                    st.markdown(f"""
                                                    **{match['team_name']}** ({match['age_group']} {match['gender']})
                                                    Club: {match['club_name'] or 'N/A'} | State: {match['state'] or 'N/A'}
                                                    Match: :{similarity_color}[{match['similarity']}%]
                                                    """)

                                                with col2:
                                                    if st.button("✅ Map This Team", key=f"map_{i}_{match['team_id_master']}"):
                                                        try:
                                                            # Get provider ID
                                                            provider_result = db.table('providers').select('id').eq('code', 'gotsport').single().execute()
                                                            provider_id = provider_result.data['id']

                                                            # Create alias mapping
                                                            db.table('team_alias_map').insert({
                                                                'provider_id': provider_id,
                                                                'provider_team_id': str(selected_provider_id),
                                                                'team_id_master': match['team_id_master'],
                                                                'match_confidence': match['similarity'] / 100,
                                                                'match_method': 'dashboard_manual',
                                                                'review_status': 'approved',
                                                                'created_at': datetime.now().isoformat()
                                                            }).execute()

                                                            st.success(f"✅ Successfully mapped Provider ID {selected_provider_id} to {match['team_name']}!")
                                                            st.balloons()
                                                            st.info("Refresh the page to see updated unmapped teams list")

                                                        except Exception as e:
                                                            st.error(f"Error creating mapping: {e}")

                                                st.divider()
                                    else:
                                        st.warning("No similar teams found. Try adjusting your search criteria.")
                                else:
                                    st.info("No teams found with those criteria.")
                else:
                    st.success("No unmapped provider team IDs found! 🎉")
            else:
                st.success("No games with unmapped teams found! 🎉")

        except Exception as e:
            st.error(f"Error loading unmapped teams: {e}")
            import traceback
            st.code(traceback.format_exc())

        st.divider()

        # Additional section for pending reviews
        st.subheader("📋 Pending Alias Reviews")
        st.markdown("Review and approve/reject aliases that were auto-matched by the system")

        try:
            result = db.table('team_alias_map').select(
                'id, provider_team_id, team_id_master, match_confidence, match_method, review_status, created_at'
            ).eq('review_status', 'pending').order('match_confidence', desc=True).limit(20).execute()

            if result.data:
                st.info(f"Found **{len(result.data)}** aliases pending review")

                for alias in result.data:
                    with st.expander(f"Provider ID: {alias['provider_team_id']} (Confidence: {alias['match_confidence']:.2%})"):
                        # Get team details
                        team_result = db.table('teams').select(
                            'team_name, club_name, age_group, gender, state_code'
                        ).eq('team_id_master', alias['team_id_master']).single().execute()

                        if team_result.data:
                            team = team_result.data

                            col1, col2 = st.columns(2)

                            with col1:
                                st.markdown("**Alias Details**")
                                st.write(f"Provider Team ID: {alias['provider_team_id']}")
                                st.write(f"Match Method: {alias['match_method']}")
                                st.write(f"Confidence: {alias['match_confidence']:.2%}")
                                st.write(f"Created: {alias['created_at'][:10]}")

                            with col2:
                                st.markdown("**Matched Team**")
                                st.write(f"Name: {team['team_name']}")
                                st.write(f"Club: {team.get('club_name', 'N/A')}")
                                st.write(f"Age/Gender: {team['age_group']} {team['gender']}")
                                st.write(f"State: {team.get('state_code', 'N/A')}")

                            # Action buttons
                            col1, col2, col3 = st.columns(3)

                            with col1:
                                if st.button("✅ Approve", key=f"approve_{alias['id']}"):
                                    try:
                                        db.table('team_alias_map').update({
                                            'review_status': 'approved',
                                            'reviewed_by': 'dashboard_user',
                                            'reviewed_at': datetime.now().isoformat()
                                        }).eq('id', alias['id']).execute()
                                        st.success("Approved!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error: {e}")

                            with col2:
                                if st.button("❌ Reject", key=f"reject_{alias['id']}"):
                                    try:
                                        db.table('team_alias_map').update({
                                            'review_status': 'rejected',
                                            'reviewed_by': 'dashboard_user',
                                            'reviewed_at': datetime.now().isoformat()
                                        }).eq('id', alias['id']).execute()
                                        st.success("Rejected!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error: {e}")

                            with col3:
                                if st.button("🆕 New Team", key=f"new_{alias['id']}"):
                                    try:
                                        db.table('team_alias_map').update({
                                            'review_status': 'new_team',
                                            'reviewed_by': 'dashboard_user',
                                            'reviewed_at': datetime.now().isoformat()
                                        }).eq('id', alias['id']).execute()
                                        st.success("Marked as new team!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error: {e}")
            else:
                st.success("No pending aliases to review! 🎉")

        except Exception as e:
            st.error(f"Error loading pending reviews: {e}")

        st.divider()

        # Add New Team Section
        st.subheader("➕ Add New Team")
        st.markdown("Create a brand new team in the database (use this when a team doesn't exist in the master list)")

        with st.expander("📝 Create New Team", expanded=False):
            st.info("Fill in all required fields to add a new team to the database")

            # Show age group -> birth year reference (always visible)
            st.markdown("**📅 Age Group → Birth Year Reference:**")
            ref_data = [[age.upper(), data['birth_year']] for age, data in AGE_GROUPS.items()]
            ref_df = pd.DataFrame(ref_data, columns=['Age Group', 'Birth Year'])
            col1, col2, col3 = st.columns([2, 1, 2])
            with col2:
                st.dataframe(ref_df, use_container_width=True, hide_index=True)
            st.caption("📌 The birth year will be automatically set based on your age group selection when you submit the form")

            # Form for new team
            with st.form("new_team_form"):
                st.markdown("### Required Information")

                col1, col2 = st.columns(2)

                with col1:
                    new_team_name = st.text_input(
                        "Team Name *",
                        placeholder="e.g., Legends FC Premier",
                        help="Full team name"
                    )
                    new_provider_team_id = st.text_input(
                        "Provider Team ID *",
                        placeholder="e.g., 544491",
                        help="The provider's unique ID for this team"
                    )
                    new_age_group = st.selectbox(
                        "Age Group *",
                        options=list(AGE_GROUPS.keys()),
                        help="Team age group (see birth year reference table above)"
                    )

                with col2:
                    new_club_name = st.text_input(
                        "Club Name",
                        placeholder="e.g., Legends FC",
                        help="Parent club/organization (optional)"
                    )
                    new_gender = st.selectbox(
                        "Gender *",
                        options=["Male", "Female"],
                        help="Team gender"
                    )
                    new_state_code = st.text_input(
                        "State Code",
                        placeholder="e.g., CA",
                        max_chars=2,
                        help="2-letter state code (optional)"
                    )

                st.markdown("### Auto-filled Information")
                st.caption("✨ These fields are automatically filled when you create the team")

                col1, col2 = st.columns(2)

                with col1:
                    birth_year_val = AGE_GROUPS.get(new_age_group, {}).get('birth_year', '?')
                    st.success(f"🎂 **Birth Year:** {birth_year_val} (based on {new_age_group.upper() if new_age_group else '?'})")
                    st.caption("See reference table above for all mappings")

                with col2:
                    st.success(f"📊 **Provider:** GotSport")

                # Submit button
                submitted = st.form_submit_button("✅ Create Team", type="primary", use_container_width=True)

                if submitted:
                    # Validate required fields
                    if not new_team_name:
                        st.error("❌ Team Name is required")
                    elif not new_provider_team_id:
                        st.error("❌ Provider Team ID is required")
                    elif not new_age_group:
                        st.error("❌ Age Group is required")
                    elif not new_gender:
                        st.error("❌ Gender is required")
                    else:
                        try:
                            # First, check if this provider_team_id already exists
                            existing_team = db.table('teams').select(
                                'team_id_master, team_name, club_name, age_group, gender, state_code'
                            ).eq('provider_team_id', str(new_provider_team_id)).execute()

                            if existing_team.data and len(existing_team.data) > 0:
                                # Team already exists - show error and guide them
                                existing = existing_team.data[0]
                                st.error(f"❌ Provider Team ID **{new_provider_team_id}** already exists in the database!")
                                st.warning("**This team already exists:**")
                                st.write(f"- **Name:** {existing['team_name']}")
                                st.write(f"- **Club:** {existing.get('club_name', 'N/A')}")
                                st.write(f"- **Age/Gender:** {existing['age_group']} {existing['gender']}")
                                st.write(f"- **State:** {existing.get('state_code', 'N/A')}")
                                st.info("💡 **What to do:** Use the **mapping tool above** (Step 2 & 3) to create an alias mapping for this team instead of adding it as new.")
                                st.stop()

                            # Check for duplicate team by name + age_group + gender
                            duplicate_team = db.table('teams').select(
                                'team_id_master, team_name, club_name, age_group, gender, state_code, provider_team_id'
                            ).eq('team_name', new_team_name.strip()).eq('age_group', new_age_group).eq('gender', new_gender).execute()

                            if duplicate_team.data and len(duplicate_team.data) > 0:
                                # Team with same name/age/gender already exists
                                existing = duplicate_team.data[0]
                                st.error(f"❌ A team with this name, age group, and gender already exists!")
                                st.warning("**Potential duplicate team found:**")
                                st.write(f"- **Name:** {existing['team_name']}")
                                st.write(f"- **Club:** {existing.get('club_name', 'N/A')}")
                                st.write(f"- **Age/Gender:** {existing['age_group']} {existing['gender']}")
                                st.write(f"- **State:** {existing.get('state_code', 'N/A')}")
                                st.write(f"- **Provider Team ID:** {existing.get('provider_team_id', 'N/A')}")
                                st.info("💡 **What to do:** If this is the same team, use the **mapping tool above** to create an alias. If it's truly a different team, consider adding a distinguishing suffix to the team name (e.g., 'Legends FC Premier 2').")
                                st.stop()

                            # Get provider ID
                            provider_result = db.table('providers').select('id').eq('code', 'gotsport').single().execute()
                            provider_id = provider_result.data['id']

                            # Generate new team_id_master
                            import uuid
                            new_team_id_master = str(uuid.uuid4())

                            # Prepare team data
                            team_data = {
                                'team_id_master': new_team_id_master,
                                'provider_team_id': str(new_provider_team_id),
                                'provider_id': provider_id,
                                'team_name': new_team_name.strip(),
                                'club_name': new_club_name.strip() if new_club_name else None,
                                'age_group': new_age_group,
                                'birth_year': AGE_GROUPS[new_age_group]['birth_year'],
                                'gender': new_gender,
                                'state_code': new_state_code.upper().strip() if new_state_code else None,
                                'created_at': datetime.now().isoformat()
                            }

                            # Insert into teams table
                            db.table('teams').insert(team_data).execute()

                            # Also create alias mapping
                            alias_data = {
                                'provider_id': provider_id,
                                'provider_team_id': str(new_provider_team_id),
                                'team_id_master': new_team_id_master,
                                'match_confidence': 1.0,
                                'match_method': 'direct_id',  # Using 'direct_id' since we're explicitly creating this mapping
                                'review_status': 'approved',
                                'created_at': datetime.now().isoformat()
                            }

                            db.table('team_alias_map').insert(alias_data).execute()

                            st.success(f"✅ Successfully created team: **{new_team_name}**")
                            st.balloons()
                            st.info(f"Team ID: `{new_team_id_master}`")
                            st.info("Refresh the page to see the new team in the database")

                        except Exception as e:
                            st.error(f"❌ Error creating team: {e}")
                            import traceback
                            with st.expander("View Error Details"):
                                st.code(traceback.format_exc())

            st.markdown("---")
            st.caption("**Note:** Only use this when the team truly doesn't exist in the master database. For existing teams, use the mapping tool above.")

# ============================================================================
# MODULAR11 TEAM REVIEW SECTION
# ============================================================================
elif section == "📋 Modular11 Team Review":
    st.header("📋 Modular11 Team Review Queue")
    st.markdown("**Review and map unmatched Modular11 teams to your database**")
    
    db = get_database()
    
    if not db:
        st.error("Database connection not configured.")
    else:
        provider_code = 'modular11'
        provider_id = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'
        
        # Get review queue items
        try:
            queue = db.table('team_match_review_queue').select('*').eq(
                'provider_id', provider_code
            ).eq('status', 'pending').order('confidence_score', desc=True).execute()
            
            if not queue.data:
                st.success("✅ No pending team matches to review!")
                st.info("Run an import and unmatched teams will appear here.")
                
                # Show stats
                col1, col2, col3 = st.columns(3)
                with col1:
                    games = db.table('games').select('*', count='exact').eq('provider_id', provider_id).execute()
                    st.metric("Modular11 Games", games.count or 0)
                with col2:
                    aliases = db.table('team_alias_map').select('*', count='exact').eq('provider_id', provider_id).execute()
                    st.metric("Team Aliases", aliases.count or 0)
                with col3:
                    unmatched = db.table('games').select('*', count='exact').eq('provider_id', provider_id).is_('home_team_master_id', 'null').execute()
                    st.metric("Unmatched Games", unmatched.count or 0)
            else:
                st.info(f"**{len(queue.data)}** teams need review")
                
                # Display as cards
                for idx, item in enumerate(queue.data):
                    conf = item.get('confidence_score', 0) or 0
                    conf_pct = conf * 100 if conf <= 1 else conf
                    conf_color = "🟢" if conf_pct >= 75 else "🟡" if conf_pct >= 50 else "🔴"
                    
                    with st.expander(
                        f"{conf_color} {item.get('provider_team_name', 'Unknown')} ({conf_pct:.0f}%)",
                        expanded=idx < 3
                    ):
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.markdown("**From Import:**")
                            st.write(f"• Team: {item.get('provider_team_name', 'N/A')}")
                            st.write(f"• Provider ID: {item.get('provider_team_id', 'N/A')}")
                            details = item.get('match_details') or {}
                            st.write(f"• Age: {details.get('age_group', 'N/A')}")
                            st.write(f"• Club: {details.get('club_name', 'N/A')}")
                        
                        with col2:
                            st.markdown("**Suggested Match:**")
                            suggested_id = item.get('suggested_master_team_id')
                            if suggested_id:
                                suggested = db.table('teams').select(
                                    'team_name, club_name, age_group, gender'
                                ).eq('team_id_master', suggested_id).limit(1).execute()
                                
                                if suggested.data:
                                    s = suggested.data[0]
                                    st.write(f"• Team: {s['team_name']}")
                                    st.write(f"• Club: {s.get('club_name', 'N/A')}")
                                    st.write(f"• Age: {s['age_group']}")
                                else:
                                    st.write(f"• UUID: {suggested_id[:8]}...")
                            else:
                                st.warning("No suggestion - search below")
                        
                        st.divider()
                        
                        # Action buttons
                        col1, col2, col3 = st.columns([1, 1, 2])
                        
                        with col1:
                            if suggested_id and st.button(f"✅ Approve", key=f"approve_{item['id']}", type="primary"):
                                try:
                                    db.table('team_alias_map').insert({
                                        'provider_id': provider_id,
                                        'provider_team_id': item['provider_team_id'],
                                        'team_id_master': suggested_id,
                                        'match_method': 'manual',
                                        'match_confidence': conf,
                                        'review_status': 'approved'
                                    }).execute()
                                    
                                    db.table('team_match_review_queue').update({
                                        'status': 'approved'
                                    }).eq('id', item['id']).execute()
                                    
                                    st.success("✅ Approved!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                        
                        with col2:
                            if st.button(f"❌ Skip", key=f"skip_{item['id']}"):
                                try:
                                    db.table('team_match_review_queue').update({
                                        'status': 'skipped'
                                    }).eq('id', item['id']).execute()
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                        
                        with col3:
                            # Search for different match
                            search_term = st.text_input(
                                "🔍 Search team:",
                                key=f"search_{item['id']}",
                                placeholder="Type team or club name..."
                            )
                            
                            if search_term and len(search_term) >= 2:
                                age = details.get('age_group', '').lower()
                                search_results = db.table('teams').select(
                                    'team_id_master, team_name, club_name, age_group'
                                ).or_(f"team_name.ilike.%{search_term}%,club_name.ilike.%{search_term}%").limit(10).execute()
                                
                                if search_results.data:
                                    for team in search_results.data:
                                        btn_label = f"{team['team_name']} ({team['age_group']})"
                                        if st.button(f"→ {btn_label[:50]}", key=f"sel_{item['id']}_{team['team_id_master'][:8]}"):
                                            try:
                                                db.table('team_alias_map').insert({
                                                    'provider_id': provider_id,
                                                    'provider_team_id': item['provider_team_id'],
                                                    'team_id_master': team['team_id_master'],
                                                    'match_method': 'manual',
                                                    'match_confidence': 1.0,
                                                    'review_status': 'approved'
                                                }).execute()
                                                
                                                db.table('team_match_review_queue').update({
                                                    'status': 'approved'
                                                }).eq('id', item['id']).execute()
                                                
                                                st.success(f"✅ Mapped!")
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"Error: {e}")
                                else:
                                    st.caption("No teams found")
                        
                        # Create New Team section
                        st.divider()
                        with st.expander("➕ Create New Team", expanded=False):
                            st.markdown("*Create a new team in the database and map this Modular11 team to it*")
                            
                            # Pre-fill from Modular11 data
                            m11_name = item.get('provider_team_name', '')
                            m11_club = details.get('club_name', '')
                            m11_age = details.get('age_group', 'U13')
                            
                            col_a, col_b = st.columns(2)
                            with col_a:
                                new_team_name = st.text_input(
                                    "Team Name *",
                                    value=f"{m11_club} {m11_age} MLS NEXT",
                                    key=f"new_name_{item['id']}",
                                    help="e.g., 'City SC Southwest 2013 MLS NEXT'"
                                )
                                new_club_name = st.text_input(
                                    "Club Name *",
                                    value=m11_club,
                                    key=f"new_club_{item['id']}"
                                )
                                new_age = st.selectbox(
                                    "Age Group *",
                                    options=['u13', 'u14', 'u15', 'u16', 'u17', 'u18', 'u19'],
                                    index=['u13', 'u14', 'u15', 'u16', 'u17', 'u18', 'u19'].index(m11_age.lower()) if m11_age.lower() in ['u13', 'u14', 'u15', 'u16', 'u17', 'u18', 'u19'] else 0,
                                    key=f"new_age_{item['id']}"
                                )
                            with col_b:
                                new_gender = st.selectbox(
                                    "Gender *",
                                    options=['Male', 'Female'],
                                    index=0,
                                    key=f"new_gender_{item['id']}"
                                )
                                new_state = st.text_input(
                                    "State",
                                    value="",
                                    key=f"new_state_{item['id']}",
                                    placeholder="e.g., California"
                                )
                                new_state_code = st.text_input(
                                    "State Code",
                                    value="",
                                    key=f"new_state_code_{item['id']}",
                                    placeholder="e.g., CA",
                                    max_chars=2
                                )
                            
                            if st.button("✅ Create Team & Map", key=f"create_{item['id']}", type="primary"):
                                if not new_team_name or not new_club_name:
                                    st.error("Team Name and Club Name are required!")
                                else:
                                    try:
                                        import uuid
                                        new_team_id = str(uuid.uuid4())
                                        
                                        # Create the new team
                                        new_team_data = {
                                            'team_id_master': new_team_id,
                                            'team_name': new_team_name,
                                            'club_name': new_club_name,
                                            'age_group': new_age,
                                            'gender': new_gender,
                                            'provider_id': provider_id,
                                            'provider_team_id': item['provider_team_id']
                                        }
                                        if new_state:
                                            new_team_data['state'] = new_state
                                        if new_state_code:
                                            new_team_data['state_code'] = new_state_code.upper()
                                        
                                        db.table('teams').insert(new_team_data).execute()
                                        
                                        # Create the alias
                                        db.table('team_alias_map').insert({
                                            'provider_id': provider_id,
                                            'provider_team_id': item['provider_team_id'],
                                            'team_id_master': new_team_id,
                                            'match_method': 'manual',
                                            'match_confidence': 1.0,
                                            'review_status': 'approved'
                                        }).execute()
                                        
                                        # Update queue status
                                        db.table('team_match_review_queue').update({
                                            'status': 'approved'
                                        }).eq('id', item['id']).execute()
                                        
                                        st.success(f"✅ Created team '{new_team_name}' and mapped!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error creating team: {e}")
                
                st.divider()
                st.markdown("### Bulk Actions")
                col1, col2 = st.columns(2)
                with col1:
                    high_conf = [q for q in queue.data if (q.get('confidence_score') or 0) >= 0.75 and q.get('suggested_master_team_id')]
                    if st.button(f"✅ Approve All 75%+ ({len(high_conf)})", type="secondary"):
                        if high_conf:
                            progress = st.progress(0)
                            for i, item in enumerate(high_conf):
                                try:
                                    db.table('team_alias_map').insert({
                                        'provider_id': provider_id,
                                        'provider_team_id': item['provider_team_id'],
                                        'team_id_master': item['suggested_master_team_id'],
                                        'match_method': 'manual_bulk',
                                        'match_confidence': item.get('confidence_score', 0),
                                        'review_status': 'approved'
                                    }).execute()
                                    db.table('team_match_review_queue').update({'status': 'approved'}).eq('id', item['id']).execute()
                                except:
                                    pass
                                progress.progress((i + 1) / len(high_conf))
                            st.success(f"✅ Approved {len(high_conf)} matches!")
                            st.rerun()
                        else:
                            st.info("No matches with 75%+ confidence")
                            
        except Exception as e:
            st.error(f"Error loading review queue: {e}")
            st.code(str(e))

# ============================================================================
# DATABASE IMPORT STATS SECTION
# ============================================================================
elif section == "📈 Database Import Stats":
    st.header("Database Import Statistics")
    st.markdown("Track recent imports and database activity")

    db = get_database()

    if not db:
        st.error("Database connection not configured. Please set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in your .env file.")
    else:
        # Overview metrics
        st.subheader("Overview")

        col1, col2, col3, col4 = st.columns(4)

        try:
            # Total teams
            teams_result = db.table('teams').select('id', count='exact').execute()
            total_teams = teams_result.count or 0

            # Total games
            games_result = db.table('games').select('id', count='exact').execute()
            total_games = games_result.count or 0

            # Teams added in last 7 days
            seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
            new_teams_result = db.table('teams').select('id', count='exact').gte('created_at', seven_days_ago).execute()
            new_teams = new_teams_result.count or 0

            # Games added in last 7 days
            new_games_result = db.table('games').select('id', count='exact').gte('created_at', seven_days_ago).execute()
            new_games = new_games_result.count or 0

            with col1:
                st.metric("Total Teams", f"{total_teams:,}")
            with col2:
                st.metric("Total Games", f"{total_games:,}")
            with col3:
                st.metric("New Teams (7d)", f"{new_teams:,}")
            with col4:
                st.metric("New Games (7d)", f"{new_games:,}")

        except Exception as e:
            st.error(f"Error loading overview metrics: {e}")

        # Daily import metrics (Today and Yesterday)
        st.divider()
        st.subheader("Daily Import Summary")

        col1, col2, col3, col4 = st.columns(4)

        try:
            # Today's imports
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            today_result = db.table('games').select('id', count='exact').gte('created_at', today_start).execute()
            today_games = today_result.count or 0

            # Yesterday's imports
            yesterday_start = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            yesterday_end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            yesterday_result = db.table('games').select('id', count='exact').gte('created_at', yesterday_start).lt('created_at', yesterday_end).execute()
            yesterday_games = yesterday_result.count or 0

            # Calculate daily average (last 30 days)
            thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
            month_result = db.table('games').select('id', count='exact').gte('created_at', thirty_days_ago).execute()
            month_games = month_result.count or 0
            daily_avg = month_games / 30 if month_games > 0 else 0

            # Delta comparison
            delta_vs_yesterday = today_games - yesterday_games if yesterday_games > 0 else None
            delta_vs_avg = today_games - daily_avg if daily_avg > 0 else None

            with col1:
                st.metric("Today's Imports", f"{today_games:,}",
                         delta=f"{delta_vs_yesterday:+,}" if delta_vs_yesterday is not None else None,
                         help="Games imported today (vs yesterday)")
            with col2:
                st.metric("Yesterday's Imports", f"{yesterday_games:,}")
            with col3:
                st.metric("Daily Average (30d)", f"{daily_avg:,.0f}")
            with col4:
                # Success rate from recent builds
                recent_builds = db.table('build_logs').select(
                    'records_succeeded, records_processed'
                ).order('started_at', desc=True).limit(10).execute()

                if recent_builds.data:
                    total_processed = sum(b.get('records_processed', 0) or 0 for b in recent_builds.data)
                    total_succeeded = sum(b.get('records_succeeded', 0) or 0 for b in recent_builds.data)
                    success_rate = (total_succeeded / total_processed * 100) if total_processed > 0 else 100
                    st.metric("Success Rate (Recent)", f"{success_rate:.1f}%")
                else:
                    st.metric("Success Rate (Recent)", "N/A")

        except Exception as e:
            st.error(f"Error loading daily metrics: {e}")

        st.divider()

        # Team Scraping Status
        st.subheader("Team Scraping Status")

        try:
            seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()

            # Teams scraped within last 7 days
            recent_scraped = db.table('teams').select('id', count='exact').gte('last_scraped_at', seven_days_ago).execute()
            recent_count = recent_scraped.count or 0

            # Teams scraped more than 7 days ago
            stale_scraped = db.table('teams').select('id', count='exact').lt('last_scraped_at', seven_days_ago).not_.is_('last_scraped_at', 'null').execute()
            stale_count = stale_scraped.count or 0

            # Teams never scraped
            never_scraped = db.table('teams').select('id', count='exact').is_('last_scraped_at', 'null').execute()
            never_count = never_scraped.count or 0

            # Total teams for percentage calculation
            total_teams = recent_count + stale_count + never_count

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                pct = (recent_count / total_teams * 100) if total_teams > 0 else 0
                st.metric("Recently Scraped (<7d)", f"{recent_count:,}",
                         help=f"{pct:.1f}% of all teams")
            with col2:
                pct = (stale_count / total_teams * 100) if total_teams > 0 else 0
                st.metric("Stale (>7d)", f"{stale_count:,}",
                         help=f"{pct:.1f}% of all teams - need re-scraping")
            with col3:
                pct = (never_count / total_teams * 100) if total_teams > 0 else 0
                st.metric("Never Scraped", f"{never_count:,}",
                         help=f"{pct:.1f}% of all teams")
            with col4:
                up_to_date_pct = (recent_count / total_teams * 100) if total_teams > 0 else 0
                st.metric("Coverage", f"{up_to_date_pct:.1f}%",
                         help="Percentage of teams scraped within 7 days")

            # Show list of stale teams in expander
            if stale_count > 0 or never_count > 0:
                with st.expander(f"View Teams Needing Scraping ({stale_count + never_count:,} teams)"):
                    # Get stale teams sorted by last_scraped_at
                    stale_teams = db.table('teams').select(
                        'team_name, age_group, gender, state_code, last_scraped_at'
                    ).or_(
                        f'last_scraped_at.lt.{seven_days_ago},last_scraped_at.is.null'
                    ).order('last_scraped_at', desc=False, nullsfirst=True).limit(100).execute()

                    if stale_teams.data:
                        df = pd.DataFrame(stale_teams.data)
                        df['last_scraped_at'] = df['last_scraped_at'].apply(
                            lambda x: pd.to_datetime(x).strftime('%Y-%m-%d') if x else 'Never'
                        )
                        df.columns = ['Team Name', 'Age Group', 'Gender', 'State', 'Last Scraped']
                        st.dataframe(df, use_container_width=True, hide_index=True)
                        if len(stale_teams.data) == 100:
                            st.caption("Showing first 100 teams. More teams may need scraping.")

        except Exception as e:
            st.error(f"Error loading scraping status: {e}")

        st.divider()

        # Validation errors summary
        st.subheader("Validation Errors (Last 30 Days)")

        try:
            thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()

            errors_result = db.table('validation_errors').select(
                'error_type, record_type, created_at'
            ).gte('created_at', thirty_days_ago).execute()

            if errors_result.data:
                df = pd.DataFrame(errors_result.data)

                # Total error count
                total_errors = len(df)

                # Group by error type
                error_summary = df.groupby(['record_type', 'error_type']).size().reset_index(name='count')
                error_summary = error_summary.sort_values('count', ascending=False)

                # Show summary metrics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Errors", f"{total_errors:,}")
                with col2:
                    unique_types = len(error_summary)
                    st.metric("Error Types", f"{unique_types}")
                with col3:
                    # Most common error
                    if len(error_summary) > 0:
                        top_error = error_summary.iloc[0]
                        st.metric("Most Common", f"{top_error['error_type'][:20]}...",
                                 help=f"{top_error['count']} occurrences")
                    else:
                        st.metric("Most Common", "N/A")

                # Rename columns for display
                error_summary.columns = ['Record Type', 'Error Type', 'Count']
                st.dataframe(error_summary, use_container_width=True, hide_index=True)

                # Show recent errors in expander
                with st.expander("View Recent Errors"):
                    recent_errors = db.table('validation_errors').select(
                        'created_at, record_type, error_type, error_message'
                    ).gte('created_at', thirty_days_ago).order('created_at', desc=True).limit(10).execute()

                    if recent_errors.data:
                        recent_df = pd.DataFrame(recent_errors.data)
                        recent_df['created_at'] = pd.to_datetime(recent_df['created_at']).dt.strftime('%Y-%m-%d %H:%M')
                        recent_df.columns = ['Time', 'Record Type', 'Error Type', 'Message']
                        st.dataframe(recent_df, use_container_width=True, hide_index=True)
            else:
                st.success("No validation errors in the last 30 days!")

        except Exception as e:
            st.error(f"Error loading validation errors: {e}")

        st.divider()

        # Team Status Distribution
        st.subheader("Team Status Distribution")
        st.markdown("Breakdown of teams by ranking status (Active, Inactive, Not Enough Ranked Games)")

        try:
            # Query rankings_full or rankings_view for status distribution
            # Try rankings_view first (includes all teams with rankings)
            status_query = """
                SELECT 
                    status,
                    COUNT(*) as team_count
                FROM rankings_view
                GROUP BY status
                ORDER BY 
                    CASE status 
                        WHEN 'Active' THEN 1 
                        WHEN 'Not Enough Ranked Games' THEN 2 
                        WHEN 'Inactive' THEN 3 
                        ELSE 4 
                    END
            """
            
            # Use RPC call or direct query
            # Since Supabase Python client doesn't support raw SQL easily, we'll use table queries
            # Get all unique statuses and count them
            all_statuses = []
            page_size = 1000
            offset = 0
            
            with st.spinner("Loading team status data..."):
                while True:
                    status_result = db.table('rankings_view').select(
                        'status'
                    ).range(offset, offset + page_size - 1).execute()
                    
                    if not status_result.data:
                        break
                    
                    all_statuses.extend([r.get('status') for r in status_result.data])
                    
                    if len(status_result.data) < page_size:
                        break
                    
                    offset += page_size
            
            if all_statuses:
                # Count statuses
                from collections import Counter
                status_counts = Counter(all_statuses)
                total_teams = len(all_statuses)
                
                # Display metrics
                col1, col2, col3, col4 = st.columns(4)
                
                active_count = status_counts.get('Active', 0)
                inactive_count = status_counts.get('Inactive', 0)
                not_enough_count = status_counts.get('Not Enough Ranked Games', 0)
                other_count = total_teams - active_count - inactive_count - not_enough_count
                
                with col1:
                    active_pct = (active_count / total_teams * 100) if total_teams > 0 else 0
                    st.metric(
                        "Active Teams",
                        f"{active_count:,}",
                        help=f"{active_pct:.1f}% of all teams"
                    )
                    st.caption("Teams with enough ranked games")
                
                with col2:
                    not_enough_pct = (not_enough_count / total_teams * 100) if total_teams > 0 else 0
                    st.metric(
                        "Not Enough Ranked Games",
                        f"{not_enough_count:,}",
                        help=f"{not_enough_pct:.1f}% of all teams"
                    )
                    st.caption("Teams with <5 ranked games")
                
                with col3:
                    inactive_pct = (inactive_count / total_teams * 100) if total_teams > 0 else 0
                    st.metric(
                        "Inactive Teams",
                        f"{inactive_count:,}",
                        help=f"{inactive_pct:.1f}% of all teams"
                    )
                    st.caption("No games in last 180 days")
                
                with col4:
                    st.metric(
                        "Total Teams",
                        f"{total_teams:,}"
                    )
                    st.caption("All teams in rankings")
                
                # Display as table
                st.divider()
                status_df = pd.DataFrame([
                    {
                        'Status': 'Active',
                        'Count': active_count,
                        'Percentage': f"{(active_count / total_teams * 100):.1f}%"
                    },
                    {
                        'Status': 'Not Enough Ranked Games',
                        'Count': not_enough_count,
                        'Percentage': f"{(not_enough_count / total_teams * 100):.1f}%"
                    },
                    {
                        'Status': 'Inactive',
                        'Count': inactive_count,
                        'Percentage': f"{(inactive_count / total_teams * 100):.1f}%"
                    }
                ])
                
                if other_count > 0:
                    status_df = pd.concat([status_df, pd.DataFrame([{
                        'Status': 'Other/Unknown',
                        'Count': other_count,
                        'Percentage': f"{(other_count / total_teams * 100):.1f}%"
                    }])], ignore_index=True)
                
                st.dataframe(status_df, use_container_width=True, hide_index=True)
                
                # Status breakdown by age group and state
                st.divider()
                st.subheader("Status Breakdown by Age Group and State")
                
                # Get status by age group and state
                age_state_status_data = []
                offset = 0
                
                with st.spinner("Loading status breakdown by age group and state..."):
                    while True:
                        age_state_status_result = db.table('rankings_view').select(
                            'age, gender, state, status'
                        ).range(offset, offset + page_size - 1).execute()
                        
                        if not age_state_status_result.data:
                            break
                        
                        age_state_status_data.extend([
                            {
                                'age': r.get('age'),
                                'gender': r.get('gender'),
                                'state': r.get('state') or 'Unknown',
                                'status': r.get('status')
                            }
                            for r in age_state_status_result.data
                        ])
                        
                        if len(age_state_status_result.data) < page_size:
                            break
                        
                        offset += page_size
                
                if age_state_status_data:
                    age_state_status_df = pd.DataFrame(age_state_status_data)
                    
                    # Create pivot table: Age Group x State x Status
                    pivot_3d = pd.crosstab(
                        [age_state_status_df['age'], age_state_status_df['state']],
                        age_state_status_df['status'],
                        margins=True,
                        margins_name='Total'
                    )
                    
                    # Reorder status columns
                    col_order = ['Active', 'Not Enough Ranked Games', 'Inactive', 'Total']
                    available_cols = [c for c in col_order if c in pivot_3d.columns]
                    other_cols = [c for c in pivot_3d.columns if c not in col_order]
                    pivot_3d = pivot_3d[available_cols + other_cols]
                    
                    # Reset index to make age and state regular columns
                    pivot_3d = pivot_3d.reset_index()
                    pivot_3d.columns.name = None
                    
                    # Rename columns for display
                    pivot_3d = pivot_3d.rename(columns={'age': 'Age', 'state': 'State'})
                    
                    # Filter out the Total row for the main display (we'll show it separately)
                    pivot_display = pivot_3d[pivot_3d['Age'] != 'Total'].copy()
                    total_row = pivot_3d[pivot_3d['Age'] == 'Total'].copy()
                    
                    # Sort by Age, then by State
                    pivot_display['Age'] = pd.to_numeric(pivot_display['Age'], errors='coerce')
                    pivot_display = pivot_display.sort_values(['Age', 'State'])
                    pivot_display['Age'] = pivot_display['Age'].apply(lambda x: f'U{int(x)}' if pd.notna(x) else 'Unknown')
                    
                    # Display the breakdown
                    st.dataframe(
                        pivot_display.style.background_gradient(
                            cmap='YlOrRd', 
                            subset=[c for c in pivot_display.columns if c not in ['Age', 'State']]
                        ),
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    # Show totals row
                    if len(total_row) > 0:
                        st.markdown("**Totals:**")
                        st.dataframe(total_row, use_container_width=True, hide_index=True)
                    
                    # Also show summary by age group only (simpler view)
                    with st.expander("View Simplified Breakdown by Age Group Only"):
                        age_only_df = age_state_status_df.groupby(['age', 'status']).size().reset_index(name='count')
                        age_only_pivot = age_only_df.pivot(index='age', columns='status', values='count').fillna(0)
                        age_only_pivot = age_only_pivot.astype(int)
                        
                        # Add totals
                        age_only_pivot['Total'] = age_only_pivot.sum(axis=1)
                        age_only_pivot.loc['Total'] = age_only_pivot.sum(axis=0)
                        
                        # Reorder columns
                        col_order = ['Active', 'Not Enough Ranked Games', 'Inactive', 'Total']
                        available_cols = [c for c in col_order if c in age_only_pivot.columns]
                        other_cols = [c for c in age_only_pivot.columns if c not in col_order]
                        age_only_pivot = age_only_pivot[available_cols + other_cols]
                        
                        # Format age labels
                        age_only_pivot.index = age_only_pivot.index.map(lambda x: f'U{int(x)}' if isinstance(x, (int, float)) and pd.notna(x) else str(x))
                        
                        st.dataframe(
                            age_only_pivot.style.background_gradient(cmap='YlOrRd', subset=age_only_pivot.columns[:-1]),
                            use_container_width=True
                        )
            else:
                st.warning("No team status data found. Rankings may not have been calculated yet.")
                
        except Exception as e:
            st.error(f"Error loading team status distribution: {e}")
            import traceback
            with st.expander("View Error Details"):
                st.code(traceback.format_exc())

# ============================================================================
# STATE COVERAGE SECTION
# ============================================================================
elif section == "🗺️ State Coverage":
    st.header("State Coverage")
    st.markdown("Team distribution by state and age group")

    db = get_database()

    if not db:
        st.error("Database connection not configured. Please set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in your .env file.")
    else:
        try:
            # Fetch all teams with state and age group info
            # Paginate to get all results (Supabase default limit is 1000)
            all_teams = []
            page_size = 1000
            offset = 0

            with st.spinner("Loading all teams..."):
                while True:
                    teams_result = db.table('teams').select(
                        'state_code, age_group, gender'
                    ).range(offset, offset + page_size - 1).execute()

                    if not teams_result.data:
                        break

                    all_teams.extend(teams_result.data)

                    if len(teams_result.data) < page_size:
                        break

                    offset += page_size

            if all_teams:
                df = pd.DataFrame(all_teams)

                # Clean up data
                df['state_code'] = df['state_code'].fillna('Unknown')
                df['age_group'] = df['age_group'].fillna('Unknown')

                # Overview metrics
                st.subheader("Overview")
                col1, col2, col3, col4 = st.columns(4)

                with col1:
                    st.metric("Total Teams", f"{len(df):,}")
                with col2:
                    st.metric("States", f"{df['state_code'].nunique()}")
                with col3:
                    st.metric("Age Groups", f"{df['age_group'].nunique()}")
                with col4:
                    # Most covered state
                    top_state = df['state_code'].value_counts().idxmax()
                    top_count = df['state_code'].value_counts().max()
                    st.metric("Top State", f"{top_state}", help=f"{top_count:,} teams")

                st.divider()

                # State by Age Group heatmap/pivot table
                st.subheader("Teams by State and Age Group")

                # Create pivot table
                pivot_df = pd.crosstab(
                    df['state_code'],
                    df['age_group'],
                    margins=True,
                    margins_name='Total'
                )

                # Sort columns by age group order from AGE_GROUPS
                age_order = list(AGE_GROUPS.keys()) + ['Unknown', 'Total']
                available_cols = [col for col in age_order if col in pivot_df.columns]
                other_cols = [col for col in pivot_df.columns if col not in age_order]
                pivot_df = pivot_df[available_cols + other_cols]

                # Sort rows by total count (descending), keep 'Total' at bottom
                if 'Total' in pivot_df.index:
                    total_row = pivot_df.loc['Total']
                    pivot_df = pivot_df.drop('Total')
                    pivot_df = pivot_df.sort_values('Total', ascending=False)
                    pivot_df = pd.concat([pivot_df, total_row.to_frame().T])

                # Display the pivot table with styling
                st.dataframe(
                    pivot_df.style.background_gradient(cmap='Blues', subset=pivot_df.columns[:-1]),
                    use_container_width=True
                )

                st.divider()

                # Gender breakdown by state
                st.subheader("Gender Distribution by State")

                gender_pivot = pd.crosstab(
                    df['state_code'],
                    df['gender'],
                    margins=True,
                    margins_name='Total'
                )

                # Sort by total
                if 'Total' in gender_pivot.index:
                    total_row = gender_pivot.loc['Total']
                    gender_pivot = gender_pivot.drop('Total')
                    gender_pivot = gender_pivot.sort_values('Total', ascending=False)
                    gender_pivot = pd.concat([gender_pivot, total_row.to_frame().T])

                col1, col2 = st.columns([2, 1])

                with col1:
                    st.dataframe(
                        gender_pivot.style.background_gradient(cmap='Greens', subset=gender_pivot.columns[:-1]),
                        use_container_width=True
                    )

                with col2:
                    # Overall gender split
                    gender_counts = df['gender'].value_counts()
                    st.markdown("**Overall Gender Split**")
                    for gender, count in gender_counts.items():
                        pct = count / len(df) * 100
                        st.write(f"- {gender}: {count:,} ({pct:.1f}%)")

                st.divider()

                # Top 10 states detailed view
                st.subheader("Top 10 States - Detailed Breakdown")

                top_states = df['state_code'].value_counts().head(10).index.tolist()

                for state in top_states:
                    state_df = df[df['state_code'] == state]
                    total_teams = len(state_df)

                    with st.expander(f"**{state}** - {total_teams:,} teams"):
                        col1, col2 = st.columns(2)

                        with col1:
                            st.markdown("**By Age Group**")
                            age_counts = state_df['age_group'].value_counts().sort_index()
                            age_df = pd.DataFrame({
                                'Age Group': age_counts.index,
                                'Teams': age_counts.values
                            })
                            st.dataframe(age_df, use_container_width=True, hide_index=True)

                        with col2:
                            st.markdown("**By Gender**")
                            gender_counts = state_df['gender'].value_counts()
                            gender_df = pd.DataFrame({
                                'Gender': gender_counts.index,
                                'Teams': gender_counts.values
                            })
                            st.dataframe(gender_df, use_container_width=True, hide_index=True)

                st.divider()

                # States with low coverage
                st.subheader("States Needing More Coverage")

                state_counts = df['state_code'].value_counts()
                low_coverage = state_counts[state_counts < 50].sort_values()

                if len(low_coverage) > 0:
                    st.warning(f"Found {len(low_coverage)} states with fewer than 50 teams")

                    low_df = pd.DataFrame({
                        'State': low_coverage.index,
                        'Teams': low_coverage.values
                    })
                    st.dataframe(low_df, use_container_width=True, hide_index=True)
                else:
                    st.success("All states have at least 50 teams!")

            else:
                st.info("No teams found in the database.")
                st.caption("Note: The query fetched 0 teams. Check database connection.")

        except Exception as e:
            st.error(f"Error loading state coverage data: {e}")
            import traceback
            st.code(traceback.format_exc())

# ============================================================================
# TEAM MERGE MANAGER SECTION
# ============================================================================
elif section == "🔀 Team Merge Manager":
    st.header("Team Merge Manager")
    st.markdown("Merge duplicate teams and view AI-powered merge suggestions")

    db = get_database()

    if not db:
        st.error("Database connection required for Team Merge Manager")
    else:
        # Create tabs for different operations
        merge_tab, suggestions_tab, history_tab = st.tabs([
            "🔗 Manual Merge",
            "💡 AI Suggestions",
            "📜 Merge History"
        ])

        # ========================
        # TAB 1: Manual Merge
        # ========================
        with merge_tab:
            st.subheader("Merge Duplicate Teams")
            st.markdown("""
            Select two teams to merge. The **deprecated team** will be hidden from rankings,
            and all references will resolve to the **canonical team**.

            > **Note:** This is reversible. No game data is modified - only lookup mappings are created.
            """)

            # User email for audit
            merge_user_email = st.text_input("Your Email (for audit)", key="merge_email")

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("##### Team to Deprecate (will be hidden)")

                # Fetch teams for selection
                try:
                    teams_result = execute_with_retry(
                        lambda: db.table('teams')
                            .select('team_id_master, team_name, club_name, state_code, age_group, gender')
                            .eq('is_deprecated', False)
                            .order('team_name')
                            .limit(5000)
                    )
                    all_teams = teams_result.data or []

                    # Create team options
                    team_options = {
                        f"{t['team_name']} ({t.get('club_name', 'N/A')}) - {t.get('state_code', '??')} {t.get('age_group', '')} {t.get('gender', '')}": t['team_id_master']
                        for t in all_teams
                    }

                    deprecated_selection = st.selectbox(
                        "Select duplicate team to deprecate",
                        options=[""] + list(team_options.keys()),
                        key="deprecated_team"
                    )
                    deprecated_team_id = team_options.get(deprecated_selection) if deprecated_selection else None

                except Exception as e:
                    st.error(f"Failed to load teams: {e}")
                    deprecated_team_id = None

            with col2:
                st.markdown("##### Canonical Team (keep this one)")

                if deprecated_team_id:
                    # Filter out the deprecated team from options
                    canonical_options = {k: v for k, v in team_options.items() if v != deprecated_team_id}
                    canonical_selection = st.selectbox(
                        "Select team to keep",
                        options=[""] + list(canonical_options.keys()),
                        key="canonical_team"
                    )
                    canonical_team_id = canonical_options.get(canonical_selection) if canonical_selection else None
                else:
                    st.info("Select a team to deprecate first")
                    canonical_team_id = None

            # Merge reason
            merge_reason = st.text_input("Reason for merge (optional)", key="merge_reason")

            # Execute merge button
            if st.button("🔗 Execute Merge", type="primary", disabled=not (deprecated_team_id and canonical_team_id and merge_user_email)):
                try:
                    result = execute_with_retry(
                        lambda: db.rpc('execute_team_merge', {
                            'p_deprecated_team_id': deprecated_team_id,
                            'p_canonical_team_id': canonical_team_id,
                            'p_merged_by': merge_user_email,
                            'p_merge_reason': merge_reason or None
                        })
                    )

                    if result.data:
                        st.success(f"✅ Successfully merged teams! Merge ID: {result.data}")
                        st.balloons()
                    else:
                        st.warning("Merge completed but no ID returned")

                except Exception as e:
                    st.error(f"❌ Merge failed: {e}")

        # ========================
        # TAB 2: AI Suggestions
        # ========================
        with suggestions_tab:
            st.subheader("AI-Powered Merge Suggestions")

            # Show success message if we just merged
            if 'last_merge_success' in st.session_state and st.session_state.last_merge_success:
                st.success(st.session_state.last_merge_success)
                st.session_state.last_merge_success = None

            st.markdown("""
            Find potential duplicate teams using multiple signals:
            - **Name Similarity (55%)** - Fuzzy name matching (penalizes Roman numeral differences)
            - **Club Match (30%)** - Same club name
            - **Geography (15%)** - Same state
            - **Opponent Overlap (+10% bonus)** - Shared opponents confirm duplicates
            """)

            # Initialize session state for dismissed suggestions
            if 'dismissed_suggestions' not in st.session_state:
                st.session_state.dismissed_suggestions = set()

            # User email for merges (required for one-click merge)
            merge_email = st.text_input("Your Email (required for merging)", key="suggestion_merge_email")

            # Filters
            col1, col2, col3 = st.columns(3)

            with col1:
                age_filter = st.selectbox(
                    "Age Group",
                    options=[""] + [f"u{i}" for i in range(8, 20)],
                    key="suggest_age"
                )

            with col2:
                gender_filter = st.selectbox(
                    "Gender",
                    options=["", "Male", "Female"],
                    key="suggest_gender"
                )

            with col3:
                min_confidence = st.slider(
                    "Min Confidence",
                    min_value=0.3,
                    max_value=0.9,
                    value=0.5,
                    step=0.1,
                    key="suggest_confidence"
                )

            # Helper functions for improved analysis
            def extract_roman_numeral(name):
                """Extract Roman numerals from team name (I, II, III, IV, V, etc.)"""
                import re
                # Match Roman numerals at word boundaries
                pattern = r'\b(I{1,3}|IV|V|VI{0,3}|IX|X)\b'
                match = re.search(pattern, name.upper())
                return match.group(1) if match else None

            def has_roman_numeral_difference(name_a, name_b):
                """Check if two names differ by Roman numeral (likely different squads)

                Catches cases like:
                - 'Team II' vs 'Team III' (both have numerals, different)
                - 'Team' vs 'Team II' (one has numeral, one doesn't)
                """
                import re
                roman_a = extract_roman_numeral(name_a)
                roman_b = extract_roman_numeral(name_b)

                # Case 1: Both have Roman numerals but they're different
                # Case 2: One has a Roman numeral, the other doesn't
                if roman_a != roman_b:
                    # Remove Roman numerals and compare base names
                    pattern = r'\b(I{1,3}|IV|V|VI{0,3}|IX|X)\b'
                    base_a = re.sub(pattern, '', name_a.upper()).strip()
                    base_b = re.sub(pattern, '', name_b.upper()).strip()
                    # Clean up extra spaces
                    base_a = ' '.join(base_a.split())
                    base_b = ' '.join(base_b.split())
                    # If base names are very similar, they're different squads (NOT duplicates)
                    if calculate_similarity(base_a.lower(), base_b.lower()) > 0.85:
                        return True
                return False

            def get_opponents(team_id, games_data):
                """Get set of opponent IDs for a team from games data"""
                opponents = set()
                for g in games_data:
                    if g.get('home_team_master_id') == team_id:
                        opp = g.get('away_team_master_id')
                        if opp:
                            opponents.add(opp)
                    elif g.get('away_team_master_id') == team_id:
                        opp = g.get('home_team_master_id')
                        if opp:
                            opponents.add(opp)
                return opponents

            def calculate_opponent_overlap(opponents_a, opponents_b):
                """Calculate Jaccard similarity of opponent sets"""
                if not opponents_a or not opponents_b:
                    return 0.0
                # Remove each other from opponent sets
                opponents_a = opponents_a.copy()
                opponents_b = opponents_b.copy()
                intersection = len(opponents_a & opponents_b)
                union = len(opponents_a | opponents_b)
                return intersection / union if union > 0 else 0.0

            # Button to trigger search - stores results in session state
            if st.button("🔍 Find Potential Duplicates", type="primary"):
                if not age_filter or not gender_filter:
                    st.warning("Please select both age group and gender")
                else:
                    with st.spinner("Analyzing teams for duplicates (including opponent overlap)..."):
                        try:
                            # Fetch teams in cohort
                            age_num = age_filter.lower().replace('u', '')
                            teams_result = execute_with_retry(
                                lambda: db.table('teams')
                                    .select('team_id_master, team_name, club_name, state_code')
                                    .eq('is_deprecated', False)
                                    .eq('gender', gender_filter)
                                    .or_(f"age_group.eq.{age_num},age_group.eq.u{age_num},age_group.eq.U{age_num}")
                                    .limit(2000)
                            )
                            teams = teams_result.data or []

                            if len(teams) < 2:
                                st.session_state.suggestions = []
                                st.session_state.suggestions_message = f"Only {len(teams)} teams found - need at least 2 for comparison"
                            else:
                                st.info(f"Analyzing {len(teams)} teams...")
                                progress_bar = st.progress(0)

                                # Fetch games for opponent overlap analysis
                                team_ids = [t['team_id_master'] for t in teams]

                                # Fetch all games involving these teams
                                st.text("Fetching game data for opponent analysis...")
                                all_games = []
                                batch_size = 50
                                for i in range(0, len(team_ids), batch_size):
                                    batch = team_ids[i:i+batch_size]
                                    # Home games
                                    home_result = execute_with_retry(
                                        lambda b=batch: db.table('games')
                                            .select('home_team_master_id, away_team_master_id, game_date')
                                            .in_('home_team_master_id', b)
                                    )
                                    all_games.extend(home_result.data or [])
                                    # Away games
                                    away_result = execute_with_retry(
                                        lambda b=batch: db.table('games')
                                            .select('home_team_master_id, away_team_master_id, game_date')
                                            .in_('away_team_master_id', b)
                                    )
                                    all_games.extend(away_result.data or [])
                                    progress_bar.progress(min(0.3, (i + batch_size) / len(team_ids) * 0.3))

                                # Build opponent sets for each team
                                st.text("Building opponent profiles...")
                                opponents_by_team = {}
                                for team_id in team_ids:
                                    opponents_by_team[team_id] = get_opponents(team_id, all_games)

                                # Analyze pairs
                                st.text("Comparing team pairs...")
                                suggestions = []
                                total_pairs = len(teams) * (len(teams) - 1) // 2
                                pair_count = 0

                                for i, team_a in enumerate(teams):
                                    for team_b in teams[i+1:]:
                                        pair_count += 1
                                        if pair_count % 100 == 0:
                                            progress_bar.progress(0.3 + (pair_count / total_pairs) * 0.7)

                                        name_a = (team_a.get('team_name') or '').lower()
                                        name_b = (team_b.get('team_name') or '').lower()
                                        club_a = (team_a.get('club_name') or '').lower()
                                        club_b = (team_b.get('club_name') or '').lower()
                                        state_a = team_a.get('state_code', '')
                                        state_b = team_b.get('state_code', '')

                                        # Check for Roman numeral difference (different squads)
                                        roman_diff = has_roman_numeral_difference(
                                            team_a.get('team_name', ''),
                                            team_b.get('team_name', '')
                                        )

                                        # Calculate signals
                                        name_sim = calculate_similarity(name_a, name_b)
                                        club_sim = calculate_similarity(club_a, club_b) if club_a and club_b else 0
                                        state_match = 1.0 if state_a == state_b else 0.0

                                        # Opponent overlap (most important signal)
                                        opponent_overlap = calculate_opponent_overlap(
                                            opponents_by_team.get(team_a['team_id_master'], set()),
                                            opponents_by_team.get(team_b['team_id_master'], set())
                                        )

                                        # Apply Roman numeral penalty
                                        roman_penalty = 0.5 if roman_diff else 1.0

                                        # Weighted score - name similarity is PRIMARY signal
                                        # Opponent overlap is a BONUS (true duplicates often have 0 overlap
                                        # because they ARE the same team, not opponents!)
                                        # Base weights: name=55%, club=30%, state=15% = 100%
                                        base_score = (
                                            0.55 * name_sim * roman_penalty +
                                            0.30 * club_sim +
                                            0.15 * state_match
                                        )

                                        # Opponent overlap as confirming bonus (up to +10%)
                                        # High overlap confirms they're likely duplicates
                                        overlap_bonus = 0.10 * opponent_overlap

                                        score = min(1.0, base_score + overlap_bonus)

                                        if score >= min_confidence:
                                            suggestion_key = f"{team_a['team_id_master']}_{team_b['team_id_master']}"

                                            # Skip if dismissed
                                            if suggestion_key in st.session_state.dismissed_suggestions:
                                                continue

                                            suggestions.append({
                                                'key': suggestion_key,
                                                'team_a_id': team_a['team_id_master'],
                                                'team_a_name': team_a['team_name'],
                                                'team_a_club': team_a.get('club_name', ''),
                                                'team_b_id': team_b['team_id_master'],
                                                'team_b_name': team_b['team_name'],
                                                'team_b_club': team_b.get('club_name', ''),
                                                'confidence': score,
                                                'name_sim': name_sim,
                                                'club_sim': club_sim,
                                                'state_match': state_match,
                                                'opponent_overlap': opponent_overlap,
                                                'roman_diff': roman_diff
                                            })

                                progress_bar.progress(1.0)

                                # Sort by confidence
                                suggestions.sort(key=lambda x: x['confidence'], reverse=True)

                                # Store suggestions in session state for persistent display
                                st.session_state.suggestions = suggestions
                                if suggestions:
                                    st.session_state.suggestions_message = f"Found {len(suggestions)} potential duplicates"
                                else:
                                    st.session_state.suggestions_message = f"No potential duplicates found above {min_confidence:.0%} confidence"

                                # Rerun to display the suggestions outside the button block
                                st.rerun()

                        except Exception as e:
                            st.error(f"Error analyzing teams: {e}")
                            import traceback
                            st.code(traceback.format_exc())

            # ========================
            # DISPLAY SUGGESTIONS FROM SESSION STATE (persists across reruns)
            # ========================
            if 'suggestions' in st.session_state:
                # Show status message
                if 'suggestions_message' in st.session_state and st.session_state.suggestions_message:
                    if st.session_state.suggestions:
                        st.success(st.session_state.suggestions_message)
                    else:
                        st.info(st.session_state.suggestions_message)

                suggestions = st.session_state.suggestions

                if suggestions:
                    # Filter out dismissed suggestions on each render
                    suggestions = [s for s in suggestions if s['key'] not in st.session_state.dismissed_suggestions]

                    for idx, s in enumerate(suggestions[:30]):
                        # Color based on confidence and warnings
                        if s['roman_diff']:
                            confidence_color = "⚠️"  # Warning - likely different squads
                        elif s['confidence'] >= 0.8:
                            confidence_color = "🟢"
                        elif s['confidence'] >= 0.6:
                            confidence_color = "🟡"
                        else:
                            confidence_color = "🟠"

                        # Add warning text if Roman numeral difference detected
                        warning_text = " ⚠️ DIFFERENT SQUADS?" if s['roman_diff'] else ""

                        with st.expander(f"{confidence_color} {s['team_a_name']} ↔ {s['team_b_name']} ({s['confidence']:.0%} match){warning_text}"):

                            # Warning banner for Roman numeral differences
                            if s['roman_diff']:
                                st.warning("⚠️ These teams have different Roman numerals (I, II, III, etc.) - likely different squads within the same club. NOT recommended to merge!")

                            col1, col2 = st.columns(2)

                            with col1:
                                st.markdown(f"**Team A:** {s['team_a_name']}")
                                st.caption(f"Club: {s['team_a_club'] or 'N/A'}")
                                st.caption(f"ID: `{s['team_a_id'][:8]}...`")

                            with col2:
                                st.markdown(f"**Team B:** {s['team_b_name']}")
                                st.caption(f"Club: {s['team_b_club'] or 'N/A'}")
                                st.caption(f"ID: `{s['team_b_id'][:8]}...`")

                            st.divider()

                            st.markdown("**Signal Breakdown:**")
                            signal_cols = st.columns(4)
                            with signal_cols[0]:
                                st.metric("Opponent Overlap", f"{s['opponent_overlap']:.0%}")
                            with signal_cols[1]:
                                st.metric("Name Match", f"{s['name_sim']:.0%}")
                            with signal_cols[2]:
                                st.metric("Club Match", f"{s['club_sim']:.0%}")
                            with signal_cols[3]:
                                st.metric("Same State", "Yes" if s['state_match'] else "No")

                            st.divider()

                            # Action buttons
                            action_cols = st.columns(4)

                            with action_cols[0]:
                                # Capture values in default args to avoid closure issues
                                if st.button(f"🔗 Merge A→B", key=f"merge_ab_{idx}",
                                           disabled=not merge_email or s['roman_diff']):
                                    try:
                                        # Use values directly from suggestion dict
                                        result = execute_with_retry(
                                            lambda tid_a=s['team_a_id'], tid_b=s['team_b_id'], conf=s['confidence']: db.rpc('execute_team_merge', {
                                                'p_deprecated_team_id': tid_a,
                                                'p_canonical_team_id': tid_b,
                                                'p_merged_by': merge_email,
                                                'p_merge_reason': f"AI suggestion ({conf:.0%} confidence)"
                                            })
                                        )
                                        # Check if RPC returned success
                                        if result.data and isinstance(result.data, dict) and result.data.get('success') == False:
                                            st.error(f"❌ Merge failed: {result.data.get('error', 'Unknown error')}")
                                        else:
                                            st.session_state.dismissed_suggestions.add(s['key'])
                                            st.session_state.last_merge_success = f"✅ Merged! {s['team_a_name']} → {s['team_b_name']}"
                                            st.rerun()
                                    except Exception as e:
                                        st.error(f"❌ Merge failed: {e}")
                                        import traceback
                                        st.code(traceback.format_exc())

                            with action_cols[1]:
                                # Capture values in default args to avoid closure issues
                                if st.button(f"🔗 Merge B→A", key=f"merge_ba_{idx}",
                                           disabled=not merge_email or s['roman_diff']):
                                    try:
                                        result = execute_with_retry(
                                            lambda tid_a=s['team_a_id'], tid_b=s['team_b_id'], conf=s['confidence']: db.rpc('execute_team_merge', {
                                                'p_deprecated_team_id': tid_b,
                                                'p_canonical_team_id': tid_a,
                                                'p_merged_by': merge_email,
                                                'p_merge_reason': f"AI suggestion ({conf:.0%} confidence)"
                                            })
                                        )
                                        # Check if RPC returned success
                                        if result.data and isinstance(result.data, dict) and result.data.get('success') == False:
                                            st.error(f"❌ Merge failed: {result.data.get('error', 'Unknown error')}")
                                        else:
                                            st.session_state.dismissed_suggestions.add(s['key'])
                                            st.session_state.last_merge_success = f"✅ Merged! {s['team_b_name']} → {s['team_a_name']}"
                                            st.rerun()
                                    except Exception as e:
                                        st.error(f"❌ Merge failed: {e}")

                            with action_cols[2]:
                                if st.button(f"❌ Not a Duplicate", key=f"dismiss_{idx}"):
                                    st.session_state.dismissed_suggestions.add(s['key'])
                                    st.rerun()

                            with action_cols[3]:
                                if not merge_email:
                                    st.caption("Enter email above to enable merge")

            # Show dismissed count
            if st.session_state.dismissed_suggestions:
                st.caption(f"📋 {len(st.session_state.dismissed_suggestions)} suggestions dismissed this session")
                if st.button("🔄 Reset Dismissed Suggestions"):
                    st.session_state.dismissed_suggestions = set()
                    st.rerun()

        # ========================
        # TAB 3: Merge History
        # ========================
        with history_tab:
            st.subheader("Recent Merge Activity")

            # Show success message if we just merged
            if 'last_merge_success' in st.session_state and st.session_state.last_merge_success:
                st.success(st.session_state.last_merge_success)
                st.session_state.last_merge_success = None

            try:
                # Fetch from team_merge_map (the actual merge records)
                history_result = execute_with_retry(
                    lambda: db.table('team_merge_map')
                        .select('*, deprecated_team:teams!team_merge_map_deprecated_team_id_fkey(team_name), canonical_team:teams!team_merge_map_canonical_team_id_fkey(team_name)')
                        .order('merged_at', desc=True)
                        .limit(50)
                )

                merges = history_result.data or []

                if merges:
                    st.info(f"Found {len(merges)} team merges")

                    for idx, merge in enumerate(merges):
                        deprecated_name = merge.get('deprecated_team', {}).get('team_name', 'Unknown') if merge.get('deprecated_team') else 'Unknown'
                        canonical_name = merge.get('canonical_team', {}).get('team_name', 'Unknown') if merge.get('canonical_team') else 'Unknown'

                        with st.expander(
                            f"~~{deprecated_name}~~ → **{canonical_name}**"
                        ):
                            col1, col2 = st.columns(2)

                            with col1:
                                st.markdown("**Deprecated Team**")
                                st.write(f"Name: {deprecated_name}")
                                st.write(f"ID: `{merge.get('deprecated_team_id', 'N/A')[:8]}...`")

                            with col2:
                                st.markdown("**Canonical Team**")
                                st.write(f"Name: {canonical_name}")
                                st.write(f"ID: `{merge.get('canonical_team_id', 'N/A')[:8]}...`")

                            st.divider()

                            st.write(f"**Merged by:** {merge.get('merged_by', 'N/A')}")
                            st.write(f"**Merged at:** {merge.get('merged_at', 'N/A')}")
                            st.write(f"**Reason:** {merge.get('merge_reason', 'No reason provided')}")

                            # Revert button
                            revert_email = st.text_input(
                                "Your email to revert",
                                key=f"revert_email_{idx}"
                            )

                            if st.button(
                                "⏪ Revert This Merge",
                                key=f"revert_{idx}",
                                disabled=not revert_email
                            ):
                                try:
                                    merge_id = merge.get('id')
                                    revert_result = execute_with_retry(
                                        lambda mid=merge_id: db.rpc('revert_team_merge', {
                                            'p_merge_id': mid,
                                            'p_reverted_by': revert_email,
                                            'p_revert_reason': 'Reverted via dashboard'
                                        })
                                    )
                                    st.session_state.last_merge_success = f"✅ Merge reverted: {deprecated_name} is now active again"
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ Revert failed: {e}")
                else:
                    st.info("No team merges found yet. Use the Manual Merge or AI Suggestions tab to merge duplicate teams.")

            except Exception as e:
                st.error(f"Error loading merge history: {e}")
                import traceback
                st.code(traceback.format_exc())

# Footer
st.divider()
st.caption(f"PitchRank Dashboard v2.0.0 | {PROJECT_NAME} v{VERSION}")
st.caption("For more information, see DASHBOARD_README.md")
