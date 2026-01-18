#!/usr/bin/env python3
"""
Check which teams have specific aliases that are causing conflicts.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from rich.console import Console
from rich.table import Table

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
conflict_aliases = ['159673', '474_U14_AD', '249_U14_AD']

console.print(f"\n[bold]Checking conflicts for aliases: {', '.join(conflict_aliases)}[/bold]\n")

for alias in conflict_aliases:
    console.print(f"\n[bold cyan]Alias: {alias}[/bold cyan]")
    
    # Find all teams that have this alias
    try:
        alias_result = supabase.table('team_alias_map').select(
            'team_id_master, provider_id, provider_team_id, division'
        ).eq('provider_team_id', alias).execute()
        
        if alias_result.data:
            # Get team details for each team_id_master
            table = Table(title=f"Teams with alias '{alias}'")
            table.add_column("Team ID", style="cyan")
            table.add_column("Team Name", style="green")
            table.add_column("Club Name", style="yellow")
            table.add_column("Age Group", style="magenta")
            table.add_column("Gender", style="blue")
            table.add_column("State", style="red")
            table.add_column("Division", style="white")
            table.add_column("Provider ID", style="white")
            
            for alias_row in alias_result.data:
                team_id = alias_row['team_id_master']
                
                # Get team details
                team_result = supabase.table('teams').select(
                    'team_id_master, team_name, club_name, age_group, gender, state_code, state'
                ).eq('team_id_master', team_id).limit(1).execute()
                
                if team_result.data:
                    team = team_result.data[0]
                    table.add_row(
                        str(team_id)[:8] + '...',
                        team.get('team_name', 'N/A'),
                        team.get('club_name', 'N/A'),
                        team.get('age_group', 'N/A'),
                        team.get('gender', 'N/A'),
                        team.get('state_code', 'N/A') or team.get('state', 'N/A'),
                        alias_row.get('division', 'N/A'),
                        str(alias_row.get('provider_id', 'N/A'))
                    )
            
            console.print(table)
        else:
            console.print(f"[yellow]No teams found with alias '{alias}'[/yellow]")
            
    except Exception as e:
        console.print(f"[red]Error checking alias {alias}: {e}[/red]")

console.print("\n")

