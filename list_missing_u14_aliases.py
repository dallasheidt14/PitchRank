#!/usr/bin/env python3
"""List teams that need U14 aliases created"""
import csv
import os
import sys
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv
from supabase import create_client
from rich.console import Console
from rich.table import Table

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

csv_teams = defaultdict(set)  # provider_id -> set of (age, division) tuples
csv_team_info = {}  # provider_id -> {team_name, club_name}

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

console.print(f"[green]Found {len(csv_teams)} unique provider IDs in CSV[/green]")

# Get all Modular11 aliases
console.print("\n[bold]Fetching database aliases...[/bold]")
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

console.print(f"[green]Found {len(all_aliases)} aliases in database[/green]")

# Build alias lookup
aliases_by_base_id = defaultdict(list)  # base_id -> list of aliases

for alias in all_aliases:
    provider_team_id = str(alias['provider_team_id'])
    
    # Extract base ID
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

# Fetch team names
for team_id in list(team_ids_to_fetch)[:500]:  # Limit to avoid huge query
    result = supabase.table('teams').select('team_id_master, team_name, age_group').eq('team_id_master', team_id).execute()
    if result.data:
        team_names_by_id[team_id] = result.data[0]

# Find missing aliases
missing_aliases = []

for csv_id, age_divisions in csv_teams.items():
    team_info = csv_team_info.get(csv_id, {})
    team_name = team_info.get('team_name', 'Unknown')
    
    # Extract base ID
    base_id = csv_id
    if '_' in csv_id:
        parts = csv_id.split('_')
        if parts[0].isdigit():
            base_id = parts[0]
    
    matching_aliases = aliases_by_base_id.get(base_id, [])
    
    if not matching_aliases:
        # No aliases at all - might be a name-based ID
        missing_aliases.append({
            'provider_id': csv_id,
            'base_id': base_id,
            'team_name': team_name,
            'needed_aliases': [f"{base_id}_{age}_{div}" for age, div in age_divisions],
            'reason': 'No aliases found'
        })
    else:
        # Check which age/division combinations are missing
        needed_aliases = []
        existing_aliases = [a['full_alias'] for a in matching_aliases]
        
        for age, division in age_divisions:
            expected_alias = f"{base_id}_{age}_{division}"
            if expected_alias not in existing_aliases:
                needed_aliases.append(expected_alias)
        
        if needed_aliases:
            # Find a master team ID to use (prefer one with matching age group)
            master_team_id = None
            master_team_name = None
            
            # Try to find a team with matching age group
            for alias_info in matching_aliases:
                team_id = alias_info['team_id_master']
                if team_id in team_names_by_id:
                    team_data = team_names_by_id[team_id]
                    if team_data.get('age_group', '').lower() == 'u14':
                        master_team_id = team_id
                        master_team_name = team_data.get('team_name', 'Unknown')
                        break
            
            # If no U14 team found, use the first one
            if not master_team_id and matching_aliases:
                master_team_id = matching_aliases[0]['team_id_master']
                if master_team_id in team_names_by_id:
                    master_team_name = team_names_by_id[master_team_id].get('team_name', 'Unknown')
            
            missing_aliases.append({
                'provider_id': csv_id,
                'base_id': base_id,
                'team_name': team_name,
                'needed_aliases': needed_aliases,
                'master_team_id': master_team_id,
                'master_team_name': master_team_name,
                'existing_aliases': existing_aliases[:5],
                'reason': 'Missing specific U14 aliases'
            })

console.print(f"\n[bold red]Found {len(missing_aliases)} teams needing U14 aliases[/bold red]\n")

# Display in table
table = Table(title="Missing U14 Aliases")
table.add_column("Provider ID", style="cyan")
table.add_column("Team Name", style="yellow")
table.add_column("Needed Aliases", style="red")
table.add_column("Master Team", style="green")

for item in missing_aliases:
    provider_id = item['provider_id']
    team_name = item['team_name'][:40] + "..." if len(item['team_name']) > 40 else item['team_name']
    needed = ", ".join(item['needed_aliases'])
    master = item.get('master_team_name', 'N/A')[:30] + "..." if item.get('master_team_name') and len(item.get('master_team_name', '')) > 30 else (item.get('master_team_name', 'N/A') or 'N/A')
    
    table.add_row(provider_id, team_name, needed, master)

console.print(table)

console.print(f"\n[bold]Summary:[/bold]")
console.print(f"  Total teams needing aliases: {len(missing_aliases)}")
console.print(f"  Total aliases needed: {sum(len(item['needed_aliases']) for item in missing_aliases)}")



