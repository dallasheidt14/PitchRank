"""The reconcile skill's self-check. Each assertion runs over today's code, which holds it, and over a
break of the code it checks, which must fail it by name, so a check that cannot fail is caught here
instead of being trusted. The check reads its ages and birth years from the season it runs in, so the
whole check is run against today's code as well."""

import argparse
import contextlib
import io
import json
import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import scripts.check_reconcile_skill_assumptions as checker  # noqa: E402
from scripts import fix_band_cohorts as fbc  # noqa: E402
from scripts import reassign_games_between_teams as reassign  # noqa: E402
from scripts import reconcile_teams_with_gotsport as reconcile  # noqa: E402
from scripts import skill_check_offline  # noqa: E402
from src.utils.gotsport_team_details import TeamDetailsResolver  # noqa: E402
from tests.unit.test_skill_check_offline import drop_update_filter, net_under_guards  # noqa: E402

EXAMINED = "Step 1 examines each team of the slice whose stored state is in --state, and no team with none"
READ_ONLY = "Step 1 without --execute writes nothing to the database"
LOGGED = "Step 1 logs every team it looked up to --exports-dir, as a dry run"
DRY_RUN_WINS = "--dry-run wins over --execute"
RENAME = (
    "with --execute a rename goes only to a live team still holding the name read, and none to a team "
    "GotSport files in another age group"
)
LIMIT = "--limit 0 examines the whole slice, where the default stops at 500 teams"
PACED = "each lookup pauses --delay, 3 s unless set, and then sends GotSport one request"
BOUNDED = "a GotSport request waits at most 15 s and is not retried"
STOPS = "ten failed lookups in a row stop the reconcile with exit code 75, its log written"
TAKES = "with --execute the reconcile takes GotSport's name where both file the team in one age group"
OTHER_AGE = "a rename is withheld, and shown in blocked_fields, where GotSport files the team in another age group"
OUR_YEAR = (
    "a rename is withheld where our name's birth year fits our age group and GotSport's states another age or no number"
)
RETIRED = "a GotSport name marking a retired registration is never taken, and is blank in the log"
FILLS = "club and state are filled only where ours is blank; a disagreement is reported, not written"
FILLED = (
    "with --execute a blank club is filled only on a live team still blank, and a blank state through "
    "apply_team_state, expecting it blank, and onto the board"
)
REPORTED = "age group and gender are logged, never written"
TRIAGED = (
    "the triage reads Step 1's read-only log: it triages the team GotSport files in another age group and no other"
)
TRIAGE_WRITES = "the triage writes nothing to the database"
TRIAGE_FILES = "the triage writes its CSV and its three plans to --exports-dir"
NO_CANDIDATE = "Step 1's read-only log adds no candidate to the bulk lane"
CANDIDATE = "an --execute reconcile's log gives the bulk lane the team GotSport files younger by its band"
RELABEL_PLAN = "the triage's relabel rows reach the age applier as would_update"
REUSED_PLAN = "the triage's reused-ID rows are pending_split, which the age applier skips"
GENDER_PLAN = "the triage's gender plan is one apply_team_fields reads"
FIELDS_DRY = "apply_team_fields writes nothing without --execute"
FIELDS_WRITES = "apply_team_fields writes each field only to a live team still holding the value it replaces"
FIELDS_LOG = "apply_team_fields logs before its first write and prints its undo command"
FIELDS_UNDO = "an undo restores each field, last write first, only while the team holds what the run wrote"
FIELDS_GENDER = "a gender other than Male or Female is refused before any write"
FIELDS_KEY = "apply_team_fields --execute stops without a service-role key, before building a client"
SPLIT_DRY = "archive_split apply without --execute writes nothing and runs no tool"
TOOLS = ("reassign_games_between_teams.py", "apply_team_fields.py", "fix_band_cohorts.py")
RECORDS = {tool: f"archive_split records the log {tool} names on its Log: line" for tool in TOOLS}
LOGS_FIRST = {tool: f"{tool} writes its log before its first write" for tool in TOOLS}
UNDO_AFTER = "apply_team_fields and fix_band_cohorts print their undo command after a run that wrote"
UNDO_DRY = "reassign_games_between_teams prints its undo command on the dry run"


