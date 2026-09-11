"""The exact structure a played event was run under, as scraped.

Per-event and scenario-shared, so it lives in the intake tier beside
``raw_scrape.jsonl`` rather than under a scenario. It holds facts — pools with
their members, and every fixture with the label the organizer gave it — and
deliberately holds no format name: a replay consumes the fixture graph, and a
name would be a summary that can disagree with it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.tournaments.gotsport_event_structure import (
    Fixture,
    Pool,
    PoolMember,
    ScrapedDivision,
)
from src.tournaments.storage._io import read_json, read_versioned_json, write_json
from src.tournaments.storage.event_key import intake_dir
from src.tournaments.storage.schema_version import stamp_schema_version

__all__ = [
    "EventStructure",
    "StructureOverwriteRefused",
    "division_from_dict",
    "event_structure_path",
    "read_event_structure",
    "write_event_structure",
]

_FILENAME = "event_structure.json"


class StructureOverwriteRefused(RuntimeError):
    """Raised when ``write_event_structure`` would replace an already-complete
    structure with a partial one."""


@dataclass(frozen=True)
class EventStructure:
    """Every division's structure from one walk of one event."""

    event_id: str
    walked_at: str
    is_complete: bool
    divisions: tuple[ScrapedDivision, ...]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EventStructure":
        return cls(
            event_id=str(payload["event_id"]),
            walked_at=str(payload["walked_at"]),
            is_complete=bool(payload["is_complete"]),
            divisions=tuple(division_from_dict(item) for item in payload.get("divisions") or ()),
            schema_version=int(payload.get("schema_version", 1)),
        )


def division_from_dict(payload: dict[str, Any]) -> ScrapedDivision:
    """Rebuild one division from its persisted form.

    Public because the crash-recovery reader in ``tournament_intake`` rebuilds
    the same shape out of ``last_walk.json``. Two rebuilders would drift, and
    the one that drifts loses a walk that was paid for.
    """
    return ScrapedDivision(
        group_id=str(payload["group_id"]),
        division_label=str(payload["division_label"]),
        pools=tuple(_pool(item) for item in payload.get("pools") or ()),
        fixtures=tuple(_fixture(item) for item in payload.get("fixtures") or ()),
        pools_readable=bool(payload["pools_readable"]),
        fixtures_readable=bool(payload["fixtures_readable"]),
        warnings=tuple(str(warning) for warning in payload.get("warnings") or ()),
    )


def _pool(payload: dict[str, Any]) -> Pool:
    return Pool(
        pool_id=str(payload["pool_id"]),
        label=str(payload["label"]),
        members=tuple(
            PoolMember(
                registration_id=str(member["registration_id"]),
                team_name=str(member["team_name"]),
                standings_position=int(member["standings_position"]),
            )
            for member in payload.get("members") or ()
        ),
    )


def _fixture(payload: dict[str, Any]) -> Fixture:
    return Fixture(
        match_number=str(payload["match_number"]),
        bracket_label=str(payload["bracket_label"]),
        kind=str(payload["kind"]),
        home_registration_id=_optional_str(payload.get("home_registration_id")),
        away_registration_id=_optional_str(payload.get("away_registration_id")),
        home_score=_optional_int(payload.get("home_score")),
        away_score=_optional_int(payload.get("away_score")),
        kickoff=str(payload["kickoff"]),
        location=str(payload["location"]),
    )


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def event_structure_path(event_key: str, *, base_dir: Path | str = "reports") -> Path:
    return intake_dir(event_key, base_dir=base_dir) / _FILENAME


def write_event_structure(
    event_key: str, structure: EventStructure, *, base_dir: Path | str = "reports"
) -> None:
    """Persist ``structure``, refusing to replace a complete walk with a partial one.

    A probe reading two divisions costs pennies; a full walk of the same event
    can cost dollars. This is the single writer for the artifact, so the guard
    lives here rather than in any one caller — a CLI backfill, a
    recovery-restore flow, a second UI surface, or a test calling this
    function directly all get it automatically, the same way
    ``_write_event_roster_recovery`` protects its own paid artifact for every
    caller of *that* writer. Only a partial ``structure``
    (``is_complete=False``) landing on a path that already holds a complete
    one is refused; a complete structure may always replace whatever came
    before it, partial or complete.

    Raises ``StructureOverwriteRefused`` rather than silently declining: a
    writer that no-ops while its caller reports success is a worse bug than
    the one this closes. A caller that wants a friendly message instead of a
    traceback (the Backtest UI's save button) catches it and shows one.
    """
    path = event_structure_path(event_key, base_dir=base_dir)
    if not structure.is_complete and _holds_a_complete_structure(path):
        raise StructureOverwriteRefused(
            f"{path} already holds a complete structure; refusing to replace it with a partial one"
        )
    write_json(path, stamp_schema_version(structure.to_dict()))


def _holds_a_complete_structure(path: Path) -> bool:
    """Does ``path`` already hold a structure walked to completion?

    Read as raw JSON rather than through ``read_event_structure`` so a schema
    mismatch cannot itself raise here — an unreadable or missing file holds
    nothing to protect. Mirrors
    ``tournament_intake._recovery_holds_a_complete_walk``, the same guard the
    sibling recovery-file writer applies to its own paid artifact.
    """
    try:
        existing = read_json(path)
    except (OSError, ValueError):
        return False
    return isinstance(existing, dict) and existing.get("is_complete") is True


def read_event_structure(
    event_key: str, *, base_dir: Path | str = "reports"
) -> EventStructure:
    return EventStructure.from_dict(
        read_versioned_json(event_structure_path(event_key, base_dir=base_dir))
    )
