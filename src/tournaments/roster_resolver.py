"""Resolve pasted roster rows to canonical team ids.

Two passes, in this order:

1. **GotSport id.** The public rankings search at ``team_ranking_data`` returns
   a ``team_id`` that *is* our ``provider_team_id`` for the ``gotsport``
   provider, so a single hit resolves by direct lookup rather than by score.
   Measured on a real 105-team roster: 58 rows resolved this way and every one
   of the 58 ids was already held locally.
2. **Exact local name.** Case-insensitive exact match inside the row's own
   cohort, accepted only when it is unique.

Pass 1 leads because it is an identity lookup. Pass 2 is a name comparison and
is measurably weaker — of the 37 rows it matched on that same roster, only 26
were unique within the right cohort, so it is the fallback rather than the
first question asked.

Rows with several candidates are never auto-picked; they carry their candidates
into the review sheet so an operator chooses.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import requests

from src.tournaments.roster_paste import RosterRow

logger = logging.getLogger(__name__)

__all__ = [
    "GOTSPORT_RANKING_SEARCH_URL",
    "ResolvedTeam",
    "build_search_params",
    "make_exact_name_lookup",
    "make_provider_id_lookup",
    "resolve_roster",
    "resolve_row",
    "search_gotsport_teams",
    "summarize",
]

GOTSPORT_RANKING_SEARCH_URL = "https://system.gotsport.com/api/v1/team_ranking_data"

_PROVIDER_GENDER = {"Male": "m", "Female": "f"}

GotsportSearch = Callable[[str, str, str], list[dict[str, Any]]]
ProviderIdLookup = Callable[[str], str | None]
ExactNameLookup = Callable[[str, str, str], list[str]]


@dataclass(frozen=True)
class ResolvedTeam:
    """Outcome of resolving one roster row.

    ``status`` is one of ``gotsport_id``, ``exact_name`` (resolved),
    ``review`` (several candidates, operator picks) or ``unresolved``.
    """

    source_index: int
    status: str
    team_id_master: str | None = None
    provider_team_id: str | None = None
    matched_name: str | None = None
    candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def build_search_params(team_name: str, age_group: str, gender: str) -> dict[str, str]:
    """Build the query for the public GotSport rankings team search.

    ``search[age]`` is the U-age as an integer, not a birth year, and the
    endpoint rejects the request unless both age and gender are present.
    """
    return {
        "search[team_country]": "USA",
        "search[age]": str(int(age_group.lower().removeprefix("u"))),
        "search[gender]": _PROVIDER_GENDER[gender],
        "search[page]": "1",
        "search[team_or_club_name]": team_name,
    }


def search_gotsport_teams(
    team_name: str,
    age_group: str,
    gender: str,
    *,
    session: requests.Session | None = None,
    timeout: int = 45,
) -> list[dict[str, Any]]:
    """Query the rankings search and return its raw team rows.

    Only ``team_id`` is load-bearing downstream; the endpoint's own rank and
    points columns are deliberately left unused.
    """
    getter = session.get if session is not None else requests.get
    response = getter(
        GOTSPORT_RANKING_SEARCH_URL,
        params=build_search_params(team_name, age_group, gender),
        headers={"Accept": "application/json", "Origin": "https://rankings.gotsport.com"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json().get("team_ranking_data") or []


def _search_names(row: RosterRow) -> list[str]:
    if row.team_name_stripped == row.team_name_raw:
        return [row.team_name_raw]
    return [row.team_name_raw, row.team_name_stripped]


def resolve_row(
    row: RosterRow,
    *,
    gotsport_search: GotsportSearch,
    lookup_provider_id: ProviderIdLookup,
    lookup_exact_name: ExactNameLookup,
) -> ResolvedTeam:
    """Resolve one row, GotSport id first and exact local name second."""
    hits: list[dict[str, Any]] = []
    for name in _search_names(row):
        hits = gotsport_search(name, row.section_age_group, row.section_gender)
        if hits:
            break

    if len(hits) > 1:
        return ResolvedTeam(
            source_index=row.source_index,
            status="review",
            candidates=tuple(hits),
        )

    if len(hits) == 1:
        provider_team_id = str(hits[0].get("team_id"))
        team_id_master = lookup_provider_id(provider_team_id)
        if team_id_master:
            return ResolvedTeam(
                source_index=row.source_index,
                status="gotsport_id",
                team_id_master=team_id_master,
                provider_team_id=provider_team_id,
                matched_name=hits[0].get("team_name"),
            )

    local = lookup_exact_name(row.team_name_stripped, row.section_age_group, row.section_gender)
    if len(local) == 1:
        return ResolvedTeam(
            source_index=row.source_index,
            status="exact_name",
            team_id_master=local[0],
            matched_name=row.team_name_stripped,
        )
    if len(local) > 1:
        return ResolvedTeam(
            source_index=row.source_index,
            status="review",
            candidates=tuple({"team_id_master": team_id} for team_id in local),
        )

    return ResolvedTeam(source_index=row.source_index, status="unresolved")


def resolve_roster(
    rows: Sequence[RosterRow],
    *,
    gotsport_search: GotsportSearch,
    lookup_provider_id: ProviderIdLookup,
    lookup_exact_name: ExactNameLookup,
    delay_seconds: float = 0.0,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[ResolvedTeam, ...]:
    """Resolve every row in source order.

    ``delay_seconds`` paces the searches. This is a public endpoint belonging to
    someone else and a roster is a few hundred rows at most, so the calls stay
    serial; 0.4s was comfortable over 105 lookups.
    """
    resolved: list[ResolvedTeam] = []
    for position, row in enumerate(rows):
        resolved.append(
            resolve_row(
                row,
                gotsport_search=gotsport_search,
                lookup_provider_id=lookup_provider_id,
                lookup_exact_name=lookup_exact_name,
            )
        )
        if on_progress is not None:
            on_progress(position + 1, len(rows))
        if delay_seconds and position + 1 < len(rows):
            time.sleep(delay_seconds)
    return tuple(resolved)


def make_provider_id_lookup(supabase_client: Any, merge_resolver: Any = None) -> ProviderIdLookup:
    """Build a ``provider_team_id`` → ``team_id_master`` lookup.

    Checks ``teams`` first and falls back to ``team_alias_map``; on the measured
    roster 53 of 58 ids sat on ``teams`` and all 58 on the alias map. The alias
    may name a team that has since been merged away, so the result goes through
    ``MergeResolver`` when one is supplied.
    """

    def lookup(provider_team_id: str) -> str | None:
        team_rows = (
            supabase_client.table("teams")
            .select("team_id_master")
            .eq("provider_team_id", provider_team_id)
            .eq("is_deprecated", False)
            .limit(2)
            .execute()
            .data
            or []
        )
        if len(team_rows) == 1:
            return _resolved_id(team_rows[0].get("team_id_master"), merge_resolver)

        alias_rows = (
            supabase_client.table("team_alias_map")
            .select("team_id_master")
            .eq("provider_team_id", provider_team_id)
            .limit(2)
            .execute()
            .data
            or []
        )
        if len(alias_rows) == 1:
            return _resolved_id(alias_rows[0].get("team_id_master"), merge_resolver)
        return None

    return lookup


def make_exact_name_lookup(supabase_client: Any, merge_resolver: Any = None) -> ExactNameLookup:
    """Build a cohort-scoped exact-name lookup returning canonical team ids."""

    def lookup(team_name: str, age_group: str, gender: str) -> list[str]:
        rows = (
            supabase_client.table("teams")
            .select("team_id_master,team_name")
            .ilike("team_name", team_name)
            .eq("age_group", age_group)
            .eq("gender", gender)
            .eq("is_deprecated", False)
            .limit(10)
            .execute()
            .data
            or []
        )
        resolved = {_resolved_id(row.get("team_id_master"), merge_resolver) for row in rows}
        return sorted(team_id for team_id in resolved if team_id)

    return lookup


def _resolved_id(team_id: str | None, merge_resolver: Any) -> str | None:
    if not team_id:
        return None
    if merge_resolver is None:
        return team_id
    return merge_resolver.resolve(team_id) or team_id


def summarize(resolved: Iterable[ResolvedTeam]) -> dict[str, int]:
    """Count rows by status, keeping absent statuses at zero for a stable headline."""
    counts = dict.fromkeys(("gotsport_id", "exact_name", "review", "unresolved"), 0)
    for item in resolved:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts
