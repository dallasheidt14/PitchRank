"""Tests for the team-cleanup run store: run files, stage progress read from markers, and the apply lock."""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from postgrest.exceptions import APIError

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.team_cleanup import run_store as rs  # noqa: E402

RUN = "2026-10-14-nv"
MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def _newest_create_table(table):
    """Comments are stripped so a commented-out definition does not count."""
    found = None
    for path in sorted(MIGRATIONS.glob("*.sql")):
        sql = re.sub(r"/\*.*?\*/", " ", path.read_text(encoding="utf-8"), flags=re.S)
        sql = re.sub(r"--[^\n]*", "", sql)
        for match in re.finditer(rf"(?is)create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?{table}\s*\(", sql):
            found = sql[match.start() : sql.index(";", match.end()) + 1]
    assert found, f"no migration creates {table}"
    return found


def _store(tmp_path, status="reviewing", name="store"):
    store = tmp_path / name
    rs.write_run(store, {"run_id": RUN, "scope": {"states": ["NV"]}, "status": status})
    return store


def _stage(store, stage="merges"):
    folder = rs.stage_dir(store, RUN, stage)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _mark(folder, *markers):
    for marker in markers:
        (folder / marker).write_text("{}", encoding="utf-8")


def _pair(n):
    return {
        "merge_id": f"m{n}",
        "keep_id": f"k{n}",
        "merge_name": f"Merge {n}",
        "keep_name": f"Keep {n}",
        "evidence": "shared fixtures",
    }


def _proposal(folder, name, rows, review=None):
    review_dir = folder / rs.REVIEW_DIR
    review_dir.mkdir(exist_ok=True)
    (review_dir / f"{name}.json").write_text(json.dumps(rows), encoding="utf-8")
    if review is not None:
        text = review if isinstance(review, str) else json.dumps(review)
        (review_dir / f"{name}{rs.REVIEW_SUFFIX}").write_text(text, encoding="utf-8")
    return review_dir


def _verdicts(rows, **changed):
    return [
        {
            "merge_id": r["merge_id"],
            "keep_id": r["keep_id"],
            "merge_name": r["merge_name"],
            "keep_name": r["keep_name"],
            "verdict": "merge",
            **changed,
        }
        for r in rows
    ]


# --- the store -------------------------------------------------------------------------------


def test_the_store_given_wins_over_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(rs.STORE_ENV, str(tmp_path / "elsewhere"))
    assert rs.store_dir(tmp_path / "given") == (tmp_path / "given").resolve()


def test_the_store_is_the_folder_the_environment_names(monkeypatch, tmp_path):
    monkeypatch.setenv(rs.STORE_ENV, str(tmp_path / "elsewhere"))
    assert rs.store_dir() == (tmp_path / "elsewhere").resolve()


def test_the_store_defaults_to_a_folder_in_the_home_folder(monkeypatch, tmp_path):
    monkeypatch.delenv(rs.STORE_ENV, raising=False)
    monkeypatch.setattr(rs.Path, "home", classmethod(lambda cls: tmp_path))
    assert rs.store_dir() == tmp_path / "pitchrank-cleanup-runs"


def test_a_relative_store_is_refused_from_either_source(monkeypatch):
    monkeypatch.setenv(rs.STORE_ENV, "cleanup-runs")
    with pytest.raises(ValueError, match="must be an absolute path, not 'cleanup-runs'"):
        rs.store_dir()
    monkeypatch.delenv(rs.STORE_ENV)
    with pytest.raises(ValueError, match="must be an absolute path, not 'given-runs'"):
        rs.store_dir(Path("given-runs"))


def test_the_statuses_are_the_ones_the_runs_table_checks():
    """The runs migration's CHECK and one-open-run index spell these out too, pinned by its tests."""
    assert rs.OPEN_STATUSES == ("proposing", "reviewing", "applying", "second_lap")
    assert rs.STATUSES == ("proposing", "reviewing", "applying", "second_lap", "done", "abandoned")


