#!/usr/bin/env python3
"""
Discover and create new teams from unmatched ("no_match") unknown opponents.

This script picks up where auto_match_unknown_opponents.py leaves off.
When an unknown opponent cannot be fuzzy-matched to any existing team
(action == "no_match"), this script:

1) Reads the match report CSV from auto_match_unknown_opponents.py
2) Filters for "no_match" rows
3) Resolves team metadata from the GotSport API, reusing the export's lookups
4) Skips a team whose lookup failed (next week retries it)
5) Validates sufficient metadata (name, age_group, gender required)
6) Checks the team doesn't already exist (alias check)
7) Creates new team in `teams` table + alias in `team_alias_map`; a team GotSport
   files as Coed is created excluded from rankings, and this script does not queue
   it for a scrape, though the scheduled enqueue sweeps can still pick it up
8) Backfills game FKs (home_team_master_id / away_team_master_id)

Examples:
    # Dry run (default) - report what would be created
    python3 scripts/discover_teams_from_opponents.py \\
        --match-report data/exports/unknown_opponent_match_report_weekly.csv

    # Execute - actually create teams
    python3 scripts/discover_teams_from_opponents.py \\
        --match-report data/exports/unknown_opponent_match_report_weekly.csv \\
        --execute

    # Limit to first 50 rows
    python3 scripts/discover_teams_from_opponents.py \\
        --match-report data/exports/unknown_opponent_match_report_weekly.csv \\
        --execute --limit 50
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests
from dotenv import load_dotenv

from supabase import create_client

# The workflow runs this as `python3 scripts/...`, which puts scripts/ on the
# path and not the repo root, and installs only supabase, python-dotenv and
# requests. Everything imported from src/ below depends only on requests and the
# standard library, so it is safe to reach for here where the shared triage
# predicate below is not.
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.utils.age_group import normalize_age_group  # noqa: E402
from src.utils.gotsport_team_details import TeamDetailsPacer  # noqa: E402
from src.utils.team_association_map import to_state_code  # noqa: E402


def _execute_with_retry(query_func, max_retries: int = 3, base_delay: float = 1.0):
    """Execute a Supabase query with exponential backoff on transient HTTP errors."""
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            return query_func()
        except Exception as e:
            last_exception = e
            err_msg = str(e).lower()
            is_transient = (
                "remoteprotocolerror" in type(e).__name__.lower()
                or "connectionterminated" in err_msg
                or "remoteprotocolerror" in err_msg
                or ("connection" in err_msg and "closed" in err_msg)
            )
            if not is_transient or attempt >= max_retries:
                raise
            delay = base_delay * (2**attempt)
            print(f"  [retry {attempt + 1}/{max_retries}] Transient error, retrying in {delay:.1f}s: {e}")
            time.sleep(delay)
    raise last_exception


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
        raise ValueError(
            "Missing Supabase credentials. "
            "Need SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_SERVICE_KEY/SUPABASE_KEY."
        )
    return create_client(supabase_url, supabase_key)


def _normalize_gender(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    s = str(v).strip().lower()
    if s in {"male", "m", "boys", "boy", "b"}:
        return "Male"
    if s in {"female", "f", "girls", "girl", "g"}:
        return "Female"
    return None


class GotSportResolver:
    BASE_URL = "https://system.gotsport.com/api/v1/team_ranking_data/team_details"

    def __init__(self, timeout: int = 15, pacer: Optional[TeamDetailsPacer] = None):
        self.timeout = timeout
        self.session = requests.Session()
        self.pacer = pacer or TeamDetailsPacer()
        self.cache: Dict[str, Dict[str, str]] = {}
        self.failed: Set[str] = set()

    def resolve(self, provider_team_id: str) -> Dict[str, str]:
        key = str(provider_team_id).strip()
        if not key:
            return {}
        if key in self.cache:
            return self.cache[key]
        try:
            response = self.pacer.get(
                self.session,
                self.BASE_URL,
                params={"team_id": key},
                timeout=self.timeout,
            )
            if response.status_code == 404:
                # "Can not find team" is a permanent answer, so cache it.
                self.cache[key] = {}
                return {}
            response.raise_for_status()
            payload = response.json() if response.content else {}
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            # A WAF block, timeout or 429 says nothing about this team, so it is
            # not cached, and main leaves the team for next week.
            self.failed.add(key)
            return {}

        # team_details has no full_name, state, age or gender key; the real fields
        # are team_association, display_age_group and display_gender.
        resolved = self.record(
            name=payload.get("name"),
            club_name=payload.get("club_name"),
            state=to_state_code(payload.get("team_association")),
            age=payload.get("display_age_group"),
            gender=payload.get("display_gender"),
        )
        self.cache[key] = resolved
        return resolved

    @staticmethod
    def record(name, club_name, state, age, gender) -> Dict[str, str]:
        """One team's details as the cache holds them, whichever stage read GotSport."""
        fields = {"name": name, "club_name": club_name, "state": state, "age": age, "gender": gender}
        return {field: str(value or "").strip() for field, value in fields.items()}

    def remember(self, provider_team_id: str, record: Dict[str, str]) -> bool:
        """Cache a lookup another stage made. Returns False when this id is already cached."""
        if provider_team_id in self.cache:
            return False
        self.cache[provider_team_id] = record
        return True


