#!/usr/bin/env python3
"""Assert the claims that .claude/skills/reconcile-gotsport makes about this repo.

That skill reconciles teams against GotSport and then writes genders, names, age groups and whole
blocks of games. Its guidance rests on claims about code behaviour: what the reconcile reads and
leaves alone, how its log feeds the triage and the bulk lane, and which guards, logs and undo commands
each write carries. Prose claims cannot fail, so they rot silently.

This script makes those claims executable. Run it before trusting the skill.

ASSERTIONS fail the run. A failure means a documented claim, or an agreement between two of the tools
that pass files to each other, no longer holds, or that a check stopped; the detail line says which.
NOT VERIFIED lists the claims no code settles; they never fail the run.

Nothing reads the database or the network: each tool runs its own entry point against an in-memory
stand-in with blank credentials, GotSport answers in-process, the tools archive_split.py would start
run in this process instead, every other process start, name lookup and connection off this machine is
refused at the audit event the interpreter raises for it, and every log lands in a temporary folder.
--code-only therefore changes nothing.

Usage:
    python scripts/check_reconcile_skill_assumptions.py               # everything
    python scripts/check_reconcile_skill_assumptions.py --code-only   # accepted; changes nothing
    python scripts/check_reconcile_skill_assumptions.py --json
"""

from __future__ import annotations

import contextlib
import fnmatch
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.skill_check_offline import (  # noqa: E402
    Database,
    Result,
    csv_rows,
    guarded,
    run_checks,
    run_main,
    run_with_anon_key,
)

SKILL_SCRIPTS = ROOT / ".claude" / "skills" / "reconcile-gotsport" / "scripts"
TRIAGE = SKILL_SCRIPTS / "triage_reconcile.py"
APPLY_FIELDS = SKILL_SCRIPTS / "apply_team_fields.py"
ARCHIVE = SKILL_SCRIPTS / "archive_split.py"
# Step 1's command, as the skill gives it.
STEP_ONE = ("--age-group", "u10,u11", "--state", "AZ", "--limit", "0")
# What the triage writes, each name less its timestamp.
TRIAGE_OUTPUTS = {
    "reconcile_triage",
    "reconcile_triage_relabel_age_plan",
    "reconcile_triage_reused_id_age_plan",
    "reconcile_triage_gender_plan",
}
# Each tool archive_split.py runs, and the pattern its log's name matches.
STEP_SIX_TOOLS = {
    "reassign_games_between_teams.py": "reassign_games_between_teams_*.csv",
    "apply_team_fields.py": "apply_team_fields_*.csv",
    "fix_band_cohorts.py": "fix_band_cohorts_apply_*.csv",
}
ARCHIVE_LOGS = {
    "games_log": "reassign_games_between_teams.py",
    "rename_log": "apply_team_fields.py",
    "relabel_log": "fix_band_cohorts.py",
}

GOTSPORT = "provider-gotsport"
BLUE, RED, WHITE, GOLD, OPPONENT, OLD_SQUAD = (f"dddddddd-0000-4000-8000-{n:012d}" for n in range(1, 7))
# The columns of each table the tools read or write, and the arguments of each function they call, as
# production defines them: the migrations, plus teams.team_name_original, which no migration creates.
COLUMNS = {
    "teams": (
        "team_id_master",
        "team_name",
        "team_name_original",
        "club_name",
        "state_code",
        "age_group",
        "gender",
        "state_source",
        "state_confidence",
        "provider_id",
        "provider_team_id",
        "is_deprecated",
    ),
    "team_alias_map": ("team_id_master", "provider_team_id", "provider_id", "review_status"),
    "providers": ("id", "code"),
    "team_state_audit": ("team_id_master", "action", "old_state_code"),
    "team_merge_map": ("deprecated_team_id", "canonical_team_id"),
    "games": (
        "id",
        "game_date",
        "home_team_master_id",
        "away_team_master_id",
        "home_score",
        "away_score",
        "competition",
        "is_excluded",
    ),
    "rankings_full": ("team_id", "state_code"),
}
FUNCTIONS = {
    "apply_team_state": (
        "p_team_id",
        "p_expected_state_code",
        "p_state_code",
        "p_source",
        "p_confidence",
        "p_actor",
        "p_action",
        "p_reason",
    ),
    "unlink_game_team": ("p_game_id", "p_team_id_master", "p_is_home_team"),
    "link_game_team": ("p_game_id", "p_team_id_master", "p_is_home_team"),
}

