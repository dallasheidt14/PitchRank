"""Unit tests for scripts/import_athletes2events_event.py.

The fixtures under tests/fixtures/athletes2events/ are trimmed from Crossfire's
2026 ZF Labor Day Challenge (event 130), as the site serves them, with every
``img`` ``src`` emptied: they are presigned S3 URLs carrying the host's AWS access
key id, and this repo is public.
"""

import csv
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from scripts import import_athletes2events_event as a2e

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "athletes2events"
HOST = "crossfire.athletes2events.com"
SEASON = 2026


def _fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _event(host=HOST):
    return a2e.parse_event(_fixture("details.html"), host, 130)


def _division(flight_id, groups="groups.html"):
    divisions, _ = a2e.parse_divisions(_fixture(groups), SEASON)
    return next(d for d in divisions if d.flight_id == flight_id)


class _PageFetcher:
    """Stands in for the network; every page of the run comes from a fixture."""

    NO_GAMES = "<html><body><div id='main'></div></body></html>"

    def __init__(self, groups="groups_one_division.html"):
        self.urls = []
        self.groups = groups

    def __call__(self, url):
        self.urls.append(url)
        if url.endswith("/details"):
            return _fixture("details.html")
        if url.endswith("/groups"):
            return _fixture(self.groups)
        key, _, value = url.rpartition("=")
        name = f"flight_{value}.html" if "flight-id" in key else f"team_{value}.html"
        path = FIXTURES / name
        return path.read_text(encoding="utf-8") if path.exists() else self.NO_GAMES


class TestParseEventUrl:
    def test_a_valid_url_yields_its_host_and_event_id(self):
        assert a2e.parse_event_url("https://crossfire.athletes2events.com/events/130") == (HOST, 130)

    def test_another_host_subdomain_is_accepted(self):
        assert a2e.parse_event_url("https://somsports.athletes2events.com/events/4471") == (
            "somsports.athletes2events.com",
            4471,
        )

    def test_a_trailing_slash_is_accepted(self):
        assert a2e.parse_event_url("https://crossfire.athletes2events.com/events/130/") == (HOST, 130)

    @pytest.mark.parametrize(
        "url",
        [
            "https://crossfire.athletes2events.com/events/",
            "https://crossfire.athletes2events.com/events/abc",
            "https://athletes2events.com/events/130",
            "https://crossfire.example.com/events/130",
            "https://crossfire.athletes2events.com.evil.test/events/130",
            "http://crossfire.athletes2events.com/events/130",
            "",
        ],
    )
    def test_anything_else_is_refused(self, url):
        with pytest.raises(ValueError):
            a2e.parse_event_url(url)


class TestParseEvent:
    def test_the_details_page_dates_the_event(self):
        event = _event()

        assert (event.start, event.end) == (date(2026, 9, 5), date(2026, 9, 7))
        assert event.name == "2026 ZF Labor Day Challenge"

    def test_the_season_comes_from_the_start_date_not_the_wall_clock(self):
        assert _event().season == 2026

    def test_a_page_without_dates_is_a_fetch_error(self):
        with pytest.raises(a2e.ScrapeFetchError):
            a2e.parse_event("<html><body><main>nothing here</main></body></html>", HOST, 130)


class TestDivisionBirthYear:
    @pytest.mark.parametrize(
        "cutoff_year, division_age, expected",
        [(2007, 19, 2008), (2009, 17, 2010), (2016, 10, 2017), (2017, 9, 2018)],
    )
    def test_the_cutoff_yields_the_bands_younger_year(self, cutoff_year, division_age, expected):
        assert a2e.division_birth_year(date(cutoff_year, 8, 1), division_age, SEASON) == expected

    def test_a_cutoff_that_is_not_august_first_is_refused(self):
        assert a2e.division_birth_year(date(2016, 1, 1), 10, SEASON) is None

    def test_a_label_that_disagrees_with_its_cutoff_is_refused(self):
        assert a2e.division_birth_year(date(2016, 8, 1), 12, SEASON) is None

    def test_the_same_division_read_against_another_season_disagrees_with_its_label(self):
        assert a2e.division_birth_year(date(2016, 8, 1), 10, SEASON + 1) is None


