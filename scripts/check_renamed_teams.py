#!/usr/bin/env python3
"""Check if renamed teams have games and can get provider_team_id"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
import json

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

db = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))
MODULAR11_PROVIDER_ID = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'

teams_to_check = [
    'Hoover Vestavia 13 NEXT AD',
    'Barca Residency Academy 09 EA AD',
    'Hillsboro Rush U13 AD'
]

for team_name in teams_to_check:
    print(f"\n{'='*70}")
    print(f"Checking: {team_name}")
    print('='*70)
    
    # Find team
    result = db.table('teams').select('team_id_master, team_name').ilike('team_name', f'%{team_name}%').execute()
    if not result.data:
        print("❌ Team not found")
        continue
    
    team = result.data[0]
    team_id = team['team_id_master']
    print(f"✅ Found team: {team['team_name']}")
    print(f"   Team ID: {team_id}")
    
    # Check for aliases
    aliases = db.table('team_alias_map').select('provider_team_id').eq(
        'provider_id', MODULAR11_PROVIDER_ID
    ).eq('team_id_master', team_id).execute()
    
    if aliases.data:
        print(f"✅ Has {len(aliases.data)} alias(es):")
        for a in aliases.data:
            print(f"   {a['provider_team_id']}")
    else:
        print("⚠️  No aliases found")
    
    # Check for games
    games = db.table('games').select(
        'id, home_provider_id, away_provider_id, game_date'
    ).eq('provider_id', MODULAR11_PROVIDER_ID).or_(
        f'home_team_master_id.eq.{team_id},away_team_master_id.eq.{team_id}'
    ).limit(5).execute()
    
    if games.data:
        print(f"✅ Has {len(games.data)} game(s) (showing first 3):")
        for g in games.data[:3]:
            if g.get('home_team_master_id') == team_id:
                print(f"   Home: provider_id={g.get('home_provider_id')}, date={g.get('game_date')}")
            else:
                print(f"   Away: provider_id={g.get('away_provider_id')}, date={g.get('game_date')}")
    else:
        print("⚠️  No games found")







