#!/usr/bin/env python3
"""Backfill ``assign_division`` overrides from raw_scrape bracket names.

Walks every registry team in a given event_key/scenario, looks up the
matching ``raw_scrape`` record's ``bracket_name``, and writes one
``assign_division`` override per team that prefix-matches a current
structure division. Idempotent: teams already carrying an explicit
assignment are skipped.

Per-team critical section preserves operator intent under interleaving:
the projection is re-read inside each team's ``acquire_scenario_lock``
window so an operator write that lands mid-script doesn't get silently
overwritten.

Usage:
    python scripts/backfill_division_assignments.py \\
        --event-key gotsport__45224__2026 --scenario default [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.tournaments.storage import (  # noqa: E402
    acquire_scenario_lock,
    append_override,
    load_overrides,
    load_raw_scrape,
    read_registry,
    read_structure,
)
from src.tournaments.storage._io import utc_now_iso  # noqa: E402
from src.tournaments.triage import (  # noqa: E402
    SOURCE_PREFIX,
    build_override_record,
    project_overrides,
    registry_provider_id,
    resolve_division_assignment,
)

_BACKFILL_ACTOR = "backfill-script@matchbalance.local"


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill assign_division overrides")
    parser.add_argument("--event-key", required=True, help="Event key (e.g. gotsport__45224__2026)")
    parser.add_argument("--scenario", required=True, help="Scenario name (e.g. default)")
    parser.add_argument(
        "--base-dir",
        default="reports",
        help="Storage base dir (default: reports)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute counts but skip every append_override call",
    )
    args = parser.parse_args()

    event_key = args.event_key
    scenario = args.scenario
    base_dir = args.base_dir
    dry_run = args.dry_run

    raw_scrape = load_raw_scrape(event_key, base_dir=base_dir)
    bracket_by_pid: dict[str, str] = {}
    for record in raw_scrape:
        pid = str(record.get("provider_team_id") or "").strip()
        if not pid:
            continue
        bracket = str(record.get("bracket_name") or record.get("division") or "").strip()
        if bracket:
            bracket_by_pid[pid] = bracket

    registry = read_registry(event_key, scenario, base_dir=base_dir)

    backfilled_count = 0
    already_assigned_count = 0
    require_triage_count = 0
    missing_raw_scrape_count = 0
    dry_run_would_backfill_count = 0

    for entry in registry:
        pid = registry_provider_id(entry)
        if not pid:
            continue
        bracket = bracket_by_pid.get(pid)
        if bracket is None:
            missing_raw_scrape_count += 1
            continue
        with acquire_scenario_lock(event_key, scenario, base_dir=base_dir, timeout=10.0):
            # Re-read overrides AND structure INSIDE the lock — a fresh
            # projection catches any operator write that landed since
            # script start, and re-reading structure prevents writing a
            # stale ``assign_division`` override against a division that
            # was renamed/removed mid-script.
            overrides = load_overrides(event_key, scenario, base_dir=base_dir)
            team_state, _ = project_overrides(overrides)
            projected = team_state.get(pid)
            if projected is not None and projected.assigned_division_name is not None:
                already_assigned_count += 1
                continue
            structure = read_structure(event_key, scenario, base_dir=base_dir)
            division_names = next(
                (
                    [d.name for d in cohort.divisions]
                    for cohort in structure
                    if cohort.age_group == entry.event_age_group and cohort.gender == entry.event_gender
                ),
                [],
            )
            resolution = resolve_division_assignment(None, bracket, division_names=division_names)
            if resolution.source != SOURCE_PREFIX or resolution.name is None:
                require_triage_count += 1
                continue
            if dry_run:
                dry_run_would_backfill_count += 1
                continue
            append_override(
                event_key,
                scenario,
                build_override_record(
                    ts=utc_now_iso(),
                    actor=_BACKFILL_ACTOR,
                    scope="team",
                    type="assign_division",
                    team_ref=pid,
                    before={"assigned_division_name": None},
                    after={"assigned_division_name": resolution.name},
                    reason=f"backfill from raw_scrape bracket_name for {event_key}/{scenario}",
                ),
                base_dir=base_dir,
                _already_locked=True,
                timeout=10.0,
            )
            backfilled_count += 1

    prefix = "DRY RUN — no writes\n" if dry_run else ""
    backfilled_label = "would-backfill" if dry_run else "backfilled"
    backfilled_value = dry_run_would_backfill_count if dry_run else backfilled_count
    print(
        f"{prefix}{backfilled_value} teams {backfilled_label}, "
        f"{already_assigned_count} teams already-assigned, "
        f"{require_triage_count} teams require triage (no prefix match), "
        f"{missing_raw_scrape_count} teams missing raw_scrape (no join)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
