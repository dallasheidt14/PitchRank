#!/usr/bin/env python3
"""Apply the owner's choices for one stage of a weekly team-cleanup run, through the stage's own applier.

A dry run unless --execute. The owner runs --execute from the repo root, with the service-role key in
the environment; an agent never does. In order, it:

  1. Refuses unless the run is in review and the stage's next step is its apply, and when any file the
     page or the collector hashed has changed since: the vetted file and decisions.json must be the
     ones collected.json names.
  2. Refuses outside the apply window that config/team_cleanup.json sets, in Arizona time, unless
     --outside-window is passed.
  3. Takes the run's apply lock (this machine's file lock, then the run row's lease), checks the files
     again, and refuses while a writer workflow's run is not completed or a Python process on this
     machine runs a team applier.
  4. Records every decided card in team_cleanup_decisions, Don't apply and Not sure included, before
     anything else is written.
  5. Applies the cards chosen Apply, a pilot of 50 and then the rest, each a cut file written beside
     the vetted file and run through the stage's applier as team-cleanup:<run>. After each batch it
     writes one team_cleanup_changes row per change the applier's log (for states, team_state_audit)
     records and the database holds, and stops on a confirmed change the database lacks or, for
     states, on one of its own writes outside the windows its revert reads. The lease is renewed
     before each batch, and the window and the other writers are checked again before the rest:
        clubs   repair_swapped_club_names.py --execute <cut> --exports-dir <store>/exports --actor ...
        ages    fix_band_cohorts.py --apply <cut> --execute --skip-name-contradictions --exports-dir ...
        states  hold_unsafe_state_applies.py splits the stage's national_snapshot.json first and the
                cuts leave out what it held; then assign_team_states.py --execute --snapshot <cut>,
                which records its own actor, assign_team_states
  6. States only: checks the window and the other writers again, then settles each card the rules only
     queued as the dashboard's State Review Queue would. Apply approves the card's pending review row,
     unless a later sweep refiled it from another state, read again just before the approval, and
     Don't apply rejects it, filing the row first when none is pending. Once every one of the stage's
     own writes lies inside the windows its revert reads, it ledgers the approvals the database holds.
  7. Writes RECORD.md, which marks the stage applied.

Its progress is kept in <stage>/apply.json, so a re-run after a stop resumes: a batch whose applier
exited 0 is not run again, and every attempt's changes are verified and ledgered again.

--revert undoes the stage, newest batch first, under the same window and checks. Clubs and ages replay
their applier's own --revert of each batch's own log, the one written as team-cleanup:<run> for the
batch's cut. States refuse while one of the stage's own writes lies outside the windows apply.json
saves, wait until every batch's and review-queue step's window has closed, and refuse when a window
holds a write that is not the stage's own, before calling revert_team_states over each window. It then
stamps reverted_at on each ledger row whose team holds its old value again, and appends what it did to
<stage>/REVERT.md.
A run already done or abandoned can still be reverted: no lease can be taken on it, so the revert holds
this machine's file lock alone.

    python scripts/team_cleanup/apply_stage.py --run 2026-10-14-nv --stage clubs
    python scripts/team_cleanup/apply_stage.py --run 2026-10-14-nv --stage clubs --execute
    python scripts/team_cleanup/apply_stage.py --run 2026-10-14-nv --stage states --revert --execute
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from postgrest.exceptions import APIError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.assign_team_states import ACTOR as STATE_SWEEP_ACTOR  # noqa: E402
from scripts.assign_team_states import (  # noqa: E402
    SNAPSHOT_RULES,
    TIER_CONFIDENCE,
    queue_key,
    queue_payload,
    snapshot_reason,
)
from scripts.find_cross_provider_duplicates import batched, get_client, page  # noqa: E402
from scripts.fix_band_cohorts import UNCONFIRMED, read_our_csv  # noqa: E402
from scripts.repair_swapped_club_names import csv_unsafe, write_log  # noqa: E402
from scripts.team_cleanup.collect import DECISIONS_FILE, VETTED, check_unchanged  # noqa: E402
from scripts.team_cleanup.decisions import (  # noqa: E402
    APPLY,
    DECISIONS_TABLE,
    DONT_APPLY,
    resolve_execute,
    team_decision_row,
)
from scripts.team_cleanup.propose_week import (  # noqa: E402
    AGES,
    APPLIER_INPUTS,
    ASSIGN_STATES,
    CLUBS,
    FIELDS,
    LOGS,
    PROPOSED_STAGES,
    STATES,
    SWAPPED_CLUBS,
    _read_csv,
    run_step,
)
from scripts.team_cleanup.review_page import fetch_teams  # noqa: E402
from scripts.team_cleanup.run_store import (  # noqa: E402
    APPLY_MARKER,
    APPLY_PROGRESS_FILE,
    COLLECTED_MARKER,
    OPEN_STATUSES,
    PAGE_MARKER,
    ApplyLockError,
    acquire_apply_lock,
    file_hash,
    hold_apply_file,
    read_progress,
    read_run,
    refused,
    renew_lease,
    stage_dir,
    stage_due,
    store_dir,
)
from src.tournaments.storage._io import read_json, utc_now_iso, write_json  # noqa: E402

APPLY_SCRIPT = "scripts/team_cleanup/apply_stage.py"
AGE_FIXER = "scripts/fix_band_cohorts.py"
HOLD_STATES = "scripts/hold_unsafe_state_applies.py"
NATIONAL_STATES = "national_snapshot.json"
APPLIERS = {CLUBS: SWAPPED_CLUBS, STATES: ASSIGN_STATES, AGES: AGE_FIXER}
# Each CSV applier's log, named by local time to the second, and read as its own --revert reads it.
APPLIER_LOGS = {CLUBS: "repair_swapped_club_names_log_*.csv", AGES: "fix_band_cohorts_apply_*.csv"}
LOG_READERS = {CLUBS: _read_csv, AGES: read_our_csv}
# The age fixer's results for a row it wrote; an unconfirmed one counts once the database shows it.
AGE_WRITTEN = ("updated", UNCONFIRMED)
# What approve_team_state and reject_team_state raise for one card: a team that moved, or a review
# settled meanwhile. Any other refusal is the database's, and stops the stage.
CARD_REFUSAL = "P0001"

CHANGES_TABLE = "team_cleanup_changes"
CHANGE_KEY = "run_id,stage,team_id_master,field,new_value"
QUEUE_TABLE = "team_state_review_queue"
REVIEW_COLS = "id,team_id_master,current_state_code,proposed_state_code,status,reviewed_at"
AUDIT_TABLE = "team_state_audit"
AUDIT_COLS = "id,team_id_master,action,old_state_code,new_state_code,applied_at,applied_by,reason"
ACTIVE_DECISION_COLS = "id,subject_key,decision,source,decided_at"

REVERT_FILE = "REVERT.md"
SAFE_FILE, HELD_FILE = "safe.json", "held.json"
PILOT, REST = "pilot", "rest"
PILOT_ROWS = 50
LEDGER_CHUNK = 500
STATE_REVERT_PAGE = 500
# A state batch is found by its time window, and this machine's clock and the database's can disagree.
CLOCK_MARGIN = timedelta(minutes=2)
OTHER_WRITER = "already at the proposed state, set by another writer"
MOVED = "moved since the choices were collected"

WINDOW_CONFIG = ROOT / "config" / "team_cleanup.json"
ARIZONA = timezone(timedelta(hours=-7), "Arizona")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
WEEK_MINUTES = 7 * 24 * 60
# (weekday, minute of the day) in Arizona. A week's applies sit between Wednesday's 18:00 UTC propose
# and the first Monday import, ea-scraper.yml's 05:00 UTC cron.
PROPOSE_AT = (2, 11 * 60)
HARD_STOP_AT = (6, 22 * 60)

# Every workflow with a step that can write teams, states or games, or that reads a field a stage writes
# into something published, whether a cron or a person starts it. The test file names why each other
# workflow is left out, a writer exempted included.
WRITER_WORKFLOWS = (
    "calculate-rankings.yml",
    "data-hygiene-weekly.yml",
    "update-missing-club-and-state.yml",
    "unknown-opponent-hygiene-weekly.yml",
    "fill-team-states-weekly.yml",
    "fix-age-year-discrepancies.yml",
    "ea-scraper.yml",
    "ut-scraper.yml",
    "wa-scraper.yml",
    "or-scraper.yml",
    "playmetrics-scrape-import.yml",
    "playmetrics-tournament-scrape-import.yml",
    "tgs-event-scrape-import.yml",
    "yssl-scraper.yml",
    "modular11-weekly-scrape.yml",
    "modular11-events-weekly-scrape.yml",
    "auto-gotsport-event-scrape.yml",
    "scrape-games.yml",
    "scrape-specific-event.yml",
    "clear-queue.yml",
    "sincsports-team-discovery.yml",
)
# The scripts that can write teams, states or games, or read a field a stage writes into something
# published, which a person or an agent may run on this machine: the appliers run only by hand, and each
# such script a checked workflow runs. The test file names why each other script those workflows run is
# left out.
APPLIER_SCRIPTS = (
    "repair_swapped_club_names.py",
    "apply_vetted_club_names.py",
    "fix_band_cohorts.py",
    "repair_out_of_board_cohorts.py",
    "assign_team_states.py",
    "review_state_queue_by_name.py",
    "reconcile_teams_with_gotsport.py",
    "apply_team_fields.py",
    "fix_gender_from_registered_name.py",
    "reassign_games_between_teams.py",
    "apply_vetted_team_merges.py",
    "merge_teams.py",
    "exclude_merge_duplicate_games.py",
    "apply_stage.py",
    "normalize_team_names.py",
    "backfill_missing_club_names.py",
    "extract_missing_club_names.py",
    "apply_unknown_opponent_matches.py",
    "auto_match_unknown_opponents.py",
    "backfill_missing_state_codes.py",
    "backfill_state_from_opponents.py",
    "backfill_state_from_team_name.py",
    "backfill_team_distinction.py",
    "calculate_rankings.py",
    "cleanup_dupe_games_by_composite.py",
    "discover_sincsports_teams.py",
    "discover_teams_from_opponents.py",
    "drain_queue.py",
    "extract_and_import_tgs_teams.py",
    "find_fuzzy_duplicate_teams.py",
    "find_queue_matches.py",
    "fix_team_age_groups.py",
    "full_club_analysis.py",
    "import_games_enhanced.py",
    "import_yssl.py",
    "link_modular11_ea_teams.py",
    "match_state_from_club.py",
    "scrape_games.py",
    "scrape_new_gotsport_events.py",
    "scrape_specific_event.py",
)
WORKFLOW_DIR = ".github/workflows"
# Every status of a run not yet finished, each asked for by name across the repository, one at a time.
UNFINISHED = ("queued", "in_progress", "requested", "waiting", "pending")
RUNS_ENDPOINT = "repos/{owner}/{repo}/actions/runs"
# One page of a status's runs. A full page fails the check rather than paging on, so no run is missed past
# it, nor as runs finish and shift between pages.
GH_PAGE = 100
CHECK_TIMEOUT_SECONDS = 120
# Every Python process with its parent and command line, as JSON: Git Bash's ps misses native Windows
# processes, and Windows PowerShell writes a redirected stdout in the OEM code page unless told otherwise.
PROCESS_QUERY = (
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
    "Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%'\" | "
    "Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
)


def actor_for(run_id: str) -> str:
    return f"team-cleanup:{run_id}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _instant(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _same(field: str, live, value) -> bool:
    """Whether a team's column holds ``value``. state_code is CHAR(2), so a state reads back padded."""
    if field == "state_code":
        return (live or "").strip() == (value or "").strip()
    return live == value


