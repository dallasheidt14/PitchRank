#!/usr/bin/env python3
"""Propose a week's team cleanup for a scope of states, unattended. Writes no team.

It opens the run in team_cleanup_runs (one open run at a time), snapshots every team's guarded
fields, then runs each stage's skill self-check and proposal step into
<store>/runs/<run_id>/<stage>/:

  clubs   repair_swapped_club_names.py over the country, cut to the scope, reading the saved
          logs in <store>/inputs/abbreviation_logs/, which must hold <GitHub run id>.log for each
          of its default runs (GitHub deletes a run's log after 90 days)
  states  assign_team_states.py --no-tier-a --reuse-answers over the country, cut to the scope: Tier A from
          the GotSport answers of the last 90 days, and no call bought
  ages    review_age_labels.py review --state <scope>, then write-plan --groups 1,2,3 (groups 4
          and 5 are owner questions, not plan rows)
  merges  find_cross_provider_duplicates.py over the country (per state for a narrower scope) and
          find_squad_key_duplicates.py per state, into merges/scans/

Each stage leaves proposals.json, one row per proposed change, beside its applier's input for the
scope: clubs/repair_swapped_club_names.csv, states/snapshot.json, ages/plan.csv, merges/pairs.json.
A merges row is one proposed pair, retiring merge_id into keep_id: each scan's proposals, the
cross-provider one's review tiers left out, once each pair, the cross-provider record kept where
both scans found it. A pair the other scan held or rejected, one touching a team another stage
proposes to change this week, and one with a team in another pair a scan proposed or held, are left
out too, and merges/scans.json counts every pair the scans or this cut left out, by why. Merges
proposes last, and waits for a retry when an earlier stage fails in the same pass, so its pairs are
always cut against every other stage's proposals.

A scope of ALL names the run <date>-all; clubs and states keep every team, one with no state
included, ages covers every team holding a US state, the age review's own scope when given none, and
merges every US state, the cross-provider scan a team with no state too. Reconcile is run by hand;
run.json says so and it does not run. A stage whose self-check fails is marked skill_stale and
skipped. A finished stage leaves propose_done, so a run stopped part way resumes at the stage it
stopped in. Once each stage has proposed or is skill_stale, each proposal whose proposed field or
liveness something else changed meanwhile, and each pair either of whose rows changed in any field
the guard watches, is listed in <stage>/stale.json, the week's health report is written, and the run
moves to reviewing.

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
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from postgrest.exceptions import APIError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.find_cross_provider_duplicates import FLIP_TIER, REJECTED_TIER, get_client  # noqa: E402
from scripts.find_squad_key_duplicates import HELD as SQUAD_KEY_HELD  # noqa: E402
from scripts.find_squad_key_duplicates import PROPOSED as SQUAD_KEY_PROPOSED  # noqa: E402
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
from scripts.team_cleanup.vetted import KEEP_AS_VETTED, MERGE_AS_VETTED  # noqa: E402
from src.tournaments.storage._file_lock import FileLockError, _acquire_file_lock  # noqa: E402
from src.tournaments.storage._io import read_json, utc_now_iso, write_json  # noqa: E402
from src.utils.us_states import STATE_CODE_TO_NAME  # noqa: E402

CLUBS, STATES, AGES = "clubs", "states", "ages"
# Merges last, so its pairs are cut against the other stages' proposals; that cut, not the order its lanes
# apply in, keeps a merge off a team another stage writes.
PROPOSED_STAGES = (CLUBS, STATES, AGES, MERGES)
ALL = "ALL"
NOT_RUN = {"reconcile": "not run: reconcile is run by hand"}
FIELDS = {CLUBS: "club_name", STATES: "state_code", AGES: "age_group", MERGES: "merged_into"}

SWAPPED_CLUBS = "scripts/repair_swapped_club_names.py"
ASSIGN_STATES = "scripts/assign_team_states.py"
AGE_REVIEW = ".claude/skills/correcting-team-age-groups/scripts/review_age_labels.py"
CROSS_PROVIDER = "scripts/find_cross_provider_duplicates.py"
SQUAD_KEY = "scripts/find_squad_key_duplicates.py"
HEALTH = "scripts/team_cleanup/health.py"
# --code-only: the state check's database half only measures, so it can crash the check but never fail it;
# the club and age checks read no database and take the flag for symmetry.
SELF_CHECKS = {
    CLUBS: ["scripts/check_club_skill_assumptions.py", "--code-only"],
    STATES: ["scripts/check_state_skill_assumptions.py", "--code-only"],
    AGES: ["scripts/check_age_skill_assumptions.py", "--code-only"],
    MERGES: ["scripts/check_merge_skill_assumptions.py", "--code-only"],
}
ABBREVIATION_LOGS = Path("inputs") / "abbreviation_logs"
SCOPED_CLUBS = "repair_swapped_club_names.csv"
SCOPED_STATES = "snapshot.json"
AGE_PLAN = "plan.csv"
AGE_REVIEW_FILE = "age_label_review.csv"
# The age review's evidence each age proposal carries: what the league's division, the opponents'
# bands and GotSport each say the age is, and how the opponents' single birth years vote.
AGE_EVIDENCE = ("gotsport_age", "div_says", "band_opps_say", "year_witness")
MERGE_SCANS = "scans"
MERGE_PAIRS = "pairs.json"
SCAN_COUNTS = "scans.json"
CROSS_PROVIDER_FILE = "cross_provider_duplicates"
# The scan that found a pair: the same squad registered with two providers, or one club's squad under two
# spellings.
CROSS_PROVIDER_DOORWAY, SQUAD_KEY_DOORWAY = "C", "D"
PROVABLY_SAFE = "1_provably_safe"
# The cross-provider scan's tiers a pair card shows; its two review tiers, a competing partner and a
# fused registration, are held with the squad-key scan's held pairs.
CROSS_PROVIDER_TIERS = (PROVABLY_SAFE, "2_both_have_games", "3_other_side_empty", FLIP_TIER, "5_both_empty")
APPLIER_INPUTS = {CLUBS: SCOPED_CLUBS, STATES: SCOPED_STATES, AGES: AGE_PLAN, MERGES: MERGE_PAIRS}
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
        # A dry run with Tier A on still spends paid probes and logs each one to the database, so Tier A
        # reads only the answers already bought.
        return [[ASSIGN_STATES, "--no-tier-a", "--reuse-answers", "--out", str(folder / "national_snapshot.json")]]
    if stage == MERGES:
        scans = folder / MERGE_SCANS
        if states == [ALL]:
            cross = [[CROSS_PROVIDER, "--out-dir", str(scans / "national")]]
        else:
            cross = [[CROSS_PROVIDER, "--state", state, "--out-dir", str(scans / state.lower())] for state in states]
        # The squad-key scan takes one state at a time and names its files by it.
        scope = sorted(STATE_CODE_TO_NAME) if states == [ALL] else states
        return cross + [[SQUAD_KEY, "--state", state, "--out-dir", str(scans)] for state in scope]
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


def pair_row(record: dict, doorway: str, **found) -> dict:
    """A scan's proposed pair as a merges proposal, retiring merge_id into keep_id: in the shape every
    stage's proposals share, and carrying what the merge applier reads."""
    return {
        "team_id_master": record["merge_id"],
        "team_name": record["merge_name"],
        "field": FIELDS[MERGES],
        "old_value": None,
        "new_value": record["keep_id"],
        **{key: record[key] for key in ("merge_id", "keep_id", "merge_name", "keep_name", "club")},
        "doorway": doorway,
        "tier": None,
        "provider": None,
        "squad_key": None,
        "alias_already_points_at_gotsport": False,
        **found,
        MERGE_AS_VETTED: record[MERGE_AS_VETTED],
        KEEP_AS_VETTED: record[KEEP_AS_VETTED],
    }


