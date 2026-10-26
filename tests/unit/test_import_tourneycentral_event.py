"""Unit tests for scripts/import_tourneycentral_event.py.

The fixtures under tests/fixtures/tourneycentral/ are pages of the 2026 Warrior Fall
Classic (wfc.tourneycentral.com) as the site served them on 2026-10-14, byte for
byte: ISO-8859-1, declared only in each page's ``<meta>``. They are five of its
divisions; every other division answers with an empty team list and schedule.
"""

import argparse
import csv
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from scripts import import_tourneycentral_event as tc
from src.etl.enhanced_pipeline import rematch_game_uid
from src.models.game_matcher import GameHistoryMatcher

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tourneycentral"
HOST = "wfc.tourneycentral.com"
SEASON = 2026


def _fixture(name):
    return (FIXTURES / name).read_bytes().decode("iso-8859-1")


class _PageFetcher:
    """Stands in for the network; every page of the run comes from a fixture."""

    NO_TEAMS = "<html><body><table><tr><td><b>Team/Location</b></td></tr></table></body></html>"
    NO_GAMES = "<html><body><table><tr><td><b>No.</b></td></tr></table></body></html>"

    def __init__(self, fail_on=None, pages=None):
        self.urls = []
        self.fail_on = fail_on
        self.pages = pages or {}

    def __call__(self, url):
        self.urls.append(url)
        if self.fail_on and self.fail_on in url:
            raise tc.ScrapeFetchError(f"HTTP 503 for {url}")
        if url.endswith("/games.html"):
            return _fixture("games.html")
        kind = "adiv" if "fnc=adiv" in url else "sked"
        name = f"{kind}_{url.rsplit('t_div=', 1)[1]}.html"
        if name in self.pages:
            return self.pages[name]
        path = FIXTURES / name
        if path.exists():
            return path.read_bytes().decode("iso-8859-1")
        return self.NO_TEAMS if kind == "adiv" else self.NO_GAMES


def _event():
    event, _ = tc.parse_games_page(_fixture("games.html"), HOST, "wfc")
    return event


def _collect(fetcher=None, board_season=SEASON, days_back=3650):
    return tc.collect_event(fetcher or _PageFetcher(), HOST, "wfc", board_season, days_back, date(2026, 10, 14))


def _by_name(rows):
    return {row.team_name: row for row in rows}


META_LATIN1 = b'<html><head><meta http-equiv="content-type" content="text/html;charset=ISO-8859-1"></head>'
META_UTF8 = b'<html><head><meta charset="utf-8"></head>'


class _Response:
    """A requests response: raw bytes, with ``encoding`` read from the header as requests reads it."""

    def __init__(self, status_code, body=b"<html></html>", content_type="text/html"):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.content = body
        self.encoding = requests.utils.get_encoding_from_headers(self.headers)

    @property
    def text(self):
        return self.content.decode(self.encoding or "utf-8", errors="replace")


class _Session:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _read(body, content_type="text/html"):
    return tc._fetch(_Session(_Response(200, body, content_type)), "u")


class TestFetch:
    def test_a_latin1_page_declared_only_in_its_meta_is_decoded(self):
        assert "Club Atlético" in _read(META_LATIN1 + "<body>Club Atlético</body></html>".encode("iso-8859-1"))

    def test_a_utf8_page_declared_only_in_its_meta_is_decoded(self):
        """requests reads a bare text/html as ISO-8859-1, which mangles this page."""
        assert "Club Atlético" in _read(META_UTF8 + "<body>Club Atlético</body></html>".encode("utf-8"))

    def test_a_curly_apostrophe_in_a_declared_latin1_page_is_read_as_a_browser_reads_it(self):
        """The form submits it as windows-1252 byte 0x92; strict ISO-8859-1 makes a control character."""
        assert "O’Fallon – Gold" in _read(META_LATIN1 + b"<body>O\x92Fallon \x96 Gold</body></html>")

    def test_a_header_charset_wins_over_the_meta(self):
        body = META_LATIN1 + "<body>Club Atlético</body></html>".encode("utf-8")

        assert "Club Atlético" in _read(body, "text/html; charset=utf-8")

    def test_a_quoted_header_charset_is_read(self):
        assert "Club Atlético" in _read("<body>Club Atlético</body>".encode("utf-8"), 'text/html; charset="utf-8"')

    @pytest.mark.parametrize("label", ["no-such-charset", "hex"])
    def test_a_charset_that_is_not_a_text_encoding_is_read_as_utf8(self, label):
        body = f'<html><head><meta charset="{label}"></head><body>Club Atlético</body></html>'.encode("utf-8")

        assert "Club Atlético" in _read(body)

    @pytest.mark.parametrize("status", [404, 500, 503])
    def test_a_status_other_than_200_raises(self, status):
        with pytest.raises(tc.ScrapeFetchError, match=f"HTTP {status}"):
            tc._fetch(_Session(_Response(status)), "u")

    def test_a_transport_error_raises(self):
        with pytest.raises(tc.ScrapeFetchError):
            tc._fetch(_Session(requests.ConnectionError("reset")), "u")

    def test_every_request_carries_a_timeout(self):
        session = _Session(_Response(200))

        tc._fetch(session, "https://wfc.tourneycentral.com/games.html")

        assert session.calls == [("https://wfc.tourneycentral.com/games.html", 90)]

    def test_the_session_retries_a_server_error_twice_and_nothing_else(self):
        retries = tc.make_session().get_adapter("https://wfc.tourneycentral.com").max_retries

        assert (retries.total, retries.backoff_factor) == (2, 1)
        assert sorted(retries.status_forcelist) == [500, 502, 503, 504]


class TestParseEventUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://wfc.tourneycentral.com/games.html",
            "https://wfc.tourneycentral.com",
            "https://WFC.tourneycentral.com/",
            "http://wfc.tourneycentral.com/cgi-bin/teams.cgi?fnc=sked&t_div=B11Gold",
        ],
    )
    def test_any_page_of_the_tournament_yields_its_host(self, url):
        assert tc.parse_event_url(url) == (HOST, "wfc")

    @pytest.mark.parametrize(
        "url",
        [
            "https://tourneycentral.com/tournament-calendar",
            "https://wfc.tourneycentral.com.evil.test/games.html",
            "https://wfc.example.com/games.html",
            "wfc.tourneycentral.com/games.html",
            "",
        ],
    )
    def test_anything_else_is_refused(self, url):
        with pytest.raises(ValueError):
            tc.parse_event_url(url)


class TestParseGamesPage:
    def test_the_tournament_is_named_and_dated_by_its_own_page(self):
        event, codes = tc.parse_games_page(_fixture("games.html"), HOST, "wfc")

        assert event.name == "Warrior Fall Classic"
        assert (event.start, event.end, event.season) == (date(2026, 10, 10), date(2026, 10, 11), 2026)
        assert len(codes) == 21
        assert (codes[0], codes[-1]) == ("B09Gold", "G14-15Red")

    def test_a_page_without_play_dates_is_a_fetch_error(self):
        with pytest.raises(tc.ScrapeFetchError, match="no play dates"):
            tc.parse_games_page("<html><body>maintenance</body></html>", HOST, "wfc")

    def test_a_page_without_divisions_is_a_fetch_error(self):
        page = '<html><body><select><option value="2026-10-10">Sat</option></select></body></html>'

        with pytest.raises(tc.ScrapeFetchError, match="no divisions"):
            tc.parse_games_page(page, HOST, "wfc")

    def test_a_play_date_written_with_spaces_is_read(self):
        page = (
            '<html><body><select><option value=" 2026-10-10 ">Sat</option></select>'
            '<select name="t_div"><option value="B11Gold">B11Gold</option></select></body></html>'
        )

        event, codes = tc.parse_games_page(page, HOST, "wfc")

        assert (event.start, codes) == (date(2026, 10, 10), ["B11Gold"])


