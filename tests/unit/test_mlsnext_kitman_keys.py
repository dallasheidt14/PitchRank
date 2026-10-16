"""Kitman season keys and the club -> state table."""

import re

import pytest

from src.models import mlsnext_kitman_keys as keys
from src.models.mlsnext_kitman_keys import club_state_or_blank, kitman_key, refuse_raw_keys, split_kitman_key


def test_key_is_squad_id_then_season():
    assert kitman_key(5747, 2026) == "5747:2026"
    assert split_kitman_key("5747:2026") == ("5747", 2026)


@pytest.mark.parametrize(
    "bad",
    [
        "5747",
        "5747:",
        ":2026",
        "٣٢:2026",
        "5747:٢٠٢٦",
        "1" * 10 + ":2026",
        "5747:26",
        "5747:2026:1",
        "5747:2026\n",
        "abc:2026",
    ],
)
def test_a_malformed_key_is_refused(bad):
    with pytest.raises(ValueError):
        split_kitman_key(bad)


def test_raw_ids_stop_the_run():
    refuse_raw_keys(["5747:2026", "9259:2026"])
    with pytest.raises(SystemExit, match="1 mlsnext_kitman ids are not season-keyed"):
        refuse_raw_keys(["5747:2026", "9259"])


def test_a_trailing_newline_is_not_a_season_key():
    with pytest.raises(SystemExit):
        refuse_raw_keys(["5747:2026\n"])


def test_club_state_reads_the_table(monkeypatch):
    monkeypatch.setitem(keys.CLUB_STATES, "Test FC", "AZ")
    assert club_state_or_blank("Test FC") == "AZ"


def test_an_unlisted_club_has_no_state(monkeypatch):
    monkeypatch.delitem(keys.CLUB_STATES, "Test FC", raising=False)
    assert club_state_or_blank("Test FC") == ""


def test_a_placeholder_club_has_no_state_even_when_listed(monkeypatch):
    monkeypatch.setitem(keys.CLUB_STATES, "No Club Selection", "AZ")
    assert club_state_or_blank("No Club Selection") == ""


def test_the_shipped_table_holds_two_letter_codes():
    assert len(keys.CLUB_STATES) > 100
    assert all(re.fullmatch(r"[A-Z]{2}", state) for state in keys.CLUB_STATES.values())
