"""Run and read reviewed Backtest cohorts using local, atomic artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from src.tournaments.backtest_intake_state import BacktestSnapshot, effective_roster
from src.tournaments.backtest_link_store import EventLinks
from src.tournaments.backtest_request import BacktestRequestError, build_cohort_backtest_requests
from src.tournaments.backtest_scope import backtest_scope_roster
from src.tournaments.storage import (
    acquire_scenario_lock,
    create_staging_run,
    ensure_scenario,
    fail_run,
    list_runs,
    promote_run,
    run_dir,
    stamp_schema_version,
)
from src.tournaments.storage._io import append_jsonl, read_json, utc_now_iso, write_json
from src.tournaments.storage.event_key import parse_event_key

BACKTEST_SCENARIO = "reviewed-backtest"
DEFAULT_MODEL_ARTIFACT = (
    "models/point_in_time_tournament_margin_postsnapshot_poisson_draw_gate_v1/"
    "point_in_time_match_model.pkl"
)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROGRESS_RE = re.compile(r"^PROGRESS:\s+(\S+)\s+(\d+)/(\d+)\s*$")
_EXPORT_FILES = (
    "done.json",
    "comparison.html",
    "summary.json",
    "historical_inputs.json",
    "division_recommendations.json",
    "division_recommendations.csv",
    "request.json",
    "run_metadata.json",
    "progress.jsonl",
    "cli_stdout.log",
    "cli_stderr.log",
)


@dataclass(frozen=True)
class ReviewedCohortReadiness:
    age_group: str
    gender: str
    team_count: int
    division_count: int
    request: dict[str, Any] | None = None
    blockers: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.request is not None and not self.blockers


@dataclass(frozen=True)
class ReviewedRunProgress:
    phase: str | None
    completed: int | None
    total: int | None
    raw_line: str


@dataclass(frozen=True)
class ReviewedRunOutcome:
    state: Literal["completed", "failed"]
    run_dir: Path
    error: str | None = None


@dataclass(frozen=True)
class ReviewedRunRecord:
    run_id: str
    run_dir: Path
    age_group: str
    gender: str
    event_name: str
    ended_at: str
    state: Literal["completed", "failed"] = "completed"
    error: str | None = None


def _cohort_sort_key(item: tuple[str, str]) -> tuple[int, str, str]:
    age, gender = item
    match = re.search(r"u(\d+)", age.casefold())
    return (int(match.group(1)) if match else 999, gender.casefold(), age.casefold())


def capture_verification_blockers(snapshot: BacktestSnapshot) -> tuple[str, ...]:
    roster = snapshot.roster
    blockers: list[str] = []
    if snapshot.limit_groups is not None:
        blockers.append("The saved capture is a limited division check; save a whole-event capture")
    if not roster.is_complete:
        blockers.append("The saved whole-event capture is incomplete")
    verification = snapshot.verification
    if verification is None:
        blockers.append("Verify the published division list and save progress")
    elif not verification.stable:
        blockers.append("The published division list did not stabilize")
    elif set(verification.group_ids) != {division.group_id for division in roster.divisions}:
        blockers.append("The verified division list differs from the saved capture")
    return tuple(blockers)


def build_reviewed_cohort_readiness(
    snapshot: BacktestSnapshot,
    links: EventLinks,
) -> tuple[ReviewedCohortReadiness, ...]:
    """Evaluate each tournament cohort independently against strict evidence."""

    roster = backtest_scope_roster(effective_roster(snapshot))
    cohort_keys = sorted(
        {(division.age_group, division.gender) for division in roster.divisions},
        key=_cohort_sort_key,
    )
    global_blockers = capture_verification_blockers(snapshot)
    rows: list[ReviewedCohortReadiness] = []
    for age_group, gender in cohort_keys:
        cohort_divisions = tuple(
            division
            for division in roster.divisions
            if division.age_group == age_group and division.gender == gender
        )
        team_keys = {
            (team.registration_id or team.source_entry_key or f"{team.group_id}:{team.source_index}")
            for team in roster.teams
            if team.group_id in {division.group_id for division in cohort_divisions}
        }
        request: dict[str, Any] | None = None
        blockers = list(global_blockers)
        if not blockers:
            try:
                requests = build_cohort_backtest_requests(
                    snapshot,
                    event_links=links,
                    cohort_filter={(age_group, gender)},
                )
            except BacktestRequestError as exc:
                blockers.append(str(exc))
            else:
                if len(requests) != 1:
                    blockers.append("The saved cohort could not be converted into one backtest request")
                else:
                    request = requests[0]
        rows.append(
            ReviewedCohortReadiness(
                age_group=age_group,
                gender=gender,
                team_count=len(team_keys),
                division_count=len(cohort_divisions),
                request=request,
                blockers=tuple(blockers),
            )
        )
    return tuple(rows)


def resolve_model_artifact(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return path.resolve()


def default_model_artifact() -> str:
    return os.getenv("MATCHBALANCE_POINT_IN_TIME_MODEL_ARTIFACT", DEFAULT_MODEL_ARTIFACT)


def _safe_part(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized or "unknown"


def _run_id(age_group: str, gender: str) -> str:
    timestamp = utc_now_iso().replace(":", "").replace("-", "")[:15]
    return f"{_safe_part(age_group)}_{_safe_part(gender)}_{timestamp}_{secrets.token_hex(6)}"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def model_artifact_sha256(path: str | Path) -> str:
    """Return the stable identity used to select compatible cohort runs."""

    return _sha256_file(resolve_model_artifact(path))


def _finalize_failure(
    event_key: str,
    run_id: str,
    staging_dir: Path,
    error: str,
    *,
    base_dir: Path | str,
) -> ReviewedRunOutcome:
    metadata_path = staging_dir / "run_metadata.json"
    if metadata_path.exists():
        metadata = read_json(metadata_path)
        metadata["ended_at"] = utc_now_iso()
        metadata["state"] = "failed"
        write_json(metadata_path, metadata)
    failed = fail_run(
        event_key,
        BACKTEST_SCENARIO,
        run_id,
        error=error,
        base_dir=base_dir,
    )
    return ReviewedRunOutcome("failed", failed, error)


def _terminate_process(process: subprocess.Popen) -> None:
    """Best-effort terminate and reap for interrupted Streamlit runs."""

    try:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)
    except Exception:
        return


def _stream_process(
    process: subprocess.Popen,
    staging_dir: Path,
    on_progress: Callable[[ReviewedRunProgress], None],
) -> list[str]:
    stderr_lines: list[str] = []

    def drain_stderr() -> None:
        if process.stderr is None:
            return
        with open(staging_dir / "cli_stderr.log", "a", encoding="utf-8") as log:
            for raw in iter(process.stderr.readline, ""):
                line = raw.rstrip("\n")
                stderr_lines.append(line)
                log.write(line + "\n")
                log.flush()

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()
    try:
        if process.stdout is not None:
            with open(staging_dir / "cli_stdout.log", "a", encoding="utf-8") as log:
                for raw in iter(process.stdout.readline, ""):
                    line = raw.rstrip("\n")
                    log.write(line + "\n")
                    log.flush()
                    phase = line.removeprefix("PHASE: ") if line.startswith("PHASE: ") else None
                    progress_match = _PROGRESS_RE.match(line)
                    completed = int(progress_match.group(2)) if progress_match else None
                    total = int(progress_match.group(3)) if progress_match else None
                    event = ReviewedRunProgress(phase, completed, total, line)
                    if phase is not None or progress_match is not None:
                        append_jsonl(
                            staging_dir / "progress.jsonl",
                            stamp_schema_version(
                                {
                                    "phase": phase or progress_match.group(1),
                                    "completed": completed,
                                    "total": total,
                                    "raw_line": line,
                                    "ts": utc_now_iso(),
                                }
                            ),
                        )
                    on_progress(event)
        process.wait()
    except BaseException:
        _terminate_process(process)
        raise
    finally:
        stderr_thread.join(timeout=5.0)
    return stderr_lines


def execute_reviewed_run(
    event_key: str,
    request: dict[str, Any],
    *,
    model_artifact: str | Path,
    base_dir: Path | str = "reports",
    on_progress: Callable[[ReviewedRunProgress], None] = lambda _event: None,
) -> ReviewedRunOutcome:
    """Run one strict reviewed cohort; the subprocess only reads PitchRank data."""

    expected_event_id = parse_event_key(event_key)[1]
    if str(request.get("event_id") or "") != expected_event_id:
        raise ValueError("Backtest request event does not match its local event directory")
    age_group = str(request.get("age_group") or "")
    gender = str(request.get("gender") or "")
    if not age_group or not gender:
        raise ValueError("Backtest request needs a cohort age and gender")
    artifact = resolve_model_artifact(model_artifact)
    if not artifact.is_file():
        raise FileNotFoundError(f"Historical model artifact not found: {artifact}")

    ensure_scenario(event_key, BACKTEST_SCENARIO, base_dir=base_dir)
    with acquire_scenario_lock(event_key, BACKTEST_SCENARIO, base_dir=base_dir, timeout=2.0):
        run_id = _run_id(age_group, gender)
        staging_dir = create_staging_run(
            event_key,
            BACKTEST_SCENARIO,
            run_id,
            base_dir=base_dir,
        )
        request_path = staging_dir / "request.json"
        write_json(request_path, request)
        command = [
            sys.executable,
            str(_REPO_ROOT / "scripts" / "backtest_tournament_cohort.py"),
            "--input",
            str(request_path),
            "--output-dir",
            str(staging_dir),
            "--predictor-source",
            "point_in_time",
            "--point-in-time-model-artifact",
            str(artifact),
            "--point-in-time-probability-strategy",
            "poisson_draw_gate",
            "--history-lookback-days",
            "365",
            "--snapshot-buffer-days",
            "30",
        ]
        started_at = utc_now_iso()
        request_bytes = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        metadata = stamp_schema_version(
            {
                "run_id": run_id,
                "event_key": event_key,
                "scenario": BACKTEST_SCENARIO,
                "event_name": str(request.get("event_name") or ""),
                "cohort_age_group": age_group,
                "cohort_gender": gender,
                "source_capture_generation": str(request.get("source_capture_generation") or ""),
                "started_at": started_at,
                "ended_at": None,
                "state": "running",
                "predictor_source": "point_in_time",
                "probability_strategy": "poisson_draw_gate",
                "model_artifact": str(artifact),
                "model_artifact_sha256": _sha256_file(artifact),
                "request_sha256": _sha256_bytes(request_bytes),
                "command": command,
            }
        )
        write_json(staging_dir / "run_metadata.json", metadata)
        process: subprocess.Popen | None = None
        try:
            on_progress(ReviewedRunProgress("starting", None, None, "Starting historical backtest"))
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=_REPO_ROOT,
                start_new_session=(sys.platform != "win32"),
            )
            stderr_lines = _stream_process(process, staging_dir, on_progress)
        except BaseException as exc:
            if process is not None:
                _terminate_process(process)
            outcome = _finalize_failure(
                event_key,
                run_id,
                staging_dir,
                f"Could not run historical backtest: {exc!r}",
                base_dir=base_dir,
            )
            if not isinstance(exc, Exception):
                raise
            return outcome
        assert process is not None
        if process.returncode != 0:
            tail = "\n".join(stderr_lines[-20:])
            error = f"Historical backtest exited with code {process.returncode}"
            if tail:
                error += f"\n{tail}"
            return _finalize_failure(event_key, run_id, staging_dir, error, base_dir=base_dir)
        if not (staging_dir / "summary.json").is_file():
            return _finalize_failure(
                event_key,
                run_id,
                staging_dir,
                "Historical backtest completed without summary.json",
                base_dir=base_dir,
            )

        try:
            from src.tournaments.backtest_reviewed_report import write_reviewed_backtest_html

            summary = read_json(staging_dir / "summary.json")
            write_reviewed_backtest_html(
                staging_dir / "comparison.html",
                summary,
                metadata,
            )
            metadata["ended_at"] = utc_now_iso()
            metadata["state"] = "completed"
            write_json(staging_dir / "run_metadata.json", metadata)
            final_dir = promote_run(
                event_key,
                BACKTEST_SCENARIO,
                run_id,
                base_dir=base_dir,
            )
        except Exception as exc:
            return _finalize_failure(
                event_key,
                run_id,
                staging_dir,
                f"Could not finalize historical backtest: {exc!r}",
                base_dir=base_dir,
            )
        return ReviewedRunOutcome("completed", final_dir)


def list_reviewed_runs(
    event_key: str,
    *,
    base_dir: Path | str = "reports",
) -> tuple[ReviewedRunRecord, ...]:
    records: list[ReviewedRunRecord] = []
    for run_id in list_runs(event_key, BACKTEST_SCENARIO, base_dir=base_dir):
        path = run_dir(event_key, BACKTEST_SCENARIO, run_id, base_dir=base_dir)
        try:
            metadata = read_json(path / "run_metadata.json")
        except (OSError, ValueError, TypeError):
            continue
        records.append(
            ReviewedRunRecord(
                run_id=run_id,
                run_dir=path,
                age_group=str(metadata.get("cohort_age_group") or ""),
                gender=str(metadata.get("cohort_gender") or ""),
                event_name=str(metadata.get("event_name") or ""),
                ended_at=str(metadata.get("ended_at") or ""),
            )
        )
    return tuple(sorted(records, key=lambda item: (item.ended_at, item.run_id), reverse=True))


def list_failed_reviewed_runs(
    event_key: str,
    *,
    base_dir: Path | str = "reports",
) -> tuple[ReviewedRunRecord, ...]:
    """List retained failed attempts so event coverage does not hide failures."""

    runs_root = run_dir(
        event_key,
        BACKTEST_SCENARIO,
        "placeholder",
        base_dir=base_dir,
    ).parent
    records: list[ReviewedRunRecord] = []
    if not runs_root.is_dir():
        return ()
    for path in runs_root.glob("*.failed"):
        try:
            metadata = read_json(path / "run_metadata.json")
            error_payload = read_json(path / "error.json")
        except (OSError, ValueError, TypeError):
            continue
        records.append(
            ReviewedRunRecord(
                run_id=path.name.removesuffix(".failed"),
                run_dir=path,
                age_group=str(metadata.get("cohort_age_group") or ""),
                gender=str(metadata.get("cohort_gender") or ""),
                event_name=str(metadata.get("event_name") or ""),
                ended_at=str(metadata.get("ended_at") or error_payload.get("failed_at") or ""),
                state="failed",
                error=str(error_payload.get("error") or "The run failed"),
            )
        )
    return tuple(sorted(records, key=lambda item: (item.ended_at, item.run_id), reverse=True))


def load_reviewed_run(record: ReviewedRunRecord) -> tuple[dict[str, Any], dict[str, Any]]:
    return read_json(record.run_dir / "summary.json"), read_json(record.run_dir / "run_metadata.json")


def reviewed_run_export(record: ReviewedRunRecord) -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in _EXPORT_FILES:
            path = record.run_dir / name
            if path.is_file():
                archive.write(path, arcname=name)
    return buffer.getvalue()