class TestParseDivisions:
    def test_every_flight_of_every_division_is_read(self):
        divisions, skipped = a2e.parse_divisions(_fixture("groups.html"), SEASON)

        assert (len(divisions), skipped) == (34, [])
        assert len({d.division_name for d in divisions}) == 17

    def test_a_flight_carries_its_divisions_gender_age_and_birth_year(self):
        division = _division(2013)

        assert (division.division_name, division.flight_name) == ("Boys-U10", "Gold")
        assert (division.gender, division.division_age, division.birth_year) == ("Male", 10, 2017)

    def test_a_division_whose_cutoff_disagrees_with_its_label_is_skipped(self):
        """A detector asserted only by ``skipped == []`` passes once it stops detecting."""
        divisions, skipped = a2e.parse_divisions(_fixture("groups_bad_cutoff.html"), SEASON)

        assert divisions == []
        assert skipped == ["Boys-U10: cutoff Aug 01, 2015 does not agree with the label"]

    def test_a_flight_table_with_no_rows_skips_its_division_rather_than_aborting(self):
        html = (
            "<html><body><table><caption>Boys-U12 (Born on or after: Aug 01, 2014)</caption>"
            '<a href="/events/130/schedules?flight-id=77">Flight A</a></table></body></html>'
        )

        divisions, skipped = a2e.parse_divisions(html, SEASON)

        assert divisions == []
        assert skipped == ["a flight table carries no rows"]

    def test_a_girls_division_is_female(self):
        divisions, _ = a2e.parse_divisions(_fixture("groups.html"), SEASON)

        assert {d.gender for d in divisions if d.division_name.startswith("Girls")} == {"Female"}


class TestParseFlightGames:
    def _games(self, flight_id):
        return a2e.parse_flight_games(_fixture(f"flight_{flight_id}.html"), _division(flight_id), "u")

    def test_a_scored_game_carries_both_team_ids_and_its_date(self):
        games, problems = self._games(2029)

        assert problems == []
        first = next(g for g in games if g.game_no == "#377")
        assert (first.home_id, first.home_score, first.away_score, first.away_id) == ("3259", 7, 0, "7072")
        assert first.game_date == date(2026, 9, 5)

    def test_a_shootout_is_recorded_at_its_regulation_score(self):
        [game], problems = self._games(2015)

        assert (game.home_score, game.away_score) == (0, 0)
        assert a2e._compute_result(game.home_score, game.away_score) == "D"
        assert problems == []

    def test_an_unfilled_bracket_slot_is_reported_and_held(self):
        games, problems = self._games(2013)

        assert len(problems) == 2
        assert all("unfilled bracket slot" in p for p in problems)
        assert "Team-2" not in {g.home_id for g in games} | {g.away_id for g in games}

    def test_the_standings_table_is_not_read_as_games(self):
        games, _ = self._games(2013)

        assert len(games) == 4


class TestParseTeamPage:
    @pytest.mark.parametrize(
        "team_id, header, coach",
        [
            ("10056", "Boys-U12 NSC EBU12, Oviedo (WA)", "Person 1"),
            ("10186", "Girls-U12 XF U11 G15-16 RCL1 (WA)", "Person 3"),
            ("9793", "Boys-U9 XF U9 B17-18 RCL 3", "Person 24"),
        ],
    )
    def test_the_header_and_coach_are_read(self, team_id, header, coach):
        assert a2e.parse_team_page(_fixture(f"team_{team_id}.html")) == (header, coach)

    def test_a_non_ascii_name_survives(self):
        header, _ = a2e.parse_team_page(_fixture("team_11525.html"))

        assert header == "Boys-U10 Nido Águila Tri Cities BU9 (WA)"

    def test_an_unreadable_page_yields_nothing_rather_than_raising(self):
        assert a2e.parse_team_page("<html><body><main>nothing</main></body></html>") == ("", "")


