#!/usr/bin/env python3
"""One tick of the weekly team cleanup's autopilot: take the open run as far as it can go now, then stop.

Run it hourly. Each tick reads the run store and team_cleanup_runs, does what is due in order, and leaves
a stage at the first step that has to wait. A dry run (the default, or --dry-run) prints what it would do
and writes nothing to the run or the database; --execute does it.

  no open run   from Wednesday 11:00 Arizona until the week's review deadline, propose this week's
                run over every team (propose_week.py --states ALL), unless it already exists; with
                --pin-code the checkout first moves to origin/main, and the run keeps that code
  proposing     propose again, which resumes where the last attempt stopped
  reviewing     each stage: build and publish its page (clubs once review_clubs.py has reviewed its guesses,
                states once review_states.py has reviewed its changes, merges once review_merges.py has
                reviewed its pairs, which can take hours), then collect and
                apply its automatic lane
                once every page is up: email the owner that the review is ready
                at the review deadline (config/team_cleanup.json), mark the review done for the owner,
                so the choices made stand and the rest come back next week
                once the review is done: collect each stage's choices and apply them
                once a lane has applied: undo it when the owner asked to on the page
                once every stage is finished and no undo waits: close the run and email the owner a summary

An apply waits for the apply window, whose end the review deadline must fall before, so the choices it
marks done apply that week. A step that exits 75 (another writer at work, the run held by another
process) waits for a later tick; a step that fails is retried by the next. While a step is due and
blocked for a day, the week's start included, the owner is emailed once. A failed move to origin/main
blocks the week's start rather than proposing on older code. It never abandons a run. While
<store>/autopilot.paused exists it does nothing. <run>/autopilot.json keeps the commit the run was
proposed with, what has been emailed, and since when and why the run has been blocked. The owner's
address is CLEANUP_OWNER_EMAIL; without it, or without RESEND_API_KEY, nothing is emailed and each
tick tries again.

    python scripts/team_cleanup/advance.py
    python scripts/team_cleanup/advance.py --execute
    python scripts/team_cleanup/advance.py --execute --pin-code   (the scheduled task, from C:\\pitchrank-weekly)

The scheduled task is registered once by scripts/team_cleanup/windows/register_team_cleanup.ps1.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import httpx
from postgrest.exceptions import APIError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.find_cross_provider_duplicates import get_client  # noqa: E402
from scripts.team_cleanup.apply_stage import (  # noqa: E402
    ARIZONA,
    WEEK_MINUTES,
    Window,
    _after_propose,
    _bound,
    _instant,
    _tail,
    in_window,
    lane_flags,
    load_window,
)
from scripts.team_cleanup.decisions import TABLE_MISSING, resolve_execute  # noqa: E402
from scripts.team_cleanup.end_run import unfinished  # noqa: E402
from scripts.team_cleanup.propose_week import ALL, PROPOSED_STAGES, REVIEWERS, run_id_for, run_step  # noqa: E402
from scripts.team_cleanup.run_store import (  # noqa: E402
    APPLY_MARKER,
    AUTO,
    AUTOPILOT_FILE,
    BUSY,
    CLEANUP_CONFIG,
    COLLECTED_MARKER,
    DONE,
    LANE_CARDS,
    MANIFEST_FILE,
    OPEN_STATUSES,
    OWNER,
    REVIEW,
    REVIEW_DIR,
    RUN_FILE,
    RUNS_TABLE,
    SHARED_STEPS,
    _utc_stamp,
    lane_dir,
    lane_name,
    list_runs,
    refused,
    run_dir,
    stage_dir,
    stage_progress,
    store_dir,
)
from src.tournaments.storage._file_lock import FileLockError, _acquire_file_lock  # noqa: E402
from src.tournaments.storage._io import read_json, write_json  # noqa: E402
from src.utils.resend_email import send_email  # noqa: E402

PAUSE_FILE = "autopilot.paused"
LOCK_FILE = "advance.lock"
OWNER_EMAIL = "CLEANUP_OWNER_EMAIL"
REVIEW_URL = "https://www.pitchrank.io/mission-control/cleanup"
STUCK_AFTER = timedelta(days=1)
MAX_STEPS = 50

PROPOSE = "scripts/team_cleanup/propose_week.py"
PAGES = "scripts/team_cleanup/pages.py"
COLLECT = "scripts/team_cleanup/collect.py"
APPLY = "scripts/team_cleanup/apply_stage.py"
END_RUN = "scripts/team_cleanup/end_run.py"
STATUS_COMMAND = "python scripts/team_cleanup/advance.py"
REQUESTS_TABLE = "team_cleanup_requests"


@dataclass(frozen=True)
class Action:
    what: str
    command: list[str]
    stage: str | None = None


def week_start(now: datetime) -> datetime:
    """The latest Wednesday 11:00 Arizona at or before ``now``, when a week's run is proposed."""
    local = now.astimezone(ARIZONA)
    since = _after_propose(local.weekday(), local.hour * 60 + local.minute)
    return (local - timedelta(minutes=since)).replace(second=0, microsecond=0)


