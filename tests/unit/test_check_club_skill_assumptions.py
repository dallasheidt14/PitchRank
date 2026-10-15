"""The club skill's self-check. Each assertion runs over today's code, which holds it, and over a break
of the code it checks, which must fail it by name, so a check that cannot fail is caught here instead
of being trusted in the weekly run. The whole check is also run once against today's code, offline."""

import contextlib
import json
import os
import subprocess
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import scripts.check_club_skill_assumptions as checker  # noqa: E402
from scripts import full_club_analysis  # noqa: E402
from scripts import repair_swapped_club_names as repair  # noqa: E402
from scripts.team_cleanup import apply_stage, pages  # noqa: E402
from tests.unit.test_skill_check_offline import drop_update_filter, net_under_guards  # noqa: E402

READS_RENAMES = "the scan reads each rename an executed weekly cleanup lowered or re-cased, and no other"
DRY_CLEANUP = "a dry run of the weekly cleanup logs no rename the scan reads"
DRY_LOG_REFUSED = "a saved log of a cleanup dry run is refused, not read as a run that renamed nothing"
NO_GH = "a saved --abbreviation-log stands in for the default run: the scan never asks gh"
SCAN_WRITES = "the scan's dry run writes nothing to the database"
SNAPSHOT_NAMED = "the scan writes its snapshot to --exports-dir and names it on its last line"
BOTH_LEAGUES = "without --league-url the scan reads both default PlayMetrics leagues"
TABLE_READ = "the skill's source table gives each tier a weight"
DECIDES = "the tiers the scan approves are the skill's Decides rows"
LISTED = "the tiers the scan lists unapproved are the skill's Listed rows"
WHOLE = "the review page applies whole exactly the tiers the scan approves"
REHEARSAL = "a rehearsal (--execute with --dry-run) writes nothing"
REPLAY_WRITES = "a replay writes only approved rows' club_name, each to a live team still holding the club just read"
SINCE_SNAPSHOT = "a team whose club moved since the snapshot is skipped, a change of case aside"
SINCE_READ = "a team that moved between the replay's read and its write is skipped_changed_since_read"
INTERRUPTED = "an interrupted replay logs the write in flight as updated and each row never reached as not_attempted"
LOG_FOUND = "the replay the weekly apply runs leaves a log the apply finds by name"
OWN_LOG = "every row of that log carries the run's actor, so the apply takes it as the batch's own"
READ_BACK = "the apply reads back every change the replay logs as written"
UNDO_PREVIEW = "an undo without --execute writes nothing"
UNDO_WRITES = "an undo writes each team back only while it still holds what the replay wrote"
UNDO_REFUSES = "an undo refuses a rehearsal's log"
KEYS = [
    f"{what} with --execute stops without a service-role key, before building a client"
    for what in ("a replay", "an undo")
]


def _failed(check, *args):
    result = checker.Result()
    check(result, *args)
    return [a["name"] for a in result.failures]


def _main(monkeypatch, capsys, *checks, argv=("--code-only",)):
    if checks:
        monkeypatch.setattr(checker, "CHECKS", list(checks))
    monkeypatch.setattr(sys, "argv", ["check_club_skill_assumptions.py", *argv])
    code = checker.main()
    return code, capsys.readouterr().out


def test_every_check_is_run():
    defined = {name for name in dir(checker) if name.startswith("check_")}
    assert defined == {check.__name__ for check in checker.CHECKS}


def test_the_whole_check_holds_on_today_s_code_without_a_database_or_the_network(monkeypatch, capsys):
    net_under_guards(monkeypatch, repair)

    code, out = _main(monkeypatch, capsys, argv=("--code-only", "--json"))

    result = json.loads(out)
    assert [a["name"] for a in result["assertions"] if not a["ok"]] == []
    assert code == 0 and len(result["assertions"]) == 33
    assert [u["name"] for u in result["unverified"]] == [name for name, _ in checker.UNVERIFIED]


def test_main_exits_1_when_an_assertion_fails(monkeypatch, capsys):
    code, out = _main(monkeypatch, capsys, lambda r: r.check("breaks", False, "why"))
    assert code == 1 and "FAIL  breaks" in out


# --- the cleanup's log ----------------------------------------------------------------------


def test_the_cleanup_log_check_fails_when_the_scan_reads_a_rename_that_only_re_cased_lower_case(monkeypatch):
    monkeypatch.setattr(repair, "lowered_abbreviation", lambda before, after: "word" if before != after else None)
    assert _failed(checker.check_cleanup_log) == [READS_RENAMES]


