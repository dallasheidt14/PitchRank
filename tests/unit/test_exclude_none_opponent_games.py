"""The cleanup must exclude only games the blank-id alias attached to the sink team.

It must also refuse to write when trg_propagate_game_exclusion would cascade to a twin that is
not a candidate.
"""

import sys
from types import SimpleNamespace

import pytest

import scripts.exclude_none_opponent_games as cleanup
from scripts.exclude_none_opponent_games import cascade_collisions, cascade_key, select_candidates

SINK = "45ad3ebf-0000-0000-0000-000000000000"
OTHER = "9b000000-0000-0000-0000-000000000000"
THIRD = "c1000000-0000-0000-0000-000000000000"
GOTSPORT_ID = "prov-gotsport"
OTHER_PROVIDER_ID = "prov-tgs"


def _game(
    gid,
    home,
    away,
    home_pid,
    away_pid,
    home_score=1,
    away_score=0,
    excluded=False,
    date="2026-09-01",
    provider=GOTSPORT_ID,
):
    return {
        "id": gid,
        "provider_id": provider,
        "game_date": date,
        "home_team_master_id": home,
        "away_team_master_id": away,
        "home_provider_id": home_pid,
        "away_provider_id": away_pid,
        "home_score": home_score,
        "away_score": away_score,
        "is_excluded": excluded,
    }


def test_sink_on_the_blank_home_side_is_a_candidate():
    game = _game("g1", SINK, OTHER, "None", "601000")

    assert [g["id"] for g in select_candidates([game], SINK, GOTSPORT_ID)] == ["g1"]


def test_sink_on_the_blank_away_side_is_a_candidate():
    game = _game("g2", OTHER, SINK, "601000", "None")

    assert [g["id"] for g in select_candidates([game], SINK, GOTSPORT_ID)] == ["g2"]


def test_sink_on_its_real_id_side_is_not_a_candidate():
    game = _game("g3", SINK, None, "601496", "None")

    assert select_candidates([game], SINK, GOTSPORT_ID) == []


def test_a_blank_side_belonging_to_another_team_is_not_a_candidate():
    game = _game("g4", OTHER, SINK, "", "601496")

    assert select_candidates([game], SINK, GOTSPORT_ID) == []


@pytest.mark.parametrize(
    ("home", "away", "home_pid", "away_pid"),
    [(SINK, OTHER, "None", "601000"), (OTHER, SINK, "601000", "None")],
)
def test_a_blank_side_game_from_another_provider_is_not_a_candidate(home, away, home_pid, away_pid):
    game = _game("g12", home, away, home_pid, away_pid, provider=OTHER_PROVIDER_ID)

    assert select_candidates([game], SINK, GOTSPORT_ID) == []


def test_cascade_key_ignores_orientation_but_not_score():
    game = _game("g5", SINK, OTHER, "None", "601000", home_score=3, away_score=1)
    swapped = _game("g6", OTHER, SINK, "601000", "None", home_score=1, away_score=3)
    other_score = _game("g7", SINK, OTHER, "None", "601000", home_score=3, away_score=2)

    assert cascade_key(game) == cascade_key(swapped)
    assert cascade_key(game) != cascade_key(other_score)


def test_cascade_collisions_returns_a_live_twin_and_ignores_an_excluded_one():
    excluding = _game("g8", SINK, OTHER, "None", "601000", home_score=2, away_score=2)
    live_twin = _game("g9", OTHER, SINK, "601000", "601496", home_score=2, away_score=2)
    excluded_twin = _game("g10", SINK, OTHER, "601496", "601000", home_score=2, away_score=2, excluded=True)
    unrelated = _game("g11", SINK, THIRD, "601496", "602000", home_score=2, away_score=2)

    collisions = cascade_collisions([excluding], [excluding, live_twin, excluded_twin, unrelated])

    assert [g["id"] for g in collisions] == ["g9"]