class TestAgeFromName:
    """The age comes from the team's own name; the division is only an upper bound."""

    U10 = 2017  # the Boys-U10 division's birth year in the 2026 season

    @pytest.mark.parametrize(
        "name, expected",
        [
            ("XF U10 RCL 2", 2017),
            ("Crossfire Select B-U10 A Matisz", 2017),
            ("XF B16-17 RCL 4", 2017),
            ("XF B17-18 RCL 1", 2018),
            ("Nido Águila Tri Cities BU9", 2018),
        ],
    )
    def test_a_stated_age_or_band_is_read_from_the_name(self, name, expected):
        assert a2e.age_from_name(name, self.U10, SEASON)[0] == expected

    def test_a_band_is_read_from_its_younger_year_whichever_way_it_is_written(self):
        for name in ("XF B17-18", "XF B18/17", "XF B2017-2018", "XF 17/18"):
            assert a2e.age_from_name(name, self.U10, SEASON)[0] == 2018

    def test_no_age_in_the_name_falls_back_to_the_division(self):
        birth_year, how = a2e.age_from_name("Arctic Wolves", self.U10, SEASON)

        assert (birth_year, how) == (self.U10, "no age in name, tournament division used")

    def test_an_odd_year_span_falls_back_to_the_division(self):
        birth_year, how = a2e.age_from_name("G2018-2016 Team", self.U10, SEASON)

        assert (birth_year, how) == (self.U10, "odd year span, tournament division used")

    @pytest.mark.parametrize("name", ["Missoula Surf U12/13 Boys", "U11/U12 Nido Aguila Zaldivar"])
    def test_two_u_ages_leave_the_team_out(self, name):
        birth_year, how = a2e.age_from_name(name, 2015, SEASON)

        assert (birth_year, how) == (None, "two U-ages, left out")

    def test_a_name_older_than_its_division_is_left_out(self):
        """A team plays up, never down, so a name naming an older band cannot be read."""
        birth_year, how = a2e.age_from_name("XF U12 Red", self.U10, SEASON)

        assert birth_year is None
        assert "older than its" in how

    def test_a_single_birth_year_takes_the_reading_the_division_allows(self):
        # 2015 is the younger year of u12 (2015/2014) and the older year of u11 (2016/2015).
        # A U11 division admits only the u11 reading.
        birth_year, how = a2e.age_from_name("XF B15 Red", 2016, SEASON)

        assert birth_year == 2016
        assert "one reading fits the division" in how

    def test_a_single_birth_year_its_division_cannot_settle_is_left_out(self):
        """A U12 division admits both readings of "B15", so neither is chosen."""
        birth_year, how = a2e.age_from_name("XF B15 Red", 2015, SEASON)

        assert birth_year is None
        assert "could be" in how

    def test_a_b12_tag_too_old_for_its_division_is_read_as_an_age(self):
        birth_year, how = a2e.age_from_name("XF B12 Red", 2015, SEASON)

        assert (birth_year, how) == (2015, "B12 read as U12")

    def test_labels_are_read_against_the_events_season_not_another(self):
        """The same U10 label names a different birth year one season later."""
        assert a2e.age_from_name("XF U10 RCL 2", self.U10, SEASON + 1)[0] == 2018


class TestBoardCohort:
    @pytest.mark.parametrize("birth_year, expected", [(2017, "u10"), (2014, "u13"), (2008, "u19"), (2009, "u19")])
    def test_a_birth_year_is_filed_on_the_board_it_sits_on_now(self, birth_year, expected):
        assert a2e.board_cohort(birth_year, SEASON) == expected

    @pytest.mark.parametrize("birth_year", [2018, 2019, 2007])
    def test_a_cohort_on_no_board_is_refused(self, birth_year):
        assert a2e.board_cohort(birth_year, SEASON) is None

    def test_the_board_moves_with_its_season(self):
        assert (a2e.board_cohort(2017, SEASON), a2e.board_cohort(2017, SEASON + 1)) == ("u10", "u11")


class TestSplitClub:
    @pytest.mark.parametrize(
        "name, club",
        [
            ("XF U10 RCL 2", "Crossfire Premier"),
            ("Crossfire U10 RCL 2", "Crossfire Premier"),
            ("Crossfire Premier B13", "Crossfire Premier"),
            ("Crossfire Select B-U10 A Matisz", "Crossfire Select Soccer Club"),
        ],
    )
    def test_the_hosts_own_club_names_are_resolved(self, name, club):
        assert a2e.split_club(name, HOST)[0] == club

    @pytest.mark.parametrize(
        "name, club",
        [
            ("Leon FC U10 premier", "Leon FC"),
            ("Arctic Wolves", "Arctic Wolves"),
            ("NSC EBU12, Oviedo", "NSC"),
            ("Nido Águila Tri Cities BU9", "Nido Águila Tri Cities"),
            ("LWPFC White Arapaimas B12/13", "LWPFC White Arapaimas"),
        ],
    )
    def test_the_club_is_the_words_before_the_first_age_tag_or_comma(self, name, club):
        assert a2e.split_club(name, HOST)[0] == club

    def test_another_host_does_not_get_this_hosts_club_table(self):
        assert a2e.split_club("XF U10 RCL 2", "somsports.athletes2events.com")[0] == "XF"


# Distinct per side, so a row builder that reads the home team where it should read
# the opponent is visible in every dimension it varies. birth_year is deliberately
# NOT varied: a board fixes it (u10 is the 2017 band in 2026), so two same-board
# teams cannot differ there and the field carries no information about the swap.
_SIDE_FIELDS = {
    "1": ("Crossfire Premier", "WA"),
    "2": ("Eastside FC", "OR"),
}


def _team_row(a2e_team_id, age_group="u10", gender="Male", name=None, birth_year=2017):
    club, state_code = _SIDE_FIELDS.get(a2e_team_id, (f"Club {a2e_team_id}", "MT"))
    return a2e.TeamRow(
        a2e_team_id=a2e_team_id,
        team_name=name or f"Team {a2e_team_id}",
        club_name=club,
        club_as_written=club,
        division_name="Boys-U10 Gold",
        division_age=10,
        birth_year=birth_year,
        age_group=age_group,
        age_source="name",
        gender=gender,
        state_code=state_code,
        coach=f"Coach {a2e_team_id}",
    )


def _game(home_id, away_id, home_score=2, away_score=1):
    return a2e.EventGame(
        flight_id=2013,
        division_name="Boys-U10 Gold",
        group="A",
        game_no="#035",
        game_date=date(2026, 9, 5),
        game_time="09:05 AM",
        venue="60 Acres",
        home_id=home_id,
        home_score=home_score,
        away_id=away_id,
        away_score=away_score,
        source_url="u",
    )


def _linked(*ids):
    return {i: a2e.Outcome("created", f"master-{i}", 1.0) for i in ids}


class TestBuildCsvRows:
    def test_a_settled_game_becomes_two_importer_rows(self):
        roster = [_team_row("1"), _team_row("2")]

        records, held, cross_age = a2e.build_csv_rows([_game("1", "2")], roster, _linked("1", "2"), _event())

        assert (len(records), held, cross_age) == (2, [], [])
        assert [r["home_away"] for r in records] == ["H", "A"]
        assert [r["result"] for r in records] == ["W", "L"]
        assert [(r["team_id"], r["opponent_id"]) for r in records] == [("1", "2"), ("2", "1")]
        assert [(r["team_name"], r["opponent_name"]) for r in records] == [
            ("Team 1", "Team 2"),
            ("Team 2", "Team 1"),
        ]
        assert [(r["club_name"], r["opponent_club_name"]) for r in records] == [
            ("Crossfire Premier", "Eastside FC"),
            ("Eastside FC", "Crossfire Premier"),
        ]
        assert [(r["state_code"], r["state"]) for r in records] == [("WA", "Washington"), ("OR", "Oregon")]

    def test_a_level_score_is_a_draw_for_both_sides(self):
        roster = [_team_row("1"), _team_row("2")]

        records, _, _ = a2e.build_csv_rows([_game("1", "2", 0, 0)], roster, _linked("1", "2"), _event())

        assert [r["result"] for r in records] == ["D", "D"]

    def test_a_game_whose_team_is_unsettled_is_held(self):
        roster = [_team_row("1"), _team_row("2")]
        outcomes = {**_linked("1"), "2": a2e.Outcome("review")}

        records, held, cross_age = a2e.build_csv_rows([_game("1", "2")], roster, outcomes, _event())

        assert (records, cross_age) == ([], [])
        assert len(held) == 1

    def test_a_team_playing_up_is_imported_and_recorded(self):
        """A U10 beating a U11 is the result worth most; each side resolves by its own alias."""
        roster = [_team_row("1", age_group="u10"), _team_row("2", age_group="u11")]

        records, held, cross_age = a2e.build_csv_rows([_game("1", "2")], roster, _linked("1", "2"), _event())

        assert len(records) == 2
        assert held == []
        assert [(c["home_age_group"], c["away_age_group"]) for c in cross_age] == [("u10", "u11")]
        assert [(c["home_team_id"], c["away_team_id"]) for c in cross_age] == [("1", "2")]

    def test_two_teams_of_different_genders_are_imported_and_recorded(self):
        """The second conjunct of the same record, violated on its own."""
        roster = [_team_row("1", gender="Male"), _team_row("2", gender="Female")]

        records, held, cross_age = a2e.build_csv_rows([_game("1", "2")], roster, _linked("1", "2"), _event())

        assert len(records) == 2
        assert [(c["home_gender"], c["away_gender"]) for c in cross_age] == [("Male", "Female")]

    def test_a_same_board_game_is_not_recorded_as_cross_age(self):
        roster = [_team_row("1"), _team_row("2")]

        _, _, cross_age = a2e.build_csv_rows([_game("1", "2")], roster, _linked("1", "2"), _event())

        assert cross_age == []

    def test_every_required_column_is_written(self):
        roster = [_team_row("1"), _team_row("2")]

        records, _, _ = a2e.build_csv_rows([_game("1", "2")], roster, _linked("1", "2"), _event())

        assert set(records[0]) == set(a2e.REQUIRED_COLUMNS)


