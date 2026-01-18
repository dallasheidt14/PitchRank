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

# Get Modular11 provider ID
provider_result = supabase.table('providers').select('id').eq('code', 'modular11').execute()
provider_id = provider_id = provider_result.data[0]['id']

# Test game from CSV
new_game = {
    'provider_id': provider_id,
    'home_provider_id': '455',
    'away_provider_id': '366',
    'game_date': '2025-11-23',
    'home_score': 1,
    'away_score': 2
}

# Check existing game
existing = supabase.table('games').select('*').eq('provider_id', provider_id).eq('game_date', '2025-11-23').or_('and(home_provider_id.eq.455,away_provider_id.eq.366),and(home_provider_id.eq.366,away_provider_id.eq.455)').execute()

print(f"Found {len(existing.data)} existing games:")
for game in existing.data:
    print(f"  home={game['home_provider_id']}, away={game['away_provider_id']}, scores={game.get('home_score')}-{game.get('away_score')}")
    print(f"  game_uid={game.get('game_uid')}")

# Try to build composite key like the code does
def make_composite_key(game):
    provider_id = str(game.get('provider_id', ''))
    home_provider_id = str(game.get('home_provider_id', ''))
    away_provider_id = str(game.get('away_provider_id', ''))
    game_date = str(game.get('game_date', ''))
    home_score = game.get('home_score')
    away_score = game.get('away_score')
    home_score_str = str(home_score) if home_score is not None else '-1'
    away_score_str = str(away_score) if away_score is not None else '-1'
    return f"{provider_id}|{home_provider_id}|{away_provider_id}|{game_date}|{home_score_str}|{away_score_str}"

new_key = make_composite_key(new_game)
print(f"\nNew game composite key: {new_key}")

if existing.data:
    existing_key = make_composite_key(existing.data[0])
    print(f"Existing game composite key: {existing_key}")
    print(f"Keys match: {new_key == existing_key}")

