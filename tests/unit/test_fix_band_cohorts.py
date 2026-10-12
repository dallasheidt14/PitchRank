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
import functools
import json
import re

import pytest

from scripts import fix_band_cohorts as fbc
from scripts import normalize_team_names

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
    def __init__(self, db, columns=None, payload=None, table="teams"):
        self._db = db
        self._table = table
        self._columns = columns
        self._payload = payload
        self._filters = {}

    def eq(self, column, value):
        self._filters[column] = value
        return self

    def in_(self, column, values):
        values = list(values)
        assert len(values) <= 100, "an id list this long overflows the URL"
        self._filters[column] = _AnyOf(values)
        return self

    def _matches(self, team):
        return all(
            team.get(column) in value if isinstance(value, _AnyOf) else team.get(column) == value
            for column, value in self._filters.items()
        )

    def execute(self):
        if self._payload is None:
            rows = [t for t in self._source() if self._matches(t)]
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


    def _source(self):
        return self._db.merges if self._table == "team_merge_map" else self._db.teams.values()


class _AnyOf(tuple):
    pass


class _Result:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, db, name):
        self._db, self._name = db, name

    def select(self, columns):
        return _Query(self._db, columns=[c.strip() for c in columns.split(",")], table=self._name)

    def update(self, payload):
        assert self._name == "teams", "nothing writes team_merge_map"
        return _Query(self._db, payload=payload)


class _Db:
    """Holds ``teams`` and ``team_merge_map`` rows and applies every filter a caller chains on."""

    def __init__(self, teams, merges=()):
        self.teams = {t["team_id_master"]: dict(t) for t in teams}
        self.merges = [dict(m) for m in merges]
        self.executed = []

    def table(self, name):
        assert name in ("teams", "team_merge_map"), f"unexpected table {name!r}"
        return _Table(self, name)

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
    _decisions(monkeypatch, tmp_path, {})
    return exports_dir


def _decisions(monkeypatch, tmp_path, sections):
    """``sections`` maps a section name to its team ids; each section's ``decided`` is '2026-10-01, <name>'."""
    path = tmp_path / "owner_decisions.json"
    body = {
        name: {"decided": f"2026-10-01, {name}", "teams": [{"team_id": t} for t in ids]}
        for name, ids in sections.items()
    }
    path.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(fbc, "OWNER_DECISIONS", path)
    return path


def _write_reconcile(exports_dir, rows):
    path = exports_dir / "reconcile_teams_with_gotsport_20261001_000000.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


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


def test_a_zero_limit_applies_no_rows(exports, tmp_path):
    """``--limit 0`` asks for none. Read as falsy it asks for all, which is the plan."""
    rows = [_plan_row(team_id_master=f"1111111{n}-1111-4111-8111-111111111111") for n in range(3)]
    db = _Db([_team_row(r) for r in rows])

    _apply(db, _write_plan(tmp_path / "plan.csv", rows), limit=0)

    assert db.writes == []
    assert [t["age_group"] for t in db.teams.values()] == ["u14", "u14", "u14"]


def test_a_negative_limit_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(fbc, "load_env", lambda: None)
    monkeypatch.setattr(fbc, "get_supabase", lambda: object())
    monkeypatch.setattr(
        "sys.argv",
        ["fix_band_cohorts.py", "--apply", str(tmp_path / "plan.csv"), "--limit", "-1", "--execute"],
    )

    with pytest.raises(SystemExit):
        fbc.main()


def _apply_log(path, rows):
    fbc.write_csv(rows, path, fbc.PLAN_FIELDS + ["result", "hold_reason"])
    return path


def test_an_unconfirmed_row_still_holding_the_written_value_is_reverted(tmp_path):
    """A PATCH whose reply was lost leaves an unconfirmed row, and it has to be undoable."""
    row = {**_plan_row(), "result": fbc.UNCONFIRMED, "hold_reason": ""}
    db = _Db([_team_row(row, age_group="u13")])

    fbc.revert(db, _apply_log(tmp_path / "log.csv", [row]), execute=True)

    assert db.age_group(row["team_id_master"]) == "u14"


