from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO

import pytest

from src.tournaments.backtest_event_rollup import build_event_rollup, event_rollup_export
from src.tournaments.backtest_intake_state import CaptureVerification
from src.tournaments.backtest_reviewed_run import (
    ReviewedRunRecord,
    build_reviewed_cohort_readiness,
)
from tests.unit.test_backtest_request import _links, _snapshot


def _verified_snapshot():
    from dataclasses import replace

    return replace(
        _snapshot(),
        verification=CaptureVerification(
            ("group-1",),
            (1, 1),
            "2026-09-12T00:00:00+00:00",
            True,
        ),
    )


def _record(tmp_path, readiness, *, with_4plus: bool = True) -> ReviewedRunRecord:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    request_bytes = json.dumps(
        readiness.request, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    metadata = {
        "source_capture_generation": "generation-1",
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "model_artifact_sha256": "model-sha",
    }
    original = {
        "projected_matchup_count": 4,
        "average_goal_differential": 2.5,
        "blowout_4plus_probability": 0.30 if with_4plus else None,
    }
    proposed = {
        "projected_matchup_count": 4,
        "average_goal_differential": 1.5,
        "blowout_4plus_probability": 0.10 if with_4plus else None,
    }
    summary = {
        "seeding_comparison": {"status": "comparable"},
        "original_model_projection": original,
        "proposed_model_projection": proposed,
        "division_recommendations": [
            {
                "entrant_id": "reg-a",
                "event_team_name": "Alpha",
                "actual_division": "Gold",
                "recommended_division": "Silver",
                "move": "move_down",
            },
            {
                "entrant_id": "reg-b",
                "event_team_name": "Bravo",
                "actual_division": "Gold",
                "recommended_division": "Gold",
                "move": "stay",
            },
        ],
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return ReviewedRunRecord(
        "run-1", run_dir, "u14", "Male", "Spring Cup", "2026-09-12T01:00:00Z"
    )


def test_event_rollup_uses_current_compatible_run_and_weighted_sales_metrics(tmp_path):
    snapshot = _verified_snapshot()
    readiness = build_reviewed_cohort_readiness(snapshot, _links())
    record = _record(tmp_path, readiness[0])

    rollup = build_event_rollup(snapshot, readiness, (record,), model_sha256="model-sha")

    assert rollup["coverage"]["completed"] == 1
    assert rollup["modelled_pool_matchups"]["original_average_goal_margin"] == 2.5
    assert rollup["modelled_pool_matchups"]["matchbalance_average_goal_margin"] == 1.5
    assert rollup["modelled_pool_matchups"]["goal_margin_improvement"] == 1.0
    assert rollup["modelled_pool_matchups"]["blowout_4plus_rate_improvement"] == pytest.approx(0.2)
    assert rollup["team_movements"]["moved_down"] == 1
    assert rollup["team_movements"]["unchanged"] == 1
    with zipfile.ZipFile(BytesIO(event_rollup_export(rollup))) as archive:
        assert set(archive.namelist()) == {
            "tournament-director-report.html",
            "tournament-backtest-rollup.json",
        }


def test_event_rollup_does_not_invent_4plus_rate_for_legacy_run(tmp_path):
    snapshot = _verified_snapshot()
    readiness = build_reviewed_cohort_readiness(snapshot, _links())
    record = _record(tmp_path, readiness[0], with_4plus=False)

    rollup = build_event_rollup(snapshot, readiness, (record,), model_sha256="model-sha")

    assert rollup["coverage"]["completed"] == 1
    assert rollup["modelled_pool_matchups"]["original_blowout_4plus_rate"] is None
    assert rollup["modelled_pool_matchups"]["blowout_4plus_rate_improvement"] is None


def test_event_rollup_rejects_stale_capture_or_different_model(tmp_path):
    snapshot = _verified_snapshot()
    readiness = build_reviewed_cohort_readiness(snapshot, _links())
    record = _record(tmp_path, readiness[0])

    rollup = build_event_rollup(snapshot, readiness, (record,), model_sha256="different")

    assert rollup["coverage"]["completed"] == 0
    assert rollup["coverage"]["ready"] == 1
    assert rollup["selected_runs"] == []
