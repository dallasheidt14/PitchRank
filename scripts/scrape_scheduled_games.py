#!/usr/bin/env python3
"""
Scheduled Games Scraper - Find future matchups from GotSport

This is a STANDALONE scraper that:
1. Takes a list of team IDs (our top-ranked teams)
2. Calls GotSport API to get their matches
3. Extracts games with future dates (no scores yet)
4. Stores them for "big game" social content

Does NOT touch the main scraper or games table.

Usage:
    python scripts/scrape_scheduled_games.py --limit 100
    python scripts/scrape_scheduled_games.py --state TX --limit 50
"""

import os
import sys
import json
import argparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import time
import random
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import psycopg2

# Try to import certifi for better SSL handling
try:
    import certifi
    CERTIFI_AVAILABLE = True
except ImportError:
    CERTIFI_AVAILABLE = False
    certifi = None

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# GotSport API
GOTSPORT_API = "https://system.gotsport.com/api/v1"

# Rate limiting - configurable via environment
DELAY_MIN = float(os.getenv('SCHEDULED_SCRAPER_DELAY_MIN', '1.5'))
DELAY_MAX = float(os.getenv('SCHEDULED_SCRAPER_DELAY_MAX', '2.5'))
MAX_RETRIES = int(os.getenv('SCHEDULED_SCRAPER_MAX_RETRIES', '3'))
TIMEOUT = int(os.getenv('SCHEDULED_SCRAPER_TIMEOUT', '30'))
RETRY_DELAY = float(os.getenv('SCHEDULED_SCRAPER_RETRY_DELAY', '2.0'))


def create_http_session() -> requests.Session:
    """
    Create an optimized HTTP session with connection pooling and retry logic.
    
    Features:
    - Connection pooling for reuse (faster, less overhead)
    - Automatic retry on 500/502/503/504 errors
    - Exponential backoff on retries
    - Proper SSL certificate handling via certifi
    """
    session = requests.Session()
    
    # SSL configuration: use certifi if available
    verify_ssl = True
    if CERTIFI_AVAILABLE:
        verify_ssl = certifi.where()
        logger.debug(f"Using certifi certificates")
    
    # Configure retry strategy
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.3,  # 0.3, 0.6, 1.2 seconds
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"]
    )
    
    # HTTPAdapter with connection pooling
    adapter = HTTPAdapter(
        pool_connections=20,  # Number of connection pools
        pool_maxsize=20,      # Max connections per pool
        max_retries=retry_strategy
    )
    
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    # Set SSL verification
    session.verify = verify_ssl
    
    # Set headers to look like a real browser
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Origin': 'https://rankings.gotsport.com',
        'Referer': 'https://rankings.gotsport.com/',
        'Connection': 'keep-alive',
    })
    
    return session


def get_db_connection():
    """Get database connection."""
    return psycopg2.connect(os.environ['DATABASE_URL'])


