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
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv

from supabase import create_client

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

# A state name preceded by one of these is part of a PLACE name, not a state:
# "Mount Washington SC" is in Baltimore, Maryland.
_PLACE_PREFIX = re.compile(
    r"\b(mount|mt|lake|fort|ft|port|cape|north|south|east|west)\s+"
    r"(washington|oregon|nevada|montana|indiana|florida|georgia|ohio|texas|utah|maine|delaware)\b",
    re.I,
)

# Two-letter tokens that are soccer vocabulary here, never a state. Without this
# "California Athletic SC" reads as South Carolina and "TSJ FC Virginia - GA"
# as Georgia -- SC is Soccer Club and GA is Girls Academy.
_NOT_STATE_TOKENS = frozenset({"SC", "FC", "GA", "AC", "SA", "CF", "DA", "RL", "EA", "NL", "PA"})

# An explicit affiliate marker: "Utah Royals FC-AZ" is the ARIZONA affiliate.
# Bracketed or hyphen-attached, so it does not fire on a bare word.
_AFFILIATE_CODE = re.compile(r"(?:-\s*|\(\s*)([A-Z]{2})(?![A-Za-z])")

# Longest first so "west virginia" wins over "virginia" and "new mexico" over
# "mexico"-adjacent fragments.
_ORDERED_STATES: List[Tuple[str, str]] = sorted(STATE_NAMES.items(), key=lambda kv: -len(kv[0]))

_PLACEHOLDER_NAME = re.compile(r"^unknown_[0-9]+$")

PAGE_SIZE = 1000
TEAMS_BATCH = 100  # URI length caps .in_() lists


def log(message: str) -> None:
    print(message, flush=True)


def get_supabase():
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_KEY")
    )
    if not url or not key:
        log("ERROR: missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (checked .env.local then .env)")
        sys.exit(1)
    return create_client(url, key)


def fetch_candidates(sb) -> List[Dict]:
    """Live teams with no state_code, placeholder names dropped."""
    teams: List[Dict] = []
    seen: Set[str] = set()
    for is_null in (True, False):
        offset = 0
        while True:
            q = (
                sb.table("teams")
                .select("team_id_master, team_name, club_name, state, state_code")
                .eq("is_deprecated", False)
                .not_.is_("team_name", "null")
            )
            q = q.is_("state_code", "null") if is_null else q.eq("state_code", "")
            rows = q.range(offset, offset + PAGE_SIZE - 1).execute().data or []
            for row in rows:
                team_id = row.get("team_id_master")
                if not team_id or team_id in seen:
                    continue
                if _PLACEHOLDER_NAME.match(row.get("team_name") or ""):
                    continue
                seen.add(team_id)
                teams.append(row)
            if len(rows) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    return teams


def collect_opponent_states(sb, team_ids: List[str]) -> Dict[str, Counter]:
    """team_id_master -> Counter of opponent state_codes, one entry per game row.

    Counts game rows rather than distinct opponents, and does not exclude
    ``is_excluded`` games. Both differ from backfill_state_from_opponents.py on
    purpose: there the ratio decides a state, here it only ever vetoes one.
    """
    opponents_by_team: Dict[str, List[str]] = defaultdict(list)
    for i in range(0, len(team_ids), TEAMS_BATCH):
        batch = team_ids[i:i + TEAMS_BATCH]
        for own_col, other_col in (
            ("home_team_master_id", "away_team_master_id"),
            ("away_team_master_id", "home_team_master_id"),
        ):
            offset = 0
            while True:
                rows = (
                    sb.table("games")
                    .select("home_team_master_id, away_team_master_id")
                    .in_(own_col, batch)
                    .range(offset, offset + PAGE_SIZE - 1)
                    .execute().data or []
                )
                for game in rows:
                    team, opponent = game.get(own_col), game.get(other_col)
                    if team and opponent:
                        opponents_by_team[team].append(opponent)
                if len(rows) < PAGE_SIZE:
                    break
                offset += PAGE_SIZE

    states = fetch_states(sb, {o for ops in opponents_by_team.values() for o in ops})
    return {
        team: Counter(states[o] for o in ops if o in states)
        for team, ops in opponents_by_team.items()
    }


def fetch_states(sb, team_ids: Set[str]) -> Dict[str, str]:
    """team_id_master -> state_code, skipping teams that have none."""
    out: Dict[str, str] = {}
    ids = [t for t in team_ids if t]
    for i in range(0, len(ids), TEAMS_BATCH):
        rows = (
            sb.table("teams")
            .select("team_id_master, state_code")
            .in_("team_id_master", ids[i:i + TEAMS_BATCH])
            .not_.is_("state_code", "null")
            .neq("state_code", "")
            .execute().data or []
        )
        for row in rows:
            out[row["team_id_master"]] = (row.get("state_code") or "").strip()
    return out


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
    # "Mount Washington SC" is in Maryland. A state name behind a place word is
    # part of a town, not a location claim.
    if _PLACE_PREFIX.search(padded):
        return None

    found = set()
    remaining = padded
    for name, code in _ORDERED_STATES:
        if f" {name} " in remaining:
            found.add(code)
            remaining = remaining.replace(f" {name} ", " ")
    if len(found) != 1:
        return None
    inferred = found.pop()

    return None if affiliate_contradicts(team_name, inferred) else inferred


