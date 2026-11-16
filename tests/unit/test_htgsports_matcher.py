"""Unit tests for the HTG Sports matcher.

It is the Tourney Central matcher with the squad-word rules, applied to every HTG event, so it reuses the
Athletes2Events database double. Each team's club and written club come from the driver's own parser, as in
production.
"""

import pytest

from scripts.import_tourneycentral_event import club_for
from src.models.heartland_matcher import HeartlandGameMatcher
from src.models.htgsports_matcher import HtgSportsGameMatcher
from src.models.squad_word_rules import SquadWordRules
from src.models.tourneycentral_matcher import TourneyCentralGameMatcher
from tests.unit.test_athletes2events_matcher import _DB, PROVIDER, _candidate

HOST = "events.htgsports.net"
KCA = "Kansas City Athletics"
BARE = "00000000-0000-4000-8000-0000000000b2"


def _register(db, name, club_cell=KCA, team_id="657001", age_group="u11", gender="Male"):
    club, written = club_for(club_cell, name, HOST)
    matcher = HtgSportsGameMatcher(db, provider_id=PROVIDER, registration_mode=True)
    return matcher._match_team(
        provider_id=PROVIDER,
        provider_team_id=team_id,
        team_name=name,
        age_group=age_group,
        gender=gender,
        club_name=club,
        state_code="KS",
        written_club=written,
    )


def _stored(team_id, name, club, age_group="u11", gender="Male"):
    return _candidate(team_id, name, club, age_group=age_group, state_code="KS", gender=gender)


def test_the_parser_guesses_a_written_club_carrying_the_squad_word():
    assert club_for(KCA, "KC Athletics Borussia U11B", HOST) == (KCA, "KC Athletics Borussia")


def test_another_squad_of_the_club_is_created_rather_than_linked():
    db = _DB([_stored("genoa", "KC Athletics Genoa u11B", "KC Athletics")])

    result = _register(db, "KC Athletics Borussia U11B")

    assert (result["matched"], result["created"]) == (True, True)
    assert result["team_id"] != "genoa"


def test_the_squad_a_stored_row_names_links_to_it():
    db = _DB([_stored("genoa", "KC Athletics Genoa u11B", "KC Athletics")])

    result = _register(db, "KC Athletics Genoa U11B")

    assert (result["matched"], result["created"], result["team_id"]) == (True, False, "genoa")


def test_a_stored_row_naming_no_squad_goes_to_review():
    db = _DB([_stored(BARE, "KC Athletics U11B", "KC Athletics")])

    result = _register(db, "KC Athletics Genoa U11B")

    assert (result.get("review"), result["created"]) == (True, False)
    [review] = db.writes("team_match_review_queue")
    assert (review["suggested_master_team_id"], review["confidence_score"]) == (BARE, 0.89)


@pytest.mark.parametrize(
    "name, stored, age_group, gender",
    [
        # The second pass gates on the written club, which carries the squad word and passes the club gate.
        pytest.param("KC Athletics IP U11B", "KC Athletics Genoa U11B", "u11", "Male", id="second-pass"),
        pytest.param(
            "KC Athletics Courage U13G", "KC Athletics Coraggio 14G", "u13", "Female", id="near-spelled-squad-word"
        ),
        # "City" is a word of the club cell, and no reason to strike "Manchester" before it.
        pytest.param(
            "KC Athletics Manchester City U12G",
            "KC Athletics Speciale 15G",
            "u12",
            "Female",
            id="squad-named-for-a-city",
        ),
        # The name canonicalises "K.C." to "KC", so the guessed club must read it as one word too.
        pytest.param(
            "K.C. Athletics Borussia U11B", "KC Athletics Genoa U11B", "u11", "Male", id="dotted-guessed-club"
        ),
    ],
)
def test_another_squad_is_created_whichever_pass_finds_the_row(name, stored, age_group, gender):
    db = _DB([_stored("other", stored, "KC Athletics", age_group, gender)])

    result = _register(db, name, age_group=age_group, gender=gender)

    assert (result["matched"], result["created"]) == (True, True)
    assert result["team_id"] != "other"


@pytest.mark.parametrize(
    "name, club_cell, bare, bare_club",
    [
        pytest.param(
            "KCA Wolfsburg U11B", "KC Athletics", "KCA U11B", "KC Athletics", id="code-the-cell-does-not-spell"
        ),
        pytest.param("K.C.L. Premier U11B", "KC Legends", "KCL U11B", "KC Legends", id="dotted-club-code"),
        pytest.param(
            "Steamer's Crew Watson U11B",
            "Steamer's Crew Soccer Club",
            "Steamers Crew U11 2015B",
            "Steamers Crew",
            id="apostrophe-in-the-club",
        ),
    ],
)
def test_a_row_naming_no_squad_goes_to_review_however_the_club_is_written(name, club_cell, bare, bare_club):
    db = _DB([_stored(BARE, bare, bare_club)])

    result = _register(db, name, club_cell)

    assert (result.get("review"), result["created"]) == (True, False)
    [review] = db.writes("team_match_review_queue")
    assert (review["suggested_master_team_id"], review["confidence_score"]) == (BARE, 0.89)


def test_the_club_cell_vouches_for_a_written_club_the_stored_row_does_not_spell():
    # "KCA" spells neither "KC" nor "Athletics", but "Kansas City Athletics" has both.
    db = _DB([_stored("kca", "KCA U11B", "KC Athletics")])

    result = _register(db, "KC Athletics U11B")

    assert (result["matched"], result["created"], result["team_id"]) == (True, False, "kca")


def test_a_match_leaves_no_filed_club_behind():
    matcher = HtgSportsGameMatcher(
        _DB([_stored("genoa", "KC Athletics Genoa U11B", "KC Athletics")]), provider_id=PROVIDER
    )
    club, written = club_for(KCA, "KC Athletics Borussia U11B", HOST)
    matcher._match_team(
        provider_id=PROVIDER,
        provider_team_id="657001",
        team_name="KC Athletics Borussia U11B",
        age_group="u11",
        gender="Male",
        club_name=club,
        state_code="KS",
        written_club=written,
    )
    matcher._written_club = "Toca Fusion"

    other_squad = matcher._names_another_squad(
        "Toca Fusion Premier BU11", "TFAC Premier BU11", "Toca Fusion Athletic Club"
    )

    assert other_squad is False


def test_a_club_cell_opening_the_name_is_struck_whole():
    # "MRSC" spells no word of "Missouri Rush", so read as a guess the club would be a squad word and a duplicate.
    db = _DB([_stored("brazil", "MRSC 15/16B Brazil", "Missouri Rush")])

    result = _register(db, "Missouri Rush 15/16B Brazil", "Missouri Rush")

    assert (result["matched"], result["created"], result["team_id"]) == (True, False, "brazil")


@pytest.mark.parametrize("matcher", [HtgSportsGameMatcher, HeartlandGameMatcher])
def test_the_rules_sit_ahead_of_the_matcher_they_extend(matcher):
    # Listed after its base, the mixin is never reached and the rules do nothing, silently.
    assert matcher.__mro__.index(SquadWordRules) < matcher.__mro__.index(TourneyCentralGameMatcher)
    assert matcher._names_another_squad is SquadWordRules._names_another_squad
