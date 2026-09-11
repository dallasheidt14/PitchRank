"""One coherent, reloadable snapshot of a completed-event intake.

The UI publishes this object with one session-state assignment. Structure,
entrants and event identity therefore cannot come from different interrupted
walks. This module writes local intake artifacts only, never the team database.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.tournaments.backtest_result_summary import tournament_result_summary
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


class ReviewConflict(ValueError):
    """Another session changed the same review field since it was loaded."""


@dataclass(frozen=True)
class DivisionReview:
    group_id: str
    structure_hash: str
    notes: str = ""
    source_url: str = ""
    checked: bool = False


@dataclass(frozen=True)
class CohortDecision:
    """A sourced operator interpretation of one published division cohort."""

    group_id: str
    age_group: str
    gender: str
    note: str
    source_url: str


@dataclass(frozen=True)
class CaptureVerification:
    """The most recent landing-only check of a saved capture's division list."""

    group_ids: tuple[str, ...]
    observed_counts: tuple[int, ...]
    verified_at: str
    stable: bool


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
        "results": tournament_result_summary(roster),
    }


@dataclass(frozen=True)
class BacktestSnapshot:
    roster: EventRoster
    resolved: tuple[ResolvedTeam, ...]
    generation: str
    captured_at: str
    limit_groups: int | None = None
    reviews: tuple[DivisionReview, ...] = ()
    cohort_decisions: tuple[CohortDecision, ...] = ()
    verification: CaptureVerification | None = None

    def __post_init__(self) -> None:
        expected = [team.source_index for team in self.roster.teams]
        actual = [item.source_index for item in self.resolved]
        if len(set(expected)) != len(expected) or sorted(expected) != sorted(actual):
            raise ValueError("Every captured entrant must have exactly one matching outcome")
        if not self.generation or not self.captured_at:
            raise ValueError("An intake needs its capture identity and timestamp")
        group_ids = {division.group_id for division in self.roster.divisions}
        decided = set()
        for decision in self.cohort_decisions:
            if decision.group_id in decided or decision.group_id not in group_ids:
                raise ValueError("Cohort decisions must identify one captured division")
            decided.add(decision.group_id)
            if not re.fullmatch(r"u[0-9]{1,2}(?:/u[0-9]{1,2})*", decision.age_group):
                raise ValueError("Cohort decisions need a lowercase U-age or combined U-age")
            if decision.gender not in {"Male", "Female"}:
                raise ValueError("Cohort decisions need a gender")
            if not decision.note.strip() or not decision.source_url.strip():
                raise ValueError("Cohort decisions need a note and source URL")
        if self.verification is not None:
            verification = self.verification
            if (
                type(verification.stable) is not bool
                or not isinstance(verification.verified_at, str)
                or not verification.verified_at.strip()
                or len(set(verification.group_ids)) != len(verification.group_ids)
                or any(not isinstance(group, str) or not group.strip() for group in verification.group_ids)
                or any(type(count) is not int or count < 0 for count in verification.observed_counts)
            ):
                raise ValueError("Invalid capture verification metadata")

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
            "cohort_decisions": [asdict(decision) for decision in self.cohort_decisions],
            "capture_verification": asdict(self.verification) if self.verification else None,
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
            cohort_decisions=tuple(CohortDecision(**item) for item in payload.get("cohort_decisions", ())),
            verification=(
                CaptureVerification(
                    group_ids=tuple(payload["capture_verification"].get("group_ids", ())),
                    observed_counts=tuple(payload["capture_verification"].get("observed_counts", ())),
                    verified_at=payload["capture_verification"]["verified_at"],
                    stable=payload["capture_verification"]["stable"],
                )
                if payload.get("capture_verification") else None
            ),
        )


