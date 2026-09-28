"""Subprocess-friendly temporary workspaces for tournament tools."""

from __future__ import annotations

import os
import secrets
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_WINDOWS = os.name == "nt"


def _create_workspace(prefix: str) -> Path:
    """Create a private-enough workspace without Python 3.13's Windows ACL."""
    if not prefix or Path(prefix).name != prefix:
        raise ValueError("Temporary workspace prefix must be a nonempty file name")

    parent = Path(tempfile.gettempdir())
    # Python 3.13 gives mkdir(mode=0o700) a Windows-only restrictive ACL.
    # Sandboxed child processes can create that directory but then lose access
    # to its contents. Inherit the user's Temp ACL on Windows; retain private
    # owner-only permissions on POSIX.
    mode = 0o777 if _WINDOWS else 0o700
    for _ in range(20):
        workspace = parent / f"{prefix}{secrets.token_hex(8)}"
        try:
            workspace.mkdir(mode=mode)
        except FileExistsError:
            continue
        return workspace
    raise FileExistsError(f"Could not allocate temporary workspace with prefix {prefix!r}")


@contextmanager
def temporary_workspace(prefix: str) -> Iterator[Path]:
    """Yield a unique workspace and never let cleanup mask a completed job."""
    workspace = _create_workspace(prefix)
    try:
        yield workspace
    finally:
        # Antivirus and browser shutdown can hold Windows handles briefly. The
        # generated artifact is already in memory, so cleanup must not turn a
        # successful prediction or PDF render into an operator-facing failure.
        shutil.rmtree(workspace, ignore_errors=True)
