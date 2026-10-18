"""Exclusion propagation must query a busy date in URI-sized batches, not in one oversized filter."""

import asyncio
from types import SimpleNamespace

from src.etl.enhanced_pipeline import EnhancedETLPipeline

DATE = "2026-10-17"
MAX_OR_TERMS = 100


def _team(n):
    return f"00000000-0000-0000-0000-{n:012d}"


class _Query:
    """Select/update double: refuses an or_ filter past the URI budget, records at execute()."""

    def __init__(self, db):
        self._db = db
        self._predicates = []
        self._update = None

    def select(self, _columns):
        return self

    def update(self, values):
        self._update = values
        return self

    def eq(self, field, value):
        self._predicates.append(lambda r: r.get(field) == value)
        return self

    def or_(self, terms):
        parts = terms.split(",")
        if len(parts) > MAX_OR_TERMS:
            raise ValueError("URL component 'query' too long")
        clauses = []
        for term in parts:
            field, _op, value = term.split(".", 2)
            clauses.append(lambda r, f=field, v=value: r.get(f) == v)
        self._predicates.append(lambda r: any(c(r) for c in clauses))
        return self

    def execute(self):
        rows = [r for r in self._db.games if all(p(r) for p in self._predicates)]
        if self._update is not None:
            for r in rows:
                r.update(self._update)
            self._db.updates.append((self._update, len(rows)))
            return SimpleNamespace(data=rows)
        return SimpleNamespace(data=[dict(r) for r in rows])


class _DB:
    def __init__(self, games):
        self.games = games
        self.updates = []

    def table(self, name):
        assert name == "games", name
        return _Query(self)


def _game(uid, home, away, home_score, away_score, excluded=False):
    return {
        "game_uid": uid,
        "game_date": DATE,
        "home_team_master_id": home,
        "away_team_master_id": away,
        "home_score": home_score,
        "away_score": away_score,
        "is_excluded": excluded,
    }


def _propagate(db, incoming):
    pipeline = EnhancedETLPipeline(db, "mlsnext_kitman", dry_run=False)
    return asyncio.run(pipeline._propagate_exclusions_to_new_games(incoming))


def test_busy_date_still_excludes_a_game_matching_an_excluded_one():
    incoming = [_game(f"new-{i}", _team(2 * i), _team(2 * i + 1), 1, 0) for i in range(60)]
    last = incoming[-1]
    stored = _game("old-excluded", last["home_team_master_id"], last["away_team_master_id"], 1, 0, excluded=True)
    db = _DB(incoming + [stored])

    excluded = _propagate(db, incoming)

    assert excluded == 1
    assert db.updates == [({"is_excluded": True}, 1)]
    assert sorted(g["game_uid"] for g in db.games if g["is_excluded"]) == ["new-59", "old-excluded"]


def test_busy_date_leaves_a_game_with_a_different_score_alone():
    incoming = [_game(f"new-{i}", _team(2 * i), _team(2 * i + 1), 1, 0) for i in range(60)]
    first = incoming[0]
    stored = _game("old-excluded", first["home_team_master_id"], first["away_team_master_id"], 3, 3, excluded=True)
    db = _DB(incoming + [stored])

    assert _propagate(db, incoming) == 0
    assert db.updates == []
