from datetime import date

import pytest

from scripts.scrape_modular11_ea import season_bounds
from src.models.modular11_ea_keys import (
    CLUB_STATES,
    UnknownClubError,
    club_state,
    ea_key,
    season_start_year,
    split_ea_key,
)


def test_key_round_trip():
    assert ea_key("3432", 2026) == "3432:2026"
    assert split_ea_key("3432:2026") == ("3432", 2026)


def test_unkeyed_id_is_refused():
    with pytest.raises(ValueError):
        split_ea_key("3432")


def test_season_turns_on_aug_1():
    assert season_start_year(date(2027, 7, 31)) == 2026
    assert season_start_year(date(2027, 8, 1)) == 2027


def test_scraper_window_follows_the_season():
    assert season_bounds(date(2027, 7, 31)) == ("2026-08-01 00:00:00", "2027-07-31 23:59:59")


def test_every_roster_club_has_one_state():
    assert len(CLUB_STATES) == 162
    assert all(len(s) == 2 and s.isupper() for s in CLUB_STATES.values())


def test_owner_answers():
    assert club_state("JaHBat") == "IL"
    assert club_state("United Soccer Group") == "MA"
    assert club_state("ALBION SC Santa Ana") == "CA"


def test_unknown_club_fails_loudly():
    with pytest.raises(UnknownClubError):
        club_state("Atlantis FC")
