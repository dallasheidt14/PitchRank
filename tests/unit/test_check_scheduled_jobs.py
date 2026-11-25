"""Tests for the daily scheduled-job check.

No test reaches the real `gh` or the network: an autouse fixture refuses both unless a test
installs a fake. The GitHub fake routes by the exact Actions API path, query string included,
and records every call. One `requests.post` fake serves both hosts, because the script and the
email helper share the imported `requests` module: Supabase answers per query text, Resend with
a status the test sets, and every response decodes its JSON from its bytes.

Run ids, addresses and project refs are made up. Real workflow files are read where a rule is
about them; fixtures that drive the rules carry real timings.
"""

import html
import json
import logging
import re
import subprocess
import sys
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs

import pytest
import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from scripts import check_scheduled_jobs as job  # noqa: E402

UTC = timezone.utc
FIXTURES = ROOT / "tests" / "fixtures" / "scheduled_jobs_check"
WORKFLOWS = ROOT / ".github" / "workflows"
NOW = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)
TOKEN = "test-token"
PROJECT_URL = "https://abcdefgh.supabase.co"
DATED_LABEL = re.compile(r"[A-Za-z][A-Za-z ]* \d{4}-\d{2}-\d{2}")


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    def refuse_gh(*args, **kwargs):
        raise AssertionError("a test reached the real gh")

    def refuse_post(*args, **kwargs):
        raise AssertionError("a test reached the network")

    monkeypatch.setattr(job.subprocess, "run", refuse_gh)
    monkeypatch.setattr(job.requests, "post", refuse_post)
    for name in (
        "GITHUB_ACTIONS",
        "GITHUB_RUN_ID",
        "GITHUB_SERVER_URL",
        "WEEKLY",
        "SUPABASE_URL",
        "SUPABASE_ACCESS_TOKEN",
        "RESEND_API_KEY",
        "ALERT_EMAIL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(job, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(job, "_github_failed", False)
    monkeypatch.setattr(job, "github_calls", 0)
    monkeypatch.setattr(job.time, "sleep", lambda seconds: None)
    yield
    resend_logger = logging.getLogger("src.utils.resend_email")
    for f in list(resend_logger.filters):
        if isinstance(f, job._HideResendBody):
            resend_logger.removeFilter(f)


# --------------------------------------------------------------------------- #
# Doubles
# --------------------------------------------------------------------------- #


class FakeGh:
    """`subprocess.run` for `gh api`: answers by exact path, and fails a path while `fail` says so.
    A route set with `then()` answers its payloads in turn and then repeats the last."""

    def __init__(self, routes=None, fail=None):
        self.routes = dict(routes or {})
        self.sequences: dict[str, list] = {}
        self.fail = fail or (lambda path, calls: False)
        self.calls: list[str] = []

    def then(self, path, *payloads):
        self.sequences[path] = list(payloads)

    def __call__(self, command, **kwargs):
        assert command[:4] == ["gh", "api", "-H", "X-GitHub-Api-Version: 2026-03-10"]
        assert kwargs == {"capture_output": True, "text": True, "check": True, "timeout": 60}
        prefix = f"repos/{job.REPO}/actions/"
        assert command[4].startswith(prefix)
        path = command[4][len(prefix) :]
        self.calls.append(path)
        if self.fail(path, self.calls):
            raise subprocess.CalledProcessError(1, command, output="", stderr="HTTP 502")
        if path in self.sequences:
            queue = self.sequences[path]
            payload = queue.pop(0) if len(queue) > 1 else queue[0]
        elif path in self.routes:
            payload = self.routes[path]
        else:
            raise AssertionError(f"no gh route for {path}")
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")


class FakeResponse:
    def __init__(self, status_code, payload=None, content=None):
        self.status_code = status_code
        self.content = content if content is not None else json.dumps(payload).encode("utf-8")

    @property
    def ok(self):
        return self.status_code < 400

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        try:
            return json.loads(self.content)
        except ValueError as exc:
            raise requests.exceptions.JSONDecodeError(str(exc), self.text, 0) from None


def row(**values):
    return [{"read_only": "on", **values}]


def healthy_answers():
    return {
        job.PUBLICATION_SQL: row(
            ranking_start="2026-11-23 12:30:00+00",
            row_count=150056,
            stale_rows=0,
            newest_calculated="2026-11-24 03:56:00.3+00",
            previous_snapshot_date="2026-11-19",
            previous_snapshot_rows=150562,
            complete=True,
        ),
        job.BUILD_HEARTBEAT_QUERY: row(heartbeats=[]),
        job.GAME_WINDOWS_QUERY: row(game_windows=[]),
        job.SCRAPE_QUEUE_QUERY: row(
            stuck_processing=0,
            oldest_stuck_claimed=None,
            oldest_pending_requested="2026-11-25 14:30:00+00",
            completed_recently=True,
        ),
    }


class FakePost:
    """`requests.post` for both hosts. A Supabase answer is a payload, a (status, payload) pair,
    or an exception to raise."""

    def __init__(self, ref="abcdefgh"):
        self.ref = ref
        self.answers = healthy_answers()
        self.resend_status = 200
        self.resend_body = b'{"id": "made-up"}'
        self.calls: dict[str, list] = {"api.supabase.com": [], "api.resend.com": []}

    def __call__(self, url, **kwargs):
        if url.startswith("https://api.supabase.com/"):
            assert url == f"https://api.supabase.com/v1/projects/{self.ref}/database/query/read-only"
            assert kwargs["headers"] == {"Authorization": f"Bearer {TOKEN}"}
            assert kwargs["timeout"] == 60 and kwargs["allow_redirects"] is False
            answer = self.answers[kwargs["json"]["query"]]
            if isinstance(answer, BaseException):
                self.calls["api.supabase.com"].append(None)
                raise answer
            status, payload = answer if isinstance(answer, tuple) else (200, answer)
            self.calls["api.supabase.com"].append(status)
            return FakeResponse(status, payload)
        if url == "https://api.resend.com/emails":
            self.calls["api.resend.com"].append(kwargs["json"])
            return FakeResponse(self.resend_status, content=self.resend_body)
        raise AssertionError(f"unexpected POST to {url}")


def freeze(monkeypatch, moment=NOW):
    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment if tz else moment.replace(tzinfo=None)

    monkeypatch.setattr(job, "datetime", _Clock)


def runs_path(file, event, since_date, *, bot=False, page=1):
    """The run-list path, percent-encoded by hand rather than by the code under test."""
    actor = "&actor=github-actions%5Bbot%5D" if bot else ""
    return f"workflows/{file}/runs?branch=main&event={event}{actor}&created=%3E%3D{since_date}&per_page=100&page={page}"


SINCE_DATE = "2026-11-10"
INVENTORY = "workflows?per_page=100&page=1"


def gh_run(run_id, started, conclusion="success", *, status="completed", event="schedule"):
    return {
        "id": run_id,
        "event": event,
        "head_branch": "main",
        "status": status,
        "conclusion": conclusion,
        "run_started_at": started,
        "html_url": f"https://github.com/example/PitchRank/actions/runs/{run_id}",
    }


def runs_page(*runs, total=None):
    return {"total_count": len(runs) if total is None else total, "workflow_runs": list(runs)}


def jobs_path(run_id, page=1):
    return f"runs/{run_id}/jobs?per_page=100&page={page}"


def jobs_payload(*steps, conclusion="success", name="run", job_id=1):
    steps = [{"name": s, "conclusion": c} for s, c in steps]
    return {"total_count": 1, "jobs": [{"id": job_id, "name": name, "conclusion": conclusion, "steps": steps}]}


DID_WORK = jobs_payload(("Set up job", "success"), ("Do the work", "success"), ("Complete job", "success"))


def state_row(file, state="active", created="2026-10-01T09:00:00.000-07:00"):
    return {"id": zlib.crc32(file.encode()), "path": f".github/workflows/{file}", "state": state, "created_at": created}


def inventory(*rows):
    return {"total_count": len(rows), "workflows": list(rows)}


def write_workflow(root, file, crons, steps, name=None):
    doc = {
        "name": name or file,
        "on": {"schedule": [{"cron": c} for c in crons], "workflow_dispatch": None},
        "jobs": {"run": {"runs-on": "ubuntu-latest", "steps": steps}},
    }
    folder = root / ".github" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / file).write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


WORK_STEPS = [
    {"name": "Checkout repository", "uses": "actions/checkout@v5"},
    {"name": "Do the work", "run": "echo work"},
]


class World:
    def __init__(self, root, gh, post):
        self.root, self.gh, self.post = root, gh, post


