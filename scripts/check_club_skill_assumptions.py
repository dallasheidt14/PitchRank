#!/usr/bin/env python3
"""Assert the claims that .claude/skills/normalizing-club-names makes about this repo.

That skill governs writes to teams.club_name, the column the duplicate scans pair teams on. Its
guidance rests on claims about code behaviour: which tiers arrive approved, which logs the scan reads,
and which guards stand between a reviewed snapshot and a write. Prose claims cannot fail, so they rot
silently.

This script makes those claims executable. Run it before trusting the skill; the weekly team cleanup
runs it before proposing club changes.

ASSERTIONS fail the run. A failure means a documented claim, or an agreement between the club tools
and the weekly cleanup that reads their files, no longer holds, or that a check stopped; the detail
line says which. NOT VERIFIED lists the claims no code settles; they never fail the run.

Nothing reads the database or the network: each tool runs, mostly through its own entry point, against an
in-memory stand-in with blank credentials, PlayMetrics is answered in-process, every process start (gh
among them), name lookup and connection off this machine is refused at the audit event the interpreter
raises for it, and every snapshot and log lands in a temporary folder. --code-only therefore changes nothing.

Usage:
    python scripts/check_club_skill_assumptions.py               # everything
    python scripts/check_club_skill_assumptions.py --code-only   # accepted; changes nothing
    python scripts/check_club_skill_assumptions.py --json
"""

from __future__ import annotations

import ast
import contextlib
import io
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.skill_check_offline import (  # noqa: E402
    Database,
    Refused,
    Result,
    csv_rows,
    guarded,
    run_checks,
    run_main,
    run_with_anon_key,
    step_is_off,
    workflow_steps,
)

SKILL = ROOT / ".claude" / "skills" / "normalizing-club-names" / "SKILL.md"
WORKFLOW = ROOT / ".github" / "workflows" / "update-missing-club-and-state.yml"
SCRIPTS = ROOT / "scripts"
FILL_SCRIPTS = ("backfill_missing_club_names.py", "extract_missing_club_names.py")
STANDARDIZER = "full_club_analysis.py"
# How a club step reads the dispatch input, the only way it may: a schedule passes the input empty, so the
# step writes. Any other spelling may make every scheduled run dry, and fails.
DISPATCH_DRY_RUN = "${{ github.event.inputs.dry_run }}"
DRY_ON_DISPATCH = re.compile(r'if \[ "\$INPUT_DRY_RUN" = "true" \]; then [A-Z_]+="--dry-run"; fi')
LEAGUE_BODY = re.compile(r"/leagues/([0-9]+)-")
TIER_ROW = re.compile(r"^\|[^|\n]*\|\s*((?:`\w+`(?:,\s*)?)+)\s*\|\s*(Decides|Listed)\b", re.M)
RUN_ID = "2026-10-12-nc"
# How gh run view --log prefixes each line of a step's output.
GITHUB_LOG_PREFIX = "Update Missing Club Names & State Codes\tUNKNOWN STEP\t2026-09-14T16:12:54.4283827Z   "

PLAYMETRICS, TGS = "provider-playmetrics", "provider-tgs"
PLAYMETRICS_TEAM = "9001"
FUSION, SURF, WICHITA, RUSH, JSC, HOMEWOOD, SOCAL, CHESAPEAKE, ABC, CHARLOTTE = (
    f"cccccccc-0000-4000-8000-{n:012d}" for n in range(1, 11)
)
# The columns of each table the tools read or write, as the migrations define them.
COLUMNS = {
    "teams": (
        "team_id_master",
        "team_name",
        "club_name",
        "state_code",
        "provider_id",
        "provider_team_id",
        "is_deprecated",
    ),
    "providers": ("id", "code"),
}
# Renames the weekly cleanup applies: four lower an abbreviation or re-case a capital, which the scan
# reads, and two were the cleanup doing its job, re-casing lower-case words or an all-caps name.
CLEANUP_FIXES = [
    {"state": "NC", "from": "JSC Soccer Club", "to": "Jsc Soccer Club", "count": 1},
    {"state": "AL", "from": "Homewood Soccer Club (AL)", "to": "Homewood Soccer Club (al)", "count": 1},
    {"state": "CA", "from": "SoCal Blues", "to": "Socal Blues", "count": 1},
    {"state": "VA", "from": "Chesapeake united sc", "to": "Chesapeake United Sc", "count": 1},
    {"state": None, "from": "ABC United", "to": "Abc United", "count": 1},
    {"state": "NC", "from": "CHARLOTTE FC", "to": "Charlotte FC", "count": 1},
]
# What each approved row of the scan writes: (team, the club it holds, the club it gets).
APPROVED_REPAIRS = [
    (FUSION, "VENTURA COUNTY FUSION", "NC Fusion"),
    (SURF, "SURF", "Oregon Surf"),
    (JSC, "Jsc Soccer Club", "JSC Soccer Club"),
    (HOMEWOOD, "Homewood Soccer Club (al)", "Homewood Soccer Club (AL)"),
    (ABC, "Abc United", "ABC United"),
]

