"""All-team review behavior and a real Streamlit render without network calls."""

import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.runtime import Runtime
from streamlit.testing.v1 import AppTest

from src.tournaments.backtest_intake_state import (
    CaptureVerification,
    CohortDecision,
    DivisionReview,
    EventTiebreakDecision,
    read_snapshot,
    structure_hash,
)
from src.tournaments.backtest_intake_ui import (
    _preserve_review_state_after_capture,
    match_table,
    search_master_teams,
)
from src.tournaments.backtest_link_store import (
    CollisionAcknowledgement,
    EventLinks,
    TeamLink,
    load_links,
    update_links,
)
from src.tournaments.backtest_reviewed_run import BACKTEST_ENGINE_VERSION
from src.tournaments.gotsport_event_structure import Pool, PoolMember
from src.tournaments.schedule_simulator import (
    STANDARD_SCORING_POLICY,
    TIGER_TOURNAMENTS_SCORING_POLICY,
    TIGER_TOURNAMENTS_TIEBREAK_ORDER,
)
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

    test = AppTest.from_string(
        "import streamlit as st\nst.write('isolated')", default_timeout=10
    ).run()

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


def test_distinct_registrations_sharing_a_canonical_team_require_explicit_acknowledgement():
    snapshot = sample_snapshot()
    links = EventLinks(event_id="51783", links=(
        TeamLink("100", "Alpha", "canonical-a", "gotsport_id", "now"),
        TeamLink("101", "Bravo", "canonical-a", "gotsport_id", "now"),
    ))
    details = {"canonical-a": {"team_name": "Canonical A"}}

    rows = match_table(snapshot, links, details)
    assert [row["Status"] for row in rows[:2]] == ["Needs review", "Needs review"]
    assert all("also linked" in row["Match issue"] for row in rows[:2])

    acknowledgement = CollisionAcknowledgement(
        "canonical-a", ("100", "101"), "Same squad entered twice", "now"
    )
    confirmed = replace(links, collision_acknowledgements=(acknowledgement,))
    assert [row["Status"] for row in match_table(snapshot, confirmed, details)[:2]] == ["Matched", "Matched"]


def test_out_of_scope_registration_does_not_create_an_in_scope_collision():
    snapshot = sample_snapshot()
    scoped = replace(
        snapshot,
        roster=replace(snapshot.roster, teams=(snapshot.roster.teams[0],)),
        resolved=(snapshot.resolved[0],),
    )
    links = EventLinks(
        event_id="51783",
        links=(
            TeamLink("100", "Alpha", "canonical-a", "gotsport_id", "now"),
            TeamLink("out-of-scope", "Youth Alpha", "canonical-a", "gotsport_id", "now"),
        ),
    )

    rows = match_table(scoped, links, {"canonical-a": {"team_name": "Canonical A"}})

    assert rows[0]["Status"] == "Matched"
    assert rows[0]["Match issue"] == ""


def test_not_found_is_a_completed_review_with_no_pitchrank_id():
    snapshot = sample_snapshot()
    links = EventLinks(event_id="51783", not_found_registration_ids=("101",))
    rows = match_table(snapshot, links, {})
    assert rows[1]["Status"] == "Not found"
    assert rows[1]["PitchRank ID"] == ""


def test_an_invalid_cohort_draft_keeps_the_last_saved_correction(monkeypatch):
    from src.tournaments import backtest_intake_ui as ui

    decision = CohortDecision("10", "u12", "Male", "Published source", "https://example.test")
    snapshot = replace(sample_snapshot(), cohort_decisions=(decision,))
    invalid = {**asdict(decision), "source_url": ""}
    monkeypatch.setattr(
        ui,
        "st",
        SimpleNamespace(session_state={f"bt_cohort_drafts_{snapshot.generation}": {"10": invalid}}),
    )

    assert ui._current_cohort_decisions(snapshot) == (decision,)


def test_unsupported_scoring_draft_blocks_a_previously_saved_rule(monkeypatch):
    from src.tournaments import backtest_intake_ui as ui

    saved = EventTiebreakDecision(
        ("points", "goal_differential"),
        "Published source",
        "https://example.test/tiebreaks",
        STANDARD_SCORING_POLICY,
    )
    snapshot = replace(sample_snapshot(), tiebreak_decision=saved)
    draft = {
        "mode": "Points → goal differential → goals scored → wins",
        "custom_order": "points, goal differential",
        "scoring_mode": "Other scoring or standings modifiers",
        "note": saved.note,
        "source_url": saved.source_url,
    }
    monkeypatch.setattr(
        ui,
        "st",
        SimpleNamespace(
            session_state={f"bt_tiebreak_draft_{snapshot.generation}": draft}
        ),
    )

    decision, error = ui._current_tiebreak_decision(snapshot)

    assert decision is None
    assert "cannot replay" in error


