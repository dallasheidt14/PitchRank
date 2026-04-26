"""Direct tests for ``src.tournaments.storage._io`` foundation primitives.

The helpers are also exercised transitively through every reader/writer,
but boundary cases (empty file, missing file, missing trailing newline,
atomic-rename .tmp cleanup) deserve direct coverage so a regression in
``_io`` doesn't show up first as a confusing failure four modules away.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tournaments.storage._io import (
    append_jsonl,
    read_csv,
    read_json,
    read_jsonl,
    read_versioned_json,
    utc_now_iso,
    write_csv,
    write_json,
)
from src.tournaments.storage.schema_version import SchemaVersionError

# -------- write_json + read_json --------------------------------------


def test_write_json_creates_parent_dirs(tmp_path: Path):
    target = tmp_path / "deep" / "nested" / "out.json"
    write_json(target, {"x": 1})
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"x": 1}


def test_write_json_atomic_no_tmp_left_behind(tmp_path: Path):
    target = tmp_path / "atomic.json"
    write_json(target, {"x": 1})
    assert target.exists()
    assert not target.with_name(target.name + ".tmp").exists()


def test_write_json_overwrites_existing(tmp_path: Path):
    target = tmp_path / "atomic.json"
    write_json(target, {"x": 1})
    write_json(target, {"x": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"x": 2}


def test_read_json_does_not_validate_schema(tmp_path: Path):
    """Read JSON does NOT enforce ``schema_version`` — safe for unstamped markers."""
    target = tmp_path / "marker.json"
    target.write_text(json.dumps({"schema_version": 999, "x": 1}), encoding="utf-8")
    assert read_json(target) == {"schema_version": 999, "x": 1}


def test_read_versioned_json_raises_on_newer(tmp_path: Path):
    target = tmp_path / "stamped.json"
    target.write_text(json.dumps({"schema_version": 2, "x": 1}), encoding="utf-8")
    with pytest.raises(SchemaVersionError):
        read_versioned_json(target)


def test_read_versioned_json_accepts_v1(tmp_path: Path):
    target = tmp_path / "stamped.json"
    target.write_text(json.dumps({"schema_version": 1, "x": 1}), encoding="utf-8")
    assert read_versioned_json(target) == {"schema_version": 1, "x": 1}


# -------- write_csv + read_csv ---------------------------------------


def test_write_csv_round_trip_with_explicit_fieldnames(tmp_path: Path):
    target = tmp_path / "out.csv"
    write_csv(target, [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}], fieldnames=("a", "b"))
    assert read_csv(target) == [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}]


def test_write_csv_defaults_missing_keys_to_empty_string(tmp_path: Path):
    target = tmp_path / "out.csv"
    write_csv(target, [{"a": "1"}], fieldnames=("a", "b"))
    rows = read_csv(target)
    assert rows == [{"a": "1", "b": ""}]


def test_write_csv_drops_extras(tmp_path: Path):
    """``extrasaction="ignore"`` — extra keys are silently dropped, not raised."""
    target = tmp_path / "out.csv"
    write_csv(target, [{"a": "1", "extra": "ignored"}], fieldnames=("a",))
    assert read_csv(target) == [{"a": "1"}]


def test_write_csv_empty_rows_writes_header_only(tmp_path: Path):
    target = tmp_path / "empty.csv"
    write_csv(target, [], fieldnames=("a", "b"))
    assert target.read_text(encoding="utf-8").splitlines()[0] == "a,b"
    assert read_csv(target) == []


def test_write_csv_atomic_no_tmp_left_behind(tmp_path: Path):
    target = tmp_path / "atomic.csv"
    write_csv(target, [{"a": "1"}], fieldnames=("a",))
    assert not target.with_name(target.name + ".tmp").exists()


# -------- append_jsonl + read_jsonl ----------------------------------


def test_append_jsonl_newline_first_protocol(tmp_path: Path):
    """File must start with ``\\n`` so a partial-tail crash is detectable."""
    target = tmp_path / "log.jsonl"
    append_jsonl(target, {"x": 1})
    raw = target.read_bytes()
    assert raw.startswith(b"\n")
    assert json.loads(raw.split(b"\n")[1]) == {"x": 1}


def test_append_jsonl_multiple_records(tmp_path: Path):
    target = tmp_path / "log.jsonl"
    for i in range(3):
        append_jsonl(target, {"i": i})
    records = list(read_jsonl(target))
    assert records == [{"i": 0}, {"i": 1}, {"i": 2}]


def test_read_jsonl_missing_file_yields_empty(tmp_path: Path):
    target = tmp_path / "missing.jsonl"
    assert list(read_jsonl(target)) == []


def test_read_jsonl_empty_file_yields_empty(tmp_path: Path):
    """File exists but is zero bytes — the missing-trailing-newline edge."""
    target = tmp_path / "empty.jsonl"
    target.write_bytes(b"")
    assert list(read_jsonl(target)) == []


def test_read_jsonl_no_trailing_newline(tmp_path: Path):
    """Newline-first protocol means the last record doesn't need a trailing \\n."""
    target = tmp_path / "log.jsonl"
    target.write_bytes(b'\n{"x": 1}\n{"x": 2}')  # second record, no trailing newline
    records = list(read_jsonl(target))
    assert records == [{"x": 1}, {"x": 2}]


def test_append_jsonl_preserves_prior_records_after_partial_tail_simulation(
    tmp_path: Path,
):
    """Simulate a partial-tail crash — prior records survive."""
    target = tmp_path / "log.jsonl"
    append_jsonl(target, {"x": 1})
    append_jsonl(target, {"x": 2})
    # Simulate a crash mid-append by truncating to mid-second-record.
    raw = target.read_bytes()
    # Lop off the final 3 bytes — partial JSON.
    target.write_bytes(raw[:-3])
    # The first record is still intact.
    parts = target.read_bytes().split(b"\n")
    assert json.loads(parts[1]) == {"x": 1}


# -------- utc_now_iso ------------------------------------------------


def test_utc_now_iso_is_timezone_aware():
    stamp = utc_now_iso()
    # Either ``+00:00`` or trailing ``Z`` is acceptable; ``isoformat`` emits ``+00:00``.
    assert "+00:00" in stamp or stamp.endswith("Z")


def test_utc_now_iso_round_trips_via_fromisoformat():
    from datetime import datetime

    parsed = datetime.fromisoformat(utc_now_iso())
    assert parsed.tzinfo is not None
