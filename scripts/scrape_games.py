#!/usr/bin/env python3
"""
Scrape games from GotSport and save to file for import
OPTIMIZED: Concurrent scraping with async/await, bulk operations, batched logging
"""

import argparse
import asyncio
import json
import logging
import subprocess
import sys
import threading
from asyncio import Semaphore
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.append(str(Path(__file__).parent.parent))

import os

from dotenv import load_dotenv
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from src.etl.bulk_ops import bulk_update_last_scraped_at, call_rpc_with_fallback
from src.scrapers.gotsport import GotSportScraper, TeamNotFoundError
from supabase import create_client

console = Console()
load_dotenv()

# Load .env.local if it exists
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

if env_local.exists():
    logger.info("Loaded .env.local")
else:
    logger.info("Loaded .env")


def _is_placeholder_unknown_team(team: Dict) -> bool:
    """Return True for placeholder teams like unknown_3712624 that should not be scraped."""
    team_name = str(team.get("team_name") or "").strip()
    provider_team_id = str(team.get("provider_team_id") or "").strip()

    if not team_name or not provider_team_id:
        return False

    return team_name.lower() == f"unknown_{provider_team_id}".lower()


def _bulk_log_team_scrapes(supabase, provider_id: str, scrape_logs: List[Dict[str, Any]]):
    """OPTIMIZATION: Batch log team scrapes instead of individual calls"""
    if not scrape_logs:
        return

    now_iso = datetime.now().isoformat()

    log_entries: List[Dict[str, Any]] = []
    update_payload: List[Dict[str, Any]] = []

    for scrape_log in scrape_logs:
        team_id_master = scrape_log["team_id_master"]
        games_found = int(scrape_log.get("games_found", 0))
        status = str(scrape_log.get("status") or ("success" if games_found > 0 else "partial"))

        log_entries.append(
            {
                "team_id": team_id_master,
                "provider_id": provider_id,
                "scraped_at": now_iso,
                "games_found": games_found,
                "status": status,
            }
        )
        if scrape_log.get("update_last_scraped_at", True):
            update_payload.append({"team_id_master": team_id_master, "last_scraped_at": now_iso})

    # Batch insert scrape logs.
    log_insert_batch_size = 500
    inserted_count = 0
    for i in range(0, len(log_entries), log_insert_batch_size):
        batch = log_entries[i : i + log_insert_batch_size]
        try:
            supabase.table("team_scrape_log").insert(batch).execute()
            inserted_count += len(batch)
        except Exception as e:
            logger.warning(f"Error batch inserting scrape logs (batch {i // log_insert_batch_size + 1}): {e}")

    updated_count = bulk_update_last_scraped_at(supabase, update_payload)

    logger.info(f"Bulk logged {inserted_count} scrape logs and updated {updated_count} team timestamps")


def _legacy_paginated_team_fetch(
    supabase,
    provider_id: str,
    limit_teams: Optional[int],
    null_teams_only: bool,
    include_recent: bool,
) -> List[Dict]:
    """Fallback path for the `get_teams_to_scrape_limited` RPC.

    Preserves the pre-RPC paginated `.range()` loop verbatim for each of the
    three legacy branches. Only invoked when the RPC returns SQLSTATE 42883
    ("function does not exist"), i.e. the migration has not been applied yet.
    """
    teams: List[Dict] = []
    page_size = 1000
    offset = 0

    while True:
        query = supabase.table("teams").select("*").eq("provider_id", provider_id)
        if null_teams_only:
            query = query.is_("last_scraped_at", "null")
        # `include_recent` and the default `limit_teams` branch both fetch all
        # provider teams; priority ordering is applied in Python below.
        teams_result = query.range(offset, offset + page_size - 1).execute()

        if not teams_result.data:
            break

        teams.extend(teams_result.data)

        if len(teams_result.data) < page_size:
            break

        offset += page_size

    if not null_teams_only and not include_recent:
        # Steady-state / limit_teams path: sort by priority
        #   1. NULL last_scraped_at first (never scraped)
        #   2. Then oldest last_scraped_at ascending
        teams.sort(
            key=lambda t: (
                0 if t.get("last_scraped_at") is None else 1,
                t.get("last_scraped_at") or "",
            )
        )

    return teams


