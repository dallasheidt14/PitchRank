#!/usr/bin/env python3
"""
Restore team_alias_map rows for teams left alias-less by a merge revert.

A merge repoints the deprecated team's alias onto the canonical. revert_one in
revert_fuzzy_auto_merges.py undoes that by finding the alias for the deprecated
team's own (provider_id, provider_team_id) from its snapshot and pointing it
back — but where the merge had moved more than one alias, or where a later merge
moved the row on again, that lookup misses and the revert restores the team row
without its alias.

The team then exists, is live, carries games, and has no provider key pointing at
it. Scraping is queue-driven and drains every 15 minutes, so the next scrape of
that provider ID resolves through the alias still sitting on the canonical and
files the games there — with no team_merge_map row and no team_merge_audit row.
There is nothing for revert_team_merge to act on afterwards, which makes this
strictly less recoverable than the merges it came from.

The snapshot is authoritative for what the alias was before the merge, so the
repair is one write per team:

  - key exists on another master  -> repoint team_alias_map.team_id_master back
  - key absent entirely           -> insert the row as direct_id

Refusals rather than guesses: a snapshot missing either half of the key, a key
claimed by two orphans, a team still redirected by team_merge_map, and (without
--force) a repoint that would strand the current holder at zero aliases — the
same defect this script exists to fix.

team_alias_map has no audit table, so every run writes the plan it acted on to
CSV first. Not having that record is what made the 5,016-merge revert guesswork.

Examples:
    python3 scripts/repair_zero_alias_teams.py --dry-run
    python3 scripts/repair_zero_alias_teams.py --dry-run --limit 20
    python3 scripts/repair_zero_alias_teams.py --execute
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

_env_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_env_dir, ".env.local"))
load_dotenv(os.path.join(_env_dir, ".env"))

REPAIR_MATCH_METHOD = "direct_id"

# Live teams with no alias at all, restored by a revert, plus the provider key
# their own pre-merge snapshot recorded and where that key sits now.
CANDIDATE_SQL = """
WITH orphan AS (
    SELECT t.team_id_master, t.team_name, t.is_deprecated
    FROM teams t
    LEFT JOIN team_alias_map am ON am.team_id_master = t.team_id_master
    WHERE t.is_deprecated = false
      AND am.team_id_master IS NULL
),
snapshot AS (
    SELECT DISTINCT ON (o.team_id_master)
           o.team_id_master,
           o.team_name,
           (a.deprecated_team_snapshot ->> 'provider_id')::uuid AS provider_id,
            a.deprecated_team_snapshot ->> 'provider_team_id'   AS provider_team_id,
            a.performed_at
    FROM orphan o
    JOIN team_merge_audit a ON a.deprecated_team_id = o.team_id_master
    WHERE a.reverted_at IS NOT NULL
    ORDER BY o.team_id_master, a.performed_at DESC
)
SELECT s.team_id_master,
       s.team_name,
       s.provider_id,
       s.provider_team_id,
       m.id                AS alias_id,
       m.team_id_master    AS current_holder,
       ht.team_name        AS current_holder_name,
       ht.is_deprecated    AS current_holder_deprecated,
       (SELECT count(*) FROM team_alias_map z WHERE z.team_id_master = m.team_id_master) AS holder_alias_count,
       (SELECT count(*) FROM snapshot d
         WHERE d.provider_id = s.provider_id
           AND d.provider_team_id = s.provider_team_id) AS claimants,
       (SELECT count(*) FROM games g
         WHERE (g.home_team_master_id = s.team_id_master OR g.away_team_master_id = s.team_id_master)
           AND g.game_date >= CURRENT_DATE - INTERVAL '180 days') AS games_180d,
       EXISTS (SELECT 1 FROM team_merge_map mm
                WHERE mm.deprecated_team_id = s.team_id_master) AS still_merged
FROM snapshot s
LEFT JOIN team_alias_map m
       ON m.provider_id = s.provider_id
      AND m.provider_team_id = s.provider_team_id
LEFT JOIN teams ht ON ht.team_id_master = m.team_id_master
ORDER BY games_180d DESC, s.team_name
"""

VERIFY_SQL = """
SELECT count(*)
FROM teams t
LEFT JOIN team_alias_map am ON am.team_id_master = t.team_id_master
WHERE t.is_deprecated = false
  AND am.team_id_master IS NULL
  AND EXISTS (SELECT 1 FROM team_merge_audit a
               WHERE a.deprecated_team_id = t.team_id_master
                 AND a.reverted_at IS NOT NULL)
