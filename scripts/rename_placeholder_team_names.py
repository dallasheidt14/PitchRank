#!/usr/bin/env python3
"""Rename every team still named ``unknown_<provider_team_id>`` to "Unknown team". Dry run unless --execute.

team_name is publicly readable, and that old placeholder name carried the provider's id. Merged-away
(deprecated) rows are renamed as well, since they carry the id too. A real name that happens to start
``unknown_`` (``unknown_elite``) is never touched: only a name that is ``unknown_`` followed by the
row's own provider_team_id is renamed.

Every candidate is selected before anything is written, paging by team_id_master. Each rename is
logged to ``<out>/placeholder_rename_<UTC>.jsonl`` before its write, then its outcome: ``renamed``,
``skipped`` (the row no longer held the old name) or ``failed`` (it still did, so the write did not
take). The write is a compare-and-set on the old name, and a write whose answer was lost is settled by
reading the row back. ``--undo <log>`` restores the old name only where the team still holds
"Unknown team"; like a rename, it writes only with --execute.

Run it only after the migration that makes the scrape functions skip "Unknown team" is live and the
code that writes the new name has merged, from a checkout of that main, and only when no
unknown-opponent-hygiene-weekly run started before the merge is still unfinished: such a run keeps
writing old-form names.

The log is the only undo, so --out may not sit inside a linked git worktree, which
``git worktree remove`` deletes together with its ignored files.

Usage:
    python scripts/rename_placeholder_team_names.py
    python scripts/rename_placeholder_team_names.py --execute --out C:/PitchRank/data/backups --limit 1000
    python scripts/rename_placeholder_team_names.py --undo <log> [--execute]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from postgrest.exceptions import APIError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.utils.gotsport_alias import is_rankings_space_id  # noqa: E402
from src.utils.placeholder_team_names import PLACEHOLDER_TEAM_NAME, is_placeholder_team_name  # noqa: E402
from supabase import create_client  # noqa: E402

PAGE_SIZE = 1000
COLUMNS = "team_id_master,team_name,provider_team_id,is_deprecated"
SAMPLE_SIZE = 10


def _new_client():
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / ".env.local", override=True)
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("ERROR: missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def is_legacy_placeholder(team: dict) -> bool:
    """The old form: ``unknown_`` and this row's own provider_team_id."""
    name = team.get("team_name") or ""
    return name.startswith("unknown_") and is_placeholder_team_name(name, str(team.get("provider_team_id") or ""))


def select_renames(sb) -> list[dict]:
    """Every row, deprecated included, still named the old form, in team_id_master order."""
    teams, after = [], None
    while True:
        query = sb.table("teams").select(COLUMNS).like("team_name", "unknown\\_%")
        if after:
            query = query.gt("team_id_master", after)
        rows = query.order("team_id_master").limit(PAGE_SIZE).execute().data or []
        teams.extend(row for row in rows if is_legacy_placeholder(row))
        if len(rows) < PAGE_SIZE:
            return teams
        after = rows[-1]["team_id_master"]


def summarize(teams: list[dict]) -> Counter:
    counts: Counter = Counter()
    for team in teams:
        state = "deprecated" if team["is_deprecated"] else "live"
        space = "rankings id" if is_rankings_space_id(team["provider_team_id"]) else "event id"
        counts[(state, space)] += 1
    return counts


def _rename_one(sb, team: dict) -> str:
    answered = True
    try:
        moved = (
            sb.table("teams")
            .update({"team_name": PLACEHOLDER_TEAM_NAME})
            .eq("team_id_master", team["team_id_master"])
            .eq("team_name", team["team_name"])
            .execute()
            .data
        )
    except (APIError, httpx.HTTPError):
        moved, answered = None, False
    if moved:
        return "renamed"
    now = sb.table("teams").select("team_name").eq("team_id_master", team["team_id_master"]).execute().data
    name = now[0]["team_name"] if now else None
    if name == team["team_name"]:
        return "failed"
    if not answered and name == PLACEHOLDER_TEAM_NAME:
        return "renamed"
    return "skipped"


