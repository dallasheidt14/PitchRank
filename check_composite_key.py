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

provider_id = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'

# Test case: game from CSV
# CSV: team_id=455, opponent_id=366, goals_for=1, goals_against=2
# This means: team 455 scored 1, team 366 scored 2
# After perspective transformation: home=455, away=366, home_score=1, away_score=2

def make_composite_key(game):
    """Mirror the database constraint"""
    provider_id_str = str(game.get('provider_id', ''))
    home_provider_id = str(game.get('home_provider_id', ''))
    away_provider_id = str(game.get('away_provider_id', ''))
    game_date = str(game.get('game_date', ''))
    home_score = game.get('home_score')
    away_score = game.get('away_score')
    home_score_str = str(home_score) if home_score is not None else '-1'
    away_score_str = str(away_score) if away_score is not None else '-1'
    
    return f"{provider_id_str}|{home_provider_id}|{away_provider_id}|{game_date}|{home_score_str}|{away_score_str}"

# Check what's in the database for this game
print("Checking database for games with these teams and date:\n")
result = supabase.table('games').select('game_uid, home_provider_id, away_provider_id, game_date, home_score, away_score').eq('provider_id', provider_id).eq('game_date', '2025-11-23').or_('home_provider_id.eq.455,away_provider_id.eq.455').or_('home_provider_id.eq.366,away_provider_id.eq.366').execute()

print(f"Found {len(result.data)} games:\n")
for game in result.data:
    print(f"Game UID: {game['game_uid']}")
    print(f"  home_provider_id={game['home_provider_id']}, away_provider_id={game['away_provider_id']}")
    print(f"  home_score={game['home_score']}, away_score={game['away_score']}")
    print(f"  Composite key: {make_composite_key({**game, 'provider_id': provider_id})}")
    print()

# Now check what the CSV would generate
print("="*70)
print("What CSV would generate:\n")

# CSV row: team_id=455, opponent_id=366, goals_for=1, goals_against=2
# After perspective transformation (if team 455 is home):
csv_game_home_455 = {
    'provider_id': provider_id,
    'home_provider_id': '455',
    'away_provider_id': '366',
    'game_date': '2025-11-23',
    'home_score': 1,  # team 455 scored 1
    'away_score': 2   # team 366 scored 2
}

# But wait, the CSV shows home_away='H' for team 455, so team 455 IS home
# So: home=455, away=366, home_score=1, away_score=2

print("CSV game (team 455 is home):")
print(f"  home_provider_id={csv_game_home_455['home_provider_id']}, away_provider_id={csv_game_home_455['away_provider_id']}")
print(f"  home_score={csv_game_home_455['home_score']}, away_score={csv_game_home_455['away_score']}")
print(f"  Composite key: {make_composite_key(csv_game_home_455)}")
print()

# Check if this composite key exists
csv_composite_key = make_composite_key(csv_game_home_455)
for game in result.data:
    db_composite_key = make_composite_key({**game, 'provider_id': provider_id})
    if db_composite_key == csv_composite_key:
        print(f"✅ MATCH FOUND: {game['game_uid']}")
    else:
        print(f"❌ NO MATCH: {game['game_uid']} (key: {db_composite_key})")
