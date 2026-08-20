#!/usr/bin/env python3
"""Undo birth years the name normalizer invented out of a club's own name.

parse_age_gender treats a bare two-digit token as a birth-year shorthand, which is
right almost always -- "14 CCFC Force" really is a 2014 team. It is wrong when the
club is *named* with those digits: "06 United FC" became "2006 United FC", so a
2016 team now carries a 2006 in its name.

The normalizer already guards this via club_skip_tokens, and both batch call sites
in normalize_team_names.py pass club_name, so the guard fires today. These rows are
damage from before it existed. The repair re-runs the current normalizer WITH club
context and writes the result, rather than restoring team_name_original wholesale --
that would undo every other correct normalization on the same row.

A fake birth year is not cosmetic here. It is what the matcher, the duplicate
scanner and the aged-out sweep all read to decide a team's cohort.

Examples:
    python3 scripts/repair_club_token_year_expansion.py --dry-run
    python3 scripts/repair_club_token_year_expansion.py --execute
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from datetime import datetime, timezone
from typing import Dict, List

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_env_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_env_dir, ".env.local"))
load_dotenv(os.path.join(_env_dir, ".env"))

from normalize_team_names import normalize_team_name  # noqa: E402

LEADING_TWO_DIGITS = re.compile(r"^(\d{2})\b")

CANDIDATE_SQL = """
SELECT team_id_master, team_name, team_name_original, club_name, age_group
FROM teams
WHERE is_deprecated = false
  AND team_name_original IS NOT NULL
  AND team_name <> team_name_original
"""


def log(message: str) -> None:
    print(message, flush=True)


def connect():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        log("ERROR: DATABASE_URL is not set (checked .env.local then .env)")
        sys.exit(1)
    return psycopg2.connect(database_url)


def invented_a_year(row: Dict) -> bool:
    """True when a leading 2-digit token became a 4-digit year that the club owns.

    Both conditions are required. Without the club check this would flag every
    correct expansion -- 1,567 of them, nearly all right.
    """
    original = (row["team_name_original"] or "").strip()
    current = (row["team_name"] or "").strip()
    club = (row["club_name"] or "").strip()

    match = LEADING_TWO_DIGITS.match(original)
    if not match:
        return False
    digits = match.group(1)
    if not current.startswith(f"20{digits}"):
        return False
    # The digits belong to the club's own name, so they were never a birth year.
    return bool(LEADING_TWO_DIGITS.match(club) and club.startswith(digits))


def write_csv(path: str, planned: List) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["team_id_master", "club_name", "team_name_original", "old_team_name", "new_team_name"])
        for row, repaired in planned:
            writer.writerow(
                [row["team_id_master"], row["club_name"], row["team_name_original"], row["team_name"], repaired]
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Undo birth years invented from a club's own name")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing (the default unless --execute)")
    parser.add_argument("--execute", action="store_true", help="Apply the repairs")
    parser.add_argument("--output", default=None, help="Where to write the CSV")
    args = parser.parse_args()

    execute = args.execute and not args.dry_run
    if args.execute and args.dry_run:
        log("Both --execute and --dry-run given; running as a dry run.")

    conn = connect()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(CANDIDATE_SQL)
    rows = [dict(r) for r in cur.fetchall()]
    affected = [r for r in rows if invented_a_year(r)]
    log(f"Normalized names examined: {len(rows)}")
    log(f"  where the leading digits belong to the CLUB, not a birth year: {len(affected)}")

    planned, unchanged = [], 0
    for row in affected:
        repaired = normalize_team_name(row["team_name_original"], row["club_name"])
        if repaired and repaired.strip() != (row["team_name"] or "").strip():
            planned.append((row, repaired.strip()))
        else:
            unchanged += 1

    if unchanged:
        log(f"  {unchanged} already normalize to their stored value with club context; nothing to do for those")

    log(f"\n  repair: {len(planned)}")
    for row, repaired in planned:
        log(f"  club {row['club_name']!r}")
        log(f"     now {row['team_name']!r}")
        log(f"     ->  {repaired!r}")

    out_path = args.output or os.path.join(
        _env_dir, "logs", f"repair_club_token_year_expansion_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    write_csv(out_path, planned)
    log(f"\nPlan written to {out_path}")

    if not execute:
        log("DRY RUN - no changes were made. Re-run with --execute to apply.")
        conn.rollback()
        cur.close()
        conn.close()
        return

    for row, repaired in planned:
        cur.execute(
            "UPDATE teams SET team_name = %s WHERE team_id_master = %s",
            (repaired, row["team_id_master"]),
        )
    conn.commit()
    log(f"\nApplied {len(planned)} name repairs.")

    cur.execute(CANDIDATE_SQL)
    remaining = [r for r in cur.fetchall() if invented_a_year(dict(r))]
    still = [
        r
        for r in remaining
        if (normalize_team_name(r["team_name_original"], r["club_name"]) or "").strip()
        != (r["team_name"] or "").strip()
    ]
    log(f"Remaining rows needing repair: {len(still)}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
