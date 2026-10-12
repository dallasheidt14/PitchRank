#!/usr/bin/env python3
"""Assert the claims that .claude/skills/correcting-team-age-groups makes about this repo.

That skill governs writes to teams.age_group, the column every ranking board is cut by. Its
guidance rests on claims about code behaviour: which band names which age group this season,
which teams the owner decided to leave alone, and which guards stand between a plan and a write.
Prose claims cannot fail, so they rot silently, and the age chart rots every Aug 1.

This script makes those claims executable. Run it before trusting the skill.

ASSERTIONS fail the run. A failure means a documented claim (the skill's or CLAUDE.md's) or an
agreement between the age tools no longer holds, or that a check stopped; the detail line says
which.

Nothing reads the database: each tool runs against an in-memory stand-in with blank credentials
and no client builder, so --code-only changes nothing.

Usage:
    python scripts/check_age_skill_assumptions.py               # everything
    python scripts/check_age_skill_assumptions.py --code-only   # accepted; changes nothing
    python scripts/check_age_skill_assumptions.py --json
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CLAUDE_MD = ROOT / "CLAUDE.md"
REVIEW = ROOT / ".claude" / "skills" / "correcting-team-age-groups" / "scripts" / "review_age_labels.py"
TRIAGE = ROOT / ".claude" / "skills" / "reconcile-gotsport" / "scripts" / "triage_reconcile.py"
WORKFLOWS = ROOT / ".github" / "workflows"
# The module name, so "python -m scripts.fix_team_age_groups" is found as well as the file.
DERIVATION = "fix_team_age_groups"
DERIVATION_FLAG = "AGE_DERIVATION_ENABLED"
DERIVATION_GATE = re.compile(r"env\.AGE_DERIVATION_ENABLED\s*==\s*'true'", re.I)
BOARDS = ["u10", "u11", "u12", "u13", "u14", "u15", "u16", "u17", "u19"]
# Every name the age tools' own client builders read, fallbacks included.
CREDENTIALS = (
    "SUPABASE_URL",
    "NEXT_PUBLIC_SUPABASE_URL",
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_SERVICE_KEY",
)

SEASON = re.compile(r"^### Age Groups \((\d{4})-\d{2} Season\)", re.M)
AGE_ROW = re.compile(r"^\|\s*(\d{4})\s*/\s*(\d{4})\s*\|\s*U\d+\s*\|\s*\*{0,2}(u\d+)\*{0,2}", re.M)
LABEL_KEY_CLAUSE = re.compile(r"((?:`[^`]+`(?:,\s*|\s+and\s+))+`[^`]+`)\s+are all\s+\*\*(U\d+)\*\*")
RECHECK_LEFT_OUT = re.compile(r"\| Left out\b[^|]*\| ([0-9,]+) \|")
TRIAGE_LEFT_OUT = re.compile(r"^([0-9]+) more whose age differs, left out", re.M)

# Distinct teams in each section of the owner's age decisions, recorded 2026-10-12. A section may grow;
# one that shrinks fails the check until whoever removed a decision lowers its floor here on purpose.
DECISION_FLOORS = {"kept_as_stored": 14, "left_held": 70, "ea_cleanup_2026_10_07": 1}

LIVE_ID = "aaaaaaaa-0000-4000-8000-000000000001"
OTHER_LIVE_ID = "aaaaaaaa-0000-4000-8000-000000000002"


@dataclass
class Result:
    assertions: list[dict] = field(default_factory=list)

    def check(self, name, ok, detail):
        self.assertions.append({"name": name, "ok": bool(ok), "detail": detail})

    @property
    def failures(self):
        return [a for a in self.assertions if not a["ok"]]


class _Recorder:
    """A Supabase stand-in that records each read and write when it executes. A read returns no rows;
    a write returns one row, as an update matching a live team does."""

    def __init__(self):
        self.writes = []
        self.reads = []

    def table(self, name):
        return _Request(self, name)

    def asked(self, table: str, column: str) -> set:
        """Every value an ``eq`` or ``in_`` filter on ``column`` asked of ``table``; ``or_``, ``gte`` and
        ``is_`` are accepted but not recorded."""
        return {
            value
            for read_table, filters in self.reads
            if read_table == table
            for read_column, values in filters
            if read_column == column
            for value in (values if isinstance(values, tuple) else (values,))
        }


class _Request:
    """One request, refusing what postgrest's builders refuse: a filter or an execute before select or
    update, an update after a select or the reverse, and ordering, paging or limiting an update."""

    def __init__(self, recorder, table):
        self.recorder, self.table_name = recorder, table
        self.kind, self.payload, self.filters = None, None, []

    def _become(self, kind):
        if self.kind is not None:
            raise AttributeError(f"a {self.kind} request has no {kind}")
        self.kind = kind
        return self

    def select(self, *columns, **options):
        return self._become("select")

    def update(self, payload):
        self._become("update")
        self.payload = payload
        return self

    def _filter(self, *args, **kwargs):
        if self.kind is None:
            raise AttributeError("a table has no filters before select or update")
        return self

    def eq(self, column, value):
        self._filter().filters.append((column, value))
        return self

    def in_(self, column, values):
        self._filter().filters.append((column, tuple(values)))
        return self

    or_ = gte = is_ = _filter

    def _select_only(self, *args, **kwargs):
        if self.kind != "select":
            raise AttributeError(f"a {self.kind or 'table'} request has no order, range or limit")
        return self

    order = range = limit = _select_only

    def execute(self):
        if self.kind == "select":
            self.recorder.reads.append((self.table_name, self.filters))
            return SimpleNamespace(data=[])
        if self.kind == "update":
            self.recorder.writes.append((self.table_name, self.payload, sorted(self.filters, key=str)))
            return SimpleNamespace(data=[{"team_id_master": LIVE_ID}])
        raise AttributeError("a table has no execute before select or update")


def _refuse_client(*args, **kwargs):
    raise RuntimeError("the age check reached a real database client")


@contextlib.contextmanager
def _offline(recorder: _Recorder, *modules, argv: list[str] | None = None):
    """Hand the age fixer and ``modules`` the recorder as their client, with no credentials set and
    no way left to build a real one."""
    from scripts import fix_band_cohorts as fbc

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ, dict.fromkeys(CREDENTIALS, "")))
        stack.enter_context(mock.patch.object(fbc, "create_client", _refuse_client))
        for module in (fbc, *modules):
            stack.enter_context(mock.patch.object(module, "load_env", lambda: None))
            stack.enter_context(mock.patch.object(module, "get_supabase", lambda: recorder))
        if argv:
            stack.enter_context(mock.patch.object(sys, "argv", argv))
        yield


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def age_section_lines(text: str) -> list[tuple[int, str]]:
    """(line number, line) for CLAUDE.md's "### Age Groups" section: its heading line, up to the next
    heading of level three or deeper."""
    lines, inside = [], False
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.startswith("### Age Groups"):
            inside = True
        elif inside and line.startswith("###"):
            break
        if inside:
            lines.append((lineno, line))
    return lines


def _age_section(text: str) -> str:
    return "\n".join(line for _, line in age_section_lines(text))


def label_key_examples(section: str) -> list[tuple[str, str]]:
    """(spelling, stated group) for each "`a`, `b` and `c` are all **U13**" clause in ``section``, read
    across line breaks."""
    text = " ".join(line.strip() for line in section.splitlines())
    return [
        (spelling, stated)
        for spellings, stated in LABEL_KEY_CLAUSE.findall(text)
        for spelling in re.findall(r"`([^`]+)`", spellings)
    ]


def _reader(review):
    try:
        return review.Reader()
    except SystemExit:
        return None


def check_chart(r: Result, claude_md: Path = CLAUDE_MD) -> None:
    """CLAUDE.md's table, the review's literal CHART and the band readers name one group per band."""
    from scripts.fix_band_cohorts import band_of
    from src.utils.team_utils import calculate_age_group_from_band

    review = _module(REVIEW, "review_age_labels")
    section = _age_section(claude_md.read_text(encoding="utf-8"))
    season = SEASON.search(section)
    r.check(
        "CLAUDE.md's age table is for the season the review's CHART is for",
        season and int(season.group(1)) == review.CHART_SEASON,
        f"CLAUDE.md: {season.group(0) if season else 'no Age Groups heading'}; CHART_SEASON = {review.CHART_SEASON}",
    )
    rows = [(int(m.group(1)), int(m.group(2)), m.group(3)) for m in AGE_ROW.finditer(section)]
    base = int(season.group(1)) if season else review.CHART_SEASON
    younger_years = sorted(younger for younger, _, _ in rows)
    r.check(
        "CLAUDE.md's table lists each band from u9 to u19 once",
        younger_years == list(range(base - 18, base - 7)),
        f"younger years read: {younger_years}; the {base} season's u9-u19 bands are {base - 18}-{base - 8}",
    )
    reader = _reader(review)
    for younger, older, group in rows:
        band = f"Club {younger}/{older}"
        readings = {
            "CHART": review.CHART.get(younger),
            "calculate_age_group_from_band": (calculate_age_group_from_band(younger) or "").lower() or None,
            "Reader.band": reader.band(band) if reader else "refused to run",
            "fix_band_cohorts.band_of": band_of(band),
        }
        wrong = {reader_name: got for reader_name, got in readings.items() if got != group}
        r.check(f"the {younger}/{older} band is {group} in every reader", not wrong, f"table says {group}; {wrong}")


def check_label_key(r: Result, claude_md: Path = CLAUDE_MD) -> None:
    """Every spelling in CLAUDE.md's label key reads as the group the key gives it."""
    review = _module(REVIEW, "review_age_labels")
    examples = label_key_examples(_age_section(claude_md.read_text(encoding="utf-8")))
    r.check("CLAUDE.md's label key is readable", len(examples) >= 13, f"{len(examples)} spellings read")
    reader = _reader(review)
    for spelling, stated in examples:
        if reader:
            ulabels, _ = reader.labels(spelling)
            got = reader.band(spelling) or (sorted(ulabels)[0] if len(ulabels) == 1 else None)
        else:
            got = "refused to run"
        r.check(
            f"label key: {spelling} is {stated}", got == stated.lower(), f"the review reads {spelling!r} as {got!r}"
        )


