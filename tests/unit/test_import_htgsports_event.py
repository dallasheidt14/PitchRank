"""Unit tests for scripts/import_htgsports_event.py.

The fixtures under tests/fixtures/htgsports/ are the API's answers for the 2026 Children's Mercy
Heartland Invitational - Boys (event 14130) as served on 2026-11-09: the event summary, six of its
divisions, and the standings and games of U12 Boys Blue and U10 Boys Blue. Every phone and manager
field is blanked and every coach renamed "Coach <n>"; the repo is public.
"""

import csv
import json
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from scripts import import_htgsports_event as htg
from scripts import import_tourneycentral_event as tc
from src.etl.enhanced_pipeline import rematch_game_uid
from src.models.game_matcher import REMATCH_PROVIDERS, SCHEDULE_ID_SUFFIX_PROVIDERS, GameHistoryMatcher

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "htgsports"
EVENT_ID = "14130"
SEASON = 2026
TODAY = date(2026, 11, 9)
U12_BLUE = "54981"
U10_BLUE = "54958"
COLUMBIA = "652207"
PLACEHOLDER_TOKEN = "00000000-0000-0000-0000-000000000000"
OTHER_TOKEN = "ABCDEF01-2345-6789-ABCD-EF0123456789"
CONFLICTING_TOKEN = "11111111-1111-1111-1111-111111111111"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _ApiFetcher:
    """Stands in for ``fetch_api``: every path of the run comes from a fixture, and a division
    with no fixture answers with no teams and no games."""

    FILES = {
        f"eventSummary2/{EVENT_ID}": "event_summary.json",
        f"divisions/{EVENT_ID}": "divisions.json",
        f"standings/{EVENT_ID}/{U12_BLUE}/false": "standings_u12_boys_blue.json",
        f"GamesForDivision/{EVENT_ID}/{U12_BLUE}": "games_u12_boys_blue.json",
        f"standings/{EVENT_ID}/{U10_BLUE}/false": "standings_u10_boys_blue.json",
        f"GamesForDivision/{EVENT_ID}/{U10_BLUE}": "games_u10_boys_blue.json",
    }

    def __init__(self, fail_on=None, answers=None):
        self.paths = []
        self.fail_on = fail_on
        self.answers = answers or {}

    def __call__(self, path):
        self.paths.append(path)
        if self.fail_on and self.fail_on in path:
            raise htg.ScrapeFetchError(f"HTTP 503 for {path}")
        if path in self.answers:
            return self.answers[path]
        if path in self.FILES:
            return _fixture(self.FILES[path])
        return []


def _collect(fetcher=None, board_season=SEASON, days_back=30, **options):
    return htg.collect_event(fetcher or _ApiFetcher(), EVENT_ID, board_season, days_back, TODAY, **options)


def _by_name(rows):
    return {row.team_name: row for row in rows}


# ── Network ────────────────────────────────────────────────────────────────────


class _Response:
    """A requests response: raw bytes, and a content type that may carry no charset."""

    def __init__(self, status_code, body=b"[]", content_type="application/json"):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.content = body
        self.encoding = requests.utils.get_encoding_from_headers(self.headers)

    @property
    def text(self):
        return self.content.decode(self.encoding or "utf-8", errors="replace")


class _Session:
    """Records every request's URL and keyword arguments, and keeps session-level headers as
    requests does, so a token written onto the session shows up here."""

    def __init__(self, responses):
        self.responses = responses
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.responses[url] if isinstance(self.responses, dict) else self.responses
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


INDEX_PAGE = b'<html><head><script src="/app/main.js?260326091857" type="text/javascript"></script></head></html>'
BUNDLE = (
    'var k=Ro;I.a.defaults.baseURL=eo()+"api/";I.a.defaults.headers.common["HTGSports-Token"]="'
    + PLACEHOLDER_TOKEN
    + '";var Vo=I.a.create({baseURL:eo()+"api/",headers:{"HTGSports-Token":"'
    + PLACEHOLDER_TOKEN
    + '"}});'
).encode("utf-8")
PAGE_URL = f"https://events.htgsports.net/?eventid={EVENT_ID}"
BUNDLE_URL = "https://events.htgsports.net/app/main.js?260326091857"


def _token_session(bundle=BUNDLE, page=INDEX_PAGE):
    return _Session(
        {PAGE_URL: _Response(200, page, "text/html"), BUNDLE_URL: _Response(200, bundle, "application/javascript")}
    )


class TestParseEventUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://events.htgsports.net/?eventid=14130#/scheduleresults",
            "https://events.htgsports.net/?eventid=14130",
            "https://EVENTS.htgsports.net/?eventid=14130#/scheduleresults/54981",
            "http://events.htgsports.net?eventid=14130",
            "https://events.htgsports.net/?lang=en&eventid=14130",
        ],
    )
    def test_any_page_of_the_event_yields_its_id(self, url):
        assert htg.parse_event_url(url) == "14130"

    @pytest.mark.parametrize(
        "url",
        [
            "https://events.htgsports.net.evil.test/?eventid=14130",
            "https://example.com/?eventid=14130",
            "https://events.htgsports.net/?eventid=١٤١٣٠",
            "https://events.htgsports.net/?eventid=014130",
            "https://events.htgsports.net/?eventid=14130x",
            "https://events.htgsports.net/eventlist",
            "events.htgsports.net/?eventid=14130",
            "",
        ],
    )
    def test_anything_else_is_refused(self, url):
        with pytest.raises(ValueError):
            htg.parse_event_url(url)


class TestReadApiToken:
    def test_the_token_is_read_from_the_bundle_the_event_page_loads(self):
        session = _token_session()

        assert htg.read_api_token(session, EVENT_ID) == PLACEHOLDER_TOKEN
        assert [url for url, _ in session.calls] == [PAGE_URL, BUNDLE_URL]

    @pytest.mark.parametrize(
        "line",
        [
            '.headers.common["HTGSports-Token"]="{t}";',
            'headers:{{"HTGSports-Token":"{t}"}}',
            "headers:{{'HTGSports-Token': '{t}'}}",
        ],
    )
    def test_each_way_the_bundle_writes_it_is_read(self, line):
        bundle = line.format(t=OTHER_TOKEN).encode("utf-8")

        assert htg.read_api_token(_token_session(bundle), EVENT_ID) == OTHER_TOKEN

    def test_a_bundle_served_from_another_host_is_not_read(self):
        page = b'<html><head><script src="https://cdn.example.test/app/main.js?1"></script></head></html>'

        with pytest.raises(htg.ScrapeFetchError, match="no app bundle"):
            htg.read_api_token(_token_session(page=page), EVENT_ID)

    def test_a_page_that_loads_no_bundle_raises(self):
        with pytest.raises(htg.ScrapeFetchError, match="no app bundle"):
            htg.read_api_token(_token_session(page=b"<html><body>maintenance</body></html>"), EVENT_ID)

    def test_a_bundle_with_no_token_raises(self):
        with pytest.raises(htg.ScrapeFetchError, match="no HTGSports-Token"):
            htg.read_api_token(_token_session(b"var a=1;"), EVENT_ID)

    def test_a_bundle_with_two_different_tokens_raises(self):
        bundle = BUNDLE.replace(PLACEHOLDER_TOKEN.encode(), CONFLICTING_TOKEN.encode(), 1)

        with pytest.raises(htg.ScrapeFetchError, match="conflicting"):
            htg.read_api_token(_token_session(bundle), EVENT_ID)


