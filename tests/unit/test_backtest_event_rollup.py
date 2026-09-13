from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import replace
from io import BytesIO

import pytest

from src.tournaments.backtest_event_rollup import build_event_rollup, event_rollup_export
from src.tournaments.backtest_intake_state import CaptureVerification
from src.tournaments.backtest_reviewed_run import (
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
    comparison = rollup["actual_vs_matchbalance"]
    assert comparison["actual_game_count"] == 1
    assert comparison["actual_average_goal_margin"] == 1.0
    assert comparison["matchbalance_projected_average_goal_margin"] == 1.5
    assert comparison["estimated_goal_margin_reduction"] == -0.5
    assert comparison["actual_blowout_4plus_rate"] == 0.0
    assert comparison["estimated_blowout_4plus_rate_reduction"] == pytest.approx(-0.1)
    assert rollup["team_movements"]["moved_down"] == 1
    assert rollup["team_movements"]["unchanged"] == 1
    with zipfile.ZipFile(BytesIO(event_rollup_export(rollup))) as archive:
        assert set(archive.namelist()) == {
            "tournament-director-report.html",
            "tournament-backtest-rollup.json",
        }
        report = archive.read("tournament-director-report.html").decode("utf-8")
        assert "Actual tournament versus MatchBalance" in report
        assert "Original projected" not in report


def test_event_rollup_does_not_invent_4plus_rate_for_legacy_run(tmp_path):
    snapshot = _verified_snapshot()
    readiness = build_reviewed_cohort_readiness(snapshot, _links())
    record = _record(tmp_path, readiness[0], with_4plus=False)

    rollup = build_event_rollup(snapshot, readiness, (record,), model_sha256="model-sha")

    assert rollup["coverage"]["completed"] == 1
    comparison = rollup["actual_vs_matchbalance"]
    assert comparison["actual_blowout_4plus_rate"] == 0.0
    assert comparison["matchbalance_projected_blowout_4plus_rate"] is None
    assert comparison["estimated_blowout_4plus_rate_reduction"] is None


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

    rollup = build_event_rollup(snapshot, readiness, (record,), model_sha256="different")

    assert rollup["coverage"]["completed"] == 0
    assert rollup["coverage"]["ready"] == 1
    assert rollup["selected_runs"] == []


def test_event_rollup_requires_explicit_model_hash(tmp_path):
    snapshot = _verified_snapshot()
    readiness = build_reviewed_cohort_readiness(snapshot, _links())
    record = _record(tmp_path, readiness[0])

    rollup = build_event_rollup(snapshot, readiness, (record,), model_sha256=None)

    assert rollup["coverage"]["completed"] == 0
    assert rollup["coverage"]["awaiting_history"] == 1
    assert rollup["selected_runs"] == []
    assert (
        rollup["coverage"]["rows"][0]["what_remains"]
        == "Select a valid historical model artifact"
    )