def check_boards(r: Result) -> None:
    from config.settings import AGE_GROUPS

    groups = sorted(AGE_GROUPS, key=lambda g: int(g[1:]))
    r.check(
        "the boards are u10-u17 and u19 (u18 files into u19; u9 and younger have none)",
        groups == BOARDS,
        f"AGE_GROUPS keys: {groups}",
    )


def check_rolled_season(r: Result) -> None:
    """The review refuses to read names with a chart from another season."""
    from src.utils import team_utils

    review = _module(REVIEW, "review_age_labels")
    with mock.patch.object(team_utils, "_soccer_season_year", lambda: review.CHART_SEASON + 1):
        refused = _reader(review) is None
    r.check(
        "the review's Reader refuses a season its CHART is not for",
        refused,
        f"Reader() with the season at {review.CHART_SEASON + 1} and CHART_SEASON {review.CHART_SEASON}",
    )


def check_owner_decisions(r: Result) -> None:
    """The owner's decisions file loads whole, and its absence stops a run."""
    from scripts import fix_band_cohorts as fbc

    try:
        sections = json.loads(fbc.OWNER_DECISIONS.read_text(encoding="utf-8-sig"))
        shaped = all(
            isinstance(body.get("decided"), str)
            and isinstance(body.get("teams"), list)
            and all(isinstance(team.get("team_id"), str) for team in body["teams"])
            for body in sections.values()
        )
    except (OSError, ValueError, AttributeError) as exc:
        sections, shaped = {}, f"{type(exc).__name__}: {exc}"
    r.check(
        "owner_decisions.json is sections of {decided, teams: [{team_id}]}",
        shaped is True,
        f"sections {sorted(sections)}; {shaped}",
    )
    try:
        loaded = {tid: section for tid, (section, _) in fbc.load_owner_decisions(_Recorder()).items()}
    except SystemExit as exc:
        loaded = {"error": str(exc)}
    in_file = {
        team["team_id"].lower(): name
        for name, body in sections.items()
        if isinstance(body.get("teams"), list)
        for team in body["teams"]
        if isinstance(team, dict) and isinstance(team.get("team_id"), str)
    }
    r.check(
        "every decided team loads under its own section",
        in_file and loaded == in_file,
        f"{len(loaded)} loaded, {len(in_file)} in the file",
    )
    sizes = Counter(in_file.values())
    shrunk = {name: (sizes[name], floor) for name, floor in DECISION_FLOORS.items() if sizes[name] < floor}
    r.check(
        "no section of the owner's decisions has fewer teams than recorded",
        not shrunk,
        f"section: (teams now, recorded floor) {shrunk}",
    )
    with mock.patch.object(fbc, "OWNER_DECISIONS", fbc.OWNER_DECISIONS.with_name("no_such_file.json")):
        try:
            fbc.load_owner_decisions(_Recorder())
            stopped = False
        except SystemExit:
            stopped = True
    r.check("a missing decisions file stops the run instead of reading as empty", stopped, "load_owner_decisions")


