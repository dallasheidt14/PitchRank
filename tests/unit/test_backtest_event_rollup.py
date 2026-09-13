from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest

from src.tournaments.backtest_event_rollup import (
    SelectedCohortRun,
    _event_projection_uncertainty,
    build_event_rollup,
    event_rollup_export,
)
from src.tournaments.backtest_intake_state import CaptureVerification
from src.tournaments.backtest_rating_fallback import (
    DIVISION_AVERAGE_BASIS,
    DIVISION_MISSING_HISTORY_AVERAGE_BASIS,
)
from src.tournaments.backtest_reviewed_run import (
    BACKTEST_ENGINE_VERSION,
    ReviewedCohortReadiness,
    ReviewedRunRecord,
    build_reviewed_cohort_readiness,
)
from tests.unit.test_backtest_request import _links, _snapshot


def _verified_snapshot():
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
        "backtest_engine_version": BACKTEST_ENGINE_VERSION,
        "source_capture_generation": "generation-1",
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "model_artifact_sha256": "model-sha",
        "merge_map_version": "merge-v1",
    }
    original = {
        "projected_matchup_count": 1,
        "average_goal_differential": 1.0,
        "blowout_4plus_probability": 0.0,
    }
    proposed = {
        "projected_matchup_count": 1,
        "average_goal_differential": 1.5,
        "blowout_4plus_probability": 0.10 if with_4plus else None,
    }
    summary = {
        "seeding_comparison": {"status": "comparable"},
        "original_model_projection": original,
        "proposed_model_projection": proposed,
        "original_schedule_projection": original,
        "proposed_schedule_projection": proposed,
        "model_validation": {"status": "passed", "blockers": []},
        "division_recommendations": [
            {
                "entrant_id": "reg-a",
                "event_team_name": "Alpha",
                "actual_division": "Gold",
                "recommended_division": "Silver",
                "actual_pool": "Pool A",
                "recommended_pool": "Pool A",
                "move": "move_down",
                "rating_basis": DIVISION_MISSING_HISTORY_AVERAGE_BASIS,
            },
            {
                "entrant_id": "reg-b",
                "event_team_name": "Bravo",
                "actual_division": "Gold",
                "recommended_division": "Gold",
                "actual_pool": "Pool A",
                "recommended_pool": "Pool B",
                "move": "stay",
                "rating_basis": DIVISION_AVERAGE_BASIS,
            },
        ],
    }
    if with_4plus:
        summary["simulation_ensemble"] = {
            "samples": {
                "proposed": {
                    "average_goal_differential": [1.0, 2.0],
                    "blowout_4plus_rate": [0.0, 0.2],
                }
            }
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

    rollup = build_event_rollup(
        snapshot,
        readiness,
        (record,),
        model_sha256="model-sha",
        merge_map_version="merge-v1",
    )

    assert rollup["coverage"]["completed"] == 1
    comparison = rollup["actual_vs_matchbalance"]
    assert comparison["actual_game_count"] == 1
    assert comparison["actual_average_goal_margin"] == 1.0
    assert comparison["matchbalance_projected_average_goal_margin"] == 1.5
    assert comparison["estimated_goal_margin_reduction"] == -0.5
    assert comparison["actual_blowout_4plus_rate"] == 0.0
    assert comparison["estimated_blowout_4plus_rate_reduction"] == pytest.approx(-0.1)
    uncertainty = comparison["projection_uncertainty"]
    assert uncertainty["status"] == "available"
    assert uncertainty["simulation_count"] == 2
    assert uncertainty["matchbalance_average_goal_margin"]["mean"] == 1.5
    assert uncertainty["matchbalance_blowout_4plus_rate"]["mean"] == 0.1
    assert rollup["team_movements"]["moved_down"] == 1
    assert rollup["team_movements"]["unchanged"] == 1
    assert rollup["team_movements"]["pool_changed_within_division"] == 1
    assert rollup["team_movements"]["placement_changed"] == 2
    assert rollup["model_validation"]["event_validation"]["status"] == "passed"
    assert rollup["rating_evidence"] == {
        "historical_snapshot": 0,
        "not_found_average_estimate": 1,
        "missing_history_average_estimate": 1,
    }
    with zipfile.ZipFile(BytesIO(event_rollup_export(rollup))) as archive:
        assert set(archive.namelist()) == {
            "tournament-director-report.html",
            "tournament-backtest-rollup.json",
        }
        report = archive.read("tournament-director-report.html").decode("utf-8")
        assert "Actual tournament versus MatchBalance" in report
        assert "Original projected" not in report
        assert "matched teams without eligible pre-event history" in report


def test_event_uncertainty_combines_cohorts_by_scheduled_match_count():
    readiness = ReviewedCohortReadiness("u14", "Male", 4, 1)
    record = ReviewedRunRecord("run", Path("."), "u14", "Male", "Cup", "now")

    def selected(match_count, margins, blowouts):
        return SelectedCohortRun(
            readiness,
            record,
            {
                "proposed_schedule_projection": {"projected_matchup_count": match_count},
                "simulation_ensemble": {
                    "samples": {
                        "proposed": {
                            "average_goal_differential": margins,
                            "blowout_4plus_rate": blowouts,
                        }
                    }
                },
            },
            {},
        )

    uncertainty = _event_projection_uncertainty(
        (
            selected(3, [1.0, 3.0], [0.0, 1.0]),
            selected(1, [5.0, 1.0], [1.0, 0.0]),
        ),
        actual_margin=2.0,
        actual_blowout_rate=0.5,
    )

    assert uncertainty["status"] == "available"
    assert uncertainty["match_count"] == 4
    assert uncertainty["matchbalance_average_goal_margin"]["mean"] == 2.25
    assert uncertainty["matchbalance_blowout_4plus_rate"]["mean"] == 0.5


def test_event_rollup_does_not_invent_4plus_rate_for_legacy_run(tmp_path):
    snapshot = _verified_snapshot()
    readiness = build_reviewed_cohort_readiness(snapshot, _links())
    record = _record(tmp_path, readiness[0], with_4plus=False)

    rollup = build_event_rollup(
        snapshot,
        readiness,
        (record,),
        model_sha256="model-sha",
        merge_map_version="merge-v1",
    )

    assert rollup["coverage"]["completed"] == 1
    comparison = rollup["actual_vs_matchbalance"]
    assert comparison["actual_blowout_4plus_rate"] == 0.0
    assert comparison["matchbalance_projected_blowout_4plus_rate"] is None
    assert comparison["estimated_blowout_4plus_rate_reduction"] is None


def test_event_rollup_keeps_small_cohort_calibration_failures_as_warnings(tmp_path):
    snapshot = _verified_snapshot()
    readiness = build_reviewed_cohort_readiness(snapshot, _links())
    record = _record(tmp_path, readiness[0])
    summary_path = record.run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["model_validation"] = {
        "status": "failed",
        "blockers": ["Unchanged 4+ blowout-rate prediction is outside the accepted tolerance"],
    }
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    rollup = build_event_rollup(
        snapshot,
        readiness,
        (record,),
        model_sha256="model-sha",
        merge_map_version="merge-v1",
    )

    comparison = rollup["actual_vs_matchbalance"]
    assert rollup["coverage"]["completed"] == 1
    assert comparison["comparison_ready"] is True
    assert comparison["matchbalance_projected_average_goal_margin"] == 1.5
    assert rollup["model_validation"]["failed_cohorts"] == 1
    assert len(rollup["model_validation"]["cohort_warnings"]) == 1


def test_event_rollup_withholds_comparison_when_event_wide_replay_fails(tmp_path):
    snapshot = _verified_snapshot()
    readiness = build_reviewed_cohort_readiness(snapshot, _links())
    record = _record(tmp_path, readiness[0])
    summary_path = record.run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["original_schedule_projection"]["average_goal_differential"] = 4.0
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    rollup = build_event_rollup(
        snapshot,
        readiness,
        (record,),
        model_sha256="model-sha",
        merge_map_version="merge-v1",
    )

    assert rollup["model_validation"]["event_validation"]["status"] == "failed"
    assert rollup["actual_vs_matchbalance"]["comparison_ready"] is False
    assert rollup["actual_vs_matchbalance"]["matchbalance_projected_average_goal_margin"] is None


def test_event_rollup_actual_baseline_always_uses_the_whole_scraped_tournament(tmp_path):
    snapshot = _verified_snapshot()
    readiness = build_reviewed_cohort_readiness(snapshot, _links())
    record = _record(tmp_path, readiness[0])
    original_division = snapshot.roster.divisions[0]
    unrelated_fixture = replace(
        original_division.fixtures[0],
        match_number="99",
        home_score=8,
        away_score=0,
        source_url="https://example.test/match/99",
    )
    unrelated_division = replace(
        original_division,
        group_id="group-2",
        division_label="Silver",
        fixtures=(unrelated_fixture,),
        age_group="u15",
    )
    snapshot = replace(
        snapshot,
        roster=replace(
            snapshot.roster,
            divisions=(original_division, unrelated_division),
        ),
    )

    waiting = ReviewedCohortReadiness(
        age_group="u15",
        gender="Male",
        team_count=0,
        division_count=1,
        blockers=("Waiting for review",),
    )
    rollup = build_event_rollup(
        snapshot,
        (*readiness, waiting),
        (record,),
        model_sha256="model-sha",
        merge_map_version="merge-v1",
    )

    comparison = rollup["actual_vs_matchbalance"]
    assert comparison["actual_game_count"] == 2
    assert comparison["actual_average_goal_margin"] == 4.5
    assert comparison["actual_blowout_4plus_count"] == 1
    assert comparison["comparison_ready"] is False
    assert comparison["matchbalance_projected_average_goal_margin"] is None


def test_event_rollup_rejects_stale_capture_or_different_model(tmp_path):
    snapshot = _verified_snapshot()
    readiness = build_reviewed_cohort_readiness(snapshot, _links())
    record = _record(tmp_path, readiness[0])

    rollup = build_event_rollup(
        snapshot,
        readiness,
        (record,),
        model_sha256="different",
        merge_map_version="merge-v1",
    )

    assert rollup["coverage"]["completed"] == 0
    assert rollup["coverage"]["ready"] == 1
    assert rollup["selected_runs"] == []


def test_event_rollup_rejects_output_from_an_older_engine_version(tmp_path):
    snapshot = _verified_snapshot()
    readiness = build_reviewed_cohort_readiness(snapshot, _links())
    record = _record(tmp_path, readiness[0])
    metadata_path = record.run_dir / "run_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["backtest_engine_version"] = "reviewed-backtest-v1"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    rollup = build_event_rollup(
        snapshot,
        readiness,
        (record,),
        model_sha256="model-sha",
        merge_map_version="merge-v1",
    )

    assert rollup["coverage"]["completed"] == 0
    assert rollup["selected_runs"] == []