@pytest.fixture
def world(tmp_path, monkeypatch):
    """One healthy weekly workflow whose last scheduled run did its work, healthy data, and every
    setting present."""
    write_workflow(tmp_path, "weekly.yml", ["0 6 * * 1"], WORK_STEPS, name="Weekly job")
    gh = FakeGh(
        {
            INVENTORY: inventory(state_row("weekly.yml")),
            runs_path("weekly.yml", "schedule", SINCE_DATE): runs_page(
                gh_run(101, "2026-11-23T13:00:00Z"), gh_run(100, "2026-11-16T13:00:00Z")
            ),
            jobs_path(101): DID_WORK,
            jobs_path(100): DID_WORK,
        }
    )
    post = FakePost()
    monkeypatch.setattr(job, "ROOT", tmp_path)
    monkeypatch.setattr(job.subprocess, "run", gh)
    monkeypatch.setattr(job.requests, "post", post)
    monkeypatch.setenv("SUPABASE_URL", PROJECT_URL)
    monkeypatch.setenv("SUPABASE_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("RESEND_API_KEY", "re_made_up")
    freeze(monkeypatch)
    return World(tmp_path, gh, post)


def make_problem(world):
    """A rankings publication missing two fifths of its rows, so the daily run has something to send."""
    world.post.answers[job.PUBLICATION_SQL] = row(
        ranking_start="2026-11-23 12:30:00+00",
        row_count=90000,
        stale_rows=0,
        newest_calculated="2026-11-24 03:56:00+00",
        previous_snapshot_date="2026-11-19",
        previous_snapshot_rows=150000,
        complete=False,
    )


def run_main(argv=(), caplog=None):
    with caplog.at_level(logging.INFO):
        return job.main(list(argv))


def messages(caplog):
    return [r.getMessage() for r in caplog.records]


def incomplete_lines(findings):
    return [f.text for f in findings if f.check == "incomplete"]


# --------------------------------------------------------------------------- #
# Cron and series
# --------------------------------------------------------------------------- #


def synthetic(crons, *, name="Synthetic", file="synthetic.yml", chain=False, guarded=False, productive=()):
    return job.Workflow(
        file=file,
        name=name,
        series=tuple(job.build_series(tuple(crons))),
        guarded=guarded,
        chain=chain,
        productive_names=frozenset(productive),
        setup_names=frozenset({"Checkout repository"}),
        importer_steps=(),
    )


@pytest.fixture(scope="module")
def real():
    workflows, broken = job.load_workflows(ROOT)
    assert broken == {}
    return {wf.file: wf for wf in workflows}


def test_a_tuesday_and_friday_cron_alternates_three_and_four_day_gaps():
    dues = job.due_times(job.parse_cron("23 5 * * 2,5"), at("2026-11-02 00:00"), at("2026-11-30 00:00"))
    gaps = {(b - a).days for a, b in zip(dues, dues[1:])}

    assert dues[0] == at("2026-11-03 05:23")
    assert gaps == {3, 4}
    assert [d.weekday() for d in dues[:4]] == [1, 4, 1, 4]


def test_a_quarter_hour_cron_is_frequent_and_a_daily_one_is_not():
    assert job.build_series(("7,22,37,52 * * * *",))[0].frequent is True
    assert job.build_series(("20 6 * * *",))[0].frequent is False


def test_day_of_week_seven_is_sunday():
    assert job.parse_cron("0 6 * * 7").weekdays == job.parse_cron("0 6 * * 0").weekdays == frozenset({0})


@pytest.mark.parametrize(
    "expr", ["0 6 * * MON", "0 6 1 * 1", "0 6 1 * *", "0 6 * 1 *", "0 6 L * *", "0 6 * * 1#2", "0 6 *"]
)
def test_a_cron_form_the_check_cannot_read_raises(expr):
    with pytest.raises(ValueError):
        job.parse_cron(expr)


def test_the_or_daylight_saving_pair_is_one_series_at_the_earlier_hour(real):
    (series,) = real["or-scraper.yml"].series

    assert series.label == "30 6 * * 1 / 30 7 * * 1"
    assert series.grace == timedelta(hours=25)
    assert series.due_times(at("2026-11-23 00:00"), at("2026-11-24 00:00")) == [at("2026-11-23 06:30")]


def test_compare_live_monitoring_has_two_series(real):
    labels = [s.label for s in real["compare-live-monitoring.yml"].series]

    assert labels == ["20 6 * * *", "30 17 * * 1"]


def test_crons_an_hour_apart_on_different_days_stay_two_series():
    series = job.build_series(("0 6 * * 1", "0 7 * * 2"))

    assert [s.label for s in series] == ["0 6 * * 1", "0 7 * * 2"]
    assert {s.grace for s in series} == {timedelta(hours=24)}


@pytest.mark.parametrize(
    "crons",
    [
        ("0 6 * * 1", "0 7 * * 1", "0 12 * * 4"),
        ("5 * * * *", "0 12 * * 1"),
        ("0 6 * * *", "0 18 * * *"),
        ("0 6 * * 1-5", "0 9 * * 1-5"),
        ("0 6 * * 1,4", "0 18 * * 1,4"),
        ("0 6 * * 1", "0 6 * * 1,4"),
        ("0 12 * * 0", "0 6 * * 1-5", "0 9 * * 1-5"),
    ],
    ids=[
        "pair beside another",
        "hourly beside weekly",
        "two daily",
        "shared weekdays",
        "two shared days",
        "same time",
        "clash not first",
    ],
)
def test_schedules_whose_runs_cannot_be_told_apart_are_refused(crons):
    with pytest.raises(job.UnmatchableSchedules):
        job.build_series(crons)


@pytest.mark.parametrize(
    "crons",
    [
        ("20 6 * * *", "30 17 * * 1"),
        ("41 6 * * *", "0 19 * * 2"),
        ("0 6 * * 1", "0 7 * * 2"),
        ("0 6 * * 1", "0 18 * * 1"),
        ("0 6 * * 1", "30 6 * * 1"),
        ("0 6 * * 1", "0 6 * * 4"),
    ],
    ids=[
        "daily and Monday",
        "this checker",
        "Monday and Tuesday",
        "twice on Monday",
        "same hour, other minute",
        "same time, other day",
    ],
)
def test_schedules_that_can_be_told_apart_are_kept(crons):
    assert [s.label for s in job.build_series(crons)] == list(crons)


def test_the_ranking_start_the_sql_assumes_is_the_ranking_schedule(real):
    """The publication SQL takes the latest Monday 12:30 UTC as the run's start. The rankings
    deadline is 30 hours later (Tuesday 18:30 UTC), and the Tuesday all-clear cron (0 19 * * 2)
    fires half an hour after that."""
    assert [s.label for s in real["calculate-rankings.yml"].series] == ["30 12 * * 1"], (
        "calculate-rankings.yml moved: update the start in scripts/sql/rankings_publication_complete.sql "
        "and the Tuesday cron in scheduled-jobs-check.yml"
    )
    assert "interval '12 hours 30 minutes'" in job.PUBLICATION_SQL
    assert job.RANKINGS_DEADLINE == timedelta(hours=30)


def test_only_the_tgs_scrape_is_a_chain(real):
    assert sorted(f for f, wf in real.items() if wf.chain) == ["tgs-event-scrape-import.yml"]


# --------------------------------------------------------------------------- #
# Provider mapping, derived from the workflow files
# --------------------------------------------------------------------------- #

# Broader than the script's own pattern, so an importer form the script misses fails here
# instead of dropping out of both.
ANY_IMPORTER = re.compile(r"(?<!\w)import_\w+\.py|-m\s*scripts\.import_\w+|process_missing_games")
SEPARATOR = re.compile(r"&&|\|\||;|\|")


def unmapped_invocations(folder: Path, root: Path) -> list[tuple[str, str]]:
    found = []
    for path in sorted(folder.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        triggers = doc.get("on", doc.get(True))
        if not (isinstance(triggers, dict) and triggers.get("schedule")):
            continue
        for job_def in doc["jobs"].values():
            for step in job_def.get("steps") or []:
                for line in str(step.get("run") or "").splitlines():
                    if line.lstrip().startswith("#"):
                        continue
                    for invocation in SEPARATOR.split(line):
                        for _ in ANY_IMPORTER.finditer(invocation):
                            try:
                                codes = job.importer_providers(invocation, root)
                            except (job.UnmappedImporter, OSError):
                                codes = set()
                            if not codes or not all(re.fullmatch(r"[a-z0-9_]+", c) for c in codes):
                                found.append((path.name, invocation.strip()))
    return found


def importer_count(folder: Path) -> int:
    count = 0
    for path in folder.glob("*.y*ml"):
        text = path.read_text(encoding="utf-8")
        if "schedule:" in text:
            live = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
            count += sum(len(ANY_IMPORTER.findall(line)) for line in live)
    return count


def test_every_scheduled_importer_invocation_maps_to_a_provider_code():
    assert importer_count(WORKFLOWS) >= 10
    assert unmapped_invocations(WORKFLOWS, ROOT) == []


@pytest.mark.parametrize(
    "file, code",
    [
        ("yssl-scraper.yml", "yssl"),
        ("process-missing-games.yml", "gotsport"),
        ("or-scraper.yml", "affinity_or"),
        ("ea-scraper.yml", "modular11_ea"),
        ("demosphere-scraper.yml", "demosphere"),
        ("tgs-event-scrape-import.yml", "tgs"),
    ],
)
def test_the_scan_finds_known_importers(real, file, code):
    assert code in {c for _, codes in real[file].importer_steps for c in codes}


def _scheduled_run(tmp_path, file, run):
    write_workflow(tmp_path, file, ["0 6 * * 1"], [{"name": "Import", "run": run}])


def test_an_importer_form_the_script_misses_fails_the_coverage_scan(tmp_path):
    _scheduled_run(tmp_path, "lines.yml", "python scripts/import_yssl.py\npython -m scripts.import_newthing\n")
    _scheduled_run(tmp_path, "joined.yml", "python scripts/import_yssl.py && python -m scripts.import_newthing\n")

    assert unmapped_invocations(tmp_path / ".github" / "workflows", ROOT) == [
        ("joined.yml", "python -m scripts.import_newthing"),
        ("lines.yml", "python -m scripts.import_newthing"),
    ]


def test_a_templated_provider_argument_is_unmapped_rather_than_truncated():
    with pytest.raises(job.UnmappedImporter):
        job.importer_providers('python scripts/import_games_enhanced.py "$F" affinity_${STATE}', ROOT)


def test_an_import_script_with_no_provider_code_is_unmapped(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "import_newthing.py").write_text("PROVIDER = 'x'\n", encoding="utf-8")

    with pytest.raises(job.UnmappedImporter):
        job.importer_providers("python scripts/import_newthing.py --days 7", tmp_path)


def test_the_tgs_team_extractor_is_not_an_importer():
    assert job.importer_providers("python scripts/extract_and_import_tgs_teams.py a.csv tgs", ROOT) == set()


def test_a_yaml_extension_reaches_the_loader_and_the_scan(tmp_path):
    _scheduled_run(tmp_path, "mapped.yaml", "python scripts/import_games_enhanced.py f.csv tgs")
    _scheduled_run(tmp_path, "other.yaml", "python -m scripts.import_x")

    workflows, broken = job.load_workflows(tmp_path)

    assert broken == {}
    assert {wf.file: wf.importer_steps for wf in workflows}["mapped.yaml"] == (("Import", frozenset({"tgs"})),)
    assert unmapped_invocations(tmp_path / ".github" / "workflows", tmp_path) == [
        ("other.yaml", "python -m scripts.import_x")
    ]


def test_each_unreadable_workflow_file_gets_its_own_reason(tmp_path):
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True)

    def raw(file, schedule, jobs=None):
        doc = {"on": {"schedule": schedule}, "jobs": {} if jobs is None else jobs}
        (folder / file).write_text(yaml.safe_dump(doc), encoding="utf-8")

    (folder / "bad-yaml.yml").write_text("on: [\n", encoding="utf-8")
    (folder / "bare-schedule.yml").write_text("on:\n  schedule:\njobs: {}\n", encoding="utf-8")
    raw("empty-schedule.yml", {})
    raw("empty-list.yml", [])
    (folder / "listed-trigger.yml").write_text("on: [workflow_dispatch, schedule]\njobs: {}\n", encoding="utf-8")
    (folder / "bare-trigger.yml").write_text("on: schedule\njobs: {}\n", encoding="utf-8")
    (folder / "push-only.yml").write_text("on: [push]\njobs: {}\n", encoding="utf-8")
    (folder / "not-utf8.yml").write_bytes(b"name: caf\xe9\non:\n  schedule:\n    - cron: '0 6 * * 1'\njobs: {}\n")
    raw("not-a-list.yml", 5)
    raw("string-entry.yml", ["0 6 * * 1"])
    raw("numeric-cron.yml", [{"cron": 600}])
    raw("no-cron.yml", [{"timezone": "UTC"}])
    raw("phoenix.yml", [{"cron": "0 6 * * 1", "timezone": "America/Phoenix"}])
    raw("jobs-list.yml", [{"cron": "0 6 * * 1"}], jobs=["build"])
    write_workflow(tmp_path, "monthly.yml", ["0 6 1 * *"], WORK_STEPS)
    write_workflow(tmp_path, "two-daily.yml", ["0 6 * * *", "0 18 * * *"], WORK_STEPS)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "import_newthing.py").write_text("PROVIDER = 'x'\n", encoding="utf-8")
    _scheduled_run(tmp_path, "unmapped.yml", "python scripts/import_newthing.py")
    raw("utc.yml", [{"cron": "0 6 * * 1", "timezone": "UTC"}])
    raw("etc-utc.yml", [{"cron": "0 6 * * 1", "timezone": "Etc/UTC"}])
    manual = {"on": {"workflow_dispatch": None}, "jobs": {}}
    (folder / "manual.yml").write_text(yaml.safe_dump(manual), encoding="utf-8")

    workflows, broken = job.load_workflows(tmp_path)

    assert [wf.file for wf in workflows] == ["etc-utc.yml", "utc.yml"]
    assert broken == {
        "bad-yaml.yml": "YAML that could not be read",
        "bare-schedule.yml": "a cron this check cannot read",
        "empty-schedule.yml": "a cron this check cannot read",
        "empty-list.yml": "a cron this check cannot read",
        "listed-trigger.yml": "a cron this check cannot read",
        "bare-trigger.yml": "a cron this check cannot read",
        "not-utf8.yml": "a workflow or importer file that is not UTF-8 text",
        "not-a-list.yml": "a cron this check cannot read",
        "string-entry.yml": "a cron this check cannot read",
        "numeric-cron.yml": "a cron this check cannot read",
        "no-cron.yml": "a cron this check cannot read",
        "phoenix.yml": "a schedule timezone other than UTC",
        "jobs-list.yml": "a layout this check cannot read",
        "monthly.yml": "a cron this check cannot read",
        "two-daily.yml": "schedules this check cannot tell apart",
        "unmapped.yml": "an importer with no provider code",
    }


