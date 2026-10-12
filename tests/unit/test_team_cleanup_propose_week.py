"""Tests for the unattended weekly propose driver and its write guard."""

import csv
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest
from postgrest.exceptions import APIError

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import repair_swapped_club_names as swapped  # noqa: E402
from scripts.team_cleanup import propose_week as pw  # noqa: E402
from scripts.team_cleanup import write_guard  # noqa: E402
from scripts.team_cleanup.run_store import read_run, run_dir, write_run  # noqa: E402
from src.tournaments.storage._file_lock import _acquire_file_lock  # noqa: E402

DAY = "2026-10-14"
RUN = "2026-10-14-nv"
DEFAULT_RUN = "34866235667"


def _team(team_id, state="NV", club="Las Vegas Sports Academy", age="u12", *, deprecated=False):
    return {
        "team_id_master": team_id,
        "team_name": f"Team {team_id}",
        "club_name": club,
        "state_code": state,
        "age_group": age,
        "gender": "Male",
        "is_deprecated": deprecated,
    }


# --- scope and commands --------------------------------------------------------------------


def test_states_are_read_as_upper_case_codes_once_each():
    assert pw.parse_states(" nv,UT, NV ") == ["NV", "UT"]


@pytest.mark.parametrize("text", ["XX", "", "NV,"], ids=["unknown", "empty", "trailing-comma"])
def test_a_scope_that_is_not_all_state_codes_is_refused(text):
    with pytest.raises(ValueError, match="is not a US state code"):
        pw.parse_states(text)


def test_the_run_id_is_the_date_and_the_scope_and_names_a_run_folder(tmp_path):
    run_id = pw.run_id_for(date(2026, 10, 14), ["NH", "VT"])

    assert run_id == "2026-10-14-nh-vt"
    assert run_dir(tmp_path, run_id) == tmp_path / "runs" / "2026-10-14-nh-vt"


def test_the_age_review_covers_every_state_in_the_scope(tmp_path):
    review = pw.stage_commands("ages", tmp_path / "ages", ["NH", "VT"], tmp_path)[0]

    assert review[review.index("--state") + 1] == "NH,VT"


def test_the_club_scan_reads_every_saved_run_log_and_never_fetches_one(tmp_path):
    saved = tmp_path / "inputs" / "abbreviation_logs"
    saved.mkdir(parents=True)
    for name in ("35000000000.log", f"{DEFAULT_RUN}.log", "notes.txt"):
        (saved / name).write_text("log", encoding="utf-8")

    command = pw.stage_commands("clubs", tmp_path / "clubs", ["NV"], tmp_path)[0]

    assert command == [
        "scripts/repair_swapped_club_names.py",
        "--exports-dir",
        str(tmp_path / "clubs" / "national"),
        "--abbreviation-log",
        str(saved / f"{DEFAULT_RUN}.log"),
        "--abbreviation-log",
        str(saved / "35000000000.log"),
    ]


@pytest.mark.parametrize(
    "saved, lacking",
    [
        ([], True),
        (["notes.txt", f"{DEFAULT_RUN}.txt"], True),
        (["35000000000.log"], True),
        ([f"{DEFAULT_RUN}.log"], False),
    ],
    ids=["none", "not-a-log", "another-run-only", "the-default-run"],
)
def test_the_club_stage_needs_a_saved_copy_of_each_default_run_log(tmp_path, saved, lacking):
    folder = tmp_path / "inputs" / "abbreviation_logs"
    folder.mkdir(parents=True)
    for name in saved:
        (folder / name).write_text("log", encoding="utf-8")

    expected = (
        f"no saved copy of run {DEFAULT_RUN}'s log in {folder}; save it from Git Bash in the repo with "
        f'mkdir -p "{folder}" && gh run view {DEFAULT_RUN} --log > "{folder / DEFAULT_RUN}.log"'
    )
    assert pw.missing_input("clubs", tmp_path) == (expected if lacking else None)
    assert pw.missing_input("states", tmp_path) is None and pw.missing_input("ages", tmp_path) is None


def _scan_row(
    team_id,
    state,
    *,
    team_name=None,
    stored="LVSA",
    proposed="Las Vegas Sports Academy",
    needs_review=False,
    approved=True,
):
    """A club-scan row as the scan builds it, before its own writer escapes it."""
    return {
        "team_id_master": team_id,
        "provider": "gotsport",
        "state": state,
        "team_name": team_name or f"Team {team_id}",
        "stored_club": stored,
        "proposed_club": proposed,
        "source": "playmetrics",
        "tier": "provider",
        "needs_review": needs_review,
        "approved": approved,
        "state_note": "",
    }


def _as_scanned(*rows):
    return [swapped.snapshot_csv_row(row) for row in rows]