UNVERIFIED = [
    (
        "Step 1: a long walk costs about --delay + 0.35 s per lookup",
        "The code pauses --delay (3 s unless set) before each lookup and then waits on one request with a "
        "15 s timeout and no retry, which is asserted; how long GotSport takes to answer is not code. The "
        "scraper-patterns skill measured the rate across every state in September 2026. Time a run before "
        "quoting a duration.",
    ),
    (
        "Step 1: a stop on consecutive failed lookups usually means GotSport's WAF is blocking",
        "The stop itself is asserted (exit code 75 after --abort-after failed lookups in a row); whether "
        "GotSport refused or the network failed is not code.",
    ),
    (
        'Reviewing the weekly re-check: the Windows task "PitchRank Weekly Age-Group Recheck" runs every Tuesday',
        'Task Scheduler holds this, not the repo. Check with: schtasks /query /tn "PitchRank Weekly Age-Group '
        'Recheck" /v',
    ),
    (
        "The bulk lane's figures: 99.3% of 12,083 corrections, and about one game in six against a band-named opponent",
        "Measurements of past data, not code.",
    ),
]


@dataclass
class Reconcile:
    code: int
    output: str
    log: Path | None
    pauses: list[float]


class _Answer:
    def __init__(self, payload: dict | None):
        self.payload = payload
        self.status_code = 404 if payload is None else 200
        self.content = json.dumps(payload).encode() if payload else b""

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class GotSport:
    """GotSport's team_details as the resolver's session meets it: one JSON answer per known team id, a
    404 for any other, and a refused connection for an id marked down. Records each request."""

    def __init__(self, answers: dict | None = None, down=()):
        self.answers, self.down, self.requests = dict(answers or {}), set(down), []

    def get(self, url, params=None, timeout=None):
        team_id = params["team_id"]
        self.requests.append((team_id, timeout))
        if team_id in self.down:
            raise requests.ConnectionError("refused")
        return _Answer(self.answers.get(team_id))


def details(name: str, age_group: str, gender: str = "Boys", club: str = "Phoenix Rising") -> dict:
    """A team_details body as GotSport sends it."""
    return {
        "name": name,
        "club_name": club,
        "team_association": "AZ",
        "display_age_group": age_group.upper(),
        "display_gender": gender,
    }


def _season() -> int:
    from src.utils.team_utils import _soccer_season_year

    return _soccer_season_year()


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _team(team_id, name, age_group, provider_team_id, state="AZ", club="Phoenix Rising", gender="Male"):
    return {
        "team_id_master": team_id,
        "team_name": name,
        "team_name_original": None,
        "club_name": club,
        "state_code": state,
        "age_group": age_group,
        "gender": gender,
        "state_source": None,
        "state_confidence": None,
        "provider_id": GOTSPORT,
        "provider_team_id": provider_team_id,
        "is_deprecated": False,
    }


def _move_side(team_of):
    def call(db, params):
        game = db.row("games", id=params["p_game_id"])
        side = "home_team_master_id" if params["p_is_home_team"] else "away_team_master_id"
        game[side] = team_of(params)
        return [{"game_id": game["id"]}]

    return call


def _apply_team_state(db, params):
    """apply_team_state's compare-and-set: the state lands only on a team still holding the expected one."""
    team = db.row("teams", team_id_master=params["p_team_id"])
    if team["state_code"] != params["p_expected_state_code"]:
        return []
    team["state_code"] = params["p_state_code"]
    return [{"team_id_master": team["team_id_master"]}]


def world(teams: list[dict], games: list[dict] = ()) -> Database:
    """``teams`` live, each that has a provider_team_id given an approved GotSport alias to it, and ``games``."""
    aliases = [
        {
            "team_id_master": team["team_id_master"],
            "provider_team_id": team["provider_team_id"],
            "provider_id": GOTSPORT,
            "review_status": "approved",
        }
        for team in teams
        if team["provider_team_id"]
    ]
    tables = {
        "teams": teams,
        "team_alias_map": aliases,
        "providers": [{"id": GOTSPORT, "code": "gotsport"}],
        "team_state_audit": [],
        "team_merge_map": [],
        "games": list(games),
        "rankings_full": [],
    }
    rpcs = {
        "apply_team_state": _apply_team_state,
        "unlink_game_team": _move_side(lambda params: None),
        "link_game_team": _move_side(lambda params: params["p_team_id_master"]),
    }
    return Database(tables, COLUMNS, FUNCTIONS, defaults={"teams": {"is_deprecated": False}}, rpcs=rpcs)


def reconcile_run(db: Database, gotsport: GotSport, folder: Path, *args: str) -> Reconcile:
    """Run the reconcile's command line against ``db``, its lookups answered by ``gotsport`` through the
    real resolver and its pauses recorded rather than slept."""
    from scripts import reconcile_teams_with_gotsport as reconcile
    from src.utils.gotsport_team_details import TeamDetailsResolver

    pauses = []

    def resolver():
        made = TeamDetailsResolver()
        made.session = gotsport
        return made

    with (
        mock.patch.object(reconcile, "TeamDetailsResolver", resolver),
        mock.patch.object(reconcile, "time", SimpleNamespace(sleep=pauses.append)),
    ):
        code, output = run_main(db, reconcile, *args, "--exports-dir", str(folder))
    logs = sorted(folder.glob("reconcile_teams_with_gotsport_*.csv"))
    return Reconcile(code, output, logs[-1] if logs else None, pauses)


def _stem(path: Path) -> str:
    """A file's name less its extension and its _YYYYMMDD_HHMMSS timestamp."""
    return path.stem.rsplit("_", 2)[0]


def _slice() -> tuple[Database, GotSport]:
    """Arizona's u10 and u11 teams, one with no stored state; GotSport renames one, files one a group
    older, and agrees with the other two."""
    teams = [
        _team(BLUE, "Phoenix Rising Blue", "u10", "101"),
        _team(RED, "Phoenix Rising Red", "u10", "102"),
        _team(WHITE, "Phoenix Rising White", "u10", "103", state=None),
        _team(GOLD, "Phoenix Rising Gold", "u11", "104"),
    ]
    answers = {
        "101": details("PR Blue", "u10"),
        "102": details("Phoenix Rising U11 Red", "u11"),
        "103": details("Phoenix Rising White", "u10"),
        "104": details("Phoenix Rising Gold", "u11"),
    }
    return world(teams), GotSport(answers)


