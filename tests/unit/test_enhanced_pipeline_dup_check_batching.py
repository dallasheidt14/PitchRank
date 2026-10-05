"""The game_uid duplicate check must keep each request under the URL length PostgREST accepts."""

import asyncio
import uuid

from src.etl.enhanced_pipeline import EnhancedETLPipeline

# Measured against production on 2026-10-04: 200 league UIDs (~96 chars, ~19,200 total) passed,
# 150 tournament UIDs (~114 chars, ~17,100 total) passed, 200 tournament UIDs (~22,800) were
# rejected with a 400. The double refuses anything past the midpoint of what failed and passed.
MAX_IN_LIST_CHARS = 21_000


class _Query:
    def __init__(self, db):
        self.db = db
        self.uids = None

    def select(self, *_a):
        return self

    def in_(self, column, values):
        assert column == "game_uid"
        self.uids = list(values)
        return self

    def execute(self):
        if sum(len(u) for u in self.uids) > MAX_IN_LIST_CHARS:
            raise RuntimeError("{'message': 'JSON could not be generated', 'code': 400}")
        self.db.executed.append(self.uids)
        return type("R", (), {"data": []})()


class _Db:
    def __init__(self):
        self.executed = []

    def table(self, name):
        assert name == "games"
        return _Query(self)


def _tournament_uid(n):
    return f"playmetrics_tournament:2026-10-03:{uuid.uuid4()}:{uuid.uuid4()}:{233000 + n}"


def test_tournament_length_uids_are_checked_in_batches_of_100():
    db = _Db()
    pipeline = EnhancedETLPipeline.__new__(EnhancedETLPipeline)
    pipeline.supabase = db
    games = [{"game_uid": _tournament_uid(n)} for n in range(250)]

    asyncio.run(pipeline._check_duplicates(games))

    assert [len(chunk) for chunk in db.executed] == [100, 100, 50]
    assert sorted(u for chunk in db.executed for u in chunk) == sorted(g["game_uid"] for g in games)