class TestFetchApi:
    URL = f"https://events.htgsports.net/api/divisions/{EVENT_ID}"

    def test_the_token_rides_on_the_api_request_alone(self):
        session = _Session(_Response(200, b"[]"))

        htg.fetch_api(session, "tok", f"divisions/{EVENT_ID}")

        [(url, kwargs)] = session.calls
        assert url == self.URL
        assert kwargs["params"] == {"format": "json"}
        assert kwargs["headers"] == {"HTGSports-Token": "tok", "Accept": "application/json"}
        assert kwargs["timeout"] == 90
        assert kwargs["allow_redirects"] is False
        assert session.headers == {}

    def test_the_real_session_carries_no_token_and_retries_server_errors_only(self):
        session = htg.make_session()

        assert not any("token" in key.lower() for key in session.headers)
        retries = session.get_adapter("https://events.htgsports.net").max_retries
        assert (retries.total, retries.backoff_factor) == (2, 1)
        assert sorted(retries.status_forcelist) == [500, 502, 503, 504]

    @pytest.mark.parametrize("status", [204, 302, 401, 404, 500])
    def test_anything_but_a_200_raises_and_a_redirect_is_never_followed(self, status):
        """A call without its token is answered 204 No Content, which must not read as no data."""
        with pytest.raises(htg.ScrapeFetchError, match=f"HTTP {status}"):
            htg.fetch_api(_Session(_Response(status)), "tok", f"divisions/{EVENT_ID}")

    @pytest.mark.parametrize("body", [b"", b"  \n"])
    def test_an_empty_body_raises(self, body):
        with pytest.raises(htg.ScrapeFetchError, match="empty response"):
            htg.fetch_api(_Session(_Response(200, body)), "tok", f"divisions/{EVENT_ID}")

    def test_a_page_instead_of_json_raises(self):
        with pytest.raises(htg.ScrapeFetchError, match="non-JSON"):
            htg.fetch_api(_Session(_Response(200, b"<html></html>", "text/html")), "tok", "divisions/1")

    def test_a_transport_error_raises(self):
        with pytest.raises(htg.ScrapeFetchError, match="request failed"):
            htg.fetch_api(_Session(requests.ConnectionError("reset")), "tok", "divisions/1")

    def test_a_name_with_accents_is_read_from_the_bytes_whatever_the_declared_charset(self):
        """requests reads a text body with no charset as ISO-8859-1, which would mangle this name."""
        body = json.dumps([{"Name": "Club Atlético U12"}], ensure_ascii=False).encode("utf-8")
        response = _Response(200, body, "text/plain")

        assert response.text != body.decode("utf-8")
        assert htg.fetch_api(_Session(response), "tok", "divisions/1") == [{"Name": "Club Atlético U12"}]


# ── Event, divisions, teams and games ──────────────────────────────────────────


class TestParseEventSummary:
    def test_the_event_is_named_and_dated_by_its_summary(self):
        event = htg.parse_event_summary(_fixture("event_summary.json"), EVENT_ID)

        assert event.name == "2026 Children's Mercy Heartland Invitational Tournament - Boys"
        assert (event.start, event.end, event.season) == (date(2026, 11, 6), date(2026, 11, 8), 2026)
        assert (event.host, event.subdomain) == ("events.htgsports.net", "htg14130")

    @pytest.mark.parametrize(
        "data",
        [
            None,
            [],
            {"Name": "", "StartDateAsString": "11/6/2026", "EndDateAsString": "11/8/2026"},
            {"Name": "X", "StartDateAsString": "", "EndDateAsString": "11/8/2026"},
            {"Name": "X", "StartDateAsString": "2026-11-06", "EndDateAsString": "11/8/2026"},
        ],
    )
    def test_a_summary_without_a_name_or_dates_raises(self, data):
        with pytest.raises(htg.ScrapeFetchError):
            htg.parse_event_summary(data, EVENT_ID)


def _division_item(name, size="9v9", division_id=54981, publish=True):
    return {"Name": name, "Id": division_id, "SizeDescr": size, "Publish": publish}


class TestParseDivision:
    @pytest.mark.parametrize(
        "name, size, expected",
        [
            ("U12 Boys Blue (2014/15) 9v9", "9v9", ("Male", 12, 12, 9)),
            ("U10 Girls Red (17/18) 7v7", "7v7", ("Female", 10, 10, 7)),
            ("U14/15 Girls Green (2012/13) 11v11", "11v11", ("Female", 14, 15, 11)),
            ("U18/19 Girls Red (2007/08) 11v11", "11v11", ("Female", 18, 19, 11)),
            ("High School Boys Blue 11v11", "11v11", ("Male", 15, 19, 11)),
            ("U08 Boys Red (2018/19) 7v7", "7v7", ("Male", 8, 8, 7)),
            ("U12 Boys Black (2014/15) 9v9", "", ("Male", 12, 12, None)),
        ],
    )
    def test_a_name_gives_gender_ages_and_the_size_gives_the_format(self, name, size, expected):
        division_id, division = htg.parse_division(_division_item(name, size))

        assert division_id == "54981"
        assert division.code == name
        assert (division.gender, division.young_age, division.old_age, division.players) == expected

    @pytest.mark.parametrize(
        "name", ["Adult Men Open", "U14/16 Girls Red", "U20 Boys", "Boys U12 Red", "U١٢ Boys Red", "U12 Coed", ""]
    )
    def test_a_name_of_another_shape_is_refused(self, name):
        assert htg.parse_division(_division_item(name)) is None

    @pytest.mark.parametrize("division_id", [True, None, 0, -5, 54981.0, "054981", "٥٤٩٨١", 12345678901])
    def test_a_division_id_that_is_not_plain_digits_is_refused(self, division_id):
        assert htg.parse_division(_division_item("U12 Boys Blue (2014/15) 9v9", division_id=division_id)) is None

    def test_a_division_id_sent_as_text_is_read_as_the_same_id(self):
        """Team ids are read the same way, so one rule covers every id the API sends."""
        division_id, _ = htg.parse_division(_division_item("U12 Boys Blue (2014/15) 9v9", division_id="54981"))

        assert division_id == "54981"

    @pytest.mark.parametrize(
        "name, size, reason",
        [
            ("U08 Boys Red (2018/19) 7v7", "7v7", "U9 and below: no board"),
            ("U09 Girls Red (2017/18) 7v7", "7v7", "U9 and below: no board"),
            ("U10 Boys Blue (2016/17) 4v4", "4v4", "small-sided"),
            ("U10 Boys Blue (2016/17) 7v7", "7v7", None),
        ],
    )
    def test_a_division_with_no_board_or_of_small_sided_play_is_skipped(self, name, size, reason):
        _, division = htg.parse_division(_division_item(name, size))

        assert htg.skip_division(division) == reason


