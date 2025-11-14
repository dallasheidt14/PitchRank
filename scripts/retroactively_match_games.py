#!/usr/bin/env python3
"""
Retroactively match games that have provider IDs but no master team IDs
Uses existing team_alias_map entries to update games
"""
import sys
import asyncio
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from datetime import datetime

console = Console()
load_dotenv(Path('.env.local'))

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

async def retroactively_match_games(provider_code: str = 'gotsport', dry_run: bool = True):
    """Match games retroactively using team_alias_map"""
    
    # Get provider ID
    provider_result = supabase.table('providers').select('id').eq('code', provider_code).single().execute()
    provider_id = provider_result.data['id']
    
    console.print(f"[bold cyan]Retroactively Matching Games for {provider_code}[/bold cyan]")
    console.print(f"[yellow]Dry run: {dry_run}[/yellow]\n")
    
    # Load all alias mappings into memory for fast lookup
    console.print("[cyan]Loading team alias mappings...[/cyan]")
    alias_mappings = supabase.table('team_alias_map').select('provider_team_id, team_id_master').eq('provider_id', provider_id).eq('review_status', 'approved').execute()
    
    # Create lookup dict: provider_team_id -> team_id_master
    alias_dict = {}
    for alias in alias_mappings.data:
        provider_team_id = str(alias['provider_team_id'])
        alias_dict[provider_team_id] = alias['team_id_master']
    
    console.print(f"[green]✓[/green] Loaded {len(alias_dict):,} alias mappings\n")
    
    # Find unmatched games
    console.print("[cyan]Finding unmatched games...[/cyan]")
    
    # Get games missing home team master ID
    unmatched_home = supabase.table('games').select('id, home_provider_id').eq('provider_id', provider_id).is_('home_team_master_id', 'null').not_.is_('home_provider_id', 'null').limit(10000).execute()
    
    # Get games missing away team master ID  
    unmatched_away = supabase.table('games').select('id, away_provider_id').eq('provider_id', provider_id).is_('away_team_master_id', 'null').not_.is_('away_provider_id', 'null').limit(10000).execute()
    
    # Create sets of game IDs that need updates
    games_to_update = {}
    
    for game in unmatched_home.data:
        game_id = game['id']
        provider_team_id = str(game.get('home_provider_id', ''))
        if provider_team_id in alias_dict:
            if game_id not in games_to_update:
                games_to_update[game_id] = {}
            games_to_update[game_id]['home_team_master_id'] = alias_dict[provider_team_id]
    
    for game in unmatched_away.data:
        game_id = game['id']
        provider_team_id = str(game.get('away_provider_id', ''))
        if provider_team_id in alias_dict:
            if game_id not in games_to_update:
                games_to_update[game_id] = {}
            games_to_update[game_id]['away_team_master_id'] = alias_dict[provider_team_id]
    
    console.print(f"[green]✓[/green] Found {len(games_to_update):,} games that can be matched\n")
    
    if not games_to_update:
        console.print("[yellow]No games found that can be matched[/yellow]")
        return
    
    # Show sample
    console.print("[bold]Sample games to update:[/bold]")
    sample_count = 0
    for game_id, updates in list(games_to_update.items())[:5]:
        console.print(f"  Game {game_id[:8]}...")
        if 'home_team_master_id' in updates:
            console.print(f"    Home: {updates['home_team_master_id'][:8]}...")
        if 'away_team_master_id' in updates:
            console.print(f"    Away: {updates['away_team_master_id'][:8]}...")
        sample_count += 1
        if sample_count >= 5:
            break
    
    if dry_run:
        console.print(f"\n[yellow]Dry run - would update {len(games_to_update):,} games[/yellow]")
        console.print("[yellow]Run with --no-dry-run to actually update[/yellow]")
        return
    
    # Update games in batches
    console.print(f"\n[cyan]Updating {len(games_to_update):,} games...[/cyan]")
    
    batch_size = 1000
    updated_count = 0
    failed_count = 0
    
    games_list = list(games_to_update.items())
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("Updating games...", total=len(games_list))
        
        for i in range(0, len(games_list), batch_size):
            batch = games_list[i:i + batch_size]
            
            for game_id, updates in batch:
                try:
                    supabase.table('games').update(updates).eq('id', game_id).execute()
                    updated_count += 1
                    progress.update(task, advance=1)
                except Exception as e:
                    failed_count += 1
                    console.print(f"[red]Error updating game {game_id}: {e}[/red]")
    
    console.print(f"\n[green]✅ Updated {updated_count:,} games[/green]")
    if failed_count > 0:
        console.print(f"[red]❌ Failed to update {failed_count:,} games[/red]")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Retroactively match games using team_alias_map')
    parser.add_argument('--provider', type=str, default='gotsport', help='Provider code')
    parser.add_argument('--no-dry-run', action='store_true', help='Actually update games (default is dry run)')
    
    args = parser.parse_args()
    
    asyncio.run(retroactively_match_games(
        provider_code=args.provider,
        dry_run=not args.no_dry_run
    ))