async def _scrape_team_concurrent(
    semaphore: Semaphore,
    scraper: GotSportScraper,
    team: Dict,
    since_date: Optional[date],
    scrape_dates_cache: Dict[str, Optional[datetime]],
    file_lock: threading.Lock,
    output_file_handle,
    log_buffer: List[Dict[str, Any]],
    flush_counter: List[int],  # Thread-safe counter for flush tracking
    progress: Progress,
    task_id,
) -> Tuple[int, Optional[str], bool]:
    """Scrape a single team (runs in thread pool for concurrency)"""
    async with semaphore:
        team_id = team.get("provider_team_id")
        team_name = team.get("team_name", "Unknown")
        team_master_id = team.get("team_id_master")

        try:
            # Determine since_date for this team
            if since_date:
                team_since_date = datetime.combine(since_date, datetime.min.time())
            else:
                # Use cached scrape date
                team_since_date = scrape_dates_cache.get(team_master_id)

            # Run synchronous scraper in thread pool (since requests is sync)
            game_data_list = await asyncio.to_thread(scraper.scrape_team_games, team_id, since_date=team_since_date)

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
                        output_file_handle.write(json.dumps(game) + "\n")

                # Increment flush counter (every team, not just those with games)
                flush_counter[0] += 1
                # Flush every 100 teams (reduced I/O, but still periodic)
                if flush_counter[0] % 100 == 0:
                    should_flush = True

                # Add to log buffer
                if team_master_id:
                    log_buffer.append(
                        {
                            "team_id_master": team_master_id,
                            "games_found": len(game_data_list),
                            "status": "success" if game_data_list else "partial",
                            "update_last_scraped_at": True,
                        }
                    )

            # Flush outside lock to avoid blocking other threads
            if should_flush:
                with file_lock:
                    output_file_handle.flush()

            progress.update(task_id, advance=1)
            return games_count, None, False

        except TeamNotFoundError as e:
            logger.warning(
                "Skipping team %s (%s): %s. The provider_team_id appears stale or is a placeholder unknown team.",
                team_id,
                team_name,
                e,
            )

            with file_lock:
                if team_master_id:
                    log_buffer.append(
                        {
                            "team_id_master": team_master_id,
                            "games_found": 0,
                            "status": "error",
                            "update_last_scraped_at": True,
                        }
                    )

            progress.update(task_id, advance=1)
            return 0, None, True

        except Exception as e:
            error_msg = f"Team {team_id} ({team_name}): {str(e)}"
            logger.error(error_msg, exc_info=True)
            progress.update(task_id, advance=1)
            return 0, error_msg, False


