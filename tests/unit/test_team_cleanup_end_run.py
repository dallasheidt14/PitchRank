"""Tests for ending a weekly team-cleanup run: --done, --abandon, and their dry run.

The runs table double is the run store's `_Db`: its `fail` error is raised before anything applies,
`lose_answer` only after the update applied, and `after_update` lets another process act between
the update and its re-read."""

import os
import shlex
import sys

import httpx
import pytest
from postgrest.exceptions import APIError

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.team_cleanup import end_run as er  # noqa: E402
from scripts.team_cleanup.run_store import APPLY_LOCK_FILE, read_run, run_dir, stage_dir, write_run  # noqa: E402
from src.tournaments.storage._file_lock import _acquire_file_lock  # noqa: E402
from tests.unit.test_team_cleanup_run_store import RUN, _api_error, _Db, _row, _stamp  # noqa: E402

OTHER = "2026-10-07-nv"
NOT_RUN = {"reconcile": "not run: reconcile is run by hand", "merges": "not run: the duplicate scans are frozen"}
APPLIED = ("preflight.json", "propose_done", "page.json", "collected.json", "RECORD.md")


def _store(tmp_path, status="reviewing", applied=("clubs", "states", "ages"), notes=None):
    """Of clubs, states and ages, the listed ones are applied and the rest have passed only their
    self-check; reconcile and merges are noted as not run."""
    store = tmp_path / "store"
    stages = {**NOT_RUN, **(notes or {})}
    write_run(store, {"run_id": RUN, "scope": {"states": ["NV"]}, "status": status, "budgets": {}, "stages": stages})
    for stage in ("clubs", "states", "ages"):
        folder = stage_dir(store, RUN, stage)
        folder.mkdir(parents=True, exist_ok=True)
        for marker in APPLIED if stage in applied else APPLIED[:1]:
            (folder / marker).write_text("{}", encoding="utf-8")
    return store


def _main(monkeypatch, capsys, store, db, *argv, store_arg=True):
    def client():
        if db is None:
            raise AssertionError("a dry run must not open the database")
        return db

    monkeypatch.setattr(er, "get_client", client)
    where = ["--store", str(store)] if store_arg else []
    monkeypatch.setattr(sys, "argv", ["end_run.py", "--run", RUN, *where, *argv])
    code = er.main()
    return code, capsys.readouterr().out


def _retry(store, how="--abandon"):
    return shlex.join(
        ["python", "scripts/team_cleanup/end_run.py", "--run", RUN, how, "--execute", "--store", str(store)]
    )


# --- the dry run ---------------------------------------------------------------------------------


@pytest.mark.parametrize("flags", [(), ("--execute", "--dry-run")], ids=["no-execute", "dry-run-wins"])
def test_a_dry_run_says_what_it_would_do_and_opens_nothing(tmp_path, monkeypatch, capsys, flags):
    store = _store(tmp_path, applied=("clubs",))

    code, out = _main(monkeypatch, capsys, store, None, "--abandon", *flags)

    assert code == 0
    unapplied = "  not applied: {}: next, write the stage's proposals\n"
    assert out == (
        "DRY RUN -- would move run 2026-10-14-nv from reviewing to abandoned.\n"
        + unapplied.format("states")
        + unapplied.format("ages")
        + "Re-run with --execute to move it.\n"
    )
    assert read_run(store, RUN)["status"] == "reviewing"


@pytest.mark.parametrize("flags", [(), ("--execute", "--dry-run")], ids=["no-execute", "dry-run-wins"])
def test_a_dry_run_refuses_what_execute_would(tmp_path, monkeypatch, capsys, flags):
    store = _store(tmp_path, applied=("clubs", "ages"))

    with pytest.raises(SystemExit, match="so it is not done; finish them or use --abandon:\n  states: next, write"):
        _main(monkeypatch, capsys, store, None, "--done", *flags)

    closed = _store(tmp_path, status="done")
    with pytest.raises(SystemExit, match="^Run 2026-10-14-nv is done; only an open run can be ended.$"):
        _main(monkeypatch, capsys, closed, None, "--abandon", *flags)


# --- ending a run -----------------------------------------------------------------------------------


def test_abandoning_moves_the_row_and_run_json_and_records_why(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path, applied=())
    db = _Db(_row(), _row(run_id=OTHER, status="done"))

    code, out = _main(monkeypatch, capsys, store, db, "--abandon", "--reason", "states failed twice", "--execute")

    assert code == 0 and out == "Moved run 2026-10-14-nv from reviewing to abandoned.\n"
    assert db.runs[RUN] == _row(status="abandoned")
    assert db.runs[OTHER] == _row(run_id=OTHER, status="done")
    run = read_run(store, RUN)
    assert run["status"] == "abandoned"
    assert (run["ended"]["status"], run["ended"]["reason"]) == ("abandoned", "states failed twice")