def test_the_cleanup_log_check_fails_when_the_scan_reads_the_rename_of_an_all_caps_name(monkeypatch):
    lowered = repair.lowered_abbreviation

    def reads_all_caps(before, after):
        return "word" if before.isupper() and before != after else lowered(before, after)

    monkeypatch.setattr(repair, "lowered_abbreviation", reads_all_caps)
    assert _failed(checker.check_cleanup_log) == [READS_RENAMES]


def test_the_cleanup_log_check_fails_when_a_dry_run_prints_its_renames_as_done(monkeypatch):
    execute = full_club_analysis.execute_fixes
    monkeypatch.setattr(
        full_club_analysis, "execute_fixes", lambda client, fixes, dry_run=True: execute(client, fixes, dry_run=False)
    )
    assert _failed(checker.check_cleanup_log) == [DRY_CLEANUP, DRY_LOG_REFUSED]


def test_the_cleanup_log_check_fails_when_a_saved_log_with_no_rename_is_accepted(monkeypatch):
    monkeypatch.setattr(repair, "read_saved_log", lambda path: path.read_text(encoding="utf-8"))
    assert _failed(checker.check_cleanup_log) == [DRY_LOG_REFUSED]


# --- the scan -------------------------------------------------------------------------------


def _quietly_through_gh_s_full_path(run):
    with contextlib.suppress(Exception):
        subprocess.run(["C:/Program Files/GitHub CLI/gh.exe", "run", "view", run, "--log"], capture_output=True)


@pytest.mark.parametrize(
    ("ask", "failed"),
    [
        (lambda run: repair.read_run_log(run), [NO_GH, SNAPSHOT_NAMED, BOTH_LEAGUES]),
        (
            lambda run: subprocess.run(["gh", "run", "view", run, "--log"], capture_output=True, check=True),
            [NO_GH, SNAPSHOT_NAMED, BOTH_LEAGUES],
        ),
        (_quietly_through_gh_s_full_path, [NO_GH]),
    ],
    ids=["through read_run_log", "through a gh call of its own", "by its full path, the refusal swallowed"],
)
def test_the_scan_check_fails_when_the_scan_asks_gh_despite_a_saved_log(monkeypatch, ask, failed):
    net_under_guards(monkeypatch, repair)
    read = repair.read_saved_log

    def asks_gh_too(path):
        ask(repair.DEFAULT_ABBREVIATION_RUNS[0])
        return read(path)

    monkeypatch.setattr(repair, "read_saved_log", asks_gh_too)
    assert _failed(checker.check_scan) == failed


@pytest.mark.parametrize(
    ("command", "runs_gh"),
    [("gh run view 1 --log", True), (["gh", "auth", "status"], True), ("git status", False), ([], False)],
)
def test_runs_gh_reads_a_command_given_as_one_string_or_as_words(command, runs_gh):
    assert checker._runs_gh(command) is runs_gh


def test_the_scan_check_fails_when_the_scan_writes(monkeypatch):
    build = repair.build_snapshot

    def writes_too(supabase, clubs, logs):
        supabase.table("teams").update({"club_name": "X"}).eq("team_id_master", checker.WICHITA).execute()
        return build(supabase, clubs, logs)

    monkeypatch.setattr(repair, "build_snapshot", writes_too)
    assert _failed(checker.check_scan) == [SCAN_WRITES]


def test_the_scan_check_fails_when_the_last_line_no_longer_names_the_snapshot(monkeypatch):
    main = repair.main
    monkeypatch.setattr(repair, "main", lambda: (main(), print("done"))[0])
    assert _failed(checker.check_scan) == [SNAPSHOT_NAMED]


def test_the_scan_check_fails_when_the_scan_reads_only_one_default_league(monkeypatch):
    parse = repair.parse_league_urls
    monkeypatch.setattr(repair, "parse_league_urls", lambda urls: parse(urls)[:1])
    assert _failed(checker.check_scan) == [BOTH_LEAGUES]


def test_the_scan_runs_the_weekly_propose_s_command_and_reads_only_the_saved_log(tmp_path):
    found = checker.scan(checker.world(), tmp_path)

    assert found.snapshot.parent == tmp_path / "clubs" / "national"
    assert found.asked_gh == [] and sorted(found.leagues) == [1014, 1207]


# --- the tiers ------------------------------------------------------------------------------


def _skill(tmp_path, extra="", table=True):
    text = checker.SKILL.read_text(encoding="utf-8")
    if not table:
        text = "\n".join(line for line in text.splitlines() if not line.startswith("|"))
    path = tmp_path / "SKILL.md"
    path.write_text(text + extra, encoding="utf-8")
    return path