def test_the_stages_are_the_ones_the_decisions_table_accepts():
    """The applier records each stage's decisions there, so a stage its CHECK refuses fails mid-apply."""
    [listed] = re.findall(
        r"stage TEXT NOT NULL CHECK \(stage IN \(([^)]*)\)\)", _newest_create_table("team_cleanup_decisions")
    )
    accepted = tuple(stage.strip(" '") for stage in listed.split(","))

    assert rs.STAGES == accepted == ("reconcile", "clubs", "states", "ages", "merges")


@pytest.mark.parametrize(
    "run_id", ["../2026-10-14-nv", "2026-10-14-NV", "nv", "2026-10-14-nv/..", "2026-10-14-nv\n", ""]
)
def test_a_run_id_that_is_not_a_dated_scope_is_refused(tmp_path, run_id):
    with pytest.raises(ValueError, match="is not a run id"):
        rs.run_dir(tmp_path, run_id)


@pytest.mark.parametrize(
    "run_id, accepted",
    [
        ("2026-10-14-nv", True),
        ("2026-10-14-nv-ut-ks", True),
        ("2026-10-14-ca-u12", True),
        ("2026-10-14-n_v", False),
        ("2026-10-14-nv-", False),
        ("2026-10-14--nv", False),
        ("2026-10-14", False),
        ("2026-10-14-nv\n", False),
    ],
)
def test_the_store_and_the_database_accept_the_same_run_ids(tmp_path, run_id, accepted):
    [database] = re.findall(r"run_id ~ '([^']+)'", _newest_create_table("team_cleanup_runs"))
    try:
        rs.run_dir(tmp_path, run_id)
        stored = True
    except ValueError:
        stored = False

    assert (stored, re.fullmatch(database, run_id) is not None) == (accepted, accepted)


def test_a_stage_outside_the_five_is_refused(tmp_path):
    with pytest.raises(ValueError, match="is not a stage"):
        rs.stage_dir(tmp_path, RUN, "games")


def test_a_run_file_round_trips_and_is_stamped(tmp_path):
    store = _store(tmp_path)
    run = rs.read_run(store, RUN)
    assert (run["run_id"], run["status"], run["scope"]) == (RUN, "reviewing", {"states": ["NV"]})
    assert datetime.fromisoformat(run["updated_at"]) > datetime.now(timezone.utc) - timedelta(minutes=1)


def test_a_run_file_refuses_an_unknown_status_or_stage(tmp_path):
    with pytest.raises(ValueError, match="is not a run status"):
        rs.write_run(tmp_path, {"run_id": RUN, "scope": {}, "status": "paused"})
    with pytest.raises(ValueError, match="stages that do not exist"):
        rs.write_run(tmp_path, {"run_id": RUN, "scope": {}, "status": "proposing", "stages": {"games": "x"}})


@pytest.mark.parametrize(
    "content",
    [json.dumps({"run_id": "2026-10-07-ut", "status": "done"}), json.dumps([RUN]), json.dumps({"run_id": RUN})],
    ids=["another-run-s-file", "not-an-object", "no-status"],
)
def test_a_folder_holding_something_other_than_its_own_run_file_cannot_be_read(tmp_path, content):
    (tmp_path / "runs" / RUN).mkdir(parents=True)
    (tmp_path / "runs" / RUN / rs.RUN_FILE).write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=f"is not a run file for {RUN}"):
        rs.read_run(tmp_path, RUN)
    assert rs.list_runs(tmp_path) == []


