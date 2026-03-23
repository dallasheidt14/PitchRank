#!/usr/bin/env python3
"""
Conservatively backfill missing state codes from club names.

This script is intended to run after:
1. backfill_missing_club_names.py
2. extract_missing_club_names.py

It updates teams with missing state_code only when a safe club-to-state match
can be inferred from:
- an existing club_name on the team, or
- a safe club extraction from team_name

It only applies matches when the club resolves to exactly one state in the
existing teams table.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import DefaultDict, Dict, List, Optional, Set

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.extract_missing_club_names import (
    NO_CLUB_VALUES,
    extract_club_name,
    get_risk_flags,
)


STATE_CODE_TO_NAME = {
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
VALID_STATE_CODES = frozenset(STATE_CODE_TO_NAME.keys())
STATE_IN_PARENS_RE = re.compile(r"\s*\(([A-Z]{2})\)\s*$", re.IGNORECASE)
ACRONYM_CLUB_RE = re.compile(r"[A-Z0-9& ]{2,5}")


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


def _is_valid_club(club: Optional[str]) -> bool:
    if not club or not isinstance(club, str):
        return False
    value = club.strip()
    if not value or len(value) < 2:
        return False
    lowered = value.lower()
    if lowered in NO_CLUB_VALUES:
        return False
    if lowered.startswith("no ") or lowered.startswith("select"):
        return False
    return True


def strip_state_from_club_name(name: Optional[str]) -> str:
    if not name or not isinstance(name, str):
        return ""
    return STATE_IN_PARENS_RE.sub("", name.strip()).strip()


def extract_state_from_club_name(name: Optional[str]) -> Optional[str]:
    if not name or not isinstance(name, str):
        return None
    match = STATE_IN_PARENS_RE.search(name.strip())
    if not match:
        return None
    code = match.group(1).upper()
    return code if code in VALID_STATE_CODES else None


def normalize_club_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    name = strip_state_from_club_name(name)
    if not name:
        return None
    normalized = name.lower().strip()
    normalized = re.sub(r"\s+soccer\s+club\s*$", " sc", normalized)
    normalized = re.sub(r"\s+s\.c\.\s*$", " sc", normalized)
    normalized = re.sub(r"\s+football\s+club\s*$", " fc", normalized)
    normalized = re.sub(r"\s+futbol\s+club\s*$", " fc", normalized)
    normalized = re.sub(r"\s+f\.c\.\s*$", " fc", normalized)
    normalized = re.sub(r"\s+f\.c\s*$", " fc", normalized)
    return normalized.strip() or None


def fetch_teams_without_state(supabase, limit: Optional[int]) -> List[Dict]:
    page_size = 1000
    rows: List[Dict] = []
    seen: Set[str] = set()

    for filter_fn in [
        lambda q: q.is_("state_code", "null"),
        lambda q: q.eq("state_code", ""),
    ]:
        offset = 0
        while True:
            query = (
                supabase.table("teams")
                .select("team_id_master,team_name,club_name,state,state_code,age_group,gender")
                .eq("is_deprecated", False)
            )
            batch = (
                filter_fn(query).range(offset, offset + page_size - 1).execute().data or []
            )
            if not batch:
                break
            for row in batch:
                team_id = row.get("team_id_master")
                if team_id and team_id not in seen:
                    seen.add(team_id)
                    rows.append(row)
            if limit and len(rows) >= limit:
                return rows[:limit]
            if len(batch) < page_size:
                break
            offset += page_size

    return rows[:limit] if limit else rows


def build_club_state_lookups(supabase) -> tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    page_size = 1000
    normalized_lookup: DefaultDict[str, Set[str]] = defaultdict(set)
    exact_lookup: DefaultDict[str, Set[str]] = defaultdict(set)
    offset = 0

    while True:
        rows = (
            supabase.table("teams")
            .select("club_name,state_code")
            .eq("is_deprecated", False)
            .not_.is_("state_code", "null")
            .neq("state_code", "")
            .not_.is_("club_name", "null")
            .neq("club_name", "")
            .range(offset, offset + page_size - 1)
            .execute()
            .data
            or []
        )
        if not rows:
            break
        for row in rows:
            club_name = str(row.get("club_name") or "").strip()
            state_code = str(row.get("state_code") or "").strip().upper()
            if not _is_valid_club(club_name) or state_code not in VALID_STATE_CODES:
                continue
            exact_lookup[club_name].add(state_code)
            normalized = normalize_club_name(club_name)
            if normalized:
                normalized_lookup[normalized].add(state_code)
        if len(rows) < page_size:
            break
        offset += page_size

    return dict(normalized_lookup), dict(exact_lookup)


def get_state_match_risk_flags(
    team_name: str,
    club_name: str,
    source_type: str,
    source_club: str,
    match_method: str,
) -> List[str]:
    """Return risk flags so Step 3 only applies safe state matches."""
    flags: List[str] = []
    stripped_source = source_club.strip()

    if source_type == "team_name_extracted":
        flags.append("team_name_extracted_source")
    else:
        if len(stripped_source) <= 5:
            flags.append("short_club_name_source")
        if ACRONYM_CLUB_RE.fullmatch(stripped_source):
            flags.append("acronym_club_name_source")

    if match_method != "exact_single_state":
        flags.append(match_method)

    if source_type == "club_name" and re.search(r"\bacademy\b", team_name, re.IGNORECASE):
        flags.append("academy_token_in_team_name")

    return flags


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Conservatively backfill missing state codes from club names"
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
    args = parser.parse_args()

    load_env()
    supabase = get_supabase()

    teams = fetch_teams_without_state(supabase, args.limit)
    if not teams:
        print("No teams with missing state_code found.")
        return

    normalized_lookup, exact_lookup = build_club_state_lookups(supabase)

    print("=== Match Missing State Codes ===")
    print(f"Teams with no state_code: {len(teams):,}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print(f"Normalized club lookup size: {len(normalized_lookup):,}")
    print("")

    updated = 0
    skipped_no_club = 0
    skipped_risky_extraction = 0
    skipped_no_match = 0
    skipped_multi_state = 0
    failed = 0
    sample_count = 0

    for team in teams:
        team_id = team["team_id_master"]
        team_name = str(team.get("team_name") or "").strip()
        club_name = str(team.get("club_name") or "").strip()

        source_club: Optional[str] = None
        source_type = "club_name"

        if _is_valid_club(club_name):
            source_club = club_name
        else:
            extracted = extract_club_name(team_name)
            if not extracted:
                skipped_no_club += 1
                continue
            extraction_risks = get_risk_flags(team_name, extracted, extracted)
            if extraction_risks:
                skipped_risky_extraction += 1
                continue
            source_club = extracted
            source_type = "team_name_extracted"

        state_from_name = extract_state_from_club_name(source_club)
        if state_from_name:
            matched_states = {state_from_name}
            match_method = "from_club_name_parens"
        else:
            exact_states = exact_lookup.get(source_club, set())
            normalized = normalize_club_name(source_club)
            normalized_states = normalized_lookup.get(normalized, set()) if normalized else set()
            matched_states = exact_states | normalized_states
            if exact_states and len(exact_states) == 1 and exact_states == matched_states:
                match_method = "exact_single_state"
            elif normalized_states and len(normalized_states) == 1 and normalized_states == matched_states:
                match_method = "normalized_single_state"
            else:
                match_method = "combined_single_state"

        if not matched_states:
            skipped_no_match += 1
            continue
        if len(matched_states) > 1:
            skipped_multi_state += 1
            continue

        risk_flags = get_state_match_risk_flags(
            team_name=team_name,
            club_name=club_name,
            source_type=source_type,
            source_club=source_club,
            match_method=match_method,
        )
        if risk_flags:
            skipped_risky_extraction += 1
            continue

        matched_state_code = next(iter(matched_states))
        matched_state_name = STATE_CODE_TO_NAME.get(matched_state_code)

        if args.dry_run:
            if sample_count < 25:
                print(
                    f"  [DRY-RUN] {team_name[:45]}... | "
                    f"{source_type}: '{source_club}' -> {matched_state_code}"
                )
                sample_count += 1
            updated += 1
            continue

        try:
            supabase.table("teams").update(
                {"state_code": matched_state_code, "state": matched_state_name}
            ).eq("team_id_master", team_id).execute()
            updated += 1
            if updated <= 25 or updated % 100 == 0:
                print(
                    f"  Updated {team_name[:45]}... -> {matched_state_code}",
                    flush=True,
                )
        except Exception as exc:
            failed += 1
            print(f"  ERROR updating {team_id}: {exc}", flush=True)

    print("")
    print("=== Summary ===")
    print(f"Updated: {updated:,}")
    print(f"Skipped (no usable club): {skipped_no_club:,}")
    print(f"Skipped (risky team-name extraction): {skipped_risky_extraction:,}")
    print(f"Skipped (no state match): {skipped_no_match:,}")
    print(f"Skipped (multiple possible states): {skipped_multi_state:,}")
    print(f"Skipped (DB error): {failed:,}")


if __name__ == "__main__":
    main()