class TestDivisionCodes:
    @pytest.mark.parametrize(
        "code, expected",
        [
            ("B11Gold", ("Male", 11, 11, None)),
            ("B107v7Gold", ("Male", 10, 10, 7)),
            ("B129v9Red", ("Male", 12, 12, 9)),
            ("G14-15Gold", ("Female", 14, 15, None)),
            ("G09Red", ("Female", 9, 9, None)),
            ("BU9Premier", ("Male", 9, 9, None)),
            ("GU11Premier", ("Female", 11, 11, None)),
            ("BU1415Black", ("Male", 14, 15, None)),
            ("GU1415Premier", ("Female", 14, 15, None)),
            ("B1011v11Gold", ("Male", 10, 10, 11)),
            ("BU107v7Gold", ("Male", 10, 10, 7)),
            ("B19Gold", ("Male", 19, 19, None)),
            ("BoysU13Red", ("Male", 13, 13, None)),
            ("BoysU1415Red", ("Male", 14, 15, None)),
            ("GirlsU09Red", ("Female", 9, 9, None)),
            ("GirlsU1314Red", ("Female", 13, 14, None)),
        ],
    )
    def test_a_code_gives_gender_ages_and_format(self, code, expected):
        division = tc.parse_division_code(code)

        assert (division.gender, division.young_age, division.old_age, division.players) == expected

    @pytest.mark.parametrize(
        "code",
        [
            "B2015Gold",
            "B2021Gold",
            "BU1416Gold",
            "B20Gold",
            "BU",
            "Open",
            "B15-14Gold",
            "BU1514Gold",
            "BoysU1416Red",
            "Boys2015Red",
            "",
        ],
    )
    def test_a_code_of_another_shape_is_refused(self, code):
        """A birth-year code read as two digits would be filed as U20."""
        assert tc.parse_division_code(code) is None

    @pytest.mark.parametrize(
        "code, reason",
        [
            ("B09Red", "U9 and below: no board"),
            ("BU9Premier", "U9 and below: no board"),
            ("B105v5Gold", "small-sided"),
            ("B11Gold", None),
            ("B107v7Gold", None),
            ("B09-10Gold", None),
        ],
    )
    def test_a_division_with_no_board_or_of_small_sided_play_is_skipped(self, code, reason):
        assert tc.skip_division(tc.parse_division_code(code)) == reason


def _team_list(name, code=None):
    division = tc.parse_division_code(code or name.split("_", 1)[1].removesuffix(".html"))
    return tc.parse_team_list(_fixture(name), division, "u")


class TestParseTeamList:
    def test_every_team_carries_its_id_name_club_location_and_coach(self):
        listings, problems = _team_list("adiv_B11Gold.html")

        assert problems == []
        assert [(t.tc_team_id, t.team_name) for t in listings] == [
            ("317605", "Club Ohio Dayton U11B Green"),
            ("315843", "Olimpia USA Purple 2016/2017 Boys Academy"),
            ("317509", "U11 Elite FC Pre-ECNL - Black"),
            ("317819", "Warrior SC B15/16 White"),
        ]
        warrior = listings[3]
        assert (warrior.club, warrior.location, warrior.coach) == ("Warrior Soccer Club", "Dayton, OH", "Tuan Ha")

    def test_a_website_link_beside_the_name_is_ignored(self):
        listings, _ = _team_list("adiv_B14-15Red.html")

        nwfc = {t.tc_team_id: t for t in listings}["314976"]
        assert (nwfc.team_name, nwfc.club, nwfc.location, nwfc.coach) == (
            "NWFC U14 Boys Orange",
            "Northwest FC",
            "Marysville, OH",
            "Gregory H Brothers",
        )

    def test_a_row_with_no_club_line_keeps_its_location(self):
        listings, _ = _team_list("adiv_G13Gold.html")

        pc = {t.tc_team_id: t for t in listings}["319591"]
        assert (pc.team_name, pc.club, pc.location) == ("PC Unitd G13/14", "", "Eaton, OH")

    @pytest.mark.parametrize("team_id", ["٣١٧٦٠٥", "0317605", "+317605", "None", "12345678901"])
    def test_a_team_id_that_is_not_a_plain_number_is_reported_not_registered(self, team_id):
        page = (
            "<table><tr><td><b>Team/Location</b></td></tr>"
            f"<tr><td>A1</td><td><b>Some Team U11</b><br><i>Club</i><br>Dayton, OH</td><td>Coach</td>"
            f'<td><form><input type=hidden name=t value="{team_id}"></form></td></tr></table>'
        )

        listings, problems = tc.parse_team_list(page, tc.parse_division_code("B11Gold"), "u")

        assert listings == []
        assert problems == [f"B11Gold: unreadable team row {tc.clean_provider_id(team_id)!r}"]

    def test_a_page_that_is_not_a_team_list_stops_the_run(self):
        with pytest.raises(tc.ScrapeFetchError, match="B11Gold: no team list"):
            tc.parse_team_list("<html><body>maintenance</body></html>", tc.parse_division_code("B11Gold"), "u")


def _schedule_page(*rows, day="Sunday, Oct 11, 2026"):
    return (
        "<table><tr><td><b>No.</b></td></tr>"
        f"<tr><td colspan=11><b>{day}</b></td></tr>"
        + "".join(
            f"<tr><td></td><td>{no}</td><td>B11Gold</td><td>9:00 AM</td><td>F1</td><td>{home}</td>"
            f"<td>{home_score}</td><td>{away_score}</td><td>{away}</td><td>-</td><td></td></tr>"
            for no, home, home_score, away_score, away in rows
        )
        + "</table>"
    )


_LINK = '<a href="/cgi-bin/teams.cgi?fnc=sked&t={}">T</a>'