def run_date(run_id: str) -> date:
    return date.fromisoformat(run_id[:10])


def load_deadline(path: Path = CLEANUP_CONFIG) -> int:
    """The review deadline, as minutes after the week's Wednesday propose, refused unless it falls before
    the apply window ends, so the choices it marks done still apply that week."""
    try:
        minutes, text = _bound(json.loads(path.read_text(encoding="utf-8"))["review_deadline"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"{path} holds no readable review_deadline ({type(exc).__name__}: {exc})") from None
    window = load_window(path)
    if minutes >= window.end:
        raise ValueError(
            f"{path}'s review_deadline, {text}, must fall before the apply window ends ({window.text}), "
            "so the choices it marks done apply that week; widen apply_window or move the deadline earlier"
        )
    return minutes


def deadline_of(run_id: str, minutes: int) -> datetime:
    """The first review deadline on or after the run's date: that week's for a run proposed on its
    Wednesday or by hand later in the week."""
    day = datetime.combine(run_date(run_id), time(0, 0), ARIZONA)
    return day + timedelta(minutes=(minutes - _after_propose(day.weekday(), 0)) % WEEK_MINUTES)


def open_stages(run: dict) -> list[str]:
    """The run's proposed stages that run.json does not note as passed over this week."""
    return [stage for stage in PROPOSED_STAGES if not (run.get("stages") or {}).get(stage)]


def read_state(store: Path, run_id: str) -> dict:
    try:
        return read_json(run_dir(store, run_id) / AUTOPILOT_FILE)
    except FileNotFoundError:
        return {}


def write_state(store: Path, run_id: str, state: dict) -> None:
    write_json(run_dir(store, run_id) / AUTOPILOT_FILE, state, indent=1)


def code_commit() -> str | None:
    try:
        found = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if found.returncode != 0:
        return None
    return found.stdout.strip() or None


def pin_code() -> str | None:
    """Move this checkout to origin/main; why it could not, if so."""
    for command in (["git", "fetch", "-q", "origin"], ["git", "checkout", "-q", "--detach", "origin/main"]):
        try:
            done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as exc:
            return f"{' '.join(command)}: {exc}"
        if done.returncode != 0:
            return f"{' '.join(command)} exited {done.returncode}: {done.stderr.strip()[:300]}"
    return None


class Tick:
    """One tick's work against one store. ``deadline`` is the review deadline in minutes after the week's
    propose."""

    def __init__(
        self, sb, store: Path, now: datetime, execute: bool, *, window: Window, deadline: int, pin: bool = False
    ):
        self.sb, self.store, self.now, self.execute = sb, store, now, execute
        self.window, self.deadline_minutes, self.pin = window, deadline, pin
        self.failed = False
        self.blocked: list[str] = []
        self.steps = 0
        self.last_log: Path | None = None
        self.reviewed: set[tuple[str, str]] = set()

    # --- running a step ------------------------------------------------------------------------

    def run(self, run_id: str, action: Action) -> int | None:
        """The step's exit code, or None on a dry run."""
        if not self.execute:
            print(f"DRY RUN -- would {action.what}: python {subprocess.list2cmdline(action.command)}")
            return None
        self.steps += 1
        name = f"{self.now:%Y%m%dT%H%M%SZ}-{self.steps:02d}-{Path(action.command[0]).stem}.log"
        log = self.store / "logs" / "autopilot" / run_id / name
        code = run_step(action.command, log)
        self.last_log = log
        if code == 0:
            print(f"{action.what}: done")
        elif code == BUSY:
            self.blocked.append(f"{action.what} waits ({_tail(log, 1) or 'no output'})")
            print(f"{action.what}: waits for a later tick; see {log}")
        else:
            self.failed = True
            self.blocked.append(f"{action.what} failed (exit {code}; see {log})")
            print(f"{action.what}: failed with exit {code}; see {log}")
        return code

    # --- emails --------------------------------------------------------------------------------

    def email(self, subject: str, body: str) -> bool:
        to = os.environ.get(OWNER_EMAIL, "").strip()
        if not self.execute:
            print(f"DRY RUN -- would email the owner: {subject}")
            return False
        if not to:
            print(f"{OWNER_EMAIL} is not set, so the owner was not emailed: {subject}")
            return False
        sent = send_email(to, subject, body)
        print(f"Emailed the owner: {subject}" if sent else f"Could not email the owner: {subject}")
        return sent

    def email_once(self, run_id: str, state: dict, key: str, subject: str, body: str) -> None:
        if (state.get("emailed") or {}).get(key):
            return
        if self.email(subject, body):
            state.setdefault("emailed", {})[key] = _utc_stamp(self.now)
            write_state(self.store, run_id, state)

    # --- a run's life ----------------------------------------------------------------------------

    def tick(self) -> int:
        runs = list_runs(self.store)
        # The page offers to undo the last finished run's changes, which apply and close in one tick; an undo
        # filed while a newer run was closing may name the run before it, so every finished run with one waiting
        # is taken.
        finished = {run["run_id"]: run for run in runs if run["status"] == DONE}
        for run_id in self.waiting_runs():
            if run_id in finished:
                self.undo(run_id, open_stages(finished[run_id]))
        run = next((run for run in runs if run["status"] in OPEN_STATUSES), None)
        if run is None:
            self.summarize_closed(runs)
            self.start_week()
        elif run["status"] == "proposing":
            self.propose(run["run_id"], run["scope"]["states"])
        elif run["status"] == "reviewing":
            self.review(run)
        else:
            print(f"Run {run['run_id']} is {run['status']}, which this tick does not move.")
        return 1 if self.failed else 0

    def start_week(self) -> None:
        run_id = run_id_for(week_start(self.now).date(), [ALL])
        if (run_dir(self.store, run_id) / RUN_FILE).exists():
            print(f"This week's run {run_id} has already run; nothing to do until next Wednesday 11:00 Arizona.")
            return
        if self.now >= self.deadline(run_id):
            print(f"This week's review deadline has passed, so run {run_id} waits for next Wednesday 11:00 Arizona.")
            return
        # A run keeps the code it was proposed with: the checkout moves only here, as a new week starts.
        if self.pin and not self.execute:
            print("DRY RUN -- would move this checkout to origin/main")
        elif self.pin:
            problem = pin_code()
            if problem:
                self.failed = True
                self.blocked.append(f"moving the checkout to origin/main failed, so run {run_id} waits ({problem})")
                print(f"Not proposing run {run_id} on older code: {problem}")
                self.settle_blockage(run_id, read_state(self.store, run_id))
                return
            print("Moved the checkout to origin/main.")
        self.propose(run_id, [ALL])

    def propose(self, run_id: str, states: list[str]) -> None:
        command = [PROPOSE, "--states", ",".join(states), "--date", run_id[:10], "--store", str(self.store)]
        if self.run(run_id, Action(f"propose run {run_id}", command)) is None:
            return
        state = read_state(self.store, run_id)
        if "code" not in state and (run_dir(self.store, run_id) / RUN_FILE).exists():
            state["code"] = code_commit()
        self.settle_blockage(run_id, state)

    def review(self, run: dict) -> None:
        run_id = run["run_id"]
        state = read_state(self.store, run_id)
        stages = open_stages(run)
        done = self.review_done(run_id)
        window_open = in_window(self.window, self.now)
        held: set[str] = set()
        while (action := self.due(run_id, stages, done, window_open, held)) is not None:
            code = self.run(run_id, action)
            if code != 0:
                held.add(action.stage)
        if all(self.page_up(run_id, stage) for stage in stages):
            self.email_once(run_id, state, "ready", *ready_email(self.store, run_id, stages, self.deadline(run_id)))
        undo_waits = self.undo(run_id, stages)
        if not unfinished(self.store, run) and not undo_waits:
            close = [END_RUN, "--run", run_id, "--done", "--execute", "--store", str(self.store)]
            if self.run(run_id, Action(f"close run {run_id}", close)) == 0:
                summary = summary_email(self.store, run_id, stages, self.undone(run_id))
                self.email_once(run_id, state, "closed", *summary)
                return
        self.settle_blockage(run_id, state)

    def due(self, run_id: str, stages: list[str], done: bool, window_open: bool, held: set[str]) -> Action | None:
        """The next step to run: every page first, then the automatic lanes, then the owner's choices once the
        review is done. A stage held this tick, waiting or failed, is passed over."""
        if self.steps >= MAX_STEPS:
            return None
        progress = {stage: stage_progress(self.store, run_id, stage) for stage in stages if stage not in held}

        def step(what: str, script: str, stage: str, *flags: str) -> Action:
            return Action(what, [script, "--run", run_id, "--stage", stage, *flags, "--store", str(self.store)], stage)

        for stage, p in progress.items():
            if stage in REVIEWERS and p.next_step is not None and self.review_due(run_id, stage, p.next_step.name):
                # A review can run for hours, so a tick runs each stage's at most once, even when it reports
                # done and leaves a slice waiting.
                if (run_id, stage) in self.reviewed:
                    continue
                self.reviewed.add((run_id, stage))
                script, what = REVIEWERS[stage]
                return step(f"review the {stage} {what}", script, stage, "--execute")
            if p.next_step is not None and p.next_step.name == "page":
                return step(f"build and publish the {stage} page", PAGES, stage, "--publish", "--execute")
        for stage, p in progress.items():
            if p.auto_step is not None and p.auto_step.name == "collect":
                return step(f"collect the {stage} automatic lane", COLLECT, stage, "--lane", AUTO)
            if p.auto_step is not None and p.auto_step.name == "apply" and window_open:
                return step(f"apply the {stage} automatic lane", APPLY, stage, "--lane", AUTO, "--execute")
        if not done:
            return None
        for stage, p in progress.items():
            if p.next_step is not None and p.next_step.name == "collect":
                return step(f"collect the owner's {stage} choices", COLLECT, stage, "--from-db")
            if p.next_step is not None and p.next_step.name == "apply" and window_open:
                return step(f"apply the owner's {stage} choices", APPLY, stage, "--execute")
        return None

    def review_due(self, run_id: str, stage: str, next_step: str) -> bool:
        """Whether the stage's review runs next: its slices wait for reviewers, or it was never queued and the
        page is next."""
        queued = (stage_dir(self.store, run_id, stage) / REVIEW_DIR).exists()
        return next_step == REVIEW.name or (next_step == "page" and not queued)

    def page_up(self, run_id: str, stage: str) -> bool:
        step = stage_progress(self.store, run_id, stage).next_step
        return step is None or step.name not in SHARED_STEPS

    def undo(self, run_id: str, stages: list[str]) -> bool:
        """Run each undo the owner asked for on the page once its lane has applied, recording how it went;
        whether one still waits, which holds the run open so no undo is left behind by the close."""
        try:
            requests = (
                self.sb.table(REQUESTS_TABLE)
                .select("id,stage,lane")
                .eq("run_id", run_id)
                .eq("status", "pending")
                .order("requested_at")
                .execute()
                .data
            )
        except (APIError, httpx.HTTPError) as exc:
            if isinstance(exc, APIError) and exc.code == TABLE_MISSING:
                # Before its migration is applied no undo can have been asked for, so nothing holds the run.
                print(f"{REQUESTS_TABLE} does not exist yet, so no undo waits.")
                return False
            self.blocked_by(refused(f"Reading run {run_id}'s undo requests from {REQUESTS_TABLE}", exc, STATUS_COMMAND))
            return True
        waits = False
        for request in requests:
            stage, lane = request["stage"], request["lane"]
            if stage not in stages:
                self.settle(request, "failed", f"the {stage} stage was not run this week, so nothing of it applied")
                continue
            if not (lane_dir(self.store, run_id, stage, lane) / APPLY_MARKER).exists():
                progress = stage_progress(self.store, run_id, stage)
                if (progress.auto_step if lane == AUTO else progress.next_step) is None:
                    self.settle(request, "failed", f"nothing was sent to {lane_name(stage, lane)}, so nothing to undo")
                else:
                    waits = True
                    print(f"The undo of {lane_name(stage, lane)} waits until it has applied.")
                continue
            command = [APPLY, "--run", run_id, "--stage", stage, *lane_flags(lane), "--revert", "--execute"]
            code = self.run(run_id, Action(f"undo {lane_name(stage, lane)}", [*command, "--store", str(self.store)]))
            if code is None or code == BUSY:
                waits = True
            else:
                self.settle(request, "done" if code == 0 else "failed", _tail(self.last_log, 12) or "no output")
        return waits

    def settle(self, request: dict, status: str, result: str) -> None:
        """Record an undo request as handled, unless something else already has."""
        if not self.execute:
            print(f"DRY RUN -- would record the undo of {request['stage']} {request['lane']} as {status}: {result}")
            return
        try:
            self.sb.table(REQUESTS_TABLE).update(
                {"status": status, "handled_at": _utc_stamp(self.now), "result": result[:2000]}
            ).eq("id", request["id"]).eq("status", "pending").execute()
        except (APIError, httpx.HTTPError) as exc:
            self.blocked_by(refused(f"Recording an undo request in {REQUESTS_TABLE}", exc, STATUS_COMMAND))

    def waiting_runs(self) -> list[str]:
        """The runs an undo request still waits on; none when the requests cannot be read."""
        try:
            rows = self.sb.table(REQUESTS_TABLE).select("run_id").eq("status", "pending").execute().data
        except (APIError, httpx.HTTPError):
            return []
        return sorted({r["run_id"] for r in rows})

    def undone(self, run_id: str) -> list[str]:
        """How each undo the owner asked for on the run went, for the summary; none when they cannot be read."""
        try:
            rows = (
                self.sb.table(REQUESTS_TABLE)
                .select("stage,lane,status,result")
                .eq("run_id", run_id)
                .order("requested_at")
                .execute()
                .data
            )
        except (APIError, httpx.HTTPError):
            return []
        return [
            f"Undo of {lane_name(r['stage'], r['lane'])}: {r['status']}"
            + (f" ({(r['result'] or '').strip()})" if r["status"] == "failed" else "")
            for r in rows
        ]

    def blocked_by(self, problem: str) -> None:
        self.failed = True
        self.blocked.append(problem)
        print(problem)

    def deadline(self, run_id: str) -> datetime:
        return deadline_of(run_id, self.deadline_minutes)

    def review_done(self, run_id: str) -> bool:
        """Whether the owner's review is marked done, marking it at the deadline for them."""
        try:
            rows = self.sb.table(RUNS_TABLE).select("owner_done_at").eq("run_id", run_id).execute().data
            if rows and rows[0]["owner_done_at"]:
                return True
            if self.now < self.deadline(run_id):
                return False
            if not self.execute:
                print(f"DRY RUN -- would mark run {run_id}'s review done at the deadline")
                return True
            marked = (
                self.sb.table(RUNS_TABLE)
                .update({"owner_done_at": _utc_stamp(self.now), "owner_done_by": "deadline"})
                .eq("run_id", run_id)
                .eq("status", "reviewing")
                .is_("owner_done_at", "null")
                .execute()
                .data
            )
        except (APIError, httpx.HTTPError) as exc:
            self.blocked_by(refused(f"Reading or marking run {run_id}'s review in {RUNS_TABLE}", exc, STATUS_COMMAND))
            return False
        if marked:
            print(f"The review deadline passed, so run {run_id}'s review is marked done.")
        return True

    def settle_blockage(self, run_id: str, state: dict) -> None:
        """Keep since when a due step has been blocked, and email the owner once when that passes a day."""
        if not self.execute:
            return
        if not self.blocked:
            state.pop("blocked_since", None)
            state.pop("problem", None)
            write_state(self.store, run_id, state)
            return
        since = state.setdefault("blocked_since", _utc_stamp(self.now))
        state["problem"] = "; ".join(self.blocked)
        write_state(self.store, run_id, state)
        if self.now - _instant(since) >= STUCK_AFTER:
            body = f"<p>Run {html.escape(run_id)} has been waiting since {html.escape(since)}:</p>"
            body += "".join(f"<p>{html.escape(line)}</p>" for line in self.blocked)
            self.email_once(
                run_id, state, f"stuck {since}", f"PitchRank cleanup {run_id} has been stuck for a day", body
            )

    def summarize_closed(self, runs: list[dict]) -> None:
        """Email the summary of the latest run once it is done, if the autopilot has notes on it and no summary
        went out, as when the email failed at the close."""
        if not runs or runs[0]["status"] != DONE:
            return
        run_id = runs[0]["run_id"]
        state = read_state(self.store, run_id)
        if state:
            summary = summary_email(self.store, run_id, open_stages(runs[0]), self.undone(run_id))
            self.email_once(run_id, state, "closed", *summary)


def _counts(store: Path, run_id: str, stage: str) -> tuple[int, int]:
    """The stage page's own cards and its automatic changes."""
    try:
        manifest = read_json(stage_dir(store, run_id, stage) / MANIFEST_FILE)
    except FileNotFoundError:
        return 0, 0
    return len(manifest.get(LANE_CARDS[OWNER], {})), len(manifest.get(LANE_CARDS[AUTO], {}))


def ready_email(store: Path, run_id: str, stages: list[str], deadline: datetime) -> tuple[str, str]:
    counts = {stage: _counts(store, run_id, stage) for stage in stages}
    cards, auto = sum(c for c, _ in counts.values()), sum(a for _, a in counts.values())
    when = _arizona_time(deadline)
    rows = "".join(
        f"<li>{html.escape(stage)}: {c} to decide, {a} applied automatically</li>" for stage, (c, a) in counts.items()
    )
    body = (
        f"<p>This week's team cleanup ({html.escape(run_id)}) is ready: {cards} change(s) to decide and {auto} "
        f"the evidence settles, which apply on their own.</p><ul>{rows}</ul>"
        f'<p><a href="{REVIEW_URL}">Open the review page</a>. Mark it done when you have finished; at '
        f"{html.escape(when)} Arizona it is marked done for you, and anything undecided comes back next week.</p>"
    )
    return f"PitchRank cleanup: {cards} change(s) to review", body


def _arizona_time(moment: datetime) -> str:
    local = moment.astimezone(ARIZONA)
    return f"{local:%A} {local.hour % 12 or 12}:{local:%M} {'AM' if local.hour < 12 else 'PM'}"


def summary_email(store: Path, run_id: str, stages: list[str], undone: list[str] = ()) -> tuple[str, str]:
    rows = []
    for stage in stages:
        owner = _collected(stage_dir(store, run_id, stage) / COLLECTED_MARKER)
        auto = _collected(stage_dir(store, run_id, stage) / AUTO / COLLECTED_MARKER)
        # A club guess the review found wrong, and a pair it found to be two teams, is settled too, as
        # Don't apply.
        settled = auto.get("apply", 0) + auto.get("dont_apply", 0)
        rows.append(
            f"<li>{html.escape(stage)}: {owner.get('apply', 0)} you chose to apply, {settled} the "
            f"evidence settled, {owner.get('undecided', 0)} left for next week</li>"
        )
    body = f"<p>This week's team cleanup ({html.escape(run_id)}) is finished.</p><ul>{''.join(rows)}</ul>"
    if undone:
        body += "<p>Undo requests:</p><ul>" + "".join(f"<li>{html.escape(line)}</li>" for line in undone) + "</ul>"
    return f"PitchRank cleanup {run_id} is finished", body


def _collected(marker: Path) -> dict:
    try:
        return read_json(marker).get("counts", {})
    except (FileNotFoundError, AttributeError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--store",
        type=Path,
        help="The run store, absolute (default: PITCHRANK_CLEANUP_DIR, else ~/pitchrank-cleanup-runs)",
    )
    parser.add_argument("--execute", action="store_true", help="Do what is due (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Force a dry run; wins over --execute")
    parser.add_argument(
        "--pin-code",
        action="store_true",
        help="Move this checkout to origin/main before proposing a new week's run (the scheduled task's checkout)",
    )
    args = parser.parse_args()
    try:
        store = store_dir(args.store)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if (store / PAUSE_FILE).exists():
        print(f"The autopilot is paused: {store / PAUSE_FILE} exists.")
        return 0
    try:
        window, deadline = load_window(), load_deadline()
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    execute = resolve_execute(args.execute, args.dry_run)
    store.mkdir(parents=True, exist_ok=True)
    try:
        with _acquire_file_lock(store / LOCK_FILE, timeout=0.0):
            now = datetime.now(timezone.utc)
            tick = Tick(get_client(), store, now, execute, window=window, deadline=deadline, pin=args.pin_code)
            return tick.tick()
    except FileLockError:
        print(f"Another tick holds {store / LOCK_FILE}; this one leaves the run to it.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
