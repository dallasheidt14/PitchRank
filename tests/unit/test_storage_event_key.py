"""Unit tests for ``src.tournaments.storage.event_key``.

Covers the optional-season-year contract, the parse round-trip including
the legacy ``unknown`` segment, and the four-bucket aggregation behavior
of ``rekey_unknown_directories`` (F5 / F18).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tournaments.storage.event_key import (
    derive_season_year,
    event_key,
    parse_event_key,
    rekey_unknown_directories,
    run_dir,
    scenario_dir,
)

# -------- event_key --------------------------------------------------


def test_event_key_with_year():
    assert event_key("gotsport", "45224", 2026) == "gotsport__45224__2026"


def test_event_key_legacy_unknown_form_when_year_is_none():
    assert event_key("gotsport", "45224") == "gotsport__45224__unknown"
    assert event_key("gotsport", "45224", None) == "gotsport__45224__unknown"


def test_event_key_rejects_empty_provider_code():
    with pytest.raises(ValueError, match="provider_code"):
        event_key("", "1", 2026)


def test_event_key_rejects_double_underscore_in_provider_code():
    with pytest.raises(ValueError, match="provider_code"):
        event_key("got__sport", "1", 2026)


def test_event_key_rejects_double_underscore_in_event_id():
    with pytest.raises(ValueError, match="provider_event_id"):
        event_key("gotsport", "12__34", 2026)


def test_event_key_rejects_year_below_2000():
    with pytest.raises(ValueError, match=">= 2000"):
        event_key("gotsport", "1", 1999)


def test_event_key_rejects_non_int_year():
    with pytest.raises(ValueError, match="must be int"):
        event_key("gotsport", "1", "2026")  # type: ignore[arg-type]


def test_event_key_rejects_bool_year():
    """``bool`` is a subclass of ``int`` — guard against accidental True/False."""
    with pytest.raises(ValueError, match="must be int"):
        event_key("gotsport", "1", True)  # type: ignore[arg-type]


# -------- parse_event_key --------------------------------------------


def test_parse_event_key_with_year():
    assert parse_event_key("gotsport__45224__2026") == ("gotsport", "45224", 2026)


def test_parse_event_key_legacy_unknown():
    assert parse_event_key("gotsport__45224__unknown") == ("gotsport", "45224", None)


def test_parse_event_key_rejects_non_int_season():
    with pytest.raises(ValueError, match="season segment"):
        parse_event_key("gotsport__45224__abcd")


def test_parse_event_key_rejects_wrong_segment_count():
    with pytest.raises(ValueError, match="three-segment|provider__eventid__season"):
        parse_event_key("gotsport__45224")


def test_parse_event_key_rejects_empty_segments():
    with pytest.raises(ValueError):
        parse_event_key("__45224__2026")


def test_parse_event_key_rejects_year_below_2000():
    """The floor on the parse path mirrors ``event_key()`` — symmetric contract."""
    with pytest.raises(ValueError, match=">= 2000"):
        parse_event_key("gotsport__45224__1999")


# -------- derive_season_year ----------------------------------------


def test_derive_season_year_iso_date():
    assert derive_season_year("2026-04-15") == 2026


def test_derive_season_year_none_input():
    assert derive_season_year(None) is None


def test_derive_season_year_unparseable_string():
    assert derive_season_year("April 15, 2026") is None
    assert derive_season_year("") is None
    assert derive_season_year("xxxx-04-15") is None


def test_derive_season_year_strict_iso_only():
    """Year-only and invalid month/day fail the strict ``YYYY-MM-DD`` parse."""
    assert derive_season_year("2026") is None
    assert derive_season_year("2026-99-99") is None
    assert derive_season_year("2026-13-01") is None
    assert derive_season_year("2026-02-30") is None


def test_derive_season_year_below_min():
    assert derive_season_year("1999-04-15") is None


# -------- rekey_unknown_directories ---------------------------------


def _seed_event_dir(base: Path, old_key: str, *, metadata: dict | None) -> Path:
    """Create ``<base>/<old_key>/intake/`` with optional ``event_metadata.json``."""
    event_dir = base / old_key
    intake = event_dir / "intake"
    intake.mkdir(parents=True, exist_ok=True)
    if metadata is not None:
        (intake / "event_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return event_dir


def test_rekey_four_bucket_aggregation(tmp_path: Path):
    """All four ``RekeyMigrationResult`` buckets exercised in one call (F18)."""
    # (a) Success
    _seed_event_dir(
        tmp_path,
        "gotsport__1__unknown",
        metadata={
            "schema_version": 1,
            "provider_code": "gotsport",
            "provider_event_id": "1",
            "event_start_date": "2026-04-15",
            "event_name": "Cup A",
            "event_slug": "events/1",
            "scrape_ts": "2026-04-25T12:00:00Z",
        },
    )
    # (b) No intake/event_metadata.json
    (tmp_path / "gotsport__2__unknown" / "intake").mkdir(parents=True)
    # (c) Metadata exists but event_start_date None → no derivable year
    _seed_event_dir(
        tmp_path,
        "gotsport__3__unknown",
        metadata={
            "schema_version": 1,
            "provider_code": "gotsport",
            "provider_event_id": "3",
            "event_start_date": None,
            "event_name": "Cup C",
            "event_slug": "events/3",
            "scrape_ts": "2026-04-25T12:00:00Z",
        },
    )
    # (d) Destination already exists
    _seed_event_dir(
        tmp_path,
        "gotsport__4__unknown",
        metadata={
            "schema_version": 1,
            "provider_code": "gotsport",
            "provider_event_id": "4",
            "event_start_date": "2026-04-15",
            "event_name": "Cup D",
            "event_slug": "events/4",
            "scrape_ts": "2026-04-25T12:00:00Z",
        },
    )
    (tmp_path / "gotsport__4__2026").mkdir()  # destination collision

    result = rekey_unknown_directories(tmp_path)

    assert result.completed == (("gotsport__1__unknown", "gotsport__1__2026"),)
    assert result.unmigrated == ("gotsport__2__unknown",)
    failed_keys = {key for key, _ in result.failed}
    assert failed_keys == {"gotsport__3__unknown", "gotsport__4__unknown"}
    failed_reasons = {key: reason for key, reason in result.failed}
    assert failed_reasons["gotsport__3__unknown"] == "no derivable season_year"
    assert failed_reasons["gotsport__4__unknown"] == "destination already exists"

    # Filesystem effects: only (a) renamed; (b)/(c)/(d) remain in place.
    assert not (tmp_path / "gotsport__1__unknown").exists()
    assert (tmp_path / "gotsport__1__2026").exists()
    assert (tmp_path / "gotsport__2__unknown").exists()
    assert (tmp_path / "gotsport__3__unknown").exists()
    assert (tmp_path / "gotsport__4__unknown").exists()


def test_rekey_idempotent(tmp_path: Path):
    """A second call finds nothing to migrate."""
    _seed_event_dir(
        tmp_path,
        "gotsport__1__unknown",
        metadata={
            "schema_version": 1,
            "provider_code": "gotsport",
            "provider_event_id": "1",
            "event_start_date": "2026-04-15",
            "event_name": "Cup A",
            "event_slug": "events/1",
            "scrape_ts": "2026-04-25T12:00:00Z",
        },
    )
    first = rekey_unknown_directories(tmp_path)
    assert len(first.completed) == 1

    second = rekey_unknown_directories(tmp_path)
    assert second.completed == ()
    assert second.failed == ()
    assert second.unmigrated == ()


def test_rekey_skips_non_unknown_directories(tmp_path: Path):
    (tmp_path / "gotsport__1__2026").mkdir()
    (tmp_path / "some_other_dir").mkdir()

    result = rekey_unknown_directories(tmp_path)
    assert result.completed == ()
    assert result.failed == ()
    assert result.unmigrated == ()


def test_rekey_returns_empty_when_base_missing(tmp_path: Path):
    result = rekey_unknown_directories(tmp_path / "does_not_exist")
    assert result.completed == ()
    assert result.failed == ()
    assert result.unmigrated == ()


def test_rekey_handles_malformed_metadata_json(tmp_path: Path):
    """Broad-except routes malformed metadata to ``failed`` without raising mid-loop."""
    intake = tmp_path / "gotsport__99__unknown" / "intake"
    intake.mkdir(parents=True)
    (intake / "event_metadata.json").write_text("{not valid json", encoding="utf-8")

    result = rekey_unknown_directories(tmp_path)
    failed_keys = {key for key, _ in result.failed}
    assert "gotsport__99__unknown" in failed_keys
    assert (tmp_path / "gotsport__99__unknown").exists()  # still in place


def test_rekey_handles_newer_schema_metadata(tmp_path: Path):
    """A v2 metadata payload routes to ``failed`` instead of driving a rekey."""
    intake = tmp_path / "gotsport__99__unknown" / "intake"
    intake.mkdir(parents=True)
    (intake / "event_metadata.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "provider_code": "gotsport",
                "provider_event_id": "99",
                "event_start_date": "2026-04-15",
                "event_name": "Future",
                "event_slug": "events/99",
                "scrape_ts": "2026-04-25T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    result = rekey_unknown_directories(tmp_path)
    failed_keys = {key for key, _ in result.failed}
    assert "gotsport__99__unknown" in failed_keys
    # No rekey happened — the __unknown dir is still in place.
    assert (tmp_path / "gotsport__99__unknown").exists()
    assert not (tmp_path / "gotsport__99__2026").exists()


# -------- path-segment validation -----------------------------------


def test_event_key_rejects_path_traversal():
    with pytest.raises(ValueError, match="provider_code"):
        event_key("..", "1", 2026)
    with pytest.raises(ValueError, match="provider_event_id"):
        event_key("gotsport", "..", 2026)
    with pytest.raises(ValueError, match="provider_code"):
        event_key("a/b", "1", 2026)
    with pytest.raises(ValueError, match="provider_code"):
        event_key("a\\b", "1", 2026)


def test_scenario_dir_rejects_path_traversal():
    with pytest.raises(ValueError, match="scenario name"):
        scenario_dir("gotsport__45224__2026", "..")
    with pytest.raises(ValueError, match="scenario name"):
        scenario_dir("gotsport__45224__2026", "a/b")
    with pytest.raises(ValueError, match="scenario name"):
        scenario_dir("gotsport__45224__2026", "a\\b")


def test_run_dir_rejects_path_traversal():
    with pytest.raises(ValueError, match="run_id"):
        run_dir("gotsport__45224__2026", "default", "..")
    with pytest.raises(ValueError, match="run_id"):
        run_dir("gotsport__45224__2026", "default", "a/b")
    with pytest.raises(ValueError, match="run_id"):
        run_dir("gotsport__45224__2026", "default", "a\\b")


def test_event_dir_rejects_pre_formed_traversal_key():
    """Pre-formed event_key strings are gated by ``_validate_segment`` too."""
    from src.tournaments.storage.event_key import event_dir

    with pytest.raises(ValueError, match="event_key"):
        event_dir("..")
    with pytest.raises(ValueError, match="event_key"):
        event_dir("a/b")
