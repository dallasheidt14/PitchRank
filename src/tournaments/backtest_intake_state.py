"""One coherent, reloadable snapshot of a completed-event intake.

The UI publishes this object with one session-state assignment. Structure,
entrants and event identity therefore cannot come from different interrupted
walks. This module writes local intake artifacts only, never the team database.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.tournaments.event_roster_intake import to_seeding_rows
from src.tournaments.gotsport_event_roster import (
    EventRoster,
    event_roster_from_dict,
    event_roster_to_dict,
)
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.storage._file_lock import _acquire_file_lock
from src.tournaments.storage._io import read_versioned_json, utc_now_iso, write_json
from src.tournaments.storage.event_key import intake_dir, parse_event_key
from src.tournaments.storage.schema_version import stamp_schema_version


class IntakeOverwriteRefused(ValueError):
    """Saving would discard a more complete capture of this event."""


@dataclass(frozen=True)
class DivisionReview:
    group_id: str
    structure_hash: str
    notes: str = ""
    source_url: str = ""
    checked: bool = False


def structure_hash(division: Any) -> str:
    encoded = json.dumps(asdict(division), sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def entrant_key(team: Any) -> str:
    """A local link key; missing provider IDs remain missing in the raw record."""
    return (team.registration_id or getattr(team, "source_entry_key", "")
            or f"unidentified:{team.group_id}:{team.source_index}")


def tournament_totals(roster: EventRoster) -> dict[str, Any]:
    """Count registrations in the event's entered divisions, never DB ages.

    A team playing up belongs to its tournament bracket. Registration IDs are
    unique within the event; a registration entered in two different cohorts
    appears in each cohort, while the overall team total counts it once.
    """
    divisions = {division.group_id: division for division in roster.divisions}
    cohorts: dict[tuple[str, str], set[str]] = {}
    all_teams: set[str] = set()
    entries: set[tuple[str, str]] = set()
    for team in roster.teams:
        division = divisions.get(team.group_id)
        age = division.age_group if division else getattr(team, "published_age_group", "")
        gender = division.gender if division else team.gender
        key = entrant_key(team)
        all_teams.add(key)
        entries.add((team.group_id, key))
        cohorts.setdefault((age, gender), set()).add(key)

    def sort_key(item):
        age, gender = item[0]
        age_number = int(age[1:]) if age.startswith("u") and age[1:].isascii() and age[1:].isdigit() else 999
        return age_number, gender

    rows = [
        {"Tournament cohort": age.upper() or "Not stated",
         "Gender": {"Male": "Boys", "Female": "Girls"}.get(gender, gender or "Not stated"),
         "Teams": len(ids)}
        for (age, gender), ids in sorted(cohorts.items(), key=sort_key)
    ]
    return {
        "event_name": getattr(roster, "event_name", "") or f"GotSport event {roster.event_id}",
        "total_teams": len(all_teams),
        "division_entries": len(entries),
        "cohort_entries": sum(row["Teams"] for row in rows),
        "cohorts": rows,
        "divisions": len(roster.divisions),
        "pools": sum(len(division.pools) for division in roster.divisions),
        "fixtures": sum(len(division.fixtures) for division in roster.divisions),
        "unidentified_teams": len({entrant_key(team) for team in roster.teams if not team.registration_id}),
    }


@dataclass(frozen=True)
class BacktestSnapshot:
    roster: EventRoster
    resolved: tuple[ResolvedTeam, ...]
    generation: str
    captured_at: str
    limit_groups: int | None = None
    reviews: tuple[DivisionReview, ...] = ()

    def __post_init__(self) -> None:
        expected = [team.source_index for team in self.roster.teams]
        actual = [item.source_index for item in self.resolved]
        if len(set(expected)) != len(expected) or sorted(expected) != sorted(actual):
            raise ValueError("Every captured entrant must have exactly one matching outcome")
        if not self.generation or not self.captured_at:
            raise ValueError("An intake needs its capture identity and timestamp")

    @property
    def parsed(self):
        return to_seeding_rows(self.roster, {})[0]

    @classmethod
    def create(cls, roster: EventRoster, resolved, *, limit_groups=None) -> BacktestSnapshot:
        return cls(roster, tuple(resolved), uuid4().hex, utc_now_iso(), limit_groups)

    def with_resolution(self, parsed, resolved, *, generation: str) -> BacktestSnapshot:
        if generation != self.generation or parsed.rows != self.parsed.rows:
            raise ValueError("Matching results belong to another event capture")
        return replace(self, resolved=tuple(resolved))

    def to_dict(self) -> dict[str, Any]:
        return stamp_schema_version({
            "generation": self.generation,
            "captured_at": self.captured_at,
            "limit_groups": self.limit_groups,
            "roster": event_roster_to_dict(self.roster),
            "resolved": [asdict(item) for item in self.resolved],
            "division_reviews": [asdict(review) for review in self.reviews],
        })

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BacktestSnapshot:
        limit = payload.get("limit_groups")
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError("Invalid division limit")
        return cls(
            roster=event_roster_from_dict(payload["roster"]),
            resolved=tuple(
                ResolvedTeam(**{**item, "candidates": tuple(item.get("candidates") or ())})
                for item in payload["resolved"]
            ),
            generation=payload["generation"],
            captured_at=payload["captured_at"],
            limit_groups=limit,
            reviews=tuple(DivisionReview(**item) for item in payload.get("division_reviews", ())),
        )


def snapshot_path(event_key: str, *, base_dir: Path | str = "reports") -> Path:
    return intake_dir(event_key, base_dir=base_dir) / "event_intake.json"


def read_snapshot(event_key: str, *, base_dir: Path | str = "reports") -> BacktestSnapshot:
    snapshot = BacktestSnapshot.from_dict(read_versioned_json(snapshot_path(event_key, base_dir=base_dir)))
    if parse_event_key(event_key)[:2] != ("gotsport", snapshot.roster.event_id):
        raise ValueError("Saved event identity disagrees with its directory")
    return snapshot


def assert_capture_preserved(previous: EventRoster, fresh: EventRoster) -> None:
    """Refuse a replacement that loses already captured event evidence."""
    if previous.event_id != fresh.event_id:
        raise IntakeOverwriteRefused("The saved capture belongs to another event")
    old_teams = {(team.group_id, entrant_key(team)) for team in previous.teams}
    new_teams = {(team.group_id, entrant_key(team)) for team in fresh.teams}
    old_divisions = {division.group_id: division for division in previous.divisions}
    new_divisions = {division.group_id: division for division in fresh.divisions}
    old_fixtures = Counter((d.group_id, f.match_number or f"row:{index}")
                           for d in previous.divisions for index, f in enumerate(d.fixtures))
    new_fixtures = Counter((d.group_id, f.match_number or f"row:{index}")
                           for d in fresh.divisions for index, f in enumerate(d.fixtures))

    def pool_members(division):
        return Counter(
            (pool.pool_id or f"row:{index}", member.registration_id
             or f"row:{member.standings_position}:{member.team_name}")
            for index, pool in enumerate(division.pools) for member in pool.members
        )

    downgraded = any(
        (division.pools_readable and not new_divisions[group].pools_readable)
        or (division.fixtures_readable and not new_divisions[group].fixtures_readable)
        or len(division.pools) > len(new_divisions[group].pools)
        or bool(pool_members(division) - pool_members(new_divisions[group]))
        for group, division in old_divisions.items() if group in new_divisions
    )
    if ((previous.is_complete and not fresh.is_complete) or not old_teams <= new_teams
            or bool(old_fixtures - new_fixtures) or not old_divisions.keys() <= new_divisions.keys()
            or downgraded):
        raise IntakeOverwriteRefused("A larger capture is saved; load it before saving this event")


def write_snapshot(
    event_key: str, snapshot: BacktestSnapshot, *, base_dir: Path | str = "reports", dry_run: bool = False
) -> Path:
    """Save the entire capture atomically; a probe cannot replace a larger walk."""
    if parse_event_key(event_key)[:2] != ("gotsport", snapshot.roster.event_id):
        raise ValueError("Refusing to save this capture under another event")
    path = snapshot_path(event_key, base_dir=base_dir)
    if dry_run:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with _acquire_file_lock(path.with_suffix(".lock"), timeout=1.0):
        if path.exists():
            previous = read_snapshot(event_key, base_dir=base_dir)
            assert_capture_preserved(previous.roster, snapshot.roster)
        write_json(path, snapshot.to_dict())
    return path