class TestOffBoardLinks:
    def test_a_link_whose_stored_board_differs_is_refused(self):
        roster = [_team_row("1", age_group="u10")]
        teams = {"master-1": {"team_id_master": "master-1", "age_group": "u11", "gender": "Male"}}

        refused = a2e.off_board_links(roster, {"1": a2e.Outcome("linked_existing", "master-1")}, teams)

        assert "u11" in refused["1"]

    def test_a_link_whose_stored_gender_differs_is_refused(self):
        roster = [_team_row("1", gender="Male")]
        teams = {"master-1": {"team_id_master": "master-1", "age_group": "u10", "gender": "Female"}}

        refused = a2e.off_board_links(roster, {"1": a2e.Outcome("linked_existing", "master-1")}, teams)

        assert "Female" in refused["1"]

    def test_a_link_that_agrees_is_kept(self):
        roster = [_team_row("1")]
        teams = {"master-1": {"team_id_master": "master-1", "age_group": "u10", "gender": "Male"}}

        assert a2e.off_board_links(roster, {"1": a2e.Outcome("linked_existing", "master-1")}, teams) == {}


class TestSharedLinks:
    def test_two_teams_of_one_event_on_one_pitchrank_team_conflict(self):
        outcomes = {
            "1": a2e.Outcome("linked_existing", "master-x"),
            "2": a2e.Outcome("linked_existing", "master-x"),
            "3": a2e.Outcome("linked_existing", "master-y"),
        }

        conflicts = a2e.shared_links(outcomes)

        assert set(conflicts) == {"1", "2"}

    def test_an_already_approved_link_keeps_its_team(self):
        outcomes = {
            "1": a2e.Outcome("already_linked", "master-x"),
            "2": a2e.Outcome("linked_existing", "master-x"),
        }

        assert set(a2e.shared_links(outcomes)) == {"2"}


class TestBuildRoster:
    def _roster(self):
        fetcher = _PageFetcher()
        event, in_scope, skipped, games, problems = a2e.collect_event(
            fetcher, HOST, 130, SEASON, 3650, date(2026, 9, 30)
        )
        return in_scope, skipped, games, problems

    def test_a_team_is_filed_by_its_own_name_not_its_division(self):
        in_scope, skipped, _, _ = self._roster()
        by_id = {r.a2e_team_id: r for r in in_scope + skipped}

        assert by_id["5587"].age_group == "u10"
        assert by_id["11532"].age_group is None

    def test_a_team_playing_up_off_the_boards_is_left_out(self):
        """A U9-named team entered in the U10 division is filed U9, which is off the boards."""
        _, skipped, _, _ = self._roster()

        assert "11532" in {r.a2e_team_id for r in skipped}
        assert "no U10-U19 board" in next(r for r in skipped if r.a2e_team_id == "11532").skip_reason

    def test_the_hosts_club_table_is_applied_to_the_roster(self):
        in_scope, skipped, _, _ = self._roster()
        by_id = {r.a2e_team_id: r for r in in_scope + skipped}

        assert by_id["6195"].club_name == "Crossfire Select Soccer Club"
        assert by_id["5587"].club_name == "Crossfire Premier"

    def test_the_state_comes_from_the_team_page(self):
        in_scope, _, _, _ = self._roster()
        by_id = {r.a2e_team_id: r for r in in_scope}

        assert by_id["10785"].state_code == "OR"
        assert by_id["5587"].state_code == "WA"

    def test_games_outside_the_window_are_dropped(self):
        fetcher = _PageFetcher()
        _, _, _, games, _ = a2e.collect_event(fetcher, HOST, 130, SEASON, 1, date(2026, 9, 30))

        assert games == []


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
        a2e_team_id = kwargs["provider_team_id"]
        self.matched.append(a2e_team_id)
        created = {"matched": True, "team_id": f"new-{a2e_team_id}", "method": "direct_id", "created": True}
        return _FakeMatcher.results.get(a2e_team_id, {**created, "confidence": 1.0})


class _ProvidersClient:
    def table(self, _name):
        return self

    def select(self, *_a):
        return self

    def eq(self, *_a):
        return self

    def execute(self):
        return SimpleNamespace(data=[{"id": "a2e-provider"}])


class _FixedDate(date):
    @classmethod
    def today(cls):
        return date(2026, 9, 30)


@pytest.fixture
def run_main(monkeypatch, tmp_path):
    def run(*flags, saved=None, queued=None, teams=None, board_season=SEASON):
        _FakeMatcher.instances = []
        imports = []
        alias_calls = []

        def fake_existing_aliases(_client, _provider_id, a2e_team_ids):
            alias_calls.append(list(a2e_team_ids))
            if len(alias_calls) == 1:
                return {}
            return saved if saved is not None else {i: f"new-{i}" for i in a2e_team_ids}

        fetcher = _PageFetcher()
        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
        monkeypatch.setattr(a2e, "create_client", lambda *_a: _ProvidersClient())
        monkeypatch.setattr(a2e, "make_session", lambda: None)
        monkeypatch.setattr(a2e, "_get", lambda _s, url: SimpleNamespace(text=fetcher(url)))
        monkeypatch.setattr(a2e, "Athletes2EventsGameMatcher", _FakeMatcher)
        monkeypatch.setattr(a2e, "existing_aliases", fake_existing_aliases)
        monkeypatch.setattr(a2e, "pending_reviews", lambda _c, ids: set(ids) if queued is None else queued)
        monkeypatch.setattr(a2e, "teams_by_id", lambda _c, ids: {i: t for i, t in (teams or {}).items() if i in ids})
        # Honours its argument: asked for the wall clock (no date) it answers the
        # board season, asked about the event's start date it answers the real one.
        # A driver that passed the wall clock where it owes the event date fails here.
        real_season = a2e._soccer_season_year
        monkeypatch.setattr(
            a2e, "_soccer_season_year", lambda now=None: board_season if now is None else real_season(now)
        )
        monkeypatch.setattr(a2e, "date", _FixedDate)
        monkeypatch.setattr(
            a2e.subprocess, "run", lambda cmd, check: imports.append(cmd) or SimpleNamespace(returncode=0)
        )
        argv = [
            "import_athletes2events_event.py",
            "--event-url",
            f"https://{HOST}/events/130",
            "--output-dir",
            str(tmp_path),
            "--days-back",
            "3650",
            "--delay-min",
            "0",
            "--delay-max",
            "0",
        ]
        monkeypatch.setattr(a2e.sys, "argv", [*argv, *flags])

        code = a2e.main()
        if code != 0:
            return SimpleNamespace(code=code, imports=imports, outcomes={}, games=[], cross_age=[], alias_calls=[])
        [report] = tmp_path.glob("*_teams.csv")
        [games_csv] = tmp_path.glob("*_games.csv")
        [cross_age_csv] = tmp_path.glob("*_cross_age.csv")
        return SimpleNamespace(
            code=code,
            imports=imports,
            outcomes={r["a2e_team_id"]: r for r in csv.DictReader(report.open(encoding="utf-8"))},
            games=list(csv.DictReader(games_csv.open(encoding="utf-8"))),
            cross_age=list(csv.DictReader(cross_age_csv.open(encoding="utf-8"))),
            alias_calls=alias_calls,
        )

    return run


class TestMain:
    def test_a_dry_run_builds_only_dry_run_matchers_and_starts_no_import(self, run_main):
        result = run_main()

        assert result.code == 0
        assert result.imports == []
        assert [(m.dry_run, m.registration_mode) for m in _FakeMatcher.instances] == [(True, True)]
        assert len(result.alias_calls) == 1

    def test_execute_imports_the_games_csv(self, run_main):
        result = run_main("--execute")

        assert [(m.dry_run, m.registration_mode) for m in _FakeMatcher.instances] == [(True, True), (False, True)]
        [command] = result.imports
        assert command[1:2] == ["scripts/import_games_enhanced.py"]
        assert command[-1] == "athletes2events"

    def test_a_bad_event_url_stops_before_any_fetch(self, run_main):
        result = run_main("--event-url", "https://example.com/events/130")

        assert result.code == 1

    def test_every_game_written_has_two_rows_and_one_age_group(self, run_main):
        result = run_main()

        assert len(result.games) % 2 == 0
        by_game = {}
        for row in result.games:
            by_game.setdefault(row["schedule_id"], []).append(row)
        assert all(len(rows) == 2 for rows in by_game.values())
        assert all(len({r["age_group"] for r in rows}) == 1 for rows in by_game.values())

    def test_teams_left_out_are_reported_with_a_reason(self, run_main):
        result = run_main()

        assert result.outcomes["11532"]["outcome"] == "skipped"
        assert result.outcomes["11532"]["reason"]

    def test_no_game_of_a_left_out_team_reaches_the_games_csv(self, run_main):
        result = run_main()

        written = {r["team_id"] for r in result.games} | {r["opponent_id"] for r in result.games}
        assert "11532" not in written


