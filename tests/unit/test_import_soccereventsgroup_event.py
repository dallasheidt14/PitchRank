"""Unit tests for scripts/import_soccereventsgroup_event.py.

The fixtures under tests/fixtures/soccereventsgroup/ are trimmed from the live 2026
Chicago Cup (ProgramID 19206): the two feeds cut to a few divisions, and two bracket
panels captured as SEG serves them.
"""

import csv
import json
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from scripts import import_soccereventsgroup_event as seg

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "soccereventsgroup"
SEASON = 2026


def _program():
    raw = json.loads((FIXTURES / "program.json").read_text(encoding="utf-8"))
    return {**raw["program"], "divisions": raw["divisions"]}


def _team_list():
    return json.loads((FIXTURES / "team_list.json").read_text(encoding="utf-8"))


def _division(session_name):
    return next(d for d in _program()["divisions"] if d["sessionName"] == session_name)


def _roster():
    return seg.build_roster(_program(), _team_list(), SEASON)


BRACKET_PAGES = {
    "575271": (FIXTURES / "bracket_u11_platinum.html").read_text(encoding="utf-8"),
    "575278": (FIXTURES / "bracket_u14_gold.html").read_text(encoding="utf-8"),
}
NO_BRACKET = "<html><body><div id='MainContent'></div></body></html>"


class _PageFetcher:
    def __init__(self):
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        return BRACKET_PAGES.get(url.rsplit("=", 1)[-1], NO_BRACKET)


class TestDivisionBirthYear:
    @pytest.mark.parametrize(
        "session_name, expected",
        [("U8", 2019), ("U10 Bronze", 2017), ("U11 Platinum", 2016), ("U14 Gold", 2013), ("U18/19 Gold", 2008)],
    )
    def test_a_single_cohort_label_yields_the_bands_younger_year(self, session_name, expected):
        assert seg.division_birth_year(_division(session_name), SEASON) == expected

    @pytest.mark.parametrize("session_name", ["U8/U9", "HS Bronze"])
    def test_mixed_and_unlabelled_divisions_have_no_birth_year(self, session_name):
        assert seg.division_birth_year(_division(session_name), SEASON) is None

    @pytest.mark.parametrize("session_name", ["U13/U14 Gold", "U13/14 Gold"])
    @pytest.mark.parametrize("cutoff", ["2012-08-01T00:00:00", "2013-08-01T00:00:00"])
    def test_a_label_naming_two_ranked_cohorts_is_skipped(self, session_name, cutoff):
        """Both cutoffs, so whichever of the two ages a guess picks agrees with one of them."""
        assert seg.division_birth_year({"sessionName": session_name, "oldestEligibleBirthdate": cutoff}, SEASON) is None

    def test_the_same_division_read_against_another_season_disagrees_with_its_label(self):
        assert seg.division_birth_year(_division("U10 Bronze"), SEASON + 1) is None

    def test_a_label_that_disagrees_with_its_cutoff_is_skipped(self):
        division = {"sessionName": "U11 Gold", "oldestEligibleBirthdate": "2016-08-01T00:00:00"}

        assert seg.division_birth_year(division, SEASON) is None

    def test_a_cutoff_not_on_august_first_is_skipped(self):
        division = {"sessionName": "U10 Gold", "oldestEligibleBirthdate": "2016-01-01T00:00:00"}

        assert seg.division_birth_year(division, SEASON) is None

    @pytest.mark.parametrize(
        "start, expected",
        [("2026-09-04T05:00:00", 2026), ("2027-03-06T00:00:00", 2026), ("2027-08-01T00:00:00", 2027)],
    )
    def test_the_season_comes_from_the_event_start(self, start, expected):
        assert seg.event_season({"start": start}) == expected


