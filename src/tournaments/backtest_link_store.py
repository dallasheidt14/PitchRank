"""Save and reload the team links a backtest walk produced.

A walk's links are two things: what the resolver settled on its own, and the
fixes an operator entered by hand. The manual ones are the expensive part — each
is a lookup on the provider's site — and without this they live only in a
Streamlit session, so a refresh throws them away.

Links live beside the event's other intake artifacts, at
``reports/<event_key>/intake/event_links.json``, rather than under the
``reports/seeding/<slug>/`` layout ``seeding_run_store`` uses. That store slugs
an operator-typed name because a pasted roster has no provider event id; a walk
has one and forms a real ``event_key``, so it needs no name.

Keyed by registration id, never by roster position. A re-walk that loses a
division to an unreadable page shifts every later position, so a position cannot
carry a manual fix from one walk to the next — measured on event 51783, where
two walks an hour apart disagreed by a division.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.tournaments.roster_paste import RosterRow
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.storage._file_lock import FileLockError, _acquire_file_lock
from src.tournaments.storage._io import write_json
from src.tournaments.storage.event_key import intake_dir, parse_event_key
from src.tournaments.storage.schema_version import (
    assert_supported_version,
    stamp_schema_version,
)

logger = logging.getLogger(__name__)

__all__ = [
    "EVENT_LINKS_FILENAME",
    "EventLinks",
    "EventLinksError",
    "EventLinksLockError",
    "EventLinksConflict",
    "CollisionAcknowledgement",
    "TeamLink",
    "build_links",
    "event_links_path",
    "link_decision_state",
    "generations_agree",
    "registration_map",
    "rows_fingerprint",
    "load_links",
    "restore_overrides",
    "save_links",
    "update_links",
]

EVENT_LINKS_FILENAME = "event_links.json"

MATCHED_BY_OPERATOR = "operator"


class EventLinksError(RuntimeError):
    """Saved link decisions cannot safely be read or changed."""


class EventLinksLockError(EventLinksError):
    """Another session is still changing this event's links."""


class EventLinksConflict(EventLinksError):
    """Another session changed a team link after this editor loaded it."""


@dataclass(frozen=True)
class TeamLink:
    """One event team tied to a team in our database."""

    registration_id: str
    event_team_name: str
    team_id_master: str
    matched_by: str
    """``gotsport_id`` / ``exact_name`` from the resolver, or ``operator``."""

    linked_at: str


@dataclass(frozen=True)
class CollisionAcknowledgement:
    """An operator confirmed several event entries intentionally name one squad."""

    team_id_master: str
    registration_ids: tuple[str, ...]
    note: str
    acknowledged_at: str


@dataclass(frozen=True)
class EventLinks:
    event_id: str = ""
    links: tuple[TeamLink, ...] = ()
    saved_at: str = ""
    removed_registration_ids: tuple[str, ...] = ()
    """Explicitly cleared registrations; only a new operator choice revives one."""
    not_found_registration_ids: tuple[str, ...] = ()
    """Entrants an operator checked and could not find in PitchRank."""
    collision_acknowledgements: tuple[CollisionAcknowledgement, ...] = ()


_NOT_FOUND_STATE = "decision:not-found"
_REMOVED_STATE = "decision:removed"


def link_decision_state(links: EventLinks, registration_id: str) -> str | None:
    """Return the complete saved state used for stale-session checks."""
    by_registration = {link.registration_id: link.team_id_master for link in links.links}
    if registration_id in by_registration:
        return by_registration[registration_id]
    if registration_id in links.not_found_registration_ids:
        return _NOT_FOUND_STATE
    if registration_id in links.removed_registration_ids:
        return _REMOVED_STATE
    return None


def event_links_path(event_key: str, *, base_dir: Path | str = "reports") -> Path:
    return intake_dir(event_key, base_dir=base_dir) / EVENT_LINKS_FILENAME


def save_links(
    event_key: str, links: EventLinks, *, base_dir: Path | str = "reports"
) -> Path:
    """Merge a legacy snapshot without erasing other sessions' decisions.

    Omission does not delete a link, and a stale snapshot cannot revive a
    cleared registration. Use ``update_links`` for explicit edits and clears.
    """
    _update_links(
        event_key,
        event_id=links.event_id,
        changed_links=links.links,
        removed_registration_ids=links.removed_registration_ids,
        not_found_registration_ids=links.not_found_registration_ids,
        collision_acknowledgements=links.collision_acknowledgements,
        base_dir=base_dir,
        allow_relink=False,
    )
    return event_links_path(event_key, base_dir=base_dir)


