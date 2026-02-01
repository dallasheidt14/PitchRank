#!/usr/bin/env python3
"""
Big Game Finder - Find marquee matchups between top-ranked teams

This script:
1. Queries scheduled_games table
2. Matches team names to our rankings
3. Identifies games where BOTH teams are highly ranked
4. Outputs social-media-ready content

Usage:
    python scripts/find_big_games.py --days 7
    python scripts/find_big_games.py --min-rank 50  # Both teams must be top 50
"""

import os
import sys
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import psycopg2


def get_db_connection():
    return psycopg2.connect(os.environ['DATABASE_URL'])


def find_big_games(conn, days: int = 7, min_rank: int = 100):
    """Find scheduled games between highly-ranked teams."""
    cur = conn.cursor()
    
    # Get scheduled games in the date range
    start_date = datetime.now().date()
    end_date = start_date + timedelta(days=days)
    
    cur.execute('''
        SELECT 
            sg.match_date,
            sg.home_team_name,
            sg.away_team_name,
            sg.event_name,
            sg.title,
            sg.match_time
        FROM scheduled_games sg
        WHERE sg.match_date BETWEEN %s AND %s
        ORDER BY sg.match_date
    ''', (start_date, end_date))
    
    scheduled = cur.fetchall()
    print(f"Found {len(scheduled)} scheduled games in next {days} days")
    
    if not scheduled:
        return []
    
    # Get current rankings (simplified - just get top teams)
    # In a real implementation, you'd have a proper rankings table
    cur.execute('''
        SELECT 
            t.team_name,
            t.club_name,
            t.state_code,
            t.gender,
            t.age_group,
            COUNT(g.id) as game_count
        FROM teams t
        JOIN games g ON g.home_team_master_id = t.id OR g.away_team_master_id = t.id
        WHERE g.game_date > NOW() - INTERVAL '180 days'
        GROUP BY t.id, t.team_name, t.club_name, t.state_code, t.gender, t.age_group
        HAVING COUNT(g.id) >= 10
        ORDER BY COUNT(g.id) DESC
        LIMIT 1000
    ''')
    
    # Build a lookup of team names
    ranked_teams = {}
    for i, row in enumerate(cur.fetchall()):
        team_name = row[0]
        club_name = row[1]
        # Store with rank (position in list)
        key = f"{club_name} {team_name}".lower()
        ranked_teams[key] = {
            'rank': i + 1,
            'team_name': team_name,
            'club_name': club_name,
            'state': row[2],
            'gender': row[3],
            'age_group': row[4],
            'games': row[5]
        }
    
    print(f"Loaded {len(ranked_teams)} ranked teams")
    
    # Find matchups
    big_games = []
    
    for match_date, home, away, event, title, match_time in scheduled:
        # Try to match home team
        home_lower = home.lower()
        away_lower = away.lower()
        
        home_match = None
        away_match = None
        
        # Simple fuzzy match - check if our ranked team name is in the scheduled name
        for key, team in ranked_teams.items():
            if team['club_name'].lower() in home_lower or team['team_name'].lower() in home_lower:
                if home_match is None or team['rank'] < home_match['rank']:
                    home_match = team
            if team['club_name'].lower() in away_lower or team['team_name'].lower() in away_lower:
                if away_match is None or team['rank'] < away_match['rank']:
                    away_match = team
        
        # If both teams matched and both are top-ranked
        if home_match and away_match:
            if home_match['rank'] <= min_rank and away_match['rank'] <= min_rank:
                big_games.append({
                    'date': match_date,
                    'time': match_time,
                    'event': event,
                    'title': title,
                    'home': home,
                    'away': away,
                    'home_rank': home_match['rank'],
                    'away_rank': away_match['rank'],
                    'home_info': home_match,
                    'away_info': away_match,
                })
    
    return big_games


def format_for_social(games):
    """Format big games for social media posts."""
    if not games:
        print("\nNo big games found!")
        return
    
    print(f"\n🔥 BIG GAMES ALERT 🔥")
    print("=" * 50)
    
    for game in sorted(games, key=lambda x: (x['date'], -(x['home_rank'] + game['away_rank']))):
        date_str = game['date'].strftime('%A, %b %d')
        
        print(f"\n📅 {date_str}")
        print(f"🏆 #{game['home_rank']} {game['home']}")
        print(f"   vs")
        print(f"🏆 #{game['away_rank']} {game['away']}")
        print(f"📍 {game['event'][:50]}")
        
        # Social media ready text
        print(f"\n💬 Social post:")
        print(f"🔥 MARQUEE MATCHUP 🔥")
        print(f"#{game['home_rank']} {game['home_info']['club_name']} vs #{game['away_rank']} {game['away_info']['club_name']}")
        print(f"📅 {date_str} | {game['event'][:30]}")
        print(f"#YouthSoccer #PitchRank")


def main():
    parser = argparse.ArgumentParser(description='Find big games between top-ranked teams')
    parser.add_argument('--days', type=int, default=7, help='Days ahead to look')
    parser.add_argument('--min-rank', type=int, default=100, help='Both teams must be within this rank')
    args = parser.parse_args()
    
    print(f"🎯 Big Game Finder")
    print(f"   Looking {args.days} days ahead for top-{args.min_rank} matchups")
    print()
    
    conn = get_db_connection()
    
    # First check if scheduled_games table exists and has data
    cur = conn.cursor()
    cur.execute('''
        SELECT COUNT(*) FROM information_schema.tables 
        WHERE table_name = 'scheduled_games'
    ''')
    
    if cur.fetchone()[0] == 0:
        print("❌ No scheduled_games table yet!")
        print("   Run: python scripts/scrape_scheduled_games.py --limit 100")
        return
    
    cur.execute('SELECT COUNT(*) FROM scheduled_games')
    count = cur.fetchone()[0]
    print(f"📊 {count} scheduled games in database")
    
    if count == 0:
        print("   Run the scraper first to populate scheduled games")
        return
    
    big_games = find_big_games(conn, days=args.days, min_rank=args.min_rank)
    
    print(f"\n🎯 Found {len(big_games)} big game matchups!")
    
    format_for_social(big_games)
    
    conn.close()


if __name__ == '__main__':
    main()