class _Query:
    """PostgREST builder double: applies the filters and column list main() sends, records only at execute()."""

    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._op = "select"
        self._predicates = []
        self._single = False
        self._window = None
        self._order = None
        self._payload = None
        self._columns = None

    def select(self, columns):
        self._columns = columns.split(",")
        return self

    def _project(self, row):
        return {c: row[c] for c in self._columns}

    def update(self, payload):
        self._op = "update"
        self._payload = payload
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
            if op == "eq":
                clauses.append(lambda r, f=field, v=value: r.get(f) == v)
            elif op == "ilike" and not any(c in value for c in "%_*"):
                clauses.append(lambda r, f=field, v=value: str(r.get(f)).lower() == v.lower())
            else:
                raise AssertionError(f"unmodeled or_ term {term!r}")
        self._predicates.append(lambda r: any(c(r) for c in clauses))
        return self

    def order(self, field, desc=False):
        self._order = (field, desc)
        return self

    def range(self, start, end):
        self._window = (start, end)
        return self

    def single(self):
        self._single = True
        return self

    def __getattr__(self, name):
        raise AssertionError(f"unmodeled builder method {name!r}")

    def execute(self):
        self._db.executed.append((self._table, self._op))
        rows = [r for r in self._db.rows.get(self._table, []) if all(p(r) for p in self._predicates)]
        if self._op == "update":
            for r in rows:
                r.update(self._payload)
            return SimpleNamespace(data=[dict(r) for r in rows])
        if self._order:
            field, desc = self._order
            rows = sorted(rows, key=lambda r: r[field], reverse=desc)
        if self._window:
            rows = rows[self._window[0] : self._window[1] + 1]
        if self._single:
            if len(rows) != 1:
                raise AssertionError("PGRST116: JSON object requested, multiple (or no) rows returned")
            return SimpleNamespace(data=self._project(rows[0]))
        return SimpleNamespace(data=[self._project(r) for r in rows])


class _DB:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def table(self, name):
        return _Query(self, name)


def _sink_db(games):
    return _DB(
        {
            "providers": [{"id": GOTSPORT_ID, "code": "gotsport"}],
            "team_alias_map": [
                {
                    "id": "a1",
                    "provider_id": GOTSPORT_ID,
                    "provider_team_id": "None",
                    "team_id_master": SINK,
                    "review_status": "approved",
                    "match_method": "direct_id",
                }
            ],
            "teams": [{"team_id_master": SINK, "team_name": "Sink FC"}],
            "games": games,
        }
    )


def _run_main(monkeypatch, db, argv):
    monkeypatch.setattr(cleanup, "get_client", lambda: db)
    monkeypatch.setattr(sys, "argv", ["exclude_none_opponent_games.py", *argv])
    return cleanup.main()


@pytest.mark.parametrize("twin_provider", [GOTSPORT_ID, OTHER_PROVIDER_ID])
def test_execute_refuses_and_writes_nothing_when_a_twin_would_cascade(monkeypatch, tmp_path, twin_provider):
    candidate = _game("g1", SINK, OTHER, "None", "601000", home_score=2, away_score=2)
    live_twin = _game("g2", OTHER, SINK, "601000", "601496", home_score=2, away_score=2, provider=twin_provider)
    db = _sink_db([candidate, live_twin])
    log = tmp_path / "log.json"

    assert _run_main(monkeypatch, db, ["--execute", "--out", str(log)]) == 1

    assert [call for call in db.executed if call[1] == "update"] == []
    assert not log.exists()


def test_default_run_is_a_dry_run(monkeypatch):
    candidate = _game("g1", SINK, OTHER, "None", "601000")
    db = _sink_db([candidate])

    assert _run_main(monkeypatch, db, []) == 0

    assert [call for call in db.executed if call[1] == "update"] == []
    assert db.rows["games"][0]["is_excluded"] is False
    assert db.rows["team_alias_map"][0]["review_status"] == "approved"