def test_runs_list_newest_first_and_skip_unreadable_files(tmp_path):
    store = tmp_path / "store"
    for run_id, status in (("2026-10-07-ut", "done"), ("2026-10-14-nv", "reviewing")):
        rs.write_run(store, {"run_id": run_id, "scope": {}, "status": status})
    (store / "runs" / "2026-10-21-ks").mkdir()
    (store / "runs" / "2026-10-21-ks" / rs.RUN_FILE).write_text("{not json", encoding="utf-8")
    (store / "runs" / "scratch").mkdir()
    (store / "runs" / "scratch" / rs.RUN_FILE).write_text(
        json.dumps({"run_id": "scratch", "status": "reviewing"}), encoding="utf-8"
    )

    assert [r["run_id"] for r in rs.list_runs(store)] == ["2026-10-14-nv", "2026-10-07-ut"]


def test_an_empty_store_has_no_runs(tmp_path):
    assert rs.list_runs(tmp_path / "nothing") == []


# --- stage progress ----------------------------------------------------------------------------


def test_a_stage_killed_mid_review_resumes_at_its_unreviewed_proposals(tmp_path):
    folder = _stage(_store(tmp_path))
    _mark(folder, "preflight.json", "propose_done")
    _proposal(folder, "prop01", [_pair(1), _pair(2)], _verdicts([_pair(1), _pair(2)]))
    _proposal(folder, "prop02", [_pair(3)])

    progress = rs.stage_progress(tmp_path / "store", RUN, "merges")

    assert (progress.next_step.name, progress.queued, progress.set_aside) == ("review", ("prop02",), ())


def test_a_reviewed_stage_moves_on_to_its_page(tmp_path):
    folder = _stage(_store(tmp_path))
    _mark(folder, "preflight.json", "propose_done")
    _proposal(folder, "prop01", [_pair(1)], _verdicts([_pair(1)]))

    assert rs.stage_progress(tmp_path / "store", RUN, "merges").next_step.name == "page"


def test_a_stage_with_nothing_to_review_moves_on_to_its_page(tmp_path):
    folder = _stage(_store(tmp_path))
    _mark(folder, "preflight.json", "propose_done")

    assert rs.stage_progress(tmp_path / "store", RUN, "merges").next_step.name == "page"


@pytest.mark.parametrize(
    "review",
    [
        _verdicts([_pair(1), _pair(2)], merge_id="m9"),
        _verdicts([_pair(1), _pair(2)], keep_id="k9"),
        _verdicts([_pair(1), _pair(2)], merge_name="Someone Else"),
        _verdicts([_pair(1), _pair(2)], keep_name="Someone Else"),
        _verdicts([_pair(1)]),
        _verdicts([_pair(2), _pair(1)]),
        _verdicts([_pair(1), _pair(2), _pair(3)]),
        [{"extra": True, "verdict": "merge"}, *_verdicts([_pair(1), _pair(2)])],
        [_verdicts([_pair(1)])[0], {"extra": True, "verdict": "merge"}, _verdicts([_pair(2)])[0]],
        {"verdicts": _verdicts([_pair(1), _pair(2)])},
        "[{not json",
        ["merge", "merge"],
    ],
    ids=[
        "other-merge-id",
        "other-keep-id",
        "other-merge-name",
        "other-keep-name",
        "row-dropped",
        "rows-reordered",
        "row-invented",
        "extra-row-first",
        "extra-row-between",
        "not-a-list",
        "unparseable",
        "rows-not-objects",
    ],
)
def test_a_review_that_does_not_copy_its_proposal_is_set_aside_and_queued_again(tmp_path, review):
    folder = _stage(_store(tmp_path))
    _mark(folder, "preflight.json", "propose_done")
    review_dir = _proposal(folder, "prop01", [_pair(1), _pair(2)], review)

    progress = rs.stage_progress(tmp_path / "store", RUN, "merges")

    assert (progress.next_step.name, progress.queued) == ("review", ("prop01",))
    assert progress.set_aside == ("prop01_review.json",)
    assert sorted(p.name for p in review_dir.iterdir()) == ["prop01.json", "prop01_review.json.bad"]


