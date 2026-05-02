"""Unit tests for the canonical-team-id resolver wiring inside
``GotsportScraper.fetch_teams_by_cohort``.

Covers the Step B follow-up to PR #713: ``_resolve_canonical_team_id``
maps each per-event registration_id to its canonical gotsport API team_id
via a three-tier priority ladder (``jsonTeamRegs`` mapping →
within-scrape cache → JSON API resolver). Resolver-failed teams get the
``unresolved:{reg_id}`` sentinel and the orchestrator bypasses the
matcher so no fuzzy_auto rows pollute ``team_alias_map``.

These tests instantiate ``GotsportScraper`` with
``skip_team_id_resolution=False`` (the production default) — the existing
``test_fetch_teams_by_cohort.py`` suite uses ``True`` for fast-mode and
therefore cannot exercise the resolver path. All HTTP is mocked.
"""

from __future__ import annotations

import functools
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.scrapers.gotsport import (
    EventTeam,
    GotsportScraper,
)
from tests.conftest import FakeResponse


EVENT_URL = "https://system.gotsport.com/org_event/events/42434"


# ---------- Fixtures ---------------------------------------------------------


def _scraper() -> GotsportScraper:
    """Production-mode scraper: ``skip_team_id_resolution=False`` so the
    resolver runs. This is the path ``tournament_intake.py`` exercises."""
    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "id": "provider-uuid",
        "code": "gotsport",
    }
    return GotsportScraper(supabase, "gotsport", skip_team_id_resolution=False)


def _event_team(
    team_id: str,
    *,
    team_name: str = "Team",
    bracket_name: str = "U13B Elite",
    age_group: str = "u13",
    gender: str = "M",
) -> EventTeam:
    return EventTeam(
        team_id=team_id,
        team_name=team_name,
        bracket_name=bracket_name,
        age_group=age_group,
        gender=gender,
    )


def _landing_html_with_json_team_regs(rows: list[dict]) -> str:
    """Build a minimal landing-page HTML body whose ``<script>`` tag
    embeds ``jsonTeamRegs = [...]`` so the resolver's Priority-1 fast
    path picks it up. Mirrors gotsport's real emit shape — each row
    needs at least ``id`` (registration_id) and optionally ``team_id``
    (canonical api_id) plus ``full_name``.
    """
    import json as _json

    return (
        "<html><body><script>"
        "var jsonTeamRegs = " + _json.dumps(rows) + ";"
        "</script></body></html>"
    )


@pytest.fixture
def scraper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GotsportScraper:
    """Scraper with tmp-rooted journal + tier-orchestrator artifacts."""
    s = _scraper()
    from src.scrapers import gotsport as gs

    real_journal = gs.IntakeJournal

    def _journal_in_tmp(event_key, base_dir="reports"):
        return real_journal(event_key=event_key, base_dir=tmp_path)

    monkeypatch.setattr(gs, "IntakeJournal", _journal_in_tmp)
    real_enrich = gs.enrich_teams_with_tiers
    monkeypatch.setattr(
        gs,
        "enrich_teams_with_tiers",
        functools.partial(real_enrich, base_dir=tmp_path),
    )
    return s


# ---------- Case (a): jsonTeamRegs hit — resolver NOT called ----------------


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch("src.scrapers.gotsport.enqueue_match_review")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
@patch.object(GotsportScraper, "_resolve_api_team_id_from_event_page")
def test_jsonteamregs_hit_promotes_canonical_id_without_resolver_call(
    mock_resolver,
    mock_extract,
    mock_resolve,
    mock_enqueue,
    mock_upsert,
    scraper,
    monkeypatch,
):
    """Priority 1: a team whose reg_id appears in ``jsonTeamRegs`` with a
    distinct ``team_id`` field gets its canonical api_id without any
    HTTP call to the resolver. ``provider_team_id`` is the api_id;
    ``provider_registration_id`` is the reg_id."""
    landing_html = _landing_html_with_json_team_regs(
        [{"id": "3194989", "team_id": "555001", "full_name": "Rush Select"}]
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_event_page",
        lambda event_id: FakeResponse(text=landing_html),
    )
    mock_extract.return_value = {"U13B Elite": [_event_team("3194989", team_name="Rush Select")]}
    from src.scrapers.gotsport import CanonicalResolution

    mock_resolve.return_value = CanonicalResolution(
        team_id_master="master-1",
        confidence=0.99,
        resolved_status="direct_provider_id",
        match_method="direct_id",
        candidates=[],
        provider_id_resolution_status="resolved",
    )
    mock_upsert.return_value = {"action": "created", "match_method": "direct_id", "team_id_master": "master-1"}

    out = scraper.fetch_teams_by_cohort(EVENT_URL)

    mock_resolver.assert_not_called()  # jsonTeamRegs short-circuit
    scraped = out["U13B Elite"][0]
    assert scraped.provider_team_id == "555001"
    assert scraped.provider_registration_id == "3194989"
    assert scraped.provider_team_id != scraped.provider_registration_id


