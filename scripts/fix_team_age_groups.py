#!/usr/bin/env python3
"""
Fix team age_groups based on birth year in team names.

This script finds teams where the age_group doesn't match the birth year
indicated in the team name (e.g., "ILLINOIS MAGIC FC 2014" should be U12, not U13).

Usage:
    python scripts/fix_team_age_groups.py --dry-run  # Preview changes
    python scripts/fix_team_age_groups.py            # Apply fixes
"""

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load .env.local first if it exists
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

from src.utils.team_utils import CURRENT_YEAR  # noqa: E402
from supabase import create_client  # noqa: E402


def calculate_age_group(birth_year: int) -> str:
    """Calculate age group from birth year.

    Formula: age_group = CURRENT_YEAR - birth_year + 1
    Season year rolls over on Aug 1.
    U18 is merged into U19 to match the canonical AGE_GROUPS keyset
    (config/settings.py) and team_name_utils.canonicalize_age_group.
    """
    age = CURRENT_YEAR - birth_year + 1
    if age == 18:
        age = 19
    if 7 <= age <= 19:
        return f"u{age}"
    return None


# Generic noise tokens stripped from club_name when computing skip tokens.
# Mirrors scripts/dryrun_team_distinction.py:_CLUB_NOISE — keep in sync.
_CLUB_NOISE = {
    "fc", "sc", "sa", "ac", "cf", "cd", "fcs", "ysa",
    "soccer", "club", "futbol", "football", "youth", "academy",
    "the", "of", "and", "association",
}


def _club_tokens(club_name: str | None) -> set:
    """Lowercase tokens of the club name (minus noise), with 4-digit expansion.

    For each 2-digit numeric token in the 06-18 range, also add its 4-digit
    `f"20{n:02d}"` form to the set. This catches club names like "Union 10 FC"
    where the polluted team_name `"Union 2010 FC 2008"` has `2010` matched by
    the regex but the literal club_skip_tokens only contains `"10"` — the
    expansion adds `"2010"` so the polluted year is correctly skipped.
    """
    if not club_name:
        return set()
    toks = re.split(r"[\s\-_./]+", club_name.lower())
    out = set()
    for t in toks:
        t = t.strip("()[]'*.,")
        if not t or t in _CLUB_NOISE or len(t) < 2:
            continue
        out.add(t)
    # 4-digit expansion for 2-digit numeric tokens in birth-year range
    expanded = set(out)
    for tok in out:
        if tok.isdigit() and len(tok) == 2 and 6 <= int(tok) <= 18:
            expanded.add(f"20{tok}")
    return expanded


def extract_birth_year(
    team_name: str,
    club_name: str | None = None,
    team_name_original: str | None = None,
) -> int | None:
    """Extract birth year from team name.

    Handles multiple formats:
    - Single year: "Team 2014" → 2014
    - Two years with slash: "Team 2013/2014" → 2013 (older/primary cohort)
    - Two years with dash: "Team 2009-2010" → 2009 (older/primary cohort)
    - Two years after letter: "B2013/2014" → 2013 (older/primary cohort)

    PitchRank business rule (per Dallas, 2026-05-01): for dual-age teams
    we always take the OLDER cohort — older birth year (smaller number) for
    year pairs, higher U-age for U-age pairs. Both forms refer to the
    same older players. So 2012/2013 → 2012 (= U14), and u10/u11 → u11.

    Source preference:
      When ``team_name_original`` is provided and non-empty, parse from it
      (the raw provider name preserved by ``normalize_team_names.py``).
      Otherwise fall back to ``team_name``. This avoids re-parsing
      pollution-affected rows where Step 1 of the weekly hygiene workflow
      previously rewrote a 2-digit shorthand like ``"10"`` (in club name
      "Union 10 FC") to ``"2010"``.

    Club-token skip:
      Years matching tokens of the team's own ``club_name`` are skipped
      (e.g., "Union 2010 FC 2008" with club_name "Union 10 FC" returns
      2008, not 2010). The skip set is expanded so 2-digit club tokens
      catch their 4-digit equivalents — see ``_club_tokens``.

    Returns the birth year if found and valid, None otherwise.
    """
    parsing_source = team_name_original if team_name_original else team_name
    if not parsing_source:
        return None
    skip = _club_tokens(club_name)

    # First, check for two-year patterns like "2013/2014" or "2009-2010" or "B2013/2014"
    # Note: Using (?<![0-9]) instead of \b to allow patterns like "B2013/2014"
    two_year_match = re.search(r"(?<![0-9])(20\d{2})[/-](20\d{2})(?![0-9])", parsing_source)
    if two_year_match:
        year1 = int(two_year_match.group(1))
        year2 = int(two_year_match.group(2))
        # Drop years that match a club token before picking older
        candidates = [y for y in (year1, year2) if str(y) not in skip]
        if candidates:
            year = min(candidates)
            if 2005 <= year <= 2018:
                return year

    # Also check for patterns like "2013/14" or "2009/10" or "B2007/08" (short second year)
    short_year_match = re.search(r"(?<![0-9])(20\d{2})[/-](\d{2})(?![0-9])", parsing_source)
    if short_year_match:
        year1 = int(short_year_match.group(1))
        year2_short = int(short_year_match.group(2))
        # Convert short year to full year (e.g., 14 -> 2014)
        year2 = 2000 + year2_short
        candidates = [y for y in (year1, year2) if str(y) not in skip]
        if candidates:
            year = min(candidates)
            if 2005 <= year <= 2018:
                return year

    # Fall back to single year match — iterate ALL matches so we can skip
    # club-token years and continue to the next plausible birth year.
    for match in re.finditer(r"(?<![0-9])(20\d{2})(?![0-9])", parsing_source):
        year = int(match.group(1))
        if str(year) in skip:
            continue
        # Validate it's a reasonable birth year (2005-2018 for youth soccer)
        if 2005 <= year <= 2018:
            return year
    return None


