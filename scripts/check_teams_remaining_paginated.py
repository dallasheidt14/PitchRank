"""Check actual teams remaining with pagination"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from rich.console import Console

console = Console()

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not supabase_url or not supabase_key:
    console.print("[red]Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.[/red]")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# Get provider ID for gotsport
provider_result = supabase.table('providers').select('id').eq('code', 'gotsport').single().execute()
if not provider_result.data:
    console.print("[red]Error: Provider 'gotsport' not found.[/red]")
    sys.exit(1)
provider_id = provider_result.data['id']

console.print("[cyan]Fetching all teams (with pagination)...[/cyan]\n")

# Fetch ALL teams with pagination
all_teams = []
page_size = 1000
offset = 0

while True:
    result = supabase.table('teams').select('id,last_scraped_at').eq('provider_id', provider_id).range(offset, offset + page_size - 1).execute()
    
    if not result.data:
        break
    
    all_teams.extend(result.data)
    
    if len(result.data) < page_size:
        break
    
    offset += page_size
    console.print(f"  Fetched {len(all_teams)} teams so far...")

total_teams = len(all_teams)
null_teams = [t for t in all_teams if t.get('last_scraped_at') is None]
scraped_teams = total_teams - len(null_teams)

console.print(f"\n[bold cyan]📊 Actual Teams Status[/bold cyan]\n")
console.print(f"Total Teams: {total_teams:,}")
console.print(f"Teams Scraped: {scraped_teams:,}")
console.print(f"[yellow]Teams Remaining (NULL last_scraped_at): {len(null_teams):,}[/yellow]")

if len(null_teams) > 0:
    progress_pct = (scraped_teams / total_teams * 100) if total_teams > 0 else 0
    console.print(f"\nProgress: {progress_pct:.1f}%")
    
    # Estimate time remaining (assuming ~2 seconds per team)
    teams_per_minute = 30  # conservative estimate (2 seconds per team)
    minutes_remaining = len(null_teams) / teams_per_minute
    hours_remaining = minutes_remaining / 60
    
    console.print(f"\n[cyan]Estimated time remaining:[/cyan]")
    console.print(f"  ~{minutes_remaining:.0f} minutes ({hours_remaining:.1f} hours) at current rate")
else:
    console.print(f"\n[green]✅ All teams have been scraped![/green]")
    console.print(f"[yellow]Note: Scraper may still be running if it's doing incremental updates[/yellow]")

