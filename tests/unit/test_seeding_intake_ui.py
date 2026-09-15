"""Exercise the operator's actual Streamlit controls and export invalidation."""

from copy import deepcopy
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from src.tournaments import seeding_intake_ui as ui
from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_predictions import SeedingPredictionBatch

APP = '''
import streamlit as st
from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_intake_ui import render_seeding_pack
parsed = parse_roster("Male U14\\nClub\\tTeam\\tState\\nAlpha\\tAlpha FC\\tTX\\nBeta\\tBeta FC\\tTX\\n"
                      "Female U15\\nClub\\tTeam\\tState\\nNew\\tNew Girls\\tTX")
resolved = (ResolvedTeam(source_index=0, status="gotsport_id", team_id_master="00000000-0000-0000-0000-000000000001"),
            ResolvedTeam(source_index=1, status="gotsport_id", team_id_master="00000000-0000-0000-0000-000000000002"),
            ResolvedTeam(source_index=2, status="unresolved"))
st.session_state.setdefault("_seeding_overrides", {})
def save():
    st.session_state["saved_count"] = st.session_state.get("saved_count", 0) + 1
    return st.session_state.get("test_save_succeeds", True)
render_seeding_pack(parsed, resolved, None, event_name="Acceptance Cup", save=save)
'''


@pytest.fixture
def operator(monkeypatch):
    calls = []

    def load(cohorts, **_kwargs):
        calls.append(cohorts)
        prediction = ComparePrediction("team_a", .65, .20, .15, {"teamA": 2, "teamB": 1},
                                       1.0, 1.5, .10, "medium", .60)
        reverse = replace(prediction, predicted_winner="team_b", win_probability_a=.20,
                          win_probability_b=.65, expected_score={"teamA": 1, "teamB": 2}, expected_margin=-1)
        teams = {key: {entrant: {
            "team_id_master": team_id, "team_name": "Alpha FC" if entrant == "0" else "Beta FC",
            "power_score_final": .55, "rank_in_cohort_final": 40, "gender": "M", "age": 14,
            "status": "Active", "games_played": 10, "prediction_game_count": 10,
        } for entrant, team_id in members.items()} for key, members in cohorts.items()}
        pairs = {key: ({("0", "1"): prediction, ("1", "0"): reverse} if len(members) == 2 else {})
                 for key, members in cohorts.items()}
        return SeedingPredictionBatch(pairs, teams, {key: {} for key in cohorts},
                                      "2026-09-15T10:00:00+00:00", "2026-09-14", "a" * 64)

    monkeypatch.setattr(ui, "load_seeding_predictions", load)
    monkeypatch.setattr(ui, "make_ratings_lookup", lambda _client: lambda _ids: {})
    monkeypatch.setattr(ui, "render_seeding_pdf", lambda _html: b"%PDF-1.7\nreviewed fixture\n%%EOF")
    return AppTest.from_string(APP, default_timeout=15).run(), calls


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception


def test_build_contains_all_cohorts_and_identity_edit_hides_old_export(operator):
    app, calls = operator
    assert not app.exception
    click(app, "Build matchup tiers")
    assert not app.error, [error.value for error in app.error]
    assert set(calls[0]) == {"u14|Male", "u15|Female"}
    document = app.session_state["_seeding_sheet_html"]
    assert "Alpha FC" in document and "Beta FC" in document and "New Girls" in document
    assert "Team identity needs review" in document
    click(app, "Generate PDF pack")
    assert app.session_state["_seeding_pdf"].startswith(b"%PDF-")
    app.session_state["_seeding_overrides"] = {0: {"team_id_master": "00000000-0000-0000-0000-000000000009"}}
    app.run()
    assert not app.exception
    assert app.session_state["_seeding_sheet_html"] is None
    assert "_seeding_pdf" not in app.session_state
    assert all(button.label != "Generate PDF pack" for button in app.button)


def test_policy_and_operator_notes_save_and_invalidate_pdf(operator):
    app, _calls = operator
    click(app, "Build matchup tiers")
    click(app, "Generate PDF pack")
    next(widget for widget in app.number_input if "goal margin" in widget.label).set_value(0.5)
    click(app, "Apply grouping preferences")
    assert app.session_state["_seeding_pack"]["policy"]["max_expected_margin"] == .5
    assert app.session_state["saved_count"] == 2
    assert "_seeding_pdf" not in app.session_state
    app.text_area[0].set_value("Keep Alpha and Beta in separate flights.")
    click(app, "Save tier decisions")
    assert "Keep Alpha and Beta in separate flights." in app.session_state["_seeding_sheet_html"]
    assert app.session_state["saved_count"] == 3
    app.text_area[1].set_value("Director should confirm the Girls placement.")
    click(app, "Save placement notes")
    assert "Director should confirm the Girls placement." in app.session_state["_seeding_sheet_html"]


def test_selecting_cohorts_requires_new_pack_and_failed_refresh_preserves_snapshot(operator, monkeypatch):
    app, calls = operator
    click(app, "Build matchup tiers")
    click(app, "Generate PDF pack")
    app.radio[0].set_value("Choose cohorts").run()
    app.multiselect[0].set_value(["u14|Male"]).run()
    assert "_seeding_pdf" not in app.session_state
    click(app, "Build matchup tiers")
    assert set(calls[-1]) == {"u14|Male"}
    assert "New Girls" not in app.session_state["_seeding_sheet_html"]
    previous = app.session_state["_seeding_pack"]
    monkeypatch.setattr(ui, "load_seeding_predictions", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("Database temporarily unavailable")))
    click(app, "Build matchup tiers")
    assert app.session_state["_seeding_pack"] == previous
    assert "Database temporarily unavailable" in app.error[0].value