def rename(sb, teams: list[dict], log_path: Path) -> Counter:
    counts: Counter = Counter()
    with log_path.open("x", encoding="utf-8") as log:
        for team in teams:
            entry = {
                "kind": "rename",
                "team_id_master": team["team_id_master"],
                "old": team["team_name"],
                "new": PLACEHOLDER_TEAM_NAME,
                "at": datetime.now(timezone.utc).isoformat(),
            }
            log.write(json.dumps(entry) + "\n")
            log.flush()
            outcome = _rename_one(sb, team)
            settled = {"kind": "outcome", "team_id_master": team["team_id_master"], "outcome": outcome}
            log.write(json.dumps(settled) + "\n")
            log.flush()
            counts[outcome] += 1
            if outcome == "failed":
                print(f"Rename of {team['team_id_master']} did not take: it still holds {team['team_name']!r}")
    return counts


def restorable(log_path: Path) -> list[dict]:
    """The logged renames that may have committed: every one but those logged skipped or failed."""
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    settled = {e["team_id_master"]: e["outcome"] for e in entries if e["kind"] == "outcome"}
    return [e for e in entries if e["kind"] == "rename" and settled.get(e["team_id_master"], "renamed") == "renamed"]


def undo(sb, log_path: Path) -> int:
    restored = 0
    for entry in reversed(restorable(log_path)):
        rows = (
            sb.table("teams")
            .update({"team_name": entry["old"]})
            .eq("team_id_master", entry["team_id_master"])
            .eq("team_name", entry["new"])
            .execute()
            .data
        )
        restored += len(rows or [])
    return restored


def in_linked_worktree(path: Path) -> bool:
    """Whether ``path`` sits in a linked git worktree, whose root holds a ``.git`` file, not a directory."""
    for folder in (path.resolve(), *path.resolve().parents):
        marker = folder / ".git"
        if marker.exists():
            return marker.is_file()
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execute", action="store_true", help="write the renames, or with --undo restore them")
    parser.add_argument("--out", type=Path, help="directory for the rename log (required with --execute)")
    parser.add_argument("--limit", type=int, help="rename at most this many teams in this run")
    parser.add_argument("--undo", type=Path, help="restore the old names logged in this file")
    args = parser.parse_args(argv)

    if args.undo:
        if not args.execute:
            count = len(restorable(args.undo))
            print(f"DRY RUN — nothing written; {count} logged renames to restore where the team still holds")
            print(f"{PLACEHOLDER_TEAM_NAME!r}.")
            return 0
        print(f"names_restored={undo(_new_client(), args.undo)}")
        return 0

    if args.execute and not args.out:
        raise SystemExit("ERROR: --execute needs --out <dir> for the rename log, the only way to undo it")
    if args.out and in_linked_worktree(args.out):
        raise SystemExit(f"ERROR: {args.out} is inside a linked git worktree, which removing it would delete")

    sb = _new_client()
    teams = select_renames(sb)
    if args.limit is not None:
        teams = teams[: args.limit]
    for (state, space), count in sorted(summarize(teams).items()):
        print(f"{state:10} {space:12} {count:,}")
    print(f"total      {len(teams):,}")

    if not args.execute:
        for team in teams[:SAMPLE_SIZE]:
            print(f"  {team['team_id_master']}: {team['team_name']!r} -> {PLACEHOLDER_TEAM_NAME!r}")
        print("DRY RUN — nothing written.")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    log_path = args.out / f"placeholder_rename_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    counts = rename(sb, teams, log_path)
    print(" ".join(f"{outcome}={counts[outcome]}" for outcome in ("renamed", "skipped", "failed")))
    print(f"Undo with: --undo {log_path} --execute")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
