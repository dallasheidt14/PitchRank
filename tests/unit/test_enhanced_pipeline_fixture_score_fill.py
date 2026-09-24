"""A result must fill in its unscored fixture rather than add a second row.

The fixture can carry a provider-id game_uid (it was a partial match when saved) while the
result arrives with a master-id game_uid, so only the (date, team pair) lookup can tie them.
"""

import asyncio
from types import SimpleNamespace

import pytest

from src.etl.enhanced_pipeline import EnhancedETLPipeline

DATE = "2026-09-20"
GREMIO = "b54514dc-0454-4c7f-932b-7aa644a69efc"
AFC = "5b6b37ce-031b-4e77-83eb-9a5b4e667c2f"
FIXTURE_UID = f"gotsport:{DATE}:471854:483752"
RESULT_UID = f"gotsport:{DATE}:{AFC}:{GREMIO}"


GOTSPORT_ID = "prov-gotsport"
PM_TOURNAMENT_ID = "prov-pm-tournament"
PROVIDERS = [
    {"id": GOTSPORT_ID, "code": "gotsport"},
    {"id": PM_TOURNAMENT_ID, "code": "playmetrics_tournament"},
    {"id": "prov-a2e", "code": "athletes2events"},
]


def _row(uid, home, away, home_score=None, away_score=None, excluded=False, provider=GOTSPORT_ID):
    return {
        "id": f"row-{uid}",
        "game_uid": uid,
        "provider_id": provider,
        "game_date": DATE,
        "home_team_master_id": home,
        "away_team_master_id": away,
        "home_score": home_score,
        "away_score": away_score,
        "is_excluded": excluded,
    }


class _Query:
    """Select double: applies eq/in_/or_, projects the selected columns, records at execute()."""

    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._columns = None
        self._predicates = []

    def select(self, columns):
        self._columns = [c.strip() for c in columns.split(",")]
        return self

    def eq(self, field, value):
        self._predicates.append(lambda r: r.get(field) == value)
        return self

    def in_(self, field, values):
        self._predicates.append(lambda r: r.get(field) in values)
        return self

    def or_(self, terms):
        clauses = []
        for term in terms.split(","):
            field, op, value = term.split(".", 2)
            assert op == "eq", term
            clauses.append(lambda r, f=field, v=value: r.get(f) == v)
        self._predicates.append(lambda r: any(c(r) for c in clauses))
        return self

    def __getattr__(self, name):
        raise AssertionError(f"unmodeled builder method {name!r}")

    def execute(self):
        self._db.executed.append((self._table, "select"))
        if self._table == "providers" and self._db.providers_error:
            raise self._db.providers_error
        source = self._db.games if self._table == "games" else PROVIDERS
        rows = [r for r in source if all(p(r) for p in self._predicates)]
        return SimpleNamespace(data=[{c: r[c] for c in self._columns} for r in rows])


class _Rpc:
    def __init__(self, db, name, params):
        self._db = db
        self._name = name
        self._params = params

    def execute(self):
        """Mirrors batch_backfill_null_scores: writes only rows matched by game_uid whose scores are both NULL."""
        assert self._name == "batch_backfill_null_scores", self._name
        self._db.rpc_calls.append(self._params["updates"])
        written = 0
        for u in self._params["updates"]:
            for r in self._db.games:
                if r["game_uid"] == u["game_uid"] and r["home_score"] is None and r["away_score"] is None:
                    r["home_score"], r["away_score"] = u["home_score"], u["away_score"]
                    written += 1
        return SimpleNamespace(data=written)


class _DB:
    def __init__(self, games):
        self.games = games
        self.executed = []
        self.rpc_calls = []
        self.providers_error = None

    def table(self, name):
        assert name in ("games", "providers"), name
        return _Query(self, name)

    def rpc(self, name, params):
        return _Rpc(self, name, params)


class _Matcher:
    def match_game_history(self, game):
        return {**game, "match_status": "matched"}


def _incoming(home, away, home_score, away_score, result="W"):
    return {
        "game_uid": RESULT_UID,
        "game_date": DATE,
        "home_team_master_id": home,
        "away_team_master_id": away,
        "home_provider_id": "471854",
        "away_provider_id": "483752",
        "home_score": home_score,
        "away_score": away_score,
        "result": result,
        "provider": "gotsport",
    }


def _import(monkeypatch, db, game, dry_run=False, provider="gotsport"):
    return _import_pipeline(monkeypatch, db, [game], dry_run, provider)[0]


