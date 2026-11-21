"""The batch rename of ``unknown_<provider_team_id>`` teams to "Unknown team".

The double applies a write at ``execute()``, never at construction, refuses a ``limit()`` with no
``order()``, and can simulate the three ways a compare-and-set leaves its outcome unconfirmed: a
concurrent writer, a write whose answer is lost after it committed, and a write refused without effect.
"""

import json
import os
import sys

import httpx
import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import rename_placeholder_team_names as rename  # noqa: E402
from tests.unit.test_placeholder_team_names import _like  # noqa: E402


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db):
        self._db = db
        self._filters = []
        self._columns = None
        self._order = None
        self._limit = None
        self._update = None
        self._eq_name = None

    def select(self, columns):
        self._columns = [c.strip() for c in columns.split(",")]
        return self

    def update(self, values):
        self._update = values
        return self

    def eq(self, column, value):
        self._filters.append(lambda row: row[column] == value)
        if column == "team_name":
            self._eq_name = value
        return self

    def gt(self, column, value):
        self._filters.append(lambda row: row[column] > value)
        return self

    def like(self, column, pattern):
        regex = _like(pattern)
        self._filters.append(lambda row: bool(regex.fullmatch(row[column] or "")))
        return self

    def order(self, column):
        self._order = column
        return self

    def limit(self, n):
        if self._order is None:
            raise AssertionError("limit() without order() pages unstably")
        self._limit = n
        return self

    def execute(self):
        rows = [r for r in self._db.rows if all(f(r) for f in self._filters)]
        if self._update is None:
            if self._order:
                rows.sort(key=lambda r: r[self._order])
            if self._limit is not None:
                rows = rows[: self._limit]
            return _Result([{c: r[c] for c in self._columns} for r in rows])
        return self._db.write(self, rows)


class _Db:
    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.writes = []
        self.before_write = None
        self.lose_answer = False
        self.refuse_writes = False

    def table(self, name):
        assert name == "teams"
        return _Query(self)

    def write(self, query, rows):
        if self.before_write:
            self.before_write(self)
            rows = [r for r in self.rows if all(f(r) for f in query._filters)]
        self.writes.append((query._update, [r["team_id_master"] for r in rows], query._eq_name))
        if self.refuse_writes:
            return _Result([])
        for row in rows:
            row.update(query._update)
        if self.lose_answer:
            raise httpx.ReadTimeout("answer lost")
        return _Result([dict(r) for r in rows])

    def name(self, team_id):
        return next(r["team_name"] for r in self.rows if r["team_id_master"] == team_id)


def _team(team_id, name, provider_team_id, deprecated=False):
    return {
        "team_id_master": team_id,
        "team_name": name,
        "provider_team_id": provider_team_id,
        "is_deprecated": deprecated,
    }


TEAMS = [
    _team("t1", "unknown_3912096", "3912096"),
    _team("t2", "unknown_640173", "640173", deprecated=True),
    _team("t3", "unknown_elite", "640174"),
    _team("t4", "unknown_999", "640175"),
    _team("t5", "Unknown team", "3912097"),
    _team("t6", "Rush 2015B Red", "640176"),
    _team("t7", "unknown_3912098", "3912098"),
    _team("t8", "unknown_3912099", None),
]


@pytest.fixture
def db(monkeypatch):
    database = _Db(TEAMS)
    monkeypatch.setattr(rename, "_new_client", lambda: database)
    monkeypatch.setattr(rename, "PAGE_SIZE", 2)
    return database