def check_step_one(r: Result) -> None:
    """Step 1's command reads the slice, writes nothing without --execute, and logs every team."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        db, gotsport = _slice()
        forced, executed = db.copy(), db.copy()
        run = reconcile_run(db, gotsport, folder / "read", *STEP_ONE)
        rows = csv_rows(run.log)
        examined = {row["team_id_master"] for row in rows}
        r.check(
            "Step 1 examines each team of the slice whose stored state is in --state, and no team with none",
            examined == {BLUE, RED, GOLD},
            f"examined {sorted(examined)}",
        )
        r.check("Step 1 without --execute writes nothing to the database", not db.writes, f"writes: {db.writes}")
        records = {alias["team_id_master"]: alias["provider_team_id"] for alias in db.tables["team_alias_map"]}
        looked_up = {team_id for team_id, _ in gotsport.requests}
        r.check(
            "Step 1 logs every team it looked up to --exports-dir, as a dry run",
            {records[row["team_id_master"]] for row in rows} == looked_up
            and {row["run_mode"] for row in rows} == {"dry-run"},
            f"looked up {sorted(looked_up)}; logged {[(row['provider_team_id'], row['run_mode']) for row in rows]}",
        )
        reconcile_run(forced, GotSport(gotsport.answers), folder / "forced", *STEP_ONE, "--execute", "--dry-run")
        r.check("--dry-run wins over --execute", not forced.writes, f"writes: {forced.writes}")
        reconcile_run(executed, GotSport(gotsport.answers), folder / "executed", *STEP_ONE, "--execute")
        want = [
            (
                "teams",
                {"team_name": "PR Blue"},
                [("is_deprecated", False), ("team_id_master", BLUE), ("team_name", "Phoenix Rising Blue")],
            )
        ]
        renames = [write for write in executed.updates() if "team_name" in write[1]]
        r.check(
            "with --execute a rename goes only to a live team still holding the name read, and none to a team "
            "GotSport files in another age group",
            renames == want,
            f"renames: {renames}",
        )

    many = world([_team(f"eeeeeeee-0000-4000-8000-{n:012d}", f"Team {n}", "u10", None) for n in range(501)])
    with tempfile.TemporaryDirectory() as tmp:
        capped = len(csv_rows(reconcile_run(many, GotSport(), Path(tmp) / "capped", "--state", "AZ").log))
        whole = len(csv_rows(reconcile_run(many, GotSport(), Path(tmp) / "whole", "--state", "AZ", "--limit", "0").log))
    r.check(
        "--limit 0 examines the whole slice, where the default stops at 500 teams",
        (capped, whole) == (500, 501),
        f"501 teams in the slice: {capped} examined by default, {whole} with --limit 0",
    )


def check_lookups(r: Result) -> None:
    """Each lookup is one paced request with a bounded wait, and a run of failures stops the run."""
    from src.utils.gotsport_team_details import TeamDetailsResolver

    with tempfile.TemporaryDirectory() as tmp:
        db, gotsport = _slice()
        run = reconcile_run(db, gotsport, Path(tmp), *STEP_ONE)
    asked = sorted(team_id for team_id, _ in gotsport.requests)
    r.check(
        "each lookup pauses --delay, 3 s unless set, and then sends GotSport one request",
        run.pauses == [3.0] * 3 and asked == ["101", "102", "104"],
        f"pauses {run.pauses}; requests for {asked}",
    )

    waits = sorted({timeout for _, timeout in gotsport.requests})
    down = GotSport(down={"101"})
    resolver = TeamDetailsResolver()
    resolver.session = down
    with guarded():
        answer = resolver.resolve("101")
    r.check(
        "a GotSport request waits at most 15 s and is not retried",
        waits == [15] and answer == {} and down.requests == [("101", 15)],
        f"the reconcile's requests wait {waits} s; resolve -> {answer}; requests {down.requests}",
    )

    # Nine failures, a 404, nine failures, an answer, then failures: only the last are in a row, and the
    # tenth of them is the thirtieth of 33 teams, so a run that does not stop there asks for more.
    ids = [str(500 + n) for n in range(33)]
    teams = [_team(f"ffffffff-0000-4000-8000-{n:012d}", f"Team {n}", "u10", pid) for n, pid in enumerate(ids)]
    blocked = GotSport({ids[19]: details("Team 19", "u10")}, down=set(ids) - {ids[9], ids[19]})
    with tempfile.TemporaryDirectory() as tmp:
        run = reconcile_run(world(teams), blocked, Path(tmp), *STEP_ONE)
        logged = len(csv_rows(run.log))
    r.check(
        "ten failed lookups in a row stop the reconcile with exit code 75, its log written",
        run.code == 75 and len(blocked.requests) == 30 and logged == 30,
        f"exit {run.code}; {len(blocked.requests)} requests for {len(ids)} teams; {logged} rows logged",
    )


def check_decide(r: Result) -> None:
    """What the reconcile takes from GotSport and what it only reports."""
    from scripts import reconcile_teams_with_gotsport as reconcile
    from scripts.fix_band_cohorts import cohort_years

    year = max(cohort_years(10))

    def decided(ours: str, theirs: str, team: dict | None = None, **resolved):
        stored = {
            "team_id_master": BLUE,
            "team_name": ours,
            "club_name": "Phoenix Rising",
            "state_code": "AZ",
            "age_group": "u10",
            "gender": "Male",
            **(team or {}),
        }
        answer = {"name": theirs, "club_name": "Phoenix Rising", "state_code": "AZ", "age_group": "u10", **resolved}
        return reconcile.decide(stored, "101", {"gender": "Male", **answer}, "resolved")

    taken = decided("Phoenix Rising Blue", "PR Blue")
    r.check(
        "with --execute the reconcile takes GotSport's name where both file the team in one age group",
        taken.updates == {"team_name": "PR Blue"},
        f"updates {taken.updates}",
    )
    other = decided("Phoenix Rising Blue", "Phoenix Rising U11 Blue", age_group="u11")
    r.check(
        "a rename is withheld, and shown in blocked_fields, where GotSport files the team in another age group",
        "team_name" not in other.updates and "team_name" in other.blocked,
        f"updates {other.updates}; blocked {other.blocked}",
    )
    traded = {theirs: decided(f"Phoenix Rising {year} Blue", theirs) for theirs in ("U12 Boys Blue", "Boys Blue")}
    r.check(
        "a rename is withheld where our name's birth year fits our age group and GotSport's states another "
        "age or no number",
        all("team_name" in d.blocked and "team_name" not in d.updates for d in traded.values()),
        {theirs: (d.updates, d.blocked) for theirs, d in traded.items()},
    )
    retired = {
        name: decided("Phoenix Rising Blue", name)
        for name in ("zz old - Phoenix Rising Blue", "Phoenix Rising Blue DO NOT USE", "Inactive Phoenix Rising")
    }
    r.check(
        "a GotSport name marking a retired registration is never taken, and is blank in the log",
        all(
            "team_name" not in d.updates and reconcile.log_row(d, "dry-run")["gotsport_team_name"] == ""
            for d in retired.values()
        ),
        {name: (d.updates, reconcile.log_row(d, "dry-run")["gotsport_team_name"]) for name, d in retired.items()},
    )
    filled = decided("Phoenix Rising Blue", "Phoenix Rising Blue", team={"club_name": "", "state_code": ""})
    differ = decided("Phoenix Rising Blue", "Phoenix Rising Blue", club_name="Phoenix Rising FC", state_code="NM")
    r.check(
        "club and state are filled only where ours is blank; a disagreement is reported, not written",
        filled.updates == {"club_name": "Phoenix Rising", "state_code": "AZ"}
        and differ.updates == {}
        and set(differ.conflicts) == {"club_name", "state_code"},
        f"blank: {filled.updates}; disagreeing: updates {differ.updates}, conflicts {differ.conflicts}",
    )
    blank = world([_team(WHITE, "Phoenix Rising White", "u10", "103", state=None, club=None)])
    with tempfile.TemporaryDirectory() as tmp:
        answers = {"103": details("Phoenix Rising White", "u10")}
        reconcile_run(blank, GotSport(answers), Path(tmp), "--age-group", "u10", "--execute")
    club = [("club_name", "is", None), ("is_deprecated", False), ("team_id_master", WHITE)]
    states = [
        (c["payload"]["p_team_id"], c["payload"]["p_expected_state_code"], c["payload"]["p_state_code"])
        for c in blank.writes
        if c["kind"] == "rpc"
    ]
    r.check(
        "with --execute a blank club is filled only on a live team still blank, and a blank state through "
        "apply_team_state, expecting it blank, and onto the board",
        [w for w in blank.updates() if w[0] == "teams"] == [("teams", {"club_name": "Phoenix Rising"}, club)]
        and states == [(WHITE, None, "AZ")]
        and [w for w in blank.updates() if w[0] == "rankings_full"]
        == [("rankings_full", {"state_code": "AZ"}, [("team_id", WHITE)])],
        f"writes: {[(w.get('table') or w.get('function'), w['payload']) for w in blank.writes]}",
    )
    reported = decided(
        "Phoenix Rising Blue", "Phoenix Rising Blue", team={"club_name": ""}, age_group="u11", gender="Female"
    )
    r.check(
        "age group and gender are logged, never written",
        set(reported.updates) == {"club_name"},
        f"updates {reported.updates}",
    )


def check_triage(r: Result) -> None:
    """Step 1's read-only log feeds the triage, which writes nothing; only an --execute log feeds the
    bulk lane."""
    from scripts.fix_band_cohorts import derive_candidates

    season = _season()
    teams = [
        _team(BLUE, "Phoenix Rising Blue", "u13", "201"),
        _team(GOLD, "Phoenix Rising Gold", "u13", "202"),
    ]
    answers = {
        "201": details(f"Phoenix Rising {season - 12}/{season - 11} Blue", "u12"),
        "202": details("Phoenix Rising Gold", "u13"),
    }
    step_one = ("--age-group", "u13", "--state", "AZ", "--limit", "0")
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        db = world(teams)
        triaged_db, executed = db.copy(), db.copy()
        read = reconcile_run(db, GotSport(answers), folder / "read", *step_one)
        triage = _module(TRIAGE, "triage_reconcile")
        run_main(triaged_db, triage, "--log", str(read.log), "--exports-dir", str(folder / "triage"))
        written = sorted((folder / "triage").glob("*"))
        triaged = [
            row["team_id_master"] for path in written if _stem(path) == "reconcile_triage" for row in csv_rows(path)
        ]
        r.check(
            "the triage reads Step 1's read-only log: it triages the team GotSport files in another age group "
            "and no other",
            triaged == [BLUE],
            f"triaged {triaged}",
        )
        r.check("the triage writes nothing to the database", not triaged_db.writes, f"writes: {triaged_db.writes}")
        r.check(
            "the triage writes its CSV and its three plans to --exports-dir",
            sorted(_stem(path) for path in written) == sorted(TRIAGE_OUTPUTS),
            f"wrote {[path.name for path in written]}",
        )
        with contextlib.redirect_stdout(io.StringIO()):
            from_read = derive_candidates(folder / "read")
        r.check(
            "Step 1's read-only log adds no candidate to the bulk lane",
            from_read == [],
            f"candidates {[c['team_id_master'] for c in from_read]}",
        )
        reconcile_run(executed, GotSport(answers), folder / "executed", *step_one, "--execute")
        with contextlib.redirect_stdout(io.StringIO()):
            from_executed = [c["team_id_master"] for c in derive_candidates(folder / "executed")]
        r.check(
            "an --execute reconcile's log gives the bulk lane the team GotSport files younger by its band",
            from_executed == [BLUE],
            f"candidates {from_executed}",
        )


def check_triage_plans(r: Result) -> None:
    """The triage's plans are files the two appliers read as the skill says."""
    from scripts import fix_band_cohorts as fbc

    triage = _module(TRIAGE, "triage_reconcile")
    fields = _module(APPLY_FIELDS, "apply_team_fields")
    base = dict.fromkeys(triage.TRIAGE_FIELDS, "")
    shared = {
        "club_name": "Phoenix Rising",
        "state_code": "AZ",
        "gender": "Male",
        "stored_age_group": "u13",
        "gotsport_age_group": "u12",
    }
    out = [
        {
            **base,
            **shared,
            "class": "relabel",
            "team_id_master": BLUE,
            "team_name": "Phoenix Rising Blue",
            "gotsport_gender": "Male",
        },
        {
            **base,
            **shared,
            "class": "reused_id",
            "team_id_master": RED,
            "team_name": "Phoenix Rising Red",
            "gotsport_gender": "Male",
        },
        {
            **base,
            **shared,
            "class": "gender_fix",
            "team_id_master": GOLD,
            "team_name": "Phoenix Rising Gold",
            "gotsport_gender": "Female",
        },
    ]
    db = world(
        [_team(tid, name, "u13", None) for tid, name in ((BLUE, "Phoenix Rising Blue"), (RED, "Phoenix Rising Red"))]
    )
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        plans = triage.write_plans(out, "20260101_000000", folder)
        applied = {}
        for cls in ("relabel", "reused_id"):
            run_main(db, fbc, "--apply", str(plans[cls][0]), "--exports-dir", str(folder / cls))
            log = next(iter((folder / cls).glob("fix_band_cohorts_apply_*.csv")), None)
            applied[cls] = [(row["team_id_master"], row["result"]) for row in (fbc.read_our_csv(log) if log else [])]
        reused = [(row["team_id_master"], row["action"]) for row in fbc.read_our_csv(plans["reused_id"][0])]
        genders = [
            (row["team_id_master"], row["field"], row["old_value"], row["new_value"])
            for row in fields.read_rows(plans["gender"][0])
        ]
    r.check(
        "the triage's relabel rows reach the age applier as would_update",
        applied["relabel"] == [(BLUE, "would_update")],
        f"the applier's dry run logged {applied['relabel']}",
    )
    r.check(
        "the triage's reused-ID rows are pending_split, which the age applier skips",
        reused == [(RED, "pending_split")] and applied["reused_id"] == [],
        f"plan {reused}; the applier's dry run logged {applied['reused_id']}",
    )
    r.check(
        "the triage's gender plan is one apply_team_fields reads",
        genders == [(GOLD, "gender", "Male", "Female")],
        f"read {genders}",
    )


