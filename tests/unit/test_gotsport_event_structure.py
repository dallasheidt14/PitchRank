"""Tests for the GotSport division-structure parser."""

from __future__ import annotations

from pathlib import Path

from src.tournaments.gotsport_event_structure import (
    parse_pools,
    standings_table_found,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gotsport"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


def test_parse_pools_reads_two_labelled_brackets():
    pools = parse_pools(_html("event_42433__group_365847.html"))

    assert [pool.label for pool in pools] == ["Bracket A", "Bracket B"]
    assert [pool.pool_id for pool in pools] == ["501350", "501351"]
    assert [len(pool.members) for pool in pools] == [4, 4]


def test_parse_pools_numbers_members_from_one_in_table_order():
    pools = parse_pools(_html("event_42433__group_365847.html"))

    positions = [member.standings_position for member in pools[0].members]
    assert positions == [1, 2, 3, 4]
    assert pools[0].members[0].team_name == "Rush Soccer Global 2013B Rush Select Blue"
    assert pools[0].members[0].registration_id.isdigit()


def test_parse_pools_keeps_a_label_that_is_not_a_bracket_letter():
    pools = parse_pools(_html("event_49371__group_485301.html"))

    assert [pool.label for pool in pools] == ["U-12 GOLD"]


def test_parse_pools_returns_nothing_when_there_is_no_standings_table():
    assert parse_pools("<html><body><p>no tables here</p></body></html>") == ()


def test_standings_table_found_separates_an_empty_pool_from_unreadable_markup():
    assert standings_table_found(_html("event_42433__group_365847.html")) is True
    assert standings_table_found("<html><body><table></table></body></html>") is False
