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
    TeamRegistryEntry,
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
