"""Where a weekly team-cleanup run keeps its files, how far each stage has got, and the apply lock.

The store sits outside the repo, so removing a worktree takes no undo log with it:

  <store>/exports/                 every applier's plans and logs (their --exports-dir)
  <store>/runs/<run_id>/run.json   scope, budgets, status, stage overrides, timestamps
  <store>/runs/<run_id>/<stage>/   that stage's files, with one marker per finished step
  <store>/health/                  weekly reports

A stage's progress is read back from its markers rather than stored, so a run killed mid-stage
resumes at the first step whose marker is missing:

  preflight.json   the stage's skill self-check passed
  propose_done     its proposals are written
  review/          every <name>.json there has a <name>_review.json that copies it
  page.json        the owner's review page is built
  collected.json   the owner's choices are collected into the stage applier's input
  RECORD.md        the apply ran and was verified

The owner acts twice: deciding on the page, before collected.json, and triggering the apply,
before RECORD.md.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import socket
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from postgrest.exceptions import APIError

from scripts.team_cleanup.decisions import MERGES, TABLE_MISSING
from src.tournaments.storage._file_lock import FileLockError, _acquire_file_lock
from src.tournaments.storage._io import read_json, utc_now_iso, write_json

logger = logging.getLogger(__name__)

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
OPEN_STATUSES = ("proposing", "reviewing", "applying", "second_lap")
STATUSES = (*OPEN_STATUSES, "done", "abandoned")

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


REVIEW = Step("review", None, "review the queued proposals")
STEPS = (
    Step("preflight", "preflight.json", "run the stage's skill self-check"),
    Step("propose", "propose_done", "write the stage's proposals"),
    REVIEW,
    Step("page", "page.json", "build the owner's review page"),
    Step("collect", "collected.json", "the owner decides on the page, then collect the choices"),
    Step("apply", "RECORD.md", "the owner runs the apply"),
)


@dataclass(frozen=True)
class StageProgress:
    stage: str
    next_step: Step | None
    queued: tuple[str, ...] = ()
    set_aside: tuple[str, ...] = ()

    @property
    def finished(self) -> bool:
        return self.next_step is None


class ApplyLockError(RuntimeError):
    """Another applier holds the run, or the run cannot be leased."""


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
    """The stage's first unfinished step, read from its markers.

    Reaching the review step re-checks the reviews, which sets aside any that does not copy its
    proposal (see ``check_reviews``).
    """
    folder = stage_dir(store, run_id, stage)
    set_aside: tuple[str, ...] = ()
    for step in STEPS:
        if step is REVIEW:
            queued, set_aside = check_reviews(folder / REVIEW_DIR, review_keys(stage))
            if queued:
                return StageProgress(stage, step, queued, set_aside)
        elif not (folder / step.marker).exists():
            return StageProgress(stage, step, set_aside=set_aside)
    return StageProgress(stage, None, set_aside=set_aside)


def default_holder() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _lease_refused(run_id: str, exc: APIError) -> str:
    if exc.code == TABLE_MISSING:
        return f"{RUNS_TABLE} does not exist yet: apply its migration before leasing run {run_id}"
    if exc.code == PERMISSION_DENIED:
        return f"could not lease run {run_id}: only the service-role key can write {RUNS_TABLE}"
    return f"could not lease run {run_id}: {exc.message}"


def _take_lease(sb, run_id: str, holder: str) -> None:
    now = datetime.now(timezone.utc)
    try:
        taken = (
            sb.table(RUNS_TABLE)
            .update({"lease_holder": holder, "lease_expires_at": _utc_stamp(now + timedelta(hours=LEASE_HOURS))})
            .eq("run_id", run_id)
            .in_("status", list(OPEN_STATUSES))
            .or_(f"lease_holder.is.null,lease_expires_at.lt.{_utc_stamp(now)}")
            .execute()
            .data
        )
        if taken:
            return
        # The guarded update matched nothing; re-read to say which guard held.
        rows = sb.table(RUNS_TABLE).select("status,lease_holder,lease_expires_at").eq("run_id", run_id).execute().data
    except APIError as exc:
        # PostgREST's own errors carry a string code and roll back. Anything else answered for it
        # (a gateway's 502, an unreadable body) may follow a committed update, so it passes through
        # to the caller's release.
        if not isinstance(exc.code, str):
            raise
        raise ApplyLockError(_lease_refused(run_id, exc)) from exc
    if not rows:
        raise ApplyLockError(f"no run {run_id} in {RUNS_TABLE}")
    row = rows[0]
    if row["status"] not in OPEN_STATUSES:
        raise ApplyLockError(f"run {run_id} is {row['status']}, so nothing may apply to it")
    if row["lease_holder"]:
        raise ApplyLockError(f"run {run_id} is held by {row['lease_holder']} until {row['lease_expires_at']}")
    raise ApplyLockError(f"run {run_id} was held when the lease was asked for and is free now; try again")


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
def acquire_apply_lock(sb, store: Path, run_id: str, *, holder: str | None = None) -> Iterator[str]:
    """Hold the run for one applier: a file lock against other shells on this machine, then the
    run row's lease against every other machine and session. Yields the holder name."""
    holder = holder or default_holder()
    folder = run_dir(store, run_id)
    if not (folder / RUN_FILE).exists():
        raise ApplyLockError(f"no run {run_id} in {store}")
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(_acquire_file_lock(folder / APPLY_LOCK_FILE, timeout=0.0))
        except FileLockError as exc:
            raise ApplyLockError(f"another apply on this machine holds run {run_id}") from exc
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
