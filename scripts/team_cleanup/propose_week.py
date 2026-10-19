#!/usr/bin/env python3
"""Propose a week's team cleanup for a scope of states, unattended. Writes no team.

It opens the run in team_cleanup_runs (one open run at a time), snapshots every team's guarded
fields, then runs each stage's skill self-check and proposal step into
<store>/runs/<run_id>/<stage>/:

  clubs   repair_swapped_club_names.py over the country, cut to the scope, reading the saved
          logs in <store>/inputs/abbreviation_logs/, which must hold <GitHub run id>.log for each
          of its default runs (GitHub deletes a run's log after 90 days)
  states  assign_team_states.py --no-tier-a over the country, cut to the scope
  ages    review_age_labels.py review --state <scope>, then write-plan --groups 1,2,3 (groups 4
          and 5 are owner questions, not plan rows)

Each stage leaves proposals.json, one row per proposed change, beside its applier's input for the
scope: clubs/repair_swapped_club_names.csv, states/snapshot.json, ages/plan.csv. A scope of ALL
names the run <date>-all; clubs and states keep every team, one with no state included, and ages
covers every team holding a US state, the age review's own scope when given none. Reconcile is run
by hand and merges wait while the duplicate scans are frozen; run.json says so and neither runs.
A stage whose self-check fails is marked skill_stale and skipped. A finished stage leaves
propose_done, so a run stopped part way resumes at the stage it stopped in. Once each stage has
proposed or is skill_stale, each proposal whose proposed field or liveness something else changed
meanwhile is listed in <stage>/stale.json, the week's health report is written, and the run moves
to reviewing.

Usage:
    python scripts/team_cleanup/propose_week.py --states NV
    python scripts/team_cleanup/propose_week.py --states ALL
    python scripts/team_cleanup/propose_week.py --states NH,VT --store <dir> --date 2026-10-14 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from postgrest.exceptions import APIError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.find_cross_provider_duplicates import get_client  # noqa: E402
from scripts.repair_swapped_club_names import (  # noqa: E402
    DEFAULT_ABBREVIATION_RUNS,
    csv_unsafe,
    is_approved,
    write_log,
)
from scripts.team_cleanup import write_guard  # noqa: E402
from scripts.team_cleanup.decisions import MERGES  # noqa: E402
from scripts.team_cleanup.run_store import (  # noqa: E402
    OPEN_STATUSES,
    PREFLIGHT_MARKER,
    PROPOSALS_FILE,
    PROPOSE_MARKER,
    RUN_FILE,
    RUNS_TABLE,
    STALE_FILE,
    read_run,
    run_dir,
    stage_dir,
    store_dir,
    write_run,
)
from src.tournaments.storage._file_lock import FileLockError, _acquire_file_lock  # noqa: E402
from src.tournaments.storage._io import read_json, utc_now_iso, write_json  # noqa: E402
from src.utils.us_states import STATE_CODE_TO_NAME  # noqa: E402

CLUBS, STATES, AGES = "clubs", "states", "ages"
PROPOSED_STAGES = (CLUBS, STATES, AGES)
ALL = "ALL"
NOT_RUN = {
    "reconcile": "not run: reconcile is run by hand",
    MERGES: "not run: the duplicate scans are frozen until the owner resumes them",
}
FIELDS = {CLUBS: "club_name", STATES: "state_code", AGES: "age_group"}

SWAPPED_CLUBS = "scripts/repair_swapped_club_names.py"
ASSIGN_STATES = "scripts/assign_team_states.py"
AGE_REVIEW = ".claude/skills/correcting-team-age-groups/scripts/review_age_labels.py"
HEALTH = "scripts/team_cleanup/health.py"
# --code-only: the state check's database half only measures, so it can crash the check but never fail it;
# the club and age checks read no database and take the flag for symmetry.
SELF_CHECKS = {
    CLUBS: ["scripts/check_club_skill_assumptions.py", "--code-only"],
    STATES: ["scripts/check_state_skill_assumptions.py", "--code-only"],
    AGES: ["scripts/check_age_skill_assumptions.py", "--code-only"],
}
ABBREVIATION_LOGS = Path("inputs") / "abbreviation_logs"
SCOPED_CLUBS = "repair_swapped_club_names.csv"
SCOPED_STATES = "snapshot.json"
AGE_PLAN = "plan.csv"
AGE_REVIEW_FILE = "age_label_review.csv"
# The age review's evidence each age proposal carries: what the league's division, the opponents'
# bands and GotSport each say the age is, and how the opponents' single birth years vote.
AGE_EVIDENCE = ("gotsport_age", "div_says", "band_opps_say", "year_witness")
APPLIER_INPUTS = {CLUBS: SCOPED_CLUBS, STATES: SCOPED_STATES, AGES: AGE_PLAN}
AGE_GROUPS_TO_APPLY = "1,2,3"
STATE_CHANGES = ("apply", "queue")
STEP_TIMEOUT_SECONDS = 4 * 60 * 60

LOGS = "logs"
PROPOSE_LOCK = "propose.lock"
GUARD_BEFORE = "write_guard_before.json"
GUARD_DONE = "write_guard.json"


def parse_states(text: str) -> list[str]:
    codes = [part.strip().upper() for part in text.split(",")]
    if ALL in codes:
        if len(codes) > 1:
            raise ValueError(f"{ALL} covers every team, so it stands alone, not beside {text!r}'s other codes")
        return [ALL]
    states = []
    for code in codes:
        if code not in STATE_CODE_TO_NAME:
            raise ValueError(f"{code!r} is not a US state code")
        if code not in states:
            states.append(code)
    return states


def in_scope(states: list[str], state: str | None) -> bool:
    """ALL takes a team with no state too."""
    return states == [ALL] or state in states


def run_id_for(day: date, states: list[str]) -> str:
    return f"{day.isoformat()}-{'-'.join(state.lower() for state in states)}"


def missing_input(stage: str, store: Path) -> str | None:
    """What the stage lacks from the store, if anything: the clubs stage needs a saved copy of each
    default run's log, since a scan given any saved log fetches no default run."""
    if stage != CLUBS:
        return None
    folder = store / ABBREVIATION_LOGS
    missing = [run for run in DEFAULT_ABBREVIATION_RUNS if not (folder / f"{run}.log").is_file()]
    if not missing:
        return None
    return (
        f"no saved copy of run {', '.join(missing)}'s log in {folder}; save it from Git Bash in the repo with "
        f'mkdir -p "{folder}" && gh run view {missing[0]} --log > "{folder / missing[0]}.log"'
    )


