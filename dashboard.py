"""
PitchRank Settings Dashboard
A Streamlit-based UI to view all tunable parameters in the ranking engine.
"""

import streamlit as st
import sys
from pathlib import Path
import os
from datetime import datetime
import pandas as pd
from supabase import create_client
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import (
    RANKING_CONFIG,
    ML_CONFIG,
    MATCHING_CONFIG,
    ETL_CONFIG,
    CACHE_CONFIG,
    AGE_GROUPS,
    VERSION,
    PROJECT_NAME,
)
from src.etl.v53e import V53EConfig

# Load environment variables
load_dotenv()


# Page configuration
st.set_page_config(
    page_title=f"{PROJECT_NAME} Settings Dashboard",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for better styling
st.markdown(
    """
<style>
    .main-header {
        font-size: 3rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 1rem;
    }
    .section-header {
        font-size: 1.8rem;
        font-weight: bold;
        color: #ff7f0e;
        margin-top: 2rem;
        margin-bottom: 1rem;
        border-bottom: 2px solid #ff7f0e;
        padding-bottom: 0.5rem;
    }
    .subsection-header {
        font-size: 1.4rem;
        font-weight: bold;
        color: #2ca02c;
        margin-top: 1.5rem;
        margin-bottom: 0.5rem;
    }
    .parameter-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 0.5rem;
    }
    .parameter-name {
        font-weight: bold;
        color: #d62728;
    }
    .parameter-value {
        font-size: 1.2rem;
        color: #1f77b4;
        font-weight: bold;
    }
    .parameter-description {
        font-style: italic;
        color: #666;
        font-size: 0.9rem;
    }
    .warning-text {
        color: #ff7f0e;
        font-weight: bold;
    }
    .info-box {
        background-color: #e7f3ff;
        padding: 1rem;
        border-left: 4px solid #1f77b4;
        margin: 1rem 0;
    }
</style>
""",
    unsafe_allow_html=True,
)


def render_parameter(name: str, value, description: str = "", unit: str = ""):
    """Render a single parameter in a nice card format."""
    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(f"**{name}**")
        if description:
            st.markdown(f"*{description}*")
    with col2:
        value_str = f"{value} {unit}".strip()
        st.markdown(
            f"<span class='parameter-value'>{value_str}</span>", unsafe_allow_html=True
        )


@st.cache_resource
def get_supabase_client():
    """Initialize and cache Supabase client."""
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

    if not supabase_url or not supabase_key:
        return None

    return create_client(supabase_url, supabase_key)


def get_pending_matches():
    """Fetch pending matches from database."""
    client = get_supabase_client()
    if not client:
        return pd.DataFrame()

    try:
        result = client.table('team_alias_map').select(
            '*, teams!team_id_master(team_name, club_name, state_code, age_group, gender)'
        ).eq('review_status', 'pending').gte(
            'match_confidence', 0.75
        ).lt('match_confidence', 0.9).order('match_confidence', desc=True).execute()

        if not result.data:
            return pd.DataFrame()

        # Flatten the data for display
        flattened = []
        for item in result.data:
            matched_team = item.get('teams', {})
            if isinstance(matched_team, list) and len(matched_team) > 0:
                matched_team = matched_team[0]
            elif not isinstance(matched_team, dict):
                matched_team = {}

            flattened.append({
                'id': item['id'],
                'provider_team_id': item.get('provider_team_id', ''),
                'provider_team_name': item.get('team_name', ''),
                'provider_age_group': item.get('age_group', ''),
                'provider_gender': item.get('gender', ''),
                'matched_team_name': matched_team.get('team_name', '') if matched_team else '',
                'matched_club_name': matched_team.get('club_name', '') if matched_team else '',
                'matched_state': matched_team.get('state_code', '') if matched_team else '',
                'matched_age_group': matched_team.get('age_group', '') if matched_team else '',
                'matched_gender': matched_team.get('gender', '') if matched_team else '',
                'confidence': item.get('match_confidence', 0),
                'match_method': item.get('match_method', ''),
                'team_id_master': item.get('team_id_master', ''),
                'created_at': item.get('created_at', '')
            })

        return pd.DataFrame(flattened)
    except Exception as e:
        st.error(f"Error fetching matches: {e}")
        return pd.DataFrame()


def approve_match(match_id: str):
    """Approve a fuzzy match."""
    client = get_supabase_client()
    if not client:
        return False

    try:
        client.table('team_alias_map').update({
            'review_status': 'approved'
        }).eq('id', match_id).execute()
        return True
    except Exception as e:
        st.error(f"Error approving match: {e}")
        return False


def reject_match(match_id: str):
    """Reject a fuzzy match."""
    client = get_supabase_client()
    if not client:
        return False

    try:
        client.table('team_alias_map').update({
            'review_status': 'rejected'
        }).eq('id', match_id).execute()
        return True
    except Exception as e:
        st.error(f"Error rejecting match: {e}")
        return False


def get_match_statistics():
    """Get statistics about pending matches."""
    client = get_supabase_client()
    if not client:
        return None

    try:
        result = client.table('team_alias_map').select(
            'match_confidence, review_status'
        ).eq('review_status', 'pending').execute()

        if not result.data:
            return None

        data = result.data
        return {
            'total': len(data),
            'high_conf': sum(1 for m in data if m.get('match_confidence', 0) >= 0.85),
            'med_conf': sum(1 for m in data if 0.80 <= m.get('match_confidence', 0) < 0.85),
            'low_conf': sum(1 for m in data if 0.75 <= m.get('match_confidence', 0) < 0.80)
        }
    except Exception as e:
        st.error(f"Error getting statistics: {e}")
        return None


def main():
    # Header
    st.markdown(
        f"<h1 class='main-header'>⚽ {PROJECT_NAME} Settings Dashboard</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<p style='text-align: center; color: #666;'>Version {VERSION} | Comprehensive view of all tunable parameters</p>",
        unsafe_allow_html=True,
    )

    # Sidebar navigation
    st.sidebar.title("Navigation")
    section = st.sidebar.radio(
        "Jump to section:",
        [
            "Overview",
            "V53E Ranking Engine",
            "Machine Learning Layer",
            "Matching Configuration",
            "Fuzzy Match Review",
            "ETL & Data",
            "Age Groups",
            "Environment Variables",
        ],
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Quick Stats")

    # Get V53EConfig instance for comparison
    v53e_config = V53EConfig()

    # Count total parameters
    total_params = (
        len(RANKING_CONFIG) + len(ML_CONFIG) + len(MATCHING_CONFIG) + len(ETL_CONFIG)
    )
    st.sidebar.metric("Total Parameters", total_params)
    st.sidebar.metric("Ranking Layers", "13")
    st.sidebar.metric("Age Groups", len(AGE_GROUPS))

    # Overview Section
    if section == "Overview":
        st.markdown(
            "<h2 class='section-header'>System Overview</h2>", unsafe_allow_html=True
        )

        st.markdown(
            """
        <div class='info-box'>
        <h3>About This Dashboard</h3>
        <p>This dashboard provides a comprehensive view of all tunable parameters in the PitchRank ranking engine.
        All parameters can be configured via environment variables or directly in the configuration files.</p>
        </div>
        """,
            unsafe_allow_html=True,
        )

        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("### V53E Ranking Engine")
            st.info(
                f"""
            - **24 Core Parameters**
            - 11 Processing Layers
            - Window: {RANKING_CONFIG['window_days']} days
            - Min Games: {RANKING_CONFIG['min_games_for_ranking']}
            """
            )

        with col2:
            st.markdown("### ML Enhancement")
            st.success(
                f"""
            - **Enabled:** {ML_CONFIG['enabled']}
            - Blend Weight: {ML_CONFIG['alpha']}
            - XGBoost + Random Forest
            - Lookback: {ML_CONFIG['lookback_days']} days
            """
            )

        with col3:
            st.markdown("### Data Processing")
            st.warning(
                f"""
            - **Batch Size:** {ETL_CONFIG['batch_size']}
            - Max Retries: {ETL_CONFIG['max_retries']}
            - Validation: {ETL_CONFIG['validation_enabled']}
            - Cache TTL: {CACHE_CONFIG['ttl_seconds']}s
            """
            )

        st.markdown("---")
        st.markdown("### Critical Parameters at a Glance")

        critical_params = {
            "SOS Transitivity Lambda": (
                RANKING_CONFIG["sos_transitivity_lambda"],
                "Controls strength of schedule transitivity (0.20 = 80% direct, 20% transitive)",
            ),
            "Recent Share": (
                RANKING_CONFIG["recent_share"],
                "Weight given to recent games vs older games",
            ),
            "Shrink Tau": (
                RANKING_CONFIG["shrink_tau"],
                "Bayesian shrinkage strength (higher = more conservative)",
            ),
            "ML Alpha": (ML_CONFIG["alpha"], "Machine learning layer blend weight"),
            "Component Weights": (
                f"OFF:{RANKING_CONFIG['off_weight']}, DEF:{RANKING_CONFIG['def_weight']}, SOS:{RANKING_CONFIG['sos_weight']}",
                "Must sum to 1.0",
            ),
        }

        for param_name, (value, desc) in critical_params.items():
            render_parameter(param_name, value, desc)

    # V53E Ranking Engine Section
    elif section == "V53E Ranking Engine":
        st.markdown(
            "<h2 class='section-header'>V53E Ranking Engine Parameters</h2>",
            unsafe_allow_html=True,
        )

        st.info(
            "The V53E engine processes rankings through 11 layers. Each layer has specific tunable parameters."
        )

        # Layer 1: Time Window & Visibility
        st.markdown(
            "<h3 class='subsection-header'>Layer 1: Time Window & Visibility</h3>",
            unsafe_allow_html=True,
        )
        render_parameter(
            "WINDOW_DAYS",
            RANKING_CONFIG["window_days"],
            "How many days of game history to consider for rankings",
            "days",
        )
        render_parameter(
            "INACTIVE_HIDE_DAYS",
            RANKING_CONFIG["inactive_hide_days"],
            "Hide teams from rankings if inactive for this many days",
            "days",
        )

        # Layer 2: Game Limits & Outlier Protection
        st.markdown(
            "<h3 class='subsection-header'>Layer 2: Game Limits & Outlier Protection</h3>",
            unsafe_allow_html=True,
        )
        render_parameter(
            "MAX_GAMES_FOR_RANK",
            RANKING_CONFIG["max_games"],
            "Maximum number of games to consider per team",
            "games",
        )
        render_parameter(
            "GOAL_DIFF_CAP",
            RANKING_CONFIG["goal_diff_cap"],
            "Cap goal differential to prevent blowout distortion",
            "goals",
        )
        render_parameter(
            "OUTLIER_GUARD_ZSCORE",
            RANKING_CONFIG["outlier_guard_zscore"],
            "Z-score threshold for clipping per-game outliers",
            "σ",
        )

        # Layer 3: Recency Weighting
        st.markdown(
            "<h3 class='subsection-header'>Layer 3: Recency Weighting</h3>",
            unsafe_allow_html=True,
        )
        render_parameter(
            "RECENT_K",
            RANKING_CONFIG["recent_k"],
            "Number of most recent games to weight more heavily",
            "games",
        )
        render_parameter(
            "RECENT_SHARE",
            RANKING_CONFIG["recent_share"],
            "Weight fraction for recent games (vs older games)",
            "",
        )
        render_parameter(
            "DAMPEN_TAIL_START",
            RANKING_CONFIG["dampen_tail_start"],
            "Game number where tail dampening begins",
            "game #",
        )
        render_parameter(
            "DAMPEN_TAIL_END",
            RANKING_CONFIG["dampen_tail_end"],
            "Game number where tail dampening ends",
            "game #",
        )
        render_parameter(
            "DAMPEN_TAIL_START_WEIGHT",
            RANKING_CONFIG["dampen_tail_start_weight"],
            "Weight at start of tail dampening",
            "",
        )
        render_parameter(
            "DAMPEN_TAIL_END_WEIGHT",
            RANKING_CONFIG["dampen_tail_end_weight"],
            "Weight at end of tail dampening",
            "",
        )

        # Layer 4: Defense Ridge
        st.markdown(
            "<h3 class='subsection-header'>Layer 4: Defense Ridge Regularization</h3>",
            unsafe_allow_html=True,
        )
        render_parameter(
            "RIDGE_GA",
            RANKING_CONFIG["ridge_ga"],
            "Ridge penalty for defensive metrics to prevent overfitting",
            "",
        )

        # Layer 5: Adaptive K
        st.markdown(
            "<h3 class='subsection-header'>Layer 5: Adaptive K-Factor</h3>",
            unsafe_allow_html=True,
        )
        render_parameter(
            "ADAPTIVE_K_ALPHA",
            RANKING_CONFIG["adaptive_k_alpha"],
            "Strength adjustment factor for adaptive K",
            "",
        )
        render_parameter(
            "ADAPTIVE_K_BETA",
            RANKING_CONFIG["adaptive_k_beta"],
            "Game count adjustment factor for adaptive K",
            "",
        )
        render_parameter(
            "TEAM_OUTLIER_GUARD_ZSCORE",
            RANKING_CONFIG["team_outlier_guard_zscore"],
            "Z-score threshold for clipping team-level aggregated metrics",
            "σ",
        )

        # Layer 6: Performance Adjustment
        st.markdown(
            "<h3 class='subsection-header'>Layer 6: Performance-Based Adjustment</h3>",
            unsafe_allow_html=True,
        )
        render_parameter(
            "PERFORMANCE_K",
            RANKING_CONFIG["performance_k"],
            "Weight of performance adjustment",
            "",
        )
        render_parameter(
            "PERFORMANCE_DECAY_RATE",
            RANKING_CONFIG["performance_decay_rate"],
            "How quickly performance impact decays over time",
            "",
        )
        render_parameter(
            "PERFORMANCE_THRESHOLD",
            RANKING_CONFIG["performance_threshold"],
            "Goal differential threshold for performance trigger",
            "goals",
        )
        render_parameter(
            "PERFORMANCE_GOAL_SCALE",
            RANKING_CONFIG["performance_goal_scale"],
            "Goals per 1.0 power difference",
            "goals",
        )

        # Layer 7: Bayesian Shrinkage
        st.markdown(
            "<h3 class='subsection-header'>Layer 7: Bayesian Shrinkage</h3>",
            unsafe_allow_html=True,
        )
        render_parameter(
            "SHRINK_TAU",
            RANKING_CONFIG["shrink_tau"],
            "Prior strength for Bayesian shrinkage (higher = more conservative)",
            "",
        )

        # Layer 8: Strength of Schedule (SOS)
        st.markdown(
            "<h3 class='subsection-header'>Layer 8: Strength of Schedule (SOS)</h3>",
            unsafe_allow_html=True,
        )
        render_parameter(
            "UNRANKED_SOS_BASE",
            RANKING_CONFIG["unranked_sos_base"],
            "Default SOS value for unranked opponents",
            "",
        )
        render_parameter(
            "SOS_REPEAT_CAP",
            RANKING_CONFIG["sos_repeat_cap"],
            "Maximum times to count same opponent in SOS",
            "games",
        )
        render_parameter(
            "SOS_ITERATIONS",
            RANKING_CONFIG["sos_iterations"],
            "Number of SOS convergence iterations",
            "iterations",
        )
        render_parameter(
            "SOS_TRANSITIVITY_LAMBDA",
            RANKING_CONFIG["sos_transitivity_lambda"],
            "Weight for transitive SOS (0.20 = 80% direct opponents, 20% opponents of opponents)",
            "",
        )

        # Layer 10: Component Weights
        st.markdown(
            "<h3 class='subsection-header'>Layer 10: Component Weights</h3>",
            unsafe_allow_html=True,
        )
        st.warning("⚠️ These three weights MUST sum to 1.0")
        render_parameter(
            "OFF_WEIGHT",
            RANKING_CONFIG["off_weight"],
            "Weight of offensive component in final score",
            "",
        )
        render_parameter(
            "DEF_WEIGHT",
            RANKING_CONFIG["def_weight"],
            "Weight of defensive component in final score",
            "",
        )
        render_parameter(
            "SOS_WEIGHT",
            RANKING_CONFIG["sos_weight"],
            "Weight of strength of schedule component in final score",
            "",
        )

        weight_sum = (
            RANKING_CONFIG["off_weight"]
            + RANKING_CONFIG["def_weight"]
            + RANKING_CONFIG["sos_weight"]
        )
        if abs(weight_sum - 1.0) > 0.001:
            st.error(f"❌ Current weights sum to {weight_sum:.3f}, not 1.0!")
        else:
            st.success(f"✅ Weights correctly sum to {weight_sum:.3f}")

        # Provisional & Context
        st.markdown(
            "<h3 class='subsection-header'>Provisional Rankings & Context Multipliers</h3>",
            unsafe_allow_html=True,
        )
        render_parameter(
            "MIN_GAMES_FOR_RANKING",
            RANKING_CONFIG["min_games_for_ranking"],
            "Minimum games required before team is ranked",
            "games",
        )
        render_parameter(
            "TOURNAMENT_KO_MULT",
            RANKING_CONFIG["tournament_ko_mult"],
            "Multiplier for tournament knockout games",
            "×",
        )
        render_parameter(
            "SEMIS_FINALS_MULT",
            RANKING_CONFIG["semis_finals_mult"],
            "Multiplier for semifinals and finals",
            "×",
        )

        # Cross-Age & Normalization
        st.markdown(
            "<h3 class='subsection-header'>Cross-Age Anchoring & Normalization</h3>",
            unsafe_allow_html=True,
        )
        render_parameter(
            "ANCHOR_PERCENTILE",
            RANKING_CONFIG["anchor_percentile"],
            "Percentile for cross-age anchoring",
            "",
        )
        render_parameter(
            "NORM_MODE",
            RANKING_CONFIG["norm_mode"],
            "Normalization method: 'percentile' or 'zscore'",
            "",
        )

    # Machine Learning Layer Section
    elif section == "Machine Learning Layer":
        st.markdown(
            "<h2 class='section-header'>Machine Learning Enhancement (Layer 13)</h2>",
            unsafe_allow_html=True,
        )

        st.info(
            f"""
        The ML layer uses ensemble learning (XGBoost + Random Forest) to capture non-linear patterns.
        **Status:** {'✅ ENABLED' if ML_CONFIG['enabled'] else '❌ DISABLED'}
        """
        )

        # Core ML Settings
        st.markdown(
            "<h3 class='subsection-header'>Core ML Settings</h3>",
            unsafe_allow_html=True,
        )
        render_parameter(
            "ML_LAYER_ENABLED",
            ML_CONFIG["enabled"],
            "Whether ML enhancement layer is active",
            "",
        )
        render_parameter(
            "ML_ALPHA",
            ML_CONFIG["alpha"],
            "Blend weight for ML adjustment (0 = no ML, 1 = full ML)",
            "",
        )
        render_parameter(
            "ML_RECENCY_DECAY_LAMBDA",
            ML_CONFIG["recency_decay_lambda"],
            "Decay rate for game age in ML features",
            "",
        )
        render_parameter(
            "ML_MIN_TEAM_GAMES",
            ML_CONFIG["min_team_games_for_residual"],
            "Minimum games before computing ML residuals",
            "games",
        )
        render_parameter(
            "ML_RESIDUAL_CLIP",
            ML_CONFIG["residual_clip_goals"],
            "Clip ML residuals to prevent extreme adjustments",
            "goals",
        )
        render_parameter(
            "ML_NORM_MODE",
            ML_CONFIG["norm_mode"],
            "Normalization for ML features: 'percentile' or 'zscore'",
            "",
        )
        render_parameter(
            "ML_LOOKBACK_DAYS",
            ML_CONFIG["lookback_days"],
            "Historical data window for ML training",
            "days",
        )

        # XGBoost Parameters
        st.markdown(
            "<h3 class='subsection-header'>XGBoost Hyperparameters</h3>",
            unsafe_allow_html=True,
        )
        xgb_params = ML_CONFIG["xgb_params"]
        render_parameter(
            "XGB_N_ESTIMATORS",
            xgb_params["n_estimators"],
            "Number of boosting rounds",
            "trees",
        )
        render_parameter(
            "XGB_MAX_DEPTH", xgb_params["max_depth"], "Maximum tree depth", "levels"
        )
        render_parameter(
            "XGB_LEARNING_RATE",
            xgb_params["learning_rate"],
            "Shrinkage parameter for boosting",
            "",
        )
        render_parameter(
            "XGB_SUBSAMPLE",
            xgb_params["subsample"],
            "Fraction of samples for each tree",
            "",
        )
        render_parameter(
            "XGB_COLSAMPLE_BYTREE",
            xgb_params["colsample_bytree"],
            "Fraction of features for each tree",
            "",
        )
        render_parameter(
            "XGB_REG_LAMBDA", xgb_params["reg_lambda"], "L2 regularization term", ""
        )
        render_parameter(
            "XGB_N_JOBS",
            xgb_params["n_jobs"],
            "Parallel threads (-1 = all cores)",
            "threads",
        )

        # Random Forest Parameters
        st.markdown(
            "<h3 class='subsection-header'>Random Forest Hyperparameters</h3>",
            unsafe_allow_html=True,
        )
        rf_params = ML_CONFIG["rf_params"]
        render_parameter(
            "RF_N_ESTIMATORS",
            rf_params["n_estimators"],
            "Number of trees in forest",
            "trees",
        )
        render_parameter(
            "RF_MAX_DEPTH", rf_params["max_depth"], "Maximum tree depth", "levels"
        )
        render_parameter(
            "RF_MIN_SAMPLES_LEAF",
            rf_params["min_samples_leaf"],
            "Minimum samples required at leaf node",
            "samples",
        )
        render_parameter(
            "RF_N_JOBS",
            rf_params["n_jobs"],
            "Parallel threads (-1 = all cores)",
            "threads",
        )

    # Matching Configuration Section
    elif section == "Matching Configuration":
        st.markdown(
            "<h2 class='section-header'>Team Matching Configuration</h2>",
            unsafe_allow_html=True,
        )

        st.info(
            "These parameters control fuzzy matching of team names across different data sources."
        )

        render_parameter(
            "Fuzzy Threshold",
            MATCHING_CONFIG["fuzzy_threshold"],
            "Minimum similarity score for potential matches",
            "",
        )
        render_parameter(
            "Auto-Approve Threshold",
            MATCHING_CONFIG["auto_approve_threshold"],
            "Similarity score for automatic approval",
            "",
        )
        render_parameter(
            "Review Threshold",
            MATCHING_CONFIG["review_threshold"],
            "Similarity score requiring manual review",
            "",
        )
        render_parameter(
            "Max Age Difference",
            MATCHING_CONFIG["max_age_diff"],
            "Maximum age group difference for matching",
            "years",
        )
        render_parameter(
            "Club Boost (Identical)",
            MATCHING_CONFIG["club_boost_identical"],
            "Boost when club names match exactly",
            "",
        )
        render_parameter(
            "Club Min Similarity",
            MATCHING_CONFIG["club_min_similarity"],
            "Minimum club name similarity",
            "",
        )

        st.markdown(
            "<h3 class='subsection-header'>Matching Component Weights</h3>",
            unsafe_allow_html=True,
        )
        st.warning("⚠️ These weights should sum to 1.0")

        weights = MATCHING_CONFIG["weights"]
        render_parameter(
            "Team Name Weight", weights["team"], "Weight of team name similarity", ""
        )
        render_parameter(
            "Club Name Weight", weights["club"], "Weight of club name similarity", ""
        )
        render_parameter(
            "Age Group Weight", weights["age"], "Weight of age group match", ""
        )
        render_parameter(
            "Location Weight", weights["location"], "Weight of location proximity", ""
        )

        weight_sum = sum(weights.values())
        if abs(weight_sum - 1.0) > 0.001:
            st.error(f"❌ Current weights sum to {weight_sum:.3f}, not 1.0!")
        else:
            st.success(f"✅ Weights correctly sum to {weight_sum:.3f}")

    # Fuzzy Match Review Section
    elif section == "Fuzzy Match Review":
        st.markdown(
            "<h2 class='section-header'>🔍 Fuzzy Match Review Dashboard</h2>",
            unsafe_allow_html=True,
        )

        # Check if Supabase is configured
        client = get_supabase_client()
        if not client:
            st.error(
                "⚠️ Supabase connection not configured. Please set SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY in your .env file."
            )
            return

        st.info(
            """
            **Review fuzzy team matches that need manual approval**

            Matches with confidence scores between 0.75 and 0.90 require human review to ensure accuracy.
            Once approved, these matches will be used for automatic matching in future imports.
            """
        )

        # Statistics Section
        st.markdown("### 📊 Match Statistics")
        stats = get_match_statistics()

        if stats:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Pending", stats['total'])
            with col2:
                st.metric("High Confidence (0.85-0.89)", stats['high_conf'],
                         delta="Best matches", delta_color="normal")
            with col3:
                st.metric("Medium Confidence (0.80-0.84)", stats['med_conf'],
                         delta="Good matches", delta_color="normal")
            with col4:
                st.metric("Low Confidence (0.75-0.79)", stats['low_conf'],
                         delta="Review carefully", delta_color="inverse")

            # Confidence distribution chart
            if stats['total'] > 0:
                st.markdown("### 📈 Confidence Distribution")
                chart_data = pd.DataFrame({
                    'Confidence Level': ['High (0.85-0.89)', 'Medium (0.80-0.84)', 'Low (0.75-0.79)'],
                    'Count': [stats['high_conf'], stats['med_conf'], stats['low_conf']]
                })
                st.bar_chart(chart_data.set_index('Confidence Level'))
        else:
            st.success("✅ No pending matches to review!")
            return

        st.markdown("---")

        # Filters Section
        st.markdown("### 🔎 Filters")
        col1, col2, col3 = st.columns(3)

        with col1:
            min_confidence = st.slider(
                "Minimum Confidence",
                min_value=0.75,
                max_value=0.89,
                value=0.75,
                step=0.01,
                help="Filter matches by minimum confidence score"
            )

        with col2:
            age_filter = st.selectbox(
                "Age Group",
                options=["All"] + sorted(list(AGE_GROUPS.keys())),
                help="Filter by age group"
            )

        with col3:
            gender_filter = st.selectbox(
                "Gender",
                options=["All", "Male", "Female"],
                help="Filter by gender"
            )

        # Fetch pending matches
        df = get_pending_matches()

        if df.empty:
            st.success("✅ No pending matches to review!")
            return

        # Apply filters
        filtered_df = df[df['confidence'] >= min_confidence].copy()

        if age_filter != "All":
            filtered_df = filtered_df[filtered_df['provider_age_group'] == age_filter]

        if gender_filter != "All":
            filtered_df = filtered_df[filtered_df['provider_gender'] == gender_filter]

        st.markdown(f"### 📋 Pending Matches ({len(filtered_df)} matches)")

        if filtered_df.empty:
            st.info("No matches found with current filters.")
            return

        # Display matches
        for idx, row in filtered_df.iterrows():
            confidence_color = "🟢" if row['confidence'] >= 0.85 else "🟡" if row['confidence'] >= 0.80 else "🔴"

            with st.expander(
                f"{confidence_color} **{row['provider_team_name'][:50]}** ➜ **{row['matched_team_name'][:50]}** "
                f"(Confidence: {row['confidence']:.2%})",
                expanded=False
            ):
                # Create two columns for comparison
                col1, col2 = st.columns(2)

                with col1:
                    st.markdown("#### Provider Team")
                    st.markdown(f"**Team Name:** {row['provider_team_name']}")
                    st.markdown(f"**Age Group:** {row['provider_age_group']}")
                    st.markdown(f"**Gender:** {row['provider_gender']}")
                    st.markdown(f"**Provider Team ID:** `{row['provider_team_id']}`")

                with col2:
                    st.markdown("#### Matched Team (Database)")
                    st.markdown(f"**Team Name:** {row['matched_team_name']}")
                    st.markdown(f"**Club Name:** {row['matched_club_name']}")
                    st.markdown(f"**State:** {row['matched_state']}")
                    st.markdown(f"**Age Group:** {row['matched_age_group']}")
                    st.markdown(f"**Gender:** {row['matched_gender']}")

                # Match details
                st.markdown("---")
                st.markdown("#### Match Details")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Confidence Score", f"{row['confidence']:.2%}")
                with col2:
                    st.markdown(f"**Match Method:** `{row['match_method']}`")
                with col3:
                    st.markdown(f"**Created:** {row['created_at'][:10] if row['created_at'] else 'N/A'}")

                # Action buttons
                st.markdown("---")
                col1, col2, col3 = st.columns([1, 1, 2])

                with col1:
                    if st.button("✅ Approve", key=f"approve_{row['id']}", type="primary"):
                        if approve_match(row['id']):
                            st.success("Match approved! Refreshing...")
                            st.rerun()
                        else:
                            st.error("Failed to approve match.")

                with col2:
                    if st.button("❌ Reject", key=f"reject_{row['id']}", type="secondary"):
                        if reject_match(row['id']):
                            st.warning("Match rejected! Refreshing...")
                            st.rerun()
                        else:
                            st.error("Failed to reject match.")

                with col3:
                    st.markdown(f"**Master Team ID:** `{row['team_id_master']}`")

        # Batch Actions
        st.markdown("---")
        st.markdown("### ⚡ Batch Actions")
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**Auto-approve high confidence matches**")
            auto_approve_threshold = st.number_input(
                "Approve all matches above confidence:",
                min_value=0.85,
                max_value=0.89,
                value=0.88,
                step=0.01,
                help="Automatically approve all matches above this confidence level"
            )

            if st.button("Auto-Approve High Confidence", type="primary"):
                high_conf_matches = filtered_df[filtered_df['confidence'] >= auto_approve_threshold]
                approved_count = 0
                for _, match in high_conf_matches.iterrows():
                    if approve_match(match['id']):
                        approved_count += 1

                if approved_count > 0:
                    st.success(f"Approved {approved_count} high-confidence matches! Refreshing...")
                    st.rerun()
                else:
                    st.info("No matches to auto-approve.")

        with col2:
            st.markdown("**Refresh Data**")
            st.markdown("Click to reload pending matches from the database")
            if st.button("🔄 Refresh", type="secondary"):
                st.cache_data.clear()
                st.rerun()

        # Help Section
        st.markdown("---")
        with st.expander("ℹ️ Help & Information"):
            st.markdown("""
            ### How Fuzzy Matching Works

            **Confidence Score Calculation:**
            - **65%** - Team name similarity (normalized and compared)
            - **25%** - Club name similarity
            - **5%** - Age group match (exact match required)
            - **5%** - Location/state match

            **Confidence Thresholds:**
            - **≥ 0.90** - Auto-approved (high confidence)
            - **0.75 - 0.89** - Manual review required (shown here)
            - **< 0.75** - Rejected (too uncertain)

            **Best Practices:**
            - Review high-confidence matches (0.85-0.89) first - these are usually correct
            - Be cautious with low-confidence matches (0.75-0.79)
            - Check that age group and gender match
            - Verify club names are similar or related
            - When in doubt, reject and let it be reviewed again later

            **After Approval:**
            Once approved, the match is saved and future imports will automatically match
            this provider team to the master team in the database.
            """)

    # ETL & Data Section
    elif section == "ETL & Data":
        st.markdown(
            "<h2 class='section-header'>ETL & Data Processing Configuration</h2>",
            unsafe_allow_html=True,
        )

        col1, col2 = st.columns(2)

        with col1:
            st.markdown(
                "<h3 class='subsection-header'>ETL Configuration</h3>",
                unsafe_allow_html=True,
            )
            render_parameter(
                "Batch Size",
                ETL_CONFIG["batch_size"],
                "Records processed per batch",
                "records",
            )
            render_parameter(
                "Max Retries",
                ETL_CONFIG["max_retries"],
                "Maximum retry attempts on failure",
                "attempts",
            )
            render_parameter(
                "Retry Delay",
                ETL_CONFIG["retry_delay"],
                "Wait time between retries",
                "seconds",
            )
            render_parameter(
                "Incremental Days",
                ETL_CONFIG["incremental_days"],
                "Days for incremental updates",
                "days",
            )
            render_parameter(
                "Validation Enabled",
                ETL_CONFIG["validation_enabled"],
                "Whether to validate data during ETL",
                "",
            )

        with col2:
            st.markdown(
                "<h3 class='subsection-header'>Cache Configuration</h3>",
                unsafe_allow_html=True,
            )
            render_parameter(
                "TTL (Time to Live)",
                CACHE_CONFIG["ttl_seconds"],
                f"Cache expiration time ({CACHE_CONFIG['ttl_seconds'] // 60} minutes)",
                "seconds",
            )
            render_parameter(
                "Max Cache Size",
                CACHE_CONFIG["max_size_mb"],
                "Maximum cache size on disk",
                "MB",
            )

    # Age Groups Section
    elif section == "Age Groups":
        st.markdown(
            "<h2 class='section-header'>Age Group Configuration</h2>",
            unsafe_allow_html=True,
        )

        st.info(
            "Each age group has a birth year and anchor score for cross-age normalization."
        )

        for age_group, config in AGE_GROUPS.items():
            with st.expander(
                f"{age_group.upper()} - Birth Year {config['birth_year']}",
                expanded=False,
            ):
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Birth Year", config["birth_year"])
                with col2:
                    st.metric("Anchor Score", f"{config['anchor_score']:.2f}")

        # Visualize anchor scores
        st.markdown(
            "<h3 class='subsection-header'>Anchor Score Progression</h3>",
            unsafe_allow_html=True,
        )

        import pandas as pd

        df = pd.DataFrame(
            [
                {"Age Group": k.upper(), "Anchor Score": v["anchor_score"]}
                for k, v in AGE_GROUPS.items()
            ]
        )

        st.bar_chart(df.set_index("Age Group"))

    # Environment Variables Section
    elif section == "Environment Variables":
        st.markdown(
            "<h2 class='section-header'>Environment Variables Reference</h2>",
            unsafe_allow_html=True,
        )

        st.info(
            """
        All parameters can be configured via environment variables. Create a `.env` file in the project root
        or set these in your system environment.
        """
        )

        env_vars = {
            "Ranking Engine": [
                ("RANKING_WINDOW_DAYS", "365", "Time window for game history"),
                ("INACTIVE_HIDE_DAYS", "180", "Days before hiding inactive teams"),
                ("MAX_GAMES_PER_TEAM", "30", "Maximum games per team"),
                ("GOAL_DIFF_CAP", "6", "Goal differential cap"),
                ("OUTLIER_GUARD_ZSCORE", "2.5", "Per-game outlier threshold"),
                ("RECENT_K", "15", "Number of recent games"),
                ("RECENT_SHARE", "0.65", "Weight for recent games"),
                ("SOS_TRANSITIVITY_LAMBDA", "0.20", "SOS transitivity weight"),
                ("SHRINK_TAU", "8.0", "Bayesian shrinkage strength"),
                ("OFF_WEIGHT", "0.25", "Offensive component weight"),
                ("DEF_WEIGHT", "0.25", "Defensive component weight"),
                ("SOS_WEIGHT", "0.50", "SOS component weight"),
            ],
            "Machine Learning": [
                ("ML_LAYER_ENABLED", "true", "Enable/disable ML layer"),
                ("ML_ALPHA", "0.12", "ML blend weight"),
                ("ML_RECENCY_DECAY_LAMBDA", "0.06", "ML recency decay"),
                ("ML_LOOKBACK_DAYS", "365", "ML training data window"),
                ("ML_XGB_N_ESTIMATORS", "220", "XGBoost trees"),
                ("ML_XGB_MAX_DEPTH", "5", "XGBoost max depth"),
                ("ML_XGB_LEARNING_RATE", "0.08", "XGBoost learning rate"),
                ("ML_RF_N_ESTIMATORS", "240", "Random Forest trees"),
                ("ML_RF_MAX_DEPTH", "18", "Random Forest max depth"),
            ],
            "System": [
                ("LOG_LEVEL", "INFO", "Logging verbosity"),
                ("USE_CACHE", "true", "Enable caching"),
                ("PARALLEL_PROCESSING", "true", "Enable parallel processing"),
                ("DEBUG_MODE", "false", "Enable debug mode"),
                ("USE_LOCAL_SUPABASE", "false", "Use local Supabase instance"),
            ],
        }

        for category, vars in env_vars.items():
            st.markdown(
                f"<h3 class='subsection-header'>{category}</h3>", unsafe_allow_html=True
            )

            for var_name, default_val, description in vars:
                with st.expander(f"`{var_name}`", expanded=False):
                    col1, col2 = st.columns([1, 2])
                    with col1:
                        st.code(f"export {var_name}={default_val}")
                    with col2:
                        st.write(f"**Description:** {description}")
                        st.write(f"**Default:** `{default_val}`")

    # Footer
    st.markdown("---")
    st.markdown(
        f"""
    <div style='text-align: center; color: #666; padding: 2rem;'>
        <p>PitchRank Settings Dashboard v{VERSION}</p>
        <p>All settings can be modified via environment variables or config files</p>
        <p>See <code>config/settings.py</code> and <code>src/etl/v53e.py</code> for details</p>
    </div>
    """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
