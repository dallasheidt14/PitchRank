"""Unit tests for scripts/scrape_affinity_or_tournament.py.

Two things here can fail silently and are what these tests exist for:

- OYSA runs the Aug 1 - Jul 31 cycle USYS adopted for 2026-27, so its U13 is
  the Aug 2013 - Jul 2014 band, which is exactly what this project calls u13.
  The division label needs no adjustment. What must not happen is reading a
  team NAME as a birth year: Oregon writes that band "13B", after its older
  year, and feeding 2013 to ``calculate_age_group_from_birth_year`` — which
  takes the band's younger year — files the whole division as u14.
- Unplayed fixtures must reach the importer with BOTH scores empty. A row
  with one score present is rejected there, so the scraper must not invent
  the missing half.

The flight/game HTTP plumbing beyond this is covered by the end-to-end
scrape+import verification (matches the WA/TGS/PlayMetrics convention).
"""

import pytest

from scripts import scrape_affinity_or_tournament as scraper
from src.utils import team_utils

PINNED_SEASON = 2026


class TestDivisionCohort:
    """An OYSA U-number is the cohort; only the band's younger year is derived."""

    @pytest.mark.parametrize(
        "age_u, expected_birth_year",
        [
            (11, 2016),
            (12, 2015),
            (13, 2014),
            (14, 2013),
        ],
    )
    def test_u_number_yields_the_bands_younger_year(self, age_u, expected_birth_year):
        assert scraper._age_u_to_birth_year(age_u, PINNED_SEASON) == expected_birth_year

    @pytest.mark.parametrize(
        "division, expected_age_group",
        [
            ("BU11 SCL", "U11"),
            ("BU12 RCL North 1", "U12"),
            ("BU13 RCL North 2", "U13"),
            ("BU14 RCL South", "U14"),
            ("GU11 RCL Central", "U11"),
            ("GU14 RCL North 4", "U14"),
        ],
    )
    def test_division_lands_on_its_own_number(self, division, expected_age_group):
        _, age_u = scraper._extract_age_gender_from_division(division)

        birth_year = scraper._age_u_to_birth_year(age_u, PINNED_SEASON)
        age_group = team_utils.calculate_age_group_from_birth_year(birth_year, PINNED_SEASON)

        assert age_group == expected_age_group

    def test_reading_a_team_name_as_a_birth_year_would_be_wrong(self):
        """The trap: 'BU13' fields teams named '13B', and 2013 is the OLDER year.

        Feeding the name's year to a function that takes the younger one moves
        the whole division up a cohort. Pinned so a future 'simplification'
        back to reading team names fails here rather than on a ranking board.
        """
        from_the_label = team_utils.calculate_age_group_from_birth_year(
            scraper._age_u_to_birth_year(13, PINNED_SEASON), PINNED_SEASON
        )
        from_the_team_name = team_utils.calculate_age_group_from_birth_year(2013, PINNED_SEASON)

        assert from_the_label == "U13"
        assert from_the_team_name == "U14"


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


def _schedule_html(rows, date_header="Bracket - Saturday,  September 12, 2026"):
    """Build a schedule_results2 page shaped like OYSA's."""
    cells = "".join(
        "<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>" for row in rows
    )
    return f"<html><body><center>{date_header}</center><table>{cells}</table></body></html>"


PLAYED = ["738750", "Duniway Park", "10:30 AM", "Turf", "A4 vs A7", "LFC 13B Red", "3", "vs.", "PCFC Unity 13B", "1"]
UNPLAYED = ["738713", "Lake Oswego", "12:00 PM", "Turf", "A5 vs A3", "OPFC 13B Gold", "", "vs.", "LCYSA 13B Red", ""]
HOME_ONLY = ["738705", "Luke Jensen", "01:30 PM", "Trf1", "A6 vs A9", "Pacific FC 13B Blue", "2", "vs.", "SCA 13B", ""]
AWAY_ONLY = ["738721", "Westside HS", "03:00 PM", "Turf", "A11 vs A10", "RYSC 13B Black", "", "vs.", "CUSC 13B", "4"]

FLIGHT = {
    "flight_guid": "9A8F7D52-BA9B-44E1-8E76-201AAEDD2767",
    "division_name": "BU13 RCL North 2",
    "birth_year": 2014,
    "age_u": 13,
    "gender": "Male",
}
TOURNAMENT = {
    "name": "2026 OYSA Fall League",
    "tournament_guid": "765ABB82-7406-4A4D-9446-7EA366142522",
    "base_url": "https://oysa.sportsaffinity.com",
}

# Whether a blank pair is a fixture depends on the wall clock, so these dates
# are far enough either side of it that the suite does not change meaning as
# time passes — a fixed 2026 date silently became "today" mid-review.
FUTURE_HEADER = "Bracket - Saturday,  September 12, 2099"
PAST_HEADER = "Bracket - Saturday,  September 12, 2020"
WIDE_WINDOW = (scraper.datetime(2019, 1, 1), scraper.datetime(2100, 1, 1))
NARROW_WINDOW = (scraper.datetime(2026, 9, 1), scraper.datetime(2026, 10, 1))


def _scrape(monkeypatch, rows, date_header=FUTURE_HEADER, window=WIDE_WINDOW):
    """Scrape `rows` with the season pinned, so Aug 1 does not move the expectations."""
    html = _schedule_html(rows, date_header)
    monkeypatch.setattr(scraper, "_fetch", lambda url, retries=3: html)
    monkeypatch.setattr(
        scraper,
        "calculate_age_group_from_birth_year",
        lambda birth_year: team_utils.calculate_age_group_from_birth_year(birth_year, PINNED_SEASON),
    )
    return scraper.scrape_flight_games(TOURNAMENT, FLIGHT, *window)


