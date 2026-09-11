"""All-team review behavior and a real Streamlit render without network calls."""

import json
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.runtime import Runtime
from streamlit.testing.v1 import AppTest

from src.tournaments.backtest_intake_state import DivisionReview, read_snapshot, structure_hash, write_snapshot
from src.tournaments.backtest_intake_ui import match_table
from src.tournaments.backtest_link_store import EventLinks, TeamLink, load_links, update_links
from src.tournaments.gotsport_event_structure import Pool, PoolMember
from tests.unit.test_backtest_intake_state import sample_snapshot


@pytest.fixture(autouse=True)
def _isolate_streamlit_process_globals(monkeypatch):
    """AppTest leaves its temporary script as __main__, breaking spawn later.

    Restore after every run, including element-triggered reruns and direct
    AppTests outside rendered_intake. Runtime/secrets are process globals too;
    AppTest's own cleanup is not protected if a run raises before completing.
    """
    original_run = AppTest._run

    def isolated_run(self, *args, **kwargs):
        original_modules = {name: sys.modules.get(name) for name in ("__main__", "__mp_main__")}
        original_runtime = Runtime._instance
        original_secrets = st.secrets
        try:
            return original_run(self, *args, **kwargs)
        finally:
            for name, module in original_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
            Runtime._instance = original_runtime
            st.secrets = original_secrets

    monkeypatch.setattr(AppTest, "_run", isolated_run)


def test_direct_apptest_restores_process_entrypoint_and_streamlit_globals():
    original_main = sys.modules["__main__"]
    original_runtime = Runtime._instance
    original_secrets = st.secrets

    test = AppTest.from_string("import streamlit as st\nst.write('isolated')").run()

    assert not test.exception
    assert sys.modules["__main__"] is original_main
    assert Runtime._instance is original_runtime
    assert st.secrets is original_secrets


def test_match_table_keeps_matched_unmatched_and_cleared_entrants():
    snapshot = sample_snapshot()
    saved = EventLinks(event_id="51783", links=(TeamLink("100", "Alpha", "canonical-a", "operator", "now"),),
                       removed_registration_ids=("102",))
    details = {"canonical-a": {"team_name": "Current Alpha", "age_group": "u11", "gender": "Male"}}

    rows = match_table(snapshot, saved, details)

    assert [row["Registration ID"] for row in rows] == ["100", "101", "102"]
    assert [row["Status"] for row in rows] == ["Matched", "Needs review", "Match cleared"]
    assert rows[0]["Tournament cohort"] == "U12"
    assert rows[0]["PitchRank team"] == "Current Alpha"
    assert rows[0]["Pools"] == "Bracket A"
    assert rows[2]["PitchRank ID"] == ""


def test_unavailable_saved_team_remains_visible_for_correction():
    snapshot = sample_snapshot()
    links = EventLinks(event_id="51783", links=(TeamLink("100", "Alpha", "missing", "operator", "now"),))

    rows = match_table(snapshot, links, {})

    assert rows[0]["Status"] == "Linked team unavailable"
    assert rows[0]["PitchRank ID"] == "missing"
    assert len(rows) == 3


def test_old_automatic_name_link_stays_visible_as_a_suggestion_until_operator_confirms():
    snapshot = sample_snapshot()
    old_name_link = TeamLink("100", "Alpha", "old-name-match", "exact_name", "before-this-intake")
    saved = EventLinks(event_id="51783", links=(old_name_link,))

    rows = match_table(snapshot, saved, {"old-name-match": {"team_name": "Possible Alpha"}})

    assert rows[0]["Status"] == "Needs review"
    assert rows[0]["PitchRank ID"] == "old-name-match"
    assert rows[0]["PitchRank team"] == "Possible Alpha"
    assert rows[0]["Match method"] == "exact_name"
    assert saved.removed_registration_ids == ()


def test_missing_registration_can_have_an_editable_local_match_without_a_fabricated_id():
    snapshot = sample_snapshot()
    first = replace(snapshot.roster.teams[0], registration_id="", provider_team_id=None,
                    source_entry_key="source:10:pool-a:alpha")
    snapshot = replace(snapshot, roster=replace(snapshot.roster, teams=(first,) + snapshot.roster.teams[1:]))
    links = EventLinks(event_id="51783", links=(
        TeamLink("source:10:pool-a:alpha", "Alpha", "operator-choice", "operator", "now"),
    ))

    rows = match_table(snapshot, links, {"operator-choice": {"team_name": "Alpha"}})

    assert rows[0]["Registration ID"] == ""
    assert rows[0]["GotSport team ID"] == ""
    assert rows[0]["Match key"] == "source:10:pool-a:alpha"
    assert rows[0]["Status"] == "Matched"
    assert rows[0]["PitchRank ID"] == "operator-choice"


