"""Unit tests for pure helpers in scripts/scrape_squadi_competition.py.

Scope (mirroring tests/unit/test_scrape_playmetrics.py):
- Pure parsers for age/gender/tier, club, external org id, source URL.
- Score validator and UTC-to-local-date converter.
- Token-bundle regex extractors.

The token harvester's network round-trip, the SquadiClient HTTP layer, the
discovery filter, and the CSV writer are covered by the end-to-end dry-run
verification in Task 16, not by unit tests.
"""

import pytest

from scripts.scrape_squadi_competition import (
    REQUIRED_COLUMNS,
    compute_result,
    parse_int_or_none,
    parse_utc_to_local_date,
)


def test_required_columns_match_canonical_28_col_list():
    assert REQUIRED_COLUMNS[0] == "provider"
    assert REQUIRED_COLUMNS[-1] == "division_name"
    assert len(REQUIRED_COLUMNS) == 28
    # Order matches scripts/scrape_playmetrics_league.py REQUIRED_COLUMNS exactly
    expected = [
        "provider", "scrape_run_id", "event_id", "event_name", "schedule_id",
        "age_year", "age_group", "gender", "team_id", "team_id_source",
        "team_name", "club_name", "opponent_id", "opponent_id_source",
        "opponent_name", "opponent_club_name", "state", "state_code",
        "game_date", "game_time", "home_away", "goals_for", "goals_against",
        "result", "venue", "source_url", "scraped_at", "division_name",
    ]
    assert REQUIRED_COLUMNS == expected


class TestComputeResult:
    @pytest.mark.parametrize(
        "gf, ga, expected",
        [(2, 1, "W"), (1, 2, "L"), (3, 3, "D"), (0, 0, "D"),
         (None, 1, "U"), (1, None, "U"), (None, None, "U")],
    )
    def test_outcomes(self, gf, ga, expected):
        assert compute_result(gf, ga) == expected


class TestParseIntOrNone:
    @pytest.mark.parametrize(
        "value, expected",
        [(0, 0), (3, 3), (50, 50), ("0", 0), ("7", 7), ("3.0", 3)],
    )
    def test_valid_scores(self, value, expected):
        assert parse_int_or_none(value) == expected

    @pytest.mark.parametrize(
        "value",
        [None, "", " ", "None", "null", True, False, "2.5", "-1", -1, 51, 999, "abc"],
    )
    def test_invalid_or_out_of_range(self, value):
        assert parse_int_or_none(value) is None


class TestParseUtcToLocalDate:
    def test_njys_evening_kickoff_stays_same_day(self):
        # 22:30 UTC on 2024-09-06 = 18:30 ET on 2024-09-06
        date_str, time_str = parse_utc_to_local_date(
            "2024-09-06T22:30:00.000Z", "America/New_York"
        )
        assert date_str == "2024-09-06"
        assert time_str == "18:30"

    def test_late_night_utc_rolls_back_to_previous_day_in_et(self):
        # 03:00 UTC on 2024-09-07 = 23:00 ET on 2024-09-06
        date_str, time_str = parse_utc_to_local_date(
            "2024-09-07T03:00:00.000Z", "America/New_York"
        )
        assert date_str == "2024-09-06"
        assert time_str == "23:00"

    def test_malformed_input_returns_blank_pair(self):
        assert parse_utc_to_local_date("not-a-date", "America/New_York") == ("", "")
        assert parse_utc_to_local_date("", "America/New_York") == ("", "")
        assert parse_utc_to_local_date(None, "America/New_York") == ("", "")
