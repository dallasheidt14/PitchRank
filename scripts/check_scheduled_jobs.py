#!/usr/bin/env python3
"""Check that each scheduled job did its work, and email the owner when one did not.

A scheduled job can fail without anyone noticing: GitHub skips and delays scheduled runs, an
import can end green having imported nothing, and the weekly ranking run can end cancelled at
the runner's time limit after saving its rankings. This reads what each job should have changed
and the GitHub run history, and emails ALERT_EMAIL only when something did not do its work:

  1. rankings: this week's publication refreshed every row, at least 95% as many as the last snapshot
  2. imports: every provider a scheduled workflow imports logged an import, or a scheduled run of
     its workflow did its work, since the import was due
  3. quiet imports: no busy provider brought almost nothing for two weeks running
  4. scrape queue: nothing is stuck in processing, and the drainer is still completing requests
  5. scheduled jobs: every daily-or-weekly schedule had a run that did its work, and no run
     failed since the last one that did

The schedules, and the providers each workflow imports, are read from the workflow files and the
importer scripts they run, so a new workflow is checked without editing this. A schedule shape it
cannot judge is reported as incomplete. Only scheduled runs on main count, plus the bot-dispatched
links on a chain's own chained-runs line: a manual run can be a dry run that would clear a real
failure with nothing imported.

Report only: it writes nothing. It keeps no state, so every date it reports is derived from the
data on each run. The Tuesday run (--weekly) always emails, so a silent week also shows the
checker is alive. A source that cannot be read is reported as "check incomplete", never as a
pass, and the run then exits 1, as it does when Resend refuses the email. Because Actions logs
are public, a live run logs one count line, plus the email helper's warning, body hidden, when
Resend refuses.

Database reads go through the Supabase Management API's read-only endpoint, with
SUPABASE_ACCESS_TOKEN; GitHub reads go through `gh api`.

Usage:
    python scripts/check_scheduled_jobs.py              # daily: email only when something is wrong
    python scripts/check_scheduled_jobs.py --weekly     # the Tuesday all-clear: always email
    python scripts/check_scheduled_jobs.py --dry-run    # print the email; send nothing
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.utils.resend_email import send_email  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DEFAULT_ALERT_EMAIL = "pitchrankio@gmail.com"
REPO = os.environ.get("GITHUB_REPOSITORY", "dallasheidt14/PitchRank")
CHECKER_WORKFLOW = "scheduled-jobs-check.yml"

# Arizona keeps standard time all year, and the owner reads the email in it.
ARIZONA = timezone(timedelta(hours=-7))
UTC = timezone.utc

RUN_HISTORY_DAYS = 15
MAX_RUN_PAGES = 10
GRACE = timedelta(hours=24)
# Runs of a daylight-saving pair count from the earlier hour, and the deadline allows the later.
DST_GRACE = timedelta(hours=25)
# Slots start this long before the run window, so a run early in the window still finds the slot
# it answers, due up to a week plus the grace before it.
SLOT_LEAD = timedelta(days=8)
FREQUENT_WINDOW = timedelta(days=7)

RANKINGS_DEADLINE = timedelta(hours=30)
QUIET_MIN_WEEKLY = 50
STUCK_HOURS = 6
PENDING_STALL = timedelta(hours=2)

FAILED = frozenset({"failure", "cancelled", "timed_out"})
# Frequent jobs end cancelled routinely.
FREQUENT_FAILED = frozenset({"failure"})

GITHUB_OWN_STEP_NAMES = frozenset({"Set up job", "Complete job", "Initialize containers", "Stop containers"})
SETUP_USES = ("actions/checkout", "actions/setup-", "actions/cache")
SETUP_COMMANDS = ("pip install", "pip3 install", "python -m pip install", "npm ci", "npm install", "mkdir")

CHECKS = ("rankings", "imports", "quiet", "queue", "schedules")
CHECK_TITLES = {
    "rankings": "Rankings",
    "imports": "Imports",
    "quiet": "Quiet imports",
    "queue": "Scrape queue",
    "schedules": "Scheduled jobs",
    "incomplete": "Checks that could not finish",
}
DATABASE_SETTINGS = ("SUPABASE_URL", "SUPABASE_ACCESS_TOKEN")

PUBLICATION_SQL = (ROOT / "scripts/sql/rankings_publication_complete.sql").read_text(encoding="utf-8")
PUBLICATION_COLUMNS = (
    "read_only",
    "ranking_start",
    "row_count",
    "stale_rows",
    "newest_calculated",
    "previous_snapshot_date",
    "previous_snapshot_rows",
    "complete",
)

# Dry runs log build rows too, so they are left out.
BUILD_HEARTBEAT_QUERY = f"""
SELECT current_setting('transaction_read_only') AS read_only,
       coalesce((SELECT jsonb_agg(jsonb_build_object('code', x.code, 'last_logged', x.last_logged)
                                  ORDER BY x.code) FROM (
           SELECT p.code, max(b.started_at) AS last_logged
           FROM public.build_logs b JOIN public.providers p ON p.id = b.provider_id
           WHERE b.started_at >= now() - interval '{RUN_HISTORY_DAYS} days'
             AND coalesce(b.parameters->>'dry_run', 'false') <> 'true'
           GROUP BY p.code
       ) x), '[]'::jsonb) AS heartbeats
"""

GAME_WINDOWS = ("last_week", "week_before", "baseline_4_weeks")
GAME_WINDOWS_QUERY = """
SELECT current_setting('transaction_read_only') AS read_only,
       coalesce((SELECT jsonb_agg(jsonb_build_object('code', x.code, 'last_week', x.last_week,
                                                     'week_before', x.week_before,
                                                     'baseline_4_weeks', x.baseline_4_weeks) ORDER BY x.code) FROM (
           SELECT p.code,
                  count(*) FILTER (WHERE g.created_at >= now() - interval '7 days') AS last_week,
                  count(*) FILTER (WHERE g.created_at >= now() - interval '14 days'
                                     AND g.created_at < now() - interval '7 days') AS week_before,
                  count(*) FILTER (WHERE g.created_at < now() - interval '14 days') AS baseline_4_weeks
           FROM public.games g JOIN public.providers p ON p.id = g.provider_id
           WHERE g.created_at >= now() - interval '42 days' AND g.created_at < now()
           GROUP BY p.code
       ) x), '[]'::jsonb) AS game_windows
