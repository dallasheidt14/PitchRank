"""The age skill's self-check. Each assertion runs over a fixture that holds and one that breaks
it, so a check that cannot fail is caught here instead of being trusted in the weekly run.

Nothing here asserts that the whole check passes on today's CLAUDE.md: that is the check's own job,
and it is meant to go red every Aug 1. The season is pinned to the one the review's literal CHART
is for, and the fixture CLAUDE.md is built from that season, so these tests survive the rollover."""

import functools
import json
import os
import re
import sys
from types import SimpleNamespace

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import scripts.check_age_skill_assumptions as checker  # noqa: E402
from scripts import fix_band_cohorts as fbc  # noqa: E402
from scripts import normalize_team_names, weekly_age_recheck  # noqa: E402
from src.utils import team_utils  # noqa: E402

REVIEW = checker._module(checker.REVIEW, "review_age_labels")
SEASON = REVIEW.CHART_SEASON
AGREEMENT = "no name the applier lets through is one the triage reads as another squad"


@pytest.fixture(autouse=True)
def _season(monkeypatch):
    monkeypatch.setattr(team_utils, "CURRENT_YEAR", SEASON)
    monkeypatch.setattr(team_utils, "_soccer_season_year", lambda: SEASON)
    monkeypatch.setattr(fbc, "_soccer_season_year", lambda: SEASON)
    for name in ("calculate_age_group_from_birth_year", "calculate_age_group_from_band"):
        convert = getattr(normalize_team_names, name)
        monkeypatch.setattr(normalize_team_names, name, functools.partial(convert, current_year=SEASON))


def _failures(check, *args):
    result = checker.Result()
    check(result, *args)
    return result.failures


def _failed(check, *args):
    return [a["name"] for a in _failures(check, *args)]


def _yy(year):
    return f"{year % 100:02d}"


def _claude_md(
    tmp_path,
    season=SEASON,
    wrong_younger=None,
    wrong_older=None,
    wrong_spelling=None,
    row_sep="/",
    clause_verb="are all",
    u10_row_copies_u13=False,
    preamble="",
):
    rows = []
    for age in range(9, 20):
        younger = season - age + 1
        older = younger - 2 if younger == wrong_older else younger - 1
        group = "u19" if age == 18 else f"u{age}"
        if younger == wrong_younger:
            group = "u15" if group == "u14" else "u14"
        rows.append(f"| {younger} {row_sep} {older} | U{age} | {group} |")
    if u10_row_copies_u13:
        rows[1] = rows[4]
    u13, u12, u11 = SEASON - 12, SEASON - 11, SEASON - 10
    u13_spellings = [
        f"{u13 - 1}/{u13}",
        f"{u13 - 1}/{_yy(u13)}",
        f"{_yy(u13 - 1)}/{_yy(u13)}",
        f"{_yy(u13)}/{_yy(u13 - 1)}",
        f"{u13 - 1}-{u13}",
        f"B{_yy(u13 - 1)}/{_yy(u13)}",
    ]
    u12_spellings = [f"{u12 - 1}/{u12}", f"{u12 - 1}/{_yy(u12)}", f"{_yy(u12 - 1)}/{_yy(u12)}"]
    u11_spellings = ["BU11", "U11", f"{_yy(u11 - 1)}/{_yy(u11)}", f"{u11 - 1}/{u11}"]

    def clause(spellings, group):
        if wrong_spelling in spellings:
            group = "U14" if group != "U14" else "U15"
        quoted = [f"`{s}`" for s in spellings]
        return f"{', '.join(quoted[:-1])} and {quoted[-1]} {clause_verb} **{group}**"

    text = "\n".join(
        [
            "# CLAUDE.md",
            preamble,
            f"### Age Groups ({season}-{_yy(season + 1)} Season)",
            "| Birth years | Real-world | PitchRank |",
            "|---|---|---|",
            *rows,
            f"**The label key.** {clause(u13_spellings, 'U13')}, and {clause(u12_spellings, 'U12')}.",
            f"A U-label is the same cohort again: {clause(u11_spellings, 'U11')}.",
            "### Division Tiers",
        ]
    )
    path = tmp_path / "CLAUDE.md"
    path.write_text(text, encoding="utf-8")
    return path


