"""Unit tests for the Demosphere driver."""

import csv
import inspect
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from bs4 import BeautifulSoup

from scripts import import_demosphere as dm
from scripts import import_games_enhanced
from scripts.import_athletes2events_event import Outcome
from src.models.demosphere_matcher import DemosphereGameMatcher, expand_club_code
from src.models.tourneycentral_matcher import TourneyCentralGameMatcher

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "demosphere"
FALL_SEASON_KEY = "116702823"
SPRING_SEASON_KEY = "115907747"
DIVISION_URL = "https://elements.demosphere.com/80738/schedules/Fall2026/116702955.html"
SCHEDULE_LINK = '<a href="/80738/schedules/Fall2026/116702955.html">NG13D4</a>'
PLACEHOLDERS = {"PERSON NAME", "COACH NAME", "MANAGER NAME", "ASST COACH NAME"}


def _fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def division():
    return dm.parse_division_page(_fixture("division_116702955.html"), "116702955", DIVISION_URL)


class TestParseDivisionPage:
    def test_reads_the_division_name(self, division):
        assert division.name == "GU13 Division 4"

    def test_reads_every_team_and_game(self, division):
        assert len(division.teams) == 10
        assert len(division.games) == 45
        assert division.problems == []

    def test_played_games_carry_scores_and_unplayed_do_not(self, division):
        played = [g for g in division.games if g.home_score is not None]
        unplayed = [g for g in division.games if g.home_score is None]
        assert (len(played), len(unplayed)) == (34, 11)
        assert all(g.away_score is not None for g in played)
        assert all(g.away_score is None for g in unplayed)
        assert max(g.game_date for g in played) == date(2026, 10, 25)
        assert min(g.game_date for g in unplayed) >= date(2026, 10, 31)

    def test_first_game_reads_both_sides_the_date_and_the_venue(self, division):
        first = division.games[0]
        assert (first.game_key, first.game_date) == ("11635852", date(2026, 9, 12))
        assert (first.home_key, first.home_score, first.away_key, first.away_score) == (
            "116796872",
            2,
            "116800863",
            1,
        )
        assert first.venue == "Potomac Green Park #2"
        assert first.division_name == "GU13 Division 4"

    def test_a_team_keeps_its_full_name_without_the_team_code(self, division):
        stub = division.teams["114577143"]
        assert (stub.team_code, stub.team_name, stub.club_key) == ("NG14107", "Villarreal VA Azul G2013/14", "97998447")
        assert division.teams["116800863"].team_name == "VISTA Warriors U13G"
        assert division.teams["108348806"].team_name == "ALEX 2013-14 Girls Red"

    def test_a_game_with_no_readable_date_is_reported_not_dropped_silently(self):
        html = _fixture("division_116702955.html").replace("Sat, September 12, 2026", "NEXT WEEK")
        page = dm.parse_division_page(html, "116702955", DIVISION_URL)
        assert any("unreadable" in problem for problem in page.problems)
        assert len(page.games) < 45

    def test_an_unrecognised_score_is_reported(self):
        html = _fixture("division_116702955.html").replace(" 2-1 ", " PPD ", 1)
        page = dm.parse_division_page(html, "116702955", DIVISION_URL)
        assert any("unreadable score 'PPD'" in problem for problem in page.problems)

    def test_a_forfeit_is_counted_not_scored_and_is_not_a_problem(self):
        html = _fixture("division_116702955.html").replace(" 2-1 ", " FFT ", 1)
        page = dm.parse_division_page(html, "116702955", DIVISION_URL)
        assert page.forfeits == ["11635852"]
        assert page.problems == []
        forfeited = next(g for g in page.games if g.game_key == "11635852")
        assert (forfeited.home_score, forfeited.away_score) == (None, None)

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ('data-cbkey="15599453"', 'data-cbkey="../../scripts/runisa.dll?x"'),
            ('data-tmkey="116796872"', 'data-tmkey="1_2"'),
            ('data-tmkey="116796872"', 'data-tmkey="١٢٣"'),
            ('data-gamekey="11635852"', 'data-gamekey="11635852/../x"'),
        ],
    )
    def test_a_key_that_is_not_ascii_digits_makes_the_row_unreadable(self, old, new):
        html = _fixture("division_116702955.html").replace(old, new, 1)
        page = dm.parse_division_page(html, "116702955", DIVISION_URL)
        assert any("unreadable game row" in problem for problem in page.problems)

    def test_a_page_with_no_schedule_is_a_problem_not_an_empty_division(self):
        page = dm.parse_division_page("<html><body>Down for maintenance</body></html>", "116702955", DIVISION_URL)
        assert page.problems == ["116702955: no schedule table or division name in the page"]
        assert page.games == []


class TestParseClubPage:
    def test_reads_the_club_name(self):
        name, _ = dm.parse_club_page(_fixture("club_15599479.html"))
        assert name == "VA Indpt Soccer Team Assoc - Travel"

    def test_links_carry_season_team_and_division_keys(self):
        _, links = dm.parse_club_page(_fixture("club_15599479.html"))
        assert {season for season, _, _ in links} == {FALL_SEASON_KEY, SPRING_SEASON_KEY}
        assert ("116702823", "116807548", "116702997") in links

    def test_season_key_is_the_one_most_links_carry(self):
        assert dm.season_key(_fixture("club_15599479.html")) == FALL_SEASON_KEY

    def test_a_page_with_no_team_links_has_no_season_key(self):
        assert dm.season_key("<html></html>") is None


def _schedule_page(label="Fall2026"):
    return _fixture("club_15599479.html") + SCHEDULE_LINK.replace("Fall2026", label)


class TestCollectLeague:
    def _fetch(self, requested):
        club_html = _fixture("club_15599479.html")
        division_html = _fixture("division_116702955.html")

        def fetch(url):
            requested.append(url)
            if "/clubs/schedule/15599479" in url:
                return _schedule_page()
            if "/teams/club/15599479" in url:
                return club_html
            if "/teams/club/" in url:
                return '<h1 class="dii-hdr-cb">Another Club</h1>'
            if "/schedules/Fall2026/" in url:
                return division_html
            raise AssertionError(f"unexpected fetch {url}")

        return fetch

    def test_walks_the_seed_clubs_divisions_and_the_clubs_those_name(self):
        requested = []
        clubs, divisions, problems = dm.collect_league(self._fetch(requested), "80738", "Fall2026", ["15599479"])
        _, links = dm.parse_club_page(_fixture("club_15599479.html"))
        fall_divisions = {division for season, _, division in links if season == FALL_SEASON_KEY}
        spring_divisions = {division for season, _, division in links if season == SPRING_SEASON_KEY}
        assert set(divisions) == fall_divisions
        assert spring_divisions - fall_divisions
        assert clubs["15599479"] == "VA Indpt Soccer Team Assoc - Travel"
        assert clubs["15599453"] == "Another Club"
        assert problems == []

    def test_fetches_each_page_once(self):
        requested = []
        dm.collect_league(self._fetch(requested), "80738", "Fall2026", ["15599479"])
        club_pages = [url for url in requested if "/teams/club/" in url]
        division_pages = [url for url in requested if "/schedules/" in url]
        assert len(club_pages) == len(set(club_pages))
        assert len(division_pages) == len(set(division_pages))

    def test_max_divisions_stops_the_walk(self):
        _, divisions, _ = dm.collect_league(self._fetch([]), "80738", "Fall2026", ["15599479"], max_divisions=2)
        assert len(divisions) == 2

    def test_pauses_after_every_fetch(self):
        pauses = []
        requested = []
        dm.collect_league(
            self._fetch(requested), "80738", "Fall2026", ["15599479"], lambda: pauses.append(1), max_divisions=1
        )
        assert len(pauses) == len(requested)

    def test_a_seed_club_with_no_team_links_fails_the_run(self):
        page = '<a href="/80738/schedules/Fall2026/1.html">x</a>'
        with pytest.raises(dm.ScrapeFetchError):
            dm.collect_league(lambda url: page, "80738", "Fall2026", ["15599479"])

    def test_a_season_the_site_does_not_list_fails_the_run_before_any_division_is_fetched(self):
        requested = []
        with pytest.raises(dm.ScrapeFetchError, match="Spring2026"):
            dm.collect_league(self._fetch(requested), "80738", "Spring2026", ["15599479"])
        assert not any("/schedules/" in url for url in requested)


class TestClubFor:
    def test_the_listed_club_is_used_when_the_name_opens_with_its_words(self):
        club, written, source = dm.club_for("Villarreal Virginia Academy", "Villarreal VA Azul G2013/14")
        assert (club, source) == ("Villarreal Virginia Academy", "listed club")
        assert written == "Villarreal VA Azul"

    def test_an_association_is_not_the_club_of_the_teams_under_it(self):
        club, _, source = dm.club_for(
            "VA Indpt Soccer Team Assoc - Travel", "VISTA HL92 Soccer Academy U11G Pink", association=True
        )
        assert source == "cut from name"
        assert club == "VISTA HL92 Soccer Academy"

    def test_a_team_written_with_a_club_code_is_filed_under_the_clubs_full_listed_name(self):
        assert dm.club_for("Herndon Youth Soccer Assoc - Travel", "HERN NCSL B2011/12 White") == (
            "Herndon Youth Soccer",
            "HERN NCSL",
            "listed club",
        )

    @pytest.mark.parametrize(
        ("name", "club"),
        [
            ("GSC Boys 13/14 Premier", "GSC"),
            ("NPSC United 2014 Boys", "NPSC United"),
            ("ARL 2013/14B Black (U13)", "ARL"),
            ("BRYC Academy B2014/15 Black", "BRYC Academy"),
            ("GSC Girls 14/15 Red", "GSC"),
            ("VISTA Blackwatch 2011G", "VISTA Blackwatch"),
            ("Arlington 2012G Red", "Arlington"),
            ("VISTA HL92 Soccer Academy 2013B Yellow", "VISTA HL92 Soccer Academy"),
            ("Loudoun Soccer 14B Red", "Loudoun Soccer"),
            ("VISTA Blackwatch 13-14 Red", "VISTA Blackwatch"),
            ("Loudoun 13/14 Red", "Loudoun"),
            ("Girls Academy 2013 Red", "Girls Academy"),
            ("NPSC United Elite 2014 Boys", "NPSC United Elite"),
        ],
    )
    def test_the_club_cut_from_a_name_stops_before_the_age_and_gender(self, name, club):
        assert dm.club_for("", name)[0] == club

    def test_a_listed_club_with_no_name_in_the_team_name_falls_back_to_the_name(self):
        club, _, source = dm.club_for("", "ALEX 2013-14 Girls Red")
        assert (club, source) == ("ALEX", "cut from name")


class TestTeamAge:
    @pytest.mark.parametrize(
        ("name", "division", "expected"),
        [
            ("Villarreal VA Azul G2013/14", "GU13 Division 4", 2014),
            ("LOUD U13G White", "GU13 Division 4", 2014),
            ("ALEX 2013-14 Girls Red", "GU13 Division 4", 2014),
            ("BRU U12B Blue", "BU13 Division 1", 2015),
        ],
    )
    def test_the_name_states_the_age(self, name, division, expected):
        assert dm.team_age(name, division, 2026)[0] == expected

    def test_the_name_wins_over_the_division(self):
        birth_year, source = dm.team_age("Club U11B Red", "BU13 Division 1", 2026)
        assert birth_year == 2016
        assert "division" not in source

    def test_a_name_with_no_age_takes_the_divisions(self):
        birth_year, source = dm.team_age("Warriors FC Black", "GU13 Division 4", 2026)
        assert birth_year == 2014
        assert source == "no age in the team name, division GU13 Division 4 used"

    def test_a_name_with_no_age_and_a_division_with_none_is_left_out(self):
        birth_year, source = dm.team_age("Warriors FC Black", "Premier Flight", 2026)
        assert birth_year is None
        assert source == "no age in the team name, and no age in the division name"

    def test_an_odd_year_span_takes_the_divisions_age_as_a_name_with_none_does(self):
        birth_year, source = dm.team_age("Club G2018-2016", "GU13 Division 4", 2026)
        assert birth_year == 2014
        assert source == "odd year span in the team name, division GU13 Division 4 used"

    def test_a_name_with_two_u_ages_is_left_out_not_given_the_divisions(self):
        birth_year, source = dm.team_age("Club U12/U13 Blue", "GU13 Division 4", 2026)
        assert birth_year is None
        assert "two U-ages" in source

    @pytest.mark.parametrize(
        ("name", "division", "expected", "source"),
        [
            ("FFC B12 Atletico", "BU12 Division 1", 2015, "B12 read as U12"),
            ("FFC B10 Roma", "BU10 Division P", 2017, "B10 read as U10"),
            (
                "TAFC Team America Spartans 2014",
                "BU12 Division 5",
                2015,
                "birth year 2014, one reading fits the division",
            ),
            ("Loudoun B2007", "BU19 N1", 2008, "birth year 2007, one reading fits the division"),
        ],
    )
    def test_a_bare_year_or_tag_is_bounded_by_the_divisions_age(self, name, division, expected, source):
        assert dm.team_age(name, division, 2026) == (expected, source)

    def test_a_bare_year_that_fits_the_division_and_the_one_above_is_the_divisions(self):
        assert dm.team_age("Loudoun G2014", "GU13 Division 4", 2026) == (
            2014,
            "birth year 2014, division GU13 Division 4 used",
        )

    def test_a_bare_year_that_fits_neither_reading_is_left_out(self):
        birth_year, source = dm.team_age("Loudoun G2014", "GU9 Division 1", 2026)
        assert birth_year is None
        assert source == "birth year 2014 could be 2014 or 2015"

    def test_a_name_older_than_its_division_is_left_out(self):
        birth_year, source = dm.team_age("Club U13 Blue", "BU12 Division 5", 2026)
        assert birth_year is None
        assert source == "name is older than its U12 division"

    def test_labels_are_read_against_the_event_season(self):
        assert dm.team_age("Club U13G", "", 2025)[0] == 2013
        assert dm.team_age("Club U13G", "", 2026)[0] == 2014


class TestTeamCohort:
    def test_a_lone_birth_year_the_band_reading_rejects_is_still_on_its_board(self):
        assert dm.team_cohort(2007, "birth year 2007", 2026) == "u19"

    def test_a_band_that_has_aged_out_is_on_no_board(self):
        assert dm.team_cohort(2007, "name", 2026) is None

    def test_a_lone_year_too_old_for_any_board_is_on_none(self):
        assert dm.team_cohort(2005, "birth year 2005", 2026) is None

    def test_an_ordinary_year_takes_the_band_reading(self):
        assert dm.team_cohort(2014, "name", 2026) == "u13"
        assert dm.team_cohort(2014, "birth year 2014", 2026) == "u13"

    def test_no_birth_year_is_no_board(self):
        assert dm.team_cohort(None, "anything", 2026) is None


class TestTeamGender:
    @pytest.mark.parametrize(
        ("division", "code", "expected"),
        [
            ("GU13 Division 4", "", "Female"),
            ("BU19 N1", "", "Male"),
            ("Premier Flight", "NG13128", "Female"),
            ("Premier Flight", "NB1405", "Male"),
            ("Premier Flight", "", None),
        ],
    )
    def test_division_first_then_team_code(self, division, code, expected):
        assert dm.team_gender(division, code) == expected

    def test_the_division_outranks_the_code(self):
        assert dm.team_gender("BU13 Division 1", "NG13128") == "Male"


class TestSeasonCandidates:
    @pytest.mark.parametrize(
        ("today", "expected"),
        [
            (date(2026, 10, 29), ["Fall2026", "Spring2026"]),
            (date(2026, 8, 1), ["Fall2026", "Spring2026"]),
            (date(2026, 12, 31), ["Fall2026", "Spring2026"]),
            (date(2027, 1, 1), ["Spring2027", "Fall2026"]),
            (date(2027, 7, 31), ["Spring2027", "Fall2026"]),
        ],
    )
    def test_the_current_season_is_tried_first_and_the_one_before_it_second(self, today, expected):
        assert dm.season_candidates(today) == expected


class TestSeasonLabel:
    @pytest.mark.parametrize(("label", "year"), [("Fall2026", 2026), ("Spring2027", 2026), ("Spring2026", 2025)])
    def test_fall_and_the_following_spring_are_one_season(self, label, year):
        assert dm.season_start_year(label) == year

    def test_an_unknown_label_is_refused(self):
        with pytest.raises(ValueError):
            dm.season_start_year("Winter2026")

    @pytest.mark.parametrize("label", ["Fall2026x", "Fall2026\n", "Fall20٢٦", "fall2026", "Fall 2026"])
    def test_a_label_that_only_looks_like_a_season_is_refused(self, label):
        with pytest.raises(ValueError):
            dm.season_start_year(label)

    @pytest.mark.parametrize(
        ("today", "label"),
        [
            (date(2026, 8, 1), "Fall2026"),
            (date(2026, 12, 31), "Fall2026"),
            (date(2027, 1, 1), "Spring2027"),
            (date(2027, 7, 31), "Spring2027"),
        ],
    )
    def test_the_current_label_follows_the_calendar(self, today, label):
        assert dm.current_season_label(today) == label

    def test_every_current_label_is_one_the_driver_can_read(self):
        for month in range(1, 13):
            dm.season_start_year(dm.current_season_label(date(2026, month, 15)))


class TestResolveState:
    def test_the_leagues_state_is_the_default(self):
        assert dm.resolve_state("LOUD U13G White", "LOUD", {}, "VA") == ("VA", "league state")

    def test_the_clubs_stored_state_wins_over_the_leagues(self):
        assert dm.resolve_state("Bowie U13G", "Bowie Soccer Club", {"Bowie Soccer Club": "MD"}, "VA") == (
            "MD",
            "club's stored teams",
        )

    def test_a_club_whose_stored_teams_disagree_is_held(self):
        state, reason = dm.resolve_state("Club U13G", "Club", {"Club": None}, "VA")
        assert state is None
        assert "disagree" in reason

    def test_another_states_tag_in_the_name_is_held_not_stamped(self):
        state, reason = dm.resolve_state("Bowie SC B2009/08 PREMIER (MD)", "Bowie SC", {}, "VA")
        assert state is None
        assert "MD" in reason

    def test_the_leagues_own_tag_is_no_reason_to_hold(self):
        assert dm.resolve_state("NSC N1 B2009/08 PREMIER RED (VA)", "NSC", {}, "VA")[0] == "VA"

    def test_a_tag_that_is_not_a_state_is_ignored(self):
        assert dm.resolve_state("Club U13 (XX)", "Club", {}, "VA")[0] == "VA"


def _stub(key, name, club="1", code="NG13100", division="GU13 Division 4"):
    return dm.TeamStub(key, club, code, name, division)


def _roster(stubs, clubs=None, stored=None, asked=None, association=()):
    def lookup(names):
        if asked is not None:
            asked.append(names)
        return stored or {}

    return dm.build_roster(
        {stub.team_key: stub for stub in stubs},
        clubs or {"1": "Loudoun Soccer"},
        lookup,
        "80738",
        "Fall2026",
        "VA",
        2026,
        association,
    )


class TestBuildRoster:
    def test_a_team_carries_everything_the_matcher_needs(self):
        (row,), left_out = _roster([_stub("11", "Loudoun U13G White")])
        assert left_out == []
        assert (row.provider_team_id, row.age_group, row.gender, row.state_code) == (
            "80738-Fall2026-11",
            "u13",
            "Female",
            "VA",
        )
        assert (row.club_name, row.club_source, row.team_code) == ("Loudoun Soccer", "listed club", "NG13100")

    def test_the_age_group_is_the_board_the_birth_year_sits_on_now(self):
        (row,), _ = _roster([_stub("11", "Loudoun G2014")])
        assert row.age_group == "u13"

    def test_a_lone_2007_birth_year_is_on_the_u19_board(self):
        (row,), _ = _roster([_stub("11", "Loudoun B2007", division="Premier Flight", code="NB1900")])
        assert (row.age_group, row.gender, row.age_source) == ("u19", "Male", "birth year 2007")

    def test_a_team_on_no_board_is_left_out_with_its_reason(self):
        in_scope, (row,) = _roster([_stub("11", "Loudoun U8B", division="BU8 Division 1")])
        assert in_scope == []
        assert "no U10-U19 board" in row.skip_reason

    def test_a_team_with_no_age_anywhere_is_left_out(self):
        in_scope, (row,) = _roster([_stub("11", "Loudoun Blue", division="Premier Flight", code="NG13100")])
        assert in_scope == []
        assert "no age" in row.skip_reason

    def test_a_team_with_no_gender_is_left_out(self):
        in_scope, (row,) = _roster([_stub("11", "Loudoun U13 Blue", code="", division="Open Division")])
        assert in_scope == []
        assert row.skip_reason == "division and team code name no gender"

    def test_a_team_held_for_state_is_left_out_with_that_reason(self):
        in_scope, (row,) = _roster([_stub("11", "Bowie U13G (MD)")])
        assert in_scope == []
        assert "MD" in row.skip_reason

    def test_teams_are_ordered_by_team_key(self):
        in_scope, _ = _roster([_stub("30", "Loudoun U13G A"), _stub("4", "Loudoun U13G B")])
        assert [row.team_key for row in in_scope] == ["4", "30"]

    def test_the_stored_state_lookup_is_asked_about_the_clubs_the_roster_uses(self):
        asked = []
        _roster(
            [_stub("11", "VISTA HL92 Soccer Academy U13G", club="2"), _stub("12", "Loudoun U13G White")],
            clubs={"1": "Loudoun Soccer", "2": "VA Indpt Soccer Team Assoc - Travel"},
            asked=asked,
            association=("2",),
        )
        assert asked == [["Loudoun Soccer", "VISTA HL92 Soccer Academy"]]

    def test_an_association_teams_club_state_comes_from_the_club_cut_from_its_name(self):
        stub = _stub("11", "VISTA HL92 Soccer Academy U13G", club="2")
        clubs = {"2": "VA Indpt Soccer Team Assoc - Travel"}
        (row,), _ = _roster([stub], clubs=clubs, stored={"VISTA HL92 Soccer Academy": "MD"}, association=("2",))
        assert (row.state_code, row.state_source) == ("MD", "club's stored teams")

    def test_a_club_whose_stored_teams_disagree_leaves_its_team_out(self):
        stub = _stub("11", "VISTA HL92 Soccer Academy U13G", club="2")
        clubs = {"2": "VA Indpt Soccer Team Assoc - Travel"}
        in_scope, (row,) = _roster([stub], clubs=clubs, stored={"VISTA HL92 Soccer Academy": None}, association=("2",))
        assert in_scope == []
        assert "disagree" in row.skip_reason


class TestMergeTeams:
    def test_a_team_in_two_divisions_keeps_the_first_division_by_key(self):
        first = dm.DivisionPage("BU13 Division 1", teams={"5": _stub("5", "Club U13B", division="BU13 Division 1")})
        second = dm.DivisionPage("Cup", teams={"5": _stub("5", "Club U13B", division="Cup")})
        assert dm.merge_teams({"200": second, "100": first})["5"].division_name == "BU13 Division 1"
        assert dm.merge_teams({"100": second, "200": first})["5"].division_name == "Cup"


def _row(key, age="u13", gender="Female", name=None):
    return dm.TeamRow(
        provider_team_id=f"80738-Fall2026-{key}",
        team_key=key,
        team_code="",
        team_name=name or f"Team {key}",
        demosphere_club=f"Listed {key}",
        club_name=f"Club {key}",
        club_as_written=f"Written {key}",
        club_source="listed club",
        division_name="GU13 Division 4",
        age_group=age,
        age_source="name",
        gender=gender,
        state_code={"1": "VA", "2": "MD"}.get(key, "VA"),
        state_source="league state",
    )


def _game(key="100", day=date(2026, 9, 12), home="1", away="2", score=(2, 1)):
    return dm.RawGame(
        game_key=key,
        game_date=day,
        home_key=home,
        away_key=away,
        home_score=score[0] if score else None,
        away_score=score[1] if score else None,
        venue="Field 1",
        division_name="GU13 Division 4",
        source_url=DIVISION_URL,
    )


def _csv(games, roster, outcomes, since=date(2026, 8, 1), today=date(2026, 10, 29)):
    return dm.build_csv_rows(games, roster, outcomes, "80738", "Fall2026", "NCSL", since, today)


def _linked(*rows):
    return {row.provider_team_id: Outcome("already_linked", f"master-{row.team_key}", 1.0) for row in rows}


class TestBuildCsvRows:
    def test_a_played_linked_game_is_two_rows_one_per_side(self):
        a, b = _row("1"), _row("2")
        records, held, cross_age = _csv([_game()], [a, b], _linked(a, b))
        assert (held, cross_age) == ([], [])
        assert [
            (r["team_id"], r["opponent_id"], r["home_away"], r["goals_for"], r["goals_against"], r["result"])
            for r in records
        ] == [
            ("80738-Fall2026-1", "80738-Fall2026-2", "H", 2, 1, "W"),
            ("80738-Fall2026-2", "80738-Fall2026-1", "A", 1, 2, "L"),
        ]

    def test_the_row_carries_the_schedule_event_and_state(self):
        a, b = _row("1"), _row("2")
        (first, _), _, _ = _csv([_game()], [a, b], _linked(a, b))
        assert first["schedule_id"] == "demosphere-80738-100"
        assert first["event_name"] == "NCSL Fall2026 - GU13 Division 4"
        assert (first["competition"], first["division_name"]) == ("NCSL", "GU13 Division 4")
        assert (first["state"], first["state_code"], first["gender"], first["age_group"]) == (
            "Virginia",
            "VA",
            "Girls",
            "u13",
        )
        assert first["game_date"] == "2026-09-12"

    def test_a_boys_game_is_written_as_boys(self):
        a, b = _row("1", gender="Male"), _row("2", gender="Male")
        (first, _), _, _ = _csv([_game()], [a, b], _linked(a, b))
        assert first["gender"] == "Boys"

    def test_a_game_before_the_floor_is_not_imported_or_held(self):
        a, b = _row("1"), _row("2")
        assert _csv([_game(day=date(2026, 7, 31))], [a, b], _linked(a, b)) == ([], [], [])

    def test_a_game_on_the_floor_is_imported(self):
        a, b = _row("1"), _row("2")
        records, _, _ = _csv([_game(day=date(2026, 8, 1))], [a, b], _linked(a, b))
        assert len(records) == 2

    def test_an_unplayed_game_is_neither_imported_nor_held(self):
        a, b = _row("1"), _row("2")
        assert _csv([_game(score=None)], [a, b], _linked(a, b)) == ([], [], [])

    def test_a_game_with_only_one_score_is_not_imported(self):
        a, b = _row("1"), _row("2")
        game = _game()
        game.away_score = None
        assert _csv([game], [a, b], _linked(a, b)) == ([], [], [])

    def test_a_game_in_the_future_is_not_imported(self):
        a, b = _row("1"), _row("2")
        records, _, _ = _csv([_game(day=date(2026, 11, 7))], [a, b], _linked(a, b))
        assert records == []

    def test_a_game_with_an_unlinked_side_is_held(self):
        a, b = _row("1"), _row("2")
        outcomes = {**_linked(a), b.provider_team_id: Outcome("review")}
        records, held, _ = _csv([_game()], [a, b], outcomes)
        assert records == []
        assert [h["reason"] for h in held] == ["a team is not linked"]

    @pytest.mark.parametrize("side", ["home", "away"])
    def test_a_game_with_a_side_left_out_of_the_roster_is_held(self, side):
        a = _row("1")
        game = _game(home="1", away="9") if side == "away" else _game(home="9", away="1")
        records, held, _ = _csv([game], [a], _linked(a))
        assert records == []
        assert [h["reason"] for h in held] == ["a team is left out of the roster"]

    def test_a_cross_age_game_is_imported_and_listed_with_both_boards(self):
        a, b = _row("1", age="u13"), _row("2", age="u12")
        records, held, cross_age = _csv([_game()], [a, b], _linked(a, b))
        assert len(records) == 2
        assert held == []
        assert [(c["home_age_group"], c["away_age_group"]) for c in cross_age] == [("u13", "u12")]
        assert list(cross_age[0]) == dm.CROSS_AGE_COLUMNS

    def test_a_cross_age_game_carries_the_home_teams_age_on_both_rows(self):
        a, b = _row("1", age="u13"), _row("2", age="u12")
        records, _, _ = _csv([_game()], [a, b], _linked(a, b))
        assert {r["age_group"] for r in records} == {"u13"}

    def test_a_cross_gender_game_is_imported_and_listed(self):
        a, b = _row("1"), _row("2", gender="Male")
        records, held, cross_age = _csv([_game()], [a, b], _linked(a, b))
        assert (len(records), held, len(cross_age)) == (2, [], 1)

    def test_a_created_team_counts_as_linked(self):
        a, b = _row("1"), _row("2")
        outcomes = {
            a.provider_team_id: Outcome("created", "m1", 1.0),
            b.provider_team_id: Outcome("created", "m2", 1.0),
        }
        records, _, _ = _csv([_game()], [a, b], outcomes)
        assert len(records) == 2

    def test_a_drawn_game_is_a_draw_on_both_sides(self):
        a, b = _row("1"), _row("2")
        records, _, _ = _csv([_game(score=(1, 1))], [a, b], _linked(a, b))
        assert [r["result"] for r in records] == ["D", "D"]

    def test_only_columns_the_importer_admits_are_written(self):
        a, b = _row("1"), _row("2")
        (first, _), _, _ = _csv([_game()], [a, b], _linked(a, b))
        assert set(first) == set(dm.REQUIRED_COLUMNS)
        for loader in (import_games_enhanced.stream_games_csv, import_games_enhanced.load_games_csv):
            source = inspect.getsource(loader)
            missing = [c for c in dm.REQUIRED_COLUMNS if f'"{c}"' not in source]
            assert missing == [], f"{loader.__name__} drops {missing}"


class TestOffBoardLinks:
    @pytest.mark.parametrize("status", ["already_linked", "linked_existing", "relinked"])
    def test_a_link_to_a_team_on_another_board_is_refused(self, status):
        row = _row("1", age="u13")
        outcomes = {row.provider_team_id: Outcome(status, "master-1", 0.95)}
        refused = dm.off_board_links([row], outcomes, {"master-1": {"age_group": "u12", "gender": "Female"}})
        assert refused == {row.provider_team_id: "linked team is on the u12 board, this team is u13"}

    def test_a_link_to_a_team_of_the_other_gender_is_refused(self):
        row = _row("1")
        refused = dm.off_board_links([row], _linked(row), {"master-1": {"age_group": "u13", "gender": "Male"}})
        assert list(refused) == [row.provider_team_id]

    def test_a_link_to_a_missing_team_is_refused(self):
        row = _row("1")
        assert dm.off_board_links([row], _linked(row), {}) == {row.provider_team_id: "linked team not found"}

    def test_a_stored_team_with_no_age_is_not_refused_for_its_age(self):
        row = _row("1")
        assert dm.off_board_links([row], _linked(row), {"master-1": {"age_group": None, "gender": "Female"}}) == {}

    def test_a_matching_link_and_a_created_team_pass(self):
        linked, created = _row("1"), _row("2")
        outcomes = {**_linked(linked), created.provider_team_id: Outcome("created", "m2", 1.0)}
        teams = {"master-1": {"age_group": "u13", "gender": "Female"}}
        assert dm.off_board_links([linked, created], outcomes, teams) == {}


class TestSharedLinks:
    def test_two_fuzzy_links_to_one_team_are_both_conflicts_labelled_demosphere(self):
        outcomes = {
            "a": Outcome("linked_existing", "m1", 0.95),
            "b": Outcome("linked_existing", "m1", 0.95),
            "c": Outcome("already_linked", "m1", 1.0),
        }
        conflicts = dm.shared_links(outcomes)
        assert conflicts == {
            "a": "same PitchRank team as Demosphere team b, c",
            "b": "same PitchRank team as Demosphere team a, c",
        }

    def test_an_approved_alias_keeps_its_team(self):
        outcomes = {"a": Outcome("already_linked", "m1", 1.0), "b": Outcome("created", "m2", 1.0)}
        assert dm.shared_links(outcomes) == {}


class _Matcher:
    def __init__(self, results):
        self.results, self.calls = results, []

    def _match_team(self, **kwargs):
        self.calls.append(kwargs)
        return self.results[kwargs["provider_team_id"]]


class TestRegisterTeams:
    def test_every_row_goes_to_the_matcher_with_its_club_and_state(self):
        row = _row("1")
        matcher = _Matcher({row.provider_team_id: {"created": True, "team_id": "m1"}})
        outcomes = dm.register_teams(matcher, "pid", [row], {})
        assert outcomes[row.provider_team_id] == Outcome("created", "m1", 1.0)
        assert matcher.calls == [
            {
                "provider_id": "pid",
                "provider_team_id": row.provider_team_id,
                "team_name": "Team 1",
                "age_group": "u13",
                "gender": "Female",
                "club_name": "Club 1",
                "state_code": "VA",
                "written_club": "Written 1",
            }
        ]

    def test_an_already_linked_team_never_reaches_the_matcher(self):
        row = _row("1")
        matcher = _Matcher({})
        outcomes = dm.register_teams(matcher, "pid", [row], {row.provider_team_id: "m1"})
        assert outcomes[row.provider_team_id].status == "already_linked"
        assert matcher.calls == []

    @pytest.mark.parametrize(
        ("result", "status"),
        [
            ({"relinked": True, "team_id": "m"}, "relinked"),
            ({"matched": True, "team_id": "m", "method": "fuzzy_auto", "confidence": 0.95}, "linked_existing"),
            ({"matched": True, "team_id": "m", "method": "direct_id"}, "already_linked"),
            ({"review": True, "confidence": 0.8}, "review"),
            ({"method": "no_match"}, "error"),
        ],
    )
    def test_each_matcher_result_has_its_own_outcome(self, result, status):
        row = _row("1")
        outcomes = dm.register_teams(_Matcher({row.provider_team_id: result}), "pid", [row], {})
        assert outcomes[row.provider_team_id].status == status

    def test_a_matcher_exception_is_an_error_not_a_crash(self):
        class Boom:
            def _match_team(self, **kwargs):
                raise RuntimeError("db down")

        row = _row("1")
        outcomes = dm.register_teams(Boom(), "pid", [row], {})
        assert outcomes[row.provider_team_id] == Outcome("error", reason="db down")


class _Recorder:
    """A supabase-py query that records its filters and answers only at ``execute``."""

    def __init__(self, rows, executed):
        self.rows, self.executed = rows, executed
        self.filters, self.order_by, self.span, self._negate = [], None, None, False

    def table(self, name):
        self.filters, self.order_by, self.span, self._negate = [("table", name)], None, None, False
        return self

    def select(self, columns):
        self.filters.append(("select", columns))
        return self

    def eq(self, column, value):
        self.filters.append((column, "eq", value))
        return self

    def neq(self, column, value):
        self.filters.append((column, "neq", value))
        return self

    def in_(self, column, values):
        self.filters.append((column, "in", tuple(values)))
        return self

    @property
    def not_(self):
        self._negate = True
        return self

    def is_(self, column, value):
        assert self._negate, "only not_.is_ is used"
        self.filters.append((column, "not.is", value))
        self._negate = False
        return self

    def order(self, column):
        self.order_by = column
        return self

    def range(self, start, end):
        assert self.order_by, "a range without an order can skip or repeat rows"
        self.span = (start, end)
        return self

    def execute(self):
        self.executed.append(list(self.filters))
        start, end = self.span or (0, len(self.rows))
        selected = [row for row in self.rows if self._matches(row)]
        return SimpleNamespace(data=selected[start : end + 1])

    def _matches(self, row):
        for entry in self.filters:
            if len(entry) != 3:
                continue
            column, operator, value = entry
            if operator == "eq" and row.get(column) != value:
                return False
            if operator == "neq" and row.get(column) == value:
                return False
            if operator == "not.is" and value == "null" and row.get(column) is None:
                return False
            if operator == "in" and row.get(column) not in value:
                return False
        return True


class TestClubStates:
    def test_a_unanimous_club_gets_its_state_and_a_split_club_none(self):
        rows = [
            {"club_name": "Bowie", "state_code": "MD", "is_deprecated": False},
            {"club_name": "Bowie", "state_code": "MD", "is_deprecated": False},
            {"club_name": "Split", "state_code": "VA", "is_deprecated": False},
            {"club_name": "Split", "state_code": "MD", "is_deprecated": False},
        ]
        found = dm.club_states(_Recorder(rows, []), ["Bowie", "Split", "Unknown"])
        assert found == {"Bowie": "MD", "Split": None}

    def test_deprecated_null_and_empty_states_do_not_vote(self):
        rows = [
            {"club_name": "Club", "state_code": "VA", "is_deprecated": False},
            {"club_name": "Club", "state_code": "MD", "is_deprecated": True},
            {"club_name": "Club", "state_code": None, "is_deprecated": False},
            {"club_name": "Club", "state_code": "", "is_deprecated": False},
        ]
        assert dm.club_states(_Recorder(rows, []), ["Club"]) == {"Club": "VA"}

    def test_the_query_is_ordered_paged_and_filtered_as_production_filters(self):
        executed = []
        dm.club_states(_Recorder([], executed), ["Club"])
        assert executed == [
            [
                ("table", "teams"),
                ("select", "state_code"),
                ("club_name", "eq", "Club"),
                ("is_deprecated", "eq", False),
                ("state_code", "not.is", "null"),
                ("state_code", "neq", ""),
            ]
        ]

    def test_a_club_with_more_rows_than_a_page_is_read_to_the_end(self, monkeypatch):
        monkeypatch.setattr(dm, "STATE_PAGE_SIZE", 2)
        rows = [{"club_name": "Big", "state_code": "VA", "is_deprecated": False}] * 2
        rows.append({"club_name": "Big", "state_code": "MD", "is_deprecated": False})
        executed = []
        found = dm.club_states(_Recorder(rows, executed), ["Big"])
        assert found == {"Big": None}
        assert len(executed) == 2

    def test_teams_stored_outside_the_leagues_region_do_not_vote(self):
        rows = [{"club_name": "Stafford Soccer Club", "state_code": "NJ", "is_deprecated": False}] * 3
        rows += [{"club_name": "Mixed", "state_code": s, "is_deprecated": False} for s in ("NJ", "VA", "VA")]
        rows += [{"club_name": "Split", "state_code": s, "is_deprecated": False} for s in ("MD", "VA", "NJ")]
        found = dm.club_states(_Recorder(rows, []), ["Stafford Soccer Club", "Mixed", "Split"], ("VA", "MD", "DC"))
        assert found == {"Mixed": "VA", "Split": None}

    def test_without_a_region_every_stored_state_votes(self):
        rows = [{"club_name": "Stafford Soccer Club", "state_code": "NJ", "is_deprecated": False}]
        assert dm.club_states(_Recorder(rows, []), ["Stafford Soccer Club"]) == {"Stafford Soccer Club": "NJ"}

    def test_ncsl_is_filed_in_its_own_region(self):
        assert dm.LEAGUES["80738"].states == ("VA", "MD", "DC", "WV", "DE")

    def test_a_placeholder_club_is_never_asked_about(self):
        executed = []
        rows = [{"club_name": "No Club Selection", "state_code": "CA", "is_deprecated": False}]
        assert dm.club_states(_Recorder(rows, executed), ["No Club Selection"]) == {}
        assert executed == []

    def test_each_club_is_asked_once(self):
        executed = []
        dm.club_states(_Recorder([], executed), ["A", "A", "B"])
        assert [f[2][2] for f in executed] == ["A", "B"]


class TestPendingReviews:
    def _rows(self):
        return [
            {"provider_id": "demosphere", "status": "pending", "provider_team_id": "a"},
            {"provider_id": "demosphere", "status": "rejected", "provider_team_id": "b"},
            {"provider_id": "yssl", "status": "pending", "provider_team_id": "c"},
        ]

    def test_only_this_providers_pending_rows_count(self):
        db = _Recorder(self._rows(), [])
        assert dm.pending_reviews(db, ["a", "b", "c"]) == {"a"}

    def test_the_queue_is_keyed_by_the_provider_code(self):
        executed = []
        dm.pending_reviews(_Recorder([], executed), ["a"])
        assert ("provider_id", "eq", "demosphere") in executed[0]
        assert ("status", "eq", "pending") in executed[0]
        assert ("table", "team_match_review_queue") in executed[0]

    def test_ids_go_in_batches_of_a_hundred(self):
        executed = []
        dm.pending_reviews(_Recorder([], executed), [str(n) for n in range(150)])
        sizes = [len(next(f for f in call if f[1] == "in")[2]) for call in executed]
        assert sizes == [100, 50]


