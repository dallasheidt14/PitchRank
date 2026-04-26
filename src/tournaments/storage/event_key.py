"""Event-key derivation, scaffolding paths, and the one-shot rekey migration.

Spec §6 defines the event-identity scheme as
``(provider_code, provider_event_id, season_year)``. Shell 01 left a
``__unknown`` placeholder for the season segment because it didn't yet own
the season convention. This module owns it.

**Back-compat with Shell 01 callers:** ``season_year`` is optional. When
``None``, derivation falls back to the legacy ``__unknown`` form so
existing callsites (e.g. ``src/scrapers/gotsport.py:2862-2869``) continue
to work without modification.

The rekey migration is non-destructive: directories that lack a derivable
season_year remain in place. A subsequent metadata refresh + rekey call
migrates them; the function never raises mid-loop.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.tournaments.storage._io import read_json
from src.tournaments.storage.schema_version import (
    SchemaVersionError,
    assert_supported_version,
)

__all__ = [
    "RekeyMigrationResult",
    "derive_season_year",
    "event_dir",
    "event_key",
    "intake_dir",
    "parse_event_key",
    "rekey_unknown_directories",
    "reports_dir",
    "run_dir",
    "scenario_dir",
    "scenarios_dir",
]


_MIN_SEASON_YEAR: int = 2000

_INVALID_SEGMENT_CHARS: tuple[str, ...] = ("/", "\\", "\x00")


def _validate_segment(value: str, *, label: str) -> None:
    """Reject empty / traversal / separator chars in a path segment.

    Defense-in-depth against ``..`` / ``/`` / ``\\`` reaching ``Path``
    joins. Internal callers (Streamlit, CLI) are operator-trusted today,
    but the helpers in this module are now part of the public storage
    surface — gate untrusted input at the constructor.
    """
    if not value:
        raise ValueError(f"{label} must be non-empty")
    if value in (".", ".."):
        raise ValueError(f"{label} must not be '.' or '..': {value!r}")
    for char in _INVALID_SEGMENT_CHARS:
        if char in value:
            raise ValueError(f"{label} must not contain {char!r}: {value!r}")


def event_key(
    provider_code: str,
    provider_event_id: str,
    season_year: int | None = None,
) -> str:
    """Return the canonical event key.

    With ``season_year`` provided, returns
    ``f"{provider_code}__{provider_event_id}__{season_year}"``. With
    ``season_year=None``, returns the legacy ``__unknown`` form so Shell 01
    callers don't need to populate the field.

    Raises ``ValueError`` if ``provider_code`` or ``provider_event_id`` is
    empty or contains the ``__`` segment separator, or if ``season_year`` is
    provided and is not an int >= 2000.
    """
    _validate_segment(provider_code, label="provider_code")
    _validate_segment(provider_event_id, label="provider_event_id")
    if "__" in provider_code:
        raise ValueError(f"provider_code must not contain '__': {provider_code!r}")
    if "__" in provider_event_id:
        raise ValueError(f"provider_event_id must not contain '__': {provider_event_id!r}")
    if season_year is None:
        return f"{provider_code}__{provider_event_id}__unknown"
    if not isinstance(season_year, int) or isinstance(season_year, bool):
        raise ValueError(f"season_year must be int, got {type(season_year).__name__}")
    if season_year < _MIN_SEASON_YEAR:
        raise ValueError(f"season_year must be >= {_MIN_SEASON_YEAR}, got {season_year}")
    return f"{provider_code}__{provider_event_id}__{season_year}"


def derive_season_year(event_start_date: str | None) -> int | None:
    """Parse the year of an ISO ``YYYY-MM-DD`` date, or ``None``.

    Strict ISO date — ``"2026"`` (year-only) and ``"2026-99-99"`` (invalid
    month/day) both return ``None``. The storage layer never silently
    invents a season_year; callers that have a reliable value from another
    source populate ``season_year`` directly.
    """
    if event_start_date is None:
        return None
    try:
        parsed = date.fromisoformat(event_start_date)
    except (TypeError, ValueError):
        return None
    if parsed.year < _MIN_SEASON_YEAR:
        return None
    return parsed.year


def parse_event_key(key: str) -> tuple[str, str, int | None]:
    """Split an event key into ``(provider_code, provider_event_id, season_year)``.

    Examples::

        parse_event_key("gotsport__45224__unknown") -> ("gotsport", "45224", None)
        parse_event_key("gotsport__45224__2026")    -> ("gotsport", "45224", 2026)
        parse_event_key("gotsport__45224__abcd")    raises ValueError

    The legacy ``unknown`` season segment is the ONLY non-int value
    accepted; any other non-int segment raises ``ValueError`` (the rekey
    migration is the sanctioned path for upgrading old keys).
    """
    parts = key.split("__")
    if len(parts) != 3:
        raise ValueError(f"event_key must have shape provider__eventid__season; got {key!r}")
    provider_code, provider_event_id, season_segment = parts
    if not provider_code or not provider_event_id:
        raise ValueError(f"event_key has empty segments: {key!r}")
    if season_segment == "unknown":
        return provider_code, provider_event_id, None
    if not season_segment.isdigit():
        raise ValueError(f"event_key season segment must be 'unknown' or an int; got {season_segment!r}")
    season_year = int(season_segment)
    if season_year < _MIN_SEASON_YEAR:
        raise ValueError(f"event_key season_year must be >= {_MIN_SEASON_YEAR}, got {season_year}")
    return provider_code, provider_event_id, season_year


def reports_dir(base_dir: Path | str = "reports") -> Path:
    """Return the root reports directory."""
    return Path(base_dir)


def event_dir(event_key: str, *, base_dir: Path | str = "reports") -> Path:
    """Return ``<reports>/<event_key>/``.

    The ``event_key`` string is treated as a single path segment — pre-formed
    keys still go through ``_validate_segment`` so a caller passing
    ``"../etc"`` directly to ``event_dir`` (bypassing the ``event_key()``
    constructor) cannot escape the reports root.
    """
    _validate_segment(event_key, label="event_key")
    return reports_dir(base_dir) / event_key


def intake_dir(event_key: str, *, base_dir: Path | str = "reports") -> Path:
    """Return ``<event_dir>/intake/`` — the immutable, scenario-shared intake tier."""
    return event_dir(event_key, base_dir=base_dir) / "intake"


def scenarios_dir(event_key: str, *, base_dir: Path | str = "reports") -> Path:
    """Return ``<event_dir>/scenarios/``."""
    return event_dir(event_key, base_dir=base_dir) / "scenarios"


def scenario_dir(event_key: str, name: str, *, base_dir: Path | str = "reports") -> Path:
    """Return ``<scenarios_dir>/<name>/``."""
    _validate_segment(name, label="scenario name")
    return scenarios_dir(event_key, base_dir=base_dir) / name


def run_dir(
    event_key: str,
    scenario: str,
    run_id: str,
    *,
    base_dir: Path | str = "reports",
) -> Path:
    """Return ``<scenario_dir>/runs/<run_id>/``."""
    _validate_segment(run_id, label="run_id")
    return scenario_dir(event_key, scenario, base_dir=base_dir) / "runs" / run_id


@dataclass(frozen=True)
class RekeyMigrationResult:
    """Per-call summary of ``rekey_unknown_directories``.

    All tuples for immutability. ``failed`` and ``unmigrated`` are
    informational — the function never raises mid-loop, so the caller is
    responsible for surfacing these to the operator (e.g. a Streamlit
    startup banner).
    """

    completed: tuple[tuple[str, str], ...]
    """``(old_key, new_key)`` pairs that renamed successfully."""

    failed: tuple[tuple[str, str], ...]
    """``(old_key, error_str)`` pairs whose rename or read failed."""

    unmigrated: tuple[str, ...]
    """``old_key`` entries that lack ``intake/event_metadata.json``."""


def rekey_unknown_directories(
    base_dir: Path | str = "reports",
) -> RekeyMigrationResult:
    """Migrate ``<provider>__<eventid>__unknown/`` to season-stamped names.

    Idempotent: a second call on the same ``base_dir`` finds no matching
    directories and returns empty results. Non-destructive: directories
    that fail to migrate (no derivable season_year, destination already
    exists) remain in place and the function returns their reasons in
    ``failed``. The function never raises mid-loop.
    """
    root = Path(base_dir)
    if not root.exists():
        return RekeyMigrationResult(completed=(), failed=(), unmigrated=())

    completed: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []
    unmigrated: list[str] = []

    for entry in sorted(root.iterdir()):
        old_key = entry.name
        try:
            if not entry.is_dir() or not old_key.endswith("__unknown"):
                continue

            metadata_path = entry / "intake" / "event_metadata.json"
            if not metadata_path.exists():
                unmigrated.append(old_key)
                continue

            payload = read_json(metadata_path)
            assert_supported_version(payload, source=str(metadata_path))
            season = derive_season_year(payload.get("event_start_date"))
            if season is None:
                failed.append((old_key, "no derivable season_year"))
                continue

            provider_code, provider_event_id, _ = parse_event_key(old_key)
            new_key = event_key(provider_code, provider_event_id, season)
            new_dir = root / new_key
            if new_dir.exists():
                failed.append((old_key, "destination already exists"))
                continue

            os.replace(entry, new_dir)
            completed.append((old_key, new_key))
        except (
            FileNotFoundError,
            FileExistsError,
            OSError,
            json.JSONDecodeError,
            ValueError,
            SchemaVersionError,
        ) as exc:
            failed.append((old_key, str(exc)))

    return RekeyMigrationResult(
        completed=tuple(completed),
        failed=tuple(failed),
        unmigrated=tuple(unmigrated),
    )
