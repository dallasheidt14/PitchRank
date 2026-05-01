"""HTML-only coverage for ``gotsport_pool_parser.parse_pool_assignments_from_html``.

Mirrors the standings-panel structure observed on event 42433 group 365847
(U13 Boys Red): one ``<a role="button">Bracket {label}</a>`` heading per
pool, ``aria-controls`` pointing at a sibling ``<div id="collapse-{id}">``
panel containing the standings table.
"""

from __future__ import annotations

from src.scrapers.gotsport_pool_parser import (
    PoolAssignment,
    parse_pool_assignments_from_html,
)


def _panel_html(panel_id: str, team_ids: list[str]) -> str:
    rows = "".join(
        f'<tr><td>{i+1}</td><td>'
        f'<a href="/org_event/events/42433/schedules?team={tid}">Team {tid}</a>'
        f"</td></tr>"
        for i, tid in enumerate(team_ids)
    )
    return (
        f'<div id="{panel_id}" class="panel-collapse collapse in" role="tabpanel">'
        f'<table class="table"><tbody>{rows}</tbody></table>'
        f"</div>"
    )


def _heading_html(label: str, panel_id: str) -> str:
    return f'<a role="button" aria-controls="{panel_id}" href="#{panel_id}">Bracket {label}</a>'


def test_parses_two_pools_each_with_four_teams():
    html = (
        "<html><body>"
        + _heading_html("A", "collapse-501350")
        + _heading_html("B", "collapse-501351")
        + _panel_html("collapse-501350", ["3194980", "3717735", "3661033", "3551475"])
        + _panel_html("collapse-501351", ["3637057", "3527908", "3717349", "3625878"])
        + "</body></html>"
    )
    pools = parse_pool_assignments_from_html(html)
    assert pools == [
        PoolAssignment(
            label="A",
            bracket_id="501350",
            provider_team_ids=("3194980", "3717735", "3661033", "3551475"),
        ),
        PoolAssignment(
            label="B",
            bracket_id="501351",
            provider_team_ids=("3637057", "3527908", "3717349", "3625878"),
        ),
    ]


def test_dedupes_per_day_schedule_anchors_pointing_at_same_panel():
    """Per-day schedule sections (``"Bracket A | Feb 13, 2026"``) re-use the
    standings panel id but must NOT produce a second pool entry."""
    html = (
        "<html><body>"
        + _heading_html("A", "collapse-1")
        + '<a role="button" aria-controls="collapse-1">Bracket A | Feb 13, 2026</a>'
        + '<a role="button" aria-controls="collapse-1">Bracket A | Feb 14, 2026</a>'
        + _panel_html("collapse-1", ["100", "101", "102"])
        + "</body></html>"
    )
    pools = parse_pool_assignments_from_html(html)
    assert len(pools) == 1
    assert pools[0].label == "A"
    assert pools[0].team_count == 3


def test_drops_pools_with_no_team_rows():
    """Aggregate / placeholder panels (no team links) are skipped — only
    standings panels with actual rows count as pools."""
    html = (
        "<html><body>"
        + _heading_html("A", "collapse-1")
        + _heading_html("B", "collapse-2")
        + _panel_html("collapse-1", ["100", "101"])
        + '<div id="collapse-2" class="panel-collapse"></div>'
        + "</body></html>"
    )
    pools = parse_pool_assignments_from_html(html)
    assert len(pools) == 1
    assert pools[0].label == "A"


def test_returns_empty_for_page_with_no_bracket_headings():
    """Knockout-only tier (no round-robin pool play): empty list."""
    html = "<html><body><h1>Schedule</h1><p>No pool play.</p></body></html>"
    assert parse_pool_assignments_from_html(html) == []


def test_preserves_team_id_order_for_finishing_position():
    """Row order on the page is finishing order for completed events;
    callers downstream rely on it for backtest seeding analysis."""
    html = (
        "<html><body>"
        + _heading_html("A", "collapse-1")
        + _panel_html("collapse-1", ["999", "111", "555"])
        + "</body></html>"
    )
    pools = parse_pool_assignments_from_html(html)
    assert pools[0].provider_team_ids == ("999", "111", "555")
