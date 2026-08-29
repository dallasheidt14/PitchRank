"""Unit tests for find_queue_matches.has_protected_division token matching.

The AD, HD and EA division markers are whole tokens. They were tested as bare
substrings, so any name whose second-or-later word merely began with those
letters -- EAST, EAGLES, ADAMS -- read as a protected division and was withheld
from every caller with no log line (IMP-135). These tests pin the token
boundary: the ordinary words stay eligible while the real markers keep their
protection.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT))

import pytest  # noqa: E402

from find_queue_matches import has_protected_division  # noqa: E402


@pytest.mark.parametrize(
    "name",
    [
        "FC EAST 2012",
        "SC EAGLES 2013",
        "EAST MEADOW 2012",
        "Solar East 19B Campos Blue",
        "Calexico Earthquakes 2018",
        "FSA Timberwolves 2016GR (L Adams NR)",
        "U14 FC Tampa Rangers Adam",
        "Eastside FC 2015",
        "HDS EAGLES U10 PREMIER",
    ],
)
def test_ordinary_words_are_not_protected(name):
    assert has_protected_division(name) is False


@pytest.mark.parametrize(
    "name",
    [
        "Dallas Hornets North U15 AD",
        "Some Club HD 2012",
        "Club EA 2013",
        "Team-AD-2011",
        "Club_EA_2014",
        "MI Stars Oakland 2016/15B Pre-MLS NEXT",
        "Academy MLSNEXT 2011",
    ],
)
def test_division_markers_stay_protected(name):
    assert has_protected_division(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "ALBION SC Central Valley 2012 EA/NPL",
        "Albion SC Central Valley - 2009 NPL/EA",
        "ALBION SC Central Valley 2009 ECNL-RL/EA",
        "Albion SC Fairfield B2010 (EA)",
        "**BU12 PRE NPL (EA)",
        "SGA U15 [MLS Next HD]",
        "Copper Mountain 2013 EA/DO",
        "BU11-PRE MLS(EA MD",
    ],
)
def test_markers_punctuated_against_their_tier_stay_protected(name):
    """A marker is routinely written against the tier it qualifies, so the token
    boundary has to be any non-alphanumeric rather than whitespace alone. These are
    live rows; admitting them to matching is the cross-tier merge CLAUDE.md forbids."""
    assert has_protected_division(name) is True


def test_empty_name_is_not_protected():
    assert has_protected_division("") is False
    assert has_protected_division(None) is False
