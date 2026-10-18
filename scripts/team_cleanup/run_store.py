"""Where a weekly team-cleanup run keeps its files, how far each stage has got, and the apply lock.

The store sits outside the repo, so removing a worktree takes no undo log with it:

  <store>/exports/                 every applier's plans and logs (their --exports-dir)
  <store>/inputs/abbreviation_logs/<GitHub run id>.log
                                   saved logs of update-missing-club-and-state.yml runs, which the
                                   club scan reads
  <store>/propose.lock             held while a week is being proposed
  <store>/runs/<run_id>/run.json   scope, budgets, status, stage overrides, timestamps
  <store>/runs/<run_id>/write_guard.json
                                   how many teams changed while the stages proposed, and each
                                   stage's stale count; written once each stage has proposed or is
                                   skill_stale, and until then write_guard_before.json holds the
                                   opening snapshot
  <store>/runs/<run_id>/<stage>/   that stage's files and logs/, with one marker per finished step
  <store>/runs/<run_id>/<stage>/auto/
                                   the stage's automatic lane, when its page settled changes with no
                                   card
  <store>/health/                  weekly reports

A stage's progress is read back from its markers rather than stored, so a run killed mid-stage
resumes at the first step whose marker is missing:

  preflight.json   the stage's skill self-check passed
  propose_done     its proposals.json is written, one row per proposed change. stale.json is
                   written beside it when write_guard.json is, listing the proposals whose
                   proposed field or liveness something else changed meanwhile
  review/          every <name>.json there has a <name>_review.json that copies it
  page.json        the owner's review page is built: page.html, and page.manifest.json, which
                   names the proposal behind each card
  collected.json   the owner's choices are collected into the stage applier's input: vetted.csv or
                   vetted.json (absent when nothing was chosen to apply), and decisions.json,
                   every decided card for the applier to record
  RECORD.md        the apply ran and was verified

An apply keeps its own record beside them, since one may stop part way through and its batches
stay written:

  apply.json       the cut files, the batches run and the review-queue cards settled, which a
                   re-run resumes from and --revert undoes
  pilot.*, rest.*  the cut files, in the applier's input format; states also keep the hold
                   script's safe.json and held.json
  REVERT.md        each --revert's account, appended

The owner acts twice: deciding on the page, before collected.json, and triggering the apply,
before RECORD.md.

A page that sends changes the evidence already settles to the automatic lane (page.json's `auto`)
gives that lane its own collected.json, vetted file, decisions.json, apply record and RECORD.md in
auto/, read from the stage folder's page and inputs; the owner triggers its apply too. The stage is
finished once both lanes are.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import re
import socket
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from postgrest.exceptions import APIError

from scripts.team_cleanup.decisions import MERGES, TABLE_MISSING
from src.tournaments.storage._file_lock import FileLockError, _acquire_file_lock
from src.tournaments.storage._io import read_json, utc_now_iso, write_json

logger = logging.getLogger(__name__)

CLEANUP_CONFIG = Path(__file__).resolve().parents[2] / "config" / "team_cleanup.json"
STORE_ENV = "PITCHRANK_CLEANUP_DIR"
RUNS_TABLE = "team_cleanup_runs"
RUN_FILE = "run.json"
APPLY_LOCK_FILE = "apply.lock"
REVIEW_DIR = "review"
REVIEW_SUFFIX = "_review.json"
BAD_SUFFIX = ".bad"
LEASE_HOURS = 6
PERMISSION_DENIED = "42501"

STAGES = ("reconcile", "clubs", "states", "ages", MERGES)
# The owner's choices on the page, and the changes the page settled with no card, each under its key in
# page.manifest.json.
OWNER, AUTO = "owner", "auto"
LANES = (OWNER, AUTO)
LANE_CARDS = {OWNER: "cards", AUTO: AUTO}
# sysexits' EX_TEMPFAIL: the command may succeed if run again later.
BUSY = 75
OPEN_STATUSES = ("proposing", "reviewing", "applying", "second_lap")
DONE, ABANDONED = "done", "abandoned"
STATUSES = (*OPEN_STATUSES, DONE, ABANDONED)
# Prefixes of run.json's note on a stage that has nothing to apply this week. A `failed:` note is not one: the
# stage is kept open to be retried.
SKIPPED_STAGE_NOTES = ("not run", "skill_stale")

# A review copies these from each proposal it judges, so a reviewer that skipped, reordered or
# invented a row is caught before its verdicts reach a page.
MERGE_REVIEW_KEYS = ("merge_id", "keep_id", "merge_name", "keep_name")
CHANGE_REVIEW_KEYS = ("team_id_master", "field", "old_value", "new_value")

_RUN_ID = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True)
class Step:
    name: str
    marker: str | None
    next_action: str


PREFLIGHT_MARKER = "preflight.json"
PROPOSE_MARKER = "propose_done"
PROPOSALS_FILE = "proposals.json"
STALE_FILE = "stale.json"
PAGE_MARKER = "page.json"
MANIFEST_FILE = "page.manifest.json"
COLLECTED_MARKER = "collected.json"
APPLY_MARKER = "RECORD.md"
APPLY_PROGRESS_FILE = "apply.json"
# The keys read_progress requires of each batch attempt, review-queue step and settled card in apply.json.
BATCH_KEYS = ("batch", "cut", "command", "output", "started_at", "ended_at", "exit", "logs")
QUEUE_STEP_KEYS = ("started_at", "ended_at", "cards", "reviews")
CARD_KEYS = ("team_id_master", "team_name", "state", "decision", "outcome", "review_id")
REVIEW = Step("review", None, "review the queued proposals")
APPLY = Step("apply", APPLY_MARKER, "the owner runs the apply")
STEPS = (
    Step("preflight", PREFLIGHT_MARKER, "run the stage's skill self-check"),
    Step("propose", PROPOSE_MARKER, "write the stage's proposals"),
    REVIEW,
    Step("page", PAGE_MARKER, "build the owner's review page"),
    Step("collect", COLLECTED_MARKER, "the owner decides on the page, then collect the choices"),
    APPLY,
)
# The owner's steps up to the page, which the automatic lane is built from too.
SHARED_STEPS = ("preflight", "propose", "review", "page")
AUTO_COLLECT = Step("collect", COLLECTED_MARKER, "collect the automatic lane")
AUTO_APPLY = Step("apply", APPLY_MARKER, "the owner runs the automatic lane's apply")


@dataclass(frozen=True)
class StageProgress:
    stage: str
    next_step: Step | None
    queued: tuple[str, ...] = ()
    set_aside: tuple[str, ...] = ()
    auto_step: Step | None = None

    @property
    def finished(self) -> bool:
        return self.next_step is None and self.auto_step is None


class ApplyLockError(RuntimeError):
    """The run's apply lock is held (its file on this machine, or another holder's live lease), or the run
    cannot be leased."""


class RunBusy(ApplyLockError):
    """Another process holds the run for now, so a later attempt may take it."""


class Busy(SystemExit):
    """A refusal that waiting may lift, such as the apply window being shut or another writer or applier at
    work. It exits BUSY; reporting_busy prints its message, which an exit code does not carry."""

    def __init__(self, message: str):
        super().__init__(message)
        self.code = BUSY


@contextlib.contextmanager
def reporting_busy() -> Iterator[None]:
    try:
        yield
    except Busy as exc:
        print(exc, file=sys.stderr)
        raise


def lane_name(stage: str, lane: str) -> str:
    return f"the {stage} automatic lane" if lane == AUTO else f"the {stage} stage"


def store_dir(given: Path | None = None) -> Path:
    """The run store: ``given``, else ``PITCHRANK_CLEANUP_DIR``, else ~/pitchrank-cleanup-runs."""
    configured = str(given or os.getenv(STORE_ENV, "")).strip()
    if not configured:
        return Path.home() / "pitchrank-cleanup-runs"
    store = Path(configured).expanduser()
    if not store.is_absolute():
        # Resolved against the current folder, a relative store differs from shell to shell, and
        # so does the apply lock inside it.
        raise ValueError(f"the run store must be an absolute path, not {configured!r}")
    return store.resolve(strict=False)


def run_dir(store: Path, run_id: str) -> Path:
    if not _RUN_ID.fullmatch(run_id or ""):
        raise ValueError(f"{run_id!r} is not a run id (<YYYY-MM-DD>-<scope>, lowercase)")
    return store / "runs" / run_id


def stage_dir(store: Path, run_id: str, stage: str) -> Path:
    if stage not in STAGES:
        raise ValueError(f"{stage!r} is not a stage; the stages are {', '.join(STAGES)}")
    return run_dir(store, run_id) / stage


def lane_dir(store: Path, run_id: str, stage: str, lane: str = OWNER) -> Path:
    if lane not in LANES:
        raise ValueError(f"{lane!r} is not a lane; the lanes are {', '.join(LANES)}")
    folder = stage_dir(store, run_id, stage)
    return folder / AUTO if lane == AUTO else folder


def inputs_dir(folder: Path) -> Path:
    """The stage folder holding the page and inputs a lane's folder was collected from."""
    return folder.parent if folder.name == AUTO else folder