class TestBoardCohort:
    @pytest.mark.parametrize(
        "birth_year, board_season, expected",
        [
            (2017, 2026, "u10"),
            (2013, 2026, "u14"),
            (2009, 2026, "u19"),
            (2008, 2026, "u19"),
            (2016, 2027, "u12"),
            (2018, 2026, None),
            (2019, 2026, None),
        ],
    )
    def test_the_board_is_this_seasons(self, birth_year, board_season, expected):
        assert seg.board_cohort(birth_year, board_season) == expected

    def test_an_event_from_last_season_files_its_teams_on_this_seasons_board(self):
        program = {
            "start": "2026-07-24T00:00:00",
            "divisions": [{"id": 1, "sessionName": "U11 Gold", "oldestEligibleBirthdate": "2014-08-01T00:00:00"}],
        }
        team_list = {
            "programTeams": [
                {
                    "divisions": [
                        {
                            "divisionId": 1,
                            "divisionName": "Boys - U11 Gold",
                            "gender": True,
                            "teams": [{"teamId": 7, "teamName": "CFYSC 11U Boys Premier", "state": "IL"}],
                        }
                    ]
                }
            ]
        }

        [row], skipped = seg.build_roster(program, team_list, SEASON)

        assert (row.age_group, row.birth_year, skipped) == ("u12", 2015, [])


class TestNameAgeMismatch:
    @pytest.mark.parametrize(
        "name, birth_year, expected",
        [
            ("CFYSC 10U Boys Premier", 2016, "name says U10, division is U11"),
            ("Pegasus FC GU13 Red", 2013, "name says U13, division is U14"),
            ("Chicago FC United U3 GA Aspire", 2014, "name says U3, division is U13"),
            ("CFYSC 11U Boys Premier", 2016, None),
            ("Rush WI U18 Girls Rush", 2008, None),
            ("Croatian Eagles 19uG Aspire", 2008, None),
            ("FC Pride U11 Pre-ECNL 15/16", 2016, None),
            ("Carmel FC N1 2012/13 (IN)", 2013, None),
        ],
    )
    def test_a_name_age_other_than_the_divisions_needs_review(self, name, birth_year, expected):
        assert seg.name_age_mismatch(name, birth_year, SEASON) == expected

    def test_names_are_read_against_the_events_own_season(self):
        """A July 2026 event's U11 fielded 2015-born players; its "11U" names are current for it."""
        assert seg.name_age_mismatch("CFYSC 11U Boys Premier", 2015, 2025) is None

    def test_a_mismatched_team_stays_in_scope_with_its_reason(self):
        team_list = {
            "programTeams": [
                {
                    "divisions": [
                        {
                            "divisionId": 239723,
                            "divisionName": "Boys - U11 Platinum",
                            "gender": True,
                            "teams": [{"teamId": 9, "teamName": "CFYSC 10U Boys Premier", "state": "IL"}],
                        }
                    ]
                }
            ]
        }

        [row], _ = seg.build_roster(_program(), team_list, SEASON)

        assert (row.age_group, row.review_reason) == ("u11", "name says U10, division is U11")


class TestOriginState:
    @pytest.mark.parametrize(
        "team, expected",
        [
            ({"state": "IL", "origin": "Chicago, IL"}, "IL"),
            ({"state": "", "origin": "Brookfield , WI"}, "WI"),
            ({"state": None, "origin": "Toronto, ON"}, None),
            ({"state": "", "origin": ""}, None),
        ],
    )
    def test_state_is_a_us_code_or_nothing(self, team, expected):
        assert seg.parse_origin_state(team) == expected


class TestBuildRoster:
    def test_in_scope_and_skipped_counts(self):
        in_scope, skipped = _roster()

        assert len(in_scope) == 22
        assert len(skipped) == 13
        assert {row.division_name for row in skipped} == {"Boys - U8", "Girls - U8/U9", "Girls - HS Bronze"}
        assert {row.skip_reason for row in skipped} == {"division names no single U10-U19 cohort"}

    def test_rows_carry_cohort_birth_year_gender_and_state(self):
        in_scope, _ = _roster()
        by_id = {row.seg_team_id: row for row in in_scope}

        croatian = by_id["581312"]
        assert (croatian.age_group, croatian.birth_year, croatian.gender, croatian.state_code) == (
            "u14",
            2013,
            "Female",
            "WI",
        )
        assert (by_id["580345"].age_group, by_id["580345"].gender, by_id["580345"].state_code) == (
            "u11",
            "Male",
            "MO",
        )
        assert by_id["577905"].age_group == "u19"

    def test_a_trailing_nbsp_is_collapsed_and_a_foreign_team_is_skipped(self):
        team_list = {
            "programTeams": [
                {
                    "divisions": [
                        {
                            "divisionId": 239717,
                            "divisionName": "Boys - U10 Bronze",
                            "gender": True,
                            "teams": [
                                {"teamId": 1, "teamName": "Indy Premier Inspire U11 \xa0", "origin": "Carmel, IN"},
                                {"teamId": 2, "teamName": "Toronto FC U10", "origin": "Toronto, ON", "state": ""},
                            ],
                        }
                    ]
                }
            ]
        }
        in_scope, skipped = seg.build_roster(_program(), team_list, SEASON)

        assert [row.team_name for row in in_scope] == ["Indy Premier Inspire U11"]
        assert [(row.seg_team_id, row.skip_reason) for row in skipped] == [("2", "no US state on the registration")]


class TestParseBracketGames:
    def test_every_scored_game_is_read_with_its_title_and_time(self):
        games = seg.parse_bracket_games(BRACKET_PAGES["575271"])

        assert games == [
            {
                "title": "Semifinal",
                "when": "9/6 2:40P, Field 26A",
                "sides": [
                    ("Lou Fusz Athletic 15/16b Blue Star Premier (2034)", "1"),
                    ("Chicago Fc United U11 Academy Red", "1"),
                ],
            },
            {
                "title": "Championship",
                "when": "9/7 8:00A, Field 26B",
                "sides": [("Lou Fusz Athletic 15/16b Blue Star Premier (2034)", "1"), ("Cfysc 11u Boys Premier", "5")],
            },
            {
                "title": "4th Place",
                "when": "9/6 3:50P, Field 23",
                "sides": [("Croatian Eagles 11ub Red", "6"), ("Fc Pride U11 Pre-ecnl 15/16", "2")],
            },
        ]

    def test_zero_zero_games_with_no_winner_are_kept(self):
        games = seg.parse_bracket_games(BRACKET_PAGES["575278"])

        assert [(g["title"], [score for _, score in g["sides"]]) for g in games] == [
            ("Semifinal", ["0", "0"]),
            ("Championship", ["0", "0"]),
            ("4th Place Game", ["0", "1"]),
            ("Consolation", ["4", "1"]),
        ]

    def test_an_unfilled_slot_or_a_non_numeric_score_is_dropped(self):
        html = """<div id="x_BracketPanel">
          <table class="game"><tr><td class="team">A FC</td><td class="score">2</td><td class="title">Final</td></tr>
          <tr><td class="team"></td><td class="score"></td><td class="time">9/7 9:00A, Field 1</td></tr></table>
          <table class="game"><tr><td class="team">B FC</td><td class="score">W</td><td class="title">Final</td></tr>
          <tr><td class="team">C FC</td><td class="score">F</td><td class="time">9/7 9:00A, Field 2</td></tr></table>
        </div>"""

        assert seg.parse_bracket_games(html) == []

    @pytest.mark.parametrize("score", ["²", "١", "1234", "9" * 5000])
    def test_a_score_that_is_not_one_to_three_ascii_digits_is_dropped(self, score):
        html = f"""<div id="x_BracketPanel">
          <table class="game">
          <tr><td class="team">A FC</td><td class="score">{score}</td><td class="title">Final</td></tr>
          <tr><td class="team">B FC</td><td class="score">1</td><td class="time">9/7 9:00A, Field 1</td></tr></table>
        </div>"""

        assert seg.parse_bracket_games(html) == []

    def test_a_page_with_no_bracket_panel_has_no_games(self):
        assert seg.parse_bracket_games(NO_BRACKET) == []


