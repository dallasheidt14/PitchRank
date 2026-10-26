"""Tests for scripts/team_cleanup/advance.py: one autopilot tick of the weekly team cleanup."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from postgrest.exceptions import APIError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.team_cleanup import advance  # noqa: E402
from scripts.team_cleanup.apply_stage import in_window, load_window  # noqa: E402
from scripts.team_cleanup.end_run import unfinished  # noqa: E402
from scripts.team_cleanup.run_store import (  # noqa: E402
    PREFLIGHT_MARKER,
    PROPOSALS_FILE,
    PROPOSE_MARKER,
    RUN_FILE,
    read_run,
    run_dir,
    stage_dir,
    write_run,
)
from src.tournaments.storage._file_lock import _acquire_file_lock  # noqa: E402

RUN = "2026-10-21-all"
STAGES = ("clubs", "states", "ages", "merges")
NOTES = {"reconcile": "not run: reconcile is run by hand"}
UTC = timezone.utc
# Arizona keeps UTC-7 all year: Wednesday 11:00 there is 18:00 UTC.
PROPOSE_TIME = datetime(2026, 10, 21, 18, 0, tzinfo=UTC)
BEFORE_WINDOW = datetime(2026, 10, 22, 18, 0, tzinfo=UTC)  # Thursday 11:00 Arizona
IN_WINDOW = datetime(2026, 10, 24, 18, 0, tzinfo=UTC)  # Saturday 11:00, inside Friday 17:00 to Sunday 22:00
PAST_DEADLINE = datetime(2026, 10, 26, 2, 0, tzinfo=UTC)  # Sunday 19:00, an hour past the Sunday 18:00 deadline
# An apply window running to Sunday 22:00, so the Sunday 18:00 deadline falls inside it.
CONFIG = {
    "apply_window": {"start": {"weekday": "Friday", "time": "17:00"}, "end": {"weekday": "Sunday", "time": "22:00"}},
    "review_deadline": {"weekday": "Sunday", "time": "18:00"},
}
COLUMNS = {
    "team_cleanup_runs": {"run_id", "status", "owner_done_at", "owner_done_by"},
    "team_cleanup_requests": {
        "id",
        "run_id",
        "stage",
        "lane",
        "action",
        "requested_at",
        "status",
        "handled_at",
        "result",
    },
}


def _config(folder, **changes):
    path = folder / "team_cleanup.json"
    path.write_text(json.dumps({**CONFIG, **changes}), encoding="utf-8")
    return path


class _Result:
    def __init__(self, data):
        self.data = data


class _Runs:
    """team_cleanup_runs and team_cleanup_requests: a select or an update, filtered by eq() and is_(col,
    "null") and ordered by order(), recorded at execute(). Like PostgREST it refuses a column the table lacks;
    ``broken`` is the error every execute() raises."""

    def __init__(self, rows=(), requests=()):
        self.tables = {
            "team_cleanup_runs": [dict(r) for r in rows],
            "team_cleanup_requests": [dict(r) for r in requests],
        }
        self.writes = []
        self.broken = None
        # Tables a migration has not created yet: PostgREST answers PGRST205 for them.
        self.missing = set()

    @property
    def rows(self):
        return self.tables["team_cleanup_runs"]

    @property
    def requests(self):
        return self.tables["team_cleanup_requests"]

    def table(self, name):
        assert name in COLUMNS, f"no table {name}"
        return _RunsQuery(self, name)


class _RunsQuery:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.payload, self.columns, self.ordered = db, name, [], None, None, None

    def _known(self, *columns):
        assert set(columns) <= COLUMNS[self.name], f"PostgREST refuses unknown columns {sorted(columns)}"

    def select(self, columns):
        self.columns = [c.strip() for c in columns.split(",")]
        self._known(*self.columns)
        return self

    def update(self, payload):
        self._known(*payload)
        self.payload = payload
        return self

    def eq(self, column, value):
        self._known(column)
        self.filters.append((column, value))
        return self

    def is_(self, column, value):
        self._known(column)
        assert value == "null"
        self.filters.append((column, None))
        return self

    def order(self, column):
        self._known(column)
        self.ordered = column
        return self

    def execute(self):
        if self.db.broken:
            raise self.db.broken
        if self.name in self.db.missing:
            raise APIError({"code": "PGRST205", "message": f"no table {self.name}", "details": None, "hint": None})
        rows = [r for r in self.db.tables[self.name] if all(r.get(c) == v for c, v in self.filters)]
        if self.ordered:
            rows.sort(key=lambda r: r[self.ordered])
        if self.payload is not None:
            self.db.writes.append(self.payload)
            for row in rows:
                row.update(self.payload)
            return _Result([dict(r) for r in rows])
        return _Result([{c: r.get(c) for c in self.columns} for r in rows])


def _arg(command, flag):
    return command[command.index(flag) + 1] if flag in command else None


class _Runner:
    """Stands in for each script the tick runs: records the command, refuses what the script refuses, and
    otherwise writes the markers the script would. ``codes`` maps (script, stage) to the exit codes of its
    successive runs; a run with no entry left behaves as the script would. ``auto`` is how many changes a page
    sends to the automatic lane. _tick() sets ``db``, ``now`` and ``window``."""

    def __init__(self, store, codes=None):
        self.store, self.codes, self.commands, self.auto = store, codes or {}, [], 1
        self.db, self.now, self.window = None, None, None

    def __call__(self, command, log):
        script, stage = Path(command[0]).name, _arg(command, "--stage")
        self.commands.append(command)
        log.parent.mkdir(parents=True, exist_ok=True)
        codes = self.codes.get((script, stage), [])
        refusal = self.refusal(script, command) if not codes else (codes.pop(0), "the step's own refusal")
        if refusal is not None and refusal[0]:
            log.write_text(refusal[1], encoding="utf-8")
            return refusal[0]
        log.write_text("ran", encoding="utf-8")
        self.succeed(script, stage, command)
        return 0

    def refusal(self, script, command):
        """The exit code and last line of a real script's refusal, if it would refuse."""
        run_id = _arg(command, "--run")
        if script == "propose_week.py":
            run_file = run_dir(self.store, f"{_arg(command, '--date')}-all") / RUN_FILE
            if run_file.exists() and json.loads(run_file.read_text(encoding="utf-8"))["status"] != "proposing":
                return 1, "its proposals are written"
        elif script == "collect.py" and "--from-db" in command:
            if not any(r["run_id"] == run_id and r.get("owner_done_at") for r in self.db.rows):
                return 1, "the owner has not marked the review done"
        elif script == "apply_stage.py":
            if "--revert" in command and not (_lane(self.store, command) / "RECORD.md").exists():
                return 1, "nothing of it was applied"
            if not in_window(self.window, self.now):
                return 75, "Outside the apply window"
        elif script == "end_run.py" and unfinished(self.store, read_run(self.store, run_id)):
            return 1, "a stage is unfinished"
        return None

    def succeed(self, script, stage, command):
        run_id = _arg(command, "--run")
        lane = "auto" if _arg(command, "--lane") == "auto" else "owner"
        if script == "propose_week.py":
            _proposed(self.store, f"{_arg(command, '--date')}-all", "reviewing")
        elif script == "pages.py":
            folder = stage_dir(self.store, run_id, stage)
            _write(folder / "page.json", {"run": "20261021T190000Z-a1b2c3", "auto": self.auto, "published": True})
            auto = {f"a{n}": {} for n in range(self.auto)}
            _write(folder / "page.manifest.json", {"cards": {"c1": {}, "c2": {}}, "auto": auto})
        elif script == "collect.py":
            folder = stage_dir(self.store, run_id, stage) / ("auto" if lane == "auto" else "")
            counts = {"apply": 1} if lane == "auto" else {"apply": 1, "dont_apply": 0, "unsure": 0, "undecided": 1}
            _write(folder / "collected.json", {"counts": counts})
        elif script == "apply_stage.py":
            marker = "REVERT.md" if "--revert" in command else "RECORD.md"
            (_lane(self.store, command) / marker).write_text("done", encoding="utf-8")
        elif script == "end_run.py":
            write_run(self.store, {**read_run(self.store, run_id), "status": "done"})

    def ran(self):
        return [
            (Path(c[0]).name, _arg(c, "--stage"), _arg(c, "--lane") or ("from-db" if "--from-db" in c else None))
            for c in self.commands
        ]


