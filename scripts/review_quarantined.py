#!/usr/bin/env python3
"""
Review quarantined games from the database
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime
from collections import Counter
from typing import Optional

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.text import Text

console = Console()
load_dotenv()


def get_quarantine_summary(supabase):
    """Get summary statistics of quarantined games"""
    # Get total count
    count_result = supabase.table('quarantine_games').select('id', count='exact').limit(1).execute()
    total_count = count_result.count if hasattr(count_result, 'count') else 0
    
    if total_count == 0:
        return None, []
    
    # Get all quarantined games (may need pagination for large datasets)
    # For summary, we'll sample or get all if reasonable size
    max_sample = 10000  # Sample up to 10k for summary
    result = supabase.table('quarantine_games').select('reason_code').limit(max_sample).execute()
    
    # Count by reason code
    reason_counts = Counter()
    for game in result.data:
        reason_counts[game.get('reason_code', 'unknown')] += 1
    
    # If we sampled, estimate percentages
    if len(result.data) < total_count:
        # Scale up the counts proportionally
        scale_factor = total_count / len(result.data)
        scaled_counts = Counter()
        for reason, count in reason_counts.items():
            scaled_counts[reason] = int(count * scale_factor)
        reason_counts = scaled_counts
    
    return reason_counts, total_count


def display_summary(reason_counts, total_count):
    """Display summary statistics"""
    console.print("\n[bold cyan]📊 Quarantined Games Summary[/bold cyan]\n")
    
    summary_table = Table(title="Quarantine Statistics", box=box.ROUNDED)
    summary_table.add_column("Reason Code", style="cyan")
    summary_table.add_column("Count", style="magenta", justify="right")
    summary_table.add_column("Percentage", style="yellow", justify="right")
    
    # Calculate actual counts from reason_counts
    displayed_total = sum(reason_counts.values())
    
    for reason, count in reason_counts.most_common():
        percentage = (count / displayed_total * 100) if displayed_total > 0 else 0
        summary_table.add_row(
            reason,
            f"{count:,}",
            f"{percentage:.1f}%"
        )
    
    summary_table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{total_count:,}[/bold]",
        "100.0%"
    )
    
    console.print(summary_table)
    
    if displayed_total < total_count:
        console.print(f"[dim]Note: Summary based on sample of {displayed_total:,} games[/dim]")


def display_game_details(game, index: int, total: int):
    """Display detailed information about a quarantined game"""
    raw_data = game.get('raw_data', {})
    reason_code = game.get('reason_code', 'unknown')
    error_details = game.get('error_details', 'No details')
    created_at = game.get('created_at', 'N/A')
    
    # Format created_at
    if created_at and created_at != 'N/A':
        try:
            created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            created_at = created_dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            pass
    
    # Create details panel
    details_text = Text()
    details_text.append(f"Game {index + 1} of {total}\n\n", style="bold cyan")
    details_text.append("Reason: ", style="bold")
    details_text.append(f"{reason_code}\n", style="red")
    details_text.append("Error Details: ", style="bold")
    details_text.append(f"{error_details}\n\n", style="yellow")
    details_text.append("Quarantined: ", style="bold")
    details_text.append(f"{created_at}\n\n", style="dim")
    
    details_text.append("Game Data:\n", style="bold")
    for key, value in sorted(raw_data.items()):
        if key != 'validation_errors':  # Skip validation_errors as it's shown in error_details
            details_text.append(f"  {key}: ", style="cyan")
            details_text.append(f"{value}\n", style="white")
    
    console.print(Panel(details_text, title="Quarantined Game Details", border_style="red"))


def browse_quarantined_games(supabase, reason_code: Optional[str] = None, limit: int = 10, offset: int = 0):
    """Browse quarantined games with filtering"""
    query = supabase.table('quarantine_games').select('*')
    
    if reason_code:
        query = query.eq('reason_code', reason_code)
    
    query = query.order('created_at', desc=True)
    query = query.range(offset, offset + limit - 1)
    
    result = query.execute()
    return result.data if result.data else []


def export_quarantined_games(supabase, output_file: str, reason_code: Optional[str] = None):
    """Export quarantined games to CSV"""
    import csv
    
    query = supabase.table('quarantine_games').select('*')
    if reason_code:
        query = query.eq('reason_code', reason_code)
    query = query.order('created_at', desc=True)
    
    result = query.execute()
    
    if not result.data:
        console.print("[yellow]No quarantined games to export[/yellow]")
        return
    
    # Flatten the data for CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        # Get all unique keys from raw_data
        all_keys = set()
        for game in result.data:
            raw_data = game.get('raw_data', {})
            all_keys.update(raw_data.keys())
        
        # Create CSV writer
        fieldnames = ['id', 'reason_code', 'error_details', 'created_at'] + sorted(all_keys)
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for game in result.data:
            row = {
                'id': str(game.get('id', '')),
                'reason_code': game.get('reason_code', ''),
                'error_details': game.get('error_details', ''),
                'created_at': game.get('created_at', '')
            }
            
            # Add raw_data fields
            raw_data = game.get('raw_data', {})
            for key in sorted(all_keys):
                row[key] = raw_data.get(key, '')
            
            writer.writerow(row)
    
    console.print(f"[green]✅ Exported {len(result.data):,} quarantined games to {output_file}[/green]")


def main():
    parser = argparse.ArgumentParser(description='Review quarantined games')
    parser.add_argument('--reason', type=str, help='Filter by reason code')
    parser.add_argument('--limit', type=int, default=10, help='Number of games to show (default: 10)')
    parser.add_argument('--offset', type=int, default=0, help='Offset for pagination (default: 0)')
    parser.add_argument('--export', type=str, help='Export to CSV file')
    parser.add_argument('--summary-only', action='store_true', help='Show summary only')
    
    args = parser.parse_args()
    
    try:
        supabase = create_client(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        )
        
        # Get summary
        result = get_quarantine_summary(supabase)
        
        if result[0] is None:
            console.print("[green]✅ No quarantined games found![/green]")
            return
        
        reason_counts, total_count = result
        display_summary(reason_counts, total_count)
        
        if args.summary_only:
            return
        
        # Export if requested
        if args.export:
            export_quarantined_games(supabase, args.export, args.reason)
            return
        
        # Browse games
        console.print(f"\n[bold cyan]📋 Browsing Quarantined Games[/bold cyan]")
        if args.reason:
            console.print(f"[yellow]Filtered by reason: {args.reason}[/yellow]")
        
        games = browse_quarantined_games(supabase, args.reason, args.limit, args.offset)
        
        if not games:
            console.print("[yellow]No games found with the specified filters[/yellow]")
            return
        
        console.print(f"\nShowing {len(games)} games (offset: {args.offset})\n")
        
        # Display each game
        for idx, game in enumerate(games):
            display_game_details(game, idx, len(games))
            
            if idx < len(games) - 1:
                console.print()  # Add spacing between games
        
        # Show pagination info
        # Get total count for pagination
        count_result = supabase.table('quarantine_games').select('id', count='exact')
        if args.reason:
            count_result = count_result.eq('reason_code', args.reason)
        count_result = count_result.limit(1).execute()
        total_filtered = count_result.count if hasattr(count_result, 'count') else len(games)
        
        if args.offset + args.limit < total_filtered:
            console.print(f"\n[yellow]Showing {args.offset + 1}-{args.offset + len(games)} of {total_filtered:,} games[/yellow]")
            console.print(f"[dim]Use --offset {args.offset + args.limit} to see more[/dim]")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()

