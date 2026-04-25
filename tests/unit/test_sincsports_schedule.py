"""Unit tests for the SincSports schedule.aspx parser.

Scope follows the repo convention: pure-function parser tests against
committed fixtures, no HTTP mocking. Live fetch is exercised by the
operator dry-run on the driver script.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.scrapers.sincsports_schedule import (
    parse_division,
    parse_tournament_index,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sincsports_events"


@pytest.fixture
def puri_u14f01_html() -> str:
    return (FIXTURES / "schedule_puri_u14f01.html").read_text(encoding="utf-8")


class TestParseTournamentIndex:
    def test_extracts_div_codes_from_root(self, puri_u14f01_html):
        # The fixture is a single division page; its own div code is referenced
        # from the URL. Live tournament-root pages reference all 60 divisions —
        # that path is exercised by the live operator dry-run.
        codes = parse_tournament_index(puri_u14f01_html)
        assert "U14F01" in codes

    def test_drops_n_sentinel(self):
        html = "<a href='?div=U14F01'>x</a> <a href='?div=N'>x</a>"
        codes = parse_tournament_index(html)
        assert "U14F01" in codes
        assert "N" not in codes

    def test_empty_html_returns_empty(self):
        assert parse_tournament_index("") == []
        assert parse_tournament_index("<html></html>") == []

    def test_codes_uppercased_and_sorted(self):
        html = "<a href='?div=u14f02'>a</a> <a href='?div=U14F01'>b</a>"
        codes = parse_tournament_index(html)
        assert codes == ["U14F01", "U14F02"]


class TestParseDivision:
    def test_puri_u14f01_extracts_all_games(self, puri_u14f01_html):
        games = parse_division(puri_u14f01_html, "TZ2565", "U14F01")
        # The Puri Cup U14F01 division is a 6-team round-robin: 9 games.
        assert len(games) == 9

    def test_each_game_has_team_ids_and_perspective(self, puri_u14f01_html):
        games = parse_division(puri_u14f01_html, "TZ2565", "U14F01")
        for g in games:
            assert g.tournament_id == "TZ2565"
            assert g.division_code == "U14F01"
            assert g.home_id and g.away_id
            assert g.home_id != g.away_id
            assert g.home_id.upper() == g.home_id
            assert g.away_id.upper() == g.away_id
            assert g.home_name and g.away_name

    def test_played_games_have_scores(self, puri_u14f01_html):
        games = parse_division(puri_u14f01_html, "TZ2565", "U14F01")
        played = [g for g in games if g.status == "Played"]
        assert len(played) >= 5  # 7 played + 2 cancelled in this division
        for g in played:
            assert g.home_score is not None
            assert g.away_score is not None
            assert 0 <= g.home_score <= 30
            assert 0 <= g.away_score <= 30

    def test_cancelled_games_have_no_scores(self, puri_u14f01_html):
        games = parse_division(puri_u14f01_html, "TZ2565", "U14F01")
        cancelled = [g for g in games if g.status == "Cancelled"]
        assert len(cancelled) == 2
        for g in cancelled:
            assert g.home_score is None
            assert g.away_score is None

    def test_known_game_extracted_correctly(self, puri_u14f01_html):
        """Spot-check #00242 — FC America 1, OSC 3 on 4/18/2026."""
        games = parse_division(puri_u14f01_html, "TZ2565", "U14F01")
        match = [g for g in games if g.game_num == "00242"]
        assert len(match) == 1
        g = match[0]
        assert g.home_id == "IAF12039"
        assert g.away_id == "WIF12063"
        assert g.home_score == 1
        assert g.away_score == 3
        assert g.status == "Played"
        assert g.date == "4/18/2026"
        assert "FC America" in g.home_name
        assert "OSC" in g.away_name

    def test_division_name_extracted(self, puri_u14f01_html):
        games = parse_division(puri_u14f01_html, "TZ2565", "U14F01")
        with_name = [g for g in games if g.division_name]
        assert len(with_name) > 0
        # Heading is "Under 14 Girls First Division.- Crossover" or similar
        assert any("Under 14" in (g.division_name or "") for g in games)

    def test_empty_html_returns_no_games(self):
        assert parse_division("", "TZ2565", "U14F01") == []
        assert parse_division("<html></html>", "TZ2565", "U14F01") == []

    def test_no_team_links_skipped(self):
        """Cards with empty hometeam/awayteam divs are dropped silently."""
        html = (
            "<div class='form-row game-row'>"
            "<div class='col-md-3 d-cell'><span>Saturday</span><span>4/18/2026</span><span>10:40 AM</span><span>#999</span></div>"
            "<div class='col-md-5'><div class='hometeam'></div><div class='awayteam'></div></div>"
            "</div>"
        )
        assert parse_division(html, "TZ2565", "ZZZ") == []
