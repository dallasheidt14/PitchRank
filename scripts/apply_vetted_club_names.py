#!/usr/bin/env python3
"""Move teams filed under the wrong club to the club their own name states.

A provider that prefixes a team name with the host club's code -- Athletes2Events
and GotSport both write "XL - BUFC B17 Blue" for a Bellevue United team playing a
Crossfire event -- leaves the importer reading that prefix as the club. The team
is then created under the host's club, appears on the host's club page, and joins
the candidate pool for every one of that club's later matches.

This script writes nothing it was not handed: it applies a vetted list, one entry
per team, each carrying the evidence that decided it. The judgement is made and
reviewed before the file is written, never inferred here -- a rule that reads the
club out of a team name is exactly what created the defect.

Dry run by default. ``--execute`` writes and logs every change to a CSV that
``--revert`` replays backwards.

Usage:
    python scripts/apply_vetted_club_names.py --file vetted.json
    python scripts/apply_vetted_club_names.py --file vetted.json --execute --log out.csv
    python scripts/apply_vetted_club_names.py --revert out.csv --execute
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from supabase import create_client  # noqa: E402

console = Console()

_env_local = Path(".env.local")
load_dotenv(_env_local if _env_local.exists() else Path(".env"))

REQUIRED_FIELDS = ("team_id_master", "from_club", "to_club", "evidence")
LOG_COLUMNS = ["team_id_master", "team_name", "from_club", "to_club", "evidence"]


def load_vetted(path: Path) -> List[Dict]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    for entry in entries:
        missing = [f for f in REQUIRED_FIELDS if not entry.get(f)]
        if missing:
            raise ValueError(f"entry {entry.get('team_id_master')} is missing {missing}")
    return entries


def current_clubs(supabase, team_ids: List[str]) -> Dict[str, Dict]:
    found: Dict[str, Dict] = {}
    for i in range(0, len(team_ids), 100):
        result = (
            supabase.table("teams")
            .select("team_id_master, team_name, club_name, is_deprecated")
            .in_("team_id_master", team_ids[i : i + 100])
            .execute()
        )
        for row in result.data or []:
            found[row["team_id_master"]] = row
    return found


def plan(entries: List[Dict], live: Dict[str, Dict]) -> tuple[List[Dict], List[str]]:
    """Split the vetted list into what still applies and what the database has moved on from."""
    apply_now: List[Dict] = []
    stale: List[str] = []
    for entry in entries:
        row = live.get(entry["team_id_master"])
        if row is None:
            stale.append(f"{entry['team_id_master']}: no such team")
        elif row["is_deprecated"]:
            stale.append(f"{entry['team_id_master']}: deprecated since the list was vetted")
        elif row["club_name"] == entry["to_club"]:
            stale.append(f"{entry['team_id_master']}: already {entry['to_club']!r}")
        elif row["club_name"] != entry["from_club"]:
            stale.append(f"{entry['team_id_master']}: club is now {row['club_name']!r}, not {entry['from_club']!r}")
        else:
            apply_now.append({**entry, "team_name": row["team_name"]})
    return apply_now, stale



def resolve_log_path(requested: Optional[Path], now: Optional[datetime] = None) -> Path:
    """The file this run records its moves in, which is never one that already exists.

    The log is the only way back from a batch, so overwriting it destroys the
    record of moves already committed. The default carries a timestamp so ordinary
    runs cannot collide; an explicitly named file that exists stops the run.
    """
    path = requested or Path("data/logs") / f"club_name_changes_{now or datetime.now():%Y%m%d_%H%M%S}.csv"
    if path.exists():
        raise FileExistsError(path)
    return path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--file", type=Path, help="Vetted JSON list")
    p.add_argument("--revert", type=Path, help="Undo a previous --execute from its CSV log")
    p.add_argument("--execute", action="store_true", help="Write (default is a dry run)")
    p.add_argument("--dry-run", action="store_true", help="Force a dry run; wins over --execute")
    p.add_argument(
        "--log",
        type=Path,
        help="Where to record the moves (default: a timestamped file under data/logs/)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.file and not args.revert:
        console.print("[red]--file or --revert is required[/red]")
        return 1

    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        console.print("[red]SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set[/red]")
        return 1
    supabase = create_client(url, key)

    if args.revert:
        logged = list(csv.DictReader(args.revert.open(encoding="utf-8")))
        entries = [
            {
                "team_id_master": r["team_id_master"],
                "from_club": r["to_club"],
                "to_club": r["from_club"],
                "evidence": f"revert of {args.revert.name}",
            }
            for r in logged
        ]
    else:
        entries = load_vetted(args.file)

    live = current_clubs(supabase, [e["team_id_master"] for e in entries])
    apply_now, stale = plan(entries, live)

    table = Table(title=f"{len(apply_now)} to move, {len(stale)} skipped")
    for column in ("team", "from", "to", "why"):
        table.add_column(column)
    for entry in apply_now:
        table.add_row(entry["team_name"][:34], entry["from_club"][:28], entry["to_club"][:28], entry["evidence"][:44])
    console.print(table)
    for reason in stale:
        console.print(f"  [yellow]skipped {reason}[/yellow]")

    if args.dry_run or not args.execute:
        console.print("\n[yellow]Dry run — nothing written. Add --execute to apply.[/yellow]")
        return 0
    if not apply_now:
        console.print("\nNothing to apply.")
        return 0

    try:
        log_path = resolve_log_path(args.log)
    except FileExistsError as existing:
        console.print(f"[red]{existing} already exists; it records an earlier batch. Name another --log.[/red]")
        return 1

    # Each move is logged and flushed before the next one runs. Writing the log
    # after the loop loses the record of everything already committed when a later
    # update raises, and --revert then cannot tell which subset was applied.
    log_path.parent.mkdir(parents=True, exist_ok=True)
    written = []
    with log_path.open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
        writer.writeheader()
        f.flush()
        for entry in apply_now:
            supabase.table("teams").update({"club_name": entry["to_club"]}).eq(
                "team_id_master", entry["team_id_master"]
            ).execute()
            row = {c: entry.get(c, "") for c in LOG_COLUMNS}
            writer.writerow(row)
            f.flush()
            written.append(row)

    after = current_clubs(supabase, [e["team_id_master"] for e in apply_now])
    wrong = [
        e["team_id_master"] for e in apply_now if after.get(e["team_id_master"], {}).get("club_name") != e["to_club"]
    ]
    console.print(f"\nMoved {len(written) - len(wrong)} of {len(written)}; log: {log_path}")
    if wrong:
        console.print(f"[red]{len(wrong)} did not take: {wrong}[/red]")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