def get_top_teams(conn, limit: int = 2000, state: Optional[str] = None, 
                   top_per_group: int = 100, all_states: bool = False,
                   states: Optional[List[str]] = None) -> List[Dict]:
    """Get top-ranked teams with their GotSport provider IDs.
    
    Strategy: Get top N teams PER AGE GROUP/GENDER to ensure coverage across
    all competitive brackets. Teams only play within their age group, so this
    ensures we catch big matchups in every bracket.
    
    Args:
        conn: Database connection
        limit: Max total teams to return (default 2000 = ~100 per group * 18 groups)
        state: Filter to specific state (optional, ignored if all_states=True)
        top_per_group: Include top N teams per group combo (default 100)
        all_states: If True, partition by state/age/gender and use state_rank
        states: List of state codes to filter (implies all_states mode)
    """
    cur = conn.cursor()
    
    # Valid age groups: U10-U18 only (no U8, U9, U19+)
    valid_age_groups = ['u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16', 'u17', 'u18',
                        'U10', 'U11', 'U12', 'U13', 'U14', 'U15', 'U16', 'U17', 'U18']
    
    params = []
    
    # If states list provided, use all_states mode
    if states:
        all_states = True
    
    if all_states:
        # Get top N teams PER STATE/AGE GROUP/GENDER
        # Compute state_rank on-the-fly from national_power_score within state/age/gender
        
        # Build state filter if specific states requested
        state_filter = ""
        if states:
            placeholders = ','.join(['%s'] * len(states))
            state_filter = f"AND t.state_code IN ({placeholders})"
            params.extend(states)
        
        query = f'''
            WITH team_with_providers AS (
                SELECT DISTINCT ON (cr.team_id)
                    cr.team_id,
                    cr.national_rank,
                    cr.national_power_score,
                    t.team_name,
                    t.club_name,
                    t.state_code,
                    t.age_group,
                    t.gender,
                    g.home_provider_id as provider_id
                FROM current_rankings cr
                JOIN teams t ON cr.team_id = t.team_id_master
                JOIN games g ON cr.team_id = g.home_team_master_id
                WHERE g.home_provider_id IS NOT NULL
                AND LENGTH(g.home_provider_id) <= 10
                AND cr.national_rank IS NOT NULL
                AND t.state_code IS NOT NULL
                {state_filter}
                AND t.age_group IN ('u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16', 'u17', 'u18', 'U10', 'U11', 'U12', 'U13', 'U14', 'U15', 'U16', 'U17', 'U18')
                ORDER BY cr.team_id, cr.national_rank
            ),
            ranked_by_state_group AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY state_code, LOWER(age_group), gender 
                        ORDER BY national_power_score DESC NULLS LAST, national_rank ASC
                    ) as state_rank,
                    ROW_NUMBER() OVER (
                        PARTITION BY state_code, LOWER(age_group), gender 
                        ORDER BY national_power_score DESC NULLS LAST, national_rank ASC
                    ) as rank_in_group
                FROM team_with_providers
            )
            SELECT * FROM ranked_by_state_group
            WHERE rank_in_group <= %s
            ORDER BY state_code, age_group, gender, state_rank
            LIMIT %s
        '''
        params.extend([top_per_group, limit])
    else:
        # Original behavior: top N teams PER AGE GROUP/GENDER using national_rank
        query = '''
            WITH team_rankings AS (
                SELECT DISTINCT ON (cr.team_id)
                    cr.team_id,
                    cr.national_rank,
                    cr.state_rank,
                    cr.national_power_score,
                    t.team_name,
                    t.club_name,
                    t.state_code,
                    t.age_group,
                    t.gender,
                    g.home_provider_id as provider_id
                FROM current_rankings cr
                JOIN teams t ON cr.team_id = t.team_id_master
                JOIN games g ON cr.team_id = g.home_team_master_id
                WHERE g.home_provider_id IS NOT NULL
                AND LENGTH(g.home_provider_id) <= 10
                AND cr.national_rank IS NOT NULL
                AND t.age_group IN ('u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16', 'u17', 'u18', 'U10', 'U11', 'U12', 'U13', 'U14', 'U15', 'U16', 'U17', 'U18')
        '''
        
        if state:
            query += ' AND t.state_code = %s'
            params.append(state)
        
        query += '''
                ORDER BY cr.team_id, cr.national_rank
            ),
            ranked_by_group AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY LOWER(age_group), gender 
                        ORDER BY national_rank
                    ) as rank_in_group
                FROM team_rankings
            )
            SELECT * FROM ranked_by_group
            WHERE rank_in_group <= %s
            ORDER BY age_group, gender, national_rank
            LIMIT %s
        '''
        params.extend([top_per_group, limit])
    
    cur.execute(query, params)
    columns = [desc[0] for desc in cur.description]
    
    teams = []
    for row in cur.fetchall():
        team = dict(zip(columns, row))
        teams.append(team)
    
    return teams