def _u12_blue():
    return htg.parse_division(_division_item("U12 Boys Blue (2014/15) 9v9"))[1]


class TestParseStandings:
    def test_every_team_carries_its_id_name_club_location_and_coach(self):
        listings, problems = htg.parse_standings(_fixture("standings_u12_boys_blue.json"), _u12_blue(), "u")

        assert problems == []
        assert len(listings) == 8
        columbia = {t.tc_team_id: t for t in listings}[COLUMBIA]
        assert (columbia.team_name, columbia.club, columbia.location, columbia.coach) == (
            "Sporting Columbia 14/15B Navy",
            "Sporting Columbia",
            "Columbia, MO",
            "Coach 4",
        )

    def test_phone_numbers_and_the_manager_are_never_read(self):
        row = {
            "Id": 1,
            "Name": "A U12",
            "ClubName": "A",
            "Location": "Overland Park, KS",
            "Coach": "Pat Coach",
            "CoachCellPhone": "9135551234",
            "CoachWorkPhone": "913-555-1235",
            "Manager": "Jo Manager",
            "MgrCellPhone": "8165551236",
        }

        listings, _ = htg.parse_standings([row], _u12_blue(), "u")

        assert not re.search(r"555|Jo Manager", repr(listings))

    @pytest.mark.parametrize("team_id", ["٦٥٥٣٦٩", "0655369", None, True, "None", 12345678901])
    def test_a_team_id_that_is_not_a_plain_number_is_reported_not_registered(self, team_id):
        listings, problems = htg.parse_standings([{"Id": team_id, "Name": "A U12"}], _u12_blue(), "u")

        assert listings == []
        assert problems == [f"U12 Boys Blue (2014/15) 9v9: unreadable team row {htg.clean_provider_id(team_id)!r}"]

    @pytest.mark.parametrize("name", ["TBD", "tba", "To Be Determined", "to be announced", "BYE"])
    def test_a_slot_held_for_a_team_still_to_come_is_reported_not_registered(self, name):
        """Event 14129's U14 Girls Red listed a "TBD" slot; the fallback would have given it the division's age."""
        listings, problems = htg.parse_standings(
            [{"Id": 659459, "Name": name, "Location": "Overland Park, KS"}], _u12_blue(), "u"
        )

        assert listings == []
        assert problems == [f"U12 Boys Blue (2014/15) 9v9: team 659459 is the placeholder {name!r}, not registered"]

    def test_a_team_whose_name_only_starts_like_a_placeholder_is_registered(self):
        listings, _ = htg.parse_standings([{"Id": 1, "Name": "TBD United U12"}], _u12_blue(), "u")

        assert [t.team_name for t in listings] == ["TBD United U12"]

    def test_standings_that_are_not_a_list_stop_the_run(self):
        with pytest.raises(htg.ScrapeFetchError, match="no standings"):
            htg.parse_standings({"Message": "error"}, _u12_blue(), "u")


def _game_row(**overrides):
    row = {
        "Id": 1001,
        "Team1Id": 11,
        "Team2Id": 12,
        "HomeTeamScore": 2,
        "VisitingTeamScore": 1,
        "Date": "11/07/2026",
        "Time": " 9:00AM",
        "Field": "OP-1 ",
        "Type": "Pool",
        "Forfeit1": False,
        "Forfeit2": False,
        "NoShow1": False,
        "NoShow2": False,
        "IgnoreResult1": False,
        "IgnoreResult2": False,
    }
    row.update(overrides)
    return row


def _parse_games(*rows):
    return htg.parse_games(list(rows), _u12_blue(), "u")


class TestParseGames:
    def test_every_scored_game_of_the_fixture_is_read(self):
        games, problems, flagged = htg.parse_games(_fixture("games_u12_boys_blue.json"), _u12_blue(), "u")

        assert problems == []
        assert flagged == {"forfeits": set(), "disputed": set(), "ignored": set()}
        columbia = sorted(
            (g.game_date, g.home_id, g.home_score, g.away_score, g.away_id)
            for g in games
            if COLUMBIA in (g.home_id, g.away_id)
        )
        assert columbia == [
            (date(2026, 11, 7), "652016", 1, 3, COLUMBIA),
            (date(2026, 11, 7), COLUMBIA, 3, 2, "653706"),
            (date(2026, 11, 8), COLUMBIA, 2, 2, "655575"),
            (date(2026, 11, 8), "655537", 1, 4, COLUMBIA),
        ]

    def test_a_game_carries_its_id_kickoff_and_field(self):
        [game], _, _ = _parse_games(_game_row())

        assert (game.game_no, game.game_time, game.venue, game.home_id, game.away_id) == (
            "1001",
            "9:00AM",
            "OP-1",
            "11",
            "12",
        )

    @pytest.mark.parametrize("flag", ["Forfeit1", "Forfeit2", "NoShow1", "NoShow2"])
    def test_a_forfeit_or_no_show_on_either_side_is_counted_and_never_imported(self, flag):
        games, problems, flagged = _parse_games(_game_row(**{flag: True}))

        assert (games, problems) == ([], [])
        assert flagged["forfeits"] == {"1001"}

    @pytest.mark.parametrize("missing", ["Team1Id", "Team2Id"])
    def test_a_forfeit_is_counted_even_when_a_team_slot_is_empty(self, missing):
        """Read before the team ids, so the event-wide hold sees it whichever copy is read."""
        games, problems, flagged = _parse_games(_game_row(Forfeit2=True, **{missing: None}))

        assert (games, problems) == ([], [])
        assert flagged["forfeits"] == {"1001"}

    @pytest.mark.parametrize("flag", ["IgnoreResult1", "IgnoreResult2"])
    def test_a_result_the_standings_ignore_is_imported_and_counted(self, flag):
        games, _, flagged = _parse_games(_game_row(**{flag: True}))

        assert [g.game_no for g in games] == ["1001"]
        assert flagged["ignored"] == {"1001"}

    @pytest.mark.parametrize(
        "overrides",
        [
            {"HomeTeamScore": -1, "VisitingTeamScore": -1},
            {"HomeTeamScore": -1},
            {"VisitingTeamScore": -1},
            {"HomeTeamScore": True},
            {"VisitingTeamScore": "2"},
            {"HomeTeamScore": None},
        ],
    )
    def test_an_unplayed_or_unreadable_score_is_reported_and_held(self, overrides):
        games, problems, _ = _parse_games(_game_row(**overrides))

        assert (games, problems) == ([], ["U12 Boys Blue (2014/15) 9v9 game 1001: no score"])

    @pytest.mark.parametrize("overrides", [{"Team1Id": 0}, {"Team2Id": None}, {"Team1Id": "٣١"}])
    def test_an_unfilled_bracket_slot_is_reported_and_held(self, overrides):
        games, problems, _ = _parse_games(_game_row(**overrides))

        assert (games, problems) == ([], ["U12 Boys Blue (2014/15) 9v9 game 1001: unfilled bracket slot"])

    @pytest.mark.parametrize("day", ["", "2026-11-07", "13/07/2026", None])
    def test_a_game_with_no_readable_day_is_reported_and_held(self, day):
        games, problems, _ = _parse_games(_game_row(Date=day))

        assert (games, problems) == ([], ["U12 Boys Blue (2014/15) 9v9 game 1001: no date"])

    def test_every_copy_of_a_game_is_returned_for_collect_event_to_compare(self):
        games, problems, flagged = _parse_games(_game_row(), _game_row(HomeTeamScore=5))

        assert [(g.game_no, g.home_score) for g in games] == [("1001", 2), ("1001", 5)]
        assert (problems, flagged["disputed"]) == ([], set())

    def test_a_game_row_with_no_id_is_reported(self):
        games, problems, _ = _parse_games(_game_row(Id=None))

        assert (games, problems) == ([], ["U12 Boys Blue (2014/15) 9v9: unreadable game row"])

    def test_games_that_are_not_a_list_stop_the_run(self):
        with pytest.raises(htg.ScrapeFetchError, match="no games"):
            htg.parse_games(None, _u12_blue(), "u")


