#!/usr/bin/env python3
"""
Normalize Team Names in Database with Backup

This script:
1. Adds team_name_original column if it doesn't exist
2. Backs up original team_name before normalizing
3. Normalizes team names using the standardized rules:
   - Birth year formats → 4-digit year: '12B' -> '2012'
   - Age group formats → U##: 'U14B' -> 'U14'
   - Gender words stripped EVERYWHERE (tracked in gender field)
   - Squad identifiers preserved (colors, divisions, coach names)

By default, processes only teams where team_name_original IS NULL (never re-processes).
Use --all-teams to scan the full table.

UPDATED 2026-01-31: Fixed edge case where gender words after 4-digit years weren't stripped.
Tested: 100k+ teams across all states - 100% clean
"""

import os
import re
import sys
from datetime import datetime

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment
from dotenv import load_dotenv
from team_name_normalizer import parse_age_gender

from src.utils.team_utils import calculate_age_group_from_birth_year

_env_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_env_dir, ".env.local"))
load_dotenv(os.path.join(_env_dir, ".env"))

# Try direct DB connection first, fall back to Supabase REST API
DATABASE_URL = os.getenv("DATABASE_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")

# Known keywords to preserve with specific formatting
LEAGUE_KEYWORDS = {
    "ecnl",
    "ecnl-rl",
    "ecrl",
    "rl",
    "mls next",
    "mls-next",
    "mlsnext",
    "npl",
    "ga",
    "dpl",
    "dplo",
    "sccl",
    "pre-ecnl",
    "pre-academy",
    "academy",
    "premier",
    "elite",
    "select",
    "classic",
    "development",
    "competitive",
    "ad",
    "hd",
    "ea",
    "copa",
    "pre",
    "nal",
}

SQUAD_IDENTIFIERS = {
    "black",
    "blue",
    "red",
    "white",
    "navy",
    "gold",
    "orange",
    "green",
    "silver",
    "gray",
    "grey",
    "purple",
    "yellow",
    "pink",
    "maroon",
    "teal",
    "i",
    "ii",
    "iii",
    "iv",
    "v",
    "vi",
    "vii",
    "viii",
    "ix",
    "x",
    "north",
    "south",
    "east",
    "west",
    "central",
    "sw",
    "ne",
    "nw",
    "se",
    "n2",
    "1",
    "2",
    "3",
    "a",
    "b",
    "c",
}

# Gender words to strip (tracked in gender field instead)
GENDER_WORDS = {"boys", "boy", "girls", "girl", "male", "female"}


# Generic noise tokens stripped from club_name when computing skip tokens.
# Mirrors scripts/dryrun_team_distinction.py:_CLUB_NOISE — keep in sync.
_NORMALIZER_CLUB_NOISE = {
    "fc", "sc", "sa", "ac", "cf", "cd", "fcs", "ysa",
    "soccer", "club", "futbol", "football", "youth", "academy",
    "the", "of", "and", "association",
}


def _normalizer_club_tokens(club_name):
    """Lowercase tokens of the club name (minus noise), no expansion.

    The bare-2-digit branch in ``parse_age_gender`` sees the input token
    (e.g., "10"), not the 4-digit form. So unlike
    ``fix_team_age_groups._club_tokens``, this set only needs the literal
    2-digit form.
    """
    if not club_name:
        return set()
    toks = re.split(r"[\s\-_./]+", club_name.lower())
    out = set()
    for t in toks:
        t = t.strip("()[]'*.,")
        if not t or t in _NORMALIZER_CLUB_NOISE or len(t) < 2:
            continue
        out.add(t)
    return out


def _cohort_label(age_group) -> "str | None":
    """teams.age_group as the token to render, e.g. "u14" -> "U14".

    Returns None for anything outside the tracked U6-U19 range, so the sentinels
    and stray values that live in that column (u0, u20, u99x) never reach a name.
    """
    if not age_group:
        return None
    digits = re.sub(r"[^0-9]", "", str(age_group))
    if not digits:
        return None
    age = int(digits)
    return f"U{age}" if 6 <= age <= 19 else None


