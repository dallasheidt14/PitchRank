#!/usr/bin/env python3
"""
Correct teams whose stored gender contradicts an unambiguous marker in their name.

auto_match_unknown_opponents.py copies age and gender from the known team on the
other side of a game when it cannot identify the unknown side. One wrong team
therefore infects every unknown opponent it faces, and each team created that way
becomes a "known" team that infects the next batch — a girls U8 cluster in San
Diego picked up Male/u12 this way.

Only gender is corrected. The name markers for it (GU8, "Boys") are unambiguous,
whereas a U-number in a name goes stale at the Aug 1 rollover and cannot be read
as the team's current cohort.

A team is only touched when its name carries a marker for one gender and none for
the other, so "2013 Boys/Girls Rec" is left alone.

Examples:
    python3 scripts/fix_team_gender_from_name.py --dry-run
    python3 scripts/fix_team_gender_from_name.py
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

from supabase import create_client

# Require a U-number or the whole word, so a club like "Girls Inc" or a coach
# surname starting with G cannot match.
GIRLS_MARKER = re.compile(r"\b(?:G\s?U\s?\d{1,2}|GU\d{1,2}|girls?)\b", re.I)
BOYS_MARKER = re.compile(r"\b(?:B\s?U\s?\d{1,2}|BU\d{1,2}|boys?)\b", re.I)


def log(message: str) -> None:
    print(message, flush=True)


def gender_from_name(team_name: Optional[str]) -> Optional[str]:
    """Return the gender a name unambiguously states, or None when it does not."""
    name = (team_name or "").strip()
    if not name:
        return None
    girls = bool(GIRLS_MARKER.search(name))
    boys = bool(BOYS_MARKER.search(name))
    if girls and not boys:
        return "Female"
    if boys and not girls:
        return "Male"
    return None


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


def fetch_contradicted_teams(supabase, limit: Optional[int]) -> List[Tuple[Dict, str]]:
    """Live teams whose name states a gender their stored value contradicts."""
    page_size = 1000
    offset = 0
    out: List[Tuple[Dict, str]] = []

    while True:
        batch = (
            supabase.table("teams")
            .select("team_id_master,team_name,club_name,gender,age_group,provider_team_id")
            .eq("is_deprecated", False)
            .range(offset, offset + page_size - 1)
            .execute()
            .data
            or []
        )
        if not batch:
            break
        for row in batch:
            stated = gender_from_name(row.get("team_name"))
            if stated and row.get("gender") and row["gender"] != stated:
                out.append((row, stated))
                if limit and len(out) >= limit:
                    return out
        if len(batch) < page_size:
            break
        offset += page_size

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix team gender that contradicts the team name")
    parser.add_argument("--dry-run", action="store_true", help="Preview updates without writing to DB")
    parser.add_argument("--limit", type=int, default=None, help="Max teams to correct (default: all)")
    args = parser.parse_args()

    load_env()
    supabase = get_supabase()

    teams = fetch_contradicted_teams(supabase, args.limit)
    if not teams:
        log("No teams contradict their name.")
        return

    log(f"=== Fix Team Gender From Name ({'DRY RUN' if args.dry_run else 'LIVE'}) ===")
    log(f"Found {len(teams):,} teams whose stored gender contradicts their name")
    log("")

    updated = 0
    errors = 0

    for team, stated in teams:
        label = f"{team['team_name'][:46]:<46} {team['gender']} -> {stated}"
        if args.dry_run:
            log(f"  [DRY-RUN] {label}")
            updated += 1
            continue
        try:
            supabase.table("teams").update({"gender": stated}).eq("team_id_master", team["team_id_master"]).execute()
            updated += 1
            log(f"  {label}")
        except Exception as e:
            errors += 1
            log(f"  ERROR updating {team['team_id_master']}: {e}")

    log("")
    log("=== Summary ===")
    log(f"Corrected: {updated:,}")
    log(f"Errors: {errors:,}")
    log("Age group deliberately untouched — a U-number in a name goes stale at the Aug 1 rollover.")


if __name__ == "__main__":
    main()
