#!/usr/bin/env python3
"""
Backfill missing club names for teams by looking them up on GotSport.

Finds all teams in the DB with no club_name (NULL or empty), gets their
GotSport provider_team_id from team_alias_map, calls the GotSport API
for team details, and updates club_name when GotSport returns a valid value.

Skips when GotSport returns "no club", "no club selection", "n/a", etc.

Reuses GotSportResolver pattern from unknown opponent hygiene scripts.

Examples:
    python3 scripts/backfill_missing_club_names.py --dry-run
    python3 scripts/backfill_missing_club_names.py --limit 100
    python3 scripts/backfill_missing_club_names.py --workers 5   # ~5x faster
    python3 scripts/backfill_missing_club_names.py
"""

from __future__ import annotations

import argparse
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests
from dotenv import load_dotenv
from supabase import create_client


# Values from GotSport that mean "no club" - do not update
NO_CLUB_VALUES: Set[str] = {
    "",
    "n/a",
    "na",
    "none",
    "null",
    "no club",
    "no club listed",
    "no club selection",
    "no club assigned",
    "no club selected",
    "not selected",
    "not applicable",
    "unassigned",
    "select club",
    "select a club",
    "choose club",
}


def _is_valid_club(club: Optional[str]) -> bool:
    """Return True if club is a real club name we should use."""
    if not club or not isinstance(club, str):
        return False
    s = club.strip()
    if not s or len(s) < 2:
        return False
    if s.lower() in NO_CLUB_VALUES:
        return False
    # Reject if it looks like a placeholder
    if s.lower().startswith("no ") or s.lower().startswith("select"):
        return False
    return True


class GotSportResolver:
    """Look up team details from GotSport API. Same pattern as unknown opponent scripts.
    Each instance has its own session; use one per thread for parallel requests."""

    BASE_URL = "https://system.gotsport.com/api/v1/team_ranking_data/team_details"

    def __init__(self, timeout: int = 20, delay_seconds: float = 0.2):
        self.timeout = timeout
        self.delay_seconds = delay_seconds
        self.session = requests.Session()
        self.cache: Dict[str, Dict[str, str]] = {}

    def resolve(self, provider_team_id: str) -> Dict[str, str]:
        key = str(provider_team_id).strip()
        if not key:
            return {}
        if key in self.cache:
            return self.cache[key]
        time.sleep(self.delay_seconds)
        try:
            response = self.session.get(
                self.BASE_URL,
                params={"team_id": key},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json() if response.content else {}
            if not isinstance(payload, dict):
                payload = {}
        except Exception as e:
            return {"_error": str(e)}
        resolved = {
            "name": str(payload.get("name") or "").strip(),
            "full_name": str(payload.get("full_name") or "").strip(),
            "club_name": str(payload.get("club_name") or "").strip(),
            "state": str(payload.get("state") or "").strip(),
            "age": str(payload.get("age") or "").strip(),
            "gender": str(payload.get("gender") or "").strip(),
        }
        self.cache[key] = resolved
        return resolved


def load_env() -> None:
    env_local = Path(".env.local")
    if env_local.exists():
        load_dotenv(env_local, override=True)
    else:
        load_dotenv()


def get_supabase():
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_KEY")
    )
    if not supabase_url or not supabase_key:
        raise ValueError(
            "Missing Supabase credentials. Need SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
        )
    return create_client(supabase_url, supabase_key)


