"""Resolve pasted roster rows to canonical team ids.

Search by club before broad team-name searches, then check local identities
before returning an ambiguous result. Only exact identities can auto-match;
different names and conflicting provider records remain operator decisions.

Two sources of identity:

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

Only a unique exact team-and-club identity can disambiguate multiple provider hits.
Remaining candidates go to review; adjacent-age identities require confirmation.
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
from src.utils.club_normalizer import are_same_club
from src.utils.us_states import STATE_CODE_TO_NAME, state_name_to_code

logger = logging.getLogger(__name__)

__all__ = [
    "GOTSPORT_RANKING_SEARCH_URL",
    "ResolvedTeam",
    "TeamDetailsLookup",
    "build_search_params",
    "escape_ilike_literal",
    "ManualReference",
    "ManualResolution",
    "fetch_gotsport_provider_id",
    "make_exact_name_lookup",
    "make_club_candidate_lookup",
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
TeamDetailsLookup = Callable[[str], dict[str, Any] | None]
ClubCandidateLookup = Callable[[RosterRow], list[dict[str, Any]]]


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
    review_reason: str | None = None


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
    hits: dict[str, dict[str, Any]] = {}
    for page in range(1, 26):
        params = build_search_params(team_name, age_group, gender)
        params["search[page]"] = str(page)
        response = getter(
            GOTSPORT_RANKING_SEARCH_URL, params=params,
            headers={"Accept": "application/json", "Origin": "https://rankings.gotsport.com"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("team_ranking_data") or []
        pagination = payload.get("pagination") or {}
        current = int(pagination.get("current_page", page))
        total = int(pagination.get("total_pages", 1))
        if current != page or total > 25 or (not rows and (total > page or page > 1)):
            raise ValueError("GotSport team search is incomplete; narrow the search before matching.")
        before = len(hits)
        for hit in rows:
            if not hit.get("team_id"):
                raise ValueError("GotSport team search returned a candidate without an identity.")
            hits[str(hit["team_id"])] = hit
        if page > 1 and rows and len(hits) == before:
            raise ValueError("GotSport team search repeated a page; matching is incomplete.")
        if page >= total:
            return list(hits.values())
    raise ValueError("GotSport team search is incomplete.")


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


def _same_club_identity(candidate: dict[str, Any], row: RosterRow) -> bool:
    return (_names_the_same_team(candidate.get("team_name", ""), row)
            and bool(row.club_raw.strip()) and bool(candidate.get("club_name"))
            and are_same_club(row.club_raw, candidate["club_name"], threshold=1.0))


def _search_provider_candidates(row: RosterRow, search: GotsportSearch, age: str) -> list[dict[str, Any]]:
    """Use the club as a retrieval query, never as proof of the squad's identity."""
    hits: dict[str, dict[str, Any]] = {}
    queries = dict.fromkeys([row.club_raw.strip(), *_search_names(row)])
    for query in queries:
        if not query:
            continue
        found = search(query, age, row.section_gender)
        for hit in found:
            hits[str(hit.get("team_id"))] = hit
    # Queries can expose different provider IDs under equivalent club labels.
    # Finish every query before deciding that an identity is unique.
    identified = [hit for hit in hits.values() if _same_club_identity(hit, row)]
    return identified or list(hits.values())


def _state_code(value: Any) -> str | None:
    """Normalize a U.S. state name or postal code for identity comparison."""
    text = str(value or "").strip()
    upper = text.upper()
    if upper in STATE_CODE_TO_NAME:
        return upper
    return state_name_to_code(text)


def _candidate_state(candidate: dict[str, Any]) -> str:
    for key in ("state_code", "state", "team_state"):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    return ""


def _identity_conflict_reason(row: RosterRow, *signals: dict[str, Any] | None) -> str | None:
    """Explain contradictory club/state evidence, while treating omissions as neutral."""
    submitted_club = row.club_raw.strip()
    submitted_state = _state_code(row.state)
    reasons: list[str] = []
    seen: set[str] = set()

    for signal in signals:
        if not signal:
            continue
        candidate_club = str(signal.get("club_name") or "").strip()
        if submitted_club and candidate_club and not are_same_club(submitted_club, candidate_club, threshold=1.0):
            reason = f"Club conflict: submitted '{submitted_club}', candidate '{candidate_club}'."
            if reason not in seen:
                reasons.append(reason)
                seen.add(reason)

        candidate_state_raw = _candidate_state(signal)
        candidate_state = _state_code(candidate_state_raw)
        if submitted_state and candidate_state and submitted_state != candidate_state:
            reason = f"State conflict: submitted '{submitted_state}', candidate '{candidate_state}'."
            if reason not in seen:
                reasons.append(reason)
                seen.add(reason)

        age = str(signal.get("age_group") or "").lower()
        if not age and signal.get("age") is not None:
            age = f"u{signal['age']}"
        gender = str(signal.get("gender") or "")
        gender = {"m": "Male", "f": "Female"}.get(gender.lower(), gender)
        for label, actual, expected in (("Age", age, row.section_age_group),
                                        ("Gender", gender, row.section_gender)):
            if actual and actual != expected:
                reason = f"{label} conflict: roster '{expected}', candidate '{actual}'."
                if reason not in seen:
                    reasons.append(reason)
                    seen.add(reason)

    return " ".join(reasons) or None


