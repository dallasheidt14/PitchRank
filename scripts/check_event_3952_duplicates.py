"""Check if event 3952 games are actually duplicates"""
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

# Read CSV
csv_file = Path('data/raw/tgs/tgs_events_3952_3952_2025-12-12T17-33-46-839280+00-00.csv')
with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

print("="*80)
print("CHECKING EVENT 3952 GAMES")
print("="*80)

# Generate game UIDs and check if they exist
unique_games = {}
for row in rows:
    game_date = row.get('game_date')
    team_id = row.get('team_id')
    opponent_id = row.get('opponent_id')
    
    if game_date and team_id and opponent_id:
        # Generate both possible UIDs (team vs opponent and opponent vs team)
        uid1 = f"tgs:{game_date}:{team_id}:{opponent_id}"
        uid2 = f"tgs:{game_date}:{opponent_id}:{team_id}"
        
        # Use the one with smaller team_id first (consistent ordering)
        if team_id < opponent_id:
            uid = uid1
        else:
            uid = uid2
        
        if uid not in unique_games:
            unique_games[uid] = {
                'game_date': game_date,
                'team_id': team_id,
                'opponent_id': opponent_id,
                'team_name': row.get('team_name'),
                'opponent_name': row.get('opponent_name'),
                'event_id': row.get('event_id')
            }

print(f"\nUnique games in CSV: {len(unique_games)}")

# Check first 10 games
sample_uids = list(unique_games.keys())[:10]
print(f"\nChecking first 10 game UIDs in database:")

found_count = 0
not_found_count = 0

for uid in sample_uids:
    game_info = unique_games[uid]
    result = supabase.table('games').select('game_uid,event_name,game_date').eq('game_uid', uid).execute()
    
    if result.data:
        found_count += 1
        game = result.data[0]
        print(f"\n✅ FOUND: {uid}")
        print(f"   Event in DB: {game.get('event_name')}")
        print(f"   Date: {game.get('game_date')}")
        print(f"   CSV Event: {game_info['event_id']}")
    else:
        not_found_count += 1
        print(f"\n❌ NOT FOUND: {uid}")
        print(f"   CSV Event: {game_info['event_id']}")
        print(f"   Date: {game_info['game_date']}")
        print(f"   Teams: {game_info['team_name']} vs {game_info['opponent_name']}")

print(f"\n{'='*80}")
print(f"Sample Results: {found_count} found, {not_found_count} not found")
print(f"{'='*80}")

# Check all games
print(f"\nChecking all {len(unique_games)} games...")
all_uids = list(unique_games.keys())

# Check in batches
batch_size = 100
found_total = 0
for i in range(0, len(all_uids), batch_size):
    batch = all_uids[i:i+batch_size]
    result = supabase.table('games').select('game_uid').in_('game_uid', batch).execute()
    found_total += len(result.data) if result.data else 0

print(f"\nTotal games found in DB: {found_total}")
print(f"Total games NOT found in DB: {len(unique_games) - found_total}")

# Check why the missing games weren't imported
print(f"\n{'='*80}")
print("CHECKING WHY 112 GAMES WEREN'T IMPORTED")
print(f"{'='*80}")

missing_uids = []
for uid in all_uids:
    result = supabase.table('games').select('game_uid').eq('game_uid', uid).execute()
    if not result.data:
        missing_uids.append(uid)

print(f"\nFound {len(missing_uids)} games that should have been imported")
print(f"\nSample of missing games:")

for uid in missing_uids[:5]:
    game_info = unique_games[uid]
    print(f"\n  {uid}")
    print(f"    Date: {game_info['game_date']}")
    print(f"    Teams: {game_info['team_id']} vs {game_info['opponent_id']}")
    print(f"    Team Names: {game_info['team_name']} vs {game_info['opponent_name']}")
    
    # Check if teams exist
    team_result = supabase.table('team_alias_map').select('team_id_master').eq(
        'provider_id', 'ea79aa6e-679f-4b5b-92b1-e9f502df7582'
    ).eq('provider_team_id', game_info['team_id']).execute()
    
    opponent_result = supabase.table('team_alias_map').select('team_id_master').eq(
        'provider_id', 'ea79aa6e-679f-4b5b-92b1-e9f502df7582'
    ).eq('provider_team_id', game_info['opponent_id']).execute()
    
    team_matched = len(team_result.data) > 0 if team_result.data else False
    opponent_matched = len(opponent_result.data) > 0 if opponent_result.data else False
    
    print(f"    Team matched: {team_matched}")
    print(f"    Opponent matched: {opponent_matched}")