def _tail(path: Path, lines: int = 6) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        return ""
    return "\n    ".join(text[-lines:])


# --- the apply window ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    start: int
    end: int
    text: str


def _after_propose(weekday: int, minute: int) -> int:
    """Minutes from Wednesday's propose to this time of the week, both in Arizona."""
    return ((weekday - PROPOSE_AT[0]) * 24 * 60 + minute - PROPOSE_AT[1]) % WEEK_MINUTES


def _bound(spec: dict) -> tuple[int, str]:
    weekday = WEEKDAYS.index(spec["weekday"].strip().lower())
    match = re.fullmatch(r"([01][0-9]|2[0-3]):([0-5][0-9])", spec["time"])
    if not match:
        raise ValueError(f"{spec['time']!r} is not a 24-hour HH:MM time")
    minute = int(match.group(1)) * 60 + int(match.group(2))
    return _after_propose(weekday, minute), f"{WEEKDAYS[weekday].title()} {spec['time']}"


def load_window(path: Path = WINDOW_CONFIG) -> Window:
    """The configured apply window, refused unless it runs forwards from Wednesday's propose and ends by
    the Monday hard stop."""
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))["apply_window"]
        start, start_text = _bound(spec["start"])
        end, end_text = _bound(spec["end"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"{path} holds no readable apply_window ({type(exc).__name__}: {exc})") from None
    if not start < end <= _after_propose(*HARD_STOP_AT):
        raise ValueError(
            f"{path}'s apply_window, {start_text} to {end_text}, must run forwards between Wednesday 11:00 "
            "(the propose) and Sunday 22:00 (the first Monday import), Arizona time"
        )
    return Window(start, end, f"{start_text} to {end_text}, Arizona time")


def in_window(window: Window, moment: datetime) -> bool:
    local = moment.astimezone(ARIZONA)
    return window.start <= _after_propose(local.weekday(), local.hour * 60 + local.minute) < window.end


def check_window(outside_window: bool) -> None:
    window = load_window()
    if not (outside_window or in_window(window, _now())):
        raise SystemExit(f"Outside the apply window ({window.text}); apply inside it, or pass --outside-window.")


# --- the pre-apply checks ------------------------------------------------------------------------


class CheckFailed(RuntimeError):
    """A pre-apply check could not run, so nothing may be applied."""


def _listing(command: list[str], what: str, **kwargs) -> list[dict]:
    """A check's JSON answer as a list of objects, one object alone being a list of one. Raises CheckFailed
    when the command fails or answers anything else, nothing included: gh answers a page even with no runs,
    and the process listing always holds this apply."""
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=CHECK_TIMEOUT_SECONDS,
            **kwargs,
        )
        if done.returncode != 0:
            raise CheckFailed(f"{what} exited {done.returncode}: {(done.stderr or '').strip()}")
        if done.stdout is None or not done.stdout.strip():
            raise CheckFailed(f"{what} printed nothing that could be read")
        found = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise CheckFailed(f"{what} failed: {type(exc).__name__}: {exc}") from None
    found = [found] if isinstance(found, dict) else found
    if not (isinstance(found, list) and all(isinstance(row, dict) for row in found)):
        raise CheckFailed(f"{what} answered {found!r:.80}, not a list of objects")
    return found


def gh_runs(status: str) -> list[dict]:
    """The repository's runs with ``status``, every workflow's, a disabled workflow's included, each naming
    its workflow file's path. gh fills in the endpoint's owner and repo from this checkout. Raises
    CheckFailed on anything but one page of runs short of full."""
    what = f"gh api {RUNS_ENDPOINT} -f status={status}"
    command = ["gh", "api", "-X", "GET", RUNS_ENDPOINT, "-f", f"status={status}", "-f", f"per_page={GH_PAGE}"]
    answer = _listing(command, what, cwd=ROOT)
    runs = answer[0].get("workflow_runs") if len(answer) == 1 else None
    if not (isinstance(runs, list) and all(isinstance(run, dict) and isinstance(run.get("path"), str) for run in runs)):
        raise CheckFailed(f"{what} answered {answer!r:.80}, not a page of workflow runs")
    if len(runs) >= GH_PAGE:
        raise CheckFailed(f"{what} filled a page of {GH_PAGE} runs, so one could lie past it")
    return runs


def python_processes() -> list[dict]:
    """Every Python process on this machine, as {"ProcessId", "ParentProcessId", "CommandLine"}."""
    return _listing(["powershell", "-NoProfile", "-Command", PROCESS_QUERY], "the process listing")


def own_processes(processes: list[dict]) -> set:
    """This process and the chain of Python processes in the listing that launched it, such as a venv's
    python.exe or python -m dotenv run, whose command lines name this script too."""
    parents = {process.get("ProcessId"): process.get("ParentProcessId") for process in processes}
    own, pid = {os.getpid()}, parents.get(os.getpid())
    # Windows reuses process ids, so a parent id can lead back into the chain.
    while pid in parents and pid not in own:
        own.add(pid)
        pid = parents[pid]
    return own


def appliers_in(command_line: str) -> list[str]:
    """The team appliers a command line runs, as a script or as a module (python -m scripts.<name>)."""
    return [
        script
        for script in APPLIER_SCRIPTS
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(script)}", command_line, re.I)
        or re.search(rf"-m\s*(?:[A-Za-z0-9_]+\.)*{re.escape(script[:-3])}(?![A-Za-z0-9_.])", command_line, re.I)
    ]


def pre_apply_problems() -> list[str]:
    """Why another writer may be running: a writer workflow's run that has not completed (any status in
    UNFINISHED), a Python process on this machine running a team applier, another apply_stage.py
    included, or one whose command line cannot be read, this apply and what launched it aside. Raises
    CheckFailed when a check cannot run."""
    writers = {f"{WORKFLOW_DIR}/{workflow}": workflow for workflow in WRITER_WORKFLOWS}
    problems = [
        f"{writers[run['path']]} run {run.get('id')} is {run.get('status')} ({run.get('event')})"
        for status in UNFINISHED
        for run in gh_runs(status)
        if run["path"] in writers
    ]
    processes = python_processes()
    own = own_processes(processes)
    for process in processes:
        pid, line = process.get("ProcessId"), process.get("CommandLine")
        if pid in own:
            continue
        if line is None:
            problems.append(f"Python process {pid}: its command line cannot be read")
        elif found := appliers_in(line):
            problems.append(f"Python process {pid} runs {', '.join(found)}")
    return problems


