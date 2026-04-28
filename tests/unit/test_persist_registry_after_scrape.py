"""Unit tests for ``tournament_intake._persist_registry_after_scrape``.

The factored helper is exercised without Streamlit mocks — it returns plain
Python data, takes ``base_dir`` end-to-end, and the supabase_client is None
in these tests so the matcher-enrichment branch short-circuits with
``matcher_*`` columns staying ``""``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.scrapers.intake_journal import IntakeJournal
from src.tournaments.storage import (
    RegistryPersistResult,
    ScenarioLockError,
    ensure_scenario,
    read_registry,
)
from tournament_intake import _persist_registry_after_scrape

EVENT_KEY = "gotsport__99999__2026"


def _seed_journal(base_dir: Path, *, records: list[dict]) -> None:
    journal = IntakeJournal(event_key=EVENT_KEY, base_dir=base_dir)
    journal.open_for_append()
    try:
        for record in records:
            journal.append(record)
    finally:
        journal.close()


def _journal_record(pid: str, *, age: str = "U14", gender: str = "Male") -> dict:
    return {
        "provider_team_id": pid,
        "team_name": f"Team {pid}",
        "club_name": "Club X",
        "cohort_age_group": age,
        "cohort_gender": gender,
        "provider_id_resolution_status": "resolved",
        "canonical": {
            "scraper_state": "alias_written",
            "team_id_master": f"master-{pid}",
            "resolved_status": "strict_exact",
        },
    }


def test_persist_writes_registry_for_active_scenario(tmp_path: Path):
    ensure_scenario(EVENT_KEY, "default", base_dir=tmp_path)
    _seed_journal(tmp_path, records=[_journal_record("111"), _journal_record("222")])

    results = _persist_registry_after_scrape(EVENT_KEY, "default", supabase_client=None, base_dir=tmp_path)

    assert len(results) == 1
    assert results[0].scenario == "default"
    assert results[0].written is True
    assert results[0].row_count == 2

    loaded = read_registry(EVENT_KEY, "default", base_dir=tmp_path)
    assert {e.resolved_gotsport_provider_team_id for e in loaded} == {"111", "222"}


def test_persist_skips_matcher_when_supabase_client_is_none(tmp_path: Path):
    ensure_scenario(EVENT_KEY, "default", base_dir=tmp_path)
    _seed_journal(tmp_path, records=[_journal_record("111")])

    results = _persist_registry_after_scrape(EVENT_KEY, "default", supabase_client=None, base_dir=tmp_path)

    assert results[0].written is True
    loaded = read_registry(EVENT_KEY, "default", base_dir=tmp_path)
    # Matcher pass skipped → matcher_* columns stay "".
    assert loaded[0].matcher_status == ""
    assert loaded[0].matcher_best_score == ""


def test_persist_fans_out_to_every_scenario(tmp_path: Path):
    ensure_scenario(EVENT_KEY, "default", base_dir=tmp_path)
    ensure_scenario(EVENT_KEY, "branch_a", base_dir=tmp_path)
    _seed_journal(tmp_path, records=[_journal_record("111"), _journal_record("222")])

    results = _persist_registry_after_scrape(EVENT_KEY, "default", supabase_client=None, base_dir=tmp_path)

    by_scenario = {r.scenario: r for r in results}
    assert set(by_scenario) == {"default", "branch_a"}
    assert by_scenario["default"].written is True
    assert by_scenario["branch_a"].written is True
    assert by_scenario["default"].row_count == 2
    assert by_scenario["branch_a"].row_count == 2

    for scenario in ("default", "branch_a"):
        loaded = read_registry(EVENT_KEY, scenario, base_dir=tmp_path)
        assert {e.resolved_gotsport_provider_team_id for e in loaded} == {"111", "222"}


def test_persist_records_lock_contention_per_scenario(tmp_path: Path):
    """Lock failure on one scenario does not abort the fan-out."""
    ensure_scenario(EVENT_KEY, "default", base_dir=tmp_path)
    ensure_scenario(EVENT_KEY, "branch_a", base_dir=tmp_path)
    _seed_journal(tmp_path, records=[_journal_record("111")])

    real_acquire = __import__(
        "src.tournaments.storage.scenario", fromlist=["acquire_scenario_lock"]
    ).acquire_scenario_lock

    import contextlib

    def fake_acquire(event_key, scenario, *, base_dir, timeout):
        if scenario == "branch_a":
            raise ScenarioLockError(f"scenario {scenario!r} is locked by another process")
        return real_acquire(event_key, scenario, base_dir=base_dir, timeout=timeout)

    @contextlib.contextmanager
    def fake_acquire_cm(*args, **kwargs):
        # Re-raise on entry to simulate contention.
        result = fake_acquire(*args, **kwargs)
        with result:
            yield

    with patch("tournament_intake.acquire_scenario_lock", fake_acquire_cm):
        results = _persist_registry_after_scrape(EVENT_KEY, "default", supabase_client=None, base_dir=tmp_path)

    by_scenario = {r.scenario: r for r in results}
    assert by_scenario["default"].written is True
    assert by_scenario["branch_a"].written is False
    assert by_scenario["branch_a"].lock_contention is True
    assert by_scenario["branch_a"].error == "locked by another tab"


def test_persist_raises_when_no_scenarios_exist(tmp_path: Path):
    """ensure_scenario must precede; no scenarios = caller-ordering bug."""
    # Note: we deliberately do NOT call ensure_scenario.
    _seed_journal(tmp_path, records=[_journal_record("111")])

    with pytest.raises(RuntimeError, match="ensure_scenario must precede"):
        _persist_registry_after_scrape(EVENT_KEY, "default", supabase_client=None, base_dir=tmp_path)


def test_persist_empty_journal_writes_header_only_csv(tmp_path: Path):
    ensure_scenario(EVENT_KEY, "default", base_dir=tmp_path)
    # No journal records appended.

    results = _persist_registry_after_scrape(EVENT_KEY, "default", supabase_client=None, base_dir=tmp_path)

    assert isinstance(results[0], RegistryPersistResult)
    assert results[0].written is True
    assert results[0].row_count == 0
    assert read_registry(EVENT_KEY, "default", base_dir=tmp_path) == []