def _is_placeholder_name(team_name: Optional[str], provider_team_id: str) -> bool:
    """Return True for auto_match_unknown_opponents' ``unknown_<pid>`` fallback.

    Spelled out here rather than imported for the same reason
    ``src.tournaments.triage`` keeps its own copy: this script runs in a
    workflow that installs three packages, and importing the shared predicate
    would drag ``src.tournaments.storage`` in behind it.
    """
    name = (team_name or "").strip()
    pid = (provider_team_id or "").strip()
    if not name or not pid:
        return False
    return name.lower() == f"unknown_{pid}".lower()


def _build_team_metadata(
    row: Dict[str, str],
    resolver: Optional[GotSportResolver],
) -> Dict[str, Optional[str]]:
    """Build team metadata from CSV row + optional GotSport API resolution."""
    provider_code = (row.get("provider_code") or "").strip().lower()
    unknown_pid = (row.get("unknown_provider_team_id") or "").strip()

    # Start with CSV fields from the match report. State is deliberately not
    # among them: unknown_state_used holds whichever state auto_match reached
    # last, which is the team's own where the export resolved it and the state of
    # the team this one PLAYED where it did not. Nothing on the column separates
    # the two, and the opponent's is wrong for every interstate game -- the
    # population that produces unknown opponents in the first place. So a team's
    # own record supplies its state here, or it stays empty for the state
    # backfills to fill from club evidence.
    team_name = (row.get("unknown_team_name_used") or "").strip()
    club_name = (row.get("unknown_club_name_used") or "").strip()
    age_group = normalize_age_group(row.get("unknown_age_group_used"))
    gender = _normalize_gender(row.get("unknown_gender_used"))
    state_code = ""
    provider_gender = ""

    # Resolve from GotSport API if available and fields are missing
    if resolver and provider_code == "gotsport" and unknown_pid:
        resolved = resolver.resolve(unknown_pid)
        if resolved:
            # auto_match hands over unknown_<pid> when its own lookup came back
            # empty. That is a fuzzy-matching scratch value, not a name, so a
            # resolved name displaces it. A transport failure is skipped in main; a
            # 404 keeps the report's values, placeholder included.
            if not team_name or _is_placeholder_name(team_name, unknown_pid):
                team_name = resolved.get("name", "") or team_name
            club_name = club_name or resolved.get("club_name", "")
            # The CSV column carries the previous stage's last-resort guess,
            # which is the cohort of the team this one played, so the team's own
            # record outranks it.
            age_group = normalize_age_group(resolved.get("age")) or age_group
            gender = _normalize_gender(resolved.get("gender")) or gender
            state_code = resolved.get("state", "")
            provider_gender = resolved.get("gender", "")

    return {
        "team_name": team_name or None,
        "club_name": club_name or None,
        "age_group": age_group,
        "gender": gender,
        "state_code": state_code.upper() if state_code else None,
        "provider_gender": provider_gender or None,
    }