def _failed(check, *args):
    result = checker.Result()
    check(result, *args)
    return [a["name"] for a in result.failures]


def _main(monkeypatch, capsys, *checks, argv=("--code-only",)):
    if checks:
        monkeypatch.setattr(checker, "CHECKS", list(checks))
    monkeypatch.setattr(sys, "argv", ["check_reconcile_skill_assumptions.py", *argv])
    code = checker.main()
    return code, capsys.readouterr().out


def _edit_module(monkeypatch, path, edit):
    """Load ``path`` as the check does, then hand the fresh module to ``edit``."""
    load = checker._module

    def edited(module_path, name):
        module = load(module_path, name)
        if module_path == path:
            edit(module)
        return module

    monkeypatch.setattr(checker, "_module", edited)


def _without_undo(main):
    """``main`` with every line naming an undo command left out of what it prints."""

    def quiet():
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            done = main()
        print("".join(line for line in out.getvalue().splitlines(keepends=True) if "Undo with" not in line), end="")
        return done

    return quiet


def _first_write_skipped(write, pending):
    """``write`` skipping each call whose rows are all ``pending``: the log a run lands before its writes."""

    def skipping(rows, *args, **kwargs):
        if rows and all(row.get("result") == pending for row in rows):
            return None
        return write(rows, *args, **kwargs)

    return skipping


def test_every_check_is_run():
    defined = {name for name in dir(checker) if name.startswith("check_")}
    assert defined == {check.__name__ for check in checker.CHECKS}


def test_the_whole_check_holds_on_today_s_code_without_a_database_or_the_network(monkeypatch, capsys):
    net_under_guards(monkeypatch, reconcile, reassign, fbc)

    code, out = _main(monkeypatch, capsys, argv=("--code-only", "--json"))

    result = json.loads(out)
    assert [a["name"] for a in result["assertions"] if not a["ok"]] == []
    assert code == 0 and len(result["assertions"]) == 39
    assert [u["name"] for u in result["unverified"]] == [name for name, _ in checker.UNVERIFIED]


def test_main_exits_1_when_an_assertion_fails(monkeypatch, capsys):
    code, out = _main(monkeypatch, capsys, lambda r: r.check("breaks", False, "why"))
    assert code == 1 and "FAIL  breaks" in out


def test_the_stand_in_for_gotsport_answers_through_the_real_resolver():
    resolver = TeamDetailsResolver()
    resolver.session = checker.GotSport({"101": checker.details("PR Blue", "u10", gender="Girls")}, down={"103"})

    with skill_check_offline.guarded():
        found, gone, failed = resolver.resolve("101"), resolver.resolve("102"), resolver.resolve("103")

    assert (found["name"], found["age_group"], found["gender"], found["state_code"]) == (
        "PR Blue",
        "u10",
        "Female",
        "AZ",
    )
    assert gone == {} and failed == {} and set(resolver.cache) == {"101", "102"}


# --- Step 1 ---------------------------------------------------------------------------------


def test_the_step_one_check_fails_when_the_state_filter_is_dropped(monkeypatch):
    fetch = reconcile.fetch_target_teams
    monkeypatch.setattr(
        reconcile, "fetch_target_teams", lambda sb, ages, states, limit, offset=0: fetch(sb, ages, [], limit, offset)
    )
    assert _failed(checker.check_step_one) == [EXAMINED]


def test_the_step_one_check_fails_when_a_dry_run_writes(monkeypatch):
    run = reconcile.run_writes
    monkeypatch.setattr(reconcile, "run_writes", lambda sb, planned, execute: run(sb, planned, True))
    assert _failed(checker.check_step_one) == [READ_ONLY, DRY_RUN_WINS]


