"""The cleanup must hide only an unscored fixture that sits beside its own scored result."""

import json
import sys
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

import scripts.exclude_unscored_fixture_twins as cleanup
from scripts.exclude_unscored_fixture_twins import select_twins

HOME = "b5000000-0000-0000-0000-000000000000"
AWAY = "5b000000-0000-0000-0000-000000000000"
THIRD = "c1000000-0000-0000-0000-000000000000"
PAST = "2026-09-20"


def _game(
    gid,
    home=HOME,
    away=AWAY,
    home_score=None,
    away_score=None,
    excluded=False,
    game_date=PAST,
    provider="prov-gotsport",
):
    return {
        "id": gid,
        "provider_id": provider,
        "game_date": game_date,
        "home_team_master_id": home,
        "away_team_master_id": away,
        "home_score": home_score,
        "away_score": away_score,
        "is_excluded": excluded,
    }


def test_a_fixture_beside_its_result_is_selected_whichever_side_is_home():
    fixture = _game("fx")
    result = _game("res", home=AWAY, away=HOME, home_score=3, away_score=0)

    assert [g["id"] for g in select_twins([fixture], [result], set())] == ["fx"]


def test_more_fixtures_than_results_is_left_alone():
    fixtures = [_game("fx1"), _game("fx2")]
    result = _game("res", home_score=3, away_score=0)

    assert select_twins(fixtures, [result], set()) == []


def test_a_fixture_without_a_result_for_its_own_pair_is_left_alone():
    fixture = _game("fx")
    other_pair = _game("res", away=THIRD, home_score=3, away_score=0)

    assert select_twins([fixture], [other_pair], set()) == []


class _Query:
    """PostgREST builder double: applies the filters and column list main() sends, records only at execute()."""

    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._op = "select"
        self._predicates = []
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

    def is_(self, field, value):
        assert value == "null", value
        self._predicates.append(lambda r: r.get(field) is None)
        return self

    def lt(self, field, value):
        self._predicates.append(lambda r: r.get(field) < value)
        return self

    def gte(self, field, value):
        self._predicates.append(lambda r: r.get(field) >= value)
        return self

    def order(self, field, desc=False):
        self._order = (field, desc)
        return self

    def range(self, start, end):
        self._window = (start, end)
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
        return SimpleNamespace(data=[self._project(r) for r in rows])


class _DB:
    def __init__(self, games):
        self.rows = {
            "games": games,
            "providers": [
                {"id": "prov-gotsport", "code": "gotsport"},
                {"id": "prov-pm-tournament", "code": "playmetrics_tournament"},
            ],
        }
        self.executed = []

    def table(self, name):
        return _Query(self, name)


def _run_main(monkeypatch, db, argv):
    monkeypatch.setattr(cleanup, "get_client", lambda: db)
    monkeypatch.setattr(sys, "argv", ["exclude_unscored_fixture_twins.py", *argv])
    return cleanup.main()


def _excluded(db):
    return sorted(g["id"] for g in db.rows["games"] if g["is_excluded"])


def test_default_run_is_a_dry_run(monkeypatch):
    db = _DB([_game("fx"), _game("res", home_score=3, away_score=0)])

    assert _run_main(monkeypatch, db, []) == 0

    assert [call for call in db.executed if call[1] == "update"] == []
    assert _excluded(db) == []


def test_execute_hides_only_the_fixture_and_logs_it(monkeypatch, tmp_path):
    future = (date.today() + timedelta(days=3)).isoformat()
    db = _DB(
        [
            _game("fx"),
            _game("res", home=AWAY, away=HOME, home_score=0, away_score=3),
            _game("fx-ambiguous-1", away=THIRD),
            _game("fx-ambiguous-2", away=THIRD),
            _game("res-ambiguous", away=THIRD, home_score=1, away_score=1),
            _game("fx-future", game_date=future),
            _game("res-future", game_date=future, home_score=2, away_score=2),
        ]
    )
    log = tmp_path / "log.json"

    assert _run_main(monkeypatch, db, ["--execute", "--out", str(log)]) == 0

    assert _excluded(db) == ["fx"]
    assert json.loads(log.read_text(encoding="utf-8")) == {"applied": True, "game_ids": ["fx"], "games_excluded": 1}


def test_an_already_excluded_result_does_not_count(monkeypatch, tmp_path):
    db = _DB([_game("fx"), _game("res", home_score=3, away_score=0, excluded=True)])

    assert _run_main(monkeypatch, db, ["--execute", "--out", str(tmp_path / "log.json")]) == 0

    assert _excluded(db) == ["res"]


def test_execute_refuses_to_overwrite_a_rollback_log(monkeypatch, tmp_path):
    db = _DB([_game("fx"), _game("res", home_score=3, away_score=0)])
    log = tmp_path / "log.json"
    log.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit):
        _run_main(monkeypatch, db, ["--execute", "--out", str(log)])

    assert _excluded(db) == []
    assert log.read_text(encoding="utf-8") == "{}"


def test_a_fixture_scored_between_the_two_reads_is_not_its_own_twin():
    fixture = _game("fx")
    same_row_now_scored = _game("fx", home_score=2, away_score=0)

    assert select_twins([fixture], [same_row_now_scored], set()) == []


def test_a_rematch_provider_fixture_is_left_alone(monkeypatch, tmp_path):
    db = _DB(
        [
            _game("fx", provider="prov-pm-tournament"),
            _game("res", home_score=3, away_score=0, provider="prov-pm-tournament"),
        ]
    )

    assert _run_main(monkeypatch, db, ["--execute", "--out", str(tmp_path / "log.json")]) == 0

    assert _excluded(db) == []


def test_since_limits_the_sweep_to_later_dates(monkeypatch, tmp_path):
    db = _DB(
        [
            _game("fx-old", game_date="2026-07-01"),
            _game("res-old", game_date="2026-07-01", home_score=1, away_score=0),
            _game("fx"),
            _game("res", home_score=3, away_score=0),
        ]
    )

    assert _run_main(monkeypatch, db, ["--since", "2026-08-01", "--execute", "--out", str(tmp_path / "log.json")]) == 0

    assert _excluded(db) == ["fx"]


def test_a_fixture_scored_after_selection_is_not_excluded(monkeypatch, tmp_path):
    db = _DB([_game("fx"), _game("res", home_score=3, away_score=0)])
    select = cleanup.select_twins

    def select_then_score(*args):
        chosen = select(*args)
        db.rows["games"][0].update(home_score=0, away_score=3)
        return chosen

    monkeypatch.setattr(cleanup, "select_twins", select_then_score)

    assert _run_main(monkeypatch, db, ["--execute", "--out", str(tmp_path / "log.json")]) == 0

    assert _excluded(db) == []


def test_a_rematch_provider_result_is_not_evidence_for_a_gotsport_fixture(monkeypatch, tmp_path):
    db = _DB([_game("fx"), _game("res", home_score=3, away_score=0, provider="prov-pm-tournament")])

    assert _run_main(monkeypatch, db, ["--execute", "--out", str(tmp_path / "log.json")]) == 0

    assert _excluded(db) == []
