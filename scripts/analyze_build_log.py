#!/usr/bin/env python3
"""Check build log details including all metrics"""
import sys
from pathlib import Path
import json
sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.json import JSON

console = Console()
load_dotenv()

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

# Get latest build log with full details
result = supabase.table('build_logs').select('*').order('started_at', desc=True).limit(1).execute()

if result.data:
    log = result.data[0]
    metrics = log.get('metrics', {})
    
    console.print(f"[cyan]Build ID: {log['build_id']}[/cyan]")
    console.print(f"[cyan]Started: {log['started_at']}[/cyan]")
    console.print(f"[cyan]Completed: {log.get('completed_at', 'IN PROGRESS')}[/cyan]\n")
    
    console.print("[bold]Metrics:[/bold]")
    console.print(JSON(json.dumps(metrics, indent=2)))
    
    # Check if game_records might be empty
    games_processed = metrics.get('games_processed', 0)
    games_accepted = metrics.get('games_accepted', 0)
    teams_matched = metrics.get('teams_matched', 0)
    duplicates_skipped = metrics.get('duplicates_skipped', 0)
    
    console.print(f"\n[cyan]Analysis:[/cyan]")
    console.print(f"  Games Processed: {games_processed:,}")
    console.print(f"  Games Accepted: {games_accepted:,}")
    console.print(f"  Teams Matched: {teams_matched:,}")
    console.print(f"  Duplicates Skipped: {duplicates_skipped:,}")
    
    # Calculate expected game_records
    # If teams_matched is high, games should be matched
    # But if games_accepted is 0, either game_records is empty OR insertion failed
    
    if teams_matched > 0 and games_accepted == 0:
        console.print(f"\n[red]⚠️  PROBLEM: {teams_matched:,} teams matched but 0 games accepted![/red]")
        console.print("[yellow]Possible causes:[/yellow]")
        console.print("  1. game_records list is empty (games matched but not added to list)")
        console.print("  2. Insertion is failing silently")
        console.print("  3. All games are duplicates (but duplicates_found is 0)")
        
        # Estimate how many games should be in game_records
        # If teams_matched is high, we should have many games
        estimated_games = teams_matched // 2  # Rough estimate (2 teams per game)
        console.print(f"\n[dim]Estimated games that should be matched: ~{estimated_games:,}[/dim]")
    
    errors = log.get('errors', [])
    if errors:
        console.print(f"\n[red]Errors ({len(errors)}):[/red]")
        for err in errors[:10]:
            console.print(f"  - {err}")