@pytest.mark.parametrize("wrong", [0, 1, 2])
def test_one_wrong_row_sets_the_whole_review_aside(tmp_path, wrong):
    pairs = [_pair(1), _pair(2), _pair(3)]
    review = _verdicts(pairs)
    review[wrong]["keep_id"] = "k9"
    folder = _stage(_store(tmp_path))
    _mark(folder, "preflight.json", "propose_done")
    _proposal(folder, "prop01", pairs, review)

    assert rs.stage_progress(tmp_path / "store", RUN, "merges").set_aside == ("prop01_review.json",)


def test_a_review_still_open_for_writing_is_left_in_place(monkeypatch, tmp_path):
    def windows_refuses(src, dst):
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    folder = _stage(_store(tmp_path))
    _mark(folder, "preflight.json", "propose_done")
    review_dir = _proposal(folder, "prop01", [_pair(1)], '[{"merge_id": "m1", "keep')
    monkeypatch.setattr(rs.os, "replace", windows_refuses)

    progress = rs.stage_progress(tmp_path / "store", RUN, "merges")

    assert (progress.next_step.name, progress.queued, progress.set_aside) == ("review", ("prop01",), ())
    assert sorted(p.name for p in review_dir.iterdir()) == ["prop01.json", "prop01_review.json"]


def test_a_second_bad_review_replaces_the_first_one_set_aside(tmp_path):
    folder = _stage(_store(tmp_path))
    _mark(folder, "preflight.json", "propose_done")
    review_dir = _proposal(folder, "prop01", [_pair(1)], _verdicts([_pair(1)], merge_id="m8"))
    rs.stage_progress(tmp_path / "store", RUN, "merges")
    _proposal(folder, "prop01", [_pair(1)], _verdicts([_pair(1)], merge_id="m9"))

    assert rs.stage_progress(tmp_path / "store", RUN, "merges").set_aside == ("prop01_review.json",)
    assert json.loads((review_dir / "prop01_review.json.bad").read_text(encoding="utf-8"))[0]["merge_id"] == "m9"


def test_a_reviewer_s_own_extra_rows_after_its_verdicts_are_not_compared(tmp_path):
    folder = _stage(_store(tmp_path))
    _mark(folder, "preflight.json", "propose_done")
    _proposal(folder, "prop01", [_pair(1)], [*_verdicts([_pair(1)]), {"extra": True, "note": "also see k7"}])

    assert rs.stage_progress(tmp_path / "store", RUN, "merges").next_step.name == "page"


def test_a_proposal_missing_a_copied_field_cannot_be_reviewed(tmp_path):
    pair = {k: v for k, v in _pair(1).items() if k != "keep_name"}
    folder = _stage(_store(tmp_path))
    _mark(folder, "preflight.json", "propose_done")
    _proposal(folder, "prop01", [pair], [{**pair, "verdict": "merge"}])

    assert rs.stage_progress(tmp_path / "store", RUN, "merges").queued == ("prop01",)


@pytest.mark.parametrize("field", ["team_id_master", "field", "old_value", "new_value"])
def test_a_single_team_review_must_copy_the_team_and_the_change(tmp_path, field):
    change = {"team_id_master": "t1", "field": "age_group", "old_value": "u12", "new_value": "u13"}
    folder = _stage(_store(tmp_path), "ages")
    _mark(folder, "preflight.json", "propose_done")
    _proposal(folder, "prop01", [change], [{**change, field: "other", "verdict": "apply"}])

    assert rs.stage_progress(tmp_path / "store", RUN, "ages").set_aside == ("prop01_review.json",)


def test_a_single_team_review_that_copies_the_change_passes(tmp_path):
    change = {"team_id_master": "t1", "field": "age_group", "old_value": "u12", "new_value": "u13"}
    folder = _stage(_store(tmp_path), "ages")
    _mark(folder, "preflight.json", "propose_done")
    _proposal(folder, "prop01", [change], [{**change, "verdict": "apply"}])

    assert rs.stage_progress(tmp_path / "store", RUN, "ages").next_step.name == "page"


@pytest.mark.parametrize(
    "markers, expected",
    [
        ((), "preflight"),
        (("preflight.json",), "propose"),
        (("preflight.json", "propose_done", "page.json"), "collect"),
        (("preflight.json", "propose_done", "page.json", "collected.json"), "apply"),
        (("preflight.json", "page.json", "collected.json", "RECORD.md"), "propose"),
    ],
)
def test_a_stage_resumes_at_its_first_missing_marker(tmp_path, markers, expected):
    folder = _stage(_store(tmp_path))
    _mark(folder, *markers)

    assert rs.stage_progress(tmp_path / "store", RUN, "merges").next_step.name == expected


def test_a_stage_with_every_marker_is_finished(tmp_path):
    folder = _stage(_store(tmp_path))
    _mark(folder, "preflight.json", "propose_done", "page.json", "collected.json", "RECORD.md")

    assert rs.stage_progress(tmp_path / "store", RUN, "merges").finished


# --- the apply lock --------------------------------------------------------------------------

COLUMNS = {"run_id", "scope", "status", "budgets", "lease_holder", "lease_expires_at", "created_at", "updated_at"}


def _stamp(**delta):
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat(timespec="seconds")


def _row(**over):
    return {"run_id": RUN, "status": "reviewing", "lease_holder": None, "lease_expires_at": None, **over}


def _api_error(code, message="refused"):
    return APIError({"code": code, "message": message, "details": None, "hint": None})


class _Result:
    def __init__(self, data):
        self.data = data


def _holds(row, kind, column, value):
    if kind == "eq":
        return row.get(column) == value
    if kind == "in":
        return row.get(column) in value
    return any(_holds_term(row, *term.split(".", 2)) for term in column.split(","))


def _holds_term(row, column, op, value):
    if op == "is" and value == "null":
        return row.get(column) is None
    if op == "lt":
        return row.get(column) is not None and datetime.fromisoformat(row[column]) < datetime.fromisoformat(value)
    raise AssertionError(f"the double does not model {column}.{op}.{value}")


class _Query:
    """Applies eq, in_ and or_ at execute(), where a write is recorded. An update that matches no
    row answers an empty list, as PostgREST does; a column the table lacks, or an or_ operator the
    double does not model, is refused when the query is built."""

    def __init__(self, db, columns=None, payload=None):
        unknown = (set(columns or ()) | set(payload or {})) - COLUMNS
        assert not unknown, f"PostgREST refuses unknown columns: {unknown}"
        self._db, self._columns, self._payload, self._filters = db, columns, payload, []

    def eq(self, column, value):
        assert column in COLUMNS, f"PostgREST refuses an unknown column: {column}"
        self._filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        assert column in COLUMNS, f"PostgREST refuses an unknown column: {column}"
        self._filters.append(("in", column, list(values)))
        return self

    def or_(self, expression):
        for term in expression.split(","):
            column, op, _ = term.split(".", 2)
            assert column in COLUMNS, f"PostgREST refuses an unknown column: {column}"
            assert op in ("is", "lt"), f"the double does not model {term}"
        self._filters.append(("or", expression, None))
        return self

    def execute(self):
        db = self._db
        if db.fail:
            raise db.fail
        rows = [r for r in db.runs.values() if all(_holds(r, *f) for f in self._filters)]
        if self._payload is None:
            return _Result([{c: r[c] for c in self._columns} for r in rows])
        if self._payload.get("lease_holder") is None and db.fail_release:
            raise db.fail_release
        db.updates.append((list(self._filters), dict(self._payload)))
        for r in rows:
            r.update(self._payload)
        hook, db.after_update = db.after_update, None
        if hook:
            hook(db)
        lost, db.lose_answer = db.lose_answer, None
        if lost:
            raise lost
        return _Result([dict(r) for r in rows])


