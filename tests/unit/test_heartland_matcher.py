"""Unit tests for the Heartland Soccer matcher.

It is the Tourney Central matcher searching Kansas, Missouri and stateless teams in the roster
pass, so it reuses the Athletes2Events database double.
"""

import pytest

from scripts.import_heartland import club_for_team
from src.models.heartland_matcher import REGION_SEARCH, HeartlandGameMatcher
from tests.unit.test_athletes2events_matcher import _DB, PROVIDER, _candidate

NAME = "FC Vardar U12 B Red"
CLUB = "FC Vardar"


def _matcher(db, registration_mode=True, dry_run=False):
    return HeartlandGameMatcher(db, provider_id=PROVIDER, registration_mode=registration_mode, dry_run=dry_run)


def _register(matcher, state_code=None, name=NAME, club=CLUB, team_id="2026fall-7210"):
    return matcher._match_team(
        provider_id=PROVIDER,
        provider_team_id=team_id,
        team_name=name,
        age_group="u12",
        gender="Male",
        club_name=club,
        state_code=state_code,
        written_club=club,
    )


def _twin(team_id, state_code):
    return _candidate(team_id, NAME, CLUB, age_group="u12", state_code=state_code)


def _candidate_reads(db):
    return [or_clauses for _, or_clauses, _ in db.reads("teams") if or_clauses]


class TestStatelessTeams:
    def test_a_stateless_team_links_to_its_stored_kansas_twin(self):
        db = _DB([_twin("ks-1", "KS")])

        result = _register(_matcher(db))

        assert (result["matched"], result["created"], result["team_id"]) == (True, False, "ks-1")
        assert db.writes("teams") == []
        [alias] = db.writes("team_alias_map")
        assert (alias["provider_team_id"], alias["team_id_master"]) == ("2026fall-7210", "ks-1")

    def test_a_stateless_team_links_to_its_stored_missouri_twin(self):
        db = _DB([_twin("mo-1", "MO")])

        assert _register(_matcher(db))["team_id"] == "mo-1"

    def test_a_stateless_team_with_no_twin_writes_nothing_and_is_not_created(self):
        db = _DB([_candidate("other", "Union KC 14/15B Pre ECNL Navy", "Union KC", age_group="u12", state_code="KS")])

        result = _register(_matcher(db))

        assert (result["matched"], result["created"]) == (False, False)
        assert not result.get("review")
        assert db.writes("teams") == []
        assert db.writes("team_alias_map") == []
        assert db.writes("team_match_review_queue") == []

    def test_equal_twins_in_kansas_and_missouri_go_to_review_once(self):
        db = _DB([_twin("ks-1", "KS"), _twin("mo-1", "MO")])

        result = _register(_matcher(db))

        assert (result.get("review"), result["created"]) == (True, False)
        assert db.writes("team_alias_map") == []
        [review] = db.writes("team_match_review_queue")
        assert (review["provider_team_id"], review["confidence_score"]) == ("2026fall-7210", 0.89)

    def test_a_twin_with_no_state_ties_with_a_kansas_one(self):
        db = _DB([_twin("ks-1", "KS"), _twin("none-1", None)])

        assert _register(_matcher(db)).get("review") is True

    def test_a_dry_run_writes_no_review_row(self):
        db = _DB([_twin("ks-1", "KS"), _twin("mo-1", "MO")])

        assert _register(_matcher(db, dry_run=True)).get("review") is True
        assert db.writes("team_match_review_queue") == []


class TestStatedTeams:
    def test_a_kansas_team_picks_its_kansas_twin_over_a_missouri_one(self):
        db = _DB([_twin("mo-1", "MO"), _twin("ks-1", "KS")])

        result = _register(_matcher(db), state_code="KS")

        assert (result["matched"], result["team_id"]) == (True, "ks-1")

    def test_a_kansas_team_finds_its_only_stored_twin_in_missouri(self):
        db = _DB([_twin("mo-1", "MO")])

        assert _register(_matcher(db), state_code="KS")["team_id"] == "mo-1"

    def test_a_stated_team_with_no_twin_is_created_in_its_state(self):
        db = _DB()

        result = _register(_matcher(db), state_code="KS")

        assert (result["matched"], result["created"]) == (True, True)
        [team] = db.writes("teams")
        assert (team["team_name"], team["state_code"]) == (NAME, "KS")