def test_every_guarded_step_has_a_literal_name():
    guarded = 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        steps = [s for j in doc["jobs"].values() for s in j.get("steps") or []]
        if not any(s.get("id") == "guard" for s in steps):
            continue
        guarded += 1
        gated = [s for s in steps if "steps.guard.outputs" in str(s.get("if") or "")]
        assert gated, path.name
        assert all(isinstance(s.get("name"), str) and "${{" not in s["name"] for s in gated), path.name
    assert guarded >= 3


@pytest.mark.parametrize("file", ["calculate-rankings.yml", "tgs-score-reconcile.yml", "yssl-scraper.yml"])
def test_install_steps_from_real_files_are_setup(real, file):
    assert "Install dependencies" in real[file].setup_names


def test_unnamed_setup_commands_and_actions_are_setup(real):
    setup = real["compare-live-monitoring.yml"].setup_names

    assert {"Run actions/checkout@v5", "Run pip install -r requirements.lock", "Run npm ci --ignore-scripts"} <= setup


# --------------------------------------------------------------------------- #
# Counted runs
# --------------------------------------------------------------------------- #


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_the_inactive_daylight_saving_run_is_not_counted(real, monkeypatch):
    run = fixture("run_inactive_guard.json")
    gh = FakeGh({jobs_path(run["id"]): fixture("jobs_inactive_guard.json")})
    monkeypatch.setattr(job.subprocess, "run", gh)

    assert job.is_counted(run, real["ut-scraper.yml"], {}) is False
    assert gh.calls == [jobs_path(run["id"])]


def test_the_same_run_with_its_import_done_is_counted(real):
    run, jobs = fixture("run_inactive_guard.json"), fixture("jobs_inactive_guard.json")
    jobs["jobs"][0]["steps"][7]["conclusion"] = "success"

    assert jobs["jobs"][0]["steps"][7]["name"] == "Import scraped UT games"
    assert job.is_counted(run, real["ut-scraper.yml"], {run["id"]: jobs["jobs"]}) is True


def test_a_green_ranking_run_whose_real_steps_were_skipped_is_not_counted(real):
    names = [
        ("Set up job", "success"),
        ("Checkout repository", "success"),
        ("Verify branch", "skipped"),
        ("Show commit hash", "skipped"),
        ("Set up Python", "success"),
        ("Install dependencies", "success"),
        ("Check for active scrape workflows", "skipped"),
        ("Calculate Rankings", "skipped"),
        ("Preserve verified prediction inputs privately", "skipped"),
        ("Report results", "skipped"),
        ("Post Set up Python", "success"),
        ("Post Checkout repository", "success"),
        ("Complete job", "success"),
    ]
    run = gh_run(7, "2026-11-24T00:08:00Z")

    assert job.is_counted(run, real["calculate-rankings.yml"], {7: jobs_payload(*names)["jobs"]}) is False


def test_a_failed_job_is_not_counted(real):
    jobs = jobs_payload(("Calculate Rankings", "success"), conclusion="failure")["jobs"]

    assert job.is_counted(gh_run(8, "2026-11-24T00:08:00Z"), real["calculate-rankings.yml"], {8: jobs}) is False


def test_a_matrix_run_with_one_productive_job_is_counted(real):
    jobs = [
        jobs_payload(("Import EA games", "failure"), conclusion="failure", name="scrape-ea (u11)")["jobs"][0],
        jobs_payload(("Import EA games", "success"), name="scrape-ea (u12)")["jobs"][0],
    ]

    assert job.is_counted(gh_run(9, "2026-11-23T12:00:00Z", "failure"), real["ea-scraper.yml"], {9: jobs}) is True


def test_a_partly_failed_matrix_run_stays_flagged_although_it_counts(real):
    jobs = [
        jobs_payload(("Import EA games", "failure"), conclusion="failure", name="scrape-ea (u11)")["jobs"][0],
        jobs_payload(("Import EA games", "success"), name="scrape-ea (u12)", job_id=2)["jobs"][0],
    ]
    run = gh_run(9, "2026-11-23T12:00:00Z", "failure")

    (line,) = problems(job.evaluate_workflow(real["ea-scraper.yml"], CREATED, [run], [], NOW, {9: jobs}))

    assert line.text == "EA Scraper: the scheduled run started 2026-11-23 ended failure"


def test_an_unfinished_chain_link_does_not_count_once_its_first_job_succeeds(real):
    prepare = jobs_payload(("Compute shard gate", "success"), name="prepare")["jobs"]
    run = gh_run(10, "2026-11-23T13:00:00Z", None, status="in_progress", event="workflow_dispatch")

    chain = real["tgs-event-scrape-import.yml"]

    assert job.is_counted(run, chain, {10: prepare}) is False
    assert job.is_counted({**run, "status": "completed", "conclusion": "success"}, chain, {10: prepare}) is True


@pytest.mark.parametrize(
    "jobs",
    [
        [{"id": 1, "name": "run", "conclusion": "success", "steps": [{"name": None, "conclusion": "success"}]}],
        [{"id": 1, "name": "run", "conclusion": "success", "steps": [{"name": "", "conclusion": "success"}]}],
        [{"id": 1, "name": "run", "conclusion": "success", "steps": None}],
        [{"id": 1, "name": "run", "conclusion": "success", "steps": {}}],
        [None],
    ],
    ids=["no name", "blank name", "no steps list", "steps mapping", "null job"],
)
def test_a_malformed_job_record_is_unreadable_rather_than_productive(real, jobs):
    with pytest.raises(job.CHECK_ERRORS):
        job.is_counted(gh_run(11, "2026-11-24T00:08:00Z"), real["calculate-rankings.yml"], {11: jobs})


def test_a_provider_count_that_is_not_a_count_is_unreadable():
    windows = {"demosphere": {"last_week": 0, "week_before": 0, "baseline_4_weeks": True}}
    expected = {"demosphere": [synthetic(["23 5 * * 1"], name="Demosphere Scraper")]}

    with pytest.raises(TypeError):
        job.quiet_findings(expected, windows, NOW)


# --------------------------------------------------------------------------- #
# Cadence
# --------------------------------------------------------------------------- #

WORK = jobs_payload(("Do the work", "success"))["jobs"]
SKIPPED_WORK = jobs_payload(("Checkout repository", "success"), ("Do the work", "skipped"))["jobs"]
CREATED = at("2026-10-01 00:00")


def jobs_ending(conclusion):
    """A run's jobs: one that did the work when the run succeeded, else one ending as the run did."""
    if conclusion == "success":
        return WORK
    return jobs_payload(("Do the work", conclusion), conclusion=conclusion)["jobs"]


def evaluate(wf, runs, now, *, created=CREATED, cache=None, links=()):
    if cache is None:
        cache = {r["id"]: jobs_ending(r["conclusion"]) for r in [*runs, *links]}
    return job.evaluate_workflow(wf, created, runs, list(links), now, cache)


