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
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.tournaments.roster_paste import RosterRow
from src.tournaments.roster_resolver import ResolvedTeam

logger = logging.getLogger(__name__)

__all__ = [
    "RUN_FILENAME",
    "SeedingRun",
    "SeedingRunEntry",
    "default_base_dir",
    "list_runs",
    "load_run",
    "save_run",
    "slugify",
]

RUN_FILENAME = "seeding_run.json"

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class SeedingRun:
    name: str
    rows: tuple[RosterRow, ...]
    resolved: tuple[ResolvedTeam, ...]
    overrides: dict[int, dict[str, Any]] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    saved_at: str = ""


@dataclass(frozen=True)
class SeedingRunEntry:
    """One row of the resume list."""

    slug: str
    name: str
    saved_at: str
    team_count: int


def default_base_dir() -> Path:
    return Path("reports") / "seeding"


def slugify(name: str) -> str:
    """Turn an operator-typed event name into a directory name."""
    slug = _SLUG_STRIP.sub("-", str(name or "").strip().lower()).strip("-")
    if not slug:
        raise ValueError(f"Cannot build a run name from {name!r}")
    return slug


def save_run(run: SeedingRun, *, base_dir: Path | str | None = None) -> Path:
    """Write the run, replacing any earlier save under the same name."""
    root = Path(base_dir) if base_dir is not None else default_base_dir()
    target = root / slugify(run.name)
    target.mkdir(parents=True, exist_ok=True)

    payload = {
        "name": run.name,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "rows": [asdict(row) for row in run.rows],
        "resolved": [asdict(item) for item in run.resolved],
        "overrides": {str(index): value for index, value in run.overrides.items()},
        "warnings": list(run.warnings),
    }

    path = target / RUN_FILENAME
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
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
