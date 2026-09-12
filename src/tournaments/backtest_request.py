"""Build strict cohort backtest requests from a reviewed local intake."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from src.tournaments.backtest_intake_state import BacktestSnapshot, effective_roster, entrant_key
from src.tournaments.backtest_link_store import EventLinks
from src.tournaments.backtest_result_summary import deduplicated_fixtures_by_group
from src.tournaments.schedule_simulator import explicit_division_schedule_template


class BacktestRequestError(ValueError):
    """The local intake lacks evidence required for an exact replay."""


def _fixture_game(
    fixture,
    *,
    division_name: str,
    canonical_by_registration: Mapping[str, str],
) -> dict[str, Any] | None:
    if fixture.home_score is None or fixture.away_score is None:
        return None
    home_registration = str(fixture.home_registration_id or "")
    away_registration = str(fixture.away_registration_id or "")
    home_canonical = canonical_by_registration.get(home_registration)
    away_canonical = canonical_by_registration.get(away_registration)
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
) -> tuple[dict[str, Any], ...]:
    """Translate checked divisions, exact pools, and saved links into requests."""

    roster = effective_roster(snapshot)
    if event_links is None or event_links.event_id != roster.event_id:
        raise BacktestRequestError("The reviewed event needs its matching EventLinks decision record")
    confirmed_links = {
        link.registration_id: link
        for link in event_links.links
        if link.matched_by in {"gotsport_id", "operator"}
    }
    all_links = {link.registration_id: link for link in event_links.links}
    removed_registrations = set(event_links.removed_registration_ids)
    not_found_registrations = set(event_links.not_found_registration_ids)
    collision_acknowledgements = {
        item.team_id_master: frozenset(item.registration_ids)
        for item in event_links.collision_acknowledgements
    }
    reviews = {review.group_id: review for review in snapshot.reviews}
    resolved_by_source = {item.source_index: item for item in snapshot.resolved}
    roster_teams_by_group_registration = {
        (team.group_id, entrant_key(team)): team for team in roster.teams
    }
    fixtures_by_group = deduplicated_fixtures_by_group(roster)
    cohorts: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for division in roster.divisions:
        cohorts[(division.age_group, division.gender)].append(division)

    requests: list[dict[str, Any]] = []
    registrations_by_canonical: dict[str, set[str]] = defaultdict(set)
    for cohort_key in sorted(cohorts):
        age_group, gender = cohort_key
        if not age_group or not gender:
            raise BacktestRequestError("Every replayed division needs a reviewed tournament cohort and gender")
        divisions_payload: list[dict[str, Any]] = []
        entrants: list[dict[str, Any]] = []
        actual_games: list[dict[str, Any]] = []
        canonical_by_registration: dict[str, str] = {}

        for division in cohorts[cohort_key]:
            division_fixtures = fixtures_by_group.get(division.group_id, ())
            review = reviews.get(division.group_id)
            if review is None or not review.checked or not review.format_code:
                raise BacktestRequestError(
                    f"Division '{division.division_label}' needs a checked review and verified replay format"
                )
            pool_sizes = tuple(len(pool.members) for pool in division.pools)
            if not pool_sizes or any(size <= 0 for size in pool_sizes):
                raise BacktestRequestError(f"Division '{division.division_label}' has no readable pool membership")
            try:
                template = explicit_division_schedule_template(
                    division_name=division.division_label,
                    pool_sizes=pool_sizes,
                    format_code=review.format_code,
                    actual_game_count=len(division_fixtures),
                    actual_division_name=division.division_label,
                )
            except ValueError as error:
                raise BacktestRequestError(str(error)) from error
            expected_pool_games = sum(size * (size - 1) // 2 for size in pool_sizes)
            captured_pool_games = sum(1 for fixture in division_fixtures if fixture.kind == "pool")
            expected_bracket_games = len(division_fixtures) - expected_pool_games
            captured_bracket_games = sum(1 for fixture in division_fixtures if fixture.kind == "bracket")
            if captured_pool_games != expected_pool_games or captured_bracket_games != expected_bracket_games:
                raise BacktestRequestError(
                    f"Division '{division.division_label}' fixture stages disagree with verified format "
                    f"{review.format_code}"
                )
            divisions_payload.append(
                {
                    "name": division.division_label,
                    "actual_division_name": division.division_label,
                    "group_id": division.group_id,
                    "team_count": sum(pool_sizes),
                    "pool_sizes": list(pool_sizes),
                    "advancement": review.format_code,
                    "playoff_format": template.playoff_format,
                    "captured_fixture_count": len(division_fixtures),
                }
            )
            for pool in division.pools:
                for member in pool.members:
                    registration = str(member.registration_id)
                    roster_team = roster_teams_by_group_registration.get((division.group_id, registration))
                    if roster_team is None:
                        raise BacktestRequestError(
                            f"Pool member {registration} in '{division.division_label}' is missing from the roster"
                        )
                    if registration in removed_registrations:
                        raise BacktestRequestError(
                            f"Team '{member.team_name}' in '{division.division_label}' has a cleared match"
                        )
                    if registration in not_found_registrations:
                        raise BacktestRequestError(
                            f"Team '{member.team_name}' in '{division.division_label}' is marked not found in PitchRank"
                        )
                    link = confirmed_links.get(registration)
                    if link is None:
                        unconfirmed = all_links.get(registration)
                        detail = (
                            f" has an unconfirmed {unconfirmed.matched_by} suggestion"
                            if unconfirmed is not None
                            else " has no saved match decision"
                        )
                        raise BacktestRequestError(
                            f"Team '{member.team_name}' in '{division.division_label}'{detail}"
                        )
                    resolved = resolved_by_source.get(roster_team.source_index)
                    canonical_id = str(link.team_id_master)
                    canonical_by_registration[registration] = canonical_id
                    registrations_by_canonical[canonical_id].add(registration)
                    entrants.append(
                        {
                            "entrant_id": f"{division.group_id}:{registration}",
                            "registration_id": registration,
                            "canonical_team_id": canonical_id,
                            "ranking_source_team_id": canonical_id,
                            "provider_team_id": str(
                                (resolved.provider_team_id if resolved is not None else None)
                                or roster_team.provider_team_id
                                or ""
                            ),
                            "event_team_name": member.team_name,
                            "event_age_group": age_group,
                            "event_gender": gender,
                            "actual_division_name": division.division_label,
                            "actual_pool_name": pool.label,
                        }
                    )
            for fixture in division_fixtures:
                game = _fixture_game(
                    fixture,
                    division_name=division.division_label,
                    canonical_by_registration=canonical_by_registration,
                )
                if game is not None:
                    actual_games.append(game)

        requests.append(
            {
                "event_name": roster.event_name or f"GotSport event {roster.event_id}",
                "event_id": roster.event_id,
                "age_group": age_group,
                "gender": gender,
                "prediction_date": roster.event_start_date,
                "divisions": divisions_payload,
                "entrants": entrants,
                "actual_games_override": actual_games,
                "assignment_policy": "competitive_balance_only",
                "source_capture_generation": snapshot.generation,
            }
        )
    for canonical_id, registrations in registrations_by_canonical.items():
        if len(registrations) < 2:
            continue
        acknowledged = collision_acknowledgements.get(canonical_id, frozenset())
        if acknowledged != frozenset(registrations):
            raise BacktestRequestError(
                f"Canonical team {canonical_id} is linked to distinct registrations without "
                "an acknowledgement for the exact membership"
            )
    return tuple(requests)