def test_saved_tiger_tiebreak_draft_remains_runnable(monkeypatch):
    from src.tournaments import backtest_intake_ui as ui

    saved = EventTiebreakDecision(
        TIGER_TOURNAMENTS_TIEBREAK_ORDER,
        "Verified from the organizer's published rules",
        "https://tigertournaments.com/resources-2/",
        TIGER_TOURNAMENTS_SCORING_POLICY,
    )
    snapshot = replace(sample_snapshot(), tiebreak_decision=saved)
    monkeypatch.setattr(ui, "st", SimpleNamespace(session_state={}))

    decision, error = ui._current_tiebreak_decision(snapshot)

    assert error == ""
    assert decision == saved


def test_targeted_capture_carries_reviews_cohorts_and_tiebreak_rules():
    original = sample_snapshot()
    review = DivisionReview("10", structure_hash(original.roster.divisions[0]), "Checked", True)
    decision = CohortDecision("10", "u12", "Male", "Published source", "https://example.test")
    tiebreak = EventTiebreakDecision(
        ("points", "goal_differential"),
        "Published source",
        "https://example.test/tiebreaks",
        STANDARD_SCORING_POLICY,
    )
    original = replace(
        original,
        reviews=(review,),
        cohort_decisions=(decision,),
        tiebreak_decision=tiebreak,
    )
    current = replace(sample_snapshot(generation="targeted"), reviews=(), cohort_decisions=())
    verification = CaptureVerification(("10", "20"), (2, 2), "now", True)

    carried = _preserve_review_state_after_capture(current, original, current.roster, verification)

    assert carried.reviews == (review,)
    assert carried.cohort_decisions == (decision,)
    assert carried.tiebreak_decision == tiebreak
    assert carried.verification == verification


def test_historical_team_search_is_paginated_and_does_not_filter_current_age():
    calls = []

    class SearchQuery:
        def select(self, columns):
            calls.append(("select", columns))
            return self

        def eq(self, column, value):
            calls.append(("eq", column, value))
            return self

        def ilike(self, column, value):
            calls.append(("ilike", column, value))
            return self

        def range(self, start, end):
            calls.append(("range", start, end))
            return self

        def execute(self):
            return SimpleNamespace(data=[{"team_id_master": "one", "team_name": "Alpha"}])

    client = SimpleNamespace(table=lambda table: SearchQuery())
    assert search_master_teams(client, name="Alpha", club="City", page=2)[0]["team_id_master"] == "one"
    assert ("range", 40, 59) in calls
    assert not any(call[0] == "eq" and call[1] == "age_group" for call in calls)


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


def _render_failed_rollup_app():
    from pathlib import Path

    from src.tournaments.backtest_intake_ui import _render_event_rollup
    from src.tournaments.backtest_reviewed_run import ReviewedCohortReadiness
    from tests.unit.test_backtest_intake_state import sample_snapshot

    _render_event_rollup(
        sample_snapshot(),
        [ReviewedCohortReadiness("u12", "Male", 2, 1, {"age_group": "u12"})],
        "gotsport__51783__2025",
        Path("."),
        predictor_sha256="predictor-sha",
        merge_map_version="merge-v1",
    )


def _render_unvalidated_rollup_app():
    from pathlib import Path

    from src.tournaments.backtest_intake_ui import _render_event_rollup
    from src.tournaments.backtest_reviewed_run import ReviewedCohortReadiness
    from tests.unit.test_backtest_intake_state import sample_snapshot

    _render_event_rollup(
        sample_snapshot(),
        [ReviewedCohortReadiness("u12", "Male", 2, 1, {"age_group": "u12"})],
        "gotsport__51783__2025",
        Path("."),
        predictor_sha256="predictor-sha",
        merge_map_version="merge-v1",
    )