def affiliate_contradicts(text: Optional[str], inferred: Optional[str]) -> bool:
    """Whether an explicit affiliate marker in ``text`` names a state other than ``inferred``.

    "Utah Royals FC-AZ" is the Arizona side. Refuse rather than pick -- the marker means
    the name and the location genuinely disagree, and guessing either way is what caused
    this whole class of bug.

    Shared with Tier E in ``assign_team_states``, which reads learned place words rather
    than state names but needs the same refusal for the same reason: "utah" is exactly
    the word that would otherwise carry those 22 Arizona teams to Utah.
    """
    if not inferred:
        return False
    for code in _AFFILIATE_CODE.findall(text or ""):
        if code in _NOT_STATE_TOKENS:
            continue
        if code in STATE_NAMES.values() and code != inferred:
            return True
    return False


def _state_to_code(value: str) -> Optional[str]:
    """A teams.state value as a 2-letter code, or None when unrecognised."""
    text = (value or "").strip()
    if len(text) == 2 and text.upper() in set(STATE_NAMES.values()):
        return text.upper()
    return STATE_NAMES.get(re.sub(r"\s+", " ", text.lower()))


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

    sb = get_supabase()

    rows = fetch_candidates(sb)
    log(f"Live teams with no state_code (excluding placeholders): {len(rows)}")

    named, overruled = [], []
    for row in rows:
        inferred = state_from_name(row["team_name"])
        if not inferred:
            continue
        row["inferred"] = inferred

        # teams.state is a separate column the candidate query does not require.
        # Where it is populated it is a direct statement of location and beats a
        # name heuristic, so a disagreement means skip rather than overwrite.
        stated = (row.get("state") or "").strip()
        if stated and _state_to_code(stated) and _state_to_code(stated) != inferred:
            row["opponents"] = f"teams.state={stated!r}"
            overruled.append(row)
            continue
        named.append(row)

    opponent_counts = collect_opponent_states(sb, [row["team_id_master"] for row in named])

    planned, contradicted = [], []
    for row in named:
        counts = opponent_counts.get(row["team_id_master"], Counter())
        total = sum(counts.values())
        row["opponents"] = ";".join(f"{s}:{n}" for s, n in counts.most_common(4)) or "none"

        # Opponents corroborate where they exist. They are NOT required -- a
        # border-state club never reaches a dominant share (Oregon Surf is 40%
        # OR / 35% WA), which is exactly why the opponent backfill cannot serve
        # these. They only veto: if the name says OR and the opponents are
        # overwhelmingly one OTHER state, trust neither and skip.
        if total >= 5:
            top_state, top_count = counts.most_common(1)[0]
            if top_state != row["inferred"] and top_count / total >= 0.90:
                contradicted.append(row)
                continue
        planned.append(row)

    if args.limit is not None:
        planned = planned[: args.limit]

    log(f"  name states exactly one US state: {len(planned) + len(contradicted) + len(overruled)}")
    log(
        f"  planned: {len(planned)}   vetoed by opponents: {len(contradicted)}   "
        f"overruled by teams.state: {len(overruled)}"
    )
    log(f"  by state: {dict(Counter(r['inferred'] for r in planned).most_common(10))}")

    log("\nSample:")
    for row in planned[:12]:
        log(
            f"  [{row['inferred']}] {row['team_name'][:46]!r}  "
            f"club={str(row['club_name'])[:18]!r}  opp={row['opponents']}"
        )
    if len(planned) > 12:
        log(f"  ... and {len(planned) - 12} more")

    if overruled:
        log("\nSkipped (teams.state already says otherwise):")
        for row in overruled[:8]:
            log(f"  [{row['inferred']}?] {row['team_name'][:46]!r}  {row['opponents']}")

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
        return

    # Over PostgREST the scan and the write are no longer one transaction, so
    # each write re-asserts the precondition its own row was selected under --
    # NULL or empty, matching the two passes in fetch_candidates. A row filled
    # by another writer in between is skipped and reported, not overwritten.
    updated = 0
    for row in planned:
        write = (
            sb.table("teams")
            .update({"state_code": row["inferred"]})
            .eq("team_id_master", row["team_id_master"])
        )
        scanned_as = row["state_code"]
        write = write.is_("state_code", "null") if scanned_as is None else write.eq("state_code", scanned_as)
        updated += len((write.execute()).data or [])
    log(f"\nUpdated {updated} teams.")
    if updated != len(planned):
        log(f"  {len(planned) - updated} skipped: state_code was set between the scan and the write.")

    remaining = [row for row in fetch_candidates(sb) if state_from_name(row["team_name"])]
    log(f"Teams still missing state_code whose name names one: {len(remaining)}")


if __name__ == "__main__":
    main()