def fetch_teams_without_club(supabase, limit: Optional[int]) -> List[Dict]:
    """Teams where club_name is NULL or empty. Excludes deprecated."""
    page_size = 1000
    offset = 0
    rows: List[Dict] = []
    seen: set = set()

    # Fetch NULL and empty string in two passes (Supabase or_ for eq empty can be tricky)
    for filter_fn in [
        lambda q: q.is_("club_name", "null"),
        lambda q: q.eq("club_name", ""),
    ]:
        offset = 0
        while True:
            query = (
                supabase.table("teams")
                .select("team_id_master,team_name,club_name,age_group,gender")
                .eq("is_deprecated", False)
            )
            query = filter_fn(query)
            batch = query.range(offset, offset + page_size - 1).execute().data or []
            if not batch:
                break
            for r in batch:
                tid = r.get("team_id_master")
                if tid and tid not in seen:
                    cn = r.get("club_name") or ""
                    if not str(cn).strip():
                        seen.add(tid)
                        rows.append(r)
            if limit and len(rows) >= limit:
                return rows[:limit]
            if len(batch) < page_size:
                break
            offset += page_size

    return rows[:limit] if limit else rows


def fetch_gotsport_provider_id(supabase) -> Optional[str]:
    providers = supabase.table("providers").select("id").eq("code", "gotsport").execute().data
    if not providers:
        return None
    return providers[0]["id"]