def _utc_stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_run(store: Path, run: dict) -> Path:
    """Write ``run`` as its run.json, stamping ``updated_at``."""
    if run.get("status") not in STATUSES:
        raise ValueError(f"{run.get('status')!r} is not a run status; the statuses are {', '.join(STATUSES)}")
    unknown = set(run.get("stages") or {}) - set(STAGES)
    if unknown:
        raise ValueError(f"run.json names stages that do not exist: {sorted(unknown)}")
    path = run_dir(store, run["run_id"]) / RUN_FILE
    write_json(path, {**run, "updated_at": utc_now_iso()}, indent=1)
    return path


def _parse_run(path: Path) -> dict:
    run_id = path.parent.name
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError(f"{run_id!r} is not a run id")
    run = read_json(path)
    if not isinstance(run, dict) or run.get("run_id") != run_id or run.get("status") not in STATUSES:
        raise ValueError(f"{path} is not a run file for {run_id}")
    return run


def read_run(store: Path, run_id: str) -> dict:
    return _parse_run(run_dir(store, run_id) / RUN_FILE)


def list_runs(store: Path) -> list[dict]:
    """Every readable run, latest date first (ordered by run id). A folder without a readable
    run.json of its own is skipped."""
    runs = []
    for path in sorted((store / "runs").glob(f"*/{RUN_FILE}")):
        try:
            runs.append(_parse_run(path))
        except (OSError, ValueError) as exc:
            logger.warning("Skipping %s: %s", path, exc)
    return sorted(runs, key=lambda run: run["run_id"], reverse=True)


