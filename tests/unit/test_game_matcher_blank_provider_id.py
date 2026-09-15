"""A blank provider team id must never resolve to a team, or become an alias.

The fixtures seed an approved alias keyed on ``"None"`` in both places the matcher reads --
the preloaded alias cache and ``team_alias_map`` -- because a guard on one alone still lets
the other resolve it.
"""

from types import SimpleNamespace

import pytest

from src.models.game_matcher import GameHistoryMatcher

SINK_ALIAS_ROW = {
    "team_id_master": "sink",
    "provider_id": "p",
    "provider_team_id": "None",
    "match_confidence": 1.0,
    "review_status": "approved",
    "match_method": "direct_id",
}


class _Query:
    """PostgREST builder double that applies its filters and records only at execute()."""

    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._op = "select"
        self._filters = []
        self._single = False

    def select(self, *_a, **_k):
        return self

    def insert(self, *_a, **_k):
        self._op = "insert"
        return self

    def update(self, *_a, **_k):
        self._op = "update"
        return self

    def eq(self, field, value):
        self._filters.append(("eq", field, value))
        return self

    def like(self, field, pattern):
        self._filters.append(("like", field, pattern))
        return self

    def ilike(self, field, pattern):
        self._filters.append(("ilike", field, pattern))
        return self

    def limit(self, *_a, **_k):
        return self

    def single(self):
        self._single = True
        return self

    def __getattr__(self, name):
        self._db.unmodeled.append(name)
        raise AttributeError(name)

    def _keeps(self, row, kind, field, value):
        cell = row.get(field)
        if kind == "eq":
            return cell == value
        needle = value.strip("%")
        if kind == "like":
            return needle in str(cell)
        return needle.lower() in str(cell).lower()

    def execute(self):
        self._db.executed.append({"table": self._table, "op": self._op, "filters": list(self._filters)})
        if self._op != "select":
            return SimpleNamespace(data=[])
        rows = [
            dict(r)
            for r in self._db.rows.get(self._table, [])
            if all(self._keeps(r, *f) for f in self._filters)
        ]
        if self._single:
            if len(rows) != 1:
                raise RuntimeError("PGRST116: JSON object requested, multiple (or no) rows returned")
            return SimpleNamespace(data=rows[0])
        return SimpleNamespace(data=rows)


class _DB:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []
        self.unmodeled = []

    def table(self, name):
        return _Query(self, name)


@pytest.fixture
def db():
    return _DB({"team_alias_map": [dict(SINK_ALIAS_ROW)]})


@pytest.fixture
def matcher(db):
    return GameHistoryMatcher(
        db,
        provider_id="p",
        alias_cache={"None": {"team_id_master": "sink", "match_method": "direct_id", "review_status": "approved"}},
    )


def _provider_team_id_filters(db):
    return [f for q in db.executed for f in q["filters"] if f[1] == "provider_team_id"]


def test_match_team_does_not_resolve_the_sentinel(db, matcher):
    result = matcher._match_team("p", "None", None, None, None)

    assert result["matched"] is False
    assert _provider_team_id_filters(db) == []
    assert db.unmodeled == []


def test_match_by_provider_id_refuses_the_sentinel_even_on_a_cache_hit(db, matcher):
    assert matcher._match_by_provider_id("p", "None") is None
    assert db.unmodeled == []


@pytest.mark.parametrize("blank", ["None", ""])
def test_create_alias_writes_nothing_for_a_blank_id(db, matcher, blank):
    matcher._create_alias(
        provider_id="p",
        provider_team_id=blank,
        team_name="Visitors",
        team_id_master="sink",
        match_method="fuzzy_auto",
        confidence=0.95,
        age_group="u13",
        gender="Male",
    )

    assert [q for q in db.executed if q["table"] == "team_alias_map"] == []
    assert db.unmodeled == []


@pytest.mark.parametrize(("provider_team_id", "queued"), [("None", False), ("98765", True)])
def test_review_queue_entry_is_only_written_for_a_real_id(provider_team_id, queued):
    db = _DB({"providers": [{"id": "p", "code": "gotsport"}]})
    matcher = GameHistoryMatcher(db, provider_id="p")

    matcher._create_review_queue_entry("p", provider_team_id, "Visitors", None, 0.8, {"match_method": "no_match"})

    inserts = [q for q in db.executed if q["table"] == "team_match_review_queue" and q["op"] == "insert"]
    assert len(inserts) == (1 if queued else 0)
    if not queued:
        assert [q for q in db.executed if q["table"] == "team_match_review_queue"] == []
    assert db.unmodeled == []


@pytest.mark.parametrize(("team_id", "opponent_id", "blank_side"), [("601496", "None", "away"), ("None", "601496", "home")])
def test_source_format_game_carries_an_empty_id_on_the_blank_side(db, matcher, team_id, opponent_id, blank_side):
    record = matcher.match_game_history(
        {
            "provider": "gotsport",
            "team_id": team_id,
            "opponent_id": opponent_id,
            "home_away": "H",
            "game_date": "2026-09-01",
            "goals_for": 1,
            "goals_against": 0,
        }
    )

    assert record[f"{blank_side}_provider_id"] == ""
    assert record[f"{blank_side}_team_master_id"] is None
    assert db.unmodeled == []


@pytest.mark.parametrize(("home_id", "away_id", "blank_side"), [("None", "601496", "home"), ("601496", "None", "away")])
def test_transformed_format_game_carries_an_empty_id_on_the_blank_side(db, matcher, home_id, away_id, blank_side):
    record = matcher.match_game_history(
        {
            "provider": "gotsport",
            "home_team_id": home_id,
            "away_team_id": away_id,
            "home_provider_id": home_id,
            "away_provider_id": away_id,
            "game_date": "2026-09-01",
            "home_score": 0,
            "away_score": 1,
        }
    )

    assert record[f"{blank_side}_provider_id"] == ""
    assert record[f"{blank_side}_team_master_id"] is None
    assert db.unmodeled == []


def test_a_real_id_still_matches_from_the_cache(db):
    matcher = GameHistoryMatcher(
        db,
        provider_id="p",
        alias_cache={"98765": {"team_id_master": "real", "match_method": "direct_id", "review_status": "approved"}},
    )

    result = matcher._match_team("p", "98765", None, None, None)

    assert result == {"matched": True, "team_id": "real", "method": "direct_id", "confidence": 1.0}
