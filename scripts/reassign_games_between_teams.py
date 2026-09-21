#!/usr/bin/env python3
"""
Move one block of games from one team to another, for a recycled provider record.

Games are immutable here and this script keeps them that way: a game's date, scores,
competition and provider ids are left exactly as imported. It rewrites only which team
the game is filed under, which is the one field an import can get wrong through no
fault of its own. A club can hand a GotSport team record to a different squad at the
August rollover, and every game the record serves afterwards belongs to a different
team than the ones before it.

Scope is a single (team, date window) block, so a record shared by two squads is split
by running this once per block. A move with no window is a whole-team merge and belongs
to the merge tooling instead.

Every write is guarded on the team id it replaces, so a game that moved since the read
is reported rather than overwritten, and every run logs a CSV that --revert replays
backwards.

Usage:
    python scripts/reassign_games_between_teams.py --from <uuid> --to <uuid> --before 2026-08-01
    python scripts/reassign_games_between_teams.py --from <uuid> --to <uuid> --since 2026-08-01 --execute
    python scripts/reassign_games_between_teams.py --revert data/exports/<log>.csv --execute
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

from supabase import create_client

sys.path.append(str(Path(__file__).resolve().parent.parent))

EXPORTS_DIR = Path("data/exports")


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
        raise ValueError(
            "Missing Supabase credentials. "
            "Need SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_SERVICE_KEY/SUPABASE_KEY."
        )
    return create_client(supabase_url, supabase_key)


def fetch_team(supabase, team_id: str) -> Optional[Dict]:
    rows = (
        supabase.table("teams")
        .select("team_id_master,team_name,age_group,gender,state_code,is_deprecated")
        .eq("team_id_master", team_id)
        .eq("is_deprecated", False)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def fetch_games(supabase, team_id: str, since: Optional[str], before: Optional[str]) -> List[Dict]:
    page_size = 1000
    offset = 0
    rows: List[Dict] = []
    while True:
        query = (
            supabase.table("games")
            .select("id,game_date,home_team_master_id,away_team_master_id,home_score,away_score,competition")
            .or_(f"home_team_master_id.eq.{team_id},away_team_master_id.eq.{team_id}")
        )
        if since:
            query = query.gte("game_date", since)
        if before:
            query = query.lt("game_date", before)
        batch = query.order("id").range(offset, offset + page_size - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        offset += page_size


def decide(game: Dict, from_team: str, to_team: str) -> Dict[str, str]:
    home = game.get("home_team_master_id")
    away = game.get("away_team_master_id")
    side = "home" if home == from_team else "away"
    opponent = away if side == "home" else home

    if home == from_team and away == from_team:
        return {"action": "skipped_self_game", "side": side, "opponent": opponent or ""}
    if opponent == to_team:
        return {"action": "skipped_would_self_play", "side": side, "opponent": opponent or ""}
    return {"action": "moved", "side": side, "opponent": opponent or ""}


def write_log(rows: List[Dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def apply_move(supabase, game_id: str, side: str, expected: str, target: str) -> bool:
    column = f"{side}_team_master_id"
    result = supabase.table("games").update({column: target}).eq("id", game_id).eq(column, expected).execute()
    return bool(result.data)


def revert(supabase, log_path: Path, execute: bool) -> Dict[str, int]:
    with log_path.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("action") == "moved"]

    counts = {"reverted": 0, "already_moved_on": 0}
    for row in rows:
        print(
            f"  {row['game_date']}  {row['game_id'][:8]}  {row['side']:4s} "
            f"{row['to_team_id'][:8]} -> {row['from_team_id'][:8]}"
        )
        if not execute:
            counts["reverted"] += 1
            continue
        moved = apply_move(supabase, row["game_id"], row["side"], row["to_team_id"], row["from_team_id"])
        counts["reverted" if moved else "already_moved_on"] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="from_team", help="team_id_master the games are filed under now")
    parser.add_argument("--to", dest="to_team", help="team_id_master they should be filed under")
    parser.add_argument("--since", help="Only games on or after this date (YYYY-MM-DD)")
    parser.add_argument("--before", help="Only games strictly before this date (YYYY-MM-DD)")
    parser.add_argument("--execute", action="store_true", help="Apply changes (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Force a dry run; wins over --execute")
    parser.add_argument("--limit", type=int, help="Only move the first N games")
    parser.add_argument("--revert", type=Path, help="Undo a previous run from its CSV log")
    args = parser.parse_args()
    # Fail safe: asking for both means the caller wants the preview.
    execute = args.execute and not args.dry_run

    load_env()
    supabase = get_supabase()

    if args.revert:
        print(f"=== Revert {args.revert} ({'EXECUTE' if execute else 'DRY-RUN'}) ===")
        counts = revert(supabase, args.revert, execute)
        print(f"\n{'Reverted' if execute else 'Would revert'}: {counts['reverted']}")
        if counts["already_moved_on"]:
            print(f"Left alone (moved on since the run): {counts['already_moved_on']}")
        return

    if not args.from_team or not args.to_team:
        parser.error("--from and --to are both required unless --revert is given")
    if args.from_team == args.to_team:
        parser.error("--from and --to are the same team")
    if not args.since and not args.before:
        parser.error("give --since and/or --before; an unwindowed move is a merge, not a reassignment")

    source = fetch_team(supabase, args.from_team)
    target = fetch_team(supabase, args.to_team)
    if not source:
        parser.error(f"--from {args.from_team} is not a live team")
    if not target:
        parser.error(f"--to {args.to_team} is not a live team")

    window = f"{args.since or '(any)'} .. {args.before or '(any)'}"
    print(f"=== Reassign games ({'EXECUTE' if execute else 'DRY-RUN'}) ===")
    print(f"From:   {source['team_name']}  [{source['age_group']} {source['gender']} {source['state_code']}]")
    print(f"To:     {target['team_name']}  [{target['age_group']} {target['gender']} {target['state_code']}]")
    print(f"Window: {window}\n")

    games = fetch_games(supabase, args.from_team, args.since, args.before)
    log_rows: List[Dict] = []
    counts: Dict[str, int] = {}

    for game in games:
        verdict = decide(game, args.from_team, args.to_team)
        counts[verdict["action"]] = counts.get(verdict["action"], 0) + 1
        log_rows.append(
            {
                "game_id": game["id"],
                "game_date": game.get("game_date") or "",
                "side": verdict["side"],
                "from_team_id": args.from_team,
                "to_team_id": args.to_team,
                "opponent_team_id": verdict["opponent"],
                "competition": game.get("competition") or "",
                "home_score": "" if game.get("home_score") is None else game["home_score"],
                "away_score": "" if game.get("away_score") is None else game["away_score"],
                "action": verdict["action"],
            }
        )

    if not log_rows:
        print("No games in that window.")
        return

    planned = [r for r in log_rows if r["action"] == "moved"]
    if args.limit is not None:
        for row in planned[args.limit :]:
            row["action"] = "skipped_over_limit"
        planned = planned[: args.limit]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = EXPORTS_DIR / f"reassign_games_between_teams_{stamp}.csv"
    # The log is the only way back, so it lands before the first write and again after
    # the last. A run that dies mid-loop still leaves every applied row on disk.
    write_log(log_rows, log_path)

    applied = set()
    try:
        for row in planned:
            score = f"{row['home_score']}-{row['away_score']}" if row["home_score"] != "" else "  -  "
            print(f"  {row['game_date']}  {score:>7s}  {row['side']:4s}  {row['competition'][:38]}")
            if not execute:
                continue
            if apply_move(supabase, row["game_id"], row["side"], args.from_team, args.to_team):
                applied.add(row["game_id"])
            else:
                row["action"] = "skipped_changed_since_read"
    finally:
        if execute:
            for row in planned:
                if row["game_id"] not in applied and row["action"] == "moved":
                    row["action"] = "planned_not_applied"
        write_log(log_rows, log_path)

    print("\n=== Summary ===")
    for action in sorted({r["action"] for r in log_rows}):
        print(f"{action}: {sum(1 for r in log_rows if r['action'] == action)}")
    print(f"\nLog: {log_path}")
    if not execute and planned:
        print(f"Re-run with --execute to apply. Undo with --revert {log_path} --execute")


if __name__ == "__main__":
    main()