class TestResolveGameDate:
    def test_month_and_day_take_the_events_year(self):
        assert seg.resolve_game_date(9, 6, {"start": "2026-09-04T05:00:00"}) == date(2026, 9, 6)

    def test_a_game_on_the_start_day_stays_in_that_year(self):
        assert seg.resolve_game_date(9, 4, {"start": "2026-09-04T05:00:00"}) == date(2026, 9, 4)

    def test_an_event_spanning_new_year_rolls_forward(self):
        assert seg.resolve_game_date(1, 2, {"start": "2026-12-30T00:00:00"}) == date(2027, 1, 2)


def _collect(today, days_back=14):
    in_scope, skipped = _roster()
    fetcher = _PageFetcher()
    games, problems = seg.collect_games(fetcher, in_scope + skipped, _program(), days_back, today)
    return games, problems, fetcher


class TestCollectGames:
    def test_recased_bracket_names_map_to_registered_ids(self):
        games, problems, _ = _collect(date(2026, 9, 14))

        assert problems == []
        assert [(g.title, g.home_id, g.home_score, g.away_id, g.away_score, g.game_date) for g in games] == [
            ("Semifinal", "580345", 1, "595379", 1, date(2026, 9, 6)),
            ("Championship", "580345", 1, "575271", 5, date(2026, 9, 7)),
            ("4th Place", "581324", 6, "592364", 2, date(2026, 9, 6)),
            ("Semifinal", "581312", 0, "576488", 0, date(2026, 9, 6)),
            ("Championship", "581312", 0, "577902", 0, date(2026, 9, 7)),
            ("4th Place Game", "595392", 0, "596374", 1, date(2026, 9, 6)),
            ("Consolation", "588950", 4, "575278", 1, date(2026, 9, 6)),
        ]
        assert (games[0].game_time, games[0].venue) == ("2:40P", "Field 26A")

    def test_only_divisions_with_a_cohort_are_fetched(self):
        _, _, fetcher = _collect(date(2026, 9, 14))

        assert fetcher.urls == [
            seg.team_page_url("592286"),
            seg.team_page_url("575271"),
            seg.team_page_url("575278"),
            seg.team_page_url("581318"),
        ]

    def test_the_earliest_day_of_the_window_is_included(self):
        games, _, _ = _collect(date(2026, 9, 20))

        assert len(games) == 7

    def test_a_day_before_the_window_is_excluded(self):
        games, _, _ = _collect(date(2026, 9, 21))

        assert [g.game_date for g in games] == [date(2026, 9, 7), date(2026, 9, 7)]

    def test_a_game_after_today_is_excluded(self):
        games, _, _ = _collect(date(2026, 9, 6))

        assert {g.game_date for g in games} == {date(2026, 9, 6)}

    def test_a_bracket_name_outside_the_division_is_a_problem_not_a_game(self):
        in_scope, skipped = _roster()
        renamed = [row for row in in_scope + skipped if row.seg_team_id != "592364"]

        games, problems = seg.collect_games(_PageFetcher(), renamed, _program(), 14, date(2026, 9, 14))

        assert "4th Place" not in [g.title for g in games]
        assert len(problems) == 1 and problems[0].startswith("Boys - U11 Platinum: bracket names not in the division")


def _linked(*seg_team_ids):
    return {i: seg.Outcome("linked_existing", f"master-{i}", 1.0) for i in seg_team_ids}