def _load_ids_from_csv(path: str) -> set:
    """Load team IDs from a CSV with an `id` column (e.g.,
    logs/age_misclass_candidates.csv produced by dryrun_investigate_c_and_d.py).
    """
    import csv
    ids = set()
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tid = row.get("id") or row.get("team_id_master")
            if tid:
                ids.add(tid)
    return ids


def main():
    parser = argparse.ArgumentParser(description="Fix team age_groups based on birth year in names")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    parser.add_argument("--team-name", type=str, help="Fix only teams matching this name (partial match)")
    parser.add_argument(
        "--ids-from-csv",
        type=str,
        default=None,
        help=(
            "Path to a CSV file (with `id` or `team_id_master` column) restricting "
            "the run to those IDs. Useful for targeted sweeps over the misclass "
            "candidate set produced by scripts/dryrun_investigate_c_and_d.py."
        ),
    )
    args = parser.parse_args()

    # Initialize Supabase client
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        print("❌ Missing SUPABASE_URL or SUPABASE_KEY environment variables")
        sys.exit(1)

    client = create_client(supabase_url, supabase_key)

    print("=" * 70)
    print("TEAM AGE GROUP FIX SCRIPT")
    print("=" * 70)
    print(f"Current Year: {CURRENT_YEAR}")
    print(f"Mode: {'DRY RUN (no changes)' if args.dry_run else 'LIVE (applying changes)'}")
    print()

    # Fetch all teams with pagination
    print("📥 Fetching teams from database...")

    teams = []
    offset = 0
    batch_size = 1000

    while True:
        query = (
            client.table("teams")
            .select(
                "id, team_id_master, team_name, team_name_original, club_name, "
                "age_group, birth_year, gender, state_code"
            )
            .eq("is_deprecated", False)
        )

        if args.team_name:
            query = query.ilike("team_name", f"%{args.team_name}%")

        query = query.range(offset, offset + batch_size - 1)
        result = query.execute()

        if not result.data:
            break

        teams.extend(result.data)
        print(f"   Fetched {len(teams)} teams...")

        if len(result.data) < batch_size:
            break

        offset += batch_size

    print(f"✅ Found {len(teams)} teams total")

    # Restrict to a CSV-supplied ID set when --ids-from-csv is passed.
    # Used for targeted sweeps over the misclass candidate list produced
    # by scripts/dryrun_investigate_c_and_d.py.
    if args.ids_from_csv:
        target_ids = _load_ids_from_csv(args.ids_from_csv)
        before = len(teams)
        # CSV from dryrun_investigate_c_and_d.py uses `teams.id` (UUID).
        # Filter against both `id` and `team_id_master` so either CSV format works.
        teams = [
            t for t in teams
            if t.get("id") in target_ids or t.get("team_id_master") in target_ids
        ]
        print(f"📋 Restricted to {len(teams)}/{before} teams from {args.ids_from_csv}")
    print()

    # Find mismatches
    mismatches = []

    for team in teams:
        team_name = team.get("team_name", "")
        current_age_group = (team.get("age_group") or "").lower()

        # Extract birth year from team name (prefers team_name_original when
        # present and skips numbers that belong to the team's own club_name).
        birth_year = extract_birth_year(
            team_name,
            team.get("club_name"),
            team.get("team_name_original"),
        )

        if birth_year:
            expected_age_group = calculate_age_group(birth_year)

            if expected_age_group and expected_age_group != current_age_group:
                mismatches.append(
                    {
                        "team_id_master": team["team_id_master"],
                        "team_name": team_name,
                        "current_age_group": current_age_group,
                        "expected_age_group": expected_age_group,
                        "birth_year": birth_year,
                        "gender": team.get("gender"),
                        "state_code": team.get("state_code"),
                    }
                )

    if not mismatches:
        print("✅ No age group mismatches found!")
        return

    print(f"⚠️  Found {len(mismatches)} teams with age group mismatches:")
    print("-" * 70)
    print(f"{'Team Name':<40} {'Current':^10} {'Expected':^10} {'Birth Year':^10}")
    print("-" * 70)

    for m in mismatches[:50]:  # Show first 50
        name = m["team_name"][:38] + ".." if len(m["team_name"]) > 40 else m["team_name"]
        print(f"{name:<40} {m['current_age_group']:^10} {m['expected_age_group']:^10} {m['birth_year']:^10}")

    if len(mismatches) > 50:
        print(f"... and {len(mismatches) - 50} more")

    print("-" * 70)
    print()

    if args.dry_run:
        print("🔍 DRY RUN - No changes applied")
        print("   Run without --dry-run to apply fixes")
        return

    # Apply fixes
    print("🔧 Applying fixes...")
    fixed_count = 0
    error_count = 0

    for m in mismatches:
        try:
            # Update team's age_group and birth_year
            client.table("teams").update(
                {
                    "age_group": m["expected_age_group"],
                    "birth_year": m["birth_year"],
                    "updated_at": datetime.now().isoformat(),
                }
            ).eq("team_id_master", m["team_id_master"]).execute()

            fixed_count += 1
            print(f"  ✓ Fixed: {m['team_name'][:50]} ({m['current_age_group']} → {m['expected_age_group']})")

        except Exception as e:
            error_count += 1
            print(f"  ✗ Error fixing {m['team_name'][:50]}: {e}")

    print()
    print("=" * 70)
    print(f"SUMMARY: Fixed {fixed_count} teams, {error_count} errors")
    print("=" * 70)

    if fixed_count > 0:
        print()
        print("⚠️  IMPORTANT: You need to recalculate rankings for the affected teams.")
        print("   Run: python -m src.rankings.calculator")


