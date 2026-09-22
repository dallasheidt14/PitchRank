"""Which stored team the PlayMetrics league matcher picks for a league team name.

League names usually leave the club out ("U12 Boys Sporting") while stored names
often lead with it ("Real U12 Boys Sporting"); the rules are in
``PlayMetricsGameMatcher._fuzzy_match_team``.

Expected confidences hold under both scorers ``_calculate_match_score`` can use:
rapidfuzz, and the difflib fallback CI runs with.
"""

from unittest.mock import MagicMock

import pytest

from src.models.playmetrics_matcher import PlayMetricsGameMatcher


def _matcher(state_code, age_group, gender, stored, stored_state=None):
    db = MagicMock()
    # Every candidate must come from the seeded cache: a query here means the
    # cache key missed and the matcher judged an empty pool instead.
    db.table.side_effect = AssertionError("the candidate cache missed and the matcher queried the database")
    matcher = PlayMetricsGameMatcher(db, provider_id="playmetrics", dry_run=True)
    matcher._candidate_cache[(state_code, age_group, gender)] = [
        {
            "team_id_master": f"team-{i}",
            "team_name": name,
            "club_name": club,
            "age_group": age_group,
            "gender": gender,
            "state_code": stored_state or state_code,
        }
        for i, (name, club) in enumerate(stored)
    ]
    return matcher


def _match(team_name, club_name, state_code, age_group, gender, stored, stored_state=None):
    matcher = _matcher(state_code, age_group, gender, stored, stored_state)
    return matcher._fuzzy_match_team(team_name, age_group, gender, club_name, state_code=state_code)


def _assert_refused_for_the_word(team_name, club_name, state_code, age_group, gender, refused, accepted):
    """``refused`` is turned away, while ``accepted`` — the same row without the word — is taken."""
    assert _match(team_name, club_name, state_code, age_group, gender, [refused]) is None
    match = _match(team_name, club_name, state_code, age_group, gender, [accepted])
    assert match["team_name"] == accepted[0]


def test_the_club_written_into_a_stored_name_is_not_a_different_squad():
    stored = [("Real U12 Boys Sporting", "Real Colorado")]

    match = _match("U12 Boys Sporting", "Real Colorado", "CO", "u12", "Male", stored)

    assert match["team_name"] == "Real U12 Boys Sporting"
    assert match["confidence"] >= 0.9


def test_a_stored_name_led_by_the_club_scores_as_the_same_team():
    stored = [("Real Colorado U12 Boys Sporting", "Real Colorado")]

    match = _match("U12 Boys Sporting", "Real Colorado", "CO", "u12", "Male", stored)

    assert match["confidence"] == 1.0


def test_the_same_words_in_another_order_score_as_the_same_team():
    stored = [("Colorado Edge United U16G", "Colorado EDGE SC")]

    match = _match("U16G United", "Colorado EDGE SC", "CO", "u16", "Female", stored)

    assert match["confidence"] == 1.0


def test_a_club_joined_by_a_hyphen_is_stripped_like_a_spaced_one():
    stored = [("Real-Colorado U12 Boys Sporting", "Real Colorado")]

    match = _match("U12 Boys Sporting", "Real Colorado", "CO", "u12", "Male", stored)

    assert match["confidence"] == 1.0


def test_the_club_is_recognised_under_either_spelling():
    short_club, long_club = "Real Colorado", "Real Colorado Soccer Club"

    league_short = _match("U12 Boys Sporting", short_club, "CO", "u12", "Male", [("RCSC U12 Boys Sporting", long_club)])
    league_long = _match("RCSC U12 Boys Sporting", long_club, "CO", "u12", "Male", [("U12 Boys Sporting", short_club)])

    assert league_short["team_name"] == "RCSC U12 Boys Sporting"
    assert league_long["team_name"] == "U12 Boys Sporting"


def test_the_clubs_initials_in_a_stored_name_are_not_a_location():
    stored = [("14 CSA Charlotte King G", "Charlotte Soccer Academy")]

    match = _match("14 Charlotte King G", "Charlotte Soccer Academy", "NC", "u13", "Female", stored)

    assert match["team_name"] == "14 CSA Charlotte King G"


def test_a_name_made_only_of_club_words_is_not_scored_as_an_exact_match():
    match = _match("Real", "Real Colorado", "CO", "u12", "Male", [("Real Colorado", "Real Colorado")])

    assert match["confidence"] == pytest.approx(0.815, abs=0.001)