class TestBuildCsvRows:
    def _rows(self, outcomes):
        in_scope, skipped = _roster()
        games, _, _ = _collect(date(2026, 9, 14))
        return seg.build_csv_rows(games, in_scope + skipped, outcomes, _program())

    def _all_linked(self):
        in_scope, _ = _roster()
        return _linked(*(row.seg_team_id for row in in_scope))

    def test_a_game_whose_away_team_is_in_review_is_held_back(self):
        outcomes = self._all_linked()
        outcomes["576488"] = seg.Outcome("review", confidence=0.85)

        records, held = self._rows(outcomes)

        assert [(g.title, g.away_id) for g in held] == [("Semifinal", "576488")]
        assert len(records) == 12

    def test_a_game_whose_home_team_is_in_review_is_held_back(self):
        outcomes = self._all_linked()
        outcomes["588950"] = seg.Outcome("review", confidence=0.85)

        _, held = self._rows(outcomes)

        assert [(g.title, g.home_id) for g in held] == [("Consolation", "588950")]

    @pytest.mark.parametrize("status", ["already_linked", "linked_existing", "relinked", "created"])
    def test_every_linked_outcome_lets_its_games_import(self, status):
        outcomes = self._all_linked()
        outcomes["596374"] = seg.Outcome(status, "master-596374", 1.0)

        records, held = self._rows(outcomes)

        assert (held, len(records)) == ([], 14)

    def test_a_game_whose_team_has_no_outcome_is_held_back(self):
        outcomes = self._all_linked()
        del outcomes["596374"]

        _, held = self._rows(outcomes)

        assert [(g.title, g.away_id) for g in held] == [("4th Place Game", "596374")]

    def test_a_zero_zero_game_is_a_draw_on_both_rows(self):
        records, _ = self._rows(self._all_linked())
        final = [r for r in records if r["schedule_id"] == "239747-Championship-2026-09-07"]

        assert [(r["team_id"], r["home_away"], r["goals_for"], r["goals_against"], r["result"]) for r in final] == [
            ("581312", "H", 0, 0, "D"),
            ("577902", "A", 0, 0, "D"),
        ]

    def test_rows_carry_what_the_importer_reads(self):
        records, _ = self._rows(self._all_linked())
        home = records[0]

        assert {
            "provider", "team_id", "team_name", "opponent_id", "opponent_name", "age_group", "gender", "state",
            "event_name", "venue", "game_date", "home_away", "goals_for", "goals_against", "result",
            "source_url", "scraped_at", "schedule_id",
        } <= set(home)
        assert {k: home[k] for k in ("provider", "event_id", "event_name", "age_group", "age_year", "gender")} == {
            "provider": "soccereventsgroup",
            "event_id": 19206,
            "event_name": "Chicago Cup - Boys - U11 Platinum",
            "age_group": "u11",
            "age_year": 2016,
            "gender": "Boys",
        }
        assert (home["team_id"], home["opponent_id"], home["state_code"], home["result"]) == (
            "580345",
            "595379",
            "MO",
            "D",
        )

    def test_a_girls_division_writes_girls_rows(self):
        records, _ = self._rows(self._all_linked())

        assert {r["gender"] for r in records if r["age_group"] == "u14"} == {"Girls"}


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
        seg_team_id = kwargs["provider_team_id"]
        self.matched.append(seg_team_id)
        created = {"matched": True, "team_id": f"new-{seg_team_id}", "method": "direct_id", "created": True}
        return _FakeMatcher.results.get(seg_team_id, {**created, "confidence": 1.0})

    def queue_for_review(self, **kwargs):
        self.matched.append(kwargs["provider_team_id"])
        return {"matched": False, "team_id": None, "method": "name_age_review", "confidence": 0.8, "review": True}


class _ProvidersClient:
    def table(self, _name):
        return self

    def select(self, *_a):
        return self

    def eq(self, *_a):
        return self

    def execute(self):
        return SimpleNamespace(data=[{"id": "seg-provider"}])


class _FixedDate(date):
    @classmethod
    def today(cls):
        return date(2026, 9, 14)


