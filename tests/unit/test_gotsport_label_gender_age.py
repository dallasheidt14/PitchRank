"""A flight letter is not a gender, and a band is named for its younger year.

Four sites in ``src/scrapers/gotsport.py`` read a cohort out of a label. Each
carried its own copy of the logic and each got it wrong in a way that reached
``teams``:

* The division reader that feeds game imports tested a bare ``B``/``G`` *before*
  the words, so ``U14 Girls Bracket B`` resolved to Boys and ``U12 Boys Flight G``
  to Girls -- while ``U14G``, the commonest spelling, matched neither branch and
  resolved to nothing.
* Two bracket/header readers ran ``\\b(B|Boys|M|Male)\\b`` ahead of the girls
  pattern, with the same result.
* The team reader defaulted to ``F`` for any value it did not recognise, so a
  payload spelling it ``Boys`` filed the team as Female.

Separately, all four read a birth year as ``\\b(20\\d{2})\\b``, which cannot see
the two-digit band clubs actually write -- ``U9 (17/18)`` -- so those teams took
the flight's age instead of their own.

Measured against live rows on 2026-09-17: 349 teams carried a gender their own
name contradicted.
"""

from pathlib import Path

import pytest

from src.scrapers.gotsport import birth_year_from_label, gender_code_from_label, gender_code_from_value


class TestGenderWordsBeatFlightLetter:
    """The regression: a trailing division letter outranked the explicit word."""

    @pytest.mark.parametrize(
        "label,expected",
        [
            ("U14 Girls Bracket B", "F"),
            ("U13 Girls Red B", "F"),
            ("GU19 Gold B", "F"),
            ("U12 Boys Flight G", "M"),
            ("U15 Boys Gold G", "M"),
        ],
    )
    def test_word_wins_over_trailing_letter(self, label, expected):
        assert gender_code_from_label(label) == expected


class TestGenderAgeAttachedLetter:
    """``U14G``/``GU19`` state a gender; the old bare-letter patterns missed them."""

    @pytest.mark.parametrize(
        "label,expected",
        [
            ("U14G", "F"),
            ("U12B", "M"),
            ("SUPER PRO - U12B", "M"),
            ("GU19", "F"),
            ("BU11", "M"),
            # Glued to the birth year rather than the U-age.
            ("Roadrunners SC G2016 White", "F"),
            ("Roadrunners SC B2017 Silver", "M"),
            ("WF ROADRUNNERS FC 16/17G BANDA", "F"),
            ("14B Navy", "M"),
        ],
    )
    def test_age_attached_letter_resolves(self, label, expected):
        assert gender_code_from_label(label) == expected


class TestGenderRefusesToGuess:
    """``None`` is the answer when the label names no gender.

    A guess here puts a team on the wrong ranking board, which is worse than
    leaving the field for another signal to fill.
    """

    @pytest.mark.parametrize("label", ["Flight B", "Bracket G", "U10 Black", "Gold Division", "", None])
    def test_unnamed_gender_is_none(self, label):
        assert gender_code_from_label(label) is None


class TestGenderFromProviderValue:
    """The same reader takes gotsport's ``display_gender`` field."""

    @pytest.mark.parametrize(
        "value,expected",
        [("Male", "M"), ("Female", "F"), ("Boys", "M"), ("Girls", "F"), ("boy", "M"), ("girl", "F")],
    )
    def test_provider_value_resolves(self, value, expected):
        assert gender_code_from_label(value) == expected


