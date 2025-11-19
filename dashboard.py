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


def get_unmatched_opponents(limit=500):
    """Fetch games with unmatched teams and extract team info."""
    client = get_supabase_client()
    if not client:
        return pd.DataFrame()

    try:
        # Query games where either home or away team is not matched
        result = client.table('games').select(
            'id, game_date, home_provider_id, away_provider_id, '
            'home_team_master_id, away_team_master_id, '
            'home_score, away_score, division_name, event_name, provider_id'
        ).or_(
            'home_team_master_id.is.null,away_team_master_id.is.null'
        ).order('game_date', desc=True).limit(limit).execute()

        if not result.data:
            return pd.DataFrame()

        # Get team names from team_alias_map for provider IDs
        all_provider_ids = set()
        for game in result.data:
            if game.get('home_team_master_id') is None:
                all_provider_ids.add(game.get('home_provider_id', ''))
            if game.get('away_team_master_id') is None:
                all_provider_ids.add(game.get('away_provider_id', ''))

        # Fetch team info from alias map (if columns exist)
        team_names = {}
        if all_provider_ids:
            try:
                # Try to get team names from alias map if those columns exist
                alias_result = client.table('team_alias_map').select(
                    'provider_team_id, team_name, age_group, gender'
                ).in_('provider_team_id', list(all_provider_ids)).execute()

                if alias_result.data:
                    for alias in alias_result.data:
                        team_names[alias['provider_team_id']] = {
                            'team_name': alias.get('team_name', ''),
                            'age_group': alias.get('age_group', ''),
                            'gender': alias.get('gender', '')
                        }
            except Exception:
                # Columns don't exist in this database, skip team name lookup
                pass

        # Get opponent team names for matched teams
        matched_team_ids = set()
        for game in result.data:
            if game.get('home_team_master_id'):
                matched_team_ids.add(game.get('home_team_master_id'))
            if game.get('away_team_master_id'):
                matched_team_ids.add(game.get('away_team_master_id'))

        # Fetch opponent team names from teams table
        opponent_names = {}
        if matched_team_ids:
            try:
                teams_result = client.table('teams').select(
                    'team_id_master, team_name'
                ).in_('team_id_master', list(matched_team_ids)).execute()

                if teams_result.data:
                    for team in teams_result.data:
                        opponent_names[team['team_id_master']] = team.get('team_name', 'Unknown Team')
            except Exception:
                pass

        # Process to extract unique unmatched teams with all info
        unmatched_teams = {}
        sample_games = {}  # Store sample games for each team

        for game in result.data:
            home_score = game.get('home_score', '-')
            away_score = game.get('away_score', '-')

            # Check home team (unmatched)
            if game.get('home_team_master_id') is None:
                team_id = game.get('home_provider_id', '')
                if team_id:
                    # Get opponent info (away team)
                    opponent_id = game.get('away_team_master_id')
                    if opponent_id:
                        opponent = opponent_names.get(opponent_id, 'Unknown')
                    else:
                        opponent = f"Unknown ({game.get('away_provider_id', 'N/A')})"

                    game_info = {
                        'date': game.get('game_date', ''),
                        'score': f"{home_score} - {away_score}",
                        'result': 'W' if home_score > away_score else 'L' if home_score < away_score else 'D',
                        'opponent': opponent,
                        'event': game.get('event_name', 'N/A')
                    }

                    if team_id not in unmatched_teams:
                        team_info = team_names.get(team_id, {})
                        unmatched_teams[team_id] = {
                            'provider_team_id': team_id,
                            'provider_id': game.get('provider_id', ''),
                            'team_name': team_info.get('team_name', f'Unknown ({team_id})'),
                            'age_group': team_info.get('age_group', ''),
                            'gender': team_info.get('gender', ''),
                            'game_count': 0,
                            'recent_game_date': game.get('game_date', ''),
                            'division_name': game.get('division_name', ''),
                            'event_name': game.get('event_name', '')
                        }
                        sample_games[team_id] = []

                    unmatched_teams[team_id]['game_count'] += 1
                    if len(sample_games[team_id]) < 5:  # Keep up to 5 sample games
                        sample_games[team_id].append(game_info)

            # Check away team (unmatched)
            if game.get('away_team_master_id') is None:
                team_id = game.get('away_provider_id', '')
                if team_id:
                    # Get opponent info (home team)
                    opponent_id = game.get('home_team_master_id')
                    if opponent_id:
                        opponent = opponent_names.get(opponent_id, 'Unknown')
                    else:
                        opponent = f"Unknown ({game.get('home_provider_id', 'N/A')})"

                    game_info = {
                        'date': game.get('game_date', ''),
                        'score': f"{away_score} - {home_score}",  # From away team's perspective
                        'result': 'W' if away_score > home_score else 'L' if away_score < home_score else 'D',
                        'opponent': opponent,
                        'event': game.get('event_name', 'N/A')
                    }

                    if team_id not in unmatched_teams:
                        team_info = team_names.get(team_id, {})
                        unmatched_teams[team_id] = {
                            'provider_team_id': team_id,
                            'provider_id': game.get('provider_id', ''),
                            'team_name': team_info.get('team_name', f'Unknown ({team_id})'),
                            'age_group': team_info.get('age_group', ''),
                            'gender': team_info.get('gender', ''),
                            'game_count': 0,
                            'recent_game_date': game.get('game_date', ''),
                            'division_name': game.get('division_name', ''),
                            'event_name': game.get('event_name', '')
                        }
                        sample_games[team_id] = []

                    unmatched_teams[team_id]['game_count'] += 1
                    if len(sample_games[team_id]) < 5:
                        sample_games[team_id].append(game_info)

        # Add sample games to the dataframe
        for team_id, team_data in unmatched_teams.items():
            team_data['sample_games'] = sample_games.get(team_id, [])

        return pd.DataFrame(list(unmatched_teams.values()))
    except Exception as e:
        st.error(f"Error fetching unmatched opponents: {e}")
        return pd.DataFrame()