@pytest.fixture
def run_main(monkeypatch, tmp_path):
    def run(*flags, saved=None, queued=None):
        raw = json.loads((FIXTURES / "program.json").read_text(encoding="utf-8"))
        _FakeMatcher.instances = []
        imports = []
        alias_calls = []
        review_calls = []

        def fake_existing_aliases(_client, _provider_id, seg_team_ids):
            alias_calls.append(list(seg_team_ids))
            if len(alias_calls) == 1:
                return {}
            return saved if saved is not None else {i: f"new-{i}" for i in seg_team_ids}

        def fake_pending_reviews(_client, seg_team_ids):
            review_calls.append(list(seg_team_ids))
            return set(seg_team_ids) if queued is None else queued & set(seg_team_ids)

        fetcher = _PageFetcher()
        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
        monkeypatch.setattr(seg, "create_client", lambda *_a: _ProvidersClient())
        monkeypatch.setattr(seg, "make_session", lambda: None)
        monkeypatch.setattr(seg, "fetch_program", lambda _s, _p: json.loads(json.dumps(raw)))
        monkeypatch.setattr(seg, "fetch_team_list", lambda _s, _a, _p: _team_list())
        monkeypatch.setattr(seg, "_get", lambda _s, url: SimpleNamespace(text=fetcher(url)))
        monkeypatch.setattr(seg, "SoccerEventsGroupGameMatcher", _FakeMatcher)
        monkeypatch.setattr(seg, "existing_aliases", fake_existing_aliases)
        monkeypatch.setattr(seg, "pending_reviews", fake_pending_reviews)
        monkeypatch.setattr(seg, "team_names_by_id", lambda _c, _ids: {})
        monkeypatch.setattr(seg, "_soccer_season_year", lambda now=None: SEASON)
        monkeypatch.setattr(seg, "date", _FixedDate)
        monkeypatch.setattr(
            seg.subprocess, "run", lambda cmd, check: imports.append(cmd) or SimpleNamespace(returncode=0)
        )
        argv = ["import_soccereventsgroup_event.py", "--program-id", "19206", "--output-dir", str(tmp_path)]
        monkeypatch.setattr(seg.sys, "argv", [*argv, "--delay-min", "0", "--delay-max", "0", *flags])

        code = seg.main()
        [report] = tmp_path.glob("*_teams.csv")
        outcomes = {r["seg_team_id"]: r for r in csv.DictReader(report.open(encoding="utf-8"))}
        return SimpleNamespace(
            code=code, imports=imports, outcomes=outcomes, alias_calls=alias_calls, review_calls=review_calls
        )

    return run


class TestMain:
    def test_a_dry_run_builds_only_dry_run_matchers_and_starts_no_import(self, run_main):
        result = run_main()

        assert result.code == 0
        assert result.imports == []
        assert [(m.dry_run, m.registration_mode) for m in _FakeMatcher.instances] == [(True, True)]
        assert len(result.alias_calls) == 1
        assert result.review_calls == []

    def test_execute_imports_the_games_csv(self, run_main):
        result = run_main("--execute")

        assert [(m.dry_run, m.registration_mode) for m in _FakeMatcher.instances] == [(True, True), (False, True)]
        [command] = result.imports
        assert command[1:2] == ["scripts/import_games_enhanced.py"] and command[-1] == "soccereventsgroup"

    def test_conflicting_teams_are_never_matched_by_the_writer(self, run_main):
        linked = {"matched": True, "team_id": "T1", "method": "fuzzy_auto", "confidence": 0.95, "created": False}
        _FakeMatcher.results = {seg_team_id: linked for seg_team_id in ("581312", "576488")}
        try:
            result = run_main("--execute")
        finally:
            _FakeMatcher.results = {}

        writer = _FakeMatcher.instances[1]
        assert {"581312", "576488"} & set(writer.matched) == set()
        assert (result.outcomes["581312"]["outcome"], result.outcomes["576488"]["outcome"]) == ("conflict", "conflict")

    def test_a_team_whose_link_was_not_saved_is_an_error(self, run_main):
        in_scope, _ = _roster()
        saved = {row.seg_team_id: f"new-{row.seg_team_id}" for row in in_scope if row.seg_team_id != "596374"}

        result = run_main("--execute", saved=saved)

        assert (result.outcomes["596374"]["outcome"], result.outcomes["596374"]["reason"]) == (
            "error",
            "link was not saved",
        )

    def test_a_relinked_team_whose_link_was_not_saved_is_an_error(self, run_main):
        relinked = {"matched": True, "team_id": "own-596374", "method": "direct_id", "confidence": 1.0}
        _FakeMatcher.results = {"596374": {**relinked, "created": False, "relinked": True}}
        in_scope, _ = _roster()
        saved = {row.seg_team_id: f"new-{row.seg_team_id}" for row in in_scope if row.seg_team_id != "596374"}
        try:
            result = run_main("--execute", saved=saved)
        finally:
            _FakeMatcher.results = {}

        assert (result.outcomes["596374"]["outcome"], result.outcomes["596374"]["reason"]) == (
            "error",
            "link was not saved",
        )

    def test_a_team_queued_for_review_with_no_pending_row_is_an_error(self, run_main):
        review = {"matched": False, "team_id": None, "method": "fuzzy_review", "confidence": 0.8, "review": True}
        _FakeMatcher.results = {"596374": review, "581312": review}
        try:
            result = run_main("--execute", queued={"581312"})
        finally:
            _FakeMatcher.results = {}

        assert sorted(result.review_calls[0]) == ["581312", "596374"]
        assert (result.outcomes["581312"]["outcome"], result.outcomes["581312"]["reason"]) == ("review", "")
        assert (result.outcomes["596374"]["outcome"], result.outcomes["596374"]["reason"]) == (
            "error",
            "review item was not saved",
        )


