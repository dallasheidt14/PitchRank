"""Unit tests for scripts/scrape_playmetrics_league.py.

Covers the pure helpers, row construction, the governing-body tables, and the
``--min-game-date`` floor end to end with the provider calls monkeypatched.
HTTP and the matcher are exercised by the smoke scrape and dry-run import, not here.
"""

import pytest

from scripts.scrape_playmetrics_league import (
    GB_STATE_MAP,
    STATE_CODE_TO_NAME,
    STATE_CODE_TO_TIMEZONE,
    _parse_league_url,
    derive_team_age_group,
    is_before_min_date,
    map_min_age_to_age_group,
    normalize_game,
    parse_int_or_none,
    parse_utc_to_local_date,
)

PINNED_SEASON = 2025


class TestDeriveTeamAgeGroup:
    """Team-name-first age_group derivation with division fallback."""

    @pytest.fixture(autouse=True)
    def _pin_season(self, monkeypatch):
        """Hold the season year so these expectations do not expire on Aug 1.

        Every case here is season-relative: a 2015-born team is u11 in 2025-26
        and u12 in 2026-27. Two patches are needed, not one.
        ``extract_birth_year_from_name`` reads ``CURRENT_YEAR`` off the module at
        call time, but ``calculate_age_group_from_birth_year`` is imported by
        value and binds its season default at definition time, so that name has
        to be replaced where the caller looks it up.
        """
        import scripts.scrape_playmetrics_league as mod
        from src.utils import team_utils

        monkeypatch.setattr(team_utils, "CURRENT_YEAR", PINNED_SEASON)
        monkeypatch.setattr(
            mod,
            "calculate_age_group_from_birth_year",
            lambda birth_year, current_year=PINNED_SEASON: (
                team_utils.calculate_age_group_from_birth_year(birth_year, current_year)
            ),
        )

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
            # U-token with a gender letter fused on
            ("LUFC U11B Navy", "u10", "u11"),
            ("WIUFC U11G Elite I", "u10", "u11"),
            ("Croatian Eagles 11uB Red 2", "u10", "u11"),
            ("LUFC U16G Navy", "u17", "u16"),
            # A two-year band is named by its younger year
            ("Neenah SC 2014/2015 Boys 11U Red Premier", "u10", "u11"),
            ("FC Chicago 2014-2015 Elite", "u10", "u11"),
            # A longer list and a non-consecutive pair name no single cohort, so
            # each falls through to the single-year lookup (its first year)
            ("CSC 2014/2015/2016 Boys", "u10", "u12"),
            ("CSC 2014 / 2015 / 2016 Boys", "u10", "u12"),
            ("CSC 2014 - 2015 - 2016 Boys", "u10", "u12"),
            ("Club 2012/2015 Girls", "u10", "u14"),
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
        # 2004 is outside ``calculate_age_group_from_birth_year``'s range for the
        # pinned season → falls through to the U-token / fallback path.
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

    def test_nc_evening_rolls_back_a_day(self):
        # 9:00 PM ET on Sep 4 2026 == 01:00Z on Sep 5 2026 (EDT = UTC-4)
        assert parse_utc_to_local_date("2026-09-05T01:00:00Z", "NC") == "2026-09-04"

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


class TestGoverningBodyStates:
    def test_ncysa_governing_body_is_north_carolina(self):
        # https://playmetricssports.com/g/leagues/1207-2289-46ec05ca/league_view.html
        # is "Classic League - Fall 2026 (Club)"; its fields are in Raleigh
        # and Holly Springs, NC.
        assert GB_STATE_MAP[1207] == "NC"
        assert STATE_CODE_TO_NAME["NC"] == "North Carolina"
        assert STATE_CODE_TO_TIMEZONE["NC"] == "America/New_York"

    @pytest.mark.parametrize("state_code", sorted(set(GB_STATE_MAP.values())))
    def test_every_governing_body_state_has_a_name_and_a_timezone(self, state_code):
        # A state in GB_STATE_MAP with no timezone silently writes the wrong
        # calendar date for every evening kickoff; one with no name writes
        # an empty `state` column.
        assert STATE_CODE_TO_NAME[state_code]
        assert STATE_CODE_TO_TIMEZONE[state_code]


