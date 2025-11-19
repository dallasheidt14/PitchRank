"""PitchRank Settings Dashboard - Comprehensive Parameter Viewer"""
import streamlit as st
import pandas as pd
from config.settings import (
    RANKING_CONFIG,
    ML_CONFIG,
    MATCHING_CONFIG,
    ETL_CONFIG,
    AGE_GROUPS,
    VERSION,
    PROJECT_NAME
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
        "🔧 Environment Variables"
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

# Footer
st.divider()
st.caption(f"PitchRank Dashboard v2.0.0 | {PROJECT_NAME} v{VERSION}")
st.caption("For more information, see DASHBOARD_README.md")
