#!/usr/bin/env python3
"""Export list of missing aliases to CSV"""
import csv
import os
import sys
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv
from supabase import create_client
from rich.console import Console

console = Console()

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set[/red]")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# Get Modular11 provider ID
provider_result = supabase.table('providers').select('id').eq('code', 'modular11').execute()
modular11_provider_id = provider_result.data[0]['id']

# Read CSV
csv_path = Path(r"C:\PitchRank\scrapers\modular11_scraper\output\MODU14.csv")
console.print(f"\n[bold]Reading CSV: {csv_path}[/bold]")

csv_teams = defaultdict(set)
csv_team_info = {}

with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        team_id = str(row.get('team_id', '')).strip()
        opponent_id = str(row.get('opponent_id', '')).strip()
        age_group = row.get('age_group', '').strip()
        mls_division = row.get('mls_division', '').strip()
        
        if team_id:
            csv_teams[team_id].add((age_group, mls_division))
            if team_id not in csv_team_info:
                csv_team_info[team_id] = {
                    'team_name': row.get('team_name', ''),
                    'club_name': row.get('club_name', '')
                }
        
        if opponent_id:
            csv_teams[opponent_id].add((age_group, mls_division))
            if opponent_id not in csv_team_info:
                csv_team_info[opponent_id] = {
                    'team_name': row.get('opponent_name', ''),
                    'club_name': row.get('opponent_club_name', '')
                }

# Get all Modular11 aliases
console.print("[bold]Fetching database aliases...[/bold]")
all_aliases = []
offset = 0
limit = 1000

while True:
    result = supabase.table('team_alias_map').select(
        'provider_team_id, team_id_master, match_method, review_status'
    ).eq('provider_id', modular11_provider_id).range(offset, offset + limit - 1).execute()
    
    if not result.data:
        break
    
    all_aliases.extend(result.data)
    
    if len(result.data) < limit:
        break
    
    offset += limit

# Build alias lookup
aliases_by_base_id = defaultdict(list)

for alias in all_aliases:
    provider_team_id = str(alias['provider_team_id'])
    
    base_id = provider_team_id
    if '_' in provider_team_id:
        parts = provider_team_id.split('_')
        if parts[0].isdigit():
            base_id = parts[0]
    
    aliases_by_base_id[base_id].append({
        'full_alias': provider_team_id,
        'team_id_master': alias['team_id_master'],
        'match_method': alias['match_method'],
        'review_status': alias['review_status']
    })

# Get team names for master IDs
team_names_by_id = {}
team_ids_to_fetch = set()
for aliases in aliases_by_base_id.values():
    for alias_info in aliases:
        team_ids_to_fetch.add(alias_info['team_id_master'])

# Fetch team names in batches
for i in range(0, len(list(team_ids_to_fetch)), 500):
    batch = list(team_ids_to_fetch)[i:i+500]
    for team_id in batch:
        result = supabase.table('teams').select('team_id_master, team_name, age_group').eq('team_id_master', team_id).execute()
        if result.data:
            team_names_by_id[team_id] = result.data[0]

# Find missing aliases
missing_aliases = []

for csv_id, age_divisions in csv_teams.items():
    team_info = csv_team_info.get(csv_id, {})
    team_name = team_info.get('team_name', 'Unknown')
    club_name = team_info.get('club_name', '')
    
    base_id = csv_id
    if '_' in csv_id:
        parts = csv_id.split('_')
        if parts[0].isdigit():
            base_id = parts[0]
    
    matching_aliases = aliases_by_base_id.get(base_id, [])
    
    if not matching_aliases:
        # No aliases at all
        for age, division in age_divisions:
            missing_aliases.append({
                'provider_id': csv_id,
                'base_id': base_id,
                'team_name': team_name,
                'club_name': club_name,
                'needed_alias': f"{base_id}_{age}_{division}",
                'age_group': age,
                'division': division,
                'master_team_id': None,
                'master_team_name': None,
                'action': 'CREATE_NEW_TEAM'
            })
    else:
        # Check which age/division combinations are missing
        existing_aliases = [a['full_alias'] for a in matching_aliases]
        
        for age, division in age_divisions:
            expected_alias = f"{base_id}_{age}_{division}"
            if expected_alias not in existing_aliases:
                # Find a master team ID to use (prefer one with matching age group)
                master_team_id = None
                master_team_name = None
                action = 'CREATE_NEW_TEAM'
                
                # Try to find a team with matching age group
                for alias_info in matching_aliases:
                    team_id = alias_info['team_id_master']
                    if team_id in team_names_by_id:
                        team_data = team_names_by_id[team_id]
                        if team_data.get('age_group', '').lower() == age.lower():
                            master_team_id = team_id
                            master_team_name = team_data.get('team_name', 'Unknown')
                            action = 'CREATE_ALIAS_ONLY'
                            break
                
                missing_aliases.append({
                    'provider_id': csv_id,
                    'base_id': base_id,
                    'team_name': team_name,
                    'club_name': club_name,
                    'needed_alias': expected_alias,
                    'age_group': age,
                    'division': division,
                    'master_team_id': master_team_id,
                    'master_team_name': master_team_name,
                    'action': action
                })

# Export to CSV
output_file = Path('missing_u14_aliases.csv')
console.print(f"\n[bold]Exporting to {output_file}...[/bold]")

with open(output_file, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'provider_id', 'base_id', 'team_name', 'club_name', 'needed_alias', 
        'age_group', 'division', 'master_team_id', 'master_team_name', 'action'
    ])
    writer.writeheader()
    writer.writerows(missing_aliases)

console.print(f"[green]✅ Exported {len(missing_aliases)} missing aliases to {output_file}[/green]")

# Also print summary
console.print(f"\n[bold]Summary:[/bold]")
console.print(f"  Total aliases needed: {len(missing_aliases)}")
create_alias_only = sum(1 for m in missing_aliases if m['action'] == 'CREATE_ALIAS_ONLY')
create_new_team = sum(1 for m in missing_aliases if m['action'] == 'CREATE_NEW_TEAM')
console.print(f"  Can create alias only (team exists): {create_alias_only}")
console.print(f"  Need new team created: {create_new_team}")

# Show first 10
console.print(f"\n[bold]First 10 entries:[/bold]")
for i, item in enumerate(missing_aliases[:10], 1):
    console.print(f"\n{i}. {item['team_name']}")
    console.print(f"   Provider ID: {item['provider_id']}")
    console.print(f"   Needed Alias: {item['needed_alias']}")
    console.print(f"   Action: {item['action']}")
    if item['master_team_name']:
        console.print(f"   Existing Team: {item['master_team_name']}")