def get_overall_matching_stats():
    """Get overall statistics about team matching."""
    client = get_supabase_client()
    if not client:
        return None

    try:
        # Get all games and calculate stats client-side for better compatibility
        games_result = client.table('games').select('home_team_master_id, away_team_master_id').execute()

        if not games_result.data:
            return None

        total_games = len(games_result.data)
        matched_both = sum(1 for g in games_result.data if g.get('home_team_master_id') and g.get('away_team_master_id'))
        matched_none = sum(1 for g in games_result.data if not g.get('home_team_master_id') and not g.get('away_team_master_id'))
        matched_one = total_games - matched_both - matched_none

        # Get team counts
        total_teams_result = client.table('teams').select('id', count='exact').execute()
        total_teams = total_teams_result.count if total_teams_result.count else 0

        # Get alias map stats
        alias_stats = client.table('team_alias_map').select('match_method, review_status').execute()

        fuzzy_auto = sum(1 for a in alias_stats.data if a.get('match_method') == 'fuzzy_auto') if alias_stats.data else 0
        fuzzy_pending = sum(1 for a in alias_stats.data if a.get('match_method') == 'fuzzy_review' and a.get('review_status') == 'pending') if alias_stats.data else 0
        manual_matches = sum(1 for a in alias_stats.data if a.get('match_method') == 'manual') if alias_stats.data else 0

        return {
            'total_games': total_games,
            'matched_both': matched_both,
            'matched_one': matched_one,
            'matched_none': matched_none,
            'total_teams': total_teams,
            'fuzzy_auto': fuzzy_auto,
            'fuzzy_pending': fuzzy_pending,
            'manual_matches': manual_matches
        }
    except Exception as e:
        st.error(f"Error fetching stats: {e}")
        return None


def search_teams(search_query: str, age_group: str = None, gender: str = None):
    """Search for teams in the master teams table."""
    client = get_supabase_client()
    if not client:
        return []

    try:
        query = client.table('teams').select(
            'team_id_master, team_name, club_name, age_group, gender, state_code'
        )

        # Add text search
        if search_query:
            query = query.ilike('team_name', f'%{search_query}%')

        # Add filters
        if age_group:
            query = query.eq('age_group', age_group)
        if gender:
            query = query.eq('gender', gender)

        result = query.limit(50).execute()
        return result.data if result.data else []
    except Exception as e:
        st.error(f"Error searching teams: {e}")
        return []


