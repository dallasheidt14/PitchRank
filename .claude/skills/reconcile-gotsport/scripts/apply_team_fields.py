#!/usr/bin/env python3
"""
Set team names or genders from a reviewed plan, each write guarded on the value it replaces.

The plan is a CSV with columns team_id_master, team_name, field, old_value, new_value,
where field is team_name or gender. A team whose live value is no longer old_value is
skipped and reported, never overwritten -- the weekly name normalizer and the
unknown-name backfill write team_name too.

Gender moves a team between ranking boards, so only Male and Female are accepted.

Names are provider text and these files are opened in a spreadsheet, so text values are
escaped on write and unescaped on read, as scripts/fix_band_cohorts.py does.

Dry run by default. Every run writes a log to data/exports that --revert replays
backwards, again only where the row still holds the value this run wrote.

Usage:
    python .claude/skills/reconcile-gotsport/scripts/apply_team_fields.py --plan <plan.csv>
    python .claude/skills/reconcile-gotsport/scripts/apply_team_fields.py --plan <plan.csv> --execute
    python .claude/skills/reconcile-gotsport/scripts/apply_team_fields.py --revert <log.csv> --execute
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from scripts.fix_band_cohorts import csv_safe, csv_unsafe, load_env  # noqa: E402
from supabase import create_client  # noqa: E402

EXPORTS = ROOT / "data" / "exports"
PLAN_COLUMNS = ("team_id_master", "team_name", "field", "old_value", "new_value")
LOG_COLUMNS = [*PLAN_COLUMNS, "result"]
TEXT_COLUMNS = ("team_name", "old_value", "new_value")
GENDERS = ("Male", "Female")
WRITABLE = ("team_name", "gender")
# A row a dead or interrupted run may or may not have written; revert replays it too,
# and the value guard means a row that never moved matches nothing.
REVERTABLE = ("updated", "planned_not_applied")


def get_supabase(execute: bool):
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    service = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    key = service or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in root .env")
    if execute and not service:
        # RLS filters an anon UPDATE to zero rows and answers 200, so it would report
        # every change as skipped while writing nothing.
        raise SystemExit("--execute needs SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def read_rows(path: Path) -> List[Dict]:
    # utf-8-sig: a plan filtered or written in Excel and saved as "CSV UTF-8" opens with a BOM.
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    missing = set(PLAN_COLUMNS) - set(rows[0] if rows else {})
    if rows and missing:
        raise SystemExit(f"{path.name} lacks column(s): {', '.join(sorted(missing))}")
    for r in rows:
        for column in TEXT_COLUMNS:
            r[column] = csv_unsafe(r[column])
        if r["field"] not in WRITABLE:
            raise SystemExit(f"{path.name}: field {r['field']!r} is not one of {', '.join(WRITABLE)}")
        if r["field"] == "gender" and r["new_value"] not in GENDERS:
            raise SystemExit(f"{path.name}: gender {r['new_value']!r} is not Male or Female")
    return rows


def write_rows(rows: List[Dict], path: Path, fields: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: csv_safe(v) if k in TEXT_COLUMNS else v for k, v in r.items()} for r in rows)


def set_field(sb, team_id: str, field: str, old: str, new: str) -> str:
    done = (
        sb.table("teams")
        .update({field: new})
        .eq("team_id_master", team_id)
        .eq("is_deprecated", False)
        .eq(field, old)
        .execute()
        .data
    )
    if done:
        return "updated"
    live = sb.table("teams").select(f"{field},is_deprecated").eq("team_id_master", team_id).limit(1).execute().data
    if not live:
        return "skipped_missing"
    if live[0]["is_deprecated"]:
        return "skipped_deprecated"
    return "already_applied" if live[0][field] == new else "skipped_changed_since"


def revert(sb, log_path: Path, execute: bool) -> Counter:
    # Last write first: a plan holding A->B then B->C for one team only gets back to A
    # when C->B is undone before B->A.
    rows = [r for r in read_rows(log_path) if r.get("result") in REVERTABLE][::-1]
    print(f"=== Revert {log_path.name} ({'EXECUTE' if execute else 'DRY RUN'}) : {len(rows)} rows ===")
    outcome = Counter()
    for r in rows:
        if execute:
            outcome[set_field(sb, r["team_id_master"], r["field"], r["new_value"], r["old_value"])] += 1
        else:
            outcome["would_revert"] += 1
            print(f"  {r['team_name']!r} {r['field']}: {r['new_value']!r} -> {r['old_value']!r}")
    return outcome


def apply(sb, plan_path: Path, execute: bool) -> Path:
    rows = [r for r in read_rows(plan_path) if r["new_value"].strip() and r["new_value"] != r["old_value"]]
    for r in rows:
        r["result"] = "planned_not_applied" if execute else "would_update"
    log_path = EXPORTS / f"apply_team_fields_{datetime.now():%Y%m%d_%H%M%S_%f}.csv"
    write_rows(rows, log_path, LOG_COLUMNS)  # lands before the first write: the log is the way back

    print(f"=== Apply {plan_path.name} ({'EXECUTE' if execute else 'DRY RUN'}) : {len(rows)} rows ===")
    try:
        for r in rows:
            print(f"  {r['team_name']!r} {r['field']}: {r['old_value']!r} -> {r['new_value']!r}")
            if execute:
                r["result"] = set_field(sb, r["team_id_master"], r["field"], r["old_value"], r["new_value"])
    finally:
        write_rows(rows, log_path, LOG_COLUMNS)

    print()
    for k, n in Counter(r["result"] for r in rows).most_common():
        print(f"  {k:22s} {n:>5}")
    return log_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, help="CSV of team_id_master, team_name, field, old_value, new_value")
    parser.add_argument("--revert", type=Path, help="Undo a previous run from its log")
    parser.add_argument("--execute", action="store_true", help="Write to the database (default is a dry run)")
    args = parser.parse_args()
    if bool(args.plan) == bool(args.revert):
        parser.error("give exactly one of --plan or --revert")

    load_env()
    sb = get_supabase(args.execute)

    if args.revert:
        for k, n in revert(sb, args.revert, args.execute).most_common():
            print(f"  {k:22s} {n:>5}")
        return

    log_path = apply(sb, args.plan, args.execute)
    print(f"\nLog: {log_path}")
    if args.execute:
        print(f"Undo with --revert {log_path} --execute")


if __name__ == "__main__":
    main()