class TestCandidateRead:
    def test_the_roster_pass_reads_kansas_missouri_and_stateless_teams(self):
        db = _DB()

        _register(_matcher(db))

        assert _candidate_reads(db) == [(("state_code", "KS"), ("state_code", "MO"), ("state_code", None))]

    def test_the_roster_pass_reads_live_teams_of_the_age_and_gender_in_a_stable_order(self):
        db = _DB()

        _register(_matcher(db))

        ((filters, _, order),) = db.reads("teams")[-1:]
        assert filters == {"age_group": "u12", "gender": "Male", "is_deprecated": False}
        assert order == "team_id_master"
        assert {"team_id_master", "team_name", "club_name", "state_code"} <= set(db.selected("teams"))

    def test_a_twin_past_the_first_page_of_candidates_is_found(self):
        filler = [
            _candidate(f"a-{i:04d}", f"Other Club U12 {i}", "Other Club", age_group="u12", state_code="KS")
            for i in range(1000)
        ]
        db = _DB([*filler, _twin("z-twin", "MO")])

        result = _register(_matcher(db))

        assert (result["matched"], result["team_id"]) == (True, "z-twin")
        assert db.writes("teams") == []

    def test_a_failed_candidate_read_raises_rather_than_reading_as_no_match(self):
        db = _DB([_twin("ks-1", "KS")])
        db.fail_candidate_query = True

        with pytest.raises(RuntimeError):
            _register(_matcher(db))

    def test_outside_the_roster_pass_a_stateless_team_reads_no_candidates(self):
        db = _DB([_twin("ks-1", "KS")])

        result = _register(_matcher(db, registration_mode=False))

        assert result["matched"] is False
        assert _candidate_reads(db) == []

    def test_outside_the_roster_pass_a_stated_team_searches_only_its_state(self):
        db = _DB()

        _register(_matcher(db, registration_mode=False), state_code="KS")

        assert _candidate_reads(db) == [(("state_code", "KS"), ("state_code", None))]

    def test_the_search_marker_is_no_state_code(self):
        assert REGION_SEARCH not in ("KS", "MO") and len(REGION_SEARCH) != 2


KCA = "Kansas City Athletics"
TOCA = "Toca Fusion Athletic Club"
SBV = "Sporting Blue Valley"
BARE = "00000000-0000-4000-8000-0000000000b1"


def _u11(team_id, name, club):
    return _candidate(team_id, name, club, age_group="u11", state_code="KS")


def _register_u11(matcher, name, club, written, team_id="2026fall-7111"):
    return matcher._match_team(
        provider_id=PROVIDER,
        provider_team_id=team_id,
        team_name=name,
        age_group="u11",
        gender="Male",
        club_name=club,
        state_code="KS",
        written_club=written,
    )


