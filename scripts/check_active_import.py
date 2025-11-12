#!/usr/bin/env python3
"""Check if import process is currently running"""
import os
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from rich.console import Console
from rich.table import Table

console = Console()
load_dotenv('.env.local')

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

provider_result = supabase.table('providers').select('id').eq('code', 'gotsport').single().execute()
provider_id = provider_result.data['id']

# Get recent build logs (last 10 minutes)
ten_minutes_ago = (datetime.now() - timedelta(minutes=10)).isoformat()
recent_logs = supabase.table('build_logs').select('*').eq('provider_id', provider_id).gte('started_at', ten_minutes_ago).order('started_at', desc=True).limit(5).execute()

# Get very recent games (last 5 minutes)
five_minutes_ago = (datetime.now() - timedelta(minutes=5)).isoformat()
recent_games = supabase.table('games').select('id', count='exact').eq('provider_id', provider_id).gte('created_at', five_minutes_ago).execute()

console.print("\n[bold cyan]🔍 Checking for Active Import Process...[/bold cyan]\n")

# Check for logs without completed_at (in progress)
active_logs = []
if recent_logs.data:
    for log in recent_logs.data:
        started = log.get('started_at', '')
        completed = log.get('completed_at')
        if not completed:
            # Check if started recently (within last hour)
            if started:
                started_dt = datetime.fromisoformat(started.replace('Z', '+00:00').replace('+00:00', ''))
                if (datetime.now() - started_dt.replace(tzinfo=None)) < timedelta(hours=1):
                    active_logs.append(log)

table = Table(title="📊 Import Status", show_header=True, header_style="bold cyan")
table.add_column("Metric", style="cyan")
table.add_column("Value", style="green")

if active_logs:
    console.print("[yellow]⚠️  Found potentially active import(s):[/yellow]\n")
    for log in active_logs:
        metrics = log.get('metrics', {})
        table.add_row("Build ID", log.get('build_id', 'N/A'))
        table.add_row("Stage", log.get('stage', 'N/A'))
        table.add_row("Started", log.get('started_at', 'N/A')[:19] if log.get('started_at') else 'N/A')
        table.add_row("Status", "🔄 IN PROGRESS (no completed_at)")
        table.add_row("Games Processed", f"{metrics.get('games_processed', 0):,}")
        table.add_row("Games Accepted", f"{metrics.get('games_accepted', 0):,}")
        table.add_row("", "")
else:
    table.add_row("Active Imports", "❌ None found")
    if recent_logs.data:
        latest = recent_logs.data[0]
        table.add_row("Latest Build", latest.get('build_id', 'N/A'))
        completed = latest.get('completed_at')
        if completed:
            table.add_row("Latest Status", f"✅ Completed at {completed[:19]}")
        else:
            table.add_row("Latest Status", "🔄 May still be running")

table.add_row("", "")
table.add_row("Games Added (Last 5 min)", f"{recent_games.count if hasattr(recent_games, 'count') else len(recent_games.data) if recent_games.data else 0:,}")

# Check terminal activity indicator
if recent_games.count > 0 if hasattr(recent_games, 'count') else (len(recent_games.data) > 0 if recent_games.data else False):
    table.add_row("Activity Indicator", "✅ Database activity detected")
else:
    table.add_row("Activity Indicator", "⚠️  No recent database activity")

console.print(table)

# Summary
if active_logs:
    console.print("\n[yellow]💡 Import appears to be running based on incomplete build logs[/yellow]")
elif recent_games.count > 0 if hasattr(recent_games, 'count') else (len(recent_games.data) > 0 if recent_games.data else False):
    console.print("\n[green]✅ Recent database activity detected - import may be processing[/green]")
else:
    console.print("\n[dim]ℹ️  No active import detected. Check terminal for HTTP requests to confirm.[/dim]")