def test_an_unconfirmed_row_that_moved_elsewhere_is_left_alone(tmp_path):
    """The predicate still decides: only a row holding what the run wrote comes back."""
    row = {**_plan_row(), "result": fbc.UNCONFIRMED, "hold_reason": ""}
    db = _Db([_team_row(row, age_group="u15")])

    fbc.revert(db, _apply_log(tmp_path / "log.csv", [row]), execute=True)

    assert db.age_group(row["team_id_master"]) == "u15"


def test_a_held_row_is_not_revertable(tmp_path):
    row = {**_plan_row(), "result": "held_name_contradicts", "hold_reason": "name says U11"}
    db = _Db([_team_row(row, age_group="u13")])

    fbc.revert(db, _apply_log(tmp_path / "log.csv", [row]), execute=True)

    assert db.age_group(row["team_id_master"]) == "u13"


def test_an_interrupted_execute_marks_its_rows_unconfirmed(exports, tmp_path):
    """A row the loop never reached is unknown, not unwritten, once the run dies."""
    row = _plan_row()
    db = _Db([_team_row(row)])
    plan = _write_plan(tmp_path / "plan.csv", [row])

    def _boom(*a, **k):
        raise KeyboardInterrupt

    original = db.table
    db.table = _boom
    with pytest.raises(KeyboardInterrupt):
        _apply(db, plan)
    db.table = original

    _, log = _log_rows(exports)
    assert [r["result"] for r in log] == [fbc.UNCONFIRMED]


def test_an_exports_dir_outside_the_repo_takes_the_apply_log_and_the_default_gets_nothing(exports, tmp_path, capsys):
    store = tmp_path / "store with space" / "exports"
    row = _plan_row()
    db = _Db([_team_row(row)])

    _apply(db, _write_plan(tmp_path / "plan.csv", [row]), exports_dir=store, actor="team-cleanup:run-1")

    assert list(exports.iterdir()) == []
    log_path, log = _log_rows(store)
    assert [(r["result"], r["actor"]) for r in log] == [("updated", "team-cleanup:run-1")]
    assert f'--revert "{log_path}" --execute' in capsys.readouterr().out


def test_an_apply_log_records_the_operator_when_no_actor_is_given(exports, tmp_path):
    row = _plan_row()
    _apply(_Db([_team_row(row)]), _write_plan(tmp_path / "plan.csv", [row]))

    _, log = _log_rows(exports)
    assert [r["actor"] for r in log] == ["pitchrank-operator"]


def test_the_dry_run_reads_reconcile_logs_from_the_exports_dir_it_is_given(exports, tmp_path):
    store = tmp_path / "store" / "exports"
    store.mkdir(parents=True)
    audit = {
        "run_mode": "execute",
        "team_id_master": "a",
        "stored_age_group": "u14",
        "gotsport_age_group": "u13",
        "gotsport_team_name": "Rush 2013/2014 Red",
        "stored_team_name": "Rush 2013 Red",
    }
    _write_reconcile(store, [audit])

    assert [c["team_id_master"] for c in fbc.derive_candidates(store)] == ["a"]
    assert fbc.derive_candidates() == []


