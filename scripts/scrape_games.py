#!/usr/bin/env python3
"""
Scrape games from GotSport and save to file for import
OPTIMIZED: Concurrent scraping with async/await, bulk operations, batched logging
"""
import asyncio
import sys
import re
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, date
import json
import csv
import logging
from typing import Dict, List, Optional, Tuple
from asyncio import Semaphore
import threading

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich import box

from src.scrapers.gotsport import GotSportScraper

console = Console()
load_dotenv()

# Load .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if env_local.exists():
    logger.info("Loaded .env.local")
else:
    logger.info("Loaded .env")


def _bulk_fetch_scrape_dates(supabase, provider_id: str, team_ids: List[str]) -> Dict[str, Optional[datetime]]:
    """OPTIMIZATION: Bulk fetch all last_scraped_at dates in one query"""
    if not team_ids:
        return {}
    
    # Initialize all teams to None
    scrape_dates = {team_id: None for team_id in team_ids}
    
    # Fetch from teams table (last_scraped_at column) - more efficient than team_scrape_log
    # Reduced batch size to avoid URL length limits (UUIDs are ~36 chars each)
    batch_size = 100
    
    for i in range(0, len(team_ids), batch_size):
        batch_ids = team_ids[i:i + batch_size]
        try:
            # Get last_scraped_at directly from teams table
            result = supabase.table('teams').select('team_id_master, last_scraped_at').in_(
                'team_id_master', batch_ids
            ).eq('provider_id', provider_id).execute()
            
            # Update scrape dates
            for team in result.data or []:
                team_id = team['team_id_master']
                last_scraped = team.get('last_scraped_at')
                if last_scraped:
                    try:
                        scrape_dates[team_id] = datetime.fromisoformat(last_scraped.replace('Z', '+00:00'))
                    except (ValueError, TypeError):
                        scrape_dates[team_id] = None
                else:
                    scrape_dates[team_id] = None
        except Exception as e:
            logger.warning(f"Error bulk fetching scrape dates: {e}")
            # Already initialized to None, so no action needed
    
    return scrape_dates


def _bulk_log_team_scrapes(supabase, provider_id: str, scrape_logs: List[Tuple[str, int]]):
    """OPTIMIZATION: Batch log team scrapes instead of individual calls"""
    if not scrape_logs:
        return
    
    now = datetime.now()
    now_iso = now.isoformat()
    
    # Prepare batch updates for teams table and log entries
    log_entries = []
    
    for team_id_master, games_found in scrape_logs:
        log_entries.append({
            'team_id': team_id_master,
            'provider_id': provider_id,
            'scraped_at': now_iso,
            'games_found': games_found,
            'status': 'success' if games_found > 0 else 'partial'
        })
    
    # Batch insert scrape logs first
    batch_size = 500  # Larger batches for inserts
    inserted_count = 0
    for i in range(0, len(log_entries), batch_size):
        batch = log_entries[i:i + batch_size]
        try:
            supabase.table('team_scrape_log').insert(batch).execute()
            inserted_count += len(batch)
        except Exception as e:
            logger.warning(f"Error batch inserting scrape logs (batch {i//batch_size + 1}): {e}")
    
    # Batch update teams.last_scraped_at (one update per team, but batched for efficiency)
    # Supabase doesn't support bulk UPDATE with different values easily, so we update individually but in batches
    batch_size = 100
    updated_count = 0
    for i in range(0, len(scrape_logs), batch_size):
        batch = scrape_logs[i:i + batch_size]
        for team_id_master, _ in batch:
            try:
                supabase.table('teams').update({
                    'last_scraped_at': now_iso
                }).eq('team_id_master', team_id_master).execute()
                updated_count += 1
            except Exception as e:
                logger.warning(f"Error updating last_scraped_at for team {team_id_master}: {e}")
    
    logger.info(f"Bulk logged {inserted_count} scrape logs and updated {updated_count} team timestamps")