class TestSquadWords:
    def test_another_squad_of_the_club_is_created_rather_than_linked(self):
        db = _DB([_u11("genoa", "KC Athletics Genoa u11B", "KC Athletics")])

        result = _register_u11(_matcher(db), "KC Athletics Borussia U11B", KCA, "KC Athletics")

        assert (result["matched"], result["created"]) == (True, True)
        assert result["team_id"] != "genoa"
        [team] = db.writes("teams")
        assert team["team_name"] == "KC Athletics Borussia U11B"

    def test_the_squad_a_stored_row_names_links_to_it(self):
        db = _DB([_u11("genoa", "KC Athletics Genoa u11B", "KC Athletics")])

        result = _register_u11(_matcher(db), "KC Athletics Genoa U11B", KCA, "KC Athletics", team_id="2026fall-7163")

        assert (result["matched"], result["created"], result["team_id"]) == (True, False, "genoa")
        assert db.writes("teams") == []

    def test_a_level_word_names_a_squad(self):
        db = _DB([_u11("champ", "Toca Fusion Championship BU11", TOCA)])

        result = _register_u11(_matcher(db), "TFAC BU11 Premier", TOCA, "TFAC", team_id="2026fall-7118")

        assert (result["matched"], result["created"]) == (True, True)
        assert result["team_id"] != "champ"

    @pytest.mark.parametrize(
        "name, club, written, bare_name",
        [
            pytest.param("SPORTING BV Burnley U11B", SBV, "SPORTING BV", "SPORTING BV U11B", id="club-in-both"),
            pytest.param("KCL Chelsea B15/16", "KC Legends", "KCL", "KCL 2015B", id="club-written-in-the-bare-row"),
            pytest.param("TFAC BU11 Premier", TOCA, "TFAC", "Toca Fusion BU11", id="club-stored-in-the-bare-row"),
            pytest.param("SPORTING BV Burnley U11B", SBV, "SPORTING BV", "SPORTING BV 2015B", id="bare-row-birth-year"),
            pytest.param(
                "SPORTING BV Burnley U11B", SBV, "SPORTING BV", "SPORTING BV 9U", id="bare-row-age-number-first"
            ),
            pytest.param("SPORTING BV Burnley U11B", SBV, "SPORTING BV", "S.B.V. U11B", id="bare-row-dotted-initials"),
        ],
    )
    def test_a_stored_row_naming_no_squad_goes_to_review_for_a_team_naming_one(self, name, club, written, bare_name):
        db = _DB([_u11(BARE, bare_name, club)])

        result = _register_u11(_matcher(db), name, club, written)

        assert (result.get("review"), result["created"]) == (True, False)
        assert db.writes("team_alias_map") == []
        [review] = db.writes("team_match_review_queue")
        assert (review["suggested_master_team_id"], review["confidence_score"]) == (BARE, 0.89)

    def test_a_team_naming_no_squad_links_to_a_stored_row_naming_none(self):
        db = _DB([_u11("bare", "SPORTING BV U11B", SBV)])

        result = _register_u11(_matcher(db), "SPORTING BV U11B", SBV, "SPORTING BV")

        assert (result["matched"], result["created"], result["team_id"]) == (True, False, "bare")

    def test_a_near_spelled_club_keeps_its_own_words(self):
        db = _DB([_u11("atletico", "KC Atletico 2016B", "KC Atletico")])

        result = _register_u11(_matcher(db), "KC Athletics Juventus U11B", KCA, "KC Athletics")

        assert (result["matched"], result["created"]) == (True, True)
        assert result["team_id"] != "atletico"

    def test_an_age_written_number_first_names_no_squad(self):
        matcher = _matcher(_DB())
        matcher._written_club = "SPORTING BV"

        assert matcher._names_no_squad("SPORTING BV 9U", "SPORTING BV U9B", SBV) is False

    @pytest.mark.parametrize(
        "name, stored, expected",
        [
            # Cut from the name, the club keeps the tier the written club drops, so 'Premier' is not struck.
            pytest.param("OPSC Premier U11B", "OPSC U11B", "review", id="club-cut-from-the-name"),
            # Nothing but the initials the stored row writes vouches for the club cut from the name.
            pytest.param("Lawrence Arsenal Premier U11B", "LA U11B", "review", id="club-written-as-initials"),
            # From the club table and spelled as the name writes it, the club is struck whole.
            pytest.param("KC Legends Maestros 2015/2016", "KCL Maestros B15/16", "linked", id="club-from-the-table"),
        ],
    )
    def test_the_club_the_driver_reads_decides_what_is_struck(self, name, stored, expected):
        club, written, _source, _entry = club_for_team(name)
        db = _DB([_u11(BARE, stored, club)])

        result = _register_u11(_matcher(db), name, club, written)

        outcome = "review" if result.get("review") else "linked" if result["team_id"] == BARE else "created"
        assert outcome == expected

    def test_a_code_ahead_of_a_word_the_club_cell_has_is_struck(self):
        # Only the club cell vouches for "Rush", the stored row writing the club as initials; "SWMO" goes with it.
        matcher = _matcher(_DB())
        matcher._written_club = "SWMO Rush"

        assert matcher._names_no_squad("SWMO Rush U11B", "SMR U11B", "Southwest MO Rush") is False

    def test_a_club_word_with_an_inner_capital_matches_one_written_in_capitals(self):
        matcher = _matcher(_DB())
        matcher._written_club = "McCarthy"

        assert matcher._names_no_squad("McCarthy Premier U11B", "MCCARTHY U11B", "McCarthy FC") is True

    @pytest.mark.parametrize("word", ["Under", "Boy", "Girl", "Male", "Female"])
    def test_age_and_gender_words_name_no_squad(self, word):
        matcher = _matcher(_DB())
        matcher._written_club = "KC Athletics"

        assert (
            matcher._names_another_squad(f"KC Athletics Genoa {word} 11", "KC Athletics Genoa Academy U11", KCA)
            is False
        )

    @pytest.mark.parametrize(
        "provider, candidate, club, written, other_squad",
        [
            pytest.param(
                "KC Athletics Borussia U11",
                "KC Athletics Genoa U11",
                KCA,
                "KC Athletics",
                True,
                id="two-squad-names",
            ),
            pytest.param(
                "TFAC U11 Premier",
                "Toca Fusion Championship U11",
                TOCA,
                "TFAC",
                True,
                id="two-level-words",
            ),
            pytest.param(
                "KC Athletics Genoa U11",
                "KC Athletics U11",
                KCA,
                "KC Athletics",
                False,
                id="stored-row-names-no-squad",
            ),
            pytest.param(
                "KC Athletics U11",
                "KC Athletics Genoa U11",
                KCA,
                "KC Athletics",
                False,
                id="team-names-no-squad",
            ),
            pytest.param(
                "KCL Chelsea B16/17",
                "KC Legends Chelsea Academy 2016",
                "KC Legends",
                "KCL",
                False,
                id="written-club-is-no-squad-word",
            ),
            pytest.param(
                "Kansas City Athletics Genoa U11",
                "KCA Genoa U11",
                KCA,
                None,
                False,
                id="stored-club-and-its-initials-are-no-squad-words",
            ),
            pytest.param(
                "SBV IP Tiger Sharks FC",
                "BV Tiger Sharks FC",
                "Sporting Blue Valley",
                "SBV",
                False,
                id="initials-of-part-of-the-club",
            ),
            pytest.param(
                "Union KC 15/16B Jr Prem. Academy MO",
                "Union KC 15/16B Jr Premier Acad MO",
                "Union KC",
                "Union KC",
                False,
                id="abbreviations-either-side",
            ),
            pytest.param(
                "SportingSpringfieldU12Atletico",
                "Sporting Springfield Atletico 2015",
                "Sporting Springfield",
                "SportingSpringfield",
                False,
                id="a-name-run-together",
            ),
            pytest.param(
                "KC Athletics Genoa U11",
                "KC Athletics Genoa 2015/16",
                KCA,
                "KC Athletics",
                False,
                id="ages-are-no-squad-words",
            ),
            pytest.param(
                "Union KC 15/16 Boys Pre-ECNL Navy",
                "Union KC Soccer Club Navy Pre-ECNL B2015/16",
                "Union KC",
                "Union KC",
                False,
                id="generic-club-words-are-no-squad-words",
            ),
            pytest.param(
                "BSSA 14/15 CHTA",
                "BSSA Cheetahs 2014",
                "Blue Springs Soccer Academy",
                "BSSA",
                False,
                id="four-letter-code",
            ),
            pytest.param(
                "BSSA 16/17 HVOC",
                "BSSA 16/17 TYTN",
                "Blue Springs Soccer Academy",
                "BSSA",
                True,
                id="two-four-letter-codes",
            ),
            pytest.param(
                "BSSA 13/14 HEAT",
                "BSSA Wheatley 2013",
                "Blue Springs Soccer Academy",
                "BSSA",
                True,
                id="code-keeps-the-first-letter",
            ),
            pytest.param(
                "SLS Lions 14/15",
                "SLS Legions 2014",
                "Sporting Lees Summit",
                "SLS",
                True,
                id="only-four-letter-codes-skip-letters",
            ),
            pytest.param(
                "KCL McNutt 2015",
                "KCL MCNUTT Academy 2015",
                "KC Legends",
                "KCL",
                False,
                id="capitals-inside-a-word",
            ),
            pytest.param(
                "KCL Mc Nutt 2015",
                "KCL McNutt 2015",
                "KC Legends",
                "KCL",
                False,
                id="words-run-together-on-one-side",
            ),
            pytest.param(
                "SLS O'Brien Pride 2014",
                "SLS OBrien Pride Academy 2014",
                "Sporting Lees Summit",
                "SLS",
                False,
                id="apostrophe-inside-a-word",
            ),
            pytest.param(
                "Toca Fusion Elite ECNL-RL G2011/12",
                "Toca Fusion Elite ECRL G2011/12",
                TOCA,
                "Toca Fusion",
                False,
                id="one-league-spelled-two-ways",
            ),
            pytest.param(
                "Santafe Academia 2013 Elite",
                "SANTAFÉ ACADEMIA 2013",
                "Santafe Academia",
                "Santafe Academia",
                False,
                id="accents",
            ),
            pytest.param(
                "KC Athletics Genoa U-11",
                "KC Athletics Genoa Academy U11",
                KCA,
                "KC Athletics",
                False,
                id="a-u-age-written-apart",
            ),
            pytest.param(
                "KC Athletics Genoa 2015B",
                "KC Athletics Genoa Academy U11B",
                KCA,
                "KC Athletics",
                False,
                id="birth-years-are-no-squad-words",
            ),
            pytest.param(
                "SportingSpringfieldU12 Atletico",
                "Sporting Springfield Atletico Hernandez 2014",
                "Sporting Springfield",
                "SportingSpringfield",
                False,
                id="a-u-age-glued-to-the-club",
            ),
            pytest.param(
                "Sporting Springfield U12Atletico",
                "Sporting Springfield Atletico Hernandez 2014",
                "Sporting Springfield",
                "SportingSpringfield",
                False,
                id="a-squad-word-glued-to-the-age",
            ),
            pytest.param(
                "KC Athletics Genoa BU9",
                "KC Athletics Genoa Academy 2018",
                KCA,
                "KC Athletics",
                False,
                id="single-digit-u-ages-are-no-squad-words",
            ),
            pytest.param(
                "KCL Mc Nutt 2014",
                "KCL McNutt Academy 2014",
                "KC Legends",
                "KCL",
                False,
                id="split-word-beside-an-extra-word",
            ),
            pytest.param(
                "KCL McNutt 2014",
                "KCL Mc Nutt Academy 2014",
                "KC Legends",
                "KCL",
                False,
                id="joined-word-beside-an-extra-word",
            ),
            pytest.param(
                "KC Athletics Genoa U11B",
                "KC Athletics\u2013Genoa Academy U11B",
                KCA,
                "KC Athletics",
                False,
                id="a-dash-parts-two-words",
            ),
            pytest.param(
                "SLS O\u2019Brien Pride 2014",
                "SLS OBrien Pride Academy 2014",
                "Sporting Lees Summit",
                "SLS",
                False,
                id="curly-apostrophe-inside-a-word",
            ),
            pytest.param(
                "CKU Fusion Elite 2014",
                "CKU Fusi\u00f3n Elite Academy 2014",
                "CKU Fusi\u00f3n",
                "CKU Fusion",
                False,
                id="an-accent-inside-the-club",
            ),
            pytest.param(
                "SWMO Rush Navy U11",
                "Southwest MO Rush Navy Academy 2015",
                "Southwest MO Rush",
                "SWMO Rush",
                False,
                id="written-club-through-its-first-vouched-word",
            ),
            pytest.param(
                "KCL DeLaSalle 2014",
                "KCL DELASALLE Academy 2014",
                "KC Legends",
                "KCL",
                False,
                id="a-word-with-two-inner-capitals",
            ),
            # 'Pride' leaves the stored side unmatched in both, so each case fails only when its own half of the
            # run rule goes.
            pytest.param(
                "KCL De La Salle 2014",
                "KCL DeLaSalle Pride 2014",
                "KC Legends",
                "KCL",
                False,
                id="three-words-run-together",
            ),
            pytest.param(
                "KCL DeLaSalle 2014",
                "KCL De La Salle Pride 2014",
                "KC Legends",
                "KCL",
                False,
                id="one-word-split-in-three",
            ),
            pytest.param(
                "TFAC BU11 Champ", "Toca Fusion Championship BU11", TOCA, "TFAC", False, id="a-word-cut-short"
            ),
            # Struck whole, a club cell outside the name takes "KV" with it; read as a guess, it would not.
            pytest.param(
                "Sporting KV Inter U11B",
                "SKV Inter Roma U11B",
                "Sporting Kaw Valley",
                "Sporting KV Inter",
                False,
                id="club-cell-outside-the-name",
            ),
        ],
    )
    def test_names_another_squad(self, provider, candidate, club, written, other_squad):
        matcher = _matcher(_DB())
        matcher._written_club = written

        assert matcher._names_another_squad(provider, candidate, club) is other_squad