def test_main_passes_the_exports_dir_and_actor_to_the_apply(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(fbc, "load_env", lambda: None)
    monkeypatch.setattr(fbc, "get_supabase", lambda: object())
    monkeypatch.setattr(fbc, "apply_plan", lambda sb, path, execute, *a: seen.update(rest=a))
    store = tmp_path / "store"
    monkeypatch.setattr(
        "sys.argv",
        ["fix_band_cohorts.py", "--apply", str(tmp_path / "plan.csv"), "--exports-dir", str(store),
         "--actor", "team-cleanup:run-1"],
    )

    fbc.main()

    assert seen["rest"][-2:] == (store, "team-cleanup:run-1")


def test_main_builds_the_plan_from_and_into_the_exports_dir_given(exports, monkeypatch, tmp_path):
    store = tmp_path / "store" / "exports"
    store.mkdir(parents=True)
    audit = {
        "run_mode": "execute", "team_id_master": "a", "stored_age_group": "u14", "gotsport_age_group": "u13",
        "gotsport_team_name": "Rush 2013/2014 Red", "stored_team_name": "Rush 2013 Red",
    }
    _write_reconcile(store, [audit])
    monkeypatch.setattr(fbc, "load_env", lambda: None)
    monkeypatch.setattr(fbc, "get_supabase", lambda: object())
    monkeypatch.setattr(fbc, "fetch_live", lambda sb, ids: {})
    monkeypatch.setattr(fbc, "attach_fixture_evidence", lambda sb, rows: None)
    monkeypatch.setattr(fbc, "fetch_all_live_teams", lambda sb: [])
    monkeypatch.setattr("sys.argv", ["fix_band_cohorts.py", "--exports-dir", str(store)])

    fbc.main()

    [plan] = sorted(store.glob("fix_band_cohorts_plan_*.csv"))
    assert [(r["team_id_master"], r["action"]) for r in fbc.read_our_csv(plan)] == [("a", "skipped_missing")]
    assert list(exports.iterdir()) == []


@pytest.fixture
def season_2026(monkeypatch):
    """The season for fbc's readers, and for band_of, whose band reader took the year at import
    (calculate_age_group_from_birth_year's current_year default) and reads it again to tell an
    aged-out band (calculate_age_group_from_band)."""
    monkeypatch.setattr(fbc, "_soccer_season_year", lambda: 2026)
    calculate = normalize_team_names.calculate_age_group_from_birth_year
    monkeypatch.setattr(
        normalize_team_names, "calculate_age_group_from_birth_year", functools.partial(calculate, current_year=2026)
    )
    band = normalize_team_names.calculate_age_group_from_band
    monkeypatch.setattr(
        normalize_team_names, "calculate_age_group_from_band", functools.partial(band, current_year=2026)
    )


@pytest.mark.parametrize(
    ("name", "target"),
    [
        ("Club 2009 Boys", "u19"),
        ("Club U19 2009", "u19"),
        ("Club 08/09 Boys", "u19"),
        ("BRAUSA '11/'12 Blue", "u15"),
        ("Club U16 Red", "u15"),
        # Last season's U-age is one group from u19, since U18 files into it.
        ("Club U17 Boys", "u19"),
        # No two numbers step by one, so none is a birth year.
        ("FC 10/12/14 Elite", "u13"),
        # 12 and 13 step by one; 15 does not, so it is not read.
        ("Club 12/13/15 Elite", "u14"),
        # Years after 2020 are season labels, inside a run too.
        ("Lions 2020/21/22", "u7"),
        # U-ages, ranges and "U/10" included, are labels, not years.
        ("Club U12/13/14 Elite", "u13"),
        ("Club U-13/14/15", "u14"),
        ("Club U/10B White", "u10"),
        # A hyphen-wrapped number is last season's U-age (owner, 2026-10-11): U9 is one group from u10.
        ("Town-G09A-Coach", "u10"),
    ],
)
def test_a_name_whose_years_fit_the_new_group_is_not_held(season_2026, name, target):
    assert fbc.name_contradiction(name, target) == ""


@pytest.mark.parametrize(
    ("name", "target", "reason"),
    [
        ("Club 14B Blue", "u15", "name has birth year 2014, outside U15 (2012/2011)"),
        ("13 WUSC Revolution Blue", "u11", "name has birth year 2013, outside U11 (2016/2015)"),
        ("Club 09 Girls", "u15", "name has birth year 2009, outside U15 (2012/2011)"),
        ("Club 2013/14 Elite", "u14", "name has birth year 2014, outside U14 (2013/2012)"),
        ("Club 2010 Boys", "u19", "name has birth year 2010, outside U19 (2009/2008/2007)"),
        ("Club U12 Red", "u15", "name says U12, 3 away from U15"),
        ("Club U16 Red", "u19", "name says U16, 2 away from U19"),
        ("Club U18 Red", "u15", "name says U18, 3 away from U15"),
        ("Club U15 Red", "u17", "name says U15, 2 away from U17"),
        ("Club U17 Red", "u15", "name says U17, 2 away from U15"),
        ("Town-G09A-Coach", "u12", "name says U9, 3 away from U12"),
        ("Club 2004 Boys", "u19", "name has birth year 2004, outside U19 (2009/2008/2007)"),
        ("Club '04 Blue", "u19", "name has birth year 2004, outside U19 (2009/2008/2007)"),
        ("Club '11 Blue", "u13", "name has birth year 2011, outside U13 (2014/2013)"),
        # Bands beside a word or an M/F letter, which birth_years does not read.
        ("Club 11/12M Blue", "u12", "name has birth year 2011, outside U12 (2015/2014)"),
        ("Club 07/08F", "u17", "name has birth year 2007, outside U17 (2010/2009)"),
        ("Club Knights13/14B", "u12", "name has birth year 2013, outside U12 (2015/2014)"),
        # Spans are held whenever any year misses the new group (owner, 2026-10-11).
        ("Storm FC G2012/13/14", "u14", "name has birth year 2014, outside U14 (2013/2012)"),
        ("Club B2012/13/14 Elite", "u14", "name has birth year 2014, outside U14 (2013/2012)"),
        ("Club 2012 / 13 / 14 Elite", "u14", "name has birth year 2014, outside U14 (2013/2012)"),
        ("Club 2012-13-14 Elite", "u14", "name has birth year 2014, outside U14 (2013/2012)"),
        ("Club 2012/2013/14", "u14", "name has birth year 2014, outside U14 (2013/2012)"),
        ("Club 12/2013/2014", "u13", "name has birth year 2012, outside U13 (2014/2013)"),
        ("Club 14/13/12 Elite", "u13", "name has birth year 2012, outside U13 (2014/2013)"),
        ("Club B2014/15/16navy", "u12", "name has birth year 2016, outside U12 (2015/2014)"),
        ("Club 06/07/08 Boys", "u19", "name has birth year 2006, outside U19 (2009/2008/2007)"),
        ("3RSC B16-18 Dev", "u10", "name has birth year 2018, outside U10 (2017/2016)"),
    ],
)
def test_a_name_stating_another_squad_is_held(season_2026, name, target, reason):
    assert fbc.name_contradiction(name, target) == reason


@pytest.mark.parametrize(
    ("name", "target", "tier"),
    [
        ("Club 2009 Boys", "u19", "C_bare_year_fits"),
        ("Club 13/14 Boys", "u13", "A_own_name_band"),
        ("2025 Club Elite", "u13", "B_gotsport_name_only"),
        ("Club 14B Blue", "u15", "D_name_contradicts"),
        ("Storm FC G2012/13/14", "u14", "D_name_contradicts"),
        # A stray year outweighs a band that agrees: the hold would stop the move.
        ("Club 2012/13 Blue 14B", "u14", "D_name_contradicts"),
        ("Club 2006/07 Boys", "u19", "D_name_contradicts"),
    ],
)
def test_evidence_tier_reads_a_name_s_years_the_way_the_hold_does(season_2026, name, target, tier):
    assert fbc.evidence_tier(name, target) == tier


@pytest.mark.parametrize(("season", "years"), [(2026, set()), (2030, {2021})])
def test_the_season_label_cut_moves_with_the_season(monkeypatch, season, years):
    monkeypatch.setattr(fbc, "_soccer_season_year", lambda: season)

    assert fbc.name_years("Club 2021 Boys") == years


def test_the_plan_holds_a_name_that_states_another_squad(tmp_path, monkeypatch, season_2026):
    """The planner's own hold, driven through build_plan rather than evidence_tier alone."""
    rows = {
        "a": ("Club 2011/2012 Boys", "u16", "u15", "Club 14B Blue"),
        "b": ("Club 2008/2009 Boys", "u17", "u19", "Club 2009 Boys"),
        "c": ("Club 2013/2014 Boys", "u14", "u13", "2025 Club Elite"),
    }
    candidates = [
        {"team_id_master": t, "gotsport_team_name": gs, "audit_age_group": old, "new_age_group": new}
        for t, (gs, old, new, _) in rows.items()
    ]
    live = {
        t: {"team_id_master": t, "team_name": ours, "age_group": old, "gender": "Male", "is_deprecated": False}
        for t, (_, old, _new, ours) in rows.items()
    }

    def backed(sb, plan_rows):
        for r in plan_rows:
            r.update(fixture_verdict="backs_move", opp_games_proposed=5, opp_games_current=0)

    monkeypatch.setattr(fbc, "derive_candidates", lambda exports_dir=None: candidates)
    monkeypatch.setattr(fbc, "fetch_live", lambda sb, ids: {t: live[t] for t in ids})
    monkeypatch.setattr(fbc, "attach_fixture_evidence", backed)
    monkeypatch.setattr(fbc, "fetch_all_live_teams", lambda sb: [])

    plan = fbc.build_plan(_Db([]), tmp_path)

    got = {r["team_id_master"]: (r["action"], r["evidence_tier"]) for r in fbc.read_our_csv(plan)}
    assert got == {
        "a": ("held_name_contradicts", "D_name_contradicts"),
        "b": ("would_update", "C_bare_year_fits"),
        "c": ("would_update", "B_gotsport_name_only"),
    }


def test_apply_writes_a_2009_team_into_u19_and_holds_a_2010_one(exports, tmp_path, season_2026):
    fits = _plan_row(team_name="Club 2009 Boys", old_age_group="u17", new_age_group="u19")
    misses = _plan_row(
        team_id_master="22222222-2222-4222-8222-222222222222",
        team_name="Club 2010 Boys",
        old_age_group="u17",
        new_age_group="u19",
    )
    db = _Db([_team_row(fits), _team_row(misses)])

    _apply(db, _write_plan(tmp_path / "plan.csv", [fits, misses]), skip_name_contradictions=True)

    assert db.age_group(fits["team_id_master"]) == "u19"
    assert db.age_group(misses["team_id_master"]) == "u17"
    held = {r["team_id_master"]: r["result"] for r in _log_rows(exports)[1]}
    assert held[misses["team_id_master"]] == "held_name_contradicts"
DECIDED = "33333333-3333-4333-8333-333333333333"


def test_apply_holds_a_team_the_owner_decided_and_says_which_decision(exports, tmp_path, monkeypatch):
    _decisions(monkeypatch, tmp_path, {"left_held": [DECIDED]})
    rows = [_plan_row(), _plan_row(team_id_master=DECIDED, team_name="Queen City 2013/14 Girls")]
    db = _Db([_team_row(r) for r in rows])
    plan = _write_plan(tmp_path / "plan.csv", rows)

    _apply(db, plan)

    assert db.age_group(DECIDED) == "u14" and db.age_group(PLAN_ROW["team_id_master"]) == "u13"
    _, logged = _log_rows(exports)
    held = next(r for r in logged if r["team_id_master"] == DECIDED)
    assert held["result"] == "held_owner_decision"
    assert held["hold_reason"] == "owner decision left_held: 2026-10-01, left_held"


def test_a_held_owner_decision_is_not_reverted(exports, tmp_path, monkeypatch):
    _decisions(monkeypatch, tmp_path, {"kept_as_stored": [DECIDED]})
    row = _plan_row(team_id_master=DECIDED)
    db = _Db([_team_row(row)])
    _apply(db, _write_plan(tmp_path / "plan.csv", [row]))
    log, _ = _log_rows(exports)
    db.teams[DECIDED]["age_group"] = "u13"  # someone else moved it since

    fbc.revert(db, log, execute=True)

    assert db.age_group(DECIDED) == "u13"


@pytest.mark.parametrize("execute", [True, False], ids=["execute", "dry-run"])
def test_an_undo_leaves_a_team_the_owner_decided_on_since_the_batch(exports, tmp_path, monkeypatch, capsys, execute):
    """The log's id is upper-cased, as a hand-edited plan could carry it: Postgres would still match it."""
    decided = "bbbb3333-3333-4333-8333-3333bbbb3333"
    rows = [_plan_row(), _plan_row(team_id_master=decided.upper())]
    db = _Db([_team_row(r) for r in rows])
    _apply(db, _write_plan(tmp_path / "plan.csv", rows))
    log, _ = _log_rows(exports)
    _decisions(monkeypatch, tmp_path, {"kept_as_stored": [decided]})
    capsys.readouterr()

    fbc.revert(db, log, execute=execute)

    assert db.age_group(decided.upper()) == "u13"
    assert db.age_group(PLAN_ROW["team_id_master"]) == ("u14" if execute else "u13")
    assert re.search(r"held_owner_decision +1\b", capsys.readouterr().out)


def test_a_decision_on_a_merged_away_team_holds_its_survivor(exports, tmp_path, monkeypatch):
    """Merge chains are followed: the decided row was merged twice before this plan."""
    survivor = "44444444-4444-4444-8444-444444444444"
    middle = "55555555-5555-4555-8555-555555555555"
    _decisions(monkeypatch, tmp_path, {"ea_cleanup_2026_10_07": [DECIDED]})
    row = _plan_row(team_id_master=survivor)
    merges = [
        {"deprecated_team_id": DECIDED, "canonical_team_id": middle},
        {"deprecated_team_id": middle, "canonical_team_id": survivor},
    ]
    db = _Db([_team_row(row)], merges)

    _apply(db, _write_plan(tmp_path / "plan.csv", [row]))

    assert db.writes == [] and db.age_group(survivor) == "u14"
    assert _log_rows(exports)[1][0]["result"] == "held_owner_decision"


@pytest.mark.parametrize(
    "content",
    [
        None,
        "{not json",
        json.dumps({"left_held": {"decided": "x"}}),
        json.dumps({"left_held": {"teams": [{}]}}),
        json.dumps(["left_held"]),
        json.dumps({"left_held": {"decided": "x", "teams": ["a"]}}),
        json.dumps({"left_held": {"decided": "x", "teams": ""}}),
        json.dumps({"left_held": {"decided": "x", "teams": {}}}),
        json.dumps({"left_held": {"decided": "x", "teams": [{"team_id": "k"}]}}),
        json.dumps({"left_held": {"decided": "x", "teams": [{"team_id": None}]}}),
        '{"left_held": {"decided": "a", "teams": []}, "left_held": {"decided": "b", "teams": []}}',
    ],
    ids=[
        "missing",
        "not-json",
        "no-teams",
        "team-without-id",
        "not-an-object",
        "team-not-an-object",
        "teams-a-string",
        "teams-an-object",
        "id-not-a-team-id",
        "id-null",
        "section-repeated",
    ],
)
def test_an_unreadable_decisions_file_stops_the_apply_before_anything_is_written(
    exports, tmp_path, monkeypatch, content
):
    path = tmp_path / "broken.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(fbc, "OWNER_DECISIONS", path)
    db = _Db([_team_row(PLAN_ROW)])

    with pytest.raises(SystemExit, match="Cannot read the owner's age decisions"):
        _apply(db, _write_plan(tmp_path / "plan.csv", [PLAN_ROW]))
    assert db.writes == [] and list(exports.glob("fix_band_cohorts_apply_*.csv")) == []


def test_the_plan_skips_every_decided_team_first(exports, tmp_path, monkeypatch):
    """One team per section, each also a candidate the rules would move, beside one that is not decided."""
    kept, held, ea, free = (f"{c * 8}-{c * 4}-4{c * 3}-8{c * 3}-{c * 12}" for c in "abcd")
    _decisions(monkeypatch, tmp_path, {"kept_as_stored": [kept], "left_held": [held], "ea_cleanup_2026_10_07": [ea]})
    store = tmp_path / "store"
    store.mkdir()
    audits = [
        {
            "run_mode": "execute",
            "team_id_master": tid,
            "stored_age_group": "u14",
            "gotsport_age_group": "u13",
            "gotsport_team_name": "Rush 2013/2014 Red",
            "stored_team_name": "Rush 2013 Red",
        }
        for tid in (kept, held, ea, free)
    ]
    _write_reconcile(store, audits)
    live = {
        a["team_id_master"]: {
            "team_id_master": a["team_id_master"],
            "team_name": f"Rush 2013/2014 {colour}",
            "age_group": "u14",
            "gender": "Male",
            "is_deprecated": False,
        }
        for a, colour in zip(audits, ("Red", "White", "Blue", "Black"))
    }

    def evidence(sb, rows):
        for r in rows:
            r.update(fixture_verdict="backs_move", opp_games_proposed=5, opp_games_current=0)

    monkeypatch.setattr(fbc, "fetch_live", lambda sb, wanted: {t: live[t] for t in wanted})
    monkeypatch.setattr(fbc, "attach_fixture_evidence", evidence)
    monkeypatch.setattr(fbc, "fetch_all_live_teams", lambda sb: [])

    plan = fbc.build_plan(_Db([]), store)

    actions = {r["team_id_master"]: r["action"] for r in fbc.read_our_csv(plan)}
    assert actions == {
        kept: "skipped_owner_decision",
        held: "skipped_owner_decision",
        ea: "skipped_owner_decision",
        free: "would_update",
    }


def test_decided_ids_match_whatever_their_letter_case(exports, tmp_path, monkeypatch):
    merged_away = "aaaa3333-3333-4333-8333-3333aaaa3333"
    survivor = "44444444-4444-4444-8444-444444444444"
    other = "6666aaaa-6666-4666-8666-66666666aaaa"
    _decisions(monkeypatch, tmp_path, {"left_held": [merged_away.upper()], "kept_as_stored": [other]})
    merges = [{"deprecated_team_id": merged_away, "canonical_team_id": survivor}]
    rows = [_plan_row(team_id_master=survivor), _plan_row(team_id_master=other.upper())]
    db = _Db([_team_row(r) for r in rows], merges)

    _apply(db, _write_plan(tmp_path / "plan.csv", rows))

    assert db.writes == []
    assert [r["result"] for r in _log_rows(exports)[1]] == ["held_owner_decision", "held_owner_decision"]


def test_decisions_past_one_batch_of_ids_still_follow_their_merges(exports, tmp_path, monkeypatch):
    decided = [f"{n:08x}-0000-4000-8000-000000000000" for n in range(101)]
    survivor = "44444444-4444-4444-8444-444444444444"
    _decisions(monkeypatch, tmp_path, {"left_held": decided})
    row = _plan_row(team_id_master=survivor)
    db = _Db([_team_row(row)], [{"deprecated_team_id": decided[-1], "canonical_team_id": survivor}])

    _apply(db, _write_plan(tmp_path / "plan.csv", [row]))

    assert db.writes == []
    assert _log_rows(exports)[1][0]["result"] == "held_owner_decision"


def test_a_dry_run_apply_reports_a_decided_team_as_held(exports, tmp_path, monkeypatch):
    _decisions(monkeypatch, tmp_path, {"left_held": [DECIDED]})
    rows = [_plan_row(), _plan_row(team_id_master=DECIDED)]
    db = _Db([_team_row(r) for r in rows])

    _apply(db, _write_plan(tmp_path / "plan.csv", rows), execute=False)

    assert db.writes == []
    assert {r["team_id_master"]: r["result"] for r in _log_rows(exports)[1]} == {
        PLAN_ROW["team_id_master"]: "would_update",
        DECIDED: "held_owner_decision",
    }


def test_a_decisions_file_saved_with_a_byte_order_mark_still_loads(tmp_path, monkeypatch):
    path = tmp_path / "owner_decisions.json"
    path.write_text(json.dumps({"left_held": {"decided": "x", "teams": [{"team_id": DECIDED}]}}), encoding="utf-8-sig")
    monkeypatch.setattr(fbc, "OWNER_DECISIONS", path)

    assert fbc.load_owner_decisions(_Db([])) == {DECIDED: ("left_held", "x")}


def test_the_owner_s_decisions_file_in_the_repo_loads():
    decided = fbc.load_owner_decisions(_Db([]))

    assert {"kept_as_stored", "left_held", "ea_cleanup_2026_10_07"} <= {section for section, _ in decided.values()}
