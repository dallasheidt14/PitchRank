"""Exercise the operator's actual Streamlit controls and export invalidation."""

from copy import deepcopy
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from src.tournaments import seeding_intake_ui as ui
from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.roster_paste import parse_roster
from src.tournaments.seeding_predictions import SeedingPredictionBatch
from src.tournaments.seeding_run_store import PackRecovery

APP = '''
import streamlit as st
from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_intake_ui import render_seeding_pack
parsed = parse_roster("Male U14\\nClub\\tTeam\\tState\\nAlpha\\tAlpha FC\\tTX\\nBeta\\tBeta Entry*\\tTX\\n"
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
        team_names = {"0": "Alpha FC", "1": "Beta FC", "2": "New Girls"}
        team_ages = {"0": 14, "1": 13, "2": 15}
        teams = {key: {entrant: {
            "team_id_master": team_id, "team_name": team_names[entrant],
            "power_score_final": .55, "rank_in_cohort_final": 40, "gender": "M",
            "age": team_ages[entrant],
            "status": "Active", "games_played": 10, "prediction_game_count": 10,
        } for entrant, team_id in members.items()} for key, members in cohorts.items()}
        pairs = {key: ({("0", "1"): prediction, ("1", "0"): reverse} if len(members) == 2 else {})
                 for key, members in cohorts.items()}
        return SeedingPredictionBatch(pairs, teams, {key: {} for key in cohorts},
                                      "2026-09-15T10:00:00+00:00", "2026-09-14", ui.seeding_predictor_sha256())

    monkeypatch.setattr(ui, "load_seeding_predictions", load)
    monkeypatch.setattr(ui, "seeding_predictor_sha256", lambda: "a" * 64)
    monkeypatch.setattr(ui, "make_ratings_lookup", lambda _client: lambda _ids: {})
    monkeypatch.setattr(ui, "render_seeding_pdf", lambda _html: b"%PDF-1.7\nreviewed fixture\n%%EOF")
    return AppTest.from_string(APP, default_timeout=15).run(), calls


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception


def test_seed_order_and_export_are_presented_as_steps_three_and_four(operator):
    app, _calls = operator

    headings = [item.value for item in app.markdown]
    assert "### 3. Build and review the seed order" in headings
    assert "### 4. Export the director pack" not in headings
    assert any("Build the seed order in step 3" in item.value for item in app.info)

    click(app, "Build seeding sheets")

    headings = [item.value for item in app.markdown]
    assert headings.index("### 3. Build and review the seed order") < headings.index(
        "### 4. Export the director pack"
    )
    assert any(button.label == "Generate PDF pack" for button in app.button)


def test_predictor_update_requires_rebuild_and_keeps_saved_team_choices(operator, monkeypatch):
    app, calls = operator
    app.session_state["_seeding_overrides"] = {
        0: {"team_id_master": "00000000-0000-0000-0000-000000000001", "team_name": "Manual match"}
    }
    click(app, "Build seeding sheets")
    click(app, "Generate PDF pack")
    pack = deepcopy(app.session_state["_seeding_pack"])
    overrides = deepcopy(app.session_state["_seeding_overrides"])
    monkeypatch.setattr(ui, "seeding_predictor_sha256", lambda: "b" * 64)
    app.run()
    assert not app.exception
    assert any("predictor has been updated" in item.value for item in app.info)
    assert "_seeding_pdf" not in app.session_state
    assert app.session_state["_seeding_sheet_html"] is None
    assert all(button.label != "Generate PDF pack" for button in app.button)
    assert app.session_state["_seeding_pack"] == pack
    assert app.session_state["_seeding_overrides"] == overrides
    assert len(calls) == 1
    click(app, "Build seeding sheets")
    assert len(calls) == 2
    assert app.session_state["_seeding_pack"]["predictor_sha256"] == "b" * 64
    assert app.session_state["_seeding_overrides"] == overrides
    assert not any("predictor has been updated" in item.value for item in app.info)
    assert any(button.label == "Generate PDF pack" for button in app.button)


def test_build_contains_all_cohorts_and_identity_edit_hides_old_export(operator):
    app, calls = operator
    assert not app.exception
    click(app, "Build seeding sheets")
    assert not app.error, [error.value for error in app.error]
    assert set(calls[0]) == {"u14|Male", "u15|Female"}
    document = app.session_state["_seeding_sheet_html"]
    assert "Alpha FC" in document and "Beta FC" in document and "New Girls" in document
    assert "Data review required" in document
    click(app, "Generate PDF pack")
    assert app.session_state["_seeding_pdf"].startswith(b"%PDF-")
    app.session_state["_seeding_overrides"] = {0: {"team_id_master": "00000000-0000-0000-0000-000000000009"}}
    app.run()
    assert not app.exception
    assert app.session_state["_seeding_sheet_html"] is None
    assert "_seeding_pdf" not in app.session_state
    assert all(button.label != "Generate PDF pack" for button in app.button)


def test_review_and_sheet_keep_registered_name_primary_with_match_and_play_up_context(operator):
    app, _calls = operator
    click(app, "Build seeding sheets")

    editor = app.dataframe[0].value
    beta = editor.loc[editor["Team"] == "Beta Entry"].iloc[0]
    assert beta["PitchRank match"] == "Beta FC"
    assert beta["Roster context"] == "Plays up from U13"

    document = app.session_state["_seeding_sheet_html"]
    row = document.split('data-entrant="1"', 1)[1].split("</tr>", 1)[0]
    assert row.index("Beta Entry") < row.index("PitchRank: Beta FC")
    assert "Plays up from U13" in row


@pytest.mark.parametrize("ranked_age", [14, 15])
def test_review_uses_generic_play_up_for_same_age_or_older_match_and_keeps_c_suffix(ranked_age):
    row = parse_roster("Male U14\nClub\tFire 13B*-c\tTX").rows[0]

    columns = ui._identity_columns(
        "0",
        {"0": {"team_name": "Fire 13B", "age": ranked_age}},
        {"0": row},
    )

    assert columns["Team"] == "Fire 13B-c"
    assert columns["Roster context"] == "Plays up"


def test_analysis_details_are_read_only_and_director_notes_save(operator):
    app, _calls = operator
    click(app, "Build seeding sheets")
    click(app, "Generate PDF pack")
    app.text_area[0].set_value("Keep Alpha and Beta in separate flights.")
    click(app, "Save director notes")
    assert "Keep Alpha and Beta in separate flights." in app.session_state["_seeding_sheet_html"]
    assert not any("goal margin" in widget.label for widget in app.number_input)


def test_main_review_shows_scores_without_internal_ids_or_close_labels(operator):
    app, _calls = operator
    click(app, "Build seeding sheets")
    editor = app.dataframe[0].value
    assert list(editor.columns)[:4] == ["Suggested seed", "Team", "PowerScore", "State rank"]
    assert editor["PowerScore"].tolist() == pytest.approx([55., 55.])
    assert "Entrant" not in editor.columns
    assert editor["Compare evidence"].tolist() == ["", ""]
    assert "Close range" not in app.session_state["_seeding_sheet_html"]
    assert "PDF and Excel" in app.text_area[0].label


def test_placement_review_stays_internal_and_resets_when_director_notes_change(operator, monkeypatch):
    app, calls = operator
    exported = []
    original_csv = ui.team_csv

    def capture_csv(*args, **kwargs):
        data = original_csv(*args, **kwargs)
        exported.append(data.decode("utf-8-sig"))
        return data

    monkeypatch.setattr(ui, "team_csv", capture_csv)
    click(app, "Build seeding sheets")
    pack = app.session_state["_seeding_pack"]
    pack["teams"]["u14|Male"]["0"]["status"] = "Not Enough Ranked Games"
    app.session_state["_seeding_assessment"] = {"coverage": "complete", "completed": True}
    # The separate unmatched cohort has a completed not-found decision.
    app.session_state["_seeding_overrides"] = {2: {"not_found": True}}
    app.run()
    assert not app.exception
    assert "DRAFT" in app.session_state["_seeding_sheet_html"]
    assert "Limited history" in app.session_state["_seeding_sheet_html"]
    assert "Placement checks" not in app.session_state["_seeding_sheet_html"]
    assert "Draft — review needed" in exported[-1]
    assert "roster review needed" not in exported[-1]
    click(app, "Mark placement review complete")
    assert "DRAFT" not in app.session_state["_seeding_sheet_html"]
    assert "Draft" not in exported[-1]
    reviewed = deepcopy(app.session_state["_seeding_pack"])
    click(app, "Generate PDF pack")
    app.text_area[0].set_value("Reviewed with the club.")
    click(app, "Save director notes")
    assert "_seeding_pdf" not in app.session_state
    assert "DRAFT" in app.session_state["_seeding_sheet_html"]
    assert "Draft — review needed" in exported[-1]
    assert any(button.label == "Mark placement review complete" for button in app.button)
    assert app.session_state["_seeding_pack"]["placement_reviews"] == reviewed["placement_reviews"]
    assert len(calls) == 1


def test_legacy_analysis_reuses_predictions_and_preserves_notes(operator):
    app, calls = operator
    click(app, "Build seeding sheets")
    click(app, "Generate PDF pack")
    pack = deepcopy(app.session_state["_seeding_pack"])
    pack["analysis_schema_version"] = 1
    pack["operator_notes"] = {"u14|Male": "Keep this note."}
    pack["policy"]["max_expected_margin"] = 1.5
    app.session_state["_seeding_pack"] = pack
    app.run()
    assert not app.exception and not app.error
    upgraded = app.session_state["_seeding_pack"]
    assert upgraded["analysis_schema_version"] == 3
    assert upgraded["predictions"] == pack["predictions"]
    assert upgraded["generated_at"] == pack["generated_at"]
    assert upgraded["operator_notes"] == pack["operator_notes"]
    assert upgraded["policy"] == pack["policy"]
    assert len(calls) == 1
    assert "_seeding_pdf" not in app.session_state
    assert "Keep this note." in app.session_state["_seeding_sheet_html"]


@pytest.mark.parametrize("action", ["upgrade", "rebuild"])
def test_export_validation_failure_preserves_previous_saved_pack(operator, monkeypatch, action):
    app, _calls = operator
    click(app, "Build seeding sheets")
    click(app, "Generate PDF pack")
    saved = deepcopy(app.session_state["_seeding_pack"])
    if action == "upgrade":
        saved["analysis_schema_version"] = 1
        app.session_state["_seeding_pack"] = saved
    monkeypatch.setattr(ui, "validate_seeding_workbook", lambda *_args: (_ for _ in ()).throw(
        ValueError("Workbook validation failed")))
    if action == "rebuild":
        click(app, "Build seeding sheets")
    else:
        app.run()
    assert not app.exception
    assert app.session_state["_seeding_pack"] == saved
    assert "previous saved pack is preserved" in app.error[0].value
    assert "_seeding_pdf" not in app.session_state and "_seeding_xlsx" not in app.session_state
    assert app.session_state["_seeding_sheet_html"] is None


def test_note_changes_invalidate_both_downloads_under_one_content_identity(operator):
    app, _calls = operator
    click(app, "Build seeding sheets")
    click(app, "Generate PDF pack")
    before = app.session_state["_seeding_export_fingerprint"]
    app.text_area[0].set_value("Edited after PDF generation")
    click(app, "Save director notes")
    assert "_seeding_pdf" not in app.session_state
    assert app.session_state["_seeding_export_fingerprint"] != before
    assert app.session_state["_seeding_xlsx_hash"] == app.session_state["_seeding_export_fingerprint"]
    from io import BytesIO
    from openpyxl import load_workbook
    workbook = load_workbook(BytesIO(app.session_state["_seeding_xlsx"]))
    assert any(cell.value == "Edited after PDF generation" for row in workbook["U14 Boys"] for cell in row)


def test_selecting_cohorts_requires_new_pack_and_failed_refresh_preserves_snapshot(operator, monkeypatch):
    app, calls = operator
    click(app, "Build seeding sheets")
    click(app, "Generate PDF pack")
    app.radio[0].set_value("Choose cohorts").run()
    app.multiselect[0].set_value(["u14|Male"]).run()
    assert "_seeding_pdf" not in app.session_state
    click(app, "Build seeding sheets")
    assert set(calls[-1]) == {"u14|Male"}
    assert "New Girls" not in app.session_state["_seeding_sheet_html"]
    previous = app.session_state["_seeding_pack"]
    monkeypatch.setattr(ui, "load_seeding_predictions", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("Database temporarily unavailable")))
    click(app, "Build seeding sheets")
    assert app.session_state["_seeding_pack"] == previous
    assert "Database temporarily unavailable" in app.error[0].value


def test_narrowing_cohorts_keeps_every_cohorts_notes_and_policy(operator):
    app, calls = operator
    click(app, "Build seeding sheets")
    app.text_area[0].set_value("Boys placement notes")
    next(button for button in app.button if button.label == "Save director notes").click().run()
    app.text_area[1].set_value("Girls placement notes")
    [button for button in app.button if button.label == "Save director notes"][1].click().run()
    app.session_state["_seeding_pack"]["placement_reviews"] = {"u15|Female": "f" * 64}
    original = deepcopy(app.session_state["_seeding_pack"])
    assert original["operator_notes"] == {"u14|Male": "Boys placement notes", "u15|Female": "Girls placement notes"}
    app.radio[0].set_value("Choose cohorts").run()
    app.multiselect[0].set_value(["u14|Male"]).run()
    click(app, "Build seeding sheets")
    assert not app.error
    rebuilt = app.session_state["_seeding_pack"]
    assert rebuilt["operator_notes"] == {"u14|Male": "Boys placement notes", "u15|Female": "Girls placement notes"}
    assert rebuilt["placement_reviews"] == {"u15|Female": "f" * 64}
    from io import BytesIO
    from openpyxl import load_workbook
    workbook = load_workbook(BytesIO(app.session_state["_seeding_xlsx"]))
    values = [cell.value for row in workbook.active for cell in row]
    assert "Boys placement notes" in values
    assert "Girls placement notes" not in values
    assert rebuilt["policy"] == original["policy"]
    assert len(calls) == 2
    assert "Boys placement notes" in app.session_state["_seeding_sheet_html"]
    assert "Girls placement notes" not in app.session_state["_seeding_sheet_html"]
    app.multiselect[0].set_value(["u14|Male", "u15|Female"]).run()
    click(app, "Build seeding sheets")
    assert "Girls placement notes" in app.session_state["_seeding_sheet_html"]


def test_unknown_gender_and_girls_cohort_build_together(operator):
    from io import BytesIO
    from openpyxl import load_workbook

    app_code = APP.replace("resolved =", '''from dataclasses import replace