def _merge_decisions(
    saved: EventLinks,
    fresh: EventLinks,
    *,
    allow_relink: bool,
) -> EventLinks:
    if saved.event_id and fresh.event_id and saved.event_id != fresh.event_id:
        raise EventLinksError("Cannot merge links from different events")
    removed = set(saved.removed_registration_ids) | set(fresh.removed_registration_ids)
    not_found = set(saved.not_found_registration_ids) | set(fresh.not_found_registration_ids)
    explicit_removals = set(fresh.removed_registration_ids)
    explicit_not_found = set(fresh.not_found_registration_ids)
    by_id = {
        link.registration_id: link
        for link in saved.links
        if link.registration_id not in removed and link.registration_id not in explicit_not_found
    }
    for link in fresh.links:
        if link.registration_id in explicit_removals:
            continue
        if link.registration_id in removed:
            if not allow_relink or link.matched_by != MATCHED_BY_OPERATOR:
                continue
            removed.remove(link.registration_id)
        if link.registration_id in not_found:
            if not allow_relink or link.matched_by != MATCHED_BY_OPERATOR:
                continue
            not_found.remove(link.registration_id)
        previous = by_id.get(link.registration_id)
        if previous is not None:
            if previous.matched_by == MATCHED_BY_OPERATOR and link.matched_by != MATCHED_BY_OPERATOR:
                continue
            if (
                previous.team_id_master == link.team_id_master
                and previous.matched_by == link.matched_by
                and previous.event_team_name == link.event_team_name
            ):
                continue  # A rerender's new linked_at is not a new decision.
        by_id[link.registration_id] = link
        not_found.discard(link.registration_id)
    acknowledged = {
        **{item.team_id_master: item for item in saved.collision_acknowledgements},
        **{item.team_id_master: item for item in fresh.collision_acknowledgements},
    }
    return EventLinks(
        event_id=fresh.event_id or saved.event_id,
        links=tuple(by_id.values()),
        saved_at=saved.saved_at,
        removed_registration_ids=tuple(sorted(removed)),
        not_found_registration_ids=tuple(sorted(not_found - removed)),
        collision_acknowledgements=tuple(acknowledged.values()),
    )


def update_links(
    event_key: str,
    *,
    event_id: str,
    changed_links: Sequence[TeamLink] = (),
    removed_registration_ids: Sequence[str] = (),
    not_found_registration_ids: Sequence[str] = (),
    reopened_registration_ids: Sequence[str] = (),
    collision_acknowledgements: Sequence[CollisionAcknowledgement] = (),
    expected_links: Mapping[str, str | None] | None = None,
    base_dir: Path | str = "reports",
    dry_run: bool = False,
) -> EventLinks:
    """Atomically apply explicit changes against this event's latest decisions.

    Automatic matches cannot replace operator choices or clear tombstones.
    An explicit operator link can relink a previously cleared registration.
    Pass only changed rows, not a full session snapshot. The returned snapshot
    includes other sessions' links and all removals so the UI can display and
    edit saved choices without turning them into permanent session overrides.
    ``dry_run`` returns the proposed merge without creating or changing files.
    """
    return _update_links(
        event_key,
        event_id=event_id,
        changed_links=changed_links,
        removed_registration_ids=removed_registration_ids,
        not_found_registration_ids=not_found_registration_ids,
        reopened_registration_ids=reopened_registration_ids,
        collision_acknowledgements=collision_acknowledgements,
        expected_links=expected_links,
        base_dir=base_dir,
        allow_relink=True,
        dry_run=dry_run,
    )


