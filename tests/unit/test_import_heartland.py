"""Unit tests for the Heartland Soccer Premier league driver."""

import csv
import re
from datetime import date
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from rich.console import Console

from scripts import import_heartland as hl
from scripts.import_tourneycentral_event import ScrapeFetchError
from src.models.heartland_matcher import HeartlandGameMatcher
from src.models.tourneycentral_matcher import TourneyCentralGameMatcher
from tests.unit.test_athletes2events_matcher import _DB, PROVIDER

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "heartland"
SERVED = {
    ("Boys", "U-12", "1"): "results_boys_u12_1.html",
    ("Boys", "U-13", "1"): "results_boys_u13_1.html",
    ("Boys", "U-14/15", "9"): "results_boys_u14-15_9.html",
    ("Girls", "U-18/19", "1"): "results_girls_u18-19_1.html",
}


def _fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _served(url, edits=None):
    """The fixture page a results URL serves, edited by ``edits[fixture name]`` where given."""
    query = {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}
    name = SERVED.get((query["b_g"], query["age"], query["subdivison"]), "no_such_subdivision.html")
    html = _fixture(name)
    return (edits or {}).get(name, lambda page: page)(html)


def _page(name, gender, age, subdivision, season=2026):
    return hl.parse_results_page(_fixture(name), gender, age, subdivision, season)


@pytest.fixture(scope="module")
def u12():
    return _page("results_boys_u12_1.html", "Boys", "U-12", 1)


class TestParseResultsPage:
    def test_reads_every_team_and_game(self, u12):
        assert len(u12.teams) == 11
        assert len(u12.games) == 44
        assert (u12.unscored, u12.problems) == (0, [])

    def test_the_team_number_is_cut_off_the_name(self, u12):
        assert u12.teams["7210"] == "FC Vardar U12 B Red"
        assert u12.teams["721A"] == "Union KC 14/15B Pre ECNL Navy"

    def test_first_game_reads_both_sides_their_scores_and_the_date(self, u12):
        first = u12.games[0]
        assert (first.game_no, first.game_date, first.game_time) == ("238", date(2026, 8, 9), "09:15 am")
        assert (first.home_id, first.home_score, first.away_id, first.away_score) == ("7210", 3, "7219", 2)
        assert first.division_code == "U-12 Boys Premier Subdivision 1"

    def test_a_game_printed_without_a_date_takes_the_one_above_it(self, u12):
        second = u12.games[1]
        assert (second.game_no, second.game_date) == ("235", date(2026, 8, 9))

    def test_a_thursday_written_thr_is_read(self):
        page = _page("results_boys_u13_1.html", "Boys", "U-13", 1)
        assert page.problems == []
        assert {g.game_no: g.game_date for g in page.games}["3296"] == date(2026, 10, 15)

    def test_a_subdivision_the_league_does_not_run_is_none(self):
        assert hl.parse_results_page(_fixture("no_such_subdivision.html"), "Boys", "U-15", 1, 2026) is None

    def test_a_page_that_is_neither_raises(self):
        with pytest.raises(ScrapeFetchError):
            hl.parse_results_page("<html><body>Service Unavailable</body></html>", "Boys", "U-12", 1, 2026)

    def test_an_unreadable_score_is_a_problem_and_not_a_game(self):
        html = _fixture("results_boys_u12_1.html").replace("<td align=center>3</td>", "<td align=center>F</td>", 1)
        page = hl.parse_results_page(html, "Boys", "U-12", 1, 2026)
        assert len(page.games) == 43
        assert page.problems == ["U-12 Boys Premier Subdivision 1 game 238: unreadable score 'F'-'2'"]

    def test_a_game_with_one_blank_score_is_a_problem(self):
        html = _fixture("results_boys_u12_1.html").replace("<td align=center>3</td>", "<td align=center></td>", 1)
        page = hl.parse_results_page(html, "Boys", "U-12", 1, 2026)
        assert (len(page.games), page.unscored) == (43, 0)
        assert page.problems == ["U-12 Boys Premier Subdivision 1 game 238: unreadable score ''-'2'"]

    def test_a_game_with_both_scores_blank_is_unscored(self):
        html = _fixture("results_boys_u12_1.html").replace(
            "<td align=center>3</td><td>7219 Toca Fusion Elite BU11</td><td align=center>2</td>",
            "<td align=center></td><td>7219 Toca Fusion Elite BU11</td><td align=center></td>",
            1,
        )
        page = hl.parse_results_page(html, "Boys", "U-12", 1, 2026)
        assert (len(page.games), page.unscored, page.problems) == (43, 1, [])

    def test_a_malformed_first_game_of_a_day_lends_its_followers_no_date(self):
        html = _fixture("results_boys_u12_1.html").replace("<td>1878</td><td>09:15 am</td>", "<td>1878</td>", 1)
        page = hl.parse_results_page(html, "Boys", "U-12", 1, 2026)
        dates = {g.game_no: g.game_date for g in page.games}
        # 1713, 1842 and 1883 follow 1878 on Aug 29; the day before, Aug 28, must not be theirs.
        assert {"1878", "1713", "1842", "1883"}.isdisjoint(dates)
        assert dates["1948"] == date(2026, 8, 30)
        assert any("unreadable game row" in p for p in page.problems)

    def test_a_page_without_its_team_list_raises(self):
        html = _fixture("results_boys_u12_1.html").replace("cols=2 class=text", "cols=2 class=roster", 1)
        with pytest.raises(ScrapeFetchError, match="no team list"):
            hl.parse_results_page(html, "Boys", "U-12", 1, 2026)

    def test_a_blank_game_number_is_a_problem_and_not_a_game(self):
        html = _fixture("results_boys_u12_1.html").replace("<td>238</td>", "<td></td>", 1)
        page = hl.parse_results_page(html, "Boys", "U-12", 1, 2026)
        assert len(page.games) == 43
        assert "" not in {g.game_no for g in page.games}
        assert page.problems == ["U-12 Boys Premier Subdivision 1: unreadable game '7210 FC Vardar U12 B Red'"]

    def test_an_unreadable_date_is_a_problem(self):
        html = _fixture("results_boys_u12_1.html").replace(" Aug 9 (Sun)", " Aug 9 (Mon)", 1)
        page = hl.parse_results_page(html, "Boys", "U-12", 1, 2026)
        assert "U-12 Boys Premier Subdivision 1: unreadable date 'Aug 9 (Mon)'" in page.problems
        assert "238" not in {g.game_no for g in page.games}


class TestGameDate:
    @pytest.mark.parametrize(
        ("label", "season", "expected"),
        [
            ("Aug 9 (Sun)", 2026, date(2026, 8, 9)),
            ("Oct 15 (Thr)", 2026, date(2026, 10, 15)),
            ("Sep 11 (Fri)", 2026, date(2026, 9, 11)),
            # A spring game falls in the season's second year.
            ("Mar 7 (Sun)", 2026, date(2027, 3, 7)),
            # The site still shows last spring after Aug 1: the weekday picks the year.
            ("Mar 7 (Sun)", 2027, date(2027, 3, 7)),
            # Aug 9 2027 is a Monday, but a fall date never moves into the next season.
            ("Aug 9 (Mon)", 2026, None),
            # A fall game read after the next season began.
            ("Oct 15 (Thr)", 2027, date(2026, 10, 15)),
            ("Smarch 9 (Sun)", 2026, None),
            ("Feb 30 (Sun)", 2026, None),
        ],
    )
    def test_the_year_is_the_one_whose_weekday_matches(self, label, season, expected):
        assert hl.game_date(label, season) == expected


class TestHalfSeason:
    def test_a_fall_season(self):
        assert hl.half_season([date(2026, 8, 7), date(2026, 10, 25)]) == ("2026fall", [])

    def test_a_spring_season(self):
        assert hl.half_season([date(2027, 3, 6)]) == ("2027spring", [])

    def test_two_halves_in_one_run_are_a_problem(self):
        half, problems = hl.half_season([date(2026, 10, 25), date(2027, 3, 6)])
        assert half is None
        assert problems == ["the pages hold games from more than one half-season: 2026fall, 2027spring"]


class TestClubAndState:
    def test_a_club_table_prefix_files_the_team_under_the_stored_club(self):
        club_name, written, source, club = hl.club_for_team("SBV IP BluSky United")
        assert (club_name, written, source) == ("Sporting Blue Valley", "SBV", "club table")
        assert club.spellings == ("SPORTING BV", "SPORTING BV IP")

    def test_the_table_matches_case_insensitively_and_keeps_the_written_spelling(self):
        club_name, written, _, _ = hl.club_for_team("SPORTING BV Pre-MLS White 15/16")
        assert (club_name, written) == ("Sporting Blue Valley", "SPORTING BV")

    def test_a_prefix_must_end_at_a_word(self):
        club_name, _, source, _ = hl.club_for_team("OPAL United U12")
        assert source == "cut from name"
        assert club_name != "OP Soccer Club"

    def test_a_club_outside_the_table_is_cut_from_the_name(self):
        club_name, written, source, club = hl.club_for_team("FC Vardar U12 B Red")
        assert (club_name, source, club) == ("FC Vardar", "cut from name", None)
        assert written == "FC Vardar"

    def test_a_state_set_for_the_club_wins(self):
        club = hl.HeartlandClub("Kansas City Athletics", ("KC Athletics",), "KS")
        stored = {"Kansas City Athletics": "KS", "KC Athletics": "MO"}
        assert hl.resolve_state("Kansas City Athletics", club, stored) == ("KS", "set for the club")

    def test_the_registry_home_is_the_clubs_state(self):
        assert hl.resolve_state("Sporting Blue Valley", None, {"Sporting Blue Valley": "MO"}) == (
            "KS",
            "club-state registry",
        )

    def test_a_club_the_registry_curates_is_held(self):
        state, source = hl.resolve_state("KC Legends", None, {"KC Legends": "KS"})
        assert state is None
        assert source == "the club-state registry asks a person to pick this club's state"

    def test_one_agreed_stored_state_is_the_clubs(self):
        assert hl.resolve_state("Topeka SC", None, {"Topeka SC": "KS"}) == ("KS", "club's stored teams")

    def test_a_club_whose_own_stored_teams_disagree_is_held(self):
        assert hl.resolve_state("Topeka SC", None, {"Topeka SC": None}) == (
            None,
            "the club's stored teams disagree on state",
        )

    def test_two_spellings_stored_in_two_states_hold_the_club(self):
        club = hl.HeartlandClub("Kansas City Athletics", ("KC Athletics",))
        stored = {"Kansas City Athletics": "KS", "KC Athletics": "MO"}
        assert hl.resolve_state("Kansas City Athletics", club, stored) == (
            None,
            "the club's stored teams disagree on state",
        )

    def test_two_spellings_stored_in_one_state_give_it(self):
        club = hl.HeartlandClub("Kansas City Athletics", ("KC Athletics",))
        stored = {"Kansas City Athletics": "KS", "KC Athletics": "KS"}
        assert hl.resolve_state("Kansas City Athletics", club, stored) == ("KS", "club's stored teams")

    def test_a_club_with_no_stored_team_is_held(self):
        assert hl.resolve_state("Liberty United Legacy", None, {}) == (None, "no stored team of this club in KS or MO")

    def test_a_registry_home_outside_the_region_is_not_taken(self):
        # The registry homes this club in Illinois; a Heartland team of that name is no reason to file one there.
        assert hl.resolve_state("Central Illinois United", None, {}) == (
            None,
            "no stored team of this club in KS or MO",
        )


