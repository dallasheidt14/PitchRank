"""
GotSport's /teams/{id}/matches answers 401 "Please log in" unless the request
carries ``past=true``, and then serves played games in a paginated
``{"matches", "pagination"}`` envelope. The fake below refuses what the live
endpoint refuses, so a request that drops ``past`` fails here as it does there.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List
from unittest.mock import MagicMock, Mock

import pytest
import requests

from src.scrapers.gotsport import GotSportScraper

TEAM_ID = 513807


def _match(day: str, match_id: int) -> Dict:
    return {
        "id": match_id,
        "match_date": f"{day}T10:00:00",
        "homeTeam": {"team_id": TEAM_ID, "full_name": "Home FC"},
        "awayTeam": {"team_id": 900000 + match_id, "full_name": f"Opponent {match_id}"},
        "home_score": 2,
        "away_score": 1,
        "competition_name": "League",
    }


class _FakeGotSport:
    """Serves ``matches`` the way the live endpoint does, recording each call's params."""

    def __init__(self, matches: List[Dict]):
        self.matches = matches
        self.calls: List[Dict[str, str]] = []

    def get(self, url, params=None, timeout=None):
        params = dict(params or {})
        if "/team_ranking_data/" in url:
            return self._response(200, {"club_name": "Home FC"})
        self.calls.append(params)
        if "past" not in params:
            return self._response(401, {"message": "Please log in"})
        per_page = int(params.get("per_page", 10))
        page = int(params.get("page", 1))
        total_pages = max(1, -(-len(self.matches) // per_page))
        chunk = self.matches[(page - 1) * per_page : page * per_page]
        return self._response(
            200,
            {
                "matches": chunk,
                "pagination": {
                    "current_page": page,
                    "total_pages": total_pages,
                    "total_entries": len(self.matches),
                    "per_page": per_page,
                },
            },
        )

    @staticmethod
    def _response(status: int, body) -> Mock:
        response = Mock()
        response.status_code = status
        response.headers = {"Server": "nginx"}
        response.raw = Mock(retries=None)
        response.json = Mock(return_value=body)
        if status >= 400:
            error = requests.exceptions.HTTPError(f"{status} Client Error")
            error.response = response
            response.raise_for_status = Mock(side_effect=error)
        else:
            response.raise_for_status = Mock()
        return response


def _scraper(fake: _FakeGotSport) -> GotSportScraper:
    scraper = GotSportScraper(MagicMock(), provider_code="gotsport")
    scraper.use_zenrows = False
    scraper.session = fake
    scraper.max_retries = 1
    scraper.retry_delay = 0
    scraper.delay_min = 0
    scraper.delay_max = 0
    return scraper


def test_request_sends_past_and_a_page_size():
    fake = _FakeGotSport([_match("2026-09-27", 1)])

    games = _scraper(fake).scrape_team_games(str(TEAM_ID), since_date=datetime(2026, 9, 1))

    assert len(games) == 1
    assert fake.calls == [{"past": "true", "per_page": "100", "page": "1"}]


def test_reads_games_from_the_paginated_envelope():
    fake = _FakeGotSport([_match("2026-09-27", 1), _match("2026-09-20", 2), _match("2026-09-13", 3)])

    games = _scraper(fake).scrape_team_games(str(TEAM_ID), since_date=datetime(2026, 9, 1))

    assert sorted(g.game_date for g in games) == ["2026-09-13", "2026-09-20", "2026-09-27"]


def test_follows_every_page(monkeypatch):
    monkeypatch.setattr("src.scrapers.gotsport.MATCHES_PER_PAGE", 2)
    fake = _FakeGotSport([_match(f"2026-09-{day:02d}", day) for day in (27, 26, 20, 19, 13)])

    games = _scraper(fake).scrape_team_games(str(TEAM_ID), since_date=datetime(2026, 9, 1))

    assert [call["page"] for call in fake.calls] == ["1", "2", "3"]
    assert len(games) == 5


def test_since_date_still_filters_client_side():
    fake = _FakeGotSport([_match("2026-09-27", 1), _match("2026-08-15", 2)])

    games = _scraper(fake).scrape_team_games(str(TEAM_ID), since_date=datetime(2026, 9, 1))

    assert [g.game_date for g in games] == ["2026-09-27"]
    assert "since_date" not in fake.calls[0]


def test_a_request_without_past_is_refused():
    """Pins the fake: dropping ``past`` must fail the way the live endpoint does."""
    fake = _FakeGotSport([_match("2026-09-27", 1)])

    with pytest.raises(requests.exceptions.HTTPError):
        fake.get("https://system.gotsport.com/api/v1/teams/1/matches", params={"page": "1"}).raise_for_status()