from src.tournaments.roster_paste import ParsedRoster
parsed = ParsedRoster((*parsed.rows, replace(parsed.rows[-1], source_index=3,
    section_gender="", team_name_raw="Unassigned team")), ())
resolved =''')
    app = AppTest.from_string(app_code, default_timeout=15).run()
    click(app, "Build seeding sheets")
    assert not app.error
    workbook = load_workbook(BytesIO(app.session_state["_seeding_xlsx"]))
    assert set(workbook.sheetnames) == {"U14 Boys", "U15 Girls", "U15 Unspecified gender"}
    assert any(button.label == "Generate PDF pack" for button in app.button)
    assert any("identity or cohort review" in item.value for item in app.warning)


def test_analysis_diagnostics_remain_collapsed_and_never_yellow(operator):
    app, _calls = operator
    click(app, "Build seeding sheets")
    details = next(item for item in app.expander if item.label == "Analysis details")
    assert not details.proto.expanded
    assert any("Score steps require" in item.value for item in details.caption)
    assert all(not any(text in item.value for text in (
        "has one team", "strength-order exception", "low outcome confidence",
    )) for item in app.warning)
    assert "Analysis details" not in app.session_state["_seeding_sheet_html"]
    assert "Score steps require" not in app.session_state["_seeding_sheet_html"]


def test_restored_snapshot_renders_without_loading_new_predictions(operator, monkeypatch):
    app, calls = operator
    click(app, "Build seeding sheets")
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
    click(app, "Build seeding sheets")
    assert not app.error
    assert len(calls) == 1
    assert "Alpha FC" in app.session_state["_seeding_sheet_html"]


@pytest.mark.parametrize("missing_field", ["policy", "generated_at"])
def test_saved_pack_missing_required_field_explains_rebuild_and_keeps_build_control(operator, missing_field):
    app, calls = operator
    click(app, "Build seeding sheets")
    malformed = deepcopy(app.session_state["_seeding_pack"])
    del malformed[missing_field]
    app.session_state["_seeding_pack"] = malformed
    app.run()
    assert not app.exception
    assert any("pack needs rebuilding" in error.value for error in app.error)
    assert app.session_state["_seeding_sheet_html"] is None
    click(app, "Build seeding sheets")
    assert not app.error
    assert len(calls) == 2
    assert "Alpha FC" in app.session_state["_seeding_sheet_html"]


def test_failed_save_banner_survives_rerun_and_successful_retry_clears_it(operator):
    app, calls = operator
    click(app, "Build seeding sheets")
    click(app, "Generate PDF pack")
    app.session_state["test_save_succeeds"] = False
    app.text_area[0].set_value("Latest reviewed notes must survive retry.")
    click(app, "Save director notes")
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
    click(app, "Build seeding sheets")
    app.text_area[0].set_value("Director requested one flight; review Alpha versus Beta.")
    click(app, "Save director notes")
    assert not any("exceeds the matchup limits" in warning.value for warning in app.warning)
    assert "Tier 1" not in app.session_state["_seeding_sheet_html"]
    assert "Director requested one flight; review Alpha versus Beta." in app.session_state["_seeding_sheet_html"]
    assert "_seeding_pdf" not in app.session_state


@pytest.mark.parametrize("analysis_version", [1, 2, 3])
def test_save_keeps_package_when_source_also_contains_younger_teams(operator, monkeypatch, analysis_version):
    import tournament_intake as intake
    from src.tournaments.roster_paste import ParsedRoster
    from src.tournaments.roster_resolver import ResolvedTeam
    from tests.unit.test_seeding_event_intake import _FakeSt, _install

    app, _calls = operator
    click(app, "Build seeding sheets")
    pack = app.session_state["_seeding_pack"]
    pack["analysis_schema_version"] = analysis_version
    raw = parse_roster("Male U14\nClub\tTeam\tState\nAlpha\tAlpha FC\tTX\nBeta\tBeta Entry*\tTX\n"
                       "Female U15\nClub\tTeam\tState\nNew\tNew Girls\tTX")
    younger = replace(raw.rows[0], source_index=3, section_age_group="u9", team_name_raw="Young")
    raw = ParsedRoster((*raw.rows, younger), ())
    resolved = (ResolvedTeam(0, "gotsport_id", team_id_master="00000000-0000-0000-0000-000000000001"),
                ResolvedTeam(1, "gotsport_id", team_id_master="00000000-0000-0000-0000-000000000002"),
                ResolvedTeam(2, "unresolved"), ResolvedTeam(3, "unresolved"))
    fake = _install(monkeypatch, _FakeSt())
    fake.session_state.update(_seeding_result=(raw, resolved), _seeding_pack=pack, _seeding_overrides={},
                             seeding_event_name="Cup")
    saved = []
    monkeypatch.setattr(intake, "save_seeding_run_file", lambda run, **_kwargs: saved.append(run))
    assert intake._autosave_seeding_run()
    assert saved[0].pack == pack
    assert len(saved[0].rows) == 4
    # Display-name enrichment leaves identity/cohort inputs unchanged.
    enriched = tuple(replace(item, matched_name="Display name") for item in resolved)
    intake._park_seeding_result((raw, enriched), event_id=None)
    assert fake.session_state["_seeding_pack"] == pack

    # A changed identity still discards the incompatible snapshot.
    changed = (replace(enriched[0], team_id_master="changed"), *enriched[1:])
    intake._park_seeding_result((raw, changed), event_id=None)
    assert "_seeding_pack" not in fake.session_state


@pytest.mark.parametrize("analysis_version", [1, 2, 3])
def test_unsupported_saved_note_remains_editable_after_export_failure(operator, analysis_version):
    app, calls = operator
    click(app, "Build seeding sheets")
    pack = app.session_state["_seeding_pack"]
    pack["analysis_schema_version"] = analysis_version
    pack["operator_notes"] = {"u14|Male": "Pasted\x0bnote"}
    app.session_state["_seeding_pack"] = pack
    app.run()
    assert not app.exception
    assert any("Could not prepare" in message.value for message in app.error)
    assert app.session_state["_seeding_pack"]["analysis_schema_version"] == analysis_version
    assert "_seeding_xlsx" not in app.session_state
    app.text_area[0].set_value("Corrected note")
    click(app, "Save director notes")
    assert not app.error
    assert app.session_state["_seeding_pack"]["operator_notes"]["u14|Male"] == "Corrected note"
    assert app.session_state["_seeding_pack"]["analysis_schema_version"] == 3
    assert "Corrected note" in app.session_state["_seeding_sheet_html"]
    assert "_seeding_xlsx" in app.session_state and len(calls) == 1


def test_unsupported_new_note_is_rejected_before_persistence(operator):
    app, _ = operator
    click(app, "Build seeding sheets")
    before = deepcopy(app.session_state["_seeding_pack"])
    app.text_area[0].set_value("Invalid\x0bnote")
    click(app, "Save director notes")
    assert any("unsupported control character" in message.value for message in app.error)
    assert app.session_state["_seeding_pack"] == before


def test_legacy_pack_fingerprint_remains_valid_with_empty_new_provenance_fields():
    import hashlib
    import json
    from dataclasses import asdict
    from src.tournaments.roster_resolver import ResolvedTeam
    from src.tournaments.seeding_pack import roster_fingerprint

    rows = parse_roster("Boys U10\nC\tA").rows
    resolved = [ResolvedTeam(0, "gotsport_id", team_id_master="a")]
    old_rows = [{key: value for key, value in asdict(row).items()
                 if key not in {"registration_id", "provider_team_id", "intake_issue"}} for row in rows]
    legacy = hashlib.sha256(json.dumps({"rows": old_rows, "team_ids": {"0": "a"}},
                                      sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert roster_fingerprint(rows, resolved, {}) == legacy


@pytest.mark.parametrize("roster,statuses", [
    ("Girls U9/U10 Mexico\nC\tMixed", [("gotsport_id", "a")]),
    ("Boys U10\nC\tUnmatched", [("unresolved", None)]),
    ("Boys U10\nC\tA\nC\tB", [("gotsport_id", "same"), ("gotsport_id", "same")]),
])
def test_selected_unfinished_cohort_exports_remain_draft(roster, statuses):
    app_code = f'''