# ── Age: the name decides, the division only fills a name with none ────────────


def _listing(team_id, name, location="Columbia, MO"):
    return tc.TeamListing(tc_team_id=team_id, team_name=name, club="Some Club", location=location, coach="")


def _event():
    return htg.parse_event_summary(_fixture("event_summary.json"), EVENT_ID)


def _division(name):
    return htg.parse_division(_division_item(name, "11v11"))[1]


def _roster(division_name, team_name, board_season=SEASON, **options):
    return tc.build_roster(
        [(_division(division_name), _listing("1", team_name))],
        _event(),
        board_season,
        division_age_fallback=True,
        **options,
    )


class TestDivisionAgeFallback:
    @pytest.mark.parametrize(
        "division_name, age_group, birth_year",
        [
            ("U12 Boys Blue (2014/15) 9v9", "u12", 2015),
            ("U10 Girls Red (17/18) 7v7", "u10", 2017),
            ("U18/19 Girls Red (2007/08) 11v11", "u19", 2009),
        ],
    )
    def test_a_name_with_no_age_takes_a_one_cohort_divisions_age(self, division_name, age_group, birth_year):
        in_scope, skipped = _roster(division_name, "Liederkranz SC")

        assert skipped == []
        assert [(row.age_group, row.birth_year, row.age_source) for row in in_scope] == [
            (age_group, birth_year, "no age in the team name, division's age used")
        ]

    def test_an_odd_year_span_takes_the_divisions_age_too(self):
        in_scope, _ = _roster("U12 Girls Red (2014/15) 9v9", "Blaze G2018-2016")

        assert [(row.age_group, row.age_source) for row in in_scope] == [
            ("u12", "odd year span in the team name, division's age used")
        ]

    @pytest.mark.parametrize("division_name", ["U14/15 Girls Green (2012/13) 11v11", "High School Boys Blue 11v11"])
    def test_a_name_with_no_age_in_a_division_of_two_ages_is_left_out(self, division_name):
        in_scope, skipped = _roster(division_name, "Liederkranz SC")

        assert in_scope == []
        assert [row.skip_reason for row in skipped] == ["no age in the team name, and its division spans two ages"]

    @pytest.mark.parametrize(
        "division_name, team_name, age_group",
        [
            ("U12 Boys Blue (2014/15) 9v9", "SPORTING BV Pre-MLS Next 15/16", "u11"),
            ("U12 Boys Blue (2014/15) 9v9", "WOU B14", "u13"),
            ("U14/15 Girls Green (2012/13) 11v11", "KC Fusion 2013 Girls", "u14"),
        ],
    )
    def test_a_name_that_states_an_age_keeps_it_whatever_the_division(self, division_name, team_name, age_group):
        in_scope, _ = _roster(division_name, team_name)

        assert [row.age_group for row in in_scope] == [age_group]
        assert "division" not in in_scope[0].age_source

    def test_an_age_the_operator_names_beats_the_divisions(self):
        in_scope, _ = _roster("U12 Boys Blue (2014/15) 9v9", "Liederkranz SC", age_groups={"1": "u13"})

        assert [(row.age_group, row.age_source) for row in in_scope] == [("u13", "set by the operator")]

    def test_a_division_age_is_read_in_the_events_season_and_filed_on_todays_board(self):
        """A U12 label of the 2026 event names 2015; a season later that team is U13."""
        in_scope, _ = _roster("U12 Boys Blue (2014/15) 9v9", "Liederkranz SC", board_season=SEASON + 1)

        assert [(row.age_group, row.birth_year) for row in in_scope] == [("u13", 2015)]

    @pytest.mark.parametrize("team_name", ["Club 2012 Est 2019", "Overland Park 2013 2014 Boys"])
    def test_a_name_with_two_birth_years_is_left_out_rather_than_filed_by_its_division(self, team_name):
        """``age_from_name`` reports two bare years as no age; the fallback must not read that as permission."""
        in_scope, skipped = _roster("U12 Boys Blue (2014/15) 9v9", team_name)

        assert in_scope == []
        assert [row.skip_reason for row in skipped] == ["name gives several birth years"]

    def test_without_the_fallback_a_name_with_no_age_is_still_left_out(self):
        in_scope, skipped = tc.build_roster(
            [(_division("U12 Boys Blue (2014/15) 9v9"), _listing("1", "Liederkranz SC"))], _event(), SEASON
        )

        assert in_scope == []
        assert [row.skip_reason for row in skipped] == ["no age in the team name"]


# ── The whole event ─────────────────────────────────────────────────────────────