def problems(findings):
    return [f for f in findings[0] if f.kind == "problem"]


WEEKLY = synthetic(["0 6 * * 1"], name="Weekly job")


def test_a_run_twelve_hours_late_satisfies_its_due_time():
    findings = evaluate(WEEKLY, [gh_run(1, "2026-11-23T18:00:00Z")], at("2026-11-25 12:00"))

    assert problems(findings) == []
    assert findings[1] == 1


def test_no_counted_run_a_day_after_the_due_time_is_flagged_with_the_last_counted_run():
    runs = [gh_run(1, "2026-11-16T13:00:00Z")]

    (line,) = problems(evaluate(WEEKLY, runs, at("2026-11-24 07:00")))

    assert line.text == (
        "Weekly job: no counted run since the one due 2026-11-22; last counted run 2026-11-16"
    )
    assert line.date_label == "due 2026-11-22"


def test_a_missing_friday_run_is_flagged_on_saturday():
    wf = synthetic(["23 5 * * 2,5"], name="Twice weekly")
    runs = [gh_run(1, "2026-11-24T11:00:00Z")]

    assert len(problems(evaluate(wf, runs, at("2026-11-28 06:00")))) == 1
    assert problems(evaluate(wf, runs, at("2026-11-26 12:00"))) == []


def test_a_frequent_series_is_never_flagged_on_timing():
    findings, on_time = evaluate(synthetic(["0 */6 * * *"], name="Six-hourly"), [], NOW)

    assert [f.kind for f in findings] == ["ok"]
    assert on_time == 0


def test_a_new_workflow_is_not_flagged_before_its_first_slot_has_had_its_grace():
    created = at("2026-11-23 10:00")

    awaiting, on_time = evaluate(WEEKLY, [], at("2026-11-24 05:00"), created=created)
    assert [f.kind for f in awaiting] == ["awaiting"] and on_time == 0
    assert [f.kind for f in evaluate(WEEKLY, [], at("2026-12-01 05:59"), created=created)[0]] == ["awaiting"]
    assert len(problems(evaluate(WEEKLY, [], at("2026-12-01 06:00"), created=created))) == 1


def test_a_daylight_saving_pair_waits_twenty_five_hours():
    wf = synthetic(["30 6 * * 1", "30 7 * * 1"], name="Pair")
    created = at("2026-11-18 00:00")

    assert problems(evaluate(wf, [], at("2026-11-24 07:00"), created=created)) == []
    assert len(problems(evaluate(wf, [], at("2026-11-24 08:00"), created=created))) == 1


def test_a_cancelled_run_gets_the_failure_text_not_skipped_its_work():
    (line,) = problems(evaluate(WEEKLY, [gh_run(1, "2026-11-23T13:00:00Z", "cancelled")], NOW))

    assert line.text.startswith("Weekly job: the scheduled run started 2026-11-23 ended cancelled; no counted run")
    assert "skipped its work" not in line.text
    assert line.link == "https://github.com/example/PitchRank/actions/runs/1"


def test_a_green_run_that_skipped_its_work_says_so():
    runs = [gh_run(1, "2026-11-23T13:00:00Z")]

    (line,) = problems(evaluate(WEEKLY, runs, NOW, cache={1: SKIPPED_WORK}))

    assert line.text.endswith("; ran on 2026-11-23 but skipped its work")


def test_a_run_whose_only_job_was_switched_off_says_it_skipped_its_work():
    (line,) = problems(evaluate(WEEKLY, [gh_run(1, "2026-11-23T13:00:00Z", "skipped")], NOW))

    assert line.text.endswith("; ran on 2026-11-23 but skipped its work")


def test_frequent_counts_start_at_the_workflow_creation():
    (series,) = job.build_series(("7,22,37,52 * * * *",))
    runs = [gh_run(1, "2026-11-25T10:07:00Z"), gh_run(2, "2026-11-25T11:07:00Z", "cancelled")]

    fired, expected, succeeded = job.frequent_counts(series, runs, at("2026-11-24 10:30"), NOW)

    assert (fired, expected, succeeded) == (2, 114, 1)


def test_run_queries_encode_the_utc_date_and_the_bot_actor():
    since = datetime(2026, 11, 10, 22, 30, tzinfo=job.ARIZONA)

    assert parse_qs(job.runs_query("schedule", since)) == {
        "branch": ["main"],
        "event": ["schedule"],
        "created": [">=2026-11-11"],
    }
    assert parse_qs(job.runs_query("workflow_dispatch", since, bot=True))["actor"] == ["github-actions[bot]"]
    assert "%3E%3D2026-11-11" in job.runs_query("schedule", since)


# --------------------------------------------------------------------------- #
# Slot matching for a workflow with two series
# --------------------------------------------------------------------------- #

MONITOR_WORK = jobs_payload(("Capture current Compare and frozen SOS arms", "success"))["jobs"]


MONITOR_SKIPPED = jobs_payload(("Capture current Compare and frozen SOS arms", "skipped"))["jobs"]


def monitor(real, runs, now, created="2026-11-20 00:00", cache=None):
    cache = cache or {r["id"]: MONITOR_WORK for r in runs}
    return job.evaluate_workflow(real["compare-live-monitoring.yml"], at(created), runs, [], now, cache)[0]


def flagged_series(findings):
    return [f.text.split(":")[0] for f in findings if f.kind == "problem"]


@pytest.mark.parametrize("check", ["2026-11-24 15:00", "2026-11-24 18:00"], ids=["before review due", "after"])
def test_a_late_daily_run_and_the_monday_review_both_count(real, check):
    runs = [gh_run(1, "2026-11-23T18:17:00Z"), gh_run(2, "2026-11-24T03:25:00Z")]

    assert flagged_series(monitor(real, runs, at(check))) == []


def test_a_slot_filled_by_a_run_that_did_no_work_is_flagged(real):
    runs = [gh_run(1, "2026-11-23T18:17:00Z"), gh_run(2, "2026-11-24T03:25:00Z"), gh_run(3, "2026-11-24T14:00:00Z")]
    cache = {1: MONITOR_WORK, 2: MONITOR_WORK, 3: MONITOR_SKIPPED}

    (line,) = [f for f in monitor(real, runs, at("2026-11-25 12:00"), cache=cache) if f.kind == "problem"]

    assert line.text == (
        "Compare Live Monitoring (20 6 * * *): no counted run for the one due 2026-11-23; "
        "last counted run 2026-11-23; ran on 2026-11-24 but skipped its work"
    )


def test_a_missing_monday_review_is_flagged_once(real):
    runs = [gh_run(1, "2026-11-23T18:17:00Z"), gh_run(3, "2026-11-24T17:51:00Z")]

    assert flagged_series(monitor(real, runs, at("2026-11-25 18:00"))) == ["Compare Live Monitoring (30 17 * * 1)"]


def test_a_daily_slot_the_review_run_took_is_flagged(real):
    """Wednesday's run fills Wednesday's slot and did its work, so the line names the last counted
    run before the missed slot rather than one after it."""
    runs = [gh_run(1, "2026-11-23T18:17:00Z"), gh_run(2, "2026-11-24T17:00:00Z"), gh_run(3, "2026-11-25T10:00:00Z")]

    findings = monitor(real, runs, at("2026-11-25 12:00"))

    assert [f.text for f in findings if f.kind == "problem"] == [
        "Compare Live Monitoring (20 6 * * *): no counted run for the one due 2026-11-23; last counted run 2026-11-23"
    ]


def test_with_no_counted_run_before_a_missed_slot_the_line_does_not_deny_a_later_one(real):
    """Monday's run did no work and Wednesday's did, so nothing counted before Tuesday's slot,
    but the series did have a counted run in the window."""
    runs = [gh_run(1, "2026-11-23T18:00:00Z"), gh_run(2, "2026-11-24T17:00:00Z"), gh_run(3, "2026-11-25T10:00:00Z")]
    cache = {1: MONITOR_SKIPPED, 2: MONITOR_WORK, 3: MONITOR_WORK}

    findings = monitor(real, runs, at("2026-11-25 12:00"), created="2026-11-23 00:00", cache=cache)

    assert [f.text for f in findings if f.kind == "problem"] == [
        "Compare Live Monitoring (20 6 * * *): no counted run for the one due 2026-11-23; "
        "no earlier counted run in 15 days"
    ]


def test_the_first_run_of_the_window_finds_its_predecessor_slot(real):
    daily, review = real["compare-live-monitoring.yml"].series
    run = gh_run(2, "2026-11-24T03:25:00Z")

    created, since, now = at("2026-11-01 00:00"), at("2026-11-24 00:00"), at("2026-11-24 15:00")

    assignment = job.assign_runs([daily, review], [run], created, since, now)

    assert assignment.runs[daily] == [run]
    assert assignment.slots == {(daily, at("2026-11-23 06:20")): run}


def test_a_run_after_every_open_slot_falls_back_to_the_latest_due_series():
    monday, tuesday = job.build_series(("0 6 * * 1", "0 7 * * 2"))
    run = gh_run(1, "2026-11-26T12:00:00Z")

    assignment = job.assign_runs([monday, tuesday], [run], CREATED, at("2026-11-11 00:00"), at("2026-11-26 13:00"))

    assert assignment.runs == {monday: [], tuesday: [run]}
    assert assignment.slots == {}


# --------------------------------------------------------------------------- #
# Failures
# --------------------------------------------------------------------------- #


def test_a_failed_active_run_stays_flagged_past_the_inactive_green_run(real):
    inactive_jobs = fixture("jobs_inactive_guard.json")["jobs"]
    done = json.loads(json.dumps(inactive_jobs))
    done[0]["steps"][7]["conclusion"] = "success"
    failed = gh_run(1, "2026-11-23T12:30:00Z", "failure")
    inactive = gh_run(2, "2026-11-23T16:21:00Z")
    cache = {1: jobs_ending("failure"), 2: inactive_jobs, 3: done}
    wf = real["ut-scraper.yml"]

    (line,) = problems(job.evaluate_workflow(wf, CREATED, [failed, inactive], [], NOW, cache))
    assert line.text.startswith("Affinity UT Scraper: the scheduled run started 2026-11-23 ended failure")

    later = gh_run(3, "2026-11-23T18:38:00Z")
    assert problems(job.evaluate_workflow(wf, CREATED, [failed, inactive, later], [], NOW, cache)) == []