def _run_self_tests() -> int:
    """Inline self-tests for extract_birth_year. Returns exit code."""
    cases = [
        # (team_name, club_name, team_name_original, expected_year, label)
        ("Union 10 FC 2008", "Union 10 FC", None, 2008,
         "raw, '10' skipped via 2-digit token"),
        ("Union 2010 FC 2008", "Union 10 FC", "Union 10 FC 2008 Boys", 2008,
         "uses team_name_original (raw)"),
        ("Union 2010 FC 2008", "Union 10 FC", None, 2008,
         "no original; expanded set has '2010' so polluted year is skipped"),
        ("Phoenix FC 2014", "Phoenix FC", None, 2014,
         "no club number leakage"),
        ("Phoenix FC 2010 Black", "Phoenix FC", None, 2010,
         "2010 is real birth year here; no club leakage"),
        ("Single Year Team 2013", None, None, 2013, "no club_name"),
        ("Bad Year Team 2099", None, None, None, "out of range"),
    ]
    failed = 0
    for tn, cn, tno, expected, label in cases:
        got = extract_birth_year(tn, cn, tno)
        ok = got == expected
        status = "✅" if ok else "❌"
        print(f"  {status} extract_birth_year({tn!r}, {cn!r}, {tno!r}) → {got!r} (expected {expected!r}) — {label}")
        if not ok:
            failed += 1
    print(f"\n{len(cases) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        sys.exit(_run_self_tests())
    main()