def stage_commands(stage: str, folder: Path, states: list[str], store: Path) -> list[list[str]]:
    """The stage's proposal step: each script, relative to the repo, and its arguments."""
    if stage == CLUBS:
        logs = [
            arg for log in sorted((store / ABBREVIATION_LOGS).glob("*.log")) for arg in ("--abbreviation-log", str(log))
        ]
        return [[SWAPPED_CLUBS, "--exports-dir", str(folder / "national"), *logs]]
    if stage == STATES:
        # A dry run with Tier A on still spends paid probes and logs each one to the database.
        return [[ASSIGN_STATES, "--no-tier-a", "--out", str(folder / "national_snapshot.json")]]
    review = folder / AGE_REVIEW_FILE
    # The age review covers every US state when given none.
    scope = [] if states == [ALL] else ["--state", ",".join(states)]
    return [
        [
            AGE_REVIEW,
            "review",
            *scope,
            "--exports-dir",
            str(store / "exports"),
            "--out",
            str(review),
        ],
        [AGE_REVIEW, "write-plan", str(review), "--groups", AGE_GROUPS_TO_APPLY, "--out", str(folder / AGE_PLAN)],
    ]


def run_step(command: list[str], log: Path) -> int:
    """Run one script from the repo root with its output in ``log``; its exit code."""
    log.parent.mkdir(parents=True, exist_ok=True)
    # Writing to a file, a child takes the Windows code page, which lacks characters the scripts print.
    env = {**os.environ, "PYTHONUTF8": "1"}
    with log.open("w", encoding="utf-8") as out:
        try:
            return subprocess.run(
                [sys.executable, *command],
                cwd=ROOT,
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
                timeout=STEP_TIMEOUT_SECONDS,
            ).returncode
        except subprocess.TimeoutExpired:
            out.write(f"\nStopped after {STEP_TIMEOUT_SECONDS} seconds.\n")
            return -1


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def club_proposals(rows: list[dict], states: list[str]) -> tuple[list[dict], list[dict]]:
    """The swap scan's rows for teams in the scope, kept as the scan wrote them, and each as a
    proposed club_name change in the values the teams hold."""
    kept = [row for row in rows if in_scope(states, row["state"])]
    return kept, [
        {
            "team_id_master": row["team_id_master"],
            "team_name": csv_unsafe(row["team_name"]),
            "field": FIELDS[CLUBS],
            "old_value": csv_unsafe(row["stored_club"]),
            "new_value": csv_unsafe(row["proposed_club"]),
            "tier": row["tier"],
            "source": row["source"],
            "needs_review": row["needs_review"] == "true",
            "approved": is_approved(row),
        }
        for row in kept
    ]


