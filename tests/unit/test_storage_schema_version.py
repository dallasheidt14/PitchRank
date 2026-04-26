"""Unit tests for ``src.tournaments.storage.schema_version``.

Covers the v1 contract: lenient on read (missing field treated as v1),
strict on write (every payload routed through ``stamp_schema_version``).
"""

from __future__ import annotations

import pytest

from src.tournaments.storage.schema_version import (
    SCHEMA_VERSION,
    SchemaVersionError,
    assert_supported_version,
    stamp_schema_version,
)


def test_schema_version_constant_is_one():
    assert SCHEMA_VERSION == 1


def test_assert_supported_version_accepts_v1():
    assert_supported_version({"schema_version": 1, "x": 1}, source="test")


def test_assert_supported_version_lenient_on_missing_field():
    """Missing ``schema_version`` is treated as v1 — Shell 01 records survive."""
    assert_supported_version({"x": 1}, source="test")


def test_assert_supported_version_raises_on_newer():
    with pytest.raises(SchemaVersionError, match="schema_version=2"):
        assert_supported_version({"schema_version": 2}, source="event_metadata.json")


def test_assert_supported_version_coerces_string_int():
    """Hand-edited JSON that stamps ``"1"`` instead of ``1`` still passes."""
    assert_supported_version({"schema_version": "1"}, source="test")


def test_assert_supported_version_typed_error_on_garbage():
    """Non-int / non-numeric values raise ``SchemaVersionError`` (not raw ``TypeError``)
    so callers like ``rekey_unknown_directories`` can catch the typed exception."""
    with pytest.raises(SchemaVersionError, match="malformed"):
        assert_supported_version({"schema_version": None}, source="test")
    with pytest.raises(SchemaVersionError, match="malformed"):
        assert_supported_version({"schema_version": "abc"}, source="test")


def test_stamp_schema_version_adds_field_when_absent():
    stamped = stamp_schema_version({"x": 1})
    assert stamped["schema_version"] == 1
    assert stamped["x"] == 1


def test_stamp_schema_version_overrides_existing():
    stamped = stamp_schema_version({"schema_version": 0, "x": 1})
    assert stamped["schema_version"] == 1


def test_stamp_schema_version_does_not_mutate_input():
    payload = {"x": 1}
    stamped = stamp_schema_version(payload)
    assert "schema_version" not in payload
    assert stamped is not payload


def test_stamp_schema_version_custom_version():
    stamped = stamp_schema_version({"x": 1}, version=2)
    assert stamped["schema_version"] == 2