def _decided_id() -> str | None:
    from scripts import fix_band_cohorts as fbc

    try:
        sections = json.loads(fbc.OWNER_DECISIONS.read_text(encoding="utf-8-sig"))
        return next(team["team_id"].lower() for body in sections.values() for team in body["teams"])
    except (OSError, ValueError, KeyError, StopIteration, AttributeError, TypeError):
        return None


def _plan(folder: Path, team_id: str) -> Path:
    from scripts import fix_band_cohorts as fbc

    row = dict.fromkeys(fbc.PLAN_FIELDS, "")
    row.update(
        team_id_master=team_id,
        team_name="Club Blue",
        old_age_group="u13",
        new_age_group="u12",
        action="would_update",
    )
    path = folder / f"plan_{team_id[:8]}.csv"
    fbc.write_csv([row], path, fbc.PLAN_FIELDS)
    return path


def _run_applier(folder: Path, *flags: str) -> _Recorder:
    from scripts import fix_band_cohorts as fbc

    recorder = _Recorder()
    argv = ["fix_band_cohorts.py", *flags, "--exports-dir", str(folder)]
    with _offline(recorder, argv=argv), contextlib.redirect_stdout(io.StringIO()):
        fbc.main()
    return recorder


def check_applier(r: Result) -> None:
    """The age applier's command line against the recorder: a dry run writes nothing, --dry-run beats
    --execute, an apply and its undo filter on the values they expect, and the owner's hold."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        plan = _plan(folder, LIVE_ID)

        dry = _run_applier(folder, "--apply", str(plan))
        r.check("the applier writes nothing without --execute", not dry.writes, f"writes: {dry.writes}")
        forced = _run_applier(folder, "--apply", str(plan), "--execute", "--dry-run")
        r.check("--dry-run wins over --execute", not forced.writes, f"writes: {forced.writes}")

        applied = _run_applier(folder, "--apply", str(plan), "--execute")
        want = [
            (
                "teams",
                {"age_group": "u12"},
                [("age_group", "u13"), ("is_deprecated", False), ("team_id_master", LIVE_ID)],
            )
        ]
        r.check(
            "an apply writes only to a live team still holding the planned old age group",
            applied.writes == want,
            f"writes: {applied.writes}",
        )

        from scripts.fix_band_cohorts import read_our_csv

        logs = sorted(folder.glob("fix_band_cohorts_apply_*.csv"))
        executed = [log for log in logs if any(row.get("result") == "updated" for row in read_our_csv(log))]
        undone = _run_applier(folder, "--revert", str(executed[-1]), "--execute") if executed else _Recorder()
        want = [("teams", {"age_group": "u13"}, [("age_group", "u12"), ("team_id_master", LIVE_ID)])]
        r.check(
            "an undo restores only a team still holding what the apply wrote",
            undone.writes == want,
            f"writes: {undone.writes}",
        )

        decided = _decided_id()
        held = _run_applier(folder, "--apply", str(_plan(folder, decided)), "--execute") if decided else None
        r.check(
            "the applier holds a team the owner decided to leave",
            held is not None and not held.writes,
            f"decided team {decided}; writes: {held.writes if held else 'no decided team to try'}",
        )


def _reconcile_log(folder: Path, decided: str | None) -> Path:
    """A reconcile log flagging the decided team and two live ones, each one group younger on GotSport.
    Two, so a count of the teams flagged cannot be read as the count left out."""
    from scripts import fix_band_cohorts as fbc

    rows = [
        {
            "run_mode": "execute",
            "team_id_master": tid,
            "stored_age_group": "u14",
            "gotsport_age_group": "u13",
            "stored_gender": "",
            "gotsport_gender": "",
        }
        for tid in (decided or "", LIVE_ID, OTHER_LIVE_ID)
    ]
    path = folder / "reconcile_teams_with_gotsport_20260101_000000.csv"
    fbc.write_csv(rows, path, list(rows[0]))
    return path


def _left_out(r: Result, tool: str, recorder: _Recorder, decided: str | None, reported: re.Match | None) -> None:
    asked = recorder.asked("teams", "team_id_master")
    r.check(f"{tool} reads a pending team live", LIVE_ID in asked, f"read live {sorted(asked)}")
    r.check(
        f"{tool} leaves a decided team out of its live read",
        decided is not None and decided not in asked,
        f"decided team {decided}; read live {sorted(asked)}",
    )
    r.check(
        f"{tool} reports the decided team it left out",
        reported is not None and reported.group(1) == "1",
        f"reported left out: {reported.group(1) if reported else 'nothing'}",
    )


def check_recheck(r: Result) -> None:
    """The weekly re-check loads the owner's decisions and leaves those teams out before its live read."""
    from scripts import weekly_age_recheck

    decided = _decided_id()
    recorder, out = _Recorder(), io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        _reconcile_log(folder, decided)
        with _offline(recorder), contextlib.redirect_stdout(out):
            weekly_age_recheck.main(folder)
    _left_out(r, "the weekly re-check", recorder, decided, RECHECK_LEFT_OUT.search(out.getvalue()))