class _Response(requests.Response):
    def __init__(self, status, body, content_type):
        super().__init__()
        self.status_code = status
        self._content = body
        self.headers["content-type"] = content_type
        self.encoding = requests.utils.get_encoding_from_headers(self.headers)


class _Session:
    def __init__(self, response):
        self.response, self.urls = response, []

    def get(self, url, timeout):
        self.urls.append(url)
        return self.response


class TestGet:
    def test_a_page_with_no_charset_is_read_as_utf8(self):
        response = _Response(200, "Atlético".encode("utf-8"), "text/html")
        assert dm._get(_Session(response), "u").text == "Atlético"

    def test_a_declared_charset_is_left_alone(self):
        response = _Response(200, "Atlético".encode("latin-1"), "text/html; charset=iso-8859-1")
        assert dm._get(_Session(response), "u").text == "Atlético"

    @pytest.mark.parametrize("status", [403, 404, 301, 500])
    def test_any_status_but_200_fails_the_run(self, status):
        with pytest.raises(dm.ScrapeFetchError, match=str(status)):
            dm._get(_Session(_Response(status, b"", "text/html")), "u")

    def test_a_transport_failure_fails_the_run(self):
        class Down:
            def get(self, url, timeout):
                raise requests.ConnectionError("down")

        with pytest.raises(dm.ScrapeFetchError):
            dm._get(Down(), "u")

    def test_the_session_sends_a_browser_agent_and_retries_server_errors(self):
        session = dm.make_session()
        assert "Mozilla/5.0" in session.headers["User-Agent"]
        retry = session.get_adapter("https://elements.demosphere.com").max_retries
        assert set(retry.status_forcelist) == {500, 502, 503, 504}


class TestReports:
    def test_the_team_report_names_the_outcome_and_reason_of_a_left_out_team(self):
        in_scope, left_out = _roster([_stub("11", "Bowie U13G (MD)")])
        (report,) = dm.report_rows(in_scope, left_out, {}, {})
        assert report["outcome"] == "skipped"
        assert "MD" in report["reason"]
        assert list(report) == dm.REPORT_COLUMNS

    def test_the_team_report_names_the_pitchrank_team_a_team_linked_to(self):
        row = _row("1")
        outcomes = {row.provider_team_id: Outcome("linked_existing", "master-1", 0.95)}
        (report,) = dm.report_rows([row], [], outcomes, {"master-1": "Stored Name"})
        assert (report["outcome"], report["team_id_master"], report["pitchrank_team_name"], report["confidence"]) == (
            "linked_existing",
            "master-1",
            "Stored Name",
            0.95,
        )

    def test_held_games_are_written_for_a_spreadsheet(self):
        (safe,) = dm._for_spreadsheets([{"home_team_name": "=cmd|' /c calc'!A1"}])
        assert safe["home_team_name"].startswith("'")

    def test_no_contact_detail_survives_into_a_fixture(self):
        for fixture in FIXTURES.glob("*.html"):
            text = fixture.read_text(encoding="utf-8")
            assert not re.search(r"mailto:(?!person@example\.com)", text), fixture.name
            assert set(re.findall(r"\d{3}-\d{3}-\d{4}", text)) <= {"000-000-0000"}, fixture.name
            names = {
                " ".join(cell.get_text().split())
                for cell in BeautifulSoup(text, "lxml").select("td.cb-cont-name, td.ct-name")
            }
            assert names <= PLACEHOLDERS, fixture.name

    def test_the_fixtures_still_carry_the_placeholders_the_scrub_left(self):
        club = _fixture("club_15599479.html")
        assert "PERSON NAME" in club
        assert "person@example.com" in club