def test_a_frequent_series_flags_failure_but_not_cancelled():
    wf = synthetic(["0 */6 * * *"], name="Six-hourly")

    assert problems(evaluate(wf, [gh_run(1, "2026-11-25T06:10:00Z", "cancelled")], NOW)) == []
    (line,) = problems(evaluate(wf, [gh_run(1, "2026-11-25T06:10:00Z", "failure")], NOW))
    assert "ended failure" in line.text


def test_a_quarter_hour_workflow_is_read_for_its_last_week_only(world):
    """Fifteen days of a quarter-hour cron is 1,440 runs, past the ten pages the pager reads, so
    a healthy job would read as unreadable; its last week, 672 at most, fits."""
    write_workflow(world.root, "drain.yml", ["7,22,37,52 * * * *"], WORK_STEPS, name="Drain")
    world.gh.routes[INVENTORY] = inventory(state_row("weekly.yml"), state_row("drain.yml"))
    week = [
        gh_run(300 + i, f"2026-11-{18 + i // 96:02d}T{i % 96 // 4:02d}:{7 + i % 4 * 15:02d}:00Z") for i in range(672)
    ]
    for page in range(1, 8):
        world.gh.routes[runs_path("drain.yml", "schedule", "2026-11-18", page=page)] = runs_page(
            *week[(page - 1) * 100 : page * 100], total=672
        )

    findings = job.collect(NOW)

    assert runs_path("drain.yml", "schedule", "2026-11-18") in world.gh.calls
    assert incomplete_lines(findings) == []
    assert any(f.text.startswith("Drain: fired") for f in findings)


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out"])
def test_the_newest_failed_chain_link_is_flagged_until_a_later_link_does_its_work(conclusion):
    wf = synthetic(["30 6 * * 1"], name="Chain", chain=True)
    seed = gh_run(1, "2026-11-23T13:00:00Z")
    failed = gh_run(2, "2026-11-23T15:00:00Z", conclusion, event="workflow_dispatch")

    (line,) = problems(evaluate(wf, [seed], NOW, links=[failed]))
    assert line.text == f"Chain (chained runs): the chained run started 2026-11-23 ended {conclusion}"

    later = gh_run(3, "2026-11-23T17:00:00Z", event="workflow_dispatch")
    assert problems(evaluate(wf, [seed], NOW, links=[failed, later])) == []


def test_a_switched_off_scheduled_workflow_has_no_finding_and_is_listed(world):
    write_workflow(world.root, "off.yml", ["0 6 * * 1"], WORK_STEPS)
    world.gh.routes[INVENTORY] = inventory(state_row("weekly.yml"), state_row("off.yml", "disabled_manually"))

    findings = job.collect(NOW)

    assert [f.text for f in findings if f.kind == "problem"] == []
    assert "Switched off in GitHub: off.yml" in [f.text for f in findings]
    assert not any(c.startswith("workflows/off.yml") for c in world.gh.calls)


def test_a_switched_off_workflow_with_no_schedule_is_listed(world):
    world.gh.routes[INVENTORY] = inventory(state_row("weekly.yml"), state_row("manual.yml", "disabled_manually"))

    assert "Switched off in GitHub: manual.yml" in [f.text for f in job.collect(NOW)]


def test_a_workflow_state_that_is_not_text_is_unreadable_rather_than_switched_off(world):
    world.gh.routes[INVENTORY] = inventory({**state_row("weekly.yml"), "state": None})

    findings = job.collect(NOW)

    assert incomplete_lines(findings) == [
        "Check incomplete: GitHub's workflow list could not be read, so the schedule and import checks did not "
        "run (checked 2026-11-25)"
    ]


IMPORT_STEPS = [{"name": "Import", "run": "python scripts/import_games_enhanced.py f.csv tgs"}]
OFF_IMPORT_STEPS = [{"name": "Import", "run": "python scripts/import_games_enhanced.py f.csv affinity_wa"}]


def importing_world(world):
    """An active TGS importer whose last run failed, and a switched-off WA importer, with TGS's
    and WA's imports late and both of them gone quiet."""
    write_workflow(world.root, "tgs.yml", ["30 6 * * 1"], IMPORT_STEPS, name="TGS import")
    write_workflow(world.root, "wa.yml", ["0 6 * * 1"], OFF_IMPORT_STEPS, name="WA import")
    world.gh.routes[INVENTORY] = inventory(
        state_row("weekly.yml"), state_row("tgs.yml"), state_row("wa.yml", "disabled_manually")
    )
    world.gh.routes[runs_path("tgs.yml", "schedule", SINCE_DATE)] = runs_page(
        gh_run(201, "2026-11-23T13:00:00Z", "failure")
    )
    world.gh.routes[jobs_path(201)] = jobs_payload(("Import", "failure"), conclusion="failure")
    world.post.answers[job.BUILD_HEARTBEAT_QUERY] = row(
        heartbeats=[
            {"code": "tgs", "last_logged": "2026-11-18T20:57:37.5+00:00"},
            {"code": "affinity_wa", "last_logged": "2026-11-16T18:52:48+00:00"},
        ]
    )
    world.post.answers[job.GAME_WINDOWS_QUERY] = row(
        game_windows=[
            {"code": "affinity_wa", "last_week": 4, "week_before": 4, "baseline_4_weeks": 400},
            {"code": "tgs", "last_week": 4, "week_before": 4, "baseline_4_weeks": 400},
        ]
    )


def test_the_import_checks_read_the_importing_workflows_and_skip_switched_off_ones(world):
    importing_world(world)

    findings = job.collect(NOW)

    assert [(f.check, f.text) for f in findings if f.check in ("imports", "quiet")] == [
        (
            "imports",
            "tgs (TGS import): no import logged and no run did its work since it was due; "
            "last import logged 2026-11-18",
        ),
        (
            "quiet",
            "tgs (TGS import): 4 new games in the last 7 days and 4 the week before, against a usual "
            "100 a week, in the two weeks to 2026-11-25",
        ),
    ]
    assert incomplete_lines(findings) == []


def test_a_present_provider_row_missing_a_count_is_incomplete(world):
    importing_world(world)
    world.post.answers[job.GAME_WINDOWS_QUERY] = row(game_windows=[{"code": "tgs", "last_week": 4, "week_before": 4}])

    findings = job.collect(NOW)

    assert "Check incomplete: the new-game counts could not be read (checked 2026-11-25)" in incomplete_lines(findings)
    assert not [f for f in findings if f.check == "quiet"]


def test_a_game_windows_value_that_is_not_a_list_is_incomplete(world):
    world.post.answers[job.GAME_WINDOWS_QUERY] = row(game_windows={})

    assert incomplete_lines(job.collect(NOW)) == [
        "Check incomplete: the new-game counts could not be read (checked 2026-11-25)"
    ]


def queue_row(**overrides):
    values = dict(
        stuck_processing=0,
        oldest_stuck_claimed="2026-10-05 21:33:19+00",
        oldest_pending_requested="2026-11-25 14:30:00+00",
        completed_recently=True,
    )
    return row(**{**values, **overrides})


def publication_row(**overrides):
    return [{**healthy_answers()[job.PUBLICATION_SQL][0], **overrides}]


SHORT_PUBLICATION = dict(row_count=90000, previous_snapshot_rows=150000, complete=False)


@pytest.mark.parametrize(
    "query, answer, what",
    [
        (
            job.GAME_WINDOWS_QUERY,
            row(game_windows=[{"code": None, "last_week": 0, "week_before": 0, "baseline_4_weeks": 0}]),
            "the new-game counts",
        ),
        (
            job.BUILD_HEARTBEAT_QUERY,
            row(heartbeats=[{"code": "", "last_logged": "2026-11-23T09:00:00+00:00"}]),
            "the import log",
        ),
        (job.BUILD_HEARTBEAT_QUERY, row(heartbeats={}), "the import log"),
        (job.SCRAPE_QUEUE_QUERY, queue_row(stuck_processing=True), "the scrape queue"),
        (job.SCRAPE_QUEUE_QUERY, queue_row(stuck_processing=-1), "the scrape queue"),
        (job.SCRAPE_QUEUE_QUERY, queue_row(stuck_processing=1.5), "the scrape queue"),
        (job.SCRAPE_QUEUE_QUERY, queue_row(completed_recently="true"), "the scrape queue"),
        (job.PUBLICATION_SQL, publication_row(row_count=True), "the rankings publication"),
        (job.PUBLICATION_SQL, publication_row(stale_rows=True), "the rankings publication"),
        (job.PUBLICATION_SQL, publication_row(previous_snapshot_rows=False), "the rankings publication"),
        (job.PUBLICATION_SQL, publication_row(complete="true"), "the rankings publication"),
        (
            job.PUBLICATION_SQL,
            publication_row(**SHORT_PUBLICATION, previous_snapshot_date=None),
            "the rankings publication",
        ),
    ],
    ids=[
        "blank provider code",
        "blank heartbeat code",
        "heartbeats mapping",
        "boolean stuck count",
        "negative stuck count",
        "fractional stuck count",
        "text progress flag",
        "boolean row count",
        "boolean stale rows",
        "boolean snapshot rows",
        "text complete flag",
        "no snapshot date",
    ],
)
def test_a_malformed_database_value_is_incomplete(world, query, answer, what):
    world.post.answers[query] = answer

    assert incomplete_lines(job.collect(NOW)) == [f"Check incomplete: {what} could not be read (checked 2026-11-25)"]


def test_an_unreadable_run_history_keeps_the_other_providers_lines(world):
    """The TGS workflow's history is read; the YSSL one fails, and with it every later GitHub read.
    The late YSSL provider is incomplete on its own line, the TGS line still shows, and no
    "N daily-or-weekly schedules on time" line appears."""
    importing_world(world)
    yssl_step = {"name": "Run", "run": "python scripts/import_games_enhanced.py f.csv yssl"}
    write_workflow(world.root, "z-yssl.yml", ["15 8 * * 1"], [yssl_step])
    world.gh.routes[INVENTORY] = inventory(
        state_row("weekly.yml"),
        state_row("tgs.yml"),
        state_row("wa.yml", "disabled_manually"),
        state_row("z-yssl.yml"),
    )
    world.gh.fail = lambda path, calls: path.startswith("workflows/z-yssl.yml")

    findings = job.collect(NOW)

    assert incomplete_lines(findings) == [
        "Check incomplete: the run history of z-yssl.yml could not be read (checked 2026-11-25)",
        "Check incomplete: the yssl import check could not be read (checked 2026-11-25)",
    ]
    assert any(f.text.startswith("tgs (TGS import): no import logged") for f in findings)
    assert not any(f.check == "schedules" and f.text.endswith("on time") for f in findings)