UNVERIFIED = [
    (
        "update-missing-club-and-state.yml runs every Monday",
        "The file schedules it, which is asserted; whether GitHub has the workflow enabled is a repository "
        "setting no code holds. Check with: gh workflow list --all",
    ),
    (
        "anon holds the UPDATE grant on teams but no UPDATE policy, so an anon write changes nothing",
        "Grants and row-level security live in the database. The code's half, that --execute refuses to run "
        "without a service-role key, is asserted.",
    ),
    ("No measured yield exists for these tiers yet", "A record of what batches have run, not of code."),
]


@dataclass
class Scan:
    snapshot: Path | None
    output: str
    asked_gh: list[str]
    leagues: list[int]


def _team(team_id, provider, state, name, club, provider_team_id=""):
    return {
        "team_id_master": team_id,
        "team_name": name,
        "club_name": club,
        "state_code": state,
        "provider_id": provider,
        "provider_team_id": provider_team_id,
        "is_deprecated": False,
    }


def world() -> Database:
    """A live team for each tier the scan gives, two for ``word`` and two for ``unclear``, each holding the
    club it is read from, and one holding each club CLEANUP_FIXES renamed to, so one of them gives no row."""
    teams = [
        _team(FUSION, PLAYMETRICS, "NC", "NC Fusion 2014 Girls", "VENTURA COUNTY FUSION", PLAYMETRICS_TEAM),
        _team(SURF, TGS, "OR", "Oregon Surf GU11 PreECNL", "SURF"),
        _team(WICHITA, TGS, "KS", "Sporting Wichita U16 HD", "Surf"),
        _team(RUSH, TGS, "CO", "Rush Blue", "SURF"),
    ]
    holders = (JSC, HOMEWOOD, SOCAL, CHESAPEAKE, ABC, CHARLOTTE)
    teams += [
        _team(tid, TGS, fix["state"], "2014 Boys Blue", fix["to"])
        for tid, fix in zip(holders, CLEANUP_FIXES, strict=True)
    ]
    providers = [{"id": PLAYMETRICS, "code": "playmetrics"}, {"id": TGS, "code": "tgs"}]
    return Database({"teams": teams, "providers": providers}, COLUMNS)


def cleanup_output(dry_run: bool) -> str:
    """What the weekly cleanup prints applying CLEANUP_FIXES, as gh run view --log shows it."""
    db = Database({"teams": []}, COLUMNS)
    out = io.StringIO()
    with guarded(), contextlib.redirect_stdout(out):
        # Imported here: the module reads the environment files when first imported.
        from scripts import full_club_analysis

        with guarded(full_club_analysis):
            full_club_analysis.execute_fixes(db, CLEANUP_FIXES, dry_run=dry_run)
    return "\n".join(GITHUB_LOG_PREFIX + line for line in out.getvalue().splitlines())


def _runs_gh(command) -> bool:
    words = command.split() if isinstance(command, str) else list(command)
    return bool(words) and Path(str(words[0])).stem.lower() == "gh"