def _edit_module(monkeypatch, path, edit):
    """Load ``path`` as the check does, then hand the fresh module to ``edit``."""
    load = checker._module

    def edited(module_path, name):
        module = load(module_path, name)
        if module_path == path:
            edit(module)
        return module

    monkeypatch.setattr(checker, "_module", edited)


def _triage_reads_names_as_the_applier(monkeypatch):
    """The triage once its birth_years ignores a hyphen-wrapped B/G age and "U/10B", as the applier's
    name_years already does."""

    def strip(read):
        return lambda name: read(fbc._HYPHEN_AGE.sub(" ", fbc._UAGE_SLASH.sub(" ", name or "")))

    _edit_module(monkeypatch, checker.TRIAGE, lambda m: setattr(m, "birth_years", strip(m.birth_years)))


def _main(monkeypatch, capsys, *checks):
    monkeypatch.setattr(checker, "CHECKS", list(checks))
    monkeypatch.setattr(sys, "argv", ["check_age_skill_assumptions.py", "--code-only"])
    code = checker.main()
    return code, capsys.readouterr().out


def test_every_check_is_run():
    defined = {name for name in dir(checker) if name.startswith("check_")}
    assert defined == {check.__name__ for check in checker.CHECKS}


def test_the_check_never_builds_a_database_client(monkeypatch, capsys):
    def refuse(*args, **kwargs):
        raise AssertionError("the age check built a database client")

    monkeypatch.setattr(fbc, "create_client", refuse)
    monkeypatch.setattr(fbc, "get_supabase", refuse)
    monkeypatch.setattr("supabase.create_client", refuse)
    monkeypatch.setattr(sys, "argv", ["check_age_skill_assumptions.py", "--code-only", "--json"])

    checker.main()

    assertions = json.loads(capsys.readouterr().out)["assertions"]
    assert assertions
    assert not [a for a in assertions if a["name"].endswith("runs to the end")]


def test_main_exits_1_when_an_assertion_fails_and_0_when_all_hold(monkeypatch, capsys):
    assert _main(monkeypatch, capsys, lambda r: r.check("holds", True, ""))[0] == 0
    code, out = _main(monkeypatch, capsys, lambda r: r.check("breaks", False, "why"))
    assert code == 1 and "FAIL  breaks" in out


def test_main_reports_a_check_that_stops_and_runs_the_rest(monkeypatch, capsys):
    def stops(r):
        raise SystemExit("Cannot read the owner's age decisions")

    def holds(r):
        r.check("holds", True, "")

    code, out = _main(monkeypatch, capsys, stops, holds)
    assert code == 1
    assert "FAIL  stops runs to the end" in out and "SystemExit: Cannot read" in out and "PASS  holds" in out


def test_the_chart_holds_when_the_table_and_every_reader_agree(tmp_path):
    assert _failed(checker.check_chart, _claude_md(tmp_path)) == []


def test_the_chart_fails_on_a_table_row_the_readers_disagree_with(tmp_path):
    younger = SEASON - 13 + 1
    failed = _failed(checker.check_chart, _claude_md(tmp_path, wrong_younger=younger))
    assert failed == [f"the {younger}/{younger - 1} band is u14 in every reader"]


def test_the_chart_fails_on_a_row_whose_older_year_is_wrong(tmp_path):
    younger = SEASON - 13 + 1
    failed = _failed(checker.check_chart, _claude_md(tmp_path, wrong_older=younger))
    assert failed == [f"the {younger}/{younger - 2} band is u13 in every reader"]


def test_the_chart_names_the_one_reader_that_disagrees(monkeypatch, tmp_path):
    convert, u18 = team_utils.calculate_age_group_from_band, SEASON - 17
    monkeypatch.setattr(
        team_utils, "calculate_age_group_from_band", lambda year, *a, **k: "U18" if year == u18 else convert(year)
    )
    failures = _failures(checker.check_chart, _claude_md(tmp_path))
    assert [f["name"] for f in failures] == [f"the {u18}/{u18 - 1} band is u19 in every reader"]
    assert "calculate_age_group_from_band" in failures[0]["detail"]