def test_single_saved_event_opens_automatically_after_session_restart(tmp_path, monkeypatch):
    import tournament_intake as app
    from src.tournaments import backtest_intake_ui as ui
    from src.tournaments.backtest_intake_state import write_snapshot

    snapshot = sample_snapshot(generation="saved-event")
    write_snapshot("gotsport__51783__unknown", snapshot, base_dir=tmp_path)
    fake_st = SimpleNamespace(session_state={}, error=lambda message: pytest.fail(message))
    monkeypatch.setattr(ui, "st", fake_st)

    ui._load_saved(tmp_path)

    assert fake_st.session_state[app._BACKTEST_KEYS.snapshot] == snapshot
    assert fake_st.session_state["bt_review_epoch_saved-event"] == 1


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
    metrics = {item.label: item.value for item in test.metric}
    assert {label: metrics[label] for label in (
        "U10-U18 teams", "Divisions", "Pools", "Fixtures", "Games counted", "Average goal margin",
        "Total goal margin", "Blowout games (4+ goals)", "Blowout rate",
    )} == {
        "U10-U18 teams": "3", "Divisions": "2", "Pools": "2", "Fixtures": "1",
        "Games counted": "1", "Average goal margin": "0.00", "Total goal margin": "0",
        "Blowout games (4+ goals)": "0", "Blowout rate": "0.0%",
    }
    assert metrics["Capture verification"] == "Verify once"
    assert metrics["Team review"] == "1 / 3"
    overview_labels = {button.label for button in test.button}
    assert "Run selected cohort" not in overview_labels
    test.radio(key="bt_section_capture-one").set_value("Backtest").run()
    run_labels = {button.label for button in test.button}
    assert "Prepare and run full tournament Backtest (2 cohorts)" in run_labels
    assert "Prepare ratings and run only this cohort" in run_labels
    assert "Check historical ratings" not in run_labels
    test.radio(key="bt_section_capture-one").set_value("Teams").run()
    test.radio(key="bt_filter_capture-one").set_value("All teams").run()
    tables = [item.value for item in test.dataframe]
    matches = next(frame for frame in tables if "PitchRank ID" in frame.columns)
    assert matches["Event team"].tolist() == ["Alpha", "Bravo", "Charlie"]
    assert matches["Status"].tolist() == ["Matched", "Needs review", "Needs review"]
    labels = {button.label for button in test.button}
    assert "Save progress" in labels
    assert not any("Seeding" in label for label in labels)
    assert test.session_state["_seeding_result"] == "seeding-must-survive"