def check_triage(r: Result) -> None:
    """The GotSport triage leaves a decided team out, and never objects to a name the applier lets through."""
    from scripts import fix_band_cohorts as fbc
    from src.utils.team_utils import _soccer_season_year

    triage = _module(TRIAGE, "triage_reconcile")
    decided = _decided_id()
    recorder, out = _Recorder(), io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        argv = ["triage_reconcile.py", "--log", str(_reconcile_log(folder, decided)), "--exports-dir", str(folder)]
        with _offline(recorder, triage, argv=argv), contextlib.redirect_stdout(out):
            triage.main()
    _left_out(r, "the triage", recorder, decided, TRIAGE_LEFT_OUT.search(out.getvalue()))

    def assess(name: str, gotsport: str, tid: str = LIVE_ID, declined: dict | None = None):
        team = {"team_id_master": tid, "team_name": name, "age_group": "u15" if gotsport == "u14" else "u14"}
        row = {"gotsport_age_group": gotsport, "gotsport_gender": ""}
        return triage.assess(_Recorder(), row, team, [tid], "", "", declined or {})

    r.check(
        "the triage passes over a team the owner decided to leave",
        decided is not None and assess("Club Blue", "u13", decided, {decided: ("left_held", "")}) is None,
        f"assess(...) for decided team {decided}, whose ages differ",
    )
    r.check(
        "the triage and the applier share one cohort_years",
        triage.cohort_years is fbc.cohort_years,
        "triage_reconcile.cohort_years is fix_band_cohorts.cohort_years",
    )
    season = _soccer_season_year()
    samples = [
        (f"Club {season - 17} Boys", "u19"),
        (f"Club {season - 16} Boys", "u19"),
        (f"Club {(season - 12) % 100:02d}B Blue", "u13"),
        (f"Club {season - 13}/{(season - 12) % 100:02d} Elite", "u13"),
        (f"Club {(season - 18) % 100:02d}/{(season - 17) % 100:02d} Boys", "u19"),
        # U-ages, not birth years: both tools blank them before reading years.
        ("Town-G09A-Coach", "u10"),
        ("Club U/10B Blue", "u10"),
    ]
    # The applier's hold is the stricter reading: a name can pass the triage and be held at apply,
    # never the reverse. The rows carry no GotSport name, so only the name's years can set the
    # triage's same_squad to False.
    reversed_ = [
        (name, target)
        for name, target in samples
        if not fbc.name_contradiction(name, target) and assess(name, target)["same_squad"] == "False"
    ]
    r.check(
        "no name the applier lets through is one the triage reads as another squad",
        not reversed_,
        f"applier passes, triage objects: {reversed_}",
    )