def test_the_step_one_check_fails_when_execute_beats_dry_run(monkeypatch):
    monkeypatch.setattr(reconcile, "resolve_execute", lambda execute, dry_run: execute)
    assert _failed(checker.check_step_one) == [DRY_RUN_WINS]


def test_the_step_one_check_fails_when_a_read_only_run_logs_as_an_execute(monkeypatch):
    row = reconcile.log_row
    monkeypatch.setattr(reconcile, "log_row", lambda decision, run_mode: row(decision, "execute"))
    assert _failed(checker.check_step_one) == [LOGGED]


def test_the_step_one_check_fails_when_a_looked_up_team_goes_unlogged(monkeypatch):
    write = reconcile.write_log
    monkeypatch.setattr(reconcile, "write_log", lambda rows, path: write(rows[1:], path))
    assert LOGGED in _failed(checker.check_step_one)


def test_the_step_one_check_fails_when_a_rename_loses_its_pre_image(monkeypatch):
    drop_update_filter(monkeypatch, "team_name", "Phoenix Rising Blue")
    assert _failed(checker.check_step_one) == [RENAME]


def test_the_step_one_check_fails_when_limit_0_keeps_the_cap(monkeypatch):
    fetch = reconcile.fetch_target_teams
    monkeypatch.setattr(
        reconcile,
        "fetch_target_teams",
        lambda sb, ages, states, limit, offset=0: fetch(sb, ages, states, limit or 500, offset),
    )
    assert _failed(checker.check_step_one) == [LIMIT]


# --- GotSport lookups -----------------------------------------------------------------------


def test_the_lookup_check_fails_when_the_default_pause_changes(monkeypatch):
    add = argparse.ArgumentParser.add_argument

    def shorter_pause(self, *args, **kwargs):
        if args and args[0] == "--delay":
            kwargs["default"] = 1.0
        return add(self, *args, **kwargs)

    monkeypatch.setattr(argparse.ArgumentParser, "add_argument", shorter_pause)
    assert _failed(checker.check_lookups) == [PACED]


def test_the_lookup_check_fails_when_a_request_may_wait_longer(monkeypatch):
    init = TeamDetailsResolver.__init__
    monkeypatch.setattr(TeamDetailsResolver, "__init__", lambda self, timeout=30: init(self, timeout))
    assert _failed(checker.check_lookups) == [BOUNDED]


def test_the_lookup_check_fails_when_a_failed_request_is_retried(monkeypatch):
    resolve = TeamDetailsResolver.resolve
    monkeypatch.setattr(TeamDetailsResolver, "resolve", lambda self, pid: resolve(self, pid) or resolve(self, pid))
    assert _failed(checker.check_lookups) == [BOUNDED, STOPS]


@pytest.mark.parametrize(
    ("name", "replacement"),
    [("exit_code", lambda aborted: 0), ("next_failure_streak", lambda streak, outcome: 0)],
    ids=["exits 0", "never stops"],
)
def test_the_lookup_check_fails_when_a_run_of_failures_no_longer_stops_with_75(monkeypatch, name, replacement):
    monkeypatch.setattr(reconcile, name, replacement)
    assert _failed(checker.check_lookups) == [STOPS]


@pytest.mark.parametrize(
    "clears",
    [("resolved",), ("gone",), ()],
    ids=["a 404 no longer clears the streak", "an answer no longer clears it", "nothing clears it"],
)
def test_the_lookup_check_fails_when_the_stop_counts_failures_not_in_a_row(monkeypatch, clears):
    def streak_after(streak, outcome):
        if outcome == "failed":
            return streak + 1
        if outcome in clears:
            return 0
        return streak

    monkeypatch.setattr(reconcile, "next_failure_streak", streak_after)
    assert _failed(checker.check_lookups) == [STOPS]


def test_the_lookup_check_fails_when_the_reconcile_asks_on_after_ten_failures_in_a_row(monkeypatch):
    monkeypatch.setattr(reconcile, "next_failure_streak", lambda streak, outcome: 0)
    monkeypatch.setattr(reconcile, "exit_code", lambda aborted: 75)
    assert _failed(checker.check_lookups) == [STOPS]


