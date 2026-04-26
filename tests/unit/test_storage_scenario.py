"""Unit tests for ``src.tournaments.storage.scenario``.

Covers branch ``intake/`` exclusion, ``ScenarioExistsError`` on duplicate
dst, ``src == dst`` rejection, and the per-scenario advisory lock
acquire / release semantics (F12 / F16 / F19).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tournaments.storage.event_key import scenario_dir, scenarios_dir
from src.tournaments.storage.scenario import (
    ScenarioExistsError,
    ScenarioLockError,
    acquire_scenario_lock,
    branch_scenario,
    ensure_scenario,
    list_scenarios,
)

EVENT_KEY = "gotsport__45224__2026"


def test_ensure_scenario_creates_directory(tmp_path: Path):
    path = ensure_scenario(EVENT_KEY, "default", base_dir=tmp_path)
    assert path.exists()
    assert path == scenario_dir(EVENT_KEY, "default", base_dir=tmp_path)


def test_ensure_scenario_idempotent(tmp_path: Path):
    ensure_scenario(EVENT_KEY, "default", base_dir=tmp_path)
    ensure_scenario(EVENT_KEY, "default", base_dir=tmp_path)


def test_branch_scenario_excludes_intake(tmp_path: Path):
    src_path = ensure_scenario(EVENT_KEY, "default", base_dir=tmp_path)
    # Stray intake at the scenario tier — branch must NOT clone it.
    (src_path / "intake").mkdir()
    (src_path / "intake" / "should_not_exist_in_branch.txt").write_text("x")
    (src_path / "overrides.jsonl").write_text("\n{}\n")

    dst_path = branch_scenario(EVENT_KEY, "default", "experiment", base_dir=tmp_path)
    assert dst_path.exists()
    assert (dst_path / "overrides.jsonl").exists()
    assert not (dst_path / "intake").exists()


def test_branch_scenario_existing_dst_raises(tmp_path: Path):
    ensure_scenario(EVENT_KEY, "default", base_dir=tmp_path)
    ensure_scenario(EVENT_KEY, "experiment", base_dir=tmp_path)
    with pytest.raises(ScenarioExistsError):
        branch_scenario(EVENT_KEY, "default", "experiment", base_dir=tmp_path)


def test_branch_scenario_same_name_raises(tmp_path: Path):
    ensure_scenario(EVENT_KEY, "default", base_dir=tmp_path)
    with pytest.raises(ValueError, match="must differ"):
        branch_scenario(EVENT_KEY, "default", "default", base_dir=tmp_path)


def test_list_scenarios_returns_sorted_names(tmp_path: Path):
    ensure_scenario(EVENT_KEY, "zeta", base_dir=tmp_path)
    ensure_scenario(EVENT_KEY, "alpha", base_dir=tmp_path)
    assert list_scenarios(EVENT_KEY, base_dir=tmp_path) == ["alpha", "zeta"]


def test_list_scenarios_empty_when_no_dir(tmp_path: Path):
    assert list_scenarios(EVENT_KEY, base_dir=tmp_path) == []


def test_acquire_lock_holds_within_context(tmp_path: Path):
    ensure_scenario(EVENT_KEY, "default", base_dir=tmp_path)
    with acquire_scenario_lock(EVENT_KEY, "default", base_dir=tmp_path):
        # Lockfile exists for the duration of the context.
        lock_path = scenarios_dir(EVENT_KEY, base_dir=tmp_path) / "default" / ".run.lock"
        assert lock_path.exists()


def test_double_acquire_raises_immediately_with_zero_timeout(tmp_path: Path):
    """F16: ``timeout=0.0`` is once-and-raise."""
    ensure_scenario(EVENT_KEY, "default", base_dir=tmp_path)
    with acquire_scenario_lock(EVENT_KEY, "default", base_dir=tmp_path):
        with pytest.raises(ScenarioLockError):
            with acquire_scenario_lock(EVENT_KEY, "default", base_dir=tmp_path, timeout=0.0):
                pytest.fail("inner acquire should have raised")


def test_release_then_reacquire(tmp_path: Path):
    ensure_scenario(EVENT_KEY, "default", base_dir=tmp_path)
    with acquire_scenario_lock(EVENT_KEY, "default", base_dir=tmp_path):
        pass
    # After context exit, a fresh acquire enters cleanly.
    with acquire_scenario_lock(EVENT_KEY, "default", base_dir=tmp_path):
        pass


def test_lockfile_persists_after_release(tmp_path: Path):
    """F19 / spec §9 line 320: lockfile is presence/lock primitive — not deleted."""
    ensure_scenario(EVENT_KEY, "default", base_dir=tmp_path)
    with acquire_scenario_lock(EVENT_KEY, "default", base_dir=tmp_path):
        pass
    lock_path = scenarios_dir(EVENT_KEY, base_dir=tmp_path) / "default" / ".run.lock"
    assert lock_path.exists()
