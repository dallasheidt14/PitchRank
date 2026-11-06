"""Tests for the Affinity GA (Georgia Soccer fall league) matcher.

The GA matcher is the state league matcher with Georgia's state and the league's name
spellings, so these cover what Georgia adds: the age forms, the club spellings and what makes
two names one squad. A game between two ages is driven through ``match_game_history`` for
both state league matchers, since a test of ``_own_board`` alone passes with the swap deleted.
"""

import pytest

from src.models.affinity_ga_matcher import AffinityGAGameMatcher
from src.models.affinity_hi_matcher import AffinityHIGameMatcher
from src.utils import team_utils
from tests.unit.test_affinity_hi_matcher import _RecordingDB, _team
from tests.unit.test_scrape_affinity_ut import _DB


@pytest.fixture(autouse=True)
def _season(monkeypatch):
    """Pin the season a birth year is read against, so Aug 1 does not move the expectations."""
    monkeypatch.setattr(team_utils, "_soccer_season_year", lambda: 2026)


def _matcher(rows=()):
    return AffinityGAGameMatcher(_DB(list(rows)), provider_id="p")


class TestOwnBoard:
    @pytest.mark.parametrize(
        "team_name, board",
        [
            ("Atlanta City FC - B12 Pre-GPL", "u12"),
            ("Hinesville SA-B14", "u14"),
            ("Hinesville SA-B15-Long County", "u15"),
            ("Georgia Wolves - BA12U", "u12"),
            ("Football Club OLeary - BR14U", "u14"),
            ("Coastal Outre - COS CREW14U", "u14"),
            ("Coastal Outre - COS CREW18U", "u19"),
        ],
    )
    def test_a_respelled_name_states_its_board(self, team_name, board):
        assert _matcher()._own_board(team_name) == board

    @pytest.mark.parametrize("team_name", ["Atlanta Furious - CH/CF", "BC Prime", "BC Blazers"])
    def test_a_name_stating_no_age_has_no_board(self, team_name):
        assert _matcher()._own_board(team_name) is None

    @pytest.mark.parametrize(
        "team_name, board",
        [
            ("Covered Bridge Soccer Club - B17U Select", "u17"),
            ("Covered Bridge Soccer Club - B19U Select", "u19"),
            ("Coastal Outreach SQUAD G18U", "u19"),
            ("UMA FC U12B", "u12"),
            ("Atlanta City FC - BU13 GPL", "u13"),
            ("Georgia Athletic SC - U18 B", "u19"),
            ("Coastal Outreach CYCLONES 13UG", "u13"),
            ("Champions FC Boys 13U", "u13"),
            ("Piedmont SA 16U - Premier", "u16"),
            ("Hinesville Waycross-U16", "u16"),
            ("BVB IA Georgia - Oconee 13/14 - CF", "u13"),
            ("Savannah United 14/15B Prem", "u12"),
            ("Savannah United 07/09B Blue", "u19"),
            ("GUSA Rome 2014B", "u13"),
            ("GUSA Rome 2011B", "u16"),
            ("Bryson Park Flash Soccer 2013 Black - GPL", "u14"),
            ("Sacred Heart Fusion 2011", "u16"),
        ],
    )
    def test_each_form_is_read_as_written(self, team_name, board):
        assert _matcher()._own_board(team_name) == board

    @pytest.mark.parametrize("team_name", ["Some Club U13/U14", None])
    def test_two_ages_or_no_name_state_no_board(self, team_name):
        assert _matcher()._own_board(team_name) is None


class TestPrepared:
    @pytest.mark.parametrize(
        "name, prepared",
        [
            ("Georgia Wolves - BA12U", "Georgia Wolves - U12"),
            ("Football Club OLeary - BR14U", "Football Club OLeary - U14"),
            ("Coastal Outre - COS CREW14U", "Coastal Outre - COS CREW U14"),
            ("Georgia Wolves - B13U - CF", "Georgia Wolves - U13 - CF"),
            ("Hinesville SA- G15U-Long County", "Hinesville SA- U15-Long County"),
            ("Coastal Outreach CYCLONES 13UG", "Coastal Outreach CYCLONES U13"),
            ("Piedmont SA 16U - Premier", "Piedmont SA U16 - Premier"),
            ("Alianza Soccer 14/15 Gold Pre-GPL", "Alianza Soccer 14/15 Gold GPL"),
            ("Hinesville SA-B14", "Hinesville SA-U14"),
            ("Hinesville SA-B15-Long County", "Hinesville SA-U15-Long County"),
            ("Atlanta City FC - B12 Pre-GPL", "Atlanta City FC - U12 GPL"),
        ],
    )
    def test_a_league_form_is_respelled(self, name, prepared):
        assert _matcher()._prepared(name) == prepared

    @pytest.mark.parametrize(
        "name",
        ["Savannah United B13/14", "B2014", "UMA FC U12B", "BVB IA Georgia - PTC 14/15", "BVB14 Blue"],
    )
    def test_a_form_it_can_read_is_left_alone(self, name):
        assert _matcher()._prepared(name) == name