class TestUnsavedLinks:
    def test_a_missing_or_misdirected_alias_is_reported(self):
        outcomes = {
            "a": a2e.Outcome("linked_existing", "T1"),
            "b": a2e.Outcome("created", "T2"),
            "c": a2e.Outcome("created", "T3"),
            "d": a2e.Outcome("review"),
            "e": a2e.Outcome("relinked", "T4"),
            "f": a2e.Outcome("already_linked", "T5"),
        }

        assert a2e.unsaved_links(outcomes, {"a": "T1", "b": "T9"}) == {
            "b": "link was not saved",
            "c": "link was not saved",
            "e": "link was not saved",
        }


class TestUnsavedReviews:
    def test_only_a_review_outcome_with_no_pending_row_is_reported(self):
        outcomes = {
            "a": a2e.Outcome("review", confidence=0.8),
            "b": a2e.Outcome("review", confidence=0.8),
            "c": a2e.Outcome("created", "T1"),
        }

        assert a2e.unsaved_reviews(outcomes, {"a"}) == {"b": "review item was not saved"}


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
        rows = [_team_row(str(i)) for i in range(7)]
        direct = {"matched": True, "method": "direct_id", "confidence": 1.0}
        matcher = _FakeMatcherForRegister(
            {
                "1": {**direct, "team_id": "t1", "created": True},
                "2": {"matched": True, "team_id": "t2", "method": "fuzzy_auto", "confidence": 0.95, "created": False},
                "3": {"matched": False, "team_id": None, "method": "fuzzy_review", "confidence": 0.8, "review": True},
                "4": RuntimeError("boom"),
                "5": {**direct, "team_id": "t5", "created": False},
                "6": {**direct, "team_id": "t6", "created": False, "relinked": True},
            }
        )

        outcomes = a2e.register_teams(matcher, "provider", rows, {"0": "t0"})

        assert {k: (o.status, o.team_id_master) for k, o in outcomes.items()} == {
            "0": ("already_linked", "t0"),
            "1": ("created", "t1"),
            "2": ("linked_existing", "t2"),
            "3": ("review", None),
            "4": ("error", None),
            "5": ("already_linked", "t5"),
            "6": ("relinked", "t6"),
        }
        assert matcher.calls == ["1", "2", "3", "4", "5", "6"]

    def test_the_club_as_the_page_wrote_it_reaches_the_matcher(self):
        """The squad gates need it: the stored spelling cannot strip Select from a name."""
        row = _team_row("1")
        row.club_name, row.club_as_written = "Crossfire Select Soccer Club", "Crossfire Select"
        captured = {}

        class _Recorder:
            def _match_team(self, **kwargs):
                captured.update(kwargs)
                return {"matched": True, "team_id": "t1", "method": "direct_id", "confidence": 1.0, "created": True}

        a2e.register_teams(_Recorder(), "provider", [row], {})

        assert captured["club_name"] == "Crossfire Select Soccer Club"
        assert captured["written_club"] == "Crossfire Select"


class _Response:
    """A requests response: bytes decoded with the declared charset, ISO-8859-1 for a bare text type."""

    def __init__(self, status_code, body=b"<html></html>", content_type="text/html; charset=utf-8"):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.content = body
        declared = re.search(r"charset=([\w-]+)", content_type)
        self.encoding = declared.group(1) if declared else ("ISO-8859-1" if content_type.startswith("text/") else None)

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


class TestFetch:
    def test_a_page_with_no_declared_charset_is_read_as_utf8(self):
        """The site serves UTF-8; requests defaults a bare text/html to ISO-8859-1."""
        response = a2e._get(_Session(_Response(200, "Nido Águila".encode("utf-8"), "text/html")), "u")

        assert response.text == "Nido Águila"

    def test_a_declared_charset_is_left_alone(self):
        response = a2e._get(_Session(_Response(200, "Nido Águila".encode("utf-8"))), "u")

        assert response.text == "Nido Águila"

    def test_a_non_200_raises(self):
        with pytest.raises(a2e.ScrapeFetchError):
            a2e._get(_Session(_Response(500)), "u")

    def test_a_transport_error_raises(self):
        with pytest.raises(a2e.ScrapeFetchError):
            a2e._get(_Session(requests.ConnectionError("reset")), "u")

    def test_every_request_carries_a_timeout(self):
        session = _Session(_Response(200))

        a2e._get(session, "https://crossfire.athletes2events.com/events/130/groups")

        assert session.calls == [("https://crossfire.athletes2events.com/events/130/groups", 90)]


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
            {"provider_id": "a2e", "provider_team_id": "1", "team_id_master": "a", "review_status": "approved"},
            {"provider_id": "gotsport", "provider_team_id": "2", "team_id_master": "b", "review_status": "approved"},
            {"provider_id": "a2e", "provider_team_id": "3", "team_id_master": "c", "review_status": "pending"},
        ]

        assert a2e.existing_aliases(_client("team_alias_map", rows), "a2e", ["1", "2", "3"]) == {"1": "a"}

    def test_ids_are_read_in_batches_of_a_hundred(self):
        executed = []
        rows = [
            {"provider_id": "a2e", "provider_team_id": str(i), "team_id_master": f"T{i}", "review_status": "approved"}
            for i in range(150)
        ]

        found = a2e.existing_aliases(_client("team_alias_map", rows, executed), "a2e", [str(i) for i in range(150)])

        assert executed == [100, 50]
        assert len(found) == 150