def test_the_chart_fails_on_a_table_for_another_season(tmp_path):
    failed = _failed(checker.check_chart, _claude_md(tmp_path, season=SEASON + 1))
    assert "CLAUDE.md's age table is for the season the review's CHART is for" in failed


def test_the_chart_fails_when_the_table_rows_go_unread(tmp_path):
    failed = _failed(checker.check_chart, _claude_md(tmp_path, row_sep="–"))
    assert failed == ["CLAUDE.md's table lists each band from u9 to u19 once"]


def test_the_chart_fails_when_a_band_is_replaced_by_a_copy_of_another(tmp_path):
    failed = _failed(checker.check_chart, _claude_md(tmp_path, u10_row_copies_u13=True))
    assert failed == ["CLAUDE.md's table lists each band from u9 to u19 once"]


def test_the_section_starts_at_its_heading_not_at_a_mention_of_it(tmp_path):
    claude_md = _claude_md(tmp_path, preamble="The age rules live under `### Age Groups` below.")
    assert _failed(checker.check_chart, claude_md) == []
    assert _failed(checker.check_label_key, claude_md) == []


def test_the_label_key_holds_when_every_spelling_reads_as_stated(tmp_path):
    assert _failed(checker.check_label_key, _claude_md(tmp_path)) == []


def test_the_label_key_fails_on_a_clause_stated_as_the_wrong_group(tmp_path):
    spelling = f"{_yy(SEASON - 13)}/{_yy(SEASON - 12)}"
    failed = _failed(checker.check_label_key, _claude_md(tmp_path, wrong_spelling=spelling))
    # The whole "are all **U13**" clause now says U14: its six spellings fail, the other seven hold.
    assert len(failed) == 6 and f"label key: {spelling} is U14" in failed
    assert all(name.endswith(" is U14") for name in failed)


def test_the_label_key_fails_when_u_labels_read_a_group_high(monkeypatch, tmp_path):
    def one_high(review):
        labels = review.Reader.labels

        def shifted(self, name):
            ulabels, years = labels(self, name)
            return {f"u{int(u[1:]) + 1}" for u in ulabels}, years

        review.Reader.labels = shifted

    _edit_module(monkeypatch, checker.REVIEW, one_high)
    assert _failed(checker.check_label_key, _claude_md(tmp_path)) == ["label key: BU11 is U11", "label key: U11 is U11"]


def test_the_label_key_reads_a_clause_broken_across_lines(tmp_path):
    assert _failed(checker.check_label_key, _claude_md(tmp_path, clause_verb="are\nall")) == []


def test_the_label_key_fails_when_its_clauses_go_unread(tmp_path):
    failed = _failed(checker.check_label_key, _claude_md(tmp_path, clause_verb="are each"))
    assert failed == ["CLAUDE.md's label key is readable"]


def test_the_boards_hold_and_fail_when_a_u18_board_appears(monkeypatch):
    from config import settings

    assert _failed(checker.check_boards) == []
    monkeypatch.setattr(settings, "AGE_GROUPS", {**settings.AGE_GROUPS, "u18": {}})
    assert _failed(checker.check_boards) == [
        "the boards are u10-u17 and u19 (u18 files into u19; u9 and younger have none)"
    ]


def test_the_rolled_season_check_fails_when_the_reader_stops_refusing(monkeypatch):
    assert _failed(checker.check_rolled_season) == []
    monkeypatch.setattr(checker, "_module", lambda path, name: SimpleNamespace(CHART_SEASON=SEASON, Reader=object))
    assert _failed(checker.check_rolled_season) == ["the review's Reader refuses a season its CHART is not for"]


def test_the_owner_decisions_check_fails_on_a_section_without_its_decision(monkeypatch, tmp_path):
    assert _failed(checker.check_owner_decisions) == []
    broken = tmp_path / "owner_decisions.json"
    broken.write_text(json.dumps({"left_held": {"teams": [{"team_id": checker.LIVE_ID}]}}), encoding="utf-8")
    monkeypatch.setattr(fbc, "OWNER_DECISIONS", broken)
    assert _failed(checker.check_owner_decisions) == [
        "owner_decisions.json is sections of {decided, teams: [{team_id}]}",
        "every decided team loads under its own section",
    ]