class TestUnsavedLinks:
    def test_a_missing_or_misdirected_alias_is_reported(self):
        outcomes = {
            "a": seg.Outcome("linked_existing", "T1"),
            "b": seg.Outcome("created", "T2"),
            "c": seg.Outcome("created", "T3"),
            "d": seg.Outcome("review"),
            "e": seg.Outcome("relinked", "T4"),
            "f": seg.Outcome("already_linked", "T5"),
        }

        assert seg.unsaved_links(outcomes, {"a": "T1", "b": "T9"}) == {
            "b": "link was not saved",
            "c": "link was not saved",
            "e": "link was not saved",
        }


class TestUnsavedReviews:
    def test_only_a_review_outcome_with_no_pending_row_is_reported(self):
        outcomes = {
            "a": seg.Outcome("review", confidence=0.8),
            "b": seg.Outcome("review", confidence=0.8),
            "c": seg.Outcome("created", "T1"),
        }

        assert seg.unsaved_reviews(outcomes, {"a"}) == {"b": "review item was not saved"}


def _outcomes_of(results):
    return {k: (o.status, o.team_id_master) for k, o in results.items()}


class _FakeMatcherForRegister:
    def __init__(self, results):
        self.results = results
        self.calls = []
        self.queued = []

    def _match_team(self, **kwargs):
        self.calls.append(kwargs["provider_team_id"])
        result = self.results[kwargs["provider_team_id"]]
        if isinstance(result, Exception):
            raise result
        return result

    def queue_for_review(self, **kwargs):
        self.queued.append((kwargs["provider_team_id"], kwargs["reason"]))
        return {"matched": False, "team_id": None, "method": "name_age_review", "confidence": 0.8, "review": True}


class TestRegisterTeams:
    def test_each_result_shape_lands_in_its_bucket(self):
        rows = [seg.TeamRow(str(i), f"Team {i}", 1, "D", "u11", 2016, "Male", "IL") for i in range(7)]
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

        outcomes = seg.register_teams(matcher, "provider", rows, {"0": "t0"})

        assert _outcomes_of(outcomes) == {
            "0": ("already_linked", "t0"),
            "1": ("created", "t1"),
            "2": ("linked_existing", "t2"),
            "3": ("review", None),
            "4": ("error", None),
            "5": ("already_linked", "t5"),
            "6": ("relinked", "t6"),
        }
        assert matcher.calls == ["1", "2", "3", "4", "5", "6"]

    def test_a_team_needing_review_by_its_name_age_is_queued_not_matched(self):
        row = seg.TeamRow("9", "CFYSC 10U Boys Premier", 1, "D", "u11", 2016, "Male", "IL")
        row.review_reason = "name says U10, division is U11"
        matcher = _FakeMatcherForRegister({})

        outcomes = seg.register_teams(matcher, "provider", [row], {})

        assert (outcomes["9"].status, outcomes["9"].reason) == ("review", "name says U10, division is U11")
        assert (matcher.calls, matcher.queued) == ([], [("9", "name says U10, division is U11")])