def test_done_is_refused_while_a_stage_is_unapplied(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path, applied=("clubs", "ages"))
    db = _Db(_row())

    with pytest.raises(SystemExit, match="finish them or use --abandon:\n  states: next, write the stage's proposals$"):
        _main(monkeypatch, capsys, store, db, "--done", "--execute")
    assert db.updates == [] and read_run(store, RUN)["status"] == "reviewing"


def test_a_stage_that_failed_to_propose_is_not_finished(tmp_path, monkeypatch, capsys):
    """A failed stage is kept open to be retried."""
    store = _store(tmp_path, applied=("clubs", "ages"), notes={"states": "failed: assign_team_states.py exited 1"})
    db = _Db(_row(status="proposing"))

    with pytest.raises(SystemExit, match="\n  states: failed: assign_team_states.py exited 1$"):
        _main(monkeypatch, capsys, store, db, "--done", "--execute")
    assert db.updates == []


@pytest.mark.parametrize("note", ["skill_stale: check exited 1", "skill_stale"], ids=["with-reason", "bare"])
def test_done_closes_a_run_whose_stages_are_applied_or_have_nothing_to_apply(tmp_path, monkeypatch, capsys, note):
    store = _store(tmp_path, applied=("clubs", "ages"), notes={"states": note})
    db = _Db(_row(status="applying"))

    code, _ = _main(monkeypatch, capsys, store, db, "--done", "--execute")

    assert code == 0 and db.runs[RUN]["status"] == "done"
    assert read_run(store, RUN)["status"] == "done"


# --- what keeps a run from ending ------------------------------------------------------------------


def test_a_run_whose_lease_is_live_is_not_ended(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path, applied=())
    until = _stamp(hours=1)
    db = _Db(_row(status="applying", lease_holder="laptop:4242", lease_expires_at=until))

    with pytest.raises(SystemExit) as caught:
        _main(monkeypatch, capsys, store, db, "--abandon", "--execute")
    assert str(caught.value) == f"Run 2026-10-14-nv is being applied by laptop:4242 until {until}."
    assert db.runs[RUN]["status"] == "applying" and read_run(store, RUN)["status"] == "reviewing"


def test_a_lease_that_has_expired_does_not_keep_a_run_open(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path, applied=())
    db = _Db(_row(status="applying", lease_holder="laptop:4242", lease_expires_at=_stamp(hours=-1)))

    _main(monkeypatch, capsys, store, db, "--abandon", "--execute")

    assert db.runs[RUN] == _row(status="abandoned")


def test_a_lease_let_go_while_asking_says_to_try_again(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path, applied=())

    def applier_finishes(db):
        db.runs[RUN].update(lease_holder=None, lease_expires_at=None)

    db = _Db(
        _row(status="applying", lease_holder="laptop:4242", lease_expires_at=_stamp(hours=1)),
        after_update=applier_finishes,
    )

    with pytest.raises(SystemExit, match="^Run 2026-10-14-nv was being applied when asked and is free now; run"):
        _main(monkeypatch, capsys, store, db, "--abandon", "--execute")
    assert db.runs[RUN]["status"] == "applying"


def test_a_run_being_applied_on_this_machine_is_not_ended(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path, applied=())
    db = _Db(_row(status="applying"))

    with _acquire_file_lock(run_dir(store, RUN) / APPLY_LOCK_FILE, timeout=0.0):
        with pytest.raises(SystemExit, match="^Run 2026-10-14-nv is being applied on this machine.$"):
            _main(monkeypatch, capsys, store, db, "--abandon", "--execute")
    assert db.updates == [] and db.runs[RUN]["status"] == "applying"


@pytest.mark.parametrize(
    "json_status, row_status, message",
    [
        ("done", "done", "Run 2026-10-14-nv is done; only an open run can be ended."),
        ("abandoned", "abandoned", "Run 2026-10-14-nv is abandoned; only an open run can be ended."),
        ("reviewing", "done", "Run 2026-10-14-nv is done in team_cleanup_runs; only an open run can be ended."),
    ],
    ids=["closed-in-run-json", "already-ended", "closed-in-the-table"],
)
def test_a_closed_run_is_not_ended_again(tmp_path, monkeypatch, capsys, json_status, row_status, message):
    store = _store(tmp_path, status=json_status, applied=())
    # The other run comes first, so a read that drops its run_id filter answers with the wrong row.
    db = _Db(_row(run_id=OTHER, status="reviewing"), _row(status=row_status))

    with pytest.raises(SystemExit) as caught:
        _main(monkeypatch, capsys, store, db, "--abandon", "--execute")
    assert str(caught.value) == message
    assert db.runs[RUN]["status"] == row_status
    assert db.runs[OTHER] == _row(run_id=OTHER, status="reviewing")


