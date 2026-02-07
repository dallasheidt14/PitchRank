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

# Check the specific game
game_uid = 'modular11:2025-09-06:14:249'

print(f"Querying database for game_uid: {game_uid}\n")

# Get the game
result = supabase.table('games').select('*').eq('game_uid', game_uid).execute()

if result.data:
    game = result.data[0]
    print("Database record:")
    print(f"  game_uid: {game.get('game_uid')}")
    print(f"  home_provider_id: {game.get('home_provider_id')}")
    print(f"  away_provider_id: {game.get('away_provider_id')}")
    print(f"  home_score: {game.get('home_score')} (type: {type(game.get('home_score'))})")
    print(f"  away_score: {game.get('away_score')} (type: {type(game.get('away_score'))})")
    print(f"  game_date: {game.get('game_date')}")
    print(f"  created_at: {game.get('created_at')}")
    print(f"  updated_at: {game.get('updated_at')}")
    print()
    print(f"Full record (JSON):")
    import json
    print(json.dumps(game, indent=2, default=str))
else:
    print("No game found with this game_uid")