def check_name_rules(r: Result) -> None:
    """u19 holds the U18 birth year, so a name with it is no reason to hold a move into u19."""
    from scripts import fix_band_cohorts as fbc
    from src.utils.team_utils import _soccer_season_year

    season = _soccer_season_year()
    r.check(
        "u19 holds three birth years, U18's included",
        fbc.cohort_years(19) == {season - 19, season - 18, season - 17},
        f"cohort_years(19) -> {sorted(fbc.cohort_years(19))}",
    )
    u18_name, u17_name = f"Club {season - 17} Boys", f"Club {season - 16} Boys"
    r.check(
        "a U18 birth year in the name does not hold a move into u19",
        fbc.name_contradiction(u18_name, "u19") == "",
        f"name_contradiction({u18_name!r}, 'u19') -> {fbc.name_contradiction(u18_name, 'u19')!r}",
    )
    r.check(
        "a U17 birth year in the name still holds a move into u19",
        fbc.name_contradiction(u17_name, "u19") != "",
        f"name_contradiction({u17_name!r}, 'u19') -> ''",
    )


def check_band_spellings(r: Result) -> None:
    """Apostrophe bands are read, and an aged-out band keeps its text but still reads as u19."""
    from scripts.fix_band_cohorts import band_of
    from scripts.normalize_team_names import normalize_team_name
    from src.utils.team_utils import _soccer_season_year, calculate_age_group_from_band, extract_band_birth_year

    for name in ("Club '11/'12 Blue", "Club ‘11/‘12 Blue"):
        group = (calculate_age_group_from_band(2012) or "").lower()
        r.check(
            f"an apostrophe band is read: {name}",
            extract_band_birth_year(name) == 2012 and band_of(name) == group,
            f"extract_band_birth_year -> {extract_band_birth_year(name)}; band_of -> {band_of(name)!r}",
        )
    younger = _soccer_season_year() - 19
    aged_out = f"Club {younger - 1}/{younger} Red"
    r.check(
        "the name tidy-up leaves the aged-out band as written",
        normalize_team_name(aged_out, None, "u20") == aged_out,
        f"normalize_team_name({aged_out!r}) -> {normalize_team_name(aged_out, None, 'u20')!r}",
    )
    r.check(
        "an aged-out band still reads as u19 to the applier, so its refusals hold",
        band_of(aged_out) == "u19",
        f"band_of({aged_out!r}) -> {band_of(aged_out)!r}",
    )