def pair_key(pair: dict) -> frozenset:
    return frozenset((pair["merge_id"], pair["keep_id"]))


def cross_provider_pairs(scans: Path) -> tuple[list[dict], list[dict], list[dict], Counter]:
    """The cross-provider scan's proposals, the pairs it held and the ones it rejected, from each of its
    runs, and what it left out, by why."""
    pairs, held, rejected, left_out = [], [], [], Counter()
    for folder in sorted(path.parent for path in scans.glob(f"*/{CROSS_PROVIDER_FILE}.csv")):
        for row in _read_csv(folder / f"{CROSS_PROVIDER_FILE}.csv"):
            if row["tier"] not in CROSS_PROVIDER_TIERS:
                (rejected if row["tier"] == REJECTED_TIER else held).append(row)
                left_out[f"cross-provider: {row['rejected_reason'] or row['tier']}"] += 1
        for record in read_json(folder / f"{CROSS_PROVIDER_FILE}.json"):
            if record["tier"] in CROSS_PROVIDER_TIERS:
                found = {key: record[key] for key in ("tier", "provider", "alias_already_points_at_gotsport")}
                pairs.append(pair_row(record, CROSS_PROVIDER_DOORWAY, **found))
    return pairs, held, rejected, left_out


def squad_key_pairs(scans: Path) -> tuple[list[dict], list[dict], list[dict], Counter]:
    """The squad-key scan's proposals, the pairs it held and the ones it rejected, from each state's run,
    and what it held or rejected, by why."""
    pairs, held, rejected, left_out = [], [], [], Counter()
    for path in sorted(scans.glob("squad_key_duplicates_*_all.json")):
        for status, records in read_json(path).items():
            if status == SQUAD_KEY_PROPOSED:
                pairs += [pair_row(record, SQUAD_KEY_DOORWAY, squad_key=record["squad_key"]) for record in records]
                continue
            (held if status == SQUAD_KEY_HELD else rejected).extend(records)
            left_out.update(f"squad-key: {record['reason']}" for record in records)
    return pairs, held, rejected, left_out


