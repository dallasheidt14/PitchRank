#!/usr/bin/env python3
"""Check detailed import errors and retry status"""
import os
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from rich.console import Console
from rich.table import Table
import json

console = Console()
load_dotenv('.env.local')

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

provider_result = supabase.table('providers').select('id').eq('code', 'gotsport').single().execute()
provider_id = provider_result.data['id']

# Get latest build logs with detailed metrics
recent_logs = supabase.table('build_logs').select('*').eq('provider_id', provider_id).order('started_at', desc=True).limit(5).execute()

console.print("\n[bold cyan]🔍 Latest Import Attempts (with errors)[/bold cyan]\n")

if recent_logs.data:
    for log in recent_logs.data:
        build_id = log.get('build_id', 'N/A')
        stage = log.get('stage', 'N/A')
        started = log.get('started_at', 'N/A')
        completed = log.get('completed_at')
        metrics = log.get('metrics', {})
        errors = metrics.get('errors', [])
        
        # Check if this is likely the 15k import (started around 15:15)
        started_dt = datetime.fromisoformat(started.replace('Z', '+00:00').replace('+00:00', '')) if started else None
        is_15k_import = started_dt and started_dt.hour == 15 and started_dt.minute >= 10 and started_dt.minute <= 20
        
        status_icon = "🔄" if not completed else "✅"
        if is_15k_import:
            status_icon = "⚠️  15K IMPORT"
        
        console.print(f"{status_icon} Build: {build_id} | Stage: {stage}")
        console.print(f"   Started: {started[:19] if started else 'N/A'}")
        console.print(f"   Completed: {completed[:19] if completed else 'IN PROGRESS'}")
        console.print(f"   Games Processed: {metrics.get('games_processed', 0):,}")
        console.print(f"   Games Accepted: {metrics.get('games_accepted', 0):,}")
        console.print(f"   Games Quarantined: {metrics.get('games_quarantined', 0):,}")
        console.print(f"   Duplicates Found: {metrics.get('duplicates_found', 0):,}")
        
        if errors:
            console.print(f"   [red]Errors: {len(errors)}[/red]")
            console.print(f"   [yellow]First few errors:[/yellow]")
            for i, error in enumerate(errors[:3], 1):
                error_msg = str(error)[:200] if len(str(error)) > 200 else str(error)
                console.print(f"     {i}. {error_msg}")
        
        console.print()

# Check for the specific 15k scrape file
raw_dir = Path('data/raw')
jsonl_files = sorted(raw_dir.glob('scraped_games_*.jsonl'), key=lambda x: x.stat().st_mtime, reverse=True)

# Look for file around 15:15 timeframe
console.print("[bold cyan]📄 Recent Scrape Files:[/bold cyan]\n")
for f in jsonl_files[:3]:
    import json
    games_count = sum(1 for line in open(f) if line.strip())
    mod_time = datetime.fromtimestamp(f.stat().st_mtime)
    console.print(f"  {f.name}")
    console.print(f"    Games: {games_count:,}")
    console.print(f"    Modified: {mod_time.strftime('%Y-%m-%d %H:%M:%S')}")
    console.print()