def _lane(store, command):
    folder = stage_dir(store, _arg(command, "--run"), _arg(command, "--stage"))
    return folder / "auto" if _arg(command, "--lane") == "auto" else folder


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _proposed(store, run_id=RUN, status="reviewing", notes=None):
    """A run whose three stages have proposed, as propose_week leaves one."""
    write_run(
        store,
        {
            "run_id": run_id,
            "scope": {"states": ["ALL"]},
            "status": status,
            "budgets": {},
            "stages": {**NOTES, **(notes or {})},
        },
    )
    for stage in STAGES:
        folder = stage_dir(store, run_id, stage)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / PREFLIGHT_MARKER).write_text("{}", encoding="utf-8")
        (folder / PROPOSE_MARKER).write_text("done", encoding="utf-8")
        (folder / PROPOSALS_FILE).write_text("[]", encoding="utf-8")


def _sender(sent):
    return lambda to, subject, body: sent.append((to, subject, body)) or True


@pytest.fixture
def emails(monkeypatch):
    sent = []
    monkeypatch.setenv("CLEANUP_OWNER_EMAIL", "owner@example.test")
    monkeypatch.setattr(advance, "send_email", _sender(sent))
    monkeypatch.setattr(advance, "code_commit", lambda: "abc1234")
    return sent


