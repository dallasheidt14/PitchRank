#!/usr/bin/env python3
"""Backfill missing state_code by inferring from opponents' state_codes.

For each team with no state_code, look at its games' opponents. If the team
has played at least MIN_OPPONENTS distinct opponents that have state_code,
and one state owns at least DOMINANCE_RATIO of them, assign that state.

Mirrors the dominance logic from match_state_from_club.py applied to game
opponents instead of clubmates. Designed to run AFTER Step 4 in the Monday
update-missing-club-and-state workflow as a residual catch-all.

Examples:
    python3 scripts/backfill_state_from_opponents.py --dry-run
    python3 scripts/backfill_state_from_opponents.py --dry-run --min-opponents 3
    python3 scripts/backfill_state_from_opponents.py --yes
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Set

from dotenv import load_dotenv

from supabase import create_client

# Defaults — same shape as match_state_from_club.py dominance constants.
MIN_OPPONENTS = 5
DOMINANCE_RATIO = 0.90
PAGE_SIZE = 1000
TEAMS_BATCH = 100  # how many no-state teams per games query

STATE_CODE_TO_NAME = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}
VALID_STATE_CODES = frozenset(STATE_CODE_TO_NAME.keys())


def load_env() -> None:
    env_local = Path(".env.local")
    if env_local.exists():
        load_dotenv(env_local, override=True)
    else:
        load_dotenv()


def get_supabase():
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_KEY")
    )
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY in env")
    return create_client(url, key)


def fetch_no_state_teams(sb) -> List[Dict]:
    teams: List[Dict] = []
    seen: Set[str] = set()
    for is_null in (True, False):
        offset = 0
        while True:
            q = (
                sb.table("teams")
                .select("team_id_master, team_name, club_name")
                .eq("is_deprecated", False)
            )
            q = q.is_("state_code", "null") if is_null else q.eq("state_code", "")
            res = q.range(offset, offset + PAGE_SIZE - 1).execute()
            rows = res.data or []
            for r in rows:
                tid = r.get("team_id_master")
                if tid and tid not in seen:
                    seen.add(tid)
                    teams.append(r)
            if len(rows) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    return teams


def collect_opponent_ids(sb, team_ids: List[str]) -> Dict[str, Set[str]]:
    """team_id_master -> {opponent_master_ids}, excluding self-opponents and excluded games."""
    by_team: Dict[str, Set[str]] = defaultdict(set)
    for i in range(0, len(team_ids), TEAMS_BATCH):
        batch = team_ids[i:i + TEAMS_BATCH]
        # Home-side games for these teams: opponent is away
        offset = 0
        while True:
            rows = (
                sb.table("games")
                .select("home_team_master_id, away_team_master_id")
                .in_("home_team_master_id", batch)
                .eq("is_excluded", False)
                .range(offset, offset + PAGE_SIZE - 1)
                .execute().data or []
            )
            if not rows:
                break
            for g in rows:
                t = g.get("home_team_master_id")
                o = g.get("away_team_master_id")
                if t and o and t != o:
                    by_team[t].add(o)
            if len(rows) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        # Away-side games for these teams: opponent is home
        offset = 0
        while True:
            rows = (
                sb.table("games")
                .select("home_team_master_id, away_team_master_id")
                .in_("away_team_master_id", batch)
                .eq("is_excluded", False)
                .range(offset, offset + PAGE_SIZE - 1)
                .execute().data or []
            )
            if not rows:
                break
            for g in rows:
                t = g.get("away_team_master_id")
                o = g.get("home_team_master_id")
                if t and o and t != o:
                    by_team[t].add(o)
            if len(rows) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    return by_team


def fetch_team_states(sb, team_ids: Set[str]) -> Dict[str, str]:
    """team_id_master -> state_code (skip teams with no state_code)."""
    out: Dict[str, str] = {}
    ids = [t for t in team_ids if t]
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        rows = (
            sb.table("teams")
            .select("team_id_master, state_code")
            .in_("team_id_master", batch)
            .not_.is_("state_code", "null")
            .neq("state_code", "")
            .execute().data or []
        )
        for r in rows:
            sc = (r.get("state_code") or "").strip().upper()
            if sc in VALID_STATE_CODES:
                out[r["team_id_master"]] = sc
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Preview without DB writes")
    ap.add_argument("--yes", action="store_true", help="Skip interactive confirm")
    ap.add_argument("--min-opponents", type=int, default=MIN_OPPONENTS,
                    help=f"Min unique opponents with state_code (default: {MIN_OPPONENTS})")
    ap.add_argument("--dominance-ratio", type=float, default=DOMINANCE_RATIO,
                    help=f"Dominance threshold 0..1 (default: {DOMINANCE_RATIO})")
    ap.add_argument("--limit", type=int, default=None, help="Cap teams to process")
    args = ap.parse_args()

    load_env()
    sb = get_supabase()

    print("=" * 80)
    print("Backfilling state_code from opponent dominance")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print(f"Thresholds: min_opponents={args.min_opponents}, dominance>={args.dominance_ratio:.0%}")
    print("=" * 80)

    teams = fetch_no_state_teams(sb)
    if args.limit:
        teams = teams[:args.limit]
    print(f"Found {len(teams)} teams without state_code")

    if not teams:
        print("Nothing to do.")
        return

    print("Step 1: collecting opponents from games...")
    opp_by_team = collect_opponent_ids(sb, [t["team_id_master"] for t in teams])
    print(f"  Teams with at least one game: {len(opp_by_team)}")

    print("Step 2: fetching opponent state_codes...")
    all_opp_ids: Set[str] = set()
    for s in opp_by_team.values():
        all_opp_ids |= s
    opp_state = fetch_team_states(sb, all_opp_ids)
    print(f"  Opponents with state_code: {len(opp_state)} / {len(all_opp_ids)}")

    print("Step 3: applying dominance...")
    matches: List[Dict] = []
    no_games: List[Dict] = []
    too_few_opp: List[Dict] = []
    no_dominance: List[Dict] = []

    for team in teams:
        tid = team["team_id_master"]
        opps = opp_by_team.get(tid, set())
        if not opps:
            no_games.append(team)
            continue
        states = Counter(opp_state.get(o) for o in opps if opp_state.get(o))
        usable = sum(states.values())
        if usable < args.min_opponents:
            too_few_opp.append({"team": team, "usable": usable})
            continue
        top_state, top_n = states.most_common(1)[0]
        ratio = top_n / usable
        if ratio < args.dominance_ratio:
            no_dominance.append({"team": team, "states": dict(states.most_common(5)), "ratio": ratio})
            continue
        matches.append({
            "team_id_master": tid,
            "team_name": team["team_name"],
            "club_name": team.get("club_name") or "",
            "matched_state_code": top_state,
            "ratio": ratio,
            "n_opponents": usable,
            "states_seen": dict(states.most_common(5)),
        })

    print()
    print(f"  Matched (opponent dominance): {len(matches)}")
    print(f"  Skipped - no games:           {len(no_games)}")
    print(f"  Skipped - too few opponents:  {len(too_few_opp)}")
    print(f"  Skipped - no dominance:       {len(no_dominance)}")
    print()

    print("Sample matches (first 15):")
    print("-" * 80)
    for i, m in enumerate(matches[:15], 1):
        print(f" {i:2d}. {m['team_name'][:40]:<40} → {m['matched_state_code']} "
              f"({m['ratio']:.0%} of {m['n_opponents']} opponents) {m['states_seen']}")
    if no_dominance:
        print()
        print("Sample non-dominance (first 5):")
        for nd in no_dominance[:5]:
            print(f"  {nd['team']['team_name'][:40]:<40} top={nd['ratio']:.0%}  states={nd['states']}")
    print()

    if not matches:
        print("No matches to apply.")
        return

    if args.dry_run:
        print(f"DRY RUN: would update {len(matches)} teams")
        return

    if not args.yes:
        ans = input(f"Update {len(matches)} teams via opponent inference? (yes/no): ").strip().lower()
        if ans != "yes":
            print("Cancelled.")
            return

    print("Updating teams...")
    by_state: Dict[str, List[str]] = defaultdict(list)
    for m in matches:
        by_state[m["matched_state_code"]].append(m["team_id_master"])

    updated = 0
    errors = 0
    for code, ids in by_state.items():
        name = STATE_CODE_TO_NAME.get(code)
        for i in range(0, len(ids), 100):
            batch = ids[i:i + 100]
            try:
                payload = {"state_code": code}
                if name:
                    payload["state"] = name
                sb.table("teams").update(payload).in_("team_id_master", batch).execute()
                updated += len(batch)
                print(f"  Updated {updated}/{len(matches)} ({code}: +{len(batch)})...")
            except Exception as e:
                errors += len(batch)
                print(f"  ERROR updating batch ({code}): {e}")

    print()
    print("=" * 80)
    print(f"Updated: {updated}")
    print(f"Errors:  {errors}")
    print("Done.")


if __name__ == "__main__":
    main()
