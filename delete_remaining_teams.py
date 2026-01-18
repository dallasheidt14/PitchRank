#!/usr/bin/env python3
"""Delete the 2 remaining teams and their games"""
import os
import sys
from pathlib import Path
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

remaining_teams = [
    ('97427c48-021a-459b-b806-195d668e8e40', 'SC Wave U17'),
    ('4bc56b7c-b106-447e-869e-d82512c92be6', 'Oregon Surf SC U15')
]

console.print("\n[bold]Deleting games and teams...[/bold]")

for team_id, team_name in remaining_teams:
    console.print(f"\n{team_name}:")
    
    # Get games
    games_result = supabase.table('games').select('game_uid').or_(
        f'home_team_master_id.eq.{team_id},away_team_master_id.eq.{team_id}'
    ).execute()
    
    # Delete games
    for game in games_result.data:
        try:
            supabase.table('games').delete().eq('game_uid', game['game_uid']).execute()
            console.print(f"  ✅ Deleted game: {game['game_uid']}")
        except Exception as e:
            console.print(f"  ❌ Error deleting game: {e}")
    
    # Delete aliases
    aliases_result = supabase.table('team_alias_map').select('id').eq('team_id_master', team_id).execute()
    for alias in aliases_result.data:
        try:
            supabase.table('team_alias_map').delete().eq('id', alias['id']).execute()
            console.print(f"  ✅ Deleted alias")
        except Exception as e:
            pass
    
    # Delete rankings
    try:
        supabase.table('current_rankings').delete().eq('team_id', team_id).execute()
    except:
        pass
    
    # Delete team
    try:
        supabase.table('teams').delete().eq('team_id_master', team_id).execute()
        console.print(f"  ✅ Deleted team")
    except Exception as e:
        console.print(f"  ❌ Error deleting team: {e}")

console.print("\n[bold green]✅ Complete![/bold green]")



