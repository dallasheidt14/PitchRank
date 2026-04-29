"""Storage layer for the MatchBalance backtest intake.

A pure-Python library that owns every file I/O, schema-version, and
scenario-locking primitive used by the Streamlit triage UI (Shell 03+) and
the existing ``backtest_tournament_event.py`` CLI. No UI, no Supabase
ownership — callers compose this layer with their own clients.

Layout (per spec §8):

    reports/<event_key>/
      intake/                       # SHARED across scenarios (immutable scrape output)
        raw_scrape.jsonl            # IntakeJournal (re-exported from src.scrapers)
        event_metadata.json
      scenarios/<name>/
        overrides.jsonl
        group_structure_summary.csv
        event_team_registry.csv
        constraints.json
        runs/<run_id>/              # promoted run dir (atomic from <run_id>.tmp/)

Public API is re-exported here; modules under ``storage/`` are the
implementation. ``read_versioned_json`` from ``_io`` is intentionally
package-private — external callers compose ``assert_supported_version`` +
``read_json`` directly.
"""

from __future__ import annotations

from src.tournaments.storage.constraints import (
    CohortConstraints,
    read_constraints,
    write_constraints,
)
from src.tournaments.storage.event_key import (
    RekeyMigrationResult,
    derive_season_year,
    event_dir,
    event_key,
    intake_dir,
    parse_event_key,
    rekey_unknown_directories,
    reports_dir,
    run_dir,
    scenario_dir,
    scenarios_dir,
)
from src.tournaments.storage.event_metadata import (
    EventMetadata,
    read_event_metadata,
    write_event_metadata,
)
from src.tournaments.storage.frozen_medians import (
    FrozenMedians,
    compute_frozen_medians,
    read_frozen_medians,
    write_frozen_medians,
)
from src.tournaments.storage.games_import import (
    GamesImportStatus,
    check_games_import_status,
)
from src.tournaments.storage.overrides import append_override, load_overrides
from src.tournaments.storage.raw_scrape import (
    DURABLE_ACTIONS,
    IntakeJournal,
    JournalCorruptionError,
    RemovedTeamsDiff,
    compute_skip_set,
    load_raw_scrape,
)
from src.tournaments.storage.registry import (
    RegistryPersistResult,
    TeamRegistryEntry,
    build_registry_entries,
    build_registry_entry,
    compute_dropped_pids,
    persist_registry_for_scenario,
    read_registry,
    write_registry,
)
from src.tournaments.storage.rescrape import RescrapeReport, merge_rescrape
from src.tournaments.storage.run_layout import (
    RunLockError,
    RunStateError,
    acquire_run_lock,
    cancel_run,
    create_staging_run,
    fail_run,
    list_runs,
    promote_run,
)
from src.tournaments.storage.scenario import (
    ScenarioExistsError,
    ScenarioLockError,
    acquire_scenario_lock,
    branch_scenario,
    ensure_scenario,
    list_scenarios,
)
from src.tournaments.storage.schema_version import (
    SCHEMA_VERSION,
    SchemaVersionError,
    assert_supported_version,
    stamp_schema_version,
)
from src.tournaments.storage.structure import (
    CohortStructure,
    DivisionStructure,
    read_structure,
    write_structure,
)

__all__ = [
    # event identity
    "event_key",
    "parse_event_key",
    "derive_season_year",
    "rekey_unknown_directories",
    "RekeyMigrationResult",
    # paths
    "reports_dir",
    "event_dir",
    "intake_dir",
    "scenarios_dir",
    "scenario_dir",
    "run_dir",
    # dataclasses
    "EventMetadata",
    "TeamRegistryEntry",
    "RegistryPersistResult",
    "DivisionStructure",
    "CohortStructure",
    "CohortConstraints",
    "FrozenMedians",
    "RescrapeReport",
    # status types / version
    "GamesImportStatus",
    "SCHEMA_VERSION",
    "SchemaVersionError",
    "stamp_schema_version",
    "assert_supported_version",
    # readers / writers
    "read_event_metadata",
    "write_event_metadata",
    "read_registry",
    "write_registry",
    "build_registry_entry",
    "build_registry_entries",
    "compute_dropped_pids",
    "persist_registry_for_scenario",
    "read_structure",
    "write_structure",
    "read_constraints",
    "write_constraints",
    "read_frozen_medians",
    "write_frozen_medians",
    "compute_frozen_medians",
    "append_override",
    "load_overrides",
    "load_raw_scrape",
    # operations
    "merge_rescrape",
    "ensure_scenario",
    "branch_scenario",
    "list_scenarios",
    "ScenarioExistsError",
    "ScenarioLockError",
    "acquire_scenario_lock",
    "create_staging_run",
    "promote_run",
    "fail_run",
    "cancel_run",
    "list_runs",
    "acquire_run_lock",
    "RunLockError",
    "RunStateError",
    "check_games_import_status",
    # raw-scrape re-exports
    "IntakeJournal",
    "JournalCorruptionError",
    "RemovedTeamsDiff",
    "compute_skip_set",
    "DURABLE_ACTIONS",
]
