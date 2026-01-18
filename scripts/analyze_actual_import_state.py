"""Analyze what actually happened during imports"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime, timedelta

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# Get Modular11 provider ID
providers_result = supabase.table('providers').select('id').eq('code', 'modular11').execute()
if not providers_result.data:
    print("Error: Modular11 provider not found")
    sys.exit(1)

modular11_provider_id = providers_result.data[0]['id']

print("=" * 70)
print("ACTUAL IMPORT STATE ANALYSIS")
print("=" * 70)

# Get all Modular11 games
games_result = supabase.table('games').select('id, game_uid, game_date, home_team_master_id, away_team_master_id, created_at').eq('provider_id', modular11_provider_id).order('created_at', desc=False).execute()

print(f"\nTotal Modular11 games in database: {len(games_result.data):,}")

# Check when games were created
if games_result.data:
    first_game = games_result.data[0]
    last_game = games_result.data[-1]
    print(f"\nFirst game created: {first_game.get('created_at', 'N/A')}")
    print(f"Last game created: {last_game.get('created_at', 'N/A')}")

# Count by matching status
matched = 0
unmatched = 0
for game in games_result.data:
    if game.get('home_team_master_id') and game.get('away_team_master_id'):
        matched += 1
    else:
        unmatched += 1

print(f"\nMatching Status:")
print(f"  Matched (both teams): {matched:,}")
print(f"  Unmatched (NULL IDs): {unmatched:,}")

# Check if games have provider_team_ids (from original CSV)
print(f"\nChecking game structure...")
sample = games_result.data[0] if games_result.data else {}
print(f"Sample game keys: {list(sample.keys())[:15]}")

# Check for home_provider_id and away_provider_id
games_with_provider_ids = 0
for game in games_result.data[:100]:  # Check first 100
    if game.get('home_provider_id') or game.get('away_provider_id'):
        games_with_provider_ids += 1

print(f"\nGames with provider_team_ids (first 100): {games_with_provider_ids}/100")

# Get team counts
teams_result = supabase.table('teams').select('team_id_master, age_group, provider_id').eq('provider_id', modular11_provider_id).execute()
print(f"\nModular11 teams in database: {len(teams_result.data):,}")

# Count teams by age
age_counts = {}
for team in teams_result.data:
    age = team.get('age_group', 'Unknown')
    age_counts[age] = age_counts.get(age, 0) + 1

print(f"\nTeams by age group:")
for age in sorted(age_counts.keys()):
    print(f"  {age}: {age_counts[age]:,} teams")

# Check alias map
alias_result = supabase.table('team_alias_map').select('id').eq('provider_id', modular11_provider_id).execute()
print(f"\nTeam alias mappings: {len(alias_result.data):,}")

# Check review queue
review_result = supabase.table('team_match_review_queue').select('id').eq('provider_id', 'modular11').eq('status', 'pending').execute()
print(f"Pending review queue entries: {len(review_result.data):,}")

print("\n" + "=" * 70)
print("KEY QUESTIONS TO ANSWER:")
print("=" * 70)
print("1. Are the 1,000 games the result of a single import or multiple?")
print("2. Why do games have NULL team IDs? (imported before matching? rejected?)")
print("3. Are there games that should have been imported but weren't?")
print("4. What's the actual state - do we need to re-import or just re-match?")
print("=" * 70)













