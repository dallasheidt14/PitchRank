"""Unit tests for pure helpers in scripts/scrape_squadi_competition.py.

Scope (mirroring tests/unit/test_scrape_playmetrics.py):
- Pure parsers for age/gender/tier, club, external org id, source URL.
- Score validator and UTC-to-local-date converter.
- Token-bundle regex extractors.

The token harvester's network round-trip, the SquadiClient HTTP layer, the
discovery filter, and the CSV writer are covered by the end-to-end dry-run
verification in Task 16, not by unit tests.
"""

from pathlib import Path

import pytest

from scripts.scrape_squadi_competition import (
    REQUIRED_COLUMNS,
    compute_result,
    extract_bundle_url_from_html,
    extract_external_org_id,
    extract_token_from_bundle,
    parse_club_name,
    parse_division_metadata,
    parse_int_or_none,
    parse_squadi_url,
    parse_utc_to_local_date,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "squadi"


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


class TestParseDivisionMetadata:
    @pytest.mark.parametrize(
        "division_name, fallback_age_int, expected",
        [
            # Standard cases
            ("11U Boys Challenge Cup", 10, ("u11", "Boys", "Challenge Cup")),
            ("14U Girls National Championship Series", 13,
             ("u14", "Girls", "National Championship Series")),
            ("17U Boys Champions League", 16, ("u17", "Boys", "Champions League")),
            # Dual-age picks the older cohort
            ("15U/16U Girls National Championship Series", 14,
             ("u16", "Girls", "National Championship Series")),
            ("13U/14U Boys Challenge Cup", 12, ("u14", "Boys", "Challenge Cup")),
            # u18 remaps to u19
            ("18U Boys Champions League", 17, ("u19", "Boys", "Champions League")),
            ("17U/18U Girls Challenge Cup", 16, ("u19", "Girls", "Challenge Cup")),
            # Trailing whitespace / mixed case
            ("  11U   Boys   Challenge Cup  ", 10, ("u11", "Boys", "Challenge Cup")),
            # Boys/Girls capitalization variants — output is always "Boys"/"Girls"
            ("11U BOYS Challenge Cup", 10, ("u11", "Boys", "Challenge Cup")),
            ("11U girls Challenge Cup", 10, ("u11", "Girls", "Challenge Cup")),
        ],
    )
    def test_well_formed_division_names(self, division_name, fallback_age_int, expected):
        assert parse_division_metadata(division_name, fallback_age_int) == expected

    def test_no_age_token_falls_back_to_division_age_int(self):
        # division.age=10 means 11U per Squadi's "min age" convention
        assert parse_division_metadata("Boys Recreational", 10) == ("u11", "Boys", "Recreational")

    def test_no_age_token_no_fallback_returns_blank_age(self):
        assert parse_division_metadata("Boys Recreational", None) == ("", "Boys", "Recreational")

    def test_no_gender_token_returns_blank_gender(self):
        assert parse_division_metadata("11U Open Division", 10) == ("u11", "", "Open Division")

    def test_age_below_tracked_range_returns_blank(self):
        # u9 etc. are out of PitchRank's tracked range
        assert parse_division_metadata("9U Boys Recreational", 8) == ("", "Boys", "Recreational")

    def test_fully_unparseable(self):
        assert parse_division_metadata("Random String", None) == ("", "", "Random String")
        assert parse_division_metadata("", None) == ("", "", "")

    def test_gender_uses_word_boundary_no_false_positives(self):
        # Substrings that *contain* "boys"/"girls" must not trigger gender detection.
        # Without word-boundary matching, "Girlscout" would falsely return "Girls".
        assert parse_division_metadata("Girlscout 11U Division", 10) == ("u11", "", "Girlscout Division")
        assert parse_division_metadata("Boysenberry 11U Division", 10) == ("u11", "", "Boysenberry Division")


class TestParseClubName:
    @pytest.mark.parametrize(
        "team_name, expected_club",
        [
            ("Mount Olive SC - STA Mount Olive 2014 EDP Boys", "Mount Olive SC"),
            ("Wall SC - Liverpool", "Wall SC"),
            ("Point Pleasant Travel SC - Wave United Black", "Point Pleasant Travel SC"),
            # No dash → club = full name
            ("NJ Stallions 14 Betis EDP", "NJ Stallions 14 Betis EDP"),
            # Empty / None
            ("", ""),
            (None, ""),
            # Multiple dashes → first segment only
            ("Team A - Sub - Detail", "Team A"),
            # Whitespace handling
            ("  Wall SC  -  Liverpool  ", "Wall SC"),
        ],
    )
    def test_split(self, team_name, expected_club):
        assert parse_club_name(team_name) == expected_club


class TestExtractExternalOrgId:
    def test_standard_logo_url(self):
        url = "https://storage.googleapis.com/download/storage/v1/b/squadi-prod-us.appspot.com/o/%2Forganisation%2Flogo_org_443_1720797311497.blob?generation=1720797311634378&alt=media"
        assert extract_external_org_id(url) == "443"

    def test_comp_logo_url_returns_none(self):
        # comp_<id> isn't an org id
        url = "https://storage.googleapis.com/download/storage/v1/b/squadi-prod-us.appspot.com/o/%2Fcomp_46%2Flogo_1725580224902.blob"
        assert extract_external_org_id(url) is None

    def test_missing_or_blank(self):
        assert extract_external_org_id(None) is None
        assert extract_external_org_id("") is None
        assert extract_external_org_id("https://example.com/no-org-here.png") is None


class TestParseSquadiUrl:
    def test_full_url_extraction(self):
        url = ("https://registration.us.squadi.com/livescoreSeasonFixture"
               "?organisationKey=7cfab077-e619-47e4-ab36-0febc29501a2"
               "&competitionUniqueKey=539ff993-3032-414e-9dfe-5466629fc1c9"
               "&yearId=6&divisionId=All")
        result = parse_squadi_url(url)
        assert result["org_uuid"] == "7cfab077-e619-47e4-ab36-0febc29501a2"
        assert result["competition_uuid"] == "539ff993-3032-414e-9dfe-5466629fc1c9"
        assert result["year_ref_id"] == 6

    def test_missing_org_key_returns_none(self):
        url = "https://registration.us.squadi.com/livescoreSeasonFixture?yearId=6"
        assert parse_squadi_url(url) is None

    def test_missing_year_id_is_optional(self):
        url = ("https://registration.us.squadi.com/livescoreSeasonFixture"
               "?organisationKey=7cfab077-e619-47e4-ab36-0febc29501a2"
               "&competitionUniqueKey=539ff993-3032-414e-9dfe-5466629fc1c9")
        result = parse_squadi_url(url)
        assert result["org_uuid"] == "7cfab077-e619-47e4-ab36-0febc29501a2"
        assert result["year_ref_id"] is None

    def test_invalid_url_returns_none(self):
        assert parse_squadi_url("not a url") is None
        assert parse_squadi_url("") is None
        assert parse_squadi_url(None) is None

    def test_empty_org_key_returns_none(self):
        # ?organisationKey= (empty string value) should be treated as missing
        url = "https://registration.us.squadi.com/livescoreSeasonFixture?organisationKey=&yearId=6"
        assert parse_squadi_url(url) is None


class TestExtractBundleUrlFromHtml:
    def test_finds_main_bundle(self):
        html = (FIXTURE_DIR / "spa_index.html").read_text()
        assert extract_bundle_url_from_html(html) == "/static/js/main.e68022e7.js"

    def test_no_main_bundle_returns_none(self):
        assert extract_bundle_url_from_html("<html></html>") is None
        assert extract_bundle_url_from_html(
            '<script src="/static/js/2.abcdef.chunk.js"></script>'
        ) is None


class TestExtractTokenFromBundle:
    def test_finds_token_next_to_authorization_keyword(self):
        bundle = (FIXTURE_DIR / "main_bundle_sample.js").read_text()
        token = extract_token_from_bundle(bundle)
        assert token is not None
        assert len(token) >= 256
        assert all(c in "0123456789abcdef" for c in token)
        assert token.startswith("f68a1ffd")

    def test_no_token_returns_none(self):
        assert extract_token_from_bundle("var x = 1; var y = 'hello';") is None

    def test_short_hex_strings_are_rejected(self):
        # Must be at least 256 chars to qualify
        bundle = 'var TOKEN="' + ("a" * 100) + '"; "authorization"'
        assert extract_token_from_bundle(bundle) is None
