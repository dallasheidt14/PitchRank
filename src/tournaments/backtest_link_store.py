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

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.tournaments.roster_paste import RosterRow
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.storage._io import write_json
from src.tournaments.storage.event_key import intake_dir

logger = logging.getLogger(__name__)

__all__ = [
    "EVENT_LINKS_FILENAME",
    "EventLinks",
    "TeamLink",
    "build_links",
    "event_links_path",
    "load_links",
    "restore_overrides",
    "save_links",
]

EVENT_LINKS_FILENAME = "event_links.json"

MATCHED_BY_OPERATOR = "operator"


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
class EventLinks:
    event_id: str = ""
    links: tuple[TeamLink, ...] = ()
    saved_at: str = ""


def event_links_path(event_key: str, *, base_dir: Path | str = "reports") -> Path:
    return intake_dir(event_key, base_dir=base_dir) / EVENT_LINKS_FILENAME


def save_links(
    event_key: str, links: EventLinks, *, base_dir: Path | str = "reports"
) -> Path:
    """Write the links, replacing whatever this event held before.

    Through ``_io.write_json`` rather than ``Path.write_text``: this file is the
    only copy of work that cost an operator a lookup each, and a truncated one
    reads back as no links at all, which the next render would then persist.
    That helper writes a sibling and renames it, so an interrupted save leaves
    the previous file whole.

    The caller is expected to hand over a merged set — see ``plan_sync``. A walk
    that saw fewer teams than the file holds must not replace it wholesale.
    """
    path = event_links_path(event_key, base_dir=base_dir)
    write_json(
        path,
        {
            "event_id": links.event_id,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "links": [asdict(link) for link in links.links],
        },
    )
    return path


def merge_links(saved: EventLinks, fresh: EventLinks) -> EventLinks:
    """Fold this walk's links into the ones already on file.

    This walk wins for every team it saw, and a saved link for a team it did not
    see is kept. A partial walk is the normal path, not an edge case: the UI
    requires a two-division probe before it will enable the full walk, so the
    first roster of every session holds a handful of an event's teams. Replacing
    the file from it would delete the operator's fixes for every other division.
    """
    walked = {link.registration_id for link in fresh.links}
    carried = tuple(link for link in saved.links if link.registration_id not in walked)
    return EventLinks(event_id=fresh.event_id or saved.event_id, links=fresh.links + carried)


def plan_sync(
    saved: EventLinks,
    rows: Sequence[RosterRow],
    resolved: Sequence[ResolvedTeam],
    overrides: Mapping[int, Mapping[str, str]],
    registration_ids: Mapping[int, str],
    event_id: str,
) -> tuple[dict[int, dict[str, str]], EventLinks]:
    """Reconcile one render against the file: what to restore, and what to store.

    Returns the operator fixes this walk is missing and the links that should be
    on disk once they are applied. Pure, and idempotent by construction — a fix
    already present is not returned, so running this on every rerun cannot
    overwrite a decision the operator is partway through changing, and no
    "have I restored yet" marker is needed. A marker is what made a second walk
    of the same event come back without its fixes: the walk clears the
    overrides, but the marker still said the event had been restored.
    """
    to_add = {
        source_index: link
        for source_index, link in restore_overrides(rows, saved, registration_ids).items()
        if source_index not in overrides
    }
    applied = {**dict(overrides), **to_add}
    fresh = build_links(event_id, rows, resolved, applied, registration_ids)
    return to_add, merge_links(saved, fresh)


def load_links(event_key: str, *, base_dir: Path | str = "reports") -> EventLinks:
    """Read an event's links back, or an empty set when there are none.

    Degrades rather than raises. An event with no links yet is the normal state
    of every event before its first walk, and a file this cannot read is worth
    no more than that — the links are recomputable, and refusing to render the
    screen over them would cost the walk that is not.
    """
    path = event_links_path(event_key, base_dir=base_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return EventLinks(
            event_id=str(payload["event_id"]),
            links=tuple(
                TeamLink(
                    registration_id=str(item["registration_id"]),
                    event_team_name=str(item["event_team_name"]),
                    team_id_master=str(item["team_id_master"]),
                    matched_by=str(item["matched_by"]),
                    linked_at=str(item["linked_at"]),
                )
                for item in payload["links"]
            ),
            saved_at=str(payload.get("saved_at", "")),
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.info("No readable links for %s: %s", event_key, exc)
        return EventLinks()


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
        if link:
            restored[row.source_index] = {
                "team_id_master": link.team_id_master,
                "team_name": link.event_team_name,
            }
    return restored