class TestRunMain:
    """``main`` end to end against fixture pages, a recording matcher and a recording import."""

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 29)

    @pytest.fixture
    def run_main(self, monkeypatch, tmp_path):
        state = SimpleNamespace(
            matchers=[],
            imports=[],
            import_code=0,
            results={},
            queued=set(),
            linked_teams={},
            stored={},
            asked=[],
            regions=[],
            club_pages={},
            fetched=[],
            site_season=None,
            division=_fixture("division_116702955.html"),
            today=self.FixedDate,
            season="Fall2026",
        )

        class FakeMatcher:
            def __init__(self, supabase, provider_id=None, registration_mode=False, dry_run=False, **_):
                self.dry_run, self.registration_mode, self.calls = dry_run, registration_mode, []
                state.matchers.append(self)

            def _match_team(self, **kwargs):
                self.calls.append(kwargs["provider_team_id"])
                default = {"created": True, "team_id": f"master-{kwargs['provider_team_id']}"}
                return state.results.get(kwargs["provider_team_id"], default)

        class FakeClient:
            def table(self, name):
                assert name == "providers"
                return SimpleNamespace(
                    select=lambda *_: SimpleNamespace(
                        eq=lambda *_: SimpleNamespace(execute=lambda: SimpleNamespace(data=[{"id": "pid"}]))
                    )
                )

        def pages(url):
            state.fetched.append(url)
            if "/clubs/schedule/15599479" in url:
                return _schedule_page(state.site_season or state.season)
            if "/teams/club/15599479" in url:
                return _fixture("club_15599479.html")
            if "/teams/club/" in url:
                name = state.club_pages.get(url.rsplit("/", 1)[-1][: -len(".html")], "Another Club")
                return f'<h1 class="dii-hdr-cb">{name}</h1>'
            if "/schedules/" in url:
                return state.division
            raise AssertionError(f"unexpected fetch {url}")

        def existing(supabase, provider_id, ids):
            return state.aliases(ids)

        def club_states(supabase, names, region=()):
            state.asked.append(names)
            state.regions.append(region)
            return state.stored

        def fake_run(command, check):
            state.imports.append(command)
            return SimpleNamespace(returncode=state.import_code)

        state.aliases = lambda ids: (
            {key: f"master-{key}" for key in ids} if any(not m.dry_run for m in state.matchers) else {}
        )
        monkeypatch.setenv("SUPABASE_URL", "http://db")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
        monkeypatch.setattr(dm, "create_client", lambda *_: FakeClient())
        monkeypatch.setattr(dm, "make_session", lambda: None)
        monkeypatch.setattr(dm, "_get", lambda session, url: SimpleNamespace(text=pages(url)))
        monkeypatch.setattr(dm, "DemosphereGameMatcher", FakeMatcher)
        monkeypatch.setattr(dm, "existing_aliases", existing)
        monkeypatch.setattr(dm, "pending_reviews", lambda supabase, ids: state.queued & set(ids))
        monkeypatch.setattr(
            dm, "teams_by_id", lambda supabase, ids: {k: v for k, v in state.linked_teams.items() if k in ids}
        )
        monkeypatch.setattr(dm, "club_states", club_states)
        monkeypatch.setattr(dm.subprocess, "run", fake_run)
        monkeypatch.setattr(dm, "date", state.today)

        def run(*argv):
            state.season = argv[argv.index("--season") + 1] if "--season" in argv else "Fall2026"
            monkeypatch.setattr(
                "sys.argv",
                ["import_demosphere.py", "--max-divisions", "1", "--delay-min", "0", "--delay-max", "0"]
                + ["--output-dir", str(tmp_path), *argv],
            )
            return dm.main()

        state.run = run
        state.monkeypatch = monkeypatch
        state.out = tmp_path
        state.rows = lambda kind: list(csv.DictReader(next(tmp_path.glob(f"*_{kind}.csv")).open(encoding="utf-8")))
        return state

    def test_a_dry_run_builds_only_a_dry_run_matcher_and_starts_no_import(self, run_main):
        assert run_main.run() == 0
        assert [(m.dry_run, m.registration_mode) for m in run_main.matchers] == [(True, True)]
        assert run_main.imports == []

    def test_a_dry_run_still_writes_the_reports_and_the_games_it_would_import(self, run_main):
        run_main.run()
        assert len(run_main.rows("teams")) == 10
        games = run_main.rows("games")
        assert len(games) == 2 * 34
        assert {row["schedule_id"] for row in games} >= {"demosphere-80738-11635852"}

    def test_execute_previews_then_writes_then_imports_once_under_the_provider_code(self, run_main):
        assert run_main.run("--execute") == 0
        assert [(m.dry_run, m.registration_mode) for m in run_main.matchers] == [(True, True), (False, True)]
        assert len(run_main.imports) == 1
        assert run_main.imports[0][-1] == "demosphere"
        assert run_main.imports[0][1] == "scripts/import_games_enhanced.py"
        assert run_main.imports[0][2] == str(next(run_main.out.glob("*_games.csv")))

    def test_a_failing_import_is_the_runs_exit_code(self, run_main):
        run_main.import_code = 2
        assert run_main.run("--execute") == 2

    def test_an_unreadable_score_fails_the_run_in_both_modes(self, run_main):
        run_main.division = _fixture("division_116702955.html").replace(" 2-1 ", " PPD ", 1)
        assert run_main.run() == 1
        assert run_main.run("--execute") == 1

    def test_a_season_the_site_does_not_list_stops_before_anything_is_registered(self, run_main, monkeypatch):
        monkeypatch.setattr(dm, "_get", lambda session, url: SimpleNamespace(text=_schedule_page("Fall2026")))
        assert run_main.run("--season", "Spring2027") == 1
        assert run_main.matchers == []
        assert run_main.imports == []

    def test_the_default_since_is_the_start_of_the_seasons_august(self, run_main):
        run_main.division = _fixture("division_116702955.html").replace("Sat, September 12, 2026", "Sat, March 6, 2027")
        later = type("Later", (date,), {"today": classmethod(lambda cls: cls(2027, 4, 1))})
        run_main.monkeypatch.setattr(dm, "date", later)
        assert run_main.run("--season", "Spring2027") == 0
        assert "demosphere-80738-11635852" in {row["schedule_id"] for row in run_main.rows("games")}

    def test_stored_states_are_asked_about_the_clubs_the_roster_uses(self, run_main):
        run_main.run()
        assert len(run_main.asked) == 1
        assert "VISTA Warriors" in run_main.asked[0]
        assert "VA Indpt Soccer Team Assoc - Travel" not in run_main.asked[0]

    def test_a_club_the_owner_renamed_is_filed_under_the_new_name_and_state(self, run_main):
        run_main.club_pages = {"15599453": "Takoma Park"}
        run_main.run()
        loud = [r for r in run_main.rows("teams") if r["team_name"].startswith("LOUD U13G")]
        assert loud
        assert {(r["club_name"], r["state_code"]) for r in loud} == {("Takoma Park Soccer Club", "MD")}

    def test_stored_club_states_are_read_inside_the_leagues_region(self, run_main):
        run_main.run()
        assert run_main.regions == [("VA", "MD", "DC", "WV", "DE")]

    def test_an_association_teams_club_state_is_the_one_stored_for_its_cut_club(self, run_main):
        run_main.stored = {"VISTA Warriors": "MD"}
        run_main.run()
        rows = [r for r in run_main.rows("games") if r["team_name"] == "VISTA Warriors U13G"]
        assert rows
        assert {r["state_code"] for r in rows} == {"MD"}

    def test_a_club_whose_stored_teams_disagree_is_left_out_and_its_games_are_held(self, run_main):
        run_main.stored = {"VISTA Warriors": None}
        run_main.run()
        team = next(r for r in run_main.rows("teams") if r["team_name"] == "VISTA Warriors U13G")
        assert team["outcome"] == "skipped"
        assert all("VISTA Warriors U13G" not in (r["team_name"], r["opponent_name"]) for r in run_main.rows("games"))
        assert {h["reason"] for h in run_main.rows("held")} == {"a team is left out of the roster"}

    def test_two_teams_linking_to_one_team_are_conflicts_and_neither_is_written(self, run_main):
        fuzzy = {"matched": True, "team_id": "same", "method": "fuzzy_auto", "confidence": 0.95}
        run_main.results = {"80738-Fall2026-116796872": fuzzy, "80738-Fall2026-116796835": fuzzy}
        assert run_main.run("--execute") == 0
        writer = next(m for m in run_main.matchers if not m.dry_run)
        assert "80738-Fall2026-116796872" not in writer.calls
        assert "80738-Fall2026-116796835" not in writer.calls
        report = {r["provider_team_id"]: r for r in run_main.rows("teams")}
        assert report["80738-Fall2026-116796872"]["outcome"] == "conflict"
        assert all("LOUD U13G" not in r["team_name"] for r in run_main.rows("games"))

    def test_a_link_the_alias_table_never_saved_is_an_error_and_its_games_wait(self, run_main):
        run_main.aliases = lambda ids: {}
        assert run_main.run("--execute") == 1
        assert {r["outcome"] for r in run_main.rows("teams")} == {"error"}
        assert run_main.rows("games") == []
        assert run_main.imports == []

    def test_a_review_row_that_was_not_saved_is_an_error(self, run_main):
        run_main.results = {"80738-Fall2026-116796872": {"review": True, "confidence": 0.8}}
        run_main.queued = set()
        assert run_main.run("--execute") == 1
        report = {r["provider_team_id"]: r for r in run_main.rows("teams")}
        assert report["80738-Fall2026-116796872"]["outcome"] == "error"

    def test_a_link_to_a_team_on_another_board_is_an_error_and_its_games_wait(self, run_main):
        team = "80738-Fall2026-116796872"
        run_main.results = {team: {"matched": True, "team_id": "stored", "method": "direct_id"}}
        run_main.linked_teams = {"stored": {"team_name": "Stored", "age_group": "u12", "gender": "Female"}}
        assert run_main.run() == 1
        report = {r["provider_team_id"]: r for r in run_main.rows("teams")}
        assert report[team]["outcome"] == "error"
        assert all("LOUD U13G Blue/Ascent" not in (r["team_name"], r["opponent_name"]) for r in run_main.rows("games"))

    def test_a_queued_review_stays_a_review(self, run_main):
        team = "80738-Fall2026-116796872"
        run_main.results = {team: {"review": True, "confidence": 0.8}}
        run_main.queued = {team}
        assert run_main.run("--execute") == 0
        assert {r["provider_team_id"]: r for r in run_main.rows("teams")}[team]["outcome"] == "review"

    def test_a_link_to_a_stored_team_on_the_right_board_has_its_games_imported(self, run_main):
        team = "80738-Fall2026-116796872"
        run_main.results = {team: {"matched": True, "team_id": "stored", "method": "direct_id"}}
        run_main.linked_teams = {"stored": {"team_name": "Stored", "age_group": "u13", "gender": "Female"}}
        assert run_main.run() == 0
        assert "demosphere-80738-11635852" in {r["schedule_id"] for r in run_main.rows("games")}

    def test_site_text_cannot_become_a_spreadsheet_formula_in_any_report(self, run_main):
        team = "80738-Fall2026-116796872"
        division = _fixture("division_116702955.html")
        division = division.replace("LOUD U13G Blue/Ascent", "=LOUD U13G Blue/Ascent")
        run_main.division = division.replace("LOUD U13G White", "=LOUD U12G White")
        run_main.results = {team: {"review": True, "confidence": 0.8}}
        run_main.queued = {team}
        run_main.run()
        teams = run_main.rows("teams")
        assert {r["team_name"] for r in teams if "LOUD" in r["team_name"]} == {
            "'=LOUD U13G Blue/Ascent",
            "'=LOUD U12G White",
        }
        held = run_main.rows("held")
        assert {"'=LOUD U13G Blue/Ascent"} <= {r["home_team_name"] for r in held} | {r["away_team_name"] for r in held}
        cross_age = run_main.rows("cross_age")
        assert {"'=LOUD U12G White"} <= {r["home_team_name"] for r in cross_age} | {
            r["away_team_name"] for r in cross_age
        }

    def test_teams_are_filed_on_the_board_of_the_wall_clock_season_not_the_events(self, run_main, monkeypatch):
        monkeypatch.setattr(dm, "_soccer_season_year", lambda: 2027)
        run_main.run("--season", "Spring2027")
        team = next(r for r in run_main.rows("teams") if r["team_name"] == "Villarreal VA Azul G2013/14")
        assert team["age_group"] == "u14"

    def test_since_bounds_the_games_imported(self, run_main):
        run_main.run("--since", "2026-10-01")
        dates = {r["game_date"] for r in run_main.rows("games")}
        assert dates
        assert min(dates) >= "2026-10-01"

    def test_an_august_game_is_inside_the_default_window(self, run_main):
        run_main.division = _fixture("division_116702955.html").replace(
            "Sat, September 12, 2026", "Sat, August 15, 2026"
        )
        run_main.run()
        assert "2026-08-15" in {r["game_date"] for r in run_main.rows("games")}

    def test_the_conflict_reason_and_the_sites_club_are_in_the_team_report(self, run_main):
        fuzzy = {"matched": True, "team_id": "same", "method": "fuzzy_auto", "confidence": 0.95}
        run_main.results = {"80738-Fall2026-116796872": fuzzy, "80738-Fall2026-116796835": fuzzy}
        run_main.run("--execute")
        report = {r["provider_team_id"]: r for r in run_main.rows("teams")}
        assert (
            report["80738-Fall2026-116796872"]["reason"]
            == "same PitchRank team as Demosphere team 80738-Fall2026-116796835"
        )
        warriors = next(r for r in report.values() if r["team_name"] == "VISTA Warriors U13G")
        assert warriors["demosphere_club"] == "VA Indpt Soccer Team Assoc - Travel"
        assert warriors["club_name"] == "VISTA Warriors"

    def test_a_run_with_no_season_falls_back_to_the_one_the_site_still_shows(self, run_main):
        run_main.site_season = "Spring2026"
        run_main.division = _fixture("division_116702955.html").replace("Sat, September 12, 2026", "Sat, March 7, 2026")
        assert run_main.run() == 0
        assert "demosphere-80738-11635852" in {r["schedule_id"] for r in run_main.rows("games")}
        assert any("Spring2026" in url for url in run_main.fetched)

    def test_a_run_with_no_season_stops_when_the_site_lists_neither(self, run_main):
        run_main.site_season = "Winter2030"
        assert run_main.run() == 1
        assert run_main.matchers == []
        assert run_main.imports == []

    def test_teams_in_conflict_are_held_but_do_not_fail_the_run(self, run_main):
        fuzzy = {"matched": True, "team_id": "same", "method": "fuzzy_auto", "confidence": 0.95}
        run_main.results = {"80738-Fall2026-116796872": fuzzy, "80738-Fall2026-116796835": fuzzy}
        assert run_main.run() == 0

    def test_a_team_whose_link_errored_still_fails_the_run(self, run_main):
        run_main.results = {"80738-Fall2026-116796872": {"method": "no_match"}}
        assert run_main.run() == 1

    def test_a_season_label_the_driver_cannot_read_stops_before_anything_is_fetched(self, run_main):
        assert run_main.run("--season", "winter2026") == 1
        assert run_main.matchers == []
        assert run_main.imports == []


class TestClubForRules:
    @pytest.mark.parametrize(
        ("listed", "stored"),
        [
            ("Herndon Youth Soccer Assoc - Travel", "Herndon Youth Soccer"),
            ("Arlington Soccer Association", "Arlington Soccer Association"),
            ("Sterling Youth Soccer Assoc - Travel", "Sterling Youth Soccer"),
            ("Potomac Soccer Association", "Potomac Soccer Association"),
            ("Manassas United - N1", "Manassas United"),
            ("Fairfax Police Youth Club - Travel", "Fairfax Police Youth Club"),
            ("Montgomery Soccer Inc.", "Montgomery Soccer Inc."),
            ("Travel Soccer Club", "Travel Soccer Club"),
            ("Association Football Club", "Association Football Club"),
            ("Takoma Park", "Takoma Park"),
        ],
    )
    def test_a_listed_club_loses_its_travel_tag_and_a_closing_assoc(self, listed, stored):
        assert dm.stored_club(listed) == stored

    def test_a_listed_club_is_used_even_when_the_name_shares_none_of_its_words(self):
        assert dm.club_for("Loudoun Soccer", "Ashburn Loudoun U13G") == (
            "Loudoun Soccer",
            "Ashburn Loudoun",
            "listed club",
        )

    def test_only_the_listed_association_falls_back_to_the_name(self):
        assert dm.LEAGUES["80738"].association_clubs == ("15599479",)

    def test_a_listed_club_is_kept_whole_when_the_name_opens_with_one_of_its_words(self):
        assert dm.club_for("Virginia Rush", "Rush U13G Blue") == ("Virginia Rush", "Rush", "listed club")

    def test_the_written_club_drops_squad_marks_the_stored_club_keeps(self):
        assert dm.club_for("", "NPSC United Elite 2014 Boys")[:2] == ("NPSC United Elite", "NPSC United")

    def test_a_name_that_opens_with_its_age_has_no_club(self):
        assert dm.club_for("", "U13G Blue") == (None, None, "cut from name")

    def test_the_before_age_cut_stops_at_a_band_and_falls_back_to_the_whole_name_when_nothing_is_left(self):
        assert dm._before_age("Loudoun 13/14 Red") == "Loudoun"
        assert dm._before_age("2013 Red") == "2013 Red"
        assert dm._before_age("Loudoun Red") == "Loudoun Red"


