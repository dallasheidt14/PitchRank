"""Tests for the Affinity HI (HYSA Oahu League) scraper.

The HI scraper runs the OR scraper's engine, so these cover only what Hawaii adds:
HYSA's division labels and forfeit marks, filing a game by each team's own age
label, the season floor, and the tournament config.
"""

import runpy
import sys

import pytest

from scripts import scrape_affinity_hi_tournament as scraper
from scripts import scrape_affinity_or_tournament as engine
from tests.unit.test_scrape_affinity_or import WIDE_WINDOW, _accepted_list_html, _schedule_html

TOURNAMENT = scraper.TOURNAMENTS[0]
SEPTEMBER = "Bracket - Saturday,  September 12, 2026"


def _flight(division, age_u, gender="Male"):
    return {
        "flight_guid": "C3D2E1F0-1A2B-4C3D-8E9F-0A1B2C3D4E5F",
        "division_name": division,
        "birth_year": 2026 - age_u + 1,
        "age_u": age_u,
        "gender": gender,
    }


def _game(home, away, home_score="2", away_score="1"):
    return [
        "683528",
        "Oahu League Fields",
        "07:30 AM",
        "11AS 13",
        "B1 vs B3",
        home,
        home_score,
        "vs.",
        away,
        away_score,
    ]


def _scrape(monkeypatch, rows, flight, header=SEPTEMBER):
    html = _schedule_html(rows, header)
    monkeypatch.setattr(engine, "_fetch", lambda url, retries=3: html)
    return engine.scrape_flight_games(TOURNAMENT, flight, *WIDE_WINDOW)


class TestDivisionLabels:
    """HYSA writes the gender letter, then the age, then the U."""

    @pytest.mark.parametrize(
        "division, gender, age_u",
        [
            ("B12U", "Male", 12),
            ("B14U R1", "Male", 14),
            ("G13U R2", "Female", 13),
            ("B19U", "Male", 19),
            ("G09U R2", "Female", 9),
            ("B18-19U", "Male", 19),
        ],
    )
    def test_gender_and_age_come_from_the_label(self, division, gender, age_u):
        assert engine._extract_age_gender_from_division(division) == (gender, age_u)

    def test_a_range_spanning_boards_is_no_cohort(self):
        assert engine._extract_age_gender_from_division("G15-19U") == ("Female", None)

    def test_a_range_is_scraped_on_its_youngest_age(self):
        assert engine._youngest_division_age("G15-19U") == 15


ACCEPTED_LIST = _accepted_list_html(
    [
        ("G15-19U", "11111111-2222-4333-8444-555555555555"),
        ("G14U", "66666666-7777-4888-9999-000000000000"),
    ]
)


class TestRangeDivisions:
    """A range spanning boards is scraped once, on its youngest age's pass, and only where names set the age."""

    def _flights(self, monkeypatch, tournament, age):
        monkeypatch.setattr(engine, "_fetch", lambda url, retries=3: ACCEPTED_LIST)
        return [f["division_name"] for f in engine.discover_flights(tournament, age, "Female")]

    def test_the_youngest_age_pass_takes_the_range(self, monkeypatch):
        assert self._flights(monkeypatch, TOURNAMENT, 15) == ["G15-19U"]

    def test_no_other_pass_takes_it(self, monkeypatch):
        assert self._flights(monkeypatch, TOURNAMENT, 16) == []

    def test_a_league_filed_by_division_skips_it(self, monkeypatch):
        by_division = {k: v for k, v in TOURNAMENT.items() if k != "age_from_name_prefix"}

        assert self._flights(monkeypatch, by_division, 15) == []


