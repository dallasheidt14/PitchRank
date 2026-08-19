"""An undeterminable gender must not become "Male".

normalize_gender() used to return "Male" for an empty or unrecognized value, so
a division label the scraper could not read produced a girls team created as
Male at confidence 1.0 with review_status approved, and nothing surfaced it.
"""

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.extract_and_import_tgs_teams import normalize_gender


@pytest.mark.parametrize("value", ["Boys", "boys", "B", "b", "Male", "m", " MALE "])
def test_boys_spellings_normalize_to_male(value):
    assert normalize_gender(value) == "Male"


@pytest.mark.parametrize("value", ["Girls", "girls", "G", "g", "Female", "f", " FEMALE "])
def test_girls_spellings_normalize_to_female(value):
    assert normalize_gender(value) == "Female"


@pytest.mark.parametrize("value", ["", None, "   ", "Coed", "Unknown", "X", "mixed"])
def test_undeterminable_gender_returns_none_rather_than_guessing(value):
    assert normalize_gender(value) is None
