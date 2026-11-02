"""A same-day rematch carries GotSport's match id; every other game carries none.

Two meetings of one pair on one date (a pool game and a final) are told apart only by the match
``id`` GotSport gives each. The scraper reads that over the team's whole match list, before its
30-match cap, and puts the id on each such game as ``schedule_id`` for the importer's key and uid.
"""

from datetime import datetime

import pytest

from src.scrapers.gotsport import GotSportScraper
from tests.unit.test_gotsport_team_matches_request import TEAM_ID, _FakeGotSport, _scraper

OPPONENT = 250383


def _meeting(match_id, day="2026-10-11", home=TEAM_ID, away=OPPONENT, home_score=1, away_score=0):
    return {
        "id": match_id,
        "match_date": f"{day}T10:00:00",
        "homeTeam": {"team_id": home, "full_name": f"Team {home}"},
        "awayTeam": {"team_id": away, "full_name": f"Team {away}"},
        "home_score": home_score,
        "away_score": away_score,
        "competition_name": "Tournament",
    }


def test_two_meetings_of_one_pair_on_one_date_are_both_marked():
    matches = [_meeting(27873104), _meeting(27873025, home_score=0)]

    assert GotSportScraper._repeat_day_match_ids(matches) == {"27873104", "27873025"}


def test_the_same_score_with_home_and_away_swapped_is_still_two_meetings():
    matches = [
        _meeting(27672820, home=254874, away=76940, home_score=4, away_score=2),
        _meeting(27672821, home=76940, away=254874, home_score=2, away_score=4),
    ]

    assert GotSportScraper._repeat_day_match_ids(matches) == {"27672820", "27672821"}


def test_a_meeting_still_to_be_scored_marks_the_day():
    matches = [_meeting(1), _meeting(2, home_score=None, away_score=None)]

    assert GotSportScraper._repeat_day_match_ids(matches) == {"1", "2"}


def test_both_teams_lists_mark_the_same_games():
    pool, final = _meeting(27873104), _meeting(27873025, home_score=0)
    team_list = [_meeting(10, day="2026-10-03", away=111), pool, final]
    opponent_list = [final, _meeting(20, day="2026-10-04", home=OPPONENT, away=222), pool]

    assert GotSportScraper._repeat_day_match_ids(team_list) == {"27873104", "27873025"}
    assert GotSportScraper._repeat_day_match_ids(opponent_list) == {"27873104", "27873025"}


@pytest.mark.parametrize(
    "matches",
    [
        pytest.param([_meeting(1)], id="one-meeting"),
        pytest.param([_meeting(1, day="2026-10-10"), _meeting(2)], id="different-dates"),
        pytest.param([_meeting(1), _meeting(2, away=999)], id="different-opponents"),
        pytest.param([_meeting(1), _meeting(1)], id="one-match-listed-twice"),
    ],
)
def test_anything_short_of_two_meetings_marks_nothing(matches):
    assert GotSportScraper._repeat_day_match_ids(matches) == set()


def _without_away_team(match):
    return {key: value for key, value in match.items() if key != "awayTeam"}


@pytest.mark.parametrize(
    "matches",
    [
        pytest.param([_meeting(1), _meeting(None)], id="null-match-id"),
        pytest.param([_meeting(1), _meeting("27873104.0")], id="non-digit-match-id"),
        pytest.param([_meeting(1, away=None), _meeting(2, away=None)], id="null-opponent-id"),
        pytest.param([_without_away_team(_meeting(1)), _without_away_team(_meeting(2))], id="missing-away-team"),
        pytest.param(
            [{**_meeting(1), "match_date": "not a date"}, {**_meeting(2), "match_date": "not a date"}],
            id="unparseable-date",
        ),
        pytest.param([None, _meeting(1)], id="not-a-match"),
    ],
)
def test_an_unreadable_match_is_left_out_without_failing(matches):
    assert GotSportScraper._repeat_day_match_ids(matches) == set()


def test_the_cap_does_not_hide_a_repeat_day():
    """The two meetings sort 30th and 31st, so only one is parsed, and it must still carry its id."""
    later = [_meeting(100 + day, day=f"2026-10-{day:02d}", away=300 + day) for day in range(1, 30)]
    meetings = [_meeting(27873104, day="2026-09-27"), _meeting(27873025, day="2026-09-27", home_score=0)]

    games = _scraper(_FakeGotSport(later + meetings)).scrape_team_games(str(TEAM_ID), since_date=datetime(2026, 9, 1))

    assert len(games) == 30
    [repeat] = [g for g in games if g.game_date == "2026-09-27"]
    assert repeat.meta["schedule_id"] == "27873104"
    assert [g for g in games if "schedule_id" in g.meta] == [repeat]


@pytest.mark.parametrize(
    ("pool_kickoff", "final_kickoff"),
    [
        pytest.param("2026-10-11T02:00:00Z", "2026-10-11T17:00:00Z", id="utc-z"),
        pytest.param("2026-10-10T20:00:00-07:00", "2026-10-11T17:00:00Z", id="offset-crossing-midnight"),
        pytest.param("2026-10-11", "2026-10-11", id="date-only"),
    ],
)
def test_the_stored_date_and_the_repeat_day_agree_on_real_timestamps(pool_kickoff, final_kickoff):
    """The day a game is stored under is the day it is grouped under, whatever offset the timestamp carries.

    The cutoff is that day itself, so the scrape loop's early date check is held to the same day too.
    """
    pool = {**_meeting(27873104), "match_date": pool_kickoff}
    final = {**_meeting(27873025, home_score=0), "match_date": final_kickoff}

    games = _scraper(_FakeGotSport([pool, final])).scrape_team_games(str(TEAM_ID), since_date=datetime(2026, 10, 11))

    assert sorted((g.game_date, g.meta["schedule_id"]) for g in games) == [
        ("2026-10-11", "27873025"),
        ("2026-10-11", "27873104"),
    ]


def test_the_import_row_carries_the_id_only_on_a_repeat_day():
    matches = [_meeting(27873104), _meeting(27873025, home_score=0), _meeting(27042295, day="2026-10-03", away=111)]
    scraper = _scraper(_FakeGotSport(matches))

    games = scraper.scrape_team_games(str(TEAM_ID), since_date=datetime(2026, 9, 1))
    rows = [scraper._game_data_to_dict(g, str(TEAM_ID)) for g in games]

    assert {(r["game_date"], r["goals_for"], r["goals_against"]): r["schedule_id"] for r in rows} == {
        ("2026-10-11", 1, 0): "27873104",
        ("2026-10-11", 0, 0): "27873025",
        ("2026-10-03", 1, 0): "",
    }