"""

# A failed row also carries completed_at, so only completed rows count as progress.
SCRAPE_QUEUE_QUERY = f"""
SELECT current_setting('transaction_read_only') AS read_only,
       (SELECT count(*) FROM public.scrape_requests
         WHERE status = 'processing' AND processed_at < now() - interval '{STUCK_HOURS} hours') AS stuck_processing,
       (SELECT min(processed_at) FROM public.scrape_requests
         WHERE status = 'processing' AND processed_at < now() - interval '{STUCK_HOURS} hours') AS oldest_stuck_claimed,
       (SELECT min(requested_at) FROM public.scrape_requests WHERE status = 'pending') AS oldest_pending_requested,
       EXISTS (SELECT 1 FROM public.scrape_requests
                WHERE status = 'completed'
                  AND completed_at >= now() - interval '{STUCK_HOURS} hours') AS completed_recently
"""

ENHANCED_IMPORT = re.compile(r"scripts/import_games_enhanced\.py\s+(\"[^\"]*\"|'[^']*'|\S+)\s+([a-z0-9_]+)(?=\s|$)")
IMPORT_SCRIPT = re.compile(r"scripts/(import_[a-z0-9_]+)\.py")
DRAINER = re.compile(r"scripts/process_missing_games\.py")
PROVIDER_CODE = re.compile(r"^PROVIDER_CODE\s*(?::\s*str\s*)?=\s*[\"']([a-z0-9_]+)[\"']", re.M)
INVOCATION_SEPARATOR = re.compile(r"&&|\|\||;|\|")

FOOTER = (
    "This email only reports: it changes nothing. It comes when a scheduled job did not do its work, "
    "and every Tuesday as an all-clear. Dates are in Arizona time."
)


class SourceUnreadable(Exception):
    """The message names the source and at most an HTTP status, never a response body."""


class UnmappedImporter(Exception):
    """A workflow runs an importer whose provider code cannot be read from the step or the script."""


class UnmatchableSchedules(ValueError):
    """A workflow's schedules form a combination whose runs cannot be filed by start time (see `build_series`)."""


class NonUtcSchedule(ValueError):
    """A schedule entry sets a timezone other than UTC; due times are computed in UTC."""


# What makes one check incomplete: the others are a malformed field in a record that was read, or
# a record missing because its source was not read (a workflow whose run history failed).
CHECK_ERRORS = (SourceUnreadable, ValueError, KeyError, TypeError, AttributeError)


@dataclass(frozen=True)
class Cron:
    """A cron with every day of the month and every month; `parse_cron` refuses the others."""

    text: str
    minutes: frozenset[int]
    hours: frozenset[int]
    weekdays: frozenset[int]

    def fires_on(self, day: date) -> bool:
        # cron counts Sunday as 0, Python as 6.
        return (day.weekday() + 1) % 7 in self.weekdays


@dataclass(frozen=True)
class Series:
    label: str
    cron: Cron
    grace: timedelta
    frequent: bool

    def due_times(self, start: datetime, end: datetime) -> list[datetime]:
        return due_times(self.cron, start, end)


@dataclass(frozen=True)
class Workflow:
    file: str
    name: str
    series: tuple[Series, ...]
    guarded: bool
    chain: bool
    productive_names: frozenset[str]
    setup_names: frozenset[str]
    importer_steps: tuple[tuple[str, frozenset[str]], ...]


@dataclass(frozen=True)
class WorkflowState:
    state: str
    created_at: datetime


@dataclass(frozen=True)
class Assignment:
    runs: dict[Series, list[dict]]
    slots: dict[tuple[Series, datetime], dict]


@dataclass(frozen=True)
class Finding:
    check: str
    text: str
    date_label: str = ""
    link: str = ""
    kind: str = "problem"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def az_date(moment: datetime) -> str:
    return moment.astimezone(ARIZONA).date().isoformat()


# Values from GitHub or the database whose malformed form could read as a pass go through these,
# so the check is incomplete instead of seeing a valid zero, an empty list, or a name that matches
# nothing. Run fields compared to literals (status, conclusion, branch) are read as GitHub's schema
# defines them.


def ts(value) -> datetime:
    """A timezone-aware timestamp from ISO text or Postgres text, whose offset can be `+00`."""
    moment = datetime.fromisoformat(re.sub(r"([+-]\d{2})$", r"\1:00", text_of(value).strip()))
    if moment.tzinfo is None:
        raise ValueError("timestamp has no offset")
    return moment


def text_of(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError("expected non-blank text")
    return value


def count_of(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError("expected a count")
    return value


def records_of(value) -> list:
    if not isinstance(value, list):
        raise TypeError("expected a list of records")
    return value


def flag_of(value) -> bool:
    if not isinstance(value, bool):
        raise TypeError("expected true or false")
    return value


def workflow_page(file: str) -> str:
    return f"https://github.com/{REPO}/actions/workflows/{file}"


def own_run_link() -> str:
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not run_id:
        return workflow_page(CHECKER_WORKFLOW)
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{os.environ.get('GITHUB_REPOSITORY', REPO)}/actions/runs/{run_id}"


# --------------------------------------------------------------------------- #
# The workflow files
# --------------------------------------------------------------------------- #

def _cron_field(text: str, low: int, high: int) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        span, slash, step = part.partition("/")
        if span == "*":
            start, end = low, high
        elif m := re.fullmatch(r"(\d+)-(\d+)", span):
            start, end = int(m[1]), int(m[2])
        elif re.fullmatch(r"\d+", span) and not slash:
            start = end = int(span)
        else:
            raise ValueError(f"unsupported cron field {text!r}")
        if slash and not re.fullmatch(r"[1-9]\d*", step):
            raise ValueError(f"unsupported cron step {text!r}")
        if not low <= start <= end <= high:
            raise ValueError(f"cron field out of range {text!r}")
        values |= set(range(start, end + 1, int(step) if slash else 1))
    return frozenset(values)


def parse_cron(expr: str) -> Cron:
    """A cron that fires at least weekly. A day-of-month or month restriction can leave more than
    the run history's `RUN_HISTORY_DAYS` between due times, so it is refused rather than half-checked."""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"cron needs five fields: {expr!r}")
    minute, hour, day, month, weekday = fields
    if day != "*" or month != "*":
        raise ValueError(f"cron restricts the day of month or the month: {expr!r}")
    weekdays = _cron_field(weekday, 0, 7)
    return Cron(expr, _cron_field(minute, 0, 59), _cron_field(hour, 0, 23), frozenset(d % 7 for d in weekdays))


def due_times(cron: Cron, start: datetime, end: datetime) -> list[datetime]:
    found = []
    day = start.astimezone(UTC).date()
    while day <= end.astimezone(UTC).date():
        if cron.fires_on(day):
            for hour in sorted(cron.hours):
                for minute in sorted(cron.minutes):
                    moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)
                    if start <= moment <= end:
                        found.append(moment)
        day += timedelta(days=1)
    return found