def check_other_writers() -> None:
    try:
        problems = pre_apply_problems()
    except CheckFailed as exc:
        raise SystemExit(f"Not applying: {exc}") from None
    if problems:
        raise SystemExit("Not applying while another writer may be running:\n  " + "\n  ".join(problems))


def keep_lease(sb, run_id: str, holder: str | None, what: str, retry: str) -> None:
    """Push the run's lease out before a step that writes, and stop once it is no longer this apply's. A
    closed run's revert holds no lease to keep."""
    if holder is None:
        return
    try:
        if renew_lease(sb, run_id, holder):
            return
    except (APIError, httpx.HTTPError) as exc:
        raise SystemExit(refused(f"Could not renew run {run_id}'s lease", exc, retry)) from None
    raise SystemExit(f"Run {run_id}'s lease is no longer {holder}'s, so {what}.")


# --- the stage's files ---------------------------------------------------------------------------


def check_collected(folder: Path, stage: str) -> dict:
    """collected.json, once the vetted file and decisions.json are the ones it names, byte for byte."""
    marker = read_json(folder / COLLECTED_MARKER)
    missing = [key for key in ("run", "collected_at", "counts", "hashes") if key not in marker]
    if missing:
        raise ValueError(f"{folder / COLLECTED_MARKER} lacks {', '.join(missing)}; collect again")
    vetted = VETTED[stage]
    if marker.get("vetted") not in (vetted, None):
        raise ValueError(f"collected.json names {marker.get('vetted')!r}, not {vetted}")
    changed = [name for name in (vetted, DECISIONS_FILE) if file_hash(folder / name) != marker["hashes"].get(name)]
    if changed:
        raise ValueError(f"changed since the choices were collected: {', '.join(changed)}; collect again")
    return marker


def open_stage(store: Path, run_id: str, stage: str) -> tuple[Path, dict]:
    """The stage's folder and collected.json, once the stage is due its apply and nothing it reads has
    changed since the page was built and the choices collected."""
    folder = stage_due(store, read_run(store, run_id), stage, ("apply",))
    try:
        check_unchanged(folder)
    except KeyError as exc:
        raise ValueError(f"{folder / PAGE_MARKER} lacks {exc}; build the page again") from None
    marker = check_collected(folder, stage)
    if stage == STATES and marker.get("vetted"):
        rules = read_json(folder / VETTED[STATES]).get("rules")
        if rules != SNAPSHOT_RULES:
            raise ValueError(
                f"the state snapshot was decided under rules {rules!r}, not {SNAPSHOT_RULES!r}, so "
                "assign_team_states.py refuses to replay it; next week's proposal decides again"
            )
    return folder, marker


def vetted_changes(folder: Path, stage: str) -> list[dict]:
    """The changes chosen Apply that the stage's applier replays, in team id order so the pilot spreads
    across the stage. A state card the rules only queued goes through the review queue instead."""
    path = folder / VETTED[stage]
    if not path.exists():
        return []
    if stage == STATES:
        return sorted((d for d in read_json(path)["decisions"] if d["action"] == "apply"), key=lambda d: d["team_id"])
    return sorted(_read_csv(path), key=lambda row: row["team_id_master"])


def pilot_and_rest(changes: list[dict]) -> list[tuple[str, list[dict]]]:
    return [(name, part) for name, part in ((PILOT, changes[:PILOT_ROWS]), (REST, changes[PILOT_ROWS:])) if part]


def cut_name(stage: str, name: str) -> str:
    return f"{name}.json" if stage == STATES else f"{name}.csv"


def write_cut(folder: Path, stage: str, name: str, changes: list[dict]) -> Path:
    """The changes in the applier's own input format, beside the vetted file. CSV rows are copied as the
    vetted file holds them, so the applier reads its own escaping back."""
    path = folder / cut_name(stage, name)
    if stage == STATES:
        write_json(path, {**read_json(folder / VETTED[STATES]), "decisions": changes}, indent=1)
    else:
        write_log(changes, path)
    return path


def applier_command(stage: str, cut: Path, store: Path, run_id: str) -> list[str]:
    exports, actor = str(store / "exports"), actor_for(run_id)
    if stage == CLUBS:
        return [SWAPPED_CLUBS, "--execute", str(cut), "--exports-dir", exports, "--actor", actor]
    if stage == AGES:
        flags = ["--execute", "--skip-name-contradictions", "--exports-dir", exports, "--actor", actor]
        return [AGE_FIXER, "--apply", str(cut), *flags]
    return [ASSIGN_STATES, "--execute", "--snapshot", str(cut)]


def hold_command(folder: Path) -> list[str]:
    """The hold script over the whole national run, so a club sent to two states is held even when one
    of them is outside this run's scope."""
    national = folder / NATIONAL_STATES
    if not national.exists():
        raise ValueError(f"there is no {national} for the hold script to read")
    return [HOLD_STATES, str(national), str(folder / SAFE_FILE), str(folder / HELD_FILE)]


def revert_command(stage: str, log: str, execute: bool) -> list[str]:
    """The applier's own --revert of one batch's log; without --execute it previews, writing nothing."""
    return [APPLIERS[stage], "--revert", log, *(["--execute"] if execute else [])]


def load_progress(folder: Path, marker: dict) -> dict:
    """apply.json as an earlier attempt at this stage left it, else a fresh one. Refuses one begun on
    choices collected before the ones collected.json now names."""
    if not (folder / APPLY_PROGRESS_FILE).exists():
        return {"collected": marker["hashes"], "cuts": None, "held": [], "batches": [], "queue": []}
    progress = read_progress(folder)
    if progress["collected"] != marker["hashes"]:
        raise ValueError(
            f"the choices were collected again after this stage began applying (see "
            f"{folder / APPLY_PROGRESS_FILE}); its earlier batches stay applied, so ask the owner before "
            "applying the new choices"
        )
    return progress


def save_progress(folder: Path, progress: dict) -> None:
    write_json(folder / APPLY_PROGRESS_FILE, progress, indent=1)


def no_recorded_end(folder: Path, store: Path, batch: dict) -> str:
    return (
        f"The {batch['batch']} batch started {batch['started_at']} has no recorded end: an apply was stopped "
        f"while its applier ran. Find what it wrote (its output {batch['output']}, and its log in "
        f"{store / 'exports'}) and record in {folder / APPLY_PROGRESS_FILE} its exit and its ended_at, a full ISO "
        "time with its offset, and for clubs or ages its log's path in its logs, the only log the revert replays, "
        "before applying or reverting again."
    )


def no_recorded_queue_end(folder: Path, step: dict) -> str:
    return (
        f"The review-queue step started {step['started_at']} has no recorded end: an apply was stopped while it "
        f"settled cards. The reviews it settled are saved in {folder / APPLY_PROGRESS_FILE}; record there when it "
        "stopped as the step's ended_at, a full ISO time with its offset, before applying or reverting again. Both "
        "then check that each approval it made lies inside its window, and name any that does not."
    )


# --- recording the owner's decisions -------------------------------------------------------------


def check_ledger(sb) -> None:
    """Read team_cleanup_changes once, so a migration not yet applied stops the apply before it writes,
    rather than once a batch has."""
    sb.table(CHANGES_TABLE).select("id").limit(1).execute()


def plan_decisions(sb, stage: str, rows: list[dict]) -> list[tuple[dict, dict, dict | None]]:
    """(card, its row for team_cleanup_decisions, the active row it replaces) for each decided card not
    already recorded with the same decision from the same page. Refuses when a later decision is
    recorded for a card, which recording this one would overturn."""
    active = {}
    for batch in batched(sorted({row["team_id_master"] for row in rows})):
        query = sb.table(DECISIONS_TABLE).select(ACTIVE_DECISION_COLS).eq("stage", stage)
        for found in query.is_("superseded_at", "null").in_("team_id_master", batch).execute().data:
            active[found["subject_key"]] = found
    planned, later = [], []
    for row in rows:
        record = team_decision_row(stage, row)
        current = active.get(record["subject_key"])
        if current and (current["decision"], current["source"]) == (record["decision"], record["source"]):
            continue
        if current and _instant(current["decided_at"]) > _instant(record["decided_at"]):
            later.append(f"{row['team_name']!r} ({current['decision']} on {current['decided_at'][:10]})")
        planned.append((row, record, current))
    if later:
        raise ValueError("a later decision is already recorded for " + ", ".join(later))
    return planned


