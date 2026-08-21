"""A gender-prefixed U-age is an age, not a squad name.

`extract_distinctions` Pass 3 recognised `b14`, `14b` and `u14b` but had no
alternative for `gu12` / `bu08`, so those tokens fell through to Pass 4 and were
emitted as squad words. 5,568 live teams resolved to values like `grey|gu12`,
which `composeTeamDisplay` renders to a reader as "LB Gu12 Grey" — the frontend's
leakage guard only screens league tokens, not ages.

Both copies of the pass are covered: the canonical one and the one
`find_fuzzy_duplicate_teams` / `find_queue_matches` gate merges with.
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

import pytest

from src.utils.team_name_utils import resolve_distinction
from _team_distinction import extract_distinctions as extract_gate

GENDERED = [
    ("LB GU12 Grey", "grey"),
    ("BU08 WHITE", "white"),
    ("Snohomish United BU10 White", "white|snohomish|united"),
    ("GU10 Elite - Benesch", "benesch|elite"),
    ("Blackhills FC - Blackhills FC BU14 Red", "red|blackhills"),
]


class TestGenderedUAgeIsStripped:
    @pytest.mark.parametrize("name,expected", GENDERED)
    def test_resolves_without_the_age(self, name, expected):
        assert resolve_distinction(name, None, None) == expected

    @pytest.mark.parametrize("name,_expected", GENDERED)
    def test_no_age_token_survives_as_a_distinction(self, name, _expected):
        got = resolve_distinction(name, None, None) or ""
        assert not any(t.startswith(("gu", "bu")) and t[2:].isdigit() for t in got.split("|"))

    def test_single_digit_form(self):
        # "bu9", not "bu09" — the pattern must not require two digits.
        assert resolve_distinction("DCSC Red BU9", None, None) == "red|dcsc"

    def test_matches_the_plain_u_age_it_is_equivalent_to(self):
        # The whole point: GU12 and U12 name the same cohort, so a club's two
        # spellings of one squad must not resolve differently.
        assert resolve_distinction("LB GU12 Grey", None, None) == resolve_distinction(
            "LB U12 Grey", None, None
        )

    def test_merge_gate_copy_agrees(self):
        # scripts/_team_distinction.py carries its own copy of the pass and gates
        # Steps 3 and 4 with it; the two must not drift.
        assert "gu12" not in extract_gate("LB GU12 Grey")["squad_words"]
        assert extract_gate("LB GU12 Grey")["age_tokens"] == extract_gate("LB U12 Grey")["age_tokens"]


class TestNothingElseChanged:
    @pytest.mark.parametrize(
        "name,club,expected",
        [
            ("LB U12 Grey", None, "grey"),
            ("Rush 14U Red", "Rush", "red"),
            ("Blues U13 Teal", "Blues", "teal"),
            ("Blues U13 ECNL", "Blues", None),  # league still blocklisted
            ("Blues 2011 II", "Blues", "ii"),  # roman numeral squad
            ("Rush 2", "Rush", "2"),  # bare 1-10 is a squad number, not an age
        ],
    )
    def test_existing_behaviour_holds(self, name, club, expected):
        assert resolve_distinction(name, club, None) == expected

    @pytest.mark.parametrize(
        "name,expected_token",
        [("Gunners Red", "gunners"), ("Bulldogs Blue", "bulldogs"), ("Guelph SC Navy", "guelph")],
    )
    def test_club_words_beginning_with_a_gender_letter_survive(self, name, expected_token):
        # The pattern anchors on <gender letter>U<digits>; a club name that merely
        # starts with one of those letters must be untouched.
        assert expected_token in (resolve_distinction(name, None, None) or "")
