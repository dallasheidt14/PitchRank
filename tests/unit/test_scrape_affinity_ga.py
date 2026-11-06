"""Tests for the Affinity GA (Georgia Soccer fall league) scraper.

The GA scraper runs the OR scraper's engine, so these cover only what Georgia adds: its
age-first division labels, leaving out the rec schedule, scraping a mixed division once on
its youngest age, keeping a game between two ages, and the tournament config.
"""

import runpy
import sys

import pytest

from scripts import scrape_affinity_ga_tournament as scraper
from scripts import scrape_affinity_or_tournament as engine
from tests.unit.test_scrape_affinity_or import WIDE_WINDOW, _accepted_list_html, _schedule_html

TOURNAMENT = scraper.TOURNAMENTS[0]
SEPTEMBER = "Bracket - Saturday,  September 12, 2026"

BOYS_DIVISIONS = (
    "12UB Pre GPL",
    "13UB GPL",
    "13UB CH/CF",
    "14UB GPL",
    "14UB CH/CF North",
    "14UB CH/CF South",
    "15UB GPL",
    "15UB Conference North",
    "15/16UB CH/CF North",
    "15/16UB CH/CF South",
    "16UB GPL",
    "17/18UB GPL",
    "17/19UB CH/CF North",
    "17/19UB CH/CF South",
    "19UB GPL",
    "19U BOYS RIAS",
)
GIRLS_DIVISIONS = ("13/14UG GPL/CH", "15/16UG GPL/CH", "17/19UG GPL/CH")


def _accepted_list(divisions):
    return _accepted_list_html(
        [(name, f"{number:08d}-2222-4333-8444-555555555555") for number, name in enumerate(divisions, start=1)]
    )


def _flight(division, age_u, gender="Male"):
    return {
        "flight_guid": "C3D2E1F0-1A2B-4C3D-8E9F-0A1B2C3D4E5F",
        "division_name": division,
        "birth_year": 2026 - age_u + 1,
        "age_u": age_u,
        "gender": gender,
    }


def _game(home, away, home_score="2", away_score="1"):
    return ["696545", "Wade Walker Park", "11:00 AM", "1A", "A1 vs A4", home, home_score, "vs.", away, away_score]


def _scrape(monkeypatch, rows, flight, header=SEPTEMBER):
    html = _schedule_html(rows, header)
    monkeypatch.setattr(engine, "_fetch", lambda url, retries=3: html)
    return engine.scrape_flight_games(TOURNAMENT, flight, *WIDE_WINDOW)


class TestDivisionLabels:
    """Georgia Soccer writes the age, then the U, then the gender letter."""

    @pytest.mark.parametrize(
        "division, gender, age_u",
        [
            ("12UB Pre GPL", "Male", 12),
            ("13UB GPL", "Male", 13),
            ("13UB CH/CF", "Male", 13),
            ("14UB GPL", "Male", 14),
            ("14UB CH/CF North", "Male", 14),
            ("14UB CH/CF South", "Male", 14),
            ("15UB GPL", "Male", 15),
            ("15UB Conference North", "Male", 15),
            ("16UB GPL", "Male", 16),
            ("19UB GPL", "Male", 19),
            ("18/19UB GPL", "Male", 19),
            ("14UG GPL", "Female", 14),
        ],
    )
    def test_gender_and_age_come_from_the_label(self, division, gender, age_u):
        assert engine._extract_age_gender_from_division(division) == (gender, age_u)

    @pytest.mark.parametrize(
        "division, gender, youngest",
        [
            ("15/16UB CH/CF North", "Male", 15),
            ("15/16UB CH/CF South", "Male", 15),
            ("17/18UB GPL", "Male", 17),
            ("17/19UB CH/CF North", "Male", 17),
            ("17/19UB CH/CF South", "Male", 17),
            ("13/14UG GPL/CH", "Female", 13),
            ("15/16UG GPL/CH", "Female", 15),
            ("17/19UG GPL/CH", "Female", 17),
        ],
    )
    def test_a_pair_spanning_boards_is_no_cohort_and_takes_its_youngest_age(self, division, gender, youngest):
        assert engine._extract_age_gender_from_division(division) == (gender, None)
        assert engine._youngest_division_age(division) == youngest