def merge_proposals(folder: Path) -> tuple[list[dict], Counter]:
    """Each pair the scans propose, once, and what was left out, by why. A pair one scan proposes and the
    other held or rejected keeps the refusal, since each scan screens what the other cannot. A pair
    touching a team the week's other stages propose to change waits a week rather than race their write,
    and a team in two pairs, a held one included, is a cluster the owner settles by hand."""
    cross, cross_held, cross_rejected, left_out = cross_provider_pairs(folder / MERGE_SCANS)
    squad, squad_held, squad_rejected, squad_left_out = squad_key_pairs(folder / MERGE_SCANS)
    left_out.update(squad_left_out)
    held = {pair_key(p) for p in cross_held + squad_held}
    refused = held | {pair_key(p) for p in cross_rejected + squad_rejected}
    pairs, seen = [], set()
    for pair in cross + squad:
        key = pair_key(pair)
        if key in refused:
            left_out["the other scan held or rejected it"] += 1
            continue
        if key in seen:
            left_out["found by both scans, kept once"] += 1
            continue
        seen.add(key)
        pairs.append(pair)
    changing = {
        p["team_id_master"]
        for stage in (CLUBS, STATES, AGES)
        if (path := folder.parent / stage / PROPOSALS_FILE).exists()
        for p in read_json(path)
    }
    clustered = Counter(team for key in seen | held for team in key)
    kept = []
    for pair in pairs:
        teams = {pair["merge_id"], pair["keep_id"]}
        if teams & changing:
            left_out["another stage proposes to change one of its teams this week"] += 1
        elif any(clustered[team] > 1 for team in teams):
            left_out["one of its teams pairs with another row too"] += 1
        else:
            kept.append(pair)
    return kept, left_out


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
    if stage == MERGES:
        proposals, left_out = merge_proposals(folder)
        write_json(folder / MERGE_PAIRS, proposals, indent=1)
        write_json(folder / SCAN_COUNTS, dict(sorted(left_out.items())), indent=1)
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
    for scans in ("national", MERGE_SCANS):
        shutil.rmtree(folder / scans, ignore_errors=True)
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
    opening snapshot, or, for a pair, any guarded field of either row) and the run's write_guard.json."""
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
        if stage == MERGES and failed:
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