def state_proposals(snapshot: dict, states: list[str]) -> tuple[dict, list[dict]]:
    """The snapshot cut to decisions whose team is in the scope before or after, and its changes."""
    decisions = [
        d for d in snapshot["decisions"] if in_scope(states, d["proposed"]) or in_scope(states, d["pre_image"])
    ]
    return {**snapshot, "decisions": decisions}, [
        {
            "team_id_master": d["team_id"],
            "team_name": d["team_name"],
            "field": FIELDS[STATES],
            "old_value": d["pre_image"],
            "new_value": d["proposed"],
            "tier": d["tier"],
            "action": d["action"],
            "reason": d["reason"],
        }
        for d in decisions
        if d["action"] in STATE_CHANGES
    ]


def age_proposals(plan: list[dict], review: list[dict]) -> list[dict]:
    proposals = [
        {
            "team_id_master": row["team_id_master"],
            "team_name": row["team_name"],
            "field": FIELDS[AGES],
            "old_value": row["old_age_group"],
            "new_value": row["new_age_group"],
            "tier": row["evidence_tier"],
        }
        for row in plan
    ]
    return with_age_evidence(proposals, review)


def with_age_evidence(proposals: list[dict], review: list[dict]) -> list[dict]:
    """Each age proposal with what the review read about its team, a blank reading as none."""
    evidence = {row["team_id"]: row for row in review}
    return [
        {**p, **{key: evidence.get(p["team_id_master"], {}).get(key) or None for key in AGE_EVIDENCE}}
        for p in proposals
    ]


def scoped_proposals(stage: str, folder: Path, states: list[str]) -> list[dict]:
    """Read the stage's output, cut a national scan's output to the scope for its applier, and return
    the stage's proposals."""
    if stage == CLUBS:
        (folder / SCOPED_CLUBS).unlink(missing_ok=True)
        scans = sorted((folder / "national").glob("repair_swapped_club_names_*.csv"))
        if not scans:  # the scan writes no file when it finds nothing
            return []
        kept, proposals = club_proposals(_read_csv(scans[-1]), states)
        write_log(kept, folder / SCOPED_CLUBS)
        return proposals
    if stage == STATES:
        scoped, proposals = state_proposals(read_json(folder / "national_snapshot.json"), states)
        write_json(folder / SCOPED_STATES, scoped, indent=1)
        return proposals
    return age_proposals(_read_csv(folder / AGE_PLAN), _read_csv(folder / AGE_REVIEW_FILE))


def preflight(stage: str, folder: Path) -> str | None:
    """Run the stage's skill self-check unless it already passed; why the stage cannot go on, if so."""
    marker = folder / PREFLIGHT_MARKER
    if marker.exists():
        return None
    check = SELF_CHECKS.get(stage)
    if check:
        log = folder / LOGS / "self_check.log"
        code = run_step(check, log)
        if code != 0:
            return f"skill_stale: {Path(check[0]).name} exited {code}; see {log}"
    write_json(marker, {"self_check": " ".join(check) if check else None, "passed_at": utc_now_iso()})
    return None


