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
from src.tournaments.storage._io import read_versioned_json, write_json
from src.tournaments.storage.event_key import intake_dir
from src.tournaments.storage.schema_version import stamp_schema_version

__all__ = [
    "EventStructure",
    "division_from_dict",
    "event_structure_path",
    "read_event_structure",
    "write_event_structure",
]

_FILENAME = "event_structure.json"


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
        pool_id=str(payload.get("pool_id") or ""),
        label=str(payload.get("label") or ""),
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
        match_number=str(payload.get("match_number") or ""),
        bracket_label=str(payload.get("bracket_label") or ""),
        kind=str(payload["kind"]),
        home_registration_id=_optional_str(payload.get("home_registration_id")),
        away_registration_id=_optional_str(payload.get("away_registration_id")),
        home_score=_optional_int(payload.get("home_score")),
        away_score=_optional_int(payload.get("away_score")),
        kickoff=str(payload.get("kickoff") or ""),
        location=str(payload.get("location") or ""),
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
    write_json(
        event_structure_path(event_key, base_dir=base_dir),
        stamp_schema_version(structure.to_dict()),
    )


def read_event_structure(
    event_key: str, *, base_dir: Path | str = "reports"
) -> EventStructure:
    return EventStructure.from_dict(
        read_versioned_json(event_structure_path(event_key, base_dir=base_dir))
    )
