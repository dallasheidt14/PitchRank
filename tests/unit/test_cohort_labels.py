"""``read_label`` expectations.

Every expectation is a literal, pinned at the 2026-27 season, and checked against
the age table and label key in CLAUDE.md: a two-year band is named by its younger
year, a single birth year ``Y`` is ``2026 - Y + 1``, and U18 files into U19.
"""

from __future__ import annotations

import pytest

from src.tournaments.cohort_labels import read_label

SEASON = 2026


@pytest.mark.parametrize(
    ("label", "cohorts", "genders"),
    [
        ("U14 Boys", {"u14"}, {"Male"}),
        ("BU14", {"u14"}, {"Male"}),
        ("U14B", {"u14"}, {"Male"}),
        ("U14M", {"u14"}, {"Male"}),
        ("U12F", {"u12"}, {"Female"}),
        ("GU12", {"u12"}, {"Female"}),
        ("U13 B D1", {"u13"}, {"Male"}),
        ("U13 G", {"u13"}, {"Female"}),
        ("13U B Gold", {"u13"}, {"Male"}),
        ("U 15 Boys", {"u15"}, {"Male"}),
        ("Under 15 Girls", {"u15"}, {"Female"}),
        ("B2013/2014", {"u13"}, {"Male"}),
        ("B13/14", {"u13"}, {"Male"}),
        ("2014/2015 Boys", {"u12"}, {"Male"}),
        ("2014-2015 Girls", {"u12"}, {"Female"}),
        ("2014–2015 Girls", {"u12"}, {"Female"}),
        ("G2015/2016", {"u11"}, {"Female"}),
        ("B2017/18", {"u9"}, {"Male"}),
        ("13/14 Boys", {"u13"}, {"Male"}),
        ("14/13 Girls", {"u13"}, {"Female"}),
        ("17/18 Boys", {"u9"}, {"Male"}),
        ("B2013", {"u14"}, {"Male"}),
        ("14B", {"u13"}, {"Male"}),
        ("Boys 2012", {"u15"}, {"Male"}),
        ("Male 2013", {"u14"}, {"Male"}),
        ("U18", {"u19"}, set()),
        ("U15/16", {"u15", "u16"}, set()),
        ("U8/U9", {"u8", "u9"}, set()),
        ("U12G (AUG 1, 2014 - JULY 31, 2015)", {"u12"}, {"Female"}),
    ],
)
def test_reads_the_cohorts_and_genders_a_label_names(label, cohorts, genders):
    reading = read_label(label, season=SEASON)

    assert reading.cohorts == frozenset(cohorts)
    assert reading.genders == frozenset(genders)


@pytest.mark.parametrize(("label", "cohort"), [("U13 Gold B2", "u13"), ("U12 Flight G1", "u12")])
def test_a_bracket_token_is_neither_a_birth_year_nor_a_gender(label, cohort):
    reading = read_label(label, season=SEASON)

    assert reading.cohort == cohort
    assert reading.genders == frozenset()
    assert label.split()[-1] in reading.leftover, "the bracket is left for the caller, not consumed"


@pytest.mark.parametrize(("label", "genders"), [("U12 B", {"Male"}), ("U13 G D1", {"Female"})])
def test_a_letter_standing_after_the_age_is_a_gender_but_not_a_firm_one(label, genders):
    reading = read_label(label, season=SEASON)

    assert reading.genders == frozenset(genders)
    assert reading.gender_is_firm is False


@pytest.mark.parametrize("label", ["U11 B/G", "U11B/G", "BU11/G"])
def test_two_gender_letters_name_both_firmly(label):
    reading = read_label(label, season=SEASON)

    assert reading.genders == frozenset({"Male", "Female"})
    assert reading.gender_is_firm is True
    assert reading.leftover == ()


def test_a_standing_letter_used_as_the_gender_is_consumed():
    assert read_label("U13 G D1", season=SEASON).leftover == ("D1",)


def test_a_standing_letter_a_firmer_gender_outranks_stays_a_word():
    assert read_label("U12G B Black", season=SEASON).leftover == ("B", "Black")


