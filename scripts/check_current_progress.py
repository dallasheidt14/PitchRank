#!/usr/bin/env python3
"""Check current import/scrape progress"""
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

# Get latest build log
latest_log = supabase.table('build_logs').select('*').eq('provider_id', provider_id).order('started_at', desc=True).limit(1).execute()

# Get recent games
one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
recent_games = supabase.table('games').select('id', count='exact').eq('provider_id', provider_id).gte('created_at', one_hour_ago).execute()

# Get recent scrape logs
recent_scrapes = supabase.table('team_scrape_log').select('*').eq('provider_id', provider_id).gte('scraped_at', one_hour_ago).order('scraped_at', desc=True).limit(10).execute()

# Check latest scrape file
raw_dir = Path('data/raw')
jsonl_files = sorted(raw_dir.glob('scraped_games_*.jsonl'), key=lambda x: x.stat().st_mtime, reverse=True)
latest_file = jsonl_files[0] if jsonl_files else None

table = Table(title="📊 Current Progress", show_header=True, header_style="bold cyan")
table.add_column("Metric", style="cyan")
table.add_column("Value", style="green")

if latest_log.data:
    log = latest_log.data[0]
    metrics = log.get('metrics', {})
    table.add_row("Latest Build ID", log.get('build_id', 'N/A'))
    table.add_row("Stage", log.get('stage', 'N/A'))
    table.add_row("Started", log.get('started_at', 'N/A')[:19] if log.get('started_at') else 'N/A')
    table.add_row("Completed", log.get('completed_at', 'N/A')[:19] if log.get('completed_at') else '🔄 IN PROGRESS')
    table.add_row("Games Processed", f"{metrics.get('games_processed', 0):,}")
    table.add_row("Games Accepted", f"{metrics.get('games_accepted', 0):,}")
    table.add_row("Games Quarantined", f"{metrics.get('games_quarantined', 0):,}")
    table.add_row("Duplicates Found", f"{metrics.get('duplicates_found', 0):,}")

table.add_row("", "")
table.add_row("Games Added (Last Hour)", f"{recent_games.count if hasattr(recent_games, 'count') else len(recent_games.data) if recent_games.data else 0:,}")

if recent_scrapes.data:
    table.add_row("Teams Scraped (Last Hour)", f"{len(recent_scrapes.data):,}")
    games_found = sum(log.get('games_found', 0) for log in recent_scrapes.data)
    table.add_row("Games Found (Last Hour)", f"{games_found:,}")

if latest_file:
    import json
    games_count = sum(1 for line in open(latest_file) if line.strip())
    table.add_row("", "")
    table.add_row("Latest Scrape File", latest_file.name)
    table.add_row("  Games in File", f"{games_count:,}")
    table.add_row("  File Modified", datetime.fromtimestamp(latest_file.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'))

console.print(table)

