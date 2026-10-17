"""The unknown-opponent auto-match never links one squad of a club's birth-year band to another."""

import pytest

from scripts import auto_match_unknown_opponents as amu
from tests.unit.test_age_token_span import _DB


def _team(team_id, name, club, age_group, gender="Male"):
    return {
        "id": 1,
        "team_id_master": team_id,
        "team_name": name,
        "club_name": club,
        "age_group": age_group,
        "gender": gender,
        "state_code": "MO",
        "is_deprecated": False,
        "provider_team_id": "999999",
    }


def _decide(unknown_name, club, age_group, candidates, gender="Male", unknown_club=None):
    db = _DB(candidates)
    row = {
        "provider_code": "gotsport",
        "unknown_provider_team_id": "754784",
        "unknown_team_name": unknown_name,
        "unknown_club_name": club if unknown_club is None else unknown_club,
        "unknown_age": age_group,
        "unknown_gender": gender,
    }
    result = amu.match_row(row, db, None, False, 160, 0.95, 0.90, {})
    assert db.executed, "match_row must fetch its candidates through the database"
    best = result["best_match"]
    return result["action"], best["team_id_master"] if best else None


@pytest.mark.parametrize(
    "unknown,candidate,club,age_group",
    [
        # The scorer refuses this pair too; the rest score at least 0.95 without the guard.
        ("SLSG MO B 2016/2017 Rennes", "SLSG MO B 2016/2017 Flamengo", "St. Louis Scott Gallagher", "u10"),
        ("Cincy SC B18-19 Elite", "Cincy SC B18-19 Premier", "Cincy SC", "u8"),
        ("TCSL Blue B2017/18 7", "TCSL Blue B2017/18 5", "St. Paul Blackhawks", "u9"),
        (
            "Legends FC (CA) PRE ECNL B2014/15 Gold",
            "Legends FC (CA) PRE ECNL B2014/15 Gold II",
            "Legends FC (CA)",
            "u12",
        ),
        ("LFA 17/18B Red Star Ace (2036)", "LFA 17/18B Red Star Tiro (2036)", "Lou Fusz Athletic", "u9"),
        ("Club B2014/15 Gold (1)", "Club B2014/15 Gold (2)", "Club", "u12"),
        ("Club B2014/15-Blue White", "Club B2014/15-Red White", "Club", "u12"),
        ("Club 2014 Navy 2", "Club 2014 Navy", "Club", "u13"),
        ("Club M08/09 Elite", "Club M08/09 Premier", "Club", "u19"),
        # A two-letter code that names no state is a squad's, in brackets or not.
        ("Club B2014/15 Blue (DA)", "Club B2014/15 Blue", "Club", "u12"),
        # Lone letters on both sides part squads unless they differ only by a gender letter.
        ("Club 2013 Maroon B", "Club 2013 Maroon C", "Club", "u13"),
        # A gender letter before the year is not a club word that hides a squad letter after it.
        ("SLSG MO B 2016/2017 Navy B", "SLSG MO B 2016/2017 Navy C", "St. Louis Scott Gallagher", "u10"),
        # The first year is the age, so a tier written between two years still parts the squads,
        # and a year repeated after the squad does not hide it.
        ("PDA G2014 Pre-ECNL G2014/15 Mon", "PDA G2014 ECNL G2014/15 Mon", "PDA", "u12"),
        (
            "Boston Athletic SC 2011 Boys 1 (2012 and 2011)",
            "Boston Athletic SC 2011 Boys 2 (2012 and 2011)",
            "Boston Athletic SC",
            "u16",
        ),
        ("Cape Coral Soccer 2009 Gold Boys RL B09", "Cape Coral Soccer 2009 Gold II Boys RL B09", "Cape Coral", "u17"),
        # A U-age joined to the band by a spaced dash leaves the band to be read, and a label that
        # is nothing but a league tag is still compared.
        ("Seacoast United - U13G -13/14 Nal", "Seacoast United - U13G -13/14 Carolina", "Seacoast United", "u13"),
        # A number up to the last birth year is a squad, not a season.
        ("Club 2014 Navy 20", "Club 2014 Navy", "Club", "u13"),
        # Each way of writing a single birth year.
        ("Club 2014 Navy 7", "Club 2014 Navy 5", "Club", "u13"),
        ("Club 14B Navy 7", "Club 14B Navy 5", "Club", "u13"),
        ("Club '14 Navy 7", "Club '14 Navy 5", "Club", "u13"),
        ("Club 14 Boys Navy 7", "Club 14 Boys Navy 5", "Club", "u13"),
        ("13 WUSC Revolution Blue", "13 WUSC Revolution Blue II", "WUSC", "u13"),
    ],
)
def test_another_squad_of_the_band_is_not_linked(unknown, candidate, club, age_group):
    candidates = [_team("wrong", candidate, club, age_group)]
    assert _decide(unknown, club, age_group, candidates) == ("no_match", None)


