#!/usr/bin/env python3
"""
Update scrape dates for teams to reflect historical import date

This sets last_scraped_at and creates team_scrape_log entries
for teams that were already imported from a previous scrape.
"""
import sys
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
from rich.console import Console
from rich.progress import track
import logging

console = Console()
load_dotenv()

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def update_scrape_dates(import_date: str, provider: str = 'gotsport', confirm: bool = True):
    """
    Update scrape dates for all teams to reflect historical import
    
    Args:
        import_date: Date string in format 'YYYY-MM-DD' (e.g., '2024-11-01')
        provider: Provider code (default: 'gotsport')
        confirm: Whether to ask for confirmation (default: True)
    """
    supabase = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    )
    
    # Parse import date
    try:
        import_dt = datetime.fromisoformat(import_date)
        import_iso = import_dt.isoformat()
    except ValueError:
        console.print(f"[red]Invalid date format: {import_date}. Use YYYY-MM-DD[/red]")
        return
    
    # Get provider ID
    provider_result = supabase.table('providers').select('id').eq('code', provider).execute()
    if not provider_result.data:
        console.print(f"[red]Provider '{provider}' not found[/red]")
        return
    
    provider_id = provider_result.data[0]['id']
    
    # Get all teams for this provider
    console.print(f"[cyan]Fetching teams for provider '{provider}'...[/cyan]")
    teams_result = supabase.table('teams').select('team_id_master, provider_team_id, team_name').eq(
        'provider_id', provider_id
    ).execute()
    
    teams = teams_result.data
    console.print(f"[green]Found {len(teams)} teams[/green]\n")
    
    if not teams:
        console.print("[yellow]No teams found to update[/yellow]")
        return
    
    # Confirm action
    console.print(f"[yellow]This will update scrape dates to: {import_date}[/yellow]")
    console.print(f"[yellow]This affects {len(teams)} teams[/yellow]")
    if confirm:
        response = input("\nContinue? (yes/no): ").strip().lower()
        if response != 'yes':
            console.print("[yellow]Cancelled[/yellow]")
            return
    
    # OPTIMIZED: Single bulk update for all teams (MUCH faster!)
    console.print(f"\n[cyan]Bulk updating teams.last_scraped_at...[/cyan]")
    
    team_ids = [team['team_id_master'] for team in teams]
    
    try:
        # Use single UPDATE query for all teams matching provider_id
        # This is MUCH faster than individual updates!
        console.print(f"[dim]Updating {len(team_ids)} teams in one query...[/dim]")
        
        result = supabase.table('teams').update({
            'last_scraped_at': import_iso
        }).eq('provider_id', provider_id).execute()
        
        # Count updated rows
        updated_teams = len(result.data) if result.data else len(team_ids)
        console.print(f"[green]✅ Updated {updated_teams} teams in one query![/green]")
        
    except Exception as e:
        console.print(f"[yellow]Bulk update failed, falling back to batch updates: {e}[/yellow]")
        logger.warning(f"Bulk update error: {e}", exc_info=True)
        
        # Fallback: Update in smaller batches
        batch_size = 50
        updated_teams = 0
        for i in track(range(0, len(team_ids), batch_size), description="Updating teams..."):
            batch_ids = team_ids[i:i + batch_size]
            for team_id in batch_ids:
                try:
                    supabase.table('teams').update({
                        'last_scraped_at': import_iso
                    }).eq('team_id_master', team_id).execute()
                    updated_teams += 1
                except Exception as err:
                    logger.warning(f"Error updating team {team_id}: {err}")
        console.print(f"[green]✅ Updated {updated_teams} teams[/green]")
    
    # Batch update/create team_scrape_log entries
    console.print(f"\n[cyan]Updating team_scrape_log entries...[/cyan]")
    
    try:
        # First, get existing log entries
        console.print("[dim]Checking existing log entries...[/dim]")
        existing_logs_result = supabase.table('team_scrape_log').select('team_id, id').eq(
            'provider_id', provider_id
        ).in_('team_id', team_ids).execute()
        
        existing_log_map = {log['team_id']: log['id'] for log in existing_logs_result.data}
        
        # Separate into updates and inserts
        to_update = []
        to_insert = []
        
        for team_id in team_ids:
            if team_id in existing_log_map:
                to_update.append({
                    'id': existing_log_map[team_id],
                    'scraped_at': import_iso
                })
            else:
                to_insert.append({
                    'team_id': team_id,
                    'provider_id': provider_id,
                    'scraped_at': import_iso,
                    'games_found': 0,
                    'status': 'success'
                })
        
        # Batch insert new entries (Supabase supports bulk inserts!)
        if to_insert:
            console.print(f"[dim]Inserting {len(to_insert)} new log entries in batches...[/dim]")
            batch_size = 100
            inserted_count = 0
            for i in range(0, len(to_insert), batch_size):
                batch = to_insert[i:i + batch_size]
                try:
                    result = supabase.table('team_scrape_log').insert(batch).execute()
                    if result.data:
                        inserted_count += len(result.data)
                except Exception as e:
                    logger.warning(f"Error inserting log batch {i}: {e}")
            console.print(f"[green]✅ Inserted {inserted_count} new log entries[/green]")
        
        # Batch update existing entries using provider filter (faster than individual)
        if to_update:
            console.print(f"[dim]Updating {len(to_update)} existing log entries...[/dim]")
            # Use bulk update with provider filter
            try:
                result = supabase.table('team_scrape_log').update({
                    'scraped_at': import_iso
                }).eq('provider_id', provider_id).execute()
                updated_logs = len(result.data) if result.data else len(to_update)
                console.print(f"[green]✅ Updated {updated_logs} log entries[/green]")
            except Exception as e:
                # Fallback to individual updates if bulk fails
                console.print(f"[yellow]Bulk log update failed, using individual updates: {e}[/yellow]")
                updated_logs = 0
                for log_entry in track(to_update, description="Updating logs..."):
                    try:
                        supabase.table('team_scrape_log').update({
                            'scraped_at': import_iso
                        }).eq('id', log_entry['id']).execute()
                        updated_logs += 1
                    except Exception as err:
                        logger.warning(f"Error updating log {log_entry['id']}: {err}")
                console.print(f"[green]✅ Updated {updated_logs} log entries[/green]")
        
    except Exception as e:
        console.print(f"[yellow]Warning: Error updating logs: {e}[/yellow]")
        logger.warning(f"Log update error: {e}", exc_info=True)
    
    updated = updated_teams
    errors = []  # Errors are logged but don't stop the process
    
    # Verify update (sample)
    console.print(f"\n[cyan]Verifying update (sample)...[/cyan]")
    try:
        verify_result = supabase.table('teams').select('team_id_master, last_scraped_at').eq(
            'provider_id', provider_id
        ).limit(5).execute()
        
        console.print(f"\n[green]Sample updated teams:[/green]")
        for team in verify_result.data:
            date_str = team['last_scraped_at'][:10] if team['last_scraped_at'] else 'NULL'
            console.print(f"  - {team['team_id_master']}: {date_str}")
    except Exception as e:
        console.print(f"[yellow]Could not verify: {e}[/yellow]")
    
    console.print(f"\n[bold green]✅ Done![/bold green]")
    console.print(f"[dim]Teams will now only scrape games after {import_date}[/dim]")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Update scrape dates for historical import')
    parser.add_argument('--import-date', type=str, required=True,
                       help='Date of historical import (YYYY-MM-DD, e.g., 2024-11-01)')
    parser.add_argument('--provider', type=str, default='gotsport',
                       help='Provider code (default: gotsport)')
    parser.add_argument('--yes', action='store_true',
                       help='Skip confirmation prompt')
    
    args = parser.parse_args()
    
    update_scrape_dates(args.import_date, args.provider, confirm=not args.yes)