import streamlit as st
from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_intake_ui import render_seeding_pack
parsed = parse_roster({roster!r})
resolved = tuple(ResolvedTeam(index, status, team_id_master=identity)
                 for index, (status, identity) in enumerate({statuses!r}))
st.session_state["_seeding_overrides"] = {{}}
st.session_state["_seeding_assessment"] = {{"coverage": "complete", "completed": list(range(len(parsed.rows)))}}
render_seeding_pack(parsed, resolved, None, event_name="Draft Cup", save=lambda: True)
'''
    app = AppTest.from_string(app_code).run()
    assert not app.exception
    assert any("Delivery status: draft" in message.value for message in app.info)
    assert not any("roster assessed" in message.value for message in app.caption)


def test_live_legacy_session_without_assessment_exports_draft(operator):
    app, _calls = operator
    assert any("Delivery status: draft" in message.value for message in app.info)
    click(app, "Build seeding sheets")
    assert "DRAFT" in app.session_state["_seeding_sheet_html"]


@pytest.mark.parametrize("reason,code", [
    ("Two roster entries appear to be the same team. Confirm both team matches before seeding.", "duplicate_entry"),
    ("Two roster entries appear to be the same team. Confirm both team matches before seeding.", None),
    ("The matched team's gender differs from the tournament cohort. Confirm the team match.", "metadata_conflict"),
    ("The matched team's current age is older than the tournament cohort. Confirm the team match.", None),
])
def test_compare_discovered_conflicts_mark_all_exports_as_draft(operator, monkeypatch, reason, code):
    app, _calls = operator
    app.session_state["_seeding_assessment"] = {"coverage": "complete", "completed": [0, 1, 2]}
    next(widget for widget in app.radio if widget.label == "Sheet pack").set_value("Choose cohorts").run()
    app.multiselect[0].set_value(["u14|Male"]).run()
    assert any("roster assessed" in message.value for message in app.caption)
    codes = {"u14|Male": {"0": code, "1": code}} if code else {}
    batch = SeedingPredictionBatch({"u14|Male": {}}, {"u14|Male": {}},
        {"u14|Male": {"0": reason, "1": reason}}, "2026-09-15T10:00:00+00:00", None, "a" * 64, codes)
    monkeypatch.setattr(ui, "load_seeding_predictions", lambda *_args, **_kwargs: batch)
    exported = []
    original_csv = ui.team_csv
    def capture_csv(*args, **kwargs):
        data = original_csv(*args, **kwargs)
        exported.append(data)
        return data
    monkeypatch.setattr(ui, "team_csv", capture_csv)
    click(app, "Build seeding sheets")
    assert not app.error
    assert any("Delivery status: draft" in message.value for message in app.info)
    assert b"Draft" in exported[-1]
    assert "DRAFT" in app.session_state["_seeding_sheet_html"]
    from io import BytesIO
    from openpyxl import load_workbook
    assert "DRAFT" in load_workbook(BytesIO(app.session_state["_seeding_xlsx"])).active["A1"].value


def test_teams_without_a_current_rating_do_not_hold_the_pack_in_draft(operator, monkeypatch):
    app, _calls = operator
    app.session_state["_seeding_assessment"] = {"coverage": "complete", "completed": [0, 1, 2]}
    next(widget for widget in app.radio if widget.label == "Sheet pack").set_value("Choose cohorts").run()
    app.multiselect[0].set_value(["u14|Male"]).run()
    reason = "Director note: no ranking on file for this team."
    batch = SeedingPredictionBatch({"u14|Male": {}}, {"u14|Male": {}}, {"u14|Male": {"0": reason, "1": reason}},
                                   "2026-09-15T10:00:00+00:00", None, "a" * 64,
                                   {"u14|Male": {"0": "no_current_rating", "1": "no_current_rating"}})
    monkeypatch.setattr(ui, "load_seeding_predictions", lambda *_args, **_kwargs: batch)
    click(app, "Build seeding sheets")
    assert not app.error
    assert not any("Delivery status: draft" in message.value for message in app.info)
    assert any("roster assessed" in message.value for message in app.caption)
    assert "DRAFT" not in app.session_state["_seeding_sheet_html"]
    assert "No current rating" in app.session_state["_seeding_sheet_html"]


@pytest.mark.parametrize("unavailable", [None, [], {"u14|Male": None}, {"u14|Male": {"0": {}}}])
def test_malformed_snapshot_shows_rebuild_message_instead_of_crashing(operator, unavailable):
    app, _calls = operator
    click(app, "Build seeding sheets")
    pack = dict(app.session_state["_seeding_pack"])
    pack["unavailable"] = unavailable
    app.session_state["_seeding_pack"] = pack
    app.run()
    assert not app.exception
    assert any("needs rebuilding" in message.value for message in app.error)


# -------- a build a click interrupts --------------------------------------


_INTERRUPTED = "A build finished but was interrupted before it was saved."


def _offered(app):
    return _INTERRUPTED in [warning.value for warning in app.warning]


def _recovery_app(store):
    code = APP.replace(
        "from src.tournaments.seeding_intake_ui import render_seeding_pack",
        "from src.tournaments.seeding_intake_ui import render_seeding_pack\n"
        "from src.tournaments.seeding_run_store import PackRecovery",
    ).replace(
        'event_name="Acceptance Cup", save=save)',
        f'event_name="Acceptance Cup", save=save, recovery=PackRecovery("Acceptance Cup", {str(store)!r}))',
    )
    return AppTest.from_string(code, default_timeout=15).run()


def _fresh_stamps(monkeypatch, *stamps):
    """Give each build its own snapshot time, as the live predictor does."""
    load = ui.load_seeding_predictions
    queue = list(stamps)

    def stamped(*args, **kwargs):
        return replace(load(*args, **kwargs), generated_at=queue.pop(0))

    monkeypatch.setattr(ui, "load_seeding_predictions", stamped)


def _interrupt_the_next_build(monkeypatch):
    """Queue a rerun mid-build so the run is abandoned before its pack is stored.

    AppTest reruns on the same thread, so the offer shows on the page that
    follows; a browser's fast rerun starts that page before the build finishes,
    and the offer waits for the next interaction.
    """
    from streamlit.runtime.scriptrunner_utils.script_requests import RerunData
    from streamlit.runtime.scriptrunner_utils.script_run_context import get_script_run_ctx

    load = ui.load_seeding_predictions
    fired = []

    def interrupted(*args, **kwargs):
        if not fired:
            fired.append(True)
            get_script_run_ctx().script_requests.request_rerun(RerunData())
        return load(*args, **kwargs)

    monkeypatch.setattr(ui, "load_seeding_predictions", interrupted)
    return fired


def test_a_build_a_click_interrupts_is_kept_and_offered_back(operator, monkeypatch, tmp_path):
    _app, calls = operator
    fired = _interrupt_the_next_build(monkeypatch)
    app = _recovery_app(tmp_path)
    next(button for button in app.button if button.label == "Build seeding sheets").click().run()

    assert fired and "_seeding_pack" not in app.session_state
    recovery_file = tmp_path / "acceptance-cup" / "pack_recovery.json"
    assert recovery_file.exists()
    assert _offered(app)
    app.radio[0].set_value("Choose cohorts").run()
    app.multiselect[0].set_value(["u14|Male"]).run()
    click(app, "Restore the interrupted build")
    assert app.radio[0].value == "All imported cohorts"
    assert app.session_state["_seeding_pack"]["generated_at"] == "2026-09-15T10:00:00+00:00"
    assert app.session_state["saved_count"] == 1
    assert not recovery_file.exists()
    assert not _offered(app)
    assert app.session_state["_seeding_sheet_html"]
    assert len(calls) == 1


def test_restoring_a_narrowed_build_selects_its_cohorts(operator, monkeypatch, tmp_path):
    _interrupt_the_next_build(monkeypatch)
    app = _recovery_app(tmp_path)
    app.radio[0].set_value("Choose cohorts").run()
    app.multiselect[0].set_value(["u14|Male"]).run()
    next(button for button in app.button if button.label == "Build seeding sheets").click().run()
    app.multiselect[0].set_value(["u14|Male", "u15|Female"]).run()
    click(app, "Restore the interrupted build")

    assert app.session_state["_seeding_pack"]["selected_cohorts"] == ["u14|Male"]
    assert app.radio[0].value == "Choose cohorts"
    assert app.multiselect[0].value == ["u14|Male"]
    assert app.session_state["_seeding_sheet_html"]


def test_discarding_an_interrupted_build_keeps_the_saved_pack(operator, monkeypatch, tmp_path):
    _interrupt_the_next_build(monkeypatch)
    app = _recovery_app(tmp_path)
    next(button for button in app.button if button.label == "Build seeding sheets").click().run()
    click(app, "Discard it")

    assert "_seeding_pack" not in app.session_state
    assert not (tmp_path / "acceptance-cup" / "pack_recovery.json").exists()
    assert not _offered(app)


def test_a_build_that_finishes_leaves_nothing_to_restore(operator, tmp_path):
    app = _recovery_app(tmp_path)
    click(app, "Build seeding sheets")

    assert app.session_state["_seeding_pack"]["generated_at"] == "2026-09-15T10:00:00+00:00"
    assert not (tmp_path / "acceptance-cup" / "pack_recovery.json").exists()
    assert not _offered(app)


def test_a_kept_build_no_newer_than_the_saved_pack_is_dropped_unseen(operator, tmp_path):
    from src.tournaments.seeding_run_store import PackRecovery

    app = _recovery_app(tmp_path)
    click(app, "Build seeding sheets")
    PackRecovery("Acceptance Cup", tmp_path).write(deepcopy(app.session_state["_seeding_pack"]))
    app.run()

    assert not _offered(app)
    assert not (tmp_path / "acceptance-cup" / "pack_recovery.json").exists()


def test_a_kept_build_for_a_different_roster_is_dropped_unseen(operator, tmp_path):
    from src.tournaments.seeding_run_store import PackRecovery

    app = _recovery_app(tmp_path)
    click(app, "Build seeding sheets")
    stale = deepcopy(app.session_state["_seeding_pack"])
    stale["generated_at"] = "2026-09-16T10:00:00+00:00"
    stale["roster_fingerprint"] = "another roster"
    PackRecovery("Acceptance Cup", tmp_path).write(stale)
    app.run()

    assert not _offered(app)
    assert not (tmp_path / "acceptance-cup" / "pack_recovery.json").exists()


def test_a_build_whose_sheets_fail_is_not_offered_back(operator, monkeypatch, tmp_path):
    app = _recovery_app(tmp_path)
    monkeypatch.setattr(ui, "build_seeding_workbook", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad sheet")))
    click(app, "Build seeding sheets")

    assert "_seeding_pack" not in app.session_state
    assert not (tmp_path / "acceptance-cup" / "pack_recovery.json").exists()


def test_the_seeding_tab_keeps_builds_beside_its_named_run(monkeypatch, tmp_path):
    import tournament_intake as intake

    seen = []
    monkeypatch.setattr(intake, "render_seeding_pack", lambda *_args, **kwargs: seen.append(kwargs["recovery"]))
    monkeypatch.setattr(intake, "default_seeding_base_dir", lambda: tmp_path)
    monkeypatch.setattr(intake, "_seeding_run_name", lambda: "Spring Cup")
    intake._render_seeding_sheet(None, (), None)
    monkeypatch.setattr(intake, "_seeding_run_name", lambda: "")
    intake._render_seeding_sheet(None, (), None)

    assert seen[0].path == tmp_path / "spring-cup" / "pack_recovery.json"
    assert seen[1] is None


def test_an_interrupted_rebuild_replaces_the_saved_pack_on_restore(operator, monkeypatch, tmp_path):
    _fresh_stamps(monkeypatch, "2026-09-15T11:00:00+00:00", "2026-09-15T12:00:00+00:00")
    app = _recovery_app(tmp_path)
    click(app, "Build seeding sheets")
    _interrupt_the_next_build(monkeypatch)
    next(button for button in app.button if button.label == "Build seeding sheets").click().run()

    assert app.session_state["_seeding_pack"]["generated_at"] == "2026-09-15T11:00:00+00:00"
    assert _offered(app)
    click(app, "Restore the interrupted build")
    assert app.session_state["_seeding_pack"]["generated_at"] == "2026-09-15T12:00:00+00:00"
    assert not (tmp_path / "acceptance-cup" / "pack_recovery.json").exists()


def test_discarding_an_interrupted_rebuild_keeps_the_saved_pack(operator, monkeypatch, tmp_path):
    _fresh_stamps(monkeypatch, "2026-09-15T11:00:00+00:00", "2026-09-15T12:00:00+00:00")
    app = _recovery_app(tmp_path)
    click(app, "Build seeding sheets")
    _interrupt_the_next_build(monkeypatch)
    next(button for button in app.button if button.label == "Build seeding sheets").click().run()
    click(app, "Discard it")

    assert app.session_state["_seeding_pack"]["generated_at"] == "2026-09-15T11:00:00+00:00"
    assert not (tmp_path / "acceptance-cup" / "pack_recovery.json").exists()


def test_a_note_saved_while_the_build_ran_survives_its_restore(operator, monkeypatch, tmp_path):
    _fresh_stamps(monkeypatch, "2026-09-15T11:00:00+00:00", "2026-09-15T12:00:00+00:00")
    app = _recovery_app(tmp_path)
    click(app, "Build seeding sheets")
    _interrupt_the_next_build(monkeypatch)
    next(button for button in app.button if button.label == "Build seeding sheets").click().run()
    app.text_area[0].set_value("Note written after the interrupted build")
    next(button for button in app.button if button.label == "Save director notes").click().run()
    app.session_state["_seeding_pack"]["placement_reviews"] = {"u14|Male": "e" * 64}
    click(app, "Restore the interrupted build")

    restored = app.session_state["_seeding_pack"]
    assert restored["generated_at"] == "2026-09-15T12:00:00+00:00"
    assert restored["operator_notes"]["u14|Male"] == "Note written after the interrupted build"
    assert restored["placement_reviews"] == {"u14|Male": "e" * 64}


def test_a_restore_whose_save_fails_keeps_the_build_until_a_save_lands(operator, monkeypatch, tmp_path):
    _interrupt_the_next_build(monkeypatch)
    app = _recovery_app(tmp_path)
    next(button for button in app.button if button.label == "Build seeding sheets").click().run()
    app.session_state["test_save_succeeds"] = False
    click(app, "Restore the interrupted build")
    recovery_file = tmp_path / "acceptance-cup" / "pack_recovery.json"

    assert app.session_state["_seeding_pack_unsaved"] is True
    assert recovery_file.exists()
    app.run()
    assert recovery_file.exists()
    app.session_state["test_save_succeeds"] = True
    click(app, "Retry saving pack")
    assert not recovery_file.exists()


def test_a_build_whose_save_fails_keeps_its_recovery(operator, tmp_path):
    app = _recovery_app(tmp_path)
    app.session_state["test_save_succeeds"] = False
    click(app, "Build seeding sheets")

    assert app.session_state["_seeding_pack_unsaved"] is True
    assert (tmp_path / "acceptance-cup" / "pack_recovery.json").exists()
    assert not _offered(app)


def test_a_rerun_between_storing_and_saving_the_pack_keeps_its_recovery(operator, monkeypatch, tmp_path):
    from streamlit.runtime.scriptrunner_utils.script_requests import RerunData
    from streamlit.runtime.scriptrunner_utils.script_run_context import get_script_run_ctx

    persist = ui._persist_decisions
    fired = []

    def interrupted(save):
        if not fired:
            fired.append(True)
            get_script_run_ctx().script_requests.request_rerun(RerunData())
        persist(save)

    monkeypatch.setattr(ui, "_persist_decisions", interrupted)
    app = _recovery_app(tmp_path)
    next(button for button in app.button if button.label == "Build seeding sheets").click().run()

    assert fired and "saved_count" not in app.session_state
    assert app.session_state["_seeding_pack_unsaved"] is True
    assert (tmp_path / "acceptance-cup" / "pack_recovery.json").exists()


def test_a_restored_build_whose_sheets_fail_keeps_the_saved_pack(operator, monkeypatch, tmp_path):
    _fresh_stamps(monkeypatch, "2026-09-15T11:00:00+00:00", "2026-09-15T12:00:00+00:00")
    app = _recovery_app(tmp_path)
    click(app, "Build seeding sheets")
    _interrupt_the_next_build(monkeypatch)
    next(button for button in app.button if button.label == "Build seeding sheets").click().run()
    saved_count = app.session_state["saved_count"]
    monkeypatch.setattr(ui, "build_seeding_workbook", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad sheet")))
    click(app, "Restore the interrupted build")

    assert app.session_state["_seeding_pack"]["generated_at"] == "2026-09-15T11:00:00+00:00"
    assert app.session_state["saved_count"] == saved_count
    assert not (tmp_path / "acceptance-cup" / "pack_recovery.json").exists()


def test_a_note_changed_while_the_build_ran_keeps_its_newer_text_on_restore(operator, monkeypatch, tmp_path):
    _fresh_stamps(monkeypatch, "2026-09-15T11:00:00+00:00", "2026-09-15T12:00:00+00:00")
    app = _recovery_app(tmp_path)
    click(app, "Build seeding sheets")
    app.text_area[0].set_value("Note before the rebuild")
    next(button for button in app.button if button.label == "Save director notes").click().run()
    app.session_state["_seeding_pack"]["placement_reviews"] = {"u14|Male": "a" * 64}
    _interrupt_the_next_build(monkeypatch)
    next(button for button in app.button if button.label == "Build seeding sheets").click().run()
    kept = PackRecovery("Acceptance Cup", tmp_path).load()
    assert kept["operator_notes"]["u14|Male"] == "Note before the rebuild"
    assert kept["placement_reviews"] == {"u14|Male": "a" * 64}
    app.text_area[0].set_value("Note changed during the rebuild")
    next(button for button in app.button if button.label == "Save director notes").click().run()
    app.session_state["_seeding_pack"]["placement_reviews"] = {"u14|Male": "b" * 64}
    click(app, "Restore the interrupted build")

    restored = app.session_state["_seeding_pack"]
    assert restored["generated_at"] == "2026-09-15T12:00:00+00:00"
    assert restored["operator_notes"]["u14|Male"] == "Note changed during the rebuild"
    assert restored["placement_reviews"] == {"u14|Male": "b" * 64}


def test_a_failing_rebuild_hands_the_recovery_back_to_the_unsaved_pack(operator, monkeypatch, tmp_path):
    _fresh_stamps(monkeypatch, "2026-09-15T11:00:00+00:00", "2026-09-15T12:00:00+00:00")
    app = _recovery_app(tmp_path)
    app.session_state["test_save_succeeds"] = False
    click(app, "Build seeding sheets")
    monkeypatch.setattr(ui, "build_seeding_workbook", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad sheet")))
    click(app, "Build seeding sheets")

    assert app.session_state["_seeding_pack"]["generated_at"] == "2026-09-15T11:00:00+00:00"
    assert PackRecovery("Acceptance Cup", tmp_path).load()["generated_at"] == "2026-09-15T11:00:00+00:00"


def test_the_seeding_app_does_not_warn_when_restore_sets_the_pickers():
    import tomllib
    from pathlib import Path

    config = tomllib.loads((Path(__file__).resolve().parents[2] / ".streamlit" / "config.toml").read_text("utf-8"))
    assert config["global"]["disableWidgetStateDuplicationWarning"] is True
