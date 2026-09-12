from __future__ import annotations

import json
import zipfile
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace

from src.tournaments.backtest_intake_state import CaptureVerification
from src.tournaments.backtest_reviewed_run import (
    build_reviewed_cohort_readiness,
    default_model_artifact,
    execute_reviewed_run,
    list_reviewed_runs,
    reviewed_run_export,
)
from tests.unit.test_backtest_request import _links, _snapshot


def _verified_snapshot():
    snapshot = _snapshot()
    return replace(
        snapshot,
        verification=CaptureVerification(
            ("group-1",),
            (1, 1),
            "2026-09-12T00:00:00+00:00",
            True,
        ),
    )


def _summary() -> dict:
    return {
        "event_name": "Spring Cup",
        "cohort": {"age_group": "u14", "gender": "Male"},
        "historical_games_used_for_prediction": 12,
        "predictor": {"prediction_date": "2025-05-10", "probability_strategy": "poisson_draw_gate"},
        "historical_inputs": {"model_artifact_sha256": "abc", "input_digest_sha256": "def"},
        "actual_results": {
            "actual_game_count": 1,
            "average_goal_differential": 1.0,
            "blowout_4plus_count": 0,
            "blowout_4plus_rate": 0.0,
        },
        "original_model_projection": {
            "average_goal_differential": 2.0,
            "median_goal_differential": 2.0,
            "close_game_probability": 0.4,
            "blowout_3plus_probability": 0.3,
            "blowout_5plus_probability": 0.1,
        },
        "proposed_model_projection": {
            "average_goal_differential": 1.5,
            "median_goal_differential": 1.0,
            "close_game_probability": 0.6,
            "blowout_3plus_probability": 0.2,
            "blowout_5plus_probability": 0.05,
        },
        "seeding_comparison": {"status": "comparable"},
        "division_recommendations": [
            {
                "event_team_name": "Alpha",
                "actual_division": "Gold",
                "recommended_division": "Gold",
                "move": "stay",
                "power_score": 0.6,
            }
        ],
    }


def test_readiness_requires_saved_landing_page_verification():
    readiness = build_reviewed_cohort_readiness(_snapshot(), _links())

    assert len(readiness) == 1
    assert readiness[0].ready is False
    assert "Verify the published division list" in readiness[0].blockers[0]


def test_verified_reviewed_cohort_builds_one_strict_request():
    readiness = build_reviewed_cohort_readiness(_verified_snapshot(), _links())

    assert readiness[0].ready is True
    assert readiness[0].team_count == 2
    assert readiness[0].division_count == 1
    assert readiness[0].request["prediction_date"] == "2025-05-10"


def test_default_model_artifact_can_be_configured(monkeypatch):
    monkeypatch.setenv("MATCHBALANCE_POINT_IN_TIME_MODEL_ARTIFACT", "C:/models/history.pkl")

    assert default_model_artifact() == "C:/models/history.pkl"