def scan(db: Database, store: Path) -> Scan:
    """Run the club scan as the weekly propose runs it, over a saved copy of the cleanup's log, with
    PlayMetrics answered in-process: the newest snapshot in its --exports-dir, what it printed, each gh
    command it tried to start, refused, and the PlayMetrics governing bodies it read."""
    from scripts import repair_swapped_club_names as repair
    from scripts.team_cleanup.propose_week import ABBREVIATION_LOGS, CLUBS, stage_commands

    saved = store / ABBREVIATION_LOGS / f"{repair.DEFAULT_ABBREVIATION_RUNS[0]}.log"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(cleanup_output(dry_run=False), encoding="utf-8")
    command = stage_commands(CLUBS, store / CLUBS, ["NC"], store)[0]

    leagues, started = [], len(db.children)
    fetch = repair.fetch_playmetrics_clubs

    def league(gb_id, league_id, key):
        leagues.append(gb_id)
        return {"divisions": [{"id": 1}]}

    def division(gb_id, league_id, key, division_id):
        listed = [{"team": {"id": int(PLAYMETRICS_TEAM)}, "club": {"name": "NC Fusion"}}]
        return {"teams": listed if gb_id == 1207 else []}

    with mock.patch.object(repair, "fetch_playmetrics_clubs", lambda found: fetch(found, league, division, 0)):
        try:
            _, output = run_main(db, repair, *command[1:])
        except Refused as refused:
            # Caught so the assertions on what the scan reached report it, rather than the check stopping.
            output = f"{type(refused).__name__}: {refused}"
    exports = Path(command[command.index("--exports-dir") + 1])
    snapshots = sorted(exports.glob("repair_swapped_club_names_*.csv"))
    asked_gh = [child for child in db.children[started:] if _runs_gh(child)]
    return Scan(snapshots[-1] if snapshots else None, output, asked_gh, leagues)


def _logs(folder: Path) -> list[Path]:
    return sorted(folder.glob("repair_swapped_club_names_log_*.csv"))


def skill_tiers(text: str) -> dict[str, set[str]]:
    """The tiers each weight of the skill's source table names: {"Decides": {...}, "Listed": {...}}."""
    weights: dict[str, set[str]] = {"Decides": set(), "Listed": set()}
    for tiers, weight in TIER_ROW.findall(text):
        weights[weight] |= set(re.findall(r"`(\w+)`", tiers))
    return weights


def check_cleanup_log(r: Result) -> None:
    """The scan reads the renames an executed weekly cleanup lowered or re-cased, none of the would-be
    renames a dry run prints, and refuses a saved dry-run log."""
    from scripts.repair_swapped_club_names import parse_cleanup_log, read_saved_log

    want = [
        ("NC", "JSC Soccer Club", "Jsc Soccer Club", "word"),
        ("AL", "Homewood Soccer Club (AL)", "Homewood Soccer Club (al)", "bracket"),
        ("CA", "SoCal Blues", "Socal Blues", "capital"),
        (None, "ABC United", "Abc United", "word"),
    ]
    executed, dry = cleanup_output(dry_run=False), cleanup_output(dry_run=True)
    read = parse_cleanup_log(executed)
    r.check(
        "the scan reads each rename an executed weekly cleanup lowered or re-cased, and no other",
        read == want,
        f"parse_cleanup_log read {read}",
    )
    r.check(
        "a dry run of the weekly cleanup logs no rename the scan reads",
        parse_cleanup_log(dry) == [],
        f"parse_cleanup_log read {parse_cleanup_log(dry)}",
    )
    with tempfile.TemporaryDirectory() as tmp:
        saved = Path(tmp) / "dry_run.log"
        saved.write_text(dry, encoding="utf-8")
        try:
            read_saved_log(saved)
            refused = False
        except ValueError:
            refused = True
    r.check(
        "a saved log of a cleanup dry run is refused, not read as a run that renamed nothing",
        refused,
        "read_saved_log accepted a log holding no rename line",
    )


def check_scan(r: Result) -> None:
    """The weekly propose's scan reads its saved log instead of asking gh, and writes nothing."""
    from scripts.repair_swapped_club_names import DEFAULT_LEAGUE_URLS

    db = world()
    with tempfile.TemporaryDirectory() as tmp:
        found = scan(db, Path(tmp))
        last = found.output.strip().splitlines()[-1] if found.output.strip() else ""
        r.check(
            "a saved --abbreviation-log stands in for the default run: the scan never asks gh",
            not found.asked_gh,
            f"gh started, and refused, as {found.asked_gh}",
        )
        r.check("the scan's dry run writes nothing to the database", not db.writes, f"writes: {db.writes}")
        r.check(
            "the scan writes its snapshot to --exports-dir and names it on its last line",
            found.snapshot is not None and str(found.snapshot) in last,
            f"snapshot {found.snapshot}; last line {last!r}",
        )
    # Read from the URLs, not through the scan's parse_league_urls, so a parser that drops a league still fails.
    defaults = sorted(int(LEAGUE_BODY.search(url).group(1)) for url in DEFAULT_LEAGUE_URLS)
    r.check(
        "without --league-url the scan reads both default PlayMetrics leagues",
        sorted(found.leagues) == defaults,
        f"read governing bodies {sorted(found.leagues)}; the defaults are {defaults}",
    )