def effective_roster(snapshot: BacktestSnapshot) -> EventRoster:
    """Apply review-time cohort interpretations without changing source evidence."""
    decisions = {decision.group_id: decision for decision in snapshot.cohort_decisions}
    if not decisions:
        return snapshot.roster
    divisions = tuple(
        replace(
            division,
            age_group=decisions[division.group_id].age_group,
            published_age_group=decisions[division.group_id].age_group,
            gender=decisions[division.group_id].gender,
        )
        if division.group_id in decisions else division
        for division in snapshot.roster.divisions
    )
    teams = tuple(
        replace(
            team,
            published_age_group=decisions[team.group_id].age_group,
            gender=decisions[team.group_id].gender,
        )
        if team.group_id in decisions else team
        for team in snapshot.roster.teams
    )
    return replace(snapshot.roster, divisions=divisions, teams=teams)


def snapshot_path(event_key: str, *, base_dir: Path | str = "reports") -> Path:
    return intake_dir(event_key, base_dir=base_dir) / "event_intake.json"


def read_snapshot(event_key: str, *, base_dir: Path | str = "reports") -> BacktestSnapshot:
    snapshot = BacktestSnapshot.from_dict(read_versioned_json(snapshot_path(event_key, base_dir=base_dir)))
    if parse_event_key(event_key)[:2] != ("gotsport", snapshot.roster.event_id):
        raise ValueError("Saved event identity disagrees with its directory")
    return snapshot


def reviews_for_capture(roster: EventRoster, reviews: tuple[DivisionReview, ...]) -> tuple[DivisionReview, ...]:
    """Retain operator notes across a new capture, invalidating changed checks."""
    divisions = {division.group_id: division for division in roster.divisions}
    aligned = []
    seen = set()
    for review in reviews:
        if review.group_id in seen:
            raise ValueError(f"Duplicate review for division {review.group_id}")
        seen.add(review.group_id)
        if review.group_id not in divisions:
            continue
        digest = structure_hash(divisions[review.group_id])
        aligned.append(review if review.structure_hash == digest else replace(
            review, structure_hash=digest, checked=False
        ))
    return tuple(aligned)


def _merge_reviews(
    previous: BacktestSnapshot,
    incoming: BacktestSnapshot,
    baseline: tuple[DivisionReview, ...] | None,
) -> tuple[DivisionReview, ...]:
    """Merge only intentional edits; omission never deletes prior operator work."""
    current = {review.group_id: review for review in reviews_for_capture(incoming.roster, previous.reviews)}
    proposed = {review.group_id: review for review in reviews_for_capture(incoming.roster, incoming.reviews)}
    before = {review.group_id: review for review in reviews_for_capture(incoming.roster, baseline or ())}
    merged = []
    for division in incoming.roster.divisions:
        group = division.group_id
        if group not in current and group not in proposed:
            continue
        empty = DivisionReview(group, structure_hash(division))
        latest = current.get(group, empty)
        desired = proposed.get(group)
        if desired is None:
            merged.append(latest)
            continue
        if baseline is None:
            # A caller without the version it edited cannot distinguish an
            # intentional clear from a fresh or stale capture's empty defaults.
            if group not in current or desired == latest:
                merged.append(desired)
            elif desired == empty:
                merged.append(latest)
            else:
                raise ReviewConflict(f"Division {group}: load saved reviews before changing them")
            continue
        original = before.get(group, empty)
        values = {}
        for field in ("notes", "source_url", "checked"):
            wanted = getattr(desired, field)
            prior = getattr(original, field)
            saved = getattr(latest, field)
            if wanted == prior:
                values[field] = saved
            elif saved == prior or saved == wanted:
                values[field] = wanted
            else:
                raise ReviewConflict(
                    f"Division {group}: {field.replace('_', ' ')} changed in another session. "
                    "Open the saved intake before applying this edit."
                )
        merged.append(DivisionReview(group, empty.structure_hash, **values))
    return tuple(merged)