def _import_pipeline(monkeypatch, db, games, dry_run=False, provider="gotsport"):
    pipeline = EnhancedETLPipeline(db, provider, dry_run=dry_run)
    pipeline.matcher = _Matcher()
    inserted = []
    stats = {"duplicates_skipped": 0, "skipped_empty_scores": 0, "date_mismatches": 0}

    async def validate(games):
        return games, [], stats

    async def no_uid_hits(_games):
        return set(), {}

    async def no_composite_hits(_games):
        return set()

    async def record_insert(records):
        inserted.extend(records)
        return len(records)

    async def zero(*_a, **_k):
        return 0

    monkeypatch.setattr(pipeline, "_ensure_initialized", lambda: None)
    monkeypatch.setattr(pipeline, "_validate_games", validate)
    monkeypatch.setattr(pipeline, "_check_duplicates", no_uid_hits)
    monkeypatch.setattr(pipeline, "_check_duplicates_by_composite_key", no_composite_hits)
    monkeypatch.setattr(pipeline, "_bulk_insert_games", record_insert)
    monkeypatch.setattr(pipeline, "_backfill_duplicate_team_links", zero)
    monkeypatch.setattr(pipeline, "_propagate_exclusions_to_new_games", zero)
    monkeypatch.setattr(pipeline, "_update_team_scrape_dates", zero)
    monkeypatch.setattr(pipeline, "_process_team_matching_stats", zero)
    monkeypatch.setattr(pipeline, "_log_build_metrics", zero)

    pipeline.batch_metrics = asyncio.run(pipeline.import_games(games))
    return inserted, pipeline


def test_result_fills_its_fixture_saved_under_a_provider_id_uid(monkeypatch):
    fixture = _row(FIXTURE_UID, GREMIO, AFC)
    db = _DB([fixture])

    inserted = _import(monkeypatch, db, _incoming(GREMIO, AFC, 0, 3))

    assert inserted == []
    assert [[u["game_uid"] for u in call] for call in db.rpc_calls] == [[FIXTURE_UID]]
    assert (fixture["home_score"], fixture["away_score"]) == (0, 3)


def test_a_result_oriented_the_other_way_swaps_the_scores_and_keeps_the_result(monkeypatch):
    fixture = _row(FIXTURE_UID, GREMIO, AFC)
    db = _DB([fixture])

    _import(monkeypatch, db, _incoming(AFC, GREMIO, 3, 0, result="W"))

    [[update]] = db.rpc_calls
    assert (update["home_score"], update["away_score"], update["result"]) == (0, 3, "W")
    assert (fixture["home_score"], fixture["away_score"]) == (0, 3)


@pytest.mark.parametrize(
    "existing",
    [
        pytest.param([_row(FIXTURE_UID, GREMIO, AFC), _row("gotsport:x:second", GREMIO, AFC)], id="two-fixtures"),
        pytest.param([_row(FIXTURE_UID, GREMIO, AFC), _row("gotsport:x:played", GREMIO, AFC, 1, 1)], id="one-scored"),
        pytest.param([_row(FIXTURE_UID, GREMIO, AFC, excluded=True)], id="fixture-excluded"),
    ],
)
def test_an_ambiguous_or_hidden_fixture_is_left_and_the_result_inserted(monkeypatch, existing):
    db = _DB(existing)

    inserted = _import(monkeypatch, db, _incoming(GREMIO, AFC, 0, 3))

    assert [g["game_uid"] for g in inserted] == [RESULT_UID]
    assert db.rpc_calls == []
    assert [(r["home_score"], r["away_score"]) for r in existing if r["game_uid"] == FIXTURE_UID] == [(None, None)]


def test_an_unscored_incoming_game_does_not_touch_the_fixture(monkeypatch):
    fixture = _row(FIXTURE_UID, GREMIO, AFC)
    db = _DB([fixture])

    _import(monkeypatch, db, _incoming(GREMIO, AFC, None, None))

    assert db.rpc_calls == []


def test_dry_run_neither_fills_nor_inserts(monkeypatch):
    fixture = _row(FIXTURE_UID, GREMIO, AFC)
    db = _DB([fixture])

    inserted = _import(monkeypatch, db, _incoming(GREMIO, AFC, 0, 3), dry_run=True)

    assert inserted == []
    assert db.rpc_calls == []
    assert (fixture["home_score"], fixture["away_score"]) == (None, None)


def test_a_fill_is_counted_as_a_score_backfill(monkeypatch):
    db = _DB([_row(FIXTURE_UID, GREMIO, AFC)])

    _, pipeline = _import_pipeline(monkeypatch, db, [_incoming(GREMIO, AFC, 0, 3)])

    assert (pipeline.metrics.scores_backfilled, pipeline.metrics.scores_backfill_failed) == (1, 0)
    assert (pipeline.batch_metrics.scores_backfilled, pipeline.batch_metrics.scores_backfill_failed) == (1, 0)


