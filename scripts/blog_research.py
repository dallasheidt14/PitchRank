#!/usr/bin/env python3
"""
Blog Research Script for Blogy
Pulls relevant data from PitchRank database to inform blog content.

Usage:
    python3 scripts/blog_research.py --state AZ
    python3 scripts/blog_research.py --state CA --age-group U14
    python3 scripts/blog_research.py --topic "club-selection"
    python3 scripts/blog_research.py --national
"""

import os
import sys
import argparse
import json
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

def get_connection():
    return psycopg2.connect(os.getenv('DATABASE_URL'))

def state_research(state_code: str, age_group: str = None):
    """Pull comprehensive stats for a state-specific blog post."""
    conn = get_connection()
    cur = conn.cursor()
    
    results = {
        "state": state_code,
        "generated_at": datetime.now().isoformat(),
        "stats": {}
    }
    
    # Total teams in state
    if age_group:
        cur.execute("""
            SELECT COUNT(*) FROM teams 
            WHERE state_code = %s AND age_group = %s
        """, (state_code, age_group))
        results["stats"]["total_teams"] = cur.fetchone()[0]
        results["stats"]["age_group"] = age_group
    else:
        cur.execute("""
            SELECT COUNT(*) FROM teams WHERE state_code = %s
        """, (state_code,))
        results["stats"]["total_teams"] = cur.fetchone()[0]
    
    # Teams by age group
    cur.execute("""
        SELECT age_group, COUNT(*) as count 
        FROM teams 
        WHERE state_code = %s 
        GROUP BY age_group 
        ORDER BY age_group
    """, (state_code,))
    results["stats"]["teams_by_age_group"] = {row[0]: row[1] for row in cur.fetchall()}
    
    # Top clubs by team count
    cur.execute("""
        SELECT club_name, COUNT(*) as team_count 
        FROM teams 
        WHERE state_code = %s AND club_name IS NOT NULL
        GROUP BY club_name 
        ORDER BY team_count DESC 
        LIMIT 15
    """, (state_code,))
    results["stats"]["top_clubs"] = [
        {"name": row[0], "teams": row[1]} for row in cur.fetchall()
    ]
    
    # Games in last 30 days
    cur.execute("""
        SELECT COUNT(*) FROM games g
        JOIN teams t1 ON g.home_team_master_id = t1.id
        WHERE t1.state_code = %s 
        AND g.game_date > NOW() - INTERVAL '30 days'
    """, (state_code,))
    results["stats"]["games_last_30_days"] = cur.fetchone()[0]
    
    # Check if ranking_history table exists and has data for this state
    try:
        cur.execute("""
            SELECT t.team_name, t.club_name, t.age_group, rh.power_score
            FROM teams t
            JOIN ranking_history rh ON t.id = rh.team_id
            WHERE t.state_code = %s 
            AND rh.power_score IS NOT NULL
            ORDER BY rh.power_score DESC
            LIMIT 10
        """, (state_code,))
        results["stats"]["top_ranked_teams"] = [
            {"team": row[0], "club": row[1], "age_group": row[2], "power_score": float(row[3]) if row[3] else None}
            for row in cur.fetchall()
        ]
    except Exception:
        conn.rollback()
        results["stats"]["top_ranked_teams"] = []
    
    # Gender breakdown
    cur.execute("""
        SELECT gender, COUNT(*) 
        FROM teams 
        WHERE state_code = %s 
        GROUP BY gender
    """, (state_code,))
    results["stats"]["gender_breakdown"] = {row[0] or "Unknown": row[1] for row in cur.fetchall()}
    
    conn.close()
    return results

def national_research():
    """Pull national-level stats for algorithm/methodology posts."""
    conn = get_connection()
    cur = conn.cursor()
    
    results = {
        "scope": "national",
        "generated_at": datetime.now().isoformat(),
        "stats": {}
    }
    
    # Total teams nationally
    cur.execute("SELECT COUNT(*) FROM teams")
    results["stats"]["total_teams"] = cur.fetchone()[0]
    
    # Teams by state (top 15)
    cur.execute("""
        SELECT state_code, COUNT(*) as count 
        FROM teams 
        WHERE state_code IS NOT NULL
        GROUP BY state_code 
        ORDER BY count DESC 
        LIMIT 15
    """)
    results["stats"]["teams_by_state"] = [
        {"state": row[0], "teams": row[1]} for row in cur.fetchall()
    ]
    
    # Total games
    cur.execute("SELECT COUNT(*) FROM games")
    results["stats"]["total_games"] = cur.fetchone()[0]
    
    # Games by month (last 6 months)
    cur.execute("""
        SELECT DATE_TRUNC('month', game_date) as month, COUNT(*) 
        FROM games 
        WHERE game_date > NOW() - INTERVAL '6 months'
        GROUP BY month 
        ORDER BY month DESC
    """)
    results["stats"]["games_by_month"] = [
        {"month": row[0].strftime("%Y-%m") if row[0] else None, "games": row[1]} 
        for row in cur.fetchall()
    ]
    
    # Age group distribution
    cur.execute("""
        SELECT age_group, COUNT(*) 
        FROM teams 
        GROUP BY age_group 
        ORDER BY age_group
    """)
    results["stats"]["teams_by_age_group"] = {row[0]: row[1] for row in cur.fetchall()}
    
    # Quarantine stats
    cur.execute("SELECT COUNT(*) FROM quarantine_games")
    results["stats"]["quarantine_count"] = cur.fetchone()[0]
    
    conn.close()
    return results