def test_registration_in_two_divisions_is_visible_in_both_with_its_single_saved_match():
    snapshot = sample_snapshot()
    extra = replace(snapshot.roster.teams[0], source_index=3, group_id="20", division_label="GU13 Silver")
    snapshot = replace(snapshot, roster=replace(snapshot.roster, teams=snapshot.roster.teams + (extra,)),
                       resolved=snapshot.resolved + (replace(snapshot.resolved[0], source_index=3),))
    links = EventLinks(event_id="51783", links=(TeamLink("100", "Alpha", "canonical-a", "operator", "now"),))

    rows = match_table(snapshot, links, {"canonical-a": {"team_name": "Alpha"}})

    alpha = [row for row in rows if row["Registration ID"] == "100"]
    assert [row["Tournament cohort"] for row in alpha] == ["U12", "U13"]
    assert all(row["PitchRank ID"] == "canonical-a" for row in alpha)


class ReadOnlyTeams:
    """Only a executed SELECT is supported; a database write fails the test."""

    def __init__(self):
        self.executed = []

    def table(self, table_name):
        assert table_name == "teams"
        return self.Query(self)

    class Query:
        def __init__(self, owner):
            self.owner = owner
            self.ids = []

        def select(self, columns):
            assert "team_id_master" in columns
            return self

        def in_(self, column, ids):
            assert column == "team_id_master"
            self.ids = ids
            return self

        def execute(self):
            self.owner.executed.append(tuple(self.ids))
            return SimpleNamespace(data=[{"team_id_master": team_id, "team_name": "Current Alpha",
                                          "age_group": "u11", "gender": "Male", "is_deprecated": False}
                                         for team_id in self.ids])


def _render_fixture_app():
    import streamlit as st

    import tournament_intake as app
    from src.tournaments.backtest_intake_ui import render_intake
    from tests.unit.test_backtest_intake_state import sample_snapshot
    from tests.unit.test_backtest_intake_ui import ReadOnlyTeams

    if app._BACKTEST_KEYS.snapshot not in st.session_state:
        st.session_state[app._BACKTEST_KEYS.snapshot] = sample_snapshot()
    st.session_state.setdefault("_seeding_result", "seeding-must-survive")
    render_intake(ReadOnlyTeams())


@pytest.fixture
def rendered_intake(tmp_path, monkeypatch):
    import tournament_intake as app

    monkeypatch.setattr(app, "reports_dir", lambda: tmp_path)
    monkeypatch.setattr(app, "_render_seeding_event_scrape", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "_seeding_merge_resolver",
                        lambda client: SimpleNamespace(version="ok", resolve=lambda team_id: team_id))
    test = AppTest.from_function(_render_fixture_app, default_timeout=10).run()
    assert not test.exception, [error.message for error in test.exception]
    return test, tmp_path


def test_real_streamlit_render_shows_event_totals_every_team_and_only_intake_actions(rendered_intake):
    test, _ = rendered_intake

    assert any("Spring Invitational" in item.value for item in test.markdown)
    assert {item.label: item.value for item in test.metric} == {
        "Total teams": "3", "Divisions": "2", "Pools": "2", "Fixtures": "1",
    }
    tables = [item.value for item in test.dataframe]
    matches = next(frame for frame in tables if "PitchRank ID" in frame.columns)
    assert matches["Event team"].tolist() == ["Alpha", "Bravo", "Charlie"]
    assert matches["Status"].tolist() == ["Matched", "Needs review", "Needs review"]
    labels = {button.label for button in test.button}
    assert "Save Backtest intake" in labels
    assert "Clear this match" in labels
    assert not any("Run backtest" in label or "Seeding" in label for label in labels)
    assert test.session_state["_seeding_result"] == "seeding-must-survive"


def test_streamlit_clear_stays_unresolved_after_rerender_and_can_be_saved(rendered_intake):
    test, tmp_path = rendered_intake
    test.button(key="bt_clear_capture-one_0").click().run()
    assert not test.exception, [error.message for error in test.exception]
    links = load_links("gotsport__51783__unknown", base_dir=tmp_path)
    assert links.removed_registration_ids == ("100",)
    assert links.links == ()
    matches = next(item.value for item in test.dataframe if "PitchRank ID" in item.value.columns)
    assert matches.loc[0, "Status"] == "Match cleared"
    assert test.session_state["_seeding_result"] == "seeding-must-survive"

    test.button(key="bt_save_capture-one").click().run()
    assert not test.exception, [error.message for error in test.exception]
    saved = read_snapshot("gotsport__51783__unknown", base_dir=tmp_path)
    assert len(saved.roster.teams) == 3
    assert len(saved.roster.divisions) == 2
    assert saved.roster.event_name == "Spring Invitational"