def check_apply_team_fields(r: Result) -> None:
    """apply_team_fields writes only with --execute, each write guarded on the value it replaces, logs
    first, and undoes only what still holds its write."""
    fields = _module(APPLY_FIELDS, "apply_team_fields")
    renamed = "Phoenix Rising 2014 Blue"
    plan_rows = [
        {
            "team_id_master": BLUE,
            "team_name": "Phoenix Rising Blue",
            "field": "gender",
            "old_value": "Male",
            "new_value": "Female",
        },
        {
            "team_id_master": BLUE,
            "team_name": "Phoenix Rising Blue",
            "field": "team_name",
            "old_value": "Phoenix Rising Blue",
            "new_value": renamed,
        },
    ]
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        plan = folder / "plan.csv"
        fields.write_rows(plan_rows, plan, list(fields.PLAN_COLUMNS))
        db = world([_team(BLUE, "Phoenix Rising Blue", "u13", None)])

        rehearsed, refused = db.copy(), db.copy()
        run_main(rehearsed, fields, "--plan", str(plan), "--exports-dir", str(folder / "dry"))
        r.check("apply_team_fields writes nothing without --execute", not rehearsed.writes, f"{rehearsed.writes}")

        unlogged = []

        def logged_yet(record: dict) -> None:
            if not any(folder.glob("run/*.csv")):
                unlogged.append(record)

        db.before_write.append(logged_yet)
        _, output = run_main(db, fields, "--plan", str(plan), "--execute", "--exports-dir", str(folder / "run"))
        guard = [("is_deprecated", False), ("team_id_master", BLUE)]
        want = [
            ("teams", {"gender": "Female"}, sorted([*guard, ("gender", "Male")], key=str)),
            ("teams", {"team_name": renamed}, sorted([*guard, ("team_name", "Phoenix Rising Blue")], key=str)),
        ]
        r.check(
            "apply_team_fields writes each field only to a live team still holding the value it replaces",
            db.updates() == want,
            f"writes: {db.updates()}",
        )
        r.check(
            "apply_team_fields logs before its first write and prints its undo command",
            db.writes and not unlogged and "Undo with --revert" in output,
            f"writes before a log: {len(unlogged)}; printed an undo: {'Undo with --revert' in output}",
        )

        undone = db.copy()
        log = next(iter((folder / "run").glob("apply_team_fields_*.csv")), None)
        run_main(undone, fields, "--revert", str(log), "--execute")
        want = [
            ("teams", {"team_name": "Phoenix Rising Blue"}, sorted([*guard, ("team_name", renamed)], key=str)),
            ("teams", {"gender": "Male"}, sorted([*guard, ("gender", "Female")], key=str)),
        ]
        # The team holds what the run wrote, so only the log's own results keep these two undos from
        # writing: a dry run's rows, and a re-run's rows an earlier run already applied.
        rehearsal_undone = db.copy()
        run_main(rehearsal_undone, fields, "--revert", str(next((folder / "dry").glob("*.csv"))), "--execute")
        rerun = db.copy()
        run_main(rerun, fields, "--plan", str(plan), "--execute", "--exports-dir", str(folder / "rerun"))
        rerun_undone = rerun.copy()
        run_main(rerun_undone, fields, "--revert", str(next((folder / "rerun").glob("*.csv"))), "--execute")
        r.check(
            "an undo restores each field, last write first, only while the team holds what the run wrote",
            undone.updates() == want and not rehearsal_undone.writes and not rerun_undone.writes,
            f"writes: {undone.updates()}; undoing the dry run's log: {rehearsal_undone.writes}; undoing a "
            f"re-run's log: {rerun_undone.writes}",
        )

        bad = folder / "bad.csv"
        fields.write_rows([{**plan_rows[0], "new_value": "Girls"}], bad, list(fields.PLAN_COLUMNS))
        code, _ = run_main(refused, fields, "--plan", str(bad), "--execute", "--exports-dir", str(folder / "bad"))
        r.check(
            "a gender other than Male or Female is refused before any write",
            code != 0 and not refused.writes,
            f"exit {code}; writes: {refused.writes}",
        )

        built, output = run_with_anon_key(
            fields, "--plan", str(plan), "--execute", "--exports-dir", str(folder / "anon")
        )
        refused_key = "SUPABASE_SERVICE_ROLE_KEY" in output
        r.check(
            "apply_team_fields --execute stops without a service-role key, before building a client",
            refused_key and not built,
            f"refused for want of the key: {refused_key}; clients built: {built}",
        )