def test_an_unreadable_workflow_list_still_checks_the_rankings_and_the_queue(world, caplog):
    world.gh.fail = lambda path, calls: path == INVENTORY

    assert run_main(caplog=caplog) == 1
    assert world.gh.calls == [INVENTORY] * 3
    body = world.post.calls["api.resend.com"][0]["html"]
    assert html.escape("Check incomplete: GitHub's workflow list could not be read") in body
    assert world.post.calls["api.supabase.com"] == [200, 200]


def test_an_empty_run_list_is_read_again_before_a_run_is_called_missed(world):
    first = runs_path("weekly.yml", "schedule", SINCE_DATE)
    world.gh.then(first, runs_page(), world.gh.routes[first])

    findings = job.collect(NOW)

    assert [f for f in findings if f.kind == "problem"] == []
    assert world.gh.calls.count(first) == 2


def test_a_failure_the_first_read_saw_survives_a_stale_second_read(world):
    first = runs_path("weekly.yml", "schedule", SINCE_DATE)
    failed = gh_run(102, "2026-11-23T20:00:00Z", "failure")
    world.gh.routes[jobs_path(102)] = jobs_payload(("Do the work", "failure"), conclusion="failure")
    stale = world.gh.routes[first]
    world.gh.then(first, runs_page(failed, *stale["workflow_runs"]), stale)

    problems_found = [f.text for f in job.collect(NOW) if f.kind == "problem"]

    assert problems_found == ["Weekly job: the scheduled run started 2026-11-23 ended failure"]
    assert world.gh.calls.count(first) == 2


def test_the_import_check_reads_the_runs_the_second_read_found(world):
    """The first read comes back empty; the second holds a counted run, so the late import log
    is a quiet week, not a missed import."""
    import_step = {"name": "Import", "run": "python scripts/import_games_enhanced.py f.csv yssl"}
    write_workflow(world.root, "yssl.yml", ["15 8 * * 1"], [import_step], name="YSSL")
    world.gh.routes[INVENTORY] = inventory(state_row("weekly.yml"), state_row("yssl.yml"))
    yssl_runs = runs_path("yssl.yml", "schedule", SINCE_DATE)
    world.gh.then(yssl_runs, runs_page(), runs_page(gh_run(301, "2026-11-23T15:00:00Z")))
    world.gh.routes[jobs_path(301)] = jobs_payload(("Import", "success"))
    logged = {"code": "yssl", "last_logged": "2026-11-18T15:56:47+00:00"}
    world.post.answers[job.BUILD_HEARTBEAT_QUERY] = row(heartbeats=[logged])

    findings = job.collect(NOW)

    assert [f.text for f in findings if f.kind == "problem"] == []


def test_the_import_check_keeps_a_run_only_the_first_read_saw(world):
    """The first read holds a counted run and a later failure, so the workflow is read again; the
    stale second read is empty. The import check must still see the counted run."""
    import_step = {"name": "Import", "run": "python scripts/import_games_enhanced.py f.csv yssl"}
    write_workflow(world.root, "yssl.yml", ["15 8 * * 1"], [import_step], name="YSSL")
    world.gh.routes[INVENTORY] = inventory(state_row("weekly.yml"), state_row("yssl.yml"))
    yssl_runs = runs_path("yssl.yml", "schedule", SINCE_DATE)
    first = runs_page(gh_run(302, "2026-11-23T20:00:00Z", "failure"), gh_run(301, "2026-11-23T15:00:00Z"))
    world.gh.then(yssl_runs, first, runs_page())
    world.gh.routes[jobs_path(301)] = jobs_payload(("Import", "success"))
    world.gh.routes[jobs_path(302)] = jobs_payload(("Import", "failure"), conclusion="failure")
    logged = {"code": "yssl", "last_logged": "2026-11-18T15:56:47+00:00"}
    world.post.answers[job.BUILD_HEARTBEAT_QUERY] = row(heartbeats=[logged])

    findings = job.collect(NOW)

    assert [f.check for f in findings if f.kind == "problem"] == ["schedules"]
    assert world.gh.calls.count(yssl_runs) == 2


def add_chain(world, scheduled_run, scheduled_jobs):
    """A chain workflow beside the weekly one, with one scheduled run; returns its bot-link path."""
    chain_steps = [{"name": "Do the work", "run": "echo work"}, {"name": "Next", "run": "gh workflow run chain.yml"}]
    write_workflow(world.root, "chain.yml", ["30 6 * * 1"], chain_steps, name="Chain")
    world.gh.routes[INVENTORY] = inventory(state_row("weekly.yml"), state_row("chain.yml"))
    world.gh.routes[runs_path("chain.yml", "schedule", SINCE_DATE)] = runs_page(scheduled_run)
    world.gh.routes[jobs_path(scheduled_run["id"])] = scheduled_jobs
    return runs_path("chain.yml", "workflow_dispatch", SINCE_DATE, bot=True)


def test_a_chain_link_the_second_read_found_is_judged(world):
    """The scheduled run failed, so the first read reports a problem and the links are read again;
    the first link list is empty and the second holds a cancelled link. The scheduled run's own
    line is also a problem, hence `in`."""
    failed_jobs = jobs_payload(("Do the work", "failure"), conclusion="failure")
    links = add_chain(world, gh_run(401, "2026-11-23T13:00:00Z", "failure"), failed_jobs)
    cancelled = gh_run(402, "2026-11-23T15:00:00Z", "cancelled", event="workflow_dispatch")
    world.gh.then(links, runs_page(), runs_page(cancelled))
    world.gh.routes[jobs_path(402)] = jobs_payload(("Do the work", "cancelled"), conclusion="cancelled")

    texts = [f.text for f in job.collect(NOW) if f.kind == "problem"]

    assert "Chain (chained runs): the chained run started 2026-11-23 ended cancelled" in texts


def test_a_failed_chain_link_the_first_read_saw_survives_a_stale_second_read(world):
    links = add_chain(world, gh_run(501, "2026-11-23T13:00:00Z"), DID_WORK)
    failed = gh_run(502, "2026-11-23T15:00:00Z", "failure", event="workflow_dispatch")
    world.gh.then(links, runs_page(failed), runs_page())
    world.gh.routes[jobs_path(502)] = jobs_payload(("Do the work", "failure"), conclusion="failure")

    texts = [f.text for f in job.collect(NOW) if f.kind == "problem"]

    assert texts == ["Chain (chained runs): the chained run started 2026-11-23 ended failure"]
    assert world.gh.calls.count(links) == 2


def test_a_stale_unfinished_copy_cannot_reopen_a_failed_chain_link(world):
    """The second read carries an older copy of the same attempt, still in progress."""
    links = add_chain(world, gh_run(501, "2026-11-23T13:00:00Z"), DID_WORK)
    failed = {**gh_run(502, "2026-11-23T15:00:00Z", "failure", event="workflow_dispatch"), "run_attempt": 1}
    stale = {**failed, "status": "in_progress", "conclusion": None}
    world.gh.then(links, runs_page(failed), runs_page(stale))
    world.gh.routes[jobs_path(502)] = jobs_payload(("Do the work", "failure"), conclusion="failure")

    texts = [f.text for f in job.collect(NOW) if f.kind == "problem"]

    assert texts == ["Chain (chained runs): the chained run started 2026-11-23 ended failure"]


def test_a_rerun_copy_replaces_the_finished_attempt():
    finished = {**gh_run(1, "2026-11-23T15:00:00Z", "failure"), "run_attempt": 1}
    rerun = {**finished, "status": "in_progress", "conclusion": None, "run_attempt": 2}
    seen = {}

    job._merge(seen, [finished])
    job._merge(seen, [rerun])

    assert seen == {1: rerun}


def test_a_second_read_that_fails_leaves_its_workflow_incomplete(world, caplog):
    first = runs_path("weekly.yml", "schedule", SINCE_DATE)
    world.gh.routes[first] = runs_page(gh_run(103, "2026-11-23T20:00:00Z", "failure"))
    world.gh.routes[jobs_path(103)] = jobs_payload(("Do the work", "failure"), conclusion="failure")
    world.gh.fail = lambda path, calls: path == first and calls.count(first) > 1

    assert run_main(caplog=caplog) == 1
    body = world.post.calls["api.resend.com"][0]["html"]
    assert "Check incomplete: the run history of Weekly job could not be read" in body
    assert "ended failure" not in body


def test_ten_full_pages_of_runs_are_unreadable_rather_than_truncated(monkeypatch):
    page = "workflows/w.yml/runs?q=1&per_page=100&page={}".format
    routes = {
        page(n): runs_page(*(gh_run(n * 1000 + i, "2026-11-20T00:00:00Z") for i in range(100)), total=1000)
        for n in range(1, 11)
    }
    monkeypatch.setattr(job.subprocess, "run", FakeGh(routes))

    with pytest.raises(job.SourceUnreadable):
        job.list_runs("w.yml", "q=1")


@pytest.mark.parametrize(
    "payload",
    [
        {"total_count": False, "workflow_runs": []},
        {"total_count": 0, "workflow_runs": {}},
        {"total_count": 1, "workflow_runs": [{**gh_run(1, "2026-11-23T13:00:00Z"), "id": None}]},
    ],
    ids=["boolean total", "mapping of runs", "null id"],
)
def test_a_malformed_page_is_unreadable_rather_than_empty(monkeypatch, payload):
    monkeypatch.setattr(job.subprocess, "run", FakeGh({"workflows/w.yml/runs?q=1&per_page=100&page=1": payload}))

    with pytest.raises(job.CHECK_ERRORS):
        job.list_runs("w.yml", "q=1")


