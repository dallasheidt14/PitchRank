"""Unit tests for ``src.tournaments.reports.schema``.

Round-trip a hand-built ``ReportCard`` through ``to_dict`` and
``from_dict``; verify schema-version handling on both sides; verify
``OverrideAuditRow`` honors the storage ``schema_version`` gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tournaments.reports.compute import (
    read_comparison_json,
    write_comparison_json,
)
from src.tournaments.reports.schema import (
    BalanceScore,
    Metric,
    OverrideAuditRow,
    ReportCard,
    RiskFlag,
    TeamMovement,
    TopReason,
)
from src.tournaments.storage.schema_version import SchemaVersionError


def _sample_report_card() -> ReportCard:
    return ReportCard(
        event_key="gotsport__45224__2026",
        scenario="default",
        run_id="u14_boys_20260430T120000_aaaaaaaaaaaa",
        age_group="u14",
        gender="Boys",
        event_name="Phoenix Cup 2026",
        computed_at="2026-04-30T12:00:00+00:00",
        balance_score=BalanceScore(actual=None, optimized=78.0, delta=None, preset_id="default"),
        metrics=(
            Metric(label="One-goal game rate", actual=0.22, optimized=0.41, delta=0.19, unit="rate"),
            Metric(label="Same-club early meetings", actual=None, optimized=0, delta=None, unit="count"),
        ),
        risk_flags=(
            RiskFlag(severity="info", category="low_games", message="Foo: only 4 games", affected_teams=("Foo",)),
            RiskFlag(severity="warning", category="stale_ranking_snapshot", message="Snapshot is 9 days old"),
        ),
        top_reasons=(TopReason(text="Reduced 5+ goal mismatches from 4 to 1 (-75%)."),),
        team_movements=(
            TeamMovement(
                canonical_team_id="tim-1",
                team_name="FC Dallas 2012",
                from_division="Super Elite",
                to_division="Super Pro",
                move="move_down",
            ),
        ),
        override_audit=(
            OverrideAuditRow.from_dict(
                {"schema_version": 1, "ts": "2026-04-30T11:00:00+00:00", "type": "accept_match", "team_ref": "pid-1"}
            ),
        ),
    )


def test_report_card_round_trip_preserves_equality():
    rc = _sample_report_card()
    payload = rc.to_dict()
    restored = ReportCard.from_dict(payload)
    assert restored == rc


def test_report_card_from_dict_tolerates_missing_schema_version():
    """Lenient on read: default to v1 (mirrors ``frozen_medians.from_dict``)."""
    rc = _sample_report_card()
    payload = rc.to_dict()
    payload.pop("schema_version", None)
    restored = ReportCard.from_dict(payload)
    assert restored.schema_version == 1


def test_override_audit_row_rejects_newer_schema():
    """The ``schema_version`` gate fires at the row level on read."""
    with pytest.raises(SchemaVersionError):
        OverrideAuditRow.from_dict({"schema_version": 999, "type": "accept_match"})


def test_override_audit_row_to_dict_round_trips():
    payload = {"schema_version": 1, "ts": "x", "type": "accept_match", "team_ref": "pid"}
    row = OverrideAuditRow.from_dict(payload)
    assert row.to_dict() == payload


def test_balance_score_round_trip_with_actual_present():
    score = BalanceScore(actual=43.0, optimized=78.0, delta=35.0, preset_id="default")
    restored = BalanceScore.from_dict(score.to_dict())
    assert restored == score


def test_metric_round_trip_with_none_actual():
    metric = Metric(label="Capped GD", actual=None, optimized=0.82, delta=None, unit="gd")
    restored = Metric.from_dict(metric.to_dict())
    assert restored == metric


def test_comparison_json_round_trip(tmp_path: Path):
    rc = _sample_report_card()
    run_dir = tmp_path / "runs" / "u14_boys_test"
    run_dir.mkdir(parents=True)
    path = write_comparison_json(rc, run_dir)
    restored = read_comparison_json(path)
    assert restored == rc


def test_comparison_json_rejects_newer_schema(tmp_path: Path):
    """Strict on write — any tampered ``schema_version`` newer than 1 fails."""
    rc = _sample_report_card()
    run_dir = tmp_path / "runs" / "u14_boys_test"
    run_dir.mkdir(parents=True)
    path = write_comparison_json(rc, run_dir)
    # Tamper the on-disk file to claim a future schema version.
    raw = path.read_text(encoding="utf-8")
    tampered = raw.replace('"schema_version": 1', '"schema_version": 999', 1)
    path.write_text(tampered, encoding="utf-8")
    with pytest.raises(SchemaVersionError):
        read_comparison_json(path)
