#!/usr/bin/env python3
"""Delete games and teams from the most recent Modular11 import"""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
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
if not provider_result.data:
    console.print("[red]Error: Modular11 provider not found[/red]")
    sys.exit(1)

modular11_provider_id = provider_result.data[0]['id']

# Find games imported in the last 2 hours (to catch everything from recent import)
cutoff_time = (datetime.now() - timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%S')

console.print(f"\n[bold]Finding games imported after {cutoff_time}...[/bold]")

games_result = supabase.table('games').select(
    'id, game_uid, created_at, home_team_master_id, away_team_master_id'
).eq('provider_id', modular11_provider_id).gte('created_at', cutoff_time).execute()

if not games_result.data:
    console.print("[green]No recent games found to delete[/green]")
    sys.exit(0)

games = games_result.data
console.print(f"[yellow]Found {len(games)} games to delete[/yellow]")

# Get unique team IDs from these games
team_ids = set()
for game in games:
    if game.get('home_team_master_id'):
        team_ids.add(game['home_team_master_id'])
    if game.get('away_team_master_id'):
        team_ids.add(game['away_team_master_id'])

console.print(f"[yellow]Found {len(team_ids)} unique teams involved[/yellow]")

# Check which teams were created recently (likely the new ones)
recent_teams = []
cutoff_time_str = cutoff_time
for team_id in team_ids:
    team_result = supabase.table('teams').select('team_id_master, team_name, created_at').eq('team_id_master', team_id).execute()
    if team_result.data:
        team = team_result.data[0]
        team_created_str = team['created_at']
        # Simple string comparison (ISO format strings compare correctly)
        # Also check if created today (in case timezone is off)
        if team_created_str > cutoff_time_str or team_created_str.startswith('2026-01-12'):
            recent_teams.append(team)

console.print(f"\n[bold]Teams created in last hour: {len(recent_teams)}[/bold]")
for team in recent_teams[:10]:
    console.print(f"  - {team['team_name']} ({team['team_id_master']})")
if len(recent_teams) > 10:
    console.print(f"  ... and {len(recent_teams) - 10} more")

# Confirm deletion
console.print("\n[bold red]⚠️  WARNING: About to delete:[/bold red]")
console.print(f"  - {len(games)} games")
console.print(f"  - {len(recent_teams)} newly created teams")
console.print("\n[bold]This action cannot be undone![/bold]")

auto_yes = '--yes' in sys.argv
if not auto_yes:
    response = input("\nType 'DELETE' to confirm: ")
    if response != 'DELETE':
        console.print("[yellow]Cancelled.[/yellow]")
        sys.exit(0)
else:
    console.print("\n[green]Auto-confirming deletion (--yes flag)[/green]")

# Delete games
console.print(f"\n[bold]Deleting {len(games)} games...[/bold]")
game_uids = [g['game_uid'] for g in games]

deleted_games = 0
batch_size = 100
for i in range(0, len(game_uids), batch_size):
    batch = game_uids[i:i+batch_size]
    for game_uid in batch:
        try:
            supabase.table('games').delete().eq('game_uid', game_uid).execute()
            deleted_games += 1
        except Exception as e:
            console.print(f"[red]Error deleting {game_uid}: {e}[/red]")

console.print(f"[green]✅ Deleted {deleted_games} games[/green]")

# Delete newly created teams (but only if they have no other games)
console.print(f"\n[bold]Checking teams for deletion...[/bold]")
deleted_teams = 0

for team in recent_teams:
    team_id = team['team_id_master']
    # Check if team has any remaining games
    games_check = supabase.table('games').select('id').or_(
        f'home_team_master_id.eq.{team_id},away_team_master_id.eq.{team_id}'
    ).limit(1).execute()
    
    if not games_check.data:
        # No games left, safe to delete
        try:
            supabase.table('teams').delete().eq('team_id_master', team_id).execute()
            deleted_teams += 1
            console.print(f"  ✅ Deleted team: {team['team_name']}")
        except Exception as e:
            console.print(f"  ❌ Error deleting team {team_id}: {e}")
    else:
        console.print(f"  ⚠️  Keeping team: {team['team_name']} (has other games)")

console.print(f"\n[green]✅ Deleted {deleted_teams} teams[/green]")

console.print("\n[bold green]=" * 80)
console.print("[bold green]UNDO COMPLETE[/bold green]")
console.print("[bold green]=" * 80)
console.print(f"\n✅ Deleted {deleted_games} games")
console.print(f"✅ Deleted {deleted_teams} teams")

