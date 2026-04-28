"""Report Card library for the MatchBalance backtest intake.

A pure-Python library that turns a Shell 06 cohort run dir into the
commercial-grade Report Card — the artifact tournament directors see
after a backtest completes. No Streamlit, no Supabase imports — Shell 08
embeds the rendered HTML and the same code can later back a Next.js route.

Layout:

    src/tournaments/reports/
      schema.py           # @dataclass(frozen=True) types + to_dict/from_dict
      compute.py          # build a ReportCard from run_dir artifacts
      render_html.py      # Jinja2 → HTML (embedded fragment / standalone)
      render_csv.py       # flatten to three CSVs
      templates/
        report_card.html

Public API is re-exported here; submodules are the implementation.
"""

from __future__ import annotations

from src.tournaments.reports.compute import (
    ReportCardError,
    compute_and_persist_report_card,
    compute_report_card,
    read_comparison_json,
    write_comparison_json,
)
from src.tournaments.reports.render_csv import (
    render_all_csv,
    render_metrics_csv,
    render_risk_flags_csv,
    render_team_movements_csv,
)
from src.tournaments.reports.render_html import render_html, write_html
from src.tournaments.reports.schema import (
    BalanceScore,
    Metric,
    OverrideAuditRow,
    ReportCard,
    RiskFlag,
    TeamMovement,
    TopReason,
)

__all__ = [
    # dataclasses
    "BalanceScore",
    "Metric",
    "OverrideAuditRow",
    "ReportCard",
    "RiskFlag",
    "TeamMovement",
    "TopReason",
    # errors
    "ReportCardError",
    # compute
    "compute_report_card",
    "compute_and_persist_report_card",
    "read_comparison_json",
    "write_comparison_json",
    # rendering
    "render_html",
    "write_html",
    "render_metrics_csv",
    "render_risk_flags_csv",
    "render_team_movements_csv",
    "render_all_csv",
]
