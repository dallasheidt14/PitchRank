"""Unit tests for ``GotsportScraper.fetch_teams_by_cohort`` + helpers.

Covers the Step 4 + Step 6 integration deliverables:

- Routing (every row of the plan's routing table produces the expected
  alias_writer call).
- Deferred-enqueue pattern: multi-bracket teams produce ONE alias_writer
  call with merged ``also_appears_in_brackets``.
- Skip-set honored by default; ``force_teams`` bypasses; ``revalidate``
  re-processes non-curated rows via DB lookup.
- Journal writes gated on ``DURABLE_ACTIONS`` — ``db_error`` skips, not
  written to JSONL.
- End-of-scrape compaction + ``removed_teams.json`` artifact emission.
- ``EventCaptchaGatedError`` propagates from ``_fetch_event_page``.

All tests use mocks for ``supabase``, ``extract_event_teams_by_bracket``,
``_fetch_event_page``, and ``alias_writer`` calls — no live DB, no network.
"""

from __future__ import annotations

import functools
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.scrapers.gotsport import (
    EventCaptchaGatedError,
    EventTeam,
    GotsportScraper,
    _build_jsonl_record,
    _event_team_to_scraped_team,
    _scraper_state_from_action,
)
from src.scrapers.provider import CanonicalResolution, ScrapedTeam
from tests.conftest import FakeResponse


EVENT_URL = "https://system.gotsport.com/org_event/events/42434"


# ---------- Fixtures ---------------------------------------------------------


def _scraper() -> GotsportScraper:
    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "id": "provider-uuid",
        "code": "gotsport",
    }
    return GotsportScraper(supabase, "gotsport", skip_team_id_resolution=True)


def _resolution(
    *,
    resolved_status: str,
    match_method: str | None,
    team_id_master: str | None,
    confidence: float | None,
    candidates: list[dict] | None = None,
    provider_id_resolution_status: str = "resolved",
) -> CanonicalResolution:
    return CanonicalResolution(
        team_id_master=team_id_master,
        confidence=confidence,
        resolved_status=resolved_status,
        match_method=match_method,
        candidates=candidates or [],
        provider_id_resolution_status=provider_id_resolution_status,
    )


