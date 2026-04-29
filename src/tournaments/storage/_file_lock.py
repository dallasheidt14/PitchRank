"""Platform-abstracted advisory file-lock contextmanager.

Factored out of ``scenario.py`` so multiple sibling lock-helpers can share
the same platform pair and retry/sleep loop. Today: the per-scenario lock
at ``scenarios/<name>/.run.lock`` (``acquire_scenario_lock``) and the
per-run lock at ``runs/<run_id>/.report.lock`` (``acquire_run_lock``).

The lockfile is purely a presence/lock primitive — see the no-IO contract
note in ``scenario.py`` module docstring. Callers MUST translate
``FileLockError`` to a typed subclass at their boundary
(``ScenarioLockError`` / ``RunLockError``) so downstream catches stay
specific.

Resolved once at module load: the platform branch and the inner module
imports don't need to re-run on every acquire call.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

__all__ = [
    "FileLockError",
    "_acquire_file_lock",
]


class FileLockError(RuntimeError):
    """Raised when an advisory file lock cannot be acquired within ``timeout``.

    Sibling helpers (``acquire_scenario_lock``, ``acquire_run_lock``)
    translate this to their typed subclass at the boundary so callers
    continue to catch the specific exception they expect.
    """


def _build_platform_lock_pair() -> tuple[Callable[[int], None], Callable[[int], None]]:
    """Build ``(lock_fn, unlock_fn)`` for the current platform."""
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
def _acquire_file_lock(lock_path: Path, *, timeout: float) -> Iterator[None]:
    """Acquire the advisory lock at ``lock_path``.

    Timeout semantics:

    - ``timeout == 0.0`` — attempt acquire exactly once. Raise
      ``FileLockError`` immediately on contention.
    - ``timeout > 0`` — retry with brief sleeps until elapsed time exceeds
      ``timeout``, then raise.

    The parent directory of ``lock_path`` must already exist; opening the
    fd in a missing directory raises ``FileNotFoundError`` — that's a
    caller-ordering bug, not a lock bug.

    The lock is released and the fd closed on exit. The lockfile itself is
    NOT deleted — it persists for the next acquirer.
    """
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
                    raise FileLockError(f"file lock at {lock_path} is held by another process")
                time.sleep(0.05)
        yield
    finally:
        try:
            if locked:
                _UNLOCK_FN(fd)
        finally:
            os.close(fd)
