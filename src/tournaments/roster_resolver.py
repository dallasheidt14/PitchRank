"""Resolve pasted roster rows to canonical team ids.

Two passes, in this order:

1. **GotSport id.** The public rankings search at ``team_ranking_data`` returns
   a ``team_id`` that *is* our ``provider_team_id`` for the ``gotsport``
   provider, so a single hit resolves by direct lookup rather than by score.
   A hit only counts when it also names the roster's team: the endpoint matches
   club names too, so one row on its own is not proof of identity. Measured on a
   real 105-team roster: 58 single hits, of which 56 named the right team, and
   every one of the 58 ids was already held locally.
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
import re
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
    "ManualReference",
    "ManualResolution",
    "make_exact_name_lookup",
    "make_provider_id_lookup",
    "make_team_details_lookup",
    "parse_manual_reference",
    "resolve_manual_reference",
    "resolve_roster",
    "resolve_row",
    "search_gotsport_teams",
    "summarize",
]

GOTSPORT_RANKING_SEARCH_URL = "https://system.gotsport.com/api/v1/team_ranking_data"
GOTSPORT_PROVIDER_CODE = "gotsport"

_UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
_TEAMS_PATH_PATTERN = re.compile(r"/teams/([0-9]+)")
_ALL_DIGITS_PATTERN = re.compile(r"^[0-9]+$")

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


def _comparable(name: str) -> str:
    return " ".join(str(name or "").split()).casefold()


def _names_the_same_team(candidate_name: str, row: RosterRow) -> bool:
    """Does the hit actually name the roster's team?

    ``team_or_club_name`` matches club names too, so a single row proves only
    that one candidate exists. Searching ``Pre-ECNL B2014/15 Gold`` for a San
    Antonio City SC team returned exactly one row named ``Beach FC Pre-ECNL
    B2014/15 Gold`` — a different club's squad. Without this check that id
    would have been accepted as a certain match.
    """
    return _comparable(candidate_name) in {
        _comparable(row.team_name_raw),
        _comparable(row.team_name_stripped),
    }


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
        if not _names_the_same_team(hits[0].get("team_name", ""), row):
            return ResolvedTeam(
                source_index=row.source_index,
                status="review",
                candidates=tuple(hits),
            )
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


@dataclass(frozen=True)
class ManualReference:
    """What an operator pasted, once we know which kind of identifier it is."""

    kind: str
    value: str


@dataclass(frozen=True)
class ManualResolution:
    """Outcome of a pasted override.

    ``status`` is ``ok``, ``not_found`` (readable but we hold no such team) or
    ``unrecognized`` (not an id we know how to read). ``cohort_matches`` is
    False when the team sits in a different age group or gender from the
    section it was pasted under, which is how a mistyped id shows itself.
    """

    status: str
    team_id_master: str | None = None
    details: dict[str, Any] | None = None
    cohort_matches: bool = True


def parse_manual_reference(text: str) -> ManualReference:
    """Read a pasted GotSport link, GotSport id, or one of our own team ids.

    A team name is deliberately not accepted. Name matching is the part this
    override exists to bypass, so guessing from one here would reintroduce the
    ambiguity the operator is resolving by hand.
    """
    candidate = (text or "").strip()

    uuid_match = _UUID_PATTERN.search(candidate)
    if uuid_match:
        return ManualReference(kind="team_id_master", value=uuid_match.group(0).lower())

    path_match = _TEAMS_PATH_PATTERN.search(candidate)
    if path_match:
        return ManualReference(kind="gotsport_id", value=path_match.group(1))

    if _ALL_DIGITS_PATTERN.match(candidate):
        return ManualReference(kind="gotsport_id", value=candidate)

    return ManualReference(kind="unrecognized", value=candidate)


def resolve_manual_reference(
    text: str,
    row: RosterRow,
    *,
    lookup_provider_id: ProviderIdLookup,
    lookup_team_details: Callable[[str], dict[str, Any] | None],
) -> ManualResolution:
    """Turn a pasted identifier into a confirmed team, or say why it could not."""
    reference = parse_manual_reference(text)
    if reference.kind == "unrecognized":
        return ManualResolution(status="unrecognized")

    if reference.kind == "gotsport_id":
        team_id_master = lookup_provider_id(reference.value)
        if not team_id_master:
            return ManualResolution(status="not_found")
    else:
        team_id_master = reference.value

    details = lookup_team_details(team_id_master)
    if not details:
        return ManualResolution(status="not_found")

    cohort_matches = str(details.get("age_group", "")).lower() == row.section_age_group and str(
        details.get("gender", "")
    ) == row.section_gender

    return ManualResolution(
        status="ok",
        team_id_master=team_id_master,
        details=details,
        cohort_matches=cohort_matches,
    )


def make_team_details_lookup(supabase_client: Any) -> Callable[[str], dict[str, Any] | None]:
    """Fetch the fields an operator needs to confirm a pasted id is the right team."""

    def lookup(team_id_master: str) -> dict[str, Any] | None:
        rows = (
            supabase_client.table("teams")
            .select("team_id_master,team_name,club_name,age_group,gender,state_code")
            .eq("team_id_master", team_id_master)
            .eq("is_deprecated", False)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    return lookup


def make_provider_id_lookup(supabase_client: Any, merge_resolver: Any = None) -> ProviderIdLookup:
    """Build a ``provider_team_id`` → ``team_id_master`` lookup.

    Checks ``teams`` first and falls back to ``team_alias_map``; on the measured
    roster 53 of 58 ids sat on ``teams`` and all 58 on the alias map, every one
    of them approved and GotSport-owned.

    Both queries are scoped to the GotSport provider, because uniqueness is on
    ``(provider_id, provider_team_id)`` and 5,439 provider team ids are in use by
    more than one provider. The alias query additionally requires
    ``review_status = 'approved'``, so a mapping still awaiting review cannot be
    reported as a certain match. The result goes through ``MergeResolver`` when
    one is supplied, since an alias can name a team that was later merged away.
    """

    cached_provider_id: list[str | None] = []

    def gotsport_provider_id() -> str | None:
        if not cached_provider_id:
            rows = (
                supabase_client.table("providers")
                .select("id")
                .eq("code", GOTSPORT_PROVIDER_CODE)
                .limit(1)
                .execute()
                .data
                or []
            )
            cached_provider_id.append(rows[0]["id"] if rows else None)
        return cached_provider_id[0]

    def lookup(provider_team_id: str) -> str | None:
        provider_id = gotsport_provider_id()
        if not provider_id:
            logger.warning("No '%s' row in providers; cannot resolve ids by provider.", GOTSPORT_PROVIDER_CODE)
            return None

        team_rows = (
            supabase_client.table("teams")
            .select("team_id_master")
            .eq("provider_team_id", provider_team_id)
            .eq("provider_id", provider_id)
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
            .eq("provider_id", provider_id)
            .eq("review_status", "approved")
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
