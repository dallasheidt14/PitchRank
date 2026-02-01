#!/usr/bin/env python3
"""
Weekend Preview Generator - Create social content for upcoming big games

This script:
1. Queries scheduled_games for upcoming weekend matchups
2. Cross-references with rankings to find marquee games
3. Generates social-media-ready content

Usage:
    python scripts/generate_weekend_preview.py
    python scripts/generate_weekend_preview.py --days 4  # Look 4 days ahead
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import psycopg2


def get_db_connection():
    return psycopg2.connect(os.environ['DATABASE_URL'])


def get_weekend_games(conn, days: int = 4) -> List[Dict]:
    """Get scheduled games for the upcoming weekend."""
    cur = conn.cursor()
    
    start_date = datetime.now().date()
    end_date = start_date + timedelta(days=days)
    
    cur.execute('''
        SELECT 
            match_date,
            home_team_name,
            away_team_name,
            event_name,
            title,
            source_team_name,
            source_club,
            source_state
        FROM scheduled_games
        WHERE match_date BETWEEN %s AND %s
        ORDER BY match_date, event_name
    ''', (start_date, end_date))
    
    columns = [desc[0] for desc in cur.description]
    games = [dict(zip(columns, row)) for row in cur.fetchall()]
    
    return games


def enrich_with_rankings(conn, games: List[Dict]) -> List[Dict]:
    """Add ranking info for teams in the games."""
    if not games:
        return games
    
    cur = conn.cursor()
    
    # Build lookup of team rankings with full team name for precise matching
    cur.execute('''
        SELECT 
            t.club_name,
            t.team_name,
            t.state_code,
            t.age_group,
            t.gender,
            cr.national_rank,
            cr.state_rank,
            cr.national_power_score
        FROM current_rankings cr
        JOIN teams t ON cr.team_id = t.team_id_master
        WHERE cr.national_rank <= 500 OR cr.state_rank <= 50
    ''')
    
    rankings_list = []
    for row in cur.fetchall():
        club, team, state, age, gender, nat_rank, state_rank, power = row
        # Create full name for matching
        full_name = f"{club} {team}".lower().strip()
        
        rankings_list.append({
            'full_name': full_name,
            'club_name': club,
            'team_name': team,
            'state': state,
            'age_group': age,
            'gender': gender,
            'national_rank': nat_rank,
            'state_rank': state_rank,
            'power_score': power
        })
    
    def find_best_match(team_name: str, exclude_match: dict = None) -> Optional[dict]:
        """Find best ranking match for a team name, optionally excluding a match."""
        if not team_name:
            return None
        
        team_lower = team_name.lower().strip()
        best_match = None
        best_score = 0
        
        for info in rankings_list:
            # Skip if this is the excluded match (to prevent same team matching both sides)
            if exclude_match and info['full_name'] == exclude_match.get('full_name'):
                continue
            
            # Calculate match score - prefer longer matches
            score = 0
            
            # Exact full name match
            if info['full_name'] == team_lower:
                score = 100
            # Full name contains team name or vice versa
            elif info['full_name'] in team_lower:
                score = len(info['full_name'])
            elif team_lower in info['full_name']:
                score = len(team_lower)
            # Club name match (weaker)
            elif info['club_name'] and info['club_name'].lower() in team_lower:
                score = len(info['club_name']) * 0.5
            
            # Update best if this is better
            if score > best_score and score >= 5:  # Minimum 5 chars to match
                best_score = score
                best_match = info
        
        return best_match
    
    # Enrich games
    enriched = []
    for game in games:
        home = game['home_team_name']
        away = game['away_team_name']
        
        # Find home ranking first
        home_rank = find_best_match(home)
        
        # Find away ranking, excluding home match to prevent duplicates
        away_rank = find_best_match(away, exclude_match=home_rank)
        
        game['home_ranking'] = home_rank
        game['away_ranking'] = away_rank
        
        # Calculate "big game" score - both teams must be DIFFERENT and ranked
        game['is_big_game'] = False
        if home_rank and away_rank and home_rank['full_name'] != away_rank['full_name']:
            h_nat = home_rank.get('national_rank') or 9999
            a_nat = away_rank.get('national_rank') or 9999
            # Both teams in top 200 nationally = big game
            if h_nat <= 200 and a_nat <= 200:
                game['is_big_game'] = True
                game['combined_rank'] = h_nat + a_nat
        
        enriched.append(game)
    
    return enriched


def generate_preview_content(games: List[Dict]) -> Dict:
    """Generate social media content from games."""
    
    # Filter to big games
    big_games = [g for g in games if g.get('is_big_game')]
    big_games.sort(key=lambda x: x.get('combined_rank', 9999))
    
    # Group by date
    by_date = {}
    for game in games:
        date = game['match_date']
        if date not in by_date:
            by_date[date] = []
        by_date[date].append(game)
    
    # Group by event
    by_event = {}
    for game in games:
        event = game.get('event_name', 'Unknown')
        if event not in by_event:
            by_event[event] = []
        by_event[event].append(game)
    
    content = {
        'total_games': len(games),
        'big_games': big_games,
        'by_date': by_date,
        'by_event': by_event,
        'social_posts': []
    }
    
    # Generate social posts
    if big_games:
        # Main marquee matchup post
        top_game = big_games[0]
        h_rank = top_game['home_ranking']['national_rank'] if top_game.get('home_ranking') else '?'
        a_rank = top_game['away_ranking']['national_rank'] if top_game.get('away_ranking') else '?'
        
        post = f"""🔥 WEEKEND MARQUEE MATCHUP 🔥