class TestClub:
    @pytest.mark.parametrize(
        "team_name, club",
        [
            ("BVB IA Georgia - South 13/14 Black", "BVB IA Georgia"),
            ("BVB IA Georgia-Oconee 09/10 - CF", "BVB IA Georgia"),
            ("Savannah United 11/12B West", "Savannah United"),
            ("Atlanta City FC - B12 Pre-GPL", "Atlanta City FC"),
            ("All-In FC Sugar Hill U13B GPL", "All-IN FC Sugar Hill"),
            ("AFC Lightning Griffin U15B Red", "AFC Lightning"),
            ("Covered Bridge Soccer Club - B14U Select", "Covered Bridge Soccer Club"),
            ("Georgia Wolves - B15U- CF North", "Georgia Wolves SC"),
            ("Georgia Athletic SC - U18 B", "Georgia Athletic Soccer Club"),
            ("Hinesville SA -BU16 - CF SOUTH", "Hinesville Soccer Association"),
            ("Hinesville Soccer Association - G19U", "Hinesville Soccer Association"),
            ("Hinesville Waycross-BU19", "Hinesville Soccer Association"),
            ("TCSA United White - B18U", "Toombs County Soccer Association"),
            ("TCSA Flames - G19U", "Toombs County Soccer Association"),
            ("Coastal Outre - COS CREW14U", "Coastal Outreach Soccer Prog."),
            ("Coastal Outreach SQUAD G18U", "Coastal Outreach Soccer Prog."),
            ("Football Club OLeary - BR14U", "FC O'Leary"),
            ("Path Academy FC - B13U Gold", "PATH ACADEMY FC"),
            ("Piedmont SA 16U - Premier", "Piedmont SA"),
            ("Alianza Soccer 14/15 Gold Pre-GPL", "Alianza Soccer Club"),
            ("UMA FC U16G", "UMA FC"),
            ("Bryson Park Soccer Club U17", "Bryson Park"),
            ("Bryson Park Soccer U15 Blue", "Bryson Park"),
            ("Bryson Park Flash Soccer 2013 Black - GPL", "Bryson Park"),
            ("Troup County Lions - B15U", "Troup County Lions"),
            ("Southern Cross FC -B16U", "Southern Cross FC"),
            ("Atlanta Furious - CH/CF", "Atlanta Furious"),
            ("BC Prime", "BC Prime"),
            ("GUSA Rome 2014B", "Georgia United SA"),
            ("Champions FC Boys 13U", "Champions FC"),
            ("Champions FC Guerrero Hapeville Boys 15U", "Champions FC"),
            ("Statesboro Stars Soccer Club - B14U", "Statesboro Stars Soccer Club"),
            ("BC Blazers", "BC Blazers"),
            ("Sacred Heart Fusion 2011", "Sacred Heart Fusion"),
            ("Some New FC - B14U Gold", "Some New FC"),
            ("Some New FC 13UG", "Some New FC"),
            ("SuperHinesville U14", "SuperHinesville"),
            ("Hinesvilleton U14", "Hinesvilleton"),
            ("Hinesvılle U14", "Hinesvılle"),
        ],
    )
    def test_the_club_is_read_as_pitchrank_stores_it(self, team_name, club):
        assert _matcher()._club_for(team_name, None) == club