def link_team_manually(provider_id: str, provider_team_id: str, master_team_id: str, team_info: dict):
    """Manually link a provider team to a master team."""
    client = get_supabase_client()
    if not client:
        return False

    try:
        # Create alias mapping (only include base fields that always exist)
        alias_data = {
            'provider_id': provider_id,
            'provider_team_id': provider_team_id,
            'team_id_master': master_team_id,
            'match_confidence': 1.0,
            'match_method': 'manual',
            'review_status': 'approved'
        }

        # Try to add optional fields if they exist in the table
        try:
            # Test if these columns exist by trying to select them
            test_result = client.table('team_alias_map').select('team_name').limit(1).execute()
            # If successful, add the optional fields
            alias_data.update({
                'team_name': team_info.get('team_name', ''),
                'age_group': team_info.get('age_group', ''),
                'gender': team_info.get('gender', '')
            })
        except Exception:
            # Columns don't exist, skip them
            pass

        client.table('team_alias_map').insert(alias_data).execute()

        # Update games table
        client.table('games').update({
            'home_team_master_id': master_team_id
        }).eq('home_provider_id', provider_team_id).is_('home_team_master_id', 'null').execute()

        client.table('games').update({
            'away_team_master_id': master_team_id
        }).eq('away_provider_id', provider_team_id).is_('away_team_master_id', 'null').execute()

        return True
    except Exception as e:
        st.error(f"Error linking team: {e}")
        return False


def create_new_team(provider_id: str, provider_team_id: str, team_data: dict):
    """Create a new team in the master teams table."""
    client = get_supabase_client()
    if not client:
        return False

    try:
        import uuid

        # Create new team
        team_id_master = str(uuid.uuid4())
        new_team = {
            'team_id_master': team_id_master,
            'team_name': team_data['team_name'],
            'club_name': team_data.get('club_name', ''),
            'age_group': team_data['age_group'],
            'gender': team_data['gender'],
            'state_code': team_data.get('state_code', ''),
            'provider_id': provider_id,
            'provider_team_id': provider_team_id
        }

        client.table('teams').insert(new_team).execute()

        # Link it
        return link_team_manually(provider_id, provider_team_id, team_id_master, team_data)
    except Exception as e:
        st.error(f"Error creating team: {e}")
        return False


def get_daily_game_imports(days=30):
    """Get daily game import counts."""
    client = get_supabase_client()
    if not client:
        return pd.DataFrame()

    try:
        # Query games grouped by date
        from datetime import datetime, timedelta, timezone

        # Calculate date range (timezone-aware)
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        # Try to fetch games using available timestamp columns
        # First try created_at, then fall back to scraped_at
        timestamp_col = None
        result = None

        # First, detect which timestamp column to use by sampling the table
        sample_result = client.table('games').select('*').limit(5).order('game_date', desc=True).execute()

        if not sample_result.data or len(sample_result.data) == 0:
            st.warning("⚠️ No games found in the database")
            return pd.DataFrame()

        sample_game = sample_result.data[0]

        # Debug info
        st.info(f"🔍 **Debug Info:** Found {len(sample_result.data)} sample games. Available columns: {list(sample_game.keys())}")

        # Determine which timestamp column to use
        timestamp_col = None
        if 'created_at' in sample_game and sample_game.get('created_at'):
            timestamp_col = 'created_at'
            st.info(f"📅 Using **created_at** for tracking. Sample value: {sample_game['created_at']}")
        elif 'scraped_at' in sample_game and sample_game.get('scraped_at'):
            timestamp_col = 'scraped_at'
            st.info(f"📅 Using **scraped_at** for tracking. Sample value: {sample_game['scraped_at']}")
        else:
            st.warning(f"⚠️ No valid timestamp column found. Available columns: {list(sample_game.keys())}")
            return pd.DataFrame()

        # Show date range being queried
        st.info(f"📆 Querying games from {start_date.date()} to {end_date.date()} (last {days} days)")

        # Fetch games in the date range (without order to avoid timeout, with reasonable limit)
        # Note: We're fetching up to 100k games which should be enough for daily tracking
        max_fetch = 100000
        result = client.table('games').select(
            timestamp_col
        ).gte(timestamp_col, start_date.isoformat()).limit(max_fetch).execute()

        games_found = len(result.data) if result.data else 0
        st.info(f"📊 Found {games_found:,} games in the date range" +
                (f" (limited to {max_fetch:,})" if games_found >= max_fetch else ""))

        if not result or not result.data:
            return pd.DataFrame()

        # Convert to DataFrame and group by date
        df = pd.DataFrame(result.data)
        df[timestamp_col] = pd.to_datetime(df[timestamp_col], utc=True)
        df['import_date'] = df[timestamp_col].dt.date

        # Count games per day
        daily_counts = df.groupby('import_date').size().reset_index(name='game_count')
        daily_counts['import_date'] = pd.to_datetime(daily_counts['import_date'])

        # Fill in missing dates with 0
        date_range = pd.date_range(start=start_date.date(), end=end_date.date(), freq='D')
        all_dates = pd.DataFrame({'import_date': date_range})
        daily_counts = all_dates.merge(daily_counts, on='import_date', how='left').fillna(0)
        daily_counts['game_count'] = daily_counts['game_count'].astype(int)

        return daily_counts
    except Exception as e:
        st.error(f"Error fetching daily imports: {e}")
        import traceback
        st.error(f"Details: {traceback.format_exc()}")
        return pd.DataFrame()