def record_decisions(sb, planned: list[tuple[dict, dict, dict | None]], retry: str) -> None:
    """Supersede, then insert: the one-active-row index is partial, so PostgREST cannot upsert on it."""
    for _, record, current in planned:
        try:
            if current:
                stamp = {"superseded_at": utc_now_iso()}
                sb.table(DECISIONS_TABLE).update(stamp).eq("id", current["id"]).is_("superseded_at", "null").execute()
            sb.table(DECISIONS_TABLE).insert(record).execute()
        except (APIError, httpx.HTTPError) as exc:
            action = f"Could not record the owner's decision on {record['subject_key']}"
            raise SystemExit(refused(action, exc, retry)) from None


# --- state cards the rules only queued -----------------------------------------------------------


def queue_cards(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("action") == "queue" and row["decision"] in (APPLY, DONT_APPLY)]


def newest_reviews(sb, team_ids) -> dict[tuple[str, str], dict]:
    """The newest review-queue row per (team, proposed state), the key the sweep reads them by."""
    newest = {}
    for batch in batched(sorted(team_ids)):
        rows = page(lambda batch=batch: sb.table(QUEUE_TABLE).select(REVIEW_COLS).in_("team_id_master", batch), "id")
        for row in rows:
            newest[queue_key(row)] = row
    return newest


def review_payload(card: dict, snapshot: dict) -> dict:
    """A review row as the sweep files one, from the snapshot's decision behind the card. Its confidence
    is the snapshot's, else its tier's."""
    decisions = {(d["team_id"], d["proposed"]): d for d in snapshot["decisions"]}
    decision = decisions[card["team_id_master"], card["new_value"]]
    if decision.get("confidence") is None:
        decision = {**decision, "confidence": TIER_CONFIDENCE.get(decision["tier"])}
    return queue_payload(decision)


def plan_queue(cards: list[dict], newest: dict, snapshot: dict, collected_at: str) -> list[dict]:
    """What each card does to the review queue. Apply approves the newest pending row for the team and
    state, Don't apply rejects it, and with none pending a row is filed first, so the owner's newer
    choice wins over an older dashboard reject. A row settled already the way the card asks is left
    alone, and so is an approved one, a reject made since the choices were collected, and for Apply a
    pending row a later sweep refiled from another state than the one the card showed."""
    plans = []
    for card in cards:
        row = newest.get((card["team_id_master"], card["new_value"]))
        status = row["status"] if row else None
        plan = {"card": card, "approve": card["decision"] == APPLY, "review_id": None, "payload": None, "skip": None}
        if status == "approved":
            plan["skip"] = "already approved" + ("" if plan["approve"] else "; Don't apply does not undo it")
        elif status == "rejected" and not plan["approve"]:
            plan["skip"] = "already rejected"
        elif status == "rejected" and row["reviewed_at"] and _instant(row["reviewed_at"]) > _instant(collected_at):
            plan["skip"] = "rejected since the choices were collected"
        elif (
            status == "pending"
            and plan["approve"]
            and not _same("state_code", row["current_state_code"], card["old_value"])
        ):
            plan["skip"] = MOVED
        elif status == "pending":
            plan["review_id"] = row["id"]
        else:
            plan["payload"] = review_payload(card, snapshot)
        plans.append(plan)
    return plans


def queue_plans(sb, folder: Path, rows: list[dict], collected_at: str) -> list[dict]:
    """The queued state cards' plans, read against the review queue as it stands."""
    cards = queue_cards(rows)
    if not cards:
        return []
    newest = newest_reviews(sb, {card["team_id_master"] for card in cards})
    return plan_queue(cards, newest, read_json(folder / APPLIER_INPUTS[STATES]), collected_at)


def describe_plan(plan: dict) -> str:
    if plan["skip"]:
        return plan["skip"]
    verb = "approve" if plan["approve"] else "reject"
    return f"{verb} review {plan['review_id']}" if plan["review_id"] else f"file a review row, then {verb} it"


def still_pending(sb, review_id, state: str) -> bool:
    """Whether the review row is still pending, filed from ``state``."""
    rows = sb.table(QUEUE_TABLE).select(REVIEW_COLS).eq("id", review_id).execute().data
    return bool(rows) and rows[0]["status"] == "pending" and _same("state_code", rows[0]["current_state_code"], state)


def _settle(sb, plan: dict, actor: str, reviews: list, save, retry: str) -> str:
    """One card's outcome. A card the database refuses, as when its team moved since its row was filed, is
    reported rather than retried; any other refusal stops, and so does a lost answer, after which a re-run
    reads where the row now stands. The review is listed in ``reviews`` and saved before it is settled, so a
    revert knows its approval as this run's even when the answer was lost or the apply was killed. A pending
    row is read again just before it is approved, since approve_team_state approves from whatever state the
    row holds by then: one settled meanwhile, or refiled by a sweep from another state, is skipped as moved."""
    review_id = plan["review_id"]
    try:
        if review_id is None:
            review_id = plan["review_id"] = sb.table(QUEUE_TABLE).insert(plan["payload"]).execute().data[0]["id"]
        elif plan["approve"] and not still_pending(sb, review_id, plan["card"]["old_value"]):
            return MOVED
        reviews.append(review_id)
        save()
        if plan["approve"]:
            sb.rpc("approve_team_state", {"p_review_id": review_id, "p_approver": actor}).execute()
            return "approved"
        sb.rpc("reject_team_state", {"p_review_id": review_id, "p_reviewer": actor}).execute()
        return "rejected"
    except (APIError, httpx.HTTPError) as exc:
        if isinstance(exc, APIError) and exc.code == CARD_REFUSAL:
            pending = f"; review {review_id} stays pending" if review_id is not None else ""
            return f"refused: {exc.message}{pending}"
        raise SystemExit(refused(f"Could not settle {plan['card']['team_name']!r}'s review", exc, retry)) from None


def settle_queue(sb, plans: list[dict], actor: str, step: dict, save, retry: str) -> None:
    for plan in plans:
        card = plan["card"]
        outcome = plan["skip"] or _settle(sb, plan, actor, step["reviews"], save, retry)
        step["cards"].append(
            {
                "team_id_master": card["team_id_master"],
                "team_name": card["team_name"],
                "state": card["new_value"],
                "decision": card["decision"],
                "outcome": outcome,
                "review_id": plan["review_id"],
            }
        )


# --- what each batch changed: the applier's own record, then the database --------------------------


def _window(step: dict) -> tuple[str, str]:
    """A step's time window, widened by the clock margin. A step stopped part way never stamped its
    end, so its window runs to now."""
    start = _instant(step["started_at"]) - CLOCK_MARGIN
    end = _instant(step["ended_at"] or utc_now_iso()) + CLOCK_MARGIN
    return start.isoformat(), end.isoformat()


def _covers(step: dict, at: datetime) -> bool:
    """Whether the step's window holds ``at``, as revert_team_states reads it: from its start, short of its end."""
    start, end = (_instant(edge) for edge in _window(step))
    return start <= at < end


def _distance(step: dict, at: datetime) -> timedelta:
    start, end = (_instant(edge) for edge in _window(step))
    return max(start - at, at - end)


def state_audit(sb, actor: str, window: tuple[str, str], *, reason: str | None = None):
    """The team_state_audit rows revert_team_states would read for the same actor and window."""

    def build():
        query = sb.table(AUDIT_TABLE).select(AUDIT_COLS).eq("applied_by", actor).neq("action", "revert")
        query = query.gte("applied_at", window[0]).lt("applied_at", window[1])
        return query.eq("reason", reason) if reason else query

    return page(build, "id")


def audit_in(sb, actor: str, column: str, values, **equal) -> list[dict]:
    """The team_state_audit rows by ``actor`` whose ``column`` is one of ``values``, at any time, that
    match ``equal`` too."""
    found = []
    for batch in batched(sorted(values)):

        def build(batch=batch):
            query = sb.table(AUDIT_TABLE).select(AUDIT_COLS).eq("applied_by", actor).in_(column, batch)
            for name, value in equal.items():
                query = query.eq(name, value)
            return query

        found += page(build, "id")
    return found


def approval_reason(review_id) -> str:
    """The audit reason approve_team_state writes for the review it settles."""
    return f"approved review {review_id}"


def replay_steps(progress: dict) -> dict[tuple[str, str], list[tuple[str, dict]]]:
    """The batch attempts that may have written each (snapshot reason, team) the replay writes: every
    attempt of the batch whose cut holds the team, each named by its place in apply.json."""
    cuts = {path: read_json(Path(path)) for path in sorted({batch["cut"] for batch in progress["batches"]})}
    steps = {}
    for n, batch in enumerate(progress["batches"]):
        cut = cuts[batch["cut"]]
        for decision in cut["decisions"]:
            key = (snapshot_reason(cut["created_at"]), decision["team_id"])
            steps.setdefault(key, []).append((f"batches[{n}]", batch))
    return steps


