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

# Get the September 6 game
game_uid = 'modular11:2025-09-06:14:249'

result = supabase.table('games').select('game_uid, home_provider_id, away_provider_id, home_team_master_id, away_team_master_id, home_score, away_score, game_date').eq('game_uid', game_uid).execute()

if result.data:
    game = result.data[0]
    print(f"Game: {game_uid}")
    print(f"  home_provider_id={game['home_provider_id']}, home_team_master_id={game['home_team_master_id']}")
    print(f"  away_provider_id={game['away_provider_id']}, away_team_master_id={game['away_team_master_id']}")
    print(f"  scores={game['home_score']}-{game['away_score']}")
    print()
    
    # Get team names
    home_team = supabase.table('teams').select('team_name, age_group, gender').eq('team_id_master', game['home_team_master_id']).execute()
    away_team = supabase.table('teams').select('team_name, age_group, gender').eq('team_id_master', game['away_team_master_id']).execute()
    
    print("Team details:")
    if home_team.data:
        print(f"  Home: {home_team.data[0]['team_name']} ({home_team.data[0].get('age_group')}, {home_team.data[0].get('gender')})")
    if away_team.data:
        print(f"  Away: {away_team.data[0]['team_name']} ({away_team.data[0].get('age_group')}, {away_team.data[0].get('gender')})")
    print()
    
    # Check what aliases these master IDs have
    print("Checking aliases for these master IDs:")
    home_aliases = supabase.table('team_alias_map').select('provider_team_id').eq('team_id_master', game['home_team_master_id']).eq('provider_id', provider_id).execute()
    away_aliases = supabase.table('team_alias_map').select('provider_team_id').eq('team_id_master', game['away_team_master_id']).eq('provider_id', provider_id).execute()
    
    print(f"  Home team ({game['home_team_master_id']}) aliases: {[a['provider_team_id'] for a in home_aliases.data]}")
    print(f"  Away team ({game['away_team_master_id']}) aliases: {[a['provider_team_id'] for a in away_aliases.data]}")
    
    # Now check what master IDs team 14 and 249 should have
    print("\n" + "="*70)
    print("Checking what master IDs provider IDs 14 and 249 should map to:")
    print("="*70)
    
    team_14_aliases = supabase.table('team_alias_map').select('team_id_master, provider_team_id').eq('provider_id', provider_id).in_('provider_team_id', ['14_U14_HD', '14_U14', '14']).execute()
    team_249_aliases = supabase.table('team_alias_map').select('team_id_master, provider_team_id').eq('provider_id', provider_id).in_('provider_team_id', ['249_U14_HD', '249_U14', '249']).execute()
    
    print(f"Team 14 aliases:")
    for alias in team_14_aliases.data:
        print(f"  {alias['provider_team_id']} -> {alias['team_id_master']}")
    
    print(f"\nTeam 249 aliases:")
    for alias in team_249_aliases.data:
        print(f"  {alias['provider_team_id']} -> {alias['team_id_master']}")
    
    print(f"\nGame's master IDs:")
    print(f"  Home master ID: {game['home_team_master_id']}")
    print(f"  Away master ID: {game['away_team_master_id']}")
    
    # Check if they match
    team_14_master_ids = set(a['team_id_master'] for a in team_14_aliases.data)
    team_249_master_ids = set(a['team_id_master'] for a in team_249_aliases.data)
    
    print(f"\nMatch check:")
    print(f"  Home master ID in team 14 IDs? {game['home_team_master_id'] in team_14_master_ids}")
    print(f"  Away master ID in team 249 IDs? {game['away_team_master_id'] in team_249_master_ids}")
