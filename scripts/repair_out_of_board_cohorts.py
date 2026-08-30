#!/usr/bin/env python3
"""
Re-resolve teams stored in a cohort that cannot be right, and correct them.

The unknown-opponent chain used to take a discovered team's age group from the team
it had played, so a mislabelled row seeded its cohort into every opponent it faced.
That is fixed at the source; these are the rows it already wrote. Each one is asked
of GotSport again and rewritten from its own record.

Only impossible cohorts are in scope by default. u8 and u9 are deliberately excluded:
GotSport reports real U8 and U9 teams and PitchRank simply does not board them, so
those rows are accurate. u20 is excluded too, and needs its own pass -- a stored U20
label does not say which season wrote it, so folding it into u19 would put aged-out
2006 squads onto the U19 board.

Every write is logged to a CSV that --revert replays backwards.

Usage:
    python scripts/repair_out_of_board_cohorts.py                     # dry run
    python scripts/repair_out_of_board_cohorts.py --execute
    python scripts/repair_out_of_board_cohorts.py --revert data/exports/<log>.csv
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

from config.settings import AGE_GROUPS  # noqa: E402
from src.utils.gotsport_team_details import TeamDetailsResolver  # noqa: E402

# Cohorts that cannot describe a real youth team. u8/u9 are real but unboarded, and
# u20 needs season evidence this script does not have.
IMPOSSIBLE_COHORTS = ("u0", "u1", "u2", "u3", "u4", "u5", "u6", "u7", "u21", "u22")

# Labels normalize_age_group collapses into u19. Accepting one here would write the
# oldest board from a label that does not say which season produced it.
FOLDED_INTO_U19 = frozenset({"U18", "U20"})

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


def fetch_target_teams(supabase, cohorts: List[str], limit: Optional[int]) -> List[Dict]:
    page_size = 1000
    offset = 0
    rows: List[Dict] = []
    while True:
        batch = (
            supabase.table("teams")
            .select("team_id_master,team_name,age_group,gender,state_code")
            .eq("is_deprecated", False)
            .in_("age_group", cohorts)
            .order("team_id_master")
            .range(offset, offset + page_size - 1)
            .execute()
            .data
            or []
        )
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    rows.sort(key=lambda r: (r.get("age_group") or "", r.get("team_name") or ""))
    return rows[:limit] if limit else rows


def fetch_gotsport_aliases(supabase, team_ids: List[str]) -> Dict[str, str]:
    provider = supabase.table("providers").select("id").eq("code", "gotsport").execute().data
    if not provider:
        return {}
    provider_id = provider[0]["id"]

    aliases: Dict[str, str] = {}
    for i in range(0, len(team_ids), 100):
        batch = team_ids[i : i + 100]
        rows = (
            supabase.table("team_alias_map")
            .select("team_id_master,provider_team_id")
            .eq("provider_id", provider_id)
            .in_("team_id_master", batch)
            .execute()
            .data
            or []
        )
        for row in rows:
            tid, pid = row["team_id_master"], str(row["provider_team_id"]).strip()
            # Bracket placeholders ("Playoffs AWinner") reach this column too, and
            # team_details only answers to a numeric id. Among real ids the lowest
            # is the earliest registration, which is the one with a club record.
            if not pid.isdigit():
                continue
            if tid not in aliases or int(pid) < int(aliases[tid]):
                aliases[tid] = pid
    return aliases


def decide(old: Optional[str], pid: Optional[str], resolved: Optional[Dict]) -> tuple:
    """Return ``(action, new_age_group)`` for one team's re-resolution."""
    if not pid:
        return "skipped_no_alias", None
    if not resolved:
        return "skipped_lookup_failed", None
    new = resolved.get("age_group")
    if new is None:
        return "skipped_provider_has_no_cohort", None
    if str(resolved.get("raw_age_group", "")).strip().upper() in FOLDED_INTO_U19:
        # normalize_age_group folds U18 and U20 into u19, which is right for a fresh
        # label but not decidable here: the provider does not say whether the team
        # is a 2007 U19 squad or an aged-out 2006 one. Same reason u20 is out of scope.
        return "skipped_needs_season_evidence", new
    if new == old:
        return "skipped_already_correct", new
    if new not in AGE_GROUPS:
        # GotSport's U-age advances every Aug 1 while the stored label does not, so
        # a row stamped u3 last season reads U4 now. Writing that moves the team
        # between two unboarded cohorts and churns again next year; only a cohort
        # PitchRank boards earns the write.
        return "skipped_provider_cohort_unboarded", new
    return "updated", new