def fetch_gotsport_ids(
    supabase, team_ids: List[str], gotsport_provider_id: str
) -> Dict[str, str]:
    """Map team_id_master -> GotSport provider_team_id.
    Sources: team_alias_map (approved), then teams.provider_team_id when provider_id=gotsport.
    """
    if not team_ids or not gotsport_provider_id:
        return {}

    lookup: Dict[str, str] = {}

    # 1. From team_alias_map
    for i in range(0, len(team_ids), 500):
        batch = team_ids[i : i + 500]
        rows = (
            supabase.table("team_alias_map")
            .select("team_id_master,provider_team_id")
            .eq("provider_id", gotsport_provider_id)
            .in_("team_id_master", batch)
            .eq("review_status", "approved")
            .execute()
            .data
            or []
        )
        for r in rows:
            tid = r.get("team_id_master")
            pid = r.get("provider_team_id")
            if tid and pid and tid not in lookup:
                lookup[tid] = str(pid).strip()

    # 2. Fallback: teams with provider_id=gotsport and provider_team_id set
    missing = [tid for tid in team_ids if tid not in lookup]
    if missing:
        for i in range(0, len(missing), 500):
            batch = missing[i : i + 500]
            rows = (
                supabase.table("teams")
                .select("team_id_master,provider_team_id")
                .eq("provider_id", gotsport_provider_id)
                .in_("team_id_master", batch)
                .not_.is_("provider_team_id", "null")
                .execute()
                .data
                or []
            )
            for r in rows:
                tid = r.get("team_id_master")
                pid = r.get("provider_team_id")
                if tid and pid and tid not in lookup:
                    lookup[tid] = str(pid).strip()

    return lookup


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill missing club names from GotSport API"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview updates without writing to DB",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max teams to process (default: all)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Seconds between API calls per worker (default: 0.2)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Concurrent API workers (default: 1). Use 5-10 for ~5-10x speedup.",
    )
    args = parser.parse_args()

    workers = max(1, args.workers)
    delay = args.delay
    if workers > 1 and delay >= 0.2:
        delay = 0.1  # Slightly faster per-worker when parallel

    load_env()
    supabase = get_supabase()

    gotsport_provider_id = fetch_gotsport_provider_id(supabase)
    if not gotsport_provider_id:
        print("ERROR: GotSport provider not found in providers table.")
        return

    teams = fetch_teams_without_club(supabase, args.limit)
    if not teams:
        print("No teams with missing club_name found.")
        return

    team_ids = [t["team_id_master"] for t in teams]
    gotsport_id_map = fetch_gotsport_ids(supabase, team_ids, gotsport_provider_id)

    # Only process teams that have a GotSport ID (alias map or teams.provider_team_id)
    processable = [t for t in teams if t["team_id_master"] in gotsport_id_map]
    skipped_no_alias = len(teams) - len(processable)

    log_lock = threading.Lock()

    def log(msg: str) -> None:
        with log_lock:
            print(msg, flush=True)

    log("=== Backfill Missing Club Names ===")
    log(f"Teams with no club: {len(teams):,}")
    log(f"With GotSport alias: {len(processable):,}")
    log(f"Skipped (no GotSport ID): {skipped_no_alias:,}")
    log(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    log(f"Workers: {workers}")
    log("")

    def process_one(team: Dict) -> Tuple[str, Optional[str], Optional[str]]:
        """Returns (team_id, club_if_valid, error_msg)."""
        team_id = team["team_id_master"]
        provider_team_id = gotsport_id_map[team_id]
        resolver = GotSportResolver(delay_seconds=delay)
        result = resolver.resolve(provider_team_id)
        if "_error" in result:
            return (team_id, None, result["_error"])
        club = result.get("club_name", "")
        if not _is_valid_club(club):
            return (team_id, None, None)  # No club from API
        return (team_id, club, None)

    updated = 0
    skipped_no_club = 0
    skipped_error = 0

    if workers <= 1:
        # Sequential (original behavior)
        resolver = GotSportResolver(delay_seconds=delay)
        for i, team in enumerate(processable, start=1):
            team_id = team["team_id_master"]
            provider_team_id = gotsport_id_map[team_id]
            team_name = team.get("team_name", "")

            result = resolver.resolve(provider_team_id)
            if "_error" in result:
                skipped_error += 1
                if skipped_error <= 5:
                    log(f"  API error for {provider_team_id}: {result['_error']}")
                continue

            club = result.get("club_name", "")
            if not _is_valid_club(club):
                skipped_no_club += 1
                continue

            if args.dry_run:
                log(f"  [DRY-RUN] Would set club: {team_name[:40]}... -> {club}")
                updated += 1
                continue

            try:
                supabase.table("teams").update({"club_name": club}).eq(
                    "team_id_master", team_id
                ).execute()
                updated += 1
                if updated <= 20 or updated % 100 == 0:
                    log(f"  Updated {team_name[:35]}... -> {club}")
            except Exception as e:
                skipped_error += 1
                log(f"  ERROR updating {team_id}: {e}")

            if i % 50 == 0:
                log(f"  Progress: {i}/{len(processable)}...")
    else:
        # Parallel: resolve in workers, then update DB sequentially (Supabase is simpler)
        team_by_id = {t["team_id_master"]: t for t in processable}
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(process_one, t): t for t in processable}
            done = 0
            to_update: List[Tuple[str, str]] = []
            for future in as_completed(futures):
                done += 1
                if done % 100 == 0:
                    log(f"  Progress: {done}/{len(processable)} resolved...")
                try:
                    team_id, club, err = future.result()
                    if err:
                        skipped_error += 1
                        if skipped_error <= 5:
                            log(f"  API error: {err}")
                    elif club:
                        to_update.append((team_id, club))
                    else:
                        skipped_no_club += 1
                except Exception as e:
                    skipped_error += 1
                    log(f"  Worker error: {e}")

        log(f"  Resolved. Applying {len(to_update):,} updates...")
        for team_id, club in to_update:
            if args.dry_run:
                team_name = team_by_id.get(team_id, {}).get("team_name", "")[:40]
                log(f"  [DRY-RUN] Would set club: {team_name}... -> {club}")
                updated += 1
                continue
            try:
                supabase.table("teams").update({"club_name": club}).eq(
                    "team_id_master", team_id
                ).execute()
                updated += 1
                if updated <= 20 or updated % 100 == 0:
                    team_name = team_by_id.get(team_id, {}).get("team_name", "")[:35]
                    log(f"  Updated {team_name}... -> {club}")
            except Exception as e:
                skipped_error += 1
                log(f"  ERROR updating {team_id}: {e}")

    log("")
    log("=== Summary ===")
    log(f"Updated: {updated:,}")
    log(f"Skipped (GotSport says no club): {skipped_no_club:,}")
    log(f"Skipped (API/DB error): {skipped_error:,}")


if __name__ == "__main__":
    main()