def test_club_scan_rows_are_cut_to_the_scope_and_read_as_the_values_the_teams_hold():
    rows = _as_scanned(
        _scan_row(
            "a",
            "NV",
            team_name="-Strikers 2014B",
            stored="=LVSA",
            proposed="'Ohana FC",
            needs_review=True,
            approved=False,
        ),
        _scan_row("b", "UT"),
        _scan_row("c", ""),
    )

    kept, proposals = pw.club_proposals(rows, ["NV"])

    assert kept == rows[:1]
    assert proposals == [
        {
            "team_id_master": "a",
            "team_name": "-Strikers 2014B",
            "field": "club_name",
            "old_value": "=LVSA",
            "new_value": "'Ohana FC",
            "tier": "provider",
            "source": "playmetrics",
            "needs_review": True,
            "approved": False,
        }
    ]


def _decision(team_id, pre, proposed, action="apply"):
    return {
        "team_id": team_id,
        "team_name": f"Team {team_id}",
        "club_name": "Club",
        "pre_image": pre,
        "proposed": proposed,
        "tier": "B",
        "confidence": 0.9,
        "action": action,
        "reason": "club-mates",
    }


def test_a_state_snapshot_keeps_decisions_moving_a_team_into_or_out_of_the_scope():
    into, out_of = _decision("into", None, "NV"), _decision("out", "NV", "CA", "queue")
    elsewhere, confirm = _decision("elsewhere", "CA", "AZ"), _decision("stays", "NV", "NV", "confirm")
    snapshot = {
        "rules": "authority",
        "created_at": "2026-10-14T18:00:00",
        "live_teams": 9,
        "decisions": [into, elsewhere, out_of, confirm],
    }

    scoped, proposals = pw.state_proposals(snapshot, ["NV"])

    assert scoped == {
        "rules": "authority",
        "created_at": "2026-10-14T18:00:00",
        "live_teams": 9,
        "decisions": [into, out_of, confirm],
    }
    assert proposals == [
        {
            "team_id_master": "into",
            "team_name": "Team into",
            "field": "state_code",
            "old_value": None,
            "new_value": "NV",
            "tier": "B",
            "action": "apply",
            "reason": "club-mates",
        },
        {
            "team_id_master": "out",
            "team_name": "Team out",
            "field": "state_code",
            "old_value": "NV",
            "new_value": "CA",
            "tier": "B",
            "action": "queue",
            "reason": "club-mates",
        },
    ]


def test_an_age_plan_row_reads_as_an_age_group_change():
    plan = [
        {
            "team_id_master": "a",
            "team_name": "A 2014B",
            "old_age_group": "u13",
            "new_age_group": "u12",
            "evidence_tier": "A_own_name_band",
            "state_code": "NV",
        }
    ]

    assert pw.age_proposals(plan) == [
        {
            "team_id_master": "a",
            "team_name": "A 2014B",
            "field": "age_group",
            "old_value": "u13",
            "new_value": "u12",
            "tier": "A_own_name_band",
        },
    ]


def test_the_club_stage_reads_the_newest_scan_and_a_scan_that_found_nothing_proposes_nothing(tmp_path):
    folder = tmp_path / "clubs"
    folder.mkdir()
    (folder / "repair_swapped_club_names.csv").write_text("an earlier attempt's cut", encoding="utf-8")

    assert pw.scoped_proposals("clubs", folder, ["NV"]) == []
    assert not (folder / "repair_swapped_club_names.csv").exists()

    older = _scan_row("older-scan", "NV")
    swapped.write_log(_as_scanned(older), folder / "national" / "repair_swapped_club_names_20261014_170000.csv")
    swapped.write_log(
        _as_scanned(_scan_row("nv-club", "NV")), folder / "national" / "repair_swapped_club_names_20261014_180000.csv"
    )

    assert [p["team_id_master"] for p in pw.scoped_proposals("clubs", folder, ["NV"])] == ["nv-club"]


# --- the write guard ---------------------------------------------------------------------


def test_the_guard_covers_every_field_a_stage_proposes():
    assert set(pw.FIELDS.values()) | {"is_deprecated"} == set(write_guard.GUARDED_FIELDS)


def test_changes_list_each_moved_field_and_teams_created_or_deleted_in_the_window():
    before = {"same": ["C", "NV", "u12", False], "moved": ["C", "NV", "u12", False], "gone": ["C", None, "u12", False]}
    after = {"same": ["C", "NV", "u12", False], "moved": ["C2", "NV", "u12", True], "new": [None, "NV", "u11", False]}

    assert write_guard.changes(before, after) == {
        "moved": {"club_name": ["C", "C2"], "is_deprecated": [False, True]},
        "gone": {"club_name": ["C", None], "age_group": ["u12", None], "is_deprecated": [False, None]},
        "new": {"state_code": [None, "NV"], "age_group": [None, "u11"], "is_deprecated": [None, False]},
    }


