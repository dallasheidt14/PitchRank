#!/usr/bin/env python3
"""Check if games from latest import were inserted"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import os
from dotenv import load_dotenv
from supabase import create_client
import json

load_dotenv('.env.local')

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

# Get provider ID
provider_result = supabase.table('providers').select('id').eq('code', 'gotsport').execute()
if not provider_result.data:
    print("Provider not found")
    sys.exit(1)
provider_id = provider_result.data[0]['id']

# Check total games
total_result = supabase.table('games').select('game_uid', count='exact').eq('provider_id', provider_id).limit(1).execute()
print(f"Total games in database: {total_result.count:,}")

# Check recent games
recent = supabase.table('games').select('game_uid, game_date, home_score, away_score, scraped_at').eq('provider_id', provider_id).order('scraped_at', desc=True).limit(10).execute()
print(f"\nMost recent 10 games:")
for g in recent.data:
    scraped_str = g['scraped_at'][:19] if g.get('scraped_at') else 'N/A'
    print(f"  {g['game_uid']} - {g['game_date']} - Score: {g['home_score']}-{g['away_score']} - Scraped: {scraped_str}")

# Check if any games from the latest scrape file exist
latest_file = Path('data/raw/scraped_games_20251111_122256.jsonl')
if latest_file.exists():
    print(f"\nChecking games from {latest_file.name}...")
    sample_games = []
    with open(latest_file, 'r') as f:
        for i, line in enumerate(f):
            if i >= 5:  # Check first 5 games
                break
            if line.strip():
                sample_games.append(json.loads(line))
    
    print(f"\nSample games from scrape file:")
    for game in sample_games:
        game_uid = f"gotsport:{game['game_date']}:{min(game['team_id'], game['opponent_id'])}:{max(game['team_id'], game['opponent_id'])}"
        # Check if exists
        check = supabase.table('games').select('game_uid').eq('game_uid', game_uid).limit(1).execute()
        exists = len(check.data) > 0
        status = "✅ EXISTS" if exists else "❌ NOT FOUND"
        print(f"  {game_uid} - {status}")