class TestParseSchedule:
    def _games(self):
        division = tc.parse_division_code("B11Gold")
        return tc.parse_schedule(_fixture("sked_B11Gold.html"), division, "u")

    def test_every_scored_game_is_read_with_both_team_ids_and_its_day(self):
        games, problems = self._games()

        assert problems == []
        assert [g.game_no for g in games] == ["71", "72", "73", "74", "75", "76", "77"]
        assert [g.game_date for g in games] == [date(2026, 10, 10)] * 4 + [date(2026, 10, 11)] * 3
        final = games[-1]
        assert (final.home_id, final.home_score, final.away_score, final.away_id) == ("315843", 3, 2, "317819")
        assert (final.game_time, final.venue) == ("2:45 PM", "WSC13")

    def test_the_pool_seed_in_a_team_cell_never_reaches_a_game(self):
        """The cell reads "A2 - Olimpia ..."; only its link is read."""
        games, _ = self._games()

        assert all(g.home_id.isdigit() and g.away_id.isdigit() for g in games)

    def _parse(self, page):
        return tc.parse_schedule(page, tc.parse_division_code("B11Gold"), "u")

    def test_an_unfilled_bracket_slot_is_reported_and_held(self):
        games, problems = self._parse(_schedule_page(("80", _LINK.format(1), 2, 1, "Winner Game 75")))

        assert (games, problems) == ([], ["B11Gold game 80: unfilled bracket slot"])

    @pytest.mark.parametrize("link_id", ["٣١", "0317605", "123456789012"])
    def test_a_team_link_whose_id_is_not_a_plain_number_is_held(self, link_id):
        games, problems = self._parse(_schedule_page(("80", _LINK.format(1), 2, 1, _LINK.format(link_id))))

        assert (games, problems) == ([], ["B11Gold game 80: unfilled bracket slot"])

    def test_a_game_the_page_prints_twice_is_read_once(self):
        """Party on the Pitch's BU10Bronze schedule lists games 37 and 40 twice."""
        game = ("80", _LINK.format(1), 2, 1, _LINK.format(2))

        games, problems = self._parse(_schedule_page(game, ("81", _LINK.format(3), 0, 0, _LINK.format(4)), game))

        assert ([g.game_no for g in games], problems) == (["80", "81"], [])

    def test_a_game_number_repeated_with_other_details_keeps_the_first_and_is_reported(self):
        first, repeat = ("80", _LINK.format(1), 2, 1, _LINK.format(2)), ("80", _LINK.format(1), 5, 1, _LINK.format(2))

        games, problems = self._parse(_schedule_page(first, repeat))

        assert [(g.game_no, g.home_score) for g in games] == [("80", 2)]
        assert problems == ["B11Gold game 80: listed twice with different details"]

    def test_an_unscored_game_is_reported_and_held(self):
        games, problems = self._parse(_schedule_page(("80", _LINK.format(1), "", "", _LINK.format(2))))

        assert (games, problems) == ([], ["B11Gold game 80: no score"])

    def test_a_row_whose_game_number_is_not_plain_digits_is_not_a_game(self):
        games, problems = self._parse(_schedule_page(("٨٠", _LINK.format(1), 2, 1, _LINK.format(2))))

        assert (games, problems) == ([], [])

    def test_games_under_an_unreadable_day_are_held_not_given_the_previous_day(self):
        page = _schedule_page(("80", _LINK.format(1), 2, 1, _LINK.format(2))).replace(
            "</table>",
            "<tr><td colspan=11><b>Sunday, Sept 13, 2026</b></td></tr>"
            f"<tr><td></td><td>81</td><td>B11Gold</td><td>9:00 AM</td><td>F1</td><td>{_LINK.format(1)}</td>"
            f"<td>3</td><td>0</td><td>{_LINK.format(2)}</td><td>-</td><td></td></tr></table>",
        )

        games, problems = self._parse(page)

        assert [(g.game_no, g.game_date) for g in games] == [("80", date(2026, 10, 11))]
        assert problems == ["B11Gold: unreadable day 'Sunday, Sept 13, 2026'", "B11Gold game 81: no date"]

    def test_a_page_with_no_schedule_table_stops_the_run(self):
        """A maintenance page answered with 200 must not read as a division with no games."""
        with pytest.raises(tc.ScrapeFetchError, match="B11Gold: no schedule"):
            self._parse("<html><body>back soon</body></html>")


class TestStateFromLocation:
    @pytest.mark.parametrize(
        "location, state",
        [
            ("Dayton, OH", "OH"),
            ("Kettering, OH, QC", "OH"),
            ("Parkersburg, WV, WV", "WV"),
            ("GC Cosmos 2014/2015 white, OH", "OH"),
            ("dayton/ohio, OH", "OH"),
            ("Toronto, ON", None),
            ("Columbus, OH, MI", None),
            ("Dayton", None),
            ("", None),
        ],
    )
    def test_the_location_names_one_us_state_or_none(self, location, state):
        assert tc.state_from_location(location) == state


class TestClubFor:
    @pytest.mark.parametrize(
        "club_cell, name, expected",
        [
            ("Warrior Soccer Club", "Warrior SC B15/16 White", ("Warrior Soccer Club", "Warrior SC")),
            ("Tournament Only team", "Celina Bulldogs G14/15", ("Celina Bulldogs", "Celina Bulldogs")),
            ("", "PC Unitd G13/14", ("PC Unitd", "PC Unitd")),
            ("PC United", "PC United 12u", ("PC United", "PC United")),
            ("Warrior Soccer Club", "Warrior SC 13/14 White", ("Warrior Soccer Club", "Warrior SC")),
            ("Worthington United", "Worthington United Navy 1 U14", ("Worthington United", "Worthington United")),
            ("Elite FC (Oh)", "U11 Elite FC Pre-ECNL - Black", ("Elite FC (Oh)", "Elite FC")),
            ("Valentis", "VASC B12/13", ("Valentis", "VASC")),
            ("Lakota Futbol Club", "Lakota FC Pre-ECNL U13 Boys", ("Lakota Futbol Club", "Lakota FC")),
            ("Worthington United SC", "Worthington United Navy 1 U14", ("Worthington United SC", "Worthington United")),
            (
                "Dayton Futbol Academy",
                "Dayton Futbol Academy DFA 2012/2013G Premier",
                ("Dayton Futbol Academy", "Dayton Futbol Academy"),
            ),
        ],
    )
    def test_the_club_field_is_the_club_and_the_name_gives_the_written_form(self, club_cell, name, expected):
        assert tc.club_for(club_cell, name, HOST) == expected


def _listing(tc_team_id, name, location="Dayton, OH", club="Some Club"):
    return tc.TeamListing(tc_team_id=tc_team_id, team_name=name, club=club, location=location, coach="")


