#!/usr/bin/env python3
"""Show each open team-cleanup run: where each stage has got, and its next step.

Reads the run store's files only, never the database. Re-checking the reviews sets aside any
review that does not copy its proposal, as <name>_review.json.bad, and queues the proposal again.

Usage:
    python scripts/team_cleanup/status.py
    python scripts/team_cleanup/status.py --store <dir> --run <run_id>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.team_cleanup.run_store import (  # noqa: E402
    BAD_SUFFIX,
    OPEN_STATUSES,
    REVIEW_DIR,
    STAGES,
    list_runs,
    read_run,
    stage_progress,
    store_dir,
)


def describe(store: Path, run: dict) -> list[str]:
    lines = [f"Run {run['run_id']} ({run['status']}), scope {run.get('scope')}"]
    overrides = run.get("stages") or {}
    for stage in STAGES:
        if stage in overrides:
            lines.append(f"  {stage:<10} {overrides[stage]}")
            continue
        progress = stage_progress(store, run["run_id"], stage)
        if progress.finished:
            lines.append(f"  {stage:<10} finished")
        else:
            waiting = f" ({len(progress.queued)} queued: {', '.join(progress.queued)})" if progress.queued else ""
            lines.append(f"  {stage:<10} next: {progress.next_step.next_action}{waiting}")
        lines += [f"  {'':<10} set aside {stage}/{REVIEW_DIR}/{name}{BAD_SUFFIX}" for name in progress.set_aside]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--store",
        type=Path,
        help="The run store, absolute (default: PITCHRANK_CLEANUP_DIR, else ~/pitchrank-cleanup-runs)",
    )
    parser.add_argument("--run", help="Show this run instead of the open ones")
    args = parser.parse_args()
    try:
        store = store_dir(args.store)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None

    if args.run:
        try:
            runs = [read_run(store, args.run)]
        except FileNotFoundError:
            raise SystemExit(f"No run {args.run} in {store}.") from None
        except ValueError as exc:
            raise SystemExit(f"Cannot read run {args.run}: {exc}") from None
    else:
        every_run = list_runs(store)
        runs = [run for run in every_run if run["status"] in OPEN_STATUSES]
        if not runs:
            last = f"; the latest is {every_run[0]['run_id']} ({every_run[0]['status']})" if every_run else ""
            print(f"No open run in {store}{last}.")
            return 0
    for run in runs:
        print("\n".join(describe(store, run)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
