from dataclasses import replace

import httpx
import pytest
from streamlit.testing.v1 import AppTest

import tournament_intake as intake
from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_run_store import SeedingRun, SeedingRunEntry, load_run, save_run
from tests.unit.test_seeding_event_intake import _FakeSessionState, _FakeSt, _install, _Rerun, _roster, _team

APP = '''
import streamlit as st
import tournament_intake as app
from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
app._init_session_state()
if not st.session_state.get("_seeding_result"):
    parsed = parse_roster("Boys U10\\nClub\\tA\\nClub\\tB\\nGirls U9/U10 Mexico\\nClub\\tMixed")
    app._park_seeding_result((parsed, (ResolvedTeam(0, "gotsport_id", team_id_master="a", matched_name="Database A"),
                                     ResolvedTeam(1, "unresolved"), ResolvedTeam(2, "unresolved"))), event_id=None)
    st.session_state["_seeding_assessment"] = {"coverage": "complete", "source_kind": "Paste team list", "completed": [0,1,2]}
    st.session_state["seeding_event_name"] = "Workflow Cup"
app._render_seeding_tab(None)
'''


COMPLETED_NOT_FOUND_APP = '''
import streamlit as st
import tournament_intake as app
from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
app._init_session_state()
if not st.session_state.get("_seeding_result"):
    text = "Boys U14\\n" + "\\n".join(f"Club\\tTeam {index}" for index in range(14))
    text += "\\nBoys U15\\n" + "\\n".join(f"Club\\tTeam {index}" for index in range(14, 24))
    parsed = parse_roster(text)
    resolved = tuple(
        ResolvedTeam(index, "gotsport_id", team_id_master=f"team-{index}", matched_name=f"Team {index}")
        if index < 12 else ResolvedTeam(index, "unresolved")
        for index in range(24)
    )
    app._park_seeding_result((parsed, resolved), event_id=None)
    st.session_state["_seeding_overrides"] = {index: {"not_found": True} for index in range(12, 24)}
    st.session_state["_seeding_assessment"] = {
        "coverage": "complete",
        "source_kind": "Paste team list",
        "completed": list(range(24)),
    }
    st.session_state["_seeding_pack_scope"] = "Choose cohorts"
    st.session_state["_seeding_pack_cohorts"] = ["u14|Male"]
    st.session_state["_seeding_pack"] = {"selected_cohorts": ["u14|Male"]}
    st.session_state["seeding_event_name"] = "Completed Workflow Cup"
app._render_seeding_tab(None)
'''


@pytest.fixture
def operator(monkeypatch, tmp_path):
    monkeypatch.setattr(intake, "default_seeding_base_dir", lambda: tmp_path)
    monkeypatch.setattr(intake, "list_seeding_runs", lambda: [])
    monkeypatch.setattr(intake, "_autosave_seeding_run", lambda **_kwargs: True)
    monkeypatch.setattr(intake, "_render_seeding_event_scrape", lambda *_args: None)
    monkeypatch.setattr(intake, "RefreshQueue", lambda *_args: pytest.fail("render queried refresh service"))
    app = AppTest.from_string(APP, default_timeout=15).run()
    assert not app.exception
    return app


