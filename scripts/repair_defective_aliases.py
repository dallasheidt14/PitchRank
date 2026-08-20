#!/usr/bin/env python3
"""Re-point team_alias_map rows whose provider name and master disagree on birth year.

Every fuzzy matcher in this repo scored names by similarity and compared colors,
directions, programs, squad numbers and coach names -- none compared birth year.
An age label cannot separate cohorts (u19 holds 2008 and 2009 at once), so
"Stateline SC-2011G Bears" was linked to "Stateline SC-2013G Bears" at 0.957.

An alias decides where a scrape files a team's games, so a wrong one silently
redirects future games with nothing recording it. team_alias_map has no audit
table and no revert RPC, which is why every run writes a CSV before it writes
anything else -- that CSV is the only rollback that exists.

RE-POINT, NEVER DELETE. Four provider matchers autocreate on an alias miss
(playmetrics_matcher.py:337-346, affinity_wa_matcher.py:307,
sincsports_matcher.py:596, modular11_matcher.py:592). Deleting an alias does not
park the team awaiting a guarded re-match: the next import creates a DUPLICATE
canonical team with a wall-clock-derived age and writes a fresh direct_id alias
to it -- invisible to any fuzzy_auto-filtered scan, and strictly worse than the
defect. playmetrics-scrape-import.yml runs weekly and is deliberately ungated.

The scan is driven from team_alias_map, never from team_match_review_queue: the
queue records 5,698 "approvals" of which 52 produced an alias, so a queue-driven
scan is wrong by two orders of magnitude.

Examples:
    python3 scripts/repair_defective_aliases.py --dry-run
    python3 scripts/repair_defective_aliases.py --execute
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_env_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_env_dir, ".env.local"))
load_dotenv(os.path.join(_env_dir, ".env"))

from src.utils.team_name_utils import birth_years, birth_years_conflict  # noqa: E402

# team_match_review_queue.provider_id holds the provider CODE as text, while
# team_alias_map.provider_id holds the providers UUID. `q.provider_id = p.code` is
# correct; joining q.provider_id to a.provider_id returns zero rows and a clean
# bill of health. Do not "tidy" this.
SCAN_SQL = """
SELECT a.id            AS alias_id,
       a.provider_id,
       a.provider_team_id,
       p.code          AS provider,
       q.provider_team_name,
       a.team_id_master,
       a.match_confidence,
       a.review_status,
       t.team_name     AS master_name,
       t.club_name     AS master_club,
       t.gender        AS master_gender
FROM team_alias_map a
JOIN providers p ON p.id = a.provider_id
JOIN teams t ON t.team_id_master = a.team_id_master
JOIN team_match_review_queue q
  ON q.provider_team_id = a.provider_team_id
 AND q.provider_id = p.code
WHERE a.match_method = 'fuzzy_auto'
  AND q.provider_team_name IS NOT NULL
"""

# Candidate re-point targets: same club, same gender, live, excluding the current
# (wrong) master. Birth-year compatibility is decided in Python by the same guard
# the matchers now use, so the scan and the fix cannot drift apart.
CANDIDATE_SQL = """
SELECT team_id_master, team_name, club_name, gender
FROM teams
WHERE is_deprecated = false
  AND team_id_master <> %(current)s
  AND club_name IS NOT NULL
  AND lower(club_name) = lower(%(club)s)
  AND lower(coalesce(gender, '')) = lower(coalesce(%(gender)s, ''))
"""


def _canonical(name: Optional[str]) -> str:
    """Casefolded, punctuation-free, whitespace-collapsed -- for identity only."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", (name or "").lower()).split())


def log(message: str) -> None:
    print(message, flush=True)


def connect():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        log("ERROR: DATABASE_URL is not set (checked .env.local then .env)")
        sys.exit(1)
    return psycopg2.connect(database_url)


def find_target(cur, row: Dict) -> tuple[Optional[Dict], str]:
    """The one same-club team whose birth years fit the provider name, or nothing.

    Returns (target, reason). A target is returned only when exactly one candidate
    survives: re-pointing to a guess writes the same class of defect this repairs.
    """
    if not row["master_club"]:
        return None, "master has no club_name to search within"

    cur.execute(
        CANDIDATE_SQL,
        {"current": row["team_id_master"], "club": row["master_club"], "gender": row["master_gender"]},
    )
    candidates = [dict(c) for c in cur.fetchall()]
    if not candidates:
        return None, "no same-club same-gender candidates"

    provider_name = row["provider_team_name"]
    fits = [c for c in candidates if not birth_years_conflict(provider_name, c["team_name"])]
    # A candidate that states no year at all is not evidence of a match -- it just
    # cannot conflict. Require the target to actually state a compatible year.
    fits = [c for c in fits if birth_years(c["team_name"])]
    if not fits:
        return None, f"no same-club candidate states a compatible birth year ({len(candidates)} searched)"
    if len(fits) == 1:
        return fits[0], "single same-club candidate with compatible birth years"

    # Tie-break on exact name equality only. Several providers restate the master's
    # name verbatim, so an exact hit among the candidates is identity rather than a
    # guess -- "Stateline SC-2011G Bears" against a candidate of exactly that name.
    # Anything looser would write the same class of defect this repairs.
    exact = [c for c in fits if _canonical(c["team_name"]) == _canonical(provider_name)]
    if len(exact) == 1:
        return exact[0], "exact name match among several compatible candidates"

    names = ", ".join(repr(c["team_name"]) for c in fits[:4])
    return None, f"ambiguous: {len(fits)} candidates fit ({names})"