class TestBirthYearBandTakesYoungerYear:
    """A band is named by its younger year, so ``(17/18)`` is a 2018 cohort."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("U9 (17/18) Girls Navy", 2018),
            ("FC Batavia U10 (16/17) Navy", 2017),
            ("MSI U10 (16/17) Boys Gold", 2017),
            ("Sun Warriors 17/18", 2018),
            ("WF ROADRUNNERS FC 16/17G BANDA", 2017),
        ],
    )
    def test_band_resolves_to_younger_year(self, name, expected):
        assert birth_year_from_label(name) == expected

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Playmaker Futbol Academy 2017 Black", 2017),
            ("Roadrunners SC G2016 White", 2016),
            ("MUSC U13-2013 Boys (25/26)", 2013),
        ],
    )
    def test_four_digit_year_still_wins(self, name, expected):
        assert birth_year_from_label(name) == expected

    @pytest.mark.parametrize("name", ["RYSC Lara A", "Academy Boys", "U12 Navy", ""])
    def test_no_year_is_none(self, name):
        assert birth_year_from_label(name) is None

    def test_non_consecutive_pair_is_not_a_band(self):
        """``11/22`` is a jersey or a date, not a two-year cohort."""
        assert birth_year_from_label("Team 11/22 Red") is None


class TestProviderFieldKeepsBareLetters:
    """A provider's gender FIELD holds nothing but a gender, so ``m`` is the value.

    The label reader refuses a bare letter because a label can carry a flight code.
    Applying that refusal to the field as well dropped genders the payload states
    outright, which then collapsed two bracket entries into one.
    """

    @pytest.mark.parametrize(
        "value,expected",
        [("m", "M"), ("M", "M"), ("b", "M"), ("f", "F"), ("F", "F"), ("g", "F"),
         ("Male", "M"), ("Female", "F"), ("Boys", "M"), ("Girls", "F"), (" m ", "M")],
    )
    def test_bare_letter_field_resolves(self, value, expected):
        assert gender_code_from_value(value) == expected

    @pytest.mark.parametrize("value", ["", None, "Coed", "unknown", "U14 Girls Bracket B"])
    def test_field_that_is_not_a_gender_is_none(self, value):
        assert gender_code_from_value(value) is None

    def test_the_label_reader_still_refuses_a_bare_letter(self):
        """The two readers must not converge; that is the whole distinction."""
        assert gender_code_from_label("B") is None
        assert gender_code_from_value("B") == "M"


class TestBandBeatsStandaloneYear:
    """A four-digit band must resolve to its younger year like a two-digit one.

    Searching for a lone year first returns the band's LEADING year, which files
    the team a group too high -- the exact defect this module exists to prevent,
    reintroduced through the other spelling.
    """

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("FC B2014/2015", 2015),
            ("Sting G2016/2017 Red", 2017),
            ("Crossfire 2013/2014 Boys", 2014),
            ("Surf B2016/17 Academy", 2017),
        ],
    )
    def test_four_digit_band_takes_the_younger_year(self, name, expected):
        assert birth_year_from_label(name) == expected


class TestSeasonLabelIsNotABirthYear:
    """``(25/26)`` is a season, and reading it as a cohort suppressed the fallback.

    The derived age was already rejected as out of range, but a truthy birth year
    still blocked the provider's own age_group, so the team silently took the
    bracket's age instead of its own.
    """

    @pytest.mark.parametrize("name", ["United U12 (25/26) Boys", "MUSC Girls (26/27)", "Rangers 24/25 Select"])
    def test_season_label_yields_no_birth_year(self, name):
        assert birth_year_from_label(name) is None

    def test_a_founding_year_older_than_any_player_is_refused(self):
        """Only a year no current player could hold is separable.

        A recent four-digit year is genuinely ambiguous -- ``2004 Legacy FC`` could
        be either -- so the window is set to catch the unambiguous case and the
        caller's own 7..19 range check handles the rest.
        """
        assert birth_year_from_label("1998 Legacy FC") is None
        assert birth_year_from_label("Est 1976 United") is None


class TestNoBareLetterGenderPatternsRemain:
    """Structural guard: the four call sites must not regrow their own copies.

    Reading the source rather than the four call sites means a fifth reader
    added later is covered too.
    """

    BARE_LETTER_PATTERNS = [
        r"\b([BG])\b",
        r"\b(B|Boys|M|Male)\b",
        r"\b(G|Girls|F|Female)\b",
    ]

    def test_source_has_no_bare_letter_gender_regex(self):
        source = Path(__file__).resolve().parents[2] / "src" / "scrapers" / "gotsport.py"
        text = source.read_text(encoding="utf-8")
        offenders = [pattern for pattern in self.BARE_LETTER_PATTERNS if pattern in text]
        assert offenders == [], f"bare-letter gender regex reintroduced: {offenders}"