# A band as providers actually write it: two years joined by a slash or a dash,
# with or without spaces, with or without a gender letter at either end —
# "15/16", "B14/15", "2014/15", "2013/2012", "2014-15", "2013 - 2014".
# The separators are excluded on both sides so a longer chain is not read as a
# band: "07/08/09/10" is a rec-league team spanning four birth years, and taking
# its first pair would name it U19 and leave "/09/10" trailing.
# The gender letter is optional on BOTH sides of BOTH years: clubs write
# "B14/15", "13/14B", "2014G -2015G" and "B07/B08" interchangeably.
_BAND_RE = re.compile(
    r"(?<![\w'/–-])[BbGgMmFf]?(\d{2}|\d{4})[BbGgMmFf]?\s*[/\-–]\s*"
    r"[BbGgMmFf]?(\d{2}|\d{4})[BbGgMmFf]?(?![\w'/–-])"
)


# A four-digit birth year standing on its own in the name.
_YEAR_RE = re.compile(r"(?<![A-Za-z0-9])(20[0-2]\d)(?![A-Za-z0-9])")


def _column_contradicted(name: str, cohort_label: str) -> bool:
    """Whether a birth year in the name disagrees with teams.age_group.

    Names that carry both a year and a U-age settle the question by themselves.
    A birth year re-derives its cohort from the wall clock, so it cannot have
    gone stale; a U-age is frozen text and can. Where the two disagree it is
    therefore the U-age that rotted — which is the whole reason the column may
    overwrite it.

    Where the YEAR disagrees with the column instead, that reasoning inverts:
    the column is the suspect side, and rendering it into the name would write an
    error over the one token that could have caught it. About 90 teams are in
    that state, most of them wildly off (`U08B Cook Inlet SC Navy 2019` against a
    `u15` column). Those names are left exactly as they are.
    """
    cohorts = {calculate_age_group_from_birth_year(int(y)) for y in _YEAR_RE.findall(name)}
    cohorts.discard(None)
    return bool(cohorts) and cohort_label not in cohorts


def _full_year(value: str) -> int:
    """'14' -> 2014, '2014' -> 2014."""
    year = int(value)
    if year >= 1900:
        return year
    return 2000 + year if year < 30 else 1900 + year


def _resolve_band(name: str):
    """Replace a two-year band with the cohort it names: "13/14B Summer" -> "U14 Summer".

    A band states BOTH birth years of a cohort, so unlike a lone birth year it
    identifies the cohort outright: U_N = {SEASON+1-N, SEASON-N}, and the
    younger year gives N. U14 is 2013/2012, U19 is 2008/2007. That is why a band
    is resolved from itself and never rendered from teams.age_group — the name
    already carries the more specific fact, and the column can only agree or be
    wrong.

    Matched against the whole name rather than token by token, because providers
    write the band with spaces often enough ("2013 - 2014") that a per-token scan
    sees two separate years and consumes the first one as the age.

    Returns (name, label) with EVERY band replaced, or (name, None) if there is
    none. Every band, not just the first: "Cape Coral Soccer - 2007/2008 Cyclone
    RL B07/08" states the cohort twice, and collapsing only the leading one
    leaves a band behind for the next run to find and the name to change again.
    """
    label_seen = None

    def _replace(match):
        nonlocal label_seen
        first, second = _full_year(match.group(1)), _full_year(match.group(2))
        # Consecutive years only. Anything else is a club founding pair, a score,
        # or an address — "1570 FC - 1570" and "10-3 Red" are not cohorts.
        if abs(first - second) != 1:
            return match.group(0)
        label = calculate_age_group_from_birth_year(max(first, second))
        if not label:
            return match.group(0)
        label_seen = label
        return label

    return _BAND_RE.sub(_replace, name), label_seen