def test_ready_saved_cohort_runs_and_renders_actual_vs_matchbalance(tmp_path, monkeypatch):
    import hashlib

    import tournament_intake as app
    from src.tournaments import backtest_intake_ui as ui
    from src.tournaments.backtest_historical_preflight import (
        HistoricalCohortCheck,
        HistoricalEntrantCheck,
        HistoricalPreflight,
        preflight_input_sha256,
    )
    from src.tournaments.backtest_intake_state import CaptureVerification, write_snapshot
    from src.tournaments.backtest_link_store import update_links
    from src.tournaments.backtest_reviewed_run import ReviewedRunOutcome
    from tests.unit.test_backtest_request import _links, _snapshot
    from tests.unit.test_backtest_reviewed_run import _summary

    event_key = "gotsport__51783__2025"
    snapshot = replace(
        _snapshot(),
        verification=CaptureVerification(
            ("group-1",),
            (1, 1),
            "2026-09-12T00:00:00+00:00",
            True,
        ),
    )
    write_snapshot(event_key, snapshot, base_dir=tmp_path)
    update_links(
        event_key,
        event_id="51783",
        changed_links=_links().links,
        base_dir=tmp_path,
    )
    calls = []

    def fake_execute(
        event_key_value,
        request,
        *,
        merge_map_version,
        base_dir,
        on_progress,
    ):
        calls.append((event_key_value, request["age_group"]))
        run_path = (
            Path(base_dir)
            / event_key_value
            / "scenarios"
            / "reviewed-backtest"
            / "runs"
            / "u14_male_test"
        )
        run_path.mkdir(parents=True)
        metadata = {
            "backtest_engine_version": BACKTEST_ENGINE_VERSION,
            "cohort_age_group": "u14",
            "cohort_gender": "Male",
            "event_name": "Spring Cup",
            "ended_at": "2026-09-12T01:00:00+00:00",
            "source_capture_generation": snapshot.generation,
            "request_sha256": hashlib.sha256(
                json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "predictor_sha256": ui.canonical_predictor_sha256(),
            "merge_map_version": merge_map_version,
        }
        (run_path / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        summary = _summary()
        summary["original_model_projection"]["average_goal_differential"] = 1.0
        summary["original_model_projection"]["blowout_4plus_probability"] = 0.0
        summary["original_schedule_projection"] = {
            **summary["original_model_projection"],
            "average_goal_differential": 1.0,
            "blowout_4plus_probability": 0.0,
        }
        (run_path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (run_path / "comparison.html").write_text("<html>report</html>", encoding="utf-8")
        (run_path / "done.json").write_text("{}", encoding="utf-8")
        return ReviewedRunOutcome("completed", run_path)

    monkeypatch.setattr(app, "reports_dir", lambda: tmp_path)
    monkeypatch.setattr(app, "_render_seeding_event_scrape", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        app,
        "_seeding_merge_resolver",
        lambda client: SimpleNamespace(version="ok", resolve=lambda team_id: team_id),
    )
    monkeypatch.setattr(ui, "execute_reviewed_run", fake_execute)
    def fake_preflight(requests, _client):
        request_list = list(requests)
        entrants = tuple(
            HistoricalEntrantCheck(
                entrant["entrant_id"],
                entrant["event_team_name"],
                entrant["canonical_team_id"],
                entrant["ranking_source_team_id"],
                True,
                snapshot_date="2025-05-09",
                source_age_group="u14",
                source_gender="Male",
                power_score=0.5,
            )
            for entrant in request_list[0]["entrants"]
        )
        return HistoricalPreflight(
            preflight_input_sha256(
                request_list,
                merge_map_version="ok",
            ),
            "2026-09-12T00:00:00+00:00",
            "2025-05-10",
            ui.canonical_predictor_sha256(),
            "merge-v1",
            (HistoricalCohortCheck("u14", "Male", len(entrants), len(entrants), entrants),),
        )

    monkeypatch.setattr(ui, "run_historical_preflight", fake_preflight)
    test = AppTest.from_function(_render_fixture_app, default_timeout=10).run()
    test.session_state[app._BACKTEST_KEYS.snapshot] = snapshot
    test.run()

    assert not test.exception, [error.message for error in test.exception]
    test.radio(key="bt_section_generation-1").set_value("Backtest").run()
    assert not any(item.label == "Advanced model settings" for item in test.expander)
    readiness_table = next(
        item.value for item in test.dataframe if {"Check", "Status", "Action"}.issubset(item.value.columns)
    )
    model_row = readiness_table.loc[readiness_table["Check"] == "Prediction engine"].iloc[0]
    assert model_row["Action"] == "PitchRank Compare predictor with historical inputs"
    run_button = next(
        button
        for button in test.button
        if button.label == "Prepare and run full tournament Backtest (1 cohort)"
    )
    assert run_button.disabled is False
    run_button.click().run()

    assert not test.exception, [error.message for error in test.exception]
    assert calls == [(event_key, "u14")]
    metrics = {item.label: item.value for item in test.metric}
    assert metrics["Observed games"] == "1"
    assert metrics["Observed average margin"] == "1.00"
    comparison = next(
        item.value for item in test.dataframe if "MatchBalance projection" in item.value.columns
    )
    assert comparison["Metric"].tolist()[0] == "Average goal margin"
    assert comparison["Actual tournament"].tolist()[0] == "1.00"
    assert comparison["MatchBalance projection"].tolist()[0] == "1.50"
    assert comparison["Estimated reduction"].tolist()[0] == "0.50 higher"
    movements = next(
        item.value for item in test.dataframe if "MatchBalance division" in item.value.columns
    )
    assert movements["Decision"].tolist() == ["Stayed"]
    assert metrics["Cohorts completed"] == "1"
    assert metrics["Division unchanged"] == "1"
    assert metrics["Pool changed within division"] == "0"


def test_failed_cohort_remains_visible_after_refresh_without_successful_runs(
    tmp_path,
    monkeypatch,
):
    import hashlib

    from src.tournaments import backtest_intake_ui as ui
    from src.tournaments.backtest_reviewed_run import ReviewedRunRecord
    from tests.unit.test_backtest_intake_state import sample_snapshot

    request = {"age_group": "u12"}
    failed_dir = tmp_path / "u12_male_failed.failed"
    failed_dir.mkdir()
    (failed_dir / "run_metadata.json").write_text(
        json.dumps(
            {
                "backtest_engine_version": BACKTEST_ENGINE_VERSION,
                "source_capture_generation": sample_snapshot().generation,
                "request_sha256": hashlib.sha256(
                    json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                "predictor_sha256": "predictor-sha",
                "merge_map_version": "merge-v1",
            }
        ),
        encoding="utf-8",
    )
    failed = ReviewedRunRecord(
        "u12_male_failed",
        failed_dir,
        "u12",
        "Male",
        "Spring Invitational",
        "2026-09-13T08:00:00+00:00",
        "failed",
        "Historical rating lookup timed out",
    )
    monkeypatch.setattr(ui, "list_reviewed_runs", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(ui, "list_failed_reviewed_runs", lambda *_args, **_kwargs: (failed,))

    test = AppTest.from_function(_render_failed_rollup_app, default_timeout=10).run()

    assert not test.exception, [error.message for error in test.exception]
    assert any("1 cohort run(s) failed" in item.value for item in test.warning)
    assert not any(item.label == "Cohorts completed" for item in test.metric)


def test_event_placements_stay_hidden_until_event_comparison_is_validated(monkeypatch):
    from src.tournaments import backtest_intake_ui as ui

    rollup = {
        "selected_runs": ["run-1"],
        "coverage": {
            "completed": 1,
            "failed": 0,
            "awaiting_matches": 0,
            "awaiting_review": 0,
            "awaiting_history": 0,
            "ready": 1,
            "rows": [
                {
                    "gender": "Male",
                    "age_group": "u12",
                    "team_count": 2,
                    "status": "completed",
                    "what_remains": "",
                }
            ],
        },
        "actual_vs_matchbalance": {
            "scope_note": "Completed compatible cohorts",
            "comparison_ready": False,
            "actual_average_goal_margin": 2.0,
            "matchbalance_projected_average_goal_margin": None,
            "estimated_goal_margin_reduction": None,
            "actual_blowout_4plus_rate": 0.25,
            "matchbalance_projected_blowout_4plus_rate": None,
            "estimated_blowout_4plus_rate_reduction": None,
        },
        "team_movements": {
            "moved_up": 1,
            "moved_down": 0,
            "unchanged": 1,
            "pool_changed_within_division": 1,
            "rows": [
                {
                    "event_team_name": "Alpha",
                    "gender": "Male",
                    "age_group": "u12",
                    "actual_division": "Silver",
                    "recommended_division": "Gold",
                    "actual_pool": "A",
                    "recommended_pool": "B",
                    "move": "up",
                }
            ],
        },
        "model_validation": {
            "event_validation": {
                "status": "failed",
                "actual_scored_game_count": 1,
                "fixture_count_coverage": 1.0,
            }
        },
    }
    monkeypatch.setattr(ui, "list_reviewed_runs", lambda *_args, **_kwargs: (object(),))
    monkeypatch.setattr(ui, "list_failed_reviewed_runs", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(ui, "build_event_rollup", lambda *_args, **_kwargs: rollup)
    monkeypatch.setattr(ui, "event_rollup_export", lambda _rollup: b"report")

    test = AppTest.from_function(_render_unvalidated_rollup_app, default_timeout=10).run()

    assert not test.exception, [error.message for error in test.exception]
    metric_labels = {item.label for item in test.metric}
    assert "Teams moved up" not in metric_labels
    assert not any(
        "MatchBalance division" in item.value.columns for item in test.dataframe
    )
    assert any(
        "placement recommendations remain hidden" in item.value.lower()
        for item in test.caption
    )


def test_run_all_continues_after_one_cohort_fails(tmp_path, monkeypatch):
    from src.tournaments import backtest_intake_ui as ui
    from src.tournaments.backtest_reviewed_run import ReviewedCohortReadiness, ReviewedRunOutcome

    calls = []

    def fake_execute(event_key, request, **_kwargs):
        calls.append(request["age_group"])
        if request["age_group"] == "u12":
            return ReviewedRunOutcome("failed", tmp_path / "failed", "U12 failed")
        completed = tmp_path / "u13-completed"
        completed.mkdir()
        return ReviewedRunOutcome("completed", completed)

    class Status:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def update(self, **_kwargs):
            return None

    class Element:
        def caption(self, *_args, **_kwargs):
            return None

        def progress(self, *_args, **_kwargs):
            return None

    errors = []
    reruns = []
    button_labels = []

    def button(label, *_args, **_kwargs):
        button_labels.append(label)
        return False

    fake_st = SimpleNamespace(
        session_state={},
        status=lambda *_args, **_kwargs: Status(),
        button=button,
        progress=lambda *_args, **_kwargs: Element(),
        empty=Element,
        error=errors.append,
        success=lambda *_args, **_kwargs: None,
        rerun=lambda: reruns.append(True),
    )
    readiness = [
        ReviewedCohortReadiness("u12", "Male", 4, 1, {"age_group": "u12"}),
        ReviewedCohortReadiness("u13", "Male", 4, 1, {"age_group": "u13"}),
    ]
    monkeypatch.setattr(ui, "st", fake_st)
    monkeypatch.setattr(ui, "execute_reviewed_run", fake_execute)

    ui._run_reviewed_requests(
        "gotsport__51783__2025",
        readiness,
        merge_map_version="merge-v1",
        base_dir=tmp_path,
    )

    assert calls == ["u12", "u13"]
    assert errors == ["U12 failed"]
    assert button_labels == ["Stop current run", "Stop current run"]
    assert fake_st.session_state["bt_completed_run_gotsport__51783__2025"] == "u13-completed"
    assert reruns == []


def test_overview_keeps_unverified_complete_capture_in_remaining_work(tmp_path, monkeypatch):
    import tournament_intake as app
    from src.tournaments.backtest_intake_state import write_snapshot
    from src.tournaments.backtest_link_store import update_links
    from tests.unit.test_backtest_request import _links, _snapshot

    snapshot = _snapshot()
    assert snapshot.roster.is_complete is True
    write_snapshot("gotsport__51783__2025", snapshot, base_dir=tmp_path)
    update_links(
        "gotsport__51783__2025",
        event_id="51783",
        changed_links=_links().links,
        base_dir=tmp_path,
    )
    monkeypatch.setattr(app, "reports_dir", lambda: tmp_path)
    monkeypatch.setattr(app, "_render_seeding_event_scrape", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        app,
        "_seeding_merge_resolver",
        lambda client: SimpleNamespace(version="ok", resolve=lambda team_id: team_id),
    )
    test = AppTest.from_function(_render_fixture_app, default_timeout=10).run()
    test.session_state[app._BACKTEST_KEYS.snapshot] = snapshot
    test.run()

    assert not test.exception, [error.message for error in test.exception]
    warnings = [item.value for item in test.warning]
    assert any("Verify the published division list once" in item for item in warnings), warnings
    assert not any("fully captured, matched, and reviewed" in item.value for item in test.success)


def test_actual_results_weight_games_follow_entered_cohorts_and_survive_saved_reload(rendered_intake, monkeypatch):
    import tournament_intake as app
    from src.tournaments import backtest_intake_ui as ui

    test, tmp_path = rendered_intake
    snapshot = sample_snapshot(generation="scored-capture")
    boys, girls = snapshot.roster.divisions
    draw = boys.fixtures[0]  # Its 4-3 shootout must contribute zero goal margin.
    blowout = replace(draw, match_number="8", home_score=4, away_score=0, result_text="4 - 0",
                      home_shootout_score=None, away_shootout_score=None)
    close_game = replace(blowout, match_number="9", home_score=3, result_text="3 - 0",
                         home_registration_id="102", home_label="Charlie",
                         away_registration_id="103", away_label="Delta", winner_registration_id="102")
    snapshot = replace(snapshot, roster=replace(snapshot.roster, divisions=(
        replace(boys, fixtures=(draw, blowout)), replace(girls, fixtures=(close_game,)),
    )))
    exported = []
    real_download = ui.st.download_button

    def record_download(label, data, **kwargs):
        if kwargs.get("mime") == "application/json":
            exported.append(json.loads(data))
        return real_download(label, data, **kwargs)

    monkeypatch.setattr(ui.st, "download_button", record_download)
    test.session_state[app._BACKTEST_KEYS.snapshot] = snapshot
    test.run()

    assert not test.exception, [error.message for error in test.exception]
    metrics = {item.label: item.value for item in test.metric}
    assert metrics["Games counted"] == "3"
    assert metrics["Total goal margin"] == "7"
    assert metrics["Average goal margin"] == "2.33"
    assert metrics["Blowout games (4+ goals)"] == "1"
    assert metrics["Blowout rate"] == "33.3%"
    cohort_table = next(item.value for item in test.dataframe
                        if "Games counted" in item.value.columns and "Division" not in item.value.columns)
    assert cohort_table["Tournament cohort"].tolist() == ["U12", "U13"]
    assert cohort_table["Gender"].tolist() == ["Boys", "Girls"]
    assert cohort_table["Games counted"].tolist() == [2, 1]
    assert cohort_table["Average goal margin"].tolist() == [2.0, 3.0]
    assert cohort_table["Blowout rate (%)"].tolist() == [50.0, 0.0]
    division_table = next(item.value for item in test.dataframe if "Division" in item.value.columns
                          and "Games counted" in item.value.columns)
    assert division_table["Division"].tolist() == ["BU12 Gold", "GU13 Silver"]
    assert division_table["Total goal margin"].tolist() == [4, 3]
    results = exported[-1]["tournament_totals"]["results"]
    assert results["scored_games"] == 3
    assert results["total_goal_margin"] == 7
    assert results["average_goal_margin"] == pytest.approx(7 / 3)
    assert results["blowout_games"] == 1
    assert results["blowout_percentage"] == pytest.approx(100 / 3)

    # The fixture app never invokes the scrape action. Opening this saved event
    # must recover the same scored evidence and recompute the same result export.
    test.button(key="bt_save_scored-capture").click().run()
    assert not test.exception, [error.message for error in test.exception]
    assert read_snapshot("gotsport__51783__unknown", base_dir=tmp_path).roster == snapshot.roster
    test.session_state[app._BACKTEST_KEYS.snapshot] = sample_snapshot(generation="different-display")
    test.run()
    assert {item.label: item.value for item in test.metric}["Games counted"] == "1"
    test.button(key="_backtest_open_saved").click().run()
    assert not test.exception, [error.message for error in test.exception]
    assert {item.label: item.value for item in test.metric} == metrics
    assert exported[-1]["tournament_totals"]["results"] == results
    assert test.session_state["_seeding_result"] == "seeding-must-survive"


def test_partial_results_explain_conflicts_and_missing_scores_instead_of_zero_average(rendered_intake):
    import tournament_intake as app

    test, _ = rendered_intake
    snapshot = sample_snapshot(generation="partial-results")
    division = snapshot.roster.divisions[0]
    draw = division.fixtures[0]
    competing_result = replace(draw, home_score=5, result_text="5 - 2",
                               home_shootout_score=None, away_shootout_score=None)
    missing_score = replace(draw, match_number="8", away_score=None, result_text="2 - ?",
                            home_shootout_score=None, away_shootout_score=None)
    snapshot = replace(snapshot, roster=replace(snapshot.roster, divisions_walked=1, divisions=(
        replace(division, fixtures=(draw, competing_result, missing_score)),
    )))
    test.session_state[app._BACKTEST_KEYS.snapshot] = snapshot

    test.run()

    assert not test.exception, [error.message for error in test.exception]
    metrics = {item.label: item.value for item in test.metric}
    assert metrics["Games counted"] == "0"
    assert metrics["Average goal margin"] == "—"
    assert metrics["Blowout rate"] == "—"
    assert metrics["Blowout games (4+ goals)"] == "0"
    assert any("results cover only the fixtures captured so far" in item.value for item in test.warning)
    assert any("1 fixtures have conflicting results" in item.value for item in test.warning)
    assert any("No eligible scored games" in item.value for item in test.info)
    assert any("Captured: 3 fixture listings, 2 identified games. 2 entries excluded" in item.value
               for item in test.caption)
    assert any("1 repeated fixture listings combined" in item.value for item in test.caption)
    exclusions = next(item.value for item in test.dataframe if "Reason" in item.value.columns)
    assert set(exclusions["Reason"]) == {"Conflicting results", "Invalid score"}
    assert exclusions["Fixtures"].sum() == 2


def test_streamlit_clear_stays_unresolved_after_rerender_and_can_be_saved(rendered_intake):
    test, tmp_path = rendered_intake
    test.radio(key="bt_section_capture-one").set_value("Teams").run()
    test.radio(key="bt_filter_capture-one").set_value("All teams").run()
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


def test_structure_is_supporting_detail_and_needs_no_manual_division_review(rendered_intake):
    test, _ = rendered_intake

    assert test.radio(key="bt_section_capture-one").options == ["Overview", "Teams", "Backtest"]
    test.checkbox(key="bt_show_structure_capture-one").check().run()

    assert not test.exception, [error.message for error in test.exception]
    assert any("Captured 2 divisions" in item.value for item in test.success)
    assert not any(item.label == "Manual replay format" for item in test.selectbox)
    assert not any("manual format" in item.label.lower() for item in test.checkbox)


def test_optional_cohort_correction_survives_explicit_save(rendered_intake):
    test, tmp_path = rendered_intake
    test.checkbox(key="bt_show_structure_capture-one").check().run()
    test.text_input(key="bt_division_capture-one_10_cohort_age").set_value("U13").run()
    test.text_input(key="bt_division_capture-one_10_cohort_note").set_value(
        "Published bracket is U13"
    ).run()
    test.text_input(key="bt_division_capture-one_10_cohort_source_url").set_value(
        "https://example.test/division/10"
    ).run()
    test.button(key="bt_save_capture-one").click().run()

    assert not test.exception, [error.message for error in test.exception]
    saved = read_snapshot("gotsport__51783__unknown", base_dir=tmp_path)
    decision = next(item for item in saved.cohort_decisions if item.group_id == "10")
    assert decision.age_group == "u13"
    assert decision.note == "Published bracket is U13"


def test_event_tiebreak_draft_survives_navigation_and_explicit_save(rendered_intake):
    test, tmp_path = rendered_intake
    test.checkbox(key="bt_show_structure_capture-one").check().run()
    test.selectbox(key="bt_tiebreak_mode_capture-one").set_value(
        "Points → goal differential → goals scored → wins"
    ).run()
    test.selectbox(key="bt_tiebreak_scoring_capture-one").set_value(
        "Standard: 3 win / 1 draw / 0 loss; uncapped goal differential"
    ).run()
    test.text_input(key="bt_tiebreak_note_capture-one").set_value(
        "Confirmed on the published event page"
    ).run()
    test.text_input(key="bt_tiebreak_source_capture-one").set_value(
        "https://example.test/tiebreaks"
    ).run()

    test.radio(key="bt_section_capture-one").set_value("Teams").run()
    test.radio(key="bt_section_capture-one").set_value("Overview").run()
    test.button(key="bt_save_capture-one").click().run()

    assert not test.exception, [error.message for error in test.exception]
    decision = read_snapshot(
        "gotsport__51783__unknown", base_dir=tmp_path
    ).tiebreak_decision
    assert decision == EventTiebreakDecision(
        ("points", "goal_differential", "goals_for", "wins"),
        "Confirmed on the published event page",
        "https://example.test/tiebreaks",
        STANDARD_SCORING_POLICY,
    )


def test_unsaved_tiebreak_edit_blocks_backtest_from_using_the_saved_rule(rendered_intake):
    import tournament_intake as app
    from src.tournaments.backtest_intake_state import write_snapshot

    test, tmp_path = rendered_intake
    saved_rule = EventTiebreakDecision(
        ("points", "goal_differential", "goals_for", "wins"),
        "Published source",
        "https://example.test/tiebreaks",
        STANDARD_SCORING_POLICY,
    )
    snapshot = replace(sample_snapshot(), tiebreak_decision=saved_rule)
    write_snapshot("gotsport__51783__unknown", snapshot, base_dir=tmp_path)
    test.session_state[app._BACKTEST_KEYS.snapshot] = snapshot
    test.run()

    test.checkbox(key="bt_show_structure_capture-one").check().run()
    test.selectbox(key="bt_tiebreak_mode_capture-one").set_value("Not verified").run()
    test.radio(key="bt_section_capture-one").set_value("Backtest").run()

    readiness = next(item.value for item in test.dataframe if "What remains" in item.value.columns)
    assert readiness["What remains"].str.contains("Save the current review").all()
    assert next(
        button for button in test.button if "full tournament Backtest" in button.label
    ).disabled


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

    test.radio(key="bt_section_capture-one").set_value("Teams").run()
    test.radio(key="bt_filter_capture-one").set_value("All teams").run()
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

    links, details, conflicts, merge_map_version = _sync_matches(snapshot, client, tmp_path)

    assert conflicts == {}
    assert merge_map_version == "ok"
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

    links, details, conflicts, merge_map_version = _sync_matches(
        snapshot, ReadOnlyTeams(), tmp_path
    )
    rows = match_table(snapshot, links, details, conflicts=conflicts)

    assert conflicts == {"100": ("canonical-a", "canonical-other")}
    assert merge_map_version == "ok"
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
    assert confirmed_rows[0]["Status"] == "Needs review"
    assert "also linked" in confirmed_rows[0]["Match issue"]
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
        if isinstance(data, str):
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
    test.radio(key="bt_section_capture-one").set_value("Backtest").run()

    readiness = next(item.value for item in test.dataframe if "What remains" in item.value.columns)
    assert readiness["What remains"].str.contains("merge-synchronized team IDs").all()
    assert next(
        button for button in test.button if "full tournament Backtest" in button.label
    ).disabled
    metrics = {item.label: item.value for item in test.metric}
    assert metrics["Team review"] == "Unavailable"
    test.radio(key="bt_section_capture-one").set_value("Teams").run()

    assert not test.exception, [error.message for error in test.exception]
    assert any("Team matching is unavailable" in warning.value for warning in test.warning)
    matches = next(item.value for item in test.dataframe if "PitchRank ID" in item.value.columns)
    assert matches["Status"].tolist() == ["Linked team unavailable", "Needs review", "Match cleared"]
    assert matches.loc[0, "PitchRank ID"] == "operator-choice"
    assert exported[-1]["links"]["links"][0]["team_id_master"] == "operator-choice"
    assert exported[-1]["links"]["removed_registration_ids"] == ["102"]
    assert exported[-1]["team_matches"][0]["PitchRank ID"] == "operator-choice"
    assert test.session_state["_seeding_result"] == "seeding-must-survive"