class TestBuildRoster:
    """A team's age comes from its name alone; the division is neither a bound nor a fallback."""

    @pytest.mark.parametrize(
        "name, age_group",
        [
            ("Warrior SC B15/16 White", "u11"),
            ("Celina Bulldogs G14/15", "u12"),
            ("VASC B12/13", "u14"),
            ("FC Storm BU15 Orange", "u15"),
            ("Panthers Pival 2014", "u13"),
            ("Elite FC U14 Boys Select", "u14"),
        ],
    )
    def test_the_fixture_teams_are_filed_by_their_own_names(self, name, age_group):
        _, in_scope, _, _, _, _ = _collect()

        assert _by_name(in_scope)[name].age_group == age_group

    def test_a_team_playing_up_is_filed_at_its_own_age(self):
        """Celina Bulldogs G14/15 entered the G13 division; the band says U12."""
        _, in_scope, _, _, _, _ = _collect()

        celina = _by_name(in_scope)["Celina Bulldogs G14/15"]
        assert (celina.division_name, celina.age_group) == ("G13Gold", "u12")

    @pytest.mark.parametrize("name", ["RVSC Rampage", "Butler Blaze", "Havok FC"])
    def test_a_name_with_no_age_is_left_out_even_in_a_one_age_division(self, name):
        _, _, skipped, _, _, _ = _collect()

        assert _by_name(skipped)[name].skip_reason == "no age in the team name"

    def test_a_name_older_than_its_division_is_still_read_from_the_name(self):
        """WOU B14 entered a U12 division; 2014 is U13, and the division does not bound it."""
        division = tc.parse_division_code("B129v9Red")

        in_scope, _ = tc.build_roster([(division, _listing("1", "WOU B14"))], _event(), SEASON)

        assert in_scope[0].age_group == "u13"

    @pytest.mark.parametrize(
        "code, name, age_group",
        [
            ("B129v9Gold", "NWC 2033 Boys Elite (U12)", "u12"),
            ("B129v9Red", "PC United 12u", "u12"),
            ("B11Gold", "Northern Alliance G2016", "u11"),
        ],
    )
    def test_spellings_the_label_key_covers_are_read(self, code, name, age_group):
        in_scope, _ = tc.build_roster([(tc.parse_division_code(code), _listing("1", name))], _event(), SEASON)

        assert in_scope[0].age_group == age_group

    @pytest.mark.parametrize(
        "code, name, location, reason",
        [
            ("B11Black", "Ohio Fusion SC BU11/U10 Blue", "Bellbrook, OH", "two U-ages, left out"),
            ("G14-15Red", "Bluffton Legacy Red", "Bluffton, OH", "no age in the team name"),
            ("G107v7Gold", "Northern Alliance Girls 17/18", "Piqua, OH", "birth year 2018 is on no U10-U19 board"),
            ("B11Gold", "Warrior SC B15/16 White", "Toronto, ON", "no US state in the location 'Toronto, ON'"),
        ],
    )
    def test_a_team_that_cannot_be_filed_is_left_out_with_its_reason(self, code, name, location, reason):
        in_scope, skipped = tc.build_roster(
            [(tc.parse_division_code(code), _listing("1", name, location))], _event(), SEASON
        )

        assert in_scope == []
        assert skipped[0].skip_reason == reason

    def test_the_state_comes_from_the_location(self):
        _, in_scope, _, _, _, _ = _collect()

        assert _by_name(in_scope)["Elite FC U14 Boys Select"].state_code == "OH"

    def test_the_operator_files_a_team_whose_name_states_no_age(self):
        """Liederkranz SC plays GirlsU12Red here; the age named is used, not the division's."""
        division = tc.parse_division_code("GirlsU12Red")
        listings = [(division, _listing("1", "Liederkranz SC")), (division, _listing("2", "Ohio Fusion"))]

        in_scope, skipped = tc.build_roster(listings, _event(), SEASON, age_groups={"1": "u10"})

        assert [(row.tc_team_id, row.age_group, row.birth_year, row.age_source) for row in in_scope] == [
            ("1", "u10", 2017, "set by the operator")
        ]
        assert [(row.tc_team_id, row.skip_reason) for row in skipped] == [("2", "no age in the team name")]

    def test_a_team_with_no_age_named_is_still_left_out(self):
        division = tc.parse_division_code("GirlsU12Red")

        in_scope, skipped = tc.build_roster([(division, _listing("1", "Liederkranz SC"))], _event(), SEASON)

        assert in_scope == []
        assert skipped[0].skip_reason == "no age in the team name"

    @pytest.mark.parametrize("value", ["314847=u10", "314847=U10", "1=u19"])
    def test_an_age_option_reads_team_id_and_board(self, value):
        team_id, _, age_group = value.partition("=")

        assert tc._age_for_team(value) == (team_id, age_group.lower())

    @pytest.mark.parametrize(
        "value", ["314847=u9", "314847=u20", "314847=u١٠", "x=u10", "0=u10", "314847", "314847=10"]
    )
    def test_an_age_option_refuses_what_is_not_a_team_and_a_board(self, value):
        with pytest.raises(argparse.ArgumentTypeError):
            tc._age_for_team(value)

    def test_the_operator_sets_the_gender_of_a_team_entered_in_the_other_genders_division(self):
        """FREEDOM U15 GIRLS entered the Boys U14-15 division; the division would file it as Male."""
        division = tc.parse_division_code("BoysU1415Red")
        listings = [(division, _listing("1", "FREEDOM U15 GIRLS")), (division, _listing("2", "Xcel U15"))]

        in_scope, _ = tc.build_roster(listings, _event(), SEASON, genders={"1": "Female"})

        assert [(row.tc_team_id, row.gender) for row in in_scope] == [("1", "Female"), ("2", "Male")]

    @pytest.mark.parametrize("value", ["317937=Female", "317937=female", "317937=MALE"])
    def test_a_gender_option_reads_team_id_and_gender(self, value):
        team_id, _, gender = value.partition("=")

        assert tc._gender_for_team(value) == (team_id, gender.capitalize())

    @pytest.mark.parametrize("value", ["317937=Girls", "317937=F", "317937", "x=Female", "0=Female", "317937=Fem٣le"])
    def test_a_gender_option_refuses_what_is_not_a_team_and_a_gender(self, value):
        with pytest.raises(argparse.ArgumentTypeError):
            tc._gender_for_team(value)

    @staticmethod
    def _cusc(*teams):
        division = tc.parse_division_code("BU10Silver")
        return [(division, _listing(team_id, name, location)) for team_id, name, location in teams]

    def test_the_operator_sets_a_teams_state_where_its_location_is_wrong(self):
        """CUSC West entered Party on the Pitch from 'Fairfield, AL'; the club is in Ohio."""
        listings = self._cusc(
            ("316493", "CUSC BU10 West Yellow", "Fairfield, AL"),
            ("316490", "CUSC BU10 West Ajax", "Ohio, AL"),
            ("315900", "CUSC BU10 South Yellow", "Cincinnati, AL"),
        )

        in_scope, _ = tc.build_roster(listings, _event(), SEASON, states={"316493": "OH", "316490": "OH"})

        assert {row.team_name: row.state_code for row in in_scope} == {
            "CUSC BU10 West Yellow": "OH",
            "CUSC BU10 West Ajax": "OH",
            "CUSC BU10 South Yellow": "AL",
        }

    def test_a_state_the_operator_sets_brings_in_a_team_whose_location_names_none(self):
        listings = self._cusc(("1", "CUSC BU10 West Yellow", "Toronto, ON"))

        in_scope, skipped = tc.build_roster(listings, _event(), SEASON, states={"1": "OH"})

        assert ([row.state_code for row in in_scope], skipped) == (["OH"], [])

    def test_a_team_the_operator_leaves_out_is_skipped_though_its_name_reads(self):
        listings = [
            (tc.parse_division_code("GU11Gold"), _listing("7", "Ohio Fusion SC G11 Blue")),
            (tc.parse_division_code("GU11Gold"), _listing("8", "Ohio Fusion SC GU11 Black")),
        ]

        in_scope, skipped = tc.build_roster(listings, _event(), SEASON, frozenset({"7"}))

        assert [(row.team_name, row.skip_reason) for row in skipped] == [
            ("Ohio Fusion SC G11 Blue", "left out by the operator")
        ]
        assert [row.team_name for row in in_scope] == ["Ohio Fusion SC GU11 Black"]

    def test_collect_event_passes_the_operators_leave_out_list_through(self):
        _, in_scope, _, _, _, _ = _collect()
        celina = _by_name(in_scope)["Celina Bulldogs G14/15"].tc_team_id

        _, in_scope, skipped, _, _, _ = tc.collect_event(
            _PageFetcher(), HOST, "wfc", SEASON, 3650, date(2026, 10, 14), leave_out=frozenset({celina})
        )

        assert "Celina Bulldogs G14/15" not in _by_name(in_scope)
        assert _by_name(skipped)["Celina Bulldogs G14/15"].skip_reason == "left out by the operator"

    @pytest.mark.parametrize("value", ["0123", "abc", "", "1" * 11, "١٢"])
    def test_a_leave_out_value_that_is_not_a_team_id_is_refused(self, value):
        with pytest.raises(argparse.ArgumentTypeError):
            tc._leave_out_id(value)

    def test_a_leave_out_team_id_is_accepted(self):
        assert tc._leave_out_id("319153") == "319153"

    def test_collect_event_passes_the_operators_states_through(self):
        _, in_scope, _, _, _, _ = _collect()
        celina = _by_name(in_scope)["Celina Bulldogs G14/15"].tc_team_id

        _, in_scope, _, _, _, _ = tc.collect_event(
            _PageFetcher(), HOST, "wfc", SEASON, 3650, date(2026, 10, 14), states={celina: "IN"}
        )

        assert _by_name(in_scope)["Celina Bulldogs G14/15"].state_code == "IN"

    @pytest.mark.parametrize("value, expected", [("316490=OH", ("316490", "OH")), ("316490=oh", ("316490", "OH"))])
    def test_a_state_option_reads_team_id_and_state(self, value, expected):
        assert tc._state_for_team(value) == expected

    @pytest.mark.parametrize(
        "value", ["316490", "316490=ZZ", "316490=Ohio", "0123=OH", "abc=OH", "=OH", "1" * 11 + "=OH"]
    )
    def test_a_state_option_that_is_not_team_id_and_state_is_refused(self, value):
        with pytest.raises(argparse.ArgumentTypeError):
            tc._state_for_team(value)

    def test_a_tournament_only_club_falls_back_to_the_names_own_club(self):
        _, in_scope, _, _, _, _ = _collect()

        assert _by_name(in_scope)["Celina Bulldogs G14/15"].club_name == "Celina Bulldogs"