class TestScoreShapes:
    """Played, scheduled and half-reported rows each have one correct outcome."""

    def test_played_game_carries_integer_scores(self, monkeypatch):
        records = _scrape(monkeypatch, [PLAYED])

        home, away = records
        assert (home["goals_for"], home["goals_against"], home["result"]) == (3, 1, "W")
        assert (away["goals_for"], away["goals_against"], away["result"]) == (1, 3, "L")

    def test_a_past_dated_blank_pair_is_not_a_fixture(self, monkeypatch):
        """The importer rejects it, so shipping it is only warning noise."""
        assert _scrape(monkeypatch, [UNPLAYED], PAST_HEADER) == []

    def test_a_past_dated_played_game_is_still_kept(self, monkeypatch):
        assert len(_scrape(monkeypatch, [PLAYED], PAST_HEADER)) == 2

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


def _accepted_list_html(divisions):
    """Build an accepted_list page shaped like OYSA's, one row per division."""
    rows = "".join(
        "<tr>"
        f"<td>{name}</td>"
        "<td>Brackets</td>"
        f'<td><a href="schedule_results2.asp?sessionguid=&flightguid={guid}'
        f'&tournamentguid=765ABB82-7406-4A4D-9446-7EA366142522">Schedule &amp; Results</a></td>'
        "</tr>"
        for name, guid in divisions
    )
    return f"<html><body><table>{rows}</table></body></html>"


DIVISIONS = [
    ("BU11 SCL", "11111111-1111-4111-8111-111111111111"),
    ("BU12 RCL North 1", "22222222-2222-4222-8222-222222222222"),
    ("BU13 RCL North 2", "33333333-3333-4333-8333-333333333333"),
    ("BU14 RCL South", "44444444-4444-4444-8444-444444444444"),
]


class TestDiscoverFlights:
    """The step that turns a division label into a cohort and a birth year.

    This is where the shipped off-by-one actually lived — the helpers were
    right in isolation and the wiring fed them the wrong thing — so the
    assertions here are on what a flight ends up carrying, not on a helper.
    """

    def _discover(self, monkeypatch, target_age, target_gender="Male"):
        monkeypatch.setattr(
            scraper, "_fetch", lambda url, retries=3: _accepted_list_html(DIVISIONS)
        )
        unpinned = scraper._age_u_to_birth_year
        monkeypatch.setattr(
            scraper,
            "_age_u_to_birth_year",
            lambda age_u, season_year=None: unpinned(age_u, PINNED_SEASON),
        )
        return scraper.discover_flights(TOURNAMENT, target_age, target_gender)

    @pytest.mark.parametrize(
        "target_age, expected_division, expected_birth_year",
        [
            (11, "BU11 SCL", 2016),
            (12, "BU12 RCL North 1", 2015),
            (13, "BU13 RCL North 2", 2014),
            (14, "BU14 RCL South", 2013),
        ],
    )
    def test_a_cohort_selects_its_own_division(
        self, monkeypatch, target_age, expected_division, expected_birth_year
    ):
        """u13 must select BU13 — not BU12, which the shipped off-by-one did."""
        flights = self._discover(monkeypatch, target_age)

        assert [f["division_name"] for f in flights] == [expected_division]
        assert flights[0]["birth_year"] == expected_birth_year
        assert flights[0]["age_u"] == target_age

    def test_other_cohorts_are_filtered_out(self, monkeypatch):
        """Without the cohort filter every sweep would return all four divisions."""
        flights = self._discover(monkeypatch, 13)

        assert len(flights) == 1

    def test_an_absent_cohort_selects_nothing(self, monkeypatch):
        assert self._discover(monkeypatch, 17) == []

    def test_the_girls_tab_is_requested_for_female(self, monkeypatch):
        seen = {}

        def fake_fetch(url, retries=3):
            seen["url"] = url
            return _accepted_list_html([("GU13 RCL Central", "55555555-5555-4555-8555-555555555555")])

        monkeypatch.setattr(scraper, "_fetch", fake_fetch)
        flights = scraper.discover_flights(TOURNAMENT, 13, "Female")

        assert "show=girls" in seen["url"]
        assert [f["gender"] for f in flights] == ["Female"]


class TestDateWindow:
    """The window bounds the scrape at both ends; --days-forward opens the near one."""

    @pytest.mark.parametrize(
        "date_header",
        [
            "Bracket - Saturday,  August 15, 2026",
            "Bracket - Saturday,  November 14, 2026",
        ],
    )
    def test_a_date_outside_the_window_is_skipped(self, monkeypatch, date_header):
        assert _scrape(monkeypatch, [PLAYED], date_header, NARROW_WINDOW) == []

    def test_a_date_inside_the_window_is_kept(self, monkeypatch):
        header = "Bracket - Saturday,  September 26, 2026"
        assert len(_scrape(monkeypatch, [PLAYED], header, NARROW_WINDOW)) == 2


class TestRecordFields:
    """A BU13 flight writes u13 rows, whatever its teams are named."""

    def test_rows_carry_the_labelled_cohort(self, monkeypatch):
        records = _scrape(monkeypatch, [PLAYED, UNPLAYED])

        assert records
        assert all(record["age_group"] == "u13" for record in records)
        assert all(record["age_year"] == 2014 for record in records)
        assert all(record["state_code"] == "OR" for record in records)
        assert all(record["provider"] == "affinity_or" for record in records)
