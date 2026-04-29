"""Per-cohort backtest run orchestration — synchronous, atomic state machine.

Spec §9 (run state machine + run safety) + Section 10 fold-ins 1b / 5b /
6 / 12b / 21b. Owns the only writer that produces a fully-promoted
``runs/<run_id>/`` directory with a ``done.json`` — every downstream
reader (Shell 07's compute, Shell 08's Report Card embed and run-history
dropdown) is allowed to assume that contract.

Per-cohort: a click on the U14 boys "Run backtest" spawns one
``backtest_tournament_cohort.py`` subprocess for that cohort. Other
cohorts' Run buttons are independent — U10's blockers don't refuse a U14
run and vice versa.

Synchronous: ``execute_run`` blocks the caller (the Streamlit click
handler) until the subprocess finishes. The scenario lock acquires inside
this frame and releases when the function returns. v1 has no Cancel — the
storage layer's ``cancel_run`` exists for v2 use.

The orchestrator owns:

- per-cohort request payload construction (entrants + divisions) so the
  cohort CLI is invoked the same way as ``backtest_tournament_event.py``
- subprocess streaming (``Popen`` line iteration) with structured PHASE /
  PROGRESS markers parsed into ``ProgressEvent`` records
- ``run_metadata.json`` (CLI args + git SHA + per-input file hashes)
- ``run_overrides_audit.jsonl`` (per-cohort scope filter applied to
  ``overrides.jsonl``) + ``fallbacks.jsonl`` (parsed from cohort
  ``summary.json``'s notes + counts)
- orphan ``.tmp/`` cleanup at preflight time so a parent crash mid-run
  doesn't leave the runs dir corrupted forever

KNOWN RISK — division-routing heuristic (now resolver-driven):
  ``_build_cohort_request_payload`` calls ``resolve_division_assignment``
  per team. Resolver-returned ``source='none'`` means both the operator's
  ``assigned_division_name`` override AND the prefix heuristic missed for
  this team. ``source='stale'`` means the operator assigned a division
  that has since been removed. Shell 09 + the one-shot
  ``scripts/backfill_division_assignments.py`` make ``source='none'``
  rare on backfilled events; greenfield events still surface it until an
  operator confirms assignments. Both kinds emit distinct
  ``parser_warnings.jsonl`` records for cleanup.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from src.tournaments.storage import (
    ScenarioLockError,
    acquire_scenario_lock,
    create_staging_run,
    fail_run,
    load_overrides,
    promote_run,
    read_event_metadata,
    read_registry,
    read_structure,
    scenario_dir,
    stamp_schema_version,
)
from src.tournaments.storage._io import (
    append_jsonl,
    read_json,
    utc_now_iso,
    write_json,
)
from src.tournaments.triage import (
    SOURCE_EXPLICIT,
    SOURCE_PREFIX,
    SOURCE_STALE,
    ReadinessResult,
    is_ready,
    project_overrides,
    registry_provider_id,
    resolve_division_assignment,
)

logger = logging.getLogger(__name__)

__all__ = [
    "PreflightResult",
    "RunOutcome",
    "execute_run",
    "generate_run_id",
    "override_in_cohort",
    "preflight",
]


_MODEL_VERSION_ARTIFACT_MAP: dict[str, str] = {
    "poisson_draw_gate_v1": (
        "models/point_in_time_tournament_margin_postsnapshot_poisson_draw_gate_v1/point_in_time_match_model.pkl"
    ),
}
"""Maps ``meta.extras["model_version_pin"]`` to the on-disk artifact path
the cohort CLI loads via ``--point-in-time-model-artifact``. Hand-maintained;
adding a new model version is one new entry. Unknown pins raise ``ValueError``
inside ``_build_cli_args`` BEFORE Popen so the orchestrator surfaces a clear
preflight error instead of letting the cohort CLI fail later with
``FileNotFoundError``.
"""

_OTHER_COHORT_PREFIX_RE = re.compile(r"^(Boys|Girls) u\d+: ")
"""Triage cohort-prefixed blocker shape (e.g. ``"Boys u14: foo pending review"``).