def _merge_cohort_decisions(
    previous: BacktestSnapshot,
    incoming: BacktestSnapshot,
    baseline: tuple[CohortDecision, ...] | None,
) -> tuple[CohortDecision, ...]:
    """Merge sourced cohort edits without letting stale omission erase work."""
    valid_groups = {division.group_id for division in incoming.roster.divisions}
    current = {item.group_id: item for item in previous.cohort_decisions if item.group_id in valid_groups}
    proposed = {item.group_id: item for item in incoming.cohort_decisions if item.group_id in valid_groups}
    before = {item.group_id: item for item in (baseline or ()) if item.group_id in valid_groups}
    merged = []
    for group in valid_groups:
        latest = current.get(group)
        desired = proposed.get(group)
        if desired is None:
            if latest is not None:
                merged.append(latest)
            continue
        if baseline is None:
            if latest is None or latest == desired:
                merged.append(desired)
            else:
                merged.append(latest)
            continue
        original = before.get(group)
        if desired == original:
            if latest is not None:
                merged.append(latest)
        elif latest is None or latest == original or latest == desired:
            merged.append(desired)
        else:
            raise ReviewConflict(
                f"Division {group}: cohort decision changed in another session. "
                "Open the saved intake before applying this edit."
            )
    return tuple(sorted(merged, key=lambda item: item.group_id))


def _fixture_source_identity(fixture: Any) -> tuple[str, str, str] | None:
    """A provider match link identifies a game; a division URL alone does not."""
    from urllib.parse import parse_qs, urlsplit

    parsed = urlsplit(fixture.source_url)
    match_ids = parse_qs(parsed.query).get("match", ())
    if len(match_ids) != 1 or not match_ids[0].isascii() or not match_ids[0].isdigit():
        return None
    return parsed.netloc.casefold(), parsed.path, match_ids[0]


def _fixture_evidence_level(field: str, value: Any) -> int:
    # Scores of zero are evidence. Truthiness would silently waive their loss.
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0
    if field == "kind":
        return 0 if value == "unknown" else 2
    if field == "result_status":
        if value in {"not_captured", "unknown"}:
            return 0
        return 1 if value in {"unrecognized", "unplayed"} else 2
    if field == "result_text" and value.strip().casefold() in {"-", "vs", "vs."}:
        return 1
    return 2


def _fixture_source_refined(previous: str, fresh: str) -> bool:
    """Adding a match id to the same division URL adds source precision."""
    from urllib.parse import parse_qs, urlsplit

    old, new = urlsplit(previous), urlsplit(fresh)
    old_query, new_query = parse_qs(old.query), parse_qs(new.query)
    if "match" in old_query or "match" not in new_query:
        return False
    new_query.pop("match")
    return (old.scheme, old.netloc, old.path, old_query) == (new.scheme, new.netloc, new.path, new_query)


def _fixture_evidence_preserved(previous: Any, fresh: Any, *, corrections: bool) -> bool:
    """Known evidence cannot become absent or uninterpretable.

    A uniquely identified game may carry corrected nonempty source values.
    Without that identity, existing values must agree: arbitrary row order or
    a repeated match number cannot establish which game a correction belongs
    to. Unknown fields can gain evidence in either case.
    """
    old_values, new_values = asdict(previous), asdict(fresh)
    source_id = _fixture_source_identity(previous)
    if source_id and source_id != _fixture_source_identity(fresh):
        return False
    deciding_scores = (
        (fresh.home_shootout_score, fresh.away_shootout_score)
        if fresh.home_shootout_score is not None or fresh.away_shootout_score is not None
        else (fresh.home_score, fresh.away_score)
    )
    corrected_draw = (
        corrections and fresh.result_status == "played" and not fresh.winner_side
        and fresh.winner_registration_id is None and deciding_scores[0] is not None
        and deciding_scores[0] == deciding_scores[1]
    )
    for field, old_value in old_values.items():
        new_value = new_values.get(field)
        old_level = _fixture_evidence_level(field, old_value)
        new_level = _fixture_evidence_level(field, new_value)
        if corrected_draw and field in {"winner_side", "winner_registration_id"}:
            continue  # A corrected draw has no winning side to preserve.
        if new_level < old_level:
            return False
        if old_level and old_value != new_value and not corrections:
            if new_level > old_level:
                continue
            if field == "source_url" and _fixture_source_refined(old_value, new_value):
                continue
            return False
    return True


