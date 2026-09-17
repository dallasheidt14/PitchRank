"""Unit tests for gender resolution from a GotSport division or bracket label.

A ``B``/``G``/``M``/``F`` plays two unrelated roles in these labels, and telling
them apart is the whole job: it is the provider's gender marker when it belongs
to the age token, and a bracket or flight name anywhere else.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from src.scrapers.gotsport import _parse_division_gender, extract_event_teams_by_bracket_from_soup


@pytest.mark.parametrize(
    "division",
    [
        "14U Girls B",
        "18/19U Girls A/B",
        "U14 Girls Bracket B",
        "Girls U13 Gold B",
    ],
)
def test_gender_word_wins_over_a_standalone_bracket_letter(division):
    assert _parse_division_gender(division) == "Girls"


def test_boys_word_wins_over_a_standalone_bracket_letter():
    assert _parse_division_gender("U12 Boys Bracket G") == "Boys"


@pytest.mark.parametrize(
    ("division", "expected"),
    [("U14G Boys", "Boys"), ("U12B Girls Bracket B", "Girls")],
)
def test_gender_word_outranks_a_contradicting_age_letter(division, expected):
    """Pins the branch ORDER, which is the whole point of this parser.

    Every other case here agrees whichever branch runs first, so without a
    label where the two disagree the ordering is free to flip unnoticed.
    """
    assert _parse_division_gender(division) == expected


@pytest.mark.parametrize(
    ("division", "expected"),
    [("U14 Male", "Boys"), ("U14 Female", "Girls")],
)
def test_male_and_female_words_resolve_gender(division, expected):
    """Pins the leading ``\\b`` on the Boys pattern.

    ``male`` is a substring of ``female``, so without it both patterns match
    ``U14 Female`` and the label reads as naming two genders.
    """
    assert _parse_division_gender(division) == expected


@pytest.mark.parametrize(
    ("division", "expected"),
    [
        ("U14G", "Girls"),
        ("U12B", "Boys"),
        ("SUPER PRO - U12B", "Boys"),
        ("11v11 U14B Bronze", "Boys"),
        ("U11G 11U 2014 G Cities", "Girls"),
        ("u12b bronze", "Boys"),
        ("14UB Silver", "Boys"),
        ("12UG Gold", "Girls"),
    ],
)
def test_letter_attached_after_the_age_resolves_gender(division, expected):
    assert _parse_division_gender(division) == expected


@pytest.mark.parametrize(
    ("division", "expected"),
    [
        ("BU11 White B", "Boys"),
        ("GU11 Navy B", "Girls"),
        ("GU18/19", "Girls"),
        ("CLUBU11 White", None),
    ],
)
def test_letter_attached_before_the_age_resolves_gender(division, expected):
    """The trailing case guards the leading word boundary: without it the ``B``
    ending ``CLUB`` reads as the gender of every team in the division."""
    assert _parse_division_gender(division) == expected


@pytest.mark.parametrize(
    ("division", "expected"),
    [
        ("U13 B D1", "Boys"),
        ("U11 G D1", "Girls"),
        ("U17 B D1 Black", "Boys"),
        ("U10/U11 B 9v9 White", "Boys"),
        ("U10 M (B)", "Boys"),
        ("U10 F (B)", "Girls"),
    ],
)
def test_letter_standing_beside_the_age_resolves_gender(division, expected):
    """Real labels from event 44540, scraped from this parser's own pages.

    The provider corroborates the reading: ``U13 B D1`` and ``U17 B D1 Black``
    were scraped from URLs carrying ``gender=m`` and ``High School G D3`` from
    one carrying ``gender=f`` (checked 2026-09-17). The letter belongs to the
    age token here, unlike the bracket letter in ``U10 Bracket B``.
    """
    assert _parse_division_gender(division) == expected


@pytest.mark.parametrize("division", ["BU10/GU10", "GU10/BU10", "Boys/Girls U10", "U12B U12G"])
def test_label_naming_two_genders_resolves_to_neither(division):
    """A mixed division must not take the gender that happens to be spelled
    first, which would make the answer depend on the order of the label."""
    assert _parse_division_gender(division) is None


@pytest.mark.parametrize("division", ["Group B", "B", "G", "Group G", "U10 Bracket B"])
def test_standalone_letter_is_a_bracket_label_and_yields_no_gender(division):
    assert _parse_division_gender(division) is None


def test_label_carrying_no_gender_signal_yields_no_gender():
    assert _parse_division_gender("Championship Flight") is None


@pytest.mark.parametrize("division", ["5 Team 7v7 U10GvSilver", "U14Gold"])
def test_letter_running_into_a_word_is_left_unresolved(division):
    """A letter with no break after it cannot be told from the start of a word.

    ``U10GvSilver`` is a girls division and ``U14Gold`` is not, so resolving
    either way is wrong for the other. No gender loses the game; the wrong one
    aliases the team onto the opposite board.
    """
    assert _parse_division_gender(division) is None


def test_empty_label_yields_no_gender():
    assert _parse_division_gender("") is None


BRACKET_HTML = """
<html><body>
  <h3>{label}</h3>
  <div><a href="/teams/100001">Rush Select</a></div>
</body></html>
"""


# The two labels reach different sites: the header gate admits only a "U<age>"
# spelling, so "14U Girls B" falls through to the bracket-name branch. Both
# resolved gender independently before this change, and both read the trailing
# bracket letter as Boys.
@pytest.mark.parametrize("label", ["U14 Girls B", "14U Girls B"])
def test_bracket_extractor_reads_the_gender_word_not_the_bracket_letter(label):
    """Guards the two callers in the module-level bracket extractor.

    Neither had any test, which is how the same defect survived here in a worse
    form -- ``\\b(B|Boys|M|Male)\\b`` puts a lone ``B`` ahead of the word -- and
    how a ``self.`` reference inside a module-level function would have shipped
    as a NameError rather than a red test.
    """
    soup = BeautifulSoup(BRACKET_HTML.format(label=label), "html.parser")

    brackets = extract_event_teams_by_bracket_from_soup(soup, "123")

    teams = [team for bracket_teams in brackets.values() for team in bracket_teams]
    assert teams, f"fixture produced no teams: {brackets}"
    assert {team.gender for team in teams} == {"F"}