def get_stale_teams(days_threshold=10):
    """Get teams with stale scrape dates."""
    client = get_supabase_client()
    if not client:
        return pd.DataFrame()

    try:
        from datetime import datetime, timedelta, timezone

        # Calculate threshold date (timezone-aware)
        threshold_date = datetime.now(timezone.utc) - timedelta(days=days_threshold)

        # Query teams with old scrape dates or null scrape dates
        result = client.table('teams').select(
            'team_id_master, team_name, club_name, age_group, gender, state_code, '
            'last_scraped_at, created_at'
        ).or_(
            f'last_scraped_at.lt.{threshold_date.isoformat()},last_scraped_at.is.null'
        ).order('last_scraped_at', desc=False).limit(500).execute()

        if not result.data:
            return pd.DataFrame()

        # Convert to DataFrame
        df = pd.DataFrame(result.data)

        # Calculate days since last scrape
        if 'last_scraped_at' in df.columns:
            df['last_scraped_at'] = pd.to_datetime(df['last_scraped_at'], errors='coerce', utc=True)
            now_utc = pd.Timestamp.now(tz='UTC')
            df['days_since_scrape'] = (now_utc - df['last_scraped_at']).dt.days
            df['days_since_scrape'] = df['days_since_scrape'].fillna(999)  # For null values
        else:
            df['days_since_scrape'] = 999

        return df
    except Exception as e:
        st.error(f"Error fetching stale teams: {e}")
        return pd.DataFrame()


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
            "Unmatched Opponents",
            "Data Quality Monitoring",
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

    # Unmatched Opponents Section
    elif section == "Unmatched Opponents":
        st.markdown(
            "<h2 class='section-header'>🔍 Unmatched Opponents Review</h2>",
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
            **Review and match teams that couldn't be automatically matched**

            These teams appear in games but couldn't be matched to any team in the master database
            (confidence < 0.75). You can manually link them to existing teams or create new teams.
            """
        )

        # Overall matching statistics
        st.markdown("### 📊 Overall Matching Statistics")
        overall_stats = get_overall_matching_stats()

        if overall_stats:
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                st.metric("Total Games", f"{overall_stats['total_games']:,}")
            with col2:
                pct_both = (overall_stats['matched_both'] / overall_stats['total_games'] * 100) if overall_stats['total_games'] > 0 else 0
                st.metric("Both Teams Matched", f"{overall_stats['matched_both']:,}",
                         delta=f"{pct_both:.1f}%", delta_color="normal")
            with col3:
                pct_one = (overall_stats['matched_one'] / overall_stats['total_games'] * 100) if overall_stats['total_games'] > 0 else 0
                st.metric("One Team Matched", f"{overall_stats['matched_one']:,}",
                         delta=f"{pct_one:.1f}%", delta_color="off")
            with col4:
                pct_none = (overall_stats['matched_none'] / overall_stats['total_games'] * 100) if overall_stats['total_games'] > 0 else 0
                st.metric("No Teams Matched", f"{overall_stats['matched_none']:,}",
                         delta=f"{pct_none:.1f}%", delta_color="inverse")
            with col5:
                st.metric("Total Master Teams", f"{overall_stats['total_teams']:,}")

            # Match method breakdown
            st.markdown("#### Match Method Breakdown")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Fuzzy Auto-Matched", f"{overall_stats['fuzzy_auto']:,}",
                         help="Teams auto-matched with confidence ≥0.90")
            with col2:
                st.metric("Fuzzy Pending Review", f"{overall_stats['fuzzy_pending']:,}",
                         help="Teams needing manual review (0.75-0.89)")
            with col3:
                st.metric("Manual Matches", f"{overall_stats['manual_matches']:,}",
                         help="Teams manually linked by you")

        st.markdown("---")

        # Fetch unmatched opponents
        df = get_unmatched_opponents(limit=500)

        if df.empty:
            st.success("✅ No unmatched opponents! All teams are matched.")
            return

        # Unmatched teams statistics
        st.markdown("### 🔴 Unmatched Teams Details")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Unique Unmatched Teams", len(df))
        with col2:
            total_games = df['game_count'].sum() if 'game_count' in df.columns else 0
            st.metric("Total Games Affected", int(total_games))
        with col3:
            avg_games = df['game_count'].mean() if 'game_count' in df.columns and len(df) > 0 else 0
            st.metric("Avg Games per Team", f"{avg_games:.1f}")

        st.markdown("---")

        # Sort options
        col1, col2 = st.columns(2)
        with col1:
            sort_by = st.selectbox(
                "Sort by",
                options=["Game Count (High to Low)", "Most Recent Game", "Provider Team ID"],
                help="Choose how to sort unmatched teams"
            )
        with col2:
            show_count = st.slider(
                "Teams to display",
                min_value=10,
                max_value=min(200, len(df)),
                value=min(50, len(df)),
                step=10
            )

        # Apply sorting
        if sort_by == "Game Count (High to Low)":
            df_sorted = df.sort_values('game_count', ascending=False)
        elif sort_by == "Most Recent Game":
            df_sorted = df.sort_values('recent_game_date', ascending=False)
        else:
            df_sorted = df.sort_values('provider_team_id')

        df_display = df_sorted.head(show_count)

        st.markdown(f"### 📋 Unmatched Teams ({len(df_display)} of {len(df)})")

        # Display each unmatched team
        for idx, row in df_display.iterrows():
            team_id = row['provider_team_id']
            team_name = row.get('team_name', f'Unknown ({team_id})')

            with st.expander(
                f"🔴 **{team_name}** ({row.get('game_count', 0)} games) - Last seen: {row.get('recent_game_date', 'N/A')[:10]}",
                expanded=False
            ):
                # Team info
                col1, col2 = st.columns([2, 1])

                with col1:
                    st.markdown("#### Team Information")
                    st.markdown(f"**Team Name:** {team_name}")
                    st.markdown(f"**Provider Team ID:** `{team_id}`")
                    if row.get('age_group'):
                        st.markdown(f"**Age Group:** {row['age_group']}")
                    if row.get('gender'):
                        st.markdown(f"**Gender:** {row['gender']}")
                    st.markdown(f"**Games:** {row.get('game_count', 0)}")
                    st.markdown(f"**Most Recent Game:** {row.get('recent_game_date', 'N/A')[:10]}")
                    st.markdown(f"**Division:** {row.get('division_name', 'N/A')}")

                    # Show sample games
                    if 'sample_games' in row and row['sample_games']:
                        st.markdown("---")
                        st.markdown("**Sample Games:**")
                        for game in row['sample_games']:
                            # Add result emoji and opponent info if available
                            result = game.get('result', '')
                            result_emoji = '✅' if result == 'W' else '❌' if result == 'L' else '🤝' if result == 'D' else ''
                            opponent = game.get('opponent', 'Unknown Opponent')

                            game_display = f"- {game['date'][:10]} - "
                            if result_emoji:
                                game_display += f"{result_emoji} **{result}** - "
                            game_display += f"Score: {game['score']} - vs {opponent}"
                            if game.get('event') and game['event'] != 'N/A':
                                game_display += f" - {game['event']}"

                            st.markdown(game_display)

                with col2:
                    st.markdown("#### Auto-Suggestions")
                    # Auto-search for similar teams
                    if team_name and not team_name.startswith('Unknown'):
                        suggested_teams = search_teams(team_name,
                                                      age_group=row.get('age_group') if row.get('age_group') else None,
                                                      gender=row.get('gender') if row.get('gender') else None)
                        if suggested_teams:
                            st.markdown(f"**Found {len(suggested_teams)} similar teams:**")
                            for i, suggested in enumerate(suggested_teams[:3]):  # Show top 3
                                if st.button(f"✓ {suggested['team_name'][:30]}",
                                           key=f"quick_link_{team_id}_{i}",
                                           help=f"{suggested.get('club_name', 'N/A')} - {suggested['age_group']} {suggested['gender']}"):
                                    if link_team_manually(
                                        row.get('provider_id', ''),
                                        team_id,
                                        suggested['team_id_master'],
                                        suggested
                                    ):
                                        st.success(f"✅ Linked to {suggested['team_name']}!")
                                        st.rerun()
                        else:
                            st.info("No similar teams found. Try manual search or create new team below.")
                    else:
                        st.info("Enter team name in alias map to see suggestions.")

                st.markdown("---")
                st.markdown("### Manual Review Options")

                action = st.radio(
                    "Choose an action:",
                    options=["Search & Link", "Create New Team"],
                    key=f"manual_action_{team_id}",
                    horizontal=True
                )

                if action == "Search & Link":
                    st.markdown("#### Search Existing Teams")

                    search_col1, search_col2, search_col3 = st.columns(3)

                    with search_col1:
                        search_query = st.text_input(
                            "Search team name",
                            key=f"search_{team_id}",
                            placeholder="Enter team name..."
                        )

                    with search_col2:
                        age_group_filter = st.selectbox(
                            "Age Group",
                            options=["Any"] + sorted(list(AGE_GROUPS.keys())),
                            key=f"age_{team_id}"
                        )

                    with search_col3:
                        gender_filter = st.selectbox(
                            "Gender",
                            options=["Any", "Male", "Female"],
                            key=f"gender_{team_id}"
                        )

                    if st.button("🔍 Search", key=f"search_btn_{team_id}"):
                        results = search_teams(
                            search_query,
                            age_group=None if age_group_filter == "Any" else age_group_filter,
                            gender=None if gender_filter == "Any" else gender_filter
                        )

                        if results:
                            st.markdown(f"**Found {len(results)} teams:**")

                            for result in results:
                                result_col1, result_col2 = st.columns([3, 1])

                                with result_col1:
                                    st.markdown(
                                        f"**{result['team_name']}** - "
                                        f"{result.get('club_name', 'N/A')} - "
                                        f"{result['age_group']} {result['gender']} - "
                                        f"{result.get('state_code', 'N/A')}"
                                    )

                                with result_col2:
                                    if st.button("Link", key=f"link_{team_id}_{result['team_id_master']}"):
                                        if link_team_manually(
                                            row.get('provider_id', ''),
                                            team_id,
                                            result['team_id_master'],
                                            result
                                        ):
                                            st.success(f"✅ Successfully linked to {result['team_name']}!")
                                            st.rerun()
                                        else:
                                            st.error("Failed to link team.")
                        else:
                            st.warning("No teams found. Try different search criteria or create a new team.")

                else:  # Create New Team
                    st.markdown("#### Create New Team")

                    with st.form(key=f"create_team_form_{team_id}"):
                        form_col1, form_col2 = st.columns(2)

                        with form_col1:
                            new_team_name = st.text_input("Team Name *", key=f"new_name_{team_id}")
                            new_club_name = st.text_input("Club Name", key=f"new_club_{team_id}")
                            new_age_group = st.selectbox(
                                "Age Group *",
                                options=sorted(list(AGE_GROUPS.keys())),
                                key=f"new_age_{team_id}"
                            )

                        with form_col2:
                            new_gender = st.selectbox(
                                "Gender *",
                                options=["Male", "Female"],
                                key=f"new_gender_{team_id}"
                            )
                            new_state_code = st.text_input(
                                "State Code (2 letters)",
                                max_chars=2,
                                key=f"new_state_{team_id}"
                            )

                        submit = st.form_submit_button("✅ Create Team")

                        if submit:
                            if not new_team_name or not new_age_group or not new_gender:
                                st.error("Please fill in all required fields (*)")
                            else:
                                team_data = {
                                    'team_name': new_team_name,
                                    'club_name': new_club_name,
                                    'age_group': new_age_group,
                                    'gender': new_gender,
                                    'state_code': new_state_code.upper() if new_state_code else ''
                                }

                                if create_new_team(row.get('provider_id', ''), team_id, team_data):
                                    st.success(f"✅ Created and linked new team: {new_team_name}!")
                                    st.rerun()
                                else:
                                    st.error("Failed to create team.")

        # Help section
        st.markdown("---")
        with st.expander("ℹ️ Help & Information"):
            st.markdown("""
            ### What are Unmatched Opponents?

            Unmatched opponents are teams that appear in game records but couldn't be automatically
            matched to any team in your master database. This happens when:

            - The fuzzy match confidence score is below 0.75 (too uncertain)
            - The team name is completely different from all known teams
            - The team is genuinely new and hasn't been added to the database yet

            ### How to Review

            **Option 1: Search & Link to Existing Team**
            1. Use the search box to find similar teams in your database
            2. Filter by age group and gender to narrow results
            3. Click "Link" to connect the unmatched team to an existing team
            4. Future games with this team will automatically match

            **Option 2: Create New Team**
            1. Enter the team information (name, club, age group, gender, state)
            2. Click "Create Team" to add it to your master database
            3. The unmatched team will be linked to this new team
            4. Future games will match automatically

            ### Best Practices

            - Start with teams that have the most games (use "Game Count" sort)
            - Search carefully before creating new teams to avoid duplicates
            - Use consistent naming conventions when creating teams
            - Check age group and gender match the game data

            ### What Happens After Linking?

            When you link or create a team:
            1. An alias mapping is created in `team_alias_map`
            2. All existing games with this team are updated
            3. Future imports automatically match this team
            4. The team appears in rankings and statistics
            """)

    # Data Quality Monitoring Section
    elif section == "Data Quality Monitoring":
        st.markdown(
            "<h2 class='section-header'>📊 Data Quality Monitoring</h2>",
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
            **Monitor data import activity and data freshness**

            Track daily game imports and identify teams that may need data refresh.
            """
        )

        # Tab selection
        tab1, tab2 = st.tabs(["📈 Daily Game Imports", "⏰ Stale Teams"])

        with tab1:
            st.markdown("### 📈 Daily Game Import Activity")

            # Days selector
            col1, col2 = st.columns([1, 3])
            with col1:
                days_range = st.selectbox(
                    "Time Range",
                    options=[7, 14, 30, 60, 90],
                    index=2,
                    format_func=lambda x: f"Last {x} days"
                )

            # Fetch data
            df_imports = get_daily_game_imports(days=days_range)

            if df_imports.empty:
                st.warning("No game import data available for the selected period.")
            else:
                # Statistics
                total_games = df_imports['game_count'].sum()
                avg_daily = df_imports['game_count'].mean()
                max_daily = df_imports['game_count'].max()
                days_with_imports = (df_imports['game_count'] > 0).sum()

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total Games Imported", f"{int(total_games):,}")
                with col2:
                    st.metric("Avg Games/Day", f"{int(avg_daily):,}")
                with col3:
                    st.metric("Peak Day", f"{int(max_daily):,}")
                with col4:
                    st.metric("Active Days", f"{days_with_imports}/{len(df_imports)}")

                # Chart
                st.markdown("#### Import Trend")
                st.line_chart(
                    df_imports.set_index('import_date')['game_count'],
                    use_container_width=True
                )

                # Recent activity table
                st.markdown("#### Recent Import Activity (Last 14 Days)")
                recent_df = df_imports.tail(14).copy()
                recent_df['import_date'] = recent_df['import_date'].dt.strftime('%Y-%m-%d')
                recent_df.columns = ['Date', 'Games Imported']
                st.dataframe(
                    recent_df.sort_values('Date', ascending=False),
                    use_container_width=True,
                    hide_index=True
                )

        with tab2:
            st.markdown("### ⏰ Teams with Stale Scrape Data")

            # Threshold selector
            col1, col2 = st.columns([1, 3])
            with col1:
                days_threshold = st.number_input(
                    "Days Threshold",
                    min_value=1,
                    max_value=365,
                    value=10,
                    step=1,
                    help="Show teams not scraped in this many days"
                )

            # Fetch data
            df_stale = get_stale_teams(days_threshold=days_threshold)

            if df_stale.empty:
                st.success(f"✅ No teams with scrape data older than {days_threshold} days!")
            else:
                # Statistics
                total_stale = len(df_stale)
                never_scraped = (df_stale['days_since_scrape'] == 999).sum()
                very_stale = (df_stale['days_since_scrape'] > 30).sum()

                # Calculate average age (exclude never-scraped teams)
                scraped_teams = df_stale[df_stale['days_since_scrape'] != 999]
                if len(scraped_teams) > 0:
                    avg_age = scraped_teams['days_since_scrape'].mean()
                    avg_age_display = f"{int(avg_age)}"
                else:
                    avg_age_display = "N/A"

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total Stale Teams", f"{total_stale:,}")
                with col2:
                    st.metric("Never Scraped", f"{never_scraped:,}")
                with col3:
                    st.metric(">30 Days Old", f"{very_stale:,}")
                with col4:
                    st.metric("Avg Days Since Scrape", avg_age_display)

                # Filter options
                st.markdown("#### Filters")
                col1, col2, col3 = st.columns(3)

                with col1:
                    age_group_filter = st.selectbox(
                        "Age Group",
                        options=["All"] + sorted(df_stale['age_group'].unique().tolist()),
                        key="stale_age_filter"
                    )

                with col2:
                    gender_filter = st.selectbox(
                        "Gender",
                        options=["All"] + sorted(df_stale['gender'].unique().tolist()),
                        key="stale_gender_filter"
                    )

                with col3:
                    sort_by = st.selectbox(
                        "Sort By",
                        options=["Oldest First", "Team Name", "Age Group"],
                        key="stale_sort"
                    )

                # Apply filters
                filtered_df = df_stale.copy()
                if age_group_filter != "All":
                    filtered_df = filtered_df[filtered_df['age_group'] == age_group_filter]
                if gender_filter != "All":
                    filtered_df = filtered_df[filtered_df['gender'] == gender_filter]

                # Apply sorting
                if sort_by == "Oldest First":
                    filtered_df = filtered_df.sort_values('days_since_scrape', ascending=False)
                elif sort_by == "Team Name":
                    filtered_df = filtered_df.sort_values('team_name')
                else:
                    filtered_df = filtered_df.sort_values('age_group')

                # Display table
                st.markdown(f"#### Stale Teams ({len(filtered_df)} teams)")

                # Format for display
                display_df = filtered_df.copy()
                display_df['last_scraped_at'] = display_df['last_scraped_at'].dt.strftime('%Y-%m-%d %H:%M')
                display_df['last_scraped_at'] = display_df['last_scraped_at'].fillna('Never')

                # Select columns to display
                display_columns = {
                    'team_name': 'Team Name',
                    'club_name': 'Club',
                    'age_group': 'Age',
                    'gender': 'Gender',
                    'state_code': 'State',
                    'last_scraped_at': 'Last Scraped',
                    'days_since_scrape': 'Days Ago'
                }

                display_df = display_df[list(display_columns.keys())]
                display_df.columns = list(display_columns.values())

                # Replace 999 with "Never" for display
                display_df['Days Ago'] = display_df['Days Ago'].replace(999, '∞ (Never)')

                st.dataframe(
                    display_df,
                    use_container_width=True,
                    hide_index=True,
                    height=500
                )

                # Download option
                csv = filtered_df.to_csv(index=False)
                st.download_button(
                    label="📥 Download as CSV",
                    data=csv,
                    file_name=f"stale_teams_{days_threshold}_days.csv",
                    mime="text/csv"
                )

        # Help section
        st.markdown("---")
        with st.expander("ℹ️ Help & Information"):
            st.markdown("""
            ### Daily Game Imports

            **Purpose:** Monitor the health of your data import pipeline by tracking how many games
            are imported each day.

            **What to Look For:**
            - **Consistent imports** - Regular daily activity indicates healthy scraping
            - **Sudden drops** - May indicate scraper issues or no games available
            - **Spikes** - Large tournaments or batch imports
            - **Zero days** - Could indicate problems that need investigation

            **Use Cases:**
            - Verify scraper is running daily
            - Identify patterns in data availability
            - Confirm tournament data imports
            - Troubleshoot import pipeline issues

            ### Stale Teams

            **Purpose:** Identify teams that haven't been scraped recently and may have outdated
            schedule or game data.

            **What to Look For:**
            - **Never scraped** - Teams that were created but never had data collected
            - **Very stale (>30 days)** - Teams that may be inactive or missed by scraper
            - **Recently stale (10-30 days)** - Teams approaching the threshold

            **Recommended Actions:**
            1. Prioritize teams with many games for scraping
            2. Check if teams are still active (verify on source website)
            3. Update scraper configuration if teams are consistently missed
            4. Archive inactive teams to reduce noise

            **Best Practices:**
            - Review stale teams weekly
            - Set threshold based on your scraping frequency
            - Keep threshold at 2-3x your normal scraping interval
            - Document teams that are intentionally not scraped
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
