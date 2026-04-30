"""HTML coverage for ``gotsport_results_parser``.

Mirrors the match-table and standings-table structure observed on event
42433 group 365847 (U13 Boys Red): one ``<table>`` with ``Match #`` /
``Time`` / ``Home Team`` / ``Results`` / ``Away Team`` / ``Location`` /
``Division`` headers per day, and one standings table per pool with
``MP / W / L / D / GF / GA / GD / PTS`` columns.
"""

from __future__ import annotations

from src.scrapers.gotsport_results_parser import (
    parse_game_results_from_html,
    parse_standings_from_html,
)


def _match_row(
    *,
    match_id: str,
    home_id: str,
    home_name: str,
    away_id: str,
    away_name: str,
    score_text: str,
    date_text: str = "Feb 13, 2026",
    time_text: str = "5:00PM MST",
    division: str = "U13 Boys Red",
) -> str:
    score_inner = (
        f'<a href="/org_event/events/42433/schedules?group=365847&match={match_id}">{score_text}</a>'
        if match_id
        else score_text
    )
    return (
        "<tr>"
        f"<td>1</td>"
        f'<td>{date_text}<div class="text-color">{time_text}</div></td>'
        f'<td><a href="/org_event/events/42433/schedules?team={home_id}">{home_name}</a></td>'
        f"<td>{score_inner}</td>"
        f'<td><a href="/org_event/events/42433/schedules?team={away_id}">{away_name}</a></td>'
        '<td><a href="#">Reach 11 - Field 17</a></td>'
        f'<td><a href="#">{division}</a></td>'
        "</tr>"
    )


def _match_table_html(rows: list[str]) -> str:
    header = (
        "<tr>"
        "<th>Match #</th><th>Time</th><th>Home Team</th><th>Results</th>"
        "<th>Away Team</th><th>Location</th><th>Division</th>"
        "</tr>"
    )
    return f'<table class="table">{header}{"".join(rows)}</table>'


def test_parses_played_game_with_score():
    html = _match_table_html(
        [
            _match_row(
                match_id="23807543",
                home_id="3661033",
                home_name="AZ Arsenal ECNL B13",
                away_id="3717735",
                away_name="Phoenix United 2014 Elite",
                score_text="0 - 1",
            )
        ]
    )
    games = parse_game_results_from_html(html)
    assert len(games) == 1
    g = games[0]
    assert g.match_id == "23807543"
    assert g.home_provider_team_id == "3661033"
    assert g.away_provider_team_id == "3717735"
    assert g.home_score == 0
    assert g.away_score == 1
    assert g.date_text == "Feb 13, 2026"
    assert "5:00PM" in g.time_text
    assert g.division_label == "U13 Boys Red"
    assert g.location == "Reach 11 - Field 17"


def test_parses_unplayed_game_with_no_score():
    """TBD / pre-tournament games have an empty score cell — match_id may
    or may not be present, but home/away IDs are. Only games with a
    match_id are emitted (no match_id = nothing to dedupe on)."""
    html = _match_table_html(
        [
            _match_row(
                match_id="9001",
                home_id="100",
                home_name="A",
                away_id="200",
                away_name="B",
                score_text="",
            )
        ]
    )
    games = parse_game_results_from_html(html)
    assert len(games) == 1
    assert games[0].home_score is None
    assert games[0].away_score is None


def test_parses_multidigit_scores():
    html = _match_table_html(
        [
            _match_row(
                match_id="9002",
                home_id="100",
                home_name="A",
                away_id="200",
                away_name="B",
                score_text="13 - 16",
            )
        ]
    )
    games = parse_game_results_from_html(html)
    assert games[0].home_score == 13
    assert games[0].away_score == 16


def test_skips_rows_with_missing_team_id():
    """Placeholder / TBD pairings (no team links) aren't real games."""
    html = (
        "<table>"
        "<tr><th>Match #</th><th>Time</th><th>Home Team</th><th>Results</th>"
        "<th>Away Team</th><th>Location</th><th>Division</th></tr>"
        '<tr><td>1</td><td>Feb 16</td><td>TBD</td>'
        '<td><a href="/org_event/events/42433/schedules?match=9999">0 - 0</a></td>'
        "<td>TBD</td><td></td><td>U13 Boys Red</td></tr>"
        "</table>"
    )
    games = parse_game_results_from_html(html)
    assert games == []


def test_dedupe_across_match_tables_via_caller_match_id():
    """Two tables on the same page each containing the same match_id —
    the caller dedupes by match_id; the parser emits both, so per-event
    callers must ``dict-by-match_id`` (which is what the enricher does)."""
    row = _match_row(
        match_id="42",
        home_id="1",
        home_name="A",
        away_id="2",
        away_name="B",
        score_text="2 - 1",
    )
    html = _match_table_html([row]) + _match_table_html([row])
    games = parse_game_results_from_html(html)
    assert len(games) == 2
    assert games[0].match_id == games[1].match_id == "42"


def test_returns_empty_when_no_match_table():
    html = "<html><body><h1>Schedule</h1></body></html>"
    assert parse_game_results_from_html(html) == []


def _standings_table_html(rows: list[tuple[int, str, str, list[str]]]) -> str:
    header = (
        "<tr>"
        "<th></th><th>Team</th>"
        "<th>MP</th><th>W</th><th>L</th><th>D</th>"
        "<th>GF</th><th>GA</th><th>GD</th><th>PTS</th>"
        "</tr>"
    )
    body = ""
    for rank, team_id, team_name, stats in rows:
        cells = "".join(f"<td>{s}</td>" for s in stats)
        body += (
            f"<tr><td>{rank}</td>"
            f'<td><a href="/org_event/events/42433/schedules?team={team_id}">{team_name}</a></td>'
            f"{cells}</tr>"
        )
    return f"<table>{header}{body}</table>"


def test_parses_standings_with_full_stat_line():
    html = _standings_table_html(
        [
            (1, "100", "Rush Soccer", ["3", "2", "0", "1", "9", "2", "7", "7"]),
            (2, "200", "Phoenix United", ["3", "2", "0", "1", "7", "1", "5", "7"]),
            (3, "300", "AZ Arsenal", ["3", "1", "2", "0", "5", "7", "-2", "3"]),
        ]
    )
    standings = parse_standings_from_html(html)
    assert [s.rank for s in standings] == [1, 2, 3]
    assert standings[0].provider_team_id == "100"
    assert standings[0].matches_played == 3
    assert standings[0].wins == 2
    assert standings[0].goal_diff == 7
    assert standings[0].points == 7
    assert standings[2].goal_diff == -2


def test_standings_returns_empty_when_no_pts_table():
    html = "<table><tr><th>Match #</th></tr></table>"
    assert parse_standings_from_html(html) == []