def check_tiers(r: Result, skill: Path = SKILL) -> None:
    """The tiers the scan approves are the skill's deciding tiers and the review page's whole tiers."""
    from scripts.repair_swapped_club_names import is_approved
    from scripts.team_cleanup.pages import WHOLE_TIERS
    from scripts.team_cleanup.propose_week import CLUBS

    weights = skill_tiers(skill.read_text(encoding="utf-8"))
    r.check(
        "the skill's source table gives each tier a weight",
        weights["Decides"] and weights["Listed"],
        f"read {weights}",
    )
    with tempfile.TemporaryDirectory() as tmp:
        rows = csv_rows(scan(world(), Path(tmp)).snapshot)
    approved = {row["tier"] for row in rows if is_approved(row)}
    listed = {row["tier"] for row in rows if not is_approved(row)}
    r.check(
        "the tiers the scan approves are the skill's Decides rows",
        approved == weights["Decides"],
        f"the scan approves {sorted(approved)}; the skill's Decides rows name {sorted(weights['Decides'])}",
    )
    r.check(
        "the tiers the scan lists unapproved are the skill's Listed rows",
        listed == weights["Listed"],
        f"the scan lists {sorted(listed)}; the skill's Listed rows name {sorted(weights['Listed'])}",
    )
    r.check(
        "the review page applies whole exactly the tiers the scan approves",
        WHOLE_TIERS[CLUBS] == approved,
        f"WHOLE_TIERS[{CLUBS!r}] = {sorted(WHOLE_TIERS[CLUBS])}; the scan approves {sorted(approved)}",
    )


def check_replay(r: Result) -> None:
    """A replay writes only approved rows, each guarded on the club just read, and reports the rest."""
    from scripts import repair_swapped_club_names as repair

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        db = world()
        snapshot = str(scan(db, folder).snapshot)
        db.row("teams", team_id_master=HOMEWOOD)["club_name"] = "Homewood SC"
        db.row("teams", team_id_master=JSC)["club_name"] = "JSC SOCCER CLUB"

        rehearsal = db.copy()
        run_main(rehearsal, repair, "--execute", snapshot, "--dry-run", "--exports-dir", str(folder / "rehearsal"))
        r.check("a rehearsal (--execute with --dry-run) writes nothing", not rehearsal.writes, f"{rehearsal.writes}")

        live, fetch = db.copy(), repair.fetch_current

        def read_then_moved(sb, team_ids):
            current = fetch(sb, team_ids)
            sb.row("teams", team_id_master=ABC)["club_name"] = "ABC United FC"
            return current

        with mock.patch.object(repair, "fetch_current", read_then_moved):
            run_main(live, repair, "--execute", snapshot, "--exports-dir", str(folder / "replay"))
        held = {FUSION: "VENTURA COUNTY FUSION", SURF: "SURF", JSC: "JSC SOCCER CLUB", ABC: "Abc United"}
        want = sorted(
            (
                (
                    "teams",
                    {"club_name": after},
                    [("club_name", held[tid]), ("is_deprecated", False), ("team_id_master", tid)],
                )
                for tid, _, after in APPROVED_REPAIRS
                if tid in held
            ),
            key=str,
        )
        r.check(
            "a replay writes only approved rows' club_name, each to a live team still holding the club just read",
            sorted(live.updates(), key=str) == want,
            f"writes: {live.updates()}",
        )
        actions = {row["team_id_master"]: row["action"] for row in csv_rows(next(iter(_logs(folder / "replay")), None))}
        r.check(
            "a team whose club moved since the snapshot is skipped, a change of case aside",
            actions.get(HOMEWOOD) == "skipped_changed_since_snapshot" and actions.get(JSC) == "updated",
            f"logged {actions}",
        )
        r.check(
            "a team that moved between the replay's read and its write is skipped_changed_since_read",
            actions.get(ABC) == "skipped_changed_since_read",
            f"logged {actions}",
        )

        stopped, apply_club, calls = db.copy(), repair.apply_club, []

        def dies_on_the_second_write(*args):
            calls.append(args)
            if len(calls) == 2:
                raise ConnectionError("the connection dropped")
            return apply_club(*args)

        with mock.patch.object(repair, "apply_club", dies_on_the_second_write), contextlib.suppress(ConnectionError):
            run_main(stopped, repair, "--execute", snapshot, "--exports-dir", str(folder / "stopped"))
        logged = [row["action"] for row in csv_rows(next(iter(_logs(folder / "stopped")), None))]
        r.check(
            "an interrupted replay logs the write in flight as updated and each row never reached as not_attempted",
            logged == ["skipped_changed_since_snapshot", "updated", "updated", "not_attempted", "not_attempted"],
            f"logged {logged}",
        )