class TestRegisterTeams:
    class _Matcher:
        def __init__(self, result=None, error=None):
            self.result, self.error = result, error

        def _match_team(self, **kwargs):
            if self.error:
                raise self.error
            return self.result

    @staticmethod
    def _row(state_code=None, state_source="no stored team of this club in KS or MO"):
        return hl.HeartlandTeamRow(
            tc_team_id="2026fall-7210",
            team_name="FC Vardar U12 B Red",
            club_name="FC Vardar",
            club_as_written="FC Vardar",
            division_name="U-12 Boys Premier Subdivision 1",
            division_age="u12",
            birth_year=2015,
            age_group="u12",
            age_source="name",
            gender="Male",
            state_code=state_code,
            state_source=state_source,
        )

    def _outcome(self, row, **matcher):
        return hl.register_teams(self._Matcher(**matcher), "pid", [row], {})[row.tc_team_id]

    def test_a_stateless_team_the_matcher_cannot_place_is_held_with_its_state_reason(self):
        outcome = self._outcome(self._row(), result={"matched": False, "created": False, "method": None})
        assert (outcome.status, outcome.reason) == ("held", "no stored team of this club in KS or MO")

    def test_a_stated_team_the_matcher_cannot_place_is_an_error(self):
        outcome = self._outcome(self._row("KS"), result={"matched": False, "created": False, "method": None})
        assert outcome.status == "error"

    def test_a_failed_lookup_is_an_error_even_for_a_stateless_team(self):
        outcome = self._outcome(self._row(), error=RuntimeError("canceling statement due to statement timeout"))
        assert (outcome.status, outcome.reason) == ("error", "canceling statement due to statement timeout")

    def test_a_stateless_team_sent_to_review_stays_a_review(self):
        outcome = self._outcome(self._row(), result={"matched": False, "review": True, "confidence": 0.89})
        assert outcome.status == "review"

    def test_a_stateless_team_that_links_is_linked(self):
        result = {"matched": True, "created": False, "team_id": "ks-1", "method": "fuzzy_auto", "confidence": 1.0}
        outcome = self._outcome(self._row(), result=result)
        assert (outcome.status, outcome.team_id_master) == ("linked_existing", "ks-1")

    def test_an_approved_alias_skips_the_matcher(self):
        row = self._row()
        outcomes = hl.register_teams(self._Matcher(error=AssertionError("asked")), "pid", [row], {row.tc_team_id: "m"})
        assert outcomes[row.tc_team_id].status == "already_linked"


class TestWindowStart:
    @pytest.mark.parametrize(
        ("since", "event_season", "expected"),
        [
            (None, 2026, date(2026, 8, 1)),
            (date(2026, 9, 1), 2026, date(2026, 9, 1)),
            # The owner's floor holds against an earlier --since and a retained spring-2026 page.
            (date(2025, 8, 1), 2026, date(2026, 8, 1)),
            (None, 2025, date(2026, 8, 1)),
            (None, 2027, date(2027, 8, 1)),
        ],
    )
    def test_no_game_before_the_owners_floor_is_imported(self, since, event_season, expected):
        assert hl.window_start(since, event_season) == expected


class TestHeldRows:
    def test_each_held_game_names_why_its_teams_wait(self, pages):
        in_scope, left_out = hl.build_roster(pages, "2026fall", 2026, 2026, lambda names: {})
        games, _ = hl.league_games(pages, "2026fall", date(2026, 8, 1), date(2026, 11, 14))
        outcomes = {
            row.tc_team_id: hl.Outcome("held", reason=row.state_source)
            if row.state_code is None
            else hl.Outcome("created", f"m-{row.tc_team_id}", 1.0)
            for row in in_scope
        }
        game = next(g for g in games if g.home_id == "2026fall-7210" and g.away_id == "2026fall-7219")
        (row,) = hl.held_rows([game], in_scope + left_out, outcomes)
        assert row["reason"] == (
            "a team is held for its state: no stored team of this club in KS or MO; "
            "a team is held for its state: no stored team of this club in KS or MO"
        )

    def test_a_held_team_beside_a_linked_one_names_only_the_held_side(self, pages):
        in_scope, left_out = hl.build_roster(pages, "2026fall", 2026, 2026, lambda names: {})
        games, _ = hl.league_games(pages, "2026fall", date(2026, 8, 1), date(2026, 11, 14))
        outcomes = {row.tc_team_id: hl.Outcome("created", f"m-{row.tc_team_id}", 1.0) for row in in_scope}
        outcomes["2026fall-7219"] = hl.Outcome("held", reason="the club's stored teams disagree on state")
        game = next(g for g in games if g.home_id == "2026fall-7210" and g.away_id == "2026fall-7219")
        (row,) = hl.held_rows([game], in_scope + left_out, outcomes)
        assert row["reason"] == "a team is held for its state: the club's stored teams disagree on state"

    def test_a_left_out_team_is_named_as_left_out(self, pages):
        in_scope, left_out = hl.build_roster(pages, "2026fall", 2026, 2026, lambda names: {})
        games, _ = hl.league_games(pages, "2026fall", date(2026, 8, 1), date(2026, 11, 14))
        game = next(g for g in games if "2026fall-7490" in (g.home_id, g.away_id))
        (row,) = hl.held_rows([game], in_scope + left_out, {})
        assert "a team is left out: no age in the team name, and its division spans two ages" in row["reason"]


@pytest.fixture(scope="module")
def pages():
    return [_page(name, gender, age, int(sd)) for (gender, age, sd), name in SERVED.items()]


class TestBuildRoster:
    @staticmethod
    def _roster(pages, stored=None):
        def lookup(names):
            return {name: "KS" for name in names} if stored is None else stored

        in_scope, left_out = hl.build_roster(pages, "2026fall", 2026, 2026, lookup)
        return {row.tc_team_id: row for row in in_scope}, {row.tc_team_id: row for row in left_out}

    def test_ids_are_scoped_to_the_half_season(self, pages):
        in_scope, left_out = self._roster(pages)
        assert "2026fall-7210" in in_scope
        assert all(re.fullmatch(r"2026fall-[0-9A-Z]{4}", key) for key in {*in_scope, *left_out})

    def test_the_name_sets_the_age(self, pages):
        in_scope, _ = self._roster(pages)
        assert in_scope["2026fall-7210"].age_group == "u12"
        # 14/15 is U12; the team number 7213 is never read as a year.
        assert in_scope["2026fall-7213"].age_group == "u12"
        # A U11 team playing up in a U12 division keeps its own age.
        assert in_scope["2026fall-7219"].age_group == "u11"

    def test_a_name_with_no_age_takes_a_one_cohort_divisions_age(self, pages):
        in_scope, _ = self._roster(pages)
        row = in_scope["2026fall-8813"]
        assert (row.team_name, row.age_group) == ("KC Athletics Acad Select Navy", "u19")

    def test_a_name_with_no_age_in_a_two_cohort_division_is_left_out(self, pages):
        _, left_out = self._roster(pages)
        row = left_out["2026fall-7490"]
        assert row.team_name == "Kansas academy fc"
        assert row.skip_reason == "no age in the team name, and its division spans two ages"

    @pytest.mark.parametrize(
        ("age", "name", "expected"),
        [
            # Heartland writes a glued or bare number as a U-age as often as a birth year, so the
            # division's age stands, where reading it as a year would put a U10 team on u17.
            ("U-10", "Manhattan Surf Blue 10B", "u10"),
            ("U-11", "KC Athletics Monaco 11B", "u11"),
            ("U-11", "LFC Academy 15", "u11"),
            # A four-digit year and a band are still the name's own age.
            ("U-10", "KC Atletico 2016B", "u11"),
            ("U-12", "Sporting BV Pre-MLS Next NV 14/15", "u12"),
        ],
    )
    def test_a_bare_or_glued_two_digit_number_is_not_read_as_a_birth_year(self, age, name, expected):
        page = hl.ResultsPage(
            division=hl.division_for("Boys", age, 1), teams={"7001": name}, games=[], unscored=0, problems=[]
        )
        in_scope, _ = self._roster([page])
        assert in_scope["2026fall-7001"].age_group == expected

    def test_u18_19_in_a_name_is_the_u19_board(self, pages):
        in_scope, _ = self._roster(pages)
        row = in_scope["2026fall-8811"]
        assert (row.team_name, row.age_group, row.age_source) == (
            "Bk Academy FC U18/19G N1",
            "u19",
            "two U-ages on one board",
        )

    @pytest.mark.parametrize("name", ["SS Academy U12/U13B Grey", "HAFC Elite U14/15G"])
    def test_two_u_ages_on_two_boards_are_left_out(self, name):
        page = hl.ResultsPage(
            division=hl.division_for("Boys", "U-13", 1), teams={"7001": name}, games=[], unscored=0, problems=[]
        )
        _, left_out = self._roster([page])
        assert left_out["2026fall-7001"].skip_reason == "two U-ages, left out"

    def test_gender_is_the_divisions(self, pages):
        in_scope, _ = self._roster(pages)
        assert in_scope["2026fall-7210"].gender == "Male"
        assert in_scope["2026fall-8813"].gender == "Female"

    def test_a_club_table_team_takes_the_registry_state(self, pages):
        in_scope, _ = self._roster(pages, stored={})
        row = in_scope["2026fall-8816"]
        assert (row.club_name, row.club_as_written, row.state_code) == ("Sporting Blue Valley", "SBV", "KS")
        assert (row.club_source, row.state_source) == ("club table", "club-state registry")

    def test_a_team_whose_club_has_no_state_stays_in_scope_to_be_matched(self, pages):
        in_scope, left_out = self._roster(pages, stored={})
        row = in_scope["2026fall-7210"]
        assert row.state_code is None
        assert row.state_source == "no stored team of this club in KS or MO"
        assert not any("state" in r.skip_reason for r in left_out.values())

    def test_a_team_listed_at_two_ages_takes_neither_divisions_age(self):
        page = _page("results_girls_u18-19_1.html", "Girls", "U-18/19", 1)
        other = hl.ResultsPage(
            division=hl.division_for("Girls", "U-17", 1),
            teams={"8813": page.teams["8813"]},
            games=[],
            unscored=0,
            problems=[],
        )
        in_scope, left_out = self._roster([page, other])
        assert "2026fall-8813" not in in_scope
        assert left_out["2026fall-8813"].skip_reason == (
            "no age in the team name, and it is listed in divisions of different ages"
        )

    def test_a_team_seen_only_in_another_divisions_games_takes_no_division_from_them(self):
        html = _fixture("results_boys_u12_1.html").replace(
            "<td width=50% height=20> 7210 FC Vardar U12 B Red</td>", "", 1
        )
        page = hl.parse_results_page(html, "Boys", "U-12", 1, 2026)
        assert "7210" in page.opponents and "7210" not in page.teams
        in_scope, left_out = self._roster([page])
        assert "2026fall-7210" not in in_scope
        assert left_out["2026fall-7210"].skip_reason == "not on any subdivision's team list"

    def test_the_lookup_is_asked_about_every_club_and_spelling(self, pages):
        asked = []
        hl.build_roster(pages, "2026fall", 2026, 2026, lambda names: asked.extend(names) or {})
        assert {"Sporting Blue Valley", "SPORTING BV", "SPORTING BV IP", "FC Vardar"} <= set(asked)


class TestLeagueGames:
    def test_games_take_season_scoped_ids_and_stay_in_the_window(self, u12):
        games, problems = hl.league_games([u12], "2026fall", date(2026, 9, 1), date(2026, 11, 14))
        assert problems == []
        assert min(g.game_date for g in games) >= date(2026, 9, 1)
        assert {g.home_id for g in games} <= {f"2026fall-{n}" for n in u12.teams}
        assert len(games) == sum(1 for g in u12.games if g.game_date >= date(2026, 9, 1))

    def test_a_game_printed_on_two_subdivisions_pages_is_read_once(self, u12):
        other = _page("results_boys_u12_1.html", "Boys", "U-12", 2)
        games, problems = hl.league_games([u12, other], "2026fall", date(2026, 8, 1), date(2026, 11, 14))
        assert (len(games), problems) == (44, [])
        assert len({g.game_no for g in games}) == 44

    def test_a_disputed_game_is_imported_in_neither_version(self, u12):
        other = hl.parse_results_page(
            _fixture("results_boys_u12_1.html").replace("<td align=center>3</td>", "<td align=center>4</td>", 1),
            "Boys",
            "U-12",
            2,
            2026,
        )
        games, problems = hl.league_games([u12, other], "2026fall", date(2026, 8, 1), date(2026, 11, 14))
        assert "238" not in {g.game_no for g in games}
        assert len(games) == 43
        assert len(problems) == 1

    def test_a_game_listed_twice_with_different_scores_is_a_problem(self, u12):
        other = hl.parse_results_page(
            _fixture("results_boys_u12_1.html").replace("<td align=center>3</td>", "<td align=center>4</td>", 1),
            "Boys",
            "U-12",
            1,
            2026,
        )
        _, problems = hl.league_games([u12, other], "2026fall", date(2026, 8, 1), date(2026, 11, 14))
        assert problems == [
            "game 238: listed in U-12 Boys Premier Subdivision 1 and U-12 Boys Premier Subdivision 1"
            " with different details"
        ]


class TestScope:
    def test_no_division_below_the_boards_is_walked(self):
        assert all(age != "U-9" for _, age in hl.DIVISIONS)

    def test_every_url_is_the_premier_results_page(self):
        url = hl.results_url("Girls", "U-18/19", 3)
        assert url.startswith("https://heartlandsoccer.net/reports/cgi-jrb/subdiv_results.cgi?")
        assert parse_qs(urlparse(url).query) == {
            "level": ["Premier"],
            "b_g": ["Girls"],
            "age": ["U-18/19"],
            "subdivison": ["3"],
        }

    def test_the_matcher_is_tourney_centrals(self):
        assert issubclass(HeartlandGameMatcher, TourneyCentralGameMatcher)


class TestFixturePrivacy:
    def test_no_contact_detail_survives_into_a_fixture(self):
        for fixture in FIXTURES.glob("*.html"):
            text = fixture.read_text(encoding="utf-8")
            assert set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", text)) <= {"person@example.com"}, fixture.name
            assert not re.search(r"\(?\d{3}\)?[-. ]\d{3}-\d{4}", text), fixture.name

    def test_the_scrubbed_page_still_carries_the_placeholder(self):
        assert "person@example.com" in _fixture("no_such_subdivision.html")


class TestRunMain:
    """``main`` end to end against fixture pages, a recording matcher and a recording import."""

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 14)

    @pytest.fixture
    def run_main(self, monkeypatch, tmp_path):
        state = SimpleNamespace(
            matchers=[],
            imports=[],
            import_code=0,
            results={},
            queued=set(),
            linked_teams={},
            fetched=[],
            regions=[],
            stored=None,
            edits={},
            pauses=[],
        )

        class FakeMatcher:
            def __init__(self, supabase, provider_id=None, registration_mode=False, dry_run=False, **_):
                self.dry_run, self.registration_mode, self.calls = dry_run, registration_mode, []
                state.matchers.append(self)

            def _match_team(self, **kwargs):
                self.calls.append(kwargs["provider_team_id"])
                if kwargs["state_code"]:
                    default = {"matched": True, "created": True, "team_id": f"master-{kwargs['provider_team_id']}"}
                else:
                    # As production: the matcher never creates a team without a state.
                    default = {"matched": False, "created": False, "method": None}
                return state.results.get(kwargs["provider_team_id"], default)

        class FakeClient:
            def table(self, name):
                assert name == "providers"
                return SimpleNamespace(
                    select=lambda *_: SimpleNamespace(
                        eq=lambda *_: SimpleNamespace(execute=lambda: SimpleNamespace(data=[{"id": "pid"}]))
                    )
                )

        def fetch(session, url):
            state.fetched.append(url)
            return _served(url, state.edits)

        def club_states(supabase, names, region=()):
            state.regions.append(region)
            return {name: "KS" for name in names} if state.stored is None else state.stored

        def fake_run(command, check):
            state.imports.append(command)
            return SimpleNamespace(returncode=state.import_code)

        state.aliases = lambda ids: (
            {key: f"master-{key}" for key in ids} if any(not m.dry_run for m in state.matchers) else {}
        )
        monkeypatch.setenv("SUPABASE_URL", "http://db")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
        monkeypatch.setattr(hl, "create_client", lambda *_: FakeClient())
        monkeypatch.setattr(hl, "make_session", lambda: None)
        monkeypatch.setattr(hl, "_fetch", fetch)
        monkeypatch.setattr(hl, "HeartlandGameMatcher", FakeMatcher)
        monkeypatch.setattr(hl, "existing_aliases", lambda supabase, provider_id, ids: state.aliases(ids))
        monkeypatch.setattr(hl, "pending_reviews", lambda supabase, ids, provider_code=None: state.queued & set(ids))
        monkeypatch.setattr(
            hl, "teams_by_id", lambda supabase, ids: {k: v for k, v in state.linked_teams.items() if k in ids}
        )
        monkeypatch.setattr(hl, "club_states", club_states)
        monkeypatch.setattr(hl.subprocess, "run", fake_run)
        monkeypatch.setattr(hl, "date", self.FixedDate)
        monkeypatch.setattr(hl.time, "sleep", state.pauses.append)
        state.console = Console(file=StringIO(), width=200)
        monkeypatch.setattr(hl, "console", state.console)

        def run(*argv):
            monkeypatch.setattr(
                "sys.argv",
                ["import_heartland.py", "--delay-min", "0", "--delay-max", "0", "--output-dir", str(tmp_path), *argv],
            )
            return hl.main()

        state.run = run
        state.out = tmp_path
        state.output = lambda: state.console.file.getvalue()
        state.rows = lambda kind: list(csv.DictReader(next(tmp_path.glob(f"*_{kind}.csv")).open(encoding="utf-8")))
        return state

    def test_only_premier_results_pages_are_fetched(self, run_main):
        run_main.run()
        for url in run_main.fetched:
            assert url.startswith("https://heartlandsoccer.net/reports/cgi-jrb/subdiv_results.cgi?")
            assert parse_qs(urlparse(url).query)["level"] == ["Premier"]
            assert not re.search(r"seedings|team_results|member-clubs|Recreational|U-9\b", url)

    def test_the_walk_covers_twenty_divisions_by_thirteen_subdivisions_pausing_after_each(self, run_main):
        run_main.run()
        assert len(run_main.fetched) == 260
        assert len(run_main.pauses) == 260
        divisions = {(q["b_g"][0], q["age"][0]) for q in (parse_qs(urlparse(u).query) for u in run_main.fetched)}
        assert len(divisions) == 20
        assert {("Boys", "U-17"), ("Girls", "U-18/19"), ("Boys", "U-14/15")} <= divisions
        assert {q["subdivison"][0] for q in (parse_qs(urlparse(u).query) for u in run_main.fetched)} == {
            str(n) for n in range(1, 14)
        }

    def test_one_named_division_walks_only_its_thirteen_subdivisions(self, run_main):
        run_main.run("--division", "Boys U-12")
        assert len(run_main.fetched) == 13
        assert all("b_g=Boys&age=U-12&" in url for url in run_main.fetched)

    def test_the_played_count_the_workflow_reads_is_the_scored_games(self, run_main):
        run_main.run()
        played = re.search(r"Games scraped: [0-9]+ \(([0-9]+) played\)", run_main.output())
        assert played and played.group(1) == "148"

    def test_a_season_with_no_scores_yet_reports_zero_played_and_registers_nothing(self, run_main):
        blank = lambda page: re.sub(r"<td align=center>[0-9]+</td>", "<td align=center></td>", page)  # noqa: E731
        run_main.edits = {name: blank for name in SERVED.values()}
        assert run_main.run("--execute") == 0
        assert re.search(r"Games scraped: 148 \(0 played\)", run_main.output())
        assert run_main.matchers == []
        assert run_main.imports == []

    def test_pages_from_two_half_seasons_fail_before_anything_is_registered(self, run_main):
        run_main.edits = {"results_boys_u13_1.html": lambda page: page.replace(" Aug 8 (Sat)", " Mar 6 (Sat)", 1)}
        assert run_main.run("--execute") == 1
        assert run_main.matchers == []
        assert run_main.imports == []
        assert "more than one half-season" in run_main.output()

    def test_the_team_report_names_where_each_club_and_state_came_from(self, run_main):
        run_main.stored = {}
        run_main.run()
        report = {r["heartland_team_id"]: r for r in run_main.rows("teams")}
        assert (report["2026fall-8816"]["club_source"], report["2026fall-8816"]["state_source"]) == (
            "club table",
            "club-state registry",
        )
        assert (report["2026fall-7210"]["club_source"], report["2026fall-7210"]["state_source"]) == (
            "cut from name",
            "no stored team of this club in KS or MO",
        )

    def test_a_dry_run_builds_only_a_dry_run_matcher_and_starts_no_import(self, run_main):
        assert run_main.run() == 0
        assert [(m.dry_run, m.registration_mode) for m in run_main.matchers] == [(True, True)]
        assert run_main.imports == []

    def test_a_dry_run_still_writes_the_reports_and_the_games_it_would_import(self, run_main):
        run_main.run()
        assert len(run_main.rows("teams")) == 37
        games = run_main.rows("games")
        assert {row["provider"] for row in games} == {"heartland"}
        assert all(re.fullmatch(r"2026fall-[0-9A-Z]{4}", row["team_id"]) for row in games)
        assert {row["schedule_id"] for row in games} >= {"heartland-2026fall-238"}
        assert "coach" not in run_main.rows("teams")[0]

    def test_execute_previews_then_writes_then_imports_once_under_the_provider_code(self, run_main):
        assert run_main.run("--execute") == 0
        assert [(m.dry_run, m.registration_mode) for m in run_main.matchers] == [(True, True), (False, True)]
        assert len(run_main.imports) == 1
        games_csv = str(next(run_main.out.glob("*_games.csv")))
        assert run_main.imports[0][1:] == ["scripts/import_games_enhanced.py", games_csv, "heartland"]

    def test_a_failing_import_is_the_runs_exit_code(self, run_main):
        run_main.import_code = 2
        assert run_main.run("--execute") == 2

    def test_stored_states_are_read_inside_kansas_and_missouri(self, run_main):
        run_main.run()
        assert run_main.regions == [("KS", "MO")]

    def test_since_drops_earlier_games(self, run_main):
        run_main.run("--since", "2026-10-01")
        assert min(row["game_date"] for row in run_main.rows("games")) >= "2026-10-01"

    def test_the_default_since_is_august_first(self, run_main):
        run_main.run()
        dates = [row["game_date"] for kind in ("games", "held") for row in run_main.rows(kind)]
        assert min(dates) == "2026-08-07"
        assert len(run_main.rows("games")) // 2 + len(run_main.rows("held")) == 148

    def test_a_new_team_held_for_its_state_has_its_games_held_and_the_run_stays_green(self, run_main):
        run_main.stored = {}
        assert run_main.run("--execute") == 0
        report = {r["heartland_team_id"]: r for r in run_main.rows("teams")}
        assert report["2026fall-7210"]["outcome"] == "held"
        assert report["2026fall-7210"]["reason"] == "no stored team of this club in KS or MO"
        assert all("2026fall-7210" not in (r["team_id"], r["opponent_id"]) for r in run_main.rows("games"))
        held = [h for h in run_main.rows("held") if "2026fall-7210" in (h["home_team_id"], h["away_team_id"])]
        assert held
        assert all("a team is held for its state: no stored team of this club in KS or MO" in h["reason"] for h in held)

    def test_a_stateless_team_is_still_offered_to_the_matcher(self, run_main):
        run_main.stored = {}
        run_main.run()
        (preview,) = run_main.matchers
        assert "2026fall-7210" in preview.calls

    def test_a_stateless_team_that_links_has_its_games_imported(self, run_main):
        run_main.stored = {}
        run_main.results = {
            "2026fall-7210": {"matched": True, "team_id": "stored", "method": "fuzzy_auto", "confidence": 1.0},
            "2026fall-7219": {"matched": True, "team_id": "stored-2", "method": "fuzzy_auto", "confidence": 1.0},
        }
        run_main.linked_teams = {
            "stored": {"team_name": "FC Vardar U12 B Red", "age_group": "u12", "gender": "Male"},
            "stored-2": {"team_name": "Toca Fusion Elite BU11", "age_group": "u11", "gender": "Male"},
        }
        assert run_main.run() == 0
        report = {r["heartland_team_id"]: r for r in run_main.rows("teams")}
        assert report["2026fall-7210"]["outcome"] == "linked_existing"
        assert any(r["schedule_id"] == "heartland-2026fall-238" for r in run_main.rows("games"))

    def test_two_teams_linking_to_one_team_are_conflicts_reported_without_failing(self, run_main):
        fuzzy = {"matched": True, "team_id": "same", "method": "fuzzy_auto", "confidence": 0.95}
        run_main.results = {"2026fall-7210": fuzzy, "2026fall-7211": fuzzy}
        assert run_main.run("--execute") == 0
        writer = next(m for m in run_main.matchers if not m.dry_run)
        assert {"2026fall-7210", "2026fall-7211"}.isdisjoint(writer.calls)
        report = {r["heartland_team_id"]: r for r in run_main.rows("teams")}
        assert report["2026fall-7210"]["outcome"] == "conflict"

    def test_a_link_the_alias_table_never_saved_is_an_error_and_fails_the_run(self, run_main):
        run_main.aliases = lambda ids: {}
        assert run_main.run("--execute") == 1
        assert run_main.rows("games") == []
        assert run_main.imports == []

    @pytest.mark.parametrize("argv", [(), ("--execute",)])
    def test_a_link_to_a_team_on_another_board_is_an_error_and_fails_the_run(self, run_main, argv):
        run_main.results = {"2026fall-7210": {"matched": True, "team_id": "stored", "method": "direct_id"}}
        run_main.linked_teams = {"stored": {"team_name": "Stored", "age_group": "u13", "gender": "Male"}}
        assert run_main.run(*argv) == 1
        report = {r["heartland_team_id"]: r for r in run_main.rows("teams")}
        assert report["2026fall-7210"]["outcome"] == "error"
        # The other games still import; the run is red for the one link.
        assert len(run_main.imports) == (1 if argv else 0)

    def test_a_review_row_that_was_not_saved_is_an_error_and_fails_the_run(self, run_main):
        run_main.results = {"2026fall-7210": {"matched": False, "review": True, "confidence": 0.85}}
        run_main.queued = set()
        assert run_main.run("--execute") == 1
        assert {r["heartland_team_id"]: r for r in run_main.rows("teams")}["2026fall-7210"]["outcome"] == "error"

    def test_a_saved_review_row_stays_a_review_and_the_run_stays_green(self, run_main):
        run_main.results = {"2026fall-7210": {"matched": False, "review": True, "confidence": 0.85}}
        run_main.queued = {"2026fall-7210"}
        assert run_main.run("--execute") == 0
        assert {r["heartland_team_id"]: r for r in run_main.rows("teams")}["2026fall-7210"]["outcome"] == "review"

    def test_an_unreadable_page_stops_the_run_before_anything_is_registered(self, run_main, monkeypatch):
        monkeypatch.setattr(hl, "_fetch", lambda session, url: "<html>Service Unavailable</html>")
        assert run_main.run("--execute") == 1
        assert run_main.matchers == []
        assert run_main.imports == []

    @pytest.mark.parametrize("argv", [(), ("--execute",)])
    def test_an_unreadable_score_fails_the_run(self, run_main, argv):
        forfeit = lambda page: page.replace("<td align=center>3</td>", "<td align=center>F</td>", 1)  # noqa: E731
        run_main.edits = {"results_boys_u12_1.html": forfeit}
        assert run_main.run(*argv) == 1
        assert len(run_main.imports) == (1 if argv else 0)


class _KeepingDB(_DB):
    """The Athletes2Events double, keeping what it inserts so a later read sees it, as the database would."""

    def __init__(self, teams=()):
        super().__init__(teams)
        self.rows["providers"] = [{"id": PROVIDER, "code": "heartland"}]

    def table(self, name):
        query = super().table(name)
        execute = query.execute

        def execute_and_keep():
            result = execute()
            if query.op == "insert":
                self.rows.setdefault(name, []).append({"is_deprecated": False, **query.payload})
            return result

        query.execute = execute_and_keep
        return query


class TestRunMainWithTheRealMatcher:
    """``main`` and ``HeartlandGameMatcher`` together, over a database double that records at ``execute()``."""

    TWIN = {
        "team_id_master": "stored-vardar",
        "team_name": "FC Vardar U12 B Red",
        "club_name": "FC Vardar",
        "age_group": "u12",
        "gender": "Male",
        "state_code": "KS",
    }

    @pytest.fixture
    def run_main(self, monkeypatch, tmp_path):
        db = _KeepingDB([self.TWIN])
        imports = []

        def fetch(session, url):
            return _served(url) if "b_g=Boys&age=U-12&subdivison=1" in url else _fixture("no_such_subdivision.html")

        monkeypatch.setenv("SUPABASE_URL", "http://db")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
        monkeypatch.setattr(hl, "create_client", lambda *_: db)
        monkeypatch.setattr(hl, "make_session", lambda: None)
        monkeypatch.setattr(hl, "_fetch", fetch)
        monkeypatch.setattr(hl, "club_states", lambda supabase, names, region=(): {})
        monkeypatch.setattr(
            hl.subprocess, "run", lambda command, check: imports.append(command) or SimpleNamespace(returncode=0)
        )
        monkeypatch.setattr(hl, "date", TestRunMain.FixedDate)

        def run(*argv):
            monkeypatch.setattr(
                "sys.argv",
                ["import_heartland.py", "--delay-min", "0", "--delay-max", "0", "--output-dir", str(tmp_path), *argv],
            )
            return hl.main()

        def rows(kind):
            return list(csv.DictReader(next(tmp_path.glob(f"*_{kind}.csv")).open(encoding="utf-8")))

        return SimpleNamespace(db=db, run=run, rows=rows, imports=imports)

    def test_a_dry_run_links_a_stateless_team_to_its_stored_twin_and_holds_the_rest(self, run_main):
        assert run_main.run() == 0
        report = {r["heartland_team_id"]: r for r in run_main.rows("teams")}
        assert (report["2026fall-7210"]["outcome"], report["2026fall-7210"]["team_id_master"]) == (
            "linked_existing",
            "stored-vardar",
        )
        assert report["2026fall-7211"]["outcome"] == "held"
        # A Sporting Blue Valley team takes the registry's Kansas and would be created.
        assert (report["2026fall-7213"]["outcome"], report["2026fall-7213"]["state_code"]) == ("created", "KS")
        schedule_ids = {r["schedule_id"] for r in run_main.rows("games")}
        assert "heartland-2026fall-792" in schedule_ids  # SBV 7213 v FC Vardar 7210
        assert "heartland-2026fall-508" not in schedule_ids  # Toca Fusion 7219 v KC Surf 7211, both held
        assert run_main.db.writes("teams") == []
        assert run_main.db.writes("team_alias_map") == []
        assert run_main.imports == []

    def test_execute_links_and_creates_but_never_creates_a_held_team(self, run_main):
        assert run_main.run("--execute") == 0
        created = {team["team_name"]: team for team in run_main.db.writes("teams")}
        assert "KC Surf Pre ECNL Blue U12B" not in created
        assert "FC Vardar U12 B Red" not in created
        assert created["Sporting BV Pre-MLS Next NV 14/15"]["state_code"] == "KS"
        aliases = {a["provider_team_id"]: a["team_id_master"] for a in run_main.db.writes("team_alias_map")}
        assert aliases["2026fall-7210"] == "stored-vardar"
        assert "2026fall-7211" not in aliases
        assert len(run_main.imports) == 1