def _daylight_saving_pair(a: Cron, b: Cron) -> bool:
    single_hours = len(a.hours) == len(b.hours) == 1
    return (a.minutes, a.weekdays) == (b.minutes, b.weekdays) and single_hours and abs(min(a.hours) - min(b.hours)) == 1


def _told_apart(a: Cron, b: Cron) -> bool:
    """Whether runs of two crons can be filed by start time: they share at most one weekday, and
    not at the same time of day. More shared days let one cron's runs fill the other's slots day
    after day, so a miss is charged to the wrong schedule."""
    shared = a.weekdays & b.weekdays
    same_time = bool(a.hours & b.hours and a.minutes & b.minutes)
    return len(shared) <= 1 and not (shared and same_time)


def build_series(crons: tuple[str, ...]) -> list[Series]:
    """One series per cron, except a daylight-saving pair: two crons one hour apart on the same
    days, of which the guard lets only one do its work.

    Several series are supported only when none fires more than daily, none is a pair, and every
    two can be told apart (`_told_apart`)."""
    parsed = [parse_cron(text) for text in crons]
    series, paired = [], set()
    for i, cron in enumerate(parsed):
        if i in paired:
            continue
        partners = (j for j in range(i + 1, len(parsed)) if j not in paired and _daylight_saving_pair(cron, parsed[j]))
        partner = next(partners, None)
        if partner is None:
            series.append(Series(cron.text, cron, GRACE, len(cron.minutes) * len(cron.hours) > 1))
            continue
        paired.add(partner)
        first, second = sorted((cron, parsed[partner]), key=lambda c: min(c.hours))
        series.append(Series(f"{first.text} / {second.text}", first, DST_GRACE, False))
    if len(series) > 1:
        crons_apart = all(_told_apart(a.cron, b.cron) for i, a in enumerate(series) for b in series[i + 1 :])
        if paired or not crons_apart or any(s.frequent for s in series):
            raise UnmatchableSchedules(f"schedules {', '.join(crons)} cannot be told apart")
    return series


def display_name(step: dict) -> str | None:
    """The name GitHub lists for a step: its literal name, else `Run <uses>` or `Run <first line>`."""
    name = step.get("name")
    if name is not None:
        return name if isinstance(name, str) and "${{" not in name else None
    if step.get("uses"):
        return f"Run {step['uses']}"
    run = step.get("run")
    if isinstance(run, str) and run.strip():
        return f"Run {run.strip().splitlines()[0]}"
    return None


def is_setup(step: dict) -> bool:
    if str(step.get("uses") or "").startswith(SETUP_USES):
        return True
    name = step.get("name")
    if isinstance(name, str):
        return name.strip().lower().startswith("install")
    run = step.get("run")
    if not isinstance(run, str):
        return False
    lines = [line.strip() for line in run.splitlines() if line.strip() and not line.strip().startswith("#")]
    return bool(lines) and all(line.startswith(SETUP_COMMANDS) for line in lines)


def is_chain(text: str, file: str) -> bool:
    """Whether some uncommented `gh workflow run` line names the file itself."""
    for line in text.splitlines():
        if line.lstrip().startswith("#") or "gh workflow run" not in line:
            continue
        if any(re.sub(r"[\"']", "", word).rsplit("/", 1)[-1] == file for word in line.split()):
            return True
    return False


def _invocation_providers(invocation: str, root: Path) -> set[str]:
    if DRAINER.search(invocation):
        return {"gotsport"}
    script = IMPORT_SCRIPT.search(invocation)
    if not script:
        return set()
    if script[1] == "import_games_enhanced":
        match = ENHANCED_IMPORT.search(invocation)
        code = match[2] if match else None
    else:
        match = PROVIDER_CODE.search((root / "scripts" / f"{script[1]}.py").read_text(encoding="utf-8"))
        code = match[1] if match else None
    if code is None:
        raise UnmappedImporter(invocation.strip())
    return {code}


def importer_providers(run_text: str, root: Path) -> set[str]:
    codes: set[str] = set()
    for line in run_text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for invocation in INVOCATION_SEPARATOR.split(line):
            codes |= _invocation_providers(invocation, root)
    return codes


def _steps(doc: dict) -> list[dict]:
    jobs = [job for job in (doc.get("jobs") or {}).values() if isinstance(job, dict)]
    return [step for job in jobs for step in job.get("steps") or [] if isinstance(step, dict)]


def _load_workflow(path: Path, root: Path) -> Workflow | None:
    text = path.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict):
        raise yaml.YAMLError("not a workflow mapping")
    triggers = doc.get("on", doc.get(True))
    if triggers == "schedule" or (isinstance(triggers, list) and "schedule" in triggers):
        raise ValueError("schedule named without its entries")
    if not isinstance(triggers, dict) or "schedule" not in triggers:
        return None
    schedule = triggers["schedule"]
    if not isinstance(schedule, list) or not schedule:
        raise ValueError("schedule is not a list of entries")
    for entry in schedule:
        if not isinstance(entry, dict) or not isinstance(entry.get("cron"), str):
            raise ValueError("schedule entry has no cron")
        if entry.get("timezone", "UTC") not in ("UTC", "Etc/UTC"):
            raise NonUtcSchedule(entry["timezone"])
    crons = tuple(entry["cron"] for entry in schedule)
    steps = _steps(doc)
    guarded = any(step.get("id") == "guard" for step in steps)
    named = [(display_name(step), step) for step in steps]
    gated = {name for name, step in named if name and "steps.guard.outputs" in str(step.get("if") or "")}
    importers = []
    for name, step in named:
        codes = importer_providers(step["run"], root) if isinstance(step.get("run"), str) else set()
        if codes:
            importers.append((name or "", frozenset(codes)))
    return Workflow(
        file=path.name,
        name=str(doc.get("name") or path.name),
        series=tuple(build_series(crons)),
        guarded=guarded,
        chain=is_chain(text, path.name),
        productive_names=frozenset(gated if guarded else ()),
        setup_names=frozenset(name for name, step in named if name and is_setup(step)),
        importer_steps=tuple(importers),
    )


def load_workflows(root: Path) -> tuple[list[Workflow], dict[str, str]]:
    """The scheduled workflows, and basename -> reason for each file that could not be read. Each
    reason completes "<file> has ..." in the email."""
    workflows, broken = [], {}
    for path in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        try:
            wf = _load_workflow(path, root)
        except yaml.YAMLError:
            broken[path.name] = "YAML that could not be read"
        except UnicodeDecodeError:
            broken[path.name] = "a workflow or importer file that is not UTF-8 text"
        except UnmatchableSchedules:
            broken[path.name] = "schedules this check cannot tell apart"
        except NonUtcSchedule:
            broken[path.name] = "a schedule timezone other than UTC"
        except ValueError:
            broken[path.name] = "a cron this check cannot read"
        except UnmappedImporter:
            broken[path.name] = "an importer with no provider code"
        except OSError:
            broken[path.name] = "an importer script that could not be read"
        except (TypeError, AttributeError):
            # A `jobs:` or `steps:` that cannot be iterated, which would otherwise stop every check.
            broken[path.name] = "a layout this check cannot read"
        else:
            if wf is not None:
                workflows.append(wf)
    return workflows, broken


# --------------------------------------------------------------------------- #
# GitHub runs, and the schedules they answer
# --------------------------------------------------------------------------- #

_github_failed = False
github_calls = 0


def github(path: str) -> dict:
    """After one read fails three times, every later read fails at once, so a GitHub outage costs
    one retry cycle rather than one per workflow."""
    global _github_failed, github_calls
    if _github_failed:
        raise SourceUnreadable("GitHub")
    command = ["gh", "api", "-H", "X-GitHub-Api-Version: 2026-03-10", f"repos/{REPO}/actions/{path}"]
    for attempt in range(3):
        github_calls += 1
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=60)
            return json.loads(result.stdout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError):
            if attempt == 2:
                _github_failed = True
                raise SourceUnreadable("GitHub") from None
            time.sleep(5 * (attempt + 1))
    raise AssertionError("unreachable")


def workflow_states() -> dict[str, WorkflowState]:
    # Anything but "active" reads as switched off, so the state must be real text.
    return {
        Path(text_of(r["path"])).name: WorkflowState(text_of(r["state"]), ts(r["created_at"]))
        for r in _paged("workflows", "workflows")
    }


def runs_query(event: str, since: datetime, *, bot: bool = False) -> str:
    params = {"branch": "main", "event": event}
    if bot:
        params["actor"] = "github-actions[bot]"
    params["created"] = ">=" + since.astimezone(UTC).strftime("%Y-%m-%d")
    return urlencode(params)