def test_a_fixture_whose_teams_fall_in_different_query_batches_is_filled_once(monkeypatch):
    # 60 teams on the date: the fixture's teams sort into the first and second batch of 50,
    # so the fixture comes back from both queries and must still count as one.
    fillers = [f"{i:08x}-0000-0000-0000-000000000000" for i in range(1, 59)]
    home, away = "00000000-0000-0000-0000-000000000000", "ffffffff-0000-0000-0000-000000000000"
    fixture = _row(FIXTURE_UID, home, away)
    filler_games = [
        {**_incoming(a, b, 1, 1), "game_uid": f"gotsport:{DATE}:{a}:{b}"} for a, b in zip(fillers[::2], fillers[1::2])
    ]
    db = _DB([fixture])

    inserted, _ = _import_pipeline(monkeypatch, db, [_incoming(home, away, 2, 1), *filler_games])

    assert (fixture["home_score"], fixture["away_score"]) == (2, 1)
    assert RESULT_UID not in [g["game_uid"] for g in inserted]
    assert db.executed.count(("games", "select")) == 2


def test_a_second_copy_of_the_filled_result_in_the_batch_is_not_inserted(monkeypatch):
    fixture = _row(FIXTURE_UID, GREMIO, AFC)
    db = _DB([fixture])
    copy = _incoming(AFC, GREMIO, 3, 0)

    inserted, _ = _import_pipeline(monkeypatch, db, [_incoming(GREMIO, AFC, 0, 3), copy])

    assert inserted == []
    assert (fixture["home_score"], fixture["away_score"]) == (0, 3)


def test_a_different_second_result_in_the_batch_is_inserted_not_merged(monkeypatch):
    fixture = _row(FIXTURE_UID, GREMIO, AFC)
    db = _DB([fixture])
    rematch = _incoming(GREMIO, AFC, 1, 1)

    inserted, _ = _import_pipeline(monkeypatch, db, [_incoming(GREMIO, AFC, 0, 3), rematch])

    assert [(g["home_score"], g["away_score"]) for g in inserted] == [(1, 1)]
    assert (fixture["home_score"], fixture["away_score"]) == (0, 3)


def test_a_rematch_provider_result_is_never_merged_into_another_fixture(monkeypatch):
    fixture = _row(FIXTURE_UID, GREMIO, AFC)
    db = _DB([fixture])

    inserted = _import(monkeypatch, db, _incoming(GREMIO, AFC, 0, 3), provider="playmetrics_tournament")

    assert [(g["home_score"], g["away_score"]) for g in inserted] == [(0, 3)]
    assert db.rpc_calls == []


def test_a_fixture_without_a_game_uid_is_never_the_fill_target(monkeypatch):
    fixture = _row(None, GREMIO, AFC)
    db = _DB([fixture])

    inserted = _import(monkeypatch, db, _incoming(GREMIO, AFC, 0, 3))

    assert [g["game_uid"] for g in inserted] == [RESULT_UID]
    assert db.rpc_calls == []


def test_a_result_never_fills_a_rematch_provider_fixture(monkeypatch):
    fixture = _row(FIXTURE_UID, GREMIO, AFC, provider=PM_TOURNAMENT_ID)
    db = _DB([fixture])

    inserted = _import(monkeypatch, db, _incoming(GREMIO, AFC, 0, 3))

    assert [(g["home_score"], g["away_score"]) for g in inserted] == [(0, 3)]
    assert db.rpc_calls == []


def test_a_rematch_provider_game_that_day_blocks_the_fill(monkeypatch):
    fixture = _row(FIXTURE_UID, GREMIO, AFC)
    tournament_game = _row("playmetrics_tournament:x", GREMIO, AFC, 1, 1, provider=PM_TOURNAMENT_ID)
    db = _DB([fixture, tournament_game])

    inserted = _import(monkeypatch, db, _incoming(GREMIO, AFC, 0, 3))

    assert [(g["home_score"], g["away_score"]) for g in inserted] == [(0, 3)]
    assert db.rpc_calls == []


def test_fills_are_withheld_when_the_rematch_providers_cannot_be_loaded(monkeypatch):
    db = _DB([_row(FIXTURE_UID, GREMIO, AFC)])
    db.providers_error = RuntimeError("providers unavailable")

    inserted = _import(monkeypatch, db, _incoming(GREMIO, AFC, 0, 3))

    assert [(g["home_score"], g["away_score"]) for g in inserted] == [(0, 3)]
    assert db.rpc_calls == []