@pytest.mark.parametrize("state", ["", "  "], ids=["empty", "blank"])
def test_a_blank_workflow_state_is_unreadable_rather_than_switched_off(world, state):
    world.gh.routes[INVENTORY] = inventory({**state_row("weekly.yml"), "state": state})

    assert incomplete_lines(job.collect(NOW)) == [
        "Check incomplete: GitHub's workflow list could not be read, so the schedule and import checks did not "
        "run (checked 2026-11-25)"
    ]


def test_a_run_list_shorter_than_its_total_is_unreadable(world):
    first = runs_path("weekly.yml", "schedule", SINCE_DATE)
    world.gh.routes[first] = runs_page(gh_run(101, "2026-11-23T13:00:00Z"), total=2)

    assert incomplete_lines(job.collect(NOW)) == [
        "Check incomplete: the run history of Weekly job could not be read (checked 2026-11-25)"
    ]


def test_a_second_page_of_runs_is_read_and_a_repeated_record_kept_once(monkeypatch):
    full = [gh_run(1000 + n, f"2026-11-{24 - n // 50:02d}T{n % 24:02d}:00:00Z") for n in range(100)]
    repeated = full[-1]
    page = "workflows/w.yml/runs?q=1&per_page=100&page={}".format
    gh = FakeGh(
        {
            page(1): runs_page(*full, total=101),
            page(2): runs_page(repeated, gh_run(2000, "2026-11-10T01:00:00Z"), total=102),
        }
    )
    monkeypatch.setattr(job.subprocess, "run", gh)

    runs = job.list_runs("w.yml", "q=1")

    assert sorted(r["id"] for r in runs) == [*range(1000, 1100), 2000]
    assert gh.calls == [page(1), page(2)]


def test_a_jobs_list_that_ends_before_its_total_is_unreadable(monkeypatch):
    one_of_two = {**jobs_payload(("Do the work", "success")), "total_count": 2}
    gh = FakeGh({jobs_path(5): one_of_two})
    monkeypatch.setattr(job.subprocess, "run", gh)

    with pytest.raises(job.SourceUnreadable):
        job.run_jobs(5, {})


@pytest.mark.parametrize("state, incomplete", [("disabled_manually", 0), ("active", 1)])
def test_an_unreadable_cron_counts_only_while_its_workflow_is_on(world, state, incomplete):
    write_workflow(world.root, "monday.yml", ["0 6 * * MON"], WORK_STEPS)
    world.gh.routes[INVENTORY] = inventory(state_row("weekly.yml"), state_row("monday.yml", state))

    findings = job.collect(NOW)

    line = "Check incomplete: monday.yml has a cron this check cannot read (checked 2026-11-25)"
    assert incomplete_lines(findings) == [line][:incomplete]
    assert ("Switched off in GitHub: monday.yml" in [f.text for f in findings]) is (state != "active")


def test_a_scheduled_file_github_does_not_list_is_incomplete(world):
    write_workflow(world.root, "unlisted.yml", ["0 6 * * 1"], WORK_STEPS)

    assert incomplete_lines(job.collect(NOW)) == [
        "Check incomplete: unlisted.yml is not in GitHub's workflow list (checked 2026-11-25)"
    ]


# --------------------------------------------------------------------------- #
# Data rules
# --------------------------------------------------------------------------- #

START = "2026-11-23 12:30:00+00"


def publication(**overrides):
    values = dict(
        read_only="on",
        ranking_start=START,
        row_count=150056,
        stale_rows=0,
        newest_calculated="2026-11-24 03:56:00+00",
        previous_snapshot_date="2026-11-19",
        previous_snapshot_rows=150562,
        complete=True,
    )
    return {**values, **overrides}


LATE = at("2026-11-23 12:30") + timedelta(hours=31)

RANKING_PROBLEMS = {
    "empty": publication(row_count=0, stale_rows=0, newest_calculated=None, complete=False),
    "no refresh time": publication(stale_rows=150056, newest_calculated=None, complete=False),
    "stale": publication(stale_rows=3, complete=False),
    "no snapshot": publication(previous_snapshot_date=None, previous_snapshot_rows=None, complete=False),
    "short": publication(row_count=90000, previous_snapshot_rows=150000, complete=False),
}


def test_a_complete_publication_passes_and_an_early_one_is_awaiting():
    assert job.rankings_finding(publication(), LATE).kind == "ok"
    unrefreshed = publication(complete=False, stale_rows=150056)
    assert job.rankings_finding(unrefreshed, at("2026-11-23 12:30") + timedelta(hours=29)).kind == "awaiting"


def test_each_incomplete_publication_names_its_own_cause():
    texts = {case: job.rankings_finding(r, LATE).text for case, r in RANKING_PROBLEMS.items()}

    assert texts == {
        "empty": "Rankings: the published table is empty; expected from the run starting 2026-11-23",
        "no refresh time": "Rankings: no row has a refresh time; expected from the run starting 2026-11-23",
        "stale": "Rankings: 3 of 150,056 rows were not refreshed by the run starting 2026-11-23 (newest refresh "
        "2026-11-23): this week's run did not refresh every row, or teams it removed were not cleaned up",
        "no snapshot": "Rankings: no ranking snapshot before the run starting 2026-11-23 to compare with",
        "short": "Rankings: 90,000 rows published, under 95% of the 150,000 in the snapshot of 2026-11-19",
    }
    assert {job.rankings_finding(r, LATE).kind for r in RANKING_PROBLEMS.values()} == {"problem"}


YSSL = synthetic(["15 8 * * 1"], name="YSSL Scraper", file="yssl-scraper.yml")
YSSL_STATES = {"yssl-scraper.yml": job.WorkflowState("active", CREATED)}


def heartbeat(logged, runs, cache):
    expected = {"yssl": [YSSL]}
    beats = {"yssl": at(logged)} if logged else {}
    return job.heartbeat_findings(expected, beats, YSSL_STATES, {"yssl-scraper.yml": runs}, cache, NOW)


def test_an_import_logged_since_it_was_due_clears():
    assert heartbeat("2026-11-23 09:00", [], {}) == []


def test_a_counted_run_with_nothing_to_import_clears():
    run = gh_run(1, "2026-11-23T15:00:00Z")

    assert heartbeat("2026-11-18 15:56", [run], {1: jobs_payload(("Scrape YSSL", "success"))["jobs"]}) == []


def test_no_import_and_no_counted_run_since_it_was_due_flags():
    run = gh_run(1, "2026-11-23T15:00:00Z", "failure")

    (line,) = heartbeat("2026-11-18 15:56", [run], {1: jobs_ending("failure")})

    assert line.text == (
        "yssl (YSSL Scraper): no import logged and no run did its work since it was due; last import logged 2026-11-18"
    )


def quiet(last, before, baseline):
    windows = {"demosphere": {"last_week": last, "week_before": before, "baseline_4_weeks": baseline}}
    return job.quiet_findings({"demosphere": [synthetic(["23 5 * * 1"], name="Demosphere Scraper")]}, windows, NOW)


@pytest.mark.parametrize(
    "last, before, baseline, flagged",
    [(4, 4, 200, True), (5, 4, 200, False), (4, 5, 200, False), (4, 4, 196, False)],
)
def test_the_quiet_rule_needs_a_busy_baseline_and_two_quiet_weeks(last, before, baseline, flagged):
    assert bool(quiet(last, before, baseline)) is flagged


def queue(**overrides):
    values = dict(
        stuck_processing=0, oldest_stuck_claimed=None, oldest_pending_requested=None, completed_recently=False
    )
    return job.queue_findings({**values, **overrides}, NOW)


def iso(moment):
    return moment.isoformat()


@pytest.mark.parametrize(
    "age, completed_recently, flagged",
    [
        (timedelta(hours=2, minutes=1), False, True),
        (timedelta(hours=2, minutes=1), True, False),
        (timedelta(hours=1, minutes=59), False, False),
    ],
)
def test_the_drainer_is_stalled_only_when_old_work_waits_and_nothing_completes(age, completed_recently, flagged):
    findings = queue(oldest_pending_requested=iso(NOW - age), completed_recently=completed_recently)

    assert bool(findings) is flagged


def test_a_stuck_processing_request_flags():
    (line,) = queue(stuck_processing=1, oldest_stuck_claimed="2026-10-05 21:33:19.465996+00", completed_recently=True)

    assert line.text == "1 scrape request stuck in processing for over 6 hours; oldest stuck request claimed 2026-10-05"


# --------------------------------------------------------------------------- #
# Unreadable sources make a check incomplete, never a pass
# --------------------------------------------------------------------------- #


def test_an_http_500_makes_only_its_check_incomplete(world, caplog):
    world.post.answers[job.SCRAPE_QUEUE_QUERY] = (500, {"message": "boom"})

    assert run_main(caplog=caplog) == 1
    assert len(world.post.calls["api.resend.com"]) == 1
    body = world.post.calls["api.resend.com"][0]["html"]
    assert "Check incomplete: the scrape queue could not be read" in body
    assert body.count("Check incomplete") == 1


@pytest.mark.parametrize(
    "answer",
    [
        row(stuck_processing=0, oldest_stuck_claimed=None, oldest_pending_requested=None),
        [{"read_only": "off", "stuck_processing": 0, "oldest_stuck_claimed": None,
          "oldest_pending_requested": None, "completed_recently": True}],
        requests.ConnectionError("reset"),
        (200, row(stuck_processing=0) * 2),
    ],
    ids=["missing column", "not read-only", "connection error", "two rows"],
)
def test_an_unusable_answer_makes_only_its_check_incomplete(world, caplog, answer):
    world.post.answers[job.SCRAPE_QUEUE_QUERY] = answer

    assert run_main(caplog=caplog) == 1
    assert len(world.post.calls["api.resend.com"]) == 1
    assert world.post.calls["api.resend.com"][0]["html"].count("Check incomplete") == 1
    assert messages(caplog) == ["checks 5, problems 0, incomplete 1, email accepted"]


def test_a_publication_that_is_not_read_only_is_incomplete(world, caplog):
    world.post.answers[job.PUBLICATION_SQL] = [{**healthy_answers()[job.PUBLICATION_SQL][0], "read_only": "off"}]

    assert run_main(caplog=caplog) == 1
    body = world.post.calls["api.resend.com"][0]["html"]
    assert "Check incomplete: the rankings publication could not be read" in body