def approval_steps(progress: dict) -> dict[str, list[tuple[str, dict]]]:
    """The audit reason of each review a queue step settled, with the steps that did, each named by its
    place in apply.json."""
    steps = {}
    for n, queued in enumerate(progress["queue"]):
        for review in queued["reviews"]:
            steps.setdefault(approval_reason(review), []).append((f"queue[{n}]", queued))
    return steps


def state_owner(progress: dict):
    """Whether a team_state_audit row is one of the stage's own writes. The replay's carry its snapshot's
    reason for a team in that cut; an approval names a review a queue step settled. Anything else in a
    step's window is another writer's."""
    replays, approvals = replay_steps(progress), approval_steps(progress)

    def own(row: dict) -> bool:
        if row["applied_by"] == STATE_SWEEP_ACTOR:
            return (row["reason"], row["team_id_master"]) in replays
        return row["action"] == "approve" and row["reason"] in approvals

    return own


def _audit_line(row: dict) -> str:
    return (
        f"{row['team_id_master']}: {row['action']} {row['old_state_code']} -> {row['new_state_code']} by "
        f"{row['applied_by']} at {row['applied_at']} (audit row {row['id']})"
    )


def unreachable_writes(sb, run_id: str, progress: dict) -> list[str]:
    """The stage's own state writes, found at any time, that lie outside the window of every step that may
    have made them: the revert reads only those windows, so it could not undo them. Each names the nearest
    of those steps. An approved card whose review has no audit row is listed too."""
    replays, approvals = replay_steps(progress), approval_steps(progress)
    replayed = audit_in(sb, STATE_SWEEP_ACTOR, "reason", {reason for reason, _ in replays})
    approved = audit_in(sb, actor_for(run_id), "reason", approvals, action="approve")
    found = [(row, replays.get((row["reason"], row["team_id_master"]))) for row in replayed]
    found += [(row, approvals[row["reason"]]) for row in approved]
    problems = []
    for row, steps in found:
        at = _instant(row["applied_at"])
        if steps and not any(_covers(step, at) for _, step in steps):
            where, step = min(steps, key=lambda named: _distance(named[1], at))
            problems.append(f"{_audit_line(row)}, outside the window of {where}, started {step['started_at']}")
    audited = {row["reason"] for row in approved}
    problems += [
        f"review {card['review_id']} ({card['team_name']!r}) in queue[{n}]: approved, with no audit row; if "
        f"team_state_audit holds none for it, the approval wrote nothing, so remove {card['review_id']} from "
        f"queue[{n}].reviews"
        for n, queued in enumerate(progress["queue"])
        for card in queued["cards"]
        if card["outcome"] == "approved"
        and card["review_id"] in queued["reviews"]
        and approval_reason(card["review_id"]) not in audited
    ]
    return problems


def unreachable_text(folder: Path, unreachable: list[str]) -> str:
    """What the apply and the revert both say of the stage's own writes its revert could not reach."""
    path = folder / APPLY_PROGRESS_FILE
    return (
        f"{len(unreachable)} of the stage's own state write(s) or approval(s) the revert could not reach, since it "
        f"reads only the windows {path} saves for the steps that made them:\n  " + "\n  ".join(unreachable) + "\nIf "
        "this machine's clock is wrong, set it right first, or a batch still to run will stop the same way. Then in "
        f"{path} widen each named step's started_at or ended_at to cover the time listed with it, written as a "
        "full ISO time with its offset, or do what a line with no time says, and re-run."
    )


def own_log(stage: str, batch: dict, run_id: str) -> str | None:
    """The batch's own log among the new ones in the exports folder: the one holding rows, each written
    as this run for a team in the batch's cut. Another writer's log landing there meanwhile is not, and
    when none or more than one passes, no log is the batch's own."""
    cut = {row["team_id_master"] for row in _read_csv(Path(batch["cut"]))}
    actor = actor_for(run_id)
    own = []
    for log in batch["logs"]:
        rows = LOG_READERS[stage](Path(log))
        if rows and all(row.get("actor") == actor and row["team_id_master"] in cut for row in rows):
            own.append(log)
    return own[0] if len(own) == 1 else None


def _state_change(row: dict, confirmed: bool) -> dict:
    return {
        "team_id_master": row["team_id_master"],
        "old_value": (row["old_state_code"] or "").strip() or None,
        "new_value": (row["new_state_code"] or "").strip(),
        "applied_at": row["applied_at"],
        "log_file": None,
        "confirmed": confirmed,
    }


def _logged_change(team_id: str, old: str, new: str, batch: dict, log: str, confirmed: bool) -> dict:
    return {
        "team_id_master": team_id,
        "old_value": old,
        "new_value": new,
        "applied_at": batch["ended_at"],
        "log_file": log,
        "confirmed": confirmed,
    }


def _club_log_changes(log: str, batch: dict, finished: bool) -> tuple[list[dict], list[list[str]]]:
    changes, skipped = [], []
    for row in _read_csv(Path(log)):
        if row["run_mode"] != "execute":
            continue
        if row["action"] != "updated":
            skipped.append([row["team_id_master"], row["action"]])
            continue
        old, new = csv_unsafe(row["before"]), csv_unsafe(row["after"])
        changes.append(_logged_change(row["team_id_master"], old, new, batch, log, finished))
    return changes, skipped


def _age_log_changes(log: str, batch: dict, finished: bool) -> tuple[list[dict], list[list[str]]]:
    """When the fixer stops, it marks unconfirmed the one row whose write was under way, which counts
    once the database shows it. A row it only planned is reported, never ledgered: it was never sent, or
    after a hard kill was sent after the log's last checkpoint, and the database holding its new age
    does not show that this run wrote it."""
    changes, skipped = [], []
    for row in read_our_csv(Path(log)):
        if row["result"] not in AGE_WRITTEN:
            why = row["result"] + (f": {row['hold_reason']}" if row["hold_reason"] else "")
            skipped.append([row["team_id_master"], why])
            continue
        confirmed = finished and row["result"] == "updated"
        old, new = row["old_age_group"], row["new_age_group"]
        changes.append(_logged_change(row["team_id_master"], old, new, batch, log, confirmed))
    return changes, skipped


LOG_CHANGES = {CLUBS: _club_log_changes, AGES: _age_log_changes}


def batch_changes(sb, run_id: str, stage: str, batch: dict) -> tuple[list[dict], list[list[str]]]:
    """The changes a batch's applier records writing, and the cut's rows it left unwritten, with why. A
    change is confirmed when the applier finished and saw its write land; an unconfirmed one counts
    only once the database shows it."""
    finished = batch["exit"] == 0
    if stage == STATES:
        # The pilot's and the rest's windows can overlap by the clock margin, and both carry one reason.
        cut = read_json(Path(batch["cut"]))
        teams = {d["team_id"] for d in cut["decisions"]}
        found = state_audit(sb, STATE_SWEEP_ACTOR, _window(batch), reason=snapshot_reason(cut["created_at"]))
        written = [row for row in found if row["team_id_master"] in teams]
        done = {row["team_id_master"] for row in written}
        why = "not written by the replay: moved, outranked or reverted since the snapshot"
        return [_state_change(row, finished) for row in written], [[team, why] for team in sorted(teams - done)]
    log = own_log(stage, batch, run_id)
    if log is None:
        return [], []
    return LOG_CHANGES[stage](log, batch, finished)


def verify(sb, field: str, changes: list[dict]) -> tuple[list[dict], list[dict]]:
    """The changes the database holds now, and the confirmed ones it does not."""
    teams = fetch_teams(sb, sorted({change["team_id_master"] for change in changes}))
    holding, missing = [], []
    for change in changes:
        team = teams.get(change["team_id_master"])
        if team is not None and _same(field, team[field], change["new_value"]):
            holding.append(change)
        elif change["confirmed"]:
            missing.append(change)
    return holding, missing


def ledger_rows(run_id: str, stage: str, changes: list[dict], applier: str, actor: str) -> list[dict]:
    return [
        {
            "run_id": run_id,
            "stage": stage,
            "team_id_master": change["team_id_master"],
            "field": FIELDS[stage],
            "old_value": change["old_value"],
            "new_value": change["new_value"],
            "applier": applier,
            "actor": actor,
            "log_file": change["log_file"],
            "applied_at": change["applied_at"],
            "reverted_at": None,
        }
        for change in changes
    ]


def write_ledger(sb, rows: list[dict], retry: str) -> None:
    """Upserted on the one-row-per-change key, clearing reverted_at, so a change undone and applied again
    in the same run reads as applied."""
    unique = {(row["team_id_master"], row["field"], row["new_value"]): row for row in rows}
    try:
        for chunk in batched(list(unique.values()), LEDGER_CHUNK):
            sb.table(CHANGES_TABLE).upsert(chunk, on_conflict=CHANGE_KEY).execute()
    except (APIError, httpx.HTTPError) as exc:
        raise SystemExit(refused(f"Could not write {CHANGES_TABLE}", exc, retry)) from None