def test_a_proposal_is_stale_when_its_own_field_moved_or_its_team_stopped_being_live_or_appeared():
    moved = {
        "club": {"club_name": ["C", "C2"]},
        "state": {"state_code": [None, "UT"]},
        "merged": {"is_deprecated": [False, True]},
        "deleted": {"club_name": ["C", None], "is_deprecated": [False, None]},
        "created": {"club_name": [None, "C"], "is_deprecated": [None, False]},
    }
    proposals = [
        {"team_id_master": "club", "field": "club_name"},
        {"team_id_master": "state", "field": "club_name"},
        {"team_id_master": "merged", "field": "age_group"},
        {"team_id_master": "deleted", "field": "state_code"},
        {"team_id_master": "created", "field": "state_code"},
        {"team_id_master": "untouched", "field": "club_name"},
    ]

    assert write_guard.stale(proposals, moved) == [
        {"team_id_master": "club", "field": "club_name", "changed": {"club_name": ["C", "C2"]}},
        {"team_id_master": "merged", "field": "age_group", "changed": {"is_deprecated": [False, True]}},
        {"team_id_master": "deleted", "field": "state_code", "changed": {"is_deprecated": [False, None]}},
        {"team_id_master": "created", "field": "state_code", "changed": {"is_deprecated": [None, False]}},
    ]


# --- a week end to end ---------------------------------------------------------------------

COLUMNS = {
    "teams": {"team_id_master", "team_name", "club_name", "state_code", "age_group", "gender", "is_deprecated"},
    "team_cleanup_runs": {"run_id", "scope", "status", "budgets", "lease_holder", "lease_expires_at"},
}
OPEN = ("proposing", "reviewing", "applying", "second_lap")
ROW_CAP = 3


class _Result:
    def __init__(self, data):
        self.data = data


def _api_error(code, message):
    return APIError({"code": code, "message": message, "details": None, "hint": None})


class _Query:
    """Records each request at execute(), where the real builder sends it. It answers at most
    ROW_CAP rows, refuses a page with no order, and refuses an insert the runs table's primary key
    or one-open-run index would refuse."""

    def __init__(self, db, table, *, columns=None, insert=None, update=None):
        for column in [*(columns or ()), *(insert or {}), *(update or {})]:
            assert column in COLUMNS[table], f"PostgREST refuses unknown column {table}.{column}"
        self._db, self._table, self._columns, self._insert, self._update = db, table, columns, insert, update
        self._filters, self._order, self._range = [], None, None

    def eq(self, column, value):
        assert column in COLUMNS[self._table]
        self._filters.append((column, (value,)))
        return self

    def in_(self, column, values):
        assert column in COLUMNS[self._table]
        self._filters.append((column, tuple(values)))
        return self

    def order(self, column):
        assert column in COLUMNS[self._table]
        self._order = column
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def _matching(self):
        return [row for row in self._db.tables[self._table] if all(row[c] in v for c, v in self._filters)]

    def execute(self):
        kind = "insert" if self._insert else "update" if self._update else "select"
        self._db.executes.append((self._table, kind, tuple(self._filters), self._insert or self._update))
        result = self._run()
        if kind in self._db.lost:
            raise self._db.lost.pop(kind)
        return result

    def _run(self):
        rows = self._db.tables[self._table]
        if self._insert:
            if any(row["run_id"] == self._insert["run_id"] for row in rows):
                raise _api_error("23505", "duplicate key value violates unique constraint")
            if self._insert["status"] in OPEN and any(row["status"] in OPEN for row in rows):
                raise _api_error("23505", "duplicate key value violates unique constraint one open run")
            rows.append(dict(self._insert))
            return _Result([dict(self._insert)])
        if self._update:
            matched = self._matching()
            for row in matched:
                row.update(self._update)
            return _Result([dict(row) for row in matched])
        assert self._order or self._range is None, "a page with no order is arbitrary"
        found = sorted(self._matching(), key=lambda r: r[self._order]) if self._order else self._matching()
        if self._range:
            found = found[self._range[0] : self._range[1] + 1]
        return _Result([{c: r[c] for c in self._columns} for r in found[:ROW_CAP]])


class _Db:
    """``lost`` maps "insert" or "update" to the error its next execute() raises after the write
    lands, as when a gateway or a dropped connection loses the answer to a committed write."""

    def __init__(self, teams, runs=(), lost=None):
        self.tables = {"teams": teams, "team_cleanup_runs": [dict(r) for r in runs]}
        self.executes, self.lost = [], dict(lost or {})

    def table(self, name):
        db = self

        class _T:
            def select(self, columns):
                return _Query(db, name, columns=[c.strip() for c in columns.split(",")])

            def insert(self, payload):
                return _Query(db, name, insert=payload)

            def update(self, payload):
                return _Query(db, name, update=payload)

        return _T()

    def writes(self):
        return [e for e in self.executes if e[1] != "select"]

    def team_reads(self):
        return [e for e in self.executes if e[0] == "teams"]


def _arg(command, flag):
    return Path(command[command.index(flag) + 1])


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


