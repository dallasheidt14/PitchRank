#!/usr/bin/env python3
"""
Quick script to check import progress from database
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()
load_dotenv()

def check_progress():
    """Check import progress from database"""
    try:
        supabase = create_client(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        )
        
        # Check games imported
        games_result = supabase.table('games').select('game_uid', count='exact').limit(1).execute()
        games_count = games_result.count if hasattr(games_result, 'count') else 0
        
        # Check quarantined games
        quarantine_result = supabase.table('quarantine_games').select('id', count='exact').limit(1).execute()
        quarantine_count = quarantine_result.count if hasattr(quarantine_result, 'count') else 0
        
        # Check pending matches
        pending_result = supabase.table('team_alias_map').select('id', count='exact').eq('review_status', 'pending').limit(1).execute()
        pending_matches = pending_result.count if hasattr(pending_result, 'count') else 0
        
        # Check approved matches
        approved_result = supabase.table('team_alias_map').select('id', count='exact').eq('review_status', 'approved').limit(1).execute()
        approved_matches = approved_result.count if hasattr(approved_result, 'count') else 0
        
        # Get recent build logs
        build_logs = supabase.table('build_logs').select('*').eq('stage', 'game_import').order('started_at', desc=True).limit(5).execute()
        
        # Display results
        console.print("\n[bold cyan]📊 Import Progress[/bold cyan]\n")
        
        # Summary table
        summary_table = Table(title="Current Status", box=box.ROUNDED)
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Count", style="green", justify="right")
        
        summary_table.add_row("Games Imported", f"{games_count:,}")
        summary_table.add_row("Games Quarantined", f"{quarantine_count:,}")
        summary_table.add_row("Team Matches (Approved)", f"{approved_matches:,}")
        summary_table.add_row("Team Matches (Pending Review)", f"{pending_matches:,}")
        
        console.print(summary_table)
        
        # Build logs
        if build_logs.data:
            console.print("\n[bold cyan]Recent Build Logs[/bold cyan]\n")
            logs_table = Table(title="Build History", box=box.ROUNDED)
            logs_table.add_column("Build ID", style="cyan", width=20)
            logs_table.add_column("Started", style="yellow", width=20)
            logs_table.add_column("Status", style="magenta", width=15)
            logs_table.add_column("Games Processed", style="green", justify="right", width=15)
            logs_table.add_column("Games Accepted", style="green", justify="right", width=15)
            
            active_import = None
            for log in build_logs.data:
                metrics = log.get('metrics', {}) or {}
                started = log.get('started_at', 'N/A')
                completed = log.get('completed_at')
                
                if started and started != 'N/A':
                    try:
                        started_dt = datetime.fromisoformat(started.replace('Z', '+00:00'))
                        started = started_dt.strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        pass
                
                # Determine status based on completed_at field
                if completed is None:
                    status = 'in_progress'
                    status_color = 'yellow'
                    if active_import is None:
                        active_import = log
                else:
                    status = 'completed'
                    status_color = 'green'
                
                logs_table.add_row(
                    str(log.get('build_id', 'N/A'))[:20],
                    started,
                    f"[{status_color}]{status}[/{status_color}]",
                    str(metrics.get('games_processed', log.get('records_processed', 0))),
                    str(metrics.get('games_accepted', log.get('records_succeeded', 0)))
                )
            
            # Show active import details if found
            if active_import:
                console.print(f"\n[bold yellow]⚠️  Active Import Detected![/bold yellow]")
                metrics = active_import.get('metrics', {}) or {}
                started = active_import.get('started_at', 'N/A')
                if started and started != 'N/A':
                    try:
                        from datetime import timezone
                        started_dt = datetime.fromisoformat(started.replace('Z', '+00:00'))
                        now = datetime.now(timezone.utc) if started_dt.tzinfo else datetime.now()
                        elapsed = (now - started_dt).total_seconds()
                        hours = int(elapsed // 3600)
                        minutes = int((elapsed % 3600) // 60)
                        console.print(f"  Build ID: [cyan]{active_import.get('build_id', 'N/A')}[/cyan]")
                        console.print(f"  Started: [yellow]{started_dt.strftime('%Y-%m-%d %H:%M:%S')}[/yellow]")
                        console.print(f"  Running for: [yellow]{hours}h {minutes}m[/yellow]")
                        console.print(f"  Games processed so far: [green]{metrics.get('games_processed', active_import.get('records_processed', 0)):,}[/green]")
                        console.print(f"  Games accepted so far: [green]{metrics.get('games_accepted', active_import.get('records_succeeded', 0)):,}[/green]")
                    except Exception as e:
                        console.print(f"  [yellow]Could not calculate elapsed time: {e}[/yellow]")
            
            console.print(logs_table)
        else:
            console.print("\n[yellow]No build logs found yet. Import may still be initializing...[/yellow]")
        
        # Progress estimate
        if games_count > 0:
            expected_total = 1_225_075  # From validation
            progress_pct = (games_count / expected_total * 100) if expected_total > 0 else 0
            remaining = expected_total - games_count
            
            console.print(f"\n[bold]Progress Estimate:[/bold]")
            console.print(f"  [green]{games_count:,}[/green] / [cyan]{expected_total:,}[/cyan] games ({progress_pct:.1f}%)")
            console.print(f"  [yellow]Remaining: {remaining:,} games[/yellow]")
        
    except Exception as e:
        console.print(f"[red]Error checking progress: {e}[/red]")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    check_progress()

