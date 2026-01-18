"""Identify and fix incorrect ECNL vs ECRL/RL matches from event 3953"""
import os
import sys
from dotenv import load_dotenv
from pathlib import Path
from supabase import create_client
import csv
from datetime import datetime

# Load environment
env_local = Path('.env.local')
load_dotenv(env_local if env_local.exists() else None, override=True)

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

# TGS provider ID
tgs_provider_id = 'ea79aa6e-679f-4b5b-92b1-e9f502df7582'

print("="*80)
print("IDENTIFYING INCORRECT ECNL/ECRL MATCHES FROM EVENT 3953")
print("="*80)

# Read event 3953 CSV to get team names
csv_file = Path('data/raw/tgs/tgs_events_3953_3953_2025-12-12T17-48-39-608611+00-00.csv')
with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    csv_rows = list(reader)

# Get unique teams from CSV
csv_teams = {}
for row in csv_rows:
    team_id = row.get('team_id')
    if team_id and team_id not in csv_teams:
        csv_teams[team_id] = {
            'team_name': row.get('team_name'),
            'club_name': row.get('club_name'),
            'age_group': row.get('age_group'),
            'gender': row.get('gender')
        }

print(f"\nFound {len(csv_teams)} unique teams in CSV")

# Check alias map for fuzzy matches created during event 3953 import
# Event 3953 was imported around 2025-12-12T10:49:00 to 10:52:00
import_start = '2025-12-12T10:49:00'
import_end = '2025-12-12T10:53:00'

fuzzy_aliases = supabase.table('team_alias_map').select('*').eq(
    'provider_id', tgs_provider_id
).eq('match_method', 'fuzzy_auto').gte('created_at', import_start).lte('created_at', import_end).execute()

print(f"\nFound {len(fuzzy_aliases.data)} fuzzy matches created during event 3953 import")

# Check each fuzzy match for league mismatches
incorrect_matches = []
for alias in fuzzy_aliases.data:
    provider_team_id = alias.get('provider_team_id')
    
    # Get team name from CSV
    csv_team = csv_teams.get(provider_team_id)
    if not csv_team:
        continue
    
    provider_name = csv_team['team_name']
    
    # Get master team details
    master_team_result = supabase.table('teams').select('team_name, club_name, age_group, gender').eq(
        'team_id_master', alias.get('team_id_master')
    ).execute()
    
    if not master_team_result.data:
        continue
    
    master_team = master_team_result.data[0]
    master_name = master_team['team_name']
    
    # Check for league mismatch
    provider_upper = provider_name.upper()
    master_upper = master_name.upper()
    
    provider_has_ecnl_only = 'ECNL' in provider_upper and 'RL' not in provider_upper and 'ECRL' not in provider_upper
    provider_has_ecnl_rl = 'ECNL' in provider_upper and ('RL' in provider_upper or 'ECRL' in provider_upper)
    provider_has_ecrl_only = 'ECRL' in provider_upper or ('RL' in provider_upper and 'ECNL' not in provider_upper)
    
    master_has_ecnl_only = 'ECNL' in master_upper and 'RL' not in master_upper and 'ECRL' not in master_upper
    master_has_ecnl_rl = 'ECNL' in master_upper and ('RL' in master_upper or 'ECRL' in master_upper)
    master_has_ecrl_only = 'ECRL' in master_upper or ('RL' in master_upper and 'ECNL' not in master_upper)
    
    # Check for mismatch
    league_mismatch = False
    if provider_has_ecnl_only and (master_has_ecnl_rl or master_has_ecrl_only):
        league_mismatch = True
    elif master_has_ecnl_only and (provider_has_ecnl_rl or provider_has_ecrl_only):
        league_mismatch = True
    elif provider_has_ecnl_rl and master_has_ecrl_only:
        league_mismatch = True
    
    if league_mismatch:
        incorrect_matches.append({
            'alias_id': alias.get('id'),
            'provider_team_id': provider_team_id,
            'provider_team_name': provider_name,
            'master_team_id': alias.get('team_id_master'),
            'master_team_name': master_name,
            'match_confidence': alias.get('match_confidence'),
            'created_at': alias.get('created_at')
        })