def _has_minimum_metadata(meta: Dict[str, Optional[str]]) -> bool:
    """Check that we have the minimum required fields to create a team."""
    return bool(meta.get("team_name") and meta.get("age_group") and meta.get("gender"))


def _is_coed(provider_gender: Optional[str]) -> bool:
    """PitchRank does not rank coed teams (owner, 2026-11-10)."""
    return str(provider_gender or "").strip().lower() == "coed"


# The export aggregate's columns this stage reuses, keyed by the record field each fills.
EXPORT_COLUMNS = {
    "name": "unknown_team_name",
    "club_name": "unknown_club_name",
    "state": "unknown_state",
    "age": "unknown_age",
    "gender": "unknown_gender",
}


def seed_from_export(resolver: GotSportResolver, aggregate_path: str) -> int:
    """Hand the resolver every lookup the export already answered, so this stage asks
    GotSport only about the ids the export could not read. Returns how many it seeded."""
    seeded = 0
    with open(aggregate_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pid = (row.get("unknown_provider_team_id") or "").strip()
            record = GotSportResolver.record(**{field: row.get(column) for field, column in EXPORT_COLUMNS.items()})
            if (row.get("provider_code") or "").strip().lower() != "gotsport" or not pid or not record["name"]:
                continue
            seeded += resolver.remember(pid, record)
    return seeded


def _alias_exists(supabase, provider_id: str, provider_team_id: str) -> Optional[str]:
    """Check if an alias already exists. Returns team_id_master if found, None otherwise."""
    existing = (
        _execute_with_retry(
            lambda: (
                supabase.table("team_alias_map")
                .select("team_id_master")
                .eq("provider_id", provider_id)
                .eq("provider_team_id", provider_team_id)
                .limit(1)
                .execute()
            )
        ).data
        or []
    )
    if existing:
        return existing[0].get("team_id_master")
    return None


def _team_exists_by_provider(supabase, provider_id: str, provider_team_id: str) -> Optional[str]:
    """Check if a team already exists for this provider+provider_team_id combo."""
    existing = (
        _execute_with_retry(
            lambda: (
                supabase.table("teams")
                .select("team_id_master")
                .eq("provider_id", provider_id)
                .eq("provider_team_id", provider_team_id)
                .limit(1)
                .execute()
            )
        ).data
        or []
    )
    if existing:
        return existing[0].get("team_id_master")
    return None


COED_EXCLUSION_REASON = "Coed team (GotSport files it as Coed); PitchRank does not rank coed teams"


def exclude_coed_team(supabase, team_id_master: str, provider_team_id: str) -> bool:
    """Keep a coed team out of the rankings. Returns False when the write fails.

    A duplicate key means a retried insert already landed, so it counts as written.
    """
    try:
        _execute_with_retry(
            lambda: (
                supabase.table("team_ranking_exclusions")
                .insert(
                    {
                        "team_id_master": team_id_master,
                        "reason": COED_EXCLUSION_REASON,
                        "evidence": {
                            "provider": "gotsport",
                            "provider_team_id": provider_team_id,
                            "gotsport_gender": "Coed",
                        },
                        "excluded_by": "discover_teams_from_opponents",
                    }
                )
                .execute()
            )
        )
    except Exception as e:
        error_str = str(e).lower()
        if "unique" in error_str or "duplicate" in error_str:
            return True
        print(f"  ERROR: coed team {provider_team_id} not excluded, so not created: {e}")
        return False
    return True


def create_team_and_alias(
    supabase,
    provider_id: str,
    provider_team_id: str,
    meta: Dict[str, Optional[str]],
    provider_code: Optional[str] = None,
    exclude_from_rankings: bool = False,
) -> Tuple[str, str]:
    """
    Create a new team and alias mapping.

    When provider_code == 'gotsport', also enqueue a scrape_requests row at
    priority 3 (discovery) so the new team enters the queue and gets its
    schedule scraped within ~15 minutes via process_missing_games. Other
    providers are skipped — schedule-driven-scraping is GotSport-only.

    With exclude_from_rankings, the team_ranking_exclusions row is written before
    the team or its alias, so a failed exclusion leaves no approved alias for a
    later import to link ranked games through; such a team is not enqueued.

    Returns (team_id_master, status) where status is one of:
    'created', 'exists_alias', 'exists_team', 'error'
    """
    # Guard: check alias first
    existing_alias = _alias_exists(supabase, provider_id, provider_team_id)
    if existing_alias:
        return existing_alias, "exists_alias"

    # Guard: check team table
    existing_team = _team_exists_by_provider(supabase, provider_id, provider_team_id)
    if existing_team:
        return existing_team, "exists_team"

    team_id_master = str(uuid.uuid4())

    if exclude_from_rankings and not exclude_coed_team(supabase, team_id_master, provider_team_id):
        return "", "error"

    # Create team record
    team_record = {
        "team_id_master": team_id_master,
        "provider_team_id": provider_team_id,
        "provider_id": provider_id,
        "team_name": meta["team_name"],
        "club_name": meta.get("club_name"),
        "state_code": meta.get("state_code"),
        "age_group": meta["age_group"],
        "gender": meta["gender"],
        "created_at": datetime.now().isoformat(),
    }

    try:
        result = _execute_with_retry(lambda: supabase.table("teams").insert(team_record).execute())
        if not result.data:
            return "", "error"
        team_id_master = result.data[0]["team_id_master"]
    except Exception as e:
        error_str = str(e).lower()
        if "unique" in error_str or "duplicate" in error_str:
            # Race condition — team was created between our check and insert
            existing = _team_exists_by_provider(supabase, provider_id, provider_team_id)
            if existing:
                team_id_master = existing
            else:
                print(f"  ERROR creating team: {e}")
                return "", "error"
        else:
            print(f"  ERROR creating team: {e}")
            return "", "error"

    # Create alias mapping
    alias_record = {
        "provider_id": provider_id,
        "provider_team_id": provider_team_id,
        "team_id_master": team_id_master,
        "match_confidence": 1.0,
        "match_method": "direct_id",
        "review_status": "approved",
        "created_at": datetime.now().isoformat(),
    }

    try:
        _execute_with_retry(
            lambda: (
                supabase.table("team_alias_map")
                .upsert(alias_record, on_conflict="provider_id,provider_team_id")
                .execute()
            )
        )
    except Exception as e:
        error_str = str(e).lower()
        if "unique" not in error_str and "duplicate" not in error_str:
            print(f"  WARNING: Team created but alias failed: {e}")

    # Schedule-driven-scraping hook: GotSport only.
    # Enqueue at priority 3 (discovery) so the new team enters the priority
    # queue and process_missing_games scrapes its schedule within ~15 min.
    # Other providers are out of scope; the queue is GotSport-only for now.
    if provider_code == "gotsport" and not exclude_from_rankings:
        try:
            _execute_with_retry(
                lambda: supabase.rpc(
                    "enqueue_scrape_request",
                    {
                        "p_team_id_master": team_id_master,
                        "p_team_name": meta.get("team_name") or "",
                        "p_provider_id": provider_id,
                        "p_provider_team_id": provider_team_id,
                        "p_game_date": date.today().isoformat(),
                        "p_request_type": "new_team",
                        "p_priority": 3,
                    },
                ).execute()
            )
        except Exception as e:
            # Enqueue failure is non-fatal: the safety-net sweep (priority 4)
            # will pick this team up within a week.
            print(f"  WARNING: Team {team_id_master} created but enqueue failed: {e}")

    return team_id_master, "created"


def backfill_games(
    supabase,
    provider_id: str,
    provider_team_id: str,
    team_id_master: str,
) -> Tuple[int, int]:
    """Backfill NULL home/away_team_master_id in games. Returns (home_count, away_count)."""
    home_count = (
        _execute_with_retry(
            lambda: (
                supabase.table("games")
                .select("id", count="exact", head=True)
                .eq("provider_id", provider_id)
                .eq("home_provider_id", provider_team_id)
                .is_("home_team_master_id", "null")
                .execute()
            )
        ).count
        or 0
    )

    away_count = (
        _execute_with_retry(
            lambda: (
                supabase.table("games")
                .select("id", count="exact", head=True)
                .eq("provider_id", provider_id)
                .eq("away_provider_id", provider_team_id)
                .is_("away_team_master_id", "null")
                .execute()
            )
        ).count
        or 0
    )

    if home_count > 0:
        _execute_with_retry(
            lambda: (
                supabase.table("games")
                .update({"home_team_master_id": team_id_master})
                .eq("provider_id", provider_id)
                .eq("home_provider_id", provider_team_id)
                .is_("home_team_master_id", "null")
                .execute()
            )
        )

    if away_count > 0:
        _execute_with_retry(
            lambda: (
                supabase.table("games")
                .update({"away_team_master_id": team_id_master})
                .eq("provider_id", provider_id)
                .eq("away_provider_id", provider_team_id)
                .is_("away_team_master_id", "null")
                .execute()
            )
        )

    return home_count, away_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover and create new teams from unmatched unknown opponents")
    parser.add_argument(
        "--match-report",
        required=True,
        help="Match report CSV from auto_match_unknown_opponents.py",
    )
    parser.add_argument(
        "--export-aggregate",
        default=None,
        help="Aggregate CSV from export_unknown_opponents.py; its GotSport lookups are reused, not repeated",
    )
    parser.add_argument(
        "--provider",
        default="gotsport",
        help="Provider code filter (default: gotsport)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually create teams and backfill games. Without this flag, runs in dry-run mode.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of no_match rows to process",
    )
    parser.add_argument(
        "--min-games",
        type=int,
        default=1,
        help="Minimum games an unknown opponent must appear in to be created (default: 1)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output report CSV path (default: data/exports/team_discovery_report_<timestamp>.csv)",
    )
    args = parser.parse_args()

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"=== Team Discovery from Unknown Opponents ({mode}) ===")

    load_env()
    supabase = get_supabase()

    # Look up provider ID
    providers = _execute_with_retry(lambda: supabase.table("providers").select("id,code,name").execute()).data or []
    code_to_id = {p["code"]: p["id"] for p in providers}

    provider_code = args.provider.lower()
    provider_id = code_to_id.get(provider_code)
    if not provider_id:
        raise ValueError(f"Unknown provider code: {provider_code}")

    # Read match report
    with open(args.match_report, "r", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    # Filter for no_match rows from the specified provider
    no_match_rows = [
        r
        for r in all_rows
        if (r.get("action") or "").strip() == "no_match"
        and (r.get("provider_code") or "").strip().lower() == provider_code
    ]

    # Deduplicate by unknown_provider_team_id (same team may appear on multiple sides)
    seen_pids: Dict[str, Dict[str, str]] = {}
    for row in no_match_rows:
        pid = (row.get("unknown_provider_team_id") or "").strip()
        if not pid:
            continue
        if pid not in seen_pids:
            seen_pids[pid] = row
        else:
            # Accumulate games_count
            existing_games = int(seen_pids[pid].get("games_count") or 0)
            new_games = int(row.get("games_count") or 0)
            seen_pids[pid]["games_count"] = str(existing_games + new_games)

    unique_rows = list(seen_pids.values())

    # Filter by minimum games
    if args.min_games > 1:
        unique_rows = [r for r in unique_rows if int(r.get("games_count") or 0) >= args.min_games]

    if args.limit:
        unique_rows = unique_rows[: args.limit]

    print(f"Provider: {provider_code} ({provider_id})")
    print(f"Total match report rows: {len(all_rows):,}")
    print(f"No-match rows (deduplicated): {len(unique_rows):,}")
    print(f"Min games filter: {args.min_games}")
    print()

    if not unique_rows:
        print("No unmatched opponents to process.")
        return

    resolver = GotSportResolver()
    if args.export_aggregate:
        print(f"GotSport lookups reused from the export: {seed_from_export(resolver, args.export_aggregate):,}")
        print()

    report_rows: List[Dict[str, object]] = []
    stats = {
        "total": 0,
        "created": 0,
        "created_coed_excluded": 0,
        "exists_alias": 0,
        "exists_team": 0,
        "skipped_metadata": 0,
        "skipped_api_empty": 0,
        "skipped_lookup_failed": 0,
        "error": 0,
        "games_backfilled_home": 0,
        "games_backfilled_away": 0,
    }

    for idx, row in enumerate(unique_rows, start=1):
        unknown_pid = (row.get("unknown_provider_team_id") or "").strip()
        games_count = int(row.get("games_count") or 0)
        stats["total"] += 1

        # Build metadata from CSV + API
        meta = _build_team_metadata(row, resolver)

        if unknown_pid in resolver.failed:
            stats["skipped_lookup_failed"] += 1
            report_rows.append(
                {
                    "unknown_provider_team_id": unknown_pid,
                    "games_count": games_count,
                    "action": "skipped_lookup_failed",
                    "team_name": meta.get("team_name") or "",
                    "club_name": "",
                    "age_group": "",
                    "gender": "",
                    "state_code": "",
                    "team_id_master": "",
                    "games_backfilled": 0,
                    "reason": "GotSport lookup failed; left for next week's run",
                }
            )
            continue

        if not meta.get("team_name"):
            stats["skipped_api_empty"] += 1
            report_rows.append(
                {
                    "unknown_provider_team_id": unknown_pid,
                    "games_count": games_count,
                    "action": "skipped_api_empty",
                    "team_name": "",
                    "club_name": "",
                    "age_group": "",
                    "gender": "",
                    "state_code": "",
                    "team_id_master": "",
                    "games_backfilled": 0,
                    "reason": "GotSport API returned no team name",
                }
            )
            continue

        if not _has_minimum_metadata(meta):
            stats["skipped_metadata"] += 1
            report_rows.append(
                {
                    "unknown_provider_team_id": unknown_pid,
                    "games_count": games_count,
                    "action": "skipped_metadata",
                    "team_name": meta.get("team_name") or "",
                    "club_name": meta.get("club_name") or "",
                    "age_group": meta.get("age_group") or "",
                    "gender": meta.get("gender") or "",
                    "state_code": meta.get("state_code") or "",
                    "team_id_master": "",
                    "games_backfilled": 0,
                    "reason": (
                        f"Missing: {', '.join(k for k in ('team_name', 'age_group', 'gender') if not meta.get(k))}"
                    ),
                }
            )
            continue

        coed = _is_coed(meta.get("provider_gender"))

        if args.execute:
            team_id_master, status = create_team_and_alias(
                supabase, provider_id, unknown_pid, meta, provider_code=provider_code, exclude_from_rankings=coed
            )
            created = status == "created"
            if created and coed:
                status = "created_coed_excluded"
            stats[status] = stats.get(status, 0) + 1

            home_bf, away_bf = 0, 0
            if created and team_id_master:
                home_bf, away_bf = backfill_games(supabase, provider_id, unknown_pid, team_id_master)
                stats["games_backfilled_home"] += home_bf
                stats["games_backfilled_away"] += away_bf

            report_rows.append(
                {
                    "unknown_provider_team_id": unknown_pid,
                    "games_count": games_count,
                    "action": status,
                    "team_name": meta.get("team_name") or "",
                    "club_name": meta.get("club_name") or "",
                    "age_group": meta.get("age_group") or "",
                    "gender": meta.get("gender") or "",
                    "state_code": meta.get("state_code") or "",
                    "team_id_master": team_id_master or "",
                    "games_backfilled": home_bf + away_bf,
                    "reason": "",
                }
            )

            if created:
                print(
                    f"  [{idx}/{len(unique_rows)}] CREATED{' (coed, excluded)' if coed else ''} {meta['team_name']} "
                    f"({meta['age_group']} {meta['gender']}) -> {team_id_master} "
                    f"(backfilled {home_bf + away_bf} games)"
                )
        else:
            # Dry run — check if already exists
            existing = _alias_exists(supabase, provider_id, unknown_pid)
            if existing:
                stats["exists_alias"] += 1
                status = "would_skip_exists"
            else:
                existing_team = _team_exists_by_provider(supabase, provider_id, unknown_pid)
                if existing_team:
                    stats["exists_team"] += 1
                    status = "would_skip_exists"
                elif coed:
                    stats["created_coed_excluded"] += 1
                    status = "would_create_coed_excluded"
                else:
                    stats["created"] += 1  # would-be-created
                    status = "would_create"

            report_rows.append(
                {
                    "unknown_provider_team_id": unknown_pid,
                    "games_count": games_count,
                    "action": status,
                    "team_name": meta.get("team_name") or "",
                    "club_name": meta.get("club_name") or "",
                    "age_group": meta.get("age_group") or "",
                    "gender": meta.get("gender") or "",
                    "state_code": meta.get("state_code") or "",
                    "team_id_master": existing or "",
                    "games_backfilled": 0,
                    "reason": "",
                }
            )

        if idx % 100 == 0:
            print(f"  Processed {idx}/{len(unique_rows)} rows...")

    # Write report CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output or f"data/exports/team_discovery_report_{timestamp}.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if report_rows:
        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(report_rows[0].keys()))
            writer.writeheader()
            writer.writerows(report_rows)

    # Summary
    print()
    print(f"=== Team Discovery Summary ({mode}) ===")
    print(f"Total no_match rows processed: {stats['total']:,}")
    if args.execute:
        print(f"Teams created: {stats['created']:,}")
        print(f"Already existed (alias): {stats['exists_alias']:,}")
        print(f"Already existed (team): {stats['exists_team']:,}")
        print(f"Skipped (no API data): {stats['skipped_api_empty']:,}")
        print(f"Skipped (insufficient metadata): {stats['skipped_metadata']:,}")
        print(f"Skipped (GotSport lookup failed, left for next week): {stats['skipped_lookup_failed']:,}")
        print(f"Coed teams created excluded from rankings: {stats['created_coed_excluded']:,}")
        print(f"Errors: {stats['error']:,}")
        print(f"Games backfilled (home): {stats['games_backfilled_home']:,}")
        print(f"Games backfilled (away): {stats['games_backfilled_away']:,}")
    else:
        print(f"Would create: {stats['created']:,}")
        print(f"Would skip (already exists): {stats['exists_alias'] + stats['exists_team']:,}")
        print(f"Skipped (no API data): {stats['skipped_api_empty']:,}")
        print(f"Skipped (insufficient metadata): {stats['skipped_metadata']:,}")
        print(f"Skipped (GotSport lookup failed, left for next week): {stats['skipped_lookup_failed']:,}")
        print(f"Would create excluded from rankings (coed): {stats['created_coed_excluded']:,}")
    print(f"Report CSV: {output_path}")

    # Print CI-friendly key lines
    print(f"DISCOVERY_TOTAL={stats['total']}")
    print(f"DISCOVERY_CREATED={stats['created']}")
    print(f"DISCOVERY_SKIPPED_METADATA={stats['skipped_metadata']}")
    print(f"DISCOVERY_SKIPPED_API_EMPTY={stats['skipped_api_empty']}")
    print(f"DISCOVERY_SKIPPED_LOOKUP_FAILED={stats['skipped_lookup_failed']}")
    print(f"DISCOVERY_COED_EXCLUDED={stats['created_coed_excluded']}")
    print(f"DISCOVERY_ERRORS={stats['error']}")
    print(f"DISCOVERY_GAMES_BACKFILLED={stats['games_backfilled_home'] + stats['games_backfilled_away']}")

    # Print sample created teams
    created_rows = [r for r in report_rows if r["action"] in ("created", "would_create")]
    if created_rows:
        print(f"\nTop 10 {'created' if args.execute else 'would-be-created'} teams:")
        for i, r in enumerate(created_rows[:10], start=1):
            print(
                f"  {i:>2}. [{r['unknown_provider_team_id']}] {r['team_name']} "
                f"({r['age_group']} {r['gender']}, {r['state_code']}) "
                f"games={r['games_count']}"
            )


if __name__ == "__main__":
    main()
