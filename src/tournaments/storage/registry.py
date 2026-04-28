"""Per-team event registry CSV — wire format mirrors the existing CLI consumer.

Spec §8 line 302: *"the existing ``backtest_tournament_event.py`` CLI is
unchanged for v1."* The columns the CLI reads from
``event_team_registry.csv`` are authoritative — this storage library is a
passthrough to that format.

Authoritative column set (verified against
``scripts/backtest_tournament_event.py:145-153, 167-217``):

- Input columns the Streamlit layer writes / the CLI reads:
  ``event_registration_id``, ``event_team_name``, ``event_age_group``,
  ``display_age_group``, ``event_gender``, ``display_gender``,
  ``event_club_name``, ``search_age_group``,
  ``resolved_gotsport_provider_team_id``, ``canonical_resolution_status``,
  ``in_scope_u10_u19`` (string ``"True"``/``"False"`` — see
  ``backtest_tournament_event.py:177``), ``resolved_team_id_master``,
  ``resolved_team_name``, ``resolved_club_name``.
- Matcher-output columns the CLI appends and re-reads on a round trip:
  ``matcher_status``, ``matcher_best_score``, ``matcher_second_score``,
  ``matcher_score_gap``, ``matcher_resolved_team_id_master``,
  ``matcher_resolved_team_name``, ``matcher_resolved_club_name``,
  ``matcher_resolved_provider_team_id``.

Schema-version stamp lives in the sibling ``event_team_registry.schema.json``
(one stamp per file), not as a per-row dataclass field — JSON-backed
dataclasses (``EventMetadata``, ``CohortConstraints``, ``FrozenMedians``)
carry ``schema_version`` because they round-trip as a single dict.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from src.tournaments.seeding_optimizer import normalize_age_group, normalize_gender_label
from src.tournaments.storage._io import read_csv, read_json, write_csv, write_json
from src.tournaments.storage.event_key import scenario_dir
from src.tournaments.storage.schema_version import (
    assert_supported_version,
    stamp_schema_version,
)

logger = logging.getLogger(__name__)

__all__ = [
    "FIELDNAMES",
    "RegistryPersistResult",
    "TeamRegistryEntry",
    "build_registry_entries",
    "build_registry_entry",
    "compute_dropped_pids",
    "persist_registry_for_scenario",
    "read_registry",
    "write_registry",
]

_ACCEPTED_CANONICAL_STATUSES: frozenset[str] = frozenset({"direct_provider_id", "strict_exact", "high_confidence"})


FIELDNAMES: tuple[str, ...] = (
    # Input columns — Streamlit writes, CLI reads
    "event_registration_id",
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
    # Matcher-output columns — CLI appends in this order
    # (see ``backtest_tournament_event.py:168-175``)
    "matcher_status",
    "matcher_best_score",
    "matcher_second_score",
    "matcher_score_gap",
    "matcher_resolved_team_id_master",
    "matcher_resolved_team_name",
    "matcher_resolved_club_name",
    "matcher_resolved_provider_team_id",
)


@dataclass(frozen=True)
class TeamRegistryEntry:
    """One row of ``event_team_registry.csv``.

    Every field is ``str`` to round-trip the CSV exactly — the CLI consumes
    strings and the matcher stores numeric scores as ``int | float | ""``,
    which only round-trips losslessly through string fields.

    No ``schema_version`` field — schema versioning for the CSV-backed
    registry lives in the sibling ``event_team_registry.schema.json`` (one
    stamp per file), not per row.
    """

    event_registration_id: str = ""
    event_team_name: str = ""
    event_age_group: str = ""
    display_age_group: str = ""
    event_gender: str = ""
    display_gender: str = ""
    event_club_name: str = ""
    search_age_group: str = ""
    resolved_gotsport_provider_team_id: str = ""
    canonical_resolution_status: str = ""
    in_scope_u10_u19: str = ""
    resolved_team_id_master: str = ""
    resolved_team_name: str = ""
    resolved_club_name: str = ""
    matcher_status: str = ""
    matcher_best_score: str = ""
    matcher_second_score: str = ""
    matcher_score_gap: str = ""
    matcher_resolved_team_id_master: str = ""
    matcher_resolved_team_name: str = ""
    matcher_resolved_club_name: str = ""
    matcher_resolved_provider_team_id: str = ""

    def to_row(self) -> dict[str, str]:
        """String-only round-trip — no type coercion (CLI consumes strings)."""
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "TeamRegistryEntry":
        """Construct from a CSV row, defaulting missing columns to ``""``.

        Extra columns in the CSV are silently ignored (forward-compat
        within ``schema_version: 1``; cf. ``write_registry`` policy).
        """
        kwargs = {field.name: str(row.get(field.name, "") or "") for field in fields(cls)}
        return cls(**kwargs)


def _schema_path(scenario_path: Path) -> Path:
    return scenario_path / "event_team_registry.schema.json"


def _csv_path(scenario_path: Path) -> Path:
    return scenario_path / "event_team_registry.csv"


def read_registry(
    event_key: str,
    scenario: str,
    *,
    base_dir: Path | str = "reports",
) -> list[TeamRegistryEntry]:
    """Read the per-scenario team registry CSV.

    Validates the sibling ``event_team_registry.schema.json`` via
    ``assert_supported_version`` (raises ``SchemaVersionError`` on a newer
    schema). A FIELDNAMES mismatch is **logged as a warning but does NOT
    raise** — the CSV header itself is the authoritative wire-format check,
    and v1.x adds of optional matcher-output columns must remain
    forward-compatible within ``schema_version: 1``.
    """
    scenario_path = scenario_dir(event_key, scenario, base_dir=base_dir)
    schema_path = _schema_path(scenario_path)
    if schema_path.exists():
        sidecar = read_json(schema_path)
        assert_supported_version(sidecar, source=str(schema_path))
        sidecar_fields = tuple(sidecar.get("fieldnames") or ())
        if sidecar_fields and sidecar_fields != FIELDNAMES:
            logger.warning(
                "[registry] %s sibling FIELDNAMES drift; on-disk=%s expected=%s",
                schema_path.name,
                sidecar_fields,
                FIELDNAMES,
            )

    rows = read_csv(_csv_path(scenario_path))
    return [TeamRegistryEntry.from_row(row) for row in rows]


def write_registry(
    event_key: str,
    scenario: str,
    entries: list[TeamRegistryEntry],
    *,
    base_dir: Path | str = "reports",
) -> None:
    """Write the per-scenario team registry CSV + sibling schema stamp."""
    scenario_path = scenario_dir(event_key, scenario, base_dir=base_dir)
    rows = [entry.to_row() for entry in entries]
    write_csv(_csv_path(scenario_path), rows, fieldnames=FIELDNAMES)
    write_json(
        _schema_path(scenario_path),
        stamp_schema_version({"fieldnames": list(FIELDNAMES)}),
    )


# ---------------------------------------------------------------------------
# Scrape-pipeline persistence (Shell 10)
#
# These helpers translate ``intake/raw_scrape.jsonl`` records into
# ``TeamRegistryEntry`` rows and persist them to ``scenarios/<name>/event_team_registry.csv``.
# Per spec §8 line 289, the registry is a derived, regenerable artifact —
# clean-rebuild every scrape; operator state survives via ``overrides.jsonl``
# layered at read time by ``triage.project_overrides``.
# ---------------------------------------------------------------------------


def _normalize_age_safe(value: Any) -> str:
    """Wrap ``normalize_age_group`` so empty / malformed cohort tags don't crash the scrape.

    ``normalize_age_group("")`` raises ``ValueError`` — we don't want a single
    bad cohort tag to abort the whole registry build. Returns ``""`` on
    failure; the caller's ``_in_scope_u10_u19`` then resolves to ``"False"``
    so the row is admitted but skipped by the matcher pass.
    """
    try:
        return normalize_age_group(str(value or ""))
    except ValueError:
        return ""


def _in_scope_u10_u19(normalized_age_group: str) -> str:
    """Return literal-string ``"True"``/``"False"`` per the CLI gate at
    ``backtest_tournament_event.py:177``.

    Input is the output of ``normalize_age_group`` (e.g. ``"u14"``); strip
    leading ``"u"``, parse int, return ``"True"`` if ``10 <= n <= 19`` else
    ``"False"``. On parse failure (empty / non-numeric) return ``"False"`` —
    out-of-scope is the safe default.
    """
    if not normalized_age_group.startswith("u"):
        return "False"
    try:
        n = int(normalized_age_group.removeprefix("u"))
    except ValueError:
        return "False"
    return "True" if 10 <= n <= 19 else "False"


def build_registry_entry(record: dict[str, Any]) -> TeamRegistryEntry:
    """Map one ``intake/raw_scrape.jsonl`` record to a ``TeamRegistryEntry``.

    Record shape per ``src/scrapers/gotsport.py::_build_jsonl_record``: top-level
    ``provider_team_id``, ``team_name``, ``club_name``, ``cohort_age_group``,
    ``cohort_gender``, ``provider_id_resolution_status``, plus a nested
    ``canonical: {team_id_master, confidence, resolved_status, match_method,
    scraper_state}`` dict that may legitimately be missing or ``None`` on
    pre-canonical or partial-write tail-recovery records (mirrors
    ``triage._classify_team_state`` defensive access).

    ``canonical_resolution_status`` is left ``""`` here — ``enrich_registry_rows_with_matcher``
    is the sole writer (see ``src/tournaments/event_team_matcher.py``). All
    ``matcher_*`` columns are also ``""``; the matcher pass populates them
    for rows where the short-circuit at ``_enrich`` doesn't fire.

    Every value is coerced to ``str``; missing values become ``""`` (the CSV
    round-trips strings only).
    """
    canonical = record.get("canonical") or {}
    raw_age = str(record.get("cohort_age_group") or "")
    raw_gender = str(record.get("cohort_gender") or "")
    normalized_age = _normalize_age_safe(raw_age)
    normalized_gender = normalize_gender_label(raw_gender) if raw_gender else ""

    provider_id_status = str(record.get("provider_id_resolution_status") or "")
    provider_team_id = str(record.get("provider_team_id") or "")
    resolved_pid = provider_team_id if provider_id_status == "resolved" else ""

    scraper_state = str(canonical.get("scraper_state") or "")
    canonical_team_id = str(canonical.get("team_id_master") or "") if scraper_state == "alias_written" else ""

    return TeamRegistryEntry(
        event_registration_id="",
        event_team_name=str(record.get("team_name") or ""),
        event_age_group=normalized_age,
        display_age_group=raw_age,
        event_gender=normalized_gender,
        display_gender=raw_gender,
        event_club_name=str(record.get("club_name") or ""),
        search_age_group="",
        resolved_gotsport_provider_team_id=resolved_pid,
        canonical_resolution_status="",
        in_scope_u10_u19=_in_scope_u10_u19(normalized_age),
        resolved_team_id_master=canonical_team_id,
        resolved_team_name="",
        resolved_club_name="",
        matcher_status="",
        matcher_best_score="",
        matcher_second_score="",
        matcher_score_gap="",
        matcher_resolved_team_id_master="",
        matcher_resolved_team_name="",
        matcher_resolved_club_name="",
        matcher_resolved_provider_team_id="",
    )


def build_registry_entries(records: list[dict[str, Any]]) -> list[TeamRegistryEntry]:
    """Build a registry-row list from journal records, deduped by ``provider_team_id``.

    Defensive dedupe (first-seen wins) — ``IntakeJournal.read()`` already
    returns ``dict[pid, record]`` so duplicates would normally be impossible.
    Logs at DEBUG when dedupe actually fires so a future journal-format change
    that admits duplicates surfaces in tests.
    """
    seen: set[str] = set()
    entries: list[TeamRegistryEntry] = []
    for record in records:
        pid = str(record.get("provider_team_id") or "")
        if pid and pid in seen:
            logger.debug("[registry] dedupe fired for provider_team_id=%s", pid)
            continue
        if pid:
            seen.add(pid)
        entries.append(build_registry_entry(record))
    return entries


def compute_dropped_pids(
    event_key: str,
    scenario: str,
    fresh: list[TeamRegistryEntry],
    *,
    base_dir: Path | str = "reports",
) -> list[str]:
    """Return ``provider_team_id`` values present in the on-disk registry but absent from ``fresh``.

    Lock contract: **caller MUST hold ``acquire_scenario_lock(event_key, scenario)``**
    for the result to be consistent with the about-to-be-written registry.
    Calling this helper outside any lock (e.g., from a diagnostic CLI) returns
    data that may already be stale relative to the on-disk CSV.

    Entries with empty ``resolved_gotsport_provider_team_id`` are intentionally
    invisible to the diff — they appear in NEITHER ``existing_pids`` NOR
    ``fresh_pids``. The truthy filter prevents collapsing all unresolved
    entries onto a phantom empty-string key.

    Returns ``[]`` when the registry CSV does not yet exist (first scrape).
    """
    try:
        existing = read_registry(event_key, scenario, base_dir=base_dir)
    except FileNotFoundError:
        return []
    existing_pids = {e.resolved_gotsport_provider_team_id for e in existing if e.resolved_gotsport_provider_team_id}
    fresh_pids = {e.resolved_gotsport_provider_team_id for e in fresh if e.resolved_gotsport_provider_team_id}
    return sorted(existing_pids - fresh_pids)


@dataclass(frozen=True)
class RegistryPersistResult:
    """Per-scenario outcome of a registry write.

    ``lock_contention`` is the discriminator the streamlit UI dispatches on —
    string-matching ``error`` is brittle because the message is operator-
    facing and may be reworded or i18n'd. The boolean is set ``True`` only
    when catching ``ScenarioLockError``; for other failures the caller sets
    it ``False`` and stashes the exception text in ``error``.
    """

    scenario: str
    written: bool
    row_count: int
    dropped_pids: list[str]
    lock_contention: bool = False
    error: str | None = None


def persist_registry_for_scenario(
    event_key: str,
    scenario: str,
    fresh: list[TeamRegistryEntry],
    *,
    base_dir: Path | str = "reports",
) -> RegistryPersistResult:
    """Compute dropped pids and clean-overwrite the registry CSV for one scenario.

    Locking is the caller's responsibility — this helper does NOT take or
    hold any lock. Tests pass ``base_dir=tmp_path`` and exercise directly.
    Internal exceptions (``OSError``, ``PermissionError``, anything from
    ``compute_dropped_pids`` / ``write_registry``) PROPAGATE; the caller
    catches them and converts to a non-``written`` ``RegistryPersistResult``.
    """
    dropped_pids = compute_dropped_pids(event_key, scenario, fresh, base_dir=base_dir)
    write_registry(event_key, scenario, fresh, base_dir=base_dir)
    if dropped_pids:
        logger.warning(
            "Registry rebuild for scenario=%s dropped %d orphaned pid(s) keyed by "
            "resolved_gotsport_provider_team_id: %s",
            scenario,
            len(dropped_pids),
            dropped_pids,
        )
    return RegistryPersistResult(
        scenario=scenario,
        written=True,
        row_count=len(fresh),
        dropped_pids=dropped_pids,
        lock_contention=False,
        error=None,
    )