def test_a_different_squad_word_still_refuses_the_match():
    _assert_refused_for_the_word(
        "U12 Boys Sporting",
        "Real Colorado",
        "CO",
        "u12",
        "Male",
        refused=("Real U12 Boys Fury", "Real Colorado"),
        accepted=("Real U12 Boys Sporting", "Real Colorado"),
    )


def test_a_location_outside_the_club_name_still_refuses_the_match():
    _assert_refused_for_the_word(
        "U12 Blue",
        "Real Colorado",
        "CO",
        "u12",
        "Male",
        refused=("U12 Blue CP", "Real Colorado"),
        accepted=("Real U12 Blue", "Real Colorado"),
    )


def test_another_state_in_a_stored_name_marks_a_different_branch():
    _assert_refused_for_the_word(
        "13 (U13) CSA Charlotte King G",
        "Charlotte Soccer Academy",
        "NC",
        "u13",
        "Female",
        refused=("13 (U13) CSA NH King G", "Charlotte Soccer Academy"),
        accepted=("13 (U13) CSA Charlotte King G", "Charlotte Soccer Academy"),
    )


def test_a_direction_in_the_club_name_is_not_a_branch():
    _assert_refused_for_the_word(
        "U12 Boys Blue",
        "North Shore United",
        "IL",
        "u12",
        "Male",
        refused=("North Shore United South U12 Boys Blue", "North Shore United"),
        accepted=("North Shore United U12 Boys Blue", "North Shore United"),
    )


def test_an_abbreviated_direction_in_the_club_name_is_not_a_branch():
    _assert_refused_for_the_word(
        "U12 Boys Metro",
        "NE Surf",
        "MA",
        "u12",
        "Male",
        refused=("NE Surf South U12 Boys Metro", "NE Surf"),
        accepted=("NE Surf U12 Boys Metro", "NE Surf"),
    )


def test_an_abbreviated_direction_in_a_league_name_is_not_a_branch():
    stored = [("U12 Boys Metro", "NE Surf")]

    match = _match("NE Surf U12 Boys Metro", "NE Surf", "MA", "u12", "Male", stored)

    assert match["team_name"] == "U12 Boys Metro"


def test_a_color_in_the_club_name_is_not_the_squads_color():
    _assert_refused_for_the_word(
        "U12 Blue",
        "Red Star",
        "MI",
        "u12",
        "Male",
        refused=("Red Star U12 Gold", "Red Star"),
        accepted=("Red Star U12 Blue", "Red Star"),
    )


def test_a_tier_in_the_club_name_still_refuses_a_name_without_it():
    _assert_refused_for_the_word(
        "U14 Girls",
        "GA Rush",
        "GA",
        "u14",
        "Female",
        refused=("GA Rush U14 Girls", "GA Rush"),
        accepted=("Rush U14 Girls", "GA Rush"),
    )


def test_the_leagues_own_state_in_a_stored_name_is_not_a_branch():
    stored = [("CO Rush North 13G Academy Blue", "Colorado Rush")]

    match = _match("North U14G Academy Blue", "Colorado Rush", "CO", "u14", "Female", stored)

    assert match["team_name"] == "CO Rush North 13G Academy Blue"


def test_a_tournament_row_accepts_the_stored_teams_own_state_in_its_name():
    stored = [("CO Rush North 13G Academy Blue", "Colorado Rush")]

    match = _match("Rush North 13G Academy Blue", "Colorado Rush", None, "u14", "Female", stored, stored_state="CO")

    assert match["team_name"] == "CO Rush North 13G Academy Blue"


def test_a_clubs_initials_that_spell_a_state_are_not_a_branch():
    match = _match("Surf U12 Blue", "LA Surf", "CA", "u12", "Male", [("LA Surf U12 Blue", "LA Surf")])

    assert match["team_name"] == "LA Surf U12 Blue"


def test_the_name_as_written_breaks_a_tie_between_a_clubs_duplicate_rows():
    stored = [("U16 Girls Red", "Polonia Soccer Club"), ("Polonia U16 Girls Red", "Polonia Soccer Club")]

    match = _match("Polonia U16 Girls Red", "Polonia Soccer Club", "WI", "u16", "Female", stored)

    assert match["team_name"] == "Polonia U16 Girls Red"
