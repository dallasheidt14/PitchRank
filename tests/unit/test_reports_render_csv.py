"""Unit tests for ``src.tournaments.reports.render_csv``.

Render the three CSVs from a hand-built ``ReportCard`` and assert column
headers, row counts, and the ``;``-join contract for ``affected_teams``.
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.tournaments.reports.render_csv import (
    METRICS_FIELDNAMES,
    RISK_FLAG_FIELDNAMES,
    TEAM_MOVEMENT_FIELDNAMES,
    render_all_csv,
    render_metrics_csv,
    render_risk_flags_csv,
    render_team_movements_csv,
)
from src.tournaments.reports.schema import (
    BalanceScore,
    Metric,
    ReportCard,
    RiskFlag,
    TeamMovement,
)


def _hand_built_report() -> ReportCard:
    return ReportCard(
        event_key="gotsport__45224__2026",
        scenario="default",
        run_id="u14_boys_test",
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
            RiskFlag(severity="info", category="low_games", message="Foo: only 4 games", affected_teams=("a", "b")),
            RiskFlag(severity="warning", category="stale_ranking_snapshot", message="9 days old"),
        ),
        top_reasons=(),
        team_movements=(
            TeamMovement(
                canonical_team_id="tim-1",
                team_name="FC Dallas 2012",
                from_division="Super Elite",
                to_division="Super Pro",
                move="move_down",
            ),
        ),
    )


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        headers = list(reader.fieldnames or ())
    return headers, rows


def test_render_metrics_csv_column_order_matches_FIELDNAMES(tmp_path: Path):
    rc = _hand_built_report()
    path = render_metrics_csv(rc, tmp_path)
    headers, rows = _read_csv(path)
    assert tuple(headers) == METRICS_FIELDNAMES
    assert len(rows) == 2


def test_metric_actual_none_renders_as_empty_cell(tmp_path: Path):
    rc = _hand_built_report()
    path = render_metrics_csv(rc, tmp_path)
    _, rows = _read_csv(path)
    # Second row's actual should be empty string, not "None".
    assert rows[1]["metric"] == "Same-club early meetings"
    assert rows[1]["actual"] == ""
    assert rows[1]["delta"] == ""


def test_render_risk_flags_csv_joins_affected_teams_with_semicolons(tmp_path: Path):
    rc = _hand_built_report()
    path = render_risk_flags_csv(rc, tmp_path)
    headers, rows = _read_csv(path)
    assert tuple(headers) == RISK_FLAG_FIELDNAMES
    assert rows[0]["affected_teams"] == "a;b"
    # Round-trips on split.
    assert rows[0]["affected_teams"].split(";") == ["a", "b"]
    # Empty affected_teams renders as empty string.
    assert rows[1]["affected_teams"] == ""


def test_render_team_movements_csv_columns(tmp_path: Path):
    rc = _hand_built_report()
    path = render_team_movements_csv(rc, tmp_path)
    headers, rows = _read_csv(path)
    assert tuple(headers) == TEAM_MOVEMENT_FIELDNAMES
    assert len(rows) == 1
    assert rows[0]["from_division"] == "Super Elite"
    assert rows[0]["to_division"] == "Super Pro"
    assert rows[0]["move"] == "move_down"


def test_render_all_csv_writes_three_files(tmp_path: Path):
    rc = _hand_built_report()
    metrics_path, flags_path, movements_path = render_all_csv(rc, tmp_path)
    assert metrics_path.exists()
    assert flags_path.exists()
    assert movements_path.exists()
    assert metrics_path.name == "comparison_metrics.csv"
    assert flags_path.name == "comparison_risk_flags.csv"
    assert movements_path.name == "comparison_team_movements.csv"