class TestCollectEvent:
    def test_sporting_columbia_is_filed_with_its_four_games(self):
        event, in_scope, _, games, problems, _, flagged = _collect()

        assert event.name.endswith("- Boys")
        columbia = _by_name(in_scope)["Sporting Columbia 14/15B Navy"]
        assert (columbia.tc_team_id, columbia.age_group, columbia.gender, columbia.state_code) == (
            COLUMBIA,
            "u12",
            "Male",
            "MO",
        )
        assert columbia.club_name == "Sporting Columbia"
        assert len([g for g in games if COLUMBIA in (g.home_id, g.away_id)]) == 4
        assert problems == []
        assert flagged == {"forfeits": set(), "disputed": set(), "ignored": set()}

    def test_a_team_playing_up_keeps_the_age_its_name_states(self):
        """SPORTING BV Pre-MLS Next 15/16 entered U12 Boys Blue; the band says U11."""
        _, in_scope, _, _, _, _, _ = _collect()

        bv = _by_name(in_scope)["SPORTING BV Pre-MLS Next 15/16"]
        assert (bv.division_name, bv.age_group) == ("U12 Boys Blue (2014/15) 9v9", "u11")

    def test_a_name_with_no_age_takes_its_divisions_age_in_a_real_run(self):
        standings = [{"Id": 700001, "Name": "Liederkranz SC", "ClubName": "Liederkranz", "Location": "Lenexa, KS"}]
        fetcher = _ApiFetcher(answers={f"standings/{EVENT_ID}/{U12_BLUE}/false": standings})

        _, in_scope, skipped, _, _, _, _ = _collect(fetcher)

        assert "Liederkranz SC" not in _by_name(skipped)
        assert _by_name(in_scope)["Liederkranz SC"].age_group == "u12"

    @staticmethod
    def _listed_twice(name, second_division, second_size="7v7"):
        team = {"Id": 700001, "Name": name, "ClubName": "Liederkranz", "Location": "Lenexa, KS"}
        divisions = [
            _division_item("U12 Boys Blue (2014/15) 9v9", division_id=int(U12_BLUE)),
            _division_item(second_division, second_size, division_id=int(U10_BLUE)),
        ]
        return _ApiFetcher(
            answers={
                f"divisions/{EVENT_ID}": divisions,
                f"standings/{EVENT_ID}/{U12_BLUE}/false": [team],
                f"standings/{EVENT_ID}/{U10_BLUE}/false": [team],
            }
        )

    def test_a_team_with_no_age_listed_in_divisions_of_two_ages_is_left_out(self):
        fetcher = self._listed_twice("Liederkranz SC", "U10 Boys Blue (2016/17) 7v7")

        _, in_scope, skipped, _, _, _, _ = _collect(fetcher)

        assert "Liederkranz SC" not in _by_name(in_scope)
        held = _by_name(skipped)["Liederkranz SC"]
        assert held.skip_reason == "no age in the team name, and it is listed in divisions of different ages"
        assert (held.age_group, held.birth_year) == (None, None)

    def test_an_odd_year_span_listed_in_divisions_of_two_ages_is_left_out_with_its_own_reason(self):
        fetcher = self._listed_twice("Blaze B2018-2016", "U10 Boys Blue (2016/17) 7v7")

        _, _, skipped, _, _, _, _ = _collect(fetcher)

        assert _by_name(skipped)["Blaze B2018-2016"].skip_reason == (
            "odd year span in the team name, and it is listed in divisions of different ages"
        )

    def test_a_team_with_no_age_listed_twice_at_one_age_takes_it(self):
        _, in_scope, _, _, _, _, _ = _collect(
            self._listed_twice("Liederkranz SC", "U12 Boys Red I (2014/15) 9v9", second_size="9v9")
        )

        assert _by_name(in_scope)["Liederkranz SC"].age_group == "u12"

    def test_a_team_whose_name_states_an_age_is_kept_however_many_divisions_list_it(self):
        fetcher = self._listed_twice("Liederkranz SC B14/15", "U10 Boys Blue (2016/17) 7v7")

        _, in_scope, _, _, _, _, _ = _collect(fetcher)

        assert _by_name(in_scope)["Liederkranz SC B14/15"].age_group == "u12"

    def test_divisions_with_no_board_are_never_fetched(self):
        fetcher = _ApiFetcher()

        _, _, _, _, _, division_skips, _ = _collect(fetcher)

        assert not any("/54950" in path for path in fetcher.paths)
        assert division_skips == ["U08 Boys Red (2018/19) 7v7: U9 and below: no board"]

    def test_an_unpublished_division_is_skipped(self):
        divisions = [_division_item("U12 Boys Blue (2014/15) 9v9", division_id=int(U12_BLUE), publish=False)]
        fetcher = _ApiFetcher(answers={f"divisions/{EVENT_ID}": divisions})

        _, in_scope, _, games, _, division_skips, _ = _collect(fetcher)

        assert (in_scope, games) == ([], [])
        assert division_skips == ["U12 Boys Blue (2014/15) 9v9: not published"]

    def test_a_game_listed_in_two_divisions_is_read_once(self):
        crossover = _fixture("games_u12_boys_blue.json")[:1]
        fetcher = _ApiFetcher(answers={f"GamesForDivision/{EVENT_ID}/{U10_BLUE}": crossover})

        _, _, _, games, problems, _, _ = _collect(fetcher)

        assert [g.game_no for g in games].count(str(crossover[0]["Id"])) == 1
        assert problems == []

    @pytest.mark.parametrize(
        "difference",
        [
            {"HomeTeamScore": 9},
            {"VisitingTeamScore": 9},
            {"Date": "11/09/2026"},
            {"Time": " 9:59PM"},
            {"Field": "SSV-9N"},
            {"Team1Id": 999999},
            {"Team2Id": 999998},
        ],
    )
    def test_a_game_two_divisions_disagree_on_is_reported_and_held(self, difference):
        """One field differs per case, so each part of the comparison is pinned on its own."""
        crossover = [dict(_fixture("games_u12_boys_blue.json")[0], **difference)]
        fetcher = _ApiFetcher(answers={f"GamesForDivision/{EVENT_ID}/{U10_BLUE}": crossover})

        _, _, _, games, problems, _, flagged = _collect(fetcher)

        game_no = str(crossover[0]["Id"])
        assert problems == [
            f"game {game_no}: listed in U10 Boys Blue (2016/17) 7v7 and U12 Boys Blue (2014/15) 9v9"
            " with different details"
        ]
        assert flagged["disputed"] == {game_no}
        assert game_no not in {g.game_no for g in games}

    def test_a_game_one_division_lists_twice_is_read_once_or_held_when_the_copies_differ(self):
        rows = _fixture("games_u12_boys_blue.json")
        same, differing = rows[0], rows[1]
        listed = [*rows, dict(same), dict(differing, HomeTeamScore=7)]
        fetcher = _ApiFetcher(answers={f"GamesForDivision/{EVENT_ID}/{U12_BLUE}": listed})

        _, _, _, games, problems, _, flagged = _collect(fetcher)

        game_nos = [g.game_no for g in games]
        assert game_nos.count(str(same["Id"])) == 1
        assert str(differing["Id"]) not in game_nos
        assert flagged["disputed"] == {str(differing["Id"])}
        assert problems == [
            f"game {differing['Id']}: listed in U12 Boys Blue (2014/15) 9v9 and U12 Boys Blue (2014/15) 9v9"
            " with different details"
        ]

    @pytest.mark.parametrize("forfeit_in", [U10_BLUE, U12_BLUE])
    def test_a_forfeit_flagged_in_one_division_holds_the_clean_copy_in_the_other(self, forfeit_in):
        """U10 Boys Blue is listed first, so this holds the forfeit whichever copy is read first."""
        clean = _fixture("games_u12_boys_blue.json")[0]
        game_no = str(clean["Id"])
        answers = {f"GamesForDivision/{EVENT_ID}/{U10_BLUE}": [clean]}
        if forfeit_in == U12_BLUE:
            answers[f"GamesForDivision/{EVENT_ID}/{U12_BLUE}"] = [dict(clean, Forfeit2=True)]
        else:
            answers[f"GamesForDivision/{EVENT_ID}/{U10_BLUE}"] = [dict(clean, Forfeit2=True)]

        _, _, _, games, _, _, flagged = _collect(_ApiFetcher(answers=answers))

        assert flagged["forfeits"] == {game_no}
        assert game_no not in {g.game_no for g in games}

    def test_a_forfeit_listed_in_two_divisions_is_counted_once(self):
        forfeit = [_game_row(Id=2001, Forfeit1=True)]
        fetcher = _ApiFetcher(
            answers={
                f"GamesForDivision/{EVENT_ID}/{U12_BLUE}": forfeit,
                f"GamesForDivision/{EVENT_ID}/{U10_BLUE}": forfeit,
            }
        )

        _, _, _, _, _, _, flagged = _collect(fetcher)

        assert flagged["forfeits"] == {"2001"}

    def test_a_call_that_fails_stops_the_run(self):
        with pytest.raises(htg.ScrapeFetchError):
            _collect(_ApiFetcher(fail_on=f"GamesForDivision/{EVENT_ID}/{U10_BLUE}"))

    @pytest.mark.parametrize("divisions", [[], {"Message": "An error has occurred."}])
    def test_an_event_with_no_divisions_stops_the_run(self, divisions):
        with pytest.raises(htg.ScrapeFetchError, match="no divisions"):
            _collect(_ApiFetcher(answers={f"divisions/{EVENT_ID}": divisions}))

    def test_a_division_of_an_unknown_shape_is_reported_and_its_games_never_read(self):
        divisions = [*_fixture("divisions.json"), {"Name": "Boys U12 Red", "Id": 55999}]
        fetcher = _ApiFetcher(answers={f"divisions/{EVENT_ID}": divisions})

        _, _, _, _, problems, _, _ = _collect(fetcher)

        assert problems == ["Boys U12 Red: unreadable division"]
        assert not any("55999" in path for path in fetcher.paths)

    def test_an_event_labelled_by_the_coming_season_stops_before_any_roster(self):
        """With no age in a name the division's label files the team, so a label a year off must stop the run."""
        standings = [{"Id": 800000 + i, "Name": f"Club{i} B15/16", "Location": "Lenexa, KS"} for i in range(8)]
        fetcher = _ApiFetcher(answers={f"standings/{EVENT_ID}/{U12_BLUE}/false": standings})

        with pytest.raises(htg.LabelSeasonError, match="band-named teams sit one year below their division"):
            _collect(fetcher)

    def test_games_outside_the_window_are_dropped(self):
        _, _, _, games, _, _, _ = _collect(days_back=0)

        assert games == []

    def test_the_window_runs_back_from_today_by_whole_days(self):
        """Today is 2026-11-09, so one day back keeps the 8th and drops the 6th and 7th."""
        _, _, _, games, _, _, _ = _collect(days_back=1)

        assert {g.game_date for g in games} == {date(2026, 11, 8)}