class TestSharedLinks:
    def test_two_new_links_to_one_team_are_both_conflicts(self):
        outcomes = {
            "a": seg.Outcome("linked_existing", "T1", 0.95),
            "b": seg.Outcome("linked_existing", "T1", 1.0),
            "c": seg.Outcome("already_linked", "T2", 1.0),
            "d": seg.Outcome("linked_existing", "T2", 0.92),
            "e": seg.Outcome("created", "T3", 1.0),
            "f": seg.Outcome("linked_existing", "T4", 1.0),
        }

        assert seg.shared_links(outcomes) == {
            "a": "same PitchRank team as SEG team b",
            "b": "same PitchRank team as SEG team a",
            "d": "same PitchRank team as SEG team c",
        }


class _AliasQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, *_a):
        return self

    def eq(self, field, value):
        self.filters.append(lambda r, f=field, v=value: r[f] == v)
        return self

    def in_(self, field, values):
        self.filters.append(lambda r, f=field, v=tuple(values): r[f] in v)
        return self

    def execute(self):
        return SimpleNamespace(data=[r for r in self.rows if all(f(r) for f in self.filters)])


class TestExistingAliases:
    def test_only_this_providers_approved_aliases_count(self):
        rows = [
            {"provider_id": "seg", "provider_team_id": "1", "team_id_master": "a", "review_status": "approved"},
            {"provider_id": "gotsport", "provider_team_id": "2", "team_id_master": "b", "review_status": "approved"},
            {"provider_id": "seg", "provider_team_id": "3", "team_id_master": "c", "review_status": "pending"},
        ]
        client = SimpleNamespace(table=lambda _name: _AliasQuery(rows))

        assert seg.existing_aliases(client, "seg", ["1", "2", "3"]) == {"1": "a"}


class TestPendingReviews:
    def test_only_this_providers_pending_rows_count(self):
        rows = [
            {"provider_id": "soccereventsgroup", "provider_team_id": "1", "status": "pending"},
            {"provider_id": "gotsport", "provider_team_id": "2", "status": "pending"},
            {"provider_id": "soccereventsgroup", "provider_team_id": "3", "status": "rejected"},
            {"provider_id": "soccereventsgroup", "provider_team_id": "4", "status": "pending"},
        ]
        client = SimpleNamespace(table=lambda _name: _AliasQuery(rows))

        assert seg.pending_reviews(client, ["1", "2", "3"]) == {"1"}


class _Response:
    """A ``requests`` response: bytes decoded with the declared charset, ISO-8859-1 for bare text/*."""

    def __init__(self, status_code, body=b"{}", content_type="application/json; charset=utf-8"):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.content = body
        declared = re.search(r"charset=([\w-]+)", content_type)
        self.encoding = declared.group(1) if declared else ("ISO-8859-1" if content_type.startswith("text/") else None)

    @property
    def text(self):
        return self.content.decode(self.encoding or "utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)


class _Session:
    def __init__(self, outcome):
        self.outcome = outcome

    def get(self, url, timeout):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class TestFetch:
    def test_a_page_with_no_declared_charset_is_read_as_utf8(self):
        response = seg._get(_Session(_Response(200, "Élite Sports Club".encode("utf-8"), "text/html")), "u")

        assert response.text == "Élite Sports Club"

    def test_a_non_200_raises(self):
        with pytest.raises(seg.ScrapeFetchError):
            seg.fetch_program(_Session(_Response(500)), 19206)

    def test_a_transport_error_raises(self):
        with pytest.raises(seg.ScrapeFetchError):
            seg.fetch_program(_Session(requests.ConnectionError("reset")), 19206)

    def test_a_non_json_body_raises(self):
        with pytest.raises(seg.ScrapeFetchError):
            seg.fetch_team_list(_Session(_Response(200, b"<html>", "text/html; charset=utf-8")), 80, 19206)