def check_loop_log(r: Result) -> None:
    """The weekly cleanup's apply runs the replay as its own actor and reads every change back from the
    log it leaves, which the skill's undo replays; a row the replay skipped is no change."""
    from scripts import repair_swapped_club_names as repair
    from scripts.team_cleanup import apply_stage
    from scripts.team_cleanup.propose_week import CLUBS

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        db = world()
        vetted = [row for row in csv_rows(scan(db, folder).snapshot) if row["approved"] == "true"]
        db.row("teams", team_id_master=HOMEWOOD)["club_name"] = "Homewood SC"
        cut = apply_stage.write_cut(folder, CLUBS, "pilot", vetted)
        command = apply_stage.applier_command(CLUBS, cut, folder, RUN_ID)
        code, _ = run_main(db, repair, *command[1:])
        logs = sorted((folder / "exports").glob(apply_stage.APPLIER_LOGS[CLUBS]))
        r.check(
            "the replay the weekly apply runs leaves a log the apply finds by name",
            len(logs) == 1,
            f"{len(logs)} log(s) matching {apply_stage.APPLIER_LOGS[CLUBS]}",
        )
        batch = {"cut": str(cut), "logs": [str(log) for log in logs], "exit": code, "ended_at": "2026-10-12T18:00:00Z"}
        r.check(
            "every row of that log carries the run's actor, so the apply takes it as the batch's own",
            apply_stage.own_log(CLUBS, batch, RUN_ID) is not None,
            f"actors logged: {sorted({row.get('actor') for log in logs for row in csv_rows(log)})}",
        )
        changes, _ = apply_stage.batch_changes(db, RUN_ID, CLUBS, batch)
        got = sorted((c["team_id_master"], c["old_value"], c["new_value"]) for c in changes)
        r.check(
            "the apply reads back every change the replay logs as written",
            got == sorted(change for change in APPROVED_REPAIRS if change[0] != HOMEWOOD),
            f"read back {got}",
        )


def check_revert(r: Result) -> None:
    """The undo replays a log backwards, only onto teams still holding what it wrote, and never a
    rehearsal's log."""
    from scripts import repair_swapped_club_names as repair

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        db = world()
        snapshot = str(scan(db, folder).snapshot)
        rehearsed = db.copy()
        run_main(rehearsed, repair, "--execute", snapshot, "--dry-run", "--exports-dir", str(folder / "rehearsal"))
        run_main(db, repair, "--execute", snapshot, "--exports-dir", str(folder / "replay"))
        applied = next(iter(_logs(folder / "replay")), None)
        db.row("teams", team_id_master=SURF)["club_name"] = "Oregon Surf SC"

        preview = db.copy()
        run_main(preview, repair, "--revert", str(applied))
        r.check("an undo without --execute writes nothing", not preview.writes, f"writes: {preview.writes}")

        undone = db.copy()
        run_main(undone, repair, "--revert", str(applied), "--execute")
        want = sorted(
            (
                (
                    "teams",
                    {"club_name": before},
                    [("club_name", after), ("is_deprecated", False), ("team_id_master", tid)],
                )
                for tid, before, after in APPROVED_REPAIRS
            ),
            key=str,
        )
        r.check(
            "an undo writes each team back only while it still holds what the replay wrote",
            sorted(undone.updates(), key=str) == want
            and undone.row("teams", team_id_master=SURF)["club_name"] == "Oregon Surf SC",
            f"writes: {undone.updates()}",
        )

        refused = db.copy()
        code, _ = run_main(refused, repair, "--revert", str(next(iter(_logs(folder / "rehearsal")), None)), "--execute")
        r.check(
            "an undo refuses a rehearsal's log",
            code != 0 and not refused.writes,
            f"exit {code}; writes: {refused.writes}",
        )


def check_service_key(r: Result) -> None:
    """--execute, for a replay and for an undo, stops without a service-role key before building a client."""
    from scripts import repair_swapped_club_names as repair

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        db = world()
        snapshot = str(scan(db, folder).snapshot)
        run_main(db, repair, "--execute", snapshot, "--exports-dir", str(folder / "replay"))
        log = str(next(iter(_logs(folder / "replay")), None))
        for what, args in (("a replay", ["--execute", snapshot]), ("an undo", ["--revert", log, "--execute"])):
            built, output = run_with_anon_key(repair, *args, "--exports-dir", str(folder / "anon"))
            refused = "SUPABASE_SERVICE_ROLE_KEY" in output
            r.check(
                f"{what} with --execute stops without a service-role key, before building a client",
                refused and not built,
                f"refused for want of the key: {refused}; clients built: {built}",
            )


