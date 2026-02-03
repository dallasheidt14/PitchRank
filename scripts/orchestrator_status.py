#!/usr/bin/env python3
"""
Orchestrator Status Dashboard
Quick health check for all PitchRank systems.

Run: python3 scripts/orchestrator_status.py
"""

import os
import sys
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv('/Users/pitchrankio-dev/Projects/PitchRank/.env')

def get_db_connection():
    import psycopg2
    return psycopg2.connect(os.getenv('DATABASE_URL'))

def check_data_health():
    """Check key data metrics."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    metrics = {}
    
    # Total teams
    cur.execute("SELECT COUNT(*) FROM teams")
    metrics['total_teams'] = cur.fetchone()[0]
    
    # Total games
    cur.execute("SELECT COUNT(*) FROM games")
    metrics['total_games'] = cur.fetchone()[0]
    
    # Games last 24h
    cur.execute("SELECT COUNT(*) FROM games WHERE created_at > NOW() - INTERVAL '24 hours'")
    metrics['games_24h'] = cur.fetchone()[0]
    
    # Quarantine count
    cur.execute("SELECT COUNT(*) FROM quarantine_games")
    metrics['quarantine'] = cur.fetchone()[0]
    
    # Stale teams (not scraped in 7 days)
    cur.execute("""
        SELECT COUNT(*) FROM teams 
        WHERE last_scraped_at < NOW() - INTERVAL '7 days' 
        OR last_scraped_at IS NULL
    """)
    metrics['stale_teams'] = cur.fetchone()[0]
    
    # Pending match reviews
    cur.execute("SELECT COUNT(*) FROM team_match_review_queue")
    metrics['pending_reviews'] = cur.fetchone()[0]
    
    # Latest ranking snapshot
    cur.execute("SELECT MAX(snapshot_date) FROM ranking_history")
    metrics['latest_ranking'] = str(cur.fetchone()[0])
    
    conn.close()
    return metrics

def check_github_actions():
    """Check recent GitHub Actions status."""
    import subprocess
    try:
        result = subprocess.run(
            ['gh', 'run', 'list', '--repo', 'dallasheidt14/PitchRank', 
             '--limit', '10', '--json', 'status,conclusion,name,createdAt'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            runs = json.loads(result.stdout)
            failed = [r for r in runs if r.get('conclusion') == 'failure']
            in_progress = [r for r in runs if r.get('status') == 'in_progress']
            return {
                'total_checked': len(runs),
                'failed': len(failed),
                'in_progress': len(in_progress),
                'failed_names': [r['name'] for r in failed[:3]]
            }
    except Exception as e:
        return {'error': str(e)}
    return {'error': 'unknown'}

def format_number(n):
    """Format number with commas."""
    return f"{n:,}"

def main():
    print("=" * 60)
    print("🎯 PITCHRANK ORCHESTRATOR STATUS")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S MT')}")
    print("=" * 60)
    
    # Data Health
    print("\n📊 DATA HEALTH")
    print("-" * 40)
    try:
        metrics = check_data_health()
        print(f"  Teams:           {format_number(metrics['total_teams'])}")
        print(f"  Games:           {format_number(metrics['total_games'])}")
        print(f"  Games (24h):     {format_number(metrics['games_24h'])}")
        print(f"  Quarantine:      {format_number(metrics['quarantine'])}")
        print(f"  Stale Teams:     {format_number(metrics['stale_teams'])}")
        print(f"  Pending Reviews: {format_number(metrics['pending_reviews'])}")
        print(f"  Latest Ranking:  {metrics['latest_ranking']}")
        
        # Alerts
        alerts = []
        if metrics['games_24h'] == 0:
            alerts.append("🔴 CRITICAL: No games imported in 24h!")
        if metrics['quarantine'] > 1000:
            alerts.append(f"🟡 WARNING: High quarantine count ({format_number(metrics['quarantine'])})")
        if metrics['stale_teams'] > 50000:
            alerts.append(f"🟡 WARNING: Many stale teams ({format_number(metrics['stale_teams'])})")
            
        if alerts:
            print("\n⚠️  ALERTS:")
            for alert in alerts:
                print(f"  {alert}")
        else:
            print("\n✅ All data metrics healthy")
            
    except Exception as e:
        print(f"  ❌ Error checking data: {e}")
    
    # GitHub Actions
    print("\n🔧 GITHUB ACTIONS")
    print("-" * 40)
    gh = check_github_actions()
    if 'error' in gh:
        print(f"  ❌ Error: {gh['error']}")
    else:
        status = "✅" if gh['failed'] == 0 else "🔴"
        print(f"  {status} Failed: {gh['failed']} | In Progress: {gh['in_progress']}")
        if gh['failed_names']:
            print(f"  Failed: {', '.join(gh['failed_names'])}")
    
    print("\n" + "=" * 60)

if __name__ == '__main__':
    main()
