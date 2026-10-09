#!/usr/bin/env python3
"""
Give each reused GotSport record's old squad a team of its own.

When a club hands a GotSport record to another squad and nobody can say which record the
old squad plays on now, the record's games before the season start go to a new archive
team, and the record is renamed and relabelled to the squad GotSport shows on it today.
The archive team has no provider link, so nothing scrapes it, and it leaves the boards
once its games pass the ranking window. When the old squad's record turns up later, merge
the archive into it.

Two subcommands:

  plan    Reads a triage CSV and writes an archive plan: one row per reused record with
          its archive team's name, id and age group. Read-only.
  apply   Runs a reviewed plan. Per record: create the archive team (logged here), then
          scripts/reassign_games_between_teams.py, the bundled apply_team_fields.py and
          scripts/fix_band_cohorts.py, each writing its own log and undo path. Dry run
          unless --execute. Each step is idempotent, so a re-run finishes a stopped run.

Usage:
    python .claude/skills/reconcile-gotsport/scripts/archive_split.py plan --triage data/exports/<triage>.csv
    python .claude/skills/reconcile-gotsport/scripts/archive_split.py apply --plan <plan>.csv --names "2016 Clay"
    python .claude/skills/reconcile-gotsport/scripts/archive_split.py apply --plan <plan>.csv --execute
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from apply_team_fields import PLAN_COLUMNS as FIELD_PLAN_COLUMNS  # noqa: E402
from apply_team_fields import write_rows as write_field_plan  # noqa: E402

from scripts.fix_band_cohorts import (  # noqa: E402
    PLAN_FIELDS,
    csv_safe,
    csv_unsafe,
    get_supabase,
    load_env,
    read_csv,
)
from scripts.fix_band_cohorts import write_csv as write_age_plan  # noqa: E402
from src.utils.team_utils import _soccer_season_year  # noqa: E402

EXPORTS = ROOT / "data" / "exports"
PLAN_COLUMNS = [
    "team_id_master",
    "club_name",
    "record",
    "our_name",
    "gender",
    "state_code",
    "stored_age_group",
    "gotsport_name",
    "gotsport_age_group",
    "archive_name",
    "archive_age_group",
    "archive_provider_team_id",
]
TEXT_COLUMNS = ("club_name", "our_name", "gotsport_name", "archive_name")


def season_start(today: Optional[date] = None) -> str:
    return date(_soccer_season_year(today), 8, 1).isoformat()


def season_label(start: str) -> str:
    """'2025-26' for the season that ended when ``start`` began."""
    year = int(start[:4])
    return f"{year - 1}-{str(year)[2:]}"


def archive_identity(club: Optional[str], record: str, our_name: str, start: str) -> Dict[str, str]:
    """The archive team's name and provider_team_id for one record.

    The id starts ``archive_`` and carries no provider, as the first archive row
    (``archive_excel_2009_496638``) does, so no scrape-enqueue job selects it.
    """
    label = season_label(start)
    slug = re.sub(r"[^a-z0-9]+", "_", (club or "club").lower()).strip("_")
    return {
        "archive_name": f"{our_name} ({label} archive)",
        "archive_provider_team_id": f"archive_{slug}_{record}_{label.replace('-', '_')}",
    }


def plan_rows(triage: List[Dict], start: str) -> List[Dict]:
    """One plan row per reused_id triage row.

    The archive sits in the record's stored age group: the old squad's games were filed
    there, and the rollover already moved that label to the old squad's current cohort.
    """
    out = []
    for r in triage:
        if r.get("class") != "reused_id":
            continue
        ident = archive_identity(r.get("club_name"), r["provider_team_id"], r["team_name"], start)
        out.append(
            {
                "team_id_master": r["team_id_master"],
                "club_name": r.get("club_name") or "",
                "record": r["provider_team_id"],
                "our_name": r["team_name"],
                "gender": r["gender"],
                "state_code": r.get("state_code") or "",
                "stored_age_group": r["stored_age_group"],
                "gotsport_name": r["gotsport_team_name"],
                "gotsport_age_group": r["gotsport_age_group"],
                "archive_age_group": r["stored_age_group"],
                **ident,
            }
        )
    return out


def write_plan(rows: List[Dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: csv_safe(v) if k in TEXT_COLUMNS else v for k, v in r.items()} for r in rows)


def read_plan(path: Path) -> List[Dict]:
    rows = read_csv(path)
    missing = set(PLAN_COLUMNS) - set(rows[0] if rows else {})
    if rows and missing:
        raise SystemExit(f"{path.name} lacks column(s): {', '.join(sorted(missing))}")
    for r in rows:
        for column in TEXT_COLUMNS:
            r[column] = csv_unsafe(r[column])
        if not r["archive_provider_team_id"].startswith("archive_"):
            raise SystemExit(f"{path.name}: {r['our_name']!r} has an archive id not starting archive_")
    return rows


def run_tool(args: List[str]) -> str:
    """Run one of the logged tools and return the log path it names."""
    done = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)
    lines = (done.stdout + done.stderr).splitlines()
    if done.returncode:
        raise SystemExit(f"{args[0]} failed:\n" + "\n".join(lines[-15:]))
    return next((line.split("Log:", 1)[1].strip() for line in lines if "Log:" in line), "")


def ensure_archive(sb, r: Dict, live: Dict, execute: bool) -> Optional[str]:
    existing = (
        sb.table("teams")
        .select("team_id_master")
        .eq("provider_team_id", r["archive_provider_team_id"])
        .is_("provider_id", "null")
        .execute()
        .data
    )
    if existing:
        return existing[0]["team_id_master"]
    if not execute:
        return None
    archive_id = str(uuid.uuid4())
    sb.table("teams").insert(
        {
            "team_id_master": archive_id,
            "provider_team_id": r["archive_provider_team_id"],
            "provider_id": None,
            "team_name": r["archive_name"],
            "club_name": live["club_name"],
            "age_group": r["archive_age_group"],
            "gender": live["gender"],
            "state_code": live["state_code"],
        }
    ).execute()
    return archive_id


def apply(sb, rows: List[Dict], execute: bool, stamp: str) -> List[Dict]:
    start = season_start()
    log: List[Dict] = []
    for r in rows:
        tid = r["team_id_master"]
        live = (
            sb.table("teams")
            .select("team_name,age_group,gender,state_code,club_name,is_deprecated")
            .eq("team_id_master", tid)
            .execute()
            .data
        )
        if not live or live[0]["is_deprecated"]:
            print(f"  skip {r['our_name']!r}: not a live team")
            continue
        live = live[0]
        print(f"\n{r['our_name']} ({r['record']}) -> {r['archive_name']!r} [{r['archive_age_group']}]")
        archive_id = ensure_archive(sb, r, live, execute)
        print(f"  archive: {archive_id or 'would create'}")
        entry = {"team_id_master": tid, "our_name": r["our_name"], "archive_id": archive_id or "", "games_log": ""}
        entry.update(rename_log="", relabel_log="")
        if not execute:
            steps = [f"move games before {start}"]
            if live["team_name"] != r["gotsport_name"]:
                steps.append(f"rename to {r['gotsport_name']!r}")
            if live["age_group"] != r["gotsport_age_group"]:
                steps.append(f"relabel {live['age_group']} -> {r['gotsport_age_group']}")
            print("  would " + ", ".join(steps))
            log.append(entry)
            continue

        moved = run_tool(
            [
                "scripts/reassign_games_between_teams.py",
                "--from",
                tid,
                "--to",
                archive_id,
                "--before",
                start,
                "--execute",
            ]
        )
        entry["games_log"] = moved
        print(f"  games: {moved or 'none before ' + start}")

        if live["team_name"] != r["gotsport_name"]:
            names = EXPORTS / f"archive_split_rename_{stamp}_{r['record']}.csv"
            write_field_plan(
                [
                    {
                        "team_id_master": tid,
                        "team_name": live["team_name"],
                        "field": "team_name",
                        "old_value": live["team_name"],
                        "new_value": r["gotsport_name"],
                    }
                ],
                names,
                list(FIELD_PLAN_COLUMNS),
            )
            entry["rename_log"] = run_tool([str(HERE / "apply_team_fields.py"), "--plan", str(names), "--execute"])
            print(f"  rename: {entry['rename_log']}")

        if live["age_group"] != r["gotsport_age_group"]:
            ages = EXPORTS / f"archive_split_relabel_{stamp}_{r['record']}.csv"
            write_age_plan(
                [
                    {
                        "state_code": live["state_code"],
                        "team_id_master": tid,
                        "team_name": r["gotsport_name"],
                        "club_name": live["club_name"],
                        "gender": live["gender"],
                        "gotsport_team_name": r["gotsport_name"],
                        "band": "",
                        "old_age_group": live["age_group"],
                        "new_age_group": r["gotsport_age_group"],
                        "action": "would_update",
                        "collision_with": "",
                        "evidence_tier": "R_reused_id",
                        "fixture_verdict": "",
                        "opp_games_proposed": "",
                        "opp_games_current": "",
                    }
                ],
                ages,
                PLAN_FIELDS,
            )
            entry["relabel_log"] = run_tool(["scripts/fix_band_cohorts.py", "--apply", str(ages), "--execute"])
            print(f"  relabel: {entry['relabel_log']}")
        log.append(entry)
    return log


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_plan = sub.add_parser("plan", help="Write an archive plan from a triage CSV (read-only)")
    p_plan.add_argument("--triage", type=Path, required=True)
    p_apply = sub.add_parser("apply", help="Run a reviewed archive plan")
    p_apply.add_argument("--plan", type=Path, required=True)
    p_apply.add_argument("--names", nargs="*", help="Only the records whose our_name is listed (a pilot)")
    p_apply.add_argument("--execute", action="store_true", help="Write to the database (default is a dry run)")
    args = parser.parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.command == "plan":
        triage = [{k: csv_unsafe(v) for k, v in r.items()} for r in read_csv(args.triage)]
        rows = plan_rows(triage, season_start())
        path = EXPORTS / f"archive_split_plan_{stamp}.csv"
        write_plan(rows, path)
        print(f"{len(rows)} reused records. Plan: {path}")
        print("Check archive_age_group on any record already relabelled: it must be the old squad's cohort.")
        return

    load_env()
    sb = get_supabase()
    rows = read_plan(args.plan)
    if args.names:
        rows = [r for r in rows if r["our_name"] in set(args.names)]
    log = apply(sb, rows, args.execute, stamp)
    if args.execute and log:
        path = EXPORTS / f"archive_split_run_{stamp}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(log[0].keys()))
            writer.writeheader()
            writer.writerows(log)
        print(f"\nRun log: {path}")
        print(
            "Undo per record, last step first: fix_band_cohorts.py --revert <relabel_log>, "
            "apply_team_fields.py --revert <rename_log>, reassign_games_between_teams.py --revert <games_log>."
        )


if __name__ == "__main__":
    main()