def settle_batch(sb, run_id: str, stage: str, batch: dict, retry: str) -> list[dict]:
    """Verify one attempt's changes, ledger the ones the database holds, and keep its counts in the
    attempt's record. Returns the confirmed changes the database does not hold."""
    changes, skipped = batch_changes(sb, run_id, stage, batch)
    holding, missing = verify(sb, FIELDS[stage], changes)
    actor = STATE_SWEEP_ACTOR if stage == STATES else actor_for(run_id)
    write_ledger(sb, ledger_rows(run_id, stage, holding, APPLIERS[stage], actor), retry)
    batch["counts"] = {"written": len(changes), "verified": len(holding), "not_verified": len(missing)}
    batch["skipped"] = skipped
    return missing


def unaudited(sb, attempts: list[dict]) -> list[str]:
    """The cut's teams that hold their proposed state though no attempt's audit window shows the replay
    writing one: another writer set them, or this machine's clock and the database's disagree by more
    than the margin."""
    proposed = {d["team_id"]: d["proposed"] for d in read_json(Path(attempts[-1]["cut"]))["decisions"]}
    unwritten = set(proposed)
    for batch in attempts:
        unwritten &= {team for team, _ in batch["skipped"]}
    teams = fetch_teams(sb, sorted(unwritten))
    return sorted(t for t in unwritten if t in teams and _same("state_code", teams[t]["state_code"], proposed[t]))


def settle_unaudited(sb, attempts: list[dict]) -> None:
    """Relabel in each attempt's ``skipped`` the unaudited teams another writer set: those with no replay
    audit row at any time. One the replay wrote outside every attempt's window keeps its label, and
    unreachable_writes stops the stage on it."""
    found = unaudited(sb, attempts)
    if not found:
        return
    reason = snapshot_reason(read_json(Path(attempts[-1]["cut"]))["created_at"])
    rows = audit_in(sb, STATE_SWEEP_ACTOR, "team_id_master", found, reason=reason)
    replayed = {row["team_id_master"] for row in rows}
    for batch in attempts:
        batch["skipped"] = [
            [team, OTHER_WRITER if team in found and team not in replayed else why] for team, why in batch["skipped"]
        ]


def batch_problem(stage: str, batch: dict, missing: list[dict], run_id: str) -> str | None:
    if batch["exit"] != 0:
        return f"its applier exited {batch['exit']}; see {batch['output']}:\n    {_tail(Path(batch['output']))}"
    if stage in APPLIER_LOGS and own_log(stage, batch, run_id) is None:
        found = ", ".join(batch["logs"]) or "none"
        return (
            f"expected one new {APPLIER_LOGS[stage]} in the exports folder written as {actor_for(run_id)} for "
            f"the {batch['batch']} cut, found {found}"
        )
    if missing:
        listed = ", ".join(f"{c['team_id_master']} ({c['new_value']!r})" for c in missing[:10])
        return f"{len(missing)} written change(s) the database does not hold: {listed}"
    return None


# --- the apply -----------------------------------------------------------------------------------


def prepare_cuts(folder: Path, stage: str, progress: dict) -> dict[str, Path]:
    """The pilot and rest cut files, written once, so a re-run replays the files the first attempt
    wrote. States run the hold script over the national run first and leave out what it held."""
    if progress["cuts"] is not None:
        cuts = {name: folder / cut["file"] for name, cut in progress["cuts"].items()}
        changed = [path.name for name, path in cuts.items() if file_hash(path) != progress["cuts"][name]["sha256"]]
        if changed:
            raise ValueError(f"changed since this stage began applying: {', '.join(changed)}")
        return cuts
    changes = vetted_changes(folder, stage)
    if stage == STATES and changes:
        log = folder / LOGS / "hold_unsafe_state_applies.log"
        code = run_step(hold_command(folder), log)
        if code != 0:
            raise SystemExit(f"hold_unsafe_state_applies.py exited {code}; see {log}:\n    {_tail(log)}")
        held = {(d["team_id"], d["proposed"]): d for d in read_json(folder / HELD_FILE)}
        chosen = {(d["team_id"], d["proposed"]) for d in changes}
        progress["held"] = [d for key, d in held.items() if key in chosen]
        changes = [d for d in changes if (d["team_id"], d["proposed"]) not in held]
    cuts, progress["cuts"] = {}, {}
    for name, part in pilot_and_rest(changes):
        cuts[name] = write_cut(folder, stage, name, part)
        progress["cuts"][name] = {"file": cuts[name].name, "rows": len(part), "sha256": file_hash(cuts[name])}
    save_progress(folder, progress)
    return cuts


def run_batch(folder: Path, store: Path, run_id: str, stage: str, name: str, cut: Path, progress: dict) -> dict:
    """Run one cut through the applier, recording the attempt before it starts and once it ends."""
    exports = store / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    pattern = APPLIER_LOGS.get(stage)
    before = set(exports.glob(pattern)) if pattern else set()
    attempt = sum(1 for b in progress["batches"] if b["batch"] == name) + 1
    output = folder / LOGS / f"apply_{name}_{attempt}.log"
    command = applier_command(stage, cut, store, run_id)
    batch = {"batch": name, "cut": str(cut), "command": command, "output": str(output), "started_at": utc_now_iso()}
    batch.update({"ended_at": None, "exit": None, "logs": []})
    progress["batches"].append(batch)
    save_progress(folder, progress)
    batch["exit"] = run_step(command, output)
    batch["ended_at"] = utc_now_iso()
    batch["logs"] = [str(path) for path in sorted(set(exports.glob(pattern)) - before)] if pattern else []
    save_progress(folder, progress)
    # Both CSV appliers name their log by the second: the clubs one refuses a name taken, and the ages
    # one overwrites it.
    time.sleep(1)
    return batch


def apply_batches(
    sb,
    folder: Path,
    store: Path,
    run_id: str,
    stage: str,
    progress: dict,
    holder: str,
    outside_window: bool,
    retry: str,
):
    for name, cut in prepare_cuts(folder, stage, progress).items():
        attempts = [b for b in progress["batches"] if b["batch"] == name]
        unfinished = [b for b in attempts if b["exit"] is None]
        if unfinished:
            raise SystemExit(no_recorded_end(folder, store, unfinished[0]))
        if not any(b["exit"] == 0 for b in attempts):
            if name == REST:
                check_window(outside_window)
                check_other_writers()
            keep_lease(sb, run_id, holder, f"the {name} was not applied", retry)
            attempts.append(run_batch(folder, store, run_id, stage, name, cut, progress))
        # Every attempt is ledgered, and the newest decides whether the apply goes on.
        for batch in attempts[:-1]:
            settle_batch(sb, run_id, stage, batch, retry)
        problem = batch_problem(stage, attempts[-1], settle_batch(sb, run_id, stage, attempts[-1], retry), run_id)
        if stage == STATES and not problem:
            settle_unaudited(sb, attempts)
            unreachable = unreachable_writes(sb, run_id, progress)
            problem = unreachable_text(folder, unreachable) if unreachable else None
        save_progress(folder, progress)
        counts = attempts[-1]["counts"]
        print(f"{name}: {counts['written']} written, {counts['verified']} verified from the database and ledgered")
        if problem:
            raise SystemExit(f"Stopped after the {name} batch: {problem}\nRe-run once it is understood: {retry}")


def apply_queue(
    sb,
    folder: Path,
    run_id: str,
    rows: list[dict],
    progress: dict,
    collected_at: str,
    holder: str,
    outside_window: bool,
    retry: str,
) -> None:
    """Settle the queued state cards, read against the review queue once the window and the other writers
    are checked, then, once every one of the stage's own writes lies where its revert reads, ledger its
    approvals the database holds: the audit rows naming a review a queue step settled."""
    unended = [queued for queued in progress["queue"] if queued["ended_at"] is None]
    if unended:
        raise SystemExit(no_recorded_queue_end(folder, unended[0]))
    if not queue_cards(rows):
        return
    check_window(outside_window)
    check_other_writers()
    keep_lease(sb, run_id, holder, "the queued cards were not settled", retry)
    plans = queue_plans(sb, folder, rows, collected_at)
    step = {"started_at": utc_now_iso(), "ended_at": None, "cards": [], "reviews": []}
    progress["queue"].append(step)
    save_progress(folder, progress)
    try:
        settle_queue(sb, plans, actor_for(run_id), step, lambda: save_progress(folder, progress), retry)
    finally:
        step["ended_at"] = utc_now_iso()
        save_progress(folder, progress)
    unreachable = unreachable_writes(sb, run_id, progress)
    if unreachable:
        raise SystemExit(f"Stopped: {unreachable_text(folder, unreachable)}")
    found = audit_in(sb, actor_for(run_id), "reason", approval_steps(progress), action="approve")
    holding, missing = verify(sb, FIELDS[STATES], [_state_change(row, True) for row in found])
    write_ledger(sb, ledger_rows(run_id, STATES, holding, APPLY_SCRIPT, actor_for(run_id)), retry)
    print("queue: " + ", ".join(f"{card['team_name']!r} {card['outcome']}" for card in step["cards"]))
    if missing:
        listed = ", ".join(change["team_id_master"] for change in missing[:10])
        raise SystemExit(f"Stopped: {len(missing)} approved state(s) the database does not hold: {listed}")