async def _scrape_team_concurrent(
    semaphore: Semaphore,
    scraper: GotSportScraper,
    team: Dict,
    since_date: Optional[date],
    scrape_dates_cache: Dict[str, Optional[datetime]],
    file_lock: threading.Lock,
    output_file_handle,
    log_buffer: List[Tuple[str, int]],
    flush_counter: List[int],  # Thread-safe counter for flush tracking
    progress: Progress,
    task_id
) -> Tuple[int, Optional[str]]:
    """Scrape a single team (runs in thread pool for concurrency)"""
    async with semaphore:
        team_id = team.get('provider_team_id')
        team_name = team.get('team_name', 'Unknown')
        team_master_id = team.get('team_id_master')
        
        try:
            # Determine since_date for this team
            if since_date:
                team_since_date = datetime.combine(since_date, datetime.min.time())
            else:
                # Use cached scrape date
                team_since_date = scrape_dates_cache.get(team_master_id)
            
            # Run synchronous scraper in thread pool (since requests is sync)
            game_data_list = await asyncio.to_thread(
                scraper.scrape_team_games,
                team_id,
                since_date=team_since_date
            )
            
            # Convert GameData to dict format
            games = []
            for game_data in game_data_list:
                game_dict = scraper._game_data_to_dict(game_data, team_id)
                if game_dict:
                    games.append(game_dict)
            
            # Thread-safe file writing
            games_count = len(games)
            should_flush = False
            
            with file_lock:
                if games_count > 0:
                    for game in games:
                        output_file_handle.write(json.dumps(game) + '\n')
                
                # Increment flush counter (every team, not just those with games)
                flush_counter[0] += 1
                # Flush every 100 teams (reduced I/O, but still periodic)
                if flush_counter[0] % 100 == 0:
                    should_flush = True
                
                # Add to log buffer
                log_buffer.append((team_master_id, len(game_data_list)))
            
            # Flush outside lock to avoid blocking other threads
            if should_flush:
                with file_lock:
                    output_file_handle.flush()
            
            progress.update(task_id, advance=1)
            return games_count, None
            
        except Exception as e:
            error_msg = f"Team {team_id} ({team_name}): {str(e)}"
            logger.error(error_msg, exc_info=True)
            progress.update(task_id, advance=1)
            return 0, error_msg


