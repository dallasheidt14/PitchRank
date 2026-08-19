#!/usr/bin/env python3
"""
Backfill real team names for `unknown_<provider_team_id>` placeholder teams from GotSport.

These rows are created by the weekly unknown-opponent hygiene pipeline
(discover_teams_from_opponents.py) when its GotSport name lookup comes back empty.
The lookup is a plain HTTPS call that CloudFront rate-limits in bursts, so this
script paces itself the way process_missing_games.py does and is meant to be run
with a small --limit on a schedule until the placeholders are gone.

Provider IDs minted before ~May 2026 no longer exist on GotSport and return 404
permanently; they are counted separately so a run that only hits those is visibly
exhausted rather than silently failing.

Updates team_name and club_name only. Age group is deliberately not written —
GotSport's display_age_group is the registered event cohort, not the birth-year
cohort, and the two disagree across the Aug 1 rollover.

Examples:
    python3 scripts/backfill_unknown_team_names.py --dry-run --limit 40
    python3 scripts/backfill_unknown_team_names.py --limit 40
    python3 scripts/backfill_unknown_team_names.py --limit 200 --delay 0.3
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

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


def log(message: str) -> None:
    print(message, flush=True)


def _is_valid_club(club: Optional[str]) -> bool:
    """Return True if club is a real club name we should use."""
    if not club or not isinstance(club, str):
        return False
    s = club.strip()
    if not s or len(s) < 2:
        return False
    if s.lower() in NO_CLUB_VALUES:
        return False
    if s.lower().startswith("no ") or s.lower().startswith("select"):
        return False
    return True


def _is_valid_name(name: Optional[str], provider_team_id: str) -> bool:
    """Return True if name is a real team name and not another placeholder."""
    if not name or not isinstance(name, str):
        return False
    s = name.strip()
    if len(s) < 2:
        return False
    return s.lower() != f"unknown_{provider_team_id}".lower()


class GotSportResolver:
    """Look up team details from GotSport API. Same pattern as unknown opponent scripts."""

    BASE_URL = "https://system.gotsport.com/api/v1/team_ranking_data/team_details"

    def __init__(self, timeout: int = 20, delay_seconds: float = 0.25):
        self.timeout = timeout
        self.delay_seconds = delay_seconds
        self.session = requests.Session()

    def resolve(self, provider_team_id: str) -> Dict[str, str]:
        key = str(provider_team_id).strip()
        if not key:
            return {"_error": "empty provider_team_id"}
        time.sleep(self.delay_seconds)
        try:
            response = self.session.get(
                self.BASE_URL,
                params={"team_id": key},
                timeout=self.timeout,
            )
        except Exception as e:
            return {"_error": str(e)}

        if response.status_code == 404:
            return {"_gone": "404 Can not find team"}
        if response.status_code != 200:
            return {"_error": f"HTTP {response.status_code}"}

        try:
            payload = response.json() if response.content else {}
        except Exception as e:
            return {"_error": f"non-JSON body: {e}"}
        if not isinstance(payload, dict):
            return {"_error": "non-dict body"}

        return {
            "name": str(payload.get("name") or "").strip(),
            "club_name": str(payload.get("club_name") or "").strip(),
            "gender": str(payload.get("display_gender") or "").strip(),
            "age_group": str(payload.get("display_age_group") or "").strip(),
            "association": str(payload.get("team_association") or "").strip(),
        }


def load_env() -> None:
    env_local = Path(".env.local")
    if env_local.exists():
        load_dotenv(env_local, override=True)
    else:
        load_dotenv()


def get_supabase():
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    )
    if not supabase_url or not supabase_key:
        raise ValueError("Missing Supabase credentials. Need SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")
    return create_client(supabase_url, supabase_key)


def fetch_placeholder_teams(supabase, limit: int, created_after: Optional[str]) -> List[Dict]:
    """Placeholder teams, newest first. Recent provider IDs still resolve; old ones 404."""
    query = (
        supabase.table("teams")
        .select("team_id_master,team_name,provider_team_id,club_name,gender,state_code")
        .like("team_name", "unknown_%")
        .eq("is_deprecated", False)
        .not_.is_("provider_team_id", "null")
    )
    if created_after:
        query = query.gte("created_at", created_after)
    rows = query.order("created_at", desc=True).limit(limit).execute().data or []
    return [r for r in rows if str(r.get("provider_team_id") or "").strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill real team names for unknown_ placeholders from GotSport")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview updates without writing to DB",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=40,
        help="Max teams to process (default: 40, matching the scrape drainer)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
        help="Seconds between API calls (default: 0.25)",
    )
    parser.add_argument(
        "--created-after",
        default="2026-08-04",
        help="Only teams created on/after this date (default: 2026-08-04). Pass '' for all.",
    )
    args = parser.parse_args()

    load_env()
    supabase = get_supabase()

    teams = fetch_placeholder_teams(supabase, args.limit, args.created_after)
    if not teams:
        log("No placeholder teams remaining.")
        return

    log(f"=== Backfill Unknown Team Names ({'DRY RUN' if args.dry_run else 'LIVE'}) ===")
    scope = f" created on/after {args.created_after}" if args.created_after else ""
    log(f"Processing {len(teams):,} placeholder teams{scope} at {args.delay}s/call")
    log("")

    resolver = GotSportResolver(delay_seconds=args.delay)
    updated = 0
    clubs_set = 0
    gone = 0
    skipped_no_name = 0
    skipped_error = 0
    gender_mismatch = 0

    for team in teams:
        team_id = team["team_id_master"]
        provider_team_id = str(team["provider_team_id"]).strip()

        result = resolver.resolve(provider_team_id)
        if "_gone" in result:
            gone += 1
            continue
        if "_error" in result:
            skipped_error += 1
            if skipped_error <= 5:
                log(f"  API error for {provider_team_id}: {result['_error']}")
            continue

        name = result.get("name", "")
        if not _is_valid_name(name, provider_team_id):
            skipped_no_name += 1
            continue

        update: Dict[str, str] = {"team_name": name}
        club = result.get("club_name", "")
        if _is_valid_club(club) and not str(team.get("club_name") or "").strip():
            update["club_name"] = club

        api_gender = result.get("gender", "")
        if api_gender and api_gender != str(team.get("gender") or "").strip():
            gender_mismatch += 1

        suffix = f"  [club: {update['club_name']}]" if "club_name" in update else ""

        if args.dry_run:
            log(f"  [DRY-RUN] {team['team_name']} -> {name}{suffix}")
            updated += 1
            clubs_set += "club_name" in update
            continue

        try:
            supabase.table("teams").update(update).eq("team_id_master", team_id).execute()
            updated += 1
            clubs_set += "club_name" in update
            log(f"  {team['team_name']} -> {name}{suffix}")
        except Exception as e:
            skipped_error += 1
            log(f"  ERROR updating {team_id}: {e}")

    log("")
    log("=== Summary ===")
    log(f"Renamed: {updated:,}")
    log(f"Club also set: {clubs_set:,}")
    log(f"Gone from GotSport (404, needs marking): {gone:,}")
    log(f"Skipped (no usable name): {skipped_no_name:,}")
    log(f"Skipped (API/DB error): {skipped_error:,}")
    if gender_mismatch:
        log(f"NOTE: {gender_mismatch:,} teams have a stored gender that disagrees with GotSport (not written)")


if __name__ == "__main__":
    main()