def _in(code, *names):
    division = tc.parse_division_code(code)
    return [(division, _listing(str(i), name)) for i, name in enumerate(names, 1)]


class TestLabelSeasonMismatch:
    def test_the_fixture_tournament_labels_by_its_own_season(self):
        listings = [
            (tc.parse_division_code(code), listing)
            for code in ("B11Gold", "B13Red", "B14-15Gold", "B14-15Red", "G13Gold")
            for listing in _team_list(f"adiv_{code}.html")[0]
        ]

        assert tc.label_season_mismatch(listings, SEASON) is None

    def test_one_division_of_teams_playing_up_does_not_condemn_the_tournament(self):
        """Judged per division, the first one here would read as mislabelled."""
        listings = (
            _in("B11White", "A B16/17", "B 2016/2017", "C B16/17 Red", "D 16/17", "E 2016/17")
            + _in("B11Gold", "F B15/16", "G 2015/2016", "H B15/16 Red")
            + _in("B13Gold", "I B13/14", "J 2013/2014", "K B13/14 Navy")
        )

        assert tc.label_season_mismatch(listings, SEASON) is None

    def test_a_tournament_labelled_by_the_coming_season_is_caught(self):
        listings = _in("B11Gold", "A B16/17", "B 2016/2017", "C B16/17 Red") + _in(
            "B13Gold", "D B14/15", "E 2014/2015", "F B14/15 Navy"
        )

        reason = tc.label_season_mismatch(listings, SEASON)

        assert reason.startswith("6 band-named teams sit one year below their division and 0 at it")

    def test_too_few_band_named_teams_say_nothing(self):
        listings = _in("B11Gold", "A B16/17", "B 2016/2017", "C B16/17 Red", "D 16/17", "E Rampage")

        assert tc.label_season_mismatch(listings, SEASON) is None


def _team_list_page(*names):
    rows = "".join(
        f"<tr><td>A{i}</td><td><b>{name}</b><br><i>Club {i}</i><br>Dayton, OH</td><td>Coach</td>"
        f"<td><form><input type=hidden name=t value={900000 + i}></form></td></tr>"
        for i, name in enumerate(names, 1)
    )
    return f"<table><tr><td><b>Team/Location</b></td></tr>{rows}</table>"


class TestCollectEvent:
    def test_divisions_with_no_board_are_never_fetched(self):
        fetcher = _PageFetcher()

        _, _, _, _, _, division_skips = _collect(fetcher)

        assert not any("t_div=B09" in url or "t_div=G09" in url for url in fetcher.urls)
        assert division_skips == [
            "B09Gold: U9 and below: no board",
            "B09Red: U9 and below: no board",
            "G09Gold: U9 and below: no board",
            "G09Red: U9 and below: no board",
        ]

    def test_a_page_that_cannot_be_read_stops_the_run(self):
        with pytest.raises(tc.ScrapeFetchError):
            _collect(_PageFetcher(fail_on="fnc=sked&sny=Y&t_div=B13Red"))

    def test_a_tournament_labelled_by_the_coming_season_stops_the_run(self):
        """Its labels are read against the tournament's own season, whatever the wall clock says."""
        fetcher = _PageFetcher(
            pages={
                "adiv_B11Gold.html": _team_list_page("A B16/17", "B 2016/2017", "C B16/17 Red"),
                "adiv_B13Red.html": _team_list_page("D B14/15", "E 2014/2015", "F B14/15 Navy"),
                "adiv_B14-15Gold.html": _team_list_page(),
                "adiv_B14-15Red.html": _team_list_page(),
                "adiv_G13Gold.html": _team_list_page(),
            }
        )

        with pytest.raises(tc.LabelSeasonError, match="6 band-named teams sit one year below"):
            _collect(fetcher, board_season=SEASON + 1)

    def test_the_schedules_problems_reach_the_run(self):
        page = _schedule_page(("80", _LINK.format(317605), "", "", _LINK.format(317509)))

        _, _, _, _, problems, _ = _collect(_PageFetcher(pages={"sked_B11Gold.html": page}))

        assert problems == ["B11Gold game 80: no score"]

    def test_games_outside_the_window_are_dropped(self):
        _, _, _, games, _, _ = _collect(days_back=1)

        assert games == []


_SIDE_FIELDS = {
    "1": ("Warrior Soccer Club", "OH"),
    "2": ("Olimpia USA", "MI"),
}


def _team_row(tc_team_id, age_group="u11", gender="Male", birth_year=2016):
    club, state_code = _SIDE_FIELDS.get(tc_team_id, (f"Club {tc_team_id}", "IN"))
    return tc.TeamRow(
        tc_team_id=tc_team_id,
        team_name=f"Team {tc_team_id}",
        club_name=club,
        club_as_written=club,
        division_name="B11Gold",
        division_age="u11",
        birth_year=birth_year,
        age_group=age_group,
        age_source="name",
        gender=gender,
        state_code=state_code,
    )


def _game(home_id, away_id, game_no="71", home_score=2, away_score=1):
    return tc.EventGame(
        division_code="B11Gold",
        game_no=game_no,
        game_date=date(2026, 10, 11),
        game_time="2:45 PM",
        venue="WSC13",
        home_id=home_id,
        home_score=home_score,
        away_id=away_id,
        away_score=away_score,
        source_url="u",
    )


def _linked(*ids):
    return {i: tc.Outcome("created", f"master-{i}", 1.0) for i in ids}


