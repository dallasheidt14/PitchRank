#!/usr/bin/env python3
"""
Process Missing Games Requests

This script processes user-initiated scrape requests from the scrape_requests table.
It queries for pending requests, scrapes the requested games, and imports them.

Usage:
    python scripts/process_missing_games.py [--limit 10] [--dry-run] [--continuous] [--interval 30]
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from supabase import Client, create_client

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.etl.bulk_ops import bulk_update_last_scraped_at
from src.scrapers.gotsport import GotSportScraper, TeamNotFoundError, WAFBlockedError

# Load environment variables
load_dotenv()

# Load .env.local if it exists
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class MissingGamesProcessor:
    """Process missing game scrape requests"""

    def __init__(self, supabase_client: Client, dry_run: bool = False):
        self.supabase = supabase_client
        self.dry_run = dry_run

        # Initialize scrapers for different providers
        self.scrapers = {
            "gotsport": GotSportScraper(supabase_client, "gotsport"),
            # Add other scrapers as needed
        }

        # Games are buffered here and imported once per batch by
        # _flush_pending_imports; each import_games call is a subprocess spawn.
        self._pending_imports: List[tuple] = []

        # Scrape attempts are buffered here and written once by
        # _flush_scrape_log, rather than costing two round-trips per request
        # on a path that runs every 15 minutes.
        self._scrape_log_buffer: List[Dict[str, Any]] = []

        self.reset_stats()

    def reset_stats(self) -> None:
        """Single source for the counter set.

        Continuous mode re-initialises stats between polls; a counter missing from
        that reset raises KeyError on the next summary instead of finishing the poll.
        """
        self.stats = {
            "processed": 0,
            "successful": 0,
            "failed": 0,
            "games_found": 0,
            "games_imported": 0,
            "waf_aborted": 0,
        }

    def get_pending_requests(self, limit: int = 40) -> List[Dict]:
        """Fetch pending scrape requests from database, ordered by priority then age."""
        try:
            result = (
                self.supabase.table("scrape_requests")
                .select("*")
                .eq("status", "pending")
                .order("priority", desc=False)
                .order("requested_at", desc=False)
                .limit(limit)
                .execute()
            )

            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error fetching pending requests: {e}")
            return []

    def update_request_status(self, request_id: str, status: str, **kwargs):
        """Update scrape request status in database"""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would update request {request_id} to status: {status}")
            return

        try:
            update_data = {"status": status}

            # Add timestamps based on status
            if status == "processing":
                update_data["processed_at"] = datetime.now().isoformat()
            elif status in ["completed", "failed"]:
                update_data["completed_at"] = datetime.now().isoformat()

            # Add any additional fields
            update_data.update(kwargs)

            self.supabase.table("scrape_requests").update(update_data).eq("id", request_id).execute()

            logger.info(f"Updated request {request_id} to status: {status}")
        except Exception as e:
            logger.error(f"Error updating request {request_id}: {e}")

    def get_provider_code(self, provider_id: str) -> Optional[str]:
        """Get provider code from provider ID"""
        try:
            result = self.supabase.table("providers").select("code").eq("id", provider_id).single().execute()

            return result.data["code"] if result.data else "gotsport"
        except Exception as e:
            logger.warning(f"Error fetching provider code for {provider_id}: {e}")
            return "gotsport"  # Default to gotsport

    def get_gotsport_alias(self, team_id_master: str, exclude_team_ids: Optional[List[str]] = None) -> Optional[Dict]:
        """
        Find a GotSport alias for a team via team_alias_map.

        This is used when the canonical provider isn't scrapable (e.g., Modular11)
        but the team has a GotSport alias that can be scraped.

        Args:
            team_id_master: The master team ID to look up aliases for
            exclude_team_ids: List of provider_team_ids to exclude (e.g., ones that already 404'd)

        Returns:
            Dict with 'provider_id' and 'provider_team_id' if found, None otherwise
        """
        try:
            # Get the GotSport provider ID
            gotsport_result = self.supabase.table("providers").select("id").eq("code", "gotsport").single().execute()

            if not gotsport_result.data:
                logger.warning("Could not find GotSport provider")
                return None

            gotsport_provider_id = gotsport_result.data["id"]

            # Check team_alias_map for a GotSport alias
            alias_result = (
                self.supabase.table("team_alias_map")
                .select("provider_id, provider_team_id")
                .eq("team_id_master", team_id_master)
                .eq("provider_id", gotsport_provider_id)
                .eq("review_status", "approved")
                .execute()
            )

            if alias_result.data:
                for alias in alias_result.data:
                    # Skip team IDs we already know are invalid
                    if exclude_team_ids and str(alias["provider_team_id"]) in exclude_team_ids:
                        logger.debug(f"Skipping excluded alias {alias['provider_team_id']}")
                        continue
                    logger.info(f"Found GotSport alias for team {team_id_master}: {alias['provider_team_id']}")
                    return {"provider_id": alias["provider_id"], "provider_team_id": alias["provider_team_id"]}

            return None
        except Exception as e:
            logger.warning(f"Error finding GotSport alias for team {team_id_master}: {e}")
            return None

    def scrape_games_for_date(self, provider_code: str, team_id: str, game_date: str) -> List[Dict]:
        """Scrape games for a specific team within a 181-day window (±90 days from selected date)"""
        scraper = self.scrapers.get(provider_code)
        if not scraper:
            raise ValueError(f"No scraper available for provider: {provider_code}")

        # Parse the target date
        target_date = datetime.strptime(game_date, "%Y-%m-%d").date()

        # Define the 181-day window: 90 days before, target date, 90 days after
        date_window_start = target_date - timedelta(days=90)
        date_window_end = target_date + timedelta(days=90)

        # Scrape with a date range starting 90 days before (to catch timezone issues)
        # The scraper uses since_date, so we'll scrape from 90 days before and filter
        start_date = datetime.combine(date_window_start, datetime.min.time())

        logger.info(
            f"Scraping games for team {team_id} in 181-day window: "
            f"{date_window_start} to {date_window_end} (selected date: {game_date})"
        )

        try:
            # Use the scraper's method to get games (only takes since_date, not until_date)
            games = scraper.scrape_team_games(team_id, since_date=start_date)

            # Filter to games within the 181-day window
            filtered_games = []
            for game in games:
                # GameData.game_date is a string in 'YYYY-MM-DD' format
                # IMPORTANT: Preserve the exact date string from scraper to avoid timezone issues
                try:
                    # Parse date for comparison only (don't modify the original string)
                    game_dt = datetime.strptime(game.game_date, "%Y-%m-%d").date()

                    # Include games within the 181-day window
                    if date_window_start <= game_dt <= date_window_end:
                        # Use the EXACT game_date string from the scraper (no manipulation)
                        # This ensures timezone issues don't cause date shifts
                        original_game_date = game.game_date

                        # Verify the date string format
                        if not isinstance(original_game_date, str) or len(original_game_date) != 10:
                            logger.warning(
                                f"Unexpected game_date format: {original_game_date}, type: {type(original_game_date)}"
                            )

                        # Convert GameData to dict format for import
                        game_dict = {
                            "provider": provider_code,
                            "team_id": str(game.team_id),
                            "team_id_source": str(game.team_id),
                            "opponent_id": str(game.opponent_id) if game.opponent_id else "",
                            "opponent_id_source": str(game.opponent_id) if game.opponent_id else "",
                            "team_name": game.team_name or "",
                            "opponent_name": game.opponent_name or "",
                            "game_date": original_game_date,  # Use exact string from scraper
                            "home_away": game.home_away or "",
                            "goals_for": game.goals_for,
                            "goals_against": game.goals_against,
                            "result": game.result if game.result in ("W", "L", "D") else None,
                            "competition": game.competition or "",
                            "venue": game.venue or "",
                            "source_url": game.meta.get("source_url", "") if game.meta else "",
                            "scraped_at": datetime.now().isoformat(),
                        }
                        filtered_games.append(game_dict)
                        logger.info(f"Including game on {original_game_date} (within window, parsed as {game_dt})")
                    else:
                        logger.debug(
                            f"Skipping game on {game.game_date} (outside window: "
                            f"{game_dt} not in {date_window_start} to {date_window_end})"
                        )
                except (ValueError, AttributeError) as e:
                    logger.warning(
                        f"Error parsing game date for game: {e}, "
                        f"game_date value: {getattr(game, 'game_date', 'MISSING')}"
                    )
                    continue

            logger.info(
                f"Found {len(filtered_games)} games in 181-day window ({date_window_start} to {date_window_end})"
            )
            if filtered_games:
                game_dates = sorted(set(g["game_date"] for g in filtered_games))
                logger.info(f"Game dates found: {', '.join(game_dates)}")

            return filtered_games

        except Exception as e:
            logger.error(f"Error scraping games: {e}")
            raise

    def save_games_to_temp_file(self, games: List[Dict]) -> Optional[str]:
        """Save games to temporary JSONL file for import"""
        if not games:
            return None

        # Log the exact dates being saved (for debugging date issues)
        game_dates_in_file = [g.get("game_date", "MISSING") for g in games]
        logger.info(f"Saving {len(games)} games with dates: {', '.join(sorted(set(game_dates_in_file)))}")

        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")

        try:
            # Write games as JSONL (one JSON object per line)
            for idx, game in enumerate(games):
                # Verify game_date before writing
                game_date = game.get("game_date", "")
                if not game_date or len(game_date) != 10:
                    logger.warning(f"Game {idx} has invalid game_date format: {game_date}")

                json.dump(game, temp_file, ensure_ascii=False)
                temp_file.write("\n")

            temp_file.flush()
            temp_file.close()

            logger.info(f"Saved {len(games)} games to {temp_file.name}")
            return temp_file.name
        except Exception:
            temp_file.close()
            # Clean up on error
            try:
                os.unlink(temp_file.name)
            except Exception:
                pass
            raise

    def import_games(self, games: List[Dict], provider_code: str) -> int:
        """Import games using import_games_enhanced.py script"""
        if not games:
            return 0

        if self.dry_run:
            logger.info(f"[DRY RUN] Would import {len(games)} games")
            return len(games)

        # Save games to temporary file
        temp_file = None
        try:
            temp_file = self.save_games_to_temp_file(games)
            if not temp_file:
                return 0

            # Get the script path
            script_dir = Path(__file__).parent
            import_script = script_dir / "import_games_enhanced.py"

            # Build command
            cmd = [
                sys.executable,
                str(import_script),
                temp_file,
                provider_code,
            ]

            if self.dry_run:
                cmd.append("--dry-run")

            logger.info(f"Running import script: {' '.join(cmd)}")

            # Prepare environment variables for subprocess
            # The import script expects SUPABASE_SERVICE_ROLE_KEY, but we might have SUPABASE_SERVICE_KEY
            env = os.environ.copy()

            # Map SUPABASE_SERVICE_KEY to SUPABASE_SERVICE_ROLE_KEY if needed
            if "SUPABASE_SERVICE_KEY" in env and "SUPABASE_SERVICE_ROLE_KEY" not in env:
                env["SUPABASE_SERVICE_ROLE_KEY"] = env["SUPABASE_SERVICE_KEY"]

            # Ensure SUPABASE_URL is available
            if "SUPABASE_URL" not in env:
                # Try NEXT_PUBLIC_SUPABASE_URL as fallback
                if "NEXT_PUBLIC_SUPABASE_URL" in env:
                    env["SUPABASE_URL"] = env["NEXT_PUBLIC_SUPABASE_URL"]

            # Run the import script with environment variables
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent.parent,  # Run from project root
                env=env,  # Pass environment variables explicitly
            )

            if result.returncode != 0:
                logger.error(f"Import script failed with return code {result.returncode}")
                logger.error(f"STDOUT: {result.stdout}")
                logger.error(f"STDERR: {result.stderr}")
                raise RuntimeError(f"Import failed: {result.stderr or 'Unknown error'}")

            # Parse machine-readable IMPORT_RESULT line from stdout
            games_accepted = len(games)  # fallback if parsing fails
            parsed_result = False
            for line in result.stdout.splitlines():
                if line.startswith("IMPORT_RESULT:"):
                    try:
                        import_data = json.loads(line[len("IMPORT_RESULT:") :])
                        games_accepted = import_data.get("games_accepted", len(games))
                        logger.info(
                            f"Import completed: {import_data.get('games_processed', '?')} processed, "
                            f"{games_accepted} accepted, "
                            f"{import_data.get('duplicates_skipped', 0)} perspective dupes skipped, "
                            f"{import_data.get('duplicates_found', 0)} already in DB, "
                            f"{import_data.get('games_quarantined', 0)} quarantined"
                        )
                        parsed_result = True
                        break
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning(f"Failed to parse import result: {e}")

            if not parsed_result:
                logger.info("Import completed successfully (could not parse detailed metrics)")
                logger.debug(f"STDOUT: {result.stdout}")

            return games_accepted

        except Exception as e:
            logger.error(f"Error importing games: {e}")
            raise
        finally:
            # Clean up temporary file
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                    logger.debug(f"Cleaned up temporary file: {temp_file}")
                except Exception as e:
                    logger.warning(f"Failed to delete temporary file {temp_file}: {e}")

    def process_request(self, request: Dict) -> bool:
        """Process a single scrape request"""
        request_id = request.get("id")
        team_name = request.get("team_name", "Unknown")
        game_date = request.get("game_date")
        provider_id = request.get("provider_id")
        provider_team_id = request.get("provider_team_id")

        # Validate required fields
        if not request_id:
            raise ValueError("Missing required field: id")
        if not game_date:
            raise ValueError("Missing required field: game_date")
        if not provider_id:
            raise ValueError("Missing required field: provider_id")
        if not provider_team_id:
            raise ValueError("Missing required field: provider_team_id")

        logger.info(f"Processing request {request_id} for {team_name} on {game_date}")
        logger.debug(f"Request data: provider_id={provider_id}, provider_team_id={provider_team_id}")

        # The scrape can be re-routed to a GotSport alias below, and the log row
        # records the provider actually scraped. Bound out here so the failure
        # handlers can read it whatever the re-routing did.
        scrape_provider_id = provider_id

        try:
            # Update status to processing
            self.update_request_status(request_id, "processing")

            # Get provider code
            provider_code = self.get_provider_code(provider_id)

            # Check if we have a scraper for this provider
            # If not, try to find a GotSport alias via team_alias_map
            scrape_provider_code = provider_code
            scrape_team_id = provider_team_id

            if provider_code not in self.scrapers:
                logger.info(f"No scraper for provider '{provider_code}', checking for GotSport alias...")
                team_id_master = request.get("team_id_master")

                if team_id_master:
                    gotsport_alias = self.get_gotsport_alias(team_id_master)
                    if gotsport_alias:
                        scrape_provider_code = "gotsport"
                        scrape_team_id = gotsport_alias["provider_team_id"]
                        scrape_provider_id = gotsport_alias["provider_id"]
                        logger.info(f"Using GotSport alias: team_id={scrape_team_id}")
                    else:
                        raise ValueError(
                            f"No scraper available for provider '{provider_code}' and no GotSport alias found"
                        )
                else:
                    raise ValueError(f"No scraper available for provider: {provider_code}")

            # Scrape games for the date (±90 days window)
            # If team ID returns 404, try alternative IDs from team_alias_map
            tried_team_ids = []
            games = None
            team_id_master = request.get("team_id_master")

            while games is None:
                try:
                    games = self.scrape_games_for_date(scrape_provider_code, scrape_team_id, game_date)
                except TeamNotFoundError:
                    tried_team_ids.append(str(scrape_team_id))
                    logger.warning(
                        f"Team {scrape_team_id} not found on {scrape_provider_code}, "
                        f"checking for alternative team IDs..."
                    )

                    # Try to find an alternative team ID from team_alias_map
                    if team_id_master and scrape_provider_code == "gotsport":
                        alt_alias = self.get_gotsport_alias(team_id_master, exclude_team_ids=tried_team_ids)
                        if alt_alias:
                            scrape_team_id = alt_alias["provider_team_id"]
                            scrape_provider_id = alt_alias["provider_id"]
                            logger.info(f"Retrying with alternative GotSport team ID: {scrape_team_id}")
                            continue

                    raise TeamNotFoundError(
                        tried_team_ids[0] if len(tried_team_ids) == 1 else tried_team_ids, scrape_provider_code
                    )

            self._record_scrape_attempt(
                team_id_master,
                scrape_provider_id,
                len(games),
                "success" if games else "partial",
                update_last_scraped_at=True,
            )

            # Buffer for the end-of-batch import rather than spawning a subprocess
            # per request. The row stays 'processing' until _flush_pending_imports
            # confirms the import: 'completed' has to mean the games reached the
            # database, because get_pending_requests only ever returns 'pending'.
            if games:
                self._pending_imports.append((scrape_provider_code, games, request_id))
                self.stats["games_found"] += len(games)
            else:
                self.update_request_status(request_id, "completed", games_found=0)

            logger.info(
                f"Successfully processed request {request_id}: "
                f"{len(games)} games found in 181-day window, buffered for import"
            )

            self.stats["successful"] += 1
            return True

        except TeamNotFoundError as e:
            team_id_master = request.get("team_id_master", "unknown")
            error_msg = (
                f"{e} — the provider_team_id in the teams table may be outdated. team_id_master={team_id_master}"
            )
            logger.error(f"Failed to process request {request_id}: {error_msg}")

            self._record_scrape_attempt(
                request.get("team_id_master"),
                scrape_provider_id,
                0,
                "error",
                update_last_scraped_at=True,
            )

            self.update_request_status(request_id, "failed", error_message=error_msg[:500])

            self.stats["failed"] += 1
            return False

        except WAFBlockedError as e:
            error_msg = f"WAF blocked: {e}"
            logger.error(f"Failed to process request {request_id}: {error_msg}")

            # A block never reached the provider, so this was not a probe. Stamping
            # last_scraped_at anyway would restart the six-month re-probe clock and
            # hold the team out of the weekly stale sweep for 90 days on a scrape
            # that did not happen.
            self._record_scrape_attempt(
                request.get("team_id_master"),
                scrape_provider_id,
                0,
                "error",
                update_last_scraped_at=False,
            )

            # Write the terminal status before re-raising: nothing reclaims a row
            # left in 'processing', and resetting it to 'pending' can collide with
            # idx_scrape_requests_pending_team.
            self.update_request_status(request_id, "failed", error_message=error_msg[:500])

            self.stats["failed"] += 1
            raise

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to process request {request_id}: {error_msg}")
            logger.debug(traceback.format_exc())

            # An unexpected failure gives no evidence the provider was reached, so
            # it logs the attempt without advancing the timestamp — same reasoning
            # as the WAF branch above.
            self._record_scrape_attempt(
                request.get("team_id_master"),
                scrape_provider_id,
                0,
                "error",
                update_last_scraped_at=False,
            )

            # Update request as failed
            self.update_request_status(
                request_id,
                "failed",
                error_message=error_msg[:500],  # Truncate error message
            )

            self.stats["failed"] += 1
            return False

    def process_all(self, limit: int = 10) -> Dict:
        """Process all pending requests up to limit"""
        logger.info(f"Starting to process missing game requests (limit: {limit})")

        # Get pending requests
        requests = self.get_pending_requests(limit)

        if not requests:
            logger.info("No pending requests found")
            return self.stats

        logger.info(f"Found {len(requests)} pending requests")

        # Process each request
        for request in requests:
            self.stats["processed"] += 1

            try:
                self.process_request(request)

            except KeyboardInterrupt:
                logger.info("Processing interrupted by user")
                break
            except WAFBlockedError:
                # Session-wide lockout: every remaining row would fail for the same
                # reason, and a 'failed' row has no retry path. Stopping leaves them
                # pending for the next run.
                remaining = len(requests) - self.stats["processed"]
                self.stats["waf_aborted"] += 1
                logger.error(
                    f"GotSport WAF abort after {self.stats['processed']} of {len(requests)} requests; "
                    f"{remaining} left pending for the next run"
                )
                break
            except Exception as e:
                logger.error(f"Unexpected error processing request: {e}")
                continue

        self._flush_pending_imports()
        self._flush_scrape_log()

        # Log summary
        self.log_summary()
        return self.stats

    def _flush_pending_imports(self) -> None:
        """Import every buffered request's games, one subprocess per provider.

        A failed batch is retried a chunk at a time so one unimportable game costs
        its own request's games rather than the whole run's.
        """
        if not self._pending_imports:
            return

        chunks_by_provider: Dict[str, List[tuple]] = {}
        for provider_code, games, request_id in self._pending_imports:
            chunks_by_provider.setdefault(provider_code, []).append((request_id, games))
        self._pending_imports = []

        for provider_code, chunks in chunks_by_provider.items():
            batch = [game for _, games in chunks for game in games]
            try:
                self.stats["games_imported"] += self.import_games(batch, provider_code)
            except Exception as e:
                logger.error(f"Batched import of {len(batch)} {provider_code} games failed: {e}")
                logger.info(f"Retrying {len(chunks)} buffered requests individually")
                self._import_chunks_individually(chunks, provider_code)
                continue

            for request_id, games in chunks:
                self.update_request_status(request_id, "completed", games_found=len(games))

    def _import_chunks_individually(self, chunks: List[tuple], provider_code: str) -> None:
        """Fallback for a failed batch, so one unimportable game costs only its own request."""
        for request_id, games in chunks:
            try:
                self.stats["games_imported"] += self.import_games(games, provider_code)
                self.update_request_status(request_id, "completed", games_found=len(games))
            except Exception as chunk_error:
                logger.error(f"Import of {len(games)} {provider_code} games failed: {chunk_error}")
                self.update_request_status(
                    request_id, "failed", error_message=f"Import failed: {chunk_error}"[:500]
                )
                self.stats["successful"] -= 1
                self.stats["failed"] += 1

    def _record_scrape_attempt(
        self,
        team_id_master: Optional[str],
        provider_id: str,
        games_found: int,
        status: str,
        update_last_scraped_at: bool,
    ) -> None:
        """Buffer one scrape attempt for the end-of-run write.

        A request without a team_id_master contributes no row: team_scrape_log.team_id
        is NOT NULL REFERENCES teams(team_id_master), and process_request treats the
        field as optional.
        """
        if not team_id_master:
            return

        self._scrape_log_buffer.append(
            {
                "team_id_master": team_id_master,
                "provider_id": provider_id,
                "games_found": games_found,
                "status": status,
                "update_last_scraped_at": update_last_scraped_at,
            }
        )

    def _flush_scrape_log(self) -> None:
        """Write the run's buffered scrape attempts, mirroring drain_queue's bulk logger.

        This drainer is the only consumer of the queue that never recorded its work.
        Two things read what it writes: teams.scrape_attempts counts the non-error
        rows, and the six-month re-probe reads last_scraped_at — which stops advancing
        precisely while a team is being filtered out of the weekly enqueue jobs, so a
        probe that finds nothing has to still bump it or the clock never restarts.

        Both writes are best-effort. A bookkeeping failure is not worth failing an
        otherwise successful scrape over.
        """
        if not self._scrape_log_buffer:
            return

        buffered = self._scrape_log_buffer
        self._scrape_log_buffer = []

        if self.dry_run:
            logger.info(f"[DRY RUN] Would log {len(buffered)} scrape attempts")
            return

        now_iso = datetime.now().isoformat()
        log_entries = [
            {
                "team_id": entry["team_id_master"],
                "provider_id": entry["provider_id"],
                "scraped_at": now_iso,
                "games_found": entry["games_found"],
                "status": entry["status"],
            }
            for entry in buffered
        ]
        update_payload = [
            {"team_id_master": entry["team_id_master"], "last_scraped_at": now_iso}
            for entry in buffered
            if entry["update_last_scraped_at"]
        ]

        log_insert_batch_size = 500
        inserted_count = 0
        for i in range(0, len(log_entries), log_insert_batch_size):
            batch = log_entries[i : i + log_insert_batch_size]
            try:
                self.supabase.table("team_scrape_log").insert(batch).execute()
                inserted_count += len(batch)
            except Exception as e:
                logger.warning(f"Error batch inserting scrape logs (batch {i // log_insert_batch_size + 1}): {e}")

        try:
            updated_count = bulk_update_last_scraped_at(self.supabase, update_payload)
        except Exception as e:
            logger.warning(f"Error bulk updating last_scraped_at for {len(update_payload)} teams: {e}")
            updated_count = 0

        logger.info(f"Logged {inserted_count} scrape attempts and updated {updated_count} team timestamps")

    def log_summary(self):
        """Log processing summary"""
        logger.info("=" * 50)
        logger.info("Processing Summary:")
        logger.info(f"  Requests Processed: {self.stats['processed']}")
        logger.info(f"  Requests Successful: {self.stats['successful']}")
        logger.info(f"  Requests Failed: {self.stats['failed']}")
        logger.info(f"  Total Games Found: {self.stats['games_found']}")
        logger.info(f"  Total Games Imported: {self.stats['games_imported']}")
        if self.stats["waf_aborted"]:
            logger.info(f"  WAF Aborts: {self.stats['waf_aborted']} (remaining rows left pending)")
        logger.info("=" * 50)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Process missing game scrape requests")
    parser.add_argument("--limit", type=int, default=40, help="Maximum number of requests to process")
    parser.add_argument("--dry-run", action="store_true", help="Run without making any changes")
    parser.add_argument("--continuous", action="store_true", help="Run continuously, checking every 30 seconds")
    parser.add_argument("--interval", type=int, default=30, help="Interval in seconds for continuous mode")

    args = parser.parse_args()

    # Initialize Supabase client
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY environment variables")
        sys.exit(1)

    try:
        supabase = create_client(supabase_url, supabase_key)
        logger.info("Connected to Supabase")
    except Exception as e:
        logger.error(f"Failed to connect to Supabase: {e}")
        sys.exit(1)

    # Create processor
    processor = MissingGamesProcessor(supabase, dry_run=args.dry_run)

    if args.continuous:
        logger.info(f"Running in continuous mode (interval: {args.interval}s)")

        while True:
            try:
                stats = processor.process_all(limit=args.limit)

                if stats["waf_aborted"]:
                    # The breaker's aborted state is terminal for the life of the
                    # process, so every later poll would raise on its first row.
                    logger.error("Terminal WAF abort - exiting so the next run starts with a fresh breaker")
                    break

                logger.info(f"Sleeping for {args.interval} seconds...")
                time.sleep(args.interval)

                processor.reset_stats()

            except KeyboardInterrupt:
                logger.info("Stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in continuous mode: {e}")
                time.sleep(60)  # Wait longer on error
    else:
        # Single run
        try:
            processor.process_all(limit=args.limit)

            # Exit with success code even if some requests failed
            # Individual request failures are logged but don't indicate script failure
            # Only exit with error code if there was a critical error preventing processing
            sys.exit(0)
        except Exception as e:
            logger.error(f"Critical error during processing: {e}")
            logger.debug(traceback.format_exc())
            sys.exit(1)


if __name__ == "__main__":
    main()
