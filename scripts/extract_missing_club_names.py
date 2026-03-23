#!/usr/bin/env python3
"""
Conservatively backfill missing club names by extracting them from team_name.

This script is intended to run after `backfill_missing_club_names.py`.
It only updates teams that still have no club_name and where:

1. The team has a state_code
2. A plausible club name can be extracted from team_name
3. The extracted name maps conservatively to exactly one existing club
   already present in that same state

Examples:
    python3 scripts/extract_missing_club_names.py --dry-run
    python3 scripts/extract_missing_club_names.py --limit 100
    python3 scripts/extract_missing_club_names.py
"""

from __future__ import annotations

import argparse
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import DefaultDict, Dict, List, Optional, Set

from dotenv import load_dotenv
from supabase import create_client


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

AGE_PATTERNS = [
    r"\b[BG]?20\d{2}[BG]?\b",
    r"\bU-?\d{1,2}[BG]?\b",
    r"\b[BG]\d{2}(?!\d)\b",
    r"\b\d{2}[BG](?!\d)\b",
    r"\b\d{2}/\d{2}\b",
    r"\bBoys\b",
    r"\bGirls\b",
    r"\bMen\b",
    r"\bWomen\b",
]

LEADING_AGE_RE = re.compile(
    r"^(?:[BG]?20\d{2}[BG]?|U-?\d{1,2}[BG]?|[BG]\d{2}|\d{2}[BG])\s+",
    re.IGNORECASE,
)

TEAM_IDENTIFIER_WORDS = {
    "black",
    "blue",
    "red",
    "white",
    "navy",
    "gold",
    "orange",
    "green",
    "purple",
    "silver",
    "grey",
    "gray",
    "yellow",
    "pink",
    "maroon",
    "teal",
    "academy",
    "premier",
    "elite",
    "select",
    "development",
    "competitive",
    "north",
    "south",
    "east",
    "west",
    "central",
    "ecnl",
    "ecnl-rl",
    "ecrl",
    "rl",
    "mls",
    "next",
    "npl",
    "dpl",
    "ga",
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    "1",
    "2",
    "3",
    "4",
    "5",
}

GENERIC_TERMS = {
    "fc",
    "sc",
    "united",
    "city",
    "west",
    "east",
    "north",
    "south",
    "academy",
    "premier",
    "elite",
    "select",
    "blue",
    "red",
    "white",
    "black",
    "gold",
    "green",
    "boys",
    "girls",
}

RISK_DIRECTION_RE = re.compile(r"\b(north|south|east|west|central)\b", re.IGNORECASE)
RISK_ACADEMY_RE = re.compile(r"\bacademy\b", re.IGNORECASE)
RISK_PROGRAM_RE = re.compile(
    r"\b(select|premier|elite|ecnl|ecnl-rl|ecrl|rl|ga|mls next)\b",
    re.IGNORECASE,
)


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


def _is_missing_club(club: Optional[str]) -> bool:
    return not str(club or "").strip()


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


def fetch_teams_without_club(supabase, limit: Optional[int]) -> List[Dict]:
    """Teams where club_name is NULL or empty. Excludes deprecated."""
    page_size = 1000
    rows: List[Dict] = []
    seen: Set[str] = set()

    for filter_fn in [
        lambda q: q.is_("club_name", "null"),
        lambda q: q.eq("club_name", ""),
    ]:
        offset = 0
        while True:
            query = (
                supabase.table("teams")
                .select("team_id_master,team_name,club_name,state_code,age_group,gender")
                .eq("is_deprecated", False)
            )
            batch = (
                filter_fn(query).range(offset, offset + page_size - 1).execute().data or []
            )
            if not batch:
                break
            for row in batch:
                team_id = row.get("team_id_master")
                if team_id and team_id not in seen and _is_missing_club(row.get("club_name")):
                    seen.add(team_id)
                    rows.append(row)
            if limit and len(rows) >= limit:
                return rows[:limit]
            if len(batch) < page_size:
                break
            offset += page_size

    return rows[:limit] if limit else rows


