"""Pure-function rescrape merge.

Spec §10 fold-in 14: overrides survive rescrape via merge on
``provider_team_id``. Removed teams surface in Shell 07's risk flags later
— this module just reports them.

The function operates on raw dicts (not ``IntakeJournal`` records or
``ScrapedTeam`` instances) so callers compose it with whatever projection
they want. Does **not** call ``compute_skip_set`` — that helper is for
resume-during-scrape, not post-scrape diff.

The result dataclass is in-memory only; never persisted. Mirrors
``RemovedTeamsDiff`` at ``src/scrapers/intake_journal.py:76`` (frozen
result, no ``schema_version`` field).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "RescrapeReport",
    "merge_rescrape",
]


@dataclass(frozen=True)
class RescrapeReport:
    """In-memory summary of a rescrape merge keyed on ``provider_team_id``.

    Orphan overrides — entries whose pid is in neither ``old_raw`` nor
    ``new_raw`` — are silently absent from every bucket; callers that need
    to surface them compute the residual themselves.
    """

    teams_added: tuple[str, ...]
    """``provider_team_id`` values in the new scrape but not the old."""

    teams_removed_but_overridden: tuple[str, ...]
    """Pids in the old scrape but not the new, with an existing override."""

    teams_with_preserved_overrides: tuple[str, ...]
    """Pids present in both scrapes whose override survives merge-on-pid."""


def _pid_set(rows: list[dict[str, Any]]) -> set[str]:
    return {str(row["provider_team_id"]) for row in rows if row.get("provider_team_id") not in (None, "")}


def merge_rescrape(
    old_raw: list[dict[str, Any]],
    new_raw: list[dict[str, Any]],
    overrides: list[dict[str, Any]],
) -> RescrapeReport:
    """Merge two scrape snapshots and report override survivability.

    ``overrides`` may contain multiple records per pid (the append-only
    overrides log). Any pid with at least one override record is treated as
    "has override" — the override semantics (replay, latest-wins) are the
    Streamlit layer's contract, not this function's.
    """
    old_ids = _pid_set(old_raw)
    new_ids = _pid_set(new_raw)
    override_ids = _pid_set(overrides)

    teams_added = tuple(sorted(new_ids - old_ids))
    removed_ids = old_ids - new_ids
    teams_removed_but_overridden = tuple(sorted(removed_ids & override_ids))
    teams_with_preserved_overrides = tuple(sorted(new_ids & override_ids))

    return RescrapeReport(
        teams_added=teams_added,
        teams_removed_but_overridden=teams_removed_but_overridden,
        teams_with_preserved_overrides=teams_with_preserved_overrides,
    )