def _paged(path: str, key: str) -> list[dict]:
    """Every record of a paged Actions list, read until a short page. A record that appears on
    two pages, because a new one arrived while paging, is kept once. Fewer records than the first
    page's total, or more pages than GitHub serves, makes the list unreadable rather than short."""
    records, total = {}, None
    for page in range(1, MAX_RUN_PAGES + 1):
        payload = github(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
        batch = records_of(payload[key])
        total = count_of(payload["total_count"]) if total is None else total
        records.update((count_of(record["id"]), record) for record in batch)
        if len(batch) < 100:
            break
    else:
        raise SourceUnreadable("GitHub")
    if len(records) < total:
        raise SourceUnreadable("GitHub")
    return list(records.values())


def list_runs(file: str, query: str) -> list[dict]:
    return _paged(f"workflows/{file}/runs?{query}", "workflow_runs")


def started(run: dict) -> datetime:
    return ts(run.get("run_started_at") or run["created_at"])


def run_jobs(run_id: int, jobs_cache: dict) -> list[dict]:
    if run_id not in jobs_cache:
        jobs_cache[run_id] = _paged(f"runs/{run_id}/jobs", "jobs")
    return jobs_cache[run_id]


def _productive(step_name: str, wf: Workflow) -> bool:
    if wf.guarded:
        return step_name in wf.productive_names
    own = step_name in GITHUB_OWN_STEP_NAMES or step_name.startswith("Post ")
    return not own and step_name not in wf.setup_names


def is_counted(run: dict, wf: Workflow, jobs_cache: dict) -> bool:
    """Whether the run did its work: a finished run on main in which some job succeeded with a
    productive step that succeeded. A guarded workflow's productive steps are the ones its guard
    gates, because the inactive daylight-saving run skips those steps and still ends green. An
    unfinished run cannot count: a chain link's first job succeeds before its scrape starts."""
    if run.get("head_branch") != "main" or run.get("status") != "completed":
        return False
    return any(
        job["conclusion"] == "success"
        and any(
            step["conclusion"] == "success" and _productive(text_of(step["name"]), wf)
            for step in records_of(job["steps"])
        )
        for job in run_jobs(run["id"], jobs_cache)
    )


def assign_runs(
    series_list: list[Series], runs: list[dict], created_at: datetime, since: datetime, now: datetime
) -> Assignment:
    """File each scheduled run under a series. With several series, each run in start order fills
    the earliest-due open slot, so a late run is not filed under a series that fired after it was due.
    A run with no open slot is filed under the series due most recently before it, without a slot.

    The run list does not say which cron started a run, so timing is all there is. When a weekly
    run never fires, a daily run starting within that slot's grace fills it: the miss shows only as
    a one-day alarm on the daily series, and the weekly series reads on time."""
    ordered = sorted(runs, key=started)
    if len(series_list) == 1:
        return Assignment({series_list[0]: ordered}, {})
    slots = sorted(
        (
            (due, i, s)
            for i, s in enumerate(series_list)
            for due in s.due_times(since - SLOT_LEAD, now)
            if due >= created_at
        ),
        key=lambda slot: (slot[0], slot[1]),
    )
    filed: dict[Series, list[dict]] = {s: [] for s in series_list}
    filled: dict[tuple[Series, datetime], dict] = {}
    for run in ordered:
        at = started(run)
        open_slots = ((s, due) for due, _, s in slots if due <= at < due + s.grace and (s, due) not in filled)
        open_slot = next(open_slots, None)
        if open_slot is not None:
            filled[open_slot] = run
            filed[open_slot[0]].append(run)
            continue
        before = [s for due, _, s in slots if due <= at]
        if before:
            filed[before[-1]].append(run)
    return Assignment(filed, filled)


def latest_due(series: Series, created_at: datetime, now: datetime) -> datetime | None:
    dues = [
        due
        for due in series.due_times(now - timedelta(days=RUN_HISTORY_DAYS), now)
        if due >= created_at and due + series.grace <= now
    ]
    return dues[-1] if dues else None


def missed_due(series: Series, due: datetime, assignment: Assignment, counted) -> bool:
    """Whether no counted run answers `due`, the series' latest due time whose grace has passed:
    with several series, the run filling its slot; with one, any run started since."""
    if len(assignment.runs) > 1:
        run = assignment.slots.get((series, due))
        return run is None or not counted(run)
    runs = sorted(assignment.runs[series], key=started, reverse=True)
    return not any(counted(run) for run in runs if started(run) >= due)


def failure_flag(runs: list[dict], counted, bad: frozenset[str] = FAILED) -> dict | None:
    """The newest run whose conclusion is in `bad`, unless a later run did its work."""
    newest_first = sorted(runs, key=started, reverse=True)
    for i, run in enumerate(newest_first):
        if run.get("conclusion") in bad:
            return None if any(counted(later) for later in newest_first[:i]) else run
    return None


def frequent_counts(series: Series, runs: list[dict], created_at: datetime, now: datetime) -> tuple[int, int, int]:
    start = max(now - FREQUENT_WINDOW, created_at)
    recent = [run for run in runs if start <= started(run) <= now]
    expected = len(series.due_times(start, now))
    return len(recent), expected, sum(run.get("conclusion") == "success" for run in recent)


def last_counted(runs: list[dict], counted) -> dict | None:
    return next((run for run in sorted(runs, key=started, reverse=True) if counted(run)), None)


def _skipped_its_work(runs: list[dict], since: datetime, counted) -> dict | None:
    for run in sorted(runs, key=started, reverse=True):
        if started(run) < since:
            break
        conclusion = run.get("conclusion")
        if conclusion == "skipped" or (conclusion == "success" and not counted(run)):
            return run
    return None


def series_line(
    title: str,
    wf: Workflow,
    failed: dict | None,
    missed: datetime | None,
    runs: list[dict],
    counted,
    *,
    chained: bool = False,
) -> Finding:
    """One line for a series, or for a chain's links. With several series a run fills one due
    time's slot, so a counted run can follow a missed slot; the line then names the slot and the
    last counted run before it, rather than claiming "since"."""
    by_slot = len(wf.series) > 1
    parts, labels = [], []
    if failed is not None:
        label = f"run started {az_date(started(failed))}"
        parts.append(f"the {'chained' if chained else 'scheduled'} {label} ended {failed.get('conclusion')}")
        labels.append(label)
    if missed is not None:
        label = f"due {az_date(missed)}"
        parts.append(f"no counted run {'for' if by_slot else 'since'} the one {label}")
        labels.append(label)
        previous = last_counted([run for run in runs if started(run) < missed], counted)
        if previous is not None:
            parts.append(f"last counted run {az_date(started(previous))}")
        else:
            parts.append(f"no {'earlier ' if by_slot else ''}counted run in {RUN_HISTORY_DAYS} days")
        skipped = _skipped_its_work(runs, missed, counted)
        if skipped is not None:
            parts.append(f"ran on {az_date(started(skipped))} but skipped its work")
    link = failed.get("html_url") if failed is not None else None
    return Finding("schedules", f"{title}: {'; '.join(parts)}", labels[0], link or workflow_page(wf.file))


def evaluate_workflow(
    wf: Workflow, created_at: datetime, runs: list[dict], links: list[dict], now: datetime, jobs_cache: dict
) -> tuple[list[Finding], int]:
    """The workflow's schedule findings, and how many of its daily-or-weekly series were on time."""

    def counted(run: dict) -> bool:
        return is_counted(run, wf, jobs_cache)

    since = now - timedelta(days=RUN_HISTORY_DAYS)
    multi = len(wf.series) > 1
    assignment = assign_runs(list(wf.series), runs, created_at, since, now)
    findings, on_time = [], 0
    for series in wf.series:
        title = f"{wf.name} ({series.label})" if multi else wf.name
        series_runs = assignment.runs[series]
        failed = failure_flag(series_runs, counted, FREQUENT_FAILED if series.frequent else FAILED)
        due = None if series.frequent else latest_due(series, created_at, now)
        missed = due if due is not None and missed_due(series, due, assignment, counted) else None
        if series.frequent:
            fired, expected, succeeded = frequent_counts(series, series_runs, created_at, now)
            text = f"{title}: fired {fired} of {expected} scheduled times in the last 7 days ({succeeded} succeeded)"
            findings.append(Finding("schedules", text, kind="ok"))
        elif due is None:
            added = f"added {az_date(created_at)}"
            text = f"{title}: awaiting its first scheduled run ({added})"
            findings.append(Finding("schedules", text, added, workflow_page(wf.file), "awaiting"))
        if failed is not None or missed is not None:
            findings.append(series_line(title, wf, failed, missed, series_runs, counted))
        elif due is not None:
            on_time += 1
    if wf.chain:
        failed = failure_flag(links, counted)
        if failed is not None:
            findings.append(series_line(f"{wf.name} (chained runs)", wf, failed, None, links, counted, chained=True))
    return findings, on_time


# --------------------------------------------------------------------------- #
# The database
# --------------------------------------------------------------------------- #


def read_only_query(sql: str, *, source: str, columns: tuple[str, ...]) -> dict:
    """The one row a query returns, read through the Management API's enforced read-only endpoint."""
    token = os.environ.get("SUPABASE_ACCESS_TOKEN", "").strip()
    parsed = urlparse(os.environ.get("SUPABASE_URL", "").strip())
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not host.endswith(".supabase.co") or not token:
        raise SourceUnreadable(source)
    try:
        response = requests.post(
            f"https://api.supabase.com/v1/projects/{host.split('.')[0]}/database/query/read-only",
            headers={"Authorization": "Bearer " + token},
            json={"query": sql},
            timeout=60,
            allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            raise SourceUnreadable(f"{source} (HTTP {response.status_code})")
        payload = response.json()
    except (requests.RequestException, ValueError):
        raise SourceUnreadable(source) from None
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise SourceUnreadable(source)
    row = payload[0]
    if row.get("read_only") != "on" or any(column not in row for column in columns):
        raise SourceUnreadable(source)
    return row


def rankings_finding(row: dict, now: datetime) -> Finding:
    start = ts(row["ranking_start"])
    published, stale = count_of(row["row_count"]), count_of(row["stale_rows"])
    previous = None if row["previous_snapshot_rows"] is None else count_of(row["previous_snapshot_rows"])
    run = f"run starting {az_date(start)}"
    link = workflow_page("calculate-rankings.yml")
    if flag_of(row["complete"]):
        text = f"Rankings: this week's publication is complete, {published:,} rows from the {run}"
        return Finding("rankings", text, run, link, "ok")
    if now - start <= RANKINGS_DEADLINE:
        return Finding("rankings", f"Rankings: awaiting this week's run (the {run})", run, link, "awaiting")
    if published == 0:
        return Finding("rankings", f"Rankings: the published table is empty; expected from the {run}", run, link)
    if row["newest_calculated"] is None:
        return Finding("rankings", f"Rankings: no row has a refresh time; expected from the {run}", run, link)
    if stale > 0:
        newest = f"newest refresh {az_date(ts(row['newest_calculated']))}"
        text = (
            f"Rankings: {stale:,} of {published:,} rows were not refreshed by the {run} "
            f"({newest}): this week's run did not refresh every row, or teams it removed were not cleaned up"
        )
        return Finding("rankings", text, newest, link)
    if previous is None:
        text = f"Rankings: no ranking snapshot before the {run} to compare with"
        return Finding("rankings", text, run, link)
    snapshot = f"snapshot of {text_of(row['previous_snapshot_date'])}"
    text = f"Rankings: {published:,} rows published, under 95% of the {previous:,} in the {snapshot}"
    return Finding("rankings", text, snapshot, link)


def expected_providers(workflows: list[Workflow], states: dict[str, WorkflowState]) -> dict[str, list[Workflow]]:
    """Provider code -> the active scheduled workflows that import it."""
    expected: dict[str, list[Workflow]] = {}
    for wf in workflows:
        state = states.get(wf.file)
        if state is None or state.state != "active":
            continue
        for code in sorted({code for _, codes in wf.importer_steps for code in codes}):
            expected.setdefault(code, []).append(wf)
    return expected


def heartbeat_findings(
    expected, heartbeats: dict[str, datetime], states, runs_by_file, jobs_cache, now: datetime
) -> list[Finding]:
    """A provider is late when its import is due, nothing was logged since, and no run of its
    workflow did its work since either: a healthy run with nothing to import logs nothing."""
    findings = []
    for code, workflows in sorted(expected.items()):
        try:
            dues = [
                due
                for wf in workflows
                for series in wf.series
                if (due := latest_due(series, states[wf.file].created_at, now)) is not None
            ]
            if not dues:
                continue
            due = max(dues)
            logged = heartbeats.get(code)
            if logged is not None and logged >= due:
                continue
            ran = [
                started(run)
                for wf in workflows
                if (run := last_counted(runs_by_file[wf.file], lambda r, wf=wf: is_counted(r, wf, jobs_cache)))
            ]
            if ran and max(ran) >= due:
                continue
        except CHECK_ERRORS:
            findings.append(incomplete_finding(f"the {code} import check could not be read", now))
            continue
        parts = []
        if logged is not None:
            parts.append(f"last import logged {az_date(logged)}")
        if ran:
            parts.append(f"last counted run {az_date(max(ran))}")
        if not parts:
            parts.append(f"import due {az_date(due)}")
        joined = "; ".join(parts)
        text = f"{code} ({workflows[0].name}): no import logged and no run did its work since it was due; {joined}"
        findings.append(Finding("imports", text, parts[0], workflow_page(workflows[0].file)))
    return findings


def quiet_findings(expected, windows: dict[str, dict], now: datetime) -> list[Finding]:
    """A provider that averaged `QUIET_MIN_WEEKLY` or more new games a week over the four weeks
    before the last two, and brought under a tenth of that in each of the last two weeks."""
    findings = []
    for code, workflows in sorted(expected.items()):
        # A provider with no games in the six weeks has no row; a row it does have carries every count.
        counts = windows.get(code, dict.fromkeys(GAME_WINDOWS, 0))
        last, before, baseline = (count_of(counts[k]) for k in GAME_WINDOWS)
        if baseline < 4 * QUIET_MIN_WEEKLY or last * 40 >= baseline or before * 40 >= baseline:
            continue
        label = f"in the two weeks to {az_date(now)}"
        text = (
            f"{code} ({workflows[0].name}): {plural(last, 'new game')} in the last 7 days and {before} the week "
            f"before, against a usual {baseline / 4:g} a week, {label}"
        )
        findings.append(Finding("quiet", text, label, workflow_page(workflows[0].file)))
    return findings


def queue_findings(row: dict, now: datetime) -> list[Finding]:
    findings = []
    link = workflow_page("process-missing-games.yml")
    stuck = count_of(row["stuck_processing"])
    completed_recently = flag_of(row["completed_recently"])
    if stuck > 0:
        label = f"oldest stuck request claimed {az_date(ts(row['oldest_stuck_claimed']))}"
        text = f"{plural(stuck, 'scrape request')} stuck in processing for over {STUCK_HOURS} hours; {label}"
        findings.append(Finding("queue", text, label, link))
    pending = row["oldest_pending_requested"]
    if pending is not None and now - ts(pending) > PENDING_STALL and not completed_recently:
        label = f"oldest waiting request queued {az_date(ts(pending))}"
        text = f"The drainer has stalled: {label}; nothing completed in the last {STUCK_HOURS} hours"
        findings.append(Finding("queue", text, label, link))
    return findings


def incomplete_finding(what: str, now: datetime) -> Finding:
    label = f"checked {az_date(now)}"
    return Finding("incomplete", f"Check incomplete: {what} ({label})", label, own_run_link())


# --------------------------------------------------------------------------- #
# The checks together
# --------------------------------------------------------------------------- #


def _merge(seen: dict[int, dict], read: list[dict]) -> None:
    """Add a read's runs to those already seen. The later copy of a run wins, except that a
    stale copy of the same attempt cannot take a finished run back to unfinished."""
    for run in read:
        earlier = seen.get(run["id"])
        regressed = (
            earlier is not None
            and earlier.get("status") == "completed"
            and run.get("status") != "completed"
            and run.get("run_attempt") == earlier.get("run_attempt")
        )
        if not regressed:
            seen[run["id"]] = run


def read_and_evaluate(
    wf: Workflow, created_at: datetime, now: datetime, jobs_cache: dict
) -> tuple[list[dict], list[Finding], int]:
    """A filtered run list now and then comes back empty or stale, so a workflow with a problem
    is read again. A stale read can leave runs out but not invent them, so the two reads are
    merged and the workflow is judged on the merged lists."""
    # A frequent workflow's lines use only its last week, and fifteen days of a quarter-hour cron
    # would pass the pager's limit.
    frequent = all(series.frequent for series in wf.series)
    since = now - (FREQUENT_WINDOW if frequent else timedelta(days=RUN_HISTORY_DAYS))
    runs: dict[int, dict] = {}
    links: dict[int, dict] = {}
    for _ in range(2):
        _merge(runs, list_runs(wf.file, runs_query("schedule", since)))
        if wf.chain:
            _merge(links, list_runs(wf.file, runs_query("workflow_dispatch", since, bot=True)))
        merged = list(runs.values())
        findings, on_time = evaluate_workflow(wf, created_at, merged, list(links.values()), now, jobs_cache)
        if not any(f.kind == "problem" for f in findings):
            break
    return merged, findings, on_time


def collect(now: datetime) -> list[Finding]:
    findings: list[Finding] = []

    def incomplete(what: str) -> None:
        findings.append(incomplete_finding(what, now))

    workflows, broken = load_workflows(ROOT)

    try:
        row = read_only_query(PUBLICATION_SQL, source="the rankings publication", columns=PUBLICATION_COLUMNS)
        findings.append(rankings_finding(row, now))
    except CHECK_ERRORS:
        incomplete("the rankings publication could not be read")

    try:
        states = workflow_states()
    except CHECK_ERRORS:
        incomplete("GitHub's workflow list could not be read, so the schedule and import checks did not run")
        states = None

    for file, reason in sorted(broken.items()):
        if states is not None and file in states and states[file].state != "active":
            continue
        incomplete(f"{file} has {reason}")

    active: list[tuple[Workflow, WorkflowState]] = []
    for wf in workflows if states is not None else []:
        state = states.get(wf.file)
        if state is None:
            incomplete(f"{wf.file} is not in GitHub's workflow list")
        elif state.state == "active":
            active.append((wf, state))

    jobs_cache: dict = {}
    runs_by_file: dict[str, list[dict]] = {}
    schedule_lines, on_time, schedule_ok = [], 0, True
    for wf, state in active:
        try:
            runs_by_file[wf.file], wf_findings, wf_on_time = read_and_evaluate(wf, state.created_at, now, jobs_cache)
        except CHECK_ERRORS:
            incomplete(f"the run history of {wf.name} could not be read")
            schedule_ok = False
            continue
        schedule_lines += wf_findings
        on_time += wf_on_time
    if states is not None:
        problems = [f for f in schedule_lines if f.kind == "problem"]
        findings += problems
        if schedule_ok and not problems:
            findings.append(Finding("schedules", f"{plural(on_time, 'daily-or-weekly schedule')} on time", kind="ok"))
        findings += [f for f in schedule_lines if f.kind == "ok"]
        switched_off = sorted(file for file, state in states.items() if state.state != "active")
        findings.append(Finding("schedules", f"Switched off in GitHub: {', '.join(switched_off) or 'none'}", kind="ok"))
        findings += [f for f in schedule_lines if f.kind == "awaiting"]

        expected = expected_providers(workflows, states)
        try:
            row = read_only_query(BUILD_HEARTBEAT_QUERY, source="the import log", columns=("heartbeats",))
            heartbeats = {text_of(r["code"]): ts(r["last_logged"]) for r in records_of(row["heartbeats"])}
            lines = heartbeat_findings(expected, heartbeats, states, runs_by_file, jobs_cache, now)
        except CHECK_ERRORS:
            incomplete("the import log could not be read")
        else:
            on_time_providers = f"All {plural(len(expected), 'scheduled provider')} on time"
            findings += lines or [Finding("imports", on_time_providers, kind="ok")]

        try:
            row = read_only_query(GAME_WINDOWS_QUERY, source="the new-game counts", columns=("game_windows",))
            lines = quiet_findings(expected, {text_of(r["code"]): r for r in records_of(row["game_windows"])}, now)
        except CHECK_ERRORS:
            incomplete("the new-game counts could not be read")
        else:
            findings += lines or [Finding("quiet", "No busy provider went quiet", kind="ok")]

    try:
        row = read_only_query(
            SCRAPE_QUEUE_QUERY,
            source="the scrape queue",
            columns=("stuck_processing", "oldest_stuck_claimed", "oldest_pending_requested", "completed_recently"),
        )
        lines = queue_findings(row, now)
    except CHECK_ERRORS:
        incomplete("the scrape queue could not be read")
    else:
        findings += lines or [Finding("queue", "Nothing stuck, and the drainer is completing requests", kind="ok")]
    return findings


# --------------------------------------------------------------------------- #
# The email
# --------------------------------------------------------------------------- #


def _shown(findings: list[Finding], weekly: bool) -> list[tuple[str, list[Finding]]]:
    groups = []
    for check in (*CHECKS, "incomplete"):
        items = [f for f in findings if f.check == check and (weekly or f.kind == "problem")]
        if items:
            groups.append((CHECK_TITLES[check], items))
    return groups


def subject(findings: list[Finding], weekly: bool) -> str:
    problems = sum(f.kind == "problem" for f in findings)
    if weekly:
        return f"PitchRank weekly job check: {plural(problems, 'problem') if problems else 'all clear'}"
    return f"PitchRank job check: {plural(problems, 'problem')}"


def render_text(findings: list[Finding], weekly: bool, now: datetime) -> str:
    lines = [subject(findings, weekly), f"Checked {az_date(now)}"]
    for title, items in _shown(findings, weekly):
        lines += ["", title]
        lines += [f"  - {f.text}" + (f" ({f.link})" if f.link else "") for f in items]
    return "\n".join([*lines, "", FOOTER])


def render_html(findings: list[Finding], weekly: bool, now: datetime) -> tuple[str, str]:
    def esc(value) -> str:
        return html.escape(str(value), quote=True)

    muted = "color:#666; font-size:13px"

    def item(f: Finding) -> str:
        link = f" <a href='{esc(f.link)}' style='color:#0B5345'>Open</a>" if f.link else ""
        style = "margin:0 0 6px" if f.kind == "problem" else f"margin:0 0 6px; {muted}"
        return f"<li style='{style}'>{esc(f.text)}{link}</li>"

    parts = [
        "<div style='font-family:Arial,Helvetica,sans-serif; font-size:15px; line-height:1.45; "
        "color:#1a1a1a; max-width:720px'>",
        f"<h2 style='margin:0; color:#0B5345'>{'Weekly job check' if weekly else 'Scheduled job check'}</h2>",
        f"<p style='margin:2px 0 12px; {muted}'>Checked {esc(az_date(now))}</p>",
    ]
    for title, items in _shown(findings, weekly):
        parts.append(f"<h3 style='margin:20px 0 4px; font-size:16px; color:#0B5345'>{esc(title)}</h3>")
        parts.append("<ul style='margin:4px 0 0; padding-left:20px'>" + "".join(item(f) for f in items) + "</ul>")
    parts.append(f"<p style='margin:28px 0 0; {muted}'>{esc(FOOTER)}</p></div>")
    return subject(findings, weekly), "\n".join(parts)


class _HideResendBody(logging.Filter):
    """Replaces the response body in the email helper's refusal warning, because Actions logs are public."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg == "Resend answered %s: %s" and isinstance(record.args, tuple) and record.args:
            record.args = (record.args[0], "(body hidden on Actions)")
        return True


def hide_resend_body() -> None:
    resend_logger = logging.getLogger("src.utils.resend_email")
    if not any(isinstance(f, _HideResendBody) for f in resend_logger.filters):
        resend_logger.addFilter(_HideResendBody())


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / ".env.local", override=True)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the email; send nothing")
    ap.add_argument("--weekly", action="store_true", help="always email: the Tuesday all-clear")
    args = ap.parse_args(argv)

    on_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    if args.dry_run and on_actions:
        print("Refusing --dry-run on Actions: it prints the email, and this repo's Actions logs are public.")
        return 2
    if on_actions:
        hide_resend_body()
    weekly = args.weekly or os.environ.get("WEEKLY") == "true"
    missing = [name for name in DATABASE_SETTINGS if not os.environ.get(name, "").strip()]
    mail_key = bool(os.environ.get("RESEND_API_KEY", "").strip())
    if not args.dry_run and not mail_key:
        missing.append("RESEND_API_KEY")

    now = datetime.now(UTC)
    findings = collect(now)
    problems = sum(f.kind == "problem" and f.check != "incomplete" for f in findings)
    incomplete = sum(f.check == "incomplete" for f in findings)
    title, body = render_html(findings, weekly, now)
    needed = weekly or problems or incomplete

    if args.dry_run:
        print(render_text(findings, weekly, now))
        print(f"Dry run: no email sent ({title if needed else 'nothing to send'}); {github_calls} GitHub reads")
        return 1 if incomplete else 0

    status = "not needed"
    if needed and mail_key:
        recipient = os.environ.get("ALERT_EMAIL", DEFAULT_ALERT_EMAIL)
        status = "accepted" if send_email(recipient, title, body) else "refused"
    elif needed:
        status = "not sent"
    line = f"checks {len(CHECKS)}, problems {problems}, incomplete {incomplete}, email {status}"
    logger.info(line + (f", missing {', '.join(missing)}" if missing else ""))
    return 1 if incomplete or not mail_key or status == "refused" else 0


if __name__ == "__main__":
    raise SystemExit(main())
