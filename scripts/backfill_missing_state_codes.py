#!/usr/bin/env python3
"""
Backfill missing state codes for teams by looking them up on GotSport.

Finds all teams in the DB with no state_code (NULL or empty), gets their
GotSport provider_team_id from team_alias_map, calls the GotSport API
for team details, and updates state_code when GotSport returns a valid value.

Skips when GotSport returns "n/a", "none", empty, etc.
Normalizes full state names (e.g. "California") to 2-letter codes (e.g. "CA").

Examples:
    python3 scripts/backfill_missing_state_codes.py --dry-run
    python3 scripts/backfill_missing_state_codes.py --limit 100
    python3 scripts/backfill_missing_state_codes.py --workers 10
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

# Valid US state codes (2-letter). GotSport returns state; we normalize to code.
STATE_CODE_TO_NAME: Dict[str, str] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia",
}
STATE_NAME_TO_CODE: Dict[str, str] = {v.upper(): k for k, v in STATE_CODE_TO_NAME.items()}
VALID_STATE_CODES: Set[str] = set(STATE_CODE_TO_NAME.keys())

NO_STATE_VALUES: Set[str] = {
    "",
    "n/a",
    "na",
    "none",
    "null",
    "not selected",
    "not applicable",
    "unassigned",
    "select state",
    "select a state",
    "choose state",
}


def _normalize_to_state_code(state: Optional[str]) -> Optional[str]:
    """Convert GotSport state (code or full name) to 2-letter state_code."""
    if not state or not isinstance(state, str):
        return None
    s = state.strip()
    if not s or s.lower() in NO_STATE_VALUES:
        return None
    # Already 2-letter code?
    if len(s) == 2 and s.upper() in VALID_STATE_CODES:
        return s.upper()
    # Full state name?
    if s.upper() in STATE_NAME_TO_CODE:
        return STATE_NAME_TO_CODE[s.upper()]
    return None


class GotSportResolver:
    """Look up team details from GotSport API."""

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
        os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    )
    if not supabase_url or not supabase_key:
        raise ValueError("Missing Supabase credentials. Need SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")
    return create_client(supabase_url, supabase_key)


def fetch_teams_without_state(supabase, limit: Optional[int]) -> List[Dict]:
    """Teams where state_code is NULL or empty. Excludes deprecated."""
    page_size = 1000
    rows: List[Dict] = []
    seen: set = set()

    for filter_fn in [
        lambda q: q.is_("state_code", "null"),
        lambda q: q.eq("state_code", ""),
    ]:
        offset = 0
        while True:
            query = (
                supabase.table("teams")
                .select("team_id_master,team_name,state_code,age_group,gender")
                .eq("is_deprecated", False)
            )
            query = filter_fn(query)
            batch = query.range(offset, offset + page_size - 1).execute().data or []
            if not batch:
                break
            for r in batch:
                tid = r.get("team_id_master")
                if tid and tid not in seen:
                    sc = r.get("state_code") or ""
                    if not str(sc).strip():
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


def fetch_gotsport_ids(supabase, team_ids: List[str], gotsport_provider_id: str) -> Dict[str, str]:
    """Map team_id_master -> GotSport provider_team_id."""
    if not team_ids or not gotsport_provider_id:
        return {}

    lookup: Dict[str, str] = {}

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
    parser = argparse.ArgumentParser(description="Backfill missing state codes from GotSport API")
    parser.add_argument("--dry-run", action="store_true", help="Preview updates without writing to DB")
    parser.add_argument("--limit", type=int, default=None, help="Max teams to process (default: all)")
    parser.add_argument("--delay", type=float, default=0.2, help="Seconds between API calls per worker")
    parser.add_argument("--workers", type=int, default=1, help="Concurrent API workers (default: 1)")
    args = parser.parse_args()

    workers = max(1, args.workers)
    delay = args.delay
    if workers > 1 and delay >= 0.2:
        delay = 0.1

    load_env()
    supabase = get_supabase()

    gotsport_provider_id = fetch_gotsport_provider_id(supabase)
    if not gotsport_provider_id:
        print("ERROR: GotSport provider not found in providers table.")
        return

    teams = fetch_teams_without_state(supabase, args.limit)
    if not teams:
        print("No teams with missing state_code found.")
        return

    team_ids = [t["team_id_master"] for t in teams]
    gotsport_id_map = fetch_gotsport_ids(supabase, team_ids, gotsport_provider_id)
    processable = [t for t in teams if t["team_id_master"] in gotsport_id_map]
    skipped_no_alias = len(teams) - len(processable)

    log_lock = threading.Lock()

    def log(msg: str) -> None:
        with log_lock:
            print(msg, flush=True)

    log("=== Backfill Missing State Codes ===")
    log(f"Teams with no state_code: {len(teams):,}")
    log(f"With GotSport alias: {len(processable):,}")
    log(f"Skipped (no GotSport ID): {skipped_no_alias:,}")
    log(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    log(f"Workers: {workers}")
    log("")

    def process_one(team: Dict) -> Tuple[str, Optional[str], Optional[str]]:
        """Returns (team_id, state_code_if_valid, error_msg)."""
        team_id = team["team_id_master"]
        provider_team_id = gotsport_id_map[team_id]
        resolver = GotSportResolver(delay_seconds=delay)
        result = resolver.resolve(provider_team_id)
        if "_error" in result:
            return (team_id, None, result["_error"])
        state_raw = result.get("state", "")
        state_code = _normalize_to_state_code(state_raw)
        if not state_code:
            return (team_id, None, None)
        return (team_id, state_code, None)

    updated = 0
    skipped_no_state = 0
    skipped_error = 0

    if workers <= 1:
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

            state_code = _normalize_to_state_code(result.get("state", ""))
            if not state_code:
                skipped_no_state += 1
                continue

            if args.dry_run:
                log(f"  [DRY-RUN] Would set state: {team_name[:40]}... -> {state_code}")
                updated += 1
                continue

            try:
                supabase.table("teams").update({"state_code": state_code}).eq("team_id_master", team_id).execute()
                updated += 1
                if updated <= 20 or updated % 100 == 0:
                    log(f"  Updated {team_name[:35]}... -> {state_code}")
            except Exception as e:
                skipped_error += 1
                log(f"  ERROR updating {team_id}: {e}")

            if i % 50 == 0:
                log(f"  Progress: {i}/{len(processable)}...")
    else:
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
                    team_id, state_code, err = future.result()
                    if err:
                        skipped_error += 1
                        if skipped_error <= 5:
                            log(f"  API error: {err}")
                    elif state_code:
                        to_update.append((team_id, state_code))
                    else:
                        skipped_no_state += 1
                except Exception as e:
                    skipped_error += 1
                    log(f"  Worker error: {e}")

        log(f"  Resolved. Applying {len(to_update):,} updates...")
        for team_id, state_code in to_update:
            if args.dry_run:
                team_name = team_by_id.get(team_id, {}).get("team_name", "")[:40]
                log(f"  [DRY-RUN] Would set state: {team_name}... -> {state_code}")
                updated += 1
                continue
            try:
                supabase.table("teams").update({"state_code": state_code}).eq("team_id_master", team_id).execute()
                updated += 1
                if updated <= 20 or updated % 100 == 0:
                    team_name = team_by_id.get(team_id, {}).get("team_name", "")[:35]
                    log(f"  Updated {team_name}... -> {state_code}")
            except Exception as e:
                skipped_error += 1
                log(f"  ERROR updating {team_id}: {e}")

    log("")
    log("=== Summary ===")
    log(f"Updated: {updated:,}")
    log(f"Skipped (GotSport says no state): {skipped_no_state:,}")
    log(f"Skipped (API/DB error): {skipped_error:,}")


if __name__ == "__main__":
    main()