def test_a_missing_access_token_makes_every_database_check_incomplete(world, caplog, monkeypatch):
    monkeypatch.delenv("SUPABASE_ACCESS_TOKEN")

    assert run_main(caplog=caplog) == 1
    assert world.post.calls["api.supabase.com"] == []
    assert len(world.post.calls["api.resend.com"]) == 1
    assert messages(caplog) == ["checks 5, problems 0, incomplete 4, email accepted, missing SUPABASE_ACCESS_TOKEN"]


def test_a_missing_mail_key_fails_even_a_quiet_day(world, caplog, monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY")

    assert run_main(caplog=caplog) == 1
    assert world.post.calls["api.resend.com"] == []
    assert messages(caplog) == ["checks 5, problems 0, incomplete 0, email not needed, missing RESEND_API_KEY"]


def test_one_github_outage_stops_every_later_github_read(world, caplog):
    write_workflow(world.root, "second.yml", ["0 7 * * 1"], WORK_STEPS)
    world.gh.routes[INVENTORY] = inventory(state_row("weekly.yml"), state_row("second.yml"))
    world.gh.fail = lambda path, calls: path != INVENTORY

    assert run_main(caplog=caplog) == 1
    assert len(world.gh.calls) == 4
    body = world.post.calls["api.resend.com"][0]["html"]
    assert "Check incomplete: the run history of Weekly job could not be read" in body
    assert "Check incomplete: the run history of second.yml could not be read" in body


def test_one_failed_attempt_leaves_later_reads_enabled(world, caplog):
    first = runs_path("weekly.yml", "schedule", SINCE_DATE)
    world.gh.fail = lambda path, calls: path == first and calls.count(first) == 1

    assert run_main(caplog=caplog) == 0
    assert world.gh.calls.count(first) == 2
    assert messages(caplog) == ["checks 5, problems 0, incomplete 0, email not needed"]


def test_an_unreadable_cron_beside_a_valid_workflow(world, caplog):
    write_workflow(world.root, "monday.yml", ["0 6 * * MON"], WORK_STEPS)
    world.gh.routes[INVENTORY] = inventory(state_row("weekly.yml"), state_row("monday.yml"))

    assert run_main(caplog=caplog) == 1
    assert runs_path("weekly.yml", "schedule", SINCE_DATE) in world.gh.calls
    body = world.post.calls["api.resend.com"][0]["html"]
    assert "Check incomplete: monday.yml has a cron this check cannot read" in body


def test_a_missing_importer_script_is_incomplete_beside_a_valid_workflow(world, caplog):
    write_workflow(world.root, "gone.yml", ["0 6 * * 1"], [{"name": "Import", "run": "python scripts/import_gone.py"}])
    world.gh.routes[INVENTORY] = inventory(state_row("weekly.yml"), state_row("gone.yml"))

    assert run_main(caplog=caplog) == 1
    assert runs_path("weekly.yml", "schedule", SINCE_DATE) in world.gh.calls
    body = world.post.calls["api.resend.com"][0]["html"]
    assert body.count("Check incomplete") == 1
    assert "gone.yml has an importer script that could not be read" in body


def test_a_refused_email_fails_the_run(world, caplog, monkeypatch):
    make_problem(world)
    monkeypatch.setattr(job, "send_email", lambda to, subject, body: False)

    assert run_main(caplog=caplog) == 1
    assert messages(caplog) == ["checks 5, problems 1, incomplete 0, email refused"]


def test_a_quiet_day_sends_nothing(world, caplog):
    assert run_main(caplog=caplog) == 0
    assert world.post.calls["api.resend.com"] == []


def test_the_tuesday_run_always_sends_an_all_clear(world, caplog, monkeypatch):
    monkeypatch.setenv("WEEKLY", "true")

    assert run_main(caplog=caplog) == 0
    (email,) = world.post.calls["api.resend.com"]
    assert email["subject"] == "PitchRank weekly job check: all clear"
    assert email["to"] == ["pitchrankio@gmail.com"]


# --------------------------------------------------------------------------- #
# Public logs
# --------------------------------------------------------------------------- #


def test_a_dry_run_prints_the_email_and_sends_nothing(world, caplog, capsys, monkeypatch):
    make_problem(world)

    def refuse(*args):
        raise AssertionError("a dry run sent an email")

    monkeypatch.setattr(job, "send_email", refuse)

    assert run_main(["--dry-run"], caplog=caplog) == 0
    out = capsys.readouterr().out
    assert "PitchRank job check: 1 problem" in out
    assert "under 95% of the 150,000 in the snapshot of 2026-11-19" in out


def test_a_dry_run_with_an_incomplete_check_exits_1(world, caplog, capsys):
    world.post.answers[job.SCRAPE_QUEUE_QUERY] = (500, {"message": "boom"})

    assert run_main(["--dry-run"], caplog=caplog) == 1
    assert "Check incomplete: the scrape queue could not be read" in capsys.readouterr().out


def test_a_dry_run_is_refused_on_actions(world, caplog, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    assert run_main(["--dry-run"], caplog=caplog) == 2
    assert world.gh.calls == [] and world.post.calls["api.supabase.com"] == []


def test_a_healthy_live_run_logs_only_its_count_line(world, caplog, capsys):
    assert run_main(caplog=caplog) == 0
    assert capsys.readouterr().out == ""
    assert messages(caplog) == ["checks 5, problems 0, incomplete 0, email not needed"]


def test_a_refused_email_on_actions_never_logs_the_response_body(world, caplog, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    world.post.resend_status = 422
    world.post.resend_body = b'{"message": "BODY-MARKER"}'

    assert run_main(["--weekly"], caplog=caplog) == 1
    assert world.post.calls["api.supabase.com"] == [200, 200, 200, 200]
    assert messages(caplog) == [
        "Resend answered 422: (body hidden on Actions)",
        "checks 5, problems 0, incomplete 0, email refused",
    ]
    assert "BODY-MARKER" not in caplog.text + capsys.readouterr().out


# --------------------------------------------------------------------------- #
# The email
# --------------------------------------------------------------------------- #


def problem_findings(real):
    """One problem line from each builder, built from fixtures through the builder itself."""
    built = [job.rankings_finding(r, LATE) for r in RANKING_PROBLEMS.values()]
    built += problems(evaluate(WEEKLY, [gh_run(1, "2026-11-23T13:00:00Z", "failure")], NOW))
    built += heartbeat("2026-11-18 15:56", [gh_run(1, "2026-11-23T15:00:00Z", "failure")], {1: jobs_ending("failure")})
    built += quiet(4, 4, 200)
    built += queue(
        stuck_processing=1,
        oldest_stuck_claimed="2026-10-05 21:33:19+00",
        oldest_pending_requested=iso(NOW - timedelta(hours=3)),
    )
    built.append(job.incomplete_finding("the scrape queue could not be read", NOW))
    return built


def test_every_problem_line_carries_a_labelled_date_and_a_link(real):
    findings = problem_findings(real)
    _, body = job.render_html(findings, False, NOW)

    assert len(findings) == 11
    for f in findings:
        assert DATED_LABEL.fullmatch(f.date_label), f
        assert f.date_label in f.text and html.escape(f.date_label) in body
        assert f.link.startswith("https://"), f
        assert f"href='{html.escape(f.link, quote=True)}'" in body
    assert findings[-1].link == f"https://github.com/{job.REPO}/actions/workflows/scheduled-jobs-check.yml"


def test_the_daily_email_lists_only_problems_and_the_weekly_one_everything():
    findings = [
        job.Finding("rankings", "Rankings: fine", kind="ok"),
        job.Finding("queue", "1 stuck; oldest stuck request claimed 2026-10-05", "claimed 2026-10-05", "https://x"),
    ]

    daily_subject, daily = job.render_html(findings, False, NOW)
    weekly_subject, weekly = job.render_html(findings, True, NOW)

    assert daily_subject == "PitchRank job check: 1 problem"
    assert "Rankings: fine" not in daily and "Rankings: fine" in weekly
    assert weekly_subject == "PitchRank weekly job check: 1 problem"


def test_settings_load_from_the_env_files(tmp_path, world, caplog, monkeypatch):
    monkeypatch.setattr(job, "load_dotenv", load_dotenv)
    for name in ("SUPABASE_URL", "ALERT_EMAIL"):
        # setenv records the variable's absence, so teardown also removes what load_dotenv writes;
        # delenv then makes it absent, because load_dotenv skips a key already present.
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    (world.root / ".env").write_text(f"SUPABASE_URL={PROJECT_URL}\nALERT_EMAIL=env@example.com\n", encoding="utf-8")
    (world.root / ".env.local").write_text("ALERT_EMAIL=local@example.com\n", encoding="utf-8")
    make_problem(world)

    assert run_main(caplog=caplog) == 0
    assert world.post.calls["api.supabase.com"] == [200, 200, 200, 200]
    assert [email["to"] for email in world.post.calls["api.resend.com"]] == [["local@example.com"]]


# --------------------------------------------------------------------------- #
# The workflow file
# --------------------------------------------------------------------------- #


def test_the_workflow_runs_the_check_with_read_only_permissions():
    doc = yaml.safe_load((WORKFLOWS / "scheduled-jobs-check.yml").read_text(encoding="utf-8"))
    triggers = doc.get("on", doc.get(True))
    (check,) = [s for s in doc["jobs"]["check"]["steps"] if s.get("name") == "Check scheduled jobs"]

    assert [entry["cron"] for entry in triggers["schedule"]] == ["41 6 * * *", "0 19 * * 2"]
    assert not (triggers["workflow_dispatch"] or {}).get("inputs")
    assert doc["permissions"] == {"contents": "read", "actions": "read"}
    assert check["run"].strip() == "python scripts/check_scheduled_jobs.py"
    assert check["env"]["WEEKLY"] == "${{ github.event.schedule == '0 19 * * 2' }}"
    assert {"GH_TOKEN", "SUPABASE_URL", "SUPABASE_ACCESS_TOKEN", "RESEND_API_KEY"} <= set(check["env"])