class _InProcess:
    """Stands in for subprocess inside archive_split.py: runs each tool's command line in this process
    against ``db``, its default log folder pointed at ``folder``, and records what each run wrote and
    printed, and whether any of its writes came before its log."""

    def __init__(self, db: Database, folder: Path):
        from scripts import fix_band_cohorts, reassign_games_between_teams

        self.db, self.folder = db, folder
        self.modules = {
            "reassign_games_between_teams.py": reassign_games_between_teams,
            "apply_team_fields.py": _module(APPLY_FIELDS, "apply_team_fields"),
            "fix_band_cohorts.py": fix_band_cohorts,
        }
        self.runs: dict[str, dict] = {}
        self.current = None
        db.before_write.append(self._logged_yet)

    def _logged_yet(self, record: dict) -> None:
        if self.current and not list(self.folder.glob(STEP_SIX_TOOLS[self.current])):
            self.runs[self.current]["unlogged"] += 1

    def run(self, command, **kwargs) -> subprocess.CompletedProcess:
        tool = Path(command[1]).name
        module = self.modules[tool]
        self.current, before = tool, len(self.db.writes)
        self.runs[tool] = {"unlogged": 0}
        try:
            code, output = run_main(self.db, module, *command[2:], exports=self.folder)
        finally:
            self.current = None
        self.runs[tool].update(code=code, output=output, writes=len(self.db.writes) - before)
        return subprocess.CompletedProcess(command, code, output, "")


