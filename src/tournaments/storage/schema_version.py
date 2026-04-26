"""Schema-version constant + check + stamp helpers.

Spec §8 line 311 mandates a per-file ``schema_version: 1`` stamp so future
v2 schemas can refuse to load against v1 code without silent data loss.

**Contract:** lenient on read, strict on write.

- Readers tolerate a missing ``schema_version`` field and treat it as v1
  (per spec §10 fold-in 16's "stamp only, no migrations" v1 contract).
  This keeps Shell 01 raw-scrape JSONL records loadable without a
  retroactive stamp pass.
- Writers MUST route their payload through ``stamp_schema_version`` before
  handing it to ``_io.write_json`` / ``_io.write_csv`` / ``_io.append_jsonl``.
  v2's stricter check will rely on this discipline — a missing stamp on a
  v1-era file is the only way the v2 reader can tell it's looking at v1
  data and not corrupted v2.

Forward migrations are deferred until v2 lands. Today, the only failure
mode is loading a payload whose declared ``schema_version`` exceeds
``SCHEMA_VERSION``, which raises ``SchemaVersionError``.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "SCHEMA_VERSION",
    "SchemaVersionError",
    "assert_supported_version",
    "stamp_schema_version",
]


SCHEMA_VERSION: int = 1
"""Current storage-layer schema version. Bump when a payload's required
fields, types, or wire format change in a way the prior version can't read.
"""


class SchemaVersionError(RuntimeError):
    """Raised when a payload's ``schema_version`` exceeds ``SCHEMA_VERSION``.

    The reader will not silently downgrade — callers must either upgrade the
    code or roll back the file. Mirrors the typed-error style of
    ``src.scrapers.intake_journal.JournalCorruptionError``.
    """


def assert_supported_version(payload: dict[str, Any], *, source: str) -> None:
    """Raise ``SchemaVersionError`` if ``payload`` claims a newer schema.

    A missing ``schema_version`` field is treated as v1 (lenient on read).
    A non-coercible value (e.g. ``None``, a non-numeric string) raises
    ``SchemaVersionError`` rather than a raw ``TypeError`` / ``ValueError``
    so callers (such as ``rekey_unknown_directories``) can rely on the
    typed exception in their except clauses. ``source`` is included in the
    error message so a single trace points the operator at the exact file.
    """
    raw = payload.get("schema_version", 1)
    try:
        got = int(raw)
    except (TypeError, ValueError) as exc:
        raise SchemaVersionError(f"{source} has malformed schema_version={raw!r}: {exc}") from exc
    if got > SCHEMA_VERSION:
        raise SchemaVersionError(f"{source} has schema_version={got}; this build supports {SCHEMA_VERSION}")


def stamp_schema_version(payload: dict[str, Any], *, version: int = SCHEMA_VERSION) -> dict[str, Any]:
    """Return a new dict with ``schema_version`` set.

    Strict on write: every storage writer MUST route its payload through
    this helper. Centralizing the stamp prevents inconsistent stamping
    across modules — a v2 schema check needs every v1-era file to have been
    explicitly stamped.
    """
    return {**payload, "schema_version": version}