Used by ``preflight`` to drop blockers naming a *different* cohort while
preserving cohort-agnostic blockers (``"event metadata missing or unreadable: ..."``)
and manual-add blockers (``"manual-add team_x: cohort attribution missing ..."``).
"""

_PROGRESS_LINE_RE = re.compile(r"^PROGRESS:\s+\S+\s+(\d+)/(\d+)\s*$")


@dataclass(frozen=True)
class ProgressEvent:
    """One structured update emitted by the running cohort subprocess.

    Module-internal — only ``execute_run``'s ``on_event`` callback exposes
    it. ``phase`` is set on a ``PHASE: <name>`` line; ``percent`` is set
    on a ``PROGRESS: <name> <i>/<n>`` line; ``raw_line`` always holds the
    original stdout text for fallback display.
    """

    phase: str | None
    percent: int | None
    raw_line: str
    ts: str


@dataclass(frozen=True)
class PreflightResult:
    """Per-cohort readiness verdict.

    ``ready`` is True iff ``blockers`` is empty. ``warnings`` never block
    the Run button — they decorate the enabled state with caveats
    (e.g. stale snapshot date, high external-team ratio).
    """

    ready: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RunOutcome:
    """Terminal state of one ``execute_run`` invocation.

    ``run_dir`` is the promoted ``runs/<run_id>/`` on success or the
    ``runs/<run_id>.failed/`` on failure. v1 has no cancelled state — the
    synchronous lifecycle never produces one.
    """

    state: Literal["completed", "failed"]
    run_dir: Path
    error: str | None = None


def generate_run_id(age: str, gender: str) -> str:
    """Return a cohort-scoped run id: ``u14_male_YYYYMMDDTHHMMSS_xxxxxxxxxxxx``.

    Cohort prefix keeps ``runs/`` listings distinguishable per cohort; the
    UTC timestamp + ``secrets.token_hex(6)`` (48 bits) makes within-second
    collisions vanishingly unlikely. If a collision still occurs,
    ``create_staging_run`` raises ``RunStateError`` and the caller surfaces
    a "click again" message rather than crashing.
    """
    timestamp = utc_now_iso().replace(":", "").replace("-", "")[:15]
    return f"{age}_{gender.lower()}_{timestamp}_{secrets.token_hex(6)}"


def _git_repo_sha() -> str:
    """Return ``git rev-parse HEAD`` or ``""`` if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _file_sha256(path: Path) -> str | None:
    """SHA-256 of the file at ``path``, or ``None`` if missing."""
    if not path.exists():
        return None
    with path.open("rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def _noop_on_event(_ev: ProgressEvent) -> None:
    """Default ``on_event`` callback — accept and discard.

    Lets callers omit ``on_event`` without sprinkling ``if cb is not None``
    null-guards through the streaming loop.
    """


def _progress_record(ev: ProgressEvent) -> dict[str, Any]:
    """Project a ``ProgressEvent`` to its JSONL row shape (single source of truth)."""
    return {"phase": ev.phase, "percent": ev.percent, "raw_line": ev.raw_line, "ts": ev.ts}


def _parse_progress_line(line: str, current_phase: str | None) -> ProgressEvent:
    """Parse one stdout line into a ``ProgressEvent``.

    - ``PHASE: <name>`` → phase set, percent None.
    - ``PROGRESS: <name> <i>/<n>`` → percent computed, phase carried from
      the most recent PHASE marker (PROGRESS does NOT change phase).
    - Anything else → both None; the line is buffered for the next
      phase-transition flush in ``execute_run``.
    """
    ts = utc_now_iso()
    if line.startswith("PHASE: "):
        return ProgressEvent(
            phase=line.removeprefix("PHASE: ").strip(),
            percent=None,
            raw_line=line,
            ts=ts,
        )
    if line.startswith("PROGRESS: "):
        match = _PROGRESS_LINE_RE.match(line)
        if match is not None:
            current = int(match.group(1))
            total = int(match.group(2))
            percent = int(round(100 * current / total)) if total else None
            return ProgressEvent(
                phase=current_phase,
                percent=percent,
                raw_line=line,
                ts=ts,
            )
    return ProgressEvent(phase=None, percent=None, raw_line=line, ts=ts)


def _slugify(value: str) -> str:
    """Lowercase + collapse non-alphanumerics — mirrors ``backtest_tournament_event._slugify``."""
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    return normalized.strip("_")


def _cleanup_orphan_staging_dirs(
    event_key: str,
    scenario: str,
    *,
    base_dir: Path | str,
    max_age_hours: int = 24,
) -> None:
    """Remove ``runs/<id>.tmp/`` directories older than ``max_age_hours``.

    Defends against parent-process crashes mid-run. Does NOT touch
    in-flight runs — ``progress.jsonl`` is appended every PHASE transition
    so its mtime tracks liveness. v1 assumes runs complete in well under
    24h (typical Phoenix Cup cohort: 30–120s).
    """
    runs_root = scenario_dir(event_key, scenario, base_dir=base_dir) / "runs"
    if not runs_root.exists():
        return
    threshold_seconds = max_age_hours * 3600
    now = time.time()
    for entry in runs_root.iterdir():
        if not entry.is_dir() or not entry.name.endswith(".tmp"):
            continue
        progress_log = entry / "progress.jsonl"
        if progress_log.exists():
            mtime = progress_log.stat().st_mtime
        else:
            mtime = entry.stat().st_mtime
        age_seconds = now - mtime
        if age_seconds > threshold_seconds:
            shutil.rmtree(entry, ignore_errors=True)
            logger.warning(
                "[run_orchestrator] cleaned up orphan staging dir %s (age %ds)",
                entry.name,
                int(age_seconds),
            )


def preflight(
    event_key: str,
    scenario: str,
    age: str,
    gender: str,
    *,
    base_dir: Path | str = "reports",
    supabase_client: Any,
) -> PreflightResult:
    """Compute per-cohort readiness + warnings before showing the Run button.

    Wraps ``triage.is_ready`` (scenario-wide) and filters its blockers to
    ones not naming a different cohort, so a U10 blocker doesn't refuse a
    U14 run. Cohort-agnostic blockers (event-metadata-missing, manual-add
    cohort-attribution-missing) survive the filter — they correctly block
    every cohort's Run button.

    Warnings axis (does NOT block):

    - Stale ranking snapshot (>14 days before kickoff or today)
    - High external-team ratio (>30% of registered cohort size)
    """
    # Cleanup races against in-flight runs in theory; the 24h threshold and
    # per-PHASE mtime updates make actual data loss vanishingly unlikely, but
    # we still skip cleanup whenever the scenario is currently locked rather
    # than block the page render waiting for the lock.
    try:
        with acquire_scenario_lock(event_key, scenario, base_dir=base_dir, timeout=0.0):
            _cleanup_orphan_staging_dirs(event_key, scenario, base_dir=base_dir)
    except ScenarioLockError:
        pass

    result: ReadinessResult = is_ready(
        event_key,
        scenario,
        base_dir=base_dir,
        supabase_client=supabase_client,
    )

    this_label = f"{gender} {age}: "

    def is_other_cohort(blocker: str) -> bool:
        match = _OTHER_COHORT_PREFIX_RE.match(blocker)
        return match is not None and not blocker.startswith(this_label)

    blockers_for_cohort = tuple(b for b in result.blockers if not is_other_cohort(b))

    warnings: list[str] = []
    try:
        meta = read_event_metadata(event_key, base_dir=base_dir)
    except Exception:  # noqa: BLE001 — warnings are best-effort; surface only via blocker path
        meta = None

    if meta is not None:
        snapshot_raw = (meta.extras or {}).get("ranking_snapshot_date")
        snapshot_date: date | None = None
        if isinstance(snapshot_raw, str):
            try:
                snapshot_date = date.fromisoformat(snapshot_raw)
            except ValueError:
                snapshot_date = None
        if snapshot_date is not None:
            reference_raw = meta.event_start_date
            reference_date: date | None = None
            if isinstance(reference_raw, str):
                try:
                    reference_date = date.fromisoformat(reference_raw)
                except ValueError:
                    reference_date = None
            if reference_date is None:
                reference_date = date.today()
            if (reference_date - snapshot_date).days > 14:
                warnings.append("ranking snapshot older than 14 days")

    try:
        overrides = load_overrides(event_key, scenario, base_dir=base_dir)
    except FileNotFoundError:
        overrides = []
    team_state, _ = project_overrides(overrides)

    try:
        registry = read_registry(event_key, scenario, base_dir=base_dir)
    except FileNotFoundError:
        registry = []

    cohort_size = sum(1 for entry in registry if entry.event_age_group == age and entry.event_gender == gender)
    external_count = 0
    for entry in registry:
        if entry.event_age_group != age or entry.event_gender != gender:
            continue
        pid = registry_provider_id(entry)
        projected = team_state.get(pid)
        if projected is not None and projected.state == "external":
            external_count += 1
    for team_ref, projected in team_state.items():
        if not team_ref.startswith("manual_"):
            continue
        if projected.cohort_age_group != age or projected.cohort_gender != gender:
            continue
        if projected.state == "external":
            external_count += 1
            cohort_size += 1
        elif projected.state == "resolved":
            cohort_size += 1

    if cohort_size and external_count / cohort_size > 0.30:
        warnings.append(f"high external-team ratio ({external_count} of {cohort_size})")

    return PreflightResult(
        ready=not blockers_for_cohort,
        blockers=blockers_for_cohort,
        warnings=tuple(warnings),
    )


def _build_cohort_request_payload(
    event_key: str,
    scenario: str,
    age: str,
    gender: str,
    *,
    base_dir: Path | str,
    extras: dict[str, Any],
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Build the cohort CLI's request payload (entrants + divisions).

    Returns ``(payload, division_routing_fallbacks, division_routing_stale_assignments)``.
    ``fallbacks`` is the list of team names whose resolver returned
    ``source="none"`` (no assignment AND no prefix match);
    ``stale_assignments`` is the list whose resolver returned
    ``source="stale"`` (operator-assigned division has since been removed).
    ``execute_run`` emits two distinct ``parser_warnings.jsonl`` kinds so
    operators can grep them independently.

    Mirrors ``scripts.backtest_tournament_event._build_request_payload``
    (event:380-440) — inlined rather than imported because the script-side
    ``sys.path`` setup is brittle for a package import. ``age`` is in
    ``u14`` form; ``gender`` is ``"Boys"`` or ``"Girls"`` (matches
    ``read_structure`` output, which already normalizes both).
    """
    if not age.startswith("u"):
        raise ValueError(f"age must be normalized (e.g. 'u14'); got {age!r}")
    if gender not in ("Boys", "Girls"):
        raise ValueError(f"gender must be 'Boys' or 'Girls'; got {gender!r}")

    meta = read_event_metadata(event_key, base_dir=base_dir)
    registry = read_registry(event_key, scenario, base_dir=base_dir)
    structure = read_structure(event_key, scenario, base_dir=base_dir)

    cohort_structure = next(
        (c for c in structure if c.age_group == age and c.gender == gender),
        None,
    )
    if cohort_structure is None:
        raise ValueError(f"structure for cohort {age}/{gender} not found")

    overrides = load_overrides(event_key, scenario, base_dir=base_dir)
    team_state, _ = project_overrides(overrides)

    division_names = [d.name for d in cohort_structure.divisions]
    teams_by_division: dict[str, list[dict[str, Any]]] = {name: [] for name in division_names}
    division_routing_fallbacks: list[str] = []
    division_routing_stale_assignments: list[str] = []

    for entry in registry:
        if entry.event_age_group != age or entry.event_gender != gender:
            continue
        pid = registry_provider_id(entry)
        projected = team_state.get(pid)
        team_id_master = (
            projected.team_id_master
            if projected is not None and projected.team_id_master
            else (entry.resolved_team_id_master or "")
        )
        if not team_id_master:
            continue
        team_name = entry.event_team_name or pid
        resolution = resolve_division_assignment(projected, team_name, division_names=division_names)
        if resolution.source in (SOURCE_EXPLICIT, SOURCE_PREFIX):
            chosen_division = resolution.name or ""
        elif resolution.source == SOURCE_STALE:
            # Stale assignment: use the prefix-resolved fallback name when
            # available, else first division. Track separately so the
            # parser_warning splits "stale" from "never assigned".
            chosen_division = resolution.name or (division_names[0] if division_names else "")
            division_routing_stale_assignments.append(team_name)
        else:  # SOURCE_NONE
            chosen_division = division_names[0] if division_names else ""
            division_routing_fallbacks.append(team_name)
        if chosen_division not in teams_by_division:
            teams_by_division[chosen_division] = []
        teams_by_division[chosen_division].append(
            {
                "team_id_master": team_id_master,
                "provider_team_id": pid,
                "event_team_name": team_name,
            }
        )

    age_suffix = age.removeprefix("u")
    bu_prefix = f"BU{age_suffix} "

    entrants: list[dict[str, Any]] = []
    divisions_payload: list[dict[str, Any]] = []
    for division in cohort_structure.divisions:
        actual_division_name = division.name
        # ``BU<n> `` strip mirrors event:403/414 for parity with the event CLI.
        normalized_name = (
            actual_division_name.removeprefix(bu_prefix).strip()
            if actual_division_name.startswith(bu_prefix)
            else actual_division_name
        )
        for team in sorted(teams_by_division.get(actual_division_name, []), key=lambda t: t["team_id_master"]):
            entrants.append(
                {
                    "entrant_id": f"{_slugify(actual_division_name)}_{_slugify(team['event_team_name'])}",
                    "canonical_team_id": team["team_id_master"],
                    "provider_team_id": team["provider_team_id"],
                    "event_team_name": team["event_team_name"],
                    "event_age_group": age,
                    "event_gender": gender,
                    "actual_division_name": normalized_name,
                }
            )
        divisions_payload.append(
            {
                "name": normalized_name,
                "actual_division_name": actual_division_name,
                "team_count": division.team_count,
                "pool_sizes": list(division.pool_sizes),
            }
        )

    payload: dict[str, Any] = {
        "event_name": meta.event_name,
        "age_group": age,
        "gender": gender.lower(),
        "divisions": divisions_payload,
        "entrants": entrants,
    }
    snapshot_date = extras.get("ranking_snapshot_date")
    if snapshot_date:
        payload["prediction_date"] = snapshot_date
    return payload, sorted(division_routing_fallbacks), sorted(division_routing_stale_assignments)


def _build_cli_args(staging_dir: Path, *, extras: dict[str, Any]) -> tuple[list[str], Path]:
    """Return ``(cli_args, request_path)`` for the cohort CLI invocation.

    All defaults are passed explicitly so ``run_metadata.cli_args`` is
    exhaustive and reproducible. Unknown ``model_version_pin`` raises
    ``ValueError`` BEFORE Popen — better than letting the cohort CLI fail
    later with ``FileNotFoundError`` on a missing artifact.
    """
    request_path = staging_dir / "request.json"
    model_pin = extras.get("model_version_pin", "poisson_draw_gate_v1")
    artifact = _MODEL_VERSION_ARTIFACT_MAP.get(model_pin)
    if artifact is None:
        raise ValueError(f"unknown model_version_pin: {model_pin!r}; known: {list(_MODEL_VERSION_ARTIFACT_MAP)}")
    cli_args = [
        "--input",
        str(request_path),
        "--output-dir",
        str(staging_dir),
        "--predictor-source",
        "point_in_time",
        "--point-in-time-model-artifact",
        artifact,
        "--history-lookback-days",
        "365",
        "--snapshot-buffer-days",
        "30",
    ]
    return cli_args, request_path


def _collect_run_metadata(
    event_key: str,
    scenario: str,
    age: str,
    gender: str,
    run_id: str,
    *,
    base_dir: Path | str,
    started_at: str,
    cli_args: list[str],
    extras: dict[str, Any],
) -> dict[str, Any]:
    """Build the ``run_metadata.json`` payload (pre-stamp).

    ``ended_at`` is left ``None``; ``execute_run`` patches it on the
    terminal transition via ``_patch_ended_at`` so the file stays
    self-describing even if the parent crashes between the patch and the
    directory rename (the staging dir is non-trustworthy by definition
    until ``promote_run`` / ``fail_run``).
    """
    meta = read_event_metadata(event_key, base_dir=base_dir)
    scenario_path = scenario_dir(event_key, scenario, base_dir=base_dir)
    return {
        "run_id": run_id,
        "event_key": event_key,
        "scenario": scenario,
        "cohort_age_group": age,
        "cohort_gender": gender,
        "event_name": meta.event_name,
        "series_id": meta.series_id,
        "started_at": started_at,
        "ended_at": None,
        "simulation_runs": 1,
        "model_version_pin": extras.get("model_version_pin"),
        "ranking_snapshot_date": extras.get("ranking_snapshot_date"),
        "capped_gd_limit": extras.get("capped_gd_limit"),
        "balance_score_weights": extras.get("balance_score_weights"),
        "git_repo_sha": _git_repo_sha(),
        "hashes": {
            "registry": _file_sha256(scenario_path / "event_team_registry.csv"),
            "structure": _file_sha256(scenario_path / "group_structure_summary.csv"),
            "constraints": _file_sha256(scenario_path / "constraints.json"),
        },
        "cli_args": list(cli_args),
    }


def _patch_ended_at(metadata_path: Path, ts: str) -> None:
    """Atomically patch ``ended_at`` into an existing ``run_metadata.json``."""
    payload = read_json(metadata_path)
    payload["ended_at"] = ts
    write_json(metadata_path, payload)


def _assert_summary_present(staging_dir: Path) -> None:
    """Confirm the cohort CLI wrote ``summary.json`` before downstream readers run.

    Shell 07's ``compute.py`` reads ``summary.json`` directly — no flat
    ``standings_actual.csv`` / ``standings_optimized.csv`` is needed here
    (the cohort summary already carries divisions/matches/standings nested
    under ``optimized_projection.simulated_schedule``). A missing summary
    is routed to ``fail_run`` by the parent's try/except.
    """
    if not (staging_dir / "summary.json").exists():
        raise RuntimeError(f"cohort CLI did not produce summary.json at {staging_dir}")


def override_in_cohort(
    record: dict[str, Any],
    age: str,
    gender: str,
    registry_by_pid: dict[str, Any],
) -> bool:
    """Return True if ``record`` is an override scoped to the requested cohort.

    For ``manual_add`` overrides the cohort lives on the override's own
    ``after.cohort_age_group`` / ``after.cohort_gender`` fields. For other
    types we look up the registry entry by ``team_ref`` (provider id) and
    compare its ``event_age_group`` / ``event_gender``.
    """
    type_ = record.get("type")
    after = record.get("after") or {}
    team_ref = str(record.get("team_ref") or "")
    if type_ == "manual_add":
        return str(after.get("cohort_age_group") or "") == age and str(after.get("cohort_gender") or "") == gender
    if type_ == "recompute_medians":
        # Cohort-scoped overrides use ``team_ref = f"{age}_{gender}"`` (cf.
        # tournament_intake._recompute_medians_inner).
        return team_ref == f"{age}_{gender}"
    entry = registry_by_pid.get(team_ref)
    if entry is None:
        return False
    return entry.event_age_group == age and entry.event_gender == gender


def _write_run_overrides_audit(
    event_key: str,
    scenario: str,
    run_id: str,
    age: str,
    gender: str,
    started_at: str,
    staging_dir: Path,
    *,
    base_dir: Path | str,
) -> None:
    """Append cohort-scoped overrides to ``run_overrides_audit.jsonl``.

    Empty (or absent) audit JSONL is fine when the cohort has zero
    overrides — Shell 08 tolerates either. Per-record fields beyond the
    source override: ``run_id``, ``applied_at`` (= ``started_at``),
    ``delta_balance_score`` (always None in v1; Shell 08's audit panel may
    lazy-compute on demand).
    """
    overrides = load_overrides(event_key, scenario, base_dir=base_dir)
    registry = read_registry(event_key, scenario, base_dir=base_dir)
    registry_by_pid: dict[str, Any] = {}
    for entry in registry:
        pid = registry_provider_id(entry)
        if pid:
            registry_by_pid[pid] = entry

    audit_path = staging_dir / "run_overrides_audit.jsonl"
    for record in overrides:
        if not override_in_cohort(record, age, gender, registry_by_pid):
            continue
        audit_entry = {
            **record,
            "run_id": run_id,
            "applied_at": started_at,
            "delta_balance_score": None,
        }
        append_jsonl(audit_path, stamp_schema_version(audit_entry))


_FALLBACK_MARKERS: tuple[tuple[str, str], ...] = (
    (": no as-of point-in-time snapshot", "future_snapshot_fallback"),
    (": no point-in-time snapshots found", "synthetic_snapshot_fallback"),
)


def _write_fallbacks_jsonl(staging_dir: Path) -> None:
    """Translate cohort-CLI ``notes`` into per-team ``fallbacks.jsonl`` rows.

    Suffix-partition (not first-colon split) so team names with embedded
    colons (e.g. ``"FC Tucson: ECNL Boys 2014"``) don't get misattributed.
    A defensive count-mismatch sentinel goes to a separate
    ``parser_warnings.jsonl`` so ``fallbacks.jsonl`` stays semantically
    clean (every row a real per-team fallback Shell 07 can render).
    """
    summary = read_json(staging_dir / "summary.json")
    counts = summary.get("predictor", {}).get("snapshot_resolution_counts", {}) or {}
    notes = summary.get("notes", []) or []

    parsed_count = 0
    for note in notes:
        if not isinstance(note, str):
            continue
        for marker, kind in _FALLBACK_MARKERS:
            head, sep, _tail = note.partition(marker)
            if sep:
                append_jsonl(
                    staging_dir / "fallbacks.jsonl",
                    stamp_schema_version(
                        {
                            "team_name": head,
                            "fallback_kind": kind,
                            "raw_note": note,
                        }
                    ),
                )
                parsed_count += 1
                break

    expected_fallback_count = int(counts.get("future_snapshot_fallback", 0) or 0) + int(
        counts.get("synthetic_snapshot_fallback", 0) or 0
    )
    if expected_fallback_count > parsed_count:
        append_jsonl(
            staging_dir / "parser_warnings.jsonl",
            stamp_schema_version(
                {
                    "kind": "fallback_count_mismatch",
                    "counts": dict(counts),
                    "parsed_records": parsed_count,
                    "raw_notes": list(notes),
                }
            ),
        )


def _stream_subprocess(
    proc: subprocess.Popen,
    staging_dir: Path,
    on_event: Callable[[ProgressEvent], None],
) -> tuple[list[str], threading.Thread]:
    """Drain stdout (structured + buffered) and stderr (background thread).

    Returns ``(stderr_lines, stderr_thread)`` so the caller can join the
    drain thread after ``proc.wait()`` and tail stderr into the failure
    message. Stdout is appended to ``cli_stdout.log`` verbatim while
    structured PHASE/PROGRESS markers also land in ``progress.jsonl``.
    Non-marker lines are buffered and flushed to ``on_event`` on each
    phase transition (UI throttling — keeps render cost bounded).
    """
    stderr_lines: list[str] = []

    def _drain_stderr() -> None:
        if proc.stderr is None:
            return
        for raw in iter(proc.stderr.readline, ""):
            line = raw.rstrip("\n")
            stderr_lines.append(line)
            with open(staging_dir / "cli_stderr.log", "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    buffered_raw_lines: list[str] = []
    current_phase: str | None = None
    with open(staging_dir / "cli_stdout.log", "a", encoding="utf-8") as cli_stdout_log:
        if proc.stdout is None:
            return stderr_lines, stderr_thread
        for raw in iter(proc.stdout.readline, ""):
            line = raw.rstrip("\n")
            cli_stdout_log.write(line + "\n")
            cli_stdout_log.flush()
            ev = _parse_progress_line(line, current_phase)
            if ev.phase is not None or ev.percent is not None:
                append_jsonl(staging_dir / "progress.jsonl", stamp_schema_version(_progress_record(ev)))
            if ev.phase is not None and ev.phase != current_phase:
                if buffered_raw_lines:
                    # Flush buffered plain-text with phase=None so the handler
                    # renders it as a log block rather than re-interpreting it
                    # as a status-label update.
                    on_event(
                        ProgressEvent(
                            phase=None,
                            percent=None,
                            raw_line="\n".join(buffered_raw_lines),
                            ts=utc_now_iso(),
                        )
                    )
                    buffered_raw_lines.clear()
                current_phase = ev.phase
                on_event(ev)
            elif ev.percent is not None:
                on_event(ev)
            else:
                buffered_raw_lines.append(line)
        if buffered_raw_lines:
            on_event(
                ProgressEvent(
                    phase=None,
                    percent=None,
                    raw_line="\n".join(buffered_raw_lines),
                    ts=utc_now_iso(),
                )
            )

    return stderr_lines, stderr_thread


def _finalize_failure(
    event_key: str,
    scenario: str,
    run_id: str,
    staging_dir: Path,
    error_msg: str,
    *,
    base_dir: Path | str,
) -> RunOutcome:
    """Patch ``ended_at``, rename to ``.failed/``, return the failure outcome.

    Resilient to the early-failure case where ``run_metadata.json`` was not
    yet written (e.g. ``_build_cohort_request_payload`` raised after
    ``create_staging_run``): the patch is best-effort.
    """
    metadata_path = staging_dir / "run_metadata.json"
    if metadata_path.exists():
        _patch_ended_at(metadata_path, utc_now_iso())
    failed_dir = fail_run(event_key, scenario, run_id, error=error_msg, base_dir=base_dir)
    return RunOutcome(state="failed", run_dir=failed_dir, error=error_msg)


def execute_run(
    event_key: str,
    scenario: str,
    age: str,
    gender: str,
    *,
    base_dir: Path | str = "reports",
    on_event: Callable[[ProgressEvent], None] = _noop_on_event,
) -> RunOutcome:
    """Run one cohort backtest synchronously, end-to-end.

    Acquires the per-scenario lock (2.0s timeout, matching the existing
    Streamlit flows at ``tournament_intake.py:1706/1835/1861``), creates
    the staging dir, writes ``run_metadata.json`` BEFORE Popen so even a
    spawn failure leaves the staging dir self-describing, streams the
    cohort CLI's stdout (structured PHASE/PROGRESS → ``progress.jsonl`` +
    ``on_event``; raw text → ``cli_stdout.log``) while a background thread
    drains stderr to ``cli_stderr.log``, then either ``promote_run`` (zero
    exit + post-run translation succeeds) or ``fail_run``.

    Lock contention surfaces as ``ScenarioLockError``; the caller catches
    it and renders ``st.error``. Any unhandled exception inside the lock
    still releases it via the context manager's ``finally``.
    """
    with acquire_scenario_lock(event_key, scenario, base_dir=base_dir, timeout=2.0):
        run_id = generate_run_id(age, gender)
        meta = read_event_metadata(event_key, base_dir=base_dir)
        extras = meta.extras or {}

        staging_dir = create_staging_run(event_key, scenario, run_id, base_dir=base_dir)

        # Anything between create_staging_run and Popen-spawn that raises
        # leaves a stale .tmp dir without a marker file. Convert to a
        # _finalize_failure call so the failure shows up as a normal failed
        # run rather than a silent orphan that needs the 24h cleanup sweep.
        try:
            (
                payload,
                division_routing_fallbacks,
                division_routing_stale_assignments,
            ) = _build_cohort_request_payload(
                event_key,
                scenario,
                age,
                gender,
                base_dir=base_dir,
                extras=extras,
            )
            cli_args, request_path = _build_cli_args(staging_dir, extras=extras)
            write_json(request_path, payload)

            started_at = utc_now_iso()
            metadata = stamp_schema_version(
                _collect_run_metadata(
                    event_key,
                    scenario,
                    age,
                    gender,
                    run_id,
                    base_dir=base_dir,
                    started_at=started_at,
                    cli_args=cli_args,
                    extras=extras,
                )
            )
            write_json(staging_dir / "run_metadata.json", metadata)

            if division_routing_fallbacks:
                append_jsonl(
                    staging_dir / "parser_warnings.jsonl",
                    stamp_schema_version(
                        {
                            "kind": "division_routing_fallback",
                            "fallback_division": (
                                payload["divisions"][0]["actual_division_name"] if payload["divisions"] else ""
                            ),
                            "team_count": len(division_routing_fallbacks),
                            "team_names": division_routing_fallbacks,
                        }
                    ),
                )
            if division_routing_stale_assignments:
                # Stale-assignment teams may route to several different
                # divisions (each prefix-resolved individually), so a single
                # ``fallback_division`` field would be misleading here —
                # omit it and rely on ``team_names`` for cleanup triage.
                append_jsonl(
                    staging_dir / "parser_warnings.jsonl",
                    stamp_schema_version(
                        {
                            "kind": "division_routing_stale_assignment",
                            "team_count": len(division_routing_stale_assignments),
                            "team_names": division_routing_stale_assignments,
                        }
                    ),
                )

            startup_ev = ProgressEvent(
                phase="orchestrator-starting",
                percent=None,
                raw_line="orchestrator: spawning cohort CLI",
                ts=utc_now_iso(),
            )
            append_jsonl(staging_dir / "progress.jsonl", stamp_schema_version(_progress_record(startup_ev)))
            on_event(startup_ev)
        except Exception as exc:  # noqa: BLE001 — pre-Popen failures route through fail_run
            return _finalize_failure(
                event_key,
                scenario,
                run_id,
                staging_dir,
                f"orchestrator pre-spawn failure: {exc!r}",
                base_dir=base_dir,
            )

        proc = subprocess.Popen(
            [sys.executable, "scripts/backtest_tournament_cohort.py", *cli_args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=Path.cwd(),
            start_new_session=(sys.platform != "win32"),
        )

        stderr_lines, stderr_thread = _stream_subprocess(proc, staging_dir, on_event)
        proc.wait()
        stderr_thread.join(timeout=5.0)

        if proc.returncode != 0:
            error_msg = f"subprocess exit {proc.returncode}"
            if stderr_lines:
                error_msg += "\nstderr tail:\n" + "\n".join(stderr_lines[-20:])
            return _finalize_failure(event_key, scenario, run_id, staging_dir, error_msg, base_dir=base_dir)

        try:
            _assert_summary_present(staging_dir)
            _write_run_overrides_audit(
                event_key,
                scenario,
                run_id,
                age,
                gender,
                started_at,
                staging_dir,
                base_dir=base_dir,
            )
            _write_fallbacks_jsonl(staging_dir)
            _patch_ended_at(staging_dir / "run_metadata.json", utc_now_iso())
            final_dir = promote_run(event_key, scenario, run_id, base_dir=base_dir)
            return RunOutcome(state="completed", run_dir=final_dir)
        except Exception as exc:  # noqa: BLE001 — translate failure routes to fail_run
            return _finalize_failure(
                event_key,
                scenario,
                run_id,
                staging_dir,
                f"post-run translation failed: {exc!r}",
                base_dir=base_dir,
            )
