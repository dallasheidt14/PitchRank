"""Unit tests for scripts/scrape_affinity_or_tournament.py.

Two things here can fail silently and are what these tests exist for:

- OYSA numbers a division ``season - birth_year``; PitchRank numbers the same
  cohort ``season - birth_year + 1``.  ``BU13`` fields 2013-born teams and
  belongs on the u14 board.  Reading the 13 as a cohort files every Oregon
  team a year low, and nothing downstream would notice.
- Unplayed fixtures must reach the importer with BOTH scores empty.  A row
  with one score present is rejected there, so the scraper must not invent
  the missing half.

The flight/game HTTP plumbing beyond this is covered by the end-to-end
scrape+import verification (matches the WA/TGS/PlayMetrics convention).
"""

import pytest

from scripts import scrape_affinity_or_tournament as scraper
from src.utils import team_utils

PINNED_SEASON = 2026


class TestDivisionBirthYear:
    """An OYSA U-number is a birth year, never a PitchRank cohort."""

    @pytest.mark.parametrize(
        "age_u, expected_birth_year",
        [
            (11, 2015),
            (12, 2014),
            (13, 2013),
            (14, 2012),
        ],
    )
    def test_u_number_reads_as_birth_year(self, age_u, expected_birth_year):
        assert scraper._division_birth_year(age_u, PINNED_SEASON) == expected_birth_year

    @pytest.mark.parametrize(
        "division, expected_age_group",
        [
            ("BU11 SCL", "U12"),
            ("BU12 RCL North 1", "U13"),
            ("BU13 RCL North 2", "U14"),
            ("BU14 RCL South", "U15"),
            ("GU11 RCL Central", "U12"),
            ("GU14 RCL North 4", "U15"),
        ],
    )
    def test_division_lands_one_cohort_above_its_own_number(self, division, expected_age_group):
        """The whole point: OYSA's BU13 is PitchRank's U14."""
        _, age_u = scraper._extract_age_gender_from_division(division)

        birth_year = scraper._division_birth_year(age_u, PINNED_SEASON)
        age_group = team_utils.calculate_age_group_from_birth_year(birth_year, PINNED_SEASON)

        assert age_group == expected_age_group

    def test_taking_the_label_as_a_cohort_would_be_wrong(self):
        """Pins the off-by-one itself, so a 'simplification' back to it fails."""
        _, age_u = scraper._extract_age_gender_from_division("BU13 RCL North 2")

        naive = f"U{age_u}"
        correct = team_utils.calculate_age_group_from_birth_year(
            scraper._division_birth_year(age_u, PINNED_SEASON), PINNED_SEASON
        )

        assert naive == "U13"
        assert correct == "U14"


class TestGenderAndAgeExtraction:
    """Both Affinity label styles must parse; OYSA writes the compact one."""

    @pytest.mark.parametrize(
        "division, gender, age_u",
        [
            # OYSA compact form — the B/G is glued to the U-number
            ("BU13 RCL North 2", "Male", 13),
            ("GU11 SCL", "Female", 11),
            ("BU14 RCL Central 1", "Male", 14),
            ("gu12 rcl south", "Female", 12),
            # Spelled-out Affinity form, kept so a relabel does not blind the scraper
            ("Boys Under 12 Div 1", "Male", 12),
            ("Girls U10 North", "Female", 10),
        ],
    )
    def test_gender_and_age_come_from_the_label(self, division, gender, age_u):
        assert scraper._extract_age_gender_from_division(division) == (gender, age_u)

    @pytest.mark.parametrize("division", ["Venue Info", "Published", ""])
    def test_non_division_rows_yield_no_age(self, division):
        _, age_u = scraper._extract_age_gender_from_division(division)

        assert age_u is None


class TestRosterBirthYear:
    """The veto reads team names; it must abstain rather than guess."""

    def test_majority_year_wins(self):
        names = [
            "LFC 13B Red 1",
            "PCFC Unity 13B",
            "OPFC LOSC 13B Gold",
            "Westside Metros 12B Copa White",
        ]

        assert scraper._roster_birth_year(names) == 2013

    def test_too_few_year_tokens_abstains(self):
        names = ["LFC 13B Red 1", "PCFC Unity 13B", "Portland Thorns Academy"]

        assert scraper._roster_birth_year(names) is None

    def test_no_year_tokens_abstains(self):
        names = ["FC Portland Red", "Eastside Timbers Blue", "CUSC Black", "SCA Gold"]

        assert scraper._roster_birth_year(names) is None