def fetch_team_matches(session: requests.Session, team_id: str) -> Optional[List[Dict]]:
    """
    Fetch all matches for a team from GotSport API.
    
    Uses manual retry loop on top of urllib3's automatic retries for:
    - Timeout errors
    - Connection errors
    - SSL errors (with session reset)
    """
    url = f"{GOTSPORT_API}/teams/{team_id}/matches"
    
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, timeout=TIMEOUT)
            
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404:
                logger.debug(f"Team {team_id} not found (404)")
                return None
            else:
                logger.warning(f"API returned {resp.status_code} for team {team_id}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                return None
                
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY * (attempt + 1)
                logger.warning(f"Timeout for team {team_id} (attempt {attempt + 1}/{MAX_RETRIES}), retrying in {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue
            logger.error(f"Timeout for team {team_id} after {MAX_RETRIES} attempts")
            return None
            
        except requests.exceptions.SSLError as e:
            if attempt < MAX_RETRIES - 1:
                # Exponential backoff for SSL errors
                wait_time = RETRY_DELAY * (2 ** attempt) + random.uniform(0, 1.0)
                logger.warning(f"SSL error for team {team_id} (attempt {attempt + 1}/{MAX_RETRIES}), retrying in {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue
            logger.error(f"SSL error for team {team_id} after {MAX_RETRIES} attempts: {e}")
            return None
            
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY * (attempt + 1)
                logger.warning(f"Request error for team {team_id} (attempt {attempt + 1}/{MAX_RETRIES}): {e}, retrying...")
                time.sleep(wait_time)
                continue
            logger.error(f"Request failed for team {team_id} after {MAX_RETRIES} attempts: {e}")
            return None
    
    return None


def extract_future_games(matches: List[Dict], team_info: Dict) -> List[Dict]:
    """Extract games with future dates from API response."""
    future_games = []
    now = datetime.now()
    
    for match in matches:
        match_time_str = match.get('matchTime')
        if not match_time_str:
            continue
        
        try:
            # Filter out U19 games (PitchRank only supports U10-U18)
            # Check if either team is U19 based on age_group or birth_year
            home_team = match.get('homeTeam', {})
            away_team = match.get('awayTeam', {})
            
            is_u19_game = False
            for team_obj in [home_team, away_team]:
                if isinstance(team_obj, dict):
                    age_group = team_obj.get('age_group', '').upper().strip()
                    birth_year = team_obj.get('birth_year')
                    
                    # Skip if age_group indicates U19
                    if age_group in ['U19', 'U-19', '19U', 'U20', 'U-20', '20U']:
                        is_u19_game = True
                        logger.debug(f"Skipping U19/U20 scheduled game (age_group={age_group})")
                        break
                    
                    # Skip if birth_year is 2007 or earlier (U19+ for 2026)
                    if birth_year and isinstance(birth_year, (int, str)):
                        try:
                            birth_year_int = int(birth_year)
                            if birth_year_int <= 2007:
                                is_u19_game = True
                                logger.debug(f"Skipping U19+ scheduled game (birth_year={birth_year_int})")
                                break
                        except (ValueError, TypeError):
                            pass
            
            if is_u19_game:
                continue
            
            # Parse ISO datetime
            match_time = datetime.fromisoformat(match_time_str.replace('Z', '+00:00'))
            match_date = match_time.replace(tzinfo=None)
            
            # Check if future
            if match_date <= now:
                continue
            
            # Check if no scores (truly scheduled, not completed)
            home_score = match.get('home_score')
            away_score = match.get('away_score')
            
            # Some games have scores even if in "future" (data issues) - skip those
            if home_score is not None and away_score is not None:
                continue
            
            # Extract game info
            title = match.get('title', '')
            # Title format: "Team A vs. Team B" or "Team A vs Team B"
            teams_in_title = title.replace(' vs. ', ' vs ').split(' vs ')
            
            home_team = teams_in_title[0].strip() if len(teams_in_title) > 0 else ''
            away_team = teams_in_title[1].strip() if len(teams_in_title) > 1 else ''
            
            future_games.append({
                'match_id': match.get('id'),
                'match_time': match_time_str,
                'match_date': match_date.strftime('%Y-%m-%d'),
                'event_id': match.get('event_id'),
                'event_name': match.get('event_name', ''),
                'bracket_id': match.get('bracket_id'),
                'home_team_name': home_team,
                'away_team_name': away_team,
                'title': title,
                # Track which of our teams this came from
                'source_team_id': team_info['provider_id'],
                'source_team_name': team_info['team_name'],
                'source_club': team_info['club_name'],
                'source_state': team_info['state_code'],
            })
            
        except Exception as e:
            continue
    
    return future_games


def save_scheduled_games(conn, games: List[Dict]):
    """Save scheduled games to database."""
    if not games:
        return 0
    
    cur = conn.cursor()
    
    # Create table if not exists
    cur.execute('''
        CREATE TABLE IF NOT EXISTS scheduled_games (
            id SERIAL PRIMARY KEY,
            match_id BIGINT UNIQUE,
            match_time TIMESTAMPTZ,
            match_date DATE,
            event_id INTEGER,
            event_name TEXT,
            bracket_id INTEGER,
            home_team_name TEXT,
            away_team_name TEXT,
            title TEXT,
            source_team_id TEXT,
            source_team_name TEXT,
            source_club TEXT,
            source_state TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    ''')
    
    # Create index on match_date for quick lookups
    cur.execute('''
        CREATE INDEX IF NOT EXISTS idx_scheduled_games_date 
        ON scheduled_games(match_date)
    ''')
    
    inserted = 0
    for game in games:
        try:
            cur.execute('''
                INSERT INTO scheduled_games 
                (match_id, match_time, match_date, event_id, event_name, bracket_id,
                 home_team_name, away_team_name, title, source_team_id, 
                 source_team_name, source_club, source_state)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (match_id) DO UPDATE SET
                    match_time = EXCLUDED.match_time,
                    event_name = EXCLUDED.event_name,
                    title = EXCLUDED.title,
                    updated_at = NOW()
            ''', (
                game['match_id'],
                game['match_time'],
                game['match_date'],
                game['event_id'],
                game['event_name'],
                game['bracket_id'],
                game['home_team_name'],
                game['away_team_name'],
                game['title'],
                game['source_team_id'],
                game['source_team_name'],
                game['source_club'],
                game['source_state'],
            ))
            inserted += 1
        except Exception as e:
            logger.warning(f"Error saving game {game.get('match_id')}: {e}")
    
    conn.commit()
    return inserted


def main():
    parser = argparse.ArgumentParser(description='Scrape scheduled/future games from GotSport')
    parser.add_argument('--limit', type=int, default=50, help='Max total teams to check')
    parser.add_argument('--state', type=str, help='Filter by state code (e.g., TX, CA)')
    parser.add_argument('--all-states', action='store_true', 
                        help='Get top N teams per state/age/gender (use with --top-per-group)')
    parser.add_argument('--states', type=str,
                        help='Comma-separated state codes (e.g., CA,TX,AZ). Implies --all-states')
    parser.add_argument('--top-per-group', type=int, default=25,
                        help='Teams per group (default 25, used with --all-states or --states)')
    parser.add_argument('--dry-run', action='store_true', help='Print findings without saving')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Parse states list if provided
    states_list = None
    if args.states:
        states_list = [s.strip().upper() for s in args.states.split(',')]
    
    print(f"🔮 Scheduled Games Scraper")
    if args.all_states or states_list:
        if states_list:
            print(f"   Mode: Top {args.top_per_group} teams per age/gender in {', '.join(states_list)}")
        else:
            print(f"   Mode: Top {args.top_per_group} teams per state/age/gender (all states)")
        print(f"   Max total: {args.limit} teams")
    else:
        print(f"   Checking up to {args.limit} teams" + (f" in {args.state}" if args.state else ""))
    print(f"   Rate limiting: {DELAY_MIN:.1f}-{DELAY_MAX:.1f}s between requests")
    print(f"   Max retries: {MAX_RETRIES}, timeout: {TIMEOUT}s")
    print()
    
    conn = get_db_connection()
    
    # Create reusable HTTP session with connection pooling
    session = create_http_session()
    logger.info("Created HTTP session with connection pooling and retry logic")
    
    # Get teams to check
    teams = get_top_teams(
        conn, 
        limit=args.limit, 
        state=args.state if not (args.all_states or states_list) else None,
        top_per_group=args.top_per_group,
        all_states=args.all_states,
        states=states_list
    )
    print(f"Found {len(teams)} teams with GotSport IDs")
    
    all_future_games = []
    teams_with_future = 0
    failed_requests = 0
    
    for i, team in enumerate(teams):
        provider_id = team['provider_id']
        print(f"[{i+1}/{len(teams)}] {team['club_name']} {team['team_name']} ({provider_id})...", end=' ', flush=True)
        
        # Rate limiting (before request, not after, to avoid unnecessary delay at end)
        if i > 0:
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        
        matches = fetch_team_matches(session, provider_id)
        if matches is None:
            print("failed")
            failed_requests += 1
            continue
        
        if not matches:
            print("no data")
            continue
        
        future_games = extract_future_games(matches, team)
        
        if future_games:
            print(f"✓ {len(future_games)} future games!")
            all_future_games.extend(future_games)
            teams_with_future += 1
            
            # Show first few
            for g in future_games[:2]:
                print(f"    📅 {g['match_date']}: {g['title']} @ {g['event_name'][:40]}")
        else:
            print("no future games")
    
    # Close session
    session.close()
    
    print()
    print(f"=" * 50)
    print(f"Summary:")
    print(f"  Teams checked: {len(teams)}")
    print(f"  Failed requests: {failed_requests}")
    print(f"  Teams with future games: {teams_with_future}")
    print(f"  Total future games found: {len(all_future_games)}")
    
    if all_future_games:
        # Deduplicate by match_id
        unique_games = {g['match_id']: g for g in all_future_games}.values()
        print(f"  Unique games: {len(unique_games)}")
        
        if not args.dry_run:
            saved = save_scheduled_games(conn, list(unique_games))
            print(f"  Saved to database: {saved}")
        else:
            print("  (dry-run, not saved)")
        
        # Show upcoming games by date
        print()
        print("📅 Upcoming games by date:")
        by_date = {}
        for g in unique_games:
            date = g['match_date']
            if date not in by_date:
                by_date[date] = []
            by_date[date].append(g)
        
        for date in sorted(by_date.keys())[:7]:  # Next 7 days with games
            print(f"  {date}: {len(by_date[date])} games")
            for g in by_date[date][:3]:
                print(f"    • {g['title']}")
    
    conn.close()


if __name__ == '__main__':
    main()
