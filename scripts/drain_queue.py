#!/usr/bin/env python3
"""
Drain the scrape_requests queue using concurrent scraping.

Clone of scrape_games.py with one difference: instead of fetching teams from
the teams table (via get_teams_to_scrape_limited RPC), it claims pending
items from the scrape_requests queue and scrapes those.

Completely independent of process_missing_games.py and scrape_games.py.
Safe to run in parallel with both — the claim_queue_items RPC uses
FOR UPDATE SKIP LOCKED to prevent double-processing.

Usage:
    python scripts/drain_queue.py --limit 2000 --concurrency 30
    python scripts/drain_queue.py --limit 500 --concurrency 8   # with ZenRows
    python scripts/drain_queue.py --dry-run --limit 100
"""

import argparse
import asyncio
import json
import logging
import subprocess
import sys
import threading
from asyncio import Semaphore
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.append(str(Path(__file__).parent.parent))

import os

from dotenv import load_dotenv
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from src.etl.bulk_ops import bulk_update_last_scraped_at
from src.scrapers.gotsport import GotSportScraper, TeamNotFoundError, WAFBlockedError, get_waf_breaker
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


# ---------------------------------------------------------------------------
# Helpers (cloned from scrape_games.py)
# ---------------------------------------------------------------------------

def _is_placeholder_unknown_team(team: Dict) -> bool:
    """Return True for placeholder teams like unknown_3712624 that should not be scraped."""
    team_name = str(team.get("team_name") or "").strip()
    provider_team_id = str(team.get("provider_team_id") or "").strip()

    if not team_name or not provider_team_id:
        return False

    return team_name.lower() == f"unknown_{provider_team_id}".lower()


def _bulk_log_team_scrapes(supabase, provider_id: str, scrape_logs: List[Dict[str, Any]]):
    """Batch log team scrapes instead of individual calls"""
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


# ---------------------------------------------------------------------------
# Queue operations (the only part that differs from scrape_games.py)
# ---------------------------------------------------------------------------

def _claim_queue_items(supabase, provider_id: str, limit: int) -> List[Dict]:
    """Atomically claim pending scrape_requests via RPC.

    Falls back to a non-atomic fetch+update when the RPC migration hasn't
    been applied yet.
    """
    try:
        result = supabase.rpc("claim_queue_items", {
            "p_provider_id": provider_id,
            "p_limit": limit,
        }).execute()
        return result.data or []
    except Exception as e:
        logger.warning(f"claim_queue_items RPC failed ({e}), using fallback")
        return _claim_queue_fallback(supabase, provider_id, limit)


def _claim_queue_fallback(supabase, provider_id: str, limit: int) -> List[Dict]:
    """Non-atomic fallback when the claim_queue_items RPC isn't deployed yet."""
    result = (
        supabase.table("scrape_requests")
        .select("id, team_id_master, team_name, provider_id, provider_team_id, game_date, priority, request_type")
        .eq("status", "pending")
        .eq("provider_id", provider_id)
        .order("priority")
        .order("requested_at")
        .limit(limit)
        .execute()
    )
    items = result.data or []
    if not items:
        return []

    ids = [item["id"] for item in items]
    now_iso = datetime.now().isoformat()
    for i in range(0, len(ids), 100):
        batch = ids[i : i + 100]
        try:
            (
                supabase.table("scrape_requests")
                .update({"status": "processing", "processed_at": now_iso})
                .in_("id", batch)
                .eq("status", "pending")
                .execute()
            )
        except Exception as e:
            logger.warning(f"Failed to mark batch as processing: {e}")

    return items


def _fetch_team_metadata(supabase, team_id_masters: List[str]) -> Dict[str, Dict]:
    """Fetch age_group, birth_year, last_scraped_at from teams table."""
    meta: Dict[str, Dict] = {}
    batch_size = 200
    for i in range(0, len(team_id_masters), batch_size):
        batch = team_id_masters[i : i + batch_size]
        r = (
            supabase.table("teams")
            .select("team_id_master, age_group, birth_year, last_scraped_at")
            .in_("team_id_master", batch)
            .execute()
        )
        for t in r.data or []:
            meta[t["team_id_master"]] = t
    return meta


