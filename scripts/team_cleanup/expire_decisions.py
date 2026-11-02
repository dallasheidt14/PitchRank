#!/usr/bin/env python3
"""Let the reviewers' refusals lapse at the eighth weekly run, so that week's scans and reviews judge them again.

A Keep separate or Don't apply that a week's review recorded (source auto:<page run>) lapses at the eighth
weekly run after its own (owner, 2026-10-31): it is superseded, and every reader takes only the rows with no
superseded_at, so the pair or the change can be proposed again and is reviewed afresh. Every other source is the
owner's own, and never lapses. What lapsed is listed in <run>/expired_decisions.json, which the run's summary
email lists; it is written before anything is stamped, and a re-run adds to it rather than replacing it.

Dry run unless --execute.

Usage:
    python scripts/team_cleanup/expire_decisions.py --run 2026-11-04-all
    python scripts/team_cleanup/expire_decisions.py --run 2026-11-04-all --execute
"""

from __future__ import annotations

import argparse
import html
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.find_cross_provider_duplicates import batched, get_client, page  # noqa: E402
from scripts.team_cleanup.decisions import (  # noqa: E402
    DECISIONS_TABLE,
    DONT_APPLY,
    KEEP_SEPARATE,
    MERGES,
    REVIEWED_SOURCE,
    resolve_execute,
)
from scripts.team_cleanup.review_page import fetch_teams  # noqa: E402
from scripts.team_cleanup.run_store import run_dir, store_dir  # noqa: E402
from src.tournaments.storage._io import read_json, utc_now_iso, write_json  # noqa: E402

LAPSE_WEEKS = 8
WEDNESDAY = 2
LAPSING = (KEEP_SEPARATE, DONT_APPLY)
EXPIRED_FILE = "expired_decisions.json"
LAPSING_COLS = "id,stage,team_id_master,other_team_id,field,proposed_value,decision,decided_at,source"


def lapse_before(run_id: str) -> datetime:
    """The start of the cleanup week seven weeks before the run's, so a refusal recorded in the week eight weeks back,
    or earlier, lapses. A week starts on the Wednesday its run is proposed, and a refusal is dated by its page's
    build, after that propose and before the next week's."""
    day = date.fromisoformat(run_id[:10])
    week = day - timedelta(days=(day.weekday() - WEDNESDAY) % 7)
    return datetime.combine(week - timedelta(weeks=LAPSE_WEEKS - 1), time(), tzinfo=timezone.utc)


def lapsing(sb, before: datetime) -> list[dict]:
    return page(
        lambda: (
            sb.table(DECISIONS_TABLE)
            .select(LAPSING_COLS)
            .is_("superseded_at", "null")
            .like("source", f"{REVIEWED_SOURCE}%")
            .in_("decision", list(LAPSING))
            .lt("decided_at", before.isoformat())
        ),
        "id",
    )


def with_names(sb, rows: list[dict]) -> list[dict]:
    """Each row with its teams' names."""
    ids = sorted({r["team_id_master"] for r in rows} | {r["other_team_id"] for r in rows if r["other_team_id"]})
    names = {team_id: team["team_name"] for team_id, team in fetch_teams(sb, ids).items()}
    return [
        {**r, "team_name": names.get(r["team_id_master"]), "other_team_name": names.get(r["other_team_id"])}
        for r in rows
    ]


def lapsed_text(row: dict) -> str:
    since = row["decided_at"][:10]
    if row["stage"] == MERGES:
        return f"merges: {row['team_name']} and {row['other_team_name']}, kept separate since {since}"
    return f"{row['stage']}: {row['team_name']} → {row['proposed_value']}, declined since {since}"


def expire(sb, store: Path, run_id: str, execute: bool) -> int:
    """Stamp the lapsing refusals superseded, listing them in the run's EXPIRED_FILE first; how many lapsed."""
    rows = with_names(sb, lapsing(sb, lapse_before(run_id)))
    if not execute:
        for row in rows:
            print(f"would lapse: {lapsed_text(row)}")
        print(f"DRY RUN -- {len(rows)} of the reviewers' decisions would lapse; nothing written.")
        return len(rows)
    path = run_dir(store, run_id) / EXPIRED_FILE
    listed = read_json(path) if path.exists() else []
    seen = {r["id"] for r in listed}
    write_json(path, listed + [r for r in rows if r["id"] not in seen], indent=1)
    stamp = {"superseded_at": utc_now_iso()}
    for batch in batched([r["id"] for r in rows]):
        sb.table(DECISIONS_TABLE).update(stamp).in_("id", batch).is_("superseded_at", "null").execute()
    print(f"{len(rows)} of the reviewers' decisions lapsed; listed in {path}")
    return len(rows)


def lapsed_section(store: Path, run_id: str) -> str:
    """The summary email's list of what lapsed this week, or nothing."""
    path = run_dir(store, run_id) / EXPIRED_FILE
    rows = read_json(path) if path.exists() else []
    if not rows:
        return ""
    items = "".join(f"<li>{html.escape(lapsed_text(row))}</li>" for row in rows)
    return (
        f"<p>{len(rows)} of the reviewers' calls reached their eighth weekly run and lapsed, so this week's scans "
        f"could propose them again:</p><ul>{items}</ul>"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True, help="The run proposing the week, whose summary lists what lapsed")
    parser.add_argument(
        "--store",
        type=Path,
        help="The run store, absolute (default: PITCHRANK_CLEANUP_DIR, else ~/pitchrank-cleanup-runs)",
    )
    parser.add_argument("--execute", action="store_true", help="Stamp them superseded (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Force a dry run; wins over --execute")
    args = parser.parse_args()
    try:
        store = store_dir(args.store)
        run_dir(store, args.run)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    expire(get_client(), store, args.run, resolve_execute(args.execute, args.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