def _fixtures_preserved(previous: Any, fresh: Any) -> bool:
    """Pair rows one-to-one, independent of order and duplicate match numbers.

    Provider match links or unique published numbers permit source corrections.
    Unnumbered/duplicate rows need compatible evidence. An augmenting-path
    match prevents either greedily rejecting enrichment or reusing one richer
    fresh row to stand in for multiple old rows.
    """
    old_source = [_fixture_source_identity(fixture) for fixture in previous]
    new_source = [_fixture_source_identity(fixture) for fixture in fresh]
    old_source_counts, new_source_counts = Counter(old_source), Counter(new_source)
    old_numbers = Counter(f.match_number for f in previous)
    new_numbers = Counter(f.match_number for f in fresh)
    candidates: list[list[int]] = []
    for old_index, old_fixture in enumerate(previous):
        compatible = []
        for new_index, new_fixture in enumerate(fresh):
            old_id, new_id = old_source[old_index], new_source[new_index]
            same_source = bool(old_id and old_id == new_id)
            same_number = bool(old_fixture.match_number and old_fixture.match_number == new_fixture.match_number)
            if old_id and old_id != new_id:
                continue
            if old_fixture.match_number and not same_number and not same_source:
                continue
            corrections = (
                (same_source and old_source_counts[old_id] == new_source_counts[new_id] == 1)
                or (same_number and old_numbers[old_fixture.match_number] == new_numbers[new_fixture.match_number] == 1)
            )
            if _fixture_evidence_preserved(old_fixture, new_fixture, corrections=corrections):
                compatible.append(new_index)
        candidates.append(compatible)

    matched_new: dict[int, int] = {}
    matched_old: dict[int, int] = {}
    for start in range(len(previous)):
        queue = [start]
        visited_old = {start}
        reached_by: dict[int, int] = {}
        free = None
        for old_index in queue:
            for new_index in candidates[old_index]:
                if new_index in reached_by:
                    continue
                reached_by[new_index] = old_index
                if new_index not in matched_new:
                    free = new_index
                    break
                owner = matched_new[new_index]
                if owner not in visited_old:
                    visited_old.add(owner)
                    queue.append(owner)
            if free is not None:
                break
        if free is None:
            return False
        while free is not None:
            owner = reached_by[free]
            displaced = matched_old.get(owner)
            matched_new[free] = owner
            matched_old[owner] = free
            free = displaced
    return True


def assert_capture_preserved(previous: EventRoster, fresh: EventRoster) -> None:
    """Refuse omitted evidence; allow identified games' nonempty corrections.

    This is an omission guard, not an assertion that a provider can never
    correct a published result. Removing previously known facts requires
    retaining/reviewing the richer capture rather than silently replacing it.
    """
    if previous.event_id != fresh.event_id:
        raise IntakeOverwriteRefused("The saved capture belongs to another event")
    old_teams = {(team.group_id, entrant_key(team)) for team in previous.teams}
    new_teams = {(team.group_id, entrant_key(team)) for team in fresh.teams}
    old_divisions = {division.group_id: division for division in previous.divisions}
    new_divisions = {division.group_id: division for division in fresh.divisions}

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
        or not _fixtures_preserved(division.fixtures, new_divisions[group].fixtures)
        for group, division in old_divisions.items() if group in new_divisions
    )
    if ((previous.is_complete and not fresh.is_complete) or not old_teams <= new_teams
            or not old_divisions.keys() <= new_divisions.keys()
            or downgraded):
        raise IntakeOverwriteRefused("A larger capture is saved; load it before saving this event")


def write_snapshot(
    event_key: str, snapshot: BacktestSnapshot, *, base_dir: Path | str = "reports", dry_run: bool = False,
    review_baseline: tuple[DivisionReview, ...] | None = None,
    cohort_baseline: tuple[CohortDecision, ...] | None = None,
) -> Path:
    """Save atomically and merge review edits against the caller's loaded baseline.

    Without a baseline, existing nonempty reviews cannot be changed. This lets
    fresh captures keep saved review work without treating their defaults as edits.
    """
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
            snapshot = replace(
                snapshot,
                reviews=_merge_reviews(previous, snapshot, review_baseline),
                cohort_decisions=_merge_cohort_decisions(previous, snapshot, cohort_baseline),
            )
        else:
            snapshot = replace(snapshot, reviews=reviews_for_capture(snapshot.roster, snapshot.reviews))
        write_json(path, snapshot.to_dict())
    return path
