#!/usr/bin/env python3
"""
Diagnose why games aren't being imported - check match_status, scores, etc.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

MODULAR11_PROVIDER_ID = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'

def main():
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
    
    if not supabase_url or not supabase_key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        sys.exit(1)
    
    db = create_client(supabase_url, supabase_key)
    
    print("=" * 80)
    print("DIAGNOSING IMPORT FAILURE")
    print("=" * 80)
    
    # Check recent build logs for details
    print("\n[1] Checking recent build logs...")
    try:
        logs = db.table('build_logs').select('*').eq('provider_id', MODULAR11_PROVIDER_ID).limit(1).execute()
        
        if logs.data:
            log = logs.data[0]
            metrics = log.get('metrics', {})
            print(f"   Latest build log:")
            print(f"   - Games processed: {metrics.get('games_processed', 0)}")
            print(f"   - Games accepted: {metrics.get('games_accepted', 0)}")
            print(f"   - Matched games: {metrics.get('matched_games_count', 0)}")
            print(f"   - Partial games: {metrics.get('partial_games_count', 0)}")
            print(f"   - Failed games: {metrics.get('failed_games_count', 0)}")
            print(f"   - Skipped empty scores: {metrics.get('skipped_empty_scores', 0)}")
            print(f"   - Duplicates found: {metrics.get('duplicates_found', 0)}")
            print(f"   - Duplicates skipped: {metrics.get('duplicates_skipped', 0)}")
    except Exception as e:
        print(f"   Could not fetch build logs: {e}")
    
    # Check if games exist in database for this provider
    print("\n[2] Checking games in database...")
    games = db.table('games').select('id, game_uid, game_date, home_team_master_id, away_team_master_id').eq('provider_id', MODULAR11_PROVIDER_ID).order('created_at', desc=True).limit(10).execute()
    
    if games.data:
        print(f"   Found {len(games.data)} recent games")
        for g in games.data[:5]:
            print(f"   - {g.get('game_date')} | UID: {g.get('game_uid', '')[:50]}")
    else:
        print("   ⚠️  No games found in database for Modular11")
    
    # Check for age mismatches in teams
    print("\n[3] Checking for potential age mismatches...")
    teams = db.table('teams').select('team_id_master, team_name, age_group').eq('provider_id', MODULAR11_PROVIDER_ID).execute()
    
    age_groups = defaultdict(list)
    for team in (teams.data or []):
        age = team.get('age_group', '').lower()
        if age:
            age_groups[age].append(team.get('team_name'))
    
    print(f"   Found {len(age_groups)} different age groups")
    for age, names in sorted(age_groups.items()):
        print(f"   - {age}: {len(names)} teams")
    
    print("\n" + "=" * 80)
    print("DIAGNOSIS COMPLETE")
    print("=" * 80)

if __name__ == '__main__':
    main()