def _reused_record() -> tuple[Database, dict]:
    """A u12 record GotSport has handed to a u11 squad, with two of the old squad's games from last
    season and one of the new squad's from this one; and its triage row."""
    season = _season()
    teams = [
        _team(BLUE, f"Phoenix Rising {season - 11} Blue", "u12", "301"),
        _team(OPPONENT, "Scottsdale Blackhawks Blue", "u12", "302"),
        _team(OLD_SQUAD, f"Phoenix Rising {season - 11} Blue II", "u12", "303"),
    ]

    def game(n, played, home, away):
        return {
            "id": f"game-{n}",
            "game_date": played,
            "home_team_master_id": home,
            "away_team_master_id": away,
            "home_score": 2,
            "away_score": 1,
            "competition": "Arizona League",
            "is_excluded": False,
        }

    games = [
        game(1, f"{season - 1}-10-04", BLUE, OPPONENT),
        game(2, f"{season - 1}-11-08", OPPONENT, BLUE),
        game(3, f"{season}-09-06", BLUE, OPPONENT),
    ]
    triage = _module(TRIAGE, "triage_reconcile")
    row = dict.fromkeys(triage.TRIAGE_FIELDS, "")
    row.update(
        {
            "class": "reused_id",
            "team_id_master": BLUE,
            "provider_team_id": "301",
            "team_name": teams[0]["team_name"],
            "club_name": "Phoenix Rising",
            "gender": "Male",
            "state_code": "AZ",
            "stored_age_group": "u12",
            "gotsport_team_name": "Phoenix Rising U11 Red",
            "gotsport_age_group": "u11",
        }
    )
    return world(teams, games), row


