"""Tests for the lapse of the reviewers' refusals after eight weeks."""

import json
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.team_cleanup import advance, collect  # noqa: E402
from scripts.team_cleanup import expire_decisions as ed  # noqa: E402
from scripts.team_cleanup import propose_week as pw  # noqa: E402
from scripts.team_cleanup.decisions import REVIEWED_SOURCE  # noqa: E402
from scripts.team_cleanup.review_page import TEAM_COLS  # noqa: E402
from scripts.team_cleanup.run_store import AUTO, OWNER, STORE_ENV, run_dir  # noqa: E402

# A Wednesday's run, whose cleanup week starts 2026-12-23; seven weeks back is 2026-11-04.
RUN = "2026-12-23-all"
COLUMNS = {
    "team_cleanup_decisions": {
        "id",
        "stage",
        "subject_key",
        "team_id_master",
        "other_team_id",
        "field",
        "proposed_value",
        "decision",
        "note",
        "decided_at",
        "source",
        "recorded_at",
        "superseded_at",
    },
    "teams": set(TEAM_COLS.split(",")),
}
ROW_CAP = 2


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Records each request at execute(), where the real builder sends it. A paged read answers at most ROW_CAP
    rows, as the server's row cap would; a read of at most 100 ids answers all of them. It refuses a page with no
    order, an unknown column, a list of more than 100 ids, and a like() pattern other than a prefix."""

    def __init__(self, db, table, columns=None, update=None):
        for column in [*(columns or ()), *(update or {})]:
            assert column in COLUMNS[table], f"PostgREST refuses unknown column {table}.{column}"
        self._db, self._table, self._columns, self._update = db, table, columns, update
        self._tests, self._order, self._range = [], None, None

    def _where(self, column, test):
        assert column in COLUMNS[self._table]
        self._tests.append((column, test))
        return self

    def is_(self, column, value):
        assert value == "null"
        return self._where(column, lambda v: v is None)

    def like(self, column, pattern):
        assert pattern.endswith("%") and pattern.count("%") == 1
        return self._where(column, lambda v: v.startswith(pattern[:-1]))

    def in_(self, column, values):
        values = list(values)
        assert len(values) <= 100, "an id list this long overflows the request's URL"
        return self._where(column, lambda v: v in values)

    def lt(self, column, value):
        bound = datetime.fromisoformat(value)
        return self._where(column, lambda v: datetime.fromisoformat(v) < bound)

    def order(self, column):
        self._order = column
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        self._db.executes.append((self._table, "update" if self._update else "select", self._update))
        if self._update:
            self._db.update_count += 1
            if self._db.update_count == self._db.fail_update:
                raise RuntimeError("connection reset")
            if self._db.before_update:
                self._db.before_update(self._db)
        matched = [r for r in self._db.tables[self._table] if all(test(r[c]) for c, test in self._tests)]
        if self._update:
            for row in matched:
                row.update(self._update)
            return _Result([dict(r) for r in matched])
        assert self._order or self._range is None, "a page with no order is arbitrary"
        if self._order:
            matched = sorted(matched, key=lambda r: r[self._order])
        if self._range:
            matched = matched[self._range[0] : self._range[1] + 1][:ROW_CAP]
        return _Result([{c: r[c] for c in self._columns} for r in matched])


class _Db:
    """``fail_update`` is the number of the update that raises before it lands; ``before_update`` runs just before
    an update does, as another writer would."""

    def __init__(self, decisions, teams=(), fail_update=None, before_update=None):
        self.tables = {"team_cleanup_decisions": [dict(d) for d in decisions], "teams": [dict(t) for t in teams]}
        self.executes, self.update_count = [], 0
        self.fail_update, self.before_update = fail_update, before_update

    def table(self, name):
        db = self

        class _T:
            def select(self, columns):
                return _Query(db, name, columns=columns.split(","))

            def update(self, payload):
                return _Query(db, name, update=payload)

        return _T()

    def updates(self):
        return [e for e in self.executes if e[1] == "update"]

    def superseded(self):
        return sorted(d["id"] for d in self.tables["team_cleanup_decisions"] if d["superseded_at"])


def _decision(id_, decided_at, source="auto:20261028T231824Z-0c3ec2", decision="keep_separate", **fields):
    row = {
        "id": id_,
        "stage": "merges",
        "subject_key": f"{id_}-a|{id_}-b",
        "team_id_master": f"{id_}-a",
        "other_team_id": f"{id_}-b",
        "field": None,
        "proposed_value": None,
        "decision": decision,
        "note": None,
        "decided_at": decided_at,
        "source": source,
        "recorded_at": decided_at,
        "superseded_at": None,
    }
    return {**row, **fields}


def _state_decline(id_, decided_at):
    fields = {"stage": "states", "other_team_id": None, "field": "state_code", "proposed_value": "AZ"}
    return _decision(id_, decided_at, decision="dont_apply", subject_key=f"{id_}-a|state_code", **fields)


def _team(team_id, name):
    return {**dict.fromkeys(COLUMNS["teams"]), "team_id_master": team_id, "team_name": name}


def _teams(*ids):
    return [_team(f"{i}-{side}", f"Team {i}{side}") for i in ids for side in "ab"]


def _store(tmp_path, name="store"):
    store = tmp_path / name
    run_dir(store, RUN).mkdir(parents=True)
    return store


def _listed(store):
    return json.loads((run_dir(store, RUN) / ed.EXPIRED_FILE).read_text(encoding="utf-8"))


def test_a_refusal_lapses_at_the_eighth_weekly_run_after_the_week_it_was_recorded():
    assert ed.lapse_before("2026-12-23-all") == datetime(2026, 11, 4, tzinfo=timezone.utc)
    assert ed.lapse_before("2026-12-29-ca") == datetime(2026, 11, 4, tzinfo=timezone.utc)
    assert ed.lapse_before("2026-12-30-all") == datetime(2026, 11, 11, tzinfo=timezone.utc)


def test_only_the_reviewers_refusals_from_eight_weeks_back_lapse(tmp_path):
    store = _store(tmp_path)
    db = _Db(
        [
            _decision("d1", "2026-10-28T23:18:24+00:00"),
            _state_decline("d2", "2026-11-03T23:59:59+00:00"),
            _decision("d3", "2026-11-04T00:00:00+00:00"),
            _decision("d4", "2026-09-25T06:37:42+00:00", source="page:20260925T063742Z-a1b2c3"),
            _decision("d5", "2026-09-25T06:37:42+00:00", source="carried:LgYdqtoU3JGnY8h632CdHC"),
            _decision("d6", "2026-10-09T22:39:59+00:00", source="undo:card-9"),
            _decision("d7", "2026-10-28T18:00:00+00:00", source="owner:audit-2026-10-28"),
            _decision("d8", "2026-10-14T17:00:00+00:00", decision="apply"),
            _decision("d9", "2026-10-07T17:00:00+00:00", superseded_at="2026-10-20T00:00:00+00:00"),
        ],
        _teams("d1", "d2"),
    )

    assert ed.expire(db, store, RUN, True) == 2

    assert db.superseded() == ["d1", "d2", "d9"]
    assert db.tables["team_cleanup_decisions"][8]["superseded_at"] == "2026-10-20T00:00:00+00:00"
    assert [ed.lapsed_text(row) for row in _listed(store)] == [
        "merges: Team d1a and Team d1b, kept separate since 2026-10-28",
        "states: Team d2a → AZ, declined since 2026-11-03",
    ]


def test_the_lapse_reads_the_source_collect_records_for_the_automatic_lane():
    assert f"{collect.LANE_SOURCES[AUTO]}:20261028T231824Z-0c3ec2".startswith(REVIEWED_SOURCE)
    assert not f"{collect.LANE_SOURCES[OWNER]}:20261028T231824Z-0c3ec2".startswith(REVIEWED_SOURCE)


def test_a_dry_run_lists_what_would_lapse_and_writes_nothing(tmp_path, capsys):
    store = _store(tmp_path)
    db = _Db([_decision("d1", "2026-10-28T23:18:24+00:00")], _teams("d1"))

    assert ed.expire(db, store, RUN, False) == 1

    assert "would lapse: merges: Team d1a and Team d1b, kept separate since 2026-10-28" in capsys.readouterr().out
    assert db.updates() == [] and db.superseded() == []
    assert not (run_dir(store, RUN) / ed.EXPIRED_FILE).exists()


def test_a_stamp_failing_part_way_leaves_every_lapse_listed_and_a_rerun_finishes_it(tmp_path):
    store = _store(tmp_path)
    ids = [f"d{n:03}" for n in range(101)]
    db = _Db([_decision(i, "2026-10-28T23:18:24+00:00") for i in ids], _teams(*ids), fail_update=2)

    with pytest.raises(RuntimeError):
        ed.expire(db, store, RUN, True)

    assert [row["id"] for row in _listed(store)] == ids and db.superseded() == ids[:100]

    assert ed.expire(db, store, RUN, True) == 1

    assert [row["id"] for row in _listed(store)] == ids and db.superseded() == ids
    assert _listed(store)[100]["team_name"] == "Team d100a"


def test_a_stamp_leaves_a_row_another_writer_superseded_meanwhile(tmp_path):
    store = _store(tmp_path)

    def the_owner_decides_again(db):
        db.tables["team_cleanup_decisions"][0]["superseded_at"] = "2026-12-23T17:59:00+00:00"

    decisions = [_decision("d1", "2026-10-28T23:18:24+00:00"), _decision("d2", "2026-10-28T23:18:24+00:00")]
    db = _Db(decisions, _teams("d1", "d2"), before_update=the_owner_decides_again)

    ed.expire(db, store, RUN, True)

    d1, d2 = db.tables["team_cleanup_decisions"]
    assert d1["superseded_at"] == "2026-12-23T17:59:00+00:00" and d2["superseded_at"] is not None


def _main(monkeypatch, db, command):
    monkeypatch.setattr(ed, "get_client", lambda: db)
    monkeypatch.setattr(sys, "argv", ["expire_decisions.py", *command[1:]])
    return ed.main()


def test_the_command_the_week_runs_lapses_them_into_its_own_store(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setenv(STORE_ENV, str(_store(tmp_path, "elsewhere")))
    db = _Db([_decision("d1", "2026-10-28T23:18:24+00:00")], _teams("d1"))

    assert _main(monkeypatch, db, pw.expire_command(store, RUN, execute=True)) == 0

    assert db.superseded() == ["d1"] and [row["id"] for row in _listed(store)] == ["d1"]


def test_the_command_the_dry_run_prints_writes_nothing(tmp_path, monkeypatch):
    store = _store(tmp_path)
    db = _Db([_decision("d1", "2026-10-28T23:18:24+00:00")], _teams("d1"))

    assert _main(monkeypatch, db, pw.expire_command(store, RUN, execute=False)) == 0

    assert db.updates() == [] and not (run_dir(store, RUN) / ed.EXPIRED_FILE).exists()


def test_the_summary_lists_what_lapsed_with_each_name_escaped(tmp_path):
    store = _store(tmp_path)
    teams = [_team("d1-a", "Storm <B13>"), _team("d1-b", "Storm")]
    ed.expire(_Db([_decision("d1", "2026-10-28T23:18:24+00:00")], teams), store, RUN, True)

    _, body = advance.summary_email(store, RUN, ["merges"])

    assert (
        "<p>1 of the reviewers' calls reached their eighth weekly run and lapsed, so this week's scans could propose "
        "them again:</p><ul><li>merges: Storm &lt;B13&gt; and Storm, kept separate since 2026-10-28</li></ul>"
    ) in body


def test_a_week_with_nothing_lapsed_says_nothing_of_it(tmp_path):
    store = _store(tmp_path)
    ed.expire(_Db([]), store, RUN, True)

    _, body = advance.summary_email(store, RUN, ["merges"])

    assert "lapsed" not in body