class TestNormalizeGame:
    GAME = {
        "id": 20,
        "home_team_id": 57610,
        "away_team_id": 66258,
        "home_team_score": 2,
        "away_team_score": 4,
        "start_datetime": "2026-08-23T13:15:00Z",
        "time": "9:15 AM",
        "status": "Played",
    }
    TEAMS = {
        "57610": {"team_name": "15 (U11) TFA Purple", "club_id": 5861, "club_name": "TOR Futbol Academy"},
        "66258": {"team_name": "15 (U11) SSL White", "club_id": 5847, "club_name": "Seashore Soccer League"},
    }
    DIVISION = {"id": 19596, "name": "'15 (U11B) 3rd EAST1"}

    def _rows(self):
        return normalize_game(
            self.GAME, self.TEAMS, self.DIVISION, "Classic League", 1207, 2289, "46ec05ca", "u11", "Male", "NC"
        )

    def test_both_rows_carry_the_governing_body_state(self):
        # The matcher scopes by this column: a blank value files every team in
        # the file under the importer's default state, a wrong one under the wrong state.
        home, away = self._rows()
        assert (home["state_code"], home["state"]) == ("NC", "North Carolina")
        assert (away["state_code"], away["state"]) == ("NC", "North Carolina")

    def test_game_date_is_the_local_calendar_day(self):
        home, _ = self._rows()
        assert home["game_date"] == "2026-08-23"

    def test_an_evening_kickoff_keeps_its_local_day_on_both_rows(self):
        # 9:00 PM ET on Jul 31 is 01:00Z on Aug 1; a UTC slice would move the
        # game across the season floor.
        game = {**self.GAME, "start_datetime": "2026-08-01T01:00:00Z"}
        home, away = normalize_game(
            game, self.TEAMS, self.DIVISION, "Classic League", 1207, 2289, "46ec05ca", "u11", "Male", "NC"
        )
        assert (home["game_date"], away["game_date"]) == ("2026-07-31", "2026-07-31")


class TestIsBeforeMinDate:
    def test_a_game_before_the_floor_is_dropped(self):
        assert is_before_min_date("2026-07-31", "2026-08-01") is True

    def test_a_game_on_the_floor_is_kept(self):
        assert is_before_min_date("2026-08-01", "2026-08-01") is False

    def test_no_floor_keeps_everything(self):
        assert is_before_min_date("2019-01-01", None) is False

    def test_an_unparseable_date_is_kept_for_the_importer_to_judge(self):
        assert is_before_min_date("", "2026-08-01") is False