class TestBuildCsvRows:
    def test_a_settled_game_becomes_two_importer_rows(self):
        roster = [_team_row("1"), _team_row("2")]

        records, held, cross_age = tc.build_csv_rows([_game("1", "2")], roster, _linked("1", "2"), _event())

        assert (len(records), held, cross_age) == (2, [], [])
        assert [r["home_away"] for r in records] == ["H", "A"]
        assert [r["result"] for r in records] == ["W", "L"]
        assert [(r["team_id"], r["opponent_id"]) for r in records] == [("1", "2"), ("2", "1")]
        assert [(r["club_name"], r["opponent_club_name"]) for r in records] == [
            ("Warrior Soccer Club", "Olimpia USA"),
            ("Olimpia USA", "Warrior Soccer Club"),
        ]
        assert [(r["state_code"], r["state"]) for r in records] == [("OH", "Ohio"), ("MI", "Michigan")]
        assert records[0]["provider"] == "tourneycentral"
        assert records[0]["event_id"] == "wfc-2026"
        assert records[0]["event_name"] == "Warrior Fall Classic - B11Gold"
        assert records[0]["schedule_id"] == "wfc-71"

    def test_each_game_keeps_its_own_day_kickoff_and_field(self):
        """The tournament starts on 2026-10-10; this game was played the day after."""
        roster = [_team_row("1"), _team_row("2")]

        records, _, _ = tc.build_csv_rows([_game("1", "2")], roster, _linked("1", "2"), _event())

        assert {(r["game_date"], r["game_time"], r["venue"]) for r in records} == {("2026-10-11", "2:45 PM", "WSC13")}

    def test_a_girls_game_is_written_as_girls(self):
        roster = [_team_row("1", gender="Female"), _team_row("2", gender="Female")]

        records, _, _ = tc.build_csv_rows([_game("1", "2")], roster, _linked("1", "2"), _event())

        assert {r["gender"] for r in records} == {"Girls"}

    def test_a_game_whose_team_is_unsettled_is_held(self):
        roster = [_team_row("1"), _team_row("2")]
        outcomes = {**_linked("1"), "2": tc.Outcome("review")}

        records, held, cross_age = tc.build_csv_rows([_game("1", "2")], roster, outcomes, _event())

        assert (records, cross_age) == ([], [])
        assert len(held) == 1

    def test_a_team_playing_up_is_imported_and_recorded(self):
        roster = [_team_row("1", age_group="u10", birth_year=2017), _team_row("2", age_group="u11")]

        records, held, cross_age = tc.build_csv_rows([_game("1", "2")], roster, _linked("1", "2"), _event())

        assert (len(records), held) == (2, [])
        assert [(c["home_age_group"], c["away_age_group"]) for c in cross_age] == [("u10", "u11")]

    def test_a_girls_team_in_a_boys_game_is_imported_and_recorded(self):
        """The second half of the cross-age test, violated on its own."""
        roster = [_team_row("1", gender="Female"), _team_row("2", gender="Male")]

        records, _, cross_age = tc.build_csv_rows([_game("1", "2")], roster, _linked("1", "2"), _event())

        assert len(records) == 2
        assert [(c["home_gender"], c["away_gender"]) for c in cross_age] == [("Female", "Male")]

    def test_every_required_column_is_written(self):
        roster = [_team_row("1"), _team_row("2")]

        records, _, _ = tc.build_csv_rows([_game("1", "2")], roster, _linked("1", "2"), _event())

        assert set(records[0]) == set(tc.REQUIRED_COLUMNS)

    def test_a_same_day_rematch_gets_two_schedule_ids_and_two_game_uids(self):
        """A pool game and the final between the same two teams, on one day.

        This pins the driver's schedule ids and the uid suffix the pipeline appends for
        them. The pipeline's composite duplicate check still merges two such games when
        their orientation and scores also match; that is a known, separate limit.
        """
        roster = [_team_row("1"), _team_row("2")]
        games = [_game("1", "2", game_no="75"), _game("2", "1", game_no="77")]

        records, _, _ = tc.build_csv_rows(games, roster, _linked("1", "2"), _event())

        schedule_ids = [r["schedule_id"] for r in records if r["home_away"] == "H"]
        assert schedule_ids == ["wfc-75", "wfc-77"]
        uid = GameHistoryMatcher.generate_game_uid(
            provider="tourneycentral", game_date="2026-10-11", team1_id="master-1", team2_id="master-2"
        )
        uids = {rematch_game_uid("tourneycentral", uid, {"raw_data": {"schedule_id": s}}) for s in schedule_ids}
        assert len(uids) == 2


class TestSharedLinks:
    def test_two_teams_of_one_tournament_on_one_pitchrank_team_conflict(self):
        outcomes = {
            "1": tc.Outcome("linked_existing", "master-x"),
            "2": tc.Outcome("linked_existing", "master-x"),
            "3": tc.Outcome("linked_existing", "master-y"),
        }

        assert tc.shared_links(outcomes) == {
            "1": "same PitchRank team as Tourney Central team 2",
            "2": "same PitchRank team as Tourney Central team 1",
        }

    @pytest.mark.parametrize("kept", ["already_linked", "relinked"])
    def test_a_link_the_team_already_owns_keeps_it_and_the_fuzzy_one_conflicts(self, kept):
        outcomes = {"1": tc.Outcome(kept, "master-x"), "2": tc.Outcome("linked_existing", "master-x")}

        assert tc.shared_links(outcomes) == {"2": "same PitchRank team as Tourney Central team 1"}


class TestOffBoardLinks:
    def _refused(self, row, outcome, teams):
        return tc.off_board_links([row], {"1": outcome}, teams)

    def test_a_link_whose_stored_board_differs_is_refused(self):
        teams = {"master-1": {"team_id_master": "master-1", "age_group": "u12", "gender": "Male"}}

        refused = self._refused(_team_row("1", age_group="u11"), tc.Outcome("linked_existing", "master-1"), teams)

        assert refused == {"1": "linked team is on the u12 board, this team is u11"}

    def test_a_link_whose_stored_gender_differs_is_refused(self):
        teams = {"master-1": {"team_id_master": "master-1", "age_group": "u11", "gender": "Female"}}

        refused = self._refused(_team_row("1"), tc.Outcome("linked_existing", "master-1"), teams)

        assert refused == {"1": "linked team is Female, this team is Male"}

    def test_a_link_to_a_missing_team_is_refused(self):
        refused = self._refused(_team_row("1"), tc.Outcome("already_linked", "master-gone"), {})

        assert refused == {"1": "linked team not found"}

    def test_a_relinked_team_is_checked_too(self):
        teams = {"master-1": {"team_id_master": "master-1", "age_group": "u13", "gender": "Male"}}

        refused = self._refused(_team_row("1"), tc.Outcome("relinked", "master-1"), teams)

        assert refused == {"1": "linked team is on the u13 board, this team is u11"}

    def test_a_link_that_agrees_and_a_created_team_are_kept(self):
        teams = {"master-1": {"team_id_master": "master-1", "age_group": "u11", "gender": "Male"}}

        assert self._refused(_team_row("1"), tc.Outcome("linked_existing", "master-1"), teams) == {}
        assert self._refused(_team_row("1"), tc.Outcome("created", "master-new"), {}) == {}


class _FakeMatcherForRegister:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def _match_team(self, **kwargs):
        self.calls.append(kwargs["provider_team_id"])
        result = self.results[kwargs["provider_team_id"]]
        if isinstance(result, Exception):
            raise result
        return result


class TestRegisterTeams:
    def test_each_result_shape_lands_in_its_bucket(self):
        rows = [_team_row(str(i)) for i in range(8)]
        direct = {"matched": True, "method": "direct_id", "confidence": 1.0}
        matcher = _FakeMatcherForRegister(
            {
                "1": {**direct, "team_id": "t1", "created": True},
                "2": {"matched": True, "team_id": "t2", "method": "fuzzy_auto", "confidence": 0.95, "created": False},
                "3": {"matched": False, "team_id": None, "method": "fuzzy_review", "confidence": 0.8, "review": True},
                "4": RuntimeError("boom"),
                "5": {**direct, "team_id": "t5", "created": False},
                "6": {**direct, "team_id": "t6", "created": False, "relinked": True},
                "7": {"matched": False, "team_id": None, "method": "no_match", "confidence": 0.0},
            }
        )

        outcomes = tc.register_teams(matcher, "provider", rows, {"0": "t0"})

        assert {k: (o.status, o.team_id_master) for k, o in outcomes.items()} == {
            "0": ("already_linked", "t0"),
            "1": ("created", "t1"),
            "2": ("linked_existing", "t2"),
            "3": ("review", None),
            "4": ("error", None),
            "5": ("already_linked", "t5"),
            "6": ("relinked", "t6"),
            "7": ("error", None),
        }
        assert matcher.calls == ["1", "2", "3", "4", "5", "6", "7"]

    def test_the_club_and_its_written_form_both_reach_the_matcher(self):
        row = _team_row("1")
        row.club_name, row.club_as_written = "Warrior Soccer Club", "Warrior SC"
        captured = {}

        class _Recorder:
            def _match_team(self, **kwargs):
                captured.update(kwargs)
                return {"matched": True, "team_id": "t1", "method": "direct_id", "confidence": 1.0, "created": True}

        tc.register_teams(_Recorder(), "provider", [row], {})

        assert (captured["club_name"], captured["written_club"]) == ("Warrior Soccer Club", "Warrior SC")


