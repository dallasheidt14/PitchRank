"""Save and reload a seeding intake run.

A run is one pasted roster, what the resolver decided about each row, and the
overrides an operator entered by hand. Those overrides are the expensive part:
each one is a manual lookup on the provider's site, so losing them to a browser
refresh costs real time. Everything here exists to make that survivable.

Runs live under ``reports/seeding/<slug>/seeding_run.json``, deliberately apart
from the backtest event layout in ``src.tournaments.storage``. A pasted roster
has no provider event id, so it cannot form a real ``event_key``, and borrowing
that layout would mean inventing one.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.tournaments.gotsport_event_roster import event_id_from
from src.tournaments.roster_paste import RosterRow
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.storage._io import write_json

logger = logging.getLogger(__name__)

__all__ = [
    "RUN_FILENAME",
    "RunNameTaken",
    "RunSourceChanged",
    "SeedingRun",
    "SeedingRunEntry",
    "default_base_dir",
    "legacy_event_id",
    "list_runs",
    "load_run",
    "save_run",
    "slugify",
]

RUN_FILENAME = "seeding_run.json"

_SEEDING_DIR_ENV = "MATCHBALANCE_SEEDING_DIR"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_LEGACY_EVENT_NAME = re.compile(r"\bGotSport\s+Event\s+(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class SeedingRun:
    name: str
    rows: tuple[RosterRow, ...]
    resolved: tuple[ResolvedTeam, ...]
    overrides: dict[int, dict[str, Any]] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    saved_at: str = ""
    pack: dict[str, Any] | None = None
    source_url: str = ""
    assessment: dict[str, Any] = field(default_factory=dict)
    cohort_decisions: dict[int, dict[str, Any]] = field(default_factory=dict)


class RunNameTaken(ValueError):
    """Another run's name already maps to this folder."""

    def __init__(self, existing: str):
        super().__init__(f"A run called {existing!r} already saves under this name")
        self.existing = existing


class RunSourceChanged(ValueError):
    """The run saved under this name came from a different roster, or a fuller walk of it."""

    def __init__(self, existing: str, *, less_complete: bool = False):
        reason = "holds a more complete walk" if less_complete else "came from a different roster"
        super().__init__(f"The saved run {existing!r} {reason}")
        self.existing = existing
        self.less_complete = less_complete


@dataclass(frozen=True)
class SeedingRunEntry:
    """One row of the resume list."""

    slug: str
    name: str
    saved_at: str
    team_count: int


def _shared_checkout_root(project_root: Path) -> Path:
    """Return the primary checkout shared by this repo's linked worktrees.

    Git writes a ``.git`` file in a linked worktree. Its ``commondir`` points
    back to the primary checkout's ``.git`` directory, whose parent is the one
    place every worktree can use for local operator data. Invalid or non-Git
    layouts fall back to the checkout that contains this module.
    """
    root = project_root.resolve(strict=False)
    dot_git = root / ".git"
    if dot_git.is_dir():
        return root
    if not dot_git.is_file():
        return root

    try:
        marker = dot_git.read_text(encoding="utf-8").strip()
        prefix = "gitdir:"
        if not marker.lower().startswith(prefix):
            return root
        git_dir = Path(marker[len(prefix) :].strip())
        if not git_dir.is_absolute():
            git_dir = root / git_dir
        git_dir = git_dir.resolve(strict=False)
        if not git_dir.is_dir():
            return root

        common_marker = (git_dir / "commondir").read_text(encoding="utf-8").strip()
        if not common_marker:
            return root
        common_git_dir = Path(common_marker)
        if not common_git_dir.is_absolute():
            common_git_dir = git_dir / common_git_dir
        common_git_dir = common_git_dir.resolve(strict=False)
        worktrees_dir = (common_git_dir / "worktrees").resolve(strict=False)
        if (
            common_git_dir.name.casefold() != ".git"
            or not common_git_dir.is_dir()
            or not git_dir.is_relative_to(worktrees_dir)
        ):
            return root
        return common_git_dir.parent
    except (OSError, RuntimeError, ValueError):
        return root


def default_base_dir() -> Path:
    """Return one durable Seeding store shared by every local worktree."""
    shared_root = _shared_checkout_root(_PROJECT_ROOT)
    configured = os.getenv(_SEEDING_DIR_ENV, "").strip()
    if configured:
        configured_path = Path(configured).expanduser()
        if not configured_path.is_absolute():
            configured_path = shared_root / configured_path
        return configured_path.resolve(strict=False)
    return shared_root / "reports" / "seeding"


def slugify(name: str) -> str:
    """Turn an operator-typed event name into a directory name."""
    slug = _SLUG_STRIP.sub("-", str(name or "").strip().lower()).strip("-")
    if not slug:
        raise ValueError(f"Cannot build a run name from {name!r}")
    return slug


