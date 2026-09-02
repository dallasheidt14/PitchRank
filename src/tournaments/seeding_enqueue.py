"""Queue a seeding roster's teams for a fresh scrape.

Seeding reads each team's current rating, so an event weeks away is worth
re-scraping before any grouping is proposed. This queues every team the intake
resolved, at the priority the other operator-initiated path uses.

Priority 1 matches ``frontend/app/api/scrape-missing-game``: a person is
waiting on the result, unlike the scheduled producers at 2 to 4. A roster is a
few hundred teams and the drainer clears roughly 3,840 a day, so a full event
is a couple of hours ahead of the scheduled work rather than a lasting
displacement of it.

A team the intake could not resolve cannot be queued at all: the RPC is keyed
on ``team_id_master`` and there is no row to name. Those are reported as
skipped so the count is honest about what was left out.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from src.tournaments.roster_paste import RosterRow
from src.tournaments.roster_resolver import ResolvedTeam

logger = logging.getLogger(__name__)

__all__ = [
    "SEEDING_REQUEST_PRIORITY",
    "SEEDING_REQUEST_TYPE",
    "EnqueueOutcome",
    "enqueue_resolved_teams",
    "make_enqueue_caller",
]

SEEDING_REQUEST_PRIORITY = 1
SEEDING_REQUEST_TYPE = "missing_games"


@dataclass(frozen=True)
class EnqueueOutcome:
    queued: int = 0
    skipped: int = 0
    failed: int = 0
    would_queue: int = 0
    failures: tuple[str, ...] = field(default_factory=tuple)


def _team_id_for(row: RosterRow, item: ResolvedTeam, overrides: Mapping[int, dict[str, Any]]) -> str | None:
    override = overrides.get(row.source_index)
    if override and override.get("team_id_master"):
        return str(override["team_id_master"])
    return item.team_id_master or None


def enqueue_resolved_teams(
    rows: Sequence[RosterRow],
    resolved: Sequence[ResolvedTeam],
    overrides: Mapping[int, dict[str, Any]],
    *,
    enqueue: Callable[[dict[str, Any]], Any],
    dry_run: bool = False,
) -> EnqueueOutcome:
    """Queue every resolved team once.

    ``dry_run`` makes no call at all, so a rehearsal cannot write. One team
    appearing on several roster rows is queued once; the RPC would collapse the
    duplicates anyway, but sending them wastes round trips.
    """
    by_index = {item.source_index: item for item in resolved}
    seen: set[str] = set()
    queued = skipped = failed = 0
    failures: list[str] = []
    anchor = date.today().isoformat()

    for row in rows:
        item = by_index.get(row.source_index)
        if item is None:
            continue
        team_id_master = _team_id_for(row, item, overrides)
        if not team_id_master:
            skipped += 1
            continue
        if team_id_master in seen:
            continue
        seen.add(team_id_master)

        if dry_run:
            continue

        try:
            enqueue(
                {
                    "p_team_id_master": team_id_master,
                    "p_team_name": row.team_name_raw,
                    "p_provider_id": None,
                    "p_provider_team_id": item.provider_team_id,
                    "p_game_date": anchor,
                    "p_request_type": SEEDING_REQUEST_TYPE,
                    "p_priority": SEEDING_REQUEST_PRIORITY,
                }
            )
            queued += 1
        except Exception as exc:  # noqa: BLE001 - one bad row must not sink the batch
            failed += 1
            failures.append(f"{team_id_master} ({row.team_name_raw}): {exc}")
            logger.warning("Could not queue %s: %s", team_id_master, exc)

    return EnqueueOutcome(
        queued=queued,
        skipped=skipped,
        failed=failed,
        would_queue=len(seen) if dry_run else 0,
        failures=tuple(failures),
    )


def make_enqueue_caller(supabase_client: Any, provider_id: str | None = None) -> Callable[[dict[str, Any]], Any]:
    """Bind the RPC, filling in the provider the roster came from."""

    def call(payload: dict[str, Any]) -> Any:
        body = dict(payload)
        if body.get("p_provider_id") is None:
            body["p_provider_id"] = provider_id
        return supabase_client.rpc("enqueue_scrape_request", body).execute()

    return call
