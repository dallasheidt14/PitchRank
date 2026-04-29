"""Unit tests for ``src.tournaments.run_orchestrator``.

Covers the synchronous per-cohort run flow: id generation, cli_args /
request payload helpers, run_metadata collection (with git + file
hashes), the Popen-streaming + state-machine path (promote vs. fail),
and the per-record helpers (overrides audit + fallbacks JSONL).

All tests use ``tmp_path`` as the storage root and monkeypatch
``subprocess.Popen`` so no real cohort CLI is invoked.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from src.tournaments import run_orchestrator
from src.tournaments.run_orchestrator import (
    _MODEL_VERSION_ARTIFACT_MAP,
    ProgressEvent,
    _build_cli_args,
    _build_cohort_request_payload,
    _cleanup_orphan_staging_dirs,
    _collect_run_metadata,
    _parse_progress_line,
    _write_fallbacks_jsonl,
    _write_run_overrides_audit,
    execute_run,
    generate_run_id,
)
from src.tournaments.storage import (
    EventMetadata,
    RunStateError,
    TeamRegistryEntry,
    append_override,
    ensure_scenario,
    write_event_metadata,
    write_registry,
    write_structure,
)
from src.tournaments.storage._io import write_json
from src.tournaments.storage.event_key import scenario_dir
from src.tournaments.storage.structure import CohortStructure, DivisionStructure

EVENT_KEY = "gotsport__45224__2026"
SCENARIO = "default"


# ---------------------------------------------------------------------------
# fixture builders
# ---------------------------------------------------------------------------


def _bootstrap_event(
    base: Path,
    *,
    extras: dict[str, Any] | None = None,
    event_start: str = "2026-05-01",
) -> None:
    """Create a minimal scenario layout for executor tests."""
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=base)
    write_event_metadata(
        EVENT_KEY,
        EventMetadata(
            provider_code="gotsport",
            provider_event_id="45224",
            event_name="Phoenix Cup 2026",
            event_slug="phoenix-cup-2026",
            event_start_date=event_start,
            scrape_ts="2026-04-15T00:00:00+00:00",
            season_year=2026,
            series_id="phoenix-cup-2026",
            extras=extras or {},
        ),
        base_dir=base,
    )
    # Single cohort/single division so the request payload is well-defined.
    write_structure(
        EVENT_KEY,
        SCENARIO,
        [
            CohortStructure(
                age_group="u14",
                gender="Boys",
                divisions=(DivisionStructure(name="A", team_count=2, pool_sizes=(2,), advancement=None),),
            )
        ],
        base_dir=base,
    )
    write_registry(
        EVENT_KEY,
        SCENARIO,
        [
            TeamRegistryEntry(
                event_registration_id="reg-1",
                event_team_name="A Alpha",
                event_age_group="u14",
                event_gender="Boys",
                resolved_gotsport_provider_team_id="pid-1",
                resolved_team_id_master="tim-1",
                canonical_resolution_status="direct_provider_id",
                in_scope_u10_u19="True",
            ),
            TeamRegistryEntry(
                event_registration_id="reg-2",
                event_team_name="A Bravo",
                event_age_group="u14",
                event_gender="Boys",
                resolved_gotsport_provider_team_id="pid-2",
                resolved_team_id_master="tim-2",
                canonical_resolution_status="direct_provider_id",
                in_scope_u10_u19="True",
            ),
        ],
        base_dir=base,
    )


def _scenario(base: Path) -> Path:
    return scenario_dir(EVENT_KEY, SCENARIO, base_dir=base)


def _runs(base: Path) -> Path:
    return _scenario(base) / "runs"


# ---------------------------------------------------------------------------
# generate_run_id
# ---------------------------------------------------------------------------


def test_generate_run_id_format():
    rid = generate_run_id("u14", "Boys")
    assert re.match(r"^u\d+_(boys|girls)_\d{8}T\d{6}_[0-9a-f]{12}$", rid), rid


def test_generate_run_id_lowercases_gender():
    rid = generate_run_id("u14", "Girls")
    assert "_girls_" in rid


# ---------------------------------------------------------------------------
# _collect_run_metadata
# ---------------------------------------------------------------------------


def test_collect_run_metadata_includes_cohort_and_hashes(tmp_path: Path):
    _bootstrap_event(
        tmp_path,
        extras={
            "model_version_pin": "poisson_draw_gate_v1",
            "ranking_snapshot_date": "2026-04-30",
            "capped_gd_limit": 3,
            "balance_score_weights": {"preset_id": "default"},
        },
    )
    # Constraints file presence drives one of the SHA hashes
    write_json(_scenario(tmp_path) / "constraints.json", {"foo": "bar"})

    metadata = _collect_run_metadata(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        "run_x",
        base_dir=tmp_path,
        started_at="2026-04-30T12:00:00+00:00",
        cli_args=["--input", "x.json"],
        extras={
            "model_version_pin": "poisson_draw_gate_v1",
            "ranking_snapshot_date": "2026-04-30",
            "capped_gd_limit": 3,
            "balance_score_weights": {"preset_id": "default"},
        },
    )

    assert metadata["cohort_age_group"] == "u14"
    assert metadata["cohort_gender"] == "Boys"
    assert metadata["event_name"] == "Phoenix Cup 2026"
    assert metadata["model_version_pin"] == "poisson_draw_gate_v1"
    assert metadata["simulation_runs"] == 1
    assert metadata["ended_at"] is None
    assert metadata["cli_args"] == ["--input", "x.json"]
    # SHA-256 hex digest is 64 chars
    assert metadata["hashes"]["registry"] is not None
    assert len(metadata["hashes"]["registry"]) == 64
    assert metadata["hashes"]["structure"] is not None
    assert metadata["hashes"]["constraints"] is not None


def test_collect_run_metadata_handles_missing_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _bootstrap_event(tmp_path)

    def _fake_git_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=args, returncode=128, stdout="", stderr="not a repo")

    monkeypatch.setattr(run_orchestrator.subprocess, "run", _fake_git_run)

    metadata = _collect_run_metadata(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        "run_x",
        base_dir=tmp_path,
        started_at="2026-04-30T12:00:00+00:00",
        cli_args=[],
        extras={},
    )
    assert metadata["git_repo_sha"] == ""


# ---------------------------------------------------------------------------
# _build_cli_args
# ---------------------------------------------------------------------------


def test_build_cli_args_resolves_known_model_pin(tmp_path: Path):
    assert (
        _MODEL_VERSION_ARTIFACT_MAP["poisson_draw_gate_v1"]
        == "models/point_in_time_tournament_margin_postsnapshot_poisson_draw_gate_v1/point_in_time_match_model.pkl"
    )
    cli_args, request_path = _build_cli_args(tmp_path / "stage", extras={})
    assert request_path == tmp_path / "stage" / "request.json"
    assert "--point-in-time-model-artifact" in cli_args
    artifact_idx = cli_args.index("--point-in-time-model-artifact") + 1
    assert cli_args[artifact_idx].endswith("point_in_time_match_model.pkl")


def test_build_cli_args_raises_on_unknown_model_pin(tmp_path: Path):
    with pytest.raises(ValueError, match="unknown model_version_pin"):
        _build_cli_args(tmp_path / "stage", extras={"model_version_pin": "future_v9"})


# ---------------------------------------------------------------------------
# _build_cohort_request_payload
# ---------------------------------------------------------------------------


def test_build_cohort_request_payload_includes_prediction_date_when_extras_set(tmp_path: Path):
    _bootstrap_event(tmp_path, extras={"ranking_snapshot_date": "2026-04-30"})
    payload, fallbacks, stale = _build_cohort_request_payload(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
        extras={"ranking_snapshot_date": "2026-04-30"},
    )
    assert payload["prediction_date"] == "2026-04-30"
    assert payload["age_group"] == "u14"
    assert payload["gender"] == "boys"
    assert len(payload["entrants"]) == 2
    # Fixture team names "A Alpha" / "A Bravo" both start with division "A"
    # so the resolver returns ``source="prefix"`` with no fallbacks.
    assert fallbacks == []
    assert stale == []


def test_build_cohort_request_payload_omits_prediction_date_when_absent(tmp_path: Path):
    _bootstrap_event(tmp_path)
    payload, _fallbacks, _stale = _build_cohort_request_payload(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
        extras={},
    )
    assert "prediction_date" not in payload


def _bootstrap_event_metadata_only(base: Path) -> None:
    """Write only event metadata + ``ensure_scenario``. Each test then
    writes its own ``write_structure`` so the structure shape (one or
    two divisions) lives next to the test that depends on it."""
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=base)
    write_event_metadata(
        EVENT_KEY,
        EventMetadata(
            provider_code="gotsport",
            provider_event_id="45224",
            event_name="Phoenix Cup 2026",
            event_slug="phoenix-cup-2026",
            event_start_date="2026-05-01",
            scrape_ts="2026-04-15T00:00:00+00:00",
            season_year=2026,
            series_id="phoenix-cup-2026",
        ),
        base_dir=base,
    )


def _two_division_structure() -> CohortStructure:
    return CohortStructure(
        age_group="u14",
        gender="Boys",
        divisions=(
            DivisionStructure(name="BU14 Premier", team_count=1, pool_sizes=(1,)),
            DivisionStructure(name="BU14 Champions", team_count=1, pool_sizes=(1,)),
        ),
    )


def _single_premier_division_structure() -> CohortStructure:
    return CohortStructure(
        age_group="u14",
        gender="Boys",
        divisions=(DivisionStructure(name="BU14 Premier", team_count=2, pool_sizes=(2,)),),
    )


def test_build_cohort_request_payload_explicit_assignment_wins_over_prefix(tmp_path: Path):
    _bootstrap_event_metadata_only(tmp_path)
    write_structure(EVENT_KEY, SCENARIO, [_two_division_structure()], base_dir=tmp_path)
    write_registry(
        EVENT_KEY,
        SCENARIO,
        [
            TeamRegistryEntry(
                event_registration_id="reg-1",
                event_team_name="BU14 Premier Phoenix Rising",
                event_age_group="u14",
                event_gender="Boys",
                resolved_gotsport_provider_team_id="pid-1",
                resolved_team_id_master="tim-1",
            ),
        ],
        base_dir=tmp_path,
    )
    append_override(
        EVENT_KEY,
        SCENARIO,
        {
            "ts": "2026-04-20T00:00:00+00:00",
            "actor": "ops@example.com",
            "scope": "team",
            "type": "assign_division",
            "team_ref": "pid-1",
            "before": {},
            "after": {"assigned_division_name": "BU14 Champions"},
            "reason": "operator override",
        },
        base_dir=tmp_path,
    )
    payload, fallbacks, stale = _build_cohort_request_payload(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
        extras={},
    )
    assert fallbacks == []
    assert stale == []
    # Lookup the entrant's actual_division_name (the BU14-stripped form).
    assert len(payload["entrants"]) == 1
    assert payload["entrants"][0]["actual_division_name"] == "Champions"


def test_build_cohort_request_payload_no_override_no_prefix_match_collects_fallbacks(tmp_path: Path):
    _bootstrap_event_metadata_only(tmp_path)
    write_structure(EVENT_KEY, SCENARIO, [_single_premier_division_structure()], base_dir=tmp_path)
    write_registry(
        EVENT_KEY,
        SCENARIO,
        [
            TeamRegistryEntry(
                event_registration_id="reg-1",
                event_team_name="Phoenix Rising",
                event_age_group="u14",
                event_gender="Boys",
                resolved_gotsport_provider_team_id="pid-1",
                resolved_team_id_master="tim-1",
            ),
            TeamRegistryEntry(
                event_registration_id="reg-2",
                event_team_name="Real Madrid",
                event_age_group="u14",
                event_gender="Boys",
                resolved_gotsport_provider_team_id="pid-2",
                resolved_team_id_master="tim-2",
            ),
        ],
        base_dir=tmp_path,
    )
    payload, fallbacks, stale = _build_cohort_request_payload(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
        extras={},
    )
    assert fallbacks == ["Phoenix Rising", "Real Madrid"]
    assert stale == []
    # Both teams still land in the only division (legacy fallback).
    assert len(payload["entrants"]) == 2


def test_build_cohort_request_payload_stale_assignment_falls_through_to_prefix(tmp_path: Path):
    _bootstrap_event_metadata_only(tmp_path)
    # Single-division structure: assignment to "BU14 Removed" is stale.
    write_structure(EVENT_KEY, SCENARIO, [_single_premier_division_structure()], base_dir=tmp_path)
    write_registry(
        EVENT_KEY,
        SCENARIO,
        [
            TeamRegistryEntry(
                event_registration_id="reg-1",
                event_team_name="BU14 Premier Phoenix Rising",
                event_age_group="u14",
                event_gender="Boys",
                resolved_gotsport_provider_team_id="pid-1",
                resolved_team_id_master="tim-1",
            ),
        ],
        base_dir=tmp_path,
    )
    append_override(
        EVENT_KEY,
        SCENARIO,
        {
            "ts": "2026-04-20T00:00:00+00:00",
            "actor": "ops@example.com",
            "scope": "team",
            "type": "assign_division",
            "team_ref": "pid-1",
            "before": {},
            "after": {"assigned_division_name": "BU14 Removed"},
            "reason": "stale after rename",
        },
        base_dir=tmp_path,
    )
    payload, fallbacks, stale = _build_cohort_request_payload(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
        extras={},
    )
    assert fallbacks == []
    assert stale == ["BU14 Premier Phoenix Rising"]
    # Team still routed via prefix-resolved name; the entrant's actual_division_name
    # is the BU14-stripped "Premier".
    assert len(payload["entrants"]) == 1
    assert payload["entrants"][0]["actual_division_name"] == "Premier"


# ---------------------------------------------------------------------------
# _parse_progress_line — exercises percent computation + phase carry
# ---------------------------------------------------------------------------


def test_parse_progress_line_phase_resets_phase():
    ev = _parse_progress_line("PHASE: writing-summary", current_phase="resolving-snapshots")
    assert ev.phase == "writing-summary"
    assert ev.percent is None


def test_parse_progress_line_progress_carries_phase_and_computes_percent():
    ev = _parse_progress_line("PROGRESS: snapshots 2/5", current_phase="resolving-snapshots")
    assert ev.phase == "resolving-snapshots"
    assert ev.percent == 40


def test_parse_progress_line_plain_text_returns_no_phase_no_percent():
    ev = _parse_progress_line("plain log line", current_phase="resolving-snapshots")
    assert ev.phase is None
    assert ev.percent is None
    assert ev.raw_line == "plain log line"


# ---------------------------------------------------------------------------
# execute_run — Popen plumbing
# ---------------------------------------------------------------------------


class _FakePopen:
    """Stand-in for ``subprocess.Popen`` used by the orchestrator's run loop.

    Designed to coexist with stray ``subprocess.run(["git", ...])`` calls
    inside ``_git_repo_sha`` — those land here too because monkeypatching
    ``run_orchestrator.subprocess.Popen`` also intercepts ``subprocess.run``
    (which uses ``Popen`` internally). Unrecognized commands return empty
    streams + zero exit so the git probe stays well-behaved.

    Supports the context-manager protocol because ``subprocess.run``
    does ``with Popen(...) as process``.
    """

    def __init__(
        self,
        cmd: list[str],
        *,
        stdout_lines: list[str],
        stderr_lines: list[str] | None = None,
        returncode: int = 0,
        write_summary: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._cmd = cmd
        is_cohort_cli = any("backtest_tournament_cohort" in part for part in cmd)
        if is_cohort_cli:
            self.stdout = io.StringIO("".join(line if line.endswith("\n") else line + "\n" for line in stdout_lines))
            self.stderr = io.StringIO(
                "".join(line if line.endswith("\n") else line + "\n" for line in (stderr_lines or []))
            )
            self.returncode = returncode
            if write_summary is not None and "--output-dir" in cmd:
                output_dir = Path(cmd[cmd.index("--output-dir") + 1])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "summary.json").write_text(json.dumps(write_summary), encoding="utf-8")
        else:
            # Non-cohort invocations (e.g. ``git rev-parse HEAD``) — quiet success.
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("")
            self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def poll(self) -> int:
        return self.returncode

    def communicate(self, input: Any = None, timeout: float | None = None) -> tuple[str, str]:
        return self.stdout.read(), self.stderr.read()

    def kill(self) -> None:
        return None

    def __enter__(self) -> "_FakePopen":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


def _install_fake_popen(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdout_lines: list[str],
    stderr_lines: list[str] | None = None,
    returncode: int = 0,
    write_summary: dict[str, Any] | None = None,
    pre_check: list[Any] | None = None,
) -> None:
    """Replace ``subprocess.Popen`` *only* for the cohort CLI invocation.

    Also stubs ``_git_repo_sha`` to ``""`` so the orchestrator's git probe
    doesn't escape the sandbox via the real ``subprocess.run`` — which would
    otherwise be re-routed through this monkeypatch and crash on the first
    Popen-API contract that ``_FakePopen`` doesn't fully implement.
    """
    monkeypatch.setattr(run_orchestrator, "_git_repo_sha", lambda: "")

    def _factory(cmd: list[str], **kwargs: Any) -> _FakePopen:
        if pre_check is not None:
            pre_check.append(cmd)
        return _FakePopen(
            cmd,
            stdout_lines=stdout_lines,
            stderr_lines=stderr_lines,
            returncode=returncode,
            write_summary=write_summary,
        )

    monkeypatch.setattr(run_orchestrator.subprocess, "Popen", _factory)


def _minimal_summary() -> dict[str, Any]:
    return {
        "event_name": "Phoenix Cup 2026",
        "cohort": {"age_group": "u14", "gender": "Boys"},
        "predictor": {
            "snapshot_resolution_counts": {
                "as_of": 2,
                "future_snapshot_fallback": 0,
                "synthetic_snapshot_fallback": 0,
            }
        },
        "notes": [],
    }


def test_execute_run_writes_metadata_before_popen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _bootstrap_event(tmp_path)

    metadata_present_at_popen: list[bool] = []
    monkeypatch.setattr(run_orchestrator, "_git_repo_sha", lambda: "")

    def _factory(cmd: list[str], **kwargs: Any) -> _FakePopen:
        if any("backtest_tournament_cohort" in part for part in cmd):
            output_dir = Path(cmd[cmd.index("--output-dir") + 1])
            metadata_present_at_popen.append((output_dir / "run_metadata.json").exists())
        return _FakePopen(
            cmd,
            stdout_lines=["PHASE: writing-summary\n"],
            returncode=0,
            write_summary=_minimal_summary(),
        )

    monkeypatch.setattr(run_orchestrator.subprocess, "Popen", _factory)

    outcome = execute_run(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
    )
    assert outcome.state == "completed"
    assert metadata_present_at_popen == [True]


def test_execute_run_streams_phase_progress_to_callback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _bootstrap_event(tmp_path)
    _install_fake_popen(
        monkeypatch,
        stdout_lines=[
            "PHASE: resolving-snapshots\n",
            "PROGRESS: snapshots 2/5\n",
            "stray log\n",
            "PHASE: writing-summary\n",
        ],
        returncode=0,
        write_summary=_minimal_summary(),
    )

    events: list[ProgressEvent] = []
    outcome = execute_run(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
        on_event=events.append,
    )
    assert outcome.state == "completed"

    # First synthetic event from the orchestrator
    assert events[0].phase == "orchestrator-starting"

    phases = [(ev.phase, ev.percent) for ev in events if ev.phase is not None]
    assert ("resolving-snapshots", None) in phases
    # PROGRESS preserves current_phase + computes percent
    assert ("resolving-snapshots", 40) in phases
    # writing-summary phase eventually fires
    assert any(p == "writing-summary" for p, _ in phases)


def test_execute_run_progress_jsonl_contains_only_structured_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _bootstrap_event(tmp_path)
    _install_fake_popen(
        monkeypatch,
        stdout_lines=[
            "PHASE: resolving-snapshots\n",
            "PROGRESS: snapshots 2/5\n",
            "stray log\n",
            "PHASE: writing-summary\n",
        ],
        returncode=0,
        write_summary=_minimal_summary(),
    )

    outcome = execute_run(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
    )
    assert outcome.state == "completed"

    progress_records = [
        json.loads(line)
        for line in (outcome.run_dir / "progress.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # synthetic + 2x PHASE + 1x PROGRESS = 4 (no plain-text noise)
    assert len(progress_records) == 4
    assert all(r["schema_version"] == 1 for r in progress_records)
    assert {r.get("phase") for r in progress_records} >= {
        "orchestrator-starting",
        "resolving-snapshots",
        "writing-summary",
    }

    cli_stdout = (outcome.run_dir / "cli_stdout.log").read_text(encoding="utf-8")
    assert "PHASE: resolving-snapshots" in cli_stdout
    assert "stray log" in cli_stdout


def test_execute_run_separates_stderr_into_log_and_error_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _bootstrap_event(tmp_path)
    _install_fake_popen(
        monkeypatch,
        stdout_lines=[],
        stderr_lines=["Traceback (most recent call last):\n", "ValueError: synthetic\n"],
        returncode=1,
    )

    outcome = execute_run(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
    )
    assert outcome.state == "failed"
    assert outcome.error and "subprocess exit 1" in outcome.error
    assert "stderr tail:" in (outcome.error or "")
    assert "synthetic" in (outcome.error or "")
    cli_stderr = (outcome.run_dir / "cli_stderr.log").read_text(encoding="utf-8")
    assert "Traceback" in cli_stderr
    assert "ValueError: synthetic" in cli_stderr


def test_execute_run_promotes_on_zero_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _bootstrap_event(tmp_path)
    _install_fake_popen(
        monkeypatch,
        stdout_lines=["PHASE: writing-summary\n"],
        returncode=0,
        write_summary=_minimal_summary(),
    )

    outcome = execute_run(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
    )
    assert outcome.state == "completed"
    assert outcome.run_dir.name.endswith("_" + outcome.run_dir.name.split("_")[-1])
    assert (outcome.run_dir / "done.json").exists()
    # staging dir gone
    assert not (outcome.run_dir.parent / (outcome.run_dir.name + ".tmp")).exists()


def test_execute_run_fails_on_nonzero_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _bootstrap_event(tmp_path)
    _install_fake_popen(
        monkeypatch,
        stdout_lines=[],
        returncode=1,
    )

    outcome = execute_run(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
    )
    assert outcome.state == "failed"
    assert outcome.run_dir.name.endswith(".failed")
    error_payload = json.loads((outcome.run_dir / "error.json").read_text(encoding="utf-8"))
    assert "subprocess exit 1" in error_payload["error"]


def test_execute_run_routes_translate_failure_to_fail_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _bootstrap_event(tmp_path)
    _install_fake_popen(
        monkeypatch,
        stdout_lines=["PHASE: writing-summary\n"],
        returncode=0,
        # NO summary written
    )

    outcome = execute_run(
        EVENT_KEY,
        SCENARIO,
        "u14",
        "Boys",
        base_dir=tmp_path,
    )
    assert outcome.state == "failed"
    assert outcome.run_dir.name.endswith(".failed")
    error_payload = json.loads((outcome.run_dir / "error.json").read_text(encoding="utf-8"))
    assert "post-run translation failed" in error_payload["error"]


def test_execute_run_collision_recovery_surfaces_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _bootstrap_event(tmp_path)
    monkeypatch.setattr(run_orchestrator.secrets, "token_hex", lambda n: "deadbeef" * (n // 4))

    # Pre-create the staging dir for the deterministic run_id so
    # create_staging_run raises RunStateError immediately.
    rid_first = generate_run_id("u14", "Boys")
    (_runs(tmp_path) / f"{rid_first}.tmp").mkdir(parents=True)

    with pytest.raises(RunStateError):
        execute_run(
            EVENT_KEY,
            SCENARIO,
            "u14",
            "Boys",
            base_dir=tmp_path,
        )


# ---------------------------------------------------------------------------
# _write_run_overrides_audit
# ---------------------------------------------------------------------------


def test_run_overrides_audit_filters_to_cohort(tmp_path: Path):
    _bootstrap_event(tmp_path)
    # A second cohort + entry for it
    write_registry(
        EVENT_KEY,
        SCENARIO,
        [
            TeamRegistryEntry(
                event_registration_id="reg-1",
                event_team_name="A Alpha",
                event_age_group="u14",
                event_gender="Boys",
                resolved_gotsport_provider_team_id="pid-1",
                resolved_team_id_master="tim-1",
            ),
            TeamRegistryEntry(
                event_registration_id="reg-3",
                event_team_name="B Charlie",
                event_age_group="u10",
                event_gender="Boys",
                resolved_gotsport_provider_team_id="pid-3",
                resolved_team_id_master="tim-3",
            ),
        ],
        base_dir=tmp_path,
    )

    append_override(
        EVENT_KEY,
        SCENARIO,
        {
            "ts": "2026-04-20T00:00:00+00:00",
            "actor": "ops@example.com",
            "scope": "team",
            "type": "accept_match",
            "team_ref": "pid-1",
            "before": {},
            "after": {"team_id_master": "tim-1"},
            "reason": "matches u14 cohort",
        },
        base_dir=tmp_path,
    )
    append_override(
        EVENT_KEY,
        SCENARIO,
        {
            "ts": "2026-04-20T00:01:00+00:00",
            "actor": "ops@example.com",
            "scope": "team",
            "type": "accept_match",
            "team_ref": "pid-3",
            "before": {},
            "after": {"team_id_master": "tim-3"},
            "reason": "matches u10 cohort",
        },
        base_dir=tmp_path,
    )

    staging = tmp_path / "stage"
    staging.mkdir()
    _write_run_overrides_audit(
        EVENT_KEY,
        SCENARIO,
        "run_x",
        "u14",
        "Boys",
        "2026-04-21T00:00:00+00:00",
        staging,
        base_dir=tmp_path,
    )

    audit_lines = [
        json.loads(line)
        for line in (staging / "run_overrides_audit.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(audit_lines) == 1
    assert audit_lines[0]["team_ref"] == "pid-1"
    assert audit_lines[0]["run_id"] == "run_x"
    assert audit_lines[0]["delta_balance_score"] is None


# ---------------------------------------------------------------------------
# _write_fallbacks_jsonl
# ---------------------------------------------------------------------------


def test_fallbacks_jsonl_uses_predictor_key_and_top_level_notes(tmp_path: Path):
    staging = tmp_path / "stage"
    staging.mkdir()
    summary = {
        "predictor": {
            "snapshot_resolution_counts": {
                "as_of": 1,
                "future_snapshot_fallback": 1,
                "synthetic_snapshot_fallback": 1,
            }
        },
        "notes": [
            "Alpha: no as-of point-in-time snapshot on 2026-04-30; using earliest later snapshot from 2026-05-02",
            "Bravo: no point-in-time snapshots found; using synthesized snapshot from current ranking inputs",
        ],
    }
    (staging / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    _write_fallbacks_jsonl(staging)
    rows = [
        json.loads(line)
        for line in (staging / "fallbacks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 2
    kinds = {row["fallback_kind"] for row in rows}
    assert kinds == {"future_snapshot_fallback", "synthetic_snapshot_fallback"}


def test_fallbacks_jsonl_handles_team_name_with_colon(tmp_path: Path):
    staging = tmp_path / "stage"
    staging.mkdir()
    summary = {
        "predictor": {
            "snapshot_resolution_counts": {
                "as_of": 0,
                "future_snapshot_fallback": 1,
                "synthetic_snapshot_fallback": 0,
            }
        },
        "notes": [
            "FC Tucson: ECNL Boys 2014: no as-of point-in-time snapshot on 2026-04-30; "
            "using earliest later snapshot from 2026-05-02"
        ],
    }
    (staging / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    _write_fallbacks_jsonl(staging)
    rows = [
        json.loads(line)
        for line in (staging / "fallbacks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["team_name"] == "FC Tucson: ECNL Boys 2014"
    assert rows[0]["fallback_kind"] == "future_snapshot_fallback"


def test_fallbacks_jsonl_emits_parser_warning_on_count_mismatch(tmp_path: Path):
    staging = tmp_path / "stage"
    staging.mkdir()
    # Counts claim two fallbacks, but only one note describes one — sentinel emits.
    summary = {
        "predictor": {
            "snapshot_resolution_counts": {
                "as_of": 0,
                "future_snapshot_fallback": 1,
                "synthetic_snapshot_fallback": 1,
            }
        },
        "notes": ["Alpha: no as-of point-in-time snapshot on 2026-04-30"],
    }
    (staging / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    _write_fallbacks_jsonl(staging)
    warnings = [
        json.loads(line)
        for line in (staging / "parser_warnings.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert warnings and warnings[0]["kind"] == "fallback_count_mismatch"
    assert warnings[0]["parsed_records"] == 1


# ---------------------------------------------------------------------------
# _cleanup_orphan_staging_dirs
# ---------------------------------------------------------------------------


def test_orphan_tmp_cleanup_removes_old_dirs(tmp_path: Path):
    _bootstrap_event(tmp_path)
    runs_root = _runs(tmp_path)
    runs_root.mkdir(exist_ok=True)
    old_dir = runs_root / "old.tmp"
    old_dir.mkdir()
    new_dir = runs_root / "new.tmp"
    new_dir.mkdir()

    cutoff = time.time() - 25 * 3600
    import os

    os.utime(old_dir, (cutoff, cutoff))

    _cleanup_orphan_staging_dirs(EVENT_KEY, SCENARIO, base_dir=tmp_path, max_age_hours=24)

    assert not old_dir.exists()
    assert new_dir.exists()


# ---------------------------------------------------------------------------
# override_in_cohort — manual_add and recompute_medians branches
# ---------------------------------------------------------------------------


def test_run_overrides_audit_includes_manual_add_for_this_cohort(tmp_path: Path):
    _bootstrap_event(tmp_path)
    append_override(
        EVENT_KEY,
        SCENARIO,
        {
            "ts": "2026-04-20T00:00:00+00:00",
            "actor": "ops@example.com",
            "scope": "team",
            "type": "manual_add",
            "team_ref": "manual_xyz",
            "before": {},
            "after": {
                "state": "external",
                "cohort_age_group": "u14",
                "cohort_gender": "Boys",
                "note": "Visiting Mexican team",
            },
            "reason": "manual add",
        },
        base_dir=tmp_path,
    )
    append_override(
        EVENT_KEY,
        SCENARIO,
        {
            "ts": "2026-04-20T00:01:00+00:00",
            "actor": "ops@example.com",
            "scope": "team",
            "type": "manual_add",
            "team_ref": "manual_other",
            "before": {},
            "after": {
                "state": "external",
                "cohort_age_group": "u10",
                "cohort_gender": "Boys",
            },
            "reason": "wrong cohort",
        },
        base_dir=tmp_path,
    )

    staging = tmp_path / "stage"
    staging.mkdir()
    _write_run_overrides_audit(
        EVENT_KEY,
        SCENARIO,
        "run_x",
        "u14",
        "Boys",
        "2026-04-21T00:00:00+00:00",
        staging,
        base_dir=tmp_path,
    )
    rows = [
        json.loads(line)
        for line in (staging / "run_overrides_audit.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["team_ref"] == "manual_xyz"


def test_run_overrides_audit_includes_recompute_medians_for_this_cohort(tmp_path: Path):
    _bootstrap_event(tmp_path)
    append_override(
        EVENT_KEY,
        SCENARIO,
        {
            "ts": "2026-04-20T00:00:00+00:00",
            "actor": "ops@example.com",
            "scope": "cohort",
            "type": "recompute_medians",
            "team_ref": "u14_Boys",
            "before": {"medians_by_division": {}},
            "after": {"medians_by_division": {"A": 0.55}},
            "reason": "ops recompute",
        },
        base_dir=tmp_path,
    )
    append_override(
        EVENT_KEY,
        SCENARIO,
        {
            "ts": "2026-04-20T00:01:00+00:00",
            "actor": "ops@example.com",
            "scope": "cohort",
            "type": "recompute_medians",
            "team_ref": "u10_Boys",
            "before": {"medians_by_division": {}},
            "after": {"medians_by_division": {"A": 0.50}},
            "reason": "other cohort",
        },
        base_dir=tmp_path,
    )

    staging = tmp_path / "stage"
    staging.mkdir()
    _write_run_overrides_audit(
        EVENT_KEY,
        SCENARIO,
        "run_x",
        "u14",
        "Boys",
        "2026-04-21T00:00:00+00:00",
        staging,
        base_dir=tmp_path,
    )
    rows = [
        json.loads(line)
        for line in (staging / "run_overrides_audit.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["team_ref"] == "u14_Boys"


# ---------------------------------------------------------------------------
# _parse_progress_line — malformed PROGRESS lines fall through cleanly
# ---------------------------------------------------------------------------


def test_parse_progress_line_malformed_progress_falls_to_plain_text():
    ev = _parse_progress_line("PROGRESS: incomplete-line", current_phase="resolving-snapshots")
    # Doesn't match the strict ^PROGRESS:\s+\S+\s+(\d+)/(\d+)\s*$ regex
    assert ev.phase is None
    assert ev.percent is None
    assert ev.raw_line == "PROGRESS: incomplete-line"


def test_parse_progress_line_zero_total_yields_none_percent():
    ev = _parse_progress_line("PROGRESS: snapshots 0/0", current_phase="resolving-snapshots")
    # Division-by-zero guard: percent is None, phase still carries
    assert ev.phase == "resolving-snapshots"
    assert ev.percent is None


# ---------------------------------------------------------------------------
# Division-routing fallback emits parser_warnings.jsonl
# ---------------------------------------------------------------------------


def test_execute_run_emits_division_routing_fallback_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Bootstrap with team names that DON'T start with division "A" → fallback fires
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    write_event_metadata(
        EVENT_KEY,
        EventMetadata(
            provider_code="gotsport",
            provider_event_id="45224",
            event_name="Phoenix Cup 2026",
            event_slug="phoenix-cup-2026",
            event_start_date="2026-05-01",
            scrape_ts="2026-04-15T00:00:00+00:00",
            season_year=2026,
        ),
        base_dir=tmp_path,
    )
    write_structure(
        EVENT_KEY,
        SCENARIO,
        [
            CohortStructure(
                age_group="u14",
                gender="Boys",
                divisions=(DivisionStructure(name="A", team_count=2, pool_sizes=(2,)),),
            )
        ],
        base_dir=tmp_path,
    )
    write_registry(
        EVENT_KEY,
        SCENARIO,
        [
            TeamRegistryEntry(
                event_registration_id="reg-1",
                event_team_name="Phoenix Rising 2012 Boys",
                event_age_group="u14",
                event_gender="Boys",
                resolved_gotsport_provider_team_id="pid-1",
                resolved_team_id_master="tim-1",
            ),
        ],
        base_dir=tmp_path,
    )
    _install_fake_popen(
        monkeypatch,
        stdout_lines=["PHASE: writing-summary\n"],
        returncode=0,
        write_summary=_minimal_summary(),
    )
    outcome = execute_run(EVENT_KEY, SCENARIO, "u14", "Boys", base_dir=tmp_path)
    assert outcome.state == "completed"
    warnings = [
        json.loads(line)
        for line in (outcome.run_dir / "parser_warnings.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(w["kind"] == "division_routing_fallback" for w in warnings)


# ---------------------------------------------------------------------------
# execute_run pre-Popen failure routes through fail_run (not orphaned .tmp)
# ---------------------------------------------------------------------------


def test_execute_run_pre_popen_failure_routes_to_fail_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _bootstrap_event(tmp_path, extras={"model_version_pin": "future_v9_unknown"})
    monkeypatch.setattr(run_orchestrator, "_git_repo_sha", lambda: "")
    outcome = execute_run(EVENT_KEY, SCENARIO, "u14", "Boys", base_dir=tmp_path)
    assert outcome.state == "failed"
    assert outcome.run_dir.name.endswith(".failed")
    assert outcome.error and "orchestrator pre-spawn failure" in outcome.error
    error_payload = json.loads((outcome.run_dir / "error.json").read_text(encoding="utf-8"))
    assert "unknown model_version_pin" in error_payload["error"]