def apply_stage(sb, store: Path, run_id: str, stage: str, outside_window: bool, retry: str) -> Path:
    with acquire_apply_lock(sb, store, run_id) as holder:
        folder, marker = open_stage(store, run_id, stage)
        check_other_writers()
        progress = load_progress(folder, marker)
        rows = read_json(folder / DECISIONS_FILE)
        check_ledger(sb)
        planned = plan_decisions(sb, stage, rows)
        record_decisions(sb, planned, retry)
        print(f"Recorded {len(planned)} decision(s) in {DECISIONS_TABLE}; {len(rows) - len(planned)} already were.")
        apply_batches(sb, folder, store, run_id, stage, progress, holder, outside_window, retry)
        if stage == STATES:
            apply_queue(sb, folder, run_id, rows, progress, marker["collected_at"], holder, outside_window, retry)
        return write_record(folder, store, run_id, stage, marker, rows, progress)


# --- RECORD.md -----------------------------------------------------------------------------------


def write_record(folder: Path, store: Path, run_id: str, stage: str, marker: dict, rows: list, progress: dict) -> Path:
    names = {row["team_id_master"]: row["team_name"] for row in rows}
    counts = ", ".join(f"{decision} {count}" for decision, count in marker["counts"].items())
    applied_as = (
        f"{STATE_SWEEP_ACTOR}, review-queue approvals as {actor_for(run_id)}" if stage == STATES else actor_for(run_id)
    )
    lines = [
        f"# {stage} applied, run {run_id}",
        "",
        f"- Page run {marker['run']}, choices collected {marker['collected_at']}: {counts}",
        f"- All {len(rows)} decided card(s) are recorded in {DECISIONS_TABLE}.",
        f"- Applied as {applied_as}, finished {utc_now_iso()}",
        "",
        "## Batches",
        "",
    ]
    if not progress["batches"]:
        lines.append("Nothing to apply: no card was chosen Apply, or the hold script held every one.")
    for batch in progress["batches"]:
        c = batch.get("counts", {})
        lines.append(
            f"- {batch['batch']} ({Path(batch['cut']).name}), {batch['started_at']} to {batch['ended_at']}: exit "
            f"{batch['exit']}, {c.get('written', 0)} written, {c.get('verified', 0)} verified and ledgered"
        )
        own = own_log(stage, batch, run_id) if stage in APPLIER_LOGS else None
        lines += [
            f"  - applier log: {log}" if log == own else f"  - another writer's log, not this batch's: {log}"
            for log in batch["logs"]
        ]
        lines.append(f"  - applier output: {batch['output']}")
    held = [f"- {names.get(d['team_id'], d['team_id'])!r}: held, {d['held_because']}" for d in progress["held"]]
    held += [f"- {names.get(team, team)!r}: {why}" for b in progress["batches"] for team, why in b.get("skipped", [])]
    lines += ["", "## Held or not written", "", *(held or ["None."])]
    if stage == STATES:
        cards = [card for queued in progress["queue"] for card in queued["cards"]]
        settled = [f"- {c['team_name']!r} to {c['state']}, {c['decision']}: {c['outcome']}" for c in cards]
        lines += ["", "## Review queue", "", *(settled or ["No queued card was decided."])]
    # Only the whole-stage revert keeps to the window, waits for other writers and stamps the ledger, so
    # no batch's own applier revert is offered.
    command = [APPLY_SCRIPT, "--run", run_id, "--stage", stage, "--revert"]
    whole = f"python {subprocess.list2cmdline([*command, '--execute', '--store', str(store)])}"
    preview = f"python {subprocess.list2cmdline([*command, '--store', str(store)])}"
    lines += [
        "",
        "## Undo",
        "",
        f"The whole stage: `{whole}`",
        "",
        f"Its dry run, which writes nothing: `{preview}`",
    ]
    path = folder / APPLY_MARKER
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


# --- undo ----------------------------------------------------------------------------------------


def state_windows(run_id: str, progress: dict) -> list[tuple[str, tuple[str, str], str]]:
    """Each state-writing step's (actor, window, label), in the order the apply ran them."""
    windows = [(STATE_SWEEP_ACTOR, _window(batch), f"{batch['batch']} batch") for batch in progress["batches"]]
    return windows + [(actor_for(run_id), _window(queued), "review-queue approvals") for queued in progress["queue"]]


def foreign_writes(sb, run_id: str, progress: dict) -> list[str]:
    """Writes in a step's window, under its actor, that are not the stage's own: reverting the window
    would undo them too."""
    own = state_owner(progress)
    found = []
    for actor, window, label in state_windows(run_id, progress):
        found += [
            f"{_audit_line(row)}, in the {label} window" for row in state_audit(sb, actor, window) if not own(row)
        ]
    return found


def revert_logs(stage: str, progress: dict, run_id: str) -> list[tuple[str, str]]:
    """Each batch's own log, newest first."""
    return [(b["batch"], log) for b in reversed(progress["batches"]) if (log := own_log(stage, b, run_id))]


def revert_refusal(sb, store: Path, folder: Path, run_id: str, stage: str, progress: dict) -> str | None:
    """Why the stage cannot be reverted yet, if it cannot: a batch or a review-queue step with no recorded
    end, a batch whose new logs are not told apart as its own, or for states one of its own writes outside
    the windows the revert reads, or a window still open or holding another writer's write."""
    unfinished = [b for b in progress["batches"] if b["exit"] is None]
    if unfinished:
        return no_recorded_end(folder, store, unfinished[0])
    unended = [queued for queued in progress["queue"] if queued["ended_at"] is None]
    if unended:
        return no_recorded_queue_end(folder, unended[0])
    if stage != STATES:
        # An attempt that failed before writing a log wrote nothing; one that finished wrote its changes.
        lost = [b for b in progress["batches"] if not b["logs"] and b["exit"] == 0]
        if lost:
            return (
                f"Not reverting: the {lost[0]['batch']} batch's applier finished but no new log was found for it, "
                f"so its changes cannot be replayed. Find its log in {store / 'exports'} (rows written as "
                f"{actor_for(run_id)} for this batch's cut), record its path in the batch's logs in "
                f"{folder / APPLY_PROGRESS_FILE} and re-run; until then this refusal repeats"
            )
        mixed = [b for b in progress["batches"] if b["logs"] and own_log(stage, b, run_id) is None]
        if mixed:
            return (
                f"Not reverting: none of the {mixed[0]['batch']} batch's new logs ({', '.join(mixed[0]['logs'])}) "
                f"is its own alone, and replaying another writer's would undo that writer's changes. If one of them "
                f"was written wholly as {actor_for(run_id)} for this batch's cut, leave only it in the batch's logs "
                f"in {folder / APPLY_PROGRESS_FILE} and re-run; until then this refusal repeats and blocks every "
                "batch's revert"
            )
        return None
    unreachable = unreachable_writes(sb, run_id, progress)
    if unreachable:
        return f"Not reverting: {unreachable_text(folder, unreachable)}"
    now = _instant(utc_now_iso())
    still_open = [
        f"the {label} window, to {window[1]}"
        for _, window, label in state_windows(run_id, progress)
        if _instant(window[1]) > now
    ]
    if still_open:
        return f"Not reverting yet: a write could still land in {', '.join(still_open)}; revert once it has closed"
    foreign = foreign_writes(sb, run_id, progress)
    if foreign:
        return (
            "Not reverting: these writes fall in the stage's windows but are not the stage's own, and the "
            "revert would undo them too:\n  " + "\n  ".join(foreign)
        )
    return None


def revert_window(sb, run_id: str, actor: str, window: tuple[str, str], label: str) -> int:
    """revert_team_states over one window, a keyset page at a time; how many teams it put back."""
    changed, after = 0, None
    while True:
        params = {
            "p_applied_by": actor,
            "p_applied_after": window[0],
            "p_applied_before": window[1],
            "p_reverted_by": f"{actor_for(run_id)}:revert",
            "p_after": after,
            "p_batch_size": STATE_REVERT_PAGE,
            "p_dry_run": False,
            "p_revert_reason": f"undo {actor_for(run_id)} states, {label}",
        }
        found = (sb.rpc("revert_team_states", params).execute().data or [{}])[0]
        changed += found.get("rows_changed") or 0
        after = found.get("last_team_id")
        if after is None:
            return changed