def test_the_lookup_check_fails_when_the_reconcile_waits_longer_on_its_own_requests(monkeypatch):
    classify = reconcile.classify_lookup

    def waits_longer_after_the_first(resolver, provider_team_id, resolved):
        resolver.timeout = 60
        return classify(resolver, provider_team_id, resolved)

    monkeypatch.setattr(reconcile, "classify_lookup", waits_longer_after_the_first)
    assert _failed(checker.check_lookups) == [BOUNDED]


# --- what the reconcile takes ---------------------------------------------------------------


def test_the_decide_check_fails_when_our_name_is_always_kept(monkeypatch):
    monkeypatch.setattr(reconcile, "keeps_our_name", lambda *args: True)
    assert _failed(checker.check_decide) == [TAKES]


def test_the_decide_check_fails_when_a_name_from_another_age_group_is_taken(monkeypatch):
    decide = reconcile.decide

    def same_age(team, pid, resolved, outcome, state_blocks=frozenset()):
        return decide(team, pid, {**resolved, "age_group": team["age_group"]}, outcome, state_blocks)

    monkeypatch.setattr(reconcile, "decide", same_age)
    assert _failed(checker.check_decide) == [OTHER_AGE]


def test_the_decide_check_fails_when_our_birth_year_is_traded_away(monkeypatch):
    monkeypatch.setattr(reconcile, "keeps_our_name", lambda *args: False)
    assert _failed(checker.check_decide) == [OUR_YEAR]


def test_the_decide_check_fails_when_a_retired_name_is_taken(monkeypatch):
    monkeypatch.setattr(reconcile, "is_retired_registration", lambda name: False)
    assert _failed(checker.check_decide) == [RETIRED]


def test_the_decide_check_fails_when_a_blank_state_is_no_longer_filled(monkeypatch):
    monkeypatch.setattr(reconcile, "FILL_ONLY_FIELDS", ("club_name",))
    assert _failed(checker.check_decide) == [FILLS, FILLED]


def test_the_decide_check_fails_when_a_state_fill_never_reaches_the_board(monkeypatch):
    monkeypatch.setattr(reconcile, "mirror_state", lambda supabase, team_id, value: None)
    assert _failed(checker.check_decide) == [FILLED]


def test_the_decide_check_fails_when_a_club_fill_is_not_guarded_on_the_blank_it_read(monkeypatch):
    def unguarded(supabase, team_id, payload, pre_image):
        query = supabase.table("teams").update(payload).eq("team_id_master", team_id).eq("is_deprecated", False)
        return bool(query.execute().data)

    monkeypatch.setattr(reconcile, "apply_table_fields", unguarded)
    assert _failed(checker.check_decide) == [FILLED]


def test_the_decide_check_fails_when_a_state_fill_expects_no_particular_state(monkeypatch):
    apply = reconcile.apply_state
    monkeypatch.setattr(
        reconcile, "apply_state", lambda supabase, team_id, expected, *args: apply(supabase, team_id, "AZ", *args)
    )
    assert _failed(checker.check_decide) == [FILLED]


def test_the_decide_check_fails_when_an_age_group_is_written(monkeypatch):
    decide = reconcile.decide

    def writes_age(team, pid, resolved, outcome, state_blocks=frozenset()):
        decision = decide(team, pid, resolved, outcome, state_blocks)
        if decision.provider.get("age_group") not in ("", team.get("age_group")):
            decision.updates["age_group"] = decision.provider["age_group"]
        return decision

    monkeypatch.setattr(reconcile, "decide", writes_age)
    assert _failed(checker.check_decide) == [REPORTED]


# --- the triage -----------------------------------------------------------------------------


def test_the_triage_check_fails_when_the_triage_skips_a_read_only_log(monkeypatch):
    def executed_only(triage):
        latest = triage.latest_rows
        triage.latest_rows = lambda logs: [row for row in latest(logs) if row["run_mode"] == "execute"]

    _edit_module(monkeypatch, checker.TRIAGE, executed_only)
    assert _failed(checker.check_triage) == [TRIAGED]


