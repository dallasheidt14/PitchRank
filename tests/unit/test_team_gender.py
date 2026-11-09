"""Reading the gender a team name or a stored column states, to refuse a cross-gender link.

The names below come from team rows found holding a boys squad and a girls squad, plus the shapes
the owner's rule decides: a spelled word beating a letter, a lone squad code, a name stating both
genders, and a name stating none.
"""

import pytest

from src.utils.team_gender import gender_verdict, name_gender, row_genders, stored_gender


@pytest.mark.parametrize(
    "name,expected",
    [
        ("LFA 17/18B Red Star Swift (2036)", "Male"),
        ("LFA 17/18G Red Star Swift (2036)", "Female"),
        ("2019 Chicago Rush South Boys Premier", "Male"),
        ("U10 Chicago Rush South Premier Girls", "Female"),
        ("2019B Locomotive EPPL Keeton", "Male"),
        ("2019G Locomotive EPPL Gone", "Female"),
        ("Black Knights ''15/16G", "Female"),
        ("FW All Stars FC u7G", "Female"),
        ("Metro West Wolves 18B Williams", "Male"),
        ("BU07 Villa", "Male"),
        ("GU07 Villa", "Female"),
        ("South 18G Gold", "Female"),
        ("Saints 12B MLS Next", "Male"),
        ("La Masia SD G2013", "Female"),
        ("14UG Hawaii RUSH Azul 12/13G", "Female"),
        ("Lonestar SC STH ECNL RL STXCL G11", "Female"),
        ("U11B EUC (WHITE)", "Male"),
        ("NTX United FC U9G Paice", "Female"),
        ("Southeast-Central B2016 Predator", "Male"),
        ("BRAZAS FC 2014/2015 Boys Black", "Male"),
        ("Brazas 2015 Girls Black Pacifico", "Female"),
        ("15G Pre-GA", "Female"),
        ("B-U10B Elite", "Male"),
        # A spelled word wins over a letter.
        ("FC Dallas 2012 Girls 1B", "Female"),
        ("2009B Girls", "Female"),
        # A lone squad code is not a gender.
        ("Premier 1B", None),
        ("Strikers 5G", None),
        ("Team B1", None),
        # Both genders stated is neither.
        ("Boys and Girls Club 2014", None),
        ("U12B and 14G", None),
        # Nothing stated, and letters that are words rather than ages.
        ("U13 (13/14) Chicago Rush DPL", None),
        ("2016 Blue II", None),
        ("GA Aspire 2012", None),
        ("Bulls 2014", None),
        ("", None),
        (None, None),
    ],
)
def test_name_gender(name, expected):
    assert name_gender(name) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Male", "Male"),
        ("female", "Female"),
        (" M ", "Male"),
        ("B", "Male"),
        ("g", "Female"),
        ("Girls", "Female"),
        ("", None),
        (None, None),
        ("Coed", None),
    ],
)
def test_stored_gender_never_defaults_to_male(value, expected):
    assert stored_gender(value) == expected


@pytest.mark.parametrize(
    "record,row,expected",
    [
        (["Female"], ["Male", "Male", None], "mismatch"),
        # GotSport said Male while the record's own name said 12/13G (Hawaii RUSH Azul).
        (["Male", "Female"], ["Male"], "mismatch"),
        # A boys-named row stored as girls (LFA, Chicago Rush South).
        (["Female"], ["Female", "Male", None], "mismatch"),
        ([None, None], ["Male"], "unknown"),
        ([], [], "unknown"),
        (["Female", "Female"], ["Female", None, None], "ok"),
        (["Male"], [None, None, None], "ok"),
    ],
)
def test_gender_verdict(record, row, expected):
    assert gender_verdict(record, row) == expected


def test_row_genders_reads_the_stored_column_and_both_names():
    row = {"gender": "Female", "team_name": "Chicago Rush South Premier", "team_name_original": "2019 Rush Boys"}
    assert row_genders(row) == ("Female", None, "Male")