SCAN_ROWS = (
    _scan_row("nv-club", "NV", stored="-LVSA"),
    _scan_row("ut-club", "UT"),
    _scan_row("no-state", ""),
)
STATE_DECISIONS = (
    _decision("nv-none", None, "NV"),
    _decision("az1", "CA", "AZ"),
    _decision("ut1", "UT", "CO", "queue"),
)


class _Runner:
    """Stands in for each script: records the command and writes the files the script would,
    through the scan's own writer where it has one. ``codes`` maps a script name to whether each of
    its successive runs fails (a truthy entry exits 2); ``during`` maps one to a change it makes to
    the database, as a concurrent writer would."""

    def __init__(self, db, codes=None, during=None, club_rows=SCAN_ROWS):
        self.db, self.codes, self.during, self.commands = db, codes or {}, during or {}, []
        self.club_rows = club_rows

    def __call__(self, command, log):
        script = Path(command[0]).name
        self.commands.append(command)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(f"ran {script}", encoding="utf-8")
        if script in self.during:
            self.during.pop(script)(self.db)
        codes = self.codes.get(script, [])
        if codes and codes.pop(0):
            return 2
        if script == "repair_swapped_club_names.py":
            exports = _arg(command, "--exports-dir")  # like the scan, writes no file when it finds nothing
            swapped.write_log(_as_scanned(*self.club_rows), exports / "repair_swapped_club_names_20261014_180000.csv")
        elif script == "assign_team_states.py":
            snapshot = {
                "rules": "authority",
                "created_at": "2026-10-14T18:00:00",
                "live_teams": 4,
                "decisions": list(STATE_DECISIONS),
            }
            _arg(command, "--out").write_text(json.dumps(snapshot), encoding="utf-8")
        elif script == "review_age_labels.py" and command[1] == "review":
            _write_csv(_arg(command, "--out"), [{"group": "1", "team_id": "nv-age"}])
        elif script == "review_age_labels.py":
            plan = {
                "team_id_master": "nv-age",
                "team_name": "Team nv-age",
                "old_age_group": "u13",
                "new_age_group": "u12",
                "evidence_tier": "A_own_name_band",
            }
            _write_csv(_arg(command, "--out"), [plan])
        return 0


def _teams():
    return [_team("nv-club", club="-LVSA"), _team("nv-none", state=None), _team("nv-age", age="u13"), _team("az1")]


def _store(tmp_path, name="store"):
    store = tmp_path / name
    saved = store / "inputs" / "abbreviation_logs"
    saved.mkdir(parents=True, exist_ok=True)
    (saved / f"{DEFAULT_RUN}.log").write_text("saved log", encoding="utf-8")
    return store


def _main(monkeypatch, capsys, db, runner, *argv):
    monkeypatch.setattr(pw, "get_client", lambda: db)
    monkeypatch.setattr(pw, "run_step", runner)
    monkeypatch.setattr(sys, "argv", ["propose_week.py", *argv])
    code = pw.main()
    return code, capsys.readouterr().out


def _week(monkeypatch, capsys, store, db, runner, states="NV"):
    return _main(monkeypatch, capsys, db, runner, "--states", states, "--store", str(store), "--date", DAY)


def _json(store, *parts, run=RUN):
    return json.loads(run_dir(store, run).joinpath(*parts).read_text(encoding="utf-8"))


def _expected(store):
    """Each step of a Nevada week, by name: the script and its arguments."""
    folder = run_dir(store, RUN)
    age_review = ".claude/skills/correcting-team-age-groups/scripts/review_age_labels.py"
    return {
        "clubs": [
            "scripts/repair_swapped_club_names.py",
            "--exports-dir",
            str(folder / "clubs" / "national"),
            "--abbreviation-log",
            str(store / "inputs" / "abbreviation_logs" / f"{DEFAULT_RUN}.log"),
        ],
        "state_check": ["scripts/check_state_skill_assumptions.py", "--code-only"],
        "states": [
            "scripts/assign_team_states.py",
            "--no-tier-a",
            "--out",
            str(folder / "states" / "national_snapshot.json"),
        ],
        "age_check": ["scripts/check_age_skill_assumptions.py", "--code-only"],
        "age_review": [
            age_review,
            "review",
            "--state",
            "NV",
            "--exports-dir",
            str(store / "exports"),
            "--out",
            str(folder / "ages" / "age_label_review.csv"),
        ],
        "age_plan": [
            age_review,
            "write-plan",
            str(folder / "ages" / "age_label_review.csv"),
            "--groups",
            "1,2,3",
            "--out",
            str(folder / "ages" / "plan.csv"),
        ],
        "health": ["scripts/team_cleanup/health.py", "--store", str(store), "--date", DAY],
    }


def _retry(store, states="NV"):
    command = ["scripts/team_cleanup/propose_week.py", "--states", states, "--date", DAY, "--store", str(store)]
    return f"python {subprocess.list2cmdline(command)}"