def test_the_skill_table_names_the_tiers_each_weight_gives():
    assert checker.skill_tiers(checker.SKILL.read_text(encoding="utf-8")) == {
        "Decides": {"provider", "swap", "word", "bracket"},
        "Listed": {"recased", "unclear", "capital"},
    }


@pytest.mark.parametrize(
    ("skill", "failed"),
    [
        ({}, []),
        ({"table": False}, [TABLE_READ, DECIDES, LISTED]),
        ({"extra": "\n| `x` | `bogus` | Decides. |\n"}, [DECIDES]),
        ({"extra": "\n| `x` | `bogus` | Listed. |\n"}, [LISTED]),
    ],
    ids=["holds", "no table", "a tier the scan never approves", "a tier the scan never lists"],
)
def test_the_tier_check_compares_the_skill_s_table_with_the_scan(tmp_path, skill, failed):
    assert _failed(checker.check_tiers, _skill(tmp_path, **skill)) == failed


def test_the_tier_check_fails_when_the_review_page_applies_another_tier_whole(monkeypatch):
    monkeypatch.setitem(pages.WHOLE_TIERS, "clubs", {"provider", "swap", "word", "bracket", "recased"})
    assert _failed(checker.check_tiers) == [WHOLE]


def test_the_tier_check_fails_when_the_scan_approves_a_listed_tier(monkeypatch):
    rows_of = repair.abbreviation_rows
    monkeypatch.setattr(repair, "abbreviation_rows", lambda *args: [{**r, "approved": True} for r in rows_of(*args)])
    assert _failed(checker.check_tiers) == [DECIDES, LISTED, WHOLE]


# --- the replay -----------------------------------------------------------------------------


def test_the_replay_check_fails_when_execute_beats_dry_run(monkeypatch):
    monkeypatch.setattr(repair, "resolve_execute", lambda execute, dry_run: execute)
    assert _failed(checker.check_replay) == [REHEARSAL]


@pytest.mark.parametrize(
    ("column", "failed"),
    [("is_deprecated", [REPLAY_WRITES]), ("club_name", [REPLAY_WRITES, SINCE_READ])],
)
def test_the_replay_check_fails_when_a_write_loses_a_filter(monkeypatch, column, failed):
    drop_update_filter(monkeypatch, column)
    assert _failed(checker.check_replay) == failed


def test_the_replay_check_fails_when_a_row_the_snapshot_no_longer_describes_is_written(monkeypatch):
    plan = repair.plan_replay

    def without_the_snapshot_check(approved, current):
        entries = plan(approved, current)
        for entry in entries:
            if entry["action"] == "skipped_changed_since_snapshot":
                entry.update(action="updated", before=current[entry["team_id_master"]])
        return entries

    monkeypatch.setattr(repair, "plan_replay", without_the_snapshot_check)
    assert _failed(checker.check_replay) == [REPLAY_WRITES, SINCE_SNAPSHOT, INTERRUPTED]


def test_the_replay_check_fails_when_a_refused_write_is_logged_as_written(monkeypatch):
    apply_club = repair.apply_club
    monkeypatch.setattr(repair, "apply_club", lambda *args: apply_club(*args) or True)
    assert _failed(checker.check_replay) == [SINCE_READ]


def test_the_replay_check_fails_when_rows_never_reached_are_logged_as_written(monkeypatch):
    run = repair.run_replay

    def all_attempted(supabase, entries, execute):
        for entry in entries:
            entry["attempted"] = True
        return run(supabase, entries, execute)

    monkeypatch.setattr(repair, "run_replay", all_attempted)
    assert _failed(checker.check_replay) == [INTERRUPTED]


# --- the weekly apply's log -----------------------------------------------------------------


def test_the_loop_log_check_fails_when_the_log_drops_the_actor(monkeypatch):
    row = repair.log_row
    monkeypatch.setattr(repair, "log_row", lambda entry, run_mode, actor=repair.DEFAULT_ACTOR: row(entry, run_mode))
    assert _failed(checker.check_loop_log) == [OWN_LOG, READ_BACK]


def test_the_loop_log_check_fails_when_the_apply_looks_for_another_name(monkeypatch):
    monkeypatch.setitem(apply_stage.APPLIER_LOGS, "clubs", "club_repairs_*.csv")
    assert _failed(checker.check_loop_log) == [LOG_FOUND, OWN_LOG, READ_BACK]


