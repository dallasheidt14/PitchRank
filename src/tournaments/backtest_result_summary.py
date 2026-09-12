"""Observed tournament margins from saved fixtures, without matching or scraping.

Only identified games with valid played scores enter the denominator. Legacy
``not_captured`` records retain the earlier parser's numeric scores and count as
played, with their own coverage count. Shootout goals never enter a goal margin.
The source does not separately identify goals scored in extra time.

``unique_fixtures`` counts identified games, including excluded conflicts;
unidentified rows remain separate in ``fixtures_without_identity`` and are
excluded. Thus fixture_rows = unique_fixtures + duplicate_rows +
fixtures_without_identity, and scored_games + excluded_games = unique_fixtures
+ fixtures_without_identity. A game attributed to multiple divisions is excluded
once overall and flagged in every affected breakdown. Breakdown coverage/conflict
counts can consequently overlap; scored-game and margin totals remain additive.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from src.tournaments.gotsport_event_roster import EventRoster
from src.tournaments.gotsport_event_structure import Fixture, ScrapedDivision


@dataclass(frozen=True)
class _Row:
    division: ScrapedDivision
    fixture: Fixture


@dataclass(frozen=True)
class _Game:
    rows: tuple[_Row, ...]
    identified: bool
    exclusion: str = ""
    margin: int | None = None
    legacy: bool = False


_CONFLICTS = frozenset({"conflicting_results", "attribution_conflict", "ambiguous_identity"})
_EXCLUDED_STATUSES = frozenset({"unplayed", "cancelled", "postponed", "forfeit", "unrecognized"})


def _provider_match_id(fixture: Fixture) -> str:
    """The provider's match ID is independent of a division URL's group query."""
    try:
        values = parse_qs(urlparse(fixture.source_url).query).get("match", ())
    except ValueError:
        return ""
    ids = {value for value in values if re.fullmatch(r"[0-9]+", value)}
    return next(iter(ids)) if len(ids) == 1 and len(ids) == len(set(values)) else ""


def _status(fixture: Fixture) -> str:
    return fixture.result_status.strip().lower() or "unknown"


def _valid_scores(fixture: Fixture) -> bool:
    return all(type(score) is int and score >= 0 for score in (fixture.home_score, fixture.away_score))


def _score_signature(fixture: Fixture) -> tuple:
    # Preserve type distinctions: Python otherwise equates True with 1 and 1.0.
    scores = tuple((type(value).__name__, repr(value)) for value in (
        fixture.home_score, fixture.away_score, fixture.home_shootout_score, fixture.away_shootout_score,
    ))
    status = _status(fixture)
    if status == "not_captured" and _valid_scores(fixture):
        status = "played"
    return status, scores


def _classify(rows: list[_Row], *, identified: bool, ambiguous: bool = False) -> _Game:
    capture = tuple(rows)
    if not identified:
        return _Game(capture, False, "missing_identity")
    if ambiguous:
        return _Game(capture, True, "ambiguous_identity")
    placements = {(r.division.group_id, r.division.age_group, r.division.gender) for r in rows}
    if len(placements) > 1:
        return _Game(capture, True, "attribution_conflict")
    participant_conflict = any(len({getattr(row.fixture, field) for row in rows
                                    if getattr(row.fixture, field)}) > 1
                               for field in ("home_registration_id", "away_registration_id"))
    if participant_conflict or len({_score_signature(row.fixture) for row in rows}) > 1:
        return _Game(capture, True, "conflicting_results")
    fixture = rows[0].fixture
    status = _status(fixture)
    if status not in {"played", "not_captured"}:
        return _Game(capture, True, status if status in _EXCLUDED_STATUSES else "unknown")
    if not _valid_scores(fixture):
        return _Game(capture, True, "invalid_score")
    return _Game(capture, True, margin=abs(fixture.home_score - fixture.away_score),
                 legacy=all(_status(row.fixture) == "not_captured" for row in rows))


def _games(roster: EventRoster) -> list[_Game]:
    rows = [_Row(division, fixture) for division in roster.divisions for fixture in division.fixtures]
    provider_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        match_id = _provider_match_id(row.fixture)
        number = row.fixture.match_number.strip()
        if match_id and number:
            provider_ids[row.division.group_id, number].add(match_id)
    buckets: dict[tuple[str, ...], list[_Row]] = defaultdict(list)
    games = []
    ambiguous = set()
    for row in rows:
        match_id = _provider_match_id(row.fixture)
        number = row.fixture.match_number.strip()
        local_key = (row.division.group_id, number)
        if match_id:
            key = ("provider", match_id)
        elif number:
            # A plain division link and a match link can represent the same row.
            candidates = provider_ids[local_key]
            key = (("provider", next(iter(candidates))) if len(candidates) == 1
                   else ("number", *local_key))
            if len(candidates) > 1:
                ambiguous.add(key)
        else:
            # Do not manufacture a game identity from row order or participant names.
            games.append(_classify([row], identified=False))
            continue
        buckets[key].append(row)
    games.extend(_classify(group, identified=True, ambiguous=key in ambiguous) for key, group in buckets.items())
    return games


def deduplicated_fixtures_by_group(roster: EventRoster) -> dict[str, tuple[Fixture, ...]]:
    """Return one captured fixture row per stable game identity and division.

    GotSport can repeat the same identified game in a division response. This
    uses the same identity rules as the result summary so strict request
    validation and reported tournament totals share one denominator. Rows
    without a stable identity remain distinct because merging them would be
    guesswork.
    """

    fixtures: dict[str, list[Fixture]] = defaultdict(list)
    for game in _games(roster):
        rows_by_group: dict[str, list[_Row]] = defaultdict(list)
        for row in game.rows:
            rows_by_group[row.division.group_id].append(row)
        for group_id, rows in rows_by_group.items():
            if game.identified:
                fixtures[group_id].append(rows[0].fixture)
            else:
                fixtures[group_id].extend(row.fixture for row in rows)
    return {group_id: tuple(rows) for group_id, rows in fixtures.items()}


def _metrics(games: list[_Game], *, partial: bool, groups: set[str] | None = None) -> dict[str, Any]:
    counts: Counter = Counter()
    reasons: Counter = Counter()
    for game in games:
        rows = [row for row in game.rows if groups is None or row.division.group_id in groups]
        if not rows:
            continue
        counts["fixture_rows"] += len(rows)
        counts["unique_fixtures"] += int(game.identified)
        counts["duplicate_rows"] += len(rows) - 1 if game.identified else 0
        counts["fixtures_without_identity"] += 0 if game.identified else len(rows)
        if game.exclusion:
            counts["excluded_games"] += 1
            counts["conflicting_games"] += int(game.exclusion in _CONFLICTS)
            reasons[game.exclusion] += 1
        else:
            counts["scored_games"] += 1
            counts["total_goal_margin"] += game.margin
            counts["blowout_games"] += int(game.margin >= 4)
            counts["legacy_scored_games"] += int(game.legacy)
    scored = counts["scored_games"]
    return {
        **{name: counts[name] for name in (
            "fixture_rows", "unique_fixtures", "scored_games", "total_goal_margin", "blowout_games",
            "excluded_games", "duplicate_rows", "conflicting_games", "fixtures_without_identity", "legacy_scored_games",
        )},
        "average_goal_margin": counts["total_goal_margin"] / scored if scored else None,
        "blowout_percentage": 100 * counts["blowout_games"] / scored if scored else None,
        "exclusion_reasons": dict(sorted(reasons.items())),
        "is_partial": partial,
    }


def tournament_result_summary(roster: EventRoster) -> dict[str, Any]:
    """JSON-safe actual results, grouped by the entered tournament cohort/division.

    All averages and percentages use the number of included games, never an
    average of division averages. This function derives only from the immutable
    captured roster; team database ages, ratings and matching are irrelevant.
    """
    games = _games(roster)
    partial = not roster.is_complete
    divisions = {division.group_id: division for division in roster.divisions}
    cohorts: dict[tuple[str, str], set[str]] = defaultdict(set)
    for division in divisions.values():
        cohorts[division.age_group, division.gender].add(division.group_id)

    def cohort_order(cohort):
        age, gender = cohort
        return int(age[1:]) if re.fullmatch(r"u[0-9]{1,2}", age) else 999, age, gender

    return {
        "summary_version": 1,
        "blowout_margin": 4,
        "score_basis": "published_excluding_shootout",
        **_metrics(games, partial=partial),
        "by_cohort": [
            {"age_group": age, "gender": gender, **_metrics(games, partial=partial, groups=cohorts[age, gender])}
            for age, gender in sorted(cohorts, key=cohort_order)
        ],
        "by_division": [
            {"group_id": division.group_id, "division_label": division.division_label,
             "age_group": division.age_group, "gender": division.gender,
             **_metrics(games, partial=partial, groups={division.group_id})}
            for division in divisions.values()
        ],
    }
