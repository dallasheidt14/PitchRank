#!/usr/bin/env python3
"""Fill state_code from a US state named in the team's own name.

The existing backfills cannot reach these. match_state_from_club.py infers state
from clubmates, which needs the club to be meaningful -- but "Oregon Surf" is
stored under club "SURF", a national brand spanning many states, and
"Washington Premier" under the placeholder "No Club Selection", so the
DOMINANCE_RATIO check correctly refuses both. backfill_state_from_opponents.py
infers from opponents at >=90%, which border-state clubs never reach: Oregon
Surf's opponents are 40% OR and 35% WA, because Pacific Northwest teams play
across the river constantly.

Meanwhile the state is sitting in the team name.

Only whole-word matches on unambiguous state names count. The ambiguous ones are
left out on purpose rather than guessed:

  - "kansas"    -> Kansas City is in MISSOURI, and it is the more common token
  - "carolina"  -> NC or SC, unknowable from the word alone
  - "new york"  -> the NY/NJ metro shares clubs across the line
  - "virginia"  -> matched only after "west virginia", never before
  - "washington"-> the state, not DC; DC clubs are named "DC ..." here

Examples:
    python3 scripts/backfill_state_from_team_name.py --dry-run
    python3 scripts/backfill_state_from_team_name.py --execute
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

_env_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_env_dir, ".env.local"))
load_dotenv(os.path.join(_env_dir, ".env"))

# Deliberately excludes kansas, carolina, new york and the bare dakotas -- see
# the module docstring. "west virginia" must be tested before "virginia", which
# the longest-first ordering below guarantees.
STATE_NAMES: Dict[str, str] = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "west virginia": "WV",
    "virginia": "VA",
    "washington": "WA",
    "wisconsin": "WI",
    "wyoming": "WY",
}

# Phrases that contain a state name but do not mean that state.
FALSE_FRIENDS = ("kansas city", "washington dc", "washington d c")

# Longest first so "west virginia" wins over "virginia" and "new mexico" over
# "mexico"-adjacent fragments.
_ORDERED_STATES: List[Tuple[str, str]] = sorted(STATE_NAMES.items(), key=lambda kv: -len(kv[0]))

CANDIDATE_SQL = """
SELECT team_id_master, team_name, club_name, state, state_code
FROM teams
WHERE is_deprecated = false
  AND (state_code IS NULL OR state_code = '')
  AND team_name IS NOT NULL
  AND team_name !~ '^unknown_[0-9]+$'
"""

OPPONENT_SQL = """
SELECT o.state_code AS s
FROM games g
JOIN teams o ON o.team_id_master = CASE
    WHEN g.home_team_master_id = %(team)s THEN g.away_team_master_id
    ELSE g.home_team_master_id END
WHERE (g.home_team_master_id = %(team)s OR g.away_team_master_id = %(team)s)
  AND o.state_code IS NOT NULL
"""


def log(message: str) -> None:
    print(message, flush=True)


def connect():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        log("ERROR: DATABASE_URL is not set (checked .env.local then .env)")
        sys.exit(1)
    return psycopg2.connect(database_url)


def state_from_name(team_name: Optional[str]) -> Optional[str]:
    """The one US state named in a team name, or None.

    Whole words only, so "Indiana" matches and "Indianapolis" does not. Returns
    None when two different states appear -- "Texas" and "Oklahoma" in one name
    is a tournament or a league, not a home state.
    """
    if not team_name:
        return None
    padded = " " + re.sub(r"[^a-z ]", " ", team_name.lower()) + " "
    padded = re.sub(r"\s+", " ", padded)
    if any(phrase in padded for phrase in FALSE_FRIENDS):
        return None

    found = set()
    remaining = padded
    for name, code in _ORDERED_STATES:
        if f" {name} " in remaining:
            found.add(code)
            remaining = remaining.replace(f" {name} ", " ")
    return found.pop() if len(found) == 1 else None


def opponent_states(cur, team_id: str) -> Counter:
    cur.execute(OPPONENT_SQL, {"team": team_id})
    return Counter(row["s"] for row in cur.fetchall())


def write_csv(path: str, planned: List[Dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["team_id_master", "team_name", "club_name", "old_state_code", "new_state_code", "opponent_states"]
        )
        for row in planned:
            writer.writerow(
                [
                    row["team_id_master"],
                    row["team_name"],
                    row["club_name"],
                    row["state_code"],
                    row["inferred"],
                    row["opponents"],
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill state_code from a state named in the team name")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing (the default unless --execute)")
    parser.add_argument("--execute", action="store_true", help="Apply the updates")
    parser.add_argument("--limit", type=int, default=None, help="Max teams to update")
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
    log(f"Live teams with no state_code (excluding placeholders): {len(rows)}")

    planned, contradicted = [], []
    for row in rows:
        inferred = state_from_name(row["team_name"])
        if not inferred:
            continue
        counts = opponent_states(cur, row["team_id_master"])
        total = sum(counts.values())
        row["inferred"] = inferred
        row["opponents"] = ";".join(f"{s}:{n}" for s, n in counts.most_common(4)) or "none"

        # Opponents corroborate where they exist. They are NOT required -- a
        # border-state club never reaches a dominant share (Oregon Surf is 40%
        # OR / 35% WA), which is exactly why the opponent backfill cannot serve
        # these. They only veto: if the name says OR and the opponents are
        # overwhelmingly one OTHER state, trust neither and skip.
        if total >= 5:
            top_state, top_count = counts.most_common(1)[0]
            if top_state != inferred and top_count / total >= 0.90:
                contradicted.append(row)
                continue
        planned.append(row)

    if args.limit is not None:
        planned = planned[: args.limit]

    log(f"  name states exactly one US state: {len(planned) + len(contradicted)}")
    log(f"  planned: {len(planned)}   vetoed by opponents: {len(contradicted)}")
    log(f"  by state: {dict(Counter(r['inferred'] for r in planned).most_common(10))}")

    log("\nSample:")
    for row in planned[:12]:
        log(
            f"  [{row['inferred']}] {row['team_name'][:46]!r}  "
            f"club={str(row['club_name'])[:18]!r}  opp={row['opponents']}"
        )
    if len(planned) > 12:
        log(f"  ... and {len(planned) - 12} more")

    if contradicted:
        log("\nVetoed (opponents point overwhelmingly elsewhere):")
        for row in contradicted[:8]:
            log(f"  [{row['inferred']}?] {row['team_name'][:46]!r}  opp={row['opponents']}")

    out_path = args.output or os.path.join(
        _env_dir, "logs", f"backfill_state_from_team_name_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv"
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

    for row in planned:
        cur.execute(
            "UPDATE teams SET state_code = %s WHERE team_id_master = %s",
            (row["inferred"], row["team_id_master"]),
        )
    conn.commit()
    log(f"\nUpdated {len(planned)} teams.")

    cur.execute(CANDIDATE_SQL)
    remaining = [r for r in cur.fetchall() if state_from_name(r["team_name"])]
    log(f"Teams still missing state_code whose name names one: {len(remaining)}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