def test_structure_review_notes_and_check_survive_save_and_reload(rendered_intake):
    test, tmp_path = rendered_intake
    test.text_area(key="bt_division_capture-one_10_notes").set_value("Top two advance; head-to-head first")
    test.checkbox(key="bt_division_capture-one_10_checked").check()
    test.button(key="bt_save_capture-one").click().run()
    assert not test.exception, [error.message for error in test.exception]

    loaded = read_snapshot("gotsport__51783__unknown", base_dir=tmp_path)
    review = next(item for item in loaded.reviews if item.group_id == "10")
    assert review.checked is True
    assert review.notes == "Top two advance; head-to-head first"


def test_refreshed_capture_loads_saved_review_work_before_rendering(rendered_intake):
    import tournament_intake as app

    test, tmp_path = rendered_intake
    snapshot = sample_snapshot()
    review = DivisionReview("10", structure_hash(snapshot.roster.divisions[0]), "Two advance", checked=True)
    write_snapshot("gotsport__51783__unknown", replace(snapshot, reviews=(review,)), base_dir=tmp_path)
    refreshed = replace(snapshot, generation="fresh-capture")
    test.session_state[app._BACKTEST_KEYS.snapshot] = refreshed

    test.run()

    assert not test.exception, [error.message for error in test.exception]
    assert test.text_area(key="bt_division_fresh-capture_10_notes").value == "Two advance"
    assert test.checkbox(key="bt_division_fresh-capture_10_checked").value is True
    test.button(key="bt_save_fresh-capture").click().run()
    assert not test.exception, [error.message for error in test.exception]
    assert read_snapshot("gotsport__51783__unknown", base_dir=tmp_path).reviews[0] == review


def test_stale_form_preserves_new_notes_and_refreshes_widgets_after_save(rendered_intake):
    test, tmp_path = rendered_intake
    snapshot = sample_snapshot()
    review = DivisionReview("10", structure_hash(snapshot.roster.divisions[0]),
                            "Saved in another session", checked=True)
    write_snapshot("gotsport__51783__unknown", replace(snapshot, reviews=(review,)), base_dir=tmp_path)

    # This form was opened before the other session saved. Its unchanged blanks
    # must not be mistaken for a request to erase that newer work.
    test.button(key="bt_save_capture-one").click().run()

    assert not test.exception, [error.message for error in test.exception]
    assert test.text_area(key="bt_division_capture-one_10_1_notes").value == review.notes
    assert test.checkbox(key="bt_division_capture-one_10_1_checked").value is True
    assert read_snapshot("gotsport__51783__unknown", base_dir=tmp_path).reviews[0] == review

    # After seeing the actual merged result, an intentional clear remains valid.
    test.text_area(key="bt_division_capture-one_10_1_notes").set_value("")
    test.checkbox(key="bt_division_capture-one_10_1_checked").uncheck()
    test.button(key="bt_save_capture-one").click().run()
    assert not test.exception, [error.message for error in test.exception]
    saved = read_snapshot("gotsport__51783__unknown", base_dir=tmp_path).reviews[0]
    assert saved.notes == ""
    assert saved.checked is False


def test_conflicting_review_save_keeps_disk_and_can_reload_latest_notes(rendered_intake):
    test, tmp_path = rendered_intake
    snapshot = sample_snapshot()
    review = DivisionReview("10", structure_hash(snapshot.roster.divisions[0]), "Other session's notes")
    path = write_snapshot("gotsport__51783__unknown", replace(snapshot, reviews=(review,)), base_dir=tmp_path)
    before = path.read_bytes()
    test.text_area(key="bt_division_capture-one_10_notes").set_value("My competing notes")

    test.button(key="bt_save_capture-one").click().run()

    assert not test.exception, [error.message for error in test.exception]
    assert any("changed in another session" in error.value for error in test.error)
    assert path.read_bytes() == before
    assert test.text_area(key="bt_division_capture-one_10_notes").value == "My competing notes"
    test.button(key="_backtest_open_saved").click().run()
    assert not test.exception, [error.message for error in test.exception]
    assert test.text_area(key="bt_division_capture-one_10_1_notes").value == review.notes