def fetch_existing_clubs_by_state(supabase, state_codes: Set[str]) -> Dict[str, Counter]:
    """Return state_code -> Counter(existing valid club names)."""
    valid_states = sorted({s.strip() for s in state_codes if str(s or "").strip()})
    clubs_by_state: DefaultDict[str, Counter] = defaultdict(Counter)
    page_size = 1000

    for i in range(0, len(valid_states), 20):
        state_batch = valid_states[i : i + 20]
        offset = 0
        while True:
            rows = (
                supabase.table("teams")
                .select("state_code,club_name")
                .eq("is_deprecated", False)
                .in_("state_code", state_batch)
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
                state_code = str(row.get("state_code") or "").strip()
                club_name = str(row.get("club_name") or "").strip()
                if state_code and _is_valid_club(club_name):
                    clubs_by_state[state_code][club_name] += 1
            if len(rows) < page_size:
                break
            offset += page_size

    return dict(clubs_by_state)


def extract_club_name(team_name: Optional[str]) -> Optional[str]:
    """Extract the club part of team_name using conservative heuristics."""
    if not team_name or not isinstance(team_name, str):
        return None

    original = team_name.strip()
    if not original:
        return None

    working = LEADING_AGE_RE.sub("", original, count=1).strip()

    earliest_pos = len(working)
    found_age = False
    for pattern in AGE_PATTERNS:
        match = re.search(pattern, working, re.IGNORECASE)
        if match and match.start() < earliest_pos:
            earliest_pos = match.start()
            found_age = True

    if found_age and 0 < earliest_pos < len(working):
        club = working[:earliest_pos].strip()
    elif found_age:
        club = ""
    else:
        club = working

    club = club.strip(" -–—.")
    words = club.split()

    while words and words[-1].lower() in TEAM_IDENTIFIER_WORDS:
        words.pop()
    while words and words[-1].isdigit():
        words.pop()
    while words and len(words[-1]) == 1 and words[-1].lower() in {"b", "g", "m", "f"}:
        words.pop()

    if len(words) >= 4:
        midpoint = len(words) // 2
        first_half = " ".join(words[:midpoint])
        second_half = " ".join(words[midpoint : midpoint * 2])
        if first_half.lower() == second_half.lower():
            words = words[:midpoint]

    extracted = " ".join(words).strip(" -–—.")
    if not _is_valid_club(extracted):
        return None
    if extracted == original:
        return None
    return extracted


def find_conservative_match(extracted: Optional[str], existing_clubs: Counter) -> Optional[str]:
    """Return one safe in-state club match, otherwise None."""
    if not extracted:
        return None
    if len(extracted) < 4:
        return None

    extracted_lower = extracted.lower()
    if extracted_lower in GENERIC_TERMS:
        return None

    clubs = list(existing_clubs.keys())

    for club in clubs:
        if club.lower() == extracted_lower:
            return club

    matching_clubs = [club for club in clubs if club.lower().startswith(extracted_lower)]
    if len(matching_clubs) > 1:
        return None
    if len(matching_clubs) == 1:
        club = matching_clubs[0]
        if len(extracted) >= len(club) * 0.7:
            return club

    reverse_matches = [club for club in clubs if extracted_lower.startswith(club.lower())]
    if len(reverse_matches) > 1:
        return None
    if len(reverse_matches) == 1:
        club = reverse_matches[0]
        if len(club) >= len(extracted) * 0.85:
            return club

    return None


def get_risk_flags(
    team_name: str, extracted: Optional[str], matched_club: Optional[str]
) -> List[str]:
    """Return risk flags used to keep Step 2 in safe-only mode."""
    if not extracted or not matched_club:
        return []

    flags: List[str] = []
    extracted_lower = extracted.lower()
    matched_lower = matched_club.lower()

    if extracted_lower != matched_lower:
        flags.append("non_exact_match")
    if RISK_DIRECTION_RE.search(team_name):
        flags.append("direction_token_in_team_name")
    if RISK_ACADEMY_RE.search(team_name):
        flags.append("academy_token_in_team_name")
    if RISK_PROGRAM_RE.search(team_name):
        flags.append("program_token_in_team_name")
    if matched_lower.startswith(extracted_lower) and extracted_lower != matched_lower:
        flags.append("prefix_completion")
    if len(extracted) <= 5:
        flags.append("short_extracted_name")

    return flags


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Conservatively backfill missing club names from team_name"
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

    teams = fetch_teams_without_club(supabase, args.limit)
    if not teams:
        print("No teams with missing club_name found.")
        return

    states = {str(team.get("state_code") or "").strip() for team in teams}
    existing_clubs_by_state = fetch_existing_clubs_by_state(supabase, states)

    print("=== Extract Missing Club Names ===")
    print(f"Teams with no club: {len(teams):,}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print(f"States with club lookup: {len(existing_clubs_by_state):,}")
    print("")

    updated = 0
    skipped_no_state = 0
    skipped_no_lookup = 0
    skipped_unextractable = 0
    skipped_no_match = 0
    skipped_risky = 0
    failed = 0
    sample_count = 0

    for team in teams:
        team_id = team["team_id_master"]
        team_name = str(team.get("team_name") or "").strip()
        state_code = str(team.get("state_code") or "").strip()

        if not state_code:
            skipped_no_state += 1
            continue

        existing_clubs = existing_clubs_by_state.get(state_code)
        if not existing_clubs:
            skipped_no_lookup += 1
            continue

        extracted = extract_club_name(team_name)
        if not extracted:
            skipped_unextractable += 1
            continue

        matched_club = find_conservative_match(extracted, existing_clubs)
        if not matched_club:
            skipped_no_match += 1
            continue

        risk_flags = get_risk_flags(team_name, extracted, matched_club)
        if risk_flags:
            skipped_risky += 1
            continue

        if args.dry_run:
            if sample_count < 25:
                print(
                    f"  [DRY-RUN] {state_code} | {team_name[:45]}... -> "
                    f"'{extracted}' => '{matched_club}'"
                )
                sample_count += 1
            updated += 1
            continue

        try:
            supabase.table("teams").update({"club_name": matched_club}).eq(
                "team_id_master", team_id
            ).execute()
            updated += 1
            if updated <= 25 or updated % 100 == 0:
                print(
                    f"  Updated {state_code} | {team_name[:45]}... -> {matched_club}",
                    flush=True,
                )
        except Exception as exc:
            failed += 1
            print(f"  ERROR updating {team_id}: {exc}", flush=True)

    print("")
    print("=== Summary ===")
    print(f"Updated: {updated:,}")
    print(f"Skipped (no state_code): {skipped_no_state:,}")
    print(f"Skipped (state had no club lookup): {skipped_no_lookup:,}")
    print(f"Skipped (could not extract club): {skipped_unextractable:,}")
    print(f"Skipped (no conservative in-state match): {skipped_no_match:,}")
    print(f"Skipped (risky match pattern): {skipped_risky:,}")
    print(f"Skipped (DB error): {failed:,}")


if __name__ == "__main__":
    main()
