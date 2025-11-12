#!/usr/bin/env python3
"""
Delete quarantined games that have empty/missing scores

These are likely scheduled games or incomplete data that shouldn't be imported.
"""
import sys
from pathlib import Path
from typing import Dict, List
import time

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()
load_dotenv()

# Load .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)


def has_empty_scores(raw_data: Dict) -> bool:
    """Check if game has empty or missing scores"""
    goals_for = raw_data.get('goals_for', '')
    goals_against = raw_data.get('goals_against', '')
    
    # Check if scores are empty, None, or empty string
    if goals_for is None or str(goals_for).strip() == '':
        return True
    if goals_against is None or str(goals_against).strip() == '':
        return True
    
    return False


def delete_games_with_empty_scores(limit: int = None, dry_run: bool = False, batch_size: int = 1000):
    """Delete quarantined games with empty scores"""
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set[/red]")
        return
    
    supabase = create_client(supabase_url, supabase_key)
    
    # Get total count
    count_query = supabase.table('quarantine_games').select('id', count='exact')
    count_result = count_query.limit(1).execute()
    total_count = count_result.count if hasattr(count_result, 'count') else 0
    
    console.print(f"[cyan]Found {total_count:,} total quarantined games[/cyan]\n")
    
    if dry_run:
        console.print("[yellow]⚠️  DRY RUN MODE - No deletions will be made[/yellow]\n")
    
    deleted_count = 0
    checked_count = 0
    offset = 0
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        total_to_check = limit or total_count
        task = progress.add_task("[cyan]Checking quarantined games...", total=total_to_check)
        
        while True:
            # Fetch batch
            batch_query = supabase.table('quarantine_games').select('id, raw_data')
            batch_query = batch_query.order('created_at', desc=False)
            batch_query = batch_query.range(offset, offset + batch_size - 1)
            
            try:
                result = batch_query.execute()
            except Exception as e:
                if 'timeout' in str(e).lower() or '57014' in str(e):
                    console.print(f"[yellow]Query timeout at offset {offset}, skipping batch...[/yellow]")
                    offset += batch_size
                    if limit and checked_count >= limit:
                        break
                    continue
                else:
                    raise
            
            if not result.data or len(result.data) == 0:
                break
            
            # Find games with empty scores
            ids_to_delete = []
            for game in result.data:
                checked_count += 1
                raw_data = game.get('raw_data', {})
                
                if has_empty_scores(raw_data):
                    ids_to_delete.append(game['id'])
            
            # Delete games with empty scores (batch delete for efficiency)
            if ids_to_delete and not dry_run:
                # Delete in smaller batches to avoid connection issues
                delete_batch_size = 100
                for i in range(0, len(ids_to_delete), delete_batch_size):
                    batch_ids = ids_to_delete[i:i + delete_batch_size]
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            # Use .in_() for batch deletion
                            supabase.table('quarantine_games').delete().in_('id', batch_ids).execute()
                            deleted_count += len(batch_ids)
                            break
                        except Exception as e:
                            if attempt < max_retries - 1:
                                time.sleep(1)  # Wait before retry
                                continue
                            else:
                                # If batch fails, try individual deletes
                                console.print(f"[yellow]Batch delete failed, trying individual deletes...[/yellow]")
                                for game_id in batch_ids:
                                    try:
                                        supabase.table('quarantine_games').delete().eq('id', game_id).execute()
                                        deleted_count += 1
                                    except Exception as e2:
                                        console.print(f"[yellow]Failed to delete {game_id}: {e2}[/yellow]")
            elif ids_to_delete and dry_run:
                deleted_count += len(ids_to_delete)
            
            offset += batch_size
            progress.update(task, advance=len(result.data))
            
            if limit and checked_count >= limit:
                break
            
            # Small delay to avoid overwhelming the database
            if not dry_run and ids_to_delete:
                time.sleep(0.1)
    
    # Display summary
    console.print("\n")
    table = Table(title="Deletion Summary", show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="magenta", justify="right")
    
    table.add_row("Games Checked", f"{checked_count:,}")
    table.add_row("Games with Empty Scores", f"{deleted_count:,}")
    
    if dry_run:
        table.add_row("Status", "[yellow]DRY RUN - No deletions made[/yellow]")
    else:
        table.add_row("Status", f"[green]Deleted {deleted_count:,} games[/green]")
    
    console.print(table)
    
    if not dry_run:
        console.print(f"\n[green]✅ Cleanup complete! Deleted {deleted_count:,} games with empty scores[/green]")
    else:
        console.print(f"\n[yellow]Dry run complete - would delete {deleted_count:,} games[/yellow]")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Delete quarantined games with empty/missing scores'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of games to check (default: all)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Batch size for processing (default: 1000)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run mode - do not delete'
    )
    
    args = parser.parse_args()
    
    console.print(Panel.fit(
        f"[bold cyan]Delete Games with Empty Scores[/bold cyan]\n\n"
        f"Limit: {args.limit or 'All'}\n"
        f"Batch Size: {args.batch_size}\n"
        f"Dry Run: {'Yes' if args.dry_run else 'No'}",
        title="Configuration"
    ))
    
    delete_games_with_empty_scores(
        limit=args.limit,
        dry_run=args.dry_run,
        batch_size=args.batch_size
    )


if __name__ == '__main__':
    main()