def propose(stage: str, folder: Path, states: list[str], store: Path) -> str | None:
    """Run the stage's proposal step and write its proposals; why it failed, if it did."""
    lacking = missing_input(stage, store)
    if lacking:
        return f"failed: {lacking}"
    # An earlier attempt's scan would otherwise stand in for a retry's scan that found nothing.
    shutil.rmtree(folder / "national", ignore_errors=True)
    for number, command in enumerate(stage_commands(stage, folder, states, store), 1):
        log = folder / LOGS / f"{number}_{Path(command[0]).stem}.log"
        code = run_step(command, log)
        if code != 0:
            return f"failed: {Path(command[0]).name} exited {code}; see {log}"
    write_json(folder / PROPOSALS_FILE, scoped_proposals(stage, folder, states), indent=1)
    (folder / PROPOSE_MARKER).write_text(utc_now_iso(), encoding="utf-8")
    return None


def _refused(action: str, exc: APIError | httpx.HTTPError, retry: str) -> str:
    # PostgREST's own errors carry a string code and roll back. A gateway's answer, or none at all,
    # may follow a committed write.
    if isinstance(exc, APIError) and isinstance(exc.code, str):
        return f"{action}: {exc.message}"
    detail = exc.message if isinstance(exc, APIError) else f"{type(exc).__name__}: {exc}"
    return f"{action}: the database's answer was lost ({detail}); re-run to see where it stands: {retry}"


def open_run(sb, store: Path, run_id: str, states: list[str], retry: str) -> dict:
    """The run's run.json, opening its row in team_cleanup_runs first. Refuses while another run is
    open, and once this one has finished proposing."""
    run = read_run(store, run_id) if (run_dir(store, run_id) / RUN_FILE).exists() else None
    if run and run["status"] != "proposing":
        raise SystemExit(f"Run {run_id} is {run['status']}: its proposals are written.")
    run = run or {"run_id": run_id, "scope": {"states": states}, "status": "proposing", "budgets": {}}
    try:
        open_runs = sb.table(RUNS_TABLE).select("run_id,status").in_("status", list(OPEN_STATUSES)).execute().data
        for row in open_runs:
            if row["run_id"] != run_id:
                raise SystemExit(
                    f"Run {row['run_id']} is still {row['status']}, and only one run may be open at a time; "
                    "see python scripts/team_cleanup/status.py"
                )
            if row["status"] != "proposing":
                # The table moved on without this file, as when the close's answer was lost.
                write_run(store, {**run, "status": row["status"]})
                raise SystemExit(f"Run {run_id} is {row['status']}: its proposals are written.")
        if not open_runs:
            sb.table(RUNS_TABLE).insert({key: run[key] for key in ("run_id", "scope", "status", "budgets")}).execute()
    except (APIError, httpx.HTTPError) as exc:
        raise SystemExit(_refused(f"Could not open run {run_id}", exc, retry)) from None
    run = {**run, "stages": {**NOT_RUN, **(run.get("stages") or {})}}
    write_run(store, run)
    return run


def close_guard(sb, store: Path, run_id: str) -> dict:
    """Write each proposed stage's stale.json (its proposals whose field or liveness moved since the
    opening snapshot) and the run's write_guard.json."""
    folder = run_dir(store, run_id)
    before = read_json(folder / GUARD_BEFORE)
    moved = write_guard.changes(before["teams"], write_guard.snapshot(sb))
    stale = {}
    for stage in PROPOSED_STAGES:
        proposals = stage_dir(store, run_id, stage) / PROPOSALS_FILE
        if proposals.exists():
            found = write_guard.stale(read_json(proposals), moved)
            write_json(proposals.with_name(STALE_FILE), found, indent=1)
            stale[stage] = len(found)
    summary = {"from": before["taken_at"], "to": utc_now_iso(), "teams_changed": len(moved), "stale": stale}
    write_json(folder / GUARD_DONE, summary, indent=1)
    (folder / GUARD_BEFORE).unlink()
    return summary


def close_run(sb, store: Path, run: dict, retry: str) -> None:
    try:
        moved = (
            sb.table(RUNS_TABLE)
            .update({"status": "reviewing"})
            .eq("run_id", run["run_id"])
            .eq("status", "proposing")
            .execute()
            .data
        )
    except (APIError, httpx.HTTPError) as exc:
        raise SystemExit(_refused(f"Could not move run {run['run_id']} to reviewing", exc, retry)) from None
    if not moved:
        raise SystemExit(f"Run {run['run_id']} is no longer proposing in {RUNS_TABLE}; it was left as it is.")
    write_run(store, {**run, "status": "reviewing"})


