"""Guards for the user-activity retention hygiene audit.

Both functions here shipped with a bug that a table test catches instantly:
grade() reported healthy between-seasons teams as 'unranked', and the merge fold
missed every game still filed under a canonical team's deprecated predecessor.
"""

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.audit_user_interest_teams import (  # noqa: E402
    expand_to_aliases,
    grade,
    season_start,
)

TODAY = date(2026, 9, 1)
RANKED = "ranked-team"
UNRANKED = "unranked-team"


def _facts(last_game, games=10, future=0, null_scores=0):
    return {"games": games, "last_game": last_game, "future": future, "null_scores": null_scores}


@pytest.mark.parametrize(
    "today,expected",
    [
        (date(2026, 9, 1), date(2026, 8, 1)),
        (date(2026, 8, 1), date(2026, 8, 1)),
        (date(2026, 7, 31), date(2025, 8, 1)),
        (date(2026, 1, 15), date(2025, 8, 1)),
    ],
)
def test_season_start_rolls_on_august_first(today, expected):
    assert season_start(today) == expected


@pytest.mark.parametrize(
    "team_id,facts,expected",
    [
        # Defects
        (RANKED, _facts(None, games=0), "no games"),
        (RANKED, _facts(None, games=10, future=10), "no games played"),
        (RANKED, _facts("2024-05-26"), "dormant"),
        (UNRANKED, _facts("2026-08-29"), "unranked"),
        # Healthy
        (RANKED, _facts("2026-08-29"), "active this season"),
        (RANKED, _facts("2026-06-07"), "between seasons"),
        # A team between seasons has no current-season games to be rated on, so
        # its absence from rankings_full is not evidence of anything.
        (UNRANKED, _facts("2026-06-07"), "between seasons"),
        # Nearly dormant but inside the year: still just between seasons.
        (UNRANKED, _facts("2025-09-15"), "between seasons"),
    ],
)
def test_grade_classifies_against_the_season(team_id, facts, expected):
    assert grade({"team_id_master": team_id}, facts, {RANKED}, TODAY) == expected


def test_dormant_boundary_is_one_full_season():
    """365 days is still between seasons; 366 is dormant."""
    assert grade({"team_id_master": RANKED}, _facts("2025-09-01"), {RANKED}, TODAY) == "between seasons"
    assert grade({"team_id_master": RANKED}, _facts("2025-08-31"), {RANKED}, TODAY) == "dormant"


class _FakeMergeTable:
    """Stands in for supabase.table('team_merge_map') filtered by canonical_team_id."""

    def __init__(self, rows):
        self._rows = rows
        self._wanted = []

    def select(self, _columns):
        return self

    def in_(self, column, values):
        assert column == "canonical_team_id"
        self._wanted = values
        return self

    def execute(self):
        matched = [r for r in self._rows if r["canonical_team_id"] in self._wanted]
        return type("Result", (), {"data": matched})()


class _FakeSupabase:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "team_merge_map"
        return _FakeMergeTable(self._rows)


def test_expand_to_aliases_covers_predecessors_of_a_watched_survivor():
    """The common case: the survivor is watchlisted, its games sit on the old id."""
    merge_rows = [{"deprecated_team_id": "old", "canonical_team_id": "survivor"}]
    # resolve_merges leaves a survivor mapped to itself.
    canonical = {"survivor": "survivor"}

    alias_map = expand_to_aliases(_FakeSupabase(merge_rows), canonical)

    assert alias_map["old"] == "survivor", "games filed under the deprecated id must fold onto the survivor"
    assert alias_map["survivor"] == "survivor"


def test_expand_to_aliases_covers_the_survivor_when_only_the_old_id_is_watched():
    """The inverse case: a deprecated id is watchlisted; the survivor's own games still count."""
    merge_rows = [{"deprecated_team_id": "old", "canonical_team_id": "survivor"}]
    canonical = {"old": "survivor"}

    alias_map = expand_to_aliases(_FakeSupabase(merge_rows), canonical)

    assert alias_map["old"] == "survivor"
    assert alias_map["survivor"] == "survivor", "the survivor's own games must be queried too"
