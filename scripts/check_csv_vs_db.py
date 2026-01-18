"""Check CSV vs imported games"""
import os
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
supabase = create_client(supabase_url, supabase_key)

provider_id = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'

# Load CSV
df = pd.read_csv('scrapers/modular11_scraper/output/modular11_u13.csv')
print(f'=== CSV STATS ===')
print(f'Total rows: {len(df)}')
print(f'Unique team_id: {df["team_id"].nunique()}')
print(f'Unique games (match_id): {df["match_id"].nunique()}')

# Get DB games
games = supabase.table('games').select('*', count='exact').eq('provider_id', provider_id).execute()
print(f'\n=== DATABASE STATS ===')
print(f'Games in DB: {games.count}')

# Get unique teams in DB games
all_games = supabase.table('games').select('home_provider_id, away_provider_id').eq('provider_id', provider_id).execute()
db_teams = set()
for g in all_games.data:
    if g.get('home_provider_id'):
        db_teams.add(str(g['home_provider_id']))
    if g.get('away_provider_id'):
        db_teams.add(str(g['away_provider_id']))
print(f'Unique teams in DB games: {len(db_teams)}')

# Compare
csv_teams = set(df['team_id'].astype(str).unique())
print(f'\n=== COMPARISON ===')
print(f'Teams in CSV: {len(csv_teams)}')
print(f'Teams in DB: {len(db_teams)}')
print(f'Teams in BOTH: {len(csv_teams & db_teams)}')
print(f'Teams ONLY in CSV: {len(csv_teams - db_teams)}')
print(f'Teams ONLY in DB: {len(db_teams - csv_teams)}')

# Why are there more teams in CSV?
# Check if CSV has games that aren't in DB
csv_match_ids = set(df['match_id'].astype(str).unique())
print(f'\n=== GAMES COMPARISON ===')
print(f'Unique games in CSV: {len(csv_match_ids)}')
print(f'Games in DB: {games.count}')
print(f'Missing from DB: {len(csv_match_ids) - games.count} games')