#{h_rank} {top_game['home_team_name']}
   vs
#{a_rank} {top_game['away_team_name']}

📅 {top_game['match_date'].strftime('%A, %b %d')}
🏆 {top_game['event_name'][:50]}

#YouthSoccer #PitchRank #WeekendPreview"""
        
        content['social_posts'].append({
            'type': 'marquee',
            'game': top_game,
            'text': post
        })
        
        # If multiple big games, create a roundup
        if len(big_games) > 1:
            roundup = "🎯 THIS WEEKEND'S BIG GAMES 🎯\n\n"
            for i, game in enumerate(big_games[:5], 1):
                h_rank = game['home_ranking']['national_rank'] if game.get('home_ranking') else '?'
                a_rank = game['away_ranking']['national_rank'] if game.get('away_ranking') else '?'
                roundup += f"{i}. #{h_rank} vs #{a_rank}\n"
                roundup += f"   {game['home_team_name'][:25]} vs {game['away_team_name'][:25]}\n\n"
            
            roundup += "#YouthSoccer #PitchRank"
            
            content['social_posts'].append({
                'type': 'roundup',
                'text': roundup
            })
    
    return content


def print_preview(content: Dict):
    """Print the preview content."""
    print("=" * 60)
    print("🏆 WEEKEND PREVIEW REPORT")
    print("=" * 60)
    
    print(f"\n📊 Total scheduled games: {content['total_games']}")
    print(f"🔥 Big game matchups: {len(content['big_games'])}")
    
    # Games by date
    print("\n📅 BY DATE:")
    for date in sorted(content['by_date'].keys()):
        games = content['by_date'][date]
        print(f"  {date}: {len(games)} games")
    
    # Top events
    print("\n🏆 TOP EVENTS:")
    sorted_events = sorted(content['by_event'].items(), key=lambda x: -len(x[1]))
    for event, games in sorted_events[:5]:
        print(f"  {event[:50]}: {len(games)} games")
    
    # Big games
    if content['big_games']:
        print("\n🔥 MARQUEE MATCHUPS:")
        for game in content['big_games'][:5]:
            h_rank = game['home_ranking']['national_rank'] if game.get('home_ranking') else '?'
            a_rank = game['away_ranking']['national_rank'] if game.get('away_ranking') else '?'
            print(f"  #{h_rank} {game['home_team_name'][:30]}")
            print(f"    vs #{a_rank} {game['away_team_name'][:30]}")
            print(f"    📅 {game['match_date']} @ {game['event_name'][:40]}")
            print()
    
    # Social posts
    if content['social_posts']:
        print("\n" + "=" * 60)
        print("📱 READY-TO-POST CONTENT")
        print("=" * 60)
        for post in content['social_posts']:
            print(f"\n--- {post['type'].upper()} POST ---")
            print(post['text'])
            print()


def main():
    parser = argparse.ArgumentParser(description='Generate weekend preview content')
    parser.add_argument('--days', type=int, default=4, help='Days ahead to look')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Check if scheduled_games exists and has data
    cur.execute('''
        SELECT COUNT(*) FROM information_schema.tables 
        WHERE table_name = 'scheduled_games'
    ''')
    if cur.fetchone()[0] == 0:
        print("❌ No scheduled_games table yet!")
        print("   Run: python scripts/scrape_scheduled_games.py --limit 100")
        return
    
    cur.execute('SELECT COUNT(*) FROM scheduled_games')
    total = cur.fetchone()[0]
    print(f"📊 {total} total scheduled games in database")
    
    # Get weekend games
    games = get_weekend_games(conn, days=args.days)
    print(f"🎯 Found {len(games)} games in next {args.days} days")
    
    if not games:
        print("\nNo upcoming games found. Try running the scraper first:")
        print("  python scripts/scrape_scheduled_games.py --limit 100")
        return
    
    # Enrich with rankings
    games = enrich_with_rankings(conn, games)
    
    # Generate content
    content = generate_preview_content(games)
    
    if args.json:
        import json
        # Convert dates to strings for JSON
        for game in content['big_games']:
            game['match_date'] = str(game['match_date'])
        print(json.dumps(content, indent=2, default=str))
    else:
        print_preview(content)
    
    conn.close()


if __name__ == '__main__':
    main()
