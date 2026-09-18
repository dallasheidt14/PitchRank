from dataclasses import replace

import httpx
import pytest
from streamlit.testing.v1 import AppTest

import tournament_intake as intake
from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from tests.unit.test_seeding_event_intake import _FakeSt, _install

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
def operator(monkeypatch):
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
        "Total U10+ teams": "2–3", "Matched": "1", "Manual matches needed": "2",
        "Cohort / input fixes needed": "1", "Suggested event price": "$199",
    }
    assert sum(widget.label == "GotSport link, GotSport id, or team_id_master" for widget in app.text_input) == 1
    assert any(button.label == "Save this run" for button in app.button)
    assert any(button.label == "Download all selected teams as CSV" for button in app.get("download_button"))
    assert not app.error


def test_cohort_correction_changes_quote_and_can_exclude_younger(operator):
    app = operator
    next(widget for widget in app.selectbox if widget.label == "Show").set_value("Cohort / input questions").run()
    next(widget for widget in app.selectbox if widget.label == "Tournament age group").set_value("u9")
    click(app, "Apply correction")
    assert next(metric.value for metric in app.metric if metric.label == "Total U10+ teams") == "2"
    assert next(metric.value for metric in app.metric if metric.label == "Cohort / input fixes needed") == "0"
    assert any("Quote ready" in message.value for message in app.success)
    assert len(app.session_state["_seeding_result"][0].rows) == 3


def test_manual_lookup_transport_error_does_not_hide_quote_or_export(operator, monkeypatch):
    monkeypatch.setattr(intake, "_seeding_provider_id_lookup", lambda *_args: (_ for _ in ()).throw(httpx.ConnectError("refused")))
    app = operator
    next(widget for widget in app.text_input if widget.label.startswith("GotSport link")).set_value("12345").run()
    assert not app.exception
    assert any("temporarily unavailable" in error.value for error in app.error)
    assert any(metric.label == "Suggested event price" for metric in app.metric)
    assert any(button.label == "Build matchup tiers" for button in app.button)


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
    resolved = tuple(ResolvedTeam(index, "gotsport_id", team_id_master=str(index)) for index in range(205))
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