def _update_links(
    event_key: str,
    *,
    event_id: str,
    changed_links: Sequence[TeamLink],
    removed_registration_ids: Sequence[str],
    not_found_registration_ids: Sequence[str] = (),
    reopened_registration_ids: Sequence[str] = (),
    collision_acknowledgements: Sequence[CollisionAcknowledgement] = (),
    expected_links: Mapping[str, str | None] | None = None,
    base_dir: Path | str,
    allow_relink: bool,
    dry_run: bool = False,
) -> EventLinks:
    path = event_links_path(event_key, base_dir=base_dir)
    expected_id = parse_event_key(event_key)[1]
    if event_id != expected_id:
        raise EventLinksError(f"Event id {event_id!r} does not match {event_key!r}")
    fresh = EventLinks(
        event_id=event_id,
        links=tuple(changed_links),
        removed_registration_ids=tuple(removed_registration_ids),
        not_found_registration_ids=tuple(not_found_registration_ids),
        collision_acknowledgements=tuple(collision_acknowledgements),
    )
    _validate_links(fresh)

    def apply() -> EventLinks:
        try:
            saved = _load_links_strict(path, expected_id=expected_id)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise EventLinksError(f"Refusing to overwrite unreadable links at {path}: {exc}") from exc
        if expected_links is not None:
            for registration_id, expected in expected_links.items():
                if link_decision_state(saved, registration_id) != expected:
                    raise EventLinksConflict(
                        f"{registration_id} changed in another session; reopen the saved intake"
                    )
        reopened = set(reopened_registration_ids)
        if reopened:
            saved = EventLinks(
                event_id=saved.event_id,
                links=saved.links,
                saved_at=saved.saved_at,
                removed_registration_ids=saved.removed_registration_ids,
                not_found_registration_ids=tuple(
                    item for item in saved.not_found_registration_ids if item not in reopened
                ),
                collision_acknowledgements=saved.collision_acknowledgements,
            )
        merged = _merge_decisions(saved, fresh, allow_relink=allow_relink)
        if dry_run or merged == saved:
            return merged
        saved_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        write_json(
            path,
            stamp_schema_version(
                {
                    "event_id": merged.event_id,
                    "saved_at": saved_at,
                    "links": [asdict(link) for link in merged.links],
                    "removed_registration_ids": list(merged.removed_registration_ids),
                    "not_found_registration_ids": list(merged.not_found_registration_ids),
                    "collision_acknowledgements": [asdict(item) for item in merged.collision_acknowledgements],
                }
            ),
        )
        return EventLinks(
            event_id=merged.event_id,
            links=merged.links,
            saved_at=saved_at,
            removed_registration_ids=merged.removed_registration_ids,
            not_found_registration_ids=merged.not_found_registration_ids,
            collision_acknowledgements=merged.collision_acknowledgements,
        )

    if dry_run:
        return apply()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _acquire_file_lock(path.with_name(".event_links.lock"), timeout=5.0):
            return apply()
    except FileLockError as exc:
        raise EventLinksLockError(str(exc)) from exc


def merge_links(saved: EventLinks, fresh: EventLinks) -> EventLinks:
    """Fold this walk's links into the ones already on file.

    Operator choices and explicit removals survive automatic rematching, and a
    saved link for a team it did not see is kept. A partial walk is the normal
    path, not an edge case: the UI
    requires a two-division probe before it will enable the full walk, so the
    first roster of every session holds a handful of an event's teams. Replacing
    the file from it would delete the operator's fixes for every other division.
    """
    return _merge_decisions(saved, fresh, allow_relink=False)


def rows_fingerprint(rows: Sequence[RosterRow]) -> str:
    """Identify one walk's roster by its content, not its length."""
    joined = "\x1f".join(f"{row.source_index}:{row.team_name_raw}" for row in rows)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def registration_map(parked: Mapping[str, Any]) -> dict[int, str]:
    """The ``source_index`` to registration-id map inside a parked entry."""
    by_index = parked.get("by_index") if isinstance(parked, Mapping) else None
    return dict(by_index) if isinstance(by_index, Mapping) else {}


def generations_agree(
    rows: Sequence[RosterRow], parked: Mapping[str, Any], event_id: str
) -> bool:
    """Do these rows and this parked registration map come from the same walk?

    ``_park_event_roster`` writes the map and the parked result as separate
    session-state writes, and Streamlit raises a queued rerun from
    ``BaseException`` at every one of them — so a stop landing between the two
    leaves this walk's map standing against the previous walk's rows. Pairing
    those by ``source_index`` would file one team's link under another team's
    registration id and then save it, which is the silent corruption this whole
    store exists to prevent.

    Compared on two axes, because either alone lets a real pair through.
    ``source_index`` is assigned as ``len(teams)``, so every walk numbers
    0..n-1 and any two walks of equal size share an index set however different
    their teams are — an index check waves the dangerous pair through. And a
    fingerprint of the rows cannot separate two *events* whose rosters match:
    annual editions field the same clubs in the same order, and the ids behind
    those identical names are not the same, so the event has to match too.
    """
    if not isinstance(parked, Mapping):
        return False
    if not registration_map(parked):
        return False
    if parked.get("event_id") != event_id:
        return False
    return parked.get("fingerprint") == rows_fingerprint(rows)