class TestDiscovery:
    def _flights(self, monkeypatch, divisions, age, gender="Male", tournament=TOURNAMENT):
        page = _accepted_list(divisions)
        monkeypatch.setattr(engine, "_fetch", lambda url, retries=3: page)
        return [f["division_name"] for f in engine.discover_flights(tournament, age, gender)]

    @pytest.mark.parametrize(
        "age, divisions",
        [
            (10, []),
            (11, []),
            (12, ["12UB Pre GPL"]),
            (13, ["13UB GPL", "13UB CH/CF"]),
            (14, ["14UB GPL", "14UB CH/CF North", "14UB CH/CF South"]),
            (15, ["15UB GPL", "15UB Conference North", "15/16UB CH/CF North", "15/16UB CH/CF South"]),
            (16, ["16UB GPL"]),
            (17, ["17/18UB GPL", "17/19UB CH/CF North", "17/19UB CH/CF South"]),
            (18, []),
            (19, ["19UB GPL"]),
        ],
    )
    def test_each_boys_division_is_scraped_on_one_pass(self, monkeypatch, age, divisions):
        assert self._flights(monkeypatch, BOYS_DIVISIONS, age) == divisions

    @pytest.mark.parametrize(
        "age, divisions",
        [(13, ["13/14UG GPL/CH"]), (14, []), (15, ["15/16UG GPL/CH"]), (16, []), (17, ["17/19UG GPL/CH"]), (19, [])],
    )
    def test_each_girls_division_is_scraped_on_one_pass(self, monkeypatch, age, divisions):
        assert self._flights(monkeypatch, GIRLS_DIVISIONS, age, "Female") == divisions

    def test_a_league_filed_by_division_skips_a_mixed_division(self, monkeypatch):
        by_division = {k: v for k, v in TOURNAMENT.items() if k != "mixed_age_divisions"}

        assert self._flights(monkeypatch, ["15/16UB CH/CF North"], 15, tournament=by_division) == []

    def test_a_rec_division_is_left_out_however_its_age_is_written(self, monkeypatch):
        """'19U BOYS RIAS' itself reads no age, so a label that does shows the skip is what drops it."""
        assert self._flights(monkeypatch, ["19UB RIAS"], 19) == []

    def test_only_a_league_that_names_the_word_skips_it(self, monkeypatch):
        no_skip = {k: v for k, v in TOURNAMENT.items() if k != "skip_divisions"}

        assert self._flights(monkeypatch, ["19UB RIAS"], 19, tournament=no_skip) == ["19UB RIAS"]

    def test_the_skip_ignores_case(self, monkeypatch):
        assert self._flights(monkeypatch, ["19UB Rias"], 19) == []

    def test_the_skip_matches_a_whole_word(self, monkeypatch):
        assert self._flights(monkeypatch, ["19UB Arias Cup"], 19) == ["19UB Arias Cup"]

    def test_a_pair_on_one_board_is_scraped_on_that_boards_pass(self, monkeypatch):
        """Only a pair spanning boards takes its youngest age, so '18/19UB' keeps the 19 pass."""
        assert self._flights(monkeypatch, ["18/19UB GPL"], 19) == ["18/19UB GPL"]
        assert self._flights(monkeypatch, ["18/19UB GPL"], 18) == []


class TestGames:
    def test_a_game_between_two_ages_is_kept_and_carries_the_divisions_age(self, monkeypatch, capsys):
        records = _scrape(
            monkeypatch,
            [_game("Savannah United 14/15B Prem", "All-In FC Sugar Hill U13B GPL")],
            _flight("13UB GPL", 13),
        )

        assert len(records) == 2
        assert {(r["age_group"], r["age_year"]) for r in records} == {("u13", 2014)}
        assert "held" not in capsys.readouterr().out

    def test_a_mixed_division_carries_its_youngest_age(self, monkeypatch):
        records = _scrape(
            monkeypatch,
            [_game("Covered Bridge Soccer Club - B19U Select", "Bryson Park Soccer Club U17")],
            _flight("17/19UB CH/CF North", 17),
        )

        assert {(r["age_group"], r["age_year"]) for r in records} == {("u17", 2010)}

    def test_a_name_stating_no_age_is_kept(self, monkeypatch):
        records = _scrape(monkeypatch, [_game("BC Prime", "Atlanta City FC - BU13 GPL")], _flight("14UB GPL", 14))

        assert {r["age_group"] for r in records} == {"u14"}

    @pytest.mark.parametrize(
        "home_score, away_score",
        [("4 F", "0"), ("0", "4 F"), ("0 CC", "0 CC"), ("CSC", "CSC")],
    )
    def test_a_marked_score_imports_nothing(self, monkeypatch, home_score, away_score):
        """A forfeit, or a game called off, is not a result."""
        row = _game(
            "BVB IA Georgia - PTC 14/15",
            'TCSA United - B12U<font color="red"><br>Forfeited Game </font>',
            home_score,
            away_score,
        )

        assert _scrape(monkeypatch, [row], _flight("12UB Pre GPL", 12)) == []


class TestTournamentConfig:
    def test_the_fall_league_entry(self):
        assert scraper.TOURNAMENTS == [
            {
                "name": "Fall 26 Georgia Soccer Scheduling",
                "tournament_guid": "72B7A2F4-DB78-434C-8D08-D119FEFD741C",
                "base_url": "https://gs-fall26schedule.sportsaffinity.com",
                "provider": "affinity_ga",
                "state": "Georgia",
                "state_code": "GA",
                "season_year": 2026,
                "skip_divisions": ("RIAS",),
                "mixed_age_divisions": True,
                "min_game_date": "2026-08-01",
            }
        ]

    def test_rows_carry_georgias_provider_and_state(self, monkeypatch):
        records = _scrape(monkeypatch, [_game("UMA FC U14B", "Savannah United 12/13B Blue")], _flight("14UB GPL", 14))

        assert len(records) == 2
        assert {(r["provider"], r["state_code"], r["state"]) for r in records} == {("affinity_ga", "GA", "Georgia")}
        assert all(r["team_id"].startswith("affinity_ga:") for r in records)

    def test_the_script_walks_georgias_league_alone(self, monkeypatch, tmp_path):
        """Run as the workflow runs it: a bare main() would scrape Oregon's league as Georgia's."""
        walked = []
        monkeypatch.setattr(engine, "discover_flights", lambda t, age, gender: walked.append(t["name"]) or [])
        monkeypatch.setattr(sys, "argv", ["x", "--age", "u13", "--gender", "male", "--output", str(tmp_path / "o.csv")])

        runpy.run_path(scraper.__file__, run_name="__main__")

        assert walked == ["Fall 26 Georgia Soccer Scheduling"]
