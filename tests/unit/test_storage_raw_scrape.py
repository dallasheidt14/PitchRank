"""Unit tests for ``src.tournaments.storage.raw_scrape``.

The module is mostly a re-export shim for ``src.scrapers.intake_journal``;
the only added surface is ``load_raw_scrape``. Tests lock down the missing
journal branch and the latest-run-wins ordering contract that Streamlit
triage UIs rely on.
"""

from __future__ import annotations

from pathlib import Path

from src.scrapers.intake_journal import IntakeJournal
from src.tournaments.storage.raw_scrape import load_raw_scrape

EVENT_KEY = "gotsport__45224__2026"


def test_load_raw_scrape_missing_journal_returns_empty(tmp_path: Path):
    assert load_raw_scrape(EVENT_KEY, base_dir=tmp_path) == []


def test_load_raw_scrape_returns_latest_run_per_pid(tmp_path: Path):
    """Latest-run-wins ordering — second record for the same pid replaces the first."""
    journal = IntakeJournal(event_key=EVENT_KEY, base_dir=tmp_path)
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
                "run_id": "2026-04-24T11:00:00+00:00",
                "provider_team_id": "t1",
                "alias_writer_action": "updated",
            }
        )
        journal.append(
            {
                "run_id": "2026-04-24T10:30:00+00:00",
                "provider_team_id": "t2",
                "alias_writer_action": "queued",
            }
        )

    records = load_raw_scrape(EVENT_KEY, base_dir=tmp_path)
    by_pid = {r["provider_team_id"]: r for r in records}
    assert set(by_pid) == {"t1", "t2"}
    assert by_pid["t1"]["alias_writer_action"] == "updated"
    assert by_pid["t2"]["alias_writer_action"] == "queued"
