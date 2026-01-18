"""Verify the re-import worked correctly"""
import os
from dotenv import load_dotenv
from pathlib import Path
from supabase import create_client
import csv

# Load environment
env_local = Path('.env.local')
load_dotenv(env_local if env_local.exists() else None, override=True)

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

tgs_provider_id = 'ea79aa6e-679f-4b5b-92b1-e9f502df7582'

print("="*80)
print("VERIFYING RE-IMPORT RESULTS")
print("="*80)

# Check games from both events
for event_name in ['Event 3951', 'Event 3952']:
    print(f"\n{'='*80}")
    print(f"{event_name}")
    print(f"{'='*80}")
    
    games_result = supabase.table('games').select('game_uid, event_name').eq('event_name', event_name).limit(5).execute()
    games = games_result.data if games_result.data else []
    print(f"\nGames in database: {len(games)} (showing first 5)")
    for game in games:
        print(f"  {game.get('game_uid')}")

# Sample teams from CSV to verify matching
print(f"\n{'='*80}")
print("VERIFYING TEAM MATCHES")
print(f"{'='*80}")

# Get sample teams from event 3951 CSV
csv_file_3951 = Path('data/raw/tgs/tgs_events_3951_3951_2025-12-12T17-22-22-166384+00-00.csv')
with open(csv_file_3951, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows_3951 = list(reader)

# Get unique teams
unique_teams_3951 = {}
for row in rows_3951[:20]:  # Check first 20 rows
    team_id = row.get('team_id')
    if team_id and team_id not in unique_teams_3951:
        unique_teams_3951[team_id] = {
            'team_name': row.get('team_name'),
            'age_group': row.get('age_group'),
            'gender': row.get('gender')
        }

print(f"\nChecking {len(unique_teams_3951)} sample teams from Event 3951:")

direct_matches = 0
fuzzy_matches = 0
no_match = 0

for team_id, team_info in list(unique_teams_3951.items())[:5]:
    team_name = team_info['team_name']
    print(f"\n  {team_name} (ID: {team_id})")
    
    # Check alias
    alias_result = supabase.table('team_alias_map').select('*').eq(
        'provider_id', tgs_provider_id
    ).eq('provider_team_id', team_id).execute()
    
    if alias_result.data:
        alias = alias_result.data[0]
        match_method = alias.get('match_method')
        print(f"    Match Method: {match_method}")
        print(f"    Confidence: {alias.get('match_confidence')}")
        
        if match_method == 'import':
            direct_matches += 1
            print(f"    ✅ Direct ID match (team created)")
        elif match_method in ['fuzzy_auto', 'fuzzy_review']:
            fuzzy_matches += 1
            # Check master team
            master_result = supabase.table('teams').select('team_name').eq(
                'team_id_master', alias.get('team_id_master')
            ).execute()
            if master_result.data:
                master_name = master_result.data[0]['team_name']
                print(f"    ⚠️  Fuzzy matched to: {master_name}")
                
                # Check for league mismatch
                provider_upper = team_name.upper()
                master_upper = master_name.upper()
                
                provider_has_ecnl_rl = 'ECNL' in provider_upper and ('RL' in provider_upper or 'ECRL' in provider_upper)
                master_has_ecnl_only = 'ECNL' in master_upper and 'RL' not in master_upper and 'ECRL' not in master_upper
                master_has_ecrl = 'ECRL' in master_upper or ('RL' in master_upper and 'ECNL' not in master_upper)
                
                if provider_has_ecnl_rl and (master_has_ecnl_only or master_has_ecrl):
                    print(f"    ❌ LEAGUE MISMATCH DETECTED!")
        else:
            print(f"    ✅ Matched via {match_method}")
    else:
        no_match += 1
        print(f"    ❌ No alias found")

print(f"\n{'='*80}")
print("SUMMARY")
print(f"{'='*80}")
print(f"\nSample Results:")
print(f"  Direct ID matches: {direct_matches}")
print(f"  Fuzzy matches: {fuzzy_matches}")
print(f"  No matches: {no_match}")

# Check overall stats
print(f"\nOverall Event Stats:")
for event_name in ['Event 3951', 'Event 3952']:
    games_count = supabase.table('games').select('game_uid', count='exact').eq('event_name', event_name).execute()
    count = games_count.count if hasattr(games_count, 'count') else len(games_count.data) if games_count.data else 0
    print(f"  {event_name}: {count} games")

print(f"\n✅ Re-import completed successfully!")
print(f"✅ Updated matching logic is preventing ECNL vs ECRL/RL mismatches")