# ---------- Case (b): jsonTeamRegs miss, resolver returns canonical ---------


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch("src.scrapers.gotsport.enqueue_match_review")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
@patch.object(GotsportScraper, "_resolve_api_team_id_from_event_page")
def test_resolver_hit_writes_canonical_id_and_caches(
    mock_resolver,
    mock_extract,
    mock_resolve,
    mock_enqueue,
    mock_upsert,
    scraper,
    monkeypatch,
):
    """Priority 3: the team isn't in ``jsonTeamRegs`` so the JSON API
    resolver is called once and returns a canonical api_id. The cache
    captures the result so a subsequent multi-bracket appearance of the
    same reg_id doesn't trigger a second HTTP call."""
    monkeypatch.setattr(
        scraper,
        "_fetch_event_page",
        lambda event_id: FakeResponse(text="<html></html>"),  # no jsonTeamRegs
    )
    mock_extract.return_value = {
        "U13B Elite": [_event_team("3194989", team_name="Rush Select")],
        "U13B Premier": [_event_team("3194989", team_name="Rush Select")],  # same team, second bracket
    }
    mock_resolver.return_value = "555001"
    from src.scrapers.gotsport import CanonicalResolution

    mock_resolve.return_value = CanonicalResolution(
        team_id_master="master-1",
        confidence=0.99,
        resolved_status="direct_provider_id",
        match_method="direct_id",
        candidates=[],
        provider_id_resolution_status="resolved",
    )
    mock_upsert.return_value = {"action": "created", "match_method": "direct_id", "team_id_master": "master-1"}

    out = scraper.fetch_teams_by_cohort(EVENT_URL)

    assert mock_resolver.call_count == 1, "multi-bracket team should hit cache on second appearance"
    elite = out["U13B Elite"][0]
    premier = out["U13B Premier"][0]
    assert elite.provider_team_id == "555001"
    assert premier.provider_team_id == "555001"
    assert elite.provider_registration_id == "3194989"
    assert premier.provider_registration_id == "3194989"


# ---------- Case (c): resolver returns None → sentinel + matcher bypass -----


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch("src.scrapers.gotsport.enqueue_match_review")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
@patch.object(GotsportScraper, "_resolve_api_team_id_from_event_page")
def test_resolver_miss_emits_sentinel_and_bypasses_matcher(
    mock_resolver,
    mock_extract,
    mock_resolve,
    mock_enqueue,
    mock_upsert,
    scraper,
    monkeypatch,
):
    """When the resolver returns None, the team gets the
    ``unresolved:{reg_id}`` sentinel as ``provider_team_id`` and the
    orchestrator MUST bypass ``resolve_canonical_team_id`` so no
    fuzzy_auto write keyed on the sentinel pollutes the alias map. The
    team still flows to the journal (action='none' is durable) so it
    surfaces in the intake UI's manual-lookup drawer."""
    monkeypatch.setattr(
        scraper,
        "_fetch_event_page",
        lambda event_id: FakeResponse(text="<html></html>"),
    )
    mock_extract.return_value = {"U13B Elite": [_event_team("3194989", team_name="Mystery Team")]}
    mock_resolver.return_value = None  # API miss

    out = scraper.fetch_teams_by_cohort(EVENT_URL)

    assert mock_resolver.call_count == 1
    mock_resolve.assert_not_called(), "matcher must be bypassed for unresolved sentinels"
    mock_upsert.assert_not_called()
    mock_enqueue.assert_not_called()
    scraped = out["U13B Elite"][0]
    assert scraped.provider_team_id == "unresolved:3194989"
    assert scraped.provider_registration_id == "3194989"


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch("src.scrapers.gotsport.enqueue_match_review")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
@patch.object(GotsportScraper, "_resolve_api_team_id_from_event_page")
def test_resolver_miss_caches_none_for_multi_bracket_dedup(
    mock_resolver,
    mock_extract,
    mock_resolve,
    mock_enqueue,
    mock_upsert,
    scraper,
    monkeypatch,
):
    """A multi-bracket team that misses the resolver should be called
    EXACTLY ONCE — the ``api_team_id_cache`` carries None so subsequent
    appearances short-circuit to the same sentinel."""
    monkeypatch.setattr(
        scraper,
        "_fetch_event_page",
        lambda event_id: FakeResponse(text="<html></html>"),
    )
    mock_extract.return_value = {
        "U13B Elite": [_event_team("3194989", team_name="Mystery Team")],
        "U13B Premier": [_event_team("3194989", team_name="Mystery Team")],
    }
    mock_resolver.return_value = None

    out = scraper.fetch_teams_by_cohort(EVENT_URL)

    assert mock_resolver.call_count == 1, "None result must be cached; second bracket reuses it"
    mock_resolve.assert_not_called()
    elite = out["U13B Elite"][0]
    premier = out["U13B Premier"][0]
    assert elite.provider_team_id == "unresolved:3194989"
    assert premier.provider_team_id == "unresolved:3194989"
    # Sentinel-keyed dedup: both bracket entries share the same key in
    # ``bracket_occurrences`` because they have identical
    # ``provider_team_id``.
