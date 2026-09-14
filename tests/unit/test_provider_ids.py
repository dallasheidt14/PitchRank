"""A provider team id that names no team must read as absent, in every spelling it arrives in.

``str(None)`` is the truthy ``"None"``, so truthiness alone is not a blank test.
"""

import pytest

from src.utils.provider_ids import clean_provider_id, is_blank_provider_id


@pytest.mark.parametrize("value", [None, "", "  ", "None", "none", "NULL"])
def test_placeholder_spellings_are_blank(value):
    assert is_blank_provider_id(value) is True


@pytest.mark.parametrize("value", ["601496", 601496])
def test_a_real_id_is_not_blank(value):
    assert is_blank_provider_id(value) is False


def test_clean_turns_a_padded_placeholder_into_empty():
    assert clean_provider_id(" None ") == ""


def test_clean_keeps_a_real_id_as_text():
    assert clean_provider_id(601496) == "601496"
