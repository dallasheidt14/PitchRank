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
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import time
import random

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import psycopg2

# GotSport API
GOTSPORT_API = "https://system.gotsport.com/api/v1"

# Rate limiting
DELAY_MIN = 2.0  # Be nice to their API
DELAY_MAX = 4.0


def get_db_connection():
    """Get database connection."""
    return psycopg2.connect(os.environ['DATABASE_URL'])


def get_top_teams(conn, limit: int = 100, state: Optional[str] = None, 
                   top_per_state: int = 20, top_national: int = 300) -> List[Dict]:
    """Get top-ranked teams with their GotSport provider IDs.
    
    Strategy: Get top N teams per state OR top M nationally, whichever produces
    teams that matter for "big game" content.
    
    Args:
        conn: Database connection
        limit: Max total teams to return
        state: Filter to specific state (optional)
        top_per_state: Include teams ranked top N in their state
        top_national: Include teams ranked top N nationally
    """
    cur = conn.cursor()
    
    # Get top-ranked teams by joining current_rankings to games for provider IDs
    query = '''
        WITH ranked_teams AS (
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
            AND (
                cr.national_rank <= %s
                OR cr.state_rank <= %s
            )
    '''
    
    params = [top_national, top_per_state]
    
    if state:
        query += ' AND t.state_code = %s'
        params.append(state)
    
    query += '''
            ORDER BY cr.team_id, cr.national_rank NULLS LAST
        )
        SELECT * FROM ranked_teams
        ORDER BY national_rank NULLS LAST
        LIMIT %s
    '''
    params.append(limit)
    
    cur.execute(query, params)
    columns = [desc[0] for desc in cur.description]
    
    teams = []
    for row in cur.fetchall():
        team = dict(zip(columns, row))
        teams.append(team)
    
    return teams


def fetch_team_matches(team_id: str, timeout: int = 30) -> Optional[List[Dict]]:
    """Fetch all matches for a team from GotSport API."""
    url = f"{GOTSPORT_API}/teams/{team_id}/matches"
    
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"  API returned {resp.status_code} for team {team_id}")
            return None
    except requests.exceptions.Timeout:
        print(f"  Timeout for team {team_id}")
        return None
    except Exception as e:
        print(f"  Error fetching team {team_id}: {e}")
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
            print(f"  Error saving game {game.get('match_id')}: {e}")
    
    conn.commit()
    return inserted


def main():
    parser = argparse.ArgumentParser(description='Scrape scheduled/future games from GotSport')
    parser.add_argument('--limit', type=int, default=50, help='Number of teams to check')
    parser.add_argument('--state', type=str, help='Filter by state code (e.g., TX, CA)')
    parser.add_argument('--dry-run', action='store_true', help='Print findings without saving')
    args = parser.parse_args()
    
    print(f"🔮 Scheduled Games Scraper")
    print(f"   Checking up to {args.limit} teams" + (f" in {args.state}" if args.state else ""))
    print()
    
    conn = get_db_connection()
    
    # Get teams to check
    teams = get_top_teams(conn, limit=args.limit, state=args.state)
    print(f"Found {len(teams)} teams with GotSport IDs")
    
    all_future_games = []
    teams_with_future = 0
    
    for i, team in enumerate(teams):
        provider_id = team['provider_id']
        print(f"[{i+1}/{len(teams)}] {team['club_name']} {team['team_name']} ({provider_id})...", end=' ')
        
        # Rate limiting
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        
        matches = fetch_team_matches(provider_id)
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
    
    print()
    print(f"=" * 50)
    print(f"Summary:")
    print(f"  Teams checked: {len(teams)}")
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