@pytest.mark.parametrize("label", ["Men\u00fc U12", "U12 Boys\u00e9", "U12 Mixed\u00e9s"])
def test_a_gender_word_inside_a_longer_word_is_not_a_gender(label):
    assert read_label(label, season=SEASON).genders == frozenset()


def test_a_decomposed_accent_is_one_word():
    reading = read_label("Girls U12 Nin\u0303as", season=SEASON)

    assert reading.leftover == ("Ni\u00f1as",)


@pytest.mark.parametrize("label", ["2025-2026 Spring Gold", "2025/26 Premier", "22/23 Boys"])
def test_a_season_pair_names_no_cohort(label):
    assert read_label(label, season=SEASON).cohorts == frozenset()


@pytest.mark.parametrize(
    ("label", "worded"), [("Boys 2012", True), ("Coed U14", True), ("B2013", False), ("U12 B", False)]
)
def test_whether_a_word_names_the_gender_is_reported(label, worded):
    assert read_label(label, season=SEASON).gender_from_word is worded


@pytest.mark.parametrize("label", ["Girls U12 B Bracket", "Girls U14 B"])
def test_a_gender_word_outranks_a_letter_standing_after_the_age(label):
    reading = read_label(label, season=SEASON)

    assert reading.genders == frozenset({"Female"})
    assert reading.gender_is_firm is True


@pytest.mark.parametrize("label", ["Boy\u017f U14", "M\u0131xed U12", "G\u0130rls U12"])
def test_a_unicode_look_alike_of_a_gender_word_does_not_break_the_reading(label):
    reading = read_label(label, season=SEASON)

    assert reading.genders <= {"Male", "Female"}
    assert len(reading.cohorts) == 1


def test_an_accented_word_counts_as_one_word():
    assert read_label("Girls U12 Ni\u00f1as \u00c9lite", season=SEASON).leftover == ("Ni\u00f1as", "\u00c9lite")


def test_a_band_counts_as_its_younger_birth_year():
    assert read_label("B2013/2014", season=SEASON).birth_years == frozenset({2014})
    assert read_label("B2013", season=SEASON).birth_years == frozenset({2013})
    assert read_label("U13 Boys", season=SEASON).birth_years == frozenset()


def test_a_very_long_label_reads_in_linear_time():
    import time

    started = time.perf_counter()
    read_label("boys " * 20_000, season=SEASON)
    read_label("U12 Boys Gold B " * 7_000, season=SEASON)

    assert time.perf_counter() - started < 2, "leftover counting went quadratic again"


@pytest.mark.parametrize("label", ["Boys/Girls U13", "Coed U14", "U14 Girls and Boys", "Mixed U12"])
def test_a_label_naming_both_genders_names_no_single_gender(label):
    reading = read_label(label, season=SEASON)

    assert reading.genders == frozenset({"Male", "Female"})
    assert reading.gender == ""


def test_a_label_naming_two_cohorts_names_no_single_cohort():
    reading = read_label("U15/16 Boys", season=SEASON)

    assert reading.cohort == ""
    assert reading.gender == "Male"


def test_a_u_age_beats_the_years_beside_it():
    assert read_label("U12 2013/2014", season=SEASON).cohorts == frozenset({"u12"})


def test_an_unboarded_year_keeps_its_own_literal():
    reading = read_label("2026 Spring Cup", season=SEASON)

    assert reading.cohorts == frozenset({"by2026"})
    assert reading.has_u_age is False


def test_a_label_naming_no_age_names_nothing():
    reading = read_label("Gold Bracket", season=SEASON)

    assert reading.cohorts == frozenset()
    assert reading.genders == frozenset()
    assert reading.leftover == ("Gold", "Bracket")


def test_leftover_words_are_what_the_reading_did_not_consume():
    assert read_label("Tyler FC Boys U14 Black", season=SEASON).leftover == ("Tyler", "FC", "Black")


def test_the_season_moves_a_birth_year_and_a_band():
    assert read_label("B2014", season=2027).cohorts == frozenset({"u14"})
    assert read_label("B2013/2014", season=2027).cohorts == frozenset({"u14"})