def check_archive_split(r: Result) -> None:
    """Step 6b's archive split runs each tool as its own logged step and takes each log from the Log: line
    the tool prints; each tool logs before its first write; the undo commands are printed where the skill
    can point to them."""
    from scripts import reassign_games_between_teams as reassign

    archive = _module(ARCHIVE, "archive_split")
    triage = _module(TRIAGE, "triage_reconcile")
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        db, row = _reused_record()
        triage.write_triage([row], folder / "triage.csv")
        run_main(db, archive, "plan", "--triage", str(folder / "triage.csv"), exports=folder)
        plan = str(next(iter(folder.glob("archive_split_plan_*.csv")), None))

        rehearsed = db.copy()
        rehearsal = _InProcess(rehearsed, folder / "rehearsal")
        with mock.patch.object(archive, "subprocess", SimpleNamespace(run=rehearsal.run)):
            run_main(rehearsed, archive, "apply", "--plan", plan, exports=folder)
        r.check(
            "archive_split apply without --execute writes nothing and runs no tool",
            not rehearsed.writes and not rehearsal.runs,
            f"writes: {rehearsed.writes}; tools run: {sorted(rehearsal.runs)}",
        )

        tools = _InProcess(db, folder / "tools")
        with mock.patch.object(archive, "subprocess", SimpleNamespace(run=tools.run)):
            run_main(db, archive, "apply", "--plan", plan, "--execute", exports=folder)
        entries = csv_rows(next(iter(folder.glob("archive_split_run_*.csv")), None))
        entry = entries[0] if entries else {}
        for column, tool in ARCHIVE_LOGS.items():
            logged = Path(entry.get(column) or "")
            r.check(
                f"archive_split records the log {tool} names on its Log: line",
                entry.get(column) and logged.is_file() and fnmatch.fnmatch(logged.name, STEP_SIX_TOOLS[tool]),
                f"{column}: {entry.get(column)!r}",
            )
            ran = tools.runs.get(tool, {})
            r.check(
                f"{tool} writes its log before its first write",
                ran.get("writes") and not ran.get("unlogged"),
                f"{ran.get('writes')} write(s), {ran.get('unlogged')} before the log existed",
            )
        printed = {tool: "Undo with" in tools.runs.get(tool, {}).get("output", "") for tool in STEP_SIX_TOOLS}
        r.check(
            "apply_team_fields and fix_band_cohorts print their undo command after a run that wrote",
            printed["apply_team_fields.py"] and printed["fix_band_cohorts.py"],
            f"printed an undo: {printed}",
        )

        moved, _ = _reused_record()
        start = archive.season_start()
        args = ("--from", BLUE, "--to", OLD_SQUAD, "--before", start, "--exports-dir", str(folder / "reassign"))
        _, output = run_main(moved, reassign, *args)
        r.check(
            "reassign_games_between_teams prints its undo command on the dry run",
            "Undo with --revert" in output,
            f"dry run printed: {output.strip().splitlines()[-1:] if output.strip() else 'nothing'}",
        )


CHECKS = [
    check_step_one,
    check_lookups,
    check_decide,
    check_triage,
    check_triage_plans,
    check_apply_team_fields,
    check_archive_split,
]


def main() -> int:
    return run_checks(CHECKS, "Check the reconcile-gotsport skill's claims", UNVERIFIED)


if __name__ == "__main__":
    sys.exit(main())
