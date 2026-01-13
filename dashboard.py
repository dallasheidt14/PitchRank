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
        "📈 Database Import Stats",
        "🗺️ State Coverage",
        "📍 Missing State Codes",
        "🔀 Team Merge Manager",
        "✏️ Manual Team Edit"
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
# MISSING STATE CODES SECTION
# ============================================================================
elif section == "📍 Missing State Codes":
    st.header("Teams Missing State Codes")
    st.markdown("View teams that are missing state or state_code information")

    # State code to state name mapping (used throughout this section)
    STATE_CODE_TO_NAME = {
        'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
        'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
        'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
        'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
        'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
        'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
        'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
        'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
        'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
        'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
        'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
        'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
        'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'District of Columbia'
    }

    db = get_database()

    if not db:
        st.error("Database connection not configured. Please set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in your .env file.")
    else:
        try:
            with st.spinner("Loading teams without state codes..."):
                # Get total teams count (with retry)
                total_result = execute_with_retry(
                    lambda: db.table('teams').select('*', count='exact'),
                    max_retries=3,
                    base_delay=2.0
                )
                total_teams = total_result.count
                time.sleep(0.5)  # Small delay between queries

                # Count teams with no state (both state and state_code are NULL)
                no_state_result = execute_with_retry(
                    lambda: db.table('teams').select('*', count='exact').is_('state', 'null').is_('state_code', 'null'),
                    max_retries=3,
                    base_delay=2.0
                )
                no_state_count = no_state_result.count
                time.sleep(0.5)

                # Count teams with state but no state_code
                has_state_no_code_result = execute_with_retry(
                    lambda: db.table('teams').select('*', count='exact').not_.is_('state', 'null').is_('state_code', 'null'),
                    max_retries=3,
                    base_delay=2.0
                )
                has_state_no_code_count = has_state_no_code_result.count
                time.sleep(0.5)

                # Count teams with state_code but no state
                has_code_no_state_result = execute_with_retry(
                    lambda: db.table('teams').select('*', count='exact').is_('state', 'null').not_.is_('state_code', 'null'),
                    max_retries=3,
                    base_delay=2.0
                )
                has_code_no_state_count = has_code_no_state_result.count
                time.sleep(0.5)

                # Count teams with both state and state_code
                has_both_result = execute_with_retry(
                    lambda: db.table('teams').select('*', count='exact').not_.is_('state', 'null').not_.is_('state_code', 'null'),
                    max_retries=3,
                    base_delay=2.0
                )
                has_both_count = has_both_result.count

            # Display summary metrics
            st.subheader("Summary")
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("Total Teams", f"{total_teams:,}")
            with col2:
                st.metric("Complete State Info", f"{has_both_count:,}", 
                         delta=f"{has_both_count/total_teams*100:.1f}%", 
                         delta_color="normal")
            with col3:
                st.metric("Missing Both", f"{no_state_count:,}", 
                         delta=f"{no_state_count/total_teams*100:.1f}%", 
                         delta_color="inverse")
            with col4:
                partial_count = has_state_no_code_count + has_code_no_state_count
                st.metric("Partial Info", f"{partial_count:,}", 
                         delta=f"{partial_count/total_teams*100:.1f}%", 
                         delta_color="off")

            st.divider()

            # Detailed breakdown
            st.subheader("Detailed Breakdown")
            
            breakdown_data = {
                'Category': [
                    'Complete (both state and state_code)',
                    'Missing both state and state_code',
                    'Has state but no state_code',
                    'Has state_code but no state'
                ],
                'Count': [
                    has_both_count,
                    no_state_count,
                    has_state_no_code_count,
                    has_code_no_state_count
                ],
                'Percentage': [
                    f"{has_both_count/total_teams*100:.2f}%",
                    f"{no_state_count/total_teams*100:.2f}%",
                    f"{has_state_no_code_count/total_teams*100:.2f}%",
                    f"{has_code_no_state_count/total_teams*100:.2f}%"
                ]
            }
            
            breakdown_df = pd.DataFrame(breakdown_data)
            st.dataframe(breakdown_df, use_container_width=True, hide_index=True)

            st.divider()

            # Show teams without state codes
            st.subheader("Teams Missing State Codes")
            
            # Fetch teams without state_code (with retry logic)
            teams_no_state = []
            page_size = 1000
            offset = 0

            with st.spinner("Loading teams without state_code..."):
                while True:
                    try:
                        result = execute_with_retry(
                            lambda: db.table('teams').select(
                                'team_id_master, team_name, club_name, age_group, gender, state, state_code'
                            ).is_('state_code', 'null').range(offset, offset + page_size - 1),
                            max_retries=3,
                            base_delay=2.0
                        )
                    except Exception as e:
                        st.warning(f"⚠️ Error loading teams at offset {offset}: {str(e)[:200]}")
                        if teams_no_state:
                            st.info(f"Using {len(teams_no_state)} teams loaded so far...")
                        break
                    
                    if not result.data:
                        break
                    
                    teams_no_state.extend(result.data)
                    offset += page_size
                    
                    if len(result.data) < page_size:
                        break
                    
                    # Small delay between pages to avoid overwhelming the connection
                    time.sleep(0.3)

            if teams_no_state:
                st.info(f"Found **{len(teams_no_state)}** teams without state_code")
                
                # Create DataFrame
                teams_df = pd.DataFrame(teams_no_state)
                
                # Add filters
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    age_filter = st.multiselect(
                        "Filter by Age Group",
                        options=sorted(teams_df['age_group'].dropna().unique()),
                        default=[]
                    )
                
                with col2:
                    gender_filter = st.multiselect(
                        "Filter by Gender",
                        options=sorted(teams_df['gender'].dropna().unique()),
                        default=[]
                    )
                
                with col3:
                    has_club = st.checkbox("Has Club Name", value=False)
                
                # Apply filters
                filtered_df = teams_df.copy()
                
                if age_filter:
                    filtered_df = filtered_df[filtered_df['age_group'].isin(age_filter)]
                
                if gender_filter:
                    filtered_df = filtered_df[filtered_df['gender'].isin(gender_filter)]
                
                if has_club:
                    filtered_df = filtered_df[filtered_df['club_name'].notna()]
                
                # Display table
                display_df = filtered_df[['team_name', 'club_name', 'age_group', 'gender', 'state', 'state_code']].copy()
                display_df = display_df.rename(columns={
                    'team_name': 'Team Name',
                    'club_name': 'Club Name',
                    'age_group': 'Age Group',
                    'gender': 'Gender',
                    'state': 'State (Full)',
                    'state_code': 'State Code'
                })
                
                st.dataframe(
                    display_df,
                    use_container_width=True,
                    hide_index=True
                )
                
                # Manual update form
                st.divider()
                st.subheader("✏️ Manually Update State Code")
                
                # Create team selection options
                team_options = {}
                for _, row in filtered_df.iterrows():
                    team_id = row['team_id_master']
                    team_name = row['team_name']
                    club_name = row['club_name'] if pd.notna(row['club_name']) else 'No Club'
                    age_group = row['age_group'] if pd.notna(row['age_group']) else 'Unknown'
                    gender = row['gender'] if pd.notna(row['gender']) else 'Unknown'
                    display_name = f"{team_name} ({club_name}) - {age_group} {gender}"
                    team_options[team_id] = display_name
                
                if team_options:
                    # Select team outside of form so it updates reactively
                    selected_team_id = st.selectbox(
                        "Select Team to Update",
                        options=[''] + list(team_options.keys()),
                        format_func=lambda x: team_options.get(x, 'Select a team...') if x else 'Select a team...',
                        help="Choose a team from the filtered list above"
                    )
                    
                    # Show current team info (outside form so it updates reactively)
                    # Debug: Check what was selected
                    if selected_team_id:
                        # Check if it's a valid team ID
                        if selected_team_id in team_options:
                            try:
                                team_info_row = filtered_df[filtered_df['team_id_master'] == selected_team_id]
                                if not team_info_row.empty:
                                    team_info = team_info_row.iloc[0]
                                    st.info(f"""
                                    **Current Info:**
                                    - Team: {team_info['team_name']}
                                    - Club: {team_info['club_name'] if pd.notna(team_info['club_name']) else 'N/A'}
                                    - Current State: {team_info['state'] if pd.notna(team_info['state']) else 'None'}
                                    - Current State Code: {team_info['state_code'] if pd.notna(team_info['state_code']) else 'None'}
                                    """)
                                else:
                                    st.warning(f"⚠️ Team with ID '{selected_team_id}' not found in filtered results")
                            except Exception as e:
                                st.error(f"Error loading team info: {e}")
                                import traceback
                                with st.expander("Error Details"):
                                    st.code(traceback.format_exc())
                        else:
                            st.info("👆 Select a team above to see its current information")
                    else:
                        st.info("👆 Select a team above to see its current information")
                    
                    st.divider()
                    
                    # Form for state code selection and submission
                    with st.form("update_state_form"):
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            # Display selected team name (read-only, for reference)
                            if selected_team_id:
                                st.text_input(
                                    "Selected Team",
                                    value=team_options.get(selected_team_id, ''),
                                    disabled=True,
                                    help="Team selected above"
                                )
                            else:
                                st.warning("⚠️ Please select a team above first")
                        
                        with col2:
                            state_code_input = st.selectbox(
                                "State Code",
                                options=[''] + sorted(STATE_CODE_TO_NAME.keys()),
                                help="Select the 2-letter state code (e.g., CA, AZ, TX)"
                            )
                            
                            # Auto-populate state name if state code is selected
                            if state_code_input:
                                auto_state_name = STATE_CODE_TO_NAME[state_code_input]
                                st.success(f"State name will be set to: **{auto_state_name}**")
                            
                            # Optional: Allow manual override of state name
                            manual_state_override = st.checkbox("Manually override state name", value=False)
                            if manual_state_override:
                                state_name_input = st.text_input(
                                    "State Name (Full)",
                                    value=STATE_CODE_TO_NAME.get(state_code_input, '') if state_code_input else '',
                                    help="Full state name (e.g., California, Arizona)"
                                )
                            else:
                                state_name_input = STATE_CODE_TO_NAME.get(state_code_input, '') if state_code_input else ''
                        
                        submitted = st.form_submit_button("Update Team State", type="primary", use_container_width=True)
                        
                        if submitted:
                            if not state_code_input:
                                st.error("Please select a state code")
                            elif not selected_team_id:
                                st.error("Please select a team")
                            else:
                                try:
                                    update_data = {
                                        'state_code': state_code_input.upper(),
                                        'state': state_name_input if state_name_input else STATE_CODE_TO_NAME.get(state_code_input.upper(), '')
                                    }
                                    
                                    result = db.table('teams').update(update_data).eq('team_id_master', selected_team_id).execute()
                                    
                                    if result.data:
                                        st.success(f"✅ Successfully updated **{team_options[selected_team_id]}** to State Code: **{update_data['state_code']}**, State: **{update_data['state']}**")
                                        time.sleep(1)  # Brief pause to show success message
                                        st.rerun()
                                    else:
                                        st.error("Failed to update team. No data returned from update operation.")
                                        
                                except Exception as e:
                                    st.error(f"Error updating team: {e}")
                                    import traceback
                                    with st.expander("View Error Details"):
                                        st.code(traceback.format_exc())
                else:
                    st.info("No teams available to update with current filters.")
                
                # Show breakdown by age group and gender
                if len(filtered_df) > 0:
                    st.divider()
                    st.subheader("Breakdown by Age Group and Gender")
                    
                    breakdown_pivot = pd.crosstab(
                        filtered_df['age_group'].fillna('Unknown'),
                        filtered_df['gender'].fillna('Unknown'),
                        margins=True,
                        margins_name='Total'
                    )
                    
                    st.dataframe(breakdown_pivot, use_container_width=True)
                    
                    # Identify clubs spanning multiple states
                    if filtered_df['club_name'].notna().sum() > 0:
                        st.divider()
                        st.subheader("🌍 Clubs Spanning Multiple States")
                        st.markdown("These clubs have teams in multiple states. Review teams by state to assign correct state codes.")
                        
                        # Fetch all teams (including those with state codes) to check for multi-state clubs
                        with st.spinner("Analyzing clubs across states..."):
                            all_teams_multi_state = []
                            page_size = 1000
                            offset = 0
                            
                            try:
                                while True:
                                    result = execute_with_retry(
                                        lambda: db.table('teams').select(
                                            'team_id_master, team_name, club_name, age_group, gender, state, state_code'
                                        ).not_.is_('club_name', 'null').range(offset, offset + page_size - 1),
                                        max_retries=3,
                                        base_delay=2.0
                                    )
                                    
                                    if not result.data:
                                        break
                                    
                                    all_teams_multi_state.extend(result.data)
                                    offset += page_size
                                    
                                    if len(result.data) < page_size:
                                        break
                                    
                                    time.sleep(0.3)
                            except Exception as e:
                                st.warning(f"⚠️ Error loading teams for multi-state analysis: {str(e)[:200]}")
                                all_teams_multi_state = []
                            
                            if all_teams_multi_state:
                                all_teams_df = pd.DataFrame(all_teams_multi_state)
                                
                                # Find clubs with teams in multiple states
                                multi_state_clubs_info = {}
                                for club_name in filtered_df['club_name'].dropna().unique():
                                    club_teams = all_teams_df[all_teams_df['club_name'] == club_name]
                                    # Get unique states (non-null state codes)
                                    states = club_teams[club_teams['state_code'].notna()]['state_code'].unique()
                                    if len(states) > 1:
                                        multi_state_clubs_info[club_name] = {
                                            'states': sorted(states.tolist()),
                                            'state_counts': club_teams[club_teams['state_code'].notna()]['state_code'].value_counts().to_dict(),
                                            'teams_missing_state': len(club_teams[club_teams['state_code'].isna()])
                                        }
                                
                                if multi_state_clubs_info:
                                    # Store multi-state clubs info in session state for later use
                                    st.session_state.multi_state_clubs_info = multi_state_clubs_info
                                    
                                    # Initialize session state for multi-state club selection
                                    if 'selected_multi_state_club' not in st.session_state:
                                        st.session_state.selected_multi_state_club = None
                                    
                                    # Create summary table
                                    multi_state_summary = []
                                    for club_name, info in multi_state_clubs_info.items():
                                        states_str = ', '.join(info['states'])
                                        state_counts_str = ', '.join([f"{state}: {count}" for state, count in info['state_counts'].items()])
                                        multi_state_summary.append({
                                            'Club Name': club_name,
                                            'States': states_str,
                                            'Teams by State': state_counts_str,
                                            'Teams Missing State': info['teams_missing_state']
                                        })
                                    
                                    multi_state_df = pd.DataFrame(multi_state_summary)
                                    multi_state_df = multi_state_df.sort_values('Teams Missing State', ascending=False)
                                    
                                    st.info(f"Found **{len(multi_state_clubs_info)}** clubs with teams in multiple states")
                                    
                                    # Club selector for multi-state clubs
                                    col1, col2 = st.columns([3, 1])
                                    with col1:
                                        multi_state_club_options = [''] + multi_state_df['Club Name'].tolist()
                                        default_multi_index = 0
                                        if st.session_state.selected_multi_state_club and st.session_state.selected_multi_state_club in multi_state_club_options:
                                            default_multi_index = multi_state_club_options.index(st.session_state.selected_multi_state_club)
                                        
                                        selected_multi_club = st.selectbox(
                                            "🔍 Select a multi-state club to review teams by state",
                                            options=multi_state_club_options,
                                            index=default_multi_index,
                                            help="Select a club to see its teams grouped by state"
                                        )
                                        if selected_multi_club:
                                            st.session_state.selected_multi_state_club = selected_multi_club
                                        else:
                                            st.session_state.selected_multi_state_club = None
                                    
                                    with col2:
                                        if st.session_state.selected_multi_state_club:
                                            if st.button("Clear Selection", key="clear_multi_state", use_container_width=True):
                                                st.session_state.selected_multi_state_club = None
                                                st.rerun()
                                    
                                    # Display teams grouped by state for selected club
                                    if st.session_state.selected_multi_state_club:
                                        club_info = multi_state_clubs_info[st.session_state.selected_multi_state_club]
                                        club_all_teams = all_teams_df[all_teams_df['club_name'] == st.session_state.selected_multi_state_club]
                                        
                                        st.markdown(f"### 📋 Teams for **{st.session_state.selected_multi_state_club}**")
                                        st.markdown(f"**States:** {', '.join(club_info['states'])} | **Teams Missing State Code:** {club_info['teams_missing_state']}")
                                        
                                        # Group teams by state
                                        for state_code in sorted(club_info['states']):
                                            state_teams = club_all_teams[club_all_teams['state_code'] == state_code]
                                            if not state_teams.empty:
                                                with st.expander(f"📍 {state_code} ({STATE_CODE_TO_NAME.get(state_code, state_code)}) - {len(state_teams)} teams", expanded=True):
                                                    state_display = state_teams[['team_name', 'age_group', 'gender', 'state', 'state_code']].copy()
                                                    state_display = state_display.rename(columns={
                                                        'team_name': 'Team Name',
                                                        'age_group': 'Age Group',
                                                        'gender': 'Gender',
                                                        'state': 'State (Full)',
                                                        'state_code': 'State Code'
                                                    })
                                                    st.dataframe(state_display, use_container_width=True, hide_index=True)
                                        
                                        # Show teams missing state codes for this club
                                        missing_state_teams = club_all_teams[club_all_teams['state_code'].isna()]
                                        if not missing_state_teams.empty:
                                            with st.expander(f"❓ Teams Missing State Code ({len(missing_state_teams)} teams)", expanded=True):
                                                st.warning("These teams need state codes assigned. Review the teams above to determine the correct state for each team.")
                                                
                                                # Prepare teams for editing - include team_id_master for updates
                                                missing_display = missing_state_teams[['team_id_master', 'team_name', 'age_group', 'gender', 'state', 'state_code']].copy()
                                                missing_display = missing_display.rename(columns={
                                                    'team_id_master': 'Team ID',
                                                    'team_name': 'Team Name',
                                                    'age_group': 'Age Group',
                                                    'gender': 'Gender',
                                                    'state': 'State (Full)',
                                                    'state_code': 'State Code'
                                                })
                                                
                                                st.info("💡 **How to edit:** Double-click on any cell in the 'State Code' column, then type a 2-letter state code (e.g., TX, CA, NY). Leave blank cells empty.")
                                                
                                                # Display editable table
                                                edited_missing_teams_df = st.data_editor(
                                                    missing_display,
                                                    column_config={
                                                        'Team ID': st.column_config.NumberColumn('Team ID', disabled=True),
                                                        'Team Name': st.column_config.TextColumn('Team Name', disabled=True),
                                                        'Age Group': st.column_config.TextColumn('Age Group', disabled=True),
                                                        'Gender': st.column_config.TextColumn('Gender', disabled=True),
                                                        'State (Full)': st.column_config.TextColumn('State (Full)', disabled=True),
                                                        'State Code': st.column_config.TextColumn(
                                                            'State Code',
                                                            help="💡 Double-click this cell to edit. Enter 2-letter state code (e.g., CA, TX, WA). Leave blank if unknown.",
                                                            max_chars=2,
                                                            default="",
                                                            required=False
                                                        )
                                                    },
                                                    use_container_width=True,
                                                    hide_index=True,
                                                    num_rows="fixed",
                                                    key=f"multi_state_editor_{st.session_state.selected_multi_state_club}"
                                                )
                                                
                                                # Apply updates button for multi-state club teams
                                                apply_multi_clicked = st.button(
                                                    "💾 Apply State Code Updates",
                                                    type="primary",
                                                    use_container_width=True,
                                                    key=f"apply_multi_state_{st.session_state.selected_multi_state_club}"
                                                )
                                                
                                                if apply_multi_clicked:
                                                    # Convert State Code column to string, handling NaN values
                                                    edited_missing_teams_df['State Code'] = edited_missing_teams_df['State Code'].fillna('').astype(str).str.strip().str.upper()
                                                    
                                                    # Find teams that have valid state codes entered (ignore blanks)
                                                    valid_state_codes = set(STATE_CODE_TO_NAME.keys())
                                                    updates_to_apply = edited_missing_teams_df[
                                                        (edited_missing_teams_df['State Code'].str.len() == 2) &
                                                        (edited_missing_teams_df['State Code'] != '') &
                                                        (edited_missing_teams_df['State Code'].isin(valid_state_codes))
                                                    ]
                                                    
                                                    if updates_to_apply.empty:
                                                        st.error("⚠️ No valid state codes found to apply!")
                                                        st.info("💡 **Blank cells are fine** - only teams with state codes entered will be updated.")
                                                        st.info("💡 Make sure you've entered **2-letter state codes** (e.g., TX, CA, NY).")
                                                    else:
                                                        with st.spinner(f"Updating {len(updates_to_apply)} teams..."):
                                                            updated_count = 0
                                                            error_count = 0
                                                            errors = []
                                                            
                                                            for _, row in updates_to_apply.iterrows():
                                                                team_id = int(row['Team ID'])
                                                                state_code = str(row['State Code']).strip().upper()
                                                                team_name = row['Team Name']
                                                                
                                                                state_name = STATE_CODE_TO_NAME[state_code]
                                                                
                                                                try:
                                                                    result = db.table('teams').update({
                                                                        'state_code': state_code,
                                                                        'state': state_name
                                                                    }).eq('team_id_master', team_id).execute()
                                                                    
                                                                    if result.data:
                                                                        updated_count += 1
                                                                    else:
                                                                        error_msg = f"No data returned for {team_name} (ID: {team_id})"
                                                                        errors.append(error_msg)
                                                                        error_count += 1
                                                                except Exception as e:
                                                                    error_msg = f"Error updating {team_name} (ID: {team_id}): {str(e)}"
                                                                    errors.append(error_msg)
                                                                    error_count += 1
                                                            
                                                            if updated_count > 0:
                                                                st.success(f"✅ Successfully updated {updated_count} teams with state codes!")
                                                                if error_count > 0:
                                                                    st.warning(f"⚠️ {error_count} teams had errors. See details below.")
                                                                time.sleep(1.5)
                                                                st.rerun()
                                                            else:
                                                                st.error(f"❌ Failed to update any teams. {error_count} errors occurred.")
                                                                if errors:
                                                                    with st.expander("View Error Details"):
                                                                        for err in errors[:20]:
                                                                            st.text(err)
                                                                        if len(errors) > 20:
                                                                            st.text(f"... and {len(errors) - 20} more errors")
                                        
                                        st.divider()
                                    
                                    # Display summary table
                                    st.markdown("#### Summary of Multi-State Clubs")
                                    st.dataframe(
                                        multi_state_df[['Club Name', 'States', 'Teams Missing State']],
                                        use_container_width=True,
                                        hide_index=True
                                    )
                                else:
                                    st.success("✅ No clubs found spanning multiple states!")
                                    
                                    # Clear selection if no multi-state clubs
                                    if 'selected_multi_state_club' in st.session_state:
                                        st.session_state.selected_multi_state_club = None
                                    if 'multi_state_clubs_info' in st.session_state:
                                        st.session_state.multi_state_clubs_info = {}
                        
                        st.divider()
                    
                    # Show breakdown by club name (top clubs)
                    if filtered_df['club_name'].notna().sum() > 0:
                        st.subheader("Top Clubs (Missing State Codes)")
                        
                        club_counts = filtered_df['club_name'].value_counts().head(20)
                        
                        # Get state codes for clubs that already have them (from teams with state codes)
                        clubs_with_states = {}
                        for club_name in club_counts.index:
                            # Check if any team with this club name has a state code
                            club_teams = teams_df[teams_df['club_name'] == club_name]
                            teams_with_state = club_teams[club_teams['state_code'].notna()]
                            if not teams_with_state.empty:
                                # Get the most common state code for this club
                                most_common_state = teams_with_state['state_code'].mode()
                                if not most_common_state.empty:
                                    clubs_with_states[club_name] = most_common_state.iloc[0]
                        
                        club_df = pd.DataFrame({
                            'Club Name': club_counts.index,
                            'Teams Missing State Code': club_counts.values
                        })
                        
                        # Add state code column (pre-populate if club already has state codes)
                        club_df['State Code'] = club_df['Club Name'].map(clubs_with_states).fillna('')
                        
                        # Initialize session state for selected club
                        if 'selected_club_missing_state' not in st.session_state:
                            st.session_state.selected_club_missing_state = None
                        
                        # Add club selector above the table
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            club_options = [''] + club_df['Club Name'].tolist()
                            # Determine default index
                            default_index = 0
                            if st.session_state.selected_club_missing_state and st.session_state.selected_club_missing_state in club_options:
                                default_index = club_options.index(st.session_state.selected_club_missing_state)
                            
                            selected_club = st.selectbox(
                                "🔍 Select a club to view its teams",
                                options=club_options,
                                index=default_index,
                                help="Select a club from the list to see all teams missing state codes for that club"
                            )
                            if selected_club:
                                st.session_state.selected_club_missing_state = selected_club
                            else:
                                st.session_state.selected_club_missing_state = None
                        
                        with col2:
                            if st.session_state.selected_club_missing_state:
                                if st.button("Clear Selection", use_container_width=True):
                                    st.session_state.selected_club_missing_state = None
                                    st.rerun()
                        
                        # Quick access: Clickable club buttons
                        with st.expander("🔗 Quick Access: Click a club name to view teams", expanded=False):
                            # Display clubs in a grid of buttons
                            num_cols = 3
                            club_list = club_df['Club Name'].tolist()
                            for i in range(0, len(club_list), num_cols):
                                cols = st.columns(num_cols)
                                for j, col in enumerate(cols):
                                    if i + j < len(club_list):
                                        club_name = club_list[i + j]
                                        team_count = club_df[club_df['Club Name'] == club_name]['Teams Missing State Code'].iloc[0]
                                        with col:
                                            if st.button(
                                                f"📋 {club_name}\n({team_count} teams)",
                                                key=f"club_btn_{club_name}",
                                                use_container_width=True
                                            ):
                                                st.session_state.selected_club_missing_state = club_name
                                                st.rerun()
                        
                        # Display teams for selected club
                        if st.session_state.selected_club_missing_state:
                            selected_club_name = st.session_state.selected_club_missing_state
                            
                            # Fetch teams missing state codes for this club
                            with st.spinner(f"Loading teams missing state codes for {selected_club_name}..."):
                                try:
                                    club_teams_missing_result = execute_with_retry(
                                        lambda: db.table('teams').select(
                                            'team_id_master, team_name, club_name, age_group, gender, state, state_code'
                                        ).eq('club_name', selected_club_name).is_('state_code', 'null'),
                                        max_retries=3,
                                        base_delay=2.0
                                    )
                                    club_teams_missing = pd.DataFrame(club_teams_missing_result.data) if club_teams_missing_result.data else pd.DataFrame()
                                    
                                    if not club_teams_missing.empty:
                                        st.markdown(f"### 📋 **{selected_club_name}**")
                                        st.info(f"Showing **{len(club_teams_missing)}** teams missing state codes")
                                        st.success("💡 **INSTRUCTIONS:** Double-click on any cell in the 'State Code' column below to edit it. Type a 2-letter state code (e.g., TX, CA, NY). Leave blank cells empty.")
                                        
                                        # Prepare teams for editing - include team_id_master for updates
                                        teams_display = club_teams_missing[['team_id_master', 'team_name', 'age_group', 'gender', 'state', 'state_code']].copy()
                                        teams_display = teams_display.rename(columns={
                                            'team_id_master': 'Team ID',
                                            'team_name': 'Team Name',
                                            'age_group': 'Age Group',
                                            'gender': 'Gender',
                                            'state': 'State (Full)',
                                            'state_code': 'State Code'
                                        })
                                        
                                        # Display editable table
                                        edited_teams_df = st.data_editor(
                                            teams_display,
                                            column_config={
                                                'Team ID': st.column_config.NumberColumn('Team ID', disabled=True),
                                                'Team Name': st.column_config.TextColumn('Team Name', disabled=True),
                                                'Age Group': st.column_config.TextColumn('Age Group', disabled=True),
                                                'Gender': st.column_config.TextColumn('Gender', disabled=True),
                                                'State (Full)': st.column_config.TextColumn('State (Full)', disabled=True),
                                                'State Code': st.column_config.TextColumn(
                                                    'State Code',
                                                    help="💡 Double-click to edit. Enter 2-letter state code (e.g., CA, TX, WA). Leave blank if unknown.",
                                                    max_chars=2,
                                                    default="",
                                                    required=False
                                                )
                                            },
                                            use_container_width=True,
                                            hide_index=True,
                                            num_rows="fixed"
                                        )
                                        
                                        # Apply updates button
                                        apply_clicked = st.button("💾 Apply State Code Updates", type="primary", use_container_width=True, key=f"apply_individual_updates_{selected_club_name}")
                                        
                                        if apply_clicked:
                                            # Convert State Code column to string, handling NaN values
                                            edited_teams_df['State Code'] = edited_teams_df['State Code'].fillna('').astype(str).str.strip().str.upper()
                                            
                                            # Find teams that have valid state codes entered (ignore blanks)
                                            # Filter for rows with exactly 2 characters that are valid state codes
                                            updates_to_apply = edited_teams_df[
                                                (edited_teams_df['State Code'].str.len() == 2) &
                                                (edited_teams_df['State Code'] != '') &
                                                (~edited_teams_df['State Code'].isin(['NA', 'NAN', 'NONE', 'NUL']))
                                            ]
                                            
                                            # Further filter to only include valid state codes
                                            valid_state_codes = set(STATE_CODE_TO_NAME.keys())
                                            updates_to_apply = updates_to_apply[
                                                updates_to_apply['State Code'].isin(valid_state_codes)
                                            ]
                                            
                                            if updates_to_apply.empty:
                                                st.error("⚠️ No valid state codes found to apply!")
                                                st.info("💡 **Blank cells are fine** - only teams with state codes entered will be updated.")
                                                st.info("💡 Make sure you've entered **2-letter state codes** (e.g., TX, CA, NY) in the State Code column above.")
                                                
                                                # Show what was actually captured
                                                rows_with_2_chars = edited_teams_df[edited_teams_df['State Code'].str.len() == 2]
                                                if not rows_with_2_chars.empty:
                                                    st.warning(f"Found {len(rows_with_2_chars)} rows with 2-character codes, but they may not be valid state codes.")
                                                
                                                # Debug info
                                                with st.expander("🔍 Debug: See what was captured", expanded=True):
                                                    st.write("**Total rows:**", len(edited_teams_df))
                                                    st.write("**Rows with 2-character codes:**", len(rows_with_2_chars))
                                                    st.write("**Sample of State Code values:**")
                                                    st.dataframe(edited_teams_df[['Team Name', 'State Code']].head(20), use_container_width=True)
                                                    if not rows_with_2_chars.empty:
                                                        st.write("**2-character codes found:**", rows_with_2_chars['State Code'].unique().tolist())
                                                        st.write("**Valid state codes:**", [code for code in rows_with_2_chars['State Code'].unique() if code in valid_state_codes])
                                                    else:
                                                        st.write("**No 2-character codes found.** Make sure you typed state codes like 'TX', 'CA', etc.")
                                            else:
                                                with st.spinner(f"Updating {len(updates_to_apply)} teams..."):
                                                    updated_count = 0
                                                    error_count = 0
                                                    errors = []
                                                    
                                                    for _, row in updates_to_apply.iterrows():
                                                        team_id = int(row['Team ID'])
                                                        state_code = str(row['State Code']).strip().upper()
                                                        team_name = row['Team Name']
                                                        
                                                        # Validate state code
                                                        if state_code not in STATE_CODE_TO_NAME:
                                                            error_msg = f"Invalid state code '{state_code}' for {team_name} (ID: {team_id})"
                                                            errors.append(error_msg)
                                                            error_count += 1
                                                            continue
                                                        
                                                        state_name = STATE_CODE_TO_NAME[state_code]
                                                        
                                                        try:
                                                            result = db.table('teams').update({
                                                                'state_code': state_code,
                                                                'state': state_name
                                                            }).eq('team_id_master', team_id).execute()
                                                            
                                                            if result.data:
                                                                updated_count += 1
                                                            else:
                                                                error_msg = f"No data returned for {team_name} (ID: {team_id})"
                                                                errors.append(error_msg)
                                                                error_count += 1
                                                        except Exception as e:
                                                            error_msg = f"Error updating {team_name} (ID: {team_id}): {str(e)}"
                                                            errors.append(error_msg)
                                                            error_count += 1
                                                    
                                                    if updated_count > 0:
                                                        st.success(f"✅ Successfully updated {updated_count} teams with state codes!")
                                                        if error_count > 0:
                                                            st.warning(f"⚠️ {error_count} teams had errors. See details below.")
                                                        time.sleep(1.5)
                                                        st.rerun()
                                                    else:
                                                        st.error(f"❌ Failed to update any teams. {error_count} errors occurred.")
                                                        if errors:
                                                            with st.expander("View Error Details"):
                                                                for err in errors[:20]:  # Show first 20 errors
                                                                    st.text(err)
                                                                if len(errors) > 20:
                                                                    st.text(f"... and {len(errors) - 20} more errors")
                                        
                                        # Bulk update section for this specific club
                                        st.divider()
                                        st.markdown("#### 🔧 Bulk Update State Code for This Club")
                                        
                                        col1, col2 = st.columns([2, 1])
                                        with col1:
                                            club_state_code = st.selectbox(
                                                "Select State Code to Apply",
                                                options=[''] + sorted(STATE_CODE_TO_NAME.keys()),
                                                key=f"club_state_{selected_club_name}",
                                                help="Select a state code to apply to all teams missing state codes for this club"
                                            )
                                        
                                        with col2:
                                            if club_state_code:
                                                state_name = STATE_CODE_TO_NAME[club_state_code]
                                                st.info(f"Will set state to: **{state_name}**")
                                        
                                        if st.button(
                                            f"🚀 Apply State Code '{club_state_code}' to All {len(club_teams_missing)} Teams",
                                            type="primary",
                                            use_container_width=True,
                                            disabled=not club_state_code or club_teams_missing.empty,
                                            key=f"apply_club_state_{selected_club_name}"
                                        ):
                                            if club_state_code and not club_teams_missing.empty:
                                                with st.spinner(f"Updating {len(club_teams_missing)} teams..."):
                                                    try:
                                                        team_ids = club_teams_missing['team_id_master'].tolist()
                                                        state_name = STATE_CODE_TO_NAME[club_state_code]
                                                        
                                                        # Update in batches
                                                        batch_size = 100
                                                        updated_count = 0
                                                        for i in range(0, len(team_ids), batch_size):
                                                            batch = team_ids[i:i + batch_size]
                                                            result = db.table('teams').update({
                                                                'state_code': club_state_code,
                                                                'state': state_name
                                                            }).in_('team_id_master', batch).execute()
                                                            updated_count += len(batch)
                                                        
                                                        st.success(f"✅ Successfully updated {updated_count} teams with state code '{club_state_code}' ({state_name})!")
                                                        time.sleep(1)
                                                        st.rerun()
                                                    except Exception as e:
                                                        st.error(f"Error updating teams: {e}")
                                                        import traceback
                                                        with st.expander("View Error Details"):
                                                            st.code(traceback.format_exc())
                                        
                                        st.divider()
                                    else:
                                        st.success(f"✅ **{selected_club_name}** has no teams missing state codes!")
                                except Exception as e:
                                    st.error(f"Error loading teams for {selected_club_name}: {e}")
                                    import traceback
                                    with st.expander("View Error Details"):
                                        st.code(traceback.format_exc())
                        
                        # Display editable table
                        edited_club_df = st.data_editor(
                            club_df,
                            column_config={
                                'Club Name': st.column_config.TextColumn('Club Name', disabled=True),
                                'Teams Missing State Code': st.column_config.NumberColumn('Teams Missing State Code', disabled=True),
                                'State Code': st.column_config.TextColumn(
                                    'State Code',
                                    help="Enter 2-letter state code (e.g., CA, TX, WA). Leave empty if unknown.",
                                    max_chars=2,
                                    default=""
                                )
                            },
                            use_container_width=True,
                            hide_index=True,
                            num_rows="fixed"
                        )
                        
                        # Check if any clubs in the table are multi-state clubs
                        multi_state_clubs_in_table = []
                        if 'multi_state_clubs_info' in st.session_state and st.session_state.multi_state_clubs_info:
                            for club_name in club_df['Club Name'].tolist():
                                if club_name in st.session_state.multi_state_clubs_info:
                                    multi_state_clubs_in_table.append(club_name)
                        
                        if multi_state_clubs_in_table:
                            st.warning(f"⚠️ **Warning:** The following clubs span multiple states: {', '.join(multi_state_clubs_in_table)}. "
                                      f"Review these clubs in the 'Clubs Spanning Multiple States' section above before bulk updating. "
                                      f"Bulk updates will apply the same state code to ALL teams for a club.")
                        
                        # Bulk update button
                        if st.button("🚀 Apply State Codes to All Teams", type="primary", use_container_width=True):
                            updates_to_apply = edited_club_df[
                                (edited_club_df['State Code'].notna()) & 
                                (edited_club_df['State Code'].str.strip() != '') &
                                (edited_club_df['State Code'].str.len() == 2)
                            ]
                            
                            if updates_to_apply.empty:
                                st.warning("⚠️ No valid state codes to apply. Please enter 2-letter state codes.")
                            else:
                                with st.spinner(f"Updating teams for {len(updates_to_apply)} clubs..."):
                                    updated_count = 0
                                    error_count = 0
                                    
                                    for _, row in updates_to_apply.iterrows():
                                        club_name = row['Club Name']
                                        state_code = row['State Code'].strip().upper()
                                        
                                        # Validate state code
                                        if state_code not in STATE_CODE_TO_NAME:
                                            st.warning(f"⚠️ Invalid state code '{state_code}' for {club_name}. Skipping.")
                                            error_count += 1
                                            continue
                                        
                                        state_name = STATE_CODE_TO_NAME[state_code]
                                        
                                        try:
                                            # Find all teams with this club name that are missing state codes
                                            teams_to_update = filtered_df[
                                                (filtered_df['club_name'] == club_name) &
                                                (filtered_df['state_code'].isna())
                                            ]
                                            
                                            if teams_to_update.empty:
                                                continue
                                            
                                            team_ids = teams_to_update['team_id_master'].tolist()
                                            
                                            # Update in batches
                                            batch_size = 100
                                            for i in range(0, len(team_ids), batch_size):
                                                batch = team_ids[i:i + batch_size]
                                                result = db.table('teams').update({
                                                    'state_code': state_code,
                                                    'state': state_name
                                                }).in_('team_id_master', batch).execute()
                                                
                                                updated_count += len(batch)
                                        
                                        except Exception as e:
                                            st.error(f"Error updating {club_name}: {e}")
                                            error_count += len(teams_to_update)
                                    
                                    if updated_count > 0:
                                        st.success(f"✅ Successfully updated {updated_count} teams with state codes!")
                                        time.sleep(1)
                                        st.rerun()
                                    else:
                                        st.info("No teams were updated. They may have already been updated.")
                                    
                                    if error_count > 0:
                                        st.warning(f"⚠️ {error_count} teams had errors during update.")
                        
                        st.info("💡 **Tip:** Enter state codes in the table above, then click 'Apply State Codes to All Teams' to bulk update all teams for each club!")

                    # ============================================================================
                    # INDIVIDUAL TEAM STATE CODE EDITOR - Enhanced for multi-state clubs
                    # ============================================================================
                    st.divider()
                    st.subheader("🔧 Individual Team State Code Editor")
                    st.markdown("""
                    **For clubs with teams in multiple states** (like Sting Soccer Club), use this section to:
                    1. Select a club and see ALL teams missing state codes
                    2. Filter teams by name, age group, or gender
                    3. Use **Quick Assign** to set the same state code for multiple selected teams
                    4. Review all pending changes before saving
                    """)

                    # Initialize session state for individual team editor
                    if 'individual_editor_club' not in st.session_state:
                        st.session_state.individual_editor_club = None
                    if 'pending_state_changes' not in st.session_state:
                        st.session_state.pending_state_changes = {}  # {team_id: {'state_code': XX, 'team_name': YY}}
                    if 'selected_teams_for_quick_assign' not in st.session_state:
                        st.session_state.selected_teams_for_quick_assign = set()

                    # Get ALL clubs with missing state codes (not just top 20)
                    all_clubs_missing = filtered_df['club_name'].dropna().value_counts()

                    if not all_clubs_missing.empty:
                        # Club selector with search
                        col1, col2, col3 = st.columns([2, 1, 1])

                        with col1:
                            # Create club options with team count
                            club_options_with_count = [''] + [f"{club} ({count} teams)" for club, count in all_clubs_missing.items()]
                            club_names_only = [''] + all_clubs_missing.index.tolist()

                            default_idx = 0
                            if st.session_state.individual_editor_club and st.session_state.individual_editor_club in club_names_only:
                                default_idx = club_names_only.index(st.session_state.individual_editor_club)

                            selected_club_display = st.selectbox(
                                "🔍 Select Club to Edit Teams",
                                options=club_options_with_count,
                                index=default_idx,
                                key="individual_club_selector",
                                help="Select a club to view and edit state codes for all its teams"
                            )

                            # Extract actual club name from display string
                            if selected_club_display:
                                selected_individual_club = selected_club_display.rsplit(' (', 1)[0]
                                st.session_state.individual_editor_club = selected_individual_club
                            else:
                                st.session_state.individual_editor_club = None

                        with col2:
                            if st.session_state.individual_editor_club:
                                if st.button("🔄 Clear Selection", key="clear_individual_club", use_container_width=True):
                                    st.session_state.individual_editor_club = None
                                    st.session_state.pending_state_changes = {}
                                    st.session_state.selected_teams_for_quick_assign = set()
                                    st.rerun()

                        with col3:
                            if st.session_state.pending_state_changes:
                                if st.button("🗑️ Clear All Changes", key="clear_pending_changes", use_container_width=True):
                                    st.session_state.pending_state_changes = {}
                                    st.rerun()

                        # Show teams for selected club
                        if st.session_state.individual_editor_club:
                            selected_club_name = st.session_state.individual_editor_club

                            # Check if this is a multi-state club
                            is_multi_state = False
                            multi_state_info = None
                            if 'multi_state_clubs_info' in st.session_state and selected_club_name in st.session_state.multi_state_clubs_info:
                                is_multi_state = True
                                multi_state_info = st.session_state.multi_state_clubs_info[selected_club_name]
                                st.warning(f"⚠️ **Multi-State Club:** {selected_club_name} has teams in {len(multi_state_info['states'])} states: {', '.join(multi_state_info['states'])}")

                            # Fetch all teams missing state codes for this club
                            with st.spinner(f"Loading teams for {selected_club_name}..."):
                                try:
                                    club_teams_result = execute_with_retry(
                                        lambda: db.table('teams').select(
                                            'team_id_master, team_name, club_name, age_group, gender, state, state_code'
                                        ).eq('club_name', selected_club_name).is_('state_code', 'null'),
                                        max_retries=3,
                                        base_delay=2.0
                                    )
                                    club_teams_df = pd.DataFrame(club_teams_result.data) if club_teams_result.data else pd.DataFrame()

                                    if not club_teams_df.empty:
                                        st.markdown(f"### 📋 {selected_club_name} - {len(club_teams_df)} teams missing state codes")

                                        # Filtering options
                                        st.markdown("#### 🔍 Filter Teams")
                                        filter_col1, filter_col2, filter_col3 = st.columns(3)

                                        with filter_col1:
                                            team_name_filter = st.text_input(
                                                "Team Name Contains",
                                                key="team_name_filter",
                                                placeholder="e.g., 'Elite', '2012', 'Boys'",
                                                help="Filter teams by name (case-insensitive)"
                                            )

                                        with filter_col2:
                                            age_groups = ['All'] + sorted(club_teams_df['age_group'].dropna().unique().tolist())
                                            age_filter = st.selectbox("Age Group", age_groups, key="age_filter_individual")

                                        with filter_col3:
                                            gender_options = ['All', 'Male', 'Female']
                                            gender_filter = st.selectbox("Gender", gender_options, key="gender_filter_individual")

                                        # Apply filters
                                        display_df = club_teams_df.copy()
                                        if team_name_filter:
                                            display_df = display_df[display_df['team_name'].str.contains(team_name_filter, case=False, na=False)]
                                        if age_filter != 'All':
                                            display_df = display_df[display_df['age_group'] == age_filter]
                                        if gender_filter != 'All':
                                            display_df = display_df[display_df['gender'] == gender_filter]

                                        st.info(f"Showing **{len(display_df)}** of {len(club_teams_df)} teams (after filters)")

                                        # Quick Assign Section
                                        st.markdown("#### ⚡ Quick Assign State Code")
                                        st.markdown("Select teams below, then assign a state code to all selected teams at once.")

                                        quick_col1, quick_col2, quick_col3 = st.columns([2, 1, 1])

                                        with quick_col1:
                                            quick_state_code = st.selectbox(
                                                "State Code to Assign",
                                                options=[''] + sorted(STATE_CODE_TO_NAME.keys()),
                                                key="quick_assign_state",
                                                help="Select a state code to apply to selected teams"
                                            )

                                        with quick_col2:
                                            if quick_state_code:
                                                st.markdown(f"**{STATE_CODE_TO_NAME[quick_state_code]}**")

                                        with quick_col3:
                                            select_all_filtered = st.button(
                                                f"☑️ Select All {len(display_df)}",
                                                key="select_all_filtered",
                                                help="Add all filtered teams to selection"
                                            )
                                            if select_all_filtered:
                                                for team_id in display_df['team_id_master'].tolist():
                                                    st.session_state.selected_teams_for_quick_assign.add(str(team_id))
                                                st.rerun()

                                        # Apply quick assign
                                        quick_assign_col1, quick_assign_col2 = st.columns([1, 1])
                                        with quick_assign_col1:
                                            selected_count = len(st.session_state.selected_teams_for_quick_assign)
                                            if st.button(
                                                f"🎯 Apply {quick_state_code} to {selected_count} Selected Teams",
                                                key="apply_quick_assign",
                                                disabled=not quick_state_code or selected_count == 0,
                                                type="primary"
                                            ):
                                                for team_id in st.session_state.selected_teams_for_quick_assign:
                                                    team_row = club_teams_df[club_teams_df['team_id_master'] == team_id]
                                                    if not team_row.empty:
                                                        team_name = team_row['team_name'].iloc[0]
                                                        st.session_state.pending_state_changes[team_id] = {
                                                            'state_code': quick_state_code,
                                                            'team_name': team_name
                                                        }
                                                st.session_state.selected_teams_for_quick_assign = set()
                                                st.rerun()

                                        with quick_assign_col2:
                                            if st.button("🔲 Clear Selection", key="clear_selection"):
                                                st.session_state.selected_teams_for_quick_assign = set()
                                                st.rerun()

                                        # Team selection table
                                        st.markdown("#### 📝 Select Teams")

                                        # Build display data with selection checkboxes and pending status
                                        teams_for_display = []
                                        for _, row in display_df.iterrows():
                                            team_id = str(row['team_id_master'])
                                            is_selected = team_id in st.session_state.selected_teams_for_quick_assign
                                            pending_change = st.session_state.pending_state_changes.get(team_id)

                                            teams_for_display.append({
                                                'Select': is_selected,
                                                'Team ID': team_id,
                                                'Team Name': row['team_name'],
                                                'Age Group': row['age_group'],
                                                'Gender': row['gender'],
                                                'Pending State': pending_change['state_code'] if pending_change else '',
                                                'Current State': row['state'] if pd.notna(row['state']) else ''
                                            })

                                        teams_edit_df = pd.DataFrame(teams_for_display)

                                        # Use data_editor for selection
                                        edited_selection = st.data_editor(
                                            teams_edit_df,
                                            column_config={
                                                'Select': st.column_config.CheckboxColumn(
                                                    'Select',
                                                    help="Check to include in Quick Assign",
                                                    default=False
                                                ),
                                                'Team ID': st.column_config.TextColumn('Team ID', disabled=True, width="small"),
                                                'Team Name': st.column_config.TextColumn('Team Name', disabled=True),
                                                'Age Group': st.column_config.TextColumn('Age', disabled=True, width="small"),
                                                'Gender': st.column_config.TextColumn('Gender', disabled=True, width="small"),
                                                'Pending State': st.column_config.TextColumn(
                                                    'Pending',
                                                    disabled=True,
                                                    width="small",
                                                    help="State code pending save"
                                                ),
                                                'Current State': st.column_config.TextColumn('Current', disabled=True, width="small")
                                            },
                                            use_container_width=True,
                                            hide_index=True,
                                            num_rows="fixed",
                                            height=400,
                                            key=f"team_selection_{selected_club_name}"
                                        )

                                        # Update selections based on checkboxes
                                        new_selections = set()
                                        for _, row in edited_selection.iterrows():
                                            if row['Select']:
                                                new_selections.add(row['Team ID'])

                                        if new_selections != st.session_state.selected_teams_for_quick_assign:
                                            st.session_state.selected_teams_for_quick_assign = new_selections

                                        # Pending Changes Summary
                                        if st.session_state.pending_state_changes:
                                            st.divider()
                                            st.markdown("#### 📊 Pending Changes Summary")

                                            # Group by state code
                                            state_groups = {}
                                            for team_id, change in st.session_state.pending_state_changes.items():
                                                sc = change['state_code']
                                                if sc not in state_groups:
                                                    state_groups[sc] = []
                                                state_groups[sc].append(change['team_name'])

                                            # Display summary
                                            summary_cols = st.columns(min(len(state_groups), 4))
                                            for idx, (state_code, team_names) in enumerate(state_groups.items()):
                                                col_idx = idx % len(summary_cols)
                                                with summary_cols[col_idx]:
                                                    state_name = STATE_CODE_TO_NAME.get(state_code, state_code)
                                                    st.metric(f"{state_code} ({state_name})", f"{len(team_names)} teams")

                                            st.info(f"**Total: {len(st.session_state.pending_state_changes)} teams** will be updated")

                                            # Show detailed pending changes
                                            with st.expander("📋 View All Pending Changes", expanded=False):
                                                pending_list = []
                                                for team_id, change in st.session_state.pending_state_changes.items():
                                                    pending_list.append({
                                                        'Team Name': change['team_name'],
                                                        'State Code': change['state_code'],
                                                        'State Name': STATE_CODE_TO_NAME.get(change['state_code'], '')
                                                    })
                                                pending_df = pd.DataFrame(pending_list)
                                                pending_df = pending_df.sort_values(['State Code', 'Team Name'])
                                                st.dataframe(pending_df, use_container_width=True, hide_index=True)

                                            # Remove individual changes
                                            remove_state = st.selectbox(
                                                "Remove pending changes by state:",
                                                options=[''] + list(state_groups.keys()),
                                                key="remove_state_group"
                                            )
                                            if remove_state and st.button(f"🗑️ Remove All {remove_state} Changes", key="remove_state_changes"):
                                                teams_to_remove = [tid for tid, change in st.session_state.pending_state_changes.items()
                                                                   if change['state_code'] == remove_state]
                                                for tid in teams_to_remove:
                                                    del st.session_state.pending_state_changes[tid]
                                                st.rerun()

                                            # Save Changes Button
                                            st.divider()
                                            if st.button(
                                                f"💾 Save All {len(st.session_state.pending_state_changes)} Changes to Database",
                                                type="primary",
                                                use_container_width=True,
                                                key="save_all_pending_changes"
                                            ):
                                                with st.spinner(f"Updating {len(st.session_state.pending_state_changes)} teams..."):
                                                    updated_count = 0
                                                    error_count = 0
                                                    errors = []

                                                    # Group updates by state code for potential batch optimization
                                                    for team_id, change in st.session_state.pending_state_changes.items():
                                                        state_code = change['state_code']
                                                        team_name = change['team_name']

                                                        if state_code not in STATE_CODE_TO_NAME:
                                                            errors.append(f"Invalid state code '{state_code}' for {team_name}")
                                                            error_count += 1
                                                            continue

                                                        state_name = STATE_CODE_TO_NAME[state_code]

                                                        try:
                                                            result = db.table('teams').update({
                                                                'state_code': state_code,
                                                                'state': state_name
                                                            }).eq('team_id_master', team_id).execute()

                                                            if result.data:
                                                                updated_count += 1
                                                            else:
                                                                errors.append(f"No data returned for {team_name}")
                                                                error_count += 1
                                                        except Exception as e:
                                                            errors.append(f"Error updating {team_name}: {str(e)}")
                                                            error_count += 1

                                                    if updated_count > 0:
                                                        st.success(f"✅ Successfully updated {updated_count} teams!")
                                                        st.session_state.pending_state_changes = {}
                                                        st.session_state.selected_teams_for_quick_assign = set()
                                                        if error_count > 0:
                                                            st.warning(f"⚠️ {error_count} teams had errors")
                                                        time.sleep(1.5)
                                                        st.rerun()
                                                    else:
                                                        st.error(f"❌ Failed to update any teams. {error_count} errors occurred.")
                                                        if errors:
                                                            with st.expander("View Error Details"):
                                                                for err in errors[:20]:
                                                                    st.text(err)
                                        else:
                                            st.info("💡 **No pending changes.** Select teams above and use Quick Assign to add state codes.")

                                    else:
                                        st.success(f"✅ **{selected_club_name}** has no teams missing state codes!")

                                except Exception as e:
                                    st.error(f"Error loading teams: {e}")
                                    import traceback
                                    with st.expander("View Error Details"):
                                        st.code(traceback.format_exc())
                    else:
                        st.info("No clubs with teams missing state codes found.")
            else:
                st.success("🎉 All teams have state codes! No action needed.")

        except Exception as e:
            st.error(f"Error loading teams without state codes: {e}")
            import traceback
            with st.expander("View Error Details"):
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

            # Age, Gender, and State filters to narrow down team selection
            st.markdown("##### Filter Teams")
            filter_col1, filter_col2, filter_col3 = st.columns(3)

            with filter_col1:
                manual_age_filter = st.selectbox(
                    "Age Group",
                    options=[""] + [f"u{i}" for i in range(8, 20)],
                    key="manual_merge_age"
                )

            with filter_col2:
                manual_gender_filter = st.selectbox(
                    "Gender",
                    options=["", "Male", "Female"],
                    key="manual_merge_gender"
                )

            with filter_col3:
                # Common US state codes for youth soccer
                state_codes = ["", "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
                              "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
                              "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
                              "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
                              "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"]
                manual_state_filter = st.selectbox(
                    "State (optional)",
                    options=state_codes,
                    key="manual_merge_state"
                )

            # Only show team selection if required filters are set
            if not manual_age_filter or not manual_gender_filter:
                st.info("👆 Select age group and gender above to see teams")
                deprecated_team_id = None
                canonical_team_id = None
                all_teams = []
                team_options = {}
            else:
                # Fetch filtered teams
                try:
                    age_num = manual_age_filter.lower().replace('u', '')
                    query = db.table('teams') \
                        .select('team_id_master, team_name, club_name, state_code, age_group, gender') \
                        .eq('is_deprecated', False) \
                        .eq('gender', manual_gender_filter) \
                        .or_(f"age_group.eq.{age_num},age_group.eq.u{age_num},age_group.eq.U{age_num}")

                    # Add state filter if selected
                    if manual_state_filter:
                        query = query.eq('state_code', manual_state_filter)

                    teams_result = execute_with_retry(
                        lambda q=query: q.order('team_name').limit(2000)
                    )
                    all_teams = teams_result.data or []

                    filter_desc = f"{manual_age_filter} {manual_gender_filter}"
                    if manual_state_filter:
                        filter_desc += f" in {manual_state_filter}"

                    if not all_teams:
                        st.warning(f"No teams found for {filter_desc}")
                        team_options = {}
                    else:
                        st.success(f"Found {len(all_teams)} teams for {filter_desc}")

                        # Create team options with more detail
                        team_options = {
                            f"{t['team_name']} ({t.get('club_name', 'N/A')}) - {t.get('state_code', '??')}": t['team_id_master']
                            for t in all_teams
                        }

                except Exception as e:
                    st.error(f"Failed to load teams: {e}")
                    all_teams = []
                    team_options = {}

                # Team selection columns
                col1, col2 = st.columns(2)

                with col1:
                    st.markdown("##### Team to Deprecate (will be hidden)")

                    if team_options:
                        deprecated_selection = st.selectbox(
                            "Select duplicate team to deprecate",
                            options=[""] + list(team_options.keys()),
                            key="deprecated_team"
                        )
                        deprecated_team_id = team_options.get(deprecated_selection) if deprecated_selection else None
                    else:
                        deprecated_team_id = None

                with col2:
                    st.markdown("##### Canonical Team (keep this one)")

                    if team_options and deprecated_team_id:
                        # Filter out the deprecated team from options
                        canonical_options = {k: v for k, v in team_options.items() if v != deprecated_team_id}
                        canonical_selection = st.selectbox(
                            "Select team to keep",
                            options=[""] + list(canonical_options.keys()),
                            key="canonical_team"
                        )
                        canonical_team_id = canonical_options.get(canonical_selection) if canonical_selection else None
                    else:
                        if not deprecated_team_id and team_options:
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

                    # Parse RPC response - Supabase wraps JSONB in weird ways
                    response = result.data

                    # Unwrap list if needed
                    if isinstance(response, list) and len(response) > 0:
                        response = response[0]

                    # Check if success is buried in 'details' field (Supabase JSONB quirk)
                    if isinstance(response, dict) and 'details' in response:
                        details_str = str(response.get('details', ''))

                        # Check for success pattern (handle various quote styles and spacing)
                        import re
                        success_match = re.search(r'success["\']?\s*:\s*true', details_str, re.IGNORECASE)

                        if success_match:
                            # Extract the message from details
                            msg_match = re.search(r'message["\']?\s*:\s*["\']([^"\']+)["\']', details_str)
                            if msg_match:
                                st.success(f"✅ {msg_match.group(1)}")
                            else:
                                st.success("✅ Merge completed successfully!")
                            # Don't show balloons for already-merged case
                            if 'already_merged' not in details_str.lower():
                                st.balloons()
                        elif re.search(r'success["\']?\s*:\s*false', details_str, re.IGNORECASE):
                            # Extract error message
                            err_match = re.search(r'error["\']?\s*:\s*["\']([^"\']+)["\']', details_str)
                            if err_match:
                                st.error(f"❌ Merge failed: {err_match.group(1)}")
                            else:
                                st.error(f"❌ Merge failed - check details")
                        else:
                            # Unknown response but might have worked - check database
                            st.warning(f"⚠️ Merge may have completed - please verify in database")
                    elif isinstance(response, dict) and 'success' in response:
                        # Direct response (no wrapper)
                        if response.get('success') == True:
                            if response.get('already_merged'):
                                st.success(f"✅ {response.get('message', 'Team is already merged')}")
                            else:
                                merge_id = response.get('merge_id', 'unknown')
                                games_affected = response.get('games_affected', 0)
                                aliases_updated = response.get('aliases_updated', 0)
                                cascaded_teams = response.get('cascaded_teams', 0)
                                st.success(f"✅ Successfully merged teams! Merge ID: {merge_id}")
                                stats_msg = f"📊 Games affected: {games_affected} | Aliases updated: {aliases_updated}"
                                if cascaded_teams > 0:
                                    stats_msg += f" | Cascaded merges: {cascaded_teams}"
                                st.info(stats_msg)
                                st.balloons()
                        else:
                            st.error(f"❌ Merge failed: {response.get('error', 'Unknown error')}")
                    else:
                        st.warning(f"Unexpected response format: {response}")

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
            filter_row1 = st.columns(4)

            with filter_row1[0]:
                age_filter = st.selectbox(
                    "Age Group",
                    options=[""] + [f"u{i}" for i in range(8, 20)],
                    key="suggest_age"
                )

            with filter_row1[1]:
                gender_filter = st.selectbox(
                    "Gender",
                    options=["", "Male", "Female"],
                    key="suggest_gender"
                )

            with filter_row1[2]:
                # State filter (optional)
                state_codes = ["", "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
                              "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
                              "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
                              "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
                              "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"]
                state_filter = st.selectbox(
                    "State (optional)",
                    options=state_codes,
                    key="suggest_state"
                )

            with filter_row1[3]:
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

            def count_games_per_team(team_ids, games_data):
                """Count total games for each team from games data"""
                game_counts = {tid: 0 for tid in team_ids}
                for g in games_data:
                    home_id = g.get('home_team_master_id')
                    away_id = g.get('away_team_master_id')
                    if home_id in game_counts:
                        game_counts[home_id] += 1
                    if away_id in game_counts:
                        game_counts[away_id] += 1
                return game_counts

            # Button to trigger search - stores results in session state
            if st.button("🔍 Find Potential Duplicates", type="primary"):
                if not age_filter or not gender_filter:
                    st.warning("Please select both age group and gender")
                else:
                    with st.spinner("Analyzing teams for duplicates (including opponent overlap)..."):
                        try:
                            # Fetch teams in cohort
                            age_num = age_filter.lower().replace('u', '')
                            query = db.table('teams') \
                                .select('team_id_master, team_name, club_name, state_code') \
                                .eq('is_deprecated', False) \
                                .eq('gender', gender_filter) \
                                .or_(f"age_group.eq.{age_num},age_group.eq.u{age_num},age_group.eq.U{age_num}")

                            # Add state filter if selected
                            if state_filter:
                                query = query.eq('state_code', state_filter)

                            teams_result = execute_with_retry(
                                lambda q=query: q.limit(2000)
                            )
                            teams = teams_result.data or []

                            # Build filter description for messages
                            filter_desc = f"{age_filter} {gender_filter}"
                            if state_filter:
                                filter_desc += f" in {state_filter}"

                            if len(teams) < 2:
                                st.session_state.suggestions = []
                                st.session_state.suggestions_message = f"Only {len(teams)} teams found for {filter_desc} - need at least 2 for comparison"
                            else:
                                st.info(f"Analyzing {len(teams)} {filter_desc} teams...")
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
                                st.text("Building opponent profiles and counting games...")
                                opponents_by_team = {}
                                for team_id in team_ids:
                                    opponents_by_team[team_id] = get_opponents(team_id, all_games)

                                # Count games per team
                                games_by_team = count_games_per_team(team_ids, all_games)

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

                                        raw_score = min(1.0, base_score + overlap_bonus)

                                        # CRITICAL: Cap the final confidence at the name similarity
                                        # If names are only 85% similar, confidence should never exceed 85%
                                        # This prevents "Colorado EDGE Eagles" matching "Colorado EDGE Legends" at 100%
                                        score = min(raw_score, name_sim * roman_penalty)

                                        if score >= min_confidence:
                                            suggestion_key = f"{team_a['team_id_master']}_{team_b['team_id_master']}"

                                            # Skip if dismissed
                                            if suggestion_key in st.session_state.dismissed_suggestions:
                                                continue

                                            # Get game counts for merge direction recommendation
                                            games_a = games_by_team.get(team_a['team_id_master'], 0)
                                            games_b = games_by_team.get(team_b['team_id_master'], 0)

                                            suggestions.append({
                                                'key': suggestion_key,
                                                'team_a_id': team_a['team_id_master'],
                                                'team_a_name': team_a['team_name'],
                                                'team_a_club': team_a.get('club_name', ''),
                                                'team_a_games': games_a,
                                                'team_b_id': team_b['team_id_master'],
                                                'team_b_name': team_b['team_name'],
                                                'team_b_club': team_b.get('club_name', ''),
                                                'team_b_games': games_b,
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

                        # Get game counts for header display
                        header_games_a = s.get('team_a_games', 0)
                        header_games_b = s.get('team_b_games', 0)
                        games_info = f" [{header_games_a}g ↔ {header_games_b}g]"

                        with st.expander(f"{confidence_color} {s['team_a_name']} ↔ {s['team_b_name']} ({s['confidence']:.0%} match){games_info}{warning_text}"):

                            # Warning banner for Roman numeral differences
                            if s['roman_diff']:
                                st.warning("⚠️ These teams have different Roman numerals (I, II, III, etc.) - likely different squads within the same club. NOT recommended to merge!")

                            # Get game counts with defaults for older cached suggestions
                            games_a = s.get('team_a_games', 0)
                            games_b = s.get('team_b_games', 0)

                            # Determine recommended merge direction based on game counts
                            if games_a > games_b:
                                recommended = "B→A"
                                rec_reason = f"Team A has more games ({games_a} vs {games_b})"
                            elif games_b > games_a:
                                recommended = "A→B"
                                rec_reason = f"Team B has more games ({games_b} vs {games_a})"
                            else:
                                recommended = None
                                rec_reason = "Equal game counts"

                            # Show recommendation banner if there's a clear winner
                            if recommended and not s['roman_diff']:
                                st.info(f"💡 **Recommended:** Merge **{recommended}** - {rec_reason}")

                            col1, col2 = st.columns(2)

                            with col1:
                                st.markdown(f"**Team A:** {s['team_a_name']}")
                                st.caption(f"Club: {s['team_a_club'] or 'N/A'}")
                                st.caption(f"ID: `{s['team_a_id'][:8]}...`")
                                # Show game count with visual indicator
                                if games_a >= games_b and games_a > 0:
                                    st.success(f"🎮 **{games_a} games**")
                                else:
                                    st.caption(f"🎮 {games_a} games")

                            with col2:
                                st.markdown(f"**Team B:** {s['team_b_name']}")
                                st.caption(f"Club: {s['team_b_club'] or 'N/A'}")
                                st.caption(f"ID: `{s['team_b_id'][:8]}...`")
                                # Show game count with visual indicator
                                if games_b >= games_a and games_b > 0:
                                    st.success(f"🎮 **{games_b} games**")
                                else:
                                    st.caption(f"🎮 {games_b} games")

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
                                        # Parse response - check for success in details or direct
                                        response = result.data
                                        if isinstance(response, list) and len(response) > 0:
                                            response = response[0]

                                        # Check if success is in 'details' field (Supabase JSONB quirk)
                                        import re
                                        details_str = str(response.get('details', '')) if isinstance(response, dict) else ''
                                        if re.search(r'success["\']?\s*:\s*true', details_str, re.IGNORECASE):
                                            st.session_state.dismissed_suggestions.add(s['key'])
                                            st.session_state.last_merge_success = f"✅ Merged! {s['team_a_name']} → {s['team_b_name']}"
                                            st.rerun()
                                        elif isinstance(response, dict) and response.get('success') == True:
                                            st.session_state.dismissed_suggestions.add(s['key'])
                                            st.session_state.last_merge_success = f"✅ Merged! {s['team_a_name']} → {s['team_b_name']}"
                                            st.rerun()
                                        else:
                                            # Extract error from details or response
                                            err_match = re.search(r'error["\']?\s*:\s*["\']([^"\']+)["\']', details_str)
                                            if err_match:
                                                err_msg = err_match.group(1)
                                            else:
                                                err_msg = response.get('error', 'Unknown error') if isinstance(response, dict) else 'Unknown error'
                                            st.error(f"❌ Merge failed: {err_msg}")
                                    except Exception as e:
                                        st.error(f"❌ Merge failed: {e}")

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
                                        # Parse response - check for success in details or direct
                                        response = result.data
                                        if isinstance(response, list) and len(response) > 0:
                                            response = response[0]

                                        # Check if success is in 'details' field (Supabase JSONB quirk)
                                        import re
                                        details_str = str(response.get('details', '')) if isinstance(response, dict) else ''
                                        if re.search(r'success["\']?\s*:\s*true', details_str, re.IGNORECASE):
                                            st.session_state.dismissed_suggestions.add(s['key'])
                                            st.session_state.last_merge_success = f"✅ Merged! {s['team_b_name']} → {s['team_a_name']}"
                                            st.rerun()
                                        elif isinstance(response, dict) and response.get('success') == True:
                                            st.session_state.dismissed_suggestions.add(s['key'])
                                            st.session_state.last_merge_success = f"✅ Merged! {s['team_b_name']} → {s['team_a_name']}"
                                            st.rerun()
                                        else:
                                            # Extract error from details or response
                                            err_match = re.search(r'error["\']?\s*:\s*["\']([^"\']+)["\']', details_str)
                                            if err_match:
                                                err_msg = err_match.group(1)
                                            else:
                                                err_msg = response.get('error', 'Unknown error') if isinstance(response, dict) else 'Unknown error'
                                            st.error(f"❌ Merge failed: {err_msg}")
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

# ============================================================================
# MANUAL TEAM EDIT SECTION
# ============================================================================
elif section == "✏️ Manual Team Edit":
    st.header("✏️ Manual Team Edit")
    st.markdown("**Look up any team and edit their information, aliases, and more**")

    db = get_database()

    if not db:
        st.error("Database connection not configured. Please set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in your .env file.")
    else:
        # Initialize session state for selected team
        if 'edit_selected_team' not in st.session_state:
            st.session_state.edit_selected_team = None

        # ========================
        # STEP 1: TEAM LOOKUP
        # ========================
        st.subheader("Step 1: Find a Team")

        # Search options in columns
        search_col1, search_col2, search_col3, search_col4 = st.columns([2, 2, 1, 1])

        with search_col1:
            search_name = st.text_input(
                "🔍 Search by Team Name or Club",
                placeholder="e.g., Barcelona FC, Legends Premier...",
                key="edit_search_name"
            )

        with search_col2:
            search_id = st.text_input(
                "🔑 Or Search by Team ID / Provider ID",
                placeholder="e.g., team_id_master or provider_team_id",
                key="edit_search_id"
            )

        with search_col3:
            search_age = st.selectbox(
                "Age Group",
                options=[""] + list(AGE_GROUPS.keys()),
                key="edit_search_age"
            )

        with search_col4:
            search_gender = st.selectbox(
                "Gender",
                options=["", "Male", "Female"],
                key="edit_search_gender"
            )

        # Search button
        if st.button("🔍 Search Teams", type="primary"):
            with st.spinner("Searching..."):
                try:
                    found_teams = []

                    # Search by ID first (exact match)
                    if search_id:
                        # Try team_id_master
                        id_result = execute_with_retry(
                            lambda: db.table('teams').select(
                                'team_id_master, provider_team_id, team_name, club_name, '
                                'age_group, gender, state_code, birth_year, is_deprecated, '
                                'created_at, updated_at, last_scraped_at, state, provider_id'
                            ).eq('team_id_master', search_id).limit(10)
                        )
                        if id_result.data:
                            found_teams.extend(id_result.data)

                        # Also try provider_team_id
                        pid_result = execute_with_retry(
                            lambda: db.table('teams').select(
                                'team_id_master, provider_team_id, team_name, club_name, '
                                'age_group, gender, state_code, birth_year, is_deprecated, '
                                'created_at, updated_at, last_scraped_at, state, provider_id'
                            ).eq('provider_team_id', search_id).limit(10)
                        )
                        if pid_result.data:
                            # Avoid duplicates
                            existing_ids = {t['team_id_master'] for t in found_teams}
                            for team in pid_result.data:
                                if team['team_id_master'] not in existing_ids:
                                    found_teams.append(team)

                    # Search by name (fuzzy)
                    if search_name or (not search_id):
                        query = db.table('teams').select(
                            'team_id_master, provider_team_id, team_name, club_name, '
                            'age_group, gender, state_code, birth_year, is_deprecated, '
                            'created_at, updated_at, last_scraped_at, state, provider_id'
                        )

                        if search_age:
                            query = query.eq('age_group', search_age)
                        if search_gender:
                            query = query.eq('gender', search_gender)

                        name_result = execute_with_retry(lambda: query.limit(500))

                        if name_result.data and search_name:
                            # Filter by similarity
                            for team in name_result.data:
                                name_sim = calculate_similarity(search_name.lower(), (team['team_name'] or '').lower())
                                club_sim = calculate_similarity(search_name.lower(), (team.get('club_name') or '').lower())
                                max_sim = max(name_sim, club_sim)

                                if max_sim >= 0.3:
                                    team['_similarity'] = max_sim
                                    existing_ids = {t['team_id_master'] for t in found_teams}
                                    if team['team_id_master'] not in existing_ids:
                                        found_teams.append(team)

                            # Sort by similarity
                            found_teams.sort(key=lambda x: x.get('_similarity', 0), reverse=True)
                        elif name_result.data and not search_name:
                            # If no name search, just use the filtered results
                            existing_ids = {t['team_id_master'] for t in found_teams}
                            for team in name_result.data[:50]:
                                if team['team_id_master'] not in existing_ids:
                                    found_teams.append(team)

                    # Store results in session state
                    st.session_state.edit_search_results = found_teams[:50]

                except Exception as e:
                    st.error(f"Search failed: {e}")
                    st.session_state.edit_search_results = []

        # Display search results
        if 'edit_search_results' in st.session_state and st.session_state.edit_search_results:
            st.success(f"Found {len(st.session_state.edit_search_results)} teams")

            # Create a selection table
            results_df = pd.DataFrame([
                {
                    'Team Name': t['team_name'],
                    'Club': t.get('club_name', ''),
                    'Age': t.get('age_group', ''),
                    'Gender': t.get('gender', ''),
                    'State': t.get('state_code', ''),
                    'Deprecated': '⚠️' if t.get('is_deprecated') else '',
                    'ID': t['team_id_master'][:8] + '...'
                }
                for t in st.session_state.edit_search_results
            ])

            st.dataframe(results_df, use_container_width=True, hide_index=True)

            # Team selector
            team_options = {
                f"{t['team_name']} ({t.get('age_group', '?')} {t.get('gender', '?')}) - {t.get('club_name', 'N/A')}": t['team_id_master']
                for t in st.session_state.edit_search_results
            }

            selected_team_label = st.selectbox(
                "Select a team to edit:",
                options=[""] + list(team_options.keys()),
                key="edit_team_selector"
            )

            if selected_team_label and selected_team_label in team_options:
                selected_team_id = team_options[selected_team_label]
                # Find the full team data
                selected_team = next(
                    (t for t in st.session_state.edit_search_results if t['team_id_master'] == selected_team_id),
                    None
                )
                if selected_team:
                    st.session_state.edit_selected_team = selected_team

        # ========================
        # STEP 2: DISPLAY & EDIT TEAM
        # ========================
        if st.session_state.edit_selected_team:
            team = st.session_state.edit_selected_team
            st.divider()

            # Create tabs for different editing sections
            info_tab, aliases_tab, games_tab = st.tabs([
                "📋 Team Information",
                "🔗 Aliases & Mappings",
                "📊 Game History"
            ])

            # ========================
            # TAB 1: TEAM INFORMATION
            # ========================
            with info_tab:
                st.subheader(f"Editing: {team['team_name']}")

                # Status badges
                status_cols = st.columns(4)
                with status_cols[0]:
                    if team.get('is_deprecated'):
                        st.error("⚠️ DEPRECATED")
                    else:
                        st.success("✅ ACTIVE")
                with status_cols[1]:
                    st.info(f"🆔 {team['team_id_master'][:12]}...")
                with status_cols[2]:
                    st.info(f"📅 Age: {team.get('age_group', 'N/A').upper()}")
                with status_cols[3]:
                    st.info(f"🏷️ Provider ID: {team.get('provider_team_id', 'N/A')}")

                st.markdown("---")

                # Editable fields in a form
                with st.form("edit_team_form"):
                    st.markdown("### Core Information")

                    edit_col1, edit_col2 = st.columns(2)

                    with edit_col1:
                        new_team_name = st.text_input(
                            "Team Name",
                            value=team.get('team_name', ''),
                            key="edit_team_name"
                        )
                        new_club_name = st.text_input(
                            "Club Name",
                            value=team.get('club_name', '') or '',
                            key="edit_club_name"
                        )
                        new_state = st.text_input(
                            "State (Full Name)",
                            value=team.get('state', '') or '',
                            key="edit_state_full"
                        )

                    with edit_col2:
                        # State code dropdown
                        state_codes = ["", "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
                                      "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
                                      "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
                                      "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
                                      "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"]
                        current_state_idx = state_codes.index(team.get('state_code', '')) if team.get('state_code', '') in state_codes else 0
                        new_state_code = st.selectbox(
                            "State Code",
                            options=state_codes,
                            index=current_state_idx,
                            key="edit_state_code"
                        )

                        # Age group - can change but be careful
                        age_options = list(AGE_GROUPS.keys())
                        current_age = team.get('age_group', '').lower()
                        current_age_idx = age_options.index(current_age) if current_age in age_options else 0
                        new_age_group = st.selectbox(
                            "Age Group",
                            options=age_options,
                            index=current_age_idx,
                            key="edit_age_group"
                        )

                        # Gender
                        gender_options = ["Male", "Female"]
                        current_gender_idx = gender_options.index(team.get('gender', 'Male')) if team.get('gender') in gender_options else 0
                        new_gender = st.selectbox(
                            "Gender",
                            options=gender_options,
                            index=current_gender_idx,
                            key="edit_gender"
                        )

                    st.markdown("### Metadata (Read-Only)")
                    meta_col1, meta_col2, meta_col3 = st.columns(3)

                    with meta_col1:
                        st.text_input("Team ID (Master)", value=team['team_id_master'], disabled=True)
                        st.text_input("Provider Team ID", value=team.get('provider_team_id', ''), disabled=True)

                    with meta_col2:
                        st.text_input("Birth Year", value=str(team.get('birth_year', '')), disabled=True)
                        st.text_input("Created At", value=str(team.get('created_at', ''))[:19], disabled=True)

                    with meta_col3:
                        st.text_input("Updated At", value=str(team.get('updated_at', ''))[:19] if team.get('updated_at') else '', disabled=True)
                        st.text_input("Last Scraped", value=str(team.get('last_scraped_at', ''))[:19] if team.get('last_scraped_at') else '', disabled=True)

                    # Submit button
                    submitted = st.form_submit_button("💾 Save Changes", type="primary", use_container_width=True)

                    if submitted:
                        try:
                            # Prepare update data
                            update_data = {
                                'team_name': new_team_name.strip(),
                                'club_name': new_club_name.strip() if new_club_name else None,
                                'state': new_state.strip() if new_state else None,
                                'state_code': new_state_code if new_state_code else None,
                                'age_group': new_age_group,
                                'gender': new_gender,
                                'birth_year': AGE_GROUPS.get(new_age_group, {}).get('birth_year'),
                                'updated_at': datetime.now().isoformat()
                            }

                            # Execute update
                            result = execute_with_retry(
                                lambda: db.table('teams').update(update_data).eq(
                                    'team_id_master', team['team_id_master']
                                )
                            )

                            st.success(f"✅ Successfully updated team: **{new_team_name}**")

                            # Update session state with new values
                            st.session_state.edit_selected_team.update(update_data)

                        except Exception as e:
                            st.error(f"❌ Failed to update team: {e}")
                            import traceback
                            with st.expander("View Error Details"):
                                st.code(traceback.format_exc())

                # Deprecation toggle (outside form for immediate action)
                st.markdown("---")
                st.markdown("### Team Status")

                if team.get('is_deprecated'):
                    st.warning("⚠️ This team is currently **DEPRECATED** (hidden from rankings)")
                    if st.button("🔄 Restore Team (Un-deprecate)", key="restore_team"):
                        try:
                            execute_with_retry(
                                lambda: db.table('teams').update({
                                    'is_deprecated': False,
                                    'updated_at': datetime.now().isoformat()
                                }).eq('team_id_master', team['team_id_master'])
                            )
                            st.success("✅ Team restored!")
                            st.session_state.edit_selected_team['is_deprecated'] = False
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Failed to restore: {e}")
                else:
                    st.success("✅ This team is **ACTIVE** (included in rankings)")
                    with st.expander("⚠️ Deprecate Team (Hide from Rankings)"):
                        st.warning("**Warning:** This will hide the team from all rankings. Use Team Merge Manager if you're merging duplicates.")
                        if st.button("⚠️ Deprecate This Team", type="secondary", key="deprecate_team"):
                            try:
                                execute_with_retry(
                                    lambda: db.table('teams').update({
                                        'is_deprecated': True,
                                        'updated_at': datetime.now().isoformat()
                                    }).eq('team_id_master', team['team_id_master'])
                                )
                                st.success("Team deprecated")
                                st.session_state.edit_selected_team['is_deprecated'] = True
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Failed to deprecate: {e}")

            # ========================
            # TAB 2: ALIASES & MAPPINGS
            # ========================
            with aliases_tab:
                st.subheader("Aliases & Provider Mappings")
                st.markdown(f"**Team:** {team['team_name']} ({team.get('age_group', '').upper()} {team.get('gender', '')})")

                # Fetch existing aliases
                try:
                    aliases_result = execute_with_retry(
                        lambda: db.table('team_alias_map').select(
                            'id, provider_id, provider_team_id, match_confidence, match_method, '
                            'review_status, division, created_at'
                        ).eq('team_id_master', team['team_id_master']).order('created_at', desc=True)
                    )

                    # Get providers for display
                    providers_result = execute_with_retry(
                        lambda: db.table('providers').select('id, name, code')
                    )
                    providers_map = {p['id']: p for p in (providers_result.data or [])}

                    if aliases_result.data:
                        st.success(f"Found **{len(aliases_result.data)}** alias mappings")

                        # Display each alias with edit/delete options
                        for idx, alias in enumerate(aliases_result.data):
                            provider = providers_map.get(alias['provider_id'], {})
                            provider_name = provider.get('name', 'Unknown')

                            with st.expander(f"📎 {provider_name}: `{alias['provider_team_id']}`", expanded=idx == 0):
                                alias_col1, alias_col2 = st.columns(2)

                                with alias_col1:
                                    st.write(f"**Provider:** {provider_name}")
                                    st.write(f"**Provider Team ID:** `{alias['provider_team_id']}`")
                                    st.write(f"**Match Method:** {alias.get('match_method', 'N/A')}")

                                with alias_col2:
                                    st.write(f"**Confidence:** {alias.get('match_confidence', 0):.0%}")
                                    st.write(f"**Status:** {alias.get('review_status', 'N/A')}")
                                    if alias.get('division'):
                                        st.write(f"**Division:** {alias['division']}")
                                    st.write(f"**Created:** {str(alias.get('created_at', ''))[:10]}")

                                # Edit alias
                                st.markdown("---")
                                edit_alias_col1, edit_alias_col2, edit_alias_col3 = st.columns([2, 2, 1])

                                with edit_alias_col1:
                                    new_provider_team_id = st.text_input(
                                        "Provider Team ID",
                                        value=alias['provider_team_id'],
                                        key=f"edit_alias_ptid_{alias['id']}"
                                    )

                                with edit_alias_col2:
                                    status_options = ['pending', 'approved', 'rejected', 'new_team']
                                    current_status_idx = status_options.index(alias.get('review_status', 'approved')) if alias.get('review_status') in status_options else 1
                                    new_status = st.selectbox(
                                        "Status",
                                        options=status_options,
                                        index=current_status_idx,
                                        key=f"edit_alias_status_{alias['id']}"
                                    )

                                with edit_alias_col3:
                                    new_division = st.text_input(
                                        "Division",
                                        value=alias.get('division', '') or '',
                                        key=f"edit_alias_div_{alias['id']}"
                                    )

                                action_col1, action_col2 = st.columns(2)

                                with action_col1:
                                    if st.button("💾 Update Alias", key=f"update_alias_{alias['id']}"):
                                        try:
                                            execute_with_retry(
                                                lambda aid=alias['id']: db.table('team_alias_map').update({
                                                    'provider_team_id': new_provider_team_id,
                                                    'review_status': new_status,
                                                    'division': new_division if new_division else None
                                                }).eq('id', aid)
                                            )
                                            st.success("✅ Alias updated!")
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"❌ Failed: {e}")

                                with action_col2:
                                    if st.button("🗑️ Delete Alias", key=f"delete_alias_{alias['id']}", type="secondary"):
                                        try:
                                            execute_with_retry(
                                                lambda aid=alias['id']: db.table('team_alias_map').delete().eq('id', aid)
                                            )
                                            st.success("✅ Alias deleted!")
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"❌ Failed: {e}")
                    else:
                        st.info("No aliases found for this team")

                except Exception as e:
                    st.error(f"Failed to load aliases: {e}")

                # Add new alias section
                st.markdown("---")
                st.subheader("➕ Add New Alias")

                with st.form("add_alias_form"):
                    new_alias_col1, new_alias_col2 = st.columns(2)

                    with new_alias_col1:
                        # Provider selector
                        try:
                            providers_list = [{'id': p['id'], 'name': p['name']} for p in (providers_result.data or [])]
                        except Exception:
                            providers_list = []

                        provider_options = {p['name']: p['id'] for p in providers_list}
                        selected_provider_name = st.selectbox(
                            "Provider",
                            options=list(provider_options.keys()),
                            key="new_alias_provider"
                        )

                        new_alias_provider_team_id = st.text_input(
                            "Provider Team ID *",
                            placeholder="e.g., 544491",
                            key="new_alias_ptid"
                        )

                    with new_alias_col2:
                        new_alias_confidence = st.slider(
                            "Match Confidence",
                            min_value=0.0,
                            max_value=1.0,
                            value=1.0,
                            step=0.1,
                            key="new_alias_confidence"
                        )

                        new_alias_method = st.selectbox(
                            "Match Method",
                            options=['dashboard_manual', 'exact_id', 'fuzzy_name', 'manual', 'direct_id'],
                            key="new_alias_method"
                        )

                        new_alias_division = st.text_input(
                            "Division (optional)",
                            placeholder="e.g., HD or AD",
                            key="new_alias_division"
                        )

                    alias_submitted = st.form_submit_button("➕ Add Alias", type="primary", use_container_width=True)

                    if alias_submitted:
                        if not new_alias_provider_team_id:
                            st.error("❌ Provider Team ID is required")
                        else:
                            try:
                                selected_provider_id = provider_options.get(selected_provider_name)

                                # Check if alias already exists
                                existing = execute_with_retry(
                                    lambda: db.table('team_alias_map').select('id').eq(
                                        'provider_id', selected_provider_id
                                    ).eq('provider_team_id', new_alias_provider_team_id)
                                )

                                if existing.data:
                                    st.error(f"❌ An alias for provider team ID `{new_alias_provider_team_id}` already exists!")
                                else:
                                    # Insert new alias
                                    alias_data = {
                                        'provider_id': selected_provider_id,
                                        'provider_team_id': new_alias_provider_team_id,
                                        'team_id_master': team['team_id_master'],
                                        'match_confidence': new_alias_confidence,
                                        'match_method': new_alias_method,
                                        'review_status': 'approved',
                                        'division': new_alias_division if new_alias_division else None,
                                        'created_at': datetime.now().isoformat()
                                    }

                                    execute_with_retry(
                                        lambda: db.table('team_alias_map').insert(alias_data)
                                    )

                                    st.success(f"✅ Alias created for `{new_alias_provider_team_id}`!")
                                    st.balloons()

                            except Exception as e:
                                st.error(f"❌ Failed to create alias: {e}")
                                import traceback
                                with st.expander("View Error Details"):
                                    st.code(traceback.format_exc())

            # ========================
            # TAB 3: GAME HISTORY
            # ========================
            with games_tab:
                st.subheader("Game History")
                st.markdown(f"**Team:** {team['team_name']}")

                try:
                    # Fetch recent games for this team
                    home_games = execute_with_retry(
                        lambda: db.table('games').select(
                            'game_id, game_date, home_team_master_id, away_team_master_id, '
                            'home_score, away_score, home_team_name, away_team_name'
                        ).eq('home_team_master_id', team['team_id_master']).order(
                            'game_date', desc=True
                        ).limit(50)
                    )

                    away_games = execute_with_retry(
                        lambda: db.table('games').select(
                            'game_id, game_date, home_team_master_id, away_team_master_id, '
                            'home_score, away_score, home_team_name, away_team_name'
                        ).eq('away_team_master_id', team['team_id_master']).order(
                            'game_date', desc=True
                        ).limit(50)
                    )

                    all_games = (home_games.data or []) + (away_games.data or [])
                    # Sort by date descending
                    all_games.sort(key=lambda x: x.get('game_date', ''), reverse=True)
                    all_games = all_games[:50]  # Limit to 50 most recent

                    if all_games:
                        st.success(f"Found **{len(all_games)}** games")

                        # Calculate record
                        wins = losses = draws = gf = ga = 0
                        for g in all_games:
                            home_score = g.get('home_score') or 0
                            away_score = g.get('away_score') or 0
                            is_home = g.get('home_team_master_id') == team['team_id_master']

                            if is_home:
                                gf += home_score
                                ga += away_score
                                if home_score > away_score:
                                    wins += 1
                                elif home_score < away_score:
                                    losses += 1
                                else:
                                    draws += 1
                            else:
                                gf += away_score
                                ga += home_score
                                if away_score > home_score:
                                    wins += 1
                                elif away_score < home_score:
                                    losses += 1
                                else:
                                    draws += 1

                        # Display record
                        record_col1, record_col2, record_col3, record_col4 = st.columns(4)
                        with record_col1:
                            st.metric("Record", f"{wins}W-{losses}L-{draws}D")
                        with record_col2:
                            st.metric("Goals For", gf)
                        with record_col3:
                            st.metric("Goals Against", ga)
                        with record_col4:
                            st.metric("Goal Diff", f"{gf - ga:+d}")

                        st.markdown("---")

                        # Display games table
                        games_df = pd.DataFrame([
                            {
                                'Date': g.get('game_date', '')[:10] if g.get('game_date') else '',
                                'Home': g.get('home_team_name', 'Unknown'),
                                'Score': f"{g.get('home_score', '-')} - {g.get('away_score', '-')}",
                                'Away': g.get('away_team_name', 'Unknown'),
                                'Result': (
                                    'W' if (g.get('home_team_master_id') == team['team_id_master'] and (g.get('home_score', 0) or 0) > (g.get('away_score', 0) or 0)) or
                                           (g.get('away_team_master_id') == team['team_id_master'] and (g.get('away_score', 0) or 0) > (g.get('home_score', 0) or 0))
                                    else 'L' if (g.get('home_team_master_id') == team['team_id_master'] and (g.get('home_score', 0) or 0) < (g.get('away_score', 0) or 0)) or
                                                (g.get('away_team_master_id') == team['team_id_master'] and (g.get('away_score', 0) or 0) < (g.get('home_score', 0) or 0))
                                    else 'D'
                                )
                            }
                            for g in all_games
                        ])

                        st.dataframe(games_df, use_container_width=True, hide_index=True)

                    else:
                        st.info("No games found for this team")

                except Exception as e:
                    st.error(f"Failed to load games: {e}")
                    import traceback
                    with st.expander("View Error Details"):
                        st.code(traceback.format_exc())

# Footer
st.divider()
st.caption(f"PitchRank Dashboard v2.0.0 | {PROJECT_NAME} v{VERSION}")
st.caption("For more information, see DASHBOARD_README.md")
