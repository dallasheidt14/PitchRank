"""Per-run directory state machine — staging → promoted/failed/cancelled.

Spec §9 run state machine::

    pending → running → completed  (rename .tmp/ → <run_id>/, done.json)
                     → failed      (rename .tmp/ → .failed/, error.json)
                     → cancelled   (rename .tmp/ → .cancelled/, cancelled.json)

Only ``runs/<run_id>/`` directories (no suffix) with a ``done.json`` inside
are valid completed runs. Failed/cancelled runs are kept for diagnosis.

**Atomic-rename note for directories.** ``os.replace(src_dir, dst_dir)``
raises ``OSError`` / ``ENOTEMPTY`` on Windows AND POSIX when ``dst_dir``
exists and is non-empty. The ``intake_journal.compact()`` pattern at
``intake_journal.py:284`` works for files because file-rename overwrites,
but directory-rename does not. Each transition adds an explicit
``dst.exists()`` precheck that turns the raw ``OSError`` into a typed
``RunStateError`` with a clear message.

**Marker JSON write protocol.** Each marker file (``done.json`` /
``error.json`` / ``cancelled.json``) is written via ``_io.write_json``
(atomic ``<path>.tmp`` + ``os.replace`` + ``fsync``) inside the staging
``.tmp/`` directory **before** the directory rename. A power loss between
marker write and directory rename leaves the marker durable in ``.tmp/``;
the directory rename either completes atomically or doesn't — no partial
``runs/<run_id>/`` ever exists without a ``done.json``.

**Awareness of extended run-dir files.** Shell 06 produces
``fallbacks.jsonl``, ``run_metadata.json``, ``run_overrides_audit.jsonl``
inside the run directory. This module does not enumerate or validate them —
they are caller-owned.
"""

from __future__ import annotations

import os
from pathlib import Path

from src.tournaments.storage._io import utc_now_iso, write_json
from src.tournaments.storage.event_key import scenario_dir
from src.tournaments.storage.schema_version import stamp_schema_version

__all__ = [
    "RunStateError",
    "cancel_run",
    "create_staging_run",
    "fail_run",
    "list_runs",
    "promote_run",
]


class RunStateError(RuntimeError):
    """Raised when a run-state transition cannot complete safely."""


def _runs_root(event_key: str, scenario: str, base_dir: Path | str) -> Path:
    return scenario_dir(event_key, scenario, base_dir=base_dir) / "runs"


def create_staging_run(
    event_key: str,
    scenario: str,
    run_id: str,
    *,
    base_dir: Path | str = "reports",
) -> Path:
    """Create ``runs/<run_id>.tmp/`` for an in-flight subprocess.

    Raises ``RunStateError`` if ``<run_id>.tmp/`` or ``<run_id>/`` already
    exists — both indicate a prior aborted run that needs manual cleanup
    before the new run can stage.
    """
    runs_root = _runs_root(event_key, scenario, base_dir)
    staging_dir = runs_root / f"{run_id}.tmp"
    final_dir = runs_root / run_id
    if staging_dir.exists():
        raise RunStateError(f"refusing to stage — {staging_dir} already exists")
    if final_dir.exists():
        raise RunStateError(f"refusing to stage — {final_dir} already exists")
    staging_dir.mkdir(parents=True, exist_ok=False)
    return staging_dir


def promote_run(
    event_key: str,
    scenario: str,
    run_id: str,
    *,
    base_dir: Path | str = "reports",
) -> Path:
    """Promote ``runs/<run_id>.tmp/`` to ``runs/<run_id>/`` after writing ``done.json``.

    Order: ``done.json`` is written via ``_io.write_json`` (fully fsynced)
    BEFORE the directory rename so the marker is durable even if the
    rename is interrupted.

    Raises ``RunStateError`` if the staging dir is missing or the final dir
    already exists.
    """
    runs_root = _runs_root(event_key, scenario, base_dir)
    staging_dir = runs_root / f"{run_id}.tmp"
    final_dir = runs_root / run_id
    if not staging_dir.exists():
        raise RunStateError(f"refusing to promote — staging dir missing at {staging_dir}")
    if final_dir.exists():
        raise RunStateError(f"refusing to promote — {final_dir} already exists; resolve manually")
    write_json(
        staging_dir / "done.json",
        stamp_schema_version({"run_id": run_id, "promoted_at": utc_now_iso()}),
    )
    os.replace(staging_dir, final_dir)
    return final_dir


def fail_run(
    event_key: str,
    scenario: str,
    run_id: str,
    error: str,
    *,
    base_dir: Path | str = "reports",
) -> Path:
    """Rename ``runs/<run_id>.tmp/`` to ``runs/<run_id>.failed/`` with ``error.json``."""
    runs_root = _runs_root(event_key, scenario, base_dir)
    staging_dir = runs_root / f"{run_id}.tmp"
    failed_dir = runs_root / f"{run_id}.failed"
    if not staging_dir.exists():
        raise RunStateError(f"refusing to fail — staging dir missing at {staging_dir}")
    if failed_dir.exists():
        raise RunStateError(f"refusing to fail — {failed_dir} already exists")
    write_json(
        staging_dir / "error.json",
        stamp_schema_version({"run_id": run_id, "failed_at": utc_now_iso(), "error": error}),
    )
    os.replace(staging_dir, failed_dir)
    return failed_dir


def cancel_run(
    event_key: str,
    scenario: str,
    run_id: str,
    *,
    base_dir: Path | str = "reports",
) -> Path:
    """Rename ``runs/<run_id>.tmp/`` to ``runs/<run_id>.cancelled/`` with ``cancelled.json``."""
    runs_root = _runs_root(event_key, scenario, base_dir)
    staging_dir = runs_root / f"{run_id}.tmp"
    cancelled_dir = runs_root / f"{run_id}.cancelled"
    if not staging_dir.exists():
        raise RunStateError(f"refusing to cancel — staging dir missing at {staging_dir}")
    if cancelled_dir.exists():
        raise RunStateError(f"refusing to cancel — {cancelled_dir} already exists")
    write_json(
        staging_dir / "cancelled.json",
        stamp_schema_version({"run_id": run_id, "cancelled_at": utc_now_iso()}),
    )
    os.replace(staging_dir, cancelled_dir)
    return cancelled_dir


def list_runs(
    event_key: str,
    scenario: str,
    *,
    completed_only: bool = True,
    base_dir: Path | str = "reports",
) -> list[str]:
    """Return run-id directory names under ``runs/``.

    With ``completed_only=True`` (the default), only directories whose name
    has no ``.tmp`` / ``.failed`` / ``.cancelled`` suffix AND that contain
    a ``done.json`` are returned. With ``completed_only=False`` every
    directory under ``runs/`` is returned (the caller does its own
    filtering).
    """
    runs_root = _runs_root(event_key, scenario, base_dir)
    if not runs_root.exists():
        return []
    names: list[str] = []
    for entry in sorted(runs_root.iterdir()):
        if not entry.is_dir():
            continue
        if completed_only:
            if "." in entry.name:
                continue
            if not (entry / "done.json").exists():
                continue
        names.append(entry.name)
    return names