def normalize_team_name(
    team_name: str, club_name: str = None, age_group: str = None, original_name: str = None
) -> str:
    """
    Normalize a team name following Jan 2026 rules.

    - Age rendered from teams.age_group when supplied: the age token becomes U##
    - Gender words stripped EVERYWHERE (B/G in age tokens normalized, standalone words removed)
    - Squad identifiers (colors, divisions, coach names) preserved
    - Case normalized for known keywords
    - Club-name number fragments are NOT rewritten (e.g., "10" in
      "Union 10 FC" stays as "10", not "2010").

    age_group:
        The team's cohort from teams.age_group. When given, the age token in the
        name is RENDERED FROM IT rather than derived from the name's own digits,
        so the name is a view of the column instead of an independent claim.

        That is what makes the annual rollover cheap. Age groups band two birth
        years and shift every Aug 1, so a birth year written into a name means a
        different cohort each season and cannot be corrected without knowing when
        it was written. Rendering from the column means the rollover is: update
        age_group, re-run this job, and every name follows.

        When age_group is absent the old behaviour applies, so callers that only
        have a name (import-time matching, tests) are unaffected.

    Returns: Normalized team name string
    """
    if not team_name:
        return team_name

    original = team_name.strip()
    club_skip_tokens = _normalizer_club_tokens(club_name)
    cohort_label = _cohort_label(age_group)
    # Bands are read from the ORIGINAL name, because collapsing one destroys the
    # evidence that it was ever there. "13/14B Summer" becomes "U13 Summer" on the
    # first pass, and on the second the U13 is indistinguishable from an ordinary
    # stale label — the column would roll it to U15 and the band's answer would
    # survive exactly one weekly run. teams.team_name_original is what makes the
    # job idempotent here. It also recovers bands that an earlier version already
    # flattened to a single year, where team_name says "2014" and the original
    # still says "13/14B".
    original, band_label = _resolve_band(original)

    # The ORIGINAL name is consulted only to VETO the column, never as a source to
    # write from. Collapsing a band destroys the evidence it was there: after
    # "13/14B Summer" becomes "U13 Summer", the U13 is indistinguishable from an
    # ordinary stale label and the next weekly run would roll it to the column's
    # U15 -- the band's answer would survive exactly one run. Knowing the original
    # held a band is enough to leave the name alone, and unlike re-rendering the
    # label it cannot put the cohort in the wrong place: "U17 Stingers 07/08"
    # normalizes to "U17 Stingers U19", where the first age token is not the band.
    had_band = band_label is not None or _resolve_band(original_name or "")[1] is not None

    # The column may rewrite a U-age, and only a U-age. A birth year in a name is
    # a fact that re-maps itself every Aug 1 and so never needs correcting; a
    # U-age is a label frozen at the season it was typed, and 18,958 of them have
    # since gone stale. Rendering the column over a birth year would delete the
    # one self-checking token in the name and put an unverifiable one in its
    # place, which is why only the U-age case is eligible here.
    column_may_drive = (
        cohort_label is not None
        and not had_band
        and not _column_contradicted(original, cohort_label)
    )

    # Tokenize the entire name
    all_tokens = re.split(r"[\s]+", original)
    all_tokens = [t.strip() for t in all_tokens if t.strip()]

    result_tokens = []
    age_found = None
    u_rendered = False

    for token in all_tokens:
        clean_token = token.strip("()[]")
        if not clean_token:
            continue
        t_lower = clean_token.lower()

        # Skip standalone gender words EVERYWHERE
        if t_lower in GENDER_WORDS:
            continue

        # Try to parse as age/gender token (skip club-name number fragments
        # so "Union 10 FC 2008" doesn't get rewritten to "Union 2010 FC 2008").
        parsed_age, _ = parse_age_gender(clean_token, club_skip_tokens=club_skip_tokens)

        # A U-age outside U6-U19 is not an age at all. parse_age_gender's
        # bare-two-digit branch returns U{n} for ANY two-digit token outside
        # 6-18, so a club's founding year parses as U94 and "Summer 26" as U26 —
        # and the normalizer then writes that into the name. Treating them as
        # ordinary text leaves 49 such names as their clubs wrote them.
        if parsed_age and parsed_age.startswith("U") and not 6 <= int(parsed_age[1:]) <= 19:
            parsed_age = None

        if parsed_age:
            is_u_age = parsed_age.startswith("U")

            # Not gated on being the FIRST age token. 2,561 names carry a birth
            # year ahead of their U-age ("2014 U12 PRE MLS I"), and those are the
            # best-evidenced rewrites of all — the year corroborates the column
            # from inside the same name. Taking only the first token would leave
            # exactly them stale.
            if is_u_age and column_may_drive and not u_rendered:
                u_rendered = True
                age_found = age_found or cohort_label
                result_tokens.append(cohort_label)
                continue

            if age_found is None:
                age_found = parsed_age
                result_tokens.append(parsed_age)
                continue
            # A second age token is left exactly as written — rewriting it too
            # would render the same cohort twice into one name.

        # Bands are handled by _resolve_band before tokenizing — a second path
        # here would see only the slash forms and would disagree with the first
        # on every spaced band.
        #
        # The band is NOT preserved as written, tempting though that is. Reading
        # it back needs both years, and the consumers of teams.team_name cannot:
        # _team_distinction tokenizes on "/" and its two-digit pattern requires a
        # leading apostrophe, so "14/15" yields NO age token where "U13" yields
        # one -- should_skip_pair then refuses the pair outright, ahead of the
        # birth-year guard that would have accepted it. frontend/lib/utils.ts is
        # worse: its standalone two-digit pattern matches "14" inside "14/15" and
        # derives U13 for a U14 team. Preserving bands needs those parsers taught
        # first.

        # Preserve league keywords with proper casing
        if t_lower in LEAGUE_KEYWORDS:
            # Uppercase short acronyms
            if len(clean_token) <= 4 or t_lower in {
                "ecnl",
                "ecrl",
                "npl",
                "dpl",
                "dplo",
                "ga",
                "ad",
                "hd",
                "ea",
                "rl",
                "sccl",
                "copa",
                "nal",
            }:
                result_tokens.append(clean_token.upper())
            elif "-" in t_lower:
                result_tokens.append(clean_token.upper())
            else:
                result_tokens.append(clean_token.title())
            continue

        # Preserve squad identifiers with proper casing
        if t_lower in SQUAD_IDENTIFIERS:
            if (
                t_lower
                in {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "n2", "1", "2", "3", "a", "b", "c"}
                or len(t_lower) <= 2
            ):
                result_tokens.append(clean_token.upper())
            else:
                result_tokens.append(clean_token.title())
            continue

        # Keep other tokens as-is (club names, coach names, etc.)
        result_tokens.append(clean_token)

    return " ".join(result_tokens) if result_tokens else original