def test_the_owner_decisions_check_fails_when_a_missing_file_reads_as_empty(monkeypatch):
    load = fbc.load_owner_decisions
    monkeypatch.setattr(fbc, "load_owner_decisions", lambda sb: load(sb) if fbc.OWNER_DECISIONS.exists() else {})
    assert _failed(checker.check_owner_decisions) == [
        "a missing decisions file stops the run instead of reading as empty"
    ]


def test_the_applier_check_fails_when_a_dry_run_writes(monkeypatch):
    assert _failed(checker.check_applier) == []
    apply_plan = fbc.apply_plan
    monkeypatch.setattr(fbc, "apply_plan", lambda sb, plan, execute, *a, **k: apply_plan(sb, plan, True, *a, **k))
    assert _failed(checker.check_applier) == [
        "the applier writes nothing without --execute",
        "--dry-run wins over --execute",
    ]


def test_the_applier_check_fails_when_execute_beats_dry_run(monkeypatch):
    apply_plan = fbc.apply_plan

    def execute_wins(sb, plan, execute, *args, **kwargs):
        return apply_plan(sb, plan, execute or "--execute" in sys.argv, *args, **kwargs)

    monkeypatch.setattr(fbc, "apply_plan", execute_wins)
    assert _failed(checker.check_applier) == ["--dry-run wins over --execute"]


@pytest.mark.parametrize(
    ("dropped", "claim"),
    [
        (("age_group", "u13"), "an apply writes only to a live team still holding the planned old age group"),
        (("is_deprecated", False), "an apply writes only to a live team still holding the planned old age group"),
        (("age_group", "u12"), "an undo restores only a team still holding what the apply wrote"),
    ],
)
def test_the_applier_check_fails_when_a_write_loses_a_filter(monkeypatch, dropped, claim):
    eq = checker._Request.eq

    def drop_on_writes(self, column, value):
        return self if self.payload is not None and (column, value) == dropped else eq(self, column, value)

    monkeypatch.setattr(checker._Request, "eq", drop_on_writes)
    assert _failed(checker.check_applier) == [claim]


def test_the_applier_check_fails_when_a_decided_team_is_moved(monkeypatch):
    monkeypatch.setattr(fbc, "load_owner_decisions", lambda sb: {})
    assert _failed(checker.check_applier) == ["the applier holds a team the owner decided to leave"]


def test_offline_sets_no_credentials_and_builds_no_real_client(monkeypatch):
    names = [
        "SUPABASE_URL",
        "NEXT_PUBLIC_SUPABASE_URL",
        "SUPABASE_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_SERVICE_KEY",
    ]
    for name in names:
        monkeypatch.setenv(name, "set-outside")
    recorder = checker._Recorder()
    with checker._offline(recorder):
        assert [os.environ.get(name) for name in names] == [""] * len(names)
        assert fbc.get_supabase() is recorder
        with pytest.raises(RuntimeError, match="real database client"):
            fbc.create_client("https://example.invalid", "key")


@pytest.mark.parametrize(
    "build",
    [
        lambda t: t.select("team_id_master").update({"age_group": "u12"}),
        lambda t: t.update({"age_group": "u12"}).select("team_id_master"),
        lambda t: t.update({"age_group": "u12"}).eq("team_id_master", "x").order("team_id_master"),
        lambda t: t.update({"age_group": "u12"}).range(0, 9),
        lambda t: t.eq("team_id_master", "x"),
        lambda t: t.execute(),
    ],
    ids=[
        "update after select",
        "select after update",
        "order an update",
        "page an update",
        "filter a table",
        "execute a table",
    ],
)
def test_the_recorder_refuses_what_postgrest_refuses(build):
    with pytest.raises(AttributeError):
        build(checker._Recorder().table("teams"))


def test_the_recheck_holds_and_fails_when_its_run_ignores_the_decisions(monkeypatch):
    assert _failed(checker.check_recheck) == []
    monkeypatch.setattr(fbc, "load_owner_decisions", lambda sb: {})
    assert _failed(checker.check_recheck) == [
        "the weekly re-check leaves a decided team out of its live read",
        "the weekly re-check reports the decided team it left out",
    ]