def stamp_reverted(sb, run_id: str, stage: str) -> tuple[int, int]:
    """Stamp reverted_at on each ledger row whose team holds its old value again: (stamped, left)."""
    rows = page(
        lambda: (
            sb.table(CHANGES_TABLE)
            .select("id,team_id_master,field,old_value")
            .eq("run_id", run_id)
            .eq("stage", stage)
            .is_("reverted_at", "null")
        ),
        "id",
    )
    teams = fetch_teams(sb, sorted({row["team_id_master"] for row in rows}))
    back = [
        row["id"]
        for row in rows
        if (team := teams.get(row["team_id_master"])) is not None
        and _same(row["field"], team[row["field"]], row["old_value"])
    ]
    stamp = {"reverted_at": utc_now_iso()}
    for ids in batched(back):
        sb.table(CHANGES_TABLE).update(stamp).in_("id", ids).is_("reverted_at", "null").execute()
    return len(back), len(rows) - len(back)


def revert_stage(sb, store: Path, run_id: str, stage: str, outside_window: bool, retry: str) -> None:
    """Undo the stage, newest step first. An open run's revert holds its lease, renewed before each step;
    a closed run's, which no lease can be taken on, holds this machine's file lock alone. Either way the
    window and the other writers are checked again before each step after the first."""
    if read_run(store, run_id)["status"] in OPEN_STATUSES:
        hold = acquire_apply_lock(sb, store, run_id)
    else:
        hold = hold_apply_file(store, run_id)
    with hold as holder:
        folder = stage_dir(store, run_id, stage)
        progress = read_progress(folder)
        check_other_writers()
        lines = [f"## Revert, {utc_now_iso()}", ""]

        def before(step: int, label: str) -> None:
            if step:
                check_window(outside_window)
                check_other_writers()
            keep_lease(sb, run_id, holder, f"the {label} revert was not run", retry)

        try:
            refusal = revert_refusal(sb, store, folder, run_id, stage, progress)
            if refusal:
                lines.append(f"Refused. {refusal}")
                raise SystemExit(refusal)
            if stage == STATES:
                for step, (actor, window, label) in enumerate(reversed(state_windows(run_id, progress))):
                    before(step, label)
                    lines.append(
                        f"- {label}: revert_team_states put back {revert_window(sb, run_id, actor, window, label)}"
                    )
                    print(lines[-1][2:])
            else:
                for step, (label, log) in enumerate(revert_logs(stage, progress, run_id)):
                    before(step, label)
                    output = folder / LOGS / f"revert_{label}_{Path(log).stem}.log"
                    code = run_step(revert_command(stage, log, execute=True), output)
                    lines.append(f"- {label}: {APPLIERS[stage]} --revert {log} exited {code}; see {output}")
                    print(lines[-1][2:])
                    if code != 0:
                        raise SystemExit(
                            f"Stopped: the {label} revert exited {code}; see {output}:\n    {_tail(output)}"
                        )
            stamped, left = stamp_reverted(sb, run_id, stage)
            lines.append(
                f"Stamped reverted_at on {stamped} ledger row(s); {left} whose team is not back at its old value."
            )
            print(lines[-1])
            late = foreign_writes(sb, run_id, progress) if stage == STATES else []
            if late:
                lines.append("Undone with them, though not the stage's own:\n  " + "\n  ".join(late))
                raise SystemExit(
                    "Reverted, but these writes landed in the stage's windows after the check and were undone "
                    "with them; put them back by hand:\n  " + "\n  ".join(late)
                )
        except (APIError, httpx.HTTPError) as exc:
            lines.append(f"Stopped: {exc}")
            raise SystemExit(refused(f"Could not finish reverting {stage}", exc, retry)) from None
        finally:
            with (folder / REVERT_FILE).open("a", encoding="utf-8") as record:
                record.write("\n".join(lines) + "\n\n")


def dry_run_revert(sb, store: Path, run_id: str, stage: str) -> None:
    folder = stage_dir(store, run_id, stage)
    progress = read_progress(folder)
    print(f"DRY RUN -- would revert {stage} for run {run_id}, newest batch first:")
    if stage == STATES:
        for actor, window, label in reversed(state_windows(run_id, progress)):
            print(f"  {label}: revert_team_states('{actor}', '{window[0]}', '{window[1]}', ...)")
    else:
        for label, log in revert_logs(stage, progress, run_id):
            print(f"  {label}: python {subprocess.list2cmdline(revert_command(stage, log, execute=False))}")
    refusal = revert_refusal(sb, store, folder, run_id, stage, progress)
    if refusal:
        print(f"It would refuse. {refusal}")
        return
    print("Then it stamps reverted_at on each ledger row whose team holds its old value again.")
    print("Re-run with --execute to revert it.")


# --- the dry run ---------------------------------------------------------------------------------


def dry_run(sb, run_id: str, stage: str, folder: Path, marker: dict) -> None:
    rows = read_json(folder / DECISIONS_FILE)
    check_ledger(sb)
    planned = plan_decisions(sb, stage, rows)
    replacing = sum(1 for *_, current in planned if current)
    print(f"DRY RUN -- {stage} for run {run_id}, page run {marker['run']}.")
    print(
        f"Would record {len(planned)} of {len(rows)} decided card(s) in {DECISIONS_TABLE}, {replacing} of them "
        "replacing an earlier decision; the rest are recorded already:"
    )
    for row, _, current in planned:
        replaces = f"  (replaces {current['decision']} from {current['source']})" if current else ""
        print(f"    {row['decision']:<10} {row['team_name']!r}: {row['old_value']!r} -> {row['new_value']!r}{replaces}")
    changes = vetted_changes(folder, stage)
    if changes:
        held = ", before the hold script's split" if stage == STATES else ""
        rest = ", then the rest" if len(changes) > PILOT_ROWS else ""
        print(f"Would apply {len(changes)} change(s){held}: a pilot of {min(len(changes), PILOT_ROWS)}{rest}:")
        if stage == STATES:
            print(f"  python {subprocess.list2cmdline(hold_command(folder))}")
        for name, part in pilot_and_rest(changes):
            print(f"  {name}: {APPLIERS[stage]} over {folder / cut_name(stage, name)}    ({len(part)} rows)")
        print(f"  each batch verified from the database and ledgered in {CHANGES_TABLE}")
    else:
        print("Nothing to apply: no card was chosen Apply.")
    for plan in queue_plans(sb, folder, rows, marker["collected_at"]) if stage == STATES else []:
        card = plan["card"]
        print(f"  queued {card['decision']:<10} {card['team_name']!r} to {card['new_value']}: {describe_plan(plan)}")
    print(f"Then it writes {folder / APPLY_MARKER}.")
    print("Re-run with --execute to apply it, inside the apply window or with --outside-window.")


# --- the command ---------------------------------------------------------------------------------


def retry_command(args: argparse.Namespace, store: Path, execute: bool) -> str:
    """The command that reads where things stand after a lost answer, in the mode this one ran: a dry
    run's is a dry run."""
    command = [APPLY_SCRIPT, "--run", args.run, "--stage", args.stage]
    command += [*(["--revert"] if args.revert else []), *(["--execute"] if execute else [])]
    command += [*(["--outside-window"] if args.outside_window else []), "--store", str(store)]
    return f"python {subprocess.list2cmdline(command)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True, help="The run id, e.g. 2026-10-14-nv")
    parser.add_argument("--stage", required=True, choices=PROPOSED_STAGES)
    parser.add_argument("--revert", action="store_true", help="Undo the stage's applied batches")
    parser.add_argument("--execute", action="store_true", help="Write to the database (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Force a dry run; wins over --execute")
    parser.add_argument("--outside-window", action="store_true", help="Run --execute outside the apply window")
    parser.add_argument(
        "--store",
        type=Path,
        help="The run store, absolute (default: PITCHRANK_CLEANUP_DIR, else ~/pitchrank-cleanup-runs)",
    )
    args = parser.parse_args()
    execute = resolve_execute(args.execute, args.dry_run)
    what = f"{'revert' if args.revert else 'apply'} the {args.stage} stage of {args.run}"
    try:
        store = store_dir(args.store)
        if args.revert:
            read_run(store, args.run)
            if not (stage_dir(store, args.run, args.stage) / APPLY_PROGRESS_FILE).exists():
                raise ValueError(f"nothing of it was applied: there is no {APPLY_PROGRESS_FILE}")
        else:
            folder, marker = open_stage(store, args.run, args.stage)
        if execute:
            check_window(args.outside_window)
        retry = retry_command(args, store, execute)
        sb = get_client()
        if args.revert and execute:
            revert_stage(sb, store, args.run, args.stage, args.outside_window, retry)
        elif args.revert:
            dry_run_revert(sb, store, args.run, args.stage)
        elif execute:
            print(f"Wrote {apply_stage(sb, store, args.run, args.stage, args.outside_window, retry)}")
        else:
            dry_run(sb, args.run, args.stage, folder, marker)
    except ApplyLockError as exc:
        raise SystemExit(f"Cannot {what}: {exc}") from None
    except (APIError, httpx.HTTPError) as exc:
        raise SystemExit(refused(f"Cannot {what}", exc, retry_command(args, store, execute))) from None
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Cannot {what}: {exc}") from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