class TestSquadMarks:
    @pytest.mark.parametrize(
        "provider, stored",
        [
            ("BVB IA Georgia - South 13/14 Black", "BVB IA Georgia - West 13/14 Black"),
            ("BVB IA Georgia - Oconee 12/13 - CH/CF", "BVB IA Georgia - PTC 12/13"),
            ("AFC Lightning Griffin U15B Red", "AFC Lightning U15B Red"),
            ("Hinesville Waycross-BU16", "Hinesville SA -BU16"),
            ("Savannah United 13/14B Blue", "Savannah United 13/14B Red"),
            ("Coastal Outre - COS CREW14U", "Coastal Outreach U14"),
            ("Concorde Fire 2014 Pre-ECNL", "Concorde Fire 2014 ECNL"),
            ("Coastal Outre - COS CREW18U", "Coastal Outre - COS CREW19U"),
            ("Georgia Wolves - BA18U", "Georgia Wolves SC U19"),
            ("Hinesville SA-B14", "Hinesville Soccer Association U13"),
        ],
    )
    def test_different_squads_conflict(self, provider, stored):
        assert _matcher()._squads_conflict(provider, stored)

    def test_ga_stays_a_squad_word(self):
        """GA also means Girls Academy, so a stored 'GA' squad is a different squad."""
        assert _matcher()._squads_conflict("Savannah United 13/14G Blue", "Savannah United 13/14G GA Blue")

    @pytest.mark.parametrize(
        "provider, stored",
        [
            ("Atlanta City FC - BU13 GPL", "Atlanta City FC 2014B"),
            ("Atlanta City FC - B12 Pre-GPL", "Atlanta City FC U12"),
            ("BVB IA Georgia - Oconee 12/13 - CH/CF", "BVB IA Georgia Oconee 2013"),
            ("Georgia Wolves - B13U - CF", "Georgia Wolves SC 2014B"),
            ("Georgia Wolves - BA12U", "Georgia Wolves SC U12"),
            ("Football Club OLeary - BR14U", "FC O'Leary U14"),
            ("Coastal Outre - COS CREW14U", "Coastal Outreach Soccer Prog. COS CREW U14"),
            ("Hinesville SA-B14", "Hinesville Soccer Association U14"),
            ("Bryson Park Flash Soccer 2013 Black - GPL", "Bryson Park 2013 Black"),
            ("BVB IA Georgia - PTC 11/12", "BVBIA Georgia - PTC 11/12 B"),
            ("Alianza Soccer 14/15 Gold Pre-GPL", "Alianza Soccer Club 14/15 Gold GPL"),
            ("Atlanta City FC - BU13 GPL", "Atlanta City FC B14"),
        ],
    )
    def test_one_squad_written_two_ways_does_not_conflict(self, provider, stored):
        assert not _matcher()._squads_conflict(provider, stored)


class TestFuzzyMatch:
    @pytest.mark.parametrize(
        "provider, stored, club, board",
        [
            ("Atlanta City FC - BU13 GPL", "Atlanta City - B2014", "Atlanta City FC", "u13"),
            ("Georgia Wolves - B14U - CH/CF", "Georgia Wolves SC 2013B", "Georgia Wolves SC", "u14"),
            ("Georgia Athletic SC - U15 B", "Georgia Athletic SC-U15B", "Georgia Athletic Soccer Club", "u15"),
        ],
    )
    def test_a_league_tag_or_gender_letter_does_not_refuse_a_stored_squad(self, provider, stored, club, board):
        """Each pair reads as two variants, which the squad-word rule rightly does not."""
        rows = [_team(stored, club, state="GA", age_group=board)]

        assert _matcher(rows)._fuzzy_match_team(provider, board, "Male")["team_id"] == stored

    def test_a_different_squad_is_still_refused_with_the_variant_gate_off(self):
        rows = [_team("Savannah United 2013B Red", "Savannah United", state="GA", age_group="u14")]

        assert _matcher(rows)._fuzzy_match_team("Savannah United 12/13B Blue", "u14", "Male") is None

    def test_the_row_carrying_the_name_beats_a_live_duplicate_that_ties_with_it(self):
        rows = [
            _team("Savannah United 12B West", "Savannah United", state="GA", age_group="u15"),
            _team("Savannah United 11/12B West", "Savannah United", state="GA", age_group="u15"),
        ]

        match = _matcher(rows)._fuzzy_match_team("Savannah United 11/12B West", "u15", "Male")

        assert match["team_id"] == "Savannah United 11/12B West"

    def test_the_row_carrying_the_name_beats_a_merged_away_duplicate_that_ties_with_it(self):
        """The fuzzy candidates include deprecated rows, and '10B Blue' stops the squad-key match taking one row."""
        merged_away = _team("Savannah United 10B Blue", "Savannah United", state="GA", age_group="u17")
        rows = [
            {**merged_away, "is_deprecated": True},
            _team("10B Blue", "Savannah United", state="GA", age_group="u17"),
            _team("Savannah United 09/10B Blue", "Savannah United", state="GA", age_group="u17"),
        ]

        match = _matcher(rows)._fuzzy_match_team("Savannah United 09/10B Blue", "u17", "Male")

        assert match["team_id"] == "Savannah United 09/10B Blue"

    def test_stored_duplicates_with_no_exact_name_stay_refused(self):
        rows = [
            _team("UMA FC 2014-15B", "UMA FC", state="GA", age_group="u12"),
            _team("UMA FC 2014-15 Boys", "UMA FC", state="GA", age_group="u12"),
        ]

        assert _matcher(rows)._fuzzy_match_team("UMA FC U12B", "u12", "Male") is None

    def test_two_stored_rows_under_the_name_choose_neither(self):
        name = "Savannah United 09/10B Blue"
        rows = [
            _team(name, "Savannah United", state="GA", age_group="u17", team_id="one"),
            _team(name, "Savannah United", state="GA", age_group="u17", team_id="two"),
        ]

        assert _matcher(rows)._fuzzy_match_team(name, "u17", "Male") is None

    @pytest.mark.parametrize(
        "stored",
        [
            {"state": "SC"},
            {"age_group": "u16"},
            {"gender": "Female"},
        ],
    )
    def test_an_exact_name_elsewhere_is_not_this_team(self, stored):
        name = "Hinesville Waycross-BU16"
        row = _team(name, "Hinesville Soccer Association", **{"state": "GA", "age_group": "u17", **stored})

        assert _matcher([row])._stored_under_own_name(name, "u17", "Male", None) is None

    def test_a_short_name_stored_under_another_club_is_not_this_team(self):
        """The create path strips a club from a stored name, so a short stored name is not unique to one club."""
        row = _team("U13B", "Atlanta City FC", state="GA", age_group="u13")

        assert _matcher([row])._stored_under_own_name("U13B", "u13", "Male", "Savannah United") is None

    def test_a_read_failure_leaves_the_exact_name_to_the_fuzzy_match(self):
        class _Unreadable:
            def table(self, _name):
                raise RuntimeError("timed out")

        matcher = AffinityGAGameMatcher(_Unreadable(), provider_id="p")

        assert matcher._stored_under_own_name("BC Prime", "u14", "Male", None) is None

    def test_a_deprecated_row_under_the_name_is_not_this_team(self):
        name = "Hinesville Waycross-BU16"
        row = {**_team(name, "Hinesville Soccer Association", state="GA", age_group="u17"), "is_deprecated": True}

        assert _matcher([row])._stored_under_own_name(name, "u17", "Male", None) is None


