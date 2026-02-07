import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))

# Check the game UIDs from the CSV
game_uids = [
    "modular11:2025-11-23:366:455",
    "modular11:2025-11-23:1348:456",
    "modular11:2025-11-23:101:474",
    "modular11:2025-11-23:1326:942",
    "modular11:2025-11-23:11:856"
]

print("Checking if these game UIDs exist in database:\n")
for uid in game_uids:
    result = supabase.table('games').select('game_uid, home_provider_id, away_provider_id, game_date, home_score, away_score').eq('game_uid', uid).execute()
    if result.data:
        print(f"✅ FOUND: {uid}")
        for game in result.data:
            print(f"   {game}")
    else:
        print(f"❌ NOT FOUND: {uid}")

print("\n" + "="*70)
print("Checking by composite key instead:")
print("="*70)

# Check by composite key (provider_id, home_provider_id, away_provider_id, game_date, scores)
provider_id = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'

test_cases = [
    {"home": "366", "away": "455", "date": "2025-11-23", "home_score": 1, "away_score": 2},
    {"home": "1348", "away": "456", "date": "2025-11-23"},
]

for case in test_cases:
    query = supabase.table('games').select('game_uid, home_provider_id, away_provider_id, game_date, home_score, away_score')
    query = query.eq('provider_id', provider_id)
    query = query.eq('home_provider_id', case['home'])
    query = query.eq('away_provider_id', case['away'])
    query = query.eq('game_date', case['date'])
    
    if 'home_score' in case:
        query = query.eq('home_score', case['home_score'])
    if 'away_score' in case:
        query = query.eq('away_score', case['away_score'])
    
    result = query.execute()
    
    print(f"\nChecking: home={case['home']}, away={case['away']}, date={case['date']}")
    if result.data:
        print(f"✅ Found {len(result.data)} game(s):")
        for game in result.data:
            print(f"   {game}")
    else:
        print(f"❌ Not found")