def test_streamlit_can_replace_an_existing_match_even_when_current_age_differs(rendered_intake, monkeypatch):
    import tournament_intake as app
    from src.tournaments import backtest_intake_ui as ui
    from src.tournaments.roster_resolver import ManualResolution

    test, tmp_path = rendered_intake
    detail = {"team_id_master": "operator-new", "team_name": "Alpha older squad", "age_group": "u14",
              "gender": "Male", "is_deprecated": False}
    monkeypatch.setattr(app, "_seeding_provider_id_lookup", lambda client: lambda provider_id: None)
    monkeypatch.setattr(ui, "make_team_details_lookup", lambda client: lambda team_id: detail)
    monkeypatch.setattr(ui, "resolve_manual_reference",
                        lambda *args, **kwargs: ManualResolution("ok", "operator-new", detail, False))

    test.text_input(key="bt_reference_capture-one_0").set_value("operator-new").run()
    assert not test.exception, [error.message for error in test.exception]
    test.button(key="bt_use_capture-one_0").click().run()
    assert not test.exception, [error.message for error in test.exception]

    links = load_links("gotsport__51783__unknown", base_dir=tmp_path)
    assert len(links.links) == 1
    assert links.links[0].team_id_master == "operator-new"
    assert links.links[0].matched_by == "operator"
    assert test.session_state["_seeding_result"] == "seeding-must-survive"


def _multi_division_snapshot(second_id):
    snapshot = sample_snapshot()
    extra = replace(snapshot.roster.teams[0], source_index=3, group_id="20", division_label="GU13 Silver")
    return replace(snapshot, roster=replace(snapshot.roster, teams=snapshot.roster.teams + (extra,)),
                   resolved=snapshot.resolved + (replace(snapshot.resolved[0], source_index=3,
                                                         team_id_master=second_id),))


def test_sync_coalesces_same_registration_after_canonical_merge_resolution(tmp_path, monkeypatch):
    import tournament_intake as app
    from src.tournaments.backtest_intake_ui import _sync_matches

    snapshot = _multi_division_snapshot("deprecated-a")
    monkeypatch.setattr(app, "_seeding_merge_resolver", lambda client: SimpleNamespace(
        version="ok", resolve=lambda team_id: "canonical-a" if team_id == "deprecated-a" else team_id
    ))
    client = ReadOnlyTeams()

    links, details, conflicts = _sync_matches(snapshot, client, tmp_path)

    assert conflicts == {}
    assert len(links.links) == 1
    assert links.links[0].registration_id == "100"
    assert links.links[0].team_id_master == "canonical-a"
    assert client.executed == [("canonical-a",)]
    rows = match_table(snapshot, links, details, conflicts=conflicts)
    assert [row["Status"] for row in rows if row["Registration ID"] == "100"] == ["Matched", "Matched"]


@pytest.mark.parametrize("saved_method", [None, "gotsport_id", "operator"])
def test_conflicting_automatic_ids_never_choose_a_team_or_discard_operator_decisions(
    tmp_path, monkeypatch, saved_method
):
    import tournament_intake as app
    from src.tournaments.backtest_intake_ui import _sync_matches

    snapshot = _multi_division_snapshot("canonical-other")
    monkeypatch.setattr(app, "_seeding_merge_resolver", lambda client: SimpleNamespace(
        version="ok", resolve=lambda team_id: team_id
    ))
    if saved_method:
        update_links("gotsport__51783__unknown", event_id="51783", base_dir=tmp_path,
                     changed_links=(TeamLink("100", "Alpha", "saved-choice", saved_method, "now"),))

    links, details, conflicts = _sync_matches(snapshot, ReadOnlyTeams(), tmp_path)
    rows = match_table(snapshot, links, details, conflicts=conflicts)

    assert conflicts == {"100": ("canonical-a", "canonical-other")}
    assert links.removed_registration_ids == ()
    assert [link.team_id_master for link in links.links] == (["saved-choice"] if saved_method else [])
    assert [row["Status"] for row in rows if row["Registration ID"] == "100"] == (
        ["Matched", "Matched"] if saved_method == "operator" else ["Needs review", "Needs review"]
    )
    assert all("canonical-other" in row["Match issue"] for row in rows if row["Registration ID"] == "100")


