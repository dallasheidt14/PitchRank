"""End-to-end wiring of ``enrich_teams_with_tiers`` into ``fetch_teams_by_cohort``.

Exercises the live wiring against captured 42433 fixtures: trims the landing
soup to the 3 gids whose ``schedules?group=<gid>`` subpages we have on disk,
mocks ``self.session.get`` to read those fixtures, asserts the 5 tier fields
land in ``raw_scrape.jsonl`` with the expected residues.
"""

from __future__ import annotations

import functools
import json
import logging
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.scrapers.gotsport import (
    EventCaptchaGatedError,
    EventTeam,
    GotsportScraper,
)
from src.scrapers.provider import CanonicalResolution
from tests.conftest import FakeResponse, trim_landing_to_gids

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gotsport"
EVENT_ID = "42433"
EVENT_URL = f"https://system.gotsport.com/org_event/events/{EVENT_ID}"

# Captured subpage gids — U13 Boys Red, Blue, White respectively.
CAPTURED_GIDS = [365847, 365849, 365850]

# Sampled team_ids extracted from each captured subpage at fixture-write time.
TEAM_IN_RED = "3194980"
TEAM_IN_BLUE = "3551474"
TEAM_IN_WHITE = "3194970"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scraper() -> GotsportScraper:
    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "id": "provider-uuid",
        "code": "gotsport",
    }
    return GotsportScraper(supabase, "gotsport", skip_team_id_resolution=True)


def _synthetic_team(team_id: str, *, age_group: str = "U13") -> EventTeam:
    return EventTeam(
        team_id=team_id,
        team_name=f"Team {team_id}",
        bracket_name="bracket",
        age_group=age_group,
        gender="M",
    )


def _resolution(team_id_master: str = "m") -> CanonicalResolution:
    return CanonicalResolution(
        team_id_master=team_id_master,
        confidence=0.99,
        resolved_status="direct_provider_id",
        match_method="direct_id",
        candidates=[],
        provider_id_resolution_status="resolved",
    )


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def wired_scraper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GotsportScraper:
    """Scraper with IntakeJournal + tier-orchestrator artifacts redirected to
    ``tmp_path``, ``_fetch_event_page`` returning the trimmed 42433 landing,
    and ``self.session.get`` reading captured per-tier fixtures."""
    s = _make_scraper()
    from src.scrapers import gotsport as gs

    real_journal = gs.IntakeJournal
    monkeypatch.setattr(
        gs,
        "IntakeJournal",
        lambda event_key, base_dir="reports": real_journal(event_key=event_key, base_dir=tmp_path),
    )
    real_enrich = gs.enrich_teams_with_tiers
    monkeypatch.setattr(
        gs,
        "enrich_teams_with_tiers",
        functools.partial(real_enrich, base_dir=tmp_path),
    )

    landing_html = (FIXTURES / f"event_{EVENT_ID}.html").read_text(encoding="utf-8")
    trimmed = trim_landing_to_gids(landing_html, CAPTURED_GIDS)
    monkeypatch.setattr(s, "_fetch_event_page", lambda eid: FakeResponse(text=trimmed, url=EVENT_URL))

    def _session_get(url, *args, **kwargs):
        m = re.search(r"group=(\d+)", url)
        if not m:
            return FakeResponse(text="", url=url)
        gid = int(m.group(1))
        path = FIXTURES / f"event_{EVENT_ID}__group_{gid}.html"
        return FakeResponse(text=path.read_text(encoding="utf-8"), url=url)

    s.session = MagicMock()
    s.session.get = _session_get
    # Disable per-subfetch throttle so the test runs in deterministic time.
    s.delay_min = 0.0
    s.delay_max = 0.0
    return s