def write_log(rows: List[Dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def revert(supabase, log_path: Path, execute: bool) -> int:
    with log_path.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("action") == "updated"]

    for row in rows:
        print(f"  {row['team_name'][:44]:44s} {row['new_age_group']} -> {row['old_age_group']}")
        if execute:
            supabase.table("teams").update({"age_group": row["old_age_group"]}).eq(
                "team_id_master", row["team_id_master"]
            ).execute()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--execute", action="store_true", help="Apply changes (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Force a dry run; wins over --execute")
    parser.add_argument("--limit", type=int, help="Only consider the first N teams")
    parser.add_argument(
        "--cohorts",
        default=",".join(IMPOSSIBLE_COHORTS),
        help="Comma-separated cohorts to repair",
    )
    parser.add_argument("--revert", type=Path, help="Undo a previous run from its CSV log")
    args = parser.parse_args()
    # Fail safe: asking for both means the caller wants the preview.
    execute = args.execute and not args.dry_run

    load_env()
    supabase = get_supabase()

    if args.revert:
        print(f"=== Revert {args.revert} ({'EXECUTE' if execute else 'DRY-RUN'}) ===")
        count = revert(supabase, args.revert, execute)
        print(f"\n{'Reverted' if execute else 'Would revert'}: {count}")
        return

    cohorts = [c.strip().lower() for c in args.cohorts.split(",") if c.strip()]
    print(f"=== Repair out-of-board cohorts ({'EXECUTE' if execute else 'DRY-RUN'}) ===")
    print(f"Cohorts: {', '.join(cohorts)}")

    teams = fetch_target_teams(supabase, cohorts, args.limit)
    print(f"Teams in scope: {len(teams)}")
    if not teams:
        return

    aliases = fetch_gotsport_aliases(supabase, [t["team_id_master"] for t in teams])
    print(f"With a GotSport alias: {len(aliases)}\n")

    resolver = TeamDetailsResolver()
    log_rows: List[Dict] = []
    counts: Dict[str, int] = {}

    for team in teams:
        tid = team["team_id_master"]
        old = team.get("age_group")
        pid = aliases.get(tid)

        resolved = resolver.resolve(pid) if pid else None
        action, new = decide(old, pid, resolved)
        raw = (resolved or {}).get("raw_age_group", "")

        counts[action] = counts.get(action, 0) + 1
        log_rows.append(
            {
                "team_id_master": tid,
                "team_name": team.get("team_name") or "",
                "provider_team_id": pid or "",
                "old_age_group": old or "",
                "new_age_group": new or "",
                "provider_label": raw,
                "action": action,
            }
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = EXPORTS_DIR / f"repair_out_of_board_cohorts_{stamp}.csv"
    planned = [r for r in log_rows if r["action"] == "updated"]
    # The log is the only way back, so it lands before the first write and again
    # after the last. A run that dies mid-loop still leaves every applied row on disk.
    write_log(log_rows, log_path)

    applied = set()
    try:
        for row in planned:
            print(f"  {row['team_name'][:44]:44s} {row['old_age_group']} -> {row['new_age_group']}"
                  f"   (GotSport: {row['provider_label']})")
            if execute:
                supabase.table("teams").update({"age_group": row["new_age_group"]}).eq(
                    "team_id_master", row["team_id_master"]
                ).execute()
            applied.add(row["team_id_master"])
    finally:
        if execute:
            for row in planned:
                if row["team_id_master"] not in applied:
                    row["action"] = "planned_not_applied"
        write_log(log_rows, log_path)

    print("\n=== Summary ===")
    for action in sorted(counts):
        print(f"{action}: {counts[action]}")
    print(f"\nLog: {log_path}")
    if not execute and counts.get("updated"):
        print(f"Re-run with --execute to apply. Undo with --revert {log_path} --execute")


if __name__ == "__main__":
    main()
