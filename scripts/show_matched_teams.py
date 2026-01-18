#!/usr/bin/env python3
"""Show teams that were matched during the TGS event 4066 import"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime

# Load environment - prioritize .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# TGS provider ID
tgs_provider_id = 'ea79aa6e-679f-4b5b-92b1-e9f502df7582'

# Get teams that were matched by looking at games imported recently
print("Finding matched teams from TGS event 4066 import...")
print("=" * 80)

# Get games imported after 13:35:00
games_result = supabase.table('games').select(
    'home_team_master_id, away_team_master_id'
).eq('provider_id', tgs_provider_id).gte(
    'created_at', '2025-12-11T13:35:00'
).execute()

if not games_result.data:
    print("No games found.")
    sys.exit(0)

# Collect unique team IDs from the games
team_ids = set()
for game in games_result.data:
    if game.get('home_team_master_id'):
        team_ids.add(game['home_team_master_id'])
    if game.get('away_team_master_id'):
        team_ids.add(game['away_team_master_id'])

print(f"\nFound {len(team_ids)} unique teams in imported games\n")

# Get team details and their TGS provider mappings with matching info
teams_data = []
for team_id_master in sorted(team_ids):
    # Get all teams (from any provider) that share this master team ID
    all_teams_result = supabase.table('teams').select(
        'team_id_master, team_name, club_name, age_group, gender, state_code, provider_id, provider_team_id'
    ).eq('team_id_master', team_id_master).execute()
    
    if not all_teams_result.data:
        continue
    
    # Find master team info (usually the first one or one with specific provider)
    master_team = None
    tgs_teams = []
    
    for team in all_teams_result.data:
        if team.get('provider_id') == tgs_provider_id:
            tgs_teams.append(team)
        else:
            # Use first non-TGS team as master (or could be any)
            if master_team is None:
                master_team = team
    
    # If no master found, use first TGS team's info
    if master_team is None and tgs_teams:
        master_team = {
            'team_name': tgs_teams[0].get('team_name', ''),
            'club_name': tgs_teams[0].get('club_name', ''),
            'age_group': tgs_teams[0].get('age_group', ''),
            'gender': tgs_teams[0].get('gender', ''),
            'state_code': tgs_teams[0].get('state_code', '')
        }
    
    if not master_team:
        continue
    
    # Get alias mapping info
    alias_result = supabase.table('team_alias_map').select(
        'provider_team_id, match_method, review_status'
    ).eq('team_id_master', team_id_master).eq(
        'provider_id', tgs_provider_id
    ).execute()
    
    # Create a mapping of provider_team_id to match_method
    match_method_map = {m['provider_team_id']: m.get('match_method', 'direct_id') for m in alias_result.data if m.get('review_status') == 'approved'}
    
    # Add each TGS team that matched to this master team
    for tgs_team in tgs_teams:
        provider_team_id = tgs_team.get('provider_team_id', '')
        teams_data.append({
            'provider_team_id': provider_team_id,
            'provider_team_name': tgs_team.get('team_name', ''),
            'provider_club_name': tgs_team.get('club_name', ''),
            'master_team_id': team_id_master,
            'master_team_name': master_team.get('team_name', ''),
            'master_club_name': master_team.get('club_name', ''),
            'age_group': master_team.get('age_group', ''),
            'gender': master_team.get('gender', ''),
            'state_code': master_team.get('state_code', ''),
            'match_method': match_method_map.get(provider_team_id, 'import')
        })

# Also get all team matches from games (to show the 234 count)
all_team_matches = []
for game in games_result.data:
    if game.get('home_team_master_id'):
        all_team_matches.append(game['home_team_master_id'])
    if game.get('away_team_master_id'):
        all_team_matches.append(game['away_team_master_id'])

# Create a lookup dict for team details
team_lookup = {t['master_team_id']: t for t in teams_data}

# Display teams with matching details
print(f"TGS Teams Matched to Master Teams ({len(teams_data)}):")
print("=" * 120)
print(f"{'TGS Team ID':<12} {'TGS Team Name':<35} {'→':<3} {'Master Team Name':<35} {'Age':<6} {'Gender':<8} {'Match':<12}")
print("-" * 120)

for team in sorted(teams_data, key=lambda x: (x['age_group'], x['gender'], x['provider_team_name'])):
    tgs_name = (team['provider_team_name'][:33] + '..') if len(team['provider_team_name']) > 35 else team['provider_team_name']
    master_name = (team['master_team_name'][:33] + '..') if len(team['master_team_name']) > 35 else team['master_team_name']
    print(f"{team['provider_team_id']:<12} {tgs_name:<35} {'→':<3} {master_name:<35} {team['age_group']:<6} {team['gender']:<8} {team['match_method']:<12}")

print(f"\n\nTotal Team Matches (including duplicates): {len(all_team_matches)}")
print("(Each game has 2 teams, so 117 games × 2 = 234 team matches)")

print("\n" + "=" * 80)
print(f"\nTotal: {len(teams_data)} teams matched")

# Show breakdown by match method
match_method_counts = {}
for team in teams_data:
    method = team['match_method']
    match_method_counts[method] = match_method_counts.get(method, 0) + 1

print("\nBreakdown by match method:")
for method, count in sorted(match_method_counts.items()):
    print(f"  {method}: {count}")

# Show breakdown by age group
age_group_counts = {}
for team in teams_data:
    age = team['age_group']
    age_group_counts[age] = age_group_counts.get(age, 0) + 1

print("\nBreakdown by age group:")
for age, count in sorted(age_group_counts.items()):
    print(f"  {age}: {count}")

# Save to CSV file
import csv
csv_path = Path('data/exports/tgs_event_4066_matched_teams.csv')
csv_path.parent.mkdir(parents=True, exist_ok=True)

with open(csv_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'tgs_team_id', 'tgs_team_name', 'tgs_club_name', 
        'master_team_id', 'master_team_name', 'master_club_name',
        'age_group', 'gender', 'state_code', 'match_method'
    ])
    writer.writeheader()
    for team in sorted(teams_data, key=lambda x: (x['age_group'], x['gender'], x['provider_team_name'])):
        writer.writerow({
            'tgs_team_id': team['provider_team_id'],
            'tgs_team_name': team['provider_team_name'],
            'tgs_club_name': team['provider_club_name'],
            'master_team_id': team['master_team_id'],
            'master_team_name': team['master_team_name'],
            'master_club_name': team['master_club_name'],
            'age_group': team['age_group'],
            'gender': team['gender'],
            'state_code': team['state_code'],
            'match_method': team['match_method']
        })

print(f"\n✅ Saved detailed list to: {csv_path}")