# ── main ───────────────────────────────────────────────────────────────────────


class _FakeMatcher:
    """Stands in for the matcher in ``main``; records how it was built and whom it matched."""

    instances = []
    results = {}

    def __init__(self, supabase, provider_id=None, registration_mode=False, dry_run=False):
        self.dry_run = dry_run
        self.registration_mode = registration_mode
        self.matched = []
        _FakeMatcher.instances.append(self)

    def _match_team(self, **kwargs):
        team_id = kwargs["provider_team_id"]
        self.matched.append(team_id)
        created = {"matched": True, "team_id": f"new-{team_id}", "method": "direct_id", "created": True}
        return _FakeMatcher.results.get(team_id, {**created, "confidence": 1.0})


class _Query:
    """A PostgREST read that filters rows and returns only the selected columns, at ``execute``."""

    def __init__(self, rows):
        self.rows, self.filters, self.columns = rows, [], []

    def select(self, columns):
        self.columns = [c.strip() for c in columns.split(",")]
        return self

    def eq(self, field, value):
        self.filters.append(lambda r, f=field, v=value: r[f] == v)
        return self

    def in_(self, field, values):
        self.filters.append(lambda r, f=field, v=tuple(values): r[f] in v)
        return self

    def execute(self):
        found = [r for r in self.rows if all(f(r) for f in self.filters)]
        return SimpleNamespace(data=[{c: r[c] for c in self.columns} for r in found])


class _Client:
    """The providers row, and a review queue keyed by provider code as the real table is."""

    def __init__(self, queue):
        self.queue = queue

    def table(self, name):
        if name == "providers":
            return _Query([{"id": "htg-provider-uuid", "code": "htgsports"}])
        assert name == "team_match_review_queue", f"unexpected table {name!r}"
        return _Query(self.queue)


class _FixedDate(date):
    @classmethod
    def today(cls):
        return TODAY


