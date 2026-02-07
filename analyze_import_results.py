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

# Check how many games were imported in the last hour
from datetime import datetime, timedelta
one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()

recent_games = supabase.table('games').select('game_uid, home_provider_id, away_provider_id, game_date, home_score, away_score, created_at').eq('provider_id', provider_id).gte('created_at', one_hour_ago).execute()

print(f"Games imported in last hour: {len(recent_games.data)}")
if recent_games.data:
    print("\nSample imported games:")
    for game in recent_games.data[:5]:
        print(f"  {game['game_uid']}: {game['home_provider_id']} vs {game['away_provider_id']}, scores={game['home_score']}-{game['away_score']}")

# Now check CSV to see what should have been imported
import csv
csv_path = Path('scrapers/modular11_scraper/output/modular11_results_20260116_151234.csv')

print("\n" + "="*70)
print("Analyzing CSV vs Database:")
print("="*70)

from src.models.game_matcher import GameHistoryMatcher
from src.utils.enhanced_validators import parse_game_date

csv_games_by_uid = {}
csv_games_by_composite = {}

with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        game_date_raw = row.get('game_date', '').strip()
        team_id = row.get('team_id', '').strip()
        opponent_id = row.get('opponent_id', '').strip()
        goals_for = row.get('goals_for', '').strip()
        goals_against = row.get('goals_against', '').strip()
        home_away = row.get('home_away', '').strip()
        
        if not game_date_raw or not team_id or not opponent_id:
            continue
        
        # Normalize date
        try:
            date_obj = parse_game_date(game_date_raw)
            game_date_normalized = date_obj.strftime('%Y-%m-%d')
        except:
            game_date_normalized = game_date_raw
        
        # Generate game_uid
        sorted_teams = sorted([team_id, opponent_id])
        game_uid = GameHistoryMatcher.generate_game_uid(
            provider='modular11',
            game_date=game_date_normalized,
            team1_id=sorted_teams[0],
            team2_id=sorted_teams[1]
        )
        
        # Determine home/away and scores
        if home_away == 'H':
            home_id = team_id
            away_id = opponent_id
            home_score = int(goals_for) if goals_for else None
            away_score = int(goals_against) if goals_against else None
        else:
            home_id = opponent_id
            away_id = team_id
            home_score = int(goals_against) if goals_against else None
            away_score = int(goals_for) if goals_for else None
        
        # Composite key
        home_score_str = str(home_score) if home_score is not None else '-1'
        away_score_str = str(away_score) if away_score is not None else '-1'
        composite_key = f"{provider_id}|{home_id}|{away_id}|{game_date_normalized}|{home_score_str}|{away_score_str}"
        
        # Store by game_uid (will have duplicates - same game from both perspectives)
        if game_uid not in csv_games_by_uid:
            csv_games_by_uid[game_uid] = []
        csv_games_by_uid[game_uid].append({
            'home_id': home_id,
            'away_id': away_id,
            'home_score': home_score,
            'away_score': away_score,
            'composite_key': composite_key
        })
        
        # Store by composite key (unique games)
        csv_games_by_composite[composite_key] = {
            'game_uid': game_uid,
            'home_id': home_id,
            'away_id': away_id,
            'home_score': home_score,
            'away_score': away_score,
            'date': game_date_normalized
        }

print(f"\nCSV Analysis:")
print(f"  Total rows: {sum(len(v) for v in csv_games_by_uid.values())}")
print(f"  Unique game_uids: {len(csv_games_by_uid)}")
print(f"  Unique composite keys: {len(csv_games_by_composite)}")

# Check which game_uids exist in database
print(f"\nChecking database for existing game_uids...")
existing_uids = set()
for game_uid in list(csv_games_by_uid.keys())[:100]:  # Check first 100
    result = supabase.table('games').select('game_uid').eq('game_uid', game_uid).execute()
    if result.data:
        existing_uids.add(game_uid)

print(f"  Found {len(existing_uids)} existing game_uids (checked first 100)")

# Check for game_uid conflicts (same game_uid but different scores)
print(f"\nChecking for game_uid conflicts (same game_uid, different scores)...")
conflicts = 0
for game_uid, csv_versions in list(csv_games_by_uid.items())[:50]:  # Check first 50
    if game_uid in existing_uids:
        # Check if any CSV version matches database
        db_result = supabase.table('games').select('home_provider_id, away_provider_id, game_date, home_score, away_score').eq('game_uid', game_uid).execute()
        if db_result.data:
            db_game = db_result.data[0]
            db_composite = f"{provider_id}|{db_game['home_provider_id']}|{db_game['away_provider_id']}|{db_game['game_date']}|{str(db_game['home_score']) if db_game['home_score'] is not None else '-1'}|{str(db_game['away_score']) if db_game['away_score'] is not None else '-1'}"
            
            # Check if any CSV version matches
            matches = False
            for csv_version in csv_versions:
                if csv_version['composite_key'] == db_composite:
                    matches = True
                    break
            
            if not matches:
                conflicts += 1
                if conflicts <= 5:
                    print(f"  Conflict: {game_uid}")
                    print(f"    DB: home={db_game['home_provider_id']}, away={db_game['away_provider_id']}, scores={db_game['home_score']}-{db_game['away_score']}")
                    print(f"    CSV: home={csv_versions[0]['home_id']}, away={csv_versions[0]['away_id']}, scores={csv_versions[0]['home_score']}-{csv_versions[0]['away_score']}")

print(f"\n  Total conflicts found: {conflicts} (checked first 50 game_uids)")