def _log_entries(out_dir):
    [log] = out_dir.glob("placeholder_rename_*.jsonl")
    return log, [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_only_each_rows_own_old_name_is_selected_deprecated_rows_included(db):
    assert [t["team_id_master"] for t in rename.select_renames(db)] == ["t1", "t2", "t7"]


def test_a_dry_run_writes_nothing(db, capsys):
    assert rename.main([]) == 0
    assert db.writes == []
    out = capsys.readouterr().out
    assert "deprecated rankings id  1" in out and "live       event id     2" in out and "total      3" in out
    assert "--execute" not in out


def test_execute_renames_each_team_guarded_on_its_old_name(db, tmp_path, capsys):
    assert rename.main(["--execute", "--out", str(tmp_path)]) == 0

    assert [db.name(t) for t in ("t1", "t2", "t7")] == ["Unknown team"] * 3
    assert [db.name(t) for t in ("t3", "t4", "t6")] == ["unknown_elite", "unknown_999", "Rush 2015B Red"]
    assert [(ids, guard) for _, ids, guard in db.writes] == [
        (["t1"], "unknown_3912096"),
        (["t2"], "unknown_640173"),
        (["t7"], "unknown_3912098"),
    ]
    _, entries = _log_entries(tmp_path)
    assert [(e["kind"], e["team_id_master"], e.get("outcome")) for e in entries] == [
        ("rename", "t1", None),
        ("outcome", "t1", "renamed"),
        ("rename", "t2", None),
        ("outcome", "t2", "renamed"),
        ("rename", "t7", None),
        ("outcome", "t7", "renamed"),
    ]
    assert "renamed=3 skipped=0 failed=0" in capsys.readouterr().out


def test_each_rename_is_logged_before_its_write(db, tmp_path):
    seen = []

    def read_log(_db):
        _, entries = _log_entries(tmp_path)
        seen.append(entries[-1])

    db.before_write = read_log
    rename.main(["--execute", "--out", str(tmp_path), "--limit", "1"])
    assert seen == [
        {"kind": "rename", "team_id_master": "t1", "old": "unknown_3912096", "new": "Unknown team", "at": seen[0]["at"]}
    ]


def test_a_team_renamed_since_it_was_selected_is_skipped(db, tmp_path):
    def backfill_resolves_it(database):
        database.rows[0]["team_name"] = "Solar SC 15B"

    db.before_write = backfill_resolves_it
    assert rename.main(["--execute", "--out", str(tmp_path), "--limit", "1"]) == 0
    assert db.name("t1") == "Solar SC 15B"
    assert _log_entries(tmp_path)[1][-1]["outcome"] == "skipped"


def test_a_lost_answer_after_the_write_committed_counts_as_renamed(db, tmp_path):
    db.lose_answer = True
    assert rename.main(["--execute", "--out", str(tmp_path), "--limit", "1"]) == 0
    assert _log_entries(tmp_path)[1][-1]["outcome"] == "renamed"


def test_a_write_that_did_not_take_fails_the_run(db, tmp_path):
    db.refuse_writes = True
    assert rename.main(["--execute", "--out", str(tmp_path), "--limit", "1"]) == 1
    assert db.name("t1") == "unknown_3912096"
    assert _log_entries(tmp_path)[1][-1]["outcome"] == "failed"


def test_execute_needs_a_log_directory(db):
    with pytest.raises(SystemExit, match="needs --out"):
        rename.main(["--execute"])
    assert db.writes == []


def test_the_log_may_not_sit_in_a_linked_worktree(db, tmp_path):
    (tmp_path / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="linked git worktree"):
        rename.main(["--execute", "--out", str(tmp_path / "data" / "backups")])
    assert db.writes == []


def test_undo_restores_only_what_still_holds_the_new_name_and_only_with_execute(db, tmp_path, capsys):
    rename.main(["--execute", "--out", str(tmp_path)])
    log, _ = _log_entries(tmp_path)
    db.rows[1]["team_name"] = "Seattle United B12"
    db.writes.clear()
    capsys.readouterr()

    assert rename.main(["--undo", str(log)]) == 0
    assert db.writes == []
    assert "--execute" not in capsys.readouterr().out

    assert rename.main(["--undo", str(log), "--execute"]) == 0
    assert [db.name(t) for t in ("t1", "t2", "t7")] == ["unknown_3912096", "Seattle United B12", "unknown_3912098"]
    assert "names_restored=2" in capsys.readouterr().out


def test_undo_restores_a_rename_whose_run_died_before_its_outcome_was_logged(db, tmp_path):
    log = tmp_path / "placeholder_rename_20261120T000000Z.jsonl"
    entry = {"kind": "rename", "team_id_master": "t1", "old": "unknown_3912096", "new": "Unknown team", "at": "x"}
    log.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    db.rows[0]["team_name"] = "Unknown team"

    rename.main(["--undo", str(log), "--execute"])
    assert db.name("t1") == "unknown_3912096"


def test_undo_leaves_a_rename_that_was_skipped(db, tmp_path):
    def someone_else_renames_it(database):
        database.rows[0]["team_name"] = "Unknown team"

    db.before_write = someone_else_renames_it
    rename.main(["--execute", "--out", str(tmp_path), "--limit", "1"])
    log, entries = _log_entries(tmp_path)
    assert entries[-1]["outcome"] == "skipped"
    db.before_write = None

    rename.main(["--undo", str(log), "--execute"])
    assert db.name("t1") == "Unknown team"


def test_an_already_renamed_team_is_not_the_old_form():
    """The query's LIKE prefilter never returns one either; this pins the helper on its own."""
    assert not rename.is_legacy_placeholder({"team_name": "Unknown team", "provider_team_id": "3912096"})
    assert rename.is_legacy_placeholder({"team_name": "unknown_3912096", "provider_team_id": "3912096"})