def _derivation_steps(folder: Path):
    """(workflow, job, step, the workflow's, job's and step's env) for each step running the derivation."""
    for workflow in sorted([*folder.glob("*.yml"), *folder.glob("*.yaml")]):
        text = workflow.read_text(encoding="utf-8")
        if DERIVATION not in text:
            continue
        doc = yaml.safe_load(text) or {}
        for job_name, job in (doc.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                if DERIVATION in str(step.get("run", "")):
                    scopes = (doc.get("env") or {}, job.get("env") or {}, step.get("env") or {})
                    yield workflow, job_name, step, scopes


def _top_level(expr: str, operator: str) -> list[str]:
    """``expr`` split on ``operator`` wherever it sits outside every bracket and string."""
    parts, depth, quote, start, i = [], 0, None, 0, 0
    while i < len(expr):
        char = expr[i]
        if quote:
            quote = None if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif depth == 0 and expr.startswith(operator, i):
            parts.append(expr[start:i])
            start = i = i + len(operator)
            continue
        i += 1
    return [part.strip() for part in [*parts, expr[start:]]]


def _unwrap(part: str) -> str:
    while part.startswith("(") and part.endswith(")"):
        part = part[1:-1].strip()
    return part


def _gated_on_the_flag(condition) -> bool:
    """True when a step's ``if:`` lets it run only with the flag 'true': the comparison is one of the
    expression's top-level ``&&`` terms and nothing is joined to it by a top-level ``||``, or the step is
    switched off outright. Any other shape reads as ungated."""
    expr = str(condition if condition is not None else "").strip()
    if expr.startswith("${{") and expr.endswith("}}"):
        expr = expr[3:-2].strip()
    if expr.lower() == "false":
        return True
    if len(_top_level(expr, "||")) > 1:
        return False
    return any(DERIVATION_GATE.fullmatch(_unwrap(term)) for term in _top_level(expr, "&&"))


def check_derivation_off(r: Result) -> None:
    """The wall-clock age derivation stays off in every workflow step that runs it."""
    steps = list(_derivation_steps(WORKFLOWS))
    r.check(
        f"a workflow step running {DERIVATION} is found",
        steps,
        f"{len(steps)} step(s) under {WORKFLOWS.name} run {DERIVATION}",
    )
    for workflow, job, step, scopes in steps:
        where = f"{workflow.name} {job}/{step.get('name') or step.get('id') or '?'}"
        r.check(
            f"{where} runs only when {DERIVATION_FLAG} is 'true'",
            _gated_on_the_flag(step.get("if")),
            f"if: {step.get('if')!r}",
        )
        # GitHub hands every env value to the step as a string; YAML reads an unquoted false as a bool.
        # Each level that sets the flag must say 'false', whichever of them the gate reads, and one must set it.
        values = [scope[DERIVATION_FLAG] for scope in scopes if DERIVATION_FLAG in scope]
        r.check(
            f"{DERIVATION_FLAG} is 'false' for {where}",
            values and all(str(value).lower() == "false" for value in values),
            f"{DERIVATION_FLAG} set to {values!r} (workflow, job, step)",
        )


CHECKS = [
    check_chart,
    check_label_key,
    check_boards,
    check_rolled_season,
    check_owner_decisions,
    check_applier,
    check_recheck,
    check_triage,
    check_name_rules,
    check_band_spellings,
    check_derivation_off,
]


def render(result: Result) -> None:
    print("\nASSERTIONS -- each FAIL is a claim or an agreement that no longer holds\n")
    for item in result.assertions:
        print(f"  {'PASS' if item['ok'] else 'FAIL'}  {item['name']}")
        if not item["ok"]:
            print(f"        {item['detail']}")
    print()
    if result.failures:
        print(f"{len(result.failures)} assertion(s) failed. Fix the code or update the skill, whichever moved.")
    else:
        print("Every assertion holds.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the age-group skill's claims")
    parser.add_argument("--code-only", action="store_true", help="Accepted for symmetry; nothing reads the database")
    parser.add_argument("--json", action="store_true", help="Emit the raw result")
    args = parser.parse_args()

    result = Result()
    for check in CHECKS:
        try:
            check(result)
        except (Exception, SystemExit) as exc:
            result.check(f"{check.__name__} runs to the end", False, f"{type(exc).__name__}: {exc}")

    if args.json:
        print(json.dumps({"assertions": result.assertions}, indent=1))
    else:
        render(result)
    return 1 if result.failures else 0


if __name__ == "__main__":
    sys.exit(main())
