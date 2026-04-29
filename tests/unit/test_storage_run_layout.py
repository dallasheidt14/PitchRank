"""Unit tests for ``src.tournaments.storage.run_layout``.

Covers the full run state machine: stage → promote/fail/cancel, the F3
stale-destination guard on promote, and ``list_runs(completed_only=True)``
filtering.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tournaments.storage.event_key import scenario_dir
from src.tournaments.storage.run_layout import (
    RunLockError,
    RunStateError,
    acquire_run_lock,
    cancel_run,
    create_staging_run,
    fail_run,
    list_runs,
    promote_run,
)
from src.tournaments.storage.scenario import ensure_scenario

EVENT_KEY = "gotsport__45224__2026"
SCENARIO = "default"


def _runs_root(base: Path) -> Path:
    return scenario_dir(EVENT_KEY, SCENARIO, base_dir=base) / "runs"


def test_create_staging_run_creates_tmp(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    staging = create_staging_run(EVENT_KEY, SCENARIO, "run_001", base_dir=tmp_path)
    assert staging.exists()
    assert staging.name == "run_001.tmp"


def test_create_staging_rejects_existing_tmp(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    create_staging_run(EVENT_KEY, SCENARIO, "run_001", base_dir=tmp_path)
    with pytest.raises(RunStateError, match="already exists"):
        create_staging_run(EVENT_KEY, SCENARIO, "run_001", base_dir=tmp_path)


def test_promote_writes_done_then_renames(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    create_staging_run(EVENT_KEY, SCENARIO, "run_001", base_dir=tmp_path)

    final_dir = promote_run(EVENT_KEY, SCENARIO, "run_001", base_dir=tmp_path)
    assert final_dir.name == "run_001"
    assert final_dir.exists()
    assert not (_runs_root(tmp_path) / "run_001.tmp").exists()
    done_payload = json.loads((final_dir / "done.json").read_text(encoding="utf-8"))
    assert done_payload["run_id"] == "run_001"
    assert done_payload["schema_version"] == 1
    assert "promoted_at" in done_payload


def test_fail_writes_error_and_renames(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    create_staging_run(EVENT_KEY, SCENARIO, "run_002", base_dir=tmp_path)

    failed_dir = fail_run(EVENT_KEY, SCENARIO, "run_002", "subprocess died", base_dir=tmp_path)
    assert failed_dir.name == "run_002.failed"
    assert failed_dir.exists()
    error_payload = json.loads((failed_dir / "error.json").read_text(encoding="utf-8"))
    assert error_payload["error"] == "subprocess died"
    assert error_payload["schema_version"] == 1


def test_cancel_writes_cancelled_and_renames(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    create_staging_run(EVENT_KEY, SCENARIO, "run_003", base_dir=tmp_path)

    cancelled_dir = cancel_run(EVENT_KEY, SCENARIO, "run_003", base_dir=tmp_path)
    assert cancelled_dir.name == "run_003.cancelled"
    payload = json.loads((cancelled_dir / "cancelled.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == "run_003"
    assert payload["schema_version"] == 1


def test_promote_missing_staging_raises(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    with pytest.raises(RunStateError, match="staging dir missing"):
        promote_run(EVENT_KEY, SCENARIO, "ghost_run", base_dir=tmp_path)


def test_promote_stale_destination_raises_before_writes(tmp_path: Path):
    """F3: pre-existing ``runs/<run_id>/`` blocks promote BEFORE any write."""
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    staging = create_staging_run(EVENT_KEY, SCENARIO, "run_004", base_dir=tmp_path)
    # Pre-create a stub final dir with content.
    final_dir = _runs_root(tmp_path) / "run_004"
    final_dir.mkdir()
    (final_dir / "stale.txt").write_text("stale")

    with pytest.raises(RunStateError, match="already exists"):
        promote_run(EVENT_KEY, SCENARIO, "run_004", base_dir=tmp_path)

    # Staging untouched, no done.json written.
    assert staging.exists()
    assert not (staging / "done.json").exists()
    # Stale content untouched.
    assert (final_dir / "stale.txt").read_text() == "stale"


def test_list_runs_completed_only_filters(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    create_staging_run(EVENT_KEY, SCENARIO, "run_a", base_dir=tmp_path)
    promote_run(EVENT_KEY, SCENARIO, "run_a", base_dir=tmp_path)

    create_staging_run(EVENT_KEY, SCENARIO, "run_b", base_dir=tmp_path)
    fail_run(EVENT_KEY, SCENARIO, "run_b", "boom", base_dir=tmp_path)

    create_staging_run(EVENT_KEY, SCENARIO, "run_c", base_dir=tmp_path)
    cancel_run(EVENT_KEY, SCENARIO, "run_c", base_dir=tmp_path)

    create_staging_run(EVENT_KEY, SCENARIO, "run_d", base_dir=tmp_path)  # left .tmp/

    completed = list_runs(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert completed == ["run_a"]

    everything = list_runs(EVENT_KEY, SCENARIO, completed_only=False, base_dir=tmp_path)
    assert sorted(everything) == [
        "run_a",
        "run_b.failed",
        "run_c.cancelled",
        "run_d.tmp",
    ]


def test_list_runs_empty_when_no_runs_dir(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert list_runs(EVENT_KEY, SCENARIO, base_dir=tmp_path) == []


# ---------------------------------------------------------------------------
# acquire_run_lock — mirrors the per-scenario lock contract at the per-run path
# ---------------------------------------------------------------------------


def _promote_run(tmp_path: Path, run_id: str) -> Path:
    """Stage + promote a run so its directory exists for lock acquisition."""
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    create_staging_run(EVENT_KEY, SCENARIO, run_id, base_dir=tmp_path)
    return promote_run(EVENT_KEY, SCENARIO, run_id, base_dir=tmp_path)


def test_acquire_run_lock_holds_within_context(tmp_path: Path):
    run_path = _promote_run(tmp_path, "run_lock_001")
    with acquire_run_lock(EVENT_KEY, SCENARIO, "run_lock_001", base_dir=tmp_path):
        assert (run_path / ".report.lock").exists()


def test_acquire_run_lock_raises_immediately_with_zero_timeout(tmp_path: Path):
    """``timeout=0.0`` is once-and-raise — mirrors scenario-lock contract."""
    _promote_run(tmp_path, "run_lock_002")
    with acquire_run_lock(EVENT_KEY, SCENARIO, "run_lock_002", base_dir=tmp_path):
        with pytest.raises(RunLockError):
            with acquire_run_lock(
                EVENT_KEY,
                SCENARIO,
                "run_lock_002",
                base_dir=tmp_path,
                timeout=0.0,
            ):
                pytest.fail("inner acquire should have raised")


def test_acquire_run_lock_lockfile_persists_after_release(tmp_path: Path):
    """Lockfile is presence/lock primitive — not deleted on context exit."""
    run_path = _promote_run(tmp_path, "run_lock_003")
    with acquire_run_lock(EVENT_KEY, SCENARIO, "run_lock_003", base_dir=tmp_path):
        pass
    assert (run_path / ".report.lock").exists()


def test_acquire_run_lock_raises_filenotfound_when_run_dir_missing(tmp_path: Path):
    """Calling acquire_run_lock for a run that never existed surfaces a
    plain ``FileNotFoundError`` (caller-ordering bug, not a lock bug)."""
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        with acquire_run_lock(EVENT_KEY, SCENARIO, "run_never_promoted", base_dir=tmp_path):
            pytest.fail("acquire should have raised before yielding")