def test_a_week_opens_the_run_proposes_each_stage_for_the_scope_and_moves_to_reviewing(monkeypatch, capsys, tmp_path):
    store, db = _store(tmp_path), _Db(_teams())

    def another_session_fills_the_state(db):
        db.tables["teams"][1]["state_code"] = "UT"

    runner = _Runner(db, during={"assign_team_states.py": another_session_fills_the_state})
    code, out = _week(monkeypatch, capsys, store, db, runner)

    assert code == 0 and "ready for review" in out
    assert runner.commands == list(_expected(store).values())
    assert db.writes() == [
        (
            "team_cleanup_runs",
            "insert",
            (),
            {"run_id": RUN, "scope": {"states": ["NV"]}, "status": "proposing", "budgets": {}},
        ),
        ("team_cleanup_runs", "update", (("run_id", (RUN,)), ("status", ("proposing",))), {"status": "reviewing"}),
    ]
    run = read_run(store, RUN)
    assert run["status"] == "reviewing" and run["scope"] == {"states": ["NV"]}
    assert run["stages"] == {
        "reconcile": "not run: reconcile is run by hand",
        "merges": "not run: the duplicate scans are frozen until the owner resumes them",
    }
    assert _json(store, "clubs", "proposals.json") == [
        {
            "team_id_master": "nv-club",
            "team_name": "Team nv-club",
            "field": "club_name",
            "old_value": "-LVSA",
            "new_value": "Las Vegas Sports Academy",
            "tier": "provider",
            "source": "playmetrics",
            "needs_review": False,
            "approved": True,
        },
    ]
    assert [p["team_id_master"] for p in _json(store, "states", "proposals.json")] == ["nv-none"]
    assert [p["team_id_master"] for p in _json(store, "ages", "proposals.json")] == ["nv-age"]
    assert _json(store, "states", "stale.json") == [
        {
            "team_id_master": "nv-none",
            "team_name": "Team nv-none",
            "field": "state_code",
            "old_value": None,
            "new_value": "NV",
            "tier": "B",
            "action": "apply",
            "reason": "club-mates",
            "changed": {"state_code": [None, "UT"]},
        },
    ]
    assert _json(store, "clubs", "stale.json") == [] and _json(store, "ages", "stale.json") == []
    guard = _json(store, "write_guard.json")
    assert (guard["teams_changed"], guard["stale"]) == (1, {"clubs": 0, "states": 1, "ages": 0})
    assert not (run_dir(store, RUN) / "write_guard_before.json").exists()
    for stage in ("clubs", "states", "ages"):
        assert (run_dir(store, RUN) / stage / "propose_done").exists()


def test_the_scoped_files_are_what_each_applier_reads_back(monkeypatch, capsys, tmp_path):
    store, db = _store(tmp_path), _Db(_teams())
    _week(monkeypatch, capsys, store, db, _Runner(db))

    clubs = swapped.load_snapshot(run_dir(store, RUN) / "clubs" / "repair_swapped_club_names.csv")
    assert clubs == [
        {
            "team_id_master": "nv-club",
            "provider": "gotsport",
            "state": "NV",
            "team_name": "Team nv-club",
            "stored_club": "-LVSA",
            "proposed_club": "Las Vegas Sports Academy",
            "source": "playmetrics",
            "tier": "provider",
            "needs_review": "false",
            "approved": "true",
            "state_note": "",
        }
    ]
    snapshot = _json(store, "states", "snapshot.json")
    assert {key: value for key, value in snapshot.items() if key != "decisions"} == {
        "rules": "authority",
        "created_at": "2026-10-14T18:00:00",
        "live_teams": 4,
    }
    assert [d["team_id"] for d in snapshot["decisions"]] == ["nv-none"]


def test_a_scope_of_two_states_keeps_both_states_proposals(monkeypatch, capsys, tmp_path):
    store, db = _store(tmp_path), _Db(_teams())

    code, _ = _week(monkeypatch, capsys, store, db, _Runner(db), states="NV,UT")

    run = "2026-10-14-nv-ut"
    assert code == 0
    assert [p["team_id_master"] for p in _json(store, "clubs", "proposals.json", run=run)] == ["nv-club", "ut-club"]
    assert [p["team_id_master"] for p in _json(store, "states", "proposals.json", run=run)] == ["nv-none", "ut1"]


def test_no_step_writes_teams_or_spends_paid_probes(monkeypatch, capsys, tmp_path):
    db = _Db(_teams())
    runner = _Runner(db)
    _week(monkeypatch, capsys, _store(tmp_path), db, runner)

    scripts = {Path(command[0]).name for command in runner.commands}
    assert scripts == {
        "repair_swapped_club_names.py",
        "check_state_skill_assumptions.py",
        "assign_team_states.py",
        "check_age_skill_assumptions.py",
        "review_age_labels.py",
        "health.py",
    }
    assert not any(flag in command for command in runner.commands for flag in ("--execute", "--apply", "--revert"))
    states = next(c for c in runner.commands if Path(c[0]).name == "assign_team_states.py")
    assert "--no-tier-a" in states