def review_keys(stage: str) -> tuple[str, ...]:
    return MERGE_REVIEW_KEYS if stage == MERGES else CHANGE_REVIEW_KEYS


def _copies(proposal_path: Path, review_path: Path, keys: tuple[str, ...]) -> bool:
    """Whether the review judges the proposal's rows, in order, copying ``keys`` from each.

    Rows a reviewer marks ``extra`` are its own additions. They must come after the rows it
    judged, since a reader pairs the proposal with the review row by row, and are not compared.
    """
    try:
        proposals = read_json(proposal_path)
        reviews = read_json(review_path)
    except (OSError, ValueError):
        return False
    if not (isinstance(proposals, list) and isinstance(reviews, list)):
        return False
    if not all(isinstance(row, dict) for row in proposals + reviews):
        return False
    judged = [row for row in reviews if not row.get("extra")]
    return (
        reviews[: len(judged)] == judged
        and len(judged) == len(proposals)
        and all(
            key in proposal and review.get(key) == proposal[key]
            for proposal, review in zip(proposals, judged)
            for key in keys
        )
    )


def check_reviews(folder: Path, keys: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The proposals in ``folder`` still waiting for a review, and the reviews set aside this time.

    A review that does not copy its proposal is renamed ``<name>_review.json.bad`` and its
    proposal queued again. A review that cannot be renamed (on Windows, usually because its
    reviewer still has it open) is left in place and its proposal stays queued.
    """
    queued, set_aside = [], []
    for proposal in sorted(folder.glob("*.json")):
        if proposal.name.endswith(REVIEW_SUFFIX):
            continue
        review = proposal.with_name(proposal.stem + REVIEW_SUFFIX)
        if review.exists():
            if _copies(proposal, review, keys):
                continue
            try:
                os.replace(review, review.with_name(review.name + BAD_SUFFIX))
                set_aside.append(review.name)
            except PermissionError:
                pass
        queued.append(proposal.stem)
    return tuple(queued), tuple(set_aside)


def stage_progress(store: Path, run_id: str, stage: str) -> StageProgress:
    """The stage's first unfinished step, and its automatic lane's, read from their markers.

    Reaching the review step re-checks the reviews, which sets aside any that does not copy its
    proposal (see ``check_reviews``).
    """
    folder = stage_dir(store, run_id, stage)
    auto = _auto_step(folder)
    set_aside: tuple[str, ...] = ()
    for step in STEPS:
        if step is REVIEW:
            queued, set_aside = check_reviews(folder / REVIEW_DIR, review_keys(stage))
            if queued:
                return StageProgress(stage, step, queued, set_aside, auto)
        elif not (folder / step.marker).exists():
            step = _apply_step(folder) if step is APPLY else step
            return StageProgress(stage, step, set_aside=set_aside, auto_step=auto)
    return StageProgress(stage, None, set_aside=set_aside, auto_step=auto)


def _auto_step(folder: Path) -> Step | None:
    """The automatic lane's first unfinished step: None once it is applied, or while no page has sent it a
    change and nothing is collected into it. A page.json that cannot be read keeps the stage open, since
    it may have sent some."""
    lane = folder / AUTO
    try:
        sent = read_json(folder / PAGE_MARKER).get(AUTO, 0)
    except FileNotFoundError:
        sent = 0
    except (OSError, ValueError, AttributeError) as exc:
        rebuild = f"build the page again: its {PAGE_MARKER} cannot be read: {exc}"
        return Step(AUTO_COLLECT.name, AUTO_COLLECT.marker, rebuild)
    if not (sent or (lane / AUTO_COLLECT.marker).exists()):
        return None
    if not (lane / AUTO_COLLECT.marker).exists():
        return AUTO_COLLECT
    if not (lane / AUTO_APPLY.marker).exists():
        return _apply_step(lane, AUTO_APPLY)
    return None


def _lacks(records, name: str, keys: tuple[str, ...]) -> list[str]:
    """What a list of records named ``name``, each holding ``keys``, lacks."""
    if not isinstance(records, list):
        return [f"a list of {name}"]
    return [
        f"{name}[{n}].{key}"
        for n, record in enumerate(records)
        for key in keys
        if not (isinstance(record, dict) and key in record)
    ]


def _has_offset(stamp) -> bool:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).tzinfo is not None
    except (AttributeError, TypeError, ValueError):
        return False


def read_progress(folder: Path) -> dict:
    """The stage's apply.json, refused naming what it lacks, as a hand edit can leave it, and any step time
    written without its offset, which no window can be compared with."""
    path = folder / APPLY_PROGRESS_FILE
    progress = read_json(path)
    if not isinstance(progress, dict):
        raise ValueError(f"{path} holds no apply record")
    missing = [key for key in ("collected", "cuts", "held", "batches", "queue") if key not in progress]
    missing += _lacks(progress.get("batches", []), "batches", BATCH_KEYS)
    missing += _lacks(progress.get("queue", []), "queue", QUEUE_STEP_KEYS)
    for n, step in enumerate(progress["queue"] if not missing else []):
        missing += _lacks(step["cards"], f"queue[{n}].cards", CARD_KEYS)
        missing += _lacks(step["reviews"], f"queue[{n}].reviews", ())
    if missing:
        raise ValueError(f"{path} lacks {', '.join(missing)}")
    untimed = [
        f"{name}[{n}].{key} {step[key]!r}"
        for name in ("batches", "queue")
        for n, step in enumerate(progress[name])
        for key in ("started_at", "ended_at")
        if not (_has_offset(step[key]) or (key == "ended_at" and step[key] is None))
    ]
    if untimed:
        raise ValueError(
            f"{path} holds {', '.join(untimed)}; write each as a full ISO time with its offset, such as "
            "2026-10-17T18:30:00-07:00"
        )
    return progress


def _apply_step(folder: Path, apply: Step = APPLY) -> Step:
    """The apply step, naming what an earlier attempt at it already wrote, which abandoning the run
    would leave in place."""
    try:
        progress = read_progress(folder)
    except FileNotFoundError:
        return apply
    except (OSError, ValueError) as exc:
        return Step(apply.name, apply.marker, f"{apply.next_action}; its {APPLY_PROGRESS_FILE} cannot be read: {exc}")
    batches, queue = progress["batches"], progress["queue"]
    applied = sorted({batch["batch"] for batch in batches if batch["exit"] == 0})
    failed = sorted({batch["batch"] for batch in batches if batch["exit"] not in (0, None)} - set(applied))
    written = [f"{len(applied)} batch(es) applied ({', '.join(applied)})"] if applied else []
    written += [f"a failed {name} attempt" for name in failed]
    written += ["review-queue cards settled"] if queue else []
    unended = ["a batch"] if any(b["exit"] is None for b in batches) else []
    unended += ["a review-queue step"] if any(step["ended_at"] is None for step in queue) else []
    said = [" and ".join(written)] if written else []
    if unended:
        said.append(f"{' and '.join(unended)} stopped with no recorded end, to record in {APPLY_PROGRESS_FILE}")
    if not said:
        return apply
    return Step(
        apply.name,
        apply.marker,
        f"{apply.next_action} again; {', '.join(said)}, so revert before abandoning the run",
    )


def stage_due(store: Path, run: dict, stage: str, steps: tuple[str, ...], lane: str = OWNER) -> Path:
    """The lane's folder, once its run is in review and the lane's next step is one of ``steps``."""
    if run["status"] != "reviewing":
        raise ValueError(
            f"run {run['run_id']} is {run['status']}; pages are built and collected while it is reviewing, "
            "and the choices applied then too"
        )
    override = (run.get("stages") or {}).get(stage)
    if override:
        raise ValueError(f"{stage} has no proposals this run: {override}")
    folder = lane_dir(store, run["run_id"], stage, lane)
    progress = stage_progress(store, run["run_id"], stage)
    if lane == OWNER:
        step = progress.next_step
        if step is None:
            raise ValueError(f"{stage} is already applied")
    else:
        step = progress.auto_step
        if progress.next_step is not None and progress.next_step.name in SHARED_STEPS:
            raise ValueError(f"{stage} is not ready for this: next, {progress.next_step.next_action}")
        if step is None and (folder / AUTO_APPLY.marker).exists():
            raise ValueError(f"{lane_name(stage, lane)} is already applied")
        if step is None:
            raise ValueError(f"{stage} has no automatic lane: no page has sent it a change")
    if step.name not in steps:
        raise ValueError(f"{stage} is not ready for this: next, {step.next_action}")
    return folder


def file_hash(path: Path) -> str | None:
    """None for a file that is not there, as the clubs stage's scoped CSV is when its scan found
    nothing in the scope."""
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def default_holder() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def definite_refusal(exc: Exception) -> bool:
    """PostgREST's own errors carry a string code and roll back. Anything else answered for it (a
    gateway's 502, an unreadable body, a dropped connection) may follow a committed write."""
    return isinstance(exc, APIError) and isinstance(exc.code, str)


def refused(action: str, exc: Exception, retry: str) -> str:
    """Why ``action`` failed: PostgREST's refusal, naming a missing migration or the wrong key, or else
    that the answer was lost, with the command whose re-run reads where things now stand."""
    if definite_refusal(exc):
        if exc.code == TABLE_MISSING:
            return f"{action}: {exc.message}; apply the table's migration first"
        if exc.code == PERMISSION_DENIED:
            return f"{action}: {exc.message}; only the service-role key may do this"
        return f"{action}: {exc.message}"
    detail = exc.message if isinstance(exc, APIError) else f"{type(exc).__name__}: {exc}"
    return f"{action}: the database's answer was lost ({detail}); re-run to see where it stands: {retry}"


def _lease_refused(run_id: str, exc: APIError) -> str:
    if exc.code == TABLE_MISSING:
        return f"{RUNS_TABLE} does not exist yet: apply its migration before leasing run {run_id}"
    if exc.code == PERMISSION_DENIED:
        return f"could not lease run {run_id}: only the service-role key can write {RUNS_TABLE}"
    return f"could not lease run {run_id}: {exc.message}"


def update_free_open_run(sb, run_id: str, payload: dict) -> tuple[list[dict], dict | None]:
    """Apply ``payload`` to the run while it is open and no applier holds a live lease on it. Returns
    the rows it changed, and when it changed none, the run's status and lease as they now stand (None
    when there is no such run), re-read to say which guard held."""
    now = datetime.now(timezone.utc)
    moved = (
        sb.table(RUNS_TABLE)
        .update(payload)
        .eq("run_id", run_id)
        .in_("status", list(OPEN_STATUSES))
        .or_(f"lease_holder.is.null,lease_expires_at.lt.{_utc_stamp(now)}")
        .execute()
        .data
    )
    if moved:
        return moved, None
    rows = sb.table(RUNS_TABLE).select("status,lease_holder,lease_expires_at").eq("run_id", run_id).execute().data
    return [], rows[0] if rows else None


def update_held_run(sb, run_id: str, holder: str, payload: dict) -> list[dict]:
    """Apply ``payload`` to the run while it is open and ``holder``'s lease on it is live. Returns the
    rows it changed: none once the lease expired, was cleared or passed to another holder."""
    return (
        sb.table(RUNS_TABLE)
        .update(payload)
        .eq("run_id", run_id)
        .eq("lease_holder", holder)
        .gt("lease_expires_at", _utc_stamp(datetime.now(timezone.utc)))
        .in_("status", list(OPEN_STATUSES))
        .execute()
        .data
    )


def _lease_expiry() -> str:
    return _utc_stamp(datetime.now(timezone.utc) + timedelta(hours=LEASE_HOURS))


def renew_lease(sb, run_id: str, holder: str) -> bool:
    """Push ``holder``'s lease out to LEASE_HOURS from now; False when the lease is no longer theirs."""
    return bool(update_held_run(sb, run_id, holder, {"lease_expires_at": _lease_expiry()}))


def _take_lease(sb, run_id: str, holder: str) -> None:
    try:
        taken, row = update_free_open_run(sb, run_id, {"lease_holder": holder, "lease_expires_at": _lease_expiry()})
        if taken:
            return
    except APIError as exc:
        # A lost answer may follow a committed update, so it passes through to the caller's release.
        if not definite_refusal(exc):
            raise
        raise ApplyLockError(_lease_refused(run_id, exc)) from exc
    if row is None:
        raise ApplyLockError(f"no run {run_id} in {RUNS_TABLE}")
    if row["status"] not in OPEN_STATUSES:
        raise ApplyLockError(f"run {run_id} is {row['status']}, so nothing may apply to it")
    if row["lease_holder"]:
        raise RunBusy(f"run {run_id} is held by {row['lease_holder']} until {row['lease_expires_at']}")
    raise RunBusy(f"run {run_id} was held when the lease was asked for and is free now; try again")


def _release_lease(sb, run_id: str, holder: str, *, quiet: bool = False) -> None:
    """Clear the lease if ``holder`` still holds it. An error is logged, not raised, so a failed
    release leaves the lease to expire rather than hiding how the apply ended."""
    try:
        released = (
            sb.table(RUNS_TABLE)
            .update({"lease_holder": None, "lease_expires_at": None})
            .eq("run_id", run_id)
            .eq("lease_holder", holder)
            .execute()
            .data
        )
    except Exception as exc:
        logger.error("Could not release run %s's lease (%s); it stays held until it expires", run_id, exc)
        return
    if not released and not quiet:
        logger.warning(
            "Run %s's lease was no longer %s's to release: it was cleared or taken meanwhile", run_id, holder
        )


@contextlib.contextmanager
def hold_apply_file(store: Path, run_id: str) -> Iterator[None]:
    """The apply lock's file half: the run's apply.lock, against other shells on this machine."""
    folder = run_dir(store, run_id)
    if not (folder / RUN_FILE).exists():
        raise ApplyLockError(f"no run {run_id} in {store}")
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(_acquire_file_lock(folder / APPLY_LOCK_FILE, timeout=0.0))
        except FileLockError as exc:
            raise RunBusy(
                f"run {run_id} is in use on this machine (an apply, revert, collect, page build or end_run holds "
                "its lock)"
            ) from exc
        yield


@contextlib.contextmanager
def acquire_apply_lock(sb, store: Path, run_id: str, *, holder: str | None = None) -> Iterator[str]:
    """Hold the run for one applier: a file lock against other shells on this machine, then the
    run row's lease against every other machine and session. Yields the holder name."""
    holder = holder or default_holder()
    with hold_apply_file(store, run_id):
        try:
            _take_lease(sb, run_id, holder)
        except ApplyLockError:
            raise
        except BaseException:
            # The update may have committed before its answer was lost; clear the lease if it did.
            _release_lease(sb, run_id, holder, quiet=True)
            raise
        try:
            yield holder
        finally:
            _release_lease(sb, run_id, holder)