def test_ga_is_a_squad_word_on_a_girls_team():
    candidates = [_team("wrong", "Club G2014/15 ECNL", "Club", "u12", "Female")]
    assert _decide("Club G2014/15 GA", "Club", "u12", candidates, "Female") == ("no_match", None)


@pytest.mark.parametrize(
    "unknown,candidate,club,age_group,gender",
    [
        (
            "East Valley NSFC N1 B11/12 Walden AZ",
            "East Valley NSFC 11/12 Boys Walden",
            "East Valley/NSFC",
            "u15",
            "Male",
        ),
        (
            "East Valley FC N1 G09/10 McMullin AZ",
            "East Valley FC 09/10 Girls McMullin",
            "East Valley/NSFC",
            "u17",
            "Female",
        ),
        (
            "East Valley NSFC N1 G08/09 Walsh AZ",
            "East Valley FC 08/09 Girls Walsh",
            "East Valley/NSFC",
            "u19",
            "Female",
        ),
        (
            "MISSISSIPPI RUSH 2016/2017 BOYS MADISON PREMIER U10",
            "MS Rush 16/17B Madison Premier",
            "Mississippi Rush",
            "u10",
            "Male",
        ),
        ("TCSL Blue B2018/19 Red U8", "TCSL Blue B2018/19 Red", "Centennial Soccer Club", "u8", "Male"),
        ("Club B2014/15 Blue U12B", "Club B2014/15 Blue", "Club", "u12", "Male"),
        ("Club B2014/15 Blue U-12", "Club B2014/15 Blue U12", "Club", "u12", "Male"),
        (
            "St. Louis Fire FC - 18/19B Inferno (7v7)",
            "St. Louis Fire FC - 18/19B Inferno",
            "Saint Louis Fire FC",
            "u8",
            "Male",
        ),
        ("LFA 17/18B Red Star Ace (2036)", "LFA 17/18B Red Star Ace", "Lou Fusz Athletic", "u9", "Male"),
        ("Club B2014/15 Male Blue", "Club B2014/15 Boys Blue", "Club", "u12", "Male"),
        ("FC Dallas High Plains 2016 Boy Blue", "FC Dallas High Plains 2016 Blue", "FC Dallas", "u11", "Male"),
        ("Toledo Celtics 2008 Girl Black", "Toledo Celtics 2008 Black", "Toledo Celtics", "u19", "Female"),
        ("Toledo Celtics 2008 Female Black", "Toledo Celtics 2008 Black", "Toledo Celtics", "u19", "Female"),
        ("TCSL Blue B2014/15Black", "TCSL Blue B2014/15 Black", "St. Paul Blackhawks", "u12", "Male"),
        ("Kirkwood United 18/19B Red Hart", "Kirkwood United 18/19B Hart Red", "Kirkwood United SC", "u8", "Male"),
        ("Kirkwood United 18/19B Hart Red", "Kirkwood United 18/19B Red Hart", "Kirkwood United SC", "u8", "Male"),
        # A lone letter on one side only, or a gender letter wherever it is written, does not part
        # a squad from itself.
        ("Club 2013 Navy C", "Club 2013 Navy", "Club", "u13", "Male"),
        ("Club 2013 Navy", "Club 2013 Navy C", "Club", "u13", "Male"),
        ("Houston Surf 17/18 B Black", "Houston Surf 17/18B Black", "Houston Surf", "u9", "Male"),
        ("Houston Surf 2015B Black I", "Houston Surf 2015 Boys Black I", "Houston Surf", "u11", "Male"),
        ("Hershey SC 2010 M Elite", "Hershey SC 2010 Elite", "Hershey SC", "u17", "Male"),
        ("2009 Red B", "2009 Red", "Blackhills FC", "u19", "Male"),
        ("2009 Red", "2009 Red B", "Blackhills FC", "u19", "Male"),
        # A possessive leaves no lone "s" to set against the other side's letter.
        ("Gallos Revolution FC 2010/11's Blue", "Gallos Revolution FC 2010/11 Blue B", "Gallos", "u16", "Male"),
        # A state in brackets, a league tag beside a squad word, a spelled direction.
        ("GSA North B2014/15 White ( GA )", "GSA North B2014/15 White NPL", "GSA North", "u12", "Male"),
        ("Denver Kickers 2012 Red", "Denver Kickers 2012B RED NPL", "Denver Kickers", "u14", "Male"),
        ("Denver Kickers 2012B RED NPL", "Denver Kickers 2012 Red", "Denver Kickers", "u14", "Male"),
        ("Lonestar 2013 Silver Nth", "Lonestar 2013 Silver North", "Lonestar SC", "u13", "Male"),
        # Bands the band grammar refuses at an apostrophe or a U, and a reversed U-age.
        ("BUSA Frederick Boys 17/18' Green", "BUSA Frederick Boys 17/18 Green", "BUSA Frederick", "u9", "Male"),
        ("Ohio Premier Academy UA GU2016/17 Black", "Ohio Premier Academy UA G2016/17 Black", "OPA", "u10", "Female"),
        ("Kernow Storm FC B2014/15 B12U Red", "Kernow Storm FC B2014/15 Red", "Kernow Storm FC", "u12", "Male"),
        ("Club 2014 Navy 14/2015'", "Club 2014 Navy 2014/15", "Club", "u13", "Male"),
        # A season or a number past the last birth year is neither the age nor a squad.
        ("Club B2011 White 25/26", "Club 2011 White", "Club", "u16", "Male"),
        ("Club 2014 Navy 21", "Club 2014 Navy", "Club", "u13", "Male"),
        ("Revolution 2050 Academy 2014 Blue", "Revolution 2050 2014 Blue", "Club", "u13", "Male"),
        # A band spaced around its separator is still one age token.
        ("Toros FC 2015 - 16 Neon", "Toros FC 2015/16 Neon", "Toros FC", "u11", "Male"),
        # A word written before the year on one side and after it on the other.
        ("Texas Rush Academy B2014/15 Blue", "Texas Rush B2014/15 Academy Blue", "Texas Rush", "u12", "Male"),
        ("Texas Rush B2014/15 Academy Blue", "Texas Rush Academy B2014/15 Blue", "Texas Rush", "u12", "Male"),
        ("PDA G2014 Pre-ECNL G2014/15 Mon", "PDA Pre-ECNL G2014/15 Mon", "PDA", "u12", "Female"),
        # A club word after the year, which the stored club name or its initials supply.
        ("2014 Lakers Green", "2014 Green", "Lakers FC", "u13", "Male"),
        ("GH 2014 GHAA Blue", "GH 2014 Blue", "Germantown Hills Athletic Association", "u13", "Male"),
    ],
)
def test_the_same_squad_written_another_way_still_links(unknown, candidate, club, age_group, gender):
    candidates = [_team("same", candidate, club, age_group, gender)]
    assert _decide(unknown, club, age_group, candidates, gender) == ("auto_link", "same")