def test_another_open_run_is_refused_before_anything_runs(monkeypatch, capsys, tmp_path):
    db = _Db(_teams(), runs=[{"run_id": "2026-10-07-ut", "status": "reviewing"}])
    runner = _Runner(db)

    with pytest.raises(SystemExit, match="Run 2026-10-07-ut is still reviewing"):
        _week(monkeypatch, capsys, _store(tmp_path), db, runner)

    assert runner.commands == [] and db.writes() == []
    assert not run_dir(_store(tmp_path), RUN).exists()


def test_a_finished_run_in_the_table_does_not_stop_the_next_one(monkeypatch, capsys, tmp_path):
    db = _Db(_teams(), runs=[{"run_id": "2026-10-07-ut", "status": "done"}])

    code, _ = _week(monkeypatch, capsys, _store(tmp_path), db, _Runner(db))

    assert code == 0
    assert [(row["run_id"], row["status"]) for row in db.tables["team_cleanup_runs"]] == [
        ("2026-10-07-ut", "done"),
        (RUN, "reviewing"),
    ]


def test_a_run_past_proposing_is_not_proposed_again(monkeypatch, capsys, tmp_path):
    db = _Db(_teams(), runs=[{"run_id": RUN, "status": "reviewing"}])
    runner = _Runner(db)

    with pytest.raises(SystemExit, match=f"Run {RUN} is reviewing: its proposals are written"):
        _week(monkeypatch, capsys, _store(tmp_path), db, runner)

    assert runner.commands == [] and db.writes() == []


def test_a_run_its_own_file_has_closed_is_refused_before_the_table_is_written(monkeypatch, capsys, tmp_path):
    store, db = _store(tmp_path), _Db(_teams())
    write_run(store, {"run_id": RUN, "scope": {"states": ["NV"]}, "status": "reviewing", "budgets": {}})

    with pytest.raises(SystemExit, match=f"Run {RUN} is reviewing: its proposals are written"):
        _week(monkeypatch, capsys, store, db, _Runner(db))

    assert db.executes == []


@pytest.mark.parametrize(
    "lost",
    [_api_error(502, "JSON could not be generated"), httpx.ReadTimeout("timed out")],
    ids=["gateway", "timeout"],
)
def test_a_close_whose_answer_was_lost_says_how_to_retry_and_the_retry_catches_up(monkeypatch, capsys, tmp_path, lost):
    store, db = _store(tmp_path), _Db(_teams(), lost={"update": lost})

    with pytest.raises(SystemExit) as stopped:
        _week(monkeypatch, capsys, store, db, _Runner(db))
    assert "the database's answer was lost" in str(stopped.value.code) and _retry(store) in str(stopped.value.code)
    assert read_run(store, RUN)["status"] == "proposing"
    assert db.tables["team_cleanup_runs"][0]["status"] == "reviewing"

    with pytest.raises(SystemExit, match=f"Run {RUN} is reviewing: its proposals are written"):
        _week(monkeypatch, capsys, store, db, _Runner(db))

    assert read_run(store, RUN)["status"] == "reviewing"


@pytest.mark.parametrize(
    "lost",
    [_api_error(504, "JSON could not be generated"), httpx.ReadTimeout("timed out")],
    ids=["gateway", "timeout"],
)
def test_an_insert_whose_answer_was_lost_is_resumed_by_the_retry_it_prints(monkeypatch, capsys, tmp_path, lost):
    store, db = _store(tmp_path), _Db(_teams(), lost={"insert": lost})
    first = _Runner(db)

    with pytest.raises(SystemExit) as stopped:
        _week(monkeypatch, capsys, store, db, first)

    assert "the database's answer was lost" in str(stopped.value.code) and _retry(store) in str(stopped.value.code)
    assert first.commands == [] and db.tables["team_cleanup_runs"][0]["status"] == "proposing"

    code, _ = _week(monkeypatch, capsys, store, db, _Runner(db))

    assert code == 0 and [e[1] for e in db.writes()] == ["insert", "update"]
    assert read_run(store, RUN)["status"] == "reviewing"


def test_an_insert_the_table_refuses_says_why(monkeypatch, capsys, tmp_path):
    db = _Db(_teams(), runs=[{"run_id": RUN, "status": "abandoned"}])
    runner = _Runner(db)

    with pytest.raises(SystemExit, match="Could not open run 2026-10-14-nv: duplicate key"):
        _week(monkeypatch, capsys, _store(tmp_path), db, runner)

    assert runner.commands == []


