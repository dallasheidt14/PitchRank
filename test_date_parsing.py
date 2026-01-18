from src.utils.enhanced_validators import parse_game_date

# Test the date format from CSV
test_dates = [
    "11/23/2025",
    "11/22/2025",
    "2025-11-23",
]

print("Testing date parsing:")
for date_str in test_dates:
    try:
        date_obj = parse_game_date(date_str)
        normalized = date_obj.strftime('%Y-%m-%d')
        print(f"✅ '{date_str}' -> '{normalized}'")
    except Exception as e:
        print(f"❌ '{date_str}' -> ERROR: {e}")

# Now test game_uid generation
from src.models.game_matcher import GameHistoryMatcher

print("\nTesting game_uid generation:")
team1 = "1326"
team2 = "942"

# With normalized date
normalized_date = "2025-11-23"
game_uid_normalized = GameHistoryMatcher.generate_game_uid(
    provider='modular11',
    game_date=normalized_date,
    team1_id=team1,
    team2_id=team2
)
print(f"Normalized date '{normalized_date}': {game_uid_normalized}")

# With raw CSV date
raw_date = "11/23/2025"
game_uid_raw = GameHistoryMatcher.generate_game_uid(
    provider='modular11',
    game_date=raw_date,
    team1_id=team1,
    team2_id=team2
)
print(f"Raw date '{raw_date}': {game_uid_raw}")

# Check what's in database
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

print("\nChecking database for these game_uids:")
for uid in [game_uid_normalized, game_uid_raw]:
    result = supabase.table('games').select('game_uid').eq('game_uid', uid).execute()
    if result.data:
        print(f"  ✅ Found: {uid}")
    else:
        print(f"  ❌ Not found: {uid}")