class TestState:
    def test_an_unknown_club_takes_georgia(self):
        assert _matcher()._state_for_new_team("Atlanta Furious") == ("GA", "Georgia")

    def test_a_club_known_only_outside_georgia_is_still_georgias(self):
        matcher = _matcher([_team("Champions FC 2014", "Champions FC", state="CO")] * 2)

        assert matcher._state_for_club("Champions FC") == "GA"
        assert matcher._state_for_new_team("Champions FC") == ("GA", "Georgia")


class TestMatchTeam:
    """The path the importer takes, which is handed the blank club every scraped row carries."""

    @pytest.mark.parametrize(
        "team_name, stored_name, club",
        [
            ("Champions FC Boys 13U", "Boys 13U", "Champions FC"),
            ("Georgia Wolves - B13U - CF", "Georgia Wolves - B13U - CF", "Georgia Wolves SC"),
        ],
    )
    def test_a_new_team_takes_its_club_and_is_filed_in_georgia(self, team_name, stored_name, club):
        """A name that starts with its stored club is stored without it, as Oregon's and Utah's are."""
        db = _RecordingDB()
        matcher = AffinityGAGameMatcher(db, provider_id="p")

        result = matcher._match_team("p", "affinity_ga:0123456789ab", team_name, "u13", "Male", "")

        assert result["created"] is True
        assert [
            (r["team_name"], r["club_name"], r["age_group"], r["state_code"], r["state"]) for r in db.written("teams")
        ] == [(stored_name, club, "u13", "GA", "Georgia")]
        assert [(r["provider_team_id"], r["team_id_master"]) for r in db.written("team_alias_map")] == [
            ("affinity_ga:0123456789ab", result["team_id"])
        ]

    def test_a_stored_squad_is_linked_without_a_new_team(self):
        db = _RecordingDB([_team("Savannah United 2013B Blue", "Savannah United", state="GA", age_group="u14")])
        matcher = AffinityGAGameMatcher(db, provider_id="p")

        result = matcher._match_team("p", "affinity_ga:abcdef012345", "Savannah United 12/13B Blue", "u14", "Male", "")

        assert (result["matched"], result["team_id"]) == (True, "Savannah United 2013B Blue")
        assert db.written("teams") == []

    @pytest.mark.parametrize("team_name", ["Some Club U9B", "Some Club 2031B", "Some Club U13/U14"])
    def test_an_age_off_the_boards_or_two_ages_take_the_age_on_the_row(self, team_name):
        db = _RecordingDB()
        matcher = AffinityGAGameMatcher(db, provider_id="p")

        matcher._match_team("p", "affinity_ga:0123456789ab", team_name, "u13", "Male", "")

        assert [r["age_group"] for r in db.written("teams")] == ["u13"]

    def test_a_name_stating_no_age_takes_the_age_on_the_row(self):
        db = _RecordingDB()
        matcher = AffinityGAGameMatcher(db, provider_id="p")

        matcher._match_team("p", "affinity_ga:0123456789ab", "BC Blazers", "u15", "Female", "")

        assert [(r["team_name"], r["age_group"]) for r in db.written("teams")] == [("BC Blazers", "u15")]


