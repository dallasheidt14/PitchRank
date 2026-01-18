"""Match unmatched Modular11 games using existing aliases"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

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
print("MATCH UNMATCHED MODULAR11 GAMES")
print("=" * 70)

# Get all unmatched games
print("\nFetching unmatched games...")
unmatched_games = supabase.table('games').select(
    'id, game_uid, game_date, home_provider_id, away_provider_id, home_team_master_id, away_team_master_id'
).eq('provider_id', modular11_provider_id).or_(
    'home_team_master_id.is.null,away_team_master_id.is.null'
).execute()

print(f"Found {len(unmatched_games.data)} unmatched games")

# Get all aliases
print("\nFetching team aliases...")
aliases_result = supabase.table('team_alias_map').select(
    'provider_team_id, team_id_master, review_status'
).eq('provider_id', modular11_provider_id).eq('review_status', 'approved').execute()

# Build alias lookup
alias_map = {}
for alias in aliases_result.data:
    provider_id = str(alias.get('provider_team_id', ''))
    if provider_id:
        alias_map[provider_id] = alias.get('team_id_master')

print(f"Found {len(alias_map)} approved aliases")

# Get all teams for age validation
print("\nFetching teams for age validation...")
teams_result = supabase.table('teams').select('team_id_master, age_group, gender').execute()
teams_by_id = {team['team_id_master']: team for team in teams_result.data}

print(f"Found {len(teams_by_id)} teams")

# Process games
print("\nProcessing games...")
matched_count = 0
failed_count = 0
age_mismatch_count = 0
no_alias_count = 0
updates = []

for game in unmatched_games.data:
    game_id = game.get('id')
    game_uid = game.get('game_uid')
    home_provider_id = str(game.get('home_provider_id', '')) if game.get('home_provider_id') else None
    away_provider_id = str(game.get('away_provider_id', '')) if game.get('away_provider_id') else None
    current_home_id = game.get('home_team_master_id')
    current_away_id = game.get('away_team_master_id')
    
    home_team_id = None
    away_team_id = None
    
    # Look up home team
    if not current_home_id and home_provider_id:
        home_team_id = alias_map.get(home_provider_id)
        if not home_team_id:
            no_alias_count += 1
            continue
    
    # Look up away team
    if not current_away_id and away_provider_id:
        away_team_id = alias_map.get(away_provider_id)
        if not away_team_id:
            no_alias_count += 1
            continue
    
    # Use existing IDs if already set
    if current_home_id:
        home_team_id = current_home_id
    if current_away_id:
        away_team_id = current_away_id
    
    # Validate age groups match
    if home_team_id and away_team_id:
        home_team = teams_by_id.get(home_team_id)
        away_team = teams_by_id.get(away_team_id)
        
        if home_team and away_team:
            home_age = home_team.get('age_group', '').lower() if home_team.get('age_group') else None
            away_age = away_team.get('age_group', '').lower() if away_team.get('age_group') else None
            
            if home_age and away_age:
                try:
                    home_age_num = int(home_age.replace('u', '').replace('U', ''))
                    away_age_num = int(away_age.replace('u', '').replace('U', ''))
                    
                    # Age mismatch if difference >= 2 years
                    if abs(home_age_num - away_age_num) >= 2:
                        age_mismatch_count += 1
                        print(f"  ⚠️  Age mismatch: {game_uid} - {home_age} vs {away_age}")
                        continue
                except (ValueError, AttributeError):
                    pass
    
    # Add to updates
    if home_team_id or away_team_id:
        update_data = {}
        if home_team_id and not current_home_id:
            update_data['home_team_master_id'] = home_team_id
        if away_team_id and not current_away_id:
            update_data['away_team_master_id'] = away_team_id
        
        if update_data:
            updates.append({
                'game_id': game_id,
                'update_data': update_data
            })
            matched_count += 1

print(f"\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"Total unmatched games: {len(unmatched_games.data)}")
print(f"  ✓ Can be matched: {matched_count}")
print(f"  ✗ No alias found: {no_alias_count}")
print(f"  ✗ Age mismatch: {age_mismatch_count}")
print(f"  ✗ Other issues: {len(unmatched_games.data) - matched_count - no_alias_count - age_mismatch_count}")

if matched_count == 0:
    print("\nNo games can be matched. Exiting.")
    sys.exit(0)

# Confirm update
print(f"\n" + "=" * 70)
response = input(f"\n⚠️  Update {matched_count} games with team matches? (type 'yes' to confirm): ").strip().lower()

if response != 'yes':
    print("\nUpdate cancelled.")
    sys.exit(0)

# Update games
print(f"\nUpdating {matched_count} games...")
updated = 0
failed = 0

for update in updates:
    try:
        supabase.table('games').update(update['update_data']).eq('id', update['game_id']).execute()
        updated += 1
        if updated % 50 == 0:
            print(f"  Updated {updated}/{matched_count} games...")
    except Exception as e:
        print(f"  ✗ Error updating game {update['game_id']}: {e}")
        failed += 1

print("\n" + "=" * 70)
print("UPDATE COMPLETE")
print("=" * 70)
print(f"✓ Successfully updated: {updated} games")
if failed > 0:
    print(f"✗ Failed to update: {failed} games")
print("=" * 70)