def _finalize_queue_items(supabase, queue_map: Dict[str, str], log_buffer: List[Dict[str, Any]]):
    """Mark claimed queue items as completed or failed based on scrape results."""
    if not queue_map:
        return

    log_index = {e["team_id_master"]: e for e in log_buffer}
    now_iso = datetime.now().isoformat()

    completed_count = 0
    failed_ids = []

    for team_id_master, request_id in queue_map.items():
        entry = log_index.get(team_id_master)

        if entry and entry.get("status") == "error":
            failed_ids.append(request_id)
        else:
            games_found = entry.get("games_found", 0) if entry else 0
            try:
                (
                    supabase.table("scrape_requests")
                    .update({"status": "completed", "completed_at": now_iso, "games_found": games_found})
                    .eq("id", request_id)
                    .execute()
                )
                completed_count += 1
            except Exception as e:
                logger.warning(f"Failed to complete queue item {request_id}: {e}")

    if failed_ids:
        try:
            (
                supabase.table("scrape_requests")
                .update({
                    "status": "failed",
                    "completed_at": now_iso,
                    "error_message": "Team not found or scrape error",
                })
                .in_("id", failed_ids)
                .execute()
            )
        except Exception as e:
            logger.warning(f"Failed to mark {len(failed_ids)} queue items as failed: {e}")

    console.print(
        f"[green]✓[/green] Queue finalized: {completed_count} completed, {len(failed_ids)} failed"
    )


# ---------------------------------------------------------------------------
# Concurrent scraping (cloned from scrape_games.py — identical)
# ---------------------------------------------------------------------------

async def _scrape_team_concurrent(
    semaphore: Semaphore,
    scraper: GotSportScraper,
    team: Dict,
    since_date,
    scrape_dates_cache: Dict[str, Optional[datetime]],
    file_lock: threading.Lock,
    output_file_handle,
    log_buffer: List[Dict[str, Any]],
    flush_counter: List[int],
    progress: Progress,
    task_id,
) -> Tuple[int, Optional[str], bool]:
    """Scrape a single team (runs in thread pool for concurrency)"""
    async with semaphore:
        await get_waf_breaker().wait_if_open_async()

        team_id = team.get("provider_team_id")
        team_name = team.get("team_name", "Unknown")
        team_master_id = team.get("team_id_master")

        try:
            # Determine since_date for this team
            if since_date:
                team_since_date = datetime.combine(since_date, datetime.min.time())
            else:
                team_since_date = scrape_dates_cache.get(team_master_id)

            game_data_list = await asyncio.to_thread(scraper.scrape_team_games, team_id, since_date=team_since_date)

            games = []
            for game_data in game_data_list:
                game_dict = scraper._game_data_to_dict(game_data, team_id)
                if game_dict:
                    games.append(game_dict)

            games_count = len(games)
            should_flush = False

            with file_lock:
                if games_count > 0:
                    for game in games:
                        output_file_handle.write(json.dumps(game) + "\n")

                flush_counter[0] += 1
                if flush_counter[0] % 100 == 0:
                    should_flush = True

                if team_master_id:
                    log_buffer.append(
                        {
                            "team_id_master": team_master_id,
                            "games_found": len(game_data_list),
                            "status": "success" if game_data_list else "partial",
                            "update_last_scraped_at": True,
                        }
                    )

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

        except WAFBlockedError:
            logger.error(
                "gotsport waf-blocked, aborting run: trip_count=%d team=%s (%s)",
                get_waf_breaker().trip_count,
                team_id,
                team_name,
            )
            with file_lock:
                if team_master_id:
                    log_buffer.append(
                        {
                            "team_id_master": team_master_id,
                            "games_found": 0,
                            "status": "error",
                            "update_last_scraped_at": False,
                        }
                    )
            progress.update(task_id, advance=1)
            raise

        except Exception as e:
            error_msg = f"Team {team_id} ({team_name}): {str(e)}"
            logger.error(error_msg, exc_info=True)
            with file_lock:
                if team_master_id:
                    log_buffer.append(
                        {
                            "team_id_master": team_master_id,
                            "games_found": 0,
                            "status": "error",
                            "update_last_scraped_at": False,
                        }
                    )
            progress.update(task_id, advance=1)
            return 0, error_msg, False