def test_a_run_missing_from_the_table_is_reported(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path, applied=())

    with pytest.raises(SystemExit, match="^No run 2026-10-14-nv in team_cleanup_runs.$"):
        _main(monkeypatch, capsys, store, _Db(), "--abandon", "--execute")


# --- when the database's answer goes missing ------------------------------------------------------


@pytest.mark.parametrize(
    "error, detail",
    [
        (httpx.ReadTimeout("timed out"), "ReadTimeout: timed out"),
        (APIError({"code": 502, "message": "JSON could not be generated"}), "JSON could not be generated"),
    ],
    ids=["timeout", "gateway-page"],
)
def test_a_lost_answer_says_how_to_retry_and_the_retry_catches_up(tmp_path, monkeypatch, capsys, error, detail):
    store = _store(tmp_path, applied=())
    db = _Db(_row(), _row(run_id=OTHER, status="done"), lose_answer=error)

    with pytest.raises(SystemExit) as caught:
        _main(monkeypatch, capsys, store, db, "--abandon", "--execute")
    assert str(caught.value) == (
        f"Could not end run 2026-10-14-nv: the database's answer was lost ({detail}); "
        f"re-run to see where it stands: {_retry(store)}"
    )
    assert db.runs[RUN]["status"] == "abandoned" and read_run(store, RUN)["status"] == "reviewing"

    code, out = _main(monkeypatch, capsys, store, db, "--abandon", "--execute")

    assert (
        code == 0 and out == "Run 2026-10-14-nv was already abandoned in team_cleanup_runs; run.json now says so too.\n"
    )
    assert read_run(store, RUN)["status"] == "abandoned"
    assert db.runs[OTHER] == _row(run_id=OTHER, status="done")


def test_a_lost_re_read_is_a_lost_answer_too(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path, applied=())

    def connection_drops(db):
        db.fail = httpx.ConnectError("connection reset")

    db = _Db(_row(status="applying", lease_holder="laptop:4242", lease_expires_at=_stamp(hours=1)))
    db.after_update = connection_drops

    with pytest.raises(SystemExit, match="the database's answer was lost \\(ConnectError: connection reset\\)"):
        _main(monkeypatch, capsys, store, db, "--abandon", "--execute")


def test_the_retry_names_the_store_even_when_it_came_from_the_environment(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path, applied=())
    monkeypatch.setenv("PITCHRANK_CLEANUP_DIR", str(store))
    db = _Db(_row(), lose_answer=httpx.ReadTimeout("timed out"))

    with pytest.raises(SystemExit) as caught:
        _main(monkeypatch, capsys, store, db, "--abandon", "--execute", store_arg=False)
    assert str(caught.value).endswith(_retry(store))


@pytest.mark.parametrize(
    "code, message",
    [
        ("42501", "Could not end run 2026-10-14-nv: only the service-role key can write team_cleanup_runs"),
        ("PGRST205", "team_cleanup_runs does not exist yet: apply its migration before ending run 2026-10-14-nv"),
        ("23514", "Could not end run 2026-10-14-nv: refused"),
    ],
    ids=["permission-denied", "table-missing", "other-refusal"],
)
def test_a_refusal_from_the_database_changes_nothing_and_says_why(tmp_path, monkeypatch, capsys, code, message):
    store = _store(tmp_path, applied=())
    db = _Db(_row(), fail=_api_error(code))

    with pytest.raises(SystemExit) as caught:
        _main(monkeypatch, capsys, store, db, "--abandon", "--execute")
    assert str(caught.value) == message
    assert db.runs[RUN] == _row() and read_run(store, RUN)["status"] == "reviewing"


# --- arguments ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv, message",
    [
        (["--run", RUN, "--abandon", "--store", "relative-store"], "must be an absolute path"),
        (["--run", "2026-10-14-NV", "--abandon"], "is not a run id"),
        (["--run", "2026-10-15-nv", "--abandon"], "No run 2026-10-15-nv in "),
    ],
    ids=["relative-store", "bad-run-id", "no-run-json"],
)
def test_a_bad_store_or_run_ends_with_a_message(tmp_path, monkeypatch, argv, message):
    monkeypatch.setenv("PITCHRANK_CLEANUP_DIR", str(tmp_path / "store"))
    monkeypatch.setattr(sys, "argv", ["end_run.py", *argv])

    with pytest.raises(SystemExit) as caught:
        er.main()
    assert message in str(caught.value)