def legacy_event_id(name: Any) -> str | None:
    """The event id older saves carried only in their generated ``GotSport Event N`` name."""
    match = _LEGACY_EVENT_NAME.search(str(name or ""))
    return match.group(1) if match else None


def _event_of(assessment: Mapping[str, Any], source_url: Any) -> str | None:
    event_id = assessment.get("event_id") or event_id_from(str(source_url or ""))
    return str(event_id) if event_id else None


def _source_conflict(existing: Mapping[str, Any], run: SeedingRun) -> RunSourceChanged | None:
    """The refusal that saving ``run`` over ``existing`` earns, or None.

    Two pasted lists are one run, so a corrected paste replaces the last one. An
    event is its own run, and a partial walk never replaces a complete one.
    """
    name = str(existing.get("name") or run.name)
    saved = existing.get("assessment")
    saved = saved if isinstance(saved, dict) else {}
    saved_event = _event_of(saved, existing.get("source_url"))
    if not saved and not existing.get("source_url"):
        saved_event = legacy_event_id(existing.get("name"))
    if saved_event != _event_of(run.assessment, run.source_url):
        return RunSourceChanged(name)
    if saved_event and saved.get("coverage") == "complete" and run.assessment.get("coverage") != "complete":
        return RunSourceChanged(name, less_complete=True)
    return None


def save_run(run: SeedingRun, *, base_dir: Path | str | None = None, archive_previous: bool = True) -> Path:
    """Replace the latest save; archive revisions but not automatic progress checkpoints.

    Refuses to write over another run: one whose name maps to the same folder
    (``RunNameTaken``), or one from a different source or a fuller walk of the
    same event (``RunSourceChanged``). A saved file that cannot be read is replaceable.
    """
    root = Path(base_dir) if base_dir is not None else default_base_dir()
    target = root / slugify(run.name)
    path = target / RUN_FILENAME
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = None
    if isinstance(existing, dict):
        existing_name = str(existing.get("name") or "")
        if existing_name and existing_name != run.name:
            raise RunNameTaken(existing_name)
        conflict = _source_conflict(existing, run)
        if conflict is not None:
            raise conflict
    target.mkdir(parents=True, exist_ok=True)

    payload = {
        "name": run.name,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "rows": [asdict(row) for row in run.rows],
        "resolved": [asdict(item) for item in run.resolved],
        "overrides": {str(index): value for index, value in run.overrides.items()},
        "warnings": list(run.warnings),
        "pack": run.pack,
        "source_url": run.source_url,
        "assessment": run.assessment,
        "cohort_decisions": {str(index): value for index, value in run.cohort_decisions.items()},
    }

    if archive_previous and path.exists():
        # Preserve the exact bytes so a damaged snapshot cannot prevent recovery.
        previous = path.read_bytes()
        history = target / "history"
        history.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        with (history / f"{stamp}.json").open("xb") as archive:
            archive.write(previous)
            archive.flush()
            os.fsync(archive.fileno())
    write_json(path, payload, indent=1)
    return path


def load_run(slug: str, *, base_dir: Path | str | None = None) -> SeedingRun:
    """Read a saved run back.

    Override keys are restored to ``int``: they index into ``rows``, and JSON
    object keys are always strings, so leaving them as strings would silently
    orphan every override on reload.
    """
    root = Path(base_dir) if base_dir is not None else default_base_dir()
    path = root / slug / RUN_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))

    return SeedingRun(
        name=payload.get("name", slug),
        rows=tuple(RosterRow(**row) for row in payload.get("rows", [])),
        resolved=tuple(
            ResolvedTeam(**{**item, "candidates": tuple(item.get("candidates") or ())})
            for item in payload.get("resolved", [])
        ),
        overrides={int(index): value for index, value in (payload.get("overrides") or {}).items()},
        warnings=tuple(payload.get("warnings") or ()),
        saved_at=payload.get("saved_at", ""),
        pack=payload.get("pack"),
        source_url=str(payload.get("source_url") or ""),
        assessment=dict(payload.get("assessment") or {}),
        cohort_decisions={int(index): value for index, value in (payload.get("cohort_decisions") or {}).items()},
    )


def list_runs(*, base_dir: Path | str | None = None) -> list[SeedingRunEntry]:
    """List saved runs, most recently saved first.

    A directory that is not a readable run is skipped rather than raised on, so
    one bad folder cannot take the resume list down with it.
    """
    root = Path(base_dir) if base_dir is not None else default_base_dir()
    if not root.exists():
        return []

    entries: list[SeedingRunEntry] = []
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir():
            continue
        path = candidate / RUN_FILENAME
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            entries.append(
                SeedingRunEntry(
                    slug=candidate.name,
                    name=payload.get("name", candidate.name),
                    saved_at=payload.get("saved_at", ""),
                    team_count=len(payload.get("rows") or []),
                )
            )
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("Skipping unreadable seeding run at %s: %s", path, exc)

    entries.sort(key=lambda entry: entry.saved_at, reverse=True)
    return entries
