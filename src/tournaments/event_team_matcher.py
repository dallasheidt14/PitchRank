"""Tournament-side team matcher built on weekly data hygiene logic."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any, Callable, TypeVar

import httpx

from scripts.find_fuzzy_duplicate_teams import _should_skip_pair, score_team_pair
from scripts.find_queue_matches import (
    extract_age_group,
    extract_club_from_name,
    extract_gender,
    extract_program_tier,
    extract_team_variant,
    has_protected_division,
    normalize_team_name,
)
from src.tournaments.seeding_optimizer import normalize_age_group, normalize_gender_label

logger = logging.getLogger(__name__)

TEAM_SELECT_COLS = "team_id_master,team_name,club_name,state_code,age_group,gender,provider_team_id,is_deprecated"

_T = TypeVar("_T")

_TRANSIENT_HTTPX_ERRORS: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.ReadTimeout,
    httpx.WriteError,
    httpx.PoolTimeout,
)


def _execute_with_retry(
    op: Callable[[], _T],
    *,
    description: str,
    max_attempts: int = 3,
    initial_backoff: float = 0.5,
) -> _T:
    backoff = initial_backoff
    for attempt in range(1, max_attempts + 1):
        try:
            return op()
        except _TRANSIENT_HTTPX_ERRORS as exc:
            if attempt >= max_attempts:
                raise
            logger.warning(
                "Transient httpx error on %s (attempt %d/%d): %s. Retrying in %.1fs.",
                description,
                attempt,
                max_attempts,
                type(exc).__name__,
                backoff,
            )
            time.sleep(backoff)
            backoff *= 2
    raise RuntimeError("unreachable")  # pragma: no cover


@dataclass(frozen=True)
class EventTeamSearchQuery:
    event_team_name: str
    event_age_group: str
    event_gender: str
    event_club_name: str | None = None
    search_age_group: str | None = None
    search_gender: str | None = None
    provider_team_id: str | None = None
    allow_play_up_years: int = 1


@dataclass(frozen=True)
class EventTeamMatch:
    team_id_master: str
    team_name: str
    club_name: str | None
    state_code: str | None
    age_group: str | None
    gender: str | None
    provider_team_id: str | None
    is_deprecated: bool
    score: float
    score_reason: str
    normalized_name_exact: bool
    club_exact: bool
    club_similarity: float
    same_club: bool
    age_match_kind: str
    variant: str | None
    program_tier: str | None


@dataclass(frozen=True)
class EventTeamSearchResult:
    query: dict[str, Any]
    resolved_status: str
    best_score: float | None
    second_score: float | None
    score_gap: float | None
    candidate_age_groups: list[str]
    matches: list[dict[str, Any]]


def _normalize_free_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(normalize_team_name(value).split())


def _normalize_club_name(value: str | None) -> str:
    if not value:
        return ""
    normalized = _normalize_free_text(value)
    return normalized.strip()


def _event_club_name(query: EventTeamSearchQuery) -> str | None:
    explicit = (query.event_club_name or "").strip()
    if explicit:
        return explicit
    extracted = extract_club_from_name(query.event_team_name)
    return extracted.strip() if extracted else None


def _search_age_group(query: EventTeamSearchQuery) -> str | None:
    if query.search_age_group:
        return normalize_age_group(query.search_age_group)
    inferred = extract_age_group(query.event_team_name, {"age_group": query.event_age_group})
    return normalize_age_group(inferred) if inferred else None


def _search_gender(query: EventTeamSearchQuery) -> str:
    if query.search_gender:
        return normalize_gender_label(query.search_gender)
    inferred = extract_gender(query.event_team_name, {"gender": query.event_gender})
    if inferred:
        return normalize_gender_label(inferred)
    return normalize_gender_label(query.event_gender)


def build_candidate_age_groups(query: EventTeamSearchQuery) -> list[str]:
    event_age = normalize_age_group(query.event_age_group)
    search_age = _search_age_group(query)

    ages: list[str] = []

    def add(age_group: str | None) -> None:
        if not age_group:
            return
        normalized = normalize_age_group(age_group)
        if normalized not in ages:
            ages.append(normalized)

    add(search_age)
    add(event_age)

    if event_age.startswith("u"):
        try:
            event_number = int(event_age.removeprefix("u"))
        except ValueError:
            event_number = None
        if event_number is not None:
            for offset in range(1, max(0, query.allow_play_up_years) + 1):
                younger = event_number - offset
                if younger >= 8:
                    add(f"u{younger}")

    return ages


def _build_age_group_or_clause(age_groups: list[str]) -> str:
    values: list[str] = []
    for age_group in age_groups:
        values.append(f"age_group.eq.{age_group}")
        values.append(f"age_group.eq.{age_group.upper()}")
    return ",".join(values)


def fetch_db_candidates(
    client,
    query: EventTeamSearchQuery,
    *,
    include_deprecated: bool = False,
    cache: dict[tuple[tuple[str, ...], str, bool], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    age_groups = tuple(build_candidate_age_groups(query))
    gender = _search_gender(query)
    cache_key = (age_groups, gender, include_deprecated)
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    rows: list[dict[str, Any]] = []
    offset = 0
    page_size = 1000
    age_clause = _build_age_group_or_clause(list(age_groups))

    while True:
        query_builder = client.table("teams").select(TEAM_SELECT_COLS).ilike("gender", gender).or_(age_clause)
        if not include_deprecated:
            query_builder = query_builder.eq("is_deprecated", False)
        paginated = query_builder.range(offset, offset + page_size - 1)
        response = _execute_with_retry(
            paginated.execute,
            description=f"teams page offset={offset} gender={gender}",
        )
        batch = response.data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    if cache is not None:
        cache[cache_key] = rows
    return rows


def _club_similarity(left: str | None, right: str | None) -> float:
    normalized_left = _normalize_club_name(left)
    normalized_right = _normalize_club_name(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return SequenceMatcher(None, normalized_left, normalized_right).ratio()


def _same_club(event_club_name: str | None, candidate_club_name: str | None) -> tuple[bool, float, bool]:
    similarity = _club_similarity(event_club_name, candidate_club_name)
    exact = bool(
        _normalize_club_name(event_club_name)
        and _normalize_club_name(event_club_name) == _normalize_club_name(candidate_club_name)
    )  # noqa: E501
    return exact or similarity >= 0.80, similarity, exact


def _age_match_kind(candidate_age_group: str | None, *, search_age_group: str | None, event_age_group: str) -> str:
    normalized_candidate = normalize_age_group(candidate_age_group)
    normalized_event = normalize_age_group(event_age_group)
    if search_age_group and normalized_candidate == search_age_group:
        return "search_age_exact"
    if normalized_candidate == normalized_event:
        return "event_age_exact"
    return "play_up_or_neighbor"


def rank_db_candidates(
    query: EventTeamSearchQuery,
    candidates: list[dict[str, Any]],
    *,
    limit: int = 10,
) -> list[EventTeamMatch]:
    if has_protected_division(query.event_team_name):
        return []

    event_team_name = query.event_team_name.strip()
    event_club_name = _event_club_name(query)
    normalized_event_name = _normalize_free_text(event_team_name)
    search_age_group = _search_age_group(query)
    event_team = {"team_name": event_team_name, "club_name": event_club_name or ""}

    matches: list[EventTeamMatch] = []
    for candidate in candidates:
        candidate_name = str(candidate.get("team_name") or "").strip()
        if not candidate_name:
            continue

        candidate_provider_team_id = str(candidate.get("provider_team_id") or "").strip() or None
        score_reason = "weekly_score"
        score = None
        if query.provider_team_id and candidate_provider_team_id == str(query.provider_team_id).strip():
            score = 1.0
            score_reason = "provider_team_id"
        else:
            score = score_team_pair(event_team, candidate)
            if score is None:
                continue

        same_club, club_similarity, club_exact = _same_club(event_club_name, candidate.get("club_name"))
        if (
            club_exact
            and score < 0.99
            and _should_skip_pair(event_team_name, candidate_name, club_name=event_club_name or "")
        ):  # noqa: E501
            continue

        normalized_candidate_name = _normalize_free_text(candidate_name)
        normalized_name_exact = normalized_candidate_name == normalized_event_name and bool(normalized_event_name)
        if normalized_name_exact:
            score = max(score, 0.995)
            score_reason = "normalized_name_exact"

        candidate_age_group = normalize_age_group(candidate.get("age_group"))
        age_match_kind = _age_match_kind(
            candidate_age_group,
            search_age_group=search_age_group,
            event_age_group=query.event_age_group,
        )
        if age_match_kind == "search_age_exact":
            score = min(1.0, score + 0.03)
        elif age_match_kind == "event_age_exact":
            score = min(1.0, score + 0.01)

        if event_club_name and not candidate.get("club_name"):
            score = max(0.0, score - 0.08)

        if club_exact:
            score = min(1.0, score + 0.02)
        elif same_club:
            score = min(1.0, score + 0.02)
        elif club_similarity >= 0.88:
            score = min(1.0, score + 0.01)

        if candidate_name.lower().startswith("unknown_"):
            score = max(0.0, score - 0.10)

        matches.append(
            EventTeamMatch(
                team_id_master=str(candidate.get("team_id_master") or ""),
                team_name=candidate_name,
                club_name=candidate.get("club_name"),
                state_code=candidate.get("state_code"),
                age_group=candidate_age_group,
                gender=candidate.get("gender"),
                provider_team_id=candidate_provider_team_id,
                is_deprecated=bool(candidate.get("is_deprecated")),
                score=round(score, 4),
                score_reason=score_reason,
                normalized_name_exact=normalized_name_exact,
                club_exact=club_exact,
                club_similarity=round(club_similarity, 4),
                same_club=same_club,
                age_match_kind=age_match_kind,
                variant=extract_team_variant(candidate_name),
                program_tier=extract_program_tier(candidate_name),
            )
        )

    matches.sort(
        key=lambda item: (
            item.score,
            item.normalized_name_exact,
            item.club_exact,
            not item.team_name.lower().startswith("unknown_"),
            item.age_match_kind == "search_age_exact",
            item.age_match_kind == "event_age_exact",
        ),
        reverse=True,
    )
    return matches[:limit]


def classify_match_result(matches: list[EventTeamMatch]) -> tuple[str, float | None, float | None, float | None]:
    if not matches:
        return "none", None, None, None

    best = matches[0]
    second_score = matches[1].score if len(matches) > 1 else None
    score_gap = round(best.score - second_score, 4) if second_score is not None else None

    if best.score_reason == "provider_team_id":
        return "direct_provider_id", best.score, second_score, score_gap

    if (
        best.normalized_name_exact
        and (best.same_club or best.club_similarity == 0.0)
        and (second_score is None or best.score - second_score >= 0.01)
    ):
        return "strict_exact", best.score, second_score, score_gap

    if best.same_club and best.score >= 0.96 and second_score is None:
        return "high_confidence", best.score, second_score, score_gap

    if best.score >= 0.97 and (second_score is None or best.score - second_score >= 0.015):
        return "high_confidence", best.score, second_score, score_gap

    # Tiebreak rules: when raw scores tie within 0.015, the existing rules above
    # bail to review even though one candidate has a clearly distinguishing
    # attribute. Apply two safe tiebreaks before falling to review.
    if best.score >= 0.90:
        near_tied = [m for m in matches[1:] if (best.score - m.score) <= 0.015]

        # A. best is the only near-tied candidate with normalized_name_exact.
        # The post-normalization name is IDENTICAL between provider and master
        # for this candidate alone, even though raw similarity scores match.
        if (
            best.normalized_name_exact
            and (best.same_club or best.club_similarity == 0.0)
            and near_tied
            and not any(m.normalized_name_exact for m in near_tied)
        ):
            return "strict_exact", best.score, second_score, score_gap

        # B. best is the only near-tied candidate with search_age_exact —
        # competitors are play-up/play-down neighbors. The exact-age candidate
        # is the unambiguous correct match.
        if (
            best.age_match_kind == "search_age_exact"
            and near_tied
            and not any(m.age_match_kind == "search_age_exact" for m in near_tied)
        ):
            return "high_confidence", best.score, second_score, score_gap

        return "review", best.score, second_score, score_gap

    return "none", best.score, second_score, score_gap


def search_event_team_in_db(
    client,
    query: EventTeamSearchQuery,
    *,
    limit: int = 10,
    include_deprecated: bool = False,
    cache: dict[tuple[tuple[str, ...], str, bool], list[dict[str, Any]]] | None = None,
) -> EventTeamSearchResult:
    candidates = fetch_db_candidates(client, query, include_deprecated=include_deprecated, cache=cache)
    matches = rank_db_candidates(query, candidates, limit=limit)
    status, best_score, second_score, score_gap = classify_match_result(matches)
    return EventTeamSearchResult(
        query={
            "event_team_name": query.event_team_name,
            "event_age_group": normalize_age_group(query.event_age_group),
            "event_gender": _search_gender(query),
            "event_club_name": _event_club_name(query),
            "search_age_group": _search_age_group(query),
            "provider_team_id": query.provider_team_id,
        },
        resolved_status=status,
        best_score=best_score,
        second_score=second_score,
        score_gap=score_gap,
        candidate_age_groups=build_candidate_age_groups(query),
        matches=[asdict(match) for match in matches],
    )


def _query_from_registry_row(row: dict[str, Any]) -> EventTeamSearchQuery:
    return EventTeamSearchQuery(
        event_team_name=str(row.get("event_team_name") or "").strip(),
        event_age_group=str(row.get("event_age_group") or row.get("display_age_group") or "").strip(),
        event_gender=str(row.get("event_gender") or row.get("display_gender") or "").strip(),
        event_club_name=str(row.get("event_club_name") or "").strip() or None,
        search_age_group=str(row.get("search_age_group") or "").strip() or None,
        provider_team_id=str(row.get("resolved_gotsport_provider_team_id") or "").strip() or None,
    )


def enrich_registry_rows_with_matcher(
    client,
    registry_rows: list[dict[str, Any]],
    *,
    accepted_statuses: set[str] | None = None,
    cache: dict[tuple[tuple[str, ...], str, bool], list[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Run the team matcher over registry rows and back-fill matcher_* columns.

    Skips rows where ``in_scope_u10_u19 != "True"`` (literal-string contract,
    matches ``backtest_tournament_event.py:177``). Short-circuits rows whose
    ``resolved_gotsport_provider_team_id`` is set AND ``canonical_resolution_status``
    is in ``{"direct_provider_id", "strict_exact", "high_confidence"}`` — those
    are already canonically resolved and the matcher pass would just confirm
    what's there.

    Score columns store raw float (or ``""`` for None) at the in-memory dict
    shape; CSV serialization stringifies the float. Never emits ``"0.0"`` or
    ``"None"`` for missing.

    For accepted matches, the canonical ``resolved_*`` columns are filled
    only when currently empty (operator-edit preservation policy from the
    legacy CLI flow). ``canonical_resolution_status`` is the column-output
    written unconditionally on accepted matches — Step 2's ``build_registry_entry``
    leaves it ``""`` so this pass is the sole writer.

    The ``cache`` parameter is load-bearing for performance — memory
    ``gotcha_matcher_cache_load_bearing.md``: without per-batch caching,
    scrapes go from minutes to 30+ minutes. When ``cache`` is None, a fresh
    dict is allocated for this call (preserves the CLI's ``cache=None`` call
    site). When provided, the cache is mutated in place and the caller can
    inspect post-call.
    """
    accepted_statuses = accepted_statuses or {"direct_provider_id", "strict_exact", "high_confidence"}
    enriched_rows = deepcopy(registry_rows)
    if cache is None:
        cache = {}
    status_counts: dict[str, int] = defaultdict(int)

    for row in enriched_rows:
        row.setdefault("matcher_status", "")
        row.setdefault("matcher_best_score", "")
        row.setdefault("matcher_second_score", "")
        row.setdefault("matcher_score_gap", "")
        row.setdefault("matcher_resolved_team_id_master", "")
        row.setdefault("matcher_resolved_team_name", "")
        row.setdefault("matcher_resolved_club_name", "")
        row.setdefault("matcher_resolved_provider_team_id", "")

        if row.get("in_scope_u10_u19") != "True":
            continue

        existing_provider_id = str(row.get("resolved_gotsport_provider_team_id") or "").strip()
        existing_status = str(row.get("canonical_resolution_status") or "").strip()
        if existing_provider_id and existing_status not in {"", "none", "review"}:
            continue

        result = search_event_team_in_db(
            client,
            _query_from_registry_row(row),
            limit=5,
            cache=cache,
        )
        status_counts[result.resolved_status] += 1
        row["matcher_status"] = result.resolved_status
        row["matcher_best_score"] = "" if result.best_score is None else result.best_score
        row["matcher_second_score"] = "" if result.second_score is None else result.second_score
        row["matcher_score_gap"] = "" if result.score_gap is None else result.score_gap

        if not result.matches:
            continue

        best = result.matches[0]
        row["matcher_resolved_team_id_master"] = best.get("team_id_master", "")
        row["matcher_resolved_team_name"] = best.get("team_name", "")
        row["matcher_resolved_club_name"] = best.get("club_name", "")
        row["matcher_resolved_provider_team_id"] = best.get("provider_team_id", "")

        if result.resolved_status not in accepted_statuses:
            continue

        if not existing_provider_id:
            row["resolved_gotsport_provider_team_id"] = best.get("provider_team_id", "") or existing_provider_id
        if not row.get("resolved_team_id_master"):
            row["resolved_team_id_master"] = best.get("team_id_master", "")
        if not row.get("resolved_team_name"):
            row["resolved_team_name"] = best.get("team_name", "")
        if not row.get("resolved_club_name"):
            row["resolved_club_name"] = best.get("club_name", "")
        row["canonical_resolution_status"] = result.resolved_status

    return enriched_rows, dict(status_counts)