def test_a_failed_stage_keeps_the_run_open_and_a_retry_on_a_later_day_resumes_only_that_stage(
    monkeypatch, capsys, tmp_path
):
    store, db = _store(tmp_path), _Db(_teams())
    first = _Runner(db, codes={"assign_team_states.py": [1]})

    code, out = _week(monkeypatch, capsys, store, db, first)

    folder = run_dir(store, RUN)
    assert code == 1 and f"Retry states with: {_retry(store)}" in out
    assert read_run(store, RUN)["stages"]["states"] == (
        f"failed: assign_team_states.py exited 2; see {folder / 'states' / 'logs' / '1_assign_team_states.log'}"
    )
    assert [e[1] for e in db.writes()] == ["insert"]
    assert (folder / "write_guard_before.json").exists() and not (folder / "states" / "propose_done").exists()
    opened = json.loads((folder / "write_guard_before.json").read_text(encoding="utf-8"))["taken_at"]

    second = _Runner(db)
    code, _ = _week(monkeypatch, capsys, store, db, second)

    expected = _expected(store)
    assert code == 0
    assert second.commands == [expected["states"], expected["health"]]
    assert "states" not in read_run(store, RUN)["stages"]
    assert _json(store, "write_guard.json")["from"] == opened
    assert [e[1] for e in db.writes()] == ["insert", "update"]


def test_the_retry_names_every_state_in_the_scope(monkeypatch, capsys, tmp_path):
    store, db = _store(tmp_path), _Db(_teams())

    code, out = _week(monkeypatch, capsys, store, db, _Runner(db, codes={"assign_team_states.py": [1]}), "NV,UT")

    assert code == 1 and f"Retry states with: {_retry(store, 'NV,UT')}" in out


def test_a_failing_self_check_marks_the_stage_stale_and_the_others_go_on(monkeypatch, capsys, tmp_path):
    store, db = _store(tmp_path), _Db(_teams())
    runner = _Runner(db, codes={"check_state_skill_assumptions.py": [1]})

    code, _ = _week(monkeypatch, capsys, store, db, runner)

    folder = run_dir(store, RUN) / "states"
    assert code == 0
    assert "assign_team_states.py" not in {Path(c[0]).name for c in runner.commands}
    run = read_run(store, RUN)
    assert run["status"] == "reviewing"
    assert run["stages"]["states"] == (
        f"skill_stale: check_state_skill_assumptions.py exited 2; see {folder / 'logs' / 'self_check.log'}"
    )
    assert not (folder / "preflight.json").exists() and not (folder / "proposals.json").exists()
    assert _json(store, "write_guard.json")["stale"] == {"clubs": 0, "ages": 0}


def test_a_failed_health_report_is_retried_alone_without_reading_the_teams_again(monkeypatch, capsys, tmp_path):
    store, db = _store(tmp_path), _Db(_teams())

    code, out = _week(monkeypatch, capsys, store, db, _Runner(db, codes={"health.py": [1]}))

    assert code == 1 and f"Retry with: {_retry(store)}" in out
    assert read_run(store, RUN)["status"] == "proposing"
    assert [e[1] for e in db.writes()] == ["insert"]
    guard = _json(store, "write_guard.json")
    reads = len(db.team_reads())

    second = _Runner(db)
    code, _ = _week(monkeypatch, capsys, store, db, second)

    assert code == 0 and second.commands == [_expected(store)["health"]]
    assert _json(store, "write_guard.json") == guard and len(db.team_reads()) == reads
    assert not (run_dir(store, RUN) / "write_guard_before.json").exists()
    assert read_run(store, RUN)["status"] == "reviewing"


def test_a_stage_whose_self_check_failed_waits_for_next_week_once_the_guard_has_closed(monkeypatch, capsys, tmp_path):
    store, db = _store(tmp_path), _Db(_teams())
    codes = {"check_state_skill_assumptions.py": [1], "health.py": [1]}
    _week(monkeypatch, capsys, store, db, _Runner(db, codes=codes))
    note = read_run(store, RUN)["stages"]["states"]

    second = _Runner(db)
    code, _ = _week(monkeypatch, capsys, store, db, second)

    assert code == 0 and second.commands == [_expected(store)["health"]]
    assert read_run(store, RUN)["stages"]["states"] == note
    assert not (run_dir(store, RUN) / "states" / "proposals.json").exists()


def test_a_club_step_without_a_saved_copy_of_the_default_run_fails_and_says_how_to_save_one(
    monkeypatch, capsys, tmp_path
):
    store, db = tmp_path / "store", _Db(_teams())
    folder = store / "inputs" / "abbreviation_logs"
    folder.mkdir(parents=True)
    (folder / f"{DEFAULT_RUN}.txt").write_text("saved under the wrong name", encoding="utf-8")
    runner = _Runner(db)

    code, _ = _week(monkeypatch, capsys, store, db, runner)

    assert code == 1
    assert read_run(store, RUN)["stages"]["clubs"] == (
        f"failed: no saved copy of run {DEFAULT_RUN}'s log in {folder}; save it from Git Bash in the repo with "
        f'mkdir -p "{folder}" && gh run view {DEFAULT_RUN} --log > "{folder / DEFAULT_RUN}.log"'
    )
    assert "repair_swapped_club_names.py" not in {Path(c[0]).name for c in runner.commands}


