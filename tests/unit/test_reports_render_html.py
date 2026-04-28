"""Unit tests for ``src.tournaments.reports.render_html``.

Render against hand-built ``ReportCard`` instances and assert structural
substrings appear. No byte-snapshot comparisons — substring assertions
only so cosmetic CSS tweaks don't break the suite.
"""

from __future__ import annotations

from pathlib import Path

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
            RiskFlag(severity="info", category="low_games", message="Foo: only 4 games", affected_teams=("Foo",)),
            RiskFlag(severity="warning", category="stale_ranking_snapshot", message="9 days old"),
        ),
        top_reasons=(
            TopReason(text="Reduced 5+ goal mismatches from 4 to 1 (-75%)."),
        ),
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
                {
                    "schema_version": 1,
                    "ts": "2026-04-30T11:00:00+00:00",
                    "type": "accept_match",
                    "team_ref": "pid-1",
                    "actor": "dallas@pitchrank.io",
                    "reason": "accepted match",
                }
            ),
        ),
    )


def test_render_html_standalone_wraps_in_html_document():
    rendered = render_html(_hand_built_report(), mode="standalone")
    assert rendered.startswith("<!DOCTYPE html>")
    assert "<html" in rendered
    assert "<style>" in rendered
    assert "</html>" in rendered


def test_render_html_embedded_returns_fragment_only():
    rendered = render_html(_hand_built_report(), mode="embedded")
    assert "<!DOCTYPE html>" not in rendered
    assert "<html" not in rendered
    # Body content still present.
    assert "Phoenix Cup 2026" in rendered


def test_render_html_includes_event_and_cohort():
    rendered = render_html(_hand_built_report())
    assert "Phoenix Cup 2026" in rendered
    assert "Boys u14" in rendered


def test_balance_score_actual_renders_n_a_when_none():
    rendered = render_html(_hand_built_report())
    assert "n/a &mdash; actual per-match data not available in v1" in rendered


def test_metric_with_none_actual_renders_n_a():
    rendered = render_html(_hand_built_report())
    # Metric "Same-club early meetings" has actual=None; should render n/a.
    assert "Same-club early meetings" in rendered
    assert ">n/a<" in rendered


def test_risk_flag_messages_appear():
    rendered = render_html(_hand_built_report())
    assert "Foo: only 4 games" in rendered
    assert "9 days old" in rendered
    # Categories surface as plain text labels.
    assert "low_games" in rendered
    assert "stale_ranking_snapshot" in rendered


def test_top_reason_text_is_present():
    rendered = render_html(_hand_built_report())
    assert "Reduced 5+ goal mismatches from 4 to 1 (-75%)." in rendered


def test_team_movement_renders_arrow_and_clubs():
    rendered = render_html(_hand_built_report())
    assert "FC Dallas 2012" in rendered
    assert "Super Elite" in rendered
    assert "Super Pro" in rendered
    assert "&rarr;" in rendered


def test_override_audit_collapsed_in_details():
    rendered = render_html(_hand_built_report())
    assert "<details" in rendered
    assert "accept_match" in rendered


def test_metric_value_rendering_formats():
    rendered = render_html(_hand_built_report())
    # rate=0.22 should render as 22%; rate=0.41 as 41%
    assert "22%" in rendered
    assert "41%" in rendered


def test_write_html_atomic(tmp_path: Path):
    rc = _hand_built_report()
    out = tmp_path / "comparison.html"
    written = write_html(rc, out)
    assert written == out
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>")
    # The intermediate ``.tmp`` file should not survive a successful write.
    assert not out.with_name(out.name + ".tmp").exists()


def test_no_streamlit_or_supabase_imports_at_runtime():
    """Reports module must not transitively import streamlit or supabase."""
    import sys

    # Force a fresh import of the reports package.
    for mod_name in list(sys.modules):
        if mod_name.startswith("src.tournaments.reports"):
            del sys.modules[mod_name]
    import src.tournaments.reports  # noqa: F401 — import for side effect

    assert "streamlit" not in sys.modules
    assert "supabase" not in sys.modules
