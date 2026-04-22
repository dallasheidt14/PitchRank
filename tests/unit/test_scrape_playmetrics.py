"""Unit tests for pure helpers in scripts/scrape_playmetrics_league.py.

Scope is limited to the novel, branch-heavy pure functions that encode domain
rules:

- ``derive_team_age_group`` — three-tier age resolution (birth year / U-token /
  division fallback) with the u18→u19 merge
- ``map_min_age_to_age_group`` — the fallback itself
- ``parse_int_or_none`` — score validation (0..50 whole integers only)
- ``parse_utc_to_local_date`` — state-local calendar-date conversion
- ``_parse_league_url`` — URL slug decomposition

The matcher and HTTP/CSV plumbing are covered by the end-to-end scrape+validate
verification in the implementation plan, not by unit tests (matches the
TGS/Affinity-WA convention).
"""

import pytest

from scripts.scrape_playmetrics_league import (
    _parse_league_url,
    derive_team_age_group,
    map_min_age_to_age_group,
    parse_int_or_none,
    parse_utc_to_local_date,
)


class TestDeriveTeamAgeGroup:
    """Team-name-first age_group derivation with division fallback."""

    @pytest.mark.parametrize(
        "name, fallback, expected",
        [
            # Birth-year parse beats division fallback
            ("11uB Croatian Eagles Red- 2015", "u10", "u11"),
            ("North Shore United 2015 Boys Blue Pre-Club Premier", "u10", "u11"),
            ("2014 ACE BLACK", "u11", "u12"),
            ("2016 Boys Red", "u10", "u10"),
            # Birth year 2007 → u19 (not u18) — PitchRank merges u18 into u19
            ("Neenah SC 2007 Girls 19U Red Premier", "u19", "u19"),
            # Birth year 2008 → u18 → remapped to u19
            ("Mukwonago 2008 Girls Blue", "u19", "u19"),
            # U-token parse when no birth year
            ("U11 Boys White", "u10", "u11"),
            ("Forward Madison FC Select U11 Boys", "u10", "u11"),
            ("Mukwonago U18 Girls Blue", "u19", "u19"),
            # Fallback when neither signal present
            ("High School Girls Borts II", "u19", "u19"),
            ("North Shore United High School Girls State Level", "u19", "u19"),
            ("ACE Team Name", "u12", "u12"),
            # Birth-year wins when both signals appear
            ("Rush 11U (2015) Wisconsin", "u10", "u11"),
            # Empty/None team name falls straight through
            ("", "u13", "u13"),
        ],
    )
    def test_derivation(self, name, fallback, expected):
        assert derive_team_age_group(name, fallback) == expected

    def test_unmapped_birth_year_falls_back(self):
        # 2004 is outside ``calculate_age_group_from_birth_year``'s range for
        # season 2025 → falls through to the U-token / fallback path.
        assert derive_team_age_group("FC 2004 Boys", "u16") == "u16"


class TestMapMinAgeToAgeGroup:
    @pytest.mark.parametrize(
        "age, expected",
        [
            (10, "u10"),
            (11, "u11"),
            (15, "u15"),
            (17, "u17"),
            (18, "u19"),  # u18 merges into u19
            (19, "u19"),
        ],
    )
    def test_valid_range(self, age, expected):
        assert map_min_age_to_age_group(age) == expected

    @pytest.mark.parametrize("age", [None, 0, 9, 20, 99, "not-an-int"])
    def test_invalid_or_out_of_range(self, age):
        assert map_min_age_to_age_group(age) is None


class TestParseIntOrNone:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (0, 0),
            (3, 3),
            (50, 50),
            ("0", 0),
            ("7", 7),
            ("50", 50),
            ("3.0", 3),  # whole-valued float accepted
        ],
    )
    def test_valid_scores(self, value, expected):
        assert parse_int_or_none(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            " ",
            "None",
            "null",
            "NONE",
            "NULL",
            True,
            False,  # bool rejected (bool is int subclass)
            "2.5",
            "-1",
            -1,
            51,
            999,
            "999",
            "abc",
            "3 goals",
        ],
    )
    def test_rejected(self, value):
        assert parse_int_or_none(value) is None


class TestParseUtcToLocalDate:
    def test_wi_evening_rolls_back_a_day(self):
        # 9:00 PM CT on Sep 6 2025 == 02:00Z on Sep 7 2025 (CDT = UTC-5)
        assert parse_utc_to_local_date("2025-09-07T02:00:00", "WI") == "2025-09-06"

    def test_wi_afternoon_same_day(self):
        # 2:30 PM CT on Sep 6 2025 == 19:30Z on Sep 6 2025
        assert parse_utc_to_local_date("2025-09-06T19:30:00", "WI") == "2025-09-06"

    def test_handles_trailing_z(self):
        assert parse_utc_to_local_date("2025-09-06T19:30:00Z", "WI") == "2025-09-06"

    def test_unmapped_state_falls_back_to_utc_slice(self):
        assert parse_utc_to_local_date("2025-09-07T02:00:00", "ZZ") == "2025-09-07"

    def test_empty_input(self):
        assert parse_utc_to_local_date("", "WI") == ""

    def test_unparseable_falls_back_to_slice(self):
        # 10-char slice of the unparseable string, not a conversion
        assert parse_utc_to_local_date("not-a-date-2025", "WI") == "not-a-date"


class TestParseLeagueUrl:
    def test_canonical_url(self):
        url = "https://playmetricssports.com/g/leagues/1014-1514-8ccd4dbb/league_view.html"
        assert _parse_league_url(url) == (1014, 1514, "8ccd4dbb")

    def test_malformed_url_returns_none(self):
        assert _parse_league_url("https://example.com/nope") is None
        assert _parse_league_url("") is None