class TestRosterRules:
    def test_the_matcher_is_given_the_club_as_the_name_writes_it(self):
        stub = _stub("11", "Villarreal VA Azul G2013/14", club="9")
        (row,), _ = _roster([stub], clubs={"9": "Villarreal Virginia Academy"})
        assert (row.club_name, row.club_as_written) == ("Villarreal Virginia Academy", "Villarreal VA Azul")

    def test_a_team_with_no_readable_club_is_left_out(self):
        in_scope, (row,) = _roster([_stub("11", "U13G Blue")], clubs={"1": ""})
        assert in_scope == []
        assert row.skip_reason == "no club could be read from the name"

    def test_a_lone_year_below_the_u10_board_is_left_out(self):
        in_scope, (row,) = _roster([_stub("11", "Loudoun B2018", division="BU9 Division 1", code="NB0900")])
        assert in_scope == []
        assert row.skip_reason == "birth year 2018 is on no U10-U19 board"

    def test_another_states_tag_outranks_the_clubs_stored_state(self):
        assert dm.resolve_state("Bowie SC U13G (MD)", "Bowie SC", {"Bowie SC": "VA"}, "VA") == (
            None,
            "name carries the MD tag, not VA",
        )


class TestAgeRules:
    def test_an_explicit_four_digit_year_is_not_reread_as_an_age(self):
        assert dm.team_age("Club B2012 Red", "BU12 Division 1", 2026) == (
            None,
            "birth year tag B2012 is older than its division",
        )

    def test_a_two_digit_tag_is_still_the_divisions_age(self):
        assert dm.team_age("Club B12 Red", "BU12 Division 1", 2026) == (2015, "B12 read as U12")

    def test_a_division_label_with_a_prefix_still_bounds_the_name_and_names_the_gender(self):
        assert dm.team_age("Loudoun U13G", "N1 BU14", 2026) == (2014, "name")
        assert dm.team_age("Loudoun Blue", "N1 BU14", 2026) == (2013, "no age in the team name, division N1 BU14 used")
        assert dm.team_gender("N1 BU14", "") == "Male"

    def test_the_lone_year_fallback_uses_the_season_it_is_given(self):
        assert dm.team_cohort(2007, "birth year 2007", 2026) == "u19"
        assert dm.team_cohort(2007, "birth year 2007", 2027) is None
        assert dm.team_cohort(2017, "birth year 2017", 2025) is None

    def test_the_ambiguity_tie_break_needs_the_divisions_own_year(self):
        assert (
            dm.team_age("Loudoun G2014", "GU13 Division 4", 2026)[1] == "birth year 2014, division GU13 Division 4 used"
        )
        assert dm.team_age("Loudoun G2014", "GU9 Division 1", 2026) == (None, "birth year 2014 could be 2014 or 2015")


def _division(replace=None, pattern=None):
    html = _fixture("division_116702955.html")
    for old, new in (replace or {}).items():
        html = html.replace(old, new, 1)
    return html


class TestDivisionParserEdges:
    def test_an_unreadable_later_day_header_drops_its_games_instead_of_keeping_the_previous_date(self):
        page = dm.parse_division_page(_division({"Sun, September 13, 2026": "NEXT WEEK"}), "116702955", DIVISION_URL)
        assert len(page.games) == 40
        assert sum(1 for g in page.games if g.game_date == date(2026, 9, 12)) == 2
        assert all(g.game_date != date(2026, 9, 13) for g in page.games)
        assert "116702955: unreadable day header 'NEXT WEEK'" in page.problems

    def test_an_away_cell_with_no_team_key_is_reported_and_adds_no_team(self):
        page = dm.parse_division_page(
            _division({'class="schedtm schedtm2" data-tmkey="116800863"': 'class="schedtm schedtm2"'}),
            "116702955",
            DIVISION_URL,
        )
        assert "116702955: unreadable game row '11635852'" in page.problems
        assert "" not in page.teams

    def test_a_cell_with_keys_but_no_text_is_unreadable(self):
        html = re.sub(r'(<td class="schedtm schedtm1"[^>]*>).*?(</td>)', r"\1\2", _division(), count=1, flags=re.DOTALL)
        page = dm.parse_division_page(html, "116702955", DIVISION_URL)
        assert "116702955: unreadable game row '11635852'" in page.problems

    def test_a_team_with_no_club_key_is_not_a_problem_and_is_never_walked_to(self):
        html = _division({'data-cbkey="15599479"': 'data-cbkey=""'})
        page = dm.parse_division_page(html, "116702955", DIVISION_URL)
        assert page.problems == []
        assert page.teams["116800863"].club_key == ""
        requested = []

        def fetch(url):
            requested.append(url)
            if "/clubs/schedule/15599479" in url:
                return _schedule_page()
            if "/teams/club/15599479" in url:
                return _fixture("club_15599479.html")
            if "/teams/club/" in url:
                return '<h1 class="dii-hdr-cb">Another Club</h1>'
            return html

        dm.collect_league(fetch, "80738", "Fall2026", ["15599479"], max_divisions=1)
        assert not any(url.endswith("/teams/club/.html") for url in requested)

    def test_a_two_digit_score_parses(self):
        page = dm.parse_division_page(_division({" 2-1 ": " 10-0 "}), "116702955", DIVISION_URL)
        assert (page.games[0].home_score, page.games[0].away_score) == (10, 0)
        assert page.problems == []

    def test_a_division_with_a_name_and_no_games_is_not_a_problem(self):
        page = dm.parse_division_page("<script>var tgname = 'GU13 Division 9';</script>", "116702999", DIVISION_URL)
        assert (page.problems, page.games, page.name) == ([], [], "GU13 Division 9")


class TestForfeitsAndUnscheduledGames:
    @pytest.mark.parametrize("score", ["3-0 FFT", "0-3 FFT", "2-10 FFT", "FFT", "ff", "Forfeit"])
    def test_a_forfeit_with_or_without_an_awarded_score_is_counted_not_scored(self, score):
        page = dm.parse_division_page(_division({" 2-1 ": f" {score} "}), "116702955", DIVISION_URL)
        assert page.forfeits == ["11635852"]
        assert page.problems == []
        assert page.games[0].home_score is None

    @pytest.mark.parametrize("header", ["TBD", "tbd", "To Be Determined", "Unscheduled"])
    def test_an_undated_section_is_skipped_without_a_problem(self, header):
        page = dm.parse_division_page(_division({"Sun, September 13, 2026": header}), "116702955", DIVISION_URL)
        assert page.problems == []
        assert len(page.games) == 40
        assert all(g.game_date != date(2026, 9, 13) for g in page.games)

    def test_a_team_in_an_undated_section_is_still_a_team(self):
        html = _division({"Sat, September 12, 2026": "TBD"})
        page = dm.parse_division_page(html, "116702955", DIVISION_URL)
        assert "114577143" in page.teams

    def test_the_undated_section_ends_at_the_next_dated_header(self):
        page = dm.parse_division_page(_division({"Sun, September 13, 2026": "TBD"}), "116702955", DIVISION_URL)
        assert any(g.game_date == date(2026, 9, 19) for g in page.games)


class TestCollectLeagueEdges:
    def test_a_division_two_clubs_both_link_is_fetched_once(self):
        _, links = dm.parse_club_page(_fixture("club_15599479.html"))
        division_key = sorted({d for s, _, d in links if s == FALL_SEASON_KEY})[0]
        requested = []

        def fetch(url):
            requested.append(url)
            if "/clubs/schedule/15599479" in url:
                return _schedule_page()
            if "/teams/club/15599479" in url:
                return _fixture("club_15599479.html")
            if "/teams/club/" in url:
                return (
                    f'<h1 class="dii-hdr-cb">Another</h1>'
                    f'<a href="/80738/teams/{FALL_SEASON_KEY}/1-{division_key}/TEAM.html">x</a>'
                )
            return _fixture("division_116702955.html")

        dm.collect_league(fetch, "80738", "Fall2026", ["15599479"])
        assert requested.count(f"https://elements.demosphere.com/80738/schedules/Fall2026/{division_key}.html") == 1

    def test_a_club_page_with_no_heading_and_no_teams_is_a_problem(self):
        def fetch(url):
            if "/clubs/schedule/15599479" in url:
                return _schedule_page()
            if "/teams/club/15599479" in url:
                return _fixture("club_15599479.html")
            if "/teams/club/" in url:
                return "<html><body>Down for maintenance</body></html>"
            return _fixture("division_116702955.html")

        _, _, problems = dm.collect_league(fetch, "80738", "Fall2026", ["15599479"], max_divisions=1)
        assert "club 15599453: no club name or teams in the page" in problems


