from dataclasses import replace

import httpx
import pytest
from streamlit.testing.v1 import AppTest

import tournament_intake as intake
from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_run_store import SeedingRun, SeedingRunEntry, load_run, save_run
from tests.unit.test_seeding_event_intake import _FakeSessionState, _FakeSt, _Rerun, _install, _roster, _team

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


@pytest.fixture
def operator(monkeypatch, tmp_path):
    monkeypatch.setattr(intake, "default_seeding_base_dir", lambda: tmp_path)
    monkeypatch.setattr(intake, "list_seeding_runs", lambda: [])
    monkeypatch.setattr(intake, "_autosave_seeding_run", lambda **_kwargs: True)
    monkeypatch.setattr(intake, "_render_seeding_event_scrape", lambda *_args: None)
    monkeypatch.setattr(intake, "fetch_gotsport_provider_id", lambda *_args: pytest.fail("render queried refresh service"))
    app = AppTest.from_string(APP, default_timeout=15).run()
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