def _tick(monkeypatch, store, db, runner, now, execute=True, pin=False):
    path = _config(store.parent)
    window = load_window(path)
    runner.db, runner.now, runner.window = db, now, window
    monkeypatch.setattr(advance, "run_step", runner)
    tick = advance.Tick(db, store, now, execute, window=window, deadline=advance.load_deadline(path), pin=pin)
    return tick.tick()


def _state(store, run_id=RUN):
    return json.loads((run_dir(store, run_id) / "autopilot.json").read_text(encoding="utf-8"))


def _subjects(emails):
    return [subject for _, subject, _ in emails]


STUCK = f"PitchRank cleanup {RUN} has been stuck for a day"


# --- the review deadline ---------------------------------------------------------------------------------


def test_a_review_deadline_after_the_apply_window_ends_is_refused(tmp_path):
    path = _config(
        tmp_path,
        apply_window={"start": {"weekday": "Friday", "time": "17:00"}, "end": {"weekday": "Saturday", "time": "22:00"}},
    )

    with pytest.raises(ValueError, match="must fall before the apply window ends"):
        advance.load_deadline(path)


def test_the_shipped_review_deadline_falls_inside_the_shipped_apply_window():
    assert advance.load_deadline() == 6180  # Sunday 18:00 Arizona, in minutes after Wednesday 11:00


@pytest.mark.parametrize("run_id", ["2026-10-21-all", "2026-10-22-ca", "2026-10-25-nv"])
def test_a_run_s_deadline_is_the_first_on_or_after_its_date(tmp_path, run_id):
    deadline = advance.load_deadline(_config(tmp_path))

    assert advance.deadline_of(run_id, deadline) == datetime(2026, 10, 26, 1, 0, tzinfo=UTC)  # Sunday 18:00 Arizona


# --- starting a week ---------------------------------------------------------------------------------