def _flags(script: Path) -> dict[str, dict]:
    """Each --option a script's parser declares, with the keyword arguments that are plain literals."""
    flags = {}
    for node in ast.walk(ast.parse(script.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument" and node.args):
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and str(first.value).startswith("--"):
            keywords = {}
            for keyword in node.keywords:
                with contextlib.suppress(ValueError):
                    keywords[keyword.arg] = ast.literal_eval(keyword.value)
            flags[first.value] = keywords
    return flags


def _scheduled_words(run: str, script: str) -> list[str]:
    """The command line a step's ``run`` starts ``script`` with on its schedule: each $VAR read from the
    plain VAR=value lines above it. A conditional assignment is not read; the check holds each one that
    passes --dry-run or reads INPUT_DRY_RUN to DRY_ON_DISPATCH's test, which a scheduled run, its input
    empty, never passes, and checks no other."""
    values = {}
    for line in run.splitlines():
        assigned = re.fullmatch(r"\s*([A-Z_]+)=(\"[^\"]*\"|'[^']*'|\S*)\s*", line)
        if assigned:
            values[assigned.group(1)] = assigned.group(2).strip("\"'")
        elif f"scripts/{script}" in line:
            return re.sub(r"\$\{?([A-Z_]+)\}?", lambda name: values.get(name.group(1), ""), line).split()
    return []


def check_weekly_cleanup(r: Result, workflow: Path = WORKFLOW, scripts: Path = SCRIPTS) -> None:
    """The weekly club cleanup runs its three club steps on a schedule, each to write, and its two fill
    scripts write unless told not to."""
    doc = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
    triggers = doc.get("on", doc.get(True)) or {}
    r.check(
        f"{workflow.name} runs on a schedule",
        isinstance(triggers, dict) and triggers.get("schedule"),
        f"triggers: {triggers}",
    )
    steps = workflow_steps(doc)
    for script in (*FILL_SCRIPTS, STANDARDIZER):
        found = [(job, step) for job, step in steps if f"scripts/{script}" in str(step.get("run", ""))]
        r.check(
            f"{workflow.name} runs {script} in a step that is switched on",
            found and not any(step_is_off(job, step) for job, step in found),
            f"{len(found)} step(s) run it; job if: {[job.get('if') for job, _ in found]}; "
            f"step if: {[step.get('if') for _, step in found]}",
        )
        runs = [str(step.get("run", "")) for _, step in found]
        inputs = [(step.get("env") or {}).get("INPUT_DRY_RUN") for _, step in found]
        dry = [
            line.strip() for run in runs for line in run.splitlines() if "--dry-run" in line or "INPUT_DRY_RUN" in line
        ]
        needs_execute = "--execute" in _flags(scripts / script)
        scheduled = [_scheduled_words(run, script) for run in runs]
        r.check(
            f"on its schedule {workflow.name} runs {script} to write, not as a dry run",
            found
            and all(value == DISPATCH_DRY_RUN for value in inputs)
            and all(DRY_ON_DISPATCH.fullmatch(line) for line in dry)
            and all("--execute" in words or not needs_execute for words in scheduled),
            f"INPUT_DRY_RUN set to {inputs}; lines reading it or passing --dry-run: {dry}; scheduled command "
            f"line(s): {[' '.join(words) for words in scheduled]}",
        )
    for script in FILL_SCRIPTS:
        flags = _flags(scripts / script)
        dry_run = flags.get("--dry-run", {})
        r.check(
            f"{script} writes unless given --dry-run",
            "--execute" not in flags and dry_run.get("action") == "store_true" and not dry_run.get("default"),
            f"its options: {sorted(flags)}; --dry-run {dry_run}",
        )


CHECKS = [
    check_cleanup_log,
    check_scan,
    check_tiers,
    check_replay,
    check_loop_log,
    check_revert,
    check_service_key,
    check_weekly_cleanup,
]


def main() -> int:
    return run_checks(CHECKS, "Check the club-name skill's claims", UNVERIFIED)


if __name__ == "__main__":
    sys.exit(main())