def test_the_recheck_fails_when_it_stops_counting_the_teams_left_out(monkeypatch):
    pending = weekly_age_recheck.pending_population
    monkeypatch.setattr(
        weekly_age_recheck, "pending_population", lambda sb, exports, decided: (pending(sb, exports, decided)[0], 0)
    )
    assert _failed(checker.check_recheck) == ["the weekly re-check reports the decided team it left out"]


def _read_one_by_one(sb, ids):
    for tid in ids:
        sb.table("teams").select("team_id_master").eq("team_id_master", tid).execute()


@pytest.mark.parametrize("read", [fbc.fetch_live, _read_one_by_one])
def test_the_recheck_fails_when_it_reads_a_decided_team_live(monkeypatch, read):
    pending = weekly_age_recheck.pending_population

    def reads_decided(sb, exports, decided):
        read(sb, list(decided))
        return pending(sb, exports, decided)

    monkeypatch.setattr(weekly_age_recheck, "pending_population", reads_decided)
    assert _failed(checker.check_recheck) == ["the weekly re-check leaves a decided team out of its live read"]


def test_the_recheck_fails_when_it_skips_its_live_read(monkeypatch):
    pending = weekly_age_recheck.pending_population
    monkeypatch.setattr(
        weekly_age_recheck,
        "pending_population",
        lambda sb, exports, decided: pending(checker._Recorder(), exports, decided),
    )
    assert _failed(checker.check_recheck) == ["the weekly re-check reads a pending team live"]


def test_the_triage_check_fails_when_the_triage_skips_its_live_read(monkeypatch):
    _triage_reads_names_as_the_applier(monkeypatch)

    def reads_elsewhere(triage):
        fetch_in = triage.fetch_in
        triage.fetch_in = lambda sb, table, *args: fetch_in(checker._Recorder(), table, *args)

    _edit_module(monkeypatch, checker.TRIAGE, reads_elsewhere)
    assert _failed(checker.check_triage) == ["the triage reads a pending team live"]


def test_the_triage_check_holds_once_the_triage_reads_names_as_the_applier(monkeypatch):
    _triage_reads_names_as_the_applier(monkeypatch)
    assert _failed(checker.check_triage) == []


def test_the_triage_run_writes_only_to_its_temp_folder(monkeypatch, tmp_path):
    _triage_reads_names_as_the_applier(monkeypatch)
    _edit_module(monkeypatch, checker.TRIAGE, lambda m: setattr(m, "EXPORTS", tmp_path))
    assert _failed(checker.check_triage) == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("check", "pattern", "claim"),
    [
        (checker.check_recheck, "RECHECK_LEFT_OUT", "the weekly re-check reports the decided team it left out"),
        (checker.check_triage, "TRIAGE_LEFT_OUT", "the triage reports the decided team it left out"),
    ],
)
def test_the_left_out_count_fails_when_its_line_is_not_found(monkeypatch, check, pattern, claim):
    _triage_reads_names_as_the_applier(monkeypatch)
    monkeypatch.setattr(checker, pattern, re.compile(r"(?!)"))
    assert _failed(check) == [claim]


def test_the_triage_check_reports_the_u_ages_the_triage_still_reads_as_birth_years():
    """Known failure: flips once the triage reads these as last season's U-ages; then drop this test."""
    failures = _failures(checker.check_triage)
    assert [f["name"] for f in failures] == [AGREEMENT]
    assert (
        failures[0]["detail"]
        == "applier passes, triage objects: [('Town-G09A-Coach', 'u10'), ('Club U/10B Blue', 'u10')]"
    )


def test_the_triage_check_fails_when_the_triage_objects_to_any_stated_year(monkeypatch):
    _edit_module(
        monkeypatch, checker.TRIAGE, lambda m: setattr(m, "birth_years", lambda name: {1990} if name else set())
    )
    failures = _failures(checker.check_triage)
    assert [f["name"] for f in failures] == [AGREEMENT]
    assert f"('Club {_yy(SEASON - 12)}B Blue', 'u13')" in failures[0]["detail"]