def plan_sync(
    saved: EventLinks,
    rows: Sequence[RosterRow],
    resolved: Sequence[ResolvedTeam],
    overrides: Mapping[int, Mapping[str, str]],
    registration_ids: Mapping[int, str],
    event_id: str,
    *,
    resolve_team_id: Callable[[str], str | None] | None = None,
    restore: bool = True,
) -> tuple[dict[int, dict[str, str]], EventLinks]:
    """Reconcile one render against the file: what to restore, and what to store.

    Returns the operator fixes this walk is missing and the links that should be
    on disk once they are applied. Pure, and idempotent by construction — a fix
    already present is not returned, so running this on every rerun cannot
    overwrite a decision the operator is partway through changing, and no
    "have I restored yet" marker is needed. A marker is what made a second walk
    of the same event come back without its fixes: the walk clears the
    overrides, but the marker still said the event had been restored.

    ``restore=False`` skips only the restoring half. A caller whose merge map
    failed to load cannot safely revive a saved id — it may have been merged
    away since — but the operator's own fixes from this session are still worth
    persisting, and suppressing both would lose a click they already made.
    """
    to_add: dict[int, dict[str, str]] = {}
    if restore:
        to_add = {
            source_index: link
            for source_index, link in restore_overrides(
                rows, saved, registration_ids, resolve_team_id=resolve_team_id
            ).items()
            if source_index not in overrides
        }
    applied = {**dict(overrides), **to_add}
    fresh = build_links(event_id, rows, resolved, applied, registration_ids)
    return to_add, merge_links(saved, fresh)


def load_links(event_key: str, *, base_dir: Path | str = "reports") -> EventLinks:
    """Read an event's links back, or an empty set when there are none.

    Malformed files remain display-compatible with the legacy reader, but
    every writer loads strictly under its lock and refuses to overwrite them.
    Future schemas and another event's decisions are always refused.
    """
    path = event_links_path(event_key, base_dir=base_dir)
    try:
        return _load_links_strict(path, expected_id=parse_event_key(event_key)[1])
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.info("No readable links for %s: %s", event_key, exc)
        return EventLinks()