def test_the_loop_log_check_fails_when_the_apply_misses_a_change(monkeypatch):
    read = apply_stage.LOG_CHANGES["clubs"]
    monkeypatch.setitem(apply_stage.LOG_CHANGES, "clubs", lambda *args: (read(*args)[0][:-1], []))
    assert _failed(checker.check_loop_log) == [READ_BACK]


def test_the_loop_log_check_fails_when_the_apply_reads_a_skipped_row_as_a_change(monkeypatch):
    read = apply_stage._read_csv
    monkeypatch.setattr(
        apply_stage,
        "_read_csv",
        lambda path: [{**row, "action": "updated"} if "action" in row else row for row in read(path)],
    )
    assert _failed(checker.check_loop_log) == [READ_BACK]


# --- the undo -------------------------------------------------------------------------------


def test_the_revert_check_fails_when_a_preview_writes(monkeypatch):
    revert = repair.revert
    monkeypatch.setattr(repair, "revert", lambda supabase, path, execute: revert(supabase, path, True))
    assert _failed(checker.check_revert) == [UNDO_PREVIEW]


def test_the_revert_check_fails_when_an_undo_overwrites_a_team_that_moved(monkeypatch):
    drop_update_filter(monkeypatch, "club_name")
    assert _failed(checker.check_revert) == [UNDO_WRITES]


def test_the_revert_check_fails_when_a_rehearsal_s_log_is_undone(monkeypatch):
    revert = repair.revert

    def accepts_rehearsals(supabase, path, execute):
        accepted = path.with_name("accepted.csv")
        accepted.write_text(path.read_text(encoding="utf-8-sig").replace(",dry-run,", ",execute,"), encoding="utf-8")
        return revert(supabase, accepted, execute)

    monkeypatch.setattr(repair, "revert", accepts_rehearsals)
    assert _failed(checker.check_revert) == [UNDO_REFUSES]


# --- the service-role key -------------------------------------------------------------------


def test_the_key_check_fails_when_execute_builds_a_client_from_the_anon_key(monkeypatch):
    build = repair.get_supabase
    monkeypatch.setattr(repair, "get_supabase", lambda require_service_role=False: build(False))
    assert _failed(checker.check_service_key) == KEYS


# --- the weekly cleanup ---------------------------------------------------------------------

STEPS = ("backfill_missing_club_names.py", "extract_missing_club_names.py", "full_club_analysis.py")
LIVE = "${{ !contains(format(',{0},', github.event.inputs.skip_steps || ''), ',1,') }}"
FILL = (
    "import argparse\n"
    "parser = argparse.ArgumentParser()\n"
    'parser.add_argument("--dry-run", action="store_true", help="Preview updates without writing")\n'
    'parser.add_argument("--limit", type=int, default=None)\n'
)
STANDARDIZE = (
    "import argparse\n"
    "parser = argparse.ArgumentParser()\n"
    'parser.add_argument("--execute", action="store_true")\n'
    'parser.add_argument("--dry-run", action="store_true")\n'
)
# The flag each step starts its script with on its schedule, as the real workflow sets it.
WRITES = {STEPS[0]: '""', STEPS[1]: '""', STEPS[2]: '"--execute"'}
DISPATCH = "${{ github.event.inputs.dry_run }}"
DRY_BY_DEFAULT = "${{ github.event.inputs.dry_run || 'true' }}"
DRY_LINES = ('if [ "$INPUT_DRY_RUN" = "true" ]; then FLAG="--dry-run"; fi',)


def _cleanup(
    tmp_path, schedule=True, job=None, switched=None, scheduled=None, inputs=None, dry=None, left_out=(), fill=None
):
    """A minimal weekly club cleanup, its two fill scripts and its standardizer, with the given parts
    changed."""
    lines = ["name: Clubs", "on:"]
    if schedule:
        lines += ["  schedule:", "    - cron: '0 10 * * 1'"]
    lines += ["  workflow_dispatch:", "jobs:", "  clubs:"]
    lines += [f"    if: {job}"] if job else []
    lines += ["    steps:"]
    for n, script in enumerate(STEPS, 1):
        if script not in left_out:
            gate = (switched or {}).get(script, LIVE)
            lines += [f"      - name: Step {n}", f"        if: {gate}"]
            lines += ["        env:", f"          INPUT_DRY_RUN: {(inputs or {}).get(script, DISPATCH)}"]
            lines += ["        run: |", f"          FLAG={(scheduled or {}).get(script, WRITES[script])}"]
            lines += [f"          {line}" for line in (dry or {}).get(script, DRY_LINES)]
            lines += [f"          python scripts/{script} $FLAG"]
    workflow = tmp_path / "clubs.yml"
    workflow.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for script in STEPS[:2]:
        (tmp_path / script).write_text((fill or {}).get(script, FILL), encoding="utf-8")
    (tmp_path / STEPS[2]).write_text(STANDARDIZE, encoding="utf-8")
    return workflow, tmp_path


