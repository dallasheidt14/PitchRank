"""Unit tests for the drop counter in ``_parse_games_from_schedule_page``.

Verifies plan Step 3 contract: rows where home or away team can't be resolved
to a real API team ID are dropped (never shipped with reg_id as
``provider_team_id``), and ``drop_counter[0]`` is incremented for each drop.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.scrapers.gotsport import GotsportScraper

# Three games:
#   1. Both teams have direct /teams/{api_id} hrefs → resolves cleanly, ships.
#   2. Home has reg_id (Priority-4 path returns None), away resolves cleanly → drops.
#   3. Both have reg_ids that resolve to None → drops.
THREE_GAME_HTML = """
<html><body>
<table>
  <thead>
    <tr>
      <th>Match #</th>
      <th>Time</th>
      <th>Home Team</th>
      <th>Results</th>
      <th>Away Team</th>
      <th>Location</th>
      <th>Division</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>1</td>
      <td>Nov 28, 2025 4:00 PM HST</td>
      <td><a href="https://system.gotsport.com/teams/100001">Resolved Home FC</a></td>
      <td>2 - 1</td>
      <td><a href="https://system.gotsport.com/teams/100002">Resolved Away FC</a></td>
      <td>Field 1</td>
      <td>U14B</td>
    </tr>
    <tr>
      <td>2</td>
      <td>Nov 28, 2025 5:00 PM HST</td>
      <td><a href="/org_event/events/123/schedules?team=900001">Unresolved Home FC</a></td>
      <td>3 - 0</td>
      <td><a href="https://system.gotsport.com/teams/100002">Resolved Away FC</a></td>
      <td>Field 2</td>
      <td>U14B</td>
    </tr>
    <tr>
      <td>3</td>
      <td>Nov 28, 2025 6:00 PM HST</td>
      <td><a href="/org_event/events/123/schedules?team=900003">Unresolved Home FC 2</a></td>
      <td>1 - 1</td>
      <td><a href="/org_event/events/123/schedules?team=900004">Unresolved Away FC</a></td>
      <td>Field 3</td>
      <td>U14B</td>
    </tr>
  </tbody>
</table>
</body></html>
"""


def _make_scraper_with_html(html: str):
    """Build a barebones scraper instance via __new__ so __init__'s heavy setup
    (Supabase providers lookup, nested scraper init) is skipped. Set only the
    attrs the parser path reads."""
    scraper = GotsportScraper.__new__(GotsportScraper)
    response = MagicMock()
    response.text = html
    response.raise_for_status.return_value = None

    session = MagicMock()
    session.get.return_value = response

    scraper.session = session
    scraper.timeout = 30
    scraper.skip_team_id_resolution = False
    scraper.provider_code = "gotsport"
    # Resolver always returns None to exercise the drop path
    scraper._resolve_api_team_id_from_event_page = MagicMock(return_value=None)
    return scraper


def test_parser_drops_rows_with_unresolved_teams_and_increments_counter():
    scraper = _make_scraper_with_html(THREE_GAME_HTML)
    drop_counter = [0]

    games = scraper._parse_games_from_schedule_page(
        schedule_url="https://system.gotsport.com/org_event/events/123/schedules?group=1",
        event_id="123",
        event_name="Test Event",
        since_date=None,
        teams_by_name={},
        api_team_id_cache={},
        registration_to_api={},
        drop_counter=drop_counter,
    )

    # Game 1 ships from BOTH home and away perspectives (the parser emits two
    # GameData rows per match — see lines 2479+ in gotsport.py). Games 2 and 3
    # drop entirely.
    assert len(games) == 2, f"Expected 2 GameData rows (game 1 home + away), got {len(games)}: {games}"
    assert drop_counter[0] == 2, f"Expected drop_counter == 2, got {drop_counter[0]}"

    # Both shipped rows should reference resolved API team IDs (100001/100002),
    # never registration IDs.
    for game in games:
        assert game.team_id in {"100001", "100002"}, f"Unexpected team_id leaked: {game.team_id}"
        assert game.opponent_id in {"100001", "100002"}, f"Unexpected opponent_id leaked: {game.opponent_id}"


def test_parser_drop_counter_optional():
    """Calling without drop_counter must not crash — defaults to None and skips increment."""
    scraper = _make_scraper_with_html(THREE_GAME_HTML)
    games = scraper._parse_games_from_schedule_page(
        schedule_url="https://system.gotsport.com/org_event/events/123/schedules?group=1",
        event_id="123",
        event_name="Test Event",
        since_date=None,
        teams_by_name={},
        api_team_id_cache={},
        registration_to_api={},
    )
    assert len(games) == 2