def test_event_rollup_withholds_old_runs_when_current_verification_is_blocked(tmp_path):
    verified = _verified_snapshot()
    verified_readiness = build_reviewed_cohort_readiness(verified, _links())
    record = _record(tmp_path, verified_readiness[0])
    unstable = replace(
        verified,
        verification=CaptureVerification(
            ("group-1",),
            (1, 2),
            "2026-09-13T00:00:00+00:00",
            False,
        ),
    )
    current_readiness = build_reviewed_cohort_readiness(unstable, _links())

    rollup = build_event_rollup(
        unstable,
        current_readiness,
        (record,),
        model_sha256="model-sha",
        merge_map_version="merge-v1",
    )

    assert rollup["selected_runs"] == []
    assert rollup["coverage"]["completed"] == 0
    assert rollup["coverage"]["awaiting_review"] == 1
    assert rollup["actual_vs_matchbalance"]["comparison_ready"] is False


def test_event_rollup_rejects_run_from_an_older_merge_map(tmp_path):
    snapshot = _verified_snapshot()
    readiness = build_reviewed_cohort_readiness(snapshot, _links())
    record = _record(tmp_path, readiness[0])

    rollup = build_event_rollup(
        snapshot,
        readiness,
        (record,),
        model_sha256="model-sha",
        merge_map_version="merge-v2",
    )

    assert rollup["coverage"]["completed"] == 0
    assert rollup["selected_runs"] == []


def test_event_rollup_requires_explicit_model_hash(tmp_path):
    snapshot = _verified_snapshot()
    readiness = build_reviewed_cohort_readiness(snapshot, _links())
    record = _record(tmp_path, readiness[0])

    rollup = build_event_rollup(
        snapshot,
        readiness,
        (record,),
        model_sha256=None,
        merge_map_version="merge-v1",
    )

    assert rollup["coverage"]["completed"] == 0
    assert rollup["coverage"]["awaiting_history"] == 1
    assert rollup["selected_runs"] == []
    assert (
        rollup["coverage"]["rows"][0]["what_remains"]
        == "Select a valid historical model artifact"
    )