# ---------------------------------------------------------------------------
# Main drain logic (mirrors scrape_games() but sources teams from queue)
# ---------------------------------------------------------------------------

async def drain_queue(
    limit: int = 2000,
    concurrency: int = 30,
    dry_run: bool = False,
    output_file: str = None,
):
    """
    Drain the scrape_requests queue using concurrent scraping.

    Clone of scrape_games() with one change: teams come from the
    scrape_requests queue instead of the teams table RPC.
    """
    if concurrency < 1:
        console.print("[red]--concurrency must be at least 1[/red]")
        sys.exit(1)

    get_waf_breaker().bind_loop(asyncio.get_running_loop())

    supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

    # Initialize scraper
    provider = "gotsport"
    scraper = GotSportScraper(supabase, provider)
    provider_id = scraper._get_provider_id()

    # ---- DIFFERENT FROM scrape_games.py: claim from queue ----
    console.print(f"[cyan]Claiming up to {limit} pending queue items...[/cyan]")
    claimed = _claim_queue_items(supabase, provider_id, limit)

    if not claimed:
        console.print("[green]Queue is empty — nothing to drain.[/green]")
        return

    console.print(f"[cyan]Claimed {len(claimed)} items from scrape_requests queue[/cyan]")

    # Build queue_map (team_id_master -> request_id) for finalization
    queue_map: Dict[str, str] = {}
    team_id_masters: List[str] = []
    for item in claimed:
        tid = item["team_id_master"]
        queue_map[tid] = item["id"]
        if tid not in team_id_masters:
            team_id_masters.append(tid)

    # Fetch team metadata (age_group, birth_year, last_scraped_at)
    console.print("[dim]Fetching team metadata...[/dim]")
    team_meta = _fetch_team_metadata(supabase, team_id_masters)

    # Build team dicts (same shape as scrape_games.py expects)
    teams: List[Dict] = []
    for item in claimed:
        tid = item["team_id_master"]
        meta = team_meta.get(tid, {})
        teams.append(
            {
                "team_id_master": tid,
                "team_name": item.get("team_name"),
                "provider_id": item.get("provider_id"),
                "provider_team_id": item.get("provider_team_id"),
                "age_group": meta.get("age_group"),
                "birth_year": meta.get("birth_year"),
                "last_scraped_at": meta.get("last_scraped_at"),
            }
        )

    if dry_run:
        console.print(f"\n[yellow][DRY RUN] Would scrape {len(teams)} teams:[/yellow]")
        for t in teams[:20]:
            console.print(f"  {t['provider_team_id']} — {t['team_name']}")
        if len(teams) > 20:
            console.print(f"  ... and {len(teams) - 20} more")
        # Release claimed items back to pending
        ids = list(queue_map.values())
        for i in range(0, len(ids), 100):
            batch = ids[i : i + 100]
            try:
                (
                    supabase.table("scrape_requests")
                    .update({"status": "pending", "processed_at": None})
                    .in_("id", batch)
                    .execute()
                )
            except Exception:
                pass
        console.print("[yellow]Released claimed items back to pending[/yellow]")
        return

    # ---- FROM HERE: identical to scrape_games.py ----

    # Filter out U8/U9 and U20+ teams (PitchRank supports U10-U19)
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

        if age_group in ["U8", "U-8", "U9", "U-9"]:
            logger.debug(f"Skipping U8/U9 team (age_group={age_group}): {team.get('team_name', 'Unknown')}")
            skipped_count += 1
            continue

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

    console.print(
        f"[bold cyan]Scraping games for {len(teams)} teams[/bold cyan]"
    )
    console.print(f"[cyan]Concurrency: {concurrency} teams at once[/cyan]")
    console.print("[dim]Using per-team last_scraped_at for incremental scraping[/dim]\n")

    # Build scrape-date cache from team metadata
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
        output_file = f"data/raw/scraped_games_{datetime.now().strftime('%Y%m%d_%H%M%S')}_drain.jsonl"

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Open file for incremental writing
    output_file_handle = open(output_path, "w", encoding="utf-8")
    file_lock = threading.Lock()
    games_saved_count = 0
    not_found_count = 0
    errors = []
    log_buffer = []
    flush_counter = [0]

    try:
        semaphore = Semaphore(concurrency)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("Draining queue...", total=len(teams))

            tasks = [
                _scrape_team_concurrent(
                    semaphore,
                    scraper,
                    team,
                    None,  # no global since_date override — use per-team cache
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

            results = await asyncio.gather(*tasks, return_exceptions=True)

            waf_aborts = [r for r in results if isinstance(r, WAFBlockedError)]

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

        output_file_handle.flush()

        # Batch log all scrapes
        if log_buffer:
            console.print(f"\n[dim]Logging {len(log_buffer)} team scrapes...[/dim]")
            _bulk_log_team_scrapes(supabase, provider_id, log_buffer)
            console.print("[green]✓[/green] Batch logging complete\n")

    finally:
        output_file_handle.close()

    waf_trip_count = get_waf_breaker().trip_count
    console.print("\n[bold green]✅ Scraping complete![/bold green]")
    console.print(f"  Games scraped: {games_saved_count:,}")
    console.print(f"  Teams processed: {len(teams)}")
    if not_found_count > 0:
        console.print(f"  Missing provider teams skipped: {not_found_count}")
    console.print(f"  Errors: {len(errors)}")
    if waf_trip_count > 0:
        console.print(f"  [yellow]CloudFront WAF trips: {waf_trip_count}[/yellow]")
    console.print(f"  Output file: {output_path}")

    if errors:
        console.print("\n[yellow]Errors encountered:[/yellow]")
        for error in errors[:10]:
            console.print(f"  - {error}")
        if len(errors) > 10:
            console.print(f"  ... and {len(errors) - 10} more")

    # Auto-import
    if games_saved_count > 0:
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

    # ---- DIFFERENT FROM scrape_games.py: finalize queue items ----
    console.print("\n[dim]Finalizing queue items...[/dim]")
    _finalize_queue_items(supabase, queue_map, log_buffer)

    # WAF abort — exit after import + finalize so partial work is preserved
    if waf_aborts:
        completed_results = sum(1 for r in results if isinstance(r, tuple))
        logger.error(
            "aborting: gotsport CloudFront WAF tripped %d times this run; teams_completed=%d, teams_remaining=%d",
            waf_trip_count,
            completed_results,
            len(teams) - completed_results,
        )
        sys.exit(2)

    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description="Drain the scrape_requests queue with concurrent scraping")
    parser.add_argument(
        "--limit", type=int, default=2000,
        help="Max queue items to claim and scrape (default: 2000)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=30,
        help="Number of concurrent scrapes (default: 30; use 8 with ZenRows)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output file path (default: auto-generated)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Claim + show targets, then release back to pending",
    )

    args = parser.parse_args()

    try:
        asyncio.run(
            drain_queue(
                limit=args.limit,
                concurrency=args.concurrency,
                dry_run=args.dry_run,
                output_file=args.output,
            )
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Scraping cancelled by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]Fatal error: {e}[/red]")
        logger.exception("Fatal error in drain_queue")
        sys.exit(1)


if __name__ == "__main__":
    main()