def _schedule_html(rows, date_header="Bracket - Saturday,  September 12, 2026"):
    """Build a schedule_results2 page shaped like OYSA's."""
    cells = "".join(
        "<tr>"
        + "".join(f"<td>{value}</td>" for value in row)
        + "</tr>"
        for row in rows
    )
    return f"<html><body><center>{date_header}</center><table>{cells}</table></body></html>"


PLAYED = ["738750", "Duniway Park", "10:30 AM", "Turf", "A4 vs A7", "LFC 13B Red", "3", "vs.", "PCFC Unity 13B", "1"]
UNPLAYED = ["738713", "Lake Oswego", "12:00 PM", "Turf", "A5 vs A3", "OPFC 13B Gold", "", "vs.", "LCYSA 13B Red", ""]
HOME_ONLY = ["738705", "Luke Jensen", "01:30 PM", "Trf1", "A6 vs A9", "Pacific FC 13B Blue", "2", "vs.", "SCA 13B Gold", ""]
AWAY_ONLY = ["738721", "Westside HS", "03:00 PM", "Turf", "A11 vs A10", "RYSC 13B Black", "", "vs.", "CUSC 13B Black", "4"]

FLIGHT = {
    "flight_guid": "9A8F7D52-BA9B-44E1-8E76-201AAEDD2767",
    "division_name": "BU13 RCL North 2",
    "birth_year": 2013,
    "age_u": 13,
    "gender": "Male",
}
TOURNAMENT = {
    "name": "2026 OYSA Fall League",
    "tournament_guid": "765ABB82-7406-4A4D-9446-7EA366142522",
    "base_url": "https://oysa.sportsaffinity.com",
}

WINDOW_START = scraper.datetime(2026, 9, 1)
WINDOW_END = scraper.datetime(2026, 10, 1)


def _scrape(monkeypatch, rows):
    """Scrape `rows` with the season pinned, so Aug 1 does not move the expectations."""
    monkeypatch.setattr(scraper, "_fetch", lambda url, retries=3: _schedule_html(rows))
    monkeypatch.setattr(
        scraper,
        "calculate_age_group_from_birth_year",
        lambda birth_year: team_utils.calculate_age_group_from_birth_year(birth_year, PINNED_SEASON),
    )
    return scraper.scrape_flight_games(TOURNAMENT, FLIGHT, WINDOW_START, WINDOW_END)


class TestScoreShapes:
    """Played, scheduled and half-reported rows each have one correct outcome."""

    def test_played_game_carries_integer_scores(self, monkeypatch):
        records = _scrape(monkeypatch, [PLAYED])

        home, away = records
        assert (home["goals_for"], home["goals_against"], home["result"]) == (3, 1, "W")
        assert (away["goals_for"], away["goals_against"], away["result"]) == (1, 3, "L")

    def test_unplayed_fixture_emits_both_scores_empty(self, monkeypatch):
        records = _scrape(monkeypatch, [UNPLAYED])

        assert len(records) == 2
        for record in records:
            assert record["goals_for"] == ""
            assert record["goals_against"] == ""
            assert record["result"] == "U"

    def test_home_only_score_is_dropped(self, monkeypatch):
        """Half a result is not a scheduled game — the importer rejects the shape."""
        assert _scrape(monkeypatch, [HOME_ONLY]) == []

    def test_away_only_score_is_dropped(self, monkeypatch):
        assert _scrape(monkeypatch, [AWAY_ONLY]) == []

    def test_played_and_unplayed_coexist(self, monkeypatch):
        records = _scrape(monkeypatch, [PLAYED, UNPLAYED])

        assert len(records) == 4
        assert sum(1 for r in records if r["goals_for"] == "") == 2


class TestCohortVeto:
    """A division whose teams disagree with its label is skipped, not written."""

    def test_disagreeing_roster_skips_the_flight(self, monkeypatch):
        shifted = [
            ["738750", "V", "10:30 AM", "T", "A1", "LFC 11B Red", "3", "vs.", "PCFC 11B", "1"],
            ["738751", "V", "12:00 PM", "T", "A2", "OPFC 11B Gold", "2", "vs.", "LCYSA 11B", "2"],
        ]

        assert _scrape(monkeypatch, shifted) == []

    def test_agreeing_roster_passes_through(self, monkeypatch):
        records = _scrape(monkeypatch, [PLAYED, UNPLAYED])

        assert records
        assert all(record["age_group"] == "u14" for record in records)
        assert all(record["state_code"] == "OR" for record in records)
        assert all(record["provider"] == "affinity_or" for record in records)