@pytest.mark.parametrize(
    "unknown,wrong,right,club,age_group",
    [
        ("Cincy SC B18-19 Elite", "Cincy SC B18-19 Premier", "Cincy SC 2018/19 Boys Elite", "Cincy SC", "u8"),
        (
            "PDA G2014 Pre-ECNL G2014/15 Mon",
            "PDA G2014 ECNL G2014/15 Mon",
            "PDA G2014 Pre-ECNL G2014/15 Mon",
            "PDA",
            "u12",
        ),
    ],
)
def test_another_squad_does_not_block_the_squads_own_row(unknown, wrong, right, club, age_group):
    candidates = [_team("wrong", wrong, club, age_group), _team("right", right, club, age_group)]
    assert _decide(unknown, club, age_group, candidates) == ("auto_link", "right")


def test_the_candidates_own_club_name_is_read_when_the_unknown_has_none():
    candidates = [_team("utd", "Kirkwood Elite Soccer Academy 2014 Utd Green", "Kirkwood Utd", "u13")]
    decision = _decide("Kirkwood Elite Soccer Academy 2014 Green", "Kirkwood Utd", "u13", candidates, unknown_club="")
    assert decision == ("review", "utd")


def test_a_candidate_with_no_club_name_is_still_read():
    candidates = [_team("five", "Club 2014 Navy 5", None, "u13")]
    assert _decide("Club 2014 Navy 7", "Club", "u13", candidates, unknown_club="") == ("no_match", None)


def test_a_leading_season_is_not_the_age():
    candidates = [_team("green", "Lakers 2014 Green", "Lakers FC", "u13")]
    assert _decide("25 Spring Lakers 2014 Green", "Lakers FC", "u13", candidates) == ("review", "green")


@pytest.mark.parametrize(
    "unknown,candidate",
    [("SLSG MO B 2016/2017", "SLSG MO B 2016/2017 Elite"), ("SLSG MO B 2016/2017 Elite", "SLSG MO B 2016/2017")],
)
def test_a_name_with_no_squad_after_its_year_is_left_to_the_scorer(unknown, candidate):
    candidates = [_team("slsg", candidate, "St. Louis Scott Gallagher", "u10")]
    assert _decide(unknown, "St. Louis Scott Gallagher", "u10", candidates) == ("auto_link", "slsg")


@pytest.mark.parametrize(
    "unknown,candidate", [("Lakers FC 2016 Green", "Lakers FC Green"), ("Lakers FC Green", "Lakers FC 2016 Green")]
)
def test_a_name_with_no_year_is_left_to_the_scorer(unknown, candidate):
    candidates = [_team("green", candidate, "Lakers FC", "u11")]
    assert _decide(unknown, "Lakers FC", "u11", candidates) == ("auto_link", "green")


def test_a_name_past_the_band_scan_limit_is_left_to_the_scorer():
    candidates = [_team("five", "Club 2014 Navy 5 " + "x" * 200, "Club", "u13")]
    assert _decide("Club 2014 Navy 7 " + "x" * 200, "Club", "u13", candidates) == ("auto_link", "five")