def _source_game(provider, home, away, age_group):
    return {
        "provider": provider,
        "team_id": f"{provider}:home",
        "team_name": home,
        "opponent_id": f"{provider}:away",
        "opponent_name": away,
        "age_group": age_group,
        "gender": "Male",
        "home_away": "H",
        "goals_for": 2,
        "goals_against": 1,
        "game_date": "2026-09-12",
    }


def _transformed_game(provider, home, away, age_group):
    """The form ``_transform_game_perspective`` hands the matcher."""
    return {
        "provider": provider,
        "home_team_id": f"{provider}:home",
        "away_team_id": f"{provider}:away",
        "home_provider_id": f"{provider}:home",
        "away_provider_id": f"{provider}:away",
        "home_team_name": home,
        "away_team_name": away,
        "age_group": age_group,
        "gender": "Male",
        "home_score": 2,
        "away_score": 1,
        "game_date": "2026-09-12",
    }


def _matcher_on(cls, provider, db, alias_cache=None):
    matcher = cls(db, provider_id="p", alias_cache=alias_cache)
    matcher._provider_id_cache[provider] = "p"
    return matcher


TWO_AGE_GAMES = [
    pytest.param(
        AffinityGAGameMatcher,
        "affinity_ga",
        "Georgia Wolves - BA12U",
        "All-In FC Sugar Hill U13B GPL",
        "u12",
        "u13",
        id="georgia",
    ),
    pytest.param(
        AffinityHIGameMatcher,
        "affinity_hi",
        "17UB - FC Hawaii Red",
        "18UB - BVB IA Hawaii",
        "u17",
        "u19",
        id="hawaii",
    ),
]


@pytest.mark.parametrize("build_game", [_source_game, _transformed_game])
@pytest.mark.parametrize("cls, provider, home, away, home_board, away_board", TWO_AGE_GAMES)
class TestAGameBetweenTwoAges:
    """Each team resolves at its own age, whichever age the importer's row carries."""

    @pytest.mark.parametrize("row_age", ["home", "away"])
    def test_two_new_teams_are_each_created_at_their_own_age(
        self, build_game, cls, provider, home, away, home_board, away_board, row_age
    ):
        db = _RecordingDB()
        matcher = _matcher_on(cls, provider, db)

        record = matcher.match_game_history(
            build_game(provider, home, away, home_board if row_age == "home" else away_board)
        )

        assert record["match_status"] == "matched"
        assert [(r["team_name"], r["age_group"]) for r in db.written("teams")] == [
            (home, home_board),
            (away, away_board),
        ]

    def test_a_stored_team_is_found_at_its_own_age_not_the_rows(
        self, build_game, cls, provider, home, away, home_board, away_board
    ):
        stored = _team(home, matcher_club(cls, home), state=cls.state_code, age_group=home_board)
        db = _RecordingDB([stored])
        matcher = _matcher_on(cls, provider, db)

        record = matcher.match_game_history(build_game(provider, home, away, away_board))

        assert record["home_team_master_id"] == home
        assert [(r["team_name"], r["age_group"]) for r in db.written("teams")] == [(away, away_board)]

    def test_a_linked_team_keeps_its_link_when_the_row_carries_its_opponents_age(
        self, build_game, cls, provider, home, away, home_board, away_board
    ):
        """The path of every weekly run after the first; refused here, it would be created at the opponent's age."""
        linked = {"team_id_master": "stored", "match_method": "direct_id", "review_status": "approved"}
        db = _RecordingDB(
            [_team("Linked", "Linked Club", state=cls.state_code, age_group=home_board, team_id="stored")]
        )
        matcher = _matcher_on(cls, provider, db, alias_cache={f"{provider}:home": linked})

        record = matcher.match_game_history(build_game(provider, home, away, away_board))

        assert record["home_team_master_id"] == "stored"
        assert [r["team_name"] for r in db.written("teams")] == [away]


def matcher_club(cls, team_name):
    return cls(_DB([]), provider_id="p")._club_for(team_name, None)