class _Db:
    """`fail` is an error every query raises from then on, before applying anything; `lose_answer`
    is raised once, after the first update has applied (a dropped connection, a Ctrl-C, a gateway's
    error page); `fail_release` is an error on any update that clears a lease; `after_update` runs
    once after the first update and before its re-read (another applier letting go, the database
    going down)."""

    def __init__(self, *rows, fail=None, lose_answer=None, fail_release=None, after_update=None):
        self.runs = {r["run_id"]: dict(r) for r in rows}
        self.updates = []
        self.fail, self.lose_answer = fail, lose_answer
        self.fail_release, self.after_update = fail_release, after_update

    def table(self, name):
        assert name == rs.RUNS_TABLE
        db = self

        class _T:
            def select(self, columns):
                return _Query(db, columns=[c.strip() for c in columns.split(",")])

            def update(self, payload):
                return _Query(db, payload=payload)

        return _T()


def test_a_free_open_run_is_leased_for_six_hours_while_the_apply_runs_and_released_after(tmp_path):
    store, db = _store(tmp_path), _Db(_row())

    with rs.acquire_apply_lock(db, store, RUN, holder="applier-a") as holder:
        row = dict(db.runs[RUN])

    assert holder == "applier-a"
    assert row["lease_holder"] == "applier-a"
    expected = datetime.now(timezone.utc) + timedelta(hours=6)
    assert abs(datetime.fromisoformat(row["lease_expires_at"]) - expected) < timedelta(seconds=5)
    assert (db.runs[RUN]["lease_holder"], db.runs[RUN]["lease_expires_at"]) == (None, None)


@pytest.mark.parametrize("status", ["proposing", "reviewing", "applying", "second_lap"])
def test_every_open_status_can_be_leased(tmp_path, status):
    store, db = _store(tmp_path), _Db(_row(status=status))
    with rs.acquire_apply_lock(db, store, RUN, holder="applier-a"):
        assert db.runs[RUN]["lease_holder"] == "applier-a"


def test_a_second_apply_on_this_machine_is_refused_by_the_file_lock(tmp_path):
    store, first, second = _store(tmp_path), _Db(_row()), _Db(_row())

    with rs.acquire_apply_lock(first, store, RUN, holder="applier-a"):
        with pytest.raises(rs.ApplyLockError, match="another apply on this machine holds run"):
            with rs.acquire_apply_lock(second, store, RUN, holder="applier-b"):
                pass

    assert second.updates == []


def test_a_second_apply_elsewhere_is_refused_by_the_lease(tmp_path):
    db = _Db(_row())
    here, elsewhere = _store(tmp_path, name="here"), _store(tmp_path, name="elsewhere")

    with rs.acquire_apply_lock(db, here, RUN, holder="applier-a"):
        with pytest.raises(rs.ApplyLockError, match="is held by applier-a until"):
            with rs.acquire_apply_lock(db, elsewhere, RUN, holder="applier-b"):
                pass
        assert db.runs[RUN]["lease_holder"] == "applier-a"


def test_an_expired_lease_is_taken_over(tmp_path):
    store, db = _store(tmp_path), _Db(_row(lease_holder="crashed", lease_expires_at=_stamp(minutes=-1)))

    with rs.acquire_apply_lock(db, store, RUN, holder="applier-b"):
        assert db.runs[RUN]["lease_holder"] == "applier-b"


def test_a_lease_expiring_this_second_is_reported_as_held(monkeypatch, tmp_path):
    class _HalfASecondPastSix(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 14, 18, 0, 0, 500000, tzinfo=timezone.utc)

    monkeypatch.setattr(rs, "datetime", _HalfASecondPastSix)
    store, db = _store(tmp_path), _Db(_row(lease_holder="applier-x", lease_expires_at="2026-10-14T18:00:00+00:00"))

    with pytest.raises(rs.ApplyLockError, match="is held by applier-x until 2026-10-14T18:00:00"):
        with rs.acquire_apply_lock(db, store, RUN, holder="applier-b"):
            pass