"""


def log(message: str) -> None:
    print(message, flush=True)


def connect():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        log("ERROR: DATABASE_URL is not set (checked .env.local then .env)")
        sys.exit(1)
    return psycopg2.connect(database_url)


def classify(row: Dict, force: bool) -> Dict:
    """Decide the action for one candidate, or the reason it is refused."""
    if not row["provider_id"] or not row["provider_team_id"]:
        return {"action": "skip", "reason": "snapshot has no provider key"}

    if row["claimants"] > 1:
        return {"action": "skip", "reason": f"provider key claimed by {row['claimants']} teams"}

    # A team team_merge_map still redirects is not actually restored, so giving it
    # back its provider key would point the scraper at a team reads route away from.
    if row["still_merged"]:
        return {"action": "skip", "reason": "team_merge_map still redirects this team"}

    if row["alias_id"] is None:
        return {"action": "insert", "reason": "no alias row exists for this key"}

    if row["current_holder"] == row["team_id_master"]:
        return {"action": "skip", "reason": "alias already points here"}

    # Repointing takes the row off its current holder. Where that is the holder's
    # only alias, the repair would simply move the defect, so it needs saying so.
    if row["holder_alias_count"] <= 1 and not force:
        return {
            "action": "skip",
            "reason": f"would strand holder {row['current_holder_name']!r} at zero aliases (use --force)",
        }

    return {"action": "repoint", "reason": f"held by {row['current_holder_name']!r}"}


def apply_repair(cur, row: Dict, action: str) -> None:
    if action == "repoint":
        cur.execute(
            "UPDATE team_alias_map SET team_id_master = %s WHERE id = %s",
            (row["team_id_master"], row["alias_id"]),
        )
    elif action == "insert":
        cur.execute(
            """
            INSERT INTO team_alias_map (provider_id, provider_team_id, team_id_master, match_method, match_confidence)
            VALUES (%s, %s, %s, %s, 1.0)
            ON CONFLICT (provider_id, provider_team_id) DO NOTHING
            """,
            (row["provider_id"], row["provider_team_id"], row["team_id_master"], REPAIR_MATCH_METHOD),
        )


def write_plan_csv(path: str, planned: List, skipped: List) -> None:
    """Record every row and its verdict — the undo instructions for this run."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "action",
                "reason",
                "team_id_master",
                "team_name",
                "provider_id",
                "provider_team_id",
                "alias_id",
                "previous_holder_id",
                "previous_holder_name",
                "games_180d",
            ]
        )
        for row, verdict in planned + skipped:
            writer.writerow(
                [
                    verdict["action"],
                    verdict["reason"],
                    row["team_id_master"],
                    row["team_name"],
                    row["provider_id"],
                    row["provider_team_id"],
                    row["alias_id"],
                    row["current_holder"],
                    row["current_holder_name"],
                    row["games_180d"],
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore alias rows for teams left alias-less by a merge revert")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing (the default unless --execute)")
    parser.add_argument("--execute", action="store_true", help="Apply the repairs")
    parser.add_argument("--limit", type=int, default=None, help="Max teams to repair (default: all)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Also repoint where doing so strands the current holder at zero aliases",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Where to write the plan CSV (default: logs/repair_zero_alias_teams_<UTC>.csv)",
    )
    args = parser.parse_args()

    execute = args.execute and not args.dry_run
    if args.execute and args.dry_run:
        log("Both --execute and --dry-run given; running as a dry run.")

    conn = connect()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(CANDIDATE_SQL)
    rows: List[Dict] = [dict(r) for r in cur.fetchall()]
    log(f"Alias-less live teams traceable to a reverted merge: {len(rows)}")

    planned = []
    skipped = []
    for row in rows:
        verdict = classify(row, args.force)
        (skipped if verdict["action"] == "skip" else planned).append((row, verdict))

    if args.limit is not None:
        planned = planned[: args.limit]

    repoints = sum(1 for _, v in planned if v["action"] == "repoint")
    inserts = sum(1 for _, v in planned if v["action"] == "insert")
    at_risk = sum(1 for r, _ in planned if r["games_180d"] > 0)
    log(f"  repoint: {repoints}   insert: {inserts}   skipped: {len(skipped)}")
    log(f"  of those planned, {at_risk} played within the last 180 days")

    if skipped:
        log("\nSkipped:")
        for row, verdict in skipped[:20]:
            log(f"  {row['team_name']!r} — {verdict['reason']}")
        if len(skipped) > 20:
            log(f"  ... and {len(skipped) - 20} more")

    log("\nPlanned:" if planned else "\nNothing to do.")
    for row, verdict in planned[:20]:
        log(
            f"  [{verdict['action']:>7}] {row['team_name']!r} "
            f"(provider_team_id={row['provider_team_id']}, {row['games_180d']} games/180d) — {verdict['reason']}"
        )
    if len(planned) > 20:
        log(f"  ... and {len(planned) - 20} more")

    out_path = args.output or os.path.join(
        _env_dir, "logs", f"repair_zero_alias_teams_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    write_plan_csv(out_path, planned, skipped)
    log(f"\nPlan written to {out_path}")

    if not execute:
        log("DRY RUN — no changes were made. Re-run with --execute to apply.")
        conn.rollback()
        cur.close()
        conn.close()
        return

    applied = 0
    for row, verdict in planned:
        apply_repair(cur, row, verdict["action"])
        applied += 1
    conn.commit()
    log(f"\nApplied {applied} repairs.")

    cur.execute(VERIFY_SQL)
    remaining = list(cur.fetchone().values())[0]
    log(f"Alias-less live teams from reverted merges remaining: {remaining}")
    if remaining and not args.limit:
        log("  (non-zero — the residue is in the skipped list above)")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
