#!/usr/bin/env python3
"""Label teams that have aged out of youth soccer as u20 so they stop being ranked.

PitchRank age groups are bands and the oldest is U19 = 2008/07, so a team whose
name states 2006 or earlier belongs to no band this season. The ranking engine
already drops anything outside U10-U19 (calculator.py VALID_AGE_MIN/VALID_AGE_MAX),
so moving these to u20 retires them through the mechanism that already exists
rather than adding an exclusion rule to the pipeline.

WHY THIS IS SAFE UNDER THE age_group WRITE FREEZE. That freeze exists because
deriving a COHORT from a birth year is ambiguous: the season straddles Jan 1, so
2011 is U15 or U16 and no function of the year alone can say which. "Aged out" is
not that kind of judgement -- 2006 appears in no band under either reading, so the
ambiguity the freeze protects against does not arise here.

Matching is unaffected. calculate_age_group_from_birth_year already returns None
for 2006, which the matcher turns into an unmatchable sentinel, so these teams
cannot be found by name today whatever their label. Provider-ID lookup runs before
any age filter and is untouched.

READS BIRTH YEARS, NEVER GREPS FOR DIGITS. A four-digit scan flags "2006 United FC"
(a club named 06 United FC) and "AFCADV2017G01" (a squad code). Every year stated
in the name must be 2006 or older, so a "2006/07" team stays put -- keeping a team
ranked is the recoverable error, removing one wrongly is not.

Examples:
    python3 scripts/retire_aged_out_teams.py --dry-run
    python3 scripts/retire_aged_out_teams.py --execute
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_env_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_env_dir, ".env.local"))
load_dotenv(os.path.join(_env_dir, ".env"))

from src.utils.team_name_utils import birth_years  # noqa: E402
from src.utils.team_utils import calculate_age_group_from_birth_year  # noqa: E402

RETIRED_AGE_GROUP = "u20"

CANDIDATE_SQL = """
SELECT team_id_master, team_name, club_name, age_group, birth_year
FROM teams
WHERE is_deprecated = false
  AND coalesce(age_group, '') NOT IN ('u20', 'u21')
"""

VERIFY_SQL = """
SELECT t.team_id_master, t.team_name, t.age_group
FROM rankings_full r
JOIN teams t ON t.team_id_master = r.team_id
WHERE coalesce(t.age_group, '') NOT IN ('u20', 'u21')
"""


def log(message: str) -> None:
    print(message, flush=True)


def connect():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        log("ERROR: DATABASE_URL is not set (checked .env.local then .env)")
        sys.exit(1)
    return psycopg2.connect(database_url)


def is_aged_out(row: Dict, season: int) -> bool:
    """True when every birth year the name states is too old for any band.

    Requires EVERY stated year to be aged out, not the earliest. A club whose own
    name carries a year ("06 United FC 2016") states two, and only one of them is
    the team's. Taking the minimum retires a live 2016 team.
    """
    years = birth_years(row["team_name"])
    if not years:
        return False
    return all(calculate_age_group_from_birth_year(year, season) is None for year in years)


def write_csv(path: str, planned: List[Dict], season: int) -> None:
    """team_name is the only evidence for this decision, so record it verbatim."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["team_id_master", "team_name", "club_name", "old_age_group", "new_age_group", "years_in_name", "season"]
        )
        for row in planned:
            writer.writerow(
                [
                    row["team_id_master"],
                    row["team_name"],
                    row["club_name"],
                    row["age_group"],
                    RETIRED_AGE_GROUP,
                    "/".join(str(y) for y in sorted(birth_years(row["team_name"]))),
                    season,
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Retire aged-out teams to u20 so they stop being ranked")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing (the default unless --execute)")
    parser.add_argument("--execute", action="store_true", help="Apply the relabel")
    parser.add_argument("--season", type=int, default=None, help="Season year to judge against (default: current)")
    parser.add_argument("--limit", type=int, default=None, help="Max teams to relabel")
    parser.add_argument("--output", default=None, help="Where to write the CSV")
    args = parser.parse_args()

    execute = args.execute and not args.dry_run
    if args.execute and args.dry_run:
        log("Both --execute and --dry-run given; running as a dry run.")

    from src.utils import team_utils

    season = args.season or team_utils.CURRENT_YEAR
    log(f"Judging against season {season} (U19 is the oldest band).")

    conn = connect()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(CANDIDATE_SQL)
    rows = [dict(r) for r in cur.fetchall()]
    planned = [r for r in rows if is_aged_out(r, season)]
    if args.limit is not None:
        planned = planned[: args.limit]

    log(f"Live teams not already retired: {len(rows)}")
    log(f"  aged out (every year in the name is too old for any band): {len(planned)}")

    cur.execute(VERIFY_SQL)
    ranked_ids = {r["team_id_master"] for r in cur.fetchall()}
    ranked_hits = [r for r in planned if r["team_id_master"] in ranked_ids]
    log(f"  of those, currently IN the rankings: {len(ranked_hits)}")

    from collections import Counter

    log(f"  by current label: {dict(Counter(r['age_group'] for r in planned).most_common(8))}")

    log("\nSample:")
    for row in planned[:12]:
        years = "/".join(str(y) for y in sorted(birth_years(row["team_name"])))
        ranked = " [RANKED]" if row["team_id_master"] in ranked_ids else ""
        log(f"  [{row['age_group']}] {row['team_name']!r} ({years}){ranked}")
    if len(planned) > 12:
        log(f"  ... and {len(planned) - 12} more")

    out_path = args.output or os.path.join(
        _env_dir, "logs", f"retire_aged_out_teams_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    write_csv(out_path, planned, season)
    log(f"\nPlan written to {out_path}")

    if not execute:
        log("DRY RUN - no changes were made. Re-run with --execute to apply.")
        conn.rollback()
        cur.close()
        conn.close()
        return

    for row in planned:
        cur.execute(
            "UPDATE teams SET age_group = %s WHERE team_id_master = %s",
            (RETIRED_AGE_GROUP, row["team_id_master"]),
        )
    conn.commit()
    log(f"\nRelabelled {len(planned)} teams to {RETIRED_AGE_GROUP}.")

    cur.execute(CANDIDATE_SQL)
    remaining = [r for r in cur.fetchall() if is_aged_out(dict(r), season)]
    log(f"Aged-out teams still carrying a rankable label: {len(remaining)}")
    log("Rankings do not change until the next calculate-rankings run.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
