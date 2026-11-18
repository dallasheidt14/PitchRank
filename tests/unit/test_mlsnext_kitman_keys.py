"""Kitman season keys, the club -> state table and the clubs that play a year up."""

import re

import pytest

from src.models import mlsnext_kitman_keys as keys
from src.models.mlsnext_kitman_keys import (
    club_state_or_blank,
    kitman_key,
    plays_up,
    refuse_raw_keys,
    split_kitman_key,
    team_ages_for_squad,
)


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


def test_the_shipped_play_up_list_names_the_earthquakes_in_kitmans_spelling():
    assert "San Jose Earthquakes" in keys.PLAY_UP_CLUBS
    assert set(keys.PLAY_UP_CLUBS) <= set(keys.CLUB_STATES), "spell a play-up club exactly as Kitman does"


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        ("u14", ("u14", "u13")),
        ("u13", ("u13", "u12")),
        ("u17", ("u17", "u16")),
        ("u19", ("u19", "u17")),
        (" U16 ", ("u16", "u15")),
    ],
)
def test_a_play_up_clubs_squad_also_takes_a_team_one_board_younger(monkeypatch, age, expected):
    monkeypatch.setitem(keys.PLAY_UP_CLUBS, "Test FC", "test")
    assert team_ages_for_squad(age, "Test FC") == expected


def test_any_other_clubs_squad_takes_only_its_own_age(monkeypatch):
    monkeypatch.delitem(keys.PLAY_UP_CLUBS, "Test FC", raising=False)
    monkeypatch.setitem(keys.PLAY_UP_CLUBS, "Test FC Two", "test")
    assert team_ages_for_squad("u14", "Test FC") == ("u14",)
    assert plays_up("test fc two") is False


def test_a_placeholder_club_never_plays_up(monkeypatch):
    monkeypatch.setitem(keys.PLAY_UP_CLUBS, "No Club Selection", "test")
    assert plays_up("No Club Selection") is False
    assert team_ages_for_squad("u14", "No Club Selection") == ("u14",)


@pytest.mark.parametrize("age", ["u١٤", "u１４", "u123", "14", ""])
def test_an_age_that_is_not_a_board_label_is_taken_as_it_is(monkeypatch, age):
    monkeypatch.setitem(keys.PLAY_UP_CLUBS, "Test FC", "test")
    assert team_ages_for_squad(age, "Test FC") == (age,)