class TestPendingReviews:
    def test_only_this_providers_pending_rows_count(self):
        rows = [
            {"provider_id": "athletes2events", "provider_team_id": "1", "status": "pending"},
            {"provider_id": "gotsport", "provider_team_id": "2", "status": "pending"},
            {"provider_id": "athletes2events", "provider_team_id": "3", "status": "rejected"},
        ]

        assert a2e.pending_reviews(_client("team_match_review_queue", rows), ["1", "2", "3"]) == {"1"}


class TestTeamsById:
    def test_every_batch_is_kept_with_the_fields_the_board_check_reads(self):
        executed = []
        fields = {"age_group": "u10", "gender": "Male"}
        rows = [{"team_id_master": f"T{i}", "team_name": f"Team {i}", **fields} for i in range(150)]

        teams = a2e.teams_by_id(_client("teams", rows, executed), [f"T{i}" for i in range(150)])

        assert executed == [100, 50]
        assert len(teams) == 150
        assert teams["T0"] == {"team_id_master": "T0", "team_name": "Team 0", **fields}


class TestMainWriteVerification:
    """``--execute`` re-reads what the matcher reported writing; the matcher swallows its own failures."""

    LINKED = {"matched": True, "team_id": "T1", "method": "fuzzy_auto", "confidence": 0.95, "created": False}

    def test_a_link_the_alias_table_does_not_confirm_is_an_error(self, run_main):
        result = run_main("--execute", saved={})

        assert {o["outcome"] for o in result.outcomes.values() if o["outcome"] != "skipped"} == {"error"}
        assert all(o["reason"] == "link was not saved" for o in result.outcomes.values() if o["outcome"] == "error")
        assert result.games == []

    def test_a_review_with_no_pending_row_is_an_error(self, run_main):
        review = {"matched": False, "team_id": None, "method": "fuzzy_review", "confidence": 0.8, "review": True}
        _FakeMatcher.results = {"5587": review}
        try:
            result = run_main("--execute", queued=set())
        finally:
            _FakeMatcher.results = {}

        assert result.outcomes["5587"]["outcome"] == "error"
        assert result.outcomes["5587"]["reason"] == "review item was not saved"

    def test_two_teams_linking_to_one_pitchrank_team_conflict_and_are_never_written(self, run_main):
        _FakeMatcher.results = {seg_id: dict(self.LINKED) for seg_id in ("6195", "5587")}
        try:
            result = run_main("--execute")
        finally:
            _FakeMatcher.results = {}

        assert {result.outcomes[i]["outcome"] for i in ("6195", "5587")} == {"conflict"}
        writer = _FakeMatcher.instances[1]
        assert "6195" not in writer.matched and "5587" not in writer.matched

    def test_a_linked_team_stored_on_another_board_is_an_error_and_its_games_are_held(self, run_main):
        _FakeMatcher.results = {"6195": dict(self.LINKED)}
        teams = {"T1": {"team_id_master": "T1", "team_name": "Other", "age_group": "u14", "gender": "Male"}}
        try:
            result = run_main("--execute", saved={"6195": "T1"}, teams=teams)
        finally:
            _FakeMatcher.results = {}

        assert result.outcomes["6195"]["outcome"] == "error"
        assert "u14" in result.outcomes["6195"]["reason"]
        written = {r["team_id"] for r in result.games} | {r["opponent_id"] for r in result.games}
        assert "6195" not in written


class TestMainSeasons:
    def test_labels_are_read_against_the_event_and_boards_against_the_wall_clock(self, run_main):
        """Swapping the two seasons would file this 2026 event's teams a year out."""
        result = run_main(board_season=SEASON + 1)

        by_id = result.outcomes
        # "XF U10 RCL 2" is a 2017 band: U10 in the event's season, U11 a season later.
        assert by_id["5587"]["age_group"] == "u11"
        assert by_id["5587"]["age_source"] == "name"
        # The division's own label still validates against the event's season, so the
        # roster is unchanged in size -- only the board each team lands on moves.
        assert by_id["6195"]["age_group"] == "u11"