@pytest.mark.parametrize("status", ["done", "abandoned"])
def test_a_closed_run_is_not_leased(tmp_path, status):
    store, db = _store(tmp_path), _Db(_row(status=status))

    with pytest.raises(rs.ApplyLockError, match=f"is {status}, so nothing may apply to it"):
        with rs.acquire_apply_lock(db, store, RUN, holder="applier-a"):
            pass

    assert db.runs[RUN]["lease_holder"] is None


def test_a_run_missing_from_the_table_is_reported(tmp_path):
    with pytest.raises(rs.ApplyLockError, match=f"no run {RUN} in {rs.RUNS_TABLE}"):
        with rs.acquire_apply_lock(_Db(), _store(tmp_path), RUN, holder="applier-a"):
            pass


def test_a_run_missing_from_the_store_is_refused_before_the_database(tmp_path):
    db = _Db(_row())
    with pytest.raises(rs.ApplyLockError, match="no run .* in "):
        with rs.acquire_apply_lock(db, tmp_path / "empty", RUN, holder="applier-a"):
            pass
    assert db.updates == []


@pytest.mark.parametrize(
    "code, message",
    [
        ("PGRST205", f"{rs.RUNS_TABLE} does not exist yet: apply its migration"),
        ("42501", f"only the service-role key can write {rs.RUNS_TABLE}"),
        ("57014", "could not lease run 2026-10-14-nv: refused"),
    ],
    ids=["table-missing", "permission-denied", "other"],
)
def test_a_lease_the_database_refuses_says_why_and_frees_the_file_lock(tmp_path, code, message):
    store = _store(tmp_path)

    with pytest.raises(rs.ApplyLockError, match=message):
        with rs.acquire_apply_lock(_Db(_row(), fail=_api_error(code)), store, RUN, holder="applier-a"):
            pass

    with rs.acquire_apply_lock(_Db(_row()), store, RUN, holder="applier-a"):
        pass


def test_an_error_page_from_in_front_of_postgrest_passes_through(tmp_path):
    """postgrest-py codes a body PostgREST did not write with the HTTP status, an int: a wrong key
    answered by the gateway, say. It is no refusal of the lease, so it is not reported as one."""
    store = _store(tmp_path)

    with pytest.raises(APIError) as raised:
        with rs.acquire_apply_lock(
            _Db(_row(), fail=_api_error(401, "Invalid API key")), store, RUN, holder="applier-a"
        ):
            pass

    assert raised.value.code == 401


def test_a_re_read_the_database_refuses_says_why(tmp_path):
    def database_goes_down(db):
        db.fail = _api_error("57014")

    store = _store(tmp_path)
    db = _Db(_row(lease_holder="applier-x", lease_expires_at=_stamp(hours=1)), after_update=database_goes_down)

    with pytest.raises(rs.ApplyLockError, match="could not lease run 2026-10-14-nv: refused"):
        with rs.acquire_apply_lock(db, store, RUN, holder="applier-b"):
            pass


def test_a_lease_freed_between_the_update_and_its_re_read_asks_for_a_retry(tmp_path):
    def holder_lets_go(db):
        db.runs[RUN].update(lease_holder=None, lease_expires_at=None)

    store = _store(tmp_path)
    db = _Db(_row(lease_holder="applier-x", lease_expires_at=_stamp(hours=1)), after_update=holder_lets_go)

    with pytest.raises(rs.ApplyLockError, match="was held when the lease was asked for and is free now; try again"):
        with rs.acquire_apply_lock(db, store, RUN, holder="applier-b"):
            pass


@pytest.mark.parametrize(
    "lost",
    [ConnectionError("connection reset"), KeyboardInterrupt(), _api_error(504, "JSON could not be generated")],
    ids=["dropped", "ctrl-c", "gateway-timeout"],
)
def test_a_lease_whose_answer_was_lost_is_cleared(tmp_path, lost):
    store, db = _store(tmp_path), _Db(_row(), lose_answer=lost)

    with pytest.raises(type(lost)):
        with rs.acquire_apply_lock(db, store, RUN, holder="applier-a"):
            pass

    assert db.runs[RUN]["lease_holder"] is None


