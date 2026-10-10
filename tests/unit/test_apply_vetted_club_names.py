"""Unit tests for scripts/apply_vetted_club_names.py.

The script moves teams filed under the wrong club. Two things carry the risk: the
vetted list has to still describe the database when it is applied, and the log has
to survive, because ``--revert`` reads it and it is the only way back.
"""

import csv
import json
from datetime import datetime

import pytest

from scripts.apply_vetted_club_names import plan, resolve_log_path


def _entry(team_id="t1", from_club="Crossfire Select Soccer Club", to_club="Bellevue United FC"):
    return {"team_id_master": team_id, "from_club": from_club, "to_club": to_club, "evidence": "name says BUFC"}


def _row(team_id="t1", club="Crossfire Select Soccer Club", deprecated=False):
    return {"team_id_master": team_id, "team_name": "BUFC B14 Blue", "club_name": club, "is_deprecated": deprecated}


class TestResolveLogPath:
    def test_the_default_carries_a_timestamp_so_two_runs_cannot_collide(self):
        first = resolve_log_path(None, datetime(2026, 9, 20, 23, 45, 1))
        second = resolve_log_path(None, datetime(2026, 9, 20, 23, 45, 2))

        assert first != second
        assert first.name == "club_name_changes_20260920_234501.csv"

    def test_a_named_file_is_used_as_given(self, tmp_path):
        wanted = tmp_path / "batch.csv"

        assert resolve_log_path(wanted) == wanted

    def test_an_existing_log_stops_the_run(self, tmp_path):
        """Overwriting it would destroy the record of the batch it describes."""
        already = tmp_path / "batch.csv"
        already.write_text("team_id_master\n", encoding="utf-8")

        with pytest.raises(FileExistsError):
            resolve_log_path(already)


class TestPlan:
    def test_a_row_still_matching_the_vetted_list_is_applied(self):
        apply_now, stale = plan([_entry()], {"t1": _row()})

        assert [e["team_id_master"] for e in apply_now] == ["t1"]
        assert stale == []

    def test_a_row_whose_club_moved_since_vetting_is_skipped(self):
        """Someone else corrected it, or corrected it differently; do not overwrite blind."""
        apply_now, stale = plan([_entry()], {"t1": _row(club="Some Other Club")})

        assert apply_now == []
        assert "Some Other Club" in stale[0]

    def test_a_row_already_at_the_target_is_skipped(self):
        apply_now, stale = plan([_entry()], {"t1": _row(club="Bellevue United FC")})

        assert apply_now == []
        assert "already" in stale[0]

    def test_a_deprecated_row_is_skipped(self):
        apply_now, stale = plan([_entry()], {"t1": _row(deprecated=True)})

        assert apply_now == []
        assert "deprecated" in stale[0]

    def test_a_row_that_no_longer_exists_is_skipped(self):
        apply_now, stale = plan([_entry()], {})

        assert apply_now == []
        assert "no such team" in stale[0]

    def test_each_skip_names_the_team_it_is_about(self):
        apply_now, stale = plan([_entry("t1"), _entry("t2")], {"t1": _row("t1", club="Moved")})

        assert apply_now == []
        assert {"t1", "t2"} == {reason.split(":")[0] for reason in stale}


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Applies every .eq and .in_ filter at execute(), where a write is recorded."""

    def __init__(self, db, columns=None, payload=None):
        self._db, self._columns, self._payload, self._eq, self._in = db, columns, payload, [], []

    def eq(self, column, value):
        self._eq.append((column, value))
        return self

    def in_(self, column, values):
        self._in.append((column, list(values)))
        return self

    def execute(self):
        rows = [
            t for t in self._db.teams.values()
            if all(t.get(c) == v for c, v in self._eq) and all(t.get(c) in v for c, v in self._in)
        ]
        if self._payload is None:
            self._db.reads += 1
            answer = [{c: t[c] for c in self._columns} for t in rows]
            if self._db.reads == 1 and self._db.after_first_read:
                self._db.after_first_read(self._db)
            return _Result(answer)
        if self._db.refuse_writes:
            return _Result([])
        for t in rows:
            t.update(self._payload)
        self._db.writes.append((list(self._eq), dict(self._payload)))
        return _Result([dict(t) for t in rows])


class _Db:
    """`after_first_read` stands in for another writer acting between the read and the write;
    `refuse_writes` for a key RLS lets read but not write, which PostgREST answers with no rows."""

    def __init__(self, *teams, after_first_read=None, refuse_writes=False):
        self.teams = {t["team_id_master"]: dict(t) for t in teams}
        self.writes, self.reads, self.after_first_read = [], 0, after_first_read
        self.refuse_writes = refuse_writes

    def table(self, name):
        assert name == "teams"
        db = self

        class _T:
            def select(self, columns):
                return _Query(db, columns=[c.strip() for c in columns.split(",")])

            def update(self, payload):
                return _Query(db, payload=payload)

        return _T()


def _run_main(monkeypatch, tmp_path, db, entries):
    import scripts.apply_vetted_club_names as script

    vetted = tmp_path / "vetted.json"
    vetted.write_text(json.dumps(entries), encoding="utf-8")
    log = tmp_path / "moves.csv"
    monkeypatch.setenv("SUPABASE_URL", "http://db.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setattr(script, "create_client", lambda url, key: db)
    monkeypatch.setattr(script.sys, "argv", ["apply_vetted_club_names.py", "--file", str(vetted), "--execute",
                                            "--log", str(log)])
    return script.main(), log


@pytest.mark.parametrize("change", [{"club_name": "Some Other Club"}, {"is_deprecated": True}],
                         ids=["club-changed", "merged"])
def test_a_team_changed_or_merged_after_it_was_read_is_not_overwritten(monkeypatch, tmp_path, capsys, change):
    def another_writer(db):
        db.teams["t1"].update(change)

    db = _Db(_row("t1"), _row("t2"), after_first_read=another_writer)

    code, log = _run_main(monkeypatch, tmp_path, db, [_entry("t1"), _entry("t2")])

    assert code == 0
    assert db.teams["t1"]["club_name"] == change.get("club_name", "Crossfire Select Soccer Club")
    assert db.teams["t2"]["club_name"] == "Bellevue United FC"
    assert [r["team_id_master"] for r in csv.DictReader(log.open(encoding="utf-8"))] == ["t2"]
    assert "skipped t1" in capsys.readouterr().out


def test_writes_that_match_nothing_while_the_row_is_unchanged_fail_the_run(monkeypatch, tmp_path, capsys):
    db = _Db(_row("t1"), refuse_writes=True)

    code, log = _run_main(monkeypatch, tmp_path, db, [_entry("t1")])

    assert code == 1
    assert "1 did not take" in capsys.readouterr().out
    assert list(csv.DictReader(log.open(encoding="utf-8"))) == []