def _review_candidate(
    *,
    team_id_master: str | None = None,
    provider_hit: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = {**(provider_hit or {}), **(details or {})}
    if team_id_master:
        candidate["team_id_master"] = team_id_master
    return candidate


def escape_ilike_literal(value: str) -> str:
    """Escape Postgres ILIKE metacharacters so a team name stays literal."""
    return (
        value.replace("\\", "\\\\")
        .replace("%", r"\%")
        .replace("_", r"\_")
        .replace("*", r"\*")
    )


def _club_team_splits(value: str) -> Iterable[tuple[str, str]]:
    """Yield every whitespace boundary as a possible ``club, team`` split.

    GotSport event pages sometimes publish one display label even though
    PitchRank stores the same identity as separate ``club_name`` and
    ``team_name`` fields.  Each half is still matched literally; trying the
    boundaries only lets ``Arizona Soccer Club 2016/17B Navy`` find the row
    whose club is ``Arizona Soccer Club`` and team is ``2016/17B Navy``.
    """
    words = str(value or "").split()
    for boundary in range(1, len(words)):
        yield " ".join(words[:boundary]), " ".join(words[boundary:])


def _postgrest_ilike_operand(value: str) -> str:
    """Quote one literal ILIKE value for a PostgREST logical filter."""
    pattern = escape_ilike_literal(value)
    quoted = pattern.replace("\\", "\\\\").replace('"', r'\"')
    return f'"{quoted}"'


def _exact_name_or_filter(value: str) -> str:
    """Match a full team name or any exact ``club_name + team_name`` split."""
    normalized = " ".join(str(value or "").split())
    clauses = [f"team_name.ilike.{_postgrest_ilike_operand(normalized)}"]
    clauses.extend(
        "and("
        f"club_name.ilike.{_postgrest_ilike_operand(club_name)},"
        f"team_name.ilike.{_postgrest_ilike_operand(team_name)}"
        ")"
        for club_name, team_name in _club_team_splits(normalized)
    )
    return ",".join(clauses)


def _resolve_provider_hits(
    row: RosterRow,
    hits: list[dict[str, Any]],
    *,
    gotsport_search: GotsportSearch,
    lookup_provider_id: ProviderIdLookup,
    lookup_team_details: TeamDetailsLookup | None = None,
) -> ResolvedTeam | None:
    # Provider search includes unrelated clubs. Disambiguate by exact identity,
    # never by provider rank, result position, or a fuzzy score.
    identified = [hit for hit in hits if _same_club_identity(hit, row)]
    if len(identified) == 1:
        hits = identified
    elif not identified and row.club_raw.strip() and re.search(r"\d{2}/\d{2}", row.team_name_stripped):
        # A younger team can enter an older tournament cohort. Surface the exact
        # club/name candidate for confirmation; do not silently change its age.
        younger = f"u{int(row.section_age_group[1:]) - 1}"
        adjacent = [hit for hit in _search_provider_candidates(row, gotsport_search, younger)
                    if _same_club_identity(hit, row)]
        if adjacent:
            candidates = []
            for hit in adjacent:
                master = lookup_provider_id(str(hit.get("team_id")))
                details = lookup_team_details(master) if master and lookup_team_details else None
                candidates.append(_review_candidate(team_id_master=master, provider_hit=hit, details=details))
            return ResolvedTeam(source_index=row.source_index, status="review", candidates=tuple(candidates),
                                review_reason=f"Exact club/name found in {younger.upper()}; confirm this is the "
                                f"team playing in {row.section_age_group.upper()}.")

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
        conflict = _identity_conflict_reason(row, hits[0])
        if conflict and "Club conflict:" in conflict:
            return ResolvedTeam(
                source_index=row.source_index,
                status="review",
                provider_team_id=str(hits[0].get("team_id")),
                candidates=tuple(hits),
                review_reason=conflict,
            )
        provider_team_id = str(hits[0].get("team_id"))
        team_id_master = lookup_provider_id(provider_team_id)
        if team_id_master:
            details = lookup_team_details(team_id_master) if lookup_team_details else None
            conflict = _identity_conflict_reason(row, hits[0], details)
            if lookup_team_details and not details:
                conflict = "The linked PitchRank record could not be verified. Confirm the team's identity."
            if conflict:
                return ResolvedTeam(
                    source_index=row.source_index,
                    status="review",
                    provider_team_id=provider_team_id,
                    candidates=(
                        _review_candidate(
                            team_id_master=team_id_master,
                            provider_hit=hits[0],
                            details=details,
                        ),
                    ),
                    review_reason=conflict,
                )
            return ResolvedTeam(
                source_index=row.source_index,
                status="gotsport_id",
                team_id_master=team_id_master,
                provider_team_id=provider_team_id,
                matched_name=hits[0].get("team_name"),
            )
        if conflict:
            return ResolvedTeam(source_index=row.source_index, status="review",
                                provider_team_id=provider_team_id, candidates=tuple(hits),
                                review_reason=conflict)

    return None


def resolve_row(
    row: RosterRow, *, gotsport_search: GotsportSearch,
    lookup_provider_id: ProviderIdLookup, lookup_exact_name: ExactNameLookup,
    lookup_team_details: TeamDetailsLookup | None = None,
    lookup_club_candidates: ClubCandidateLookup | None = None,
) -> ResolvedTeam:
    """Resolve exact identities; gather local evidence before requesting review."""
    hits = _search_provider_candidates(row, gotsport_search, row.section_age_group)
    provider = _resolve_provider_hits(
        row, hits, gotsport_search=gotsport_search,
        lookup_provider_id=lookup_provider_id, lookup_team_details=lookup_team_details,
    )
    if provider and provider.status == "gotsport_id":
        return provider

    local = {candidate["team_id_master"]: candidate
             for candidate in (lookup_club_candidates(row) if lookup_club_candidates else ())
             if candidate.get("team_id_master")}
    missing_details: set[str] = set()
    exact_ids = {team_id for team_id, candidate in local.items()
                 if _names_the_same_team(candidate.get("team_name", ""), row)}
    if not exact_ids:
        # Other squads at this club do not prove the requested team is absent.
        # Keep the literal-name fallback, including equivalent club spellings.
        exact_ids = set(lookup_exact_name(row.team_name_stripped, row.section_age_group, row.section_gender))
        for team_id in sorted(exact_ids):
            details = lookup_team_details(team_id) if lookup_team_details else None
            if lookup_team_details and not details:
                missing_details.add(team_id)
            local[team_id] = _review_candidate(team_id_master=team_id, details=details)
    exact = [candidate for candidate in local.values()
             if (candidate["team_id_master"] in exact_ids or _names_the_same_team(candidate.get("team_name", ""), row))
             and candidate["team_id_master"] not in missing_details
             and not _identity_conflict_reason(row, candidate)]
    strong = [candidate for candidate in exact
              if row.club_raw.strip() and candidate.get("club_name")
              and are_same_club(row.club_raw, candidate["club_name"], threshold=1.0)]
    # An exact local identity may resolve unrelated search noise, but cannot
    # overrule conflicting identity evidence or two exact provider identities.
    foreign_club_noise = bool(row.club_raw.strip() and hits) and all(
        hit.get("club_name") and not are_same_club(row.club_raw, hit["club_name"], threshold=1.0)
        for hit in hits
    )
    blocked = bool(provider and provider.review_reason)
    if foreign_club_noise and provider and (provider.review_reason or "").startswith("Club conflict:"):
        blocked = False
    blocked = blocked or sum(_same_club_identity(hit, row) for hit in hits) > 1
    choice = strong[0] if len(strong) == 1 else None
    if provider is None and len(exact_ids) == 1 and len(exact) == 1:
        choice = exact[0]
    if choice and not blocked:
        return ResolvedTeam(source_index=row.source_index, status="exact_name",
                            team_id_master=choice["team_id_master"],
                            matched_name=choice.get("team_name") or row.team_name_stripped)

    same_club = [candidate for candidate in local.values()
                 if row.club_raw.strip() and candidate.get("club_name")
                 and are_same_club(row.club_raw, candidate["club_name"], threshold=1.0)]
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in [*(same_club or local.values()), *(provider.candidates if provider else ())]:
        key = ("master", str(candidate["team_id_master"])) if candidate.get("team_id_master") else (
            "provider", str(candidate.get("team_id")))
        candidates[key] = {**candidates.get(key, {}), **candidate}
    if candidates:
        reason = provider.review_reason if provider else None
        if not reason:
            reason = next((reason for candidate in local.values()
                           if (reason := _identity_conflict_reason(row, candidate))), None)
        return ResolvedTeam(source_index=row.source_index, status="review",
                            provider_team_id=provider.provider_team_id if provider else None,
                            candidates=tuple(candidates.values()), review_reason=reason)
    return ResolvedTeam(source_index=row.source_index, status="unresolved")


def resolve_roster(
    rows: Sequence[RosterRow],
    *,
    gotsport_search: GotsportSearch,
    lookup_provider_id: ProviderIdLookup,
    lookup_exact_name: ExactNameLookup,
    lookup_team_details: TeamDetailsLookup | None = None,
    lookup_club_candidates: ClubCandidateLookup | None = None,
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
                lookup_team_details=lookup_team_details,
                lookup_club_candidates=lookup_club_candidates,
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


def make_team_details_lookup(supabase_client: Any) -> TeamDetailsLookup:
    """Fetch the fields an operator needs to confirm a pasted id is the right team."""

    def lookup(team_id_master: str) -> dict[str, Any] | None:
        rows = (
            supabase_client.table("teams")
            .select("team_id_master,team_name,club_name,age_group,gender,state_code,state")
            .eq("team_id_master", team_id_master)
            .eq("is_deprecated", False)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    return lookup


def fetch_gotsport_provider_id(supabase_client: Any) -> str | None:
    """Resolve the GotSport row in ``providers``.

    Uniqueness on both id-bearing tables is ``(provider_id, provider_team_id)``,
    so every id lookup needs this to be meaningful.
    """
    rows = (
        supabase_client.table("providers")
        .select("id")
        .eq("code", GOTSPORT_PROVIDER_CODE)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0]["id"] if rows else None


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
            cached_provider_id.append(fetch_gotsport_provider_id(supabase_client))
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
    """Build a cohort-scoped literal-name lookup returning canonical team ids.

    Besides the normal ``team_name`` comparison, accept a registered display
    label when it exactly equals the stored ``club_name + team_name``.  No
    prefix is stripped heuristically: both stored fields must match one full
    whitespace-boundary split in the same live cohort.
    """

    def lookup(team_name: str, age_group: str, gender: str) -> list[str]:
        rows = []
        while True:
            page = (
                supabase_client.table("teams")
                .select("team_id_master,team_name,club_name")
                .eq("age_group", age_group)
                .eq("gender", gender)
                .eq("is_deprecated", False)
                .or_(_exact_name_or_filter(team_name))
                .order("team_id_master").range(len(rows), len(rows) + 99)
                .execute().data or []
            )
            rows.extend(page)
            if len(page) < 100:
                break
        expected = _comparable(team_name)
        rows = [
            row
            for row in rows
            if _comparable(row.get("team_name", "")) == expected
            or _comparable(f"{row.get('club_name', '')} {row.get('team_name', '')}") == expected
        ]
        resolved = {_resolved_id(row.get("team_id_master"), merge_resolver) for row in rows}
        return sorted(team_id for team_id in resolved if team_id)

    return lookup


def make_club_candidate_lookup(supabase_client: Any, merge_resolver: Any = None) -> ClubCandidateLookup:
    """Read every current-cohort squad at the submitted club, across providers.

    Include exact squad names under equivalent club labels so a literal-club
    hit cannot hide a second identity. Fetch their metadata in the same paginated
    query instead of issuing one details request per generic-name result.
    Different squad names remain review candidates only.
    """
    def lookup(row: RosterRow) -> list[dict[str, Any]]:
        if not row.club_raw.strip():
            return []
        candidates: dict[str, dict[str, Any]] = {}
        offset = 0
        while True:
            page = (supabase_client.table("teams")
                    .select("team_id_master,team_name,club_name,age_group,gender,state_code,state")
                    .eq("age_group", row.section_age_group).eq("gender", row.section_gender)
                    .eq("is_deprecated", False)
                    .or_(f"club_name.ilike.{_postgrest_ilike_operand(row.club_raw.strip())},"
                         f"{_exact_name_or_filter(row.team_name_stripped)}")
                    .order("team_id_master").range(offset, offset + 99).execute().data or [])
            for candidate in page:
                club = str(candidate.get("club_name") or "").strip()
                literal_club = club.casefold() == row.club_raw.strip().casefold()
                equivalent_identity = (bool(club) and _names_the_same_team(candidate.get("team_name", ""), row)
                                       and are_same_club(row.club_raw, club, threshold=1.0))
                if not literal_club and not equivalent_identity:
                    continue
                team_id = _resolved_id(candidate.get("team_id_master"), merge_resolver)
                if not team_id:
                    continue
                if team_id != candidate["team_id_master"]:
                    candidate = make_team_details_lookup(supabase_client)(team_id)
                if candidate:
                    candidates[team_id] = candidate
            if len(page) < 100:
                return list(candidates.values())
            offset += len(page)
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