class TestUnsavedLinks:
    def test_a_missing_or_misdirected_alias_is_reported(self):
        outcomes = {
            "a": tc.Outcome("linked_existing", "T1"),
            "b": tc.Outcome("created", "T2"),
            "c": tc.Outcome("created", "T3"),
            "d": tc.Outcome("review"),
            "e": tc.Outcome("relinked", "T4"),
            "f": tc.Outcome("already_linked", "T5"),
        }

        assert tc.unsaved_links(outcomes, {"a": "T1", "b": "T9"}) == {
            "b": "link was not saved",
            "c": "link was not saved",
            "e": "link was not saved",
        }


class TestUnsavedReviews:
    def test_only_a_review_outcome_with_no_pending_row_is_reported(self):
        outcomes = {
            "a": tc.Outcome("review", confidence=0.8),
            "b": tc.Outcome("review", confidence=0.8),
            "c": tc.Outcome("created", "T1"),
        }

        assert tc.unsaved_reviews(outcomes, {"a"}) == {"b": "review item was not saved"}


class _Query:
    """A PostgREST read: filters rows, returns only the selected columns, records each batch size."""

    def __init__(self, rows, executed):
        self.rows, self.executed = rows, executed
        self.filters, self.columns, self.batch = [], [], 0

    def select(self, columns):
        self.columns = [c.strip() for c in columns.split(",")]
        return self

    def eq(self, field, value):
        self.filters.append(lambda r, f=field, v=value: r[f] == v)
        return self

    def in_(self, field, values):
        self.batch = len(values)
        self.filters.append(lambda r, f=field, v=tuple(values): r[f] in v)
        return self

    def execute(self):
        self.executed.append(self.batch)
        found = [r for r in self.rows if all(f(r) for f in self.filters)]
        return SimpleNamespace(data=[{c: r[c] for c in self.columns} for r in found])


def _client(table, rows, executed=None):
    def open_table(name):
        assert name == table, f"queried {name!r}, not {table!r}"
        return _Query(rows, [] if executed is None else executed)

    return SimpleNamespace(table=open_table)


class TestExistingAliases:
    def test_only_this_providers_approved_aliases_count(self):
        rows = [
            {"provider_id": "tc", "provider_team_id": "1", "team_id_master": "a", "review_status": "approved"},
            {"provider_id": "gotsport", "provider_team_id": "2", "team_id_master": "b", "review_status": "approved"},
            {"provider_id": "tc", "provider_team_id": "3", "team_id_master": "c", "review_status": "pending"},
        ]

        assert tc.existing_aliases(_client("team_alias_map", rows), "tc", ["1", "2", "3"]) == {"1": "a"}

    def test_ids_are_read_in_batches_of_a_hundred(self):
        executed = []
        rows = [
            {"provider_id": "tc", "provider_team_id": str(i), "team_id_master": f"T{i}", "review_status": "approved"}
            for i in range(150)
        ]

        found = tc.existing_aliases(_client("team_alias_map", rows, executed), "tc", [str(i) for i in range(150)])

        assert executed == [100, 50]
        assert len(found) == 150


class TestPendingReviews:
    def test_the_review_queue_is_read_by_the_provider_code(self):
        """The queue keys providers by code, not by the providers row's id."""
        rows = [
            {"provider_id": "tourneycentral", "provider_team_id": "1", "status": "pending"},
            {"provider_id": "athletes2events", "provider_team_id": "2", "status": "pending"},
            {"provider_id": "tourneycentral", "provider_team_id": "3", "status": "rejected"},
        ]

        assert tc.pending_reviews(_client("team_match_review_queue", rows), ["1", "2", "3"]) == {"1"}


class TestTeamsById:
    def test_every_batch_is_kept_with_the_fields_the_board_check_reads(self):
        executed = []
        fields = {"age_group": "u11", "gender": "Male"}
        rows = [{"team_id_master": f"T{i}", "team_name": f"Team {i}", **fields} for i in range(150)]

        teams = tc.teams_by_id(_client("teams", rows, executed), [f"T{i}" for i in range(150)])

        assert executed == [100, 50]
        assert teams["T0"] == {"team_id_master": "T0", "team_name": "Team 0", **fields}


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
        tc_team_id = kwargs["provider_team_id"]
        self.matched.append(tc_team_id)
        created = {"matched": True, "team_id": f"new-{tc_team_id}", "method": "direct_id", "created": True}
        return _FakeMatcher.results.get(tc_team_id, {**created, "confidence": 1.0})


class _ProvidersClient:
    def table(self, _name):
        return self

    def select(self, *_a):
        return self

    def eq(self, *_a):
        return self

    def execute(self):
        return SimpleNamespace(data=[{"id": "tc-provider"}])


class _FixedDate(date):
    @classmethod
    def today(cls):
        return date(2026, 10, 14)


@pytest.fixture
def run_main(monkeypatch, tmp_path):
    def run(*flags, fetcher=None, board_season=SEASON, results=None, saved=None, queued=None, teams=None):
        """Run ``main`` with every outside call stood in for.

        Before the run nothing is linked. Afterwards ``saved`` is what the alias table
        holds (default: every alias the matcher reported), ``queued`` the pending review
        rows (default: every review it reported) and ``teams`` the stored team rows.
        """
        _FakeMatcher.instances = []
        _FakeMatcher.results = results or {}
        imports = []
        alias_calls = []
        fetcher = fetcher or _PageFetcher()

        def fake_existing_aliases(_client, _provider_id, tc_team_ids):
            alias_calls.append(list(tc_team_ids))
            if len(alias_calls) == 1:
                return {}
            return saved if saved is not None else {i: f"new-{i}" for i in tc_team_ids}

        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
        monkeypatch.setattr(tc, "create_client", lambda *_a: _ProvidersClient())
        monkeypatch.setattr(tc, "make_session", lambda: None)
        monkeypatch.setattr(tc, "_fetch", lambda _s, url: fetcher(url))
        monkeypatch.setattr(tc, "TourneyCentralGameMatcher", _FakeMatcher)
        monkeypatch.setattr(tc, "existing_aliases", fake_existing_aliases)
        monkeypatch.setattr(tc, "pending_reviews", lambda _c, ids: set(ids) if queued is None else queued)
        monkeypatch.setattr(tc, "teams_by_id", lambda _c, ids: {i: t for i, t in (teams or {}).items() if i in ids})
        # Asked for the wall clock (no date) it answers the board season; asked about the
        # tournament's own date it answers the real one.
        real_season = tc._soccer_season_year
        monkeypatch.setattr(
            tc, "_soccer_season_year", lambda now=None: board_season if now is None else real_season(now)
        )
        monkeypatch.setattr(tc, "date", _FixedDate)
        monkeypatch.setattr(
            tc.subprocess, "run", lambda cmd, check: imports.append(cmd) or SimpleNamespace(returncode=0)
        )
        argv = [
            "import_tourneycentral_event.py",
            "--event-url",
            f"https://{HOST}/games.html",
            "--output-dir",
            str(tmp_path),
            "--days-back",
            "3650",
            "--delay-min",
            "0",
            "--delay-max",
            "0",
        ]
        monkeypatch.setattr(tc.sys, "argv", [*argv, *flags])

        try:
            code = tc.main()
        finally:
            _FakeMatcher.results = {}
        if code != 0:
            return SimpleNamespace(code=code, imports=imports, outcomes={}, games=[], cross_age=[])
        [report] = tmp_path.glob("*_teams.csv")
        [games_csv] = tmp_path.glob("*_games.csv")
        [cross_age_csv] = tmp_path.glob("*_cross_age.csv")
        return SimpleNamespace(
            code=code,
            imports=imports,
            outcomes={r["team_name"]: r for r in csv.DictReader(report.open(encoding="utf-8"))},
            games=list(csv.DictReader(games_csv.open(encoding="utf-8"))),
            cross_age=list(csv.DictReader(cross_age_csv.open(encoding="utf-8"))),
            files=sorted(p.name for p in tmp_path.iterdir()),
        )

    return run