def test_the_triage_check_fails_when_a_decided_team_is_assessed(monkeypatch):
    _triage_reads_names_as_the_applier(monkeypatch)

    def ignore_decisions(triage):
        assess = triage.assess
        triage.assess = lambda sb, row, team, ids, start, since, declined: assess(sb, row, team, ids, start, since, {})

    _edit_module(monkeypatch, checker.TRIAGE, ignore_decisions)
    assert _failed(checker.check_triage) == ["the triage passes over a team the owner decided to leave"]


def test_the_triage_check_fails_when_its_run_ignores_the_decisions(monkeypatch):
    _triage_reads_names_as_the_applier(monkeypatch)
    _edit_module(monkeypatch, checker.TRIAGE, lambda m: setattr(m, "load_owner_decisions", lambda sb: {}))
    assert _failed(checker.check_triage) == [
        "the triage leaves a decided team out of its live read",
        "the triage reports the decided team it left out",
    ]


def test_the_triage_check_fails_when_the_triage_keeps_its_own_cohort_years(monkeypatch):
    _triage_reads_names_as_the_applier(monkeypatch)
    _edit_module(
        monkeypatch, checker.TRIAGE, lambda m: setattr(m, "cohort_years", lambda *a, **k: fbc.cohort_years(*a, **k))
    )
    assert _failed(checker.check_triage) == ["the triage and the applier share one cohort_years"]


def test_the_name_rules_fail_when_a_u17_year_stops_holding_a_move_into_u19(monkeypatch):
    monkeypatch.setattr(fbc, "name_contradiction", lambda name, target: "")
    assert _failed(checker.check_name_rules) == ["a U17 birth year in the name still holds a move into u19"]


def test_the_name_rules_fail_when_u19_drops_the_u18_year(monkeypatch):
    assert _failed(checker.check_name_rules) == []
    monkeypatch.setattr(fbc, "cohort_years", lambda age, season=None: {SEASON - 19, SEASON - 18})
    assert _failed(checker.check_name_rules) == [
        "u19 holds three birth years, U18's included",
        "a U18 birth year in the name does not hold a move into u19",
    ]


def test_the_band_spellings_fail_when_apostrophe_bands_go_unread(monkeypatch):
    assert _failed(checker.check_band_spellings) == []
    monkeypatch.setattr(team_utils, "extract_band_birth_year", lambda *args, **kwargs: None)
    assert _failed(checker.check_band_spellings) == [
        "an apostrophe band is read: Club '11/'12 Blue",
        "an apostrophe band is read: Club ‘11/‘12 Blue",
    ]


def test_the_band_spellings_fail_when_the_tidy_up_rewrites_the_aged_out_band(monkeypatch):
    monkeypatch.setattr(normalize_team_names, "normalize_team_name", lambda name, *args, **kwargs: "Club U19 Red")
    assert _failed(checker.check_band_spellings) == ["the name tidy-up leaves the aged-out band as written"]


def test_the_band_spellings_fail_when_the_aged_out_band_loses_its_label(monkeypatch):
    aged_out, resolve = f"{SEASON - 20}/{SEASON - 19}", fbc._resolve_band
    monkeypatch.setattr(fbc, "_resolve_band", lambda name: (name, None) if aged_out in name else resolve(name))
    assert _failed(checker.check_band_spellings) == [
        "an aged-out band still reads as u19 to the applier, so its refusals hold"
    ]


GATE = "${{ env.AGE_DERIVATION_ENABLED == 'true' }}"
RUN = "python scripts/fix_team_age_groups.py"


