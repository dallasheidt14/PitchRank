#!/usr/bin/env python3
"""Phase D verification helper for Shell 01 event intake.

Parses a compacted ``raw_scrape.jsonl`` journal and emits the plan-shaped
JSON metrics contract to stdout. Exit codes:

  0 — OK (or below threshold without ``--fail-below-threshold``)
  1 — below threshold AND ``--fail-below-threshold`` set
  2 — journal missing or corrupt

Usage:
  python scripts/verify_scrape_intake.py gotsport__42434__unknown
  python scripts/verify_scrape_intake.py gotsport__42434__unknown --fail-below-threshold

Plan thresholds:
  - provider_id_resolution_rate >= 95%  (teams with view_rankings link
    whose provider_id was extracted / teams with view_rankings link)
  - master_team_match_rate >= 80%       (teams with canonical
    team_id_master / teams whose provider_id was extracted)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.scrapers.intake_journal import IntakeJournal, JournalCorruptionError


PROVIDER_ID_RESOLUTION_THRESHOLD = 0.95
MASTER_TEAM_MATCH_THRESHOLD = 0.80


def compute_metrics(event_key: str, base_dir: str = "reports") -> dict[str, Any]:
    """Read the compacted journal for ``event_key`` and return the plan-
    shaped metrics dict.

    Raises ``FileNotFoundError`` if the journal doesn't exist and
    ``JournalCorruptionError`` on mid-file corruption (exit code 2 cases).
    """
    journal = IntakeJournal(event_key=event_key, base_dir=base_dir)
    if not journal.path.exists():
        raise FileNotFoundError(f"No journal at {journal.path}")
    store = journal.read()

    has_link_total = 0
    has_link_resolved = 0
    resolved_for_match_denom = 0
    matched_master = 0
    structurally_unresolvable = 0
    action_histogram: dict[str, int] = {}
    queue_stats = {
        "queued": 0,
        "deduped_pending": 0,
        "skipped_rejected": 0,
        "skipped_already_approved": 0,
        "multi_conflict": 0,
        "db_error": 0,
    }

    for record in store.values():
        if record.get("has_view_rankings_link"):
            has_link_total += 1
            if record.get("provider_id_resolution_status") == "resolved":
                has_link_resolved += 1
        else:
            structurally_unresolvable += 1

        if record.get("provider_id_resolution_status") == "resolved":
            resolved_for_match_denom += 1
            canonical = record.get("canonical") or {}
            if canonical.get("team_id_master"):
                matched_master += 1

        action = record.get("alias_writer_action") or "none"
        action_histogram[action] = action_histogram.get(action, 0) + 1
        if action in queue_stats:
            queue_stats[action] += 1

    removed_teams_path = journal.removed_teams_path
    if removed_teams_path.exists():
        removed_payload = json.loads(removed_teams_path.read_text(encoding="utf-8"))
        removed_teams = removed_payload.get("removed_provider_team_ids", [])
    else:
        removed_teams = []

    pir_rate = (has_link_resolved / has_link_total) if has_link_total else None
    mtm_rate = (matched_master / resolved_for_match_denom) if resolved_for_match_denom else None

    return {
        "event_key": event_key,
        "provider_id_resolution_rate": pir_rate,
        "master_team_match_rate": mtm_rate,
        "denominators": {
            "provider_id_resolution": has_link_total,
            "master_team_match": resolved_for_match_denom,
        },
        "structurally_unresolvable_count": structurally_unresolvable,
        "removed_teams": removed_teams,
        "queue_stats": queue_stats,
        "action_histogram": action_histogram,
    }


def _below_threshold(metrics: dict[str, Any]) -> bool:
    pir = metrics.get("provider_id_resolution_rate")
    mtm = metrics.get("master_team_match_rate")
    if pir is not None and pir < PROVIDER_ID_RESOLUTION_THRESHOLD:
        return True
    if mtm is not None and mtm < MASTER_TEAM_MATCH_THRESHOLD:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse a compacted raw_scrape.jsonl journal and emit Phase D metrics.",
    )
    parser.add_argument(
        "event_key",
        help="Event key (e.g., gotsport__42434__unknown). Points at reports/<key>/intake/.",
    )
    parser.add_argument(
        "--base-dir",
        default="reports",
        help="Root directory for event artifacts (default: reports).",
    )
    parser.add_argument(
        "--fail-below-threshold",
        action="store_true",
        help=(
            f"Exit 1 when provider_id_resolution_rate < "
            f"{PROVIDER_ID_RESOLUTION_THRESHOLD:.0%} or master_team_match_rate "
            f"< {MASTER_TEAM_MATCH_THRESHOLD:.0%}."
        ),
    )
    args = parser.parse_args()

    try:
        metrics = compute_metrics(args.event_key, base_dir=args.base_dir)
    except FileNotFoundError as e:
        print(json.dumps({"error": "missing", "detail": str(e)}), file=sys.stderr)
        return 2
    except JournalCorruptionError as e:
        print(json.dumps({"error": "corrupt", "detail": str(e)}), file=sys.stderr)
        return 2

    print(json.dumps(metrics, indent=2))

    if args.fail_below_threshold and _below_threshold(metrics):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
