#!/usr/bin/env python3
import os
from dotenv import load_dotenv
from supabase import create_client
from pathlib import Path

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))

tgs_provider = supabase.table('providers').select('id').eq('code', 'tgs').execute()
tgs_id = tgs_provider.data[0]['id']

print("Games with TGS Team ID 79561 (Eastside FC ECNL B12):")
games = supabase.table('games').select('game_uid, game_date, home_provider_id, away_provider_id, home_team_master_id, away_team_master_id').eq('home_provider_id', '79561').eq('provider_id', tgs_id).limit(5).execute()

if games.data:
    print(f"\nFound {len(games.data)} games (showing first 5):")
    for g in games.data:
        print(f"  {g['game_uid']}")
        print(f"    Date: {g['game_date']}")
        print(f"    Home Team Master ID: {g['home_team_master_id']}")
        
        # Get team name
        if g['home_team_master_id']:
            team = supabase.table('teams').select('team_name, age_group').eq('team_id_master', g['home_team_master_id']).execute()
            if team.data:
                print(f"    Team: {team.data[0].get('team_name')} ({team.data[0].get('age_group')})")
else:
    print("  No games found")

# Also check away games
away_games = supabase.table('games').select('game_uid, game_date, away_team_master_id').eq('away_provider_id', '79561').eq('provider_id', tgs_id).limit(3).execute()
if away_games.data:
    print(f"\nAway games (showing first 3):")
    for g in away_games.data:
        print(f"  {g['game_uid']} - {g['game_date']}")
        if g['away_team_master_id']:
            team = supabase.table('teams').select('team_name').eq('team_id_master', g['away_team_master_id']).execute()
            if team.data:
                print(f"    Team: {team.data[0].get('team_name')}")