@pytest.fixture
def run_main(monkeypatch, tmp_path):
    def run(*flags, fetcher=None, results=None, saved=None, queue=None, teams=None, import_code=0):
        """Run ``main`` with every outside call stood in for.

        Before the run nothing is linked. Afterwards ``saved`` is what the alias table holds
        (default: ``new-<id>`` for every id, as the default matcher result reports), ``queue`` the
        review queue's rows, ``teams``
        the stored team rows, and ``import_code`` what the game importer exits with.
        """
        _FakeMatcher.instances = []
        _FakeMatcher.results = results or {}
        imports = []
        alias_calls = []
        fetcher = fetcher or _ApiFetcher()

        def fake_existing_aliases(_client, _provider_id, team_ids):
            alias_calls.append(list(team_ids))
            if len(alias_calls) == 1:
                return {}
            return saved if saved is not None else {i: f"new-{i}" for i in team_ids}

        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
        monkeypatch.setattr(htg, "create_client", lambda *_a: _Client(queue or []))
        monkeypatch.setattr(htg, "make_session", lambda: None)
        monkeypatch.setattr(htg, "read_api_token", lambda _s, _event_id: PLACEHOLDER_TOKEN)
        monkeypatch.setattr(htg, "fetch_api", lambda _s, _token, path: fetcher(path))
        monkeypatch.setattr(htg, "HtgSportsGameMatcher", _FakeMatcher)
        monkeypatch.setattr(htg, "existing_aliases", fake_existing_aliases)
        monkeypatch.setattr(htg, "teams_by_id", lambda _c, ids: {i: t for i, t in (teams or {}).items() if i in ids})
        monkeypatch.setattr(htg, "_soccer_season_year", lambda now=None: SEASON)
        monkeypatch.setattr(htg, "date", _FixedDate)
        monkeypatch.setattr(
            htg.subprocess, "run", lambda cmd, check: imports.append(cmd) or SimpleNamespace(returncode=import_code)
        )
        argv = [
            "import_htgsports_event.py",
            "--event-url",
            f"https://events.htgsports.net/?eventid={EVENT_ID}#/scheduleresults",
            "--output-dir",
            str(tmp_path),
            "--delay-min",
            "0",
            "--delay-max",
            "0",
        ]
        monkeypatch.setattr(htg.sys, "argv", [*argv, *flags])

        try:
            code = htg.main()
        finally:
            _FakeMatcher.results = {}
        if code != 0:
            return SimpleNamespace(code=code, imports=imports, fetched=fetcher.paths)
        [report] = tmp_path.glob("*_teams.csv")
        [games_csv] = tmp_path.glob("*_games.csv")
        [cross_age_csv] = tmp_path.glob("*_cross_age.csv")
        report_rows = list(csv.DictReader(report.open(encoding="utf-8")))
        return SimpleNamespace(
            code=code,
            imports=imports,
            report_columns=list(report_rows[0]) if report_rows else [],
            outcomes={r["team_name"]: r for r in report_rows},
            games=list(csv.DictReader(games_csv.open(encoding="utf-8"))),
            games_csv=games_csv,
            cross_age=list(csv.DictReader(cross_age_csv.open(encoding="utf-8"))),
            files=sorted(p.name for p in tmp_path.iterdir()),
        )

    return run


REVIEW = {"matched": False, "team_id": None, "method": "fuzzy_review", "confidence": 0.8, "review": True}
FUZZY = {"matched": True, "team_id": "T1", "method": "fuzzy_auto", "confidence": 0.95, "created": False}


