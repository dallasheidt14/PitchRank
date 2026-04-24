"""Unit tests for ``GotsportScraper.resolve_canonical_team_id`` + helpers.

Covers every row of the plan's Step 6 routing table plus the ``ScrapedTeam``
provider-id resolution-status states (``no_link`` / ``link_no_id`` /
``resolved``). Uses a mocked ``search_event_team_in_db`` so no live DB is
required.

Plan routing table (unchanged by this commit; writes are deferred to the
Step 4+6 integration):

| resolved_status    | best_score | team_id_master | match_method |
|--------------------|------------|----------------|--------------|
| direct_provider_id | >= 0.97    | matches[0]     | direct_id    |
| direct_provider_id | <  0.97    | None           | None         |
| strict_exact       | any        | matches[0]     | fuzzy_auto   |
| high_confidence    | any        | matches[0]     | fuzzy_auto   |
| review             | any        | None           | None         |
| none               | any        | None           | None         |
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.scrapers.gotsport import (
    GotsportScraper,
    _provider_id_resolution_status,
    _route_resolution,
)
from src.scrapers.provider import CanonicalResolution, ScrapedTeam


# ---------- Fixtures ----------


def _scraped_team(
    *,
    provider_team_id: str = "pt-42",
    has_view_rankings_link: bool = True,
    club_name: str | None = "SC Del Sol",
    team_name: str = "SC Del Sol 13B Black",
    cohort_age_group: str = "u13",
    cohort_gender: str = "M",
) -> ScrapedTeam:
    return ScrapedTeam(
        provider_team_id=provider_team_id,
        team_name=team_name,
        club_name=club_name,
        cohort_age_group=cohort_age_group,
        cohort_gender=cohort_gender,
        division=None,
        bracket_name=None,
        playing_up=False,
        has_view_rankings_link=has_view_rankings_link,
    )


def _scraper() -> GotsportScraper:
    """GotsportScraper with a mocked Supabase providers row."""
    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "id": "provider-uuid-xyz",
        "code": "gotsport",
    }
    return GotsportScraper(supabase, "gotsport", skip_team_id_resolution=True)


def _search_result(
    *,
    resolved_status: str,
    best_score: float | None,
    matches: list[dict] | None = None,
) -> MagicMock:
    """Build a fake EventTeamSearchResult-shaped object."""
    r = MagicMock()
    r.resolved_status = resolved_status
    r.best_score = best_score
    r.matches = matches if matches is not None else []
    return r


@pytest.fixture
def scraper() -> GotsportScraper:
    return _scraper()


# ---------- _provider_id_resolution_status ----------


def test_provider_id_status_resolved():
    team = _scraped_team(provider_team_id="pt-42", has_view_rankings_link=True)
    assert _provider_id_resolution_status(team) == "resolved"


def test_provider_id_status_link_no_id():
    team = _scraped_team(provider_team_id="", has_view_rankings_link=True)
    assert _provider_id_resolution_status(team) == "link_no_id"


def test_provider_id_status_no_link():
    team = _scraped_team(provider_team_id="pt-42", has_view_rankings_link=False)
    assert _provider_id_resolution_status(team) == "no_link"


# ---------- _route_resolution (pure) ----------


def test_route_direct_provider_id_at_or_above_threshold():
    assert _route_resolution("direct_provider_id", 0.97) == ("alias", "direct_id")
    assert _route_resolution("direct_provider_id", 0.99) == ("alias", "direct_id")
    assert _route_resolution("direct_provider_id", 1.00) == ("alias", "direct_id")


def test_route_direct_provider_id_below_threshold():
    assert _route_resolution("direct_provider_id", 0.9699) == (None, None)
    assert _route_resolution("direct_provider_id", 0.50) == (None, None)


def test_route_direct_provider_id_missing_score():
    # Defensive: None best_score shouldn't silently elevate to alias.
    assert _route_resolution("direct_provider_id", None) == (None, None)


def test_route_strict_exact_and_high_confidence():
    assert _route_resolution("strict_exact", 0.92) == ("alias", "fuzzy_auto")
    assert _route_resolution("high_confidence", 0.97) == ("alias", "fuzzy_auto")


def test_route_review_goes_to_queue():
    assert _route_resolution("review", 0.92) == (None, None)


def test_route_none_goes_unresolved():
    assert _route_resolution("none", 0.0) == (None, None)
    assert _route_resolution("none", None) == (None, None)


def test_route_unknown_status_is_unresolved():
    # Defensive: future statuses default to unresolved rather than silently
    # routing to alias.
    assert _route_resolution("mystery_new_status", 0.99) == (None, None)


# ---------- resolve_canonical_team_id: plan routing table ----------


@patch("src.tournaments.event_team_matcher.search_event_team_in_db")
def test_resolve_direct_provider_id_at_threshold(mock_search, scraper):
    mock_search.return_value = _search_result(
        resolved_status="direct_provider_id",
        best_score=0.99,
        matches=[{"team_id_master": "master-A", "team_name": "SC Del Sol 13B Black", "score": 0.99}],
    )
    team = _scraped_team()
    res = scraper.resolve_canonical_team_id(team)
    assert isinstance(res, CanonicalResolution)
    assert res.resolved_status == "direct_provider_id"
    assert res.match_method == "direct_id"
    assert res.team_id_master == "master-A"
    assert res.confidence == 0.99
    assert res.provider_id_resolution_status == "resolved"
    assert len(res.candidates) == 1


@patch("src.tournaments.event_team_matcher.search_event_team_in_db")
def test_resolve_direct_provider_id_below_threshold_routes_queue(mock_search, scraper):
    """Plan: direct_provider_id + <0.97 → review queue. team_id_master is None
    in the CanonicalResolution; the caller (fetch_teams_by_cohort) routes to
    enqueue_match_review and persists match_details.suggested_master_team_id
    from the candidates list."""
    mock_search.return_value = _search_result(
        resolved_status="direct_provider_id",
        best_score=0.90,
        matches=[{"team_id_master": "master-B", "score": 0.90}],
    )
    team = _scraped_team()
    res = scraper.resolve_canonical_team_id(team)
    assert res.resolved_status == "direct_provider_id"
    assert res.match_method is None
    assert res.team_id_master is None  # queue routing
    assert res.confidence == 0.90
    # Candidates are still carried so the caller can extract suggested master.
    assert res.candidates == [{"team_id_master": "master-B", "score": 0.90}]


@patch("src.tournaments.event_team_matcher.search_event_team_in_db")
def test_resolve_strict_exact(mock_search, scraper):
    mock_search.return_value = _search_result(
        resolved_status="strict_exact",
        best_score=0.95,
        matches=[{"team_id_master": "master-C", "score": 0.95}],
    )
    team = _scraped_team()
    res = scraper.resolve_canonical_team_id(team)
    assert res.resolved_status == "strict_exact"
    assert res.match_method == "fuzzy_auto"
    assert res.team_id_master == "master-C"
    assert res.confidence == 0.95


@patch("src.tournaments.event_team_matcher.search_event_team_in_db")
def test_resolve_high_confidence(mock_search, scraper):
    mock_search.return_value = _search_result(
        resolved_status="high_confidence",
        best_score=0.98,
        matches=[{"team_id_master": "master-D", "score": 0.98}],
    )
    team = _scraped_team()
    res = scraper.resolve_canonical_team_id(team)
    assert res.resolved_status == "high_confidence"
    assert res.match_method == "fuzzy_auto"
    assert res.team_id_master == "master-D"


@patch("src.tournaments.event_team_matcher.search_event_team_in_db")
def test_resolve_review(mock_search, scraper):
    mock_search.return_value = _search_result(
        resolved_status="review",
        best_score=0.92,
        matches=[
            {"team_id_master": "master-E1", "score": 0.92},
            {"team_id_master": "master-E2", "score": 0.91},
        ],
    )
    team = _scraped_team()
    res = scraper.resolve_canonical_team_id(team)
    assert res.resolved_status == "review"
    assert res.match_method is None
    assert res.team_id_master is None  # queue routing
    assert res.confidence == 0.92
    assert len(res.candidates) == 2


@patch("src.tournaments.event_team_matcher.search_event_team_in_db")
def test_resolve_none(mock_search, scraper):
    mock_search.return_value = _search_result(
        resolved_status="none",
        best_score=0.42,
        matches=[],
    )
    team = _scraped_team()
    res = scraper.resolve_canonical_team_id(team)
    assert res.resolved_status == "none"
    assert res.match_method is None
    assert res.team_id_master is None
    assert res.confidence == 0.42
    assert res.candidates == []


# ---------- resolve_canonical_team_id: ScrapedTeam provider-id states ----------


@patch("src.tournaments.event_team_matcher.search_event_team_in_db")
def test_resolve_team_with_no_view_rankings_link(mock_search, scraper):
    """Plan: when has_view_rankings_link=False, provider_id_resolution_status
    is 'no_link' and provider_team_id is NOT passed to the matcher (we have
    no canonical id to look up by)."""
    mock_search.return_value = _search_result(
        resolved_status="review",
        best_score=0.91,
        matches=[],
    )
    team = _scraped_team(has_view_rankings_link=False)
    res = scraper.resolve_canonical_team_id(team)
    assert res.provider_id_resolution_status == "no_link"
    query_passed = mock_search.call_args[0][1]
    assert query_passed.provider_team_id is None


@patch("src.tournaments.event_team_matcher.search_event_team_in_db")
def test_resolve_team_link_but_no_id(mock_search, scraper):
    mock_search.return_value = _search_result(
        resolved_status="review",
        best_score=0.91,
        matches=[],
    )
    team = _scraped_team(provider_team_id="", has_view_rankings_link=True)
    res = scraper.resolve_canonical_team_id(team)
    assert res.provider_id_resolution_status == "link_no_id"
    query_passed = mock_search.call_args[0][1]
    assert query_passed.provider_team_id is None


@patch("src.tournaments.event_team_matcher.search_event_team_in_db")
def test_resolve_team_resolved_passes_provider_team_id(mock_search, scraper):
    mock_search.return_value = _search_result(
        resolved_status="direct_provider_id",
        best_score=0.99,
        matches=[{"team_id_master": "master-X", "score": 0.99}],
    )
    team = _scraped_team(provider_team_id="pt-42", has_view_rankings_link=True)
    res = scraper.resolve_canonical_team_id(team)
    assert res.provider_id_resolution_status == "resolved"
    query_passed = mock_search.call_args[0][1]
    assert query_passed.provider_team_id == "pt-42"


# ---------- Query-building ----------


@patch("src.tournaments.event_team_matcher.search_event_team_in_db")
def test_resolve_builds_query_from_scraped_team(mock_search, scraper):
    mock_search.return_value = _search_result(resolved_status="none", best_score=None)
    team = _scraped_team(
        team_name="Foo FC 14B Elite",
        club_name="Foo FC",
        cohort_age_group="u14",
        cohort_gender="M",
    )
    scraper.resolve_canonical_team_id(team)
    query = mock_search.call_args[0][1]
    assert query.event_team_name == "Foo FC 14B Elite"
    assert query.event_club_name == "Foo FC"
    assert query.event_age_group == "u14"
    assert query.event_gender == "M"


# ---------- Candidate list is capped at 3 ----------


@patch("src.tournaments.event_team_matcher.search_event_team_in_db")
def test_resolve_caps_candidates_at_3(mock_search, scraper):
    mock_search.return_value = _search_result(
        resolved_status="review",
        best_score=0.92,
        matches=[{"team_id_master": f"m-{i}"} for i in range(10)],
    )
    team = _scraped_team()
    res = scraper.resolve_canonical_team_id(team)
    assert len(res.candidates) == 3


# ---------- Confidence is returned unclamped ----------


@patch("src.tournaments.event_team_matcher.search_event_team_in_db")
def test_resolve_confidence_is_unclamped(mock_search, scraper):
    """Plan: alias_writer applies the fuzzy_confidence_ceiling clamp at
    DB-write time. The CanonicalResolution returned here exposes the true
    pre-clamp score so callers can stash it in match_details.true_confidence
    and priority_score."""
    mock_search.return_value = _search_result(
        resolved_status="high_confidence",
        best_score=0.9995,  # above the 0.99 ceiling
        matches=[{"team_id_master": "master-Y", "score": 0.9995}],
    )
    team = _scraped_team()
    res = scraper.resolve_canonical_team_id(team)
    assert res.confidence == 0.9995
    assert res.match_method == "fuzzy_auto"