class TestAgeFromNameLabels:
    """A game is filed by each team's own age label, never by the division it is played in."""

    def test_names_that_agree_are_filed_by_their_label(self, monkeypatch):
        records = _scrape(
            monkeypatch, [_game("12UB -RUSH Cinza 14/15B", "12UB - HSC Bulls 14/15B - I")], _flight("B12U", 12)
        )

        assert {(r["age_group"], r["age_year"]) for r in records} == {("u12", 2015)}

    def test_two_teams_playing_up_together_keep_their_own_age(self, monkeypatch):
        records = _scrape(
            monkeypatch, [_game("17UB - 10B Surf Hawaii Academy I", "17UB - FC Hawaii Red")], _flight("B19U", 19)
        )

        assert {(r["age_group"], r["age_year"]) for r in records} == {("u17", 2010)}

    def test_u18_and_u19_labels_share_the_u19_board(self, monkeypatch):
        records = _scrape(
            monkeypatch, [_game("18UB - BVB IA Hawaii", "19UB - Leahi Na Koa 08/09 Blue")], _flight("B19U", 19)
        )

        assert {r["age_group"] for r in records} == {"u19"}

    def test_a_label_only_name_is_filed_by_its_label(self, monkeypatch):
        records = _scrape(monkeypatch, [_game("13UB - Hoomau", "13UB - Inter Ohana CF Rosa")], _flight("B13U R1", 13))

        assert {r["age_group"] for r in records} == {"u13"}

    def test_a_name_with_two_u_ages_uses_its_label(self, monkeypatch):
        records = _scrape(
            monkeypatch,
            [_game("15UB - ALBION SC Hawaii HNL BU14/U15 Academy", "15UB - FC Hawaii Red")],
            _flight("B15U", 15),
        )

        assert {r["age_group"] for r in records} == {"u15"}

    def test_a_u9_team_is_held(self, monkeypatch):
        assert (
            _scrape(monkeypatch, [_game("09UG - 808 FC Black", "10UG - 808 FC Gold")], _flight("G10U", 10, "Female"))
            == []
        )

    def test_two_u9_teams_playing_up_together_are_held(self, monkeypatch):
        """They agree with each other, so only the board check holds them."""
        assert (
            _scrape(monkeypatch, [_game("09UG - 808 FC Black", "09UG - 808 FC Gold")], _flight("G10U", 10, "Female"))
            == []
        )

    @pytest.mark.parametrize(
        "home, away",
        [
            ("12UG - Leahi 14/15 West Blue", "12UB - FC Hawaii Red"),
            ("12UB - FC Hawaii Red", "12UG - Leahi 14/15 West Blue"),
        ],
    )
    def test_a_label_of_the_other_gender_is_held(self, monkeypatch, home, away):
        assert _scrape(monkeypatch, [_game(home, away)], _flight("B12U", 12)) == []

    @pytest.mark.parametrize(
        "home, away",
        [
            ("13UB - HSC Bulls 14/15B - I", "13UB - FC Hawaii Red"),
            ("13UB - FC Hawaii Red", "13UB - HSC Bulls 14/15B - I"),
        ],
    )
    def test_a_later_age_that_disagrees_with_the_label_is_held(self, monkeypatch, home, away):
        """'14/15B' is the U12 band, so a 13UB label on it is not a U13 team."""
        assert _scrape(monkeypatch, [_game(home, away)], _flight("B13U R1", 13)) == []

    @pytest.mark.parametrize(
        "home, away",
        [
            ("HSC Bulls 13/14B - I", "13UB - FC Hawaii Red"),
            ("13UB - FC Hawaii Red", "HSC Bulls 13/14B - I"),
        ],
    )
    def test_a_name_without_a_label_is_held(self, monkeypatch, home, away):
        assert _scrape(monkeypatch, [_game(home, away)], _flight("B13U R1", 13)) == []

    def test_teams_on_different_boards_are_held_and_counted(self, monkeypatch, capsys):
        records = _scrape(monkeypatch, [_game("17UB - FC Hawaii Red", "18UB - BVB IA Hawaii")], _flight("B19U", 19))

        assert records == []
        assert "(held 1 whose team names disagree on age)" in capsys.readouterr().out


class TestForfeits:
    def test_a_forfeit_imports_nothing(self, monkeypatch):
        """HYSA marks the score ('2F') and the team that forfeited; the score is not a result."""
        row = _game(
            "14UB - Leahi Na Koa 12/13 Windward",
            '14UB - Hawaii United FC 12/13<font color="red"><br>Forfeited Game </font>',
            home_score='&nbsp;2<font color="red">F</font>&nbsp;',
        )

        assert _scrape(monkeypatch, [row], _flight("B14U R1", 14)) == []


class TestSeasonFloor:
    GAME = _game("12UB - RUSH 14/15B", "12UB - FC Hawaii Red")

    def test_a_game_before_the_floor_is_dropped(self, monkeypatch):
        assert _scrape(monkeypatch, [self.GAME], _flight("B12U", 12), "Bracket - Friday,  July 31, 2026") == []

    def test_a_game_on_the_floor_is_kept(self, monkeypatch):
        records = _scrape(monkeypatch, [self.GAME], _flight("B12U", 12), "Bracket - Saturday,  August 1, 2026")

        assert {r["game_date"] for r in records} == {"2026-08-01"}

    def test_a_league_without_a_floor_keeps_every_date(self, monkeypatch):
        html = _schedule_html([self.GAME], "Bracket - Friday,  July 31, 2026")
        monkeypatch.setattr(engine, "_fetch", lambda url, retries=3: html)
        unfloored = {k: v for k, v in TOURNAMENT.items() if k != "min_game_date"}

        assert len(engine.scrape_flight_games(unfloored, _flight("B12U", 12), *WIDE_WINDOW)) == 2


class TestTournamentConfig:
    def test_the_oahu_league_entry(self):
        assert scraper.TOURNAMENTS == [
            {
                "name": "2026/27 Oahu League Season",
                "tournament_guid": "B52D16EC-4B82-4251-AD18-8E5C35567EC2",
                "base_url": "https://ol-fall-26-27.sportsaffinity.com",
                "provider": "affinity_hi",
                "state": "Hawaii",
                "state_code": "HI",
                "season_year": 2026,
                "age_from_name_prefix": True,
                "min_game_date": "2026-08-01",
            }
        ]

    def test_rows_carry_hawaiis_provider_and_state(self, monkeypatch):
        records = _scrape(monkeypatch, [_game("12UB - RUSH 14/15B", "12UB - FC Hawaii Red")], _flight("B12U", 12))

        assert len(records) == 2
        assert {(r["provider"], r["state_code"], r["state"]) for r in records} == {("affinity_hi", "HI", "Hawaii")}
        assert all(r["team_id"].startswith("affinity_hi:") for r in records)

    def test_the_script_walks_hawaiis_league_alone(self, monkeypatch, tmp_path):
        """Run as the workflow runs it: a bare main() would scrape Oregon's league as Hawaii's."""
        walked = []
        monkeypatch.setattr(engine, "discover_flights", lambda t, age, gender: walked.append(t["name"]) or [])
        monkeypatch.setattr(sys, "argv", ["x", "--age", "u13", "--gender", "male", "--output", str(tmp_path / "o.csv")])

        runpy.run_path(scraper.__file__, run_name="__main__")

        assert walked == ["2026/27 Oahu League Season"]