class TestDateFloorWiring:
    """The floor is applied inside the division loop and passed by the workflow."""

    PAYLOAD = {
        "sport_configuration": {"name": "Soccer"},
        "teams": [
            {"team": {"id": 1, "name": "15 (U11) A"}, "club": {"id": 10, "name": "Club A"}},
            {"team": {"id": 2, "name": "15 (U11) B"}, "club": {"id": 20, "name": "Club B"}},
        ],
        "schedule": [
            {
                "id": 100,
                "status": "Played",
                "home_team_id": 1,
                "away_team_id": 2,
                "start_datetime": "2026-07-25T14:00Z",
            },
            {
                "id": 101,
                "status": "Played",
                "home_team_id": 2,
                "away_team_id": 1,
                "start_datetime": "2026-08-22T14:00Z",
            },
            {
                # 9:00 PM ET on Jul 31: the UTC day is already Aug 1.
                "id": 102,
                "status": "Played",
                "home_team_id": 1,
                "away_team_id": 2,
                "start_datetime": "2026-08-01T01:00:00Z",
            },
        ],
    }
    DIVISION = {"id": 5, "name": "'15 (U11B) 3rd", "min_age": 11, "gender": "M"}

    def _scrape(self, monkeypatch, min_game_date):
        import scripts.scrape_playmetrics_league as mod

        monkeypatch.setattr(mod, "get_division", lambda *a, **k: self.PAYLOAD)
        config = {"governing_body_id": 1207, "league_id": 2289, "key": "k", "min_game_date": min_game_date}
        return mod.scrape_division(self.DIVISION, "Classic League", config)

    def test_games_before_the_floor_are_dropped_by_local_date_and_counted(self, monkeypatch):
        records, counts = self._scrape(monkeypatch, "2026-08-01")
        assert counts["skipped_before_min_date"] == 2
        assert counts["games_emitted"] == 1
        assert {r["game_date"] for r in records} == {"2026-08-22"}

    def test_no_floor_keeps_every_game(self, monkeypatch):
        records, counts = self._scrape(monkeypatch, None)
        assert counts["skipped_before_min_date"] == 0
        assert counts["games_emitted"] == 3

    def test_the_league_summary_rolls_up_the_floor_count(self, monkeypatch):
        import scripts.scrape_playmetrics_league as mod

        monkeypatch.setattr(mod, "get_league", lambda *a, **k: {"name": "Classic League", "divisions": [self.DIVISION]})
        monkeypatch.setattr(mod, "get_division", lambda *a, **k: self.PAYLOAD)
        monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
        config = {"governing_body_id": 1207, "league_id": 2289, "key": "k", "delay_sec": 0}
        config["min_game_date"] = "2026-08-01"

        records, summary = mod.scrape_league(config)

        assert summary["skipped_before_min_date"] == 2
        assert summary["games_emitted"] == 1
        assert len(records) == 2

    def test_the_workflow_passes_the_floor_on_every_scraper_invocation(self):
        from pathlib import Path

        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/playmetrics-scrape-import.yml"
        text = workflow.read_text(encoding="utf-8")
        # Drop comment lines, then join backslash continuations so each
        # invocation is one logical command; a commented-out flag must not count.
        code = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))
        commands = code.replace("\\\n", " ").splitlines()
        scrape_calls = [c for c in commands if "python scripts/scrape_playmetrics_league.py" in c]
        assert scrape_calls, "workflow no longer calls the league scraper"
        for call in scrape_calls:
            assert '--min-game-date "$MIN_GAME_DATE"' in call, call
        assert "MIN_GAME_DATE: ${{ inputs.min_game_date || '2026-08-01' }}" in text
        input_block = text.split("min_game_date:", 1)[1].split("\n\n", 1)[0]
        assert "default: '2026-08-01'" in input_block


class TestResolveConfig:
    URL = "https://playmetricssports.com/g/leagues/1207-2289-46ec05ca/league_view.html"

    def _config(self, monkeypatch, *extra):
        import sys

        import scripts.scrape_playmetrics_league as mod

        monkeypatch.delenv("PLAYMETRICS_LEAGUE_URL", raising=False)
        monkeypatch.setattr(sys, "argv", ["scrape_playmetrics_league.py", "--league-url", self.URL, *extra])
        return mod.resolve_config()

    def test_no_floor_by_default(self, monkeypatch):
        monkeypatch.delenv("PLAYMETRICS_MIN_GAME_DATE", raising=False)
        assert self._config(monkeypatch)["min_game_date"] is None

    def test_a_valid_floor_is_kept(self, monkeypatch):
        assert self._config(monkeypatch, "--min-game-date", "2026-08-01")["min_game_date"] == "2026-08-01"

    def test_the_env_var_supplies_the_floor(self, monkeypatch):
        monkeypatch.setenv("PLAYMETRICS_MIN_GAME_DATE", "2026-08-01")
        config = self._config(monkeypatch)
        assert config["min_game_date"] == "2026-08-01"

    ARABIC_INDIC = "\u0662\u0660\u0662\u0666-\u0660\u0668-\u0660\u0661"

    @pytest.mark.parametrize("bad", ["09/01/2026", "2026-8-1", "2026-18-01", "2026-02-30", ARABIC_INDIC])
    def test_a_floor_that_is_not_a_real_ascii_date_stops_the_run(self, monkeypatch, bad):
        # A malformed floor is compared lexicographically, so it silently keeps
        # or drops the whole league behind a green run; the run must refuse to start.
        with pytest.raises(SystemExit):
            self._config(monkeypatch, "--min-game-date", bad)