@pytest.fixture
def completed_not_found_operator(monkeypatch, tmp_path):
    monkeypatch.setattr(intake, "default_seeding_base_dir", lambda: tmp_path)
    monkeypatch.setattr(intake, "list_seeding_runs", lambda: [])
    monkeypatch.setattr(intake, "_autosave_seeding_run", lambda **_kwargs: True)
    monkeypatch.setattr(intake, "_render_seeding_event_scrape", lambda *_args: None)
    monkeypatch.setattr(intake, "_render_seeding_sheet", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(intake, "snapshot_matches_roster", lambda *_args, **_kwargs: False)
    app = AppTest.from_string(COMPLETED_NOT_FOUND_APP, default_timeout=15).run()
    assert not app.exception
    return app


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception


def test_summary_and_single_review_are_usable_during_database_outage(operator):
    app = operator
    assert {metric.label: metric.value for metric in app.metric} == {
        "Resolved": "1", "Matched": "1", "Not found": "0", "Needs attention": "2",
        "Total U10+ teams": "2–3", "Matched": "1", "Manual matches needed": "2",
        "Additional cohort / input fixes": "0", "Suggested event price": "$199",
    }
    assert sum(widget.label == "GotSport team link or PitchRank team ID" for widget in app.text_input) == 1
    assert any(button.label == "Save this run" for button in app.button)
    assert any(button.label == "Load PitchRank team names" for button in app.button)
    assert not any(button.label == "Build seeding sheets" for button in app.button)
    assert not app.error


def test_cohort_correction_changes_quote_and_can_exclude_younger(operator):
    app = operator
    next(widget for widget in app.selectbox if widget.label == "Show").set_value("Cohort / input questions").run()
    next(widget for widget in app.selectbox if widget.label == "Tournament age group").set_value("u9")
    click(app, "Apply correction")
    assert next(metric.value for metric in app.metric if metric.label == "Total U10+ teams") == "2"
    assert next(metric.value for metric in app.metric if metric.label == "Additional cohort / input fixes") == "0"
    assert any("Quote ready" in message.value for message in app.success)
    assert len(app.session_state["_seeding_result"][0].rows) == 3


def test_mark_not_found_removes_team_from_matching_queue(operator):
    app = operator
    next(widget for widget in app.radio if widget.label == "Match decision").set_value("Not found in PitchRank").run()
    click(app, "Confirm not found in PitchRank")

    assert app.session_state["_seeding_overrides"][1] == {"not_found": True}
    assert 1 in app.session_state["_seeding_assessment"]["completed"]
    assert next(metric.value for metric in app.metric if metric.label == "Resolved") == "2"
    assert next(metric.value for metric in app.metric if metric.label == "Manual matches needed") == "1"
    assert any("Marked not found in PitchRank: 1" in caption.value for caption in app.caption)
    next(widget for widget in app.selectbox if widget.label == "Show").set_value("Not found in PitchRank").run()
    assert any(button.label == "Reopen matching" for button in app.button)


def test_only_the_active_workflow_step_renders(operator):
    app = operator
    headings = [item.value for item in app.markdown]
    assert "### 2. Match teams to PitchRank" in headings
    assert next(button for button in app.button if button.label == "3. Review seed order").disabled
    assert not any(value.startswith("### 1.") or value.startswith("### 3.") or value.startswith("### 4.")
                   for value in headings)

    app.session_state["_seeding_active_step"] = 1
    app.run()
    headings = [item.value for item in app.markdown]
    assert "### 1. Import tournament teams" in headings
    assert not any(value.startswith("### 2.") or value.startswith("### 3.") or value.startswith("### 4.")
                   for value in headings)

    click(app, "Continue to matching")
    headings = [item.value for item in app.markdown]
    assert "### 2. Match teams to PitchRank" in headings
    assert next(button for button in app.button if button.label == "Continue to seed order").disabled


def test_completed_run_keeps_step_two_clickable_and_focuses_not_found(completed_not_found_operator):
    app = completed_not_found_operator
    match_step = next(button for button in app.button if button.label == "2. Match to PitchRank")
    seed_step = next(button for button in app.button if button.label == "3. Review seed order")
    assert not match_step.disabled
    assert seed_step.disabled
    assert any("Complete · 12 matched · 12 not found" == caption.value for caption in app.caption)
    before_result = app.session_state["_seeding_result"]
    before_overrides = dict(app.session_state["_seeding_overrides"])

    match_step.click().run()

    assert not app.exception
    assert "### 2. Match teams to PitchRank" in [item.value for item in app.markdown]
    assert next(widget for widget in app.selectbox if widget.label == "Show").value == "Not found in PitchRank"
    assert next(widget for widget in app.selectbox if widget.label == "Filter cohort").value == "Boys U14"
    assert any(button.label == "Reopen matching" for button in app.button)
    assert app.session_state["_seeding_result"] == before_result
    assert dict(app.session_state["_seeding_overrides"]) == before_overrides


def test_step_two_does_not_focus_a_selected_cohort_without_not_found_teams(
    completed_not_found_operator,
):
    app = completed_not_found_operator
    parsed, resolved = app.session_state["_seeding_result"]
    updated = list(resolved)
    for index in (12, 13):
        updated[index] = ResolvedTeam(
            index,
            "gotsport_id",
            team_id_master=f"team-{index}",
            matched_name=f"Team {index}",
        )
    app.session_state["_seeding_result"] = (parsed, tuple(updated))
    app.session_state["_seeding_overrides"] = {
        index: {"not_found": True} for index in range(14, 24)
    }
    app.run()

    next(button for button in app.button if button.label == "2. Match to PitchRank").click().run()

    assert not app.exception
    assert next(widget for widget in app.selectbox if widget.label == "Show").value == "Not found in PitchRank"
    assert next(widget for widget in app.selectbox if widget.label == "Filter cohort").value == "All cohorts"
    assert any(button.label == "Reopen matching" for button in app.button)


def test_seed_order_callout_opens_the_not_found_review(completed_not_found_operator):
    app = completed_not_found_operator
    assert any(
        message.value
        == "2 accepted teams have no PitchRank match. They remain in the pack without a PowerScore. "
        "These teams are already marked not found. Reviewing them again is optional."
        for message in app.info
    )

    click(app, "Review 2 not-found teams")

    assert "### Review 2 unmatched teams" in [item.value for item in app.markdown]
    assert not app.selectbox
    assert {button.key for button in app.button if button.label == "Reopen matching"} == {
        "_seeding_seed_reopen_12", "_seeding_seed_reopen_13",
    }
    assert any("Team 12" in item.value for item in app.markdown)
    assert any("Team 13" in item.value for item in app.markdown)
    assert not any("Team 14" in item.value for item in app.markdown)

    click(app, "Reopen matching")

    assert not app.selectbox
    assert app.session_state["_seeding_focused_review_indices"] == [12, 13]
    assert any(widget.label == "Match decision" for widget in app.radio)
    assert app.button(key="_seeding_focused_return").disabled

    next(widget for widget in app.radio if widget.label == "Match decision").set_value("Not found in PitchRank").run()
    click(app, "Confirm not found in PitchRank")
    assert not app.button(key="_seeding_focused_return").disabled
    click(app, "Return to seed order")
    assert app.session_state["_seeding_active_step"] == 3
    assert app.session_state["seeding_event_name"] == "Completed Workflow Cup"
    assert app.session_state["_seeding_pack_cohorts"] == ["u14|Male"]
    assert app.session_state["_seeding_overrides"][12] == {"not_found": True}
    assert "_seeding_focused_review_indices" not in app.session_state


def test_reopening_not_found_over_an_automatic_match_keeps_the_team_visible(
    completed_not_found_operator,
):
    app = completed_not_found_operator
    parsed, resolved = app.session_state["_seeding_result"]
    updated = list(resolved)
    updated[12] = ResolvedTeam(
        12,
        "gotsport_id",
        team_id_master="team-12",
        matched_name="Team 12",
    )
    app.session_state["_seeding_result"] = (parsed, tuple(updated))
    app.run()

    click(app, "Review 2 not-found teams")
    click(app, "Reopen matching")

    assert not app.selectbox
    assert app.session_state["_seeding_focused_review_indices"] == [12, 13]
    assert any(widget.label == "Match decision" for widget in app.radio)
    assert app.button(key="_seeding_focused_return").disabled
    click(app, "Done")
    assert not app.button(key="_seeding_focused_return").disabled


def test_focused_review_returns_without_changing_decisions(completed_not_found_operator):
    app = completed_not_found_operator
    app.session_state["_seeding_pack"] = {"selected_cohorts": ["u15|Male"]}
    app.run()
    before = dict(app.session_state["_seeding_overrides"])
    before_result = app.session_state["_seeding_result"]
    click(app, "Review 2 not-found teams")
    app.run()  # Hidden run/scope widgets must survive cleanup on another rerun.
    assert app.session_state["_seeding_pack_cohorts"] == ["u14|Male"]
    click(app, "Return to seed order")
    assert app.session_state["_seeding_result"] == before_result
    assert dict(app.session_state["_seeding_overrides"]) == before
    assert app.session_state["_seeding_pack_cohorts"] == ["u14|Male"]
    assert app.session_state["seeding_event_name"] == "Completed Workflow Cup"


def test_unnamed_focused_review_does_not_claim_decisions_are_saved(completed_not_found_operator):
    app = completed_not_found_operator
    app.text_input(key="seeding_event_name").set_value("").run()
    assert not any("decisions are saved" in message.value for message in app.info)
    click(app, "Review 2 not-found teams")
    assert any("This run is not saved" in message.value for message in app.warning)
    click(app, "Open full matching tools")
    assert app.text_input(key="seeding_event_name").value == ""
    assert any("Give this run a name" in message.value for message in app.info)


def test_focused_review_can_open_full_tools(completed_not_found_operator):
    app = completed_not_found_operator
    click(app, "Review 2 not-found teams")
    click(app, "Open full matching tools")
    assert "_seeding_focused_review_indices" not in app.session_state
    assert any(widget.label == "Show" for widget in app.selectbox)
    assert app.session_state["_seeding_active_step"] == 2


@pytest.mark.parametrize("pending_rows, expected_summary", [
    ([], "29 need matching · 5 more need cohort/input fixes · 34 teams total to review."),
    ([215, 216, 217], "26 need matching · 5 more need cohort/input fixes · 3 awaiting lookup · 34 teams total to review."),
])
def test_review_summary_counts_each_team_once(pending_rows, expected_summary):
    app = AppTest.from_string('''
import streamlit as st
from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_review_ui import render_assessment
text = "Boys U10\\n" + "\\n".join(f"Club\\tTeam {i}" for i in range(215))
text += "\\nGirls U9/U10\\n" + "\\n".join(f"Club\\tTeam {i}" for i in range(215, 227))
parsed = parse_roster(text)
resolved = tuple(
    ResolvedTeam(i, "gotsport_id", team_id_master=f"team-{i}")
    if i < 193 or i >= 222 else ResolvedTeam(i, "unresolved")
    for i in range(227)
)
st.session_state["_seeding_assessment"] = {
    "coverage": "complete", "completed": [i for i in range(227) if i not in st.session_state.pending_rows],
}
render_assessment(parsed, resolved, {i: {"team_id_master": f"team-{i}"} for i in range(5)})
''', default_timeout=15)
    app.session_state["pending_rows"] = pending_rows
    app.run()

    assert not app.exception
    assert expected_summary in [caption.value for caption in app.caption]
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Matched"] == "198"
    assert metrics["Additional cohort / input fixes"] == "5"
    assert "Manual matches applied: 5 · Younger teams excluded: 0" in [caption.value for caption in app.caption]


def test_manual_lookup_transport_error_does_not_hide_quote_or_export(operator, monkeypatch):
    monkeypatch.setattr(intake, "_seeding_provider_id_lookup", lambda *_args: (_ for _ in ()).throw(httpx.ConnectError("refused")))
    app = operator
    next(widget for widget in app.text_input if widget.label.startswith("GotSport team link")).set_value("12345").run()
    assert not app.exception
    assert any("temporarily unavailable" in error.value for error in app.error)
    assert any(metric.label == "Suggested event price" for metric in app.metric)
    assert next(button for button in app.button if button.label == "Continue to seed order").disabled


def test_incremental_lookup_keeps_success_and_retries_only_unfinished(monkeypatch):
    fake = _install(monkeypatch, _FakeSt())
    parsed = parse_roster("Boys U10\nC\tA\nC\tB\nC\tC")
    resolved = tuple(ResolvedTeam(index, "unresolved", provider_team_id=str(index)) for index in range(3))
    intake._park_seeding_result((parsed, resolved), event_id="123")
    fake.session_state["_seeding_assessment"] = {"coverage": "complete", "event_id": "123", "completed": []}
    fake.session_state["_seeding_overrides"] = {}
    calls = []
    failed = False

    def lookup(provider_id):
        nonlocal failed
        calls.append(provider_id)
        if provider_id == "1" and not failed:
            failed = True
            raise httpx.ConnectError("connection refused")
        return "master-" + provider_id

    monkeypatch.setattr(intake, "_seeding_provider_id_lookup", lambda _client: lookup)
    monkeypatch.setattr(intake, "_enrich_seeding_names", lambda resolved, _client: tuple(resolved))
    checkpoints = []
    monkeypatch.setattr(intake, "_autosave_seeding_run", lambda **_kwargs: checkpoints.append(fake.session_state["_seeding_result"]) or True)
    intake._run_seeding_name_lookup(parsed, resolved, None)
    assert fake.session_state["_seeding_result"][1][0].team_id_master == "master-0"
    assert fake.session_state["_seeding_assessment"]["completed"] == [0]
    assert fake.session_state["_seeding_resolution_failed"]
    intake._run_seeding_name_lookup(*fake.session_state["_seeding_result"], None)
    assert calls == ["0", "1", "1", "2"]
    assert fake.session_state["_seeding_assessment"]["completed"] == [0, 1, 2]
    assert not fake.session_state["_seeding_resolution_failed"]
    assert checkpoints[0][1][0].team_id_master == "master-0"


def test_pending_blank_url_clears_previous_event_and_source(monkeypatch):
    fake = _install(monkeypatch, _FakeSt())
    fake.session_state.update(seeding_event_url="https://system.gotsport.com/org_event/events/123",
                              _seeding_pending_event_url="", _seeding_pending_name="Pasted cup",
                              _seeding_assessment={"source_kind": "Paste team list"})
    intake._apply_pending_seeding_widgets()
    assert fake.session_state["seeding_event_url"] == ""
    assert fake.session_state["_seeding_source"] == "Paste team list"


def test_incomplete_context_cannot_save_old_rows_with_new_coverage(monkeypatch):
    fake = _install(monkeypatch, _FakeSt())
    parsed = parse_roster("Boys U10\nC\tA")
    intake._park_seeding_result((parsed, (ResolvedTeam(0, "unresolved"),)), event_id="123")
    fake.session_state.update(seeding_event_name="Cup", _seeding_assessment={"fingerprint": "another roster"})
    monkeypatch.setattr(intake, "save_seeding_run_file", lambda *_args: pytest.fail("mixed context saved"))
    assert not intake._autosave_seeding_run()


def test_name_enrichment_batches_100_and_preserves_authoritative_id():
    batches = []
    class Client:
        def table(self, name):
            assert name == "teams"
            return self
        def select(self, _columns):
            return self
        def in_(self, column, ids):
            assert column == "team_id_master"
            self.ids = ids
            return self
        def execute(self):
            batches.append(self.ids)
            return type("Response", (), {"data": [{"team_id_master": value, "team_name": "Name " + value} for value in self.ids]})()
    resolved = tuple(ResolvedTeam(index, "gotsport_id", team_id_master=str(index), matched_name="Provider name")
                     for index in range(205))
    enriched = intake._enrich_seeding_names(resolved, Client())
    assert list(map(len, batches)) == [100, 100, 5]
    assert enriched[11] == replace(resolved[11], matched_name="Name 11")


def test_renaming_while_excluding_cannot_restore_old_identity(operator):
    app = operator
    next(widget for widget in app.selectbox if widget.label == "Show").set_value("All teams").run()
    next(widget for widget in app.selectbox if widget.label == "Team to review").set_value(0).run()
    next(widget for widget in app.text_input if widget.label == "Submitted team name").set_value("Different Team")
    next(widget for widget in app.checkbox if widget.label.startswith("Exclude this entry")).check()
    click(app, "Apply correction")
    # Reopen the parked state, including the excluded row and its correction.
    # A new harness avoids AppTest's stale widgets after a rerun removes a row.
    reopened = AppTest.from_string(APP, default_timeout=15)
    for key in ("_seeding_result", "_seeding_cohort_decisions", "_seeding_overrides", "_seeding_assessment"):
        reopened.session_state[key] = app.session_state[key]
    app = reopened.run()
    click(app, "Restore entry")
    assert app.session_state["_seeding_cohort_decisions"][0]["team_name_raw"] == "Different Team"
    assert app.session_state["_seeding_result"][1][0].team_id_master is None
    assert 0 not in app.session_state["_seeding_overrides"]


@pytest.mark.parametrize("source", ["refresh", "load"])
@pytest.mark.parametrize("stop_key", ["_seeding_assessment", "_seeding_overrides", "_seeding_result",
                                     "_seeding_result_event_id", "_seeding_resolution_failed", "_seeding_event_probe"])
def test_interrupted_source_transition_reinstalls_one_complete_generation(monkeypatch, source, stop_key):
    class InterruptState(_FakeSessionState):
        def __setitem__(self, key, value):
            if self.__dict__.get("stop_key") == key:
                self.__dict__["stop_key"] = None
                raise _Rerun()
            super().__setitem__(key, value)
        def pop(self, key, default=None):
            if self.__dict__.get("stop_key") == key:
                self.__dict__["stop_key"] = None
                raise _Rerun()
            return super().pop(key, default)

    fake = _install(monkeypatch, _FakeSt())
    fake.session_state = InterruptState()
    roster = _roster(_team(0, provider_team_id="123"), divisions_walked=40)
    parsed, old = intake.to_seeding_rows(roster, {"123": "old-id"})
    fake.session_state.update(_seeding_result=(parsed, old), _seeding_result_event_id=roster.event_id,
                             _seeding_overrides={}, _seeding_assessment={"coverage": "partial"},
                             _seed_name_0="Old form value")
    monkeypatch.setattr(intake, "_write_event_roster_recovery", lambda *_args: None)
    monkeypatch.setattr(intake, "resolve_master_ids", lambda *_args, **_kwargs: ({"123": "new-id"}, ()))
    new = (replace(old[0], team_id_master="new-id"),)
    monkeypatch.setattr(intake, "load_seeding_run_file", lambda _slug: SeedingRun(
        "New Run", parsed.rows, new, assessment={"coverage": "complete", "event_id": roster.event_id}))
    fake.session_state.__dict__["stop_key"] = stop_key
    with pytest.raises(_Rerun):
        if source == "load":
            intake._load_seeding_run("new-run")
        else:
            intake._park_event_roster("https://system.gotsport.com/org_event/events/52975", roster, None, None)
    assert fake.session_state.get("_seeding_transition")
    assert not intake._autosave_seeding_run(), "partial state must never be saved"
    intake._apply_seeding_transition()
    assert fake.session_state["_seeding_result"][1][0].team_id_master == "new-id"
    assert fake.session_state["_seeding_assessment"]["coverage"] == "complete"
    assert "_seed_name_0" not in fake.session_state
    assert "_seeding_transition" not in fake.session_state
    if source == "load":
        assert fake.session_state["_seeding_loaded_slug"] == "new-run"
    else:
        assert fake.session_state["_seeding_event_probe"]["complete"]


def test_saved_run_switch_preserves_corrections_when_save_fails(monkeypatch):
    fake = _install(monkeypatch, _FakeSt())
    parsed = parse_roster("Boys U10\nC\tA")
    pair = (parsed, (ResolvedTeam(0, "unresolved"),))
    fake.session_state.update(_seeding_result=pair, _seeding_loaded_slug="old",
                             _seeding_overrides={0: {"team_id_master": "unsaved"}}, _seeding_save_error=True)
    monkeypatch.setattr(intake, "list_seeding_runs", lambda: [SeedingRunEntry("new", "New", "", 1)])
    monkeypatch.setattr(intake, "_autosave_seeding_run", lambda **_kwargs: False)
    monkeypatch.setattr(intake, "_load_seeding_run", lambda *_args: pytest.fail("unsaved work was replaced"))
    intake._render_seeding_run_controls()
    assert fake.session_state["_seeding_result"] == pair
    assert fake.session_state["_seeding_overrides"][0]["team_id_master"] == "unsaved"
    assert fake.session_state["_seeding_save_error"]
    assert fake.errors


@pytest.mark.parametrize("stop_key", ["seeding_event_name", "seeding_event_url"])
def test_loaded_widget_handoff_survives_interruption(monkeypatch, stop_key):
    class InterruptState(_FakeSessionState):
        def __setitem__(self, key, value):
            if self.__dict__.get("stop_key") == key:
                self.__dict__["stop_key"] = None
                raise _Rerun()
            super().__setitem__(key, value)
    fake = _install(monkeypatch, _FakeSt())
    fake.session_state = InterruptState()
    fake.session_state.update(seeding_event_name="Old", seeding_event_url="old-url",
                             _seeding_pending_name="New", _seeding_pending_event_url="new-url")
    fake.session_state.__dict__["stop_key"] = stop_key
    with pytest.raises(_Rerun):
        intake._apply_pending_seeding_widgets()
    assert not intake._autosave_seeding_run()
    intake._apply_pending_seeding_widgets()
    assert fake.session_state["seeding_event_name"] == "New"
    assert fake.session_state["seeding_event_url"] == "new-url"
    assert "_seeding_pending_name" not in fake.session_state


def test_matching_checkpoints_preserve_previous_source_snapshot(monkeypatch, tmp_path):
    fake = _install(monkeypatch, _FakeSt())
    old = parse_roster("Boys U10\nC\tPrevious source")
    save_run(SeedingRun("Cup", old.rows, (ResolvedTeam(0, "unresolved"),)), base_dir=tmp_path)
    fresh = parse_roster("Boys U10\nC\tRefreshed source")
    outcomes = (ResolvedTeam(0, "unresolved", provider_team_id="123"),)
    fake.session_state.update(_seeding_result=(fresh, outcomes), _seeding_overrides={},
                             seeding_event_name="Cup", _seeding_assessment={"coverage": "complete"})
    monkeypatch.setattr(intake, "save_seeding_run_file", lambda run, **kwargs: save_run(run, base_dir=tmp_path, **kwargs))
    monkeypatch.setattr(intake, "_seeding_provider_id_lookup", lambda _client: lambda _provider: "matched")
    monkeypatch.setattr(intake, "_enrich_seeding_names", lambda resolved, _client: resolved)
    intake._resolve_seeding_incrementally(fresh, outcomes, None)
    assert load_run("cup", base_dir=tmp_path).resolved[0].team_id_master == "matched"
    history = list((tmp_path / "cup/history").glob("*.json"))
    assert any("Previous source" in path.read_text() for path in history)
    assert len(history) == 2


def test_incremental_matching_uses_local_club_candidates_and_preserves_manual_decisions(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from tests.unit.test_roster_resolver import PROVIDERS, READING, _club_team, _FakeClient

    fake = _install(monkeypatch, _FakeSt())
    parsed = parse_roster("Girls U14\nReading Rage Surf\tECNL RL G2012/13\tPA\nNLSA Surf\tECNL RL G2012/13\tNJ")
    outcomes = tuple(ResolvedTeam(row.source_index, "unresolved") for row in parsed.rows)
    manual = {1: {"team_id_master": "7ce98e99-b7fe-45ad-bc35-99d78befda80", "team_name": "NLSA ECNL RL 2013"}}
    fake.session_state.update(_seeding_result=(parsed, outcomes), _seeding_overrides=manual,
                             seeding_event_name="Club lookup regression", _seeding_assessment={"coverage": "complete"})
    client = _FakeClient(teams=[_club_team()], providers=PROVIDERS)
    monkeypatch.setattr(intake, "_seeding_merge_resolver", lambda _: SimpleNamespace(resolve=lambda value: value))
    monkeypatch.setattr(intake, "_seeding_provider_id_lookup", lambda _: lambda _pid: None)
    monkeypatch.setattr(intake, "_enrich_seeding_names", lambda resolved, _client: resolved)
    monkeypatch.setattr(intake, "save_seeding_run_file", lambda run, **kwargs: save_run(run, base_dir=tmp_path, **kwargs))
    searched = []

    def search(query, age, gender, **kwargs):
        searched.append(query)
        return []

    monkeypatch.setattr(intake, "search_gotsport_teams", search)
    intake._resolve_seeding_incrementally(parsed, outcomes, client)
    saved = load_run("club-lookup-regression", base_dir=tmp_path)
    assert saved.resolved[0].team_id_master == READING
    assert saved.overrides == manual
    assert "Reading Rage Surf" in searched
    assert "NLSA Surf" not in searched
    assert not fake.session_state["_seeding_resolution_failed"]


def test_saved_matching_queues_before_a_pending_streamlit_rerun(monkeypatch, tmp_path):
    from src.tournaments.seeding_refresh import read_refresh
    from tests.unit.test_seeding_refresh import Queue
    fake = _install(monkeypatch, _FakeSt())
    parsed = parse_roster("Boys U13\nClub\tTeam A\nClub\tTeam B")
    outcomes = (ResolvedTeam(0, "exact_name", team_id_master="a"), ResolvedTeam(1, "unresolved"))
    fake.session_state.update(_seeding_result=(parsed, outcomes), seeding_event_name="Saved matching",
                             _seeding_overrides={1: {"team_id_master": "b"}},
                             _seeding_assessment={"coverage": "complete"})
    queue = Queue()
    monkeypatch.setattr(intake, "RefreshQueue", lambda _client: queue)
    monkeypatch.setattr(intake, "default_seeding_base_dir", lambda: tmp_path)
    monkeypatch.setattr(intake, "load_seeding_run_file", lambda slug: load_run(slug, base_dir=tmp_path))

    def save_then_rerun(run, **kwargs):
        result = save_run(run, base_dir=tmp_path, **kwargs)
        fake.session_state.arm(_Rerun())
        return result

    monkeypatch.setattr(intake, "save_seeding_run_file", save_then_rerun)
    with pytest.raises(_Rerun):
        intake._autosave_seeding_run(refresh_client=object())
    assert len(queue.inserts) == 2
    assert set(read_refresh(tmp_path / "saved-matching", "Saved matching")["teams"]) == {"a", "b"}
    assert load_run("saved-matching", base_dir=tmp_path).overrides == {1: {"team_id_master": "b"}}


def test_failed_match_save_does_not_queue(monkeypatch):
    fake = _install(monkeypatch, _FakeSt())
    parsed = parse_roster("Boys U13\nClub\tTeam A")
    fake.session_state.update(_seeding_result=(parsed, (ResolvedTeam(0, "exact_name", team_id_master="a"),)),
                             seeding_event_name="Cannot save", _seeding_assessment={"coverage": "complete"})
    def cannot_save(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(intake, "save_seeding_run_file", cannot_save)
    monkeypatch.setattr(intake, "RefreshQueue", lambda *_: pytest.fail("unsaved match queued"))
    assert not intake._autosave_seeding_run(refresh_client=object())


def test_incremental_matches_queue_before_interrupt_and_resume_without_duplicates(monkeypatch, tmp_path):
    from tests.unit.test_seeding_refresh import Queue
    fake = _install(monkeypatch, _FakeSt())
    parsed = parse_roster("Boys U13\nClub\tTeam A\nClub\tTeam B\nClub\tTeam C")
    resolved = (ResolvedTeam(0, "exact_name", team_id_master="a"),
                ResolvedTeam(1, "unresolved"), ResolvedTeam(2, "unresolved"))
    fake.session_state.update(_seeding_result=(parsed, resolved), seeding_event_name="Interrupted matching",
                             _seeding_assessment={"coverage": "complete"}, _seeding_overrides={})
    queue, constructions = Queue(), []
    def construct(_):
        constructions.append(True)
        return queue
    monkeypatch.setattr(intake, "RefreshQueue", construct)
    monkeypatch.setattr(intake, "default_seeding_base_dir", lambda: tmp_path)
    monkeypatch.setattr(intake, "load_seeding_run_file", lambda slug: load_run(slug, base_dir=tmp_path))
    monkeypatch.setattr(intake, "save_seeding_run_file", lambda run, **kw: save_run(run, base_dir=tmp_path, **kw))
    monkeypatch.setattr(intake, "_seeding_provider_id_lookup", lambda _: None)
    monkeypatch.setattr(intake, "_seeding_merge_resolver", lambda _: None)
    monkeypatch.setattr(intake, "make_club_candidate_lookup", lambda *_: None)
    monkeypatch.setattr(intake, "_enrich_seeding_names", lambda items, _: items)
    interrupted = False
    def resolve(_parsed, items, *, indices, **_):
        nonlocal interrupted
        index = indices[0]
        assert any(row["team_id_master"] == "a" for row in queue.requests.values())
        if index == 2 and not interrupted:
            interrupted = True
            raise KeyboardInterrupt()
        return tuple(replace(item, status="exact_name", team_id_master="abc"[index])
                     if item.source_index == index else item for item in items)
    monkeypatch.setattr(intake, "resolve_unlinked", resolve)
    with pytest.raises(KeyboardInterrupt):
        intake._resolve_seeding_incrementally(parsed, resolved, object())
    assert [row["team_id_master"] for row in queue.inserts] == ["a", "b"]
    assert len(constructions) == 1
    saved = load_run("interrupted-matching", base_dir=tmp_path)
    assert saved.resolved[1].team_id_master == "b"
    intake._resolve_seeding_incrementally(parsed, saved.resolved, object())
    assert [row["team_id_master"] for row in queue.inserts] == ["a", "b", "c"]
    assert len(constructions) == 2


@pytest.mark.parametrize("initial_failure", ["unnamed", "write_error"])
def test_retrying_an_ordinary_save_finishes_the_pending_match_refresh(monkeypatch, tmp_path, initial_failure):
    from tests.unit.test_seeding_refresh import Queue
    fake = _install(monkeypatch, _FakeSt())
    parsed = parse_roster("Boys U13\nClub\tTeam A")
    fake.session_state.update(_seeding_result=(parsed, (ResolvedTeam(0, "exact_name", team_id_master="a"),)),
                             seeding_event_name="" if initial_failure == "unnamed" else "Save retry",
                             _seeding_assessment={"coverage": "complete"})
    queue = Queue()
    monkeypatch.setattr(intake, "RefreshQueue", lambda _: queue)
    monkeypatch.setattr(intake, "default_seeding_base_dir", lambda: tmp_path)
    monkeypatch.setattr(intake, "load_seeding_run_file", lambda slug: load_run(slug, base_dir=tmp_path))
    def failed(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(intake, "save_seeding_run_file", failed)
    assert not intake._autosave_seeding_run(refresh_client=object())
    assert not queue.inserts
    fake.session_state.seeding_event_name = "Save retry"
    monkeypatch.setattr(intake, "save_seeding_run_file", lambda run, **kwargs: save_run(run, base_dir=tmp_path, **kwargs))
    assert intake._autosave_seeding_run()
    assert [x["team_id_master"] for x in queue.inserts] == ["a"]
    assert intake._autosave_seeding_run()
    assert len(queue.inserts) == 1
