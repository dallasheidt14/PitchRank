"""A null opponent team_id from the GotSport API must parse to an empty id, not "None".

``str(opponent.get("team_id", ""))`` fills the default only for a missing key, so a present
``null`` becomes ``"None"``. The game parses either way, so only the opponent id shows the defect.
"""

from datetime import date
from unittest.mock import MagicMock

from src.scrapers.gotsport import GotSportScraper


def _scraper() -> GotSportScraper:
    scraper = GotSportScraper(MagicMock(), provider_code="gotsport")
    scraper.session = MagicMock()
    return scraper


def _match(away_team_id):
    return {
        "homeTeam": {"team_id": 111, "full_name": "Home FC"},
        "awayTeam": {"team_id": away_team_id, "full_name": "Visitors", "club": {"name": "Visitors FC"}},
        "match_date": "2026-09-01",
        "home_score": 2,
        "away_score": 1,
        "venue": {"name": "Field 1"},
        "competition_name": "League",
        "division_name": "",
        "event_name": "",
    }


def test_null_opponent_id_parses_to_empty():
    scraper = _scraper()

    game = scraper._parse_api_match(_match(None), 111, date(2020, 1, 1))

    assert game is not None
    assert game.opponent_id == ""
    scraper.session.get.assert_not_called()


def test_real_opponent_id_is_kept():
    scraper = _scraper()

    game = scraper._parse_api_match(_match(98765), 111, date(2020, 1, 1))

    assert game is not None
    assert game.opponent_id == "98765"
    scraper.session.get.assert_not_called()