def _workflow(folder, name, flag="'false'", job_flag=None, steps=((None, GATE, RUN),)):
    """One job whose steps are (step-level flag, if:, run:), named "Fix ages 1", "Fix ages 2", ..."""
    lines = ["env:", f"  AGE_DERIVATION_ENABLED: {flag}", "jobs:", "  fix:"]
    if job_flag:
        lines += ["    env:", f"      AGE_DERIVATION_ENABLED: {job_flag}"]
    lines.append("    steps:")
    for n, (step_flag, gate, run) in enumerate(steps, 1):
        lines += [f"      - name: Fix ages {n}", f"        if: {gate}", f"        run: {run}"]
        if step_flag:
            lines += ["        env:", f"          AGE_DERIVATION_ENABLED: {step_flag}"]
    (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


ENV_FAILS = "AGE_DERIVATION_ENABLED is 'false' for b.yaml fix/Fix ages {}"
GATE_FAILS = "b.yaml fix/Fix ages {} runs only when AGE_DERIVATION_ENABLED is 'true'"


@pytest.mark.parametrize(
    ("second", "failed"),
    [
        ({}, []),
        ({"flag": "false"}, []),
        ({"flag": "'true'"}, [ENV_FAILS.format(1)]),
        ({"job_flag": "'true'"}, [ENV_FAILS.format(1)]),
        ({"steps": ((None, GATE, RUN), ("'true'", GATE, RUN))}, [ENV_FAILS.format(2)]),
        ({"steps": ((None, GATE, RUN), (None, "${{ always() }}", RUN))}, [GATE_FAILS.format(2)]),
        ({"steps": ((None, "${{ always() }}", "python -m scripts.fix_team_age_groups"),)}, [GATE_FAILS.format(1)]),
        ({"steps": ((None, "false", RUN),)}, []),
        (
            {
                "steps": (
                    (
                        None,
                        "${{ !contains(format(',{0},', github.event.inputs.skip_steps || ''), ',2,') "
                        "&& env.AGE_ROLLOVER_FREEZE == 'false' && env.AGE_DERIVATION_ENABLED == 'TRUE' }}",
                        RUN,
                    ),
                )
            },
            [],
        ),
        ({"steps": ((None, "${{ env.AGE_DERIVATION_ENABLED == 'true' || always() }}", RUN),)}, [GATE_FAILS.format(1)]),
        (
            {
                "steps": (
                    (
                        None,
                        "${{ env.AGE_DERIVATION_ENABLED == 'true' && env.AGE_ROLLOVER_FREEZE == 'false' "
                        "|| github.event_name == 'workflow_dispatch' }}",
                        RUN,
                    ),
                )
            },
            [GATE_FAILS.format(1)],
        ),
        (
            {
                "steps": (
                    (
                        None,
                        "${{ (env.AGE_DERIVATION_ENABLED == 'true' || github.event_name == 'workflow_dispatch') "
                        "&& env.AGE_ROLLOVER_FREEZE == 'false' }}",
                        RUN,
                    ),
                )
            },
            [GATE_FAILS.format(1)],
        ),
        ({"steps": ((None, "${{ !(env.AGE_DERIVATION_ENABLED == 'true') }}", RUN),)}, [GATE_FAILS.format(1)]),
    ],
    ids=[
        "holds",
        "unquoted false",
        "workflow flag on",
        "job flag on",
        "second step's flag on",
        "second step ungated",
        "module form ungated",
        "switched off",
        "skip-steps and freeze gate",
        "top-level or",
        "or after an and",
        "nested or",
        "negated",
    ],
)
def test_the_derivation_check_reads_every_step_that_runs_it(monkeypatch, tmp_path, second, failed):
    _workflow(tmp_path, "a.yml")
    _workflow(tmp_path, "b.yaml", **second)
    monkeypatch.setattr(checker, "WORKFLOWS", tmp_path)
    assert _failed(checker.check_derivation_off) == failed


def test_the_derivation_check_fails_when_no_step_runs_it(monkeypatch, tmp_path):
    (tmp_path / "other.yml").write_text("jobs:\n  other:\n    steps:\n      - run: echo hi\n", encoding="utf-8")
    monkeypatch.setattr(checker, "WORKFLOWS", tmp_path)
    assert _failed(checker.check_derivation_off) == ["a workflow step running fix_team_age_groups is found"]


def test_the_derivation_check_reads_both_real_workflows_and_holds():
    """Season-independent, so it reads the real workflows: an edit that turns the derivation on fails CI."""
    found = {workflow.name for workflow, *_ in checker._derivation_steps(checker.WORKFLOWS)}
    assert found == {"data-hygiene-weekly.yml", "fix-age-year-discrepancies.yml"}
    assert _failed(checker.check_derivation_off) == []