def _weekly(name, script):
    return {
        "schedule": "clubs.yml runs on a schedule",
        "step": f"clubs.yml runs {script} in a step that is switched on",
        "writes on schedule": f"on its schedule clubs.yml runs {script} to write, not as a dry run",
        "writes": f"{script} writes unless given --dry-run",
    }[name]


@pytest.mark.parametrize(
    ("change", "failed"),
    [
        ({}, []),
        ({"schedule": False}, [_weekly("schedule", "")]),
        ({"switched": {STEPS[1]: "false"}}, [_weekly("step", STEPS[1])]),
        ({"switched": {STEPS[0]: "'false'"}}, [_weekly("step", STEPS[0])]),
        ({"switched": {STEPS[2]: "${{ false }}"}}, [_weekly("step", STEPS[2])]),
        ({"switched": {STEPS[2]: "${{ false && github.event_name == 'schedule' }}"}}, [_weekly("step", STEPS[2])]),
        ({"job": "false"}, [_weekly("step", script) for script in STEPS]),
        ({"job": "${{ false }}"}, [_weekly("step", script) for script in STEPS]),
        ({"scheduled": {STEPS[0]: '"--dry-run"'}}, [_weekly("writes on schedule", STEPS[0])]),
        ({"scheduled": {STEPS[2]: '"--dry-run"'}}, [_weekly("writes on schedule", STEPS[2])]),
        ({"scheduled": {STEPS[2]: '"--execute --dry-run"'}}, [_weekly("writes on schedule", STEPS[2])]),
        ({"scheduled": {STEPS[2]: '""'}}, [_weekly("writes on schedule", STEPS[2])]),
        ({"inputs": {STEPS[0]: DRY_BY_DEFAULT}}, [_weekly("writes on schedule", STEPS[0])]),
        ({"inputs": {STEPS[2]: DRY_BY_DEFAULT}}, [_weekly("writes on schedule", STEPS[2])]),
        (
            {"dry": {STEPS[1]: ('if [ "${INPUT_DRY_RUN:-true}" = "true" ]; then FLAG="--dry-run"; fi',)}},
            [_weekly("writes on schedule", STEPS[1])],
        ),
        (
            {"dry": {STEPS[2]: ('if [ "$INPUT_DRY_RUN" != "false" ]; then FLAG="--dry-run"; fi',)}},
            [_weekly("writes on schedule", STEPS[2])],
        ),
        (
            {"dry": {STEPS[0]: ('INPUT_DRY_RUN="${INPUT_DRY_RUN:-true}"', *DRY_LINES)}},
            [_weekly("writes on schedule", STEPS[0])],
        ),
        ({"left_out": (STEPS[0],)}, [_weekly("step", STEPS[0]), _weekly("writes on schedule", STEPS[0])]),
        (
            {"fill": {STEPS[0]: FILL + 'parser.add_argument("--execute", action="store_true")\n'}},
            [_weekly("writes on schedule", STEPS[0]), _weekly("writes", STEPS[0])],
        ),
        (
            {"fill": {STEPS[1]: FILL.replace('action="store_true",', 'action="store_true", default=True,')}},
            [_weekly("writes", STEPS[1])],
        ),
    ],
    ids=[
        "holds",
        "unscheduled",
        "a fill step off",
        "a fill step off, quoted",
        "the standardizer off",
        "the standardizer off by a false && term",
        "the job off",
        "the job off in an expression",
        "a fill step dry on its schedule",
        "the standardizer dry on its schedule",
        "the standardizer dry beside --execute on its schedule",
        "the standardizer without --execute on its schedule",
        "a fill step's input dry by default",
        "the standardizer's input dry by default",
        "a fill step dry while its input is unset",
        "the standardizer dry unless its input is false",
        "a fill step's input defaulted to dry in the shell",
        "a fill step gone",
        "a fill script asks for --execute",
        "a fill script dry by default",
    ],
)
def test_the_weekly_cleanup_check_reads_each_club_step_and_each_fill_script(tmp_path, change, failed):
    assert _failed(checker.check_weekly_cleanup, *_cleanup(tmp_path, **change)) == failed


def test_the_weekly_cleanup_check_reads_the_real_workflow_and_fill_scripts_and_holds():
    assert _failed(checker.check_weekly_cleanup) == []