def test_restored_snapshot_renders_without_loading_new_predictions(operator, monkeypatch):
    app, calls = operator
    click(app, "Build matchup tiers")
    snapshot = app.session_state["_seeding_pack"]
    monkeypatch.setattr(ui, "load_seeding_predictions", lambda *_args, **_kwargs: pytest.fail("unexpected reload"))
    reopened = AppTest.from_string(APP, default_timeout=15)
    reopened.session_state["_seeding_pack"] = snapshot
    reopened.run()
    assert not reopened.exception
    assert "Alpha FC" in reopened.session_state["_seeding_sheet_html"]
    assert len(calls) == 1


@pytest.mark.parametrize("malformed", ["broken JSON value", ["wrong shape"], 42])
def test_malformed_saved_pack_type_can_be_rebuilt_without_losing_the_build_control(operator, malformed):
    app, calls = operator
    app.session_state["_seeding_pack"] = malformed
    app.session_state["_seeding_pdf"] = b"outdated PDF"
    app.run()
    assert not app.exception
    assert any("saved pack is unreadable" in warning.value for warning in app.warning)
    assert "_seeding_pdf" not in app.session_state
    click(app, "Build matchup tiers")
    assert not app.error
    assert len(calls) == 1
    assert "Alpha FC" in app.session_state["_seeding_sheet_html"]


@pytest.mark.parametrize("missing_field", ["policy", "generated_at"])
def test_saved_pack_missing_required_field_explains_rebuild_and_keeps_build_control(operator, missing_field):
    app, calls = operator
    click(app, "Build matchup tiers")
    malformed = deepcopy(app.session_state["_seeding_pack"])
    del malformed[missing_field]
    app.session_state["_seeding_pack"] = malformed
    app.run()
    assert not app.exception
    assert any("pack needs rebuilding" in error.value for error in app.error)
    assert app.session_state["_seeding_sheet_html"] is None
    click(app, "Build matchup tiers")
    assert not app.error
    assert len(calls) == 2
    assert "Alpha FC" in app.session_state["_seeding_sheet_html"]


def test_failed_save_banner_survives_rerun_and_successful_retry_clears_it(operator):
    app, calls = operator
    click(app, "Build matchup tiers")
    click(app, "Generate PDF pack")
    app.session_state["test_save_succeeds"] = False
    app.text_area[0].set_value("Latest reviewed notes must survive retry.")
    click(app, "Save tier decisions")
    assert app.session_state["_seeding_pack_unsaved"] is True
    assert any("only in memory: saving failed" in warning.value for warning in app.warning)
    assert "_seeding_pdf" not in app.session_state
    app.run()
    assert not app.exception
    assert any("only in memory: saving failed" in warning.value for warning in app.warning)
    app.session_state["test_save_succeeds"] = True
    click(app, "Retry saving pack")
    assert app.session_state["_seeding_pack_unsaved"] is False
    assert not any("only in memory: saving failed" in warning.value for warning in app.warning)
    assert all(button.label != "Retry saving pack" for button in app.button)
    assert app.session_state["saved_count"] == 3
    assert len(calls) == 1
    assert "Latest reviewed notes must survive retry." in app.session_state["_seeding_sheet_html"]


def _merge_editor_tiers(app):
    # AppTest exposes data_editor as a dataframe, without an edit-cell helper.
    # Supply the same row-delta widget state that Streamlit's editor sends.
    keys = [key for key in app.session_state.filtered_state if key.startswith("_seeding_tier_editor_u14|Male_")]
    assert len(keys) == 1
    app.session_state[keys[0]] = {"edited_rows": {1: {"Tier": 1}}, "added_rows": [], "deleted_rows": []}


def test_manual_unsafe_merge_warning_and_notes_reach_the_sheet_and_restore_clears_editor(operator):
    app, _calls = operator
    click(app, "Build matchup tiers")
    next(widget for widget in app.number_input if "goal margin" in widget.label).set_value(0.5)
    click(app, "Apply grouping preferences")
    assert app.dataframe[0].value["Tier"].tolist() == [1, 2]

    _merge_editor_tiers(app)
    app.text_area[0].set_value("Director requested one flight; review Alpha versus Beta.")
    click(app, "Save tier decisions")
    assert app.session_state["_seeding_pack"]["manual_groups"]["u14|Male"] == [["0", "1"]]
    assert app.dataframe[0].value["Tier"].tolist() == [1, 1]
    assert any("exceeds the matchup limits" in warning.value for warning in app.warning)
    assert "exceeds the matchup limits" in app.session_state["_seeding_sheet_html"]
    assert "Director requested one flight; review Alpha versus Beta." in app.session_state["_seeding_sheet_html"]

    click(app, "Generate PDF pack")
    click(app, "Restore suggested tiers")
    assert "u14|Male" not in app.session_state["_seeding_pack"]["manual_groups"]
    assert app.dataframe[0].value["Tier"].tolist() == [1, 2]
    assert "_seeding_pdf" not in app.session_state
    assert not any("exceeds the matchup limits" in warning.value for warning in app.warning)
    assert "exceeds the matchup limits" not in app.session_state["_seeding_sheet_html"]
    assert "Director requested one flight; review Alpha versus Beta." in app.session_state["_seeding_sheet_html"]
    # Saving without touching the restored editor must not reapply its old merge.
    click(app, "Save tier decisions")
    assert app.session_state["_seeding_pack"]["manual_groups"]["u14|Male"] == [["0"], ["1"]]
