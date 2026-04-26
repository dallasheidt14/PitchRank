"""Atomic file I/O helpers used by every storage module.

Conventions captured here so callers don't reinvent them:

- ``write_json`` / ``write_csv`` write to ``<path>.tmp`` then ``os.replace``
  for crash-safe file replacement (mirrors ``intake_journal.py:284``).
- ``append_jsonl`` follows the newline-first protocol from
  ``intake_journal.py:175-179`` (``"\\n" + json.dumps(record)``, ``flush`` +
  ``os.fsync`` per record).
- ``read_versioned_json`` enforces the shell's "lenient on read, strict on
  write" schema-version contract — package-private because external callers
  who need versioned reads should compose ``assert_supported_version(read_json(path), source=...)``
  directly using the public exports.
- Path arguments accept ``Path | str``; cast to ``Path`` at the top.
"""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.tournaments.storage.schema_version import assert_supported_version


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string.

    Centralized so every storage writer that stamps a ``promoted_at`` /
    ``failed_at`` / ``cancelled_at`` / ``computed_at`` field uses the same
    timezone-aware format.
    """
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path | str, payload: dict[str, Any], *, indent: int = 2) -> None:
    """Atomically write ``payload`` as JSON to ``path``.

    Writes to ``<path>.tmp`` then ``os.replace`` for crash safety. The parent
    directory is created with ``parents=True, exist_ok=True``. The temp file
    is fsynced before the rename so a crash between write and rename leaves
    the prior file intact (or absent).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    encoded = json.dumps(payload, ensure_ascii=False, indent=indent).encode("utf-8")
    with open(tmp_path, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def read_json(path: Path | str) -> dict[str, Any]:
    """Read a JSON file. Does NOT enforce ``schema_version``.

    Safe for unstamped JSON (``done.json`` / ``error.json`` /
    ``cancelled.json`` run markers). For schema-stamped files, use
    ``read_versioned_json`` (package-private) or compose
    ``assert_supported_version(read_json(path), source=str(path))`` from the
    public exports.
    """
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8"))


def read_versioned_json(path: Path | str) -> dict[str, Any]:
    """Read a JSON file and enforce ``schema_version``.

    Package-private; not in ``storage.__all__``. External callers compose
    ``assert_supported_version`` + ``read_json`` themselves.
    """
    path = Path(path)
    payload = read_json(path)
    assert_supported_version(payload, source=str(path))
    return payload


def write_csv(
    path: Path | str,
    rows: list[dict[str, Any]],
    *,
    fieldnames: tuple[str, ...],
) -> None:
    """Atomically write ``rows`` to ``path`` with explicit column order.

    ``fieldnames`` is required — callers pass declared module constants so
    column order is stable across runs. Missing keys in a row write as the
    empty string; extra keys are silently dropped.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    field_list = list(fieldnames)
    with open(tmp_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=field_list, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in field_list})
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def read_csv(path: Path | str) -> list[dict[str, Any]]:
    """Read a CSV file via ``csv.DictReader``."""
    path = Path(path)
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def append_jsonl(path: Path | str, record: dict[str, Any]) -> None:
    """Append one record to a JSONL file using the newline-first protocol.

    Mirrors ``src.scrapers.intake_journal.IntakeJournal.append`` at
    ``intake_journal.py:175-179``: ``"\\n" + json.dumps(record)`` so a
    partial-tail crash leaves prior records intact, then ``flush`` +
    ``os.fsync`` for durability.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = ("\n" + json.dumps(record, ensure_ascii=False)).encode("utf-8")
    with open(path, "ab") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path | str) -> Iterator[dict[str, Any]]:
    """Stream-read a JSONL file, yielding one dict per non-empty line.

    Returns an empty iterator if the file does not exist.
    """
    path = Path(path)
    if not path.exists():
        return
    raw = path.read_bytes()
    for line in raw.split(b"\n"):
        if not line.strip():
            continue
        yield json.loads(line)
