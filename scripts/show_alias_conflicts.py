#!/usr/bin/env python3
"""
Show detailed information about alias conflicts from the CA import.
"""
import os
import sys
import csv
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment[/red]")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# Aliases that caused warnings
conflict_aliases = {
    '159673': None,
    '474_U14_AD': None,
    '249_U14_AD': None
}

# Read CSV to find which teams were trying to use these aliases
csv_path = Path('u14_male_ca.csv')
csv_teams = {}

if csv_path.exists():
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            team_id = row.get('team_id_master', '').strip()
            alias_str = row.get('alias', '').strip()
            modular11_alias_str = row.get('modular11_alias', '').strip()
            
            # Check all aliases (semicolon-separated)
            all_aliases = []
            if alias_str:
                all_aliases.extend([a.strip() for a in alias_str.split(';') if a.strip()])
            if modular11_alias_str:
                all_aliases.extend([a.strip() for a in modular11_alias_str.split(';') if a.strip()])
            
            for alias in all_aliases:
                if alias in conflict_aliases:
                    if alias not in csv_teams:
                        csv_teams[alias] = []
                    csv_teams[alias].append({
                        'team_id_master': team_id,
                        'team_name': row.get('team_name', 'N/A'),
                        'club_name': row.get('club_name', 'N/A'),
                        'age_group': row.get('age_group', 'N/A'),
                        'gender': row.get('gender', 'N/A'),
                        'state': row.get('state_code', 'N/A') or row.get('state', 'N/A')
                    })

console.print("\n[bold]Alias Conflict Analysis[/bold]\n")

for alias in conflict_aliases.keys():
    console.print(f"\n[bold cyan]{'='*80}[/bold cyan]")
    console.print(f"[bold cyan]Alias: {alias}[/bold cyan]")
    console.print(f"[bold cyan]{'='*80}[/bold cyan]\n")
    
    # Find teams in database that already have this alias
    try:
        db_result = supabase.table('team_alias_map').select(
            'team_id_master, provider_id, provider_team_id, division'
        ).eq('provider_team_id', alias).execute()
        
        if db_result.data:
            console.print("[bold yellow]Teams in DATABASE with this alias:[/bold yellow]")
            db_table = Table()
            db_table.add_column("Team ID", style="cyan")
            db_table.add_column("Team Name", style="green")
            db_table.add_column("Club Name", style="yellow")
            db_table.add_column("Age Group", style="magenta")
            db_table.add_column("Gender", style="blue")
            db_table.add_column("State", style="red")
            db_table.add_column("Division", style="white")
            
            for alias_row in db_result.data:
                team_id = alias_row['team_id_master']
                
                # Get team details
                team_result = supabase.table('teams').select(
                    'team_id_master, team_name, club_name, age_group, gender, state_code, state'
                ).eq('team_id_master', team_id).limit(1).execute()
                
                if team_result.data:
                    team = team_result.data[0]
                    db_table.add_row(
                        team_id[:8] + '...',
                        team.get('team_name', 'N/A'),
                        team.get('club_name', 'N/A'),
                        team.get('age_group', 'N/A'),
                        team.get('gender', 'N/A'),
                        team.get('state_code', 'N/A') or team.get('state', 'N/A'),
                        alias_row.get('division', 'N/A')
                    )
            
            console.print(db_table)
        else:
            console.print("[yellow]No teams found in database with this alias[/yellow]")
    except Exception as e:
        console.print(f"[red]Error checking database: {e}[/red]")
    
    # Show teams from CSV that were trying to use this alias
    if alias in csv_teams:
        console.print(f"\n[bold yellow]Teams in CSV trying to use this alias:[/bold yellow]")
        csv_table = Table()
        csv_table.add_column("Team ID", style="cyan")
        csv_table.add_column("Team Name", style="green")
        csv_table.add_column("Club Name", style="yellow")
        csv_table.add_column("Age Group", style="magenta")
        csv_table.add_column("Gender", style="blue")
        csv_table.add_column("State", style="red")
        
        for team_info in csv_teams[alias]:
            csv_table.add_row(
                team_info['team_id_master'][:8] + '...',
                team_info['team_name'],
                team_info['club_name'],
                team_info['age_group'],
                team_info['gender'],
                team_info['state']
            )
        
        console.print(csv_table)
        
        # Check if they're the same teams
        if db_result.data and csv_teams[alias]:
            db_team_ids = {row['team_id_master'] for row in db_result.data}
            csv_team_ids = {team['team_id_master'] for team in csv_teams[alias]}
            
            if db_team_ids == csv_team_ids:
                console.print("\n[green]✓ Same team(s) - no conflict, just duplicate alias assignment[/green]")
            elif db_team_ids & csv_team_ids:
                console.print("\n[yellow]⚠ Partial match - some teams are the same[/yellow]")
            else:
                console.print("\n[red]✗ Different teams - CONFLICT![/red]")
    else:
        console.print("\n[yellow]No teams in CSV were trying to use this alias[/yellow]")
    
    console.print()

console.print()

