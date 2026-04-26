"""Scenario directory scaffolding + per-scenario advisory lock.

Spec §8 enforces a two-tier layout: ``intake/`` is shared across scenarios
and ``scenarios/<name>/`` overlays it. Branching creates a new overlay
without copying ``intake/`` (the scrape genuinely is shared).

Spec §9 line 320 mandates a per-scenario file lock at
``scenarios/<name>/.run.lock`` so two run subprocesses can't race the same
scenario. ``acquire_scenario_lock`` implements it as an OS advisory lock —
``fcntl.flock`` on POSIX, ``msvcrt.locking`` on Windows.

**No-IO contract on the lockfile:** the helper opens the fd and immediately
acquires the lock without any intervening reads or writes. Callers MUST NOT
use the lockfile body for state (PID, holder name, etc.) — Windows
``msvcrt.locking`` locks a 1-byte range from the current file pointer; any
intervening I/O could shift the locked range. The lockfile is purely a
presence/lock primitive.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from src.tournaments.storage.event_key import scenario_dir, scenarios_dir

__all__ = [
    "ScenarioExistsError",
    "ScenarioLockError",
    "acquire_scenario_lock",
    "branch_scenario",
    "ensure_scenario",
    "list_scenarios",
]


class ScenarioExistsError(RuntimeError):
    """Raised when ``branch_scenario`` finds the destination already exists."""


class ScenarioLockError(RuntimeError):
    """Raised when ``acquire_scenario_lock`` cannot acquire within ``timeout``."""


def ensure_scenario(event_key: str, name: str, *, base_dir: Path | str = "reports") -> Path:
    """Create ``scenarios/<name>/`` (idempotent).

    Does NOT copy ``intake/`` — intake is shared at the event tier and
    scenarios overlay (spec §8).
    """
    path = scenario_dir(event_key, name, base_dir=base_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def branch_scenario(
    event_key: str,
    src_name: str,
    dst_name: str,
    *,
    base_dir: Path | str = "reports",
) -> Path:
    """Copy ``scenarios/<src>/`` to ``scenarios/<dst>/``.

    Excludes any nested ``intake/`` so a stray intake dir at the scenario
    tier doesn't get cloned. Raises ``ScenarioExistsError`` if the
    destination already exists; raises ``ValueError`` if src and dst are
    the same name.
    """
    if src_name == dst_name:
        raise ValueError(f"branch source and destination must differ: {src_name!r}")
    src_path = scenario_dir(event_key, src_name, base_dir=base_dir)
    dst_path = scenario_dir(event_key, dst_name, base_dir=base_dir)
    if dst_path.exists():
        raise ScenarioExistsError(f"scenario {dst_name!r} already exists at {dst_path}")
    shutil.copytree(src_path, dst_path, ignore=shutil.ignore_patterns("intake"))
    return dst_path


def list_scenarios(event_key: str, *, base_dir: Path | str = "reports") -> list[str]:
    """Return the directory names under ``scenarios/`` (sorted)."""
    root = scenarios_dir(event_key, base_dir=base_dir)
    if not root.exists():
        return []
    return sorted(entry.name for entry in root.iterdir() if entry.is_dir())


def _build_platform_lock_pair() -> tuple[Callable[[int], None], Callable[[int], None]]:
    """Build ``(lock_fn, unlock_fn)`` for the current platform.

    Resolved once at module load — the platform branch and module imports
    don't need to re-run on every ``acquire_scenario_lock`` call.
    """
    if sys.platform == "win32":
        import msvcrt

        def lock_fn(fd: int) -> None:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

        def unlock_fn(fd: int) -> None:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        def lock_fn(fd: int) -> None:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def unlock_fn(fd: int) -> None:
            fcntl.flock(fd, fcntl.LOCK_UN)

    return lock_fn, unlock_fn


_LOCK_FN, _UNLOCK_FN = _build_platform_lock_pair()


@contextlib.contextmanager
def acquire_scenario_lock(
    event_key: str,
    scenario: str,
    *,
    base_dir: Path | str = "reports",
    timeout: float = 0.0,
) -> Iterator[None]:
    """Acquire the per-scenario advisory lock at ``scenarios/<name>/.run.lock``.

    Timeout semantics:

    - ``timeout == 0.0`` (default) — attempt acquire exactly once. Raise
      ``ScenarioLockError`` immediately on contention.
    - ``timeout > 0`` — retry with brief sleeps until elapsed time exceeds
      ``timeout``, then raise.

    The scenario directory must already exist (``ensure_scenario`` is the
    sanctioned creator). Opening the lockfile in a missing directory raises
    ``FileNotFoundError`` — that's a caller-ordering bug, not a lock bug.

    The lock is released and the fd closed on exit. The lockfile itself is
    NOT deleted — it persists for the next acquirer.
    """
    lock_path = scenario_dir(event_key, scenario, base_dir=base_dir) / ".run.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    locked = False
    try:
        deadline = time.monotonic() + timeout if timeout > 0 else None
        while True:
            try:
                _LOCK_FN(fd)
                locked = True
                break
            except (BlockingIOError, OSError):
                if deadline is None or time.monotonic() >= deadline:
                    raise ScenarioLockError(f"scenario {scenario!r} is locked by another process")
                time.sleep(0.05)
        yield
    finally:
        if locked:
            try:
                _UNLOCK_FN(fd)
            finally:
                os.close(fd)
        else:
            os.close(fd)
