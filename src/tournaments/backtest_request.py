"""Build strict cohort backtest requests from a reviewed local intake."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Collection
from dataclasses import replace
from datetime import date
from typing import Any, Mapping

from src.tournaments.backtest_intake_state import BacktestSnapshot, effective_roster, entrant_key
from src.tournaments.backtest_link_store import EventLinks, canonicalize_event_links
from src.tournaments.backtest_rating_fallback import RATING_FALLBACK_POLICY
from src.tournaments.backtest_replay_format import (
    assess_replay_format,
    build_captured_fixture_slots,
)
from src.tournaments.backtest_result_summary import (
    UNSAFE_REPLAY_FIXTURE_EXCLUSIONS,
    deduplicated_fixtures_by_group,
)
from src.tournaments.backtest_scope import backtest_scope_roster
from src.tournaments.schedule_simulator import (
    SUPPORTED_SCORING_POLICIES,
    captured_division_schedule_template,
)


class BacktestRequestError(ValueError):
    """The local intake lacks evidence required for an exact replay."""


def _fixture_game(
    fixture,
    *,
    division_name: str,
    canonical_by_participant: Mapping[str, str],
) -> dict[str, Any] | None:
    if fixture.home_score is None or fixture.away_score is None:
        return None
    home_registration = str(fixture.home_registration_id or "")
    away_registration = str(fixture.away_registration_id or "")
    home_label = " ".join(str(fixture.home_label or "").split()).casefold()
    away_label = " ".join(str(fixture.away_label or "").split()).casefold()
    home_key = f"registration:{home_registration}" if home_registration else f"name:{home_label}"
    away_key = f"registration:{away_registration}" if away_registration else f"name:{away_label}"
    home_canonical = canonical_by_participant.get(home_key)
    away_canonical = canonical_by_participant.get(away_key)
    if not home_canonical or not away_canonical:
        raise BacktestRequestError(
            f"Fixture {fixture.match_number or fixture.source_url} does not resolve to two matched registrations"
        )
    return {
        "id": str(fixture.source_url or fixture.match_number),
        "division_name": division_name,
        "game_date": str(fixture.date_label or fixture.kickoff),
        "home_team_master_id": home_canonical,
        "away_team_master_id": away_canonical,
        "home_score": int(fixture.home_score),
        "away_score": int(fixture.away_score),
    }


def build_cohort_backtest_requests(
    snapshot: BacktestSnapshot,
    *,
    event_links: EventLinks | None = None,
    resolve_team_id: Callable[[str], str | None] | None = None,
    cohort_filter: Collection[tuple[str, str]] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Translate checked divisions, exact pools, and saved links into requests.

    ``cohort_filter`` lets the UI evaluate and run one cohort without an
    unfinished cohort elsewhere in the same event hiding its readiness.
    """

    roster = backtest_scope_roster(effective_roster(snapshot))
    if not roster.event_start_date:
        raise BacktestRequestError(
            "The reviewed event needs a normalized event start date before a historical backtest can run"
        )
    try:
        prediction_date = date.fromisoformat(str(roster.event_start_date)).isoformat()
    except ValueError as error:
        raise BacktestRequestError(
            "The reviewed event start date must use YYYY-MM-DD before a historical backtest can run"
        ) from error
    if event_links is None or event_links.event_id != roster.event_id:
        raise BacktestRequestError("The reviewed event needs its matching EventLinks decision record")
    if snapshot.tiebreak_decision is None:
        raise BacktestRequestError(
            "Verify the tournament's published tiebreak order before running a Backtest"
        )
    tiebreak_decision = snapshot.tiebreak_decision
    if tiebreak_decision.scoring_policy not in SUPPORTED_SCORING_POLICIES:
        raise BacktestRequestError(
            "Verify the event's published points and standings modifiers; this rule is not supported yet"
        )

    def canonicalize(team_id: str) -> str:
        if resolve_team_id is None:
            return str(team_id)
        return str(resolve_team_id(str(team_id)) or team_id)

    if resolve_team_id is not None:
        event_links = canonicalize_event_links(event_links, resolve_team_id)
    confirmed_links = {
        link.registration_id: link
        for link in event_links.links
        if link.matched_by in {"gotsport_id", "operator"}
    }
    all_links = {link.registration_id: link for link in event_links.links}
    removed_registrations = set(event_links.removed_registration_ids)
    not_found_registrations = set(event_links.not_found_registration_ids)

    collision_acknowledgements = {
        canonicalize(item.team_id_master): frozenset(item.registration_ids)
        for item in event_links.collision_acknowledgements
    }
    selected_group_ids = {division.group_id for division in roster.divisions}
    roster_participants = {
        entrant_key(team) for team in roster.teams if team.group_id in selected_group_ids
    }
    registrations_by_canonical: dict[str, set[str]] = defaultdict(set)
    for participant_key, link in confirmed_links.items():
        if (
            participant_key in roster_participants
            and participant_key not in removed_registrations
            and participant_key not in not_found_registrations
        ):
            registrations_by_canonical[canonicalize(link.team_id_master)].add(participant_key)
    for canonical_id, registrations in registrations_by_canonical.items():
        if len(registrations) < 2:
            continue
        acknowledged = collision_acknowledgements.get(canonical_id, frozenset())
        if acknowledged != frozenset(registrations):
            raise BacktestRequestError(
                f"Canonical team {canonical_id} is linked to distinct registrations without "
                "an acknowledgement for the exact membership"
            )
    reviews = {review.group_id: review for review in snapshot.reviews}
    resolved_by_source = {item.source_index: item for item in snapshot.resolved}
    roster_teams_by_group_registration = {
        (team.group_id, entrant_key(team)): team for team in roster.teams
    }
    fixtures_by_group = deduplicated_fixtures_by_group(roster)
    cohorts: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for division in roster.divisions:
        cohort_key = (division.age_group, division.gender)
        if cohort_filter is None or cohort_key in cohort_filter:
            cohorts[cohort_key].append(division)

    requests: list[dict[str, Any]] = []
    for cohort_key in sorted(cohorts):
        age_group, gender = cohort_key
        if not age_group or not gender:
            raise BacktestRequestError("Every replayed division needs a reviewed tournament cohort and gender")
        divisions_payload: list[dict[str, Any]] = []
        entrants: list[dict[str, Any]] = []
        actual_games: list[dict[str, Any]] = []
        canonical_by_participant: dict[str, str] = {}
        participant_divisions: dict[str, str] = {}

        for division in cohorts[cohort_key]:
            fixture_evidence = fixtures_by_group.get(division.group_id, ())
            fixture_conflicts = tuple(
                item.exclusion
                for item in fixture_evidence
                if item.exclusion in UNSAFE_REPLAY_FIXTURE_EXCLUSIONS
            )
            if fixture_conflicts:
                reasons = ", ".join(sorted(set(fixture_conflicts)))
                raise BacktestRequestError(
                    f"Division '{division.division_label}' has unsafe fixture evidence "
                    f"({reasons}); verify or recapture the source before replay"
                )
            division_fixtures = tuple(item.fixture for item in fixture_evidence)
            review = reviews.get(division.group_id)
            manual_format = review.format_code if review is not None and review.checked else ""
            assessment = assess_replay_format(
                replace(division, fixtures=division_fixtures),
                manual_format=manual_format,
            )
            if not assessment.ready:
                raise BacktestRequestError(
                    f"Division '{division.division_label}' needs replay support: {assessment.reason}"
                )
            format_code = assessment.format_code
            pool_sizes = tuple(len(pool.members) for pool in division.pools)
            if not pool_sizes or any(size <= 0 for size in pool_sizes):
                raise BacktestRequestError(f"Division '{division.division_label}' has no readable pool membership")
            fixture_slots = build_captured_fixture_slots(division, division_fixtures)
            tiebreak_source_urls = tuple(dict.fromkeys(
                (tiebreak_decision.source_url,)
                + tuple(link.url for link in division.rules_links if link.url)
            ))
            pool_format_labels = " ".join(pool.label or "" for pool in division.pools)
            normalized_pool_format = pool_format_labels.casefold().replace("-", " ")
            three_team_head_to_head = (
                "cross bracket" in normalized_pool_format
                or "crossover" in normalized_pool_format
            )
            try:
                template = captured_division_schedule_template(
                    division_name=division.group_id,
                    actual_division_name=division.division_label,
                    pool_sizes=pool_sizes,
                    fixture_slots=fixture_slots,
                    tiebreak_order=tiebreak_decision.order,
                    tiebreak_source_urls=tiebreak_source_urls,
                    scoring_policy=tiebreak_decision.scoring_policy,
                    three_team_head_to_head=three_team_head_to_head,
                )
            except ValueError as error:
                raise BacktestRequestError(str(error)) from error
            divisions_payload.append(
                {
                    "skill_order": len(divisions_payload) + 1,
                    "name": division.group_id,
                    "actual_division_name": division.division_label,
                    "group_id": division.group_id,
                    "team_count": sum(pool_sizes),
                    "pool_sizes": list(pool_sizes),
                    "pool_names": [pool.label or f"Pool {index + 1}" for index, pool in enumerate(division.pools)],
                    "advancement": format_code,
                    "playoff_format": template.playoff_format,
                    "captured_fixture_count": len(division_fixtures),
                    "captured_schedule": template.to_dict(),
                }
            )
            normalized_names = Counter(
                " ".join(member.team_name.split()).casefold()
                for pool in division.pools
                for member in pool.members
            )
            for pool_index, pool in enumerate(division.pools):
                for member in pool.members:
                    registration = str(member.registration_id or "")
                    participant_key = registration or (
                        f"pool:{division.group_id}:{pool.pool_id or pool_index}:{member.standings_position}"
                    )
                    previous_division = participant_divisions.get(participant_key)
                    if previous_division is not None:
                        raise BacktestRequestError(
                            f"Tournament registration/source key '{participant_key}' appears more than once "
                            f"in cohort {age_group} {gender} (divisions {previous_division} and "
                            f"{division.group_id})"
                        )
                    participant_divisions[participant_key] = division.group_id
                    roster_team = roster_teams_by_group_registration.get(
                        (division.group_id, participant_key)
                    )
                    if roster_team is None:
                        raise BacktestRequestError(
                            f"Pool member {registration} in '{division.division_label}' is missing from the roster"
                        )
                    if participant_key in removed_registrations:
                        raise BacktestRequestError(
                            f"Team '{member.team_name}' in '{division.division_label}' has a cleared match"
                        )
                    resolved = resolved_by_source.get(roster_team.source_index)
                    rating_fallback = ""
                    if participant_key in not_found_registrations:
                        canonical_id = f"not-found:{roster.event_id}:{participant_key}"
                        ranking_source_id = ""
                        rating_fallback = RATING_FALLBACK_POLICY
                    else:
                        link = confirmed_links.get(participant_key)
                        if link is None:
                            unconfirmed = all_links.get(participant_key)
                            detail = (
                                f" has an unconfirmed {unconfirmed.matched_by} suggestion"
                                if unconfirmed is not None
                                else " has no saved match decision"
                            )
                            raise BacktestRequestError(
                                f"Team '{member.team_name}' in '{division.division_label}'{detail}"
                            )
                        canonical_id = canonicalize(link.team_id_master)
                        ranking_source_id = canonical_id
                    if registration:
                        canonical_by_participant[f"registration:{registration}"] = canonical_id
                    normalized_name = " ".join(member.team_name.split()).casefold()
                    if normalized_names[normalized_name] == 1:
                        canonical_by_participant[f"name:{normalized_name}"] = canonical_id
                    entrants.append(
                        {
                            "entrant_id": f"{division.group_id}:{participant_key}",
                            "registration_id": registration,
                            "source_entry_key": participant_key if not registration else "",
                            "canonical_team_id": canonical_id,
                            "ranking_source_team_id": ranking_source_id,
                            "rating_fallback": rating_fallback,
                            "provider_team_id": str(
                                (resolved.provider_team_id if resolved is not None else None)
                                or roster_team.provider_team_id
                                or ""
                            ),
                            "event_team_name": member.team_name,
                            "event_age_group": age_group,
                            "event_gender": gender,
                            "actual_division_key": division.group_id,
                            "actual_division_name": division.division_label,
                            "actual_pool_key": (
                                f"{division.group_id}:{pool.pool_id or f'row:{pool_index}'}"
                            ),
                            "actual_pool_name": pool.label,
                        }
                    )
            for evidence in fixture_evidence:
                if evidence.exclusion:
                    continue
                game = _fixture_game(
                    evidence.fixture,
                    division_name=division.division_label,
                    canonical_by_participant=canonical_by_participant,
                )
                if game is not None:
                    actual_games.append(game)

        requests.append(
            {
                "event_name": roster.event_name or f"GotSport event {roster.event_id}",
                "event_id": roster.event_id,
                "age_group": age_group,
                "gender": gender,
                "prediction_date": prediction_date,
                "divisions": divisions_payload,
                "entrants": entrants,
                "actual_games_override": actual_games,
                "assignment_policy": "ranked_division_bands_balanced_pools",
                "source_capture_generation": snapshot.generation,
            }
        )
    return tuple(requests)