def test_a_week_with_no_run_is_proposed_over_every_team_from_wednesday_11(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    runner = _Runner(store)

    code = _tick(monkeypatch, store, _Runs(), runner, PROPOSE_TIME)

    assert code == 0
    assert runner.commands[0] == [
        "scripts/team_cleanup/propose_week.py",
        "--states",
        "ALL",
        "--date",
        "2026-10-21",
        "--store",
        str(store),
    ]
    assert _state(store)["code"] == "abc1234"


def test_nothing_is_proposed_or_emailed_before_wednesday_11_after_a_run_closed_by_hand(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store, "2026-10-14-all", "done")
    runner = _Runner(store)

    _tick(monkeypatch, store, _Runs(), runner, PROPOSE_TIME - timedelta(minutes=1))

    assert runner.commands == [] and emails == []


def test_a_week_whose_run_closed_early_is_not_proposed_again(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store, status="done")
    runner = _Runner(store)

    assert _tick(monkeypatch, store, _Runs(), runner, IN_WINDOW) == 0
    assert runner.commands == []


def test_a_week_past_its_review_deadline_is_left_for_next_wednesday(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    runner = _Runner(store)

    _tick(monkeypatch, store, _Runs(), runner, PAST_DEADLINE)

    assert runner.commands == []


def test_a_run_still_proposing_is_proposed_again_with_its_own_scope_and_date(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store, status="proposing")
    runner = _Runner(store)

    _tick(monkeypatch, store, _Runs(), runner, BEFORE_WINDOW)

    assert runner.commands[0][:5] == ["scripts/team_cleanup/propose_week.py", "--states", "ALL", "--date", "2026-10-21"]


def test_the_checkout_moves_to_new_code_before_a_new_week_s_propose_and_only_then(tmp_path, monkeypatch, emails):
    """A run keeps the code it was proposed with, so a change merged mid-week cannot alter its rules."""
    store = tmp_path / "store"
    runner = _Runner(store)
    monkeypatch.setattr(advance, "pin_code", lambda: runner.commands.append(["pin"]))

    _tick(monkeypatch, store, _reviewing(), runner, PROPOSE_TIME, pin=True)
    assert [c[0] for c in runner.commands] == ["pin", "scripts/team_cleanup/propose_week.py"]

    write_run(store, {**read_run(store, RUN), "status": "proposing"})
    _tick(monkeypatch, store, _reviewing(), runner, PROPOSE_TIME + timedelta(hours=1), pin=True)
    _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW, pin=True)

    assert [c[0] for c in runner.commands].count("pin") == 1


def test_a_failed_move_to_new_code_holds_the_week_and_emails_the_owner_after_a_day(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    runner = _Runner(store)
    monkeypatch.setattr(advance, "pin_code", lambda: "git checkout -q --detach origin/main exited 1: local changes")

    assert _tick(monkeypatch, store, _Runs(), runner, PROPOSE_TIME, pin=True) == 1
    assert runner.commands == [] and "moving the checkout to origin/main failed" in _state(store)["problem"]

    _tick(monkeypatch, store, _Runs(), runner, PROPOSE_TIME + timedelta(hours=25), pin=True)

    assert runner.commands == [] and _subjects(emails) == [STUCK]


def test_a_week_whose_propose_fails_before_its_run_exists_emails_the_owner_after_a_day(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    runner = _Runner(store, codes={("propose_week.py", None): [1, 1]})

    for hours in (0, 25):
        assert _tick(monkeypatch, store, _Runs(), runner, PROPOSE_TIME + timedelta(hours=hours)) == 1

    assert not (run_dir(store, RUN) / RUN_FILE).exists() and _subjects(emails) == [STUCK]


# --- the review ----------------------------------------------------------------------------------------


def _reviewing(owner_done_at=None, requests=()):
    run = {"run_id": RUN, "status": "reviewing", "owner_done_at": owner_done_at, "owner_done_by": None}
    return _Runs([run], requests)


def _undo(stage="states", lane="auto", n=1):
    """An undo the owner asked for on the page, as the website files it."""
    return {
        "id": f"r{n}",
        "run_id": RUN,
        "stage": stage,
        "lane": lane,
        "action": "revert",
        "requested_at": f"2026-10-24T17:0{n}:00Z",
        "status": "pending",
        "handled_at": None,
        "result": None,
    }


def _reverts(runner):
    return [c for c in runner.commands if "--revert" in c]


def test_every_page_is_built_and_published_and_the_owner_emailed_once(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    runner = _Runner(store)

    code = _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW)

    assert code == 0
    assert runner.ran() == [
        ("pages.py", "clubs", None),
        ("pages.py", "states", None),
        ("pages.py", "ages", None),
        ("pages.py", "merges", None),
        ("collect.py", "clubs", "auto"),
        ("collect.py", "states", "auto"),
        ("collect.py", "ages", "auto"),
        ("collect.py", "merges", "auto"),
    ]
    assert all({"--publish", "--execute"} <= set(c) for c in runner.commands[:4])
    assert _subjects(emails) == ["PitchRank cleanup: 8 change(s) to review"]
    assert "https://www.pitchrank.io/mission-control/cleanup" in emails[0][2] and "Sunday 6:00 PM" in emails[0][2]

    _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW + timedelta(hours=1))

    assert len(emails) == 1


def test_the_automatic_lanes_apply_inside_the_window_while_the_owner_still_decides(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    runner = _Runner(store)
    _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW)
    runner.commands.clear()

    _tick(monkeypatch, store, _reviewing(), runner, IN_WINDOW)

    assert runner.ran() == [("apply_stage.py", stage, "auto") for stage in STAGES]
    assert all(c[c.index("--lane") :][:3] == ["--lane", "auto", "--execute"] for c in runner.commands)


def test_once_the_owner_marks_done_the_choices_are_collected_applied_and_the_run_closed(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    runner = _Runner(store)

    _tick(monkeypatch, store, _reviewing("2026-10-24T17:00:00Z"), runner, IN_WINDOW)

    assert [r for r in runner.ran() if r[0] != "pages.py"] == [
        *[step for stage in STAGES for step in (("collect.py", stage, "auto"), ("apply_stage.py", stage, "auto"))],
        *[step for stage in STAGES for step in (("collect.py", stage, "from-db"), ("apply_stage.py", stage, None))],
        ("end_run.py", None, None),
    ]
    assert runner.commands[-1] == [
        "scripts/team_cleanup/end_run.py",
        "--run",
        RUN,
        "--done",
        "--execute",
        "--store",
        str(store),
    ]
    assert read_run(store, RUN)["status"] == "done"
    assert _subjects(emails) == ["PitchRank cleanup: 8 change(s) to review", f"PitchRank cleanup {RUN} is finished"]


def test_within_a_tick_each_lane_reaches_merges_after_the_other_stages(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    runner = _Runner(store)

    _tick(monkeypatch, store, _reviewing("2026-10-24T17:00:00Z"), runner, IN_WINDOW)

    applies = [(stage, lane) for script, stage, lane in runner.ran() if script == "apply_stage.py"]
    assert applies == [
        ("clubs", "auto"),
        ("states", "auto"),
        ("ages", "auto"),
        ("merges", "auto"),
        ("clubs", None),
        ("states", None),
        ("ages", None),
        ("merges", None),
    ]


def test_choices_marked_done_before_the_window_are_collected_and_wait_for_it(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    runner = _Runner(store)

    assert _tick(monkeypatch, store, _reviewing("2026-10-22T17:00:00Z"), runner, BEFORE_WINDOW) == 0

    assert ("collect.py", "states", "from-db") in runner.ran()
    assert not [r for r in runner.ran() if r[0] == "apply_stage.py"] and "blocked_since" not in _state(store)


def test_at_the_deadline_the_review_is_marked_done_and_the_choices_apply(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    db = _reviewing()
    runner = _Runner(store)

    _tick(monkeypatch, store, db, runner, PAST_DEADLINE)

    assert db.rows[0]["owner_done_by"] == "deadline" and db.rows[0]["owner_done_at"] == "2026-10-26T02:00:00Z"
    assert ("apply_stage.py", "states", None) in runner.ran() and read_run(store, RUN)["status"] == "done"


def test_a_failed_close_sends_no_summary(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    runner = _Runner(store, codes={("end_run.py", None): [1]})

    assert _tick(monkeypatch, store, _reviewing("2026-10-24T17:00:00Z"), runner, IN_WINDOW) == 1

    assert f"PitchRank cleanup {RUN} is finished" not in _subjects(emails)


def test_a_stage_noted_as_not_run_this_week_is_left_alone(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store, notes={"ages": "skill_stale: the self-check exited 1"})
    runner = _Runner(store)

    _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW)

    assert "ages" not in {stage for _, stage, _ in runner.ran()}


# --- undo requests --------------------------------------------------------------------------------------


def test_an_undo_runs_once_its_lane_has_applied_and_is_recorded_done_before_the_run_closes(
    tmp_path, monkeypatch, emails
):
    store = tmp_path / "store"
    _proposed(store)
    db = _reviewing("2026-10-24T17:00:00Z", [_undo("states", "auto")])
    runner = _Runner(store)

    assert _tick(monkeypatch, store, db, runner, IN_WINDOW) == 0

    assert _reverts(runner) == [
        [
            "scripts/team_cleanup/apply_stage.py",
            "--run",
            RUN,
            "--stage",
            "states",
            "--lane",
            "auto",
            "--revert",
            "--execute",
            "--store",
            str(store),
        ]
    ]
    assert runner.commands.index(_reverts(runner)[0]) < [Path(c[0]).name for c in runner.commands].index("end_run.py")
    assert (db.requests[0]["status"], db.requests[0]["handled_at"], db.requests[0]["result"]) == (
        "done",
        "2026-10-24T18:00:00Z",
        "ran",
    )


def test_an_undo_of_a_lane_not_yet_applied_waits_for_it(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    db = _reviewing(None, [_undo("states", "owner")])
    runner = _Runner(store)

    _tick(monkeypatch, store, db, runner, IN_WINDOW)

    assert _reverts(runner) == [] and db.requests[0]["status"] == "pending"


def test_an_undo_that_must_wait_holds_the_close_and_one_that_fails_is_recorded(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    db = _reviewing("2026-10-24T17:00:00Z", [_undo("states", "auto")])
    # The states automatic apply, the owner's apply, then the undo: waiting, then failing.
    runner = _Runner(store, codes={("apply_stage.py", "states"): [0, 0, 75, 1]})

    _tick(monkeypatch, store, db, runner, IN_WINDOW)

    assert db.requests[0]["status"] == "pending" and read_run(store, RUN)["status"] == "reviewing"
    assert "end_run.py" not in [Path(c[0]).name for c in runner.commands]

    assert _tick(monkeypatch, store, db, runner, IN_WINDOW + timedelta(hours=1)) == 1

    assert (db.requests[0]["status"], db.requests[0]["result"]) == ("failed", "the step's own refusal")
    # The run then closes in that tick, so the summary is where the owner hears the undo failed.
    assert read_run(store, RUN)["status"] == "done"
    assert "Undo of the states automatic lane: failed (the step&#x27;s own refusal)" in emails[-1][2]


def test_an_undo_of_the_last_finished_run_is_run_by_the_next_tick(tmp_path, monkeypatch, emails):
    """A run's last lane applies and the run closes in one tick, so the page offers its undo after the close."""
    store = tmp_path / "store"
    _proposed(store, status="done")
    (stage_dir(store, RUN, "states") / "auto").mkdir()
    (stage_dir(store, RUN, "states") / "auto" / "RECORD.md").write_text("applied", encoding="utf-8")
    db = _Runs([], [_undo("states", "auto")])
    runner = _Runner(store)

    _tick(monkeypatch, store, db, runner, IN_WINDOW)

    assert [c[c.index("--stage") :][:5] for c in _reverts(runner)] == [
        ["--stage", "states", "--lane", "auto", "--revert"]
    ]
    assert db.requests[0]["status"] == "done"


def test_an_undo_left_on_an_older_finished_run_is_still_run_after_a_newer_run_closes(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    older = "2026-10-14-all"
    _proposed(store, older, "done")
    _proposed(store, status="done")
    (stage_dir(store, older, "states") / "auto").mkdir()
    (stage_dir(store, older, "states") / "auto" / "RECORD.md").write_text("applied", encoding="utf-8")
    db = _Runs([], [{**_undo("states", "auto"), "run_id": older}])
    runner = _Runner(store)

    _tick(monkeypatch, store, db, runner, IN_WINDOW)

    assert [_arg(c, "--run") for c in _reverts(runner)] == [older]
    assert db.requests[0]["status"] == "done"


def test_a_requests_table_not_yet_created_holds_no_run_open(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    db = _reviewing("2026-10-24T17:00:00Z")
    db.missing.add("team_cleanup_requests")

    assert _tick(monkeypatch, store, db, _Runner(store), IN_WINDOW) == 0

    assert read_run(store, RUN)["status"] == "done"


def test_an_undo_of_a_lane_nothing_was_sent_to_or_a_stage_not_run_is_recorded_failed(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store, notes={"ages": "skill_stale: the self-check exited 1"})
    db = _reviewing("2026-10-24T17:00:00Z", [_undo("clubs", "auto", 1), _undo("ages", "owner", 2)])
    runner = _Runner(store)
    runner.auto = 0

    _tick(monkeypatch, store, db, runner, IN_WINDOW)

    assert _reverts(runner) == []
    assert [(r["status"], r["result"]) for r in db.requests] == [
        ("failed", "nothing was sent to the clubs automatic lane, so nothing to undo"),
        ("failed", "the ages stage was not run this week, so nothing of it applied"),
    ]
    assert read_run(store, RUN)["status"] == "done"


# --- waiting, failing and being stuck -------------------------------------------------------------------


def test_a_step_that_must_wait_holds_only_its_own_stage(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    runner = _Runner(store, codes={("pages.py", "states"): [75]})

    code = _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW)

    assert code == 0
    assert ("pages.py", "ages", None) in runner.ran() and ("collect.py", "states", "auto") not in runner.ran()
    assert emails == [] and _state(store)["blocked_since"] == "2026-10-22T18:00:00Z"


def test_a_failed_step_fails_the_tick_and_is_tried_again_by_the_next(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    runner = _Runner(store, codes={("pages.py", "clubs"): [1]})

    assert _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW) == 1
    assert "build and publish the clubs page failed" in _state(store)["problem"]

    assert _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW + timedelta(hours=1)) == 0
    assert "blocked_since" not in _state(store)


def test_a_database_that_cannot_be_read_fails_the_tick_and_is_recorded(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    db = _reviewing()
    db.broken = APIError({"code": "PGRST000", "message": "connection refused", "details": None, "hint": None})

    assert _tick(monkeypatch, store, db, _Runner(store), BEFORE_WINDOW) == 1
    assert f"Reading or marking run {RUN}'s review in team_cleanup_runs" in _state(store)["problem"]


def test_a_run_blocked_for_a_day_emails_the_owner_once(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    runner = _Runner(store, codes={("pages.py", "clubs"): [75, 75, 75]})

    for hours in (0, 25, 26):
        _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW + timedelta(hours=hours))

    assert _subjects(emails).count(STUCK) == 1


def test_a_stuck_email_that_failed_to_send_is_sent_by_a_later_tick(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    runner = _Runner(store, codes={("pages.py", "clubs"): [75, 75, 75, 75]})
    _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW)

    monkeypatch.setattr(advance, "send_email", lambda to, subject, body: False)
    _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW + timedelta(hours=25))
    monkeypatch.setattr(advance, "send_email", _sender(emails))
    for hours in (26, 27):
        _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW + timedelta(hours=hours))

    assert _subjects(emails) == [STUCK]


def test_an_apply_outside_the_window_is_waiting_not_stuck(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    runner = _Runner(store)

    for hours in (0, 25):  # Thursday 11:00 and Friday 12:00, both before the window opens
        _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW + timedelta(hours=hours))

    assert "blocked_since" not in _state(store)
    assert not [s for s in _subjects(emails) if "stuck" in s]


def test_an_owner_without_an_address_is_emailed_on_a_later_tick(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    runner = _Runner(store)
    monkeypatch.delenv("CLEANUP_OWNER_EMAIL")

    _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW)
    assert emails == []

    monkeypatch.setenv("CLEANUP_OWNER_EMAIL", "owner@example.test")
    _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW + timedelta(hours=1))
    assert _subjects(emails) == ["PitchRank cleanup: 8 change(s) to review"]


def test_a_summary_that_failed_to_send_is_sent_by_a_later_tick(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    _proposed(store)
    runner = _Runner(store)
    monkeypatch.setattr(
        advance, "send_email", lambda to, subject, body: "finished" not in subject and emails.append(subject) is None
    )
    _tick(monkeypatch, store, _reviewing("2026-10-24T17:00:00Z"), runner, IN_WINDOW)
    assert read_run(store, RUN)["status"] == "done" and "closed" not in _state(store).get("emailed", {})

    monkeypatch.setattr(advance, "send_email", lambda to, subject, body: emails.append(subject) is None)
    _tick(monkeypatch, store, _reviewing("2026-10-24T17:00:00Z"), runner, IN_WINDOW + timedelta(hours=1))

    assert emails[-1] == f"PitchRank cleanup {RUN} is finished" and "closed" in _state(store)["emailed"]


# --- a dry run, the command line, the pause and the lock --------------------------------------------------


def test_a_dry_run_runs_nothing_writes_nothing_and_emails_no_one(tmp_path, monkeypatch, emails, capsys):
    store = tmp_path / "store"
    _proposed(store)
    db = _reviewing()
    runner = _Runner(store)

    code = _tick(monkeypatch, store, db, runner, PAST_DEADLINE, execute=False)

    out = capsys.readouterr().out
    assert code == 0 and runner.commands == [] and db.writes == [] and emails == []
    assert not (run_dir(store, RUN) / "autopilot.json").exists()
    assert "DRY RUN -- would build and publish the clubs page" in out
    assert "DRY RUN -- would mark run 2026-10-21-all's review done at the deadline" in out


def test_a_dry_run_moves_no_code_and_sends_no_email_still_owed(tmp_path, monkeypatch, emails):
    store = tmp_path / "store"
    monkeypatch.setattr(advance, "pin_code", lambda: pytest.fail("a dry run moved the checkout"))
    _tick(monkeypatch, store, _Runs(), _Runner(store), PROPOSE_TIME, execute=False, pin=True)

    _proposed(store)
    runner = _Runner(store)
    monkeypatch.delenv("CLEANUP_OWNER_EMAIL")
    _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW)
    state = _state(store)
    monkeypatch.setenv("CLEANUP_OWNER_EMAIL", "owner@example.test")
    _tick(monkeypatch, store, _reviewing(), runner, BEFORE_WINDOW + timedelta(hours=1), execute=False)

    assert emails == [] and _state(store) == state


class _FakeTick:
    made = []

    def __init__(self, sb, store, now, execute, *, window, deadline, pin=False):
        _FakeTick.made.append({"execute": execute, "pin": pin, "window": window, "deadline": deadline})

    def tick(self):
        return 3


def _main(monkeypatch, store, *flags, client=None):
    if client is None:
        monkeypatch.setattr(advance, "get_client", lambda: pytest.fail("a paused or locked tick opens no client"))
    else:
        monkeypatch.setattr(advance, "get_client", lambda: client)
    monkeypatch.setattr(sys, "argv", ["advance.py", "--store", str(store), *flags])
    return advance.main()


def _settings_from(monkeypatch, path):
    """main() reads config/team_cleanup.json; these tests read a copy whose deadline falls inside the window."""
    load_deadline = advance.load_deadline
    monkeypatch.setattr(advance, "load_window", lambda config=path: load_window(config))
    monkeypatch.setattr(advance, "load_deadline", lambda: load_deadline(path))


def test_the_command_line_reaches_the_tick_dry_unless_told_and_returns_its_code(tmp_path, monkeypatch):
    path = _config(tmp_path)
    _settings_from(monkeypatch, path)
    monkeypatch.setattr(advance, "Tick", _FakeTick)
    _FakeTick.made = []
    store = tmp_path / "store"

    codes = [
        _main(monkeypatch, store, *flags, client=_Runs())
        for flags in ((), ("--pin-code",), ("--execute", "--pin-code"), ("--execute", "--dry-run"))
    ]

    assert codes == [3, 3, 3, 3]
    assert [(made["execute"], made["pin"]) for made in _FakeTick.made] == [
        (False, False),
        (False, True),
        (True, True),
        (False, False),
    ]
    assert _FakeTick.made[0]["window"] == load_window(path) and _FakeTick.made[0]["deadline"] == 6180


def test_a_paused_autopilot_does_nothing(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    store.mkdir()
    (store / "autopilot.paused").write_text("", encoding="utf-8")

    assert _main(monkeypatch, store, "--execute") == 0
    assert "The autopilot is paused" in capsys.readouterr().out


def test_a_tick_leaves_the_run_to_another_tick_already_running(tmp_path, monkeypatch, capsys):
    store = tmp_path / "store"
    store.mkdir()
    _settings_from(monkeypatch, _config(tmp_path))

    with _acquire_file_lock(store / "advance.lock", timeout=0.0):
        assert _main(monkeypatch, store, "--execute") == 0
    assert "Another tick holds" in capsys.readouterr().out