# ---------------------------------------------------------------------------
# Golden path
# ---------------------------------------------------------------------------


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_golden_path_persists_tier_fields_to_jsonl(
    mock_extract,
    mock_resolve,
    mock_upsert,
    wired_scraper,
    tmp_path,
    caplog,
):
    """Trimmed landing → orchestrator subfetches 3 captured gids → enrichment
    populated → ``raw_scrape.jsonl`` carries the 5 tier fields with expected
    residues for U13 Boys Red/Blue/White."""
    mock_extract.return_value = {
        "U13 Boys Red": [_synthetic_team(TEAM_IN_RED)],
        "U13 Boys Blue": [_synthetic_team(TEAM_IN_BLUE)],
        "U13 Boys White": [_synthetic_team(TEAM_IN_WHITE)],
    }
    mock_resolve.return_value = _resolution()
    mock_upsert.return_value = {"action": "created"}

    caplog.set_level(logging.INFO, logger="src.scrapers.gotsport")
    wired_scraper.fetch_teams_by_cohort(EVENT_URL, force_teams=True)

    journal_path = tmp_path / f"gotsport__{EVENT_ID}__unknown" / "intake" / "raw_scrape.jsonl"
    assert journal_path.exists(), f"no journal at {journal_path}"
    records = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines() if line]
    by_pid = {r["provider_team_id"]: r for r in records}

    red = by_pid[TEAM_IN_RED]
    assert red["group_name"] == "Red"
    assert red["group_id"] == 365847
    assert red["tier_discovery_source"] == "landing"
    assert red["tier_membership_source"] == "subpage"
    assert red["tier_parse_outcome"] == "matched"

    assert by_pid[TEAM_IN_BLUE]["group_name"] == "Blue"
    assert by_pid[TEAM_IN_BLUE]["group_id"] == 365849
    assert by_pid[TEAM_IN_WHITE]["group_name"] == "White"
    assert by_pid[TEAM_IN_WHITE]["group_id"] == 365850

    # End-of-scrape summary log includes the new dropped count field.
    assert any("dropped_out_of_scope_teams=" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Backwards-compat read passthrough
# ---------------------------------------------------------------------------


def test_load_raw_scrape_returns_legacy_records_without_tier_keys(tmp_path):
    """Legacy ``raw_scrape.jsonl`` records (pre-Shell-02) lack the 5 tier
    keys. ``load_raw_scrape`` returns ``list[dict]`` — no implicit
    rehydration / no ``"unenriched"`` injection."""
    from src.tournaments.storage.raw_scrape import load_raw_scrape

    event_key = f"gotsport__{EVENT_ID}__unknown"
    intake = tmp_path / event_key / "intake"
    intake.mkdir(parents=True, exist_ok=True)
    legacy_record = {
        "run_id": "2026-04-29T00:00:00+00:00",
        "provider_team_id": "legacy-1",
        "team_name": "Legacy Team",
        "alias_writer_action": "created",
    }
    (intake / "raw_scrape.jsonl").write_text(json.dumps(legacy_record) + "\n", encoding="utf-8")

    records = load_raw_scrape(event_key=event_key, base_dir=tmp_path)
    assert len(records) == 1
    assert records[0].get("tier_parse_outcome") is None
    assert records[0].get("group_name") is None


# ---------------------------------------------------------------------------
# Captcha mid-subfetch
# ---------------------------------------------------------------------------


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_captcha_mid_subfetch_propagates_and_writes_safe_filename_artifact(
    mock_extract,
    mock_resolve,
    mock_upsert,
    wired_scraper,
    tmp_path,
):
    """An orchestrator subfetch returns a captcha body → orchestrator raises
    ``EventCaptchaGatedError`` and writes ``tier_orchestrator_abort__<safe>.json``
    with sanitized run_id — Windows rejects ``:`` in filenames, so the ISO
    ``run_id`` must be sanitized for the artifact name while the payload
    keeps the canonical form. No journal write occurs (``open_for_append``
    happens AFTER enrichment)."""
    mock_extract.return_value = {"U13 Boys Red": [_synthetic_team(TEAM_IN_RED)]}
    mock_resolve.return_value = _resolution()
    mock_upsert.return_value = {"action": "created"}

    captcha_body = '<html><body>Please verify to continue.<div data-sitekey="6Lc1234567890">x</div></body></html>'

    def _captcha_get(url, *args, **kwargs):
        return FakeResponse(text=captcha_body, url=url)

    wired_scraper.session.get = _captcha_get

    with pytest.raises(EventCaptchaGatedError):
        wired_scraper.fetch_teams_by_cohort(EVENT_URL, force_teams=True)

    intake = tmp_path / f"gotsport__{EVENT_ID}__unknown" / "intake"
    journal = intake / "raw_scrape.jsonl"
    assert (not journal.exists()) or journal.read_text(encoding="utf-8") == ""

    abort_files = list(intake.glob("tier_orchestrator_abort__*.json"))
    assert len(abort_files) == 1, f"expected 1 abort file, got {abort_files}"
    fname = abort_files[0].name
    assert ":" not in fname, f"unsanitized run_id in filename: {fname}"
    abort = json.loads(abort_files[0].read_text(encoding="utf-8"))
    assert abort["failure_kind"] == "captcha"
    # Metrics artifact written immediately after discovery — survives the abort.
    assert (intake / "tier_parse_metrics.json").exists()


# ---------------------------------------------------------------------------
# Micro-cohort filter (fail-open)
# ---------------------------------------------------------------------------


@patch("src.scrapers.gotsport.upsert_team_alias")
@patch.object(GotsportScraper, "resolve_canonical_team_id")
@patch.object(GotsportScraper, "extract_event_teams_by_bracket")
def test_u7_micro_cohort_dropped_loose_age_kept(
    mock_extract,
    mock_resolve,
    mock_upsert,
    wired_scraper,
    tmp_path,
    caplog,
):
    """Positive U7 leading-token → drop. ``"Unknown"`` age_group → kept
    (fail-open polarity)."""
    mock_extract.return_value = {
        "U7 Boys Red": [_synthetic_team("U7-team", age_group="U7")],
        "U13 Loose": [_synthetic_team(TEAM_IN_RED, age_group="Unknown")],
    }
    mock_resolve.return_value = _resolution()
    mock_upsert.return_value = {"action": "created"}

    caplog.set_level(logging.INFO, logger="src.scrapers.gotsport")
    wired_scraper.fetch_teams_by_cohort(EVENT_URL, force_teams=True)

    journal_path = tmp_path / f"gotsport__{EVENT_ID}__unknown" / "intake" / "raw_scrape.jsonl"
    records = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines() if line]
    by_pid = {r["provider_team_id"]: r for r in records}

    assert "U7-team" not in by_pid, "U7 micro-cohort must be filtered"
    assert TEAM_IN_RED in by_pid, "loose age_group ('Unknown') must be kept (fail-open)"

    summary_lines = [r.message for r in caplog.records if "dropped_out_of_scope_teams=" in r.message]
    assert summary_lines, "no fetch_teams_by_cohort summary line emitted"
    assert "dropped_out_of_scope_teams=1" in summary_lines[0]