def test_the_triage_check_fails_when_the_triage_writes(monkeypatch):
    def writes(triage):
        assess = triage.assess

        def assess_and_write(sb, row, team, *args):
            sb.table("teams").update({"age_group": "u12"}).eq("team_id_master", team["team_id_master"]).execute()
            return assess(sb, row, team, *args)

        triage.assess = assess_and_write

    _edit_module(monkeypatch, checker.TRIAGE, writes)
    assert _failed(checker.check_triage) == [TRIAGE_WRITES]


def test_the_triage_check_fails_when_the_plans_are_not_written(monkeypatch):
    _edit_module(monkeypatch, checker.TRIAGE, lambda triage: setattr(triage, "write_plans", lambda *args: {}))
    assert _failed(checker.check_triage) == [TRIAGE_FILES]


def test_the_triage_check_fails_when_the_bulk_lane_reads_a_read_only_log(monkeypatch):
    read = fbc.read_csv
    monkeypatch.setattr(fbc, "read_csv", lambda path: [{**row, "run_mode": "execute"} for row in read(path)])
    assert _failed(checker.check_triage) == [NO_CANDIDATE]


def test_the_triage_check_fails_when_the_bulk_lane_misses_a_band_confirmed_team(monkeypatch):
    monkeypatch.setattr(fbc, "single_band", lambda *names: None)
    assert _failed(checker.check_triage) == [CANDIDATE]


@pytest.mark.parametrize(
    ("action", "failed"),
    [("pending_split", [RELABEL_PLAN]), ("would_update", [REUSED_PLAN])],
)
def test_the_plans_check_fails_when_the_triage_marks_every_age_row_alike(monkeypatch, action, failed):
    def every_row(triage):
        write = triage.write_age_plan
        triage.write_age_plan = lambda rows, path, fields: write([{**r, "action": action} for r in rows], path, fields)

    _edit_module(monkeypatch, checker.TRIAGE, every_row)
    assert _failed(checker.check_triage_plans) == failed


def test_the_plans_check_fails_when_the_gender_plan_swaps_its_values(monkeypatch):
    def swapped(triage):
        write = triage.write_field_plan
        triage.write_field_plan = lambda rows, path, fields: write(
            [{**r, "old_value": r["new_value"], "new_value": r["old_value"]} for r in rows], path, fields
        )

    _edit_module(monkeypatch, checker.TRIAGE, swapped)
    assert _failed(checker.check_triage_plans) == [GENDER_PLAN]


# --- apply_team_fields ----------------------------------------------------------------------


def test_the_fields_check_fails_when_a_dry_run_writes(monkeypatch):
    def always_writes(fields):
        apply = fields.apply
        fields.apply = lambda sb, plan, execute, *args: apply(sb, plan, True, *args)

    _edit_module(monkeypatch, checker.APPLY_FIELDS, always_writes)
    # The rows a dry run that writes logs are ones its undo then replays.
    assert _failed(checker.check_apply_team_fields) == [FIELDS_DRY, FIELDS_UNDO]


@pytest.mark.parametrize(
    ("dropped", "failed"),
    # Unguarded, a re-run writes again, and logs a row its undo then replays.
    [(("gender", "Male"), [FIELDS_WRITES, FIELDS_UNDO]), (("gender", "Female"), [FIELDS_UNDO])],
    ids=["the apply's pre-image", "the undo's"],
)
def test_the_fields_check_fails_when_a_write_loses_its_guard(monkeypatch, dropped, failed):
    drop_update_filter(monkeypatch, *dropped)
    assert _failed(checker.check_apply_team_fields) == failed


@pytest.mark.parametrize("result", ["would_update", "already_applied"], ids=["a dry run's", "a re-run's"])
def test_the_fields_check_fails_when_an_undo_replays_rows_its_run_never_wrote(monkeypatch, result):
    def widened(fields):
        fields.REVERTABLE = (*fields.REVERTABLE, result)

    _edit_module(monkeypatch, checker.APPLY_FIELDS, widened)
    assert _failed(checker.check_apply_team_fields) == [FIELDS_UNDO]


