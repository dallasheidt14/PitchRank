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

# Get team master IDs
team_14_aliases = supabase.table('team_alias_map').select('team_id_master').eq('provider_id', provider_id).in_('provider_team_id', ['14_U14_HD', '14_U14', '14']).execute()
team_249_aliases = supabase.table('team_alias_map').select('team_id_master').eq('provider_id', provider_id).in_('provider_team_id', ['249_U14_HD', '249_U14', '249']).execute()

team_14_master_ids = [a['team_id_master'] for a in team_14_aliases.data] if team_14_aliases.data else []
team_249_master_ids = [a['team_id_master'] for a in team_249_aliases.data] if team_249_aliases.data else []

print(f"Team 14 master IDs: {team_14_master_ids}")
print(f"Team 249 master IDs: {team_249_master_ids}\n")

# Check ALL games between these teams (by master IDs)
print("="*70)
print("Checking games by master team IDs:")
print("="*70)

if team_14_master_ids and team_249_master_ids:
    for team_14_id in team_14_master_ids:
        for team_249_id in team_249_master_ids:
            # Check games where team 14 is home
            games_home = supabase.table('games').select('game_uid, home_provider_id, away_provider_id, game_date, home_score, away_score, home_team_master_id, away_team_master_id').eq('provider_id', provider_id).eq('home_team_master_id', team_14_id).eq('away_team_master_id', team_249_id).execute()
            
            # Check games where team 14 is away
            games_away = supabase.table('games').select('game_uid, home_provider_id, away_provider_id, game_date, home_score, away_score, home_team_master_id, away_team_master_id').eq('provider_id', provider_id).eq('home_team_master_id', team_249_id).eq('away_team_master_id', team_14_id).execute()
            
            all_games = (games_home.data or []) + (games_away.data or [])
            
            if all_games:
                print(f"\nFound {len(all_games)} game(s) between these teams:")
                for game in all_games:
                    print(f"  game_uid: {game['game_uid']}")
                    print(f"  date: {game['game_date']}")
                    print(f"  home={game['home_provider_id']} (master: {game['home_team_master_id']})")
                    print(f"  away={game['away_provider_id']} (master: {game['away_team_master_id']})")
                    print(f"  scores: {game['home_score']}-{game['away_score']}")
                    print()

# Also check by provider IDs directly
print("="*70)
print("Checking games by provider IDs (14 vs 249):")
print("="*70)

games_by_provider = supabase.table('games').select('game_uid, home_provider_id, away_provider_id, game_date, home_score, away_score').eq('provider_id', provider_id).or_('and(home_provider_id.eq.14,away_provider_id.eq.249),and(home_provider_id.eq.249,away_provider_id.eq.14)').execute()

print(f"Found {len(games_by_provider.data)} game(s) by provider IDs:")
for game in games_by_provider.data:
    print(f"  game_uid: {game['game_uid']}")
    print(f"  date: {game['game_date']}")
    print(f"  home={game['home_provider_id']}, away={game['away_provider_id']}")
    print(f"  scores: {game['home_score']}-{game['away_score']}")
    print()
