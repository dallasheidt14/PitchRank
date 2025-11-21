"""PitchRank Settings Dashboard - Comprehensive Parameter Viewer"""
import streamlit as st
import pandas as pd
import os
from datetime import datetime, timedelta
from difflib import SequenceMatcher
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

# Sidebar navigation
st.sidebar.title("Navigation")
section = st.sidebar.radio(
    "Select Section",
    [
        "📊 Overview",
        "🎯 V53E Ranking Engine",
        "🤖 Machine Learning Layer",
        "🔍 Matching Configuration",
        "⚙️ ETL & Data Processing",
        "👥 Age Groups",
        "🔧 Environment Variables",
        "🔎 Unknown Teams Mapper",
        "📈 Database Import Stats"
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
# OVERVIEW SECTION
# ============================================================================
if section == "📊 Overview":
    st.header("Overview")
    st.markdown("Quick view of critical parameters and system health.")

    # Key metrics
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

    # Critical parameters
    st.subheader("🔴 Critical Parameters")

    param_info(
        "SOS_TRANSITIVITY_LAMBDA",
        RANKING_CONFIG['sos_transitivity_lambda'],
        "Controls strength of schedule transitivity. 0.20 = 80% direct opponents, 20% opponents of opponents"
    )

    param_info(
        "RECENT_SHARE",
        RANKING_CONFIG['recent_share'],
        "Weight given to recent games vs older games. Higher = more emphasis on recent performance"
    )

    param_info(
        "SHRINK_TAU",
        RANKING_CONFIG['shrink_tau'],
        "Bayesian shrinkage strength. Higher = more conservative estimates"
    )

    param_info(
        "ML_ALPHA",
        ML_CONFIG['alpha'],
        "Machine learning layer contribution. 0 = no ML, 1 = full ML"
    )

    st.divider()

    # Component weights validation
    st.subheader("⚖️ Component Weights Validation")

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

# ============================================================================
# V53E RANKING ENGINE SECTION
# ============================================================================
elif section == "🎯 V53E Ranking Engine":
    st.header("V53E Ranking Engine")
    st.markdown("All 24 core parameters across 11 processing layers")

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

# ============================================================================
# MACHINE LEARNING LAYER SECTION
# ============================================================================
elif section == "🤖 Machine Learning Layer":
    st.header("Machine Learning Layer (Layer 13)")
    st.markdown("XGBoost and Random Forest ensemble for predictive adjustment")

    # ML Layer Status
    col1, col2 = st.columns(2)
    with col1:
        if ML_CONFIG['enabled']:
            st.success("✓ ML Layer Enabled")
        else:
            st.warning("⚠️ ML Layer Disabled")
    with col2:
        st.metric("ML Alpha (Blend Weight)", ML_CONFIG['alpha'])

    st.divider()

    # Core ML Parameters
    st.subheader("Core ML Parameters")

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

    st.divider()

    # XGBoost Parameters
    st.subheader("XGBoost Hyperparameters")
    xgb_df = pd.DataFrame([
        {"Parameter": k, "Value": v}
        for k, v in ML_CONFIG['xgb_params'].items()
    ])
    st.dataframe(xgb_df, use_container_width=True, hide_index=True)

    st.divider()

    # Random Forest Parameters
    st.subheader("Random Forest Hyperparameters")
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
            # Get unique provider team IDs from games that have NULL master IDs
            unmapped_query = """
                SELECT DISTINCT
                    COALESCE(home_provider_id, away_provider_id) as provider_team_id,
                    COUNT(*) as game_count
                FROM games
                WHERE home_team_master_id IS NULL OR away_team_master_id IS NULL
                GROUP BY provider_team_id
                ORDER BY game_count DESC
                LIMIT 50
            """

            # Simpler approach - get games with null IDs and extract provider IDs
            null_games = db.table('games').select(
                'home_provider_id, away_provider_id, home_team_master_id, away_team_master_id, game_date'
            ).or_('home_team_master_id.is.null,away_team_master_id.is.null').order(
                'game_date', desc=True
            ).limit(200).execute()

            if null_games.data:
                # Extract unique unmapped provider IDs
                unmapped_ids = {}
                for game in null_games.data:
                    if not game.get('home_team_master_id') and game.get('home_provider_id'):
                        pid = str(game['home_provider_id'])
                        unmapped_ids[pid] = unmapped_ids.get(pid, 0) + 1
                    if not game.get('away_team_master_id') and game.get('away_provider_id'):
                        pid = str(game['away_provider_id'])
                        unmapped_ids[pid] = unmapped_ids.get(pid, 0) + 1

                if unmapped_ids:
                    st.info(f"Found **{len(unmapped_ids)}** unique unmapped provider team IDs affecting **{sum(unmapped_ids.values())}** games")

                    # Sort by frequency
                    sorted_ids = sorted(unmapped_ids.items(), key=lambda x: x[1], reverse=True)

                    # Display as table
                    unmapped_df = pd.DataFrame(sorted_ids, columns=['Provider Team ID', 'Games Affected'])
                    st.dataframe(unmapped_df, use_container_width=True, hide_index=True)

                    st.divider()

                    # Step 2: Select a team to map
                    st.subheader("Step 2: Map a Team")

                    # Add search/filter box
                    search_filter = st.text_input(
                        "🔍 Search Provider Team ID:",
                        placeholder="Type to filter (e.g., 615537)",
                        help="Filter the list below by typing part of the Provider Team ID"
                    )

                    # Filter the list based on search
                    if search_filter:
                        filtered_ids = [(pid, count) for pid, count in sorted_ids if search_filter in str(pid)]
                        if not filtered_ids:
                            st.warning(f"No Provider Team IDs found matching '{search_filter}'")
                            st.stop()
                    else:
                        filtered_ids = sorted_ids

                    st.caption(f"Showing {len(filtered_ids)} of {len(sorted_ids)} unmapped teams")

                    selected_provider_id = st.selectbox(
                        "Select Provider Team ID to map:",
                        options=[pid for pid, _ in filtered_ids],
                        format_func=lambda x: f"{x} ({unmapped_ids[x]} games affected)"
                    )

                    if selected_provider_id:
                        st.info(f"Mapping Provider Team ID: **{selected_provider_id}**")

                        # Try to get team name from teams table (in case it exists but isn't mapped)
                        team_lookup = db.table('teams').select(
                            'team_name, club_name, age_group, gender, state_code'
                        ).eq('provider_team_id', selected_provider_id).execute()

                        if team_lookup.data and len(team_lookup.data) > 0:
                            team_info = team_lookup.data[0]
                            st.success(f"✓ Found team in database: **{team_info['team_name']}**")
                            st.write(f"Club: {team_info.get('club_name', 'N/A')}")
                            st.write(f"Age/Gender: {team_info['age_group']} {team_info['gender']}")
                            st.write(f"State: {team_info.get('state_code', 'N/A')}")
                            search_name_default = team_info['team_name']
                            search_age_default = team_info['age_group']
                            search_gender_default = team_info['gender']
                        else:
                            st.warning("⚠️ Team name not found in database. Search manually below.")
                            search_name_default = ""
                            search_age_default = ""
                            search_gender_default = ""

                        st.divider()

                        # Step 3: Search for matches
                        st.subheader("Step 3: Find Master Team Match")

                        col1, col2, col3 = st.columns(3)

                        with col1:
                            search_name = st.text_input(
                                "Team Name to Search",
                                value=search_name_default,
                                placeholder="Enter team name..."
                            )
                        with col2:
                            age_options = [""] + list(AGE_GROUPS.keys())
                            default_age_idx = age_options.index(search_age_default) if search_age_default in age_options else 0
                            search_age = st.selectbox("Age Group", age_options, index=default_age_idx)
                        with col3:
                            gender_options = ["", "Male", "Female"]
                            default_gender_idx = gender_options.index(search_gender_default) if search_gender_default in gender_options else 0
                            search_gender = st.selectbox("Gender", gender_options, index=default_gender_idx)

                        if st.button("🔍 Search for Matches", type="primary") and search_name:
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
                                        similarity = calculate_similarity(search_name, team['team_name'])
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

        # Recent builds
        st.subheader("Recent Import Activity")

        try:
            # Get recent game imports from build_logs
            builds_result = db.table('build_logs').select(
                'build_id, stage, started_at, completed_at, records_processed, records_succeeded, records_failed'
            ).eq('stage', 'game_import').order('started_at', desc=True).limit(20).execute()

            if builds_result.data:
                df = pd.DataFrame(builds_result.data)

                # Add status column with proper null handling
                def get_status(row):
                    if row['completed_at'] is None or pd.isna(row['completed_at']):
                        return '🔄 Running'
                    elif row['records_failed'] and row['records_failed'] > 0:
                        return '⚠️ Partial'
                    else:
                        return '✅ Success'

                df['status'] = df.apply(get_status, axis=1)

                # Format dates with null handling
                df['started_at'] = pd.to_datetime(df['started_at']).dt.strftime('%Y-%m-%d %H:%M')
                df['completed_at'] = df['completed_at'].apply(
                    lambda x: pd.to_datetime(x).strftime('%Y-%m-%d %H:%M') if x and not pd.isna(x) else '—'
                )

                # Reorder columns for better readability
                display_df = df[['build_id', 'status', 'started_at', 'completed_at',
                         'records_processed', 'records_succeeded', 'records_failed']]

                # Rename columns for display
                display_df.columns = ['Build ID', 'Status', 'Started', 'Completed',
                             'Processed', 'Succeeded', 'Failed/Dups']

                st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("No import logs found. Import activity will appear here after running the import pipeline.")

        except Exception as e:
            st.error(f"Error loading import activity: {e}")

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

# Footer
st.divider()
st.caption(f"PitchRank Dashboard v2.0.0 | {PROJECT_NAME} v{VERSION}")
st.caption("For more information, see DASHBOARD_README.md")