@pytest.mark.parametrize(
    "edit",
    [
        lambda fields: setattr(fields, "write_rows", _first_write_skipped(fields.write_rows, "planned_not_applied")),
        lambda fields: setattr(fields, "main", _without_undo(fields.main)),
    ],
    ids=["no log before the writes", "no undo printed"],
)
def test_the_fields_check_fails_without_the_log_or_the_undo(monkeypatch, edit):
    _edit_module(monkeypatch, checker.APPLY_FIELDS, edit)
    assert _failed(checker.check_apply_team_fields) == [FIELDS_LOG]


def test_the_fields_check_fails_when_any_gender_is_accepted(monkeypatch):
    _edit_module(
        monkeypatch, checker.APPLY_FIELDS, lambda fields: setattr(fields, "GENDERS", ("Male", "Female", "Girls"))
    )
    assert _failed(checker.check_apply_team_fields) == [FIELDS_GENDER]


def test_the_fields_check_fails_when_execute_builds_a_client_from_the_anon_key(monkeypatch):
    def any_key(fields):
        build = fields.get_supabase
        fields.get_supabase = lambda execute: build(False)

    _edit_module(monkeypatch, checker.APPLY_FIELDS, any_key)
    assert _failed(checker.check_apply_team_fields) == [FIELDS_KEY]


# --- the archive split ----------------------------------------------------------------------


def test_the_split_check_fails_when_a_dry_run_runs_the_tools(monkeypatch):
    def always_executes(archive):
        apply = archive.apply
        archive.apply = lambda sb, rows, execute, stamp: apply(sb, rows, True, stamp)

    _edit_module(monkeypatch, checker.ARCHIVE, always_executes)
    assert _failed(checker.check_archive_split) == [SPLIT_DRY]


def test_the_split_check_fails_when_the_split_cannot_read_a_log_line(monkeypatch):
    def no_log_line(archive):
        run = archive.run_tool
        archive.run_tool = lambda args: run(args) and ""

    _edit_module(monkeypatch, checker.ARCHIVE, no_log_line)
    assert _failed(checker.check_archive_split) == [RECORDS[tool] for tool in TOOLS]


def _reassign_logs_last(monkeypatch):
    write, calls = reassign.write_log, []

    def skips_the_first(rows, path):
        calls.append(path)
        return None if len(calls) == 1 else write(rows, path)

    monkeypatch.setattr(reassign, "write_log", skips_the_first)


def _fields_logs_last(monkeypatch):
    def late(fields):
        fields.write_rows = _first_write_skipped(fields.write_rows, "planned_not_applied")

    _edit_module(monkeypatch, checker.APPLY_FIELDS, late)


def _fixer_logs_last(monkeypatch):
    monkeypatch.setattr(fbc, "write_csv", _first_write_skipped(fbc.write_csv, "planned_not_applied"))


@pytest.mark.parametrize(
    ("late", "tool"),
    [(_reassign_logs_last, TOOLS[0]), (_fields_logs_last, TOOLS[1]), (_fixer_logs_last, TOOLS[2])],
    ids=TOOLS,
)
def test_the_split_check_fails_when_a_tool_writes_before_its_log(monkeypatch, late, tool):
    late(monkeypatch)
    assert _failed(checker.check_archive_split) == [LOGS_FIRST[tool]]


def test_the_split_check_fails_when_a_tool_stops_printing_its_undo(monkeypatch):
    _edit_module(monkeypatch, checker.APPLY_FIELDS, lambda fields: setattr(fields, "main", _without_undo(fields.main)))
    assert _failed(checker.check_archive_split) == [UNDO_AFTER]


def test_the_split_check_fails_when_reassign_s_dry_run_stops_printing_its_undo(monkeypatch):
    monkeypatch.setattr(reassign, "main", _without_undo(reassign.main))
    assert _failed(checker.check_archive_split) == [UNDO_DRY]
