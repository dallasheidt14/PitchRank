"""Unit tests for ``src.tournaments.storage.registry``.

Asserts FIELDNAMES match the authoritative CLI column set at
``scripts/backtest_tournament_event.py:145-153, 167-217``, that the CSV
round-trips losslessly, and that the sibling ``event_team_registry.schema.json``
is written + validated on read.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.tournaments.storage.event_key import scenario_dir
from src.tournaments.storage.registry import (
    FIELDNAMES,
    RegistryPersistResult,
    TeamRegistryEntry,
    build_registry_entries,
    build_registry_entry,
    compute_dropped_pids,
    persist_registry_for_scenario,
    read_registry,
    write_registry,
)
from src.tournaments.storage.scenario import ensure_scenario

EVENT_KEY = "gotsport__45224__2026"
SCENARIO = "default"


def test_fieldnames_cover_cli_input_set():
    """F1: column set is locked to the CLI consumer."""
    required_input = {
        "event_team_name",
        "event_age_group",
        "display_age_group",
        "event_gender",
        "display_gender",
        "event_club_name",
        "search_age_group",
        "resolved_gotsport_provider_team_id",
        "canonical_resolution_status",
        "in_scope_u10_u19",
        "resolved_team_id_master",
        "resolved_team_name",
        "resolved_club_name",
        "event_registration_id",
    }
    missing = required_input - set(FIELDNAMES)
    assert missing == set(), f"missing required CLI input columns: {missing}"


def test_fieldnames_cover_matcher_output_set():
    required_matcher = {
        "matcher_status",
        "matcher_best_score",
        "matcher_second_score",
        "matcher_score_gap",
        "matcher_resolved_team_id_master",
        "matcher_resolved_team_name",
        "matcher_resolved_club_name",
        "matcher_resolved_provider_team_id",
    }
    missing = required_matcher - set(FIELDNAMES)
    assert missing == set(), f"missing matcher-output columns: {missing}"


def test_round_trip_stable_across_cycles(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    entries = [
        TeamRegistryEntry(
            event_registration_id="reg-1",
            event_team_name="Team A",
            event_age_group="u14",
            event_gender="Female",
            in_scope_u10_u19="True",
            resolved_team_id_master="master-1",
            matcher_status="strict_exact",
            matcher_best_score="0.97",
        ),
        TeamRegistryEntry(
            event_registration_id="reg-2",
            event_team_name="Team B",
            event_age_group="u15",
            in_scope_u10_u19="False",
        ),
    ]
    for _ in range(2):
        write_registry(EVENT_KEY, SCENARIO, entries, base_dir=tmp_path)
        loaded = read_registry(EVENT_KEY, SCENARIO, base_dir=tmp_path)
        assert loaded == entries


def test_sibling_schema_json_written_and_validated(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    write_registry(EVENT_KEY, SCENARIO, [], base_dir=tmp_path)
    schema_path = scenario_dir(EVENT_KEY, SCENARIO, base_dir=tmp_path) / "event_team_registry.schema.json"
    assert schema_path.exists()
    sidecar = json.loads(schema_path.read_text(encoding="utf-8"))
    assert sidecar["schema_version"] == 1
    assert tuple(sidecar["fieldnames"]) == FIELDNAMES


def test_matcher_output_columns_default_to_empty(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    entry = TeamRegistryEntry(event_registration_id="reg-1")
    write_registry(EVENT_KEY, SCENARIO, [entry], base_dir=tmp_path)
    loaded = read_registry(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert loaded[0].matcher_status == ""
    assert loaded[0].matcher_best_score == ""


def test_fieldnames_drift_logs_warning_not_raises(tmp_path: Path, caplog):
    """F22: forward-compat — drift warns but read succeeds."""
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    entry = TeamRegistryEntry(event_registration_id="reg-1", event_team_name="Team A")
    write_registry(EVENT_KEY, SCENARIO, [entry], base_dir=tmp_path)

    schema_path = scenario_dir(EVENT_KEY, SCENARIO, base_dir=tmp_path) / "event_team_registry.schema.json"
    schema_path.write_text(
        json.dumps({"schema_version": 1, "fieldnames": ["event_team_name"]}),
        encoding="utf-8",
    )
    with caplog.at_level("WARNING"):
        loaded = read_registry(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert loaded[0].event_team_name == "Team A"
    assert any("FIELDNAMES drift" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Shell 10: build_registry_entry / compute_dropped_pids / persist_registry_for_scenario
# ---------------------------------------------------------------------------


def _journal_record(
    *,
    pid: str = "12345",
    team_name: str = "Test FC 2014",
    club_name: str = "Test FC",
    cohort_age: str = "U14",
    cohort_gender: str = "Male",
    provider_id_status: str = "resolved",
    canonical: dict | None = None,
) -> dict:
    return {
        "provider_team_id": pid,
        "team_name": team_name,
        "club_name": club_name,
        "cohort_age_group": cohort_age,
        "cohort_gender": cohort_gender,
        "provider_id_resolution_status": provider_id_status,
        "canonical": canonical
        if canonical is not None
        else {
            "scraper_state": "alias_written",
            "team_id_master": "master-abc",
            "resolved_status": "strict_exact",
        },
    }


def test_build_registry_entry_maps_journal_record():
    entry = build_registry_entry(_journal_record())
    assert entry.event_team_name == "Test FC 2014"
    assert entry.event_age_group == "u14"
    assert entry.display_age_group == "U14"
    assert entry.event_gender == "Male"
    assert entry.in_scope_u10_u19 == "True"
    assert entry.resolved_gotsport_provider_team_id == "12345"
    assert entry.resolved_team_id_master == "master-abc"
    # canonical_resolution_status is left empty — matcher pass is sole writer.
    assert entry.canonical_resolution_status == ""
    # All matcher_* columns are empty in the builder; matcher pass populates.
    assert entry.matcher_status == ""
    assert entry.matcher_best_score == ""


def test_build_registry_entry_in_scope_for_u10_through_u19():
    for age in ("u10", "u14", "u19"):
        entry = build_registry_entry(_journal_record(cohort_age=age))
        assert entry.in_scope_u10_u19 == "True", age


def test_build_registry_entry_out_of_scope_for_u8_and_u20():
    for age in ("U8", "u9", "u20"):
        entry = build_registry_entry(_journal_record(cohort_age=age))
        assert entry.in_scope_u10_u19 == "False", age


def test_build_registry_entry_handles_missing_canonical():
    base = _journal_record()
    base["canonical"] = None
    entry_none = build_registry_entry(base)

    no_key = _journal_record()
    no_key.pop("canonical", None)
    entry_no_key = build_registry_entry(no_key)

    for entry in (entry_none, entry_no_key):
        # No crash; resolved_team_id_master left empty when no canonical.
        assert entry.resolved_team_id_master == ""


def test_build_registry_entry_handles_malformed_age():
    entry = build_registry_entry(_journal_record(cohort_age=""))
    assert entry.event_age_group == ""
    assert entry.in_scope_u10_u19 == "False"


def test_build_registry_entry_resolved_pid_only_when_status_resolved():
    entry = build_registry_entry(_journal_record(provider_id_status="placeholder"))
    assert entry.resolved_gotsport_provider_team_id == ""


def test_build_registry_entries_dedupes_multibracket():
    records = [_journal_record(pid="111"), _journal_record(pid="111", team_name="DUP")]
    entries = build_registry_entries(records)
    assert len(entries) == 1
    # First-seen wins.
    assert entries[0].event_team_name == "Test FC 2014"


def test_compute_dropped_pids(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    existing = [
        TeamRegistryEntry(resolved_gotsport_provider_team_id="a"),
        TeamRegistryEntry(resolved_gotsport_provider_team_id="b"),
        TeamRegistryEntry(resolved_gotsport_provider_team_id="c"),
    ]
    write_registry(EVENT_KEY, SCENARIO, existing, base_dir=tmp_path)
    fresh = [
        TeamRegistryEntry(resolved_gotsport_provider_team_id="b"),
        TeamRegistryEntry(resolved_gotsport_provider_team_id="c"),
        TeamRegistryEntry(resolved_gotsport_provider_team_id="d"),
    ]
    dropped = compute_dropped_pids(EVENT_KEY, SCENARIO, fresh, base_dir=tmp_path)
    assert dropped == ["a"]


def test_compute_dropped_pids_first_scrape(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    fresh = [TeamRegistryEntry(resolved_gotsport_provider_team_id="a")]
    assert compute_dropped_pids(EVENT_KEY, SCENARIO, fresh, base_dir=tmp_path) == []


def test_compute_dropped_pids_ignores_unresolved(tmp_path: Path):
    """Entries with empty pid appear in NEITHER set — invisible to the diff."""
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    existing = [
        TeamRegistryEntry(resolved_gotsport_provider_team_id=""),
        TeamRegistryEntry(resolved_gotsport_provider_team_id="b"),
    ]
    write_registry(EVENT_KEY, SCENARIO, existing, base_dir=tmp_path)
    fresh = [
        TeamRegistryEntry(resolved_gotsport_provider_team_id=""),
        TeamRegistryEntry(resolved_gotsport_provider_team_id="b"),
    ]
    # Both unresolved entries are invisible — "" is not "dropped".
    assert compute_dropped_pids(EVENT_KEY, SCENARIO, fresh, base_dir=tmp_path) == []


def test_persist_registry_for_scenario_writes_clean(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    fresh = [TeamRegistryEntry(event_team_name="X", resolved_gotsport_provider_team_id="a")]
    result = persist_registry_for_scenario(EVENT_KEY, SCENARIO, fresh, base_dir=tmp_path)
    assert isinstance(result, RegistryPersistResult)
    assert result.written is True
    assert result.row_count == 1
    assert result.dropped_pids == []
    assert result.lock_contention is False
    loaded = read_registry(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert loaded == fresh


def test_persist_registry_for_scenario_overwrites_existing(tmp_path: Path):
    """Clean-rebuild — no merge. Prior matcher_* values are not preserved."""
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    prior = [
        TeamRegistryEntry(
            resolved_gotsport_provider_team_id="a",
            matcher_resolved_team_name="Operator Edited",
        )
    ]
    write_registry(EVENT_KEY, SCENARIO, prior, base_dir=tmp_path)
    fresh = [TeamRegistryEntry(resolved_gotsport_provider_team_id="a")]
    persist_registry_for_scenario(EVENT_KEY, SCENARIO, fresh, base_dir=tmp_path)
    loaded = read_registry(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert loaded == fresh
    # The "Operator Edited" string is gone — clean overwrite by design.
    assert loaded[0].matcher_resolved_team_name == ""


def test_persist_registry_for_scenario_returns_dropped_pids(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    write_registry(
        EVENT_KEY,
        SCENARIO,
        [
            TeamRegistryEntry(resolved_gotsport_provider_team_id="a"),
            TeamRegistryEntry(resolved_gotsport_provider_team_id="b"),
        ],
        base_dir=tmp_path,
    )
    fresh = [TeamRegistryEntry(resolved_gotsport_provider_team_id="b")]
    result = persist_registry_for_scenario(EVENT_KEY, SCENARIO, fresh, base_dir=tmp_path)
    assert result.dropped_pids == ["a"]


def test_persist_registry_for_scenario_empty_journal(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    result = persist_registry_for_scenario(EVENT_KEY, SCENARIO, [], base_dir=tmp_path)
    assert result.written is True
    assert result.row_count == 0
    assert read_registry(EVENT_KEY, SCENARIO, base_dir=tmp_path) == []


def test_persist_registry_for_scenario_all_out_of_scope(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    fresh = [
        build_registry_entry(_journal_record(pid="1", cohort_age="U8")),
        build_registry_entry(_journal_record(pid="2", cohort_age="u9")),
    ]
    assert all(e.in_scope_u10_u19 == "False" for e in fresh)
    result = persist_registry_for_scenario(EVENT_KEY, SCENARIO, fresh, base_dir=tmp_path)
    assert result.written is True
    assert result.row_count == 2
    loaded = read_registry(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert all(e.in_scope_u10_u19 == "False" for e in loaded)


def test_matcher_status_locked_vocabulary(tmp_path: Path):
    """Round-trip a registry with each locked-vocabulary value; FIELDNAMES contract holds."""
    locked = ["", "strict_exact", "high_confidence", "direct_provider_id", "review", "none"]
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    entries = [
        TeamRegistryEntry(
            resolved_gotsport_provider_team_id=f"pid-{i}",
            matcher_status=value,
        )
        for i, value in enumerate(locked)
    ]
    write_registry(EVENT_KEY, SCENARIO, entries, base_dir=tmp_path)
    loaded = read_registry(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    seen = {e.matcher_status for e in loaded}
    assert seen <= set(locked)
