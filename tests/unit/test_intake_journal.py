"""Unit tests for ``src.scrapers.intake_journal``.

Covers every Shell 01 Step 4 invariant the plan's Step 7 verification touches:
newline-first append protocol, byte-accurate tail recovery, Windows-safe
compaction (no open handle when ``os.replace`` fires), skip-set computation
under ``--force-teams``, removed-teams diff artifact shape.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.scrapers.intake_journal import (
    DURABLE_ACTIONS,
    IntakeJournal,
    JournalCorruptionError,
    RemovedTeamsDiff,
    compute_skip_set,
)

EVENT_KEY = "gotsport__99999__unknown"


def _record(
    provider_team_id: str,
    run_id: str = "2026-04-24T12:00:00+00:00",
    *,
    action: str = "created",
    extra: dict | None = None,
) -> dict:
    """Plan-shaped JSONL record with sensible defaults."""
    rec = {
        "run_id": run_id,
        "provider_team_id": provider_team_id,
        "team_name": f"Team {provider_team_id}",
        "alias_writer_action": action,
        "canonical": {
            "team_id_master": f"master-{provider_team_id}",
            "confidence": 0.98,
            "resolved_status": "direct_provider_id",
            "match_method": "direct_id",
            "scraper_state": "alias_written",
        },
        "scrape_ts": run_id,
    }
    if extra:
        rec.update(extra)
    return rec


@pytest.fixture
def journal(tmp_path: Path) -> IntakeJournal:
    """Fresh journal rooted at a tmp dir."""
    return IntakeJournal(event_key=EVENT_KEY, base_dir=tmp_path)


# -------- startup_cleanup -----------------------------------------------------


def test_startup_cleanup_deletes_stale_tmp(journal: IntakeJournal):
    journal.tmp_path.parent.mkdir(parents=True, exist_ok=True)
    journal.tmp_path.write_bytes(b"garbage from crashed compaction")
    assert journal.tmp_path.exists()
    assert journal.startup_cleanup() is True
    assert not journal.tmp_path.exists()


def test_startup_cleanup_noop_when_absent(journal: IntakeJournal):
    assert journal.startup_cleanup() is False


# -------- append + read round-trip -------------------------------------------


def test_append_writes_newline_first_and_fsyncs(journal: IntakeJournal):
    with journal:
        journal.append(_record("t1"))
    raw = journal.path.read_bytes()
    # File begins with "\n" under the newline-first protocol.
    assert raw.startswith(b"\n")
    # One record decodes.
    lines = [ln for ln in raw.split(b"\n") if ln.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["provider_team_id"] == "t1"


def test_append_without_open_raises(journal: IntakeJournal):
    with pytest.raises(RuntimeError, match="open_for_append"):
        journal.append(_record("t1"))


def test_append_tracks_last_good_offset(journal: IntakeJournal):
    with journal:
        off1 = journal.append(_record("t1"))
        off2 = journal.append(_record("t2"))
    assert off1 > 0
    assert off2 > off1
    assert off2 == journal.path.stat().st_size


# -------- read / resume -------------------------------------------------------


def test_read_empty_journal(journal: IntakeJournal):
    assert journal.read() == {}
    assert journal.last_good_offset == 0


def test_read_nonexistent_file(journal: IntakeJournal):
    assert not journal.path.exists()
    assert journal.read() == {}


def test_read_latest_run_id_wins(journal: IntakeJournal):
    with journal:
        journal.append(_record("t1", run_id="2026-04-24T10:00:00+00:00", action="created"))
        journal.append(_record("t1", run_id="2026-04-24T11:00:00+00:00", action="updated"))
        journal.append(_record("t2", run_id="2026-04-24T10:30:00+00:00", action="queued"))

    store = journal.read()
    assert set(store.keys()) == {"t1", "t2"}
    assert store["t1"]["alias_writer_action"] == "updated"  # latest run_id wins
    assert store["t2"]["alias_writer_action"] == "queued"


def test_read_recovers_from_partial_tail_line(journal: IntakeJournal):
    with journal:
        journal.append(_record("t1"))
        journal.append(_record("t2"))
    # Simulate a crash mid-append: write an incomplete line at the tail.
    with open(journal.path, "ab") as f:
        f.write(b'\n{"provider_team_id": "t3", "run_id": "2026-0')

    store = journal.read()
    assert set(store.keys()) == {"t1", "t2"}, "partial tail record must be dropped"
    # After read(), the file should have been truncated back to the last good offset.
    assert journal.path.stat().st_size == journal.last_good_offset
    # Verify the file parses cleanly on a second read.
    store2 = journal.read()
    assert store == store2


def test_read_raises_on_mid_file_corruption(journal: IntakeJournal):
    # Build a journal with a corrupt middle line surrounded by good ones.
    with journal:
        journal.append(_record("t1"))
        journal.append(_record("t2"))
        journal.append(_record("t3"))
    raw = journal.path.read_bytes()
    lines = raw.split(b"\n")
    # lines[0] is empty (leading \n), lines[1..3] are records. Corrupt lines[2].
    lines[2] = b"{garbled"
    journal.path.write_bytes(b"\n".join(lines))

    with pytest.raises(JournalCorruptionError, match="Manual inspection"):
        journal.read()


def test_read_skips_records_without_provider_team_id(journal: IntakeJournal):
    # Plan treats provider_team_id as the index key; records missing it are
    # malformed but shouldn't crash the reader.
    with journal:
        journal.append(_record("t1"))
    with open(journal.path, "ab") as f:
        f.write(b'\n{"team_name": "orphan"}')  # no provider_team_id
    store = journal.read()
    assert set(store.keys()) == {"t1"}


# -------- compaction ----------------------------------------------------------


def test_compact_keeps_latest_drops_stale(journal: IntakeJournal):
    with journal:
        journal.append(_record("t1", run_id="2026-04-24T10:00:00+00:00"))
        journal.append(_record("t1", run_id="2026-04-24T11:00:00+00:00"))
        journal.append(_record("t2", run_id="2026-04-24T10:30:00+00:00"))
        journal.append(_record("t1", run_id="2026-04-24T12:00:00+00:00"))
    kept, dropped = journal.compact()
    assert (kept, dropped) == (2, 2)

    store = journal.read()
    assert store["t1"]["run_id"] == "2026-04-24T12:00:00+00:00"
    assert store["t2"]["run_id"] == "2026-04-24T10:30:00+00:00"


def test_compact_windows_safe_closes_handle_first(journal: IntakeJournal):
    """``os.replace`` on Windows fails if the destination has an open handle.
    Compaction must close the append handle before the replace."""
    journal.open_for_append()
    journal.append(_record("t1"))
    # Don't call close() — compact() must close internally.
    kept, dropped = journal.compact()
    assert kept == 1
    assert journal._handle is None
    assert not journal.tmp_path.exists()  # tmp swapped in
    assert journal.path.exists()


def test_compact_on_empty_journal_is_noop(journal: IntakeJournal):
    # No file created yet.
    kept, dropped = journal.compact()
    assert (kept, dropped) == (0, 0)


def test_compact_leaves_no_tmp_behind(journal: IntakeJournal):
    with journal:
        journal.append(_record("t1"))
    journal.compact()
    assert not journal.tmp_path.exists()


# -------- compute_skip_set ----------------------------------------------------


def test_skip_set_includes_durable_actions():
    store = {
        "t1": _record("t1", action="created"),
        "t2": _record("t2", action="updated"),
        "t3": _record("t3", action="queued"),
        "t4": _record("t4", action="skipped_rejected"),
    }
    skip = compute_skip_set(store)
    assert skip == {"t1", "t2", "t3", "t4"}


def test_skip_set_excludes_db_error():
    store = {
        "t1": _record("t1", action="created"),
        "t2": _record("t2", action="db_error"),
    }
    skip = compute_skip_set(store)
    assert skip == {"t1"}


def test_skip_set_force_teams_clears_all():
    store = {
        "t1": _record("t1", action="created"),
        "t2": _record("t2", action="queued"),
    }
    assert compute_skip_set(store, force_teams=True) == set()


def test_skip_set_excludes_unknown_actions():
    # Defensive: an unknown action should NOT be treated as durable
    # (safer to re-scrape than to skip silently).
    store = {
        "t1": _record("t1", action="mystery_new_action"),
    }
    assert compute_skip_set(store) == set()


def test_durable_actions_frozen():
    # Catch accidental mutation.
    with pytest.raises(AttributeError):
        DURABLE_ACTIONS.add("new_action")  # type: ignore[attr-defined]


# -------- removed-teams diff + artifact --------------------------------------


def test_compute_removed_teams(journal: IntakeJournal):
    with journal:
        journal.append(_record("t1"))
        journal.append(_record("t2"))
        journal.append(_record("t3"))
    diff = journal.compute_removed_teams(
        live_provider_team_ids={"t1", "t3"},  # t2 gone
        run_id="2026-04-24T12:00:00+00:00",
    )
    assert diff.removed_provider_team_ids == ["t2"]
    assert diff.run_id == "2026-04-24T12:00:00+00:00"


def test_compute_removed_teams_all_live(journal: IntakeJournal):
    with journal:
        journal.append(_record("t1"))
    diff = journal.compute_removed_teams({"t1"}, run_id="r")
    assert diff.removed_provider_team_ids == []


def test_write_removed_teams_artifact(journal: IntakeJournal):
    with journal:
        journal.append(_record("t1"))
        journal.append(_record("t2"))
    diff = journal.compute_removed_teams({"t1"}, run_id="2026-04-24T12:00:00+00:00")
    path = journal.write_removed_teams_artifact(diff)
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "run_id": "2026-04-24T12:00:00+00:00",
        "removed_provider_team_ids": ["t2"],
    }


# -------- path / event_key conventions ---------------------------------------


def test_paths_follow_plan_convention(journal: IntakeJournal):
    assert journal.path.name == "raw_scrape.jsonl"
    assert journal.path.parent.name == "intake"
    assert journal.path.parent.parent.name == EVENT_KEY
    assert journal.tmp_path.name == "raw_scrape.jsonl.tmp"
    assert journal.removed_teams_path.name == "removed_teams.json"


# -------- context-manager discipline -----------------------------------------


def test_context_manager_closes_on_exception(journal: IntakeJournal):
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with journal:
            journal.append(_record("t1"))
            raise Boom()
    assert journal._handle is None
    # File is intact and the record is durable.
    store = journal.read()
    assert set(store.keys()) == {"t1"}


def test_subsequent_scrape_appends_without_corruption(journal: IntakeJournal):
    """Two consecutive runs should not corrupt each other's records."""
    with journal:
        journal.append(_record("t1", run_id="2026-04-24T10:00:00+00:00"))
    with journal:
        journal.append(_record("t2", run_id="2026-04-24T11:00:00+00:00"))
    store = journal.read()
    assert set(store.keys()) == {"t1", "t2"}