async def scrape_games(
    provider: str = "gotsport",
    output_file: str = None,
    limit_teams: int = None,
    skip_teams: int = 0,
    null_teams_only: bool = False,
    include_recent: bool = False,
    since_date: date = None,
    auto_import: bool = False,
    concurrency: int = 30,
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
    supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

    # Initialize scraper
    scraper = GotSportScraper(supabase, provider)
    provider_id = scraper._get_provider_id()

    # Get teams to scrape via get_teams_to_scrape_limited RPC (SQL-side filter,
    # priority order, and shard-by-hash). The three legacy modes (null_teams_only,
    # include_recent, limit_teams) collapse into a single call.
    shard_index = int(os.getenv("SCRAPE_SHARD_INDEX", "0"))
    shard_count = int(os.getenv("SCRAPE_SHARD_COUNT", "1"))
    rpc_params = {
        "p_provider_id": provider_id,
        "p_limit": limit_teams if limit_teams else None,
        "p_shard_index": shard_index,
        "p_shard_count": shard_count,
        "p_include_recent": bool(include_recent),
        "p_null_only": bool(null_teams_only),
    }

    if null_teams_only:
        console.print("[cyan]Fetching teams with NULL last_scraped_at (RPC)...[/cyan]")
    elif include_recent:
        console.print("[cyan]Fetching ALL teams (including recently scraped) (RPC)...[/cyan]")
    elif limit_teams:
        console.print(f"[cyan]Fetching top {limit_teams} teams by scrape priority (RPC)...[/cyan]")
    else:
        console.print("[cyan]Incremental mode: Scraping teams not updated in last 7 days (RPC)...[/cyan]")

    if shard_count > 1:
        console.print(f"[dim]Shard {shard_index} of {shard_count} (hash-partitioned by team_id_master)[/dim]")

    teams = (
        call_rpc_with_fallback(
            supabase,
            "get_teams_to_scrape_limited",
            rpc_params,
            fallback=lambda: _legacy_paginated_team_fetch(
                supabase, provider_id, limit_teams, null_teams_only, include_recent
            ),
            log_msg="PERF REGRESSION: Falling back to paginated team fetch: %s",
        )
        or []
    )

    console.print(f"[cyan]Found {len(teams)} teams[/cyan]")
    if not null_teams_only:
        console.print("[dim]Each team will use its cached last_scraped_at for incremental updates[/dim]")

    # Filter out U8/U9 and U20+ teams (PitchRank supports U10-U19)
    len(teams)
    filtered_teams = []
    skipped_count = 0
    placeholder_unknown_count = 0

    for team in teams:
        if _is_placeholder_unknown_team(team):
            logger.debug(f"Skipping placeholder unknown team: {team.get('team_name', 'Unknown')}")
            placeholder_unknown_count += 1
            continue

        age_group = team.get("age_group", "").upper().strip()
        birth_year = team.get("birth_year")

        # Skip if age_group matches U8/U9 patterns
        if age_group in ["U8", "U-8", "U9", "U-9"]:
            logger.debug(f"Skipping U8/U9 team (age_group={age_group}): {team.get('team_name', 'Unknown')}")
            skipped_count += 1
            continue

        # Skip if birth_year is 2017, 2018, 2019 (U8/U9) or 2005, 2006 (U20+)
        if birth_year in [2005, 2006, 2017, 2018, 2019]:
            logger.debug(f"Skipping out-of-range team (birth_year={birth_year}): {team.get('team_name', 'Unknown')}")
            skipped_count += 1
            continue

        filtered_teams.append(team)

    teams = filtered_teams
    if placeholder_unknown_count > 0:
        console.print(f"[yellow]Filtered out {placeholder_unknown_count} placeholder unknown teams[/yellow]")
    if skipped_count > 0:
        console.print(f"[yellow]Filtered out {skipped_count} out-of-range teams (PitchRank is U10-U19 only)[/yellow]")

    # Apply skip and limit to teams list
    total_eligible = len(teams)
    if skip_teams > 0:
        teams = teams[skip_teams:]
        console.print(f"[cyan]Skipping first {skip_teams} teams[/cyan]")
    if limit_teams:
        teams = teams[:limit_teams]
        console.print(f"[cyan]Limiting to {limit_teams} teams[/cyan]")

    console.print(
        f"[bold cyan]Scraping games for {len(teams)} teams (of {total_eligible} eligible after filtering)[/bold cyan]"
    )
    console.print(f"[cyan]Concurrency: {concurrency} teams at once[/cyan]")
    if since_date:
        console.print(f"[cyan]Using override since_date: {since_date}[/cyan]\n")
    elif not null_teams_only:
        console.print("[dim]Using per-team last_scraped_at for incremental scraping[/dim]\n")
    else:
        console.print()

    # The team fetch already returned `last_scraped_at` on every row, so the
    # scrape-date cache is built in-memory — no extra round-trips.
    scrape_dates_cache: Dict[str, Optional[datetime]] = {}
    for t in teams:
        tid = t.get("team_id_master")
        if not tid:
            continue
        last_scraped = t.get("last_scraped_at")
        if last_scraped:
            try:
                scrape_dates_cache[tid] = datetime.fromisoformat(last_scraped.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                scrape_dates_cache[tid] = None
        else:
            scrape_dates_cache[tid] = None
    console.print(f"[green]✓[/green] Scrape-date cache built for {len(scrape_dates_cache)} teams\n")

    # Set up output file for incremental saving
    if not output_file:
        output_file = f"data/raw/scraped_games_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Open file for incremental writing
    output_file_handle = open(output_path, "w", encoding="utf-8")
    file_lock = threading.Lock()  # Thread-safe file access
    games_saved_count = 0
    not_found_count = 0
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
            console=console,
        ) as progress:
            task_id = progress.add_task("Scraping teams...", total=len(teams))

            # Create tasks for all teams
            tasks = [
                _scrape_team_concurrent(
                    semaphore,
                    scraper,
                    team,
                    since_date,
                    scrape_dates_cache,
                    file_lock,
                    output_file_handle,
                    log_buffer,
                    flush_counter,
                    progress,
                    task_id,
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
                    games_count, error, team_not_found = result
                    games_saved_count += games_count
                    if team_not_found:
                        not_found_count += 1
                    if error:
                        errors.append(error)

        # OPTIMIZATION 3: Final flush and batch logging
        output_file_handle.flush()

        # Batch log all scrapes
        if log_buffer:
            console.print(f"\n[dim]Logging {len(log_buffer)} team scrapes...[/dim]")
            _bulk_log_team_scrapes(supabase, provider_id, log_buffer)
            console.print("[green]✓[/green] Batch logging complete\n")

    finally:
        # Always close the file
        output_file_handle.close()

    console.print("\n[bold green]✅ Scraping complete![/bold green]")
    console.print(f"  Games scraped: {games_saved_count:,}")
    console.print(f"  Teams processed: {len(teams)}")
    if not_found_count > 0:
        console.print(f"  Missing provider teams skipped: {not_found_count}")
    console.print(f"  Errors: {len(errors)}")
    console.print(f"  Output file: {output_path}")

    if errors:
        console.print("\n[yellow]Errors encountered:[/yellow]")
        for error in errors[:10]:
            console.print(f"  - {error}")
        if len(errors) > 10:
            console.print(f"  ... and {len(errors) - 10} more")

    # Auto-import if requested
    if auto_import and games_saved_count > 0:
        console.print("\n[bold cyan]🔄 Auto-importing games...[/bold cyan]")
        try:
            import_script = Path(__file__).parent / "import_games_enhanced.py"
            cmd = [sys.executable, str(import_script), str(output_path), provider, "--stream", "--batch-size", "1000"]

            result = subprocess.run(cmd, capture_output=False, text=True)

            if result.returncode == 0:
                console.print("\n[bold green]✅ Auto-import complete![/bold green]")
            else:
                console.print(
                    f"\n[yellow]⚠️  Auto-import completed with warnings (return code: {result.returncode})[/yellow]"
                )
                console.print("[dim]You can manually import with:[/dim]")
                console.print(f"[dim]  python scripts/import_games_enhanced.py {output_path} {provider} --stream[/dim]")
        except Exception as e:
            console.print(f"\n[red]❌ Auto-import failed: {e}[/red]")
            console.print("[yellow]You can manually import with:[/yellow]")
            console.print(f"  python scripts/import_games_enhanced.py {output_path} {provider} --stream")
            logger.error(f"Auto-import error: {e}", exc_info=True)
    elif games_saved_count > 0:
        console.print("\n[green]Next step: Import games[/green]")
        console.print(f"  python scripts/import_games_enhanced.py {output_path} {provider} --stream")

    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description="Scrape games from GotSport")
    parser.add_argument("--provider", type=str, default="gotsport", help="Provider code")
    parser.add_argument("--output", type=str, default=None, help="Output file path (default: auto-generated)")
    parser.add_argument("--limit-teams", type=int, default=None, help="Limit number of teams to scrape (for testing)")
    parser.add_argument("--skip-teams", type=int, default=0, help="Skip first N teams (for splitting large scrapes)")
    parser.add_argument("--null-teams-only", action="store_true", help="Only scrape teams with NULL last_scraped_at")
    parser.add_argument(
        "--include-recent",
        action="store_true",
        help="Include teams scraped within last 7 days (override default filter)",
    )
    parser.add_argument(
        "--since-date",
        type=str,
        default=None,
        help="Override since_date for scraping (YYYY-MM-DD format, used for NULL teams)",
    )
    parser.add_argument(
        "--auto-import", action="store_true", help="Automatically import scraped games after scraping completes"
    )
    parser.add_argument("--concurrency", type=int, default=30, help="Number of concurrent scrapes (default: 30)")

    args = parser.parse_args()

    # Parse since_date if provided
    since_date_obj = None
    if args.since_date:
        try:
            since_date_obj = datetime.strptime(args.since_date, "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error: Invalid date format '{args.since_date}'. Use YYYY-MM-DD format.[/red]")
            sys.exit(1)

    try:
        asyncio.run(
            scrape_games(
                provider=args.provider,
                output_file=args.output,
                limit_teams=args.limit_teams,
                skip_teams=args.skip_teams,
                null_teams_only=args.null_teams_only,
                include_recent=args.include_recent,
                since_date=since_date_obj,
                auto_import=args.auto_import,
                concurrency=args.concurrency,
            )
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Scraping cancelled by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]Fatal error: {e}[/red]")
        logger.exception("Fatal error in scraper")
        sys.exit(1)


if __name__ == "__main__":
    main()
