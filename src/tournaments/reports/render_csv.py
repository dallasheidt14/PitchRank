"""Flat CSV exports of a ``ReportCard``.

Three files written into a caller-supplied directory (typically the run
dir, but any path works):

- ``comparison_metrics.csv`` — one row per ``Metric``.
- ``comparison_risk_flags.csv`` — one row per ``RiskFlag``;
  ``affected_teams`` joined with ``";"``.
- ``comparison_team_movements.csv`` — one row per ``TeamMovement``.

Module-level ``FIELDNAMES`` tuples drive column order (mirrors
``storage/registry.py:55-81``). ``_io.write_csv`` is atomic and treats
missing keys as empty cells, which is exactly what ``Metric.actual=None``
needs.
"""

from __future__ import annotations

from pathlib import Path

from src.tournaments.reports.schema import ReportCard
from src.tournaments.storage._io import write_csv

__all__ = [
    "METRICS_FIELDNAMES",
    "RISK_FLAG_FIELDNAMES",
    "TEAM_MOVEMENT_FIELDNAMES",
    "render_all_csv",
    "render_metrics_csv",
    "render_risk_flags_csv",
    "render_team_movements_csv",
]


METRICS_FIELDNAMES: tuple[str, ...] = (
    "metric",
    "actual",
    "optimized",
    "delta",
    "unit",
)

RISK_FLAG_FIELDNAMES: tuple[str, ...] = (
    "severity",
    "category",
    "message",
    "affected_teams",
)

TEAM_MOVEMENT_FIELDNAMES: tuple[str, ...] = (
    "canonical_team_id",
    "team_name",
    "from_division",
    "to_division",
    "move",
)


def _none_to_blank(value: object) -> object:
    """``write_csv`` writes empty strings for missing keys; this maps
    ``None`` values to empty strings explicitly so a ``Metric`` row with
    ``actual=None`` doesn't get rendered as the literal string ``"None"``.
    """
    return "" if value is None else value


def render_metrics_csv(report_card: ReportCard, dir_path: Path) -> Path:
    """Write ``comparison_metrics.csv`` to ``dir_path``."""
    rows = [
        {
            "metric": metric.label,
            "actual": _none_to_blank(metric.actual),
            "optimized": _none_to_blank(metric.optimized),
            "delta": _none_to_blank(metric.delta),
            "unit": metric.unit,
        }
        for metric in report_card.metrics
    ]
    path = dir_path / "comparison_metrics.csv"
    write_csv(path, rows, fieldnames=METRICS_FIELDNAMES)
    return path


def render_risk_flags_csv(report_card: ReportCard, dir_path: Path) -> Path:
    """Write ``comparison_risk_flags.csv`` to ``dir_path``.

    ``affected_teams`` joined with ``";"`` so each cell stays single-line
    in spreadsheet readers; round-trips via ``cell.split(";")``.
    """
    rows = [
        {
            "severity": flag.severity,
            "category": flag.category,
            "message": flag.message,
            "affected_teams": ";".join(flag.affected_teams),
        }
        for flag in report_card.risk_flags
    ]
    path = dir_path / "comparison_risk_flags.csv"
    write_csv(path, rows, fieldnames=RISK_FLAG_FIELDNAMES)
    return path


def render_team_movements_csv(report_card: ReportCard, dir_path: Path) -> Path:
    """Write ``comparison_team_movements.csv`` to ``dir_path``."""
    rows = [
        {
            "canonical_team_id": movement.canonical_team_id,
            "team_name": movement.team_name,
            "from_division": movement.from_division,
            "to_division": movement.to_division,
            "move": movement.move,
        }
        for movement in report_card.team_movements
    ]
    path = dir_path / "comparison_team_movements.csv"
    write_csv(path, rows, fieldnames=TEAM_MOVEMENT_FIELDNAMES)
    return path


def render_all_csv(report_card: ReportCard, dir_path: Path) -> tuple[Path, Path, Path]:
    """Convenience: write all three CSVs and return their paths."""
    return (
        render_metrics_csv(report_card, dir_path),
        render_risk_flags_csv(report_card, dir_path),
        render_team_movements_csv(report_card, dir_path),
    )