def _written(result):
    return {r["team_id"] for r in result.games} | {r["opponent_id"] for r in result.games}


class TestMain:
    def test_a_dry_run_builds_only_a_dry_run_matcher_and_starts_no_import(self, run_main):
        result = run_main()

        assert result.code == 0
        assert result.imports == []
        assert [(m.dry_run, m.registration_mode) for m in _FakeMatcher.instances] == [(True, True)]
        assert all(name.startswith("wfc_2026_") for name in result.files)

    def test_execute_imports_the_games_csv_under_this_provider(self, run_main):
        result = run_main("--execute")

        assert [(m.dry_run, m.registration_mode) for m in _FakeMatcher.instances] == [(True, True), (False, True)]
        [command] = result.imports
        assert command[1:2] == ["scripts/import_games_enhanced.py"]
        assert command[-1] == "tourneycentral"

    def test_a_page_that_cannot_be_read_exits_before_any_team_is_registered(self, run_main):
        result = run_main("--execute", fetcher=_PageFetcher(fail_on="t_div=B13Red"))

        assert result.code == 1
        assert (_FakeMatcher.instances, result.imports) == ([], [])

    def test_a_tournament_labelled_by_another_season_exits_before_any_team_is_registered(self, run_main):
        pages = {
            "adiv_B11Gold.html": _team_list_page("A B16/17", "B 2016/2017", "C B16/17 Red"),
            "adiv_B13Red.html": _team_list_page("D B14/15", "E 2014/2015", "F B14/15 Navy"),
            "adiv_B14-15Gold.html": _team_list_page(),
            "adiv_B14-15Red.html": _team_list_page(),
            "adiv_G13Gold.html": _team_list_page(),
        }

        result = run_main("--execute", fetcher=_PageFetcher(pages=pages))

        assert result.code == 1
        assert (_FakeMatcher.instances, result.imports) == ([], [])

    def test_a_bad_tournament_url_stops_before_any_fetch(self, run_main):
        fetcher = _PageFetcher()

        result = run_main("--event-url", "https://wfc.example.com/games.html", fetcher=fetcher)

        assert (result.code, fetcher.urls) == (1, [])

    def test_a_left_out_team_is_reported_and_none_of_its_games_is_written(self, run_main):
        result = run_main()

        assert result.outcomes["RVSC Rampage"]["outcome"] == "skipped"
        assert result.outcomes["RVSC Rampage"]["reason"] == "no age in the team name"
        assert "314628" not in _written(result)

    def test_every_game_written_has_two_rows(self, run_main):
        result = run_main()

        by_game = {}
        for row in result.games:
            by_game.setdefault(row["schedule_id"], []).append(row)
        assert by_game
        assert all(len(rows) == 2 for rows in by_game.values())

    def test_a_team_playing_up_is_listed_in_the_cross_age_file(self, run_main):
        """Celina Bulldogs G14/15 (U12) played the G13 division."""
        result = run_main()

        celina = [c for c in result.cross_age if "314448" in (c["home_team_id"], c["away_team_id"])]
        assert celina
        assert all("u12" in (c["home_age_group"], c["away_age_group"]) for c in celina)
        assert "314448" in _written(result)

    def test_labels_are_read_against_the_tournament_and_boards_against_the_wall_clock(self, run_main):
        """Swapping the two seasons would file this 2026 tournament's teams a year out."""
        result = run_main(board_season=SEASON + 1)

        # A band names birth years: B15/16 is U11 now and U12 a season later.
        assert result.outcomes["Warrior SC B15/16 White"]["age_group"] == "u12"
        # A U-age is read in the tournament's season, then filed on the later board.
        assert result.outcomes["U11 Elite FC Pre-ECNL - Black"]["age_group"] == "u12"

    def test_a_formula_in_a_team_name_is_defanged_in_the_report_only(self, run_main):
        pages = {"adiv_B11Gold.html": _team_list_page('=HYPERLINK("x") U11')}

        result = run_main(fetcher=_PageFetcher(pages=pages))

        assert '\'=HYPERLINK("x") U11' in result.outcomes


class TestMainWriteVerification:
    """``--execute`` re-reads what the matcher reported writing; the matcher swallows its own failures."""

    FUZZY = {"matched": True, "team_id": "T1", "method": "fuzzy_auto", "confidence": 0.95, "created": False}

    def test_two_teams_linking_to_one_pitchrank_team_conflict_and_are_never_written(self, run_main):
        result = run_main("--execute", results={"317605": dict(self.FUZZY), "317509": dict(self.FUZZY)})

        assert {
            result.outcomes[n]["outcome"] for n in ("Club Ohio Dayton U11B Green", "U11 Elite FC Pre-ECNL - Black")
        } == {"conflict"}
        writer = _FakeMatcher.instances[1]
        assert "317605" not in writer.matched and "317509" not in writer.matched
        assert not {"317605", "317509"} & _written(result)

    def test_a_link_the_alias_table_does_not_confirm_is_an_error_and_writes_no_game(self, run_main):
        result = run_main("--execute", saved={})

        assert {o["outcome"] for o in result.outcomes.values() if o["outcome"] != "skipped"} == {"error"}
        assert {o["reason"] for o in result.outcomes.values() if o["outcome"] == "error"} == {"link was not saved"}
        assert result.games == []

    def test_an_alias_pointing_at_another_team_is_an_error(self, run_main):
        result = run_main("--execute", results={"317605": dict(self.FUZZY)}, saved={"317605": "T-other"})

        assert result.outcomes["Club Ohio Dayton U11B Green"]["outcome"] == "error"
        assert "317605" not in _written(result)

    def test_a_review_with_no_pending_row_is_an_error(self, run_main):
        review = {"matched": False, "team_id": None, "method": "fuzzy_review", "confidence": 0.8, "review": True}

        result = run_main("--execute", results={"317605": review}, queued=set())

        assert result.outcomes["Club Ohio Dayton U11B Green"]["outcome"] == "error"
        assert result.outcomes["Club Ohio Dayton U11B Green"]["reason"] == "review item was not saved"

    def test_a_linked_team_stored_on_another_board_is_an_error_and_its_games_are_held(self, run_main):
        teams = {"T1": {"team_id_master": "T1", "team_name": "Other", "age_group": "u14", "gender": "Male"}}

        result = run_main("--execute", results={"317605": dict(self.FUZZY)}, saved={"317605": "T1"}, teams=teams)

        assert result.outcomes["Club Ohio Dayton U11B Green"]["outcome"] == "error"
        assert "u14" in result.outcomes["Club Ohio Dayton U11B Green"]["reason"]
        assert "317605" not in _written(result)