def club_research(club_name: str = None):
    """Pull stats for club selection/comparison posts."""
    conn = get_connection()
    cur = conn.cursor()
    
    results = {
        "topic": "club_analysis",
        "generated_at": datetime.now().isoformat(),
        "stats": {}
    }
    
    # Top clubs nationally
    cur.execute("""
        SELECT club_name, state_code, COUNT(*) as team_count 
        FROM teams 
        WHERE club_name IS NOT NULL
        GROUP BY club_name, state_code 
        ORDER BY team_count DESC 
        LIMIT 25
    """)
    results["stats"]["largest_clubs"] = [
        {"name": row[0], "state": row[1], "teams": row[2]} 
        for row in cur.fetchall()
    ]
    
    # Clubs with most age groups covered
    cur.execute("""
        SELECT club_name, COUNT(DISTINCT age_group) as age_groups, COUNT(*) as teams
        FROM teams 
        WHERE club_name IS NOT NULL
        GROUP BY club_name 
        HAVING COUNT(DISTINCT age_group) >= 8
        ORDER BY age_groups DESC, teams DESC
        LIMIT 20
    """)
    results["stats"]["full_pathway_clubs"] = [
        {"name": row[0], "age_groups": row[1], "teams": row[2]} 
        for row in cur.fetchall()
    ]
    
    conn.close()
    return results

def competitor_urls(keyword: str):
    """Generate competitor URLs to fetch for research."""
    # Common youth soccer ranking competitors
    competitors = [
        f"https://www.gotsoccer.com/rankings",
        f"https://www.topdrawersoccer.com/club-soccer-rankings",
        f"https://www.soccerwire.com/rankings",
    ]
    
    # State-specific if keyword contains state
    state_keywords = {
        "arizona": "az", "california": "ca", "texas": "tx", 
        "florida": "fl", "new york": "ny", "new jersey": "nj"
    }
    
    for state_name, code in state_keywords.items():
        if state_name in keyword.lower() or code in keyword.lower():
            competitors.append(f"https://www.gotsoccer.com/rankings/{code}")
    
    return competitors

def main():
    parser = argparse.ArgumentParser(description='Research data for blog posts')
    parser.add_argument('--state', help='State code (e.g., AZ, CA, TX)')
    parser.add_argument('--age-group', help='Age group (e.g., U14, U12)')
    parser.add_argument('--national', action='store_true', help='National stats')
    parser.add_argument('--clubs', action='store_true', help='Club analysis stats')
    parser.add_argument('--keyword', help='Get competitor URLs for keyword')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    args = parser.parse_args()
    
    if args.state:
        data = state_research(args.state.upper(), args.age_group)
    elif args.national:
        data = national_research()
    elif args.clubs:
        data = club_research()
    elif args.keyword:
        data = {"competitor_urls": competitor_urls(args.keyword)}
    else:
        # Default: show national overview
        data = national_research()
    
    if args.json:
        print(json.dumps(data, indent=2, default=str))
    else:
        # Pretty print for human reading
        print("\n" + "="*60)
        print(f"📊 BLOG RESEARCH DATA")
        print("="*60)
        
        if "state" in data:
            print(f"\n🏠 State: {data['state']}")
        
        stats = data.get("stats", {})
        
        if "total_teams" in stats:
            print(f"\n📈 Total Teams: {stats['total_teams']:,}")
        
        if "top_clubs" in stats:
            print(f"\n🏆 Top Clubs:")
            for club in stats["top_clubs"][:10]:
                print(f"   • {club['name']}: {club['teams']} teams")
        
        if "teams_by_age_group" in stats:
            print(f"\n👶 Teams by Age Group:")
            for ag, count in sorted(stats["teams_by_age_group"].items()):
                print(f"   • {ag}: {count}")
        
        if "teams_by_state" in stats:
            print(f"\n🗺️ Teams by State (Top 10):")
            for item in stats["teams_by_state"][:10]:
                print(f"   • {item['state']}: {item['teams']:,}")
        
        if "top_ranked_teams" in stats and stats["top_ranked_teams"]:
            print(f"\n⭐ Top Ranked Teams:")
            for team in stats["top_ranked_teams"][:5]:
                score = f"{team['power_score']:.3f}" if team['power_score'] else "N/A"
                print(f"   • {team['team']} ({team['club']}) - {team['age_group']} - {score}")
        
        if "competitor_urls" in data:
            print(f"\n🔍 Competitor URLs to Research:")
            for url in data["competitor_urls"]:
                print(f"   • {url}")
        
        print("\n" + "="*60)
        print(f"Generated: {data.get('generated_at', 'N/A')}")
        print("="*60 + "\n")

if __name__ == "__main__":
    main()
