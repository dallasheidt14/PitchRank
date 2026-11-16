"""Unit tests for the name primitives several roster-pass matchers share."""

import pytest

from src.models.tournament_name_gates import AGE_WORD, begins, initials


@pytest.mark.parametrize(
    "short, long, expected", [("prem", "premier", True), ("bla", "blaze", False), ("blaz", "blaze", True)]
)
def test_a_word_begins_a_longer_one_only_from_four_letters(short, long, expected):
    assert begins(short, long) is expected


def test_initials_take_each_words_first_letter():
    assert initials(["sporting", "blue", "valley"]) == "sbv"


@pytest.mark.parametrize("word", ["U9", "bu9", "U11", "gu12", "12u", "16b", "2015", "B2015", "2015G"])
def test_an_age_word(word):
    assert AGE_WORD.fullmatch(word)


@pytest.mark.parametrize("word", ["premier", "navy", "u100", "2", "u\u0663\u0662"])
def test_not_an_age_word(word):
    assert AGE_WORD.fullmatch(word) is None