def _validate_links(links: EventLinks) -> None:
    registrations: set[str] = set()
    for link in links.links:
        if not isinstance(link, TeamLink):
            raise ValueError("Every saved link must be a TeamLink")
        for field in ("registration_id", "team_id_master", "matched_by", "linked_at"):
            value = getattr(link, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Link {field} must be a nonempty string")
        if not isinstance(link.event_team_name, str):
            raise ValueError("Link event_team_name must be a string")
        if link.registration_id in registrations:
            raise ValueError(f"Duplicate registration id {link.registration_id!r}")
        registrations.add(link.registration_id)
    removed: set[str] = set()
    for registration_id in links.removed_registration_ids:
        if not isinstance(registration_id, str) or not registration_id.strip():
            raise ValueError("Removed registration ids must be nonempty strings")
        if registration_id in removed or registration_id in registrations:
            raise ValueError(f"Conflicting registration id {registration_id!r}")
        removed.add(registration_id)
    not_found: set[str] = set()
    for registration_id in links.not_found_registration_ids:
        if not isinstance(registration_id, str) or not registration_id.strip():
            raise ValueError("Not-found registration ids must be nonempty strings")
        if registration_id in not_found or registration_id in registrations or registration_id in removed:
            raise ValueError(f"Conflicting registration id {registration_id!r}")
        not_found.add(registration_id)
    for acknowledgement in links.collision_acknowledgements:
        if not isinstance(acknowledgement, CollisionAcknowledgement):
            raise ValueError("Collision acknowledgements must be typed")
        if not acknowledgement.team_id_master.strip() or not acknowledgement.note.strip():
            raise ValueError("Collision acknowledgements need a team id and note")
        if len(set(acknowledgement.registration_ids)) < 2:
            raise ValueError("Collision acknowledgements need at least two distinct registrations")


def _load_links_strict(path: Path, *, expected_id: str) -> EventLinks:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return EventLinks()
    payload = json.loads(raw)
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must hold an object")
    assert_supported_version(payload, source=str(path))
    if payload["event_id"] != expected_id:
        raise EventLinksError(f"Saved event id at {path} does not match {expected_id!r}")
    if not isinstance(payload["links"], list):
        raise ValueError("Saved links must be a list")
    removed = payload.get("removed_registration_ids", [])
    if not isinstance(removed, list):
        raise ValueError("Saved removed_registration_ids must be a list")
    not_found = payload.get("not_found_registration_ids", [])
    acknowledgements = payload.get("collision_acknowledgements", [])
    if not isinstance(not_found, list) or not isinstance(acknowledgements, list):
        raise ValueError("Saved review decisions must be lists")
    decoded: list[TeamLink] = []
    for item in payload["links"]:
        if not isinstance(item, Mapping):
            raise ValueError("Each saved link must be an object")
        decoded.append(
            TeamLink(
                registration_id=item["registration_id"],
                event_team_name=item["event_team_name"],
                team_id_master=item["team_id_master"],
                matched_by=item["matched_by"],
                linked_at=item["linked_at"],
            )
        )
    links = EventLinks(
        event_id=payload["event_id"],
        links=tuple(decoded),
        saved_at=str(payload.get("saved_at", "")),
        removed_registration_ids=tuple(removed),
        not_found_registration_ids=tuple(not_found),
        collision_acknowledgements=tuple(
            CollisionAcknowledgement(
                team_id_master=item["team_id_master"],
                registration_ids=tuple(item["registration_ids"]),
                note=item["note"],
                acknowledged_at=item["acknowledged_at"],
            )
            for item in acknowledgements
        ),
    )
    _validate_links(links)
    return links


def build_links(
    event_id: str,
    rows: Sequence[RosterRow],
    resolved: Sequence[ResolvedTeam],
    overrides: Mapping[int, Mapping[str, str]],
    registration_ids: Mapping[int, str],
) -> EventLinks:
    """Collect every team this walk tied to a database row.

    A team the walk could not settle carries no link and is left out: this file
    records decisions, and an absent one is not a decision. The operator's fix
    wins over the resolver's, which is the whole reason they entered it.
    """
    linked_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    by_index = {item.source_index: item for item in resolved}

    links: list[TeamLink] = []
    for row in rows:
        registration_id = registration_ids.get(row.source_index)
        if not registration_id:
            continue
        override = overrides.get(row.source_index)
        if override and override.get("team_id_master"):
            team_id_master, matched_by = str(override["team_id_master"]), MATCHED_BY_OPERATOR
        else:
            item = by_index.get(row.source_index)
            if not item or not item.team_id_master:
                continue
            team_id_master, matched_by = item.team_id_master, item.status
        links.append(
            TeamLink(
                registration_id=registration_id,
                event_team_name=row.team_name_raw,
                team_id_master=team_id_master,
                matched_by=matched_by,
                linked_at=linked_at,
            )
        )
    return EventLinks(event_id=event_id, links=tuple(links))


def restore_overrides(
    rows: Sequence[RosterRow],
    links: EventLinks,
    registration_ids: Mapping[int, str],
    *,
    resolve_team_id: Callable[[str], str | None] | None = None,
) -> dict[int, dict[str, str]]:
    """Re-attach the operator's saved fixes to this walk's rows.

    Only the operator's. The resolver recomputes its own matches on every walk,
    and restoring one as an override would pin a decision the resolver has since
    moved past — the override exists precisely to overrule it.
    """
    saved = {
        link.registration_id: link
        for link in links.links
        if link.matched_by == MATCHED_BY_OPERATOR
    }
    restored: dict[int, dict[str, str]] = {}
    for row in rows:
        link = saved.get(registration_ids.get(row.source_index) or "")
        if not link:
            continue
        team_id = link.team_id_master
        if resolve_team_id:
            team_id = resolve_team_id(team_id) or team_id
        restored[row.source_index] = {
            "team_id_master": team_id,
            "team_name": link.event_team_name,
        }
    return restored