@pytest.mark.parametrize("failure", [RuntimeError("verify failed"), KeyboardInterrupt()], ids=["error", "ctrl-c"])
def test_the_lease_is_released_when_the_apply_stops(tmp_path, failure):
    store, db = _store(tmp_path), _Db(_row())

    with pytest.raises(type(failure)):
        with rs.acquire_apply_lock(db, store, RUN, holder="applier-a"):
            raise failure

    assert db.runs[RUN]["lease_holder"] is None


@pytest.mark.parametrize(
    "failure", [_api_error("57014"), ConnectionError("connection reset")], ids=["refused", "dropped"]
)
def test_a_release_that_fails_does_not_hide_how_the_apply_ended(tmp_path, caplog, failure):
    store = _store(tmp_path)

    with pytest.raises(RuntimeError, match="verify failed"):
        with rs.acquire_apply_lock(_Db(_row(), fail_release=failure), store, RUN, holder="applier-a"):
            raise RuntimeError("verify failed")
    with rs.acquire_apply_lock(_Db(_row(), fail_release=failure), store, RUN, holder="applier-a"):
        pass

    assert caplog.text.count(f"Could not release run {RUN}'s lease") == 2


def test_the_file_lock_is_free_again_after_an_apply(tmp_path):
    store, db = _store(tmp_path), _Db(_row())
    with rs.acquire_apply_lock(db, store, RUN, holder="applier-a"):
        pass
    with rs.acquire_apply_lock(db, store, RUN, holder="applier-b"):
        assert db.runs[RUN]["lease_holder"] == "applier-b"


def test_releasing_leaves_a_lease_another_applier_has_since_taken_and_says_so(tmp_path, caplog):
    store, db = _store(tmp_path), _Db(_row())

    with rs.acquire_apply_lock(db, store, RUN, holder="applier-a"):
        db.runs[RUN].update(lease_holder="applier-b", lease_expires_at=_stamp(hours=6))

    assert db.runs[RUN]["lease_holder"] == "applier-b"
    assert f"Run {RUN}'s lease was no longer applier-a's to release" in caplog.text


# Two runs in the table, so a filter that dropped its run id would reach the other one.
OTHER = "2026-10-07-ut"


def test_leasing_a_closed_run_never_leases_the_open_one_beside_it(tmp_path):
    store = _store(tmp_path, status="done")
    db = _Db(_row(status="done"), _row(run_id=OTHER))

    with pytest.raises(rs.ApplyLockError, match=f"run {RUN} is done"):
        with rs.acquire_apply_lock(db, store, RUN, holder="applier-a"):
            pass

    assert db.runs[OTHER]["lease_holder"] is None


def test_a_refusal_reports_the_run_asked_for(tmp_path):
    store = _store(tmp_path)
    db = _Db(_row(run_id=OTHER, status="done"), _row(lease_holder="applier-x", lease_expires_at=_stamp(hours=1)))

    with pytest.raises(rs.ApplyLockError, match=f"run {RUN} is held by applier-x"):
        with rs.acquire_apply_lock(db, store, RUN, holder="applier-b"):
            pass


def test_releasing_leaves_another_run_s_lease_with_the_same_holder(tmp_path):
    stale = _stamp(hours=-1)
    store = _store(tmp_path)
    db = _Db(_row(run_id=OTHER, status="done", lease_holder="applier-a", lease_expires_at=stale), _row())

    with rs.acquire_apply_lock(db, store, RUN, holder="applier-a"):
        pass

    assert (db.runs[OTHER]["lease_holder"], db.runs[OTHER]["lease_expires_at"]) == ("applier-a", stale)