def test_a_retried_club_stage_never_reads_an_earlier_attempt_s_scan(monkeypatch, capsys, tmp_path):
    store, db = _store(tmp_path), _Db(_teams())
    earlier = run_dir(store, RUN) / "clubs" / "national" / "repair_swapped_club_names_20261014_170000.csv"
    swapped.write_log(_as_scanned(_scan_row("from-the-first-attempt", "NV")), earlier)

    _week(monkeypatch, capsys, store, db, _Runner(db, club_rows=()))

    assert _json(store, "clubs", "proposals.json") == []


def test_a_run_abandoned_while_proposing_is_left_as_it_is(monkeypatch, capsys, tmp_path):
    store, db = _store(tmp_path), _Db(_teams())

    def the_owner_abandons_it(db):
        db.tables["team_cleanup_runs"][0]["status"] = "abandoned"

    runner = _Runner(db, during={"health.py": the_owner_abandons_it})

    with pytest.raises(SystemExit, match=f"Run {RUN} is no longer proposing"):
        _week(monkeypatch, capsys, store, db, runner)

    assert read_run(store, RUN)["status"] == "proposing"
    assert db.tables["team_cleanup_runs"][0]["status"] == "abandoned"


def test_the_write_guard_reads_every_team_past_the_row_cap():
    db = _Db([_team(f"t{i}") for i in (4, 0, 3, 1, 2)])

    assert sorted(write_guard.snapshot(db)) == ["t0", "t1", "t2", "t3", "t4"]


def test_a_dry_run_prints_each_step_quoted_and_touches_nothing(monkeypatch, capsys, tmp_path):
    db = _Db(_teams())
    runner = _Runner(db)
    store = _store(tmp_path, name="cleanup store")
    before = sorted(str(p) for p in store.rglob("*"))

    code, out = _main(
        monkeypatch, capsys, db, runner, "--states", "NV", "--store", str(store), "--date", DAY, "--dry-run"
    )

    snapshot = run_dir(store, RUN) / "states" / "national_snapshot.json"
    assert code == 0 and "DRY RUN" in out
    assert f'python scripts/assign_team_states.py --no-tier-a --out "{snapshot}"' in out
    assert runner.commands == [] and db.executes == [] and sorted(str(p) for p in store.rglob("*")) == before


def test_a_dry_run_shows_a_stage_that_would_fail_for_want_of_an_input(monkeypatch, capsys, tmp_path):
    db = _Db(_teams())
    store = tmp_path / "store"

    code, out = _main(monkeypatch, capsys, db, _Runner(db), "--states", "NV", "--store", str(store), "--dry-run")

    assert code == 0 and f"    would fail: no saved copy of run {DEFAULT_RUN}'s log" in out
    assert "repair_swapped_club_names.py" not in out and not store.exists()


def test_a_second_propose_in_the_same_store_is_refused(monkeypatch, capsys, tmp_path):
    store, db = _store(tmp_path), _Db(_teams())
    runner = _Runner(db)

    with _acquire_file_lock(store / "propose.lock", timeout=0.0):
        with pytest.raises(SystemExit, match="Another propose is already running"):
            _week(monkeypatch, capsys, store, db, runner)

    assert runner.commands == [] and db.executes == []


@pytest.mark.parametrize(
    "argv, message",
    [
        (["--states", "XX"], "'XX' is not a US state code"),
        (["--states", "NV", "--store", "rel"], "absolute path"),
        (["--states", "NV", "--date", "2026-13-01"], "--date: month must be in 1..12"),
    ],
    ids=["unknown-state", "relative-store", "bad-date"],
)
def test_bad_arguments_exit_with_a_message(monkeypatch, capsys, tmp_path, argv, message):
    with pytest.raises(SystemExit) as stopped:
        _main(monkeypatch, capsys, _Db(_teams()), _Runner(None), *argv)
    assert message in str(stopped.value.code)


# --- running a step ------------------------------------------------------------------------


def test_a_step_runs_from_the_repo_in_utf_8_with_its_output_and_errors_in_its_log(monkeypatch, tmp_path):
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "step.py"
    script.write_text(
        "import os\nprint(os.getcwd())\nprint(os.environ.get('PYTHONUTF8'), 'Zoë ✓', flush=True)\n"
        "raise RuntimeError('boom')\n",
        encoding="utf-8",
    )
    log = tmp_path / "logs" / "step.log"

    assert pw.run_step([str(script)], log) == 1
    lines = log.read_text(encoding="utf-8").splitlines()
    assert lines[:2] == [str(pw.ROOT), "1 Zoë ✓"]
    assert lines[-1] == "RuntimeError: boom"


def test_a_step_that_overruns_is_stopped(monkeypatch, tmp_path):
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    monkeypatch.setattr(pw, "STEP_TIMEOUT_SECONDS", 1)
    log = tmp_path / "slow.log"

    assert pw.run_step([str(script)], log) == -1
    assert "Stopped after 1 seconds." in log.read_text(encoding="utf-8")