def run_with_psycopg2(args):
    """Run normalization using direct Postgres connection (faster)."""
    import psycopg2

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    print("Using direct Postgres connection")

    # Build query with filters
    where_clauses = []
    if not args.all_teams:
        where_clauses.append("team_name_original IS NULL")
    params = []

    if args.state:
        where_clauses.append("state_code = %s")
        params.append(args.state.upper())
    if args.gender:
        where_clauses.append("gender = %s")
        params.append(args.gender)
    if args.age_group:
        where_clauses.append("age_group = %s")
        params.append(args.age_group.lower())

    where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"
    print(f"Scan scope: {'ALL teams' if args.all_teams else 'Only teams with team_name_original IS NULL'}")

    # Count teams
    cur.execute(f"SELECT COUNT(*) FROM teams WHERE {where_sql}", params)
    total = cur.fetchone()[0]
    print(f"Total teams to process: {total}")

    if total == 0:
        print("No teams need processing!")
        return

    # Fetch all teams
    limit_sql = f" LIMIT {args.limit}" if args.limit else ""
    cur.execute(
        f"""
        SELECT id, team_name, club_name, team_name_original, age_group
        FROM teams
        WHERE {where_sql}
        {limit_sql}
    """,
        params,
    )

    teams = cur.fetchall()
    print(f"Fetched {len(teams)} teams")

    # Process
    updated = 0
    skipped = 0
    samples = []

    for team_id, team_name, club_name, team_name_original, age_group in teams:
        normalized = normalize_team_name(team_name, club_name, age_group, team_name_original)

        if normalized != team_name:
            if len(samples) < 15:
                samples.append((team_name, normalized))

            if not args.dry_run:
                cur.execute(
                    """
                    UPDATE teams
                    SET team_name_original = COALESCE(team_name_original, %s), team_name = %s
                    WHERE id = %s
                """,
                    (team_name, normalized, team_id),
                )
            updated += 1
        else:
            skipped += 1

    if not args.dry_run:
        conn.commit()

    conn.close()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"✅ {'Would update' if args.dry_run else 'Updated'}: {updated}")
    print(f"⏭️  Skipped (no change): {skipped}")

    if samples:
        print("\n📋 Sample Transformations:")
        print("-" * 60)
        for before, after in samples:
            print(f"  Before: {before}")
            print(f"  After:  {after}")
            print()

    if args.dry_run:
        print("\n⚠️  DRY RUN - No changes were made")


