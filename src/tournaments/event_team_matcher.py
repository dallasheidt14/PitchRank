"""Tournament-side team matcher built on weekly data hygiene logic."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any

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


TEAM_SELECT_COLS = "team_id_master,team_name,club_name,state_code,age_group,gender,provider_team_id,is_deprecated"


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
        response = query_builder.range(offset, offset + page_size - 1).execute()
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
    exact = bool(_normalize_club_name(event_club_name) and _normalize_club_name(event_club_name) == _normalize_club_name(candidate_club_name))
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
        if club_exact and score < 0.99 and _should_skip_pair(event_team_name, candidate_name, club_name=event_club_name or ""):
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

    if best.normalized_name_exact and (best.same_club or best.club_similarity == 0.0) and (
        second_score is None or best.score - second_score >= 0.01
    ):
        return "strict_exact", best.score, second_score, score_gap

    if best.same_club and best.score >= 0.96 and second_score is None:
        return "high_confidence", best.score, second_score, score_gap

    if best.score >= 0.97 and (second_score is None or best.score - second_score >= 0.015):
        return "high_confidence", best.score, second_score, score_gap

    if best.score >= 0.90:
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