@pytest.mark.parametrize("pool_id,source_key", [("named", "pool:10:named:1"), ("", "pool:10:1:1")])
def test_empty_registration_pool_membership_uses_only_its_exact_source_entry(pool_id, source_key):
    snapshot = sample_snapshot()
    division = replace(snapshot.roster.divisions[0], pools=(
        Pool("first", "Wrong pool", (PoolMember("", "Alpha", 1),)),
        Pool(pool_id, "Correct pool", (PoolMember("", "Alpha", 1),)),
    ))
    team = replace(snapshot.roster.teams[0], registration_id="", source_entry_key=source_key)
    roster = replace(snapshot.roster, teams=(team,) + snapshot.roster.teams[1:],
                     divisions=(division,) + snapshot.roster.divisions[1:])
    snapshot = replace(snapshot, roster=roster)

    rows = match_table(snapshot, EventLinks(event_id="51783"), {})

    assert rows[0]["Pools"] == "Correct pool"
    no_source = replace(snapshot, roster=replace(roster, teams=(replace(team, source_entry_key=""),)
                                                + roster.teams[1:]))
    assert match_table(no_source, EventLinks(event_id="51783"), {})[0]["Pools"] == ""


def test_reordered_source_only_names_do_not_inherit_confirmed_matches_until_reconfirmed(tmp_path):
    snapshot = sample_snapshot()
    first, second = snapshot.roster.teams[:2]
    swapped = (replace(first, team_name="Bravo", registration_id="", source_entry_key="pool:10:A:1"),
               replace(second, team_name="Alpha", registration_id="", source_entry_key="pool:10:A:2"))
    snapshot = replace(snapshot, generation="rewalk", roster=replace(
        snapshot.roster, teams=swapped + snapshot.roster.teams[2:]
    ))
    saved = update_links("gotsport__51783__unknown", event_id="51783", base_dir=tmp_path, changed_links=(
        TeamLink("pool:10:A:1", "Alpha", "canonical-a", "operator", "earlier"),
        TeamLink("pool:10:A:2", "Bravo", "canonical-b", "operator", "earlier"),
    ))
    details = {"canonical-a": {"team_name": "Alpha"}, "canonical-b": {"team_name": "Bravo"}}

    rows = match_table(snapshot, saved, details)

    assert [row["Status"] for row in rows[:2]] == ["Needs review", "Needs review"]
    assert rows[0]["PitchRank ID"] == "canonical-a"
    assert "previously held 'Alpha'" in rows[0]["Match issue"]
    assert "previously held 'Bravo'" in rows[1]["Match issue"]
    confirmed = update_links("gotsport__51783__unknown", event_id="51783", base_dir=tmp_path, changed_links=(
        TeamLink("pool:10:A:1", "Bravo", "canonical-b", "operator", "confirmed-now"),
    ))
    confirmed_rows = match_table(snapshot, confirmed, details)
    assert confirmed_rows[0]["Status"] == "Matched"
    assert confirmed_rows[0]["Match issue"] == ""
    assert confirmed_rows[1]["Status"] == "Needs review"


@pytest.mark.parametrize("failure_stage", ["merge", "database"])
def test_streamlit_outage_keeps_local_links_and_clears_in_display_and_export(
    rendered_intake, monkeypatch, failure_stage
):
    import tournament_intake as app
    from src.tournaments import backtest_intake_ui as ui

    test, tmp_path = rendered_intake
    update_links("gotsport__51783__unknown", event_id="51783", base_dir=tmp_path,
                 changed_links=(TeamLink("100", "Alpha", "operator-choice", "operator", "now"),),
                 removed_registration_ids=("102",))
    exported = []
    real_download = ui.st.download_button

    def record_download(label, data, **kwargs):
        exported.append(json.loads(data))
        return real_download(label, data, **kwargs)

    def unavailable(*args, **kwargs):
        raise OSError("database temporarily unavailable")

    monkeypatch.setattr(ui.st, "download_button", record_download)
    if failure_stage == "merge":
        monkeypatch.setattr(app, "_seeding_merge_resolver", unavailable)
    else:
        monkeypatch.setattr(ReadOnlyTeams.Query, "execute", unavailable)
    test.run()

    assert not test.exception, [error.message for error in test.exception]
    assert any("Team matching is unavailable" in warning.value for warning in test.warning)
    matches = next(item.value for item in test.dataframe if "PitchRank ID" in item.value.columns)
    assert matches["Status"].tolist() == ["Linked team unavailable", "Needs review", "Match cleared"]
    assert matches.loc[0, "PitchRank ID"] == "operator-choice"
    assert exported[-1]["links"]["links"][0]["team_id_master"] == "operator-choice"
    assert exported[-1]["links"]["removed_registration_ids"] == ["102"]
    assert exported[-1]["team_matches"][0]["PitchRank ID"] == "operator-choice"
    assert test.session_state["_seeding_result"] == "seeding-must-survive"
