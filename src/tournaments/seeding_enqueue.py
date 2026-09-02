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
on ``team_id_master`` and there is no row to name. Nor is a team queued without
a ``provider_team_id`` — ``process_missing_games`` raises
``Missing required field: provider_team_id`` and the row becomes a guaranteed
failure instead of a scrape. Only the GotSport-id pass yields that id directly,
so rows settled by name or by hand have it looked up. Both kinds of omission
are reported as skipped, so the count says what was left out.
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
    "make_provider_team_id_lookup",
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
    lookup_provider_team_id: Callable[[str], str | None] | None = None,
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

        provider_team_id = item.provider_team_id
        if not provider_team_id and lookup_provider_team_id is not None:
            provider_team_id = lookup_provider_team_id(team_id_master)
        if not provider_team_id:
            skipped += 1
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
                    "p_provider_team_id": provider_team_id,
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


def make_provider_team_id_lookup(supabase_client: Any, provider_id: str | None) -> Callable[[str], str | None]:
    """Find a team's GotSport id when the resolver did not supply one.

    Checks ``teams`` first, then ``team_alias_map``, both scoped to GotSport
    since uniqueness is on ``(provider_id, provider_team_id)``.
    """

    def lookup(team_id_master: str) -> str | None:
        rows = (
            supabase_client.table("teams")
            .select("provider_team_id")
            .eq("team_id_master", team_id_master)
            .eq("provider_id", provider_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if rows and rows[0].get("provider_team_id"):
            return str(rows[0]["provider_team_id"])

        alias_rows = (
            supabase_client.table("team_alias_map")
            .select("provider_team_id")
            .eq("team_id_master", team_id_master)
            .eq("provider_id", provider_id)
            .eq("review_status", "approved")
            .limit(1)
            .execute()
            .data
            or []
        )
        if alias_rows and alias_rows[0].get("provider_team_id"):
            return str(alias_rows[0]["provider_team_id"])
        return None

    return lookup