def write_csv(path: str, planned: List, skipped: List) -> None:
    """The only rollback that exists -- team_alias_map has no audit table."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "action",
                "reason",
                "alias_id",
                "provider",
                "provider_team_id",
                "provider_team_name",
                "provider_years",
                "old_team_id_master",
                "old_master_name",
                "old_match_confidence",
                "old_review_status",
                "new_team_id_master",
                "new_master_name",
            ]
        )
        for row, verdict, target in planned + skipped:
            writer.writerow(
                [
                    verdict["action"],
                    verdict["reason"],
                    row["alias_id"],
                    row["provider"],
                    row["provider_team_id"],
                    row["provider_team_name"],
                    "/".join(str(y) for y in sorted(birth_years(row["provider_team_name"]))),
                    row["team_id_master"],
                    row["master_name"],
                    row["match_confidence"],
                    row["review_status"],
                    (target or {}).get("team_id_master"),
                    (target or {}).get("team_name"),
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-point aliases whose birth years disagree with their master")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing (the default unless --execute)")
    parser.add_argument("--execute", action="store_true", help="Apply the re-points")
    parser.add_argument("--limit", type=int, default=None, help="Max aliases to repair (default: all repairable)")
    parser.add_argument(
        "--output",
        default=None,
        help="Where to write the CSV (default: logs/repair_defective_aliases_<UTC>.csv)",
    )
    args = parser.parse_args()

    execute = args.execute and not args.dry_run
    if args.execute and args.dry_run:
        log("Both --execute and --dry-run given; running as a dry run.")

    conn = connect()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(SCAN_SQL)
    scanned = [dict(r) for r in cur.fetchall()]
    defective = [r for r in scanned if birth_years_conflict(r["provider_team_name"], r["master_name"])]

    log(f"Scannable fuzzy_auto aliases (joinable to a queue name): {len(scanned)}")
    log(f"Birth-year defective: {len(defective)}")

    # The blind spot, stated rather than implied. "17 defective" is not a census.
    cur.execute("SELECT count(*) AS n FROM team_alias_map WHERE match_method = 'fuzzy_auto'")
    total_fuzzy = cur.fetchone()["n"]
    cur.execute("SELECT count(*) AS n FROM team_alias_map WHERE match_method = 'direct_id'")
    total_direct = cur.fetchone()["n"]
    log(
        f"  NOT SCANNED: {total_fuzzy - len(scanned)} fuzzy_auto aliases have no recoverable provider name "
        f"(team_alias_map has no provider_team_name column), and the entire direct_id population "
        f"({total_direct}) is out of scope for this scan."
    )

    planned, skipped = [], []
    for row in defective:
        target, reason = find_target(cur, row)
        if target is None:
            skipped.append((row, {"action": "skip", "reason": reason}, None))
        else:
            planned.append((row, {"action": "repoint", "reason": reason}, target))

    if args.limit is not None:
        planned = planned[: args.limit]

    log(f"\n  repoint: {len(planned)}   skipped: {len(skipped)}")

    if planned:
        log("\nPlanned re-points:")
        for row, _, target in planned:
            log(f"  [{row['provider']}] {row['provider_team_name']!r}")
            log(f"       from {row['master_name']!r}")
            log(f"       to   {target['team_name']!r}")

    if skipped:
        log("\nSkipped (left alone rather than guessed):")
        for row, verdict, _ in skipped:
            log(f"  [{row['provider']}] {row['provider_team_name']!r} -> {row['master_name']!r}")
            log(f"       {verdict['reason']}")

    out_path = args.output or os.path.join(
        _env_dir, "logs", f"repair_defective_aliases_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    write_csv(out_path, planned, skipped)
    log(f"\nPlan written to {out_path}")

    if not execute:
        log("DRY RUN - no changes were made. Re-run with --execute to apply.")
        conn.rollback()
        cur.close()
        conn.close()
        return

    applied = 0
    for row, _, target in planned:
        cur.execute(
            "UPDATE team_alias_map SET team_id_master = %s WHERE id = %s",
            (target["team_id_master"], row["alias_id"]),
        )
        applied += 1
    conn.commit()
    log(f"\nApplied {applied} re-points.")

    cur.execute(SCAN_SQL)
    still_bad = [
        r for r in cur.fetchall() if birth_years_conflict(r["provider_team_name"], r["master_name"])
    ]
    log(f"Birth-year defective after repair: {len(still_bad)} (expected {len(skipped)}, the deliberate skips)")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
