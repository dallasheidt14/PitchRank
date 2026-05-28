import sys
from pathlib import Path

# scripts/ holds dryrun_team_distinction.py and validate_normalizer.py
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from dryrun_team_distinction import classify_distinction_problems  # noqa: E402


def test_none_distinction_has_no_problems():
    assert classify_distinction_problems(None, "Solar SC") == set()


def test_clean_color_distinction_has_no_problems():
    assert classify_distinction_problems("white", "Solar SC") == set()


def test_unknown_token_flagged():
    assert "unknown" in classify_distinction_problems("unknown", None)


def test_league_token_flagged():
    # "nl" is league-redundant; "mls" too. ad/hd are NOT flagged (Modular11 sacred).
    assert "league_token" in classify_distinction_problems("martinez|north|nl", "DKSC")
    assert "league_token" not in classify_distinction_problems("hd", "LA Bulls")
    assert "league_token" not in classify_distinction_problems("ad", "Breakers FC")


def test_club_acronym_flagged():
    # "cosc" == initials of California Odyssey Soccer Club
    assert "club_acronym" in classify_distinction_problems("cosc", "California Odyssey Soccer Club")
    # a real color is not an acronym
    assert "club_acronym" not in classify_distinction_problems("blue", "San Diego Surf Soccer Club")


def test_multi_token_flagged():
    assert "multi_token" in classify_distinction_problems("blue|alcaraz", "San Diego Surf")
    assert "multi_token" not in classify_distinction_problems("blue", "San Diego Surf")


def test_single_char_flagged():
    assert "single_char" in classify_distinction_problems("a", "Some Club")
    assert "single_char" not in classify_distinction_problems("white", "Some Club")