async def scrape_games(
    provider: str = 'gotsport',
    output_file: str = None,
    limit_teams: int = None,
    skip_teams: int = 0,
    null_teams_only: bool = False,
    include_recent: bool = False,
    since_date: date = None,
    auto_import: bool = False,
    concurrency: int = 30
):
    """
    Scrape games from GotSport for all teams or specified teams

    OPTIMIZED with:
    - Concurrent scraping (async with semaphore)
    - Bulk fetch of scrape dates
    - Batched logging
    - Reduced file I/O

    Args:
        provider: Provider code (default: 'gotsport')
        output_file: Output file path (default: auto-generated)
        limit_teams: Limit number of teams to scrape (for testing)
        null_teams_only: Only scrape teams with NULL last_scraped_at (bootstrap mode)
        include_recent: Include teams scraped within last 7 days (override default filter)
        since_date: Override since_date for scraping (for NULL teams)
        auto_import: Automatically import scraped games after scraping completes
        concurrency: Number of concurrent scrapes (default: 30)
    """
    supabase = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    )
    
    # Initialize scraper
    scraper = GotSportScraper(supabase, provider)
    provider_id = scraper._get_provider_id()
    
    # Get teams to scrape
    # When limit_teams is specified, auto-enable include_recent so the user
    # actually gets that many teams instead of being capped by the 7-day filter
    if limit_teams and not null_teams_only and not include_recent:
        include_recent = True
        console.print(f"[cyan]--limit-teams={limit_teams} specified, auto-including all teams (sorted by stalest first)[/cyan]")

    if null_teams_only:
        # Get teams with NULL last_scraped_at (with pagination to handle >1000 teams)
        console.print("[cyan]Fetching teams with NULL last_scraped_at (paginated)...[/cyan]")
        teams = []
        page_size = 1000
        offset = 0

        while True:
            teams_result = supabase.table('teams').select('*').eq(
                'provider_id', provider_id
            ).is_('last_scraped_at', 'null').range(offset, offset + page_size - 1).execute()

            if not teams_result.data:
                break

            teams.extend(teams_result.data)

            if len(teams_result.data) < page_size:
                break

            offset += page_size
            console.print(f"  Fetched {len(teams)} teams so far...")

        console.print(f"[cyan]Found {len(teams)} teams with NULL last_scraped_at[/cyan]")
    elif include_recent:
        # Include ALL teams (override 7-day filter) - useful for manual re-scrapes
        # Sort by last_scraped_at so stalest teams are scraped first
        console.print("[cyan]Fetching ALL teams (including recently scraped, stalest first)...[/cyan]")
        teams = []
        page_size = 1000
        offset = 0

        while True:
            teams_result = supabase.table('teams').select('*').eq(
                'provider_id', provider_id
            ).order('last_scraped_at', desc=False, nullsfirst=True).range(offset, offset + page_size - 1).execute()

            if not teams_result.data:
                break

            teams.extend(teams_result.data)

            if len(teams_result.data) < page_size:
                break

            offset += page_size
            console.print(f"  Fetched {len(teams)} teams so far...")

        console.print(f"[cyan]Found {len(teams)} total teams (all teams mode)[/cyan]")
        console.print(f"[dim]Each team will use its cached last_scraped_at for incremental updates[/dim]")
    else:
        # Steady-state incremental mode: scrape teams not scraped in last 7 days
        teams = scraper._get_teams_to_scrape()
        console.print(f"[cyan]Incremental mode: Scraping teams not updated in last 7 days[/cyan]")
        console.print(f"[dim]Each team will use its cached last_scraped_at for incremental updates[/dim]")

    # Filter out teams outside supported U10-U18 range
    # Dynamically calculate based on current year
    current_year = datetime.now().year
    min_birth_year = current_year - 18  # oldest U18 player
    max_birth_year = current_year - 10  # youngest U10 player

    teams_before_filter = len(teams)
    filtered_teams = []
    skipped_count = 0

    for team in teams:
        age_group = team.get('age_group', '').upper().strip()
        birth_year = team.get('birth_year')

        # Skip if age_group is outside U10-U18 range
        age_match = re.match(r'U-?(\d+)', age_group)
        if age_match:
            age_num = int(age_match.group(1))
            if age_num < 10 or age_num > 18:
                logger.debug(f"Skipping U{age_num} team (age_group={age_group}): {team.get('team_name', 'Unknown')}")
                skipped_count += 1
                continue

        # Skip if birth_year is outside supported range
        if birth_year is not None and (birth_year < min_birth_year or birth_year > max_birth_year):
            logger.debug(f"Skipping team (birth_year={birth_year}, supported={min_birth_year}-{max_birth_year}): {team.get('team_name', 'Unknown')}")
            skipped_count += 1
            continue

        filtered_teams.append(team)
    
    teams = filtered_teams
    if skipped_count > 0:
        console.print(f"[yellow]Filtered out {skipped_count} teams outside U10-U18 range (birth_year {min_birth_year}-{max_birth_year})[/yellow]")
    
    # Apply skip and limit to teams list
    total_eligible = len(teams)
    if skip_teams > 0:
        teams = teams[skip_teams:]
        console.print(f"[cyan]Skipping first {skip_teams} teams[/cyan]")
    if limit_teams:
        teams = teams[:limit_teams]
        console.print(f"[cyan]Limiting to {limit_teams} teams[/cyan]")

    console.print(f"[bold cyan]Scraping games for {len(teams)} teams (of {total_eligible} eligible, {skipped_count} U8/U9/U19 filtered)[/bold cyan]")
    console.print(f"[cyan]Concurrency: {concurrency} teams at once[/cyan]")
    if since_date:
        console.print(f"[cyan]Using override since_date: {since_date}[/cyan]\n")
    elif not null_teams_only:
        console.print(f"[dim]Using per-team last_scraped_at for incremental scraping[/dim]\n")
    else:
        console.print()
    
    # OPTIMIZATION 1: Bulk fetch all scrape dates
    console.print("[dim]Fetching scrape dates for all teams...[/dim]")
    team_ids = [t.get('team_id_master') for t in teams if t.get('team_id_master')]
    scrape_dates_cache = _bulk_fetch_scrape_dates(supabase, provider_id, team_ids)
    console.print(f"[green]✓[/green] Loaded scrape dates for {len(scrape_dates_cache)} teams\n")
    
    # Set up output file for incremental saving
    if not output_file:
        output_file = f"data/raw/scraped_games_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Open file for incremental writing
    output_file_handle = open(output_path, 'w', encoding='utf-8')
    file_lock = threading.Lock()  # Thread-safe file access
    games_saved_count = 0
    errors = []
    log_buffer = []  # Batch logging buffer
    flush_counter = [0]  # Thread-safe counter for periodic flushing
    
    try:
        # OPTIMIZATION 2: Concurrent scraping with semaphore
        semaphore = Semaphore(concurrency)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task_id = progress.add_task("Scraping teams...", total=len(teams))
            
            # Create tasks for all teams
            tasks = [
                _scrape_team_concurrent(
                    semaphore, scraper, team, since_date, scrape_dates_cache,
                    file_lock, output_file_handle, log_buffer, flush_counter, progress, task_id
                )
                for team in teams
            ]
            
            # Execute all tasks concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for result in results:
                if isinstance(result, Exception):
                    errors.append(str(result))
                elif isinstance(result, tuple):
                    games_count, error = result
                    games_saved_count += games_count
                    if error:
                        errors.append(error)
        
        # OPTIMIZATION 3: Final flush and batch logging
        output_file_handle.flush()
        
        # Batch log all scrapes
        if log_buffer:
            console.print(f"\n[dim]Logging {len(log_buffer)} team scrapes...[/dim]")
            _bulk_log_team_scrapes(supabase, provider_id, log_buffer)
            console.print(f"[green]✓[/green] Batch logging complete\n")
        
    finally:
        # Always close the file
        output_file_handle.close()
    
    console.print(f"\n[bold green]✅ Scraping complete![/bold green]")
    console.print(f"  Games scraped: {games_saved_count:,}")
    console.print(f"  Teams processed: {len(teams)}")
    console.print(f"  Errors: {len(errors)}")
    console.print(f"  Output file: {output_path}")
    
    if errors:
        console.print(f"\n[yellow]Errors encountered:[/yellow]")
        for error in errors[:10]:
            console.print(f"  - {error}")
        if len(errors) > 10:
            console.print(f"  ... and {len(errors) - 10} more")
    
    # Auto-import if requested
    if auto_import and games_saved_count > 0:
        console.print(f"\n[bold cyan]🔄 Auto-importing games...[/bold cyan]")
        try:
            import_script = Path(__file__).parent / "import_games_enhanced.py"
            cmd = [
                sys.executable,
                str(import_script),
                str(output_path),
                provider,
                '--stream',
                '--batch-size', '1000'
            ]
            
            result = subprocess.run(cmd, capture_output=False, text=True)
            
            if result.returncode == 0:
                console.print(f"\n[bold green]✅ Auto-import complete![/bold green]")
            else:
                console.print(f"\n[yellow]⚠️  Auto-import completed with warnings (return code: {result.returncode})[/yellow]")
                console.print(f"[dim]You can manually import with:[/dim]")
                console.print(f"[dim]  python scripts/import_games_enhanced.py {output_path} {provider} --stream[/dim]")
        except Exception as e:
            console.print(f"\n[red]❌ Auto-import failed: {e}[/red]")
            console.print(f"[yellow]You can manually import with:[/yellow]")
            console.print(f"  python scripts/import_games_enhanced.py {output_path} {provider} --stream")
            logger.error(f"Auto-import error: {e}", exc_info=True)
    elif games_saved_count > 0:
        console.print(f"\n[green]Next step: Import games[/green]")
        console.print(f"  python scripts/import_games_enhanced.py {output_path} {provider} --stream")
    
    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description='Scrape games from GotSport')
    parser.add_argument('--provider', type=str, default='gotsport', help='Provider code')
    parser.add_argument('--output', type=str, default=None, help='Output file path (default: auto-generated)')
    parser.add_argument('--limit-teams', type=int, default=None, help='Limit number of teams to scrape (for testing)')
    parser.add_argument('--skip-teams', type=int, default=0, help='Skip first N teams (for splitting large scrapes)')
    parser.add_argument('--null-teams-only', action='store_true', help='Only scrape teams with NULL last_scraped_at')
    parser.add_argument('--include-recent', action='store_true', help='Include teams scraped within last 7 days (override default filter)')
    parser.add_argument('--since-date', type=str, default=None, help='Override since_date for scraping (YYYY-MM-DD format, used for NULL teams)')
    parser.add_argument('--auto-import', action='store_true', help='Automatically import scraped games after scraping completes')
    parser.add_argument('--concurrency', type=int, default=30, help='Number of concurrent scrapes (default: 30)')
    
    args = parser.parse_args()
    
    # Parse since_date if provided
    since_date_obj = None
    if args.since_date:
        try:
            since_date_obj = datetime.strptime(args.since_date, '%Y-%m-%d').date()
        except ValueError:
            console.print(f"[red]Error: Invalid date format '{args.since_date}'. Use YYYY-MM-DD format.[/red]")
            sys.exit(1)
    
    try:
        output_file = asyncio.run(scrape_games(
            provider=args.provider,
            output_file=args.output,
            limit_teams=args.limit_teams,
            skip_teams=args.skip_teams,
            null_teams_only=args.null_teams_only,
            include_recent=args.include_recent,
            since_date=since_date_obj,
            auto_import=args.auto_import,
            concurrency=args.concurrency
        ))
    except KeyboardInterrupt:
        console.print("\n[yellow]Scraping cancelled by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]Fatal error: {e}[/red]")
        logger.exception("Fatal error in scraper")
        sys.exit(1)


if __name__ == '__main__':
    main()