def _event_team(
    team_id: str = "t1",
    *,
    team_name: str = "Team 1",
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


@pytest.fixture
def scraper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GotsportScraper:
    """Scraper + a tmpdir-rooted journal via monkeypatched IntakeJournal."""
    s = _scraper()
    # Redirect IntakeJournal base_dir to tmp so artifacts don't pollute repo.
    from src.scrapers import gotsport as gs

    real_journal = gs.IntakeJournal

    def _journal_in_tmp(event_key, base_dir="reports"):
        return real_journal(event_key=event_key, base_dir=tmp_path)

    monkeypatch.setattr(gs, "IntakeJournal", _journal_in_tmp)
    # Redirect tier-orchestrator artifact writes to tmp_path too — without
    # this, ``enrich_teams_with_tiers`` writes ``tier_parse_metrics.json``
    # under the live ``reports/`` directory on every test run.
    real_enrich = gs.enrich_teams_with_tiers
    monkeypatch.setattr(
        gs,
        "enrich_teams_with_tiers",
        functools.partial(real_enrich, base_dir=tmp_path),
    )
    # Also stub _fetch_event_page so no network hit.
    monkeypatch.setattr(s, "_fetch_event_page", lambda event_id: FakeResponse())
    return s


# ---------- Helper purity ----------------------------------------------------


def test_event_team_to_scraped_team_with_team_id():
    et = _event_team(team_id="42")
    st = _event_team_to_scraped_team(et, "U13B Elite")
    assert st.provider_team_id == "42"
    assert st.has_view_rankings_link is True
    assert st.team_name == "Team 1"
    assert st.cohort_age_group == "u13"
    assert st.cohort_gender == "M"


def test_event_team_to_scraped_team_without_team_id():
    et = _event_team(team_id="")
    st = _event_team_to_scraped_team(et, "U13B Elite")
    assert st.provider_team_id == ""
    assert st.has_view_rankings_link is False


def test_scraper_state_from_action_table():
    assert _scraper_state_from_action("created") == "alias_written"
    assert _scraper_state_from_action("updated") == "alias_written"
    assert _scraper_state_from_action("skipped_weaker_metadata") == "alias_written"
    assert _scraper_state_from_action("queued") == "review_queued"
    assert _scraper_state_from_action("deduped_pending") == "review_queued"
    assert _scraper_state_from_action("skipped_rejected") == "review_queued"
    assert _scraper_state_from_action("conflict_loop_detected") == "review_queued"
    assert _scraper_state_from_action("none") == "unresolved"
    assert _scraper_state_from_action("db_error") == "unresolved"
    assert _scraper_state_from_action("mystery_action") == "unresolved"


def test_build_jsonl_record_alias_written():
    scraped = ScrapedTeam(
        provider_team_id="t1",
        team_name="T1",
        club_name=None,
        cohort_age_group="u13",
        cohort_gender="M",
        division=None,
        bracket_name="U13B",
        playing_up=False,
        has_view_rankings_link=True,
    )
    res = _resolution(
        resolved_status="direct_provider_id",
        match_method="direct_id",
        team_id_master="master-1",
        confidence=0.99,
    )
    action_dict = {"action": "created"}
    record = _build_jsonl_record(
        scraped=scraped,
        resolution=res,
        action_dict=action_dict,
        brackets=["U13B"],
        run_id="2026-04-24T12:00:00+00:00",
        source_url=EVENT_URL,
        provider_event_id="42434",
    )
    assert record["provider_team_id"] == "t1"
    assert record["canonical"]["scraper_state"] == "alias_written"
    assert record["canonical"]["match_method"] == "direct_id"
    assert record["canonical"]["team_id_master"] == "master-1"
    assert record["alias_writer_action"] == "created"
    assert record["provider_event_id"] == "42434"
    assert record["source_url"] == EVENT_URL


def test_build_jsonl_record_queued_clears_match_method():
    scraped = ScrapedTeam(
        provider_team_id="t1",
        team_name="T1",
        club_name=None,
        cohort_age_group="u13",
        cohort_gender="M",
        division=None,
        bracket_name="U13B",
        playing_up=False,
        has_view_rankings_link=True,
    )
    res = _resolution(
        resolved_status="review",
        match_method=None,
        team_id_master=None,
        confidence=0.92,
        candidates=[{"team_id_master": "candidate-1"}],
    )
    record = _build_jsonl_record(
        scraped=scraped,
        resolution=res,
        action_dict={"action": "queued"},
        brackets=["U13B"],
        run_id="r",
        source_url=EVENT_URL,
        provider_event_id="42434",
    )
    assert record["canonical"]["scraper_state"] == "review_queued"
    assert record["canonical"]["match_method"] is None
    assert record["canonical"]["team_id_master"] is None
    assert record["canonical"]["confidence"] == 0.92


# ---------- fetch_teams_by_cohort: routing -----------------------------------


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch("src.scrapers.gotsport.enqueue_match_review")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_direct_id_at_threshold_routes_to_upsert(mock_extract, mock_resolve, mock_enqueue, mock_upsert, scraper):
    mock_extract.return_value = {"U13B Elite": [_event_team("t1")]}
    mock_resolve.return_value = _resolution(
        resolved_status="direct_provider_id",
        match_method="direct_id",
        team_id_master="master-1",
        confidence=0.99,
    )
    mock_upsert.return_value = {"action": "created"}

    out = scraper.fetch_teams_by_cohort(EVENT_URL)

    mock_upsert.assert_called_once()
    mock_enqueue.assert_not_called()
    call_kwargs = mock_upsert.call_args.kwargs
    assert call_kwargs["match_method"] == "direct_id"
    assert call_kwargs["team_id_master"] == "master-1"
    assert call_kwargs["priority_score"] == 0.99
    assert set(out.keys()) == {"U13B Elite"}


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch("src.scrapers.gotsport.enqueue_match_review")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_direct_id_low_name_score_still_routes_to_upsert(
    mock_extract, mock_resolve, mock_enqueue, mock_upsert, scraper
):
    """direct_provider_id at low name score routes to upsert (direct_id),
    not queue. The matcher's gate at ``_route_resolution`` was removed —
    canonical pid match IS ground truth, names can't override.

    Pre-fix: the gate demoted direct-id matches with score < 0.97 to the
    review queue, leaving curated alias rows un-promoted (e.g. event
    42433's "Dynamos SC 14B SC" vs stored "Dynamos SC 2014 SC")."""
    mock_extract.return_value = {"U13B Elite": [_event_team("t1")]}
    mock_resolve.return_value = _resolution(
        resolved_status="direct_provider_id",
        match_method="direct_id",
        team_id_master="master-1",
        confidence=0.90,
    )
    mock_upsert.return_value = {"action": "created"}

    scraper.fetch_teams_by_cohort(EVENT_URL)

    mock_upsert.assert_called_once()
    mock_enqueue.assert_not_called()
    kwargs = mock_upsert.call_args.kwargs
    assert kwargs["match_method"] == "direct_id"
    assert kwargs["team_id_master"] == "master-1"


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch("src.scrapers.gotsport.enqueue_match_review")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_strict_exact_routes_to_upsert_fuzzy_auto(mock_extract, mock_resolve, mock_enqueue, mock_upsert, scraper):
    mock_extract.return_value = {"B1": [_event_team("t1")]}
    mock_resolve.return_value = _resolution(
        resolved_status="strict_exact",
        match_method="fuzzy_auto",
        team_id_master="master-1",
        confidence=0.95,
    )
    mock_upsert.return_value = {"action": "created"}

    scraper.fetch_teams_by_cohort(EVENT_URL)

    mock_upsert.assert_called_once()
    assert mock_upsert.call_args.kwargs["match_method"] == "fuzzy_auto"


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch("src.scrapers.gotsport.enqueue_match_review")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_review_routes_to_queue_no_reason(mock_extract, mock_resolve, mock_enqueue, mock_upsert, scraper):
    mock_extract.return_value = {"B1": [_event_team("t1")]}
    mock_resolve.return_value = _resolution(
        resolved_status="review",
        match_method=None,
        team_id_master=None,
        confidence=0.92,
        candidates=[{"team_id_master": "candidate-1"}],
    )
    mock_enqueue.return_value = {"action": "queued"}

    scraper.fetch_teams_by_cohort(EVENT_URL)

    mock_upsert.assert_not_called()
    mock_enqueue.assert_called_once()
    md = mock_enqueue.call_args.kwargs["match_details"]
    assert "reason" not in md, "review path has no low-name-sim reason"


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch("src.scrapers.gotsport.enqueue_match_review")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_none_status_neither_writes_nor_journals(
    mock_extract, mock_resolve, mock_enqueue, mock_upsert, scraper, caplog
):
    mock_extract.return_value = {"B1": [_event_team("t1")]}
    mock_resolve.return_value = _resolution(
        resolved_status="none",
        match_method=None,
        team_id_master=None,
        confidence=0.5,
    )

    with caplog.at_level("WARNING"):
        scraper.fetch_teams_by_cohort(EVENT_URL)

    mock_upsert.assert_not_called()
    mock_enqueue.assert_not_called()
    assert any("unresolved" in rec.message for rec in caplog.records)


# ---------- Multi-bracket deferred enqueue -----------------------------------


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch("src.scrapers.gotsport.enqueue_match_review")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_multi_bracket_team_gets_single_writer_call(mock_extract, mock_resolve, mock_enqueue, mock_upsert, scraper):
    """One provider_team_id in 2 brackets → ONE upsert call, with
    ``match_details.also_appears_in_brackets`` listing both."""
    et = _event_team("t1")
    mock_extract.return_value = {
        "U13B Elite": [et],
        "U13B Gold": [et],  # same team, second bracket
    }
    mock_resolve.return_value = _resolution(
        resolved_status="direct_provider_id",
        match_method="direct_id",
        team_id_master="master-1",
        confidence=0.99,
    )
    mock_upsert.return_value = {"action": "created"}

    scraper.fetch_teams_by_cohort(EVENT_URL)

    assert mock_upsert.call_count == 1
    # resolve is also called only once (same pid; first-seen wins).
    assert mock_resolve.call_count == 1


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch("src.scrapers.gotsport.enqueue_match_review")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_multi_bracket_review_carries_all_brackets_in_match_details(
    mock_extract, mock_resolve, mock_enqueue, mock_upsert, scraper
):
    et = _event_team("t1")
    mock_extract.return_value = {"B1": [et], "B2": [et]}
    mock_resolve.return_value = _resolution(
        resolved_status="review",
        match_method=None,
        team_id_master=None,
        confidence=0.92,
        candidates=[{"team_id_master": "cand"}],
    )
    mock_enqueue.return_value = {"action": "queued"}

    scraper.fetch_teams_by_cohort(EVENT_URL)

    md = mock_enqueue.call_args.kwargs["match_details"]
    assert set(md["also_appears_in_brackets"]) == {"B1", "B2"}


# ---------- Skip-set: default / force_teams / revalidate ---------------------


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_default_skip_set_skips_already_resolved(mock_extract, mock_resolve, mock_upsert, scraper):
    # Pre-seed the journal with a durable record for t1.
    from src.scrapers.intake_journal import IntakeJournal
    from src.scrapers import gotsport as gs

    # Use the same monkeypatched IntakeJournal to pre-seed.
    journal = gs.IntakeJournal("gotsport__42434__unknown")
    with journal:
        journal.append(
            {
                "run_id": "2026-04-24T10:00:00+00:00",
                "provider_team_id": "t1",
                "alias_writer_action": "created",
            }
        )

    mock_extract.return_value = {"B1": [_event_team("t1"), _event_team("t2")]}
    mock_resolve.return_value = _resolution(
        resolved_status="direct_provider_id",
        match_method="direct_id",
        team_id_master="master",
        confidence=0.99,
    )
    mock_upsert.return_value = {"action": "created"}

    scraper.fetch_teams_by_cohort(EVENT_URL)

    # Only t2 is resolved — t1 was skipped.
    assert mock_resolve.call_count == 1
    resolved_teams = [call.args[0].provider_team_id for call in mock_resolve.call_args_list]
    assert resolved_teams == ["t2"]


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_force_teams_bypasses_skip_set(mock_extract, mock_resolve, mock_upsert, scraper):
    from src.scrapers import gotsport as gs

    journal = gs.IntakeJournal("gotsport__42434__unknown")
    with journal:
        journal.append(
            {
                "run_id": "2026-04-24T10:00:00+00:00",
                "provider_team_id": "t1",
                "alias_writer_action": "created",
            }
        )

    mock_extract.return_value = {"B1": [_event_team("t1"), _event_team("t2")]}
    mock_resolve.return_value = _resolution(
        resolved_status="direct_provider_id",
        match_method="direct_id",
        team_id_master="master",
        confidence=0.99,
    )
    mock_upsert.return_value = {"action": "created"}

    scraper.fetch_teams_by_cohort(EVENT_URL, force_teams=True)

    assert mock_resolve.call_count == 2


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_revalidate_reprocesses_non_curated_rows(mock_extract, mock_resolve, mock_upsert, scraper):
    """Plan: --revalidate re-resolves non-curated rows. Curated = review_status
    ='approved' AND match_method in {direct_id, manual, manual_review,
    manual_queue, import}. Machine-written fuzzy_auto rows are NOT curated."""
    from src.scrapers import gotsport as gs

    journal = gs.IntakeJournal("gotsport__42434__unknown")
    with journal:
        journal.append(
            {
                "run_id": "2026-04-24T10:00:00+00:00",
                "provider_team_id": "t1",
                "alias_writer_action": "created",
            }
        )
        journal.append(
            {
                "run_id": "2026-04-24T10:00:00+00:00",
                "provider_team_id": "t2",
                "alias_writer_action": "created",
            }
        )

    # DB: t1 is curated (direct_id + approved); t2 is machine (fuzzy_auto).
    scraper.supabase_client.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = [
        {"provider_team_id": "t1", "review_status": "approved", "match_method": "direct_id"},
        {"provider_team_id": "t2", "review_status": "approved", "match_method": "fuzzy_auto"},
    ]

    mock_extract.return_value = {"B1": [_event_team("t1"), _event_team("t2"), _event_team("t3")]}
    mock_resolve.return_value = _resolution(
        resolved_status="direct_provider_id",
        match_method="direct_id",
        team_id_master="m",
        confidence=0.99,
    )
    mock_upsert.return_value = {"action": "created"}

    scraper.fetch_teams_by_cohort(EVENT_URL, revalidate=True)

    # t1 stays skipped (curated); t2 and t3 are re-resolved.
    resolved = [c.args[0].provider_team_id for c in mock_resolve.call_args_list]
    assert "t1" not in resolved
    assert set(resolved) == {"t2", "t3"}


# ---------- Journal durable-action gating ------------------------------------


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_db_error_action_not_written_to_journal(mock_extract, mock_resolve, mock_upsert, scraper, tmp_path):
    """Per plan Step 4: db_error is non-durable — skip JSONL, log, retry next run."""
    from src.scrapers import gotsport as gs

    mock_extract.return_value = {"B1": [_event_team("t1")]}
    mock_resolve.return_value = _resolution(
        resolved_status="direct_provider_id",
        match_method="direct_id",
        team_id_master="m",
        confidence=0.99,
    )
    mock_upsert.return_value = {"action": "db_error", "error": "connection reset"}

    scraper.fetch_teams_by_cohort(EVENT_URL)

    # Post-compaction journal should have no t1 record.
    journal = gs.IntakeJournal("gotsport__42434__unknown")
    store = journal.read()
    assert "t1" not in store


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_durable_action_is_written_to_journal(mock_extract, mock_resolve, mock_upsert, scraper):
    from src.scrapers import gotsport as gs

    mock_extract.return_value = {"B1": [_event_team("t1")]}
    mock_resolve.return_value = _resolution(
        resolved_status="direct_provider_id",
        match_method="direct_id",
        team_id_master="m",
        confidence=0.99,
    )
    mock_upsert.return_value = {"action": "created"}

    scraper.fetch_teams_by_cohort(EVENT_URL)

    journal = gs.IntakeJournal("gotsport__42434__unknown")
    store = journal.read()
    assert "t1" in store
    assert store["t1"]["alias_writer_action"] == "created"
    assert store["t1"]["canonical"]["scraper_state"] == "alias_written"


# ---------- Compaction + removed_teams --------------------------------------


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_compaction_runs_at_end(mock_extract, mock_resolve, mock_upsert, scraper):
    from src.scrapers import gotsport as gs

    mock_extract.return_value = {"B1": [_event_team("t1"), _event_team("t2")]}
    mock_resolve.return_value = _resolution(
        resolved_status="direct_provider_id",
        match_method="direct_id",
        team_id_master="m",
        confidence=0.99,
    )
    mock_upsert.return_value = {"action": "created"}

    scraper.fetch_teams_by_cohort(EVENT_URL)
    journal = gs.IntakeJournal("gotsport__42434__unknown")
    assert journal.path.exists()
    assert not journal.tmp_path.exists()


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_removed_teams_artifact_on_pid_drop(mock_extract, mock_resolve, mock_upsert, scraper):
    """A team present in the journal but absent from this run's live set
    becomes a 'removed_provider_team_id' in the artifact."""
    import json as _json
    from src.scrapers import gotsport as gs

    # Pre-seed journal with t1 + t2.
    journal = gs.IntakeJournal("gotsport__42434__unknown")
    with journal:
        for pid in ("t1", "t2"):
            journal.append(
                {
                    "run_id": "2026-04-24T10:00:00+00:00",
                    "provider_team_id": pid,
                    "alias_writer_action": "created",
                    "canonical": {"scraper_state": "alias_written"},
                }
            )

    # Live scrape includes only t1 (t2 dropped).
    mock_extract.return_value = {"B1": [_event_team("t1")]}
    mock_resolve.return_value = _resolution(
        resolved_status="direct_provider_id",
        match_method="direct_id",
        team_id_master="m",
        confidence=0.99,
    )
    mock_upsert.return_value = {"action": "created"}

    scraper.fetch_teams_by_cohort(EVENT_URL, force_teams=True)

    assert journal.removed_teams_path.exists()
    payload = _json.loads(journal.removed_teams_path.read_text(encoding="utf-8"))
    assert payload["removed_provider_team_ids"] == ["t2"]


# ---------- CAPTCHA propagation ---------------------------------------------


@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_captcha_gated_event_raises(mock_extract, scraper, monkeypatch):
    def raise_captcha(event_id):
        raise EventCaptchaGatedError(
            provider_event_id=event_id,
            captcha_url=f"https://system.gotsport.com/org_event/events/{event_id}/verify_captchas/new",
            sitekey="6Lf7TGog...",
        )

    monkeypatch.setattr(scraper, "_fetch_event_page", raise_captcha)

    with pytest.raises(EventCaptchaGatedError) as exc_info:
        scraper.fetch_teams_by_cohort(EVENT_URL)
    assert exc_info.value.provider_event_id == "42434"
    mock_extract.assert_not_called()


# ---------- URL parsing -----------------------------------------------------


def test_bad_url_raises_value_error(scraper):
    with pytest.raises(ValueError, match="Cannot extract event id"):
        scraper.fetch_teams_by_cohort("https://example.com/not-an-event")
