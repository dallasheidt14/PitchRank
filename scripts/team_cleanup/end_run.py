#!/usr/bin/env python3
"""Finish or abandon a weekly team-cleanup run, moving its team_cleanup_runs row and its run.json.

Only one run may be open at a time, so a run left open blocks every later week's propose. --done
closes a run whose stages are all finished: applied, or with nothing to apply this week (not run, or
skill_stale). --abandon closes a run whatever its stages hold and leaves everything it applied in
place; undo that first if it is unwanted. Neither moves a run while an apply holds it: its file lock
on this machine, or a live lease.

A dry run unless --execute, and a dry run checks neither. Like status.py, it re-checks each stage's
reviews, so a review that no longer copies its proposal is set aside as <name>_review.json.bad and
its proposal queued again.

    python scripts/team_cleanup/end_run.py --run 2026-10-14-nv --abandon --reason "stage failed twice"
    python scripts/team_cleanup/end_run.py --run 2026-10-14-nv --done --execute
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

import httpx
from postgrest.exceptions import APIError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.find_cross_provider_duplicates import get_client  # noqa: E402
from scripts.team_cleanup.decisions import TABLE_MISSING, resolve_execute  # noqa: E402
from scripts.team_cleanup.run_store import (  # noqa: E402
    ABANDONED,
    APPLY_LOCK_FILE,
    DONE,
    OPEN_STATUSES,
    PERMISSION_DENIED,
    RUNS_TABLE,
    SKIPPED_STAGE_NOTES,
    STAGES,
    read_run,
    run_dir,
    stage_progress,
    store_dir,
    update_free_open_run,
    write_run,
)
from src.tournaments.storage._file_lock import FileLockError, _acquire_file_lock  # noqa: E402
from src.tournaments.storage._io import utc_now_iso  # noqa: E402


def unfinished(store: Path, run: dict) -> list[str]:
    """The stages that keep the run from being done, each with its run.json note or else its next step.
    A stage noted as having nothing to apply this week is left out."""
    notes = run.get("stages") or {}
    lines = []
    for stage in STAGES:
        note = notes.get(stage)
        if note:
            if not note.startswith(SKIPPED_STAGE_NOTES):
                lines.append(f"{stage}: {note}")
            continue
        step = stage_progress(store, run["run_id"], stage).next_step
        if step is not None:
            lines.append(f"{stage}: next, {step.next_action}")
    return lines


def check(store: Path, run: dict, target: str) -> list[str]:
    """Refuse what the run store's files can refuse, before the database is touched. Returns what
    --done would still wait for."""
    if run["status"] not in OPEN_STATUSES:
        raise SystemExit(f"Run {run['run_id']} is {run['status']}; only an open run can be ended.")
    left = unfinished(store, run)
    if target == DONE and left:
        raise SystemExit(
            f"Run {run['run_id']} has stages not yet applied, so it is not done; finish them or use --abandon:\n  "
            + "\n  ".join(left)
        )
    return left


def end_run(sb, store: Path, run: dict, target: str, reason: str | None) -> bool:
    """Move the row first, since it is what keeps the next run from opening, then run.json. Returns
    whether the row had already moved, as when an earlier attempt's answer was lost."""
    run_id = run["run_id"]
    try:
        with _acquire_file_lock(run_dir(store, run_id) / APPLY_LOCK_FILE, timeout=0.0):
            moved, row = update_free_open_run(
                sb, run_id, {"status": target, "lease_holder": None, "lease_expires_at": None}
            )
    except FileLockError:
        raise SystemExit(f"Run {run_id} is being applied on this machine.") from None
    if not moved:
        if row is None:
            raise SystemExit(f"No run {run_id} in {RUNS_TABLE}.")
        if row["status"] in OPEN_STATUSES and row["lease_holder"]:
            raise SystemExit(f"Run {run_id} is being applied by {row['lease_holder']} until {row['lease_expires_at']}.")
        if row["status"] in OPEN_STATUSES:
            raise SystemExit(f"Run {run_id} was being applied when asked and is free now; run this again.")
        if row["status"] != target:
            raise SystemExit(f"Run {run_id} is {row['status']} in {RUNS_TABLE}; only an open run can be ended.")
    write_run(store, {**run, "status": target, "ended": {"status": target, "at": utc_now_iso(), "reason": reason}})
    return not moved


def refused(run_id: str, exc: APIError | httpx.HTTPError, retry: str) -> str:
    """PostgREST's own errors carry a string code and roll back. Anything else (a gateway's 502, an
    unreadable body, a dropped connection) may follow a committed update, so the
    outcome is unknown and a re-run reads where it stands."""
    if isinstance(exc, APIError) and isinstance(exc.code, str):
        if exc.code == TABLE_MISSING:
            return f"{RUNS_TABLE} does not exist yet: apply its migration before ending run {run_id}"
        if exc.code == PERMISSION_DENIED:
            return f"Could not end run {run_id}: only the service-role key can write {RUNS_TABLE}"
        return f"Could not end run {run_id}: {exc.message}"
    detail = exc.message if isinstance(exc, APIError) else f"{type(exc).__name__}: {exc}"
    return (
        f"Could not end run {run_id}: the database's answer was lost ({detail}); re-run to see where it stands: {retry}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True, help="The run id, e.g. 2026-10-14-nv")
    how = parser.add_mutually_exclusive_group(required=True)
    how.add_argument("--done", action="store_true", help="Close a run whose stages are all finished")
    how.add_argument("--abandon", action="store_true", help="Close a run whatever its stages hold")
    parser.add_argument("--reason", help="Why, recorded in run.json")
    parser.add_argument("--execute", action="store_true", help="Move the run (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Force a dry run; wins over --execute")
    parser.add_argument(
        "--store",
        type=Path,
        help="The run store, absolute (default: PITCHRANK_CLEANUP_DIR, else ~/pitchrank-cleanup-runs)",
    )
    args = parser.parse_args()
    target = DONE if args.done else ABANDONED
    try:
        store = store_dir(args.store)
        run = read_run(store, args.run)
    except FileNotFoundError:
        raise SystemExit(f"No run {args.run} in {store}.") from None
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    left = check(store, run, target)

    if not resolve_execute(args.execute, args.dry_run):
        print(f"DRY RUN -- would move run {args.run} from {run['status']} to {target}.")
        for line in left:
            print(f"  not applied: {line}")
        print("Re-run with --execute to move it.")
        return 0
    retry = ["python", "scripts/team_cleanup/end_run.py", "--run", args.run, "--done" if args.done else "--abandon"]
    retry += [*(["--reason", args.reason] if args.reason else []), "--execute", "--store", str(store)]
    try:
        already = end_run(get_client(), store, run, target, args.reason)
    except (APIError, httpx.HTTPError) as exc:
        raise SystemExit(refused(args.run, exc, shlex.join(retry))) from None
    if already:
        print(f"Run {args.run} was already {target} in {RUNS_TABLE}; run.json now says so too.")
    else:
        print(f"Moved run {args.run} from {run['status']} to {target}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