def run_with_supabase(args):
    """Run normalization using Supabase REST API (fallback)."""
    from supabase import create_client

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Using Supabase REST API (slower)")

    # This is the original implementation - kept for fallback
    query = supabase.table("teams").select("id, team_name, club_name, team_name_original, age_group")

    if args.state:
        query = query.eq("state_code", args.state.upper())
    if args.gender:
        query = query.eq("gender", args.gender)
    if args.age_group:
        query = query.eq("age_group", args.age_group.lower())

    if not args.all_teams:
        query = query.is_("team_name_original", "null")
    print(f"Scan scope: {'ALL teams' if args.all_teams else 'Only teams with team_name_original IS NULL'}")

    # Paginated fetch
    all_teams = []
    offset = 0
    batch_size = 1000

    print("Fetching teams...")
    while True:
        batch = query.range(offset, offset + batch_size - 1).execute()
        if not batch.data:
            break
        all_teams.extend(batch.data)
        offset += batch_size
        print(f"  Fetched {len(all_teams)}...")

        if args.limit and len(all_teams) >= args.limit:
            all_teams = all_teams[: args.limit]
            break

    print(f"Total teams to process: {len(all_teams)}")

    if not all_teams:
        print("No teams need processing!")
        return

    # Process
    updated = 0
    skipped = 0
    samples = []

    for team in all_teams:
        team_id = team["id"]
        team_name = team["team_name"]
        club_name = team.get("club_name")
        age_group = team.get("age_group")

        normalized = normalize_team_name(team_name, club_name, age_group, team.get("team_name_original"))

        if normalized != team_name:
            if len(samples) < 15:
                samples.append((team_name, normalized))

            if not args.dry_run:
                # Preserve the first-seen original name if already present.
                original_backup = team.get("team_name_original") or team_name
                supabase.table("teams").update({"team_name_original": original_backup, "team_name": normalized}).eq(
                    "id", team_id
                ).execute()
            updated += 1
        else:
            skipped += 1

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"✅ {'Would update' if args.dry_run else 'Updated'}: {updated}")
    print(f"⏭️  Skipped (no change): {skipped}")

    if samples:
        print("\n📋 Sample Transformations:")
        for before, after in samples:
            print(f"  {before} → {after}")

    if args.dry_run:
        print("\n⚠️  DRY RUN - No changes were made")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Normalize team names in database")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without updating")
    parser.add_argument(
        "--all-teams", action="store_true", help="Scan all teams instead of only team_name_original IS NULL"
    )
    parser.add_argument("--state", type=str, help="Filter by state_code (e.g., AZ, CA)")
    parser.add_argument("--gender", type=str, choices=["Male", "Female"], help="Filter by gender")
    parser.add_argument("--age-group", type=str, help="Filter by age_group (e.g., u14)")
    parser.add_argument("--limit", type=int, help="Max teams to process")
    args = parser.parse_args()

    print("=" * 60)
    print("TEAM NAME NORMALIZER")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode: {'DRY RUN (preview only)' if args.dry_run else 'LIVE (will update database)'}")
    print()

    # Use Supabase REST API first (most reliable), fall back to direct Postgres
    if SUPABASE_URL and SUPABASE_KEY:
        run_with_supabase(args)
    elif DATABASE_URL:
        run_with_psycopg2(args)
    else:
        print("❌ No database connection configured")
        print("   Set SUPABASE_URL + SUPABASE_KEY or DATABASE_URL in .env")
        sys.exit(1)


if __name__ == "__main__":
    main()
