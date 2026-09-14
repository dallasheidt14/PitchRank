from __future__ import annotations

import json

import pandas as pd

from src.tournaments.backtest_historical_preflight import (
    HistoricalCohortCheck,
    HistoricalEntrantCheck,
    HistoricalPreflight,
)
from src.tournaments.historical_coverage_reporting import (
    build_historical_coverage_report,
    write_historical_coverage_report,
)


def _preflight() -> HistoricalPreflight:
    entrants = (
        HistoricalEntrantCheck(
            "strong",
            "Strong Team",
            "canonical-strong",
            "canonical-strong",
            True,
            snapshot_date="2026-08-30",
            power_score=0.8,
            games_played=18,
        ),
        HistoricalEntrantCheck(
            "limited",
            "Limited Team",
            "canonical-limited",
            "canonical-limited",
            True,
            snapshot_date="2026-08-30",
            power_score=0.5,
            games_played=3,
        ),
        HistoricalEntrantCheck(
            "missing",
            "Missing Team",
            "canonical-missing",
            "average-estimate:missing",
            True,
            power_score=0.5,
            rating_basis="cohort_average_estimate_missing_pre_event_history",
            rating_fallback="missing_pre_event_history_average_estimate",
        ),
        HistoricalEntrantCheck(
            "unknown",
            "Unknown Team",
            "not-found:unknown",
            "average-estimate:unknown",
            True,
            power_score=0.5,
            rating_basis="cohort_average_estimate",
            rating_fallback="division_then_cohort_average_estimate",
        ),
    )
    return HistoricalPreflight(
        input_sha256="input",
        checked_at="2026-09-13T00:00:00+00:00",
        cutoff_exclusive="2026-09-05",
        model_artifact_sha256="artifact",
        model_data_end_date="2026-09-04",
        merge_map_version="merge",
        cohorts=(HistoricalCohortCheck("u14", "Male", 4, 4, entrants),),
    )


def test_historical_coverage_report_exposes_each_evidence_quality():
    report = build_historical_coverage_report(_preflight())

    assert report["summary"]["total_entrants"] == 4
    assert report["summary"]["average_estimate_entrants"] == 2
    assert report["summary"]["average_estimate_rate"] == 0.5
    assert report["summary"]["counts_by_quality"] == {
        "established_history": 1,
        "limited_history": 1,
        "missing_history_average": 1,
        "not_found_average": 1,
    }


def test_historical_coverage_report_writes_reviewable_json_and_csv(tmp_path):
    paths = write_historical_coverage_report(_preflight(), tmp_path)

    payload = json.loads((tmp_path / "historical_coverage.json").read_text())
    frame = pd.read_csv(tmp_path / "historical_coverage.csv")
    assert paths == {
        "json": str(tmp_path / "historical_coverage.json"),
        "csv": str(tmp_path / "historical_coverage.csv"),
    }
    assert payload["cutoff_exclusive"] == "2026-09-05"
    assert frame.iloc[0]["needs_evidence_recovery"]
    assert set(frame["event_team_name"]) == {
        "Strong Team",
        "Limited Team",
        "Missing Team",
        "Unknown Team",
    }
