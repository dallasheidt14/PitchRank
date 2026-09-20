"""The band-cohort applier writes only where the plan's pre-image still stands.

Every write carries three predicates -- the team id, ``is_deprecated = false`` and the
planned old age group -- and each one is the whole guard against a different way a row
can move between the plan and the apply. They are tested one at a time: a fixture
violating two at once still dies when either is deleted, so it proves neither.

The double applies the ``.eq()`` filters itself and records at ``execute()``. A double
that returned rows without filtering would pass for an applier whose compare-and-set had
been removed, which is the defect these tests exist to catch.
"""

import csv

import pytest

from scripts import fix_band_cohorts as fbc

PLAN_ROW = {
    "state_code": "NC",
    "team_id_master": "11111111-1111-4111-8111-111111111111",
    "team_name": "Queen City 2013/14 Boys",
    "club_name": "Queen City FC",
    "gender": "Male",
    "gotsport_team_name": "Queen City 2013/2014 B",
    "band": "u13",
    "old_age_group": "u14",
    "new_age_group": "u13",
    "action": "would_update",
    "collision_with": "",
    "evidence_tier": "A_own_name_band",
    "fixture_verdict": "backs_move",
    "opp_games_proposed": "9",
    "opp_games_current": "0",
}


def _plan_row(**overrides):
    return {**PLAN_ROW, **overrides}


def _team_row(row, **overrides):
    team = {
        "team_id_master": row["team_id_master"],
        "age_group": row["old_age_group"],
        "is_deprecated": False,
    }
    team.update(overrides)
    return team


def _write_plan(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fbc.PLAN_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


class _Query:
    def __init__(self, db, columns=None, payload=None):
        self._db = db
        self._columns = columns
        self._payload = payload
        self._filters = {}

    def eq(self, column, value):
        self._filters[column] = value
        return self

    def _matches(self, team):
        return all(team.get(column) == value for column, value in self._filters.items())

    def execute(self):
        if self._payload is None:
            rows = [t for t in self._db.teams.values() if self._matches(t)]
            projected = [{c: t.get(c) for c in self._columns} for t in rows]
            self._db.executed.append(("select", dict(self._filters)))
            return _Result(projected)

        updated = []
        for team in self._db.teams.values():
            if self._matches(team):
                team.update(self._payload)
                updated.append(dict(team))
        self._db.executed.append(("update", dict(self._filters), dict(self._payload)))
        return _Result(updated)


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, db):
        self._db = db

    def select(self, columns):
        return _Query(self._db, columns=[c.strip() for c in columns.split(",")])

    def update(self, payload):
        return _Query(self._db, payload=payload)


class _Db:
    """Holds ``teams`` rows and applies every filter a caller chains onto a write."""

    def __init__(self, teams):
        self.teams = {t["team_id_master"]: dict(t) for t in teams}
        self.executed = []

    def table(self, name):
        assert name == "teams", f"unexpected table {name!r}"
        return _Table(self)

    @property
    def writes(self):
        return [call for call in self.executed if call[0] == "update"]

    def age_group(self, team_id):
        return self.teams[team_id]["age_group"]


@pytest.fixture
def exports(tmp_path, monkeypatch):
    """A throwaway repo layout: the logs sit under ROOT, as they do in the real tree.

    ``apply_plan`` prints its undo command as paths relative to ROOT, so an exports
    directory outside ROOT would fail there for a reason production never meets.
    """
    root = tmp_path / "repo"
    exports_dir = root / "data" / "exports"
    exports_dir.mkdir(parents=True)
    monkeypatch.setattr(fbc, "ROOT", root)
    monkeypatch.setattr(fbc, "EXPORTS", exports_dir)
    monkeypatch.setattr(fbc, "__file__", str(root / "scripts" / "fix_band_cohorts.py"))
    return exports_dir


def _apply(db, plan_path, **kwargs):
    options = {
        "execute": True,
        "limit": None,
        "include_collisions": False,
        "strong_only": False,
        "boarded_only": False,
    }
    options.update(kwargs)
    fbc.apply_plan(db, plan_path, **options)


def _log_rows(exports_dir):
    logs = sorted(exports_dir.glob("fix_band_cohorts_apply_*.csv"))
    assert logs, "the apply wrote no log"
    with logs[-1].open(encoding="utf-8-sig", newline="") as f:
        return logs[-1], list(csv.DictReader(f))


def test_a_row_still_holding_the_planned_value_is_updated(exports, tmp_path):
    row = _plan_row()
    db = _Db([_team_row(row)])

    _apply(db, _write_plan(tmp_path / "plan.csv", [row]))

    assert db.age_group(row["team_id_master"]) == "u13"
    _, log = _log_rows(exports)
    assert [r["result"] for r in log] == ["updated"]


def test_a_row_whose_age_group_moved_since_the_plan_is_not_overwritten(exports, tmp_path):
    """Violates the ``age_group`` predicate alone: the team is live and present."""
    row = _plan_row()
    db = _Db([_team_row(row, age_group="u15")])

    _apply(db, _write_plan(tmp_path / "plan.csv", [row]))

    assert db.age_group(row["team_id_master"]) == "u15"
    _, log = _log_rows(exports)
    assert [r["result"] for r in log] == ["skipped_moved"]


