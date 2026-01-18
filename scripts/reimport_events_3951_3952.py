"""Delete and re-import events 3951 and 3952"""
import os
from dotenv import load_dotenv
from pathlib import Path
from supabase import create_client
import subprocess
import sys

# Load environment
env_local = Path('.env.local')
load_dotenv(env_local if env_local.exists() else None, override=True)

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

tgs_provider_id = 'ea79aa6e-679f-4b5b-92b1-e9f502df7582'

print("="*80)
print("DELETING AND RE-IMPORTING EVENTS 3951 AND 3952")
print("="*80)

events_to_process = ['Event 3951', 'Event 3952']

for event_name in events_to_process:
    print(f"\n{'='*80}")
    print(f"PROCESSING {event_name}")
    print(f"{'='*80}")
    
    # Find games from this event
    print(f"\nFinding games from {event_name}...")
    games_result = supabase.table('games').select('game_uid, home_team_master_id, away_team_master_id').eq(
        'event_name', event_name
    ).execute()
    
    games = games_result.data if games_result.data else []
    print(f"  Found {len(games)} games")
    
    if games:
        # Get unique team master IDs
        team_ids = set()
        for game in games:
            team_ids.add(game.get('home_team_master_id'))
            team_ids.add(game.get('away_team_master_id'))
        
        print(f"  Found {len(team_ids)} unique teams")
        
        # Delete games
        print(f"\nDeleting {len(games)} games...")
        game_uids = [g['game_uid'] for g in games]
        
        # Delete in batches
        batch_size = 100
        deleted_count = 0
        for i in range(0, len(game_uids), batch_size):
            batch = game_uids[i:i+batch_size]
            for game_uid in batch:
                try:
                    supabase.table('games').delete().eq('game_uid', game_uid).execute()
                    deleted_count += 1
                except Exception as e:
                    print(f"    Error deleting game {game_uid}: {e}")
        
        print(f"  ✅ Deleted {deleted_count} games")
        
        # Find alias entries created during the original import
        # Event 3951 was imported around 2025-12-12T10:27:00
        # Event 3952 was imported around 2025-12-12T10:38:00
        if event_name == 'Event 3951':
            import_start = '2025-12-12T10:27:00'
            import_end = '2025-12-12T10:28:00'
        else:  # Event 3952
            import_start = '2025-12-12T10:38:00'
            import_end = '2025-12-12T10:39:00'
        
        print(f"\nFinding alias entries created during original import...")
        aliases_result = supabase.table('team_alias_map').select('*').eq(
            'provider_id', tgs_provider_id
        ).gte('created_at', import_start).lte('created_at', import_end).execute()
        
        aliases = aliases_result.data if aliases_result.data else []
        print(f"  Found {len(aliases)} alias entries")
        
        if aliases:
            # Delete alias entries
            print(f"\nDeleting {len(aliases)} alias entries...")
            deleted_aliases = 0
            for alias in aliases:
                try:
                    supabase.table('team_alias_map').delete().eq('id', alias.get('id')).execute()
                    deleted_aliases += 1
                except Exception as e:
                    print(f"    Error deleting alias {alias.get('id')}: {e}")
            
            print(f"  ✅ Deleted {deleted_aliases} alias entries")
    else:
        print(f"  No games found for {event_name}")

print(f"\n{'='*80}")
print("DELETION COMPLETE - NOW RE-IMPORTING")
print(f"{'='*80}")

# Re-import events
csv_files = [
    'data/raw/tgs/tgs_events_3951_3951_2025-12-12T17-22-22-166384+00-00.csv',
    'data/raw/tgs/tgs_events_3952_3952_2025-12-12T17-33-46-839280+00-00.csv'
]

for csv_file in csv_files:
    csv_path = Path(csv_file)
    if not csv_path.exists():
        print(f"\n⚠️  CSV file not found: {csv_file}")
        continue
    
    event_id = csv_path.stem.split('_')[2]  # Extract event ID from filename
    print(f"\n{'='*80}")
    print(f"RE-IMPORTING EVENT {event_id}")
    print(f"{'='*80}")
    
    # Run import
    result = subprocess.run(
        [sys.executable, 'scripts/import_games_enhanced.py', str(csv_path), 'tgs'],
        capture_output=True,
        text=True
    )
    
    # Print summary
    output_lines = result.stdout.split('\n')
    for line in output_lines:
        if any(keyword in line for keyword in ['Games processed', 'Games accepted', 'Teams matched', 'Teams created', 'Import completed', 'Metrics:']):
            print(line)
    
    if result.returncode != 0:
        print(f"\n⚠️  Import had errors:")
        print(result.stderr)

print(f"\n{'='*80}")
print("RE-IMPORT COMPLETE")
print(f"{'='*80}")









