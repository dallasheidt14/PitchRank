"""Unit tests for ``scripts.verify_scrape_intake``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from src.scrapers.intake_journal import IntakeJournal

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_scrape_intake.py"
_spec = importlib.util.spec_from_file_location("verify_scrape_intake", SCRIPT)
verify_scrape_intake = importlib.util.module_from_spec(_spec)
sys.modules["verify_scrape_intake"] = verify_scrape_intake
_spec.loader.exec_module(verify_scrape_intake)


def _record(
    pid: str,
    *,
    resolved_status: str = "direct_provider_id",
    provider_id_resolution_status: str = "resolved",
    has_view_rankings_link: bool = True,
    team_id_master: str | None = "master-1",
    action: str = "created",
    scraper_state: str = "alias_written",
) -> dict:
    return {
        "run_id": "2026-04-24T10:00:00+00:00",
        "provider_team_id": pid,
        "team_name": f"Team {pid}",
        "has_view_rankings_link": has_view_rankings_link,
        "provider_id_resolution_status": provider_id_resolution_status,
        "canonical": {
            "team_id_master": team_id_master,
            "resolved_status": resolved_status,
            "scraper_state": scraper_state,
        },
        "alias_writer_action": action,
    }


@pytest.fixture
def journal_dir(tmp_path: Path) -> str:
    """Base dir for IntakeJournal; tests write records into it."""
    return str(tmp_path)


def _seed(journal_dir: str, event_key: str, records: list[dict]) -> None:
    j = IntakeJournal(event_key=event_key, base_dir=journal_dir)
    with j:
        for r in records:
            j.append(r)


def test_empty_journal_raises_missing(journal_dir):
    with pytest.raises(FileNotFoundError):
        verify_scrape_intake.compute_metrics("gotsport__99__unknown", base_dir=journal_dir)


def test_basic_rates_and_denominators(journal_dir):
    event_key = "gotsport__1__unknown"
    _seed(
        journal_dir, event_key,
        [
            _record("t1", has_view_rankings_link=True, team_id_master="m1", action="created"),
            _record("t2", has_view_rankings_link=True, team_id_master="m2", action="created"),
            _record(
                "t3",
                has_view_rankings_link=True,
                provider_id_resolution_status="link_no_id",
                team_id_master=None,
                action="none",
                scraper_state="unresolved",
            ),
            _record(
                "t4",
                has_view_rankings_link=False,
                provider_id_resolution_status="no_link",
                team_id_master=None,
                action="none",
                scraper_state="unresolved",
            ),
        ],
    )
    m = verify_scrape_intake.compute_metrics(event_key, base_dir=journal_dir)
    assert m["denominators"] == {"provider_id_resolution": 3, "master_team_match": 2}
    assert m["provider_id_resolution_rate"] == pytest.approx(2 / 3)
    assert m["master_team_match_rate"] == 1.0
    assert m["structurally_unresolvable_count"] == 1


def test_queue_stats_and_action_histogram(journal_dir):
    event_key = "gotsport__2__unknown"
    _seed(
        journal_dir, event_key,
        [
            _record("t1", action="created"),
            _record("t2", action="created"),
            _record("t3", action="queued", team_id_master=None, scraper_state="review_queued"),
            _record("t4", action="queued", team_id_master=None, scraper_state="review_queued"),
            _record("t5", action="deduped_pending", team_id_master=None, scraper_state="review_queued"),
            _record("t6", action="skipped_rejected", team_id_master=None, scraper_state="review_queued"),
        ],
    )
    m = verify_scrape_intake.compute_metrics(event_key, base_dir=journal_dir)
    assert m["queue_stats"]["queued"] == 2
    assert m["queue_stats"]["deduped_pending"] == 1
    assert m["queue_stats"]["skipped_rejected"] == 1
    assert m["action_histogram"] == {
        "created": 2,
        "queued": 2,
        "deduped_pending": 1,
        "skipped_rejected": 1,
    }


def test_all_structurally_unresolvable_leaves_master_rate_none(journal_dir):
    event_key = "gotsport__3__unknown"
    _seed(
        journal_dir, event_key,
        [
            _record(
                "t1",
                has_view_rankings_link=False,
                provider_id_resolution_status="no_link",
                team_id_master=None,
                action="none",
                scraper_state="unresolved",
            ),
        ],
    )
    m = verify_scrape_intake.compute_metrics(event_key, base_dir=journal_dir)
    assert m["provider_id_resolution_rate"] is None  # denominator zero
    assert m["master_team_match_rate"] is None
    assert m["structurally_unresolvable_count"] == 1


def test_removed_teams_picked_up_from_artifact(journal_dir):
    event_key = "gotsport__4__unknown"
    _seed(journal_dir, event_key, [_record("t1", action="created")])
    # Seed a removed_teams.json alongside the journal.
    j = IntakeJournal(event_key=event_key, base_dir=journal_dir)
    j.removed_teams_path.parent.mkdir(parents=True, exist_ok=True)
    j.removed_teams_path.write_text(
        json.dumps({"run_id": "r", "removed_provider_team_ids": ["old1", "old2"]}),
        encoding="utf-8",
    )
    m = verify_scrape_intake.compute_metrics(event_key, base_dir=journal_dir)
    assert m["removed_teams"] == ["old1", "old2"]


def test_below_threshold_helper():
    below = verify_scrape_intake._below_threshold
    assert below({"provider_id_resolution_rate": 0.90, "master_team_match_rate": 0.90}) is True
    assert below({"provider_id_resolution_rate": 0.95, "master_team_match_rate": 0.50}) is True
    assert below({"provider_id_resolution_rate": 0.95, "master_team_match_rate": 0.80}) is False
    # None rates (empty denominators) don't count as below-threshold.
    assert below({"provider_id_resolution_rate": None, "master_team_match_rate": None}) is False