class TestMain:
    def test_a_dry_run_builds_only_a_dry_run_matcher_and_starts_no_import(self, run_main):
        result = run_main()

        assert result.code == 0
        assert result.imports == []
        assert [(m.dry_run, m.registration_mode) for m in _FakeMatcher.instances] == [(True, True)]
        assert all(name.startswith("htg14130_2026_") for name in result.files)

    def test_sporting_columbias_four_games_are_written_under_this_provider(self, run_main):
        result = run_main()

        columbia = [r for r in result.games if r["team_id"] == COLUMBIA]
        assert len(columbia) == 4
        assert {r["provider"] for r in result.games} == {"htgsports"}
        assert {r["event_id"] for r in result.games} == {"htg14130-2026"}
        assert {r["schedule_id"] for r in columbia} == {
            "htg14130-1476592",
            "htg14130-1476594",
            "htg14130-1476597",
            "htg14130-1476600",
        }
        assert {r["source_url"] for r in columbia} == {
            f"https://events.htgsports.net/?eventid={EVENT_ID}#/scheduleresults/{U12_BLUE}"
        }

    def test_execute_imports_the_games_csv_under_this_provider(self, run_main):
        result = run_main("--execute")

        assert [(m.dry_run, m.registration_mode) for m in _FakeMatcher.instances] == [(True, True), (False, True)]
        [command] = result.imports
        assert command[1:] == ["scripts/import_games_enhanced.py", str(result.games_csv), "htgsports"]

    def test_a_failed_game_import_fails_the_run(self, run_main):
        result = run_main("--execute", import_code=3)

        assert result.code == 3

    def test_a_link_the_alias_table_does_not_confirm_is_an_error_and_writes_no_game(self, run_main):
        """The matcher reports a link it failed to save; its games must not import half-matched."""
        result = run_main("--execute", saved={})

        assert result.outcomes["Sporting Columbia 14/15B Navy"]["outcome"] == "error"
        assert result.outcomes["Sporting Columbia 14/15B Navy"]["reason"] == "link was not saved"
        assert result.games == []

    def test_a_link_to_a_team_on_another_board_is_an_error_and_its_games_are_held(self, run_main):
        linked = {"matched": True, "team_id": "T9", "method": "direct_id", "confidence": 1.0, "created": False}
        teams = {"T9": {"team_id_master": "T9", "team_name": "Other", "age_group": "u13", "gender": "Male"}}

        result = run_main(results={COLUMBIA: linked}, teams=teams)

        assert result.outcomes["Sporting Columbia 14/15B Navy"]["outcome"] == "error"
        assert result.outcomes["Sporting Columbia 14/15B Navy"]["reason"] == (
            "linked team is on the u13 board, this team is u12"
        )
        assert not any(COLUMBIA in (r["team_id"], r["opponent_id"]) for r in result.games)

    def test_a_team_the_operator_leaves_out_is_reported_and_none_of_its_games_is_written(self, run_main):
        result = run_main("--leave-out", COLUMBIA)

        assert result.outcomes["Sporting Columbia 14/15B Navy"]["outcome"] == "skipped"
        assert result.outcomes["Sporting Columbia 14/15B Navy"]["reason"] == "left out by the operator"
        assert not any(COLUMBIA in (r["team_id"], r["opponent_id"]) for r in result.games)

    @pytest.mark.parametrize(
        "flag, value, column, expected",
        [
            ("--age", f"{COLUMBIA}=u13", "age_group", "u13"),
            ("--state", f"{COLUMBIA}=KS", "state_code", "KS"),
            ("--gender", f"{COLUMBIA}=Female", "gender", "Female"),
        ],
    )
    def test_the_operators_settings_reach_the_team(self, run_main, flag, value, column, expected):
        result = run_main(flag, value)

        assert result.outcomes["Sporting Columbia 14/15B Navy"][column] == expected

    def test_an_event_labelled_by_the_coming_season_exits_before_any_team_is_registered(self, run_main):
        standings = [{"Id": 800000 + i, "Name": f"Club{i} B15/16", "Location": "Lenexa, KS"} for i in range(8)]

        result = run_main(
            "--execute", fetcher=_ApiFetcher(answers={f"standings/{EVENT_ID}/{U12_BLUE}/false": standings})
        )

        assert result.code == 1
        assert (_FakeMatcher.instances, result.imports) == ([], [])

    def test_days_back_sets_the_window_of_games_written(self, run_main):
        result = run_main("--days-back", "1")

        assert result.games
        assert {r["game_date"] for r in result.games} == {"2026-11-08"}

    def test_a_formula_in_a_team_name_is_defanged_in_the_report_only(self, run_main):
        standings = [
            *_fixture("standings_u12_boys_blue.json"),
            {"Id": 700002, "Name": '=HYPERLINK("x") 14/15B', "Location": "Lenexa, KS"},
        ]

        result = run_main(fetcher=_ApiFetcher(answers={f"standings/{EVENT_ID}/{U12_BLUE}/false": standings}))

        assert '\'=HYPERLINK("x") 14/15B' in result.outcomes

    def test_a_game_between_two_boards_is_written_and_listed_in_the_cross_age_file(self, run_main):
        """SPORTING BV Pre-MLS Next 15/16 (u11) played Sporting Columbia (u12) in U12 Boys Blue."""
        result = run_main()

        pairs = {(r["home_team_id"], r["away_team_id"]) for r in result.cross_age}
        assert ("652016", COLUMBIA) in pairs
        assert any(r["team_id"] == "652016" and r["opponent_id"] == COLUMBIA for r in result.games)

    def test_a_queued_review_is_found_in_the_queue_under_this_providers_code(self, run_main):
        queue = [{"provider_id": "htgsports", "provider_team_id": COLUMBIA, "status": "pending"}]

        result = run_main("--execute", results={COLUMBIA: dict(REVIEW)}, queue=queue)

        assert result.outcomes["Sporting Columbia 14/15B Navy"]["outcome"] == "review"

    def test_a_review_queued_under_another_providers_code_is_an_error(self, run_main):
        queue = [{"provider_id": "tourneycentral", "provider_team_id": COLUMBIA, "status": "pending"}]

        result = run_main("--execute", results={COLUMBIA: dict(REVIEW)}, queue=queue)

        assert result.outcomes["Sporting Columbia 14/15B Navy"]["outcome"] == "error"
        assert result.outcomes["Sporting Columbia 14/15B Navy"]["reason"] == "review item was not saved"

    def test_two_teams_linking_to_one_pitchrank_team_conflict_in_htg_terms(self, run_main):
        result = run_main("--execute", results={COLUMBIA: dict(FUZZY), "655575": dict(FUZZY)})

        assert result.outcomes["Sporting Columbia 14/15B Navy"]["outcome"] == "conflict"
        assert (
            result.outcomes["Sporting Columbia 14/15B Navy"]["reason"]
            == "same PitchRank team as HTG Sports team 655575"
        )
        assert COLUMBIA not in _FakeMatcher.instances[1].matched
        assert not any(COLUMBIA in (r["team_id"], r["opponent_id"]) for r in result.games)

    def test_the_team_report_names_its_id_column_for_htg(self, run_main):
        result = run_main()

        assert result.report_columns == htg.HTG_REPORT_COLUMNS
        assert result.report_columns[0] == "htg_team_id"
        assert result.outcomes["Sporting Columbia 14/15B Navy"]["htg_team_id"] == COLUMBIA

    def test_a_call_that_fails_exits_before_any_team_is_registered(self, run_main):
        result = run_main("--execute", fetcher=_ApiFetcher(fail_on=f"standings/{EVENT_ID}/{U12_BLUE}"))

        assert result.code == 1
        assert (_FakeMatcher.instances, result.imports) == ([], [])

    def test_a_bad_event_url_stops_before_any_fetch(self, run_main):
        fetcher = _ApiFetcher()

        result = run_main("--event-url", "https://events.example.com/?eventid=14130", fetcher=fetcher)

        assert (result.code, fetcher.paths) == (1, [])


# ── Same-day rematches ─────────────────────────────────────────────────────────


class TestRematches:
    def test_htg_sports_keeps_same_day_rematches_apart(self):
        """Named here, not drawn from the set, so dropping the provider fails this test."""
        assert "htgsports" in REMATCH_PROVIDERS
        assert "htgsports" in SCHEDULE_ID_SUFFIX_PROVIDERS

    def test_a_pool_game_and_a_final_between_two_teams_on_one_day_get_two_game_uids(self):
        uid = GameHistoryMatcher.generate_game_uid(
            provider="htgsports", game_date="2026-11-08", team1_id="master-a", team2_id="master-b"
        )

        uids = {
            rematch_game_uid("htgsports", uid, {"raw_data": {"schedule_id": schedule_id}})
            for schedule_id in ("htg14130-1476437", "htg14130-1476438")
        }

        assert len(uids) == 2


# ── Fixtures carry no personal data ────────────────────────────────────────────


_PHONE = re.compile(r"(?<![\d(])\d{10}(?!\d)|(?<!\d)\d{3}[-. )]\s?\d{3}[-. ]\d{4}(?!\d)")
_GUID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")


class TestFixtureScrub:
    FILES = sorted(FIXTURES.glob("*.json"))

    def test_there_are_fixtures_to_check(self):
        assert len(self.FILES) == 6

    @pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
    def test_no_fixture_carries_a_phone_number_or_a_token(self, path):
        text = path.read_text(encoding="utf-8")

        assert not _PHONE.search(text)
        assert not _GUID.search(text)

    @pytest.mark.parametrize("path", sorted(FIXTURES.glob("standings_*.json")), ids=lambda p: p.name)
    def test_every_contact_field_in_the_standings_is_blank_or_a_placeholder(self, path):
        for row in json.loads(path.read_text(encoding="utf-8")):
            contact = {k: v for k, v in row.items() if "phone" in k.lower() or k.lower().startswith("mgr")}
            assert set(contact.values()) <= {""}
            assert row["Manager"] == ""
            assert re.fullmatch(r"Coach \d+|", row["Coach"])

    def test_this_module_carries_only_made_up_tokens(self):
        """The site's real token is public, but the tests have no reason to carry it."""
        found = set(_GUID.findall(Path(__file__).read_text(encoding="utf-8")))

        assert found == {PLACEHOLDER_TOKEN, OTHER_TOKEN, CONFLICTING_TOKEN}