def test_execute_reviewed_run_promotes_local_evidence(tmp_path, monkeypatch):
    from src.tournaments import backtest_reviewed_run as runner

    artifact = tmp_path / "model.pkl"
    artifact.write_bytes(b"historical model")
    process = SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: process)

    def stream(_process, staging_dir, on_progress):
        (staging_dir / "summary.json").write_text(json.dumps(_summary()), encoding="utf-8")
        (staging_dir / "historical_inputs.json").write_text("{}", encoding="utf-8")
        (staging_dir / "division_recommendations.json").write_text("[]", encoding="utf-8")
        (staging_dir / "division_recommendations.csv").write_text("team\nAlpha\n", encoding="utf-8")
        on_progress(runner.ReviewedRunProgress("running-optimizer", None, None, "PHASE: running-optimizer"))
        return []

    monkeypatch.setattr(runner, "_stream_process", stream)
    request = build_reviewed_cohort_readiness(_verified_snapshot(), _links())[0].request
    events = []

    outcome = execute_reviewed_run(
        "gotsport__51783__2025",
        request,
        model_artifact=artifact,
        base_dir=tmp_path,
        on_progress=events.append,
    )

    assert outcome.state == "completed"
    assert (outcome.run_dir / "done.json").is_file()
    assert (outcome.run_dir / "comparison.html").is_file()
    metadata = json.loads((outcome.run_dir / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["state"] == "completed"
    assert metadata["source_capture_generation"] == "generation-1"
    assert metadata["model_artifact_sha256"]
    assert events[-1].phase == "running-optimizer"

    records = list_reviewed_runs("gotsport__51783__2025", base_dir=tmp_path)
    assert [record.run_id for record in records] == [outcome.run_dir.name]
    with zipfile.ZipFile(BytesIO(reviewed_run_export(records[0]))) as archive:
        assert set(archive.namelist()) >= {
            "comparison.html",
            "summary.json",
            "historical_inputs.json",
            "request.json",
            "run_metadata.json",
        }


def test_execute_reviewed_run_preserves_failed_evidence(tmp_path, monkeypatch):
    from src.tournaments import backtest_reviewed_run as runner

    artifact = tmp_path / "model.pkl"
    artifact.write_bytes(b"historical model")
    process = SimpleNamespace(returncode=7)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        runner,
        "_stream_process",
        lambda _process, _staging_dir, _on_progress: ["historical data unavailable"],
    )
    request = build_reviewed_cohort_readiness(_verified_snapshot(), _links())[0].request

    outcome = execute_reviewed_run(
        "gotsport__51783__2025",
        request,
        model_artifact=artifact,
        base_dir=tmp_path,
    )

    assert outcome.state == "failed"
    assert outcome.run_dir.name.endswith(".failed")
    assert (outcome.run_dir / "error.json").is_file()
    metadata = json.loads((outcome.run_dir / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["state"] == "failed"
    assert "historical data unavailable" in (outcome.error or "")


def test_execute_reviewed_run_terminates_child_when_streamlit_interrupts(tmp_path, monkeypatch):
    from src.tournaments import backtest_reviewed_run as runner

    class InterruptedProcess:
        returncode = None
        terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode

    artifact = tmp_path / "model.pkl"
    artifact.write_bytes(b"historical model")
    process = InterruptedProcess()
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        runner,
        "_stream_process",
        lambda _process, _staging_dir, _on_progress: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    request = build_reviewed_cohort_readiness(_verified_snapshot(), _links())[0].request

    try:
        execute_reviewed_run(
            "gotsport__51783__2025",
            request,
            model_artifact=artifact,
            base_dir=tmp_path,
        )
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("Streamlit control-flow interruption should be re-raised")

    assert process.terminated is True
    failed = list(
        (tmp_path / "gotsport__51783__2025" / "scenarios" / "reviewed-backtest" / "runs").glob(
            "*.failed"
        )
    )
    assert len(failed) == 1
    assert (failed[0] / "error.json").is_file()


def test_execute_reviewed_run_marks_report_generation_failure(tmp_path, monkeypatch):
    from src.tournaments import backtest_reviewed_run as runner

    artifact = tmp_path / "model.pkl"
    artifact.write_bytes(b"historical model")
    process = SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: process)

    def stream(_process, staging_dir, _on_progress):
        (staging_dir / "summary.json").write_text("not-json", encoding="utf-8")
        return []

    monkeypatch.setattr(runner, "_stream_process", stream)
    request = build_reviewed_cohort_readiness(_verified_snapshot(), _links())[0].request

    outcome = execute_reviewed_run(
        "gotsport__51783__2025",
        request,
        model_artifact=artifact,
        base_dir=tmp_path,
    )

    assert outcome.state == "failed"
    assert outcome.run_dir.name.endswith(".failed")
    assert "Could not finalize" in (outcome.error or "")
    assert (outcome.run_dir / "error.json").is_file()


def test_execute_reviewed_run_rejects_an_event_directory_mismatch(tmp_path):
    artifact = tmp_path / "model.pkl"
    artifact.write_bytes(b"model")
    request = dict(build_reviewed_cohort_readiness(_verified_snapshot(), _links())[0].request)
    request["event_id"] = "other"

    try:
        execute_reviewed_run(
            "gotsport__51783__2025",
            request,
            model_artifact=artifact,
            base_dir=tmp_path,
        )
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("event mismatch should fail before staging")