class TestCsvRowRules:
    def test_every_value_comes_from_its_own_side(self):
        a, b = _row("1"), _row("2")
        (first, second), _, _ = _csv([_game()], [a, b], _linked(a, b))
        assert (first["team_name"], first["opponent_name"]) == ("Team 1", "Team 2")
        assert (first["club_name"], first["opponent_club_name"]) == ("Club 1", "Club 2")
        assert (second["club_name"], second["opponent_club_name"]) == ("Club 2", "Club 1")
        assert (first["state"], first["state_code"]) == ("Virginia", "VA")
        assert (second["state"], second["state_code"]) == ("Maryland", "MD")
        assert first["venue"] == "Field 1"

    @pytest.mark.parametrize("status", ["linked_existing", "relinked"])
    def test_a_linked_team_of_either_kind_has_its_games_imported(self, status):
        a, b = _row("1"), _row("2")
        outcomes = {a.provider_team_id: Outcome(status, "m1", 0.95), b.provider_team_id: Outcome(status, "m2", 0.95)}
        records, held, _ = _csv([_game()], [a, b], outcomes)
        assert (len(records), held) == (2, [])

    def test_a_game_played_today_is_imported(self):
        a, b = _row("1"), _row("2")
        records, _, _ = _csv([_game(day=date(2026, 10, 29))], [a, b], _linked(a, b))
        assert len(records) == 2

    def test_a_held_game_names_the_left_out_team_by_its_site_key(self):
        a = _row("1")
        _, held, _ = _csv([_game(home="9", away="1")], [a], _linked(a))
        assert (held[0]["home_team_id"], held[0]["away_team_id"]) == ("9", "80738-Fall2026-1")

    def test_the_cross_age_file_names_the_stored_teams(self):
        a, b = _row("1", age="u13"), _row("2", age="u12")
        _, _, cross_age = _csv([_game()], [a, b], _linked(a, b))
        assert (cross_age[0]["home_team_id_master"], cross_age[0]["away_team_id_master"]) == ("master-1", "master-2")

    def test_the_column_lists_are_the_ones_the_importer_and_operators_read(self):
        assert dm.REQUIRED_COLUMNS == [
            "provider", "schedule_id", "competition", "division_name", "event_name", "age_group", "gender",
            "team_id", "team_id_source", "team_name", "club_name", "opponent_id", "opponent_id_source",
            "opponent_name", "opponent_club_name", "state", "state_code", "game_date", "home_away",
            "goals_for", "goals_against", "result", "venue", "source_url", "scraped_at",
        ]  # fmt: skip
        assert dm.CROSS_AGE_COLUMNS == [
            "game_date", "division", "home_team_id", "home_team_name", "home_age_group", "home_gender",
            "home_team_id_master", "away_team_id", "away_team_name", "away_age_group", "away_gender",
            "away_team_id_master", "home_score", "away_score", "source_url",
        ]  # fmt: skip
        assert dm.HELD_COLUMNS == ["reason", *dm.CROSS_AGE_COLUMNS]
        assert dm.REPORT_COLUMNS == [
            "provider_team_id", "team_key", "team_name", "team_code", "demosphere_club", "club_name",
            "club_source", "division", "age_group", "age_source", "gender", "state_code", "state_source",
            "outcome", "team_id_master", "pitchrank_team_name", "confidence", "reason",
        ]  # fmt: skip


class TestOutcomesAndLinks:
    def test_each_matcher_result_carries_its_team_and_confidence(self):
        row = _row("1")
        expected = [
            ({"relinked": True, "team_id": "m"}, Outcome("relinked", "m", 1.0)),
            (
                {"matched": True, "team_id": "m", "method": "fuzzy_auto", "confidence": 0.95},
                Outcome("linked_existing", "m", 0.95),
            ),
            ({"matched": True, "team_id": "m", "method": "direct_id"}, Outcome("already_linked", "m", None)),
            ({"review": True, "confidence": 0.8}, Outcome("review", confidence=0.8)),
        ]
        for result, outcome in expected:
            outcomes = dm.register_teams(_Matcher({row.provider_team_id: result}), "pid", [row], {})
            assert outcomes[row.provider_team_id] == outcome

    def test_a_relinked_team_shares_its_team_with_a_fuzzy_link(self):
        outcomes = {"a": Outcome("relinked", "m1", 1.0), "b": Outcome("linked_existing", "m1", 0.95)}
        assert dm.shared_links(outcomes) == {"b": "same PitchRank team as Demosphere team a"}

    def test_a_stored_team_with_no_gender_is_not_refused_for_its_gender(self):
        row = _row("1")
        assert dm.off_board_links([row], _linked(row), {"master-1": {"age_group": "u13", "gender": None}}) == {}


class TestClubCodeExpansion:
    @pytest.mark.parametrize(
        ("name", "club", "expected"),
        [
            ("HERN NCSL B2011/12 White", "Herndon Youth Soccer", "Herndon NCSL B2011/12 White"),
            ("ARL 2013/14G Black", "Arlington Soccer", "Arlington 2013/14G Black"),
            ("LOUD U13G White", "Loudoun Soccer", "Loudoun U13G White"),
            ("MCLN U11 Girls Gold", "McLean Youth Soccer", "MCLN U11 Girls Gold"),
            ("Herndon NCSL G2010/11", "Herndon Youth Soccer", "Herndon NCSL G2010/11"),
            ("HE NCSL B2011/12", "Herndon Youth Soccer", "HE NCSL B2011/12"),
            ("HERN", "Herndon Youth Soccer", "HERN"),
            ("HERN NCSL B2011/12", None, "HERN NCSL B2011/12"),
        ],
    )
    def test_a_leading_club_code_is_spelled_out_only_when_it_is_a_prefix_of_the_stored_clubs_first_word(
        self, name, club, expected
    ):
        assert expand_club_code(name, club) == expected

    def test_the_matcher_matches_on_the_spelled_out_name(self):
        matcher = object.__new__(DemosphereGameMatcher)
        with patch.object(TourneyCentralGameMatcher, "_fuzzy_match_team", return_value=None) as base:
            matcher._fuzzy_match_team("HERN NCSL B2011/12 White", "u15", "Male", "Herndon Youth Soccer", "VA")
        base.assert_called_once_with("Herndon NCSL B2011/12 White", "u15", "Male", "Herndon Youth Soccer", "VA")


class TestOwnerClubDecisions:
    @pytest.mark.parametrize(
        ("listed", "club", "state"),
        [
            ("Prince William Courage - Travel", "Prince William Soccer Inc", None),
            ("Bethesda Soccer Club", "Bethesda SC", "MD"),
            ("FC Charles", "FC Charles 1658", "MD"),
            ("Montgomery Soccer Inc.", "Montgomery Soccer (MSI)", "MD"),
            ("Northern Virginia Soccer Club - Travel", "NVSC", None),
            ("NPC Futbol and Futsal", "NPC Futbol & Futsal", "VA"),
            ("Potomac Soccer Association", "Potomac Soccer Association", "MD"),
            ("Alexandria Soccer Association - Travel", "Alexandria SA", None),
            ("Arlington Soccer Association", "Arlington SA", None),
            ("BVBIA - PAC Northern Virginia", "Premier AC", None),
            ("Cipriani Sports Academy", "Cipriani Accademia FC", None),
            ("Clarke County Soccer", "Clarke County Soccer League", None),
            ("South County Athletic Association", "South County Athletic Association", None),
            ("St Mary's Soccer", "St. Mary's Soccer", "MD"),
            ("Springfield South County Youth - Travel", "Springfield SYC", None),
            ("Takoma Park", "Takoma Park Soccer Club", "MD"),
            ("The St. James FC - Travel", "The St. James Football Club", None),
            ("Virginia Soccer Association - Travel", "Virginia Soccer Association", None),
            ("Herndon Youth Soccer Assoc - Travel", "Herndon Youth Soccer", None),
        ],
    )
    def test_each_club_is_filed_under_the_name_and_state_the_owner_set(self, listed, club, state):
        overrides = dm.LEAGUES["80738"].club_overrides
        stub = _stub("11", "ABC U13G White", club="9")
        (row,), _ = dm.build_roster(
            {"11": stub}, {"9": listed}, lambda names: {}, "80738", "Fall2026", "VA", 2026, (), overrides
        )
        assert row.club_name == club
        assert (row.state_code, row.state_source) == ((state, "set for the club") if state else ("VA", "league state"))

    def test_vista_hl92_teams_are_filed_under_the_spelled_out_association(self):
        overrides = dm.LEAGUES["80738"].club_overrides
        club, written, source = dm.club_for(
            "VA Indpt Soccer Team Assoc - Travel", "VISTA HL92 Soccer Academy U12B Blue", True, overrides
        )
        assert (club, source) == ("Virginia Independent Soccer Team Association", "cut from name")
        assert written == "VISTA HL92 Soccer"

    def test_the_other_vista_clubs_keep_the_club_cut_from_their_names(self):
        overrides = dm.LEAGUES["80738"].club_overrides
        listed = "VA Indpt Soccer Team Assoc - Travel"
        assert dm.club_for(listed, "VISTA Warriors U13G", True, overrides)[0] == "VISTA Warriors"

    def test_the_decided_clubs_are_exactly_these(self):
        assert dm.NCSL_CLUBS == {
            "Prince William Courage": ("Prince William Soccer Inc", None),
            "Bethesda Soccer Club": ("Bethesda SC", "MD"),
            "FC Charles": ("FC Charles 1658", "MD"),
            "Montgomery Soccer Inc.": ("Montgomery Soccer (MSI)", "MD"),
            "Northern Virginia Soccer Club": ("NVSC", None),
            "NPC Futbol and Futsal": ("NPC Futbol & Futsal", "VA"),
            "Potomac Soccer Association": ("Potomac Soccer Association", "MD"),
            "St Mary's Soccer": ("St. Mary's Soccer", "MD"),
            "Springfield South County Youth": ("Springfield SYC", None),
            "Takoma Park": ("Takoma Park Soccer Club", "MD"),
            "The St. James FC": ("The St. James Football Club", None),
            "Alexandria Soccer Association": ("Alexandria SA", None),
            "Arlington Soccer Association": ("Arlington SA", None),
            "BVBIA - PAC Northern Virginia": ("Premier AC", None),
            "Cipriani Sports Academy": ("Cipriani Accademia FC", None),
            "Clarke County Soccer": ("Clarke County Soccer League", None),
            "VISTA HL92 Soccer Academy": ("Virginia Independent Soccer Team Association", None),
        }

    def test_a_club_state_set_for_the_club_outranks_what_its_stored_teams_say(self):
        assert dm.resolve_state("ABC U13G", "Bethesda SC", {"Bethesda SC": "VA"}, "VA", "MD") == (
            "MD",
            "set for the club",
        )

    def test_a_tag_that_matches_the_clubs_own_state_is_no_reason_to_hold(self):
        assert dm.resolve_state("Takoma U13G (MD)", "Takoma Park Soccer Club", {}, "VA", "MD")[0] == "MD"

    def test_a_tag_that_disagrees_with_the_clubs_own_state_is_held(self):
        state, reason = dm.resolve_state("Takoma U13G (VA)", "Takoma Park Soccer Club", {}, "VA", "MD")
        assert (state, reason) == (None, "name carries the VA tag, not MD")