print(f"\n{'='*80}")
print(f"FOUND {len(incorrect_matches)} INCORRECT MATCHES")
print(f"{'='*80}")

for i, match in enumerate(incorrect_matches, 1):
    print(f"\n{i}. Provider Team: {match['provider_team_name']}")
    print(f"   Master Team: {match['master_team_name']}")
    print(f"   Confidence: {match['match_confidence']}")
    print(f"   Alias ID: {match['alias_id']}")
    print(f"   Master Team ID: {match['master_team_id']}")

if not incorrect_matches:
    print("\n✅ No incorrect matches found!")
    exit(0)

# Find games that used these incorrect matches
print(f"\n{'='*80}")
print("FINDING AFFECTED GAMES")
print(f"{'='*80}")

affected_games = []
for match in incorrect_matches:
    master_team_id = match['master_team_id']
    
    # Find games from event 3953 that reference this master team
    games_result = supabase.table('games').select('game_uid, home_team_master_id, away_team_master_id, event_name').or_(
        f'home_team_master_id.eq.{master_team_id},away_team_master_id.eq.{master_team_id}'
    ).eq('event_name', 'Event 3953').execute()
    
    if games_result.data:
        for game in games_result.data:
            affected_games.append({
                'game_uid': game.get('game_uid'),
                'home_team_master_id': game.get('home_team_master_id'),
                'away_team_master_id': game.get('away_team_master_id'),
                'incorrect_match': match
            })

print(f"\nFound {len(affected_games)} games affected by incorrect matches")

# Ask for confirmation
print(f"\n{'='*80}")
print("FIX PLAN")
print(f"{'='*80}")
print(f"\nWill delete:")
print(f"  - {len(incorrect_matches)} incorrect alias entries")
print(f"  - {len(affected_games)} incorrectly matched games")
print(f"\nAfter deletion, you can re-import event 3953 to create correct matches.")

# Check for --yes flag
auto_confirm = '--yes' in sys.argv

if not auto_confirm:
    response = input("\nProceed with deletion? (yes/no): ").strip().lower()
    if response != 'yes':
        print("\nCancelled.")
        exit(0)
else:
    print("\nAuto-confirming deletion (--yes flag provided)...")

# Delete affected games first
print(f"\nDeleting {len(affected_games)} affected games...")
game_uids = [g['game_uid'] for g in affected_games]

# Delete in batches
batch_size = 100
deleted_games = 0
for i in range(0, len(game_uids), batch_size):
    batch = game_uids[i:i+batch_size]
    for game_uid in batch:
        try:
            supabase.table('games').delete().eq('game_uid', game_uid).execute()
            deleted_games += 1
        except Exception as e:
            print(f"  Error deleting game {game_uid}: {e}")

print(f"  ✅ Deleted {deleted_games} games")

# Delete incorrect alias entries
print(f"\nDeleting {len(incorrect_matches)} incorrect alias entries...")
deleted_aliases = 0
for match in incorrect_matches:
    try:
        supabase.table('team_alias_map').delete().eq('id', match['alias_id']).execute()
        deleted_aliases += 1
    except Exception as e:
        print(f"  Error deleting alias {match['alias_id']}: {e}")

print(f"  ✅ Deleted {deleted_aliases} alias entries")

print(f"\n{'='*80}")
print("FIX COMPLETE")
print(f"{'='*80}")
print(f"\n✅ Deleted {deleted_games} games")
print(f"✅ Deleted {deleted_aliases} incorrect alias entries")
print(f"\nNext step: Re-import event 3953 to create correct matches:")
print(f"  python scripts/import_games_enhanced.py data/raw/tgs/tgs_events_3953_3953_2025-12-12T17-48-39-608611+00-00.csv tgs")