def retry_command(store: Path, states: list[str], day: date) -> str:
    command = ["scripts/team_cleanup/propose_week.py", "--states", ",".join(states), "--date", day.isoformat()]
    return f"python {subprocess.list2cmdline([*command, '--store', str(store)])}"


def dry_run(store: Path, run_id: str, states: list[str]) -> None:
    print(f"Run {run_id} in {run_dir(store, run_id)}")
    for stage, note in NOT_RUN.items():
        print(f"  {stage}: {note}")
    for stage in PROPOSED_STAGES:
        folder = stage_dir(store, run_id, stage)
        check = SELF_CHECKS.get(stage)
        print(f"  {stage}: self-check {' '.join(check) if check else 'none'}")
        lacking = missing_input(stage, store)
        if lacking:
            print(f"    would fail: {lacking}")
            continue
        for command in stage_commands(stage, folder, states, store):
            print(f"    python {subprocess.list2cmdline(command)}")
    print("DRY RUN -- nothing run, nothing written.")


def propose_stages(store: Path, run: dict, states: list[str]) -> list[str]:
    """Propose each stage not proposed yet, noting any that cannot in run.json; the ones that failed."""
    failed = []
    for stage in PROPOSED_STAGES:
        folder = stage_dir(store, run["run_id"], stage)
        if (folder / PROPOSE_MARKER).exists():
            continue
        run["stages"].pop(stage, None)
        problem = preflight(stage, folder)
        if problem is None:
            problem = propose(stage, folder, states, store)
            if problem:
                failed.append(stage)
        if problem:
            run["stages"][stage] = problem
            print(f"{stage}: {problem}")
        write_run(store, run)
    return failed


def propose_week(sb, store: Path, run_id: str, states: list[str], day: date) -> int:
    retry = retry_command(store, states, day)
    run = open_run(sb, store, run_id, states, retry)
    folder = run_dir(store, run_id)
    # Stages propose only while the write guard is open. Once it has closed, a stage still
    # unproposed (its self-check failed) waits for next week: proposed now, nothing would guard it.
    if not (folder / GUARD_DONE).exists():
        if not (folder / GUARD_BEFORE).exists():
            snapshot = {"taken_at": utc_now_iso(), "teams": write_guard.snapshot(sb)}
            write_json(folder / GUARD_BEFORE, snapshot, indent=None)
        failed = propose_stages(store, run, states)
        if failed:
            print(f"Run {run_id} stays open. Retry {', '.join(failed)} with: {retry}")
            return 1
        summary = close_guard(sb, store, run_id)
        stale = ", ".join(f"{stage} {count}" for stage, count in summary["stale"].items())
        print(f"Write guard: {summary['teams_changed']:,} teams changed meanwhile; stale proposals: {stale}")
    log = folder / LOGS / "health.log"
    code = run_step([HEALTH, "--store", str(store), "--date", day.isoformat()], log)
    if code != 0:
        print(f"The health report failed (exit {code}); see {log}. Retry with: {retry}")
        return 1
    close_run(sb, store, run, retry)
    print(f"Run {run_id} is ready for review.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--states", required=True, help="The run's scope, comma-separated state codes, or ALL")
    parser.add_argument(
        "--store",
        type=Path,
        help="The run store, absolute (default: PITCHRANK_CLEANUP_DIR, else ~/pitchrank-cleanup-runs)",
    )
    parser.add_argument(
        "--date",
        default=datetime.now(timezone.utc).date().isoformat(),
        help="The run's date, YYYY-MM-DD (default: today, UTC); a retry passes the failed run's date",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print each stage's commands and run nothing")
    args = parser.parse_args()
    try:
        states = parse_states(args.states)
        store = store_dir(args.store)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    try:
        day = date.fromisoformat(args.date)
    except ValueError as exc:
        raise SystemExit(f"--date: {exc}") from None
    run_id = run_id_for(day, states)

    if args.dry_run:
        dry_run(store, run_id, states)
        return 0
    store.mkdir(parents=True, exist_ok=True)
    try:
        with _acquire_file_lock(store / PROPOSE_LOCK, timeout=0.0):
            return propose_week(get_client(), store, run_id, states, day)
    except FileLockError:
        raise SystemExit(f"Another propose is already running in {store}.") from None


if __name__ == "__main__":
    raise SystemExit(main())