def test_a_deprecated_row_is_not_overwritten(exports, tmp_path):
    """Violates the ``is_deprecated`` predicate alone: id and age group both match."""
    row = _plan_row()
    db = _Db([_team_row(row, is_deprecated=True)])

    _apply(db, _write_plan(tmp_path / "plan.csv", [row]))

    assert db.age_group(row["team_id_master"]) == "u14"
    _, log = _log_rows(exports)
    assert [r["result"] for r in log] == ["skipped_deprecated"]


def test_a_row_the_table_no_longer_holds_is_not_written(exports, tmp_path):
    """Violates the ``team_id_master`` predicate alone."""
    row = _plan_row()
    db = _Db([])

    _apply(db, _write_plan(tmp_path / "plan.csv", [row]))

    assert db.teams == {}
    _, log = _log_rows(exports)
    assert [r["result"] for r in log] == ["skipped_missing"]


def test_a_dry_run_executes_no_write(exports, tmp_path):
    row = _plan_row()
    db = _Db([_team_row(row)])

    _apply(db, _write_plan(tmp_path / "plan.csv", [row]), execute=False)

    assert db.writes == []
    assert db.age_group(row["team_id_master"]) == "u14"
    _, log = _log_rows(exports)
    assert [r["result"] for r in log] == ["would_update"]


def test_dry_run_beats_execute_on_the_command_line(monkeypatch, tmp_path):
    """``--dry-run`` wins, which is the whole fail-safe: asking for both means preview."""
    seen = {}

    monkeypatch.setattr(fbc, "load_env", lambda: None)
    monkeypatch.setattr(fbc, "get_supabase", lambda: object())
    monkeypatch.setattr(fbc, "apply_plan", lambda sb, path, execute, *a, **k: seen.update(execute=execute))
    monkeypatch.setattr(
        "sys.argv",
        ["fix_band_cohorts.py", "--apply", str(tmp_path / "plan.csv"), "--execute", "--dry-run"],
    )

    fbc.main()

    assert seen["execute"] is False


def test_limit_applies_exactly_n_rows(exports, tmp_path):
    rows = [
        _plan_row(team_id_master=f"1111111{n}-1111-4111-8111-111111111111")
        for n in range(4)
    ]
    db = _Db([_team_row(r) for r in rows])

    _apply(db, _write_plan(tmp_path / "plan.csv", rows), limit=2)

    moved = [t for t in db.teams.values() if t["age_group"] == "u13"]
    assert len(moved) == 2
    assert len(db.writes) == 2


def test_a_name_contradicting_row_is_held_rather_than_written(exports, tmp_path):
    """``--skip-name-contradictions`` holds a name stating another squad's birth year."""
    row = _plan_row(team_name="BRAUSA '11/'12", new_age_group="u13", old_age_group="u14")
    db = _Db([_team_row(row)])

    _apply(db, _write_plan(tmp_path / "plan.csv", [row]), skip_name_contradictions=True)

    assert db.writes == []
    assert db.age_group(row["team_id_master"]) == "u14"
    _, log = _log_rows(exports)
    assert [r["result"] for r in log] == ["held_name_contradicts"]
    assert "2011" in log[0]["hold_reason"]


def test_revert_restores_a_row_that_still_holds_what_the_apply_wrote(exports, tmp_path):
    row = _plan_row()
    db = _Db([_team_row(row)])
    _apply(db, _write_plan(tmp_path / "plan.csv", [row]))
    log_path, _ = _log_rows(exports)

    fbc.revert(db, log_path, execute=True)

    assert db.age_group(row["team_id_master"]) == "u14"


def test_revert_leaves_a_row_that_moved_again_since_the_apply(exports, tmp_path):
    row = _plan_row()
    db = _Db([_team_row(row)])
    _apply(db, _write_plan(tmp_path / "plan.csv", [row]))
    log_path, _ = _log_rows(exports)
    db.teams[row["team_id_master"]]["age_group"] = "u12"

    fbc.revert(db, log_path, execute=True)

    assert db.age_group(row["team_id_master"]) == "u12"


def test_a_dry_run_revert_executes_no_write(exports, tmp_path):
    row = _plan_row()
    db = _Db([_team_row(row)])
    _apply(db, _write_plan(tmp_path / "plan.csv", [row]))
    log_path, _ = _log_rows(exports)
    before = len(db.writes)

    fbc.revert(db, log_path, execute=False)

    assert len(db.writes) == before
    assert db.age_group(row["team_id_master"]) == "u13"


def test_a_log_row_the_apply_did_not_write_is_not_reverted(exports, tmp_path):
    """Revert replays ``updated`` rows only, so a held row is never written backwards."""
    row = _plan_row(team_name="BRAUSA '11/'12")
    db = _Db([_team_row(row)])
    _apply(db, _write_plan(tmp_path / "plan.csv", [row]), skip_name_contradictions=True)
    log_path, log = _log_rows(exports)
    assert log[0]["result"] == "held_name_contradicts"

    fbc.revert(db, log_path, execute=True)

    assert db.writes == []
    assert db.age_group(row["team_id_master"]) == "u14"
