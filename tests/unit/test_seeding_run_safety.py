"""A new roster never autosaves over a different saved run, and every refusal stays visible.

The Seeding tab saves after every import and every match, under the name in its
name box. These tests drive the real save path against a store under
``tmp_path``, so the refusals come from ``save_run`` itself rather than a stub.
"""

from __future__ import annotations

import contextlib
import json

import pytest

import tournament_intake as intake
from src.tournaments.roster_paste import parse_roster
from src.tournaments.roster_resolver import ResolvedTeam
from src.tournaments.seeding_assessment import source_fingerprint
from src.tournaments.seeding_run_store import SeedingRun, load_run, save_run
from tests.unit.test_seeding_event_intake import (
    _FakeSessionState,
    _FakeSt,
    _install,
    _no_lock,
    _RecordingScrape,
    _Rerun,
    _roster,
    _team,
)

EVENT_111 = "https://system.gotsport.com/org_event/events/111"
EVENT_ROWS = "Boys U12\nClub\tEvent Team A\nClub\tEvent Team B"
PASTE_ROWS = "Boys U12\nClub\tPasted Team A\nClub\tPasted Team B\nClub\tPasted Team C"


@pytest.fixture
def store(monkeypatch, tmp_path):
    """The real run store under ``tmp_path``, with every network lookup answered empty."""
    monkeypatch.setattr(intake, "save_seeding_run_file", lambda run, **kw: save_run(run, base_dir=tmp_path, **kw))
    monkeypatch.setattr(intake, "_seeding_provider_id_lookup", lambda _client: (lambda _pid: None))
    monkeypatch.setattr(intake, "_enrich_seeding_names", lambda resolved, _client: tuple(resolved))
    monkeypatch.setattr(intake, "make_exact_name_lookup", lambda _client: (lambda *_a: []))
    monkeypatch.setattr(intake, "search_gotsport_teams", lambda *_a, **_kw: [])
    monkeypatch.setattr(intake, "_SEEDING_LOOKUP_DELAY_SECONDS", 0)
    return tmp_path


def _unresolved(parsed):
    return tuple(ResolvedTeam(row.source_index, "unresolved") for row in parsed.rows)


def _open_event_run(fake: _FakeSt, store, name: str = "Cup A") -> None:
    """Save an event walk under ``name`` and leave it open, as loading it does."""
    parsed = parse_roster(EVENT_ROWS)
    assessment = {
        "event_id": "111", "coverage": "complete", "source_kind": "GotSport event",
        "source_url": EVENT_111, "completed": [0, 1], "fingerprint": source_fingerprint(parsed.rows),
    }
    save_run(SeedingRun(name, parsed.rows, _unresolved(parsed), source_url=EVENT_111, assessment=assessment),
             base_dir=store)
    intake._park_seeding_result((parsed, _unresolved(parsed)), event_id="111")
    fake.session_state.update(
        seeding_event_name=name, _seeding_loaded_slug="cup-a", seeding_resume_choice="cup-a",
        _seeding_assessment=dict(assessment), _seeding_overrides={},
    )


def _open_pasted_run(fake: _FakeSt, store, name: str = "Cup A") -> None:
    parsed = parse_roster(EVENT_ROWS)
    assessment = {"coverage": "unknown", "source_kind": "Paste team list", "source_url": "",
                  "completed": [0, 1], "fingerprint": source_fingerprint(parsed.rows)}
    save_run(SeedingRun(name, parsed.rows, _unresolved(parsed), assessment=assessment), base_dir=store)
    intake._park_seeding_result((parsed, _unresolved(parsed)), event_id=None)
    fake.session_state.update(seeding_event_name=name, _seeding_loaded_slug="cup-a",
                              _seeding_assessment=dict(assessment), _seeding_overrides={})


def _next_run(fake: _FakeSt) -> None:
    """What a rerun does to the page: erase what was drawn, then draw the notices waiting."""
    fake.errors.clear()
    fake.warnings.clear()
    fake.infos.clear()
    fake.session_state.disarm()
    intake._render_seeding_notices()


def _saved_teams(store, slug: str = "cup-a") -> list[str]:
    return [row.team_name_raw for row in load_run(slug, base_dir=store).rows]


# -------- a new roster over an open run waits for a name ------------------


def test_a_paste_into_an_open_event_run_leaves_that_run_and_waits_for_a_name(monkeypatch, store):
    fake = _install(monkeypatch, _FakeSt())
    _open_event_run(fake, store)

    assert intake._run_seeding_resolve(PASTE_ROWS, None)

    assert _saved_teams(store) == ["Event Team A", "Event Team B"]
    assert load_run("cup-a", base_dir=store).source_url == EVENT_111
    assert [team.team_name_raw for team in fake.session_state["_seeding_result"][0].rows] == [
        "Pasted Team A", "Pasted Team B", "Pasted Team C"]
    _next_run(fake)
    assert any("'Cup A'" in message and "new name" in message for message in fake.warnings)


def test_a_detached_roster_is_still_matched(monkeypatch, store):
    fake = _install(monkeypatch, _FakeSt())
    _open_event_run(fake, store)

    intake._run_seeding_resolve(PASTE_ROWS, None)

    assert fake.session_state["_seeding_assessment"]["completed"] == [0, 1, 2]
    assert not any("Matching paused" in text for _level, text in fake.session_state["_seeding_notices"])


def test_the_next_render_empties_the_name_and_unlinks_the_saved_run(monkeypatch, store):
    fake = _install(monkeypatch, _FakeSt())
    _open_event_run(fake, store)
    intake._run_seeding_resolve(PASTE_ROWS, None)

    intake._apply_pending_seeding_widgets()

    assert fake.session_state["seeding_event_name"] == ""
    assert fake.session_state["_seeding_loaded_slug"] is None
    assert fake.session_state["seeding_resume_choice"] is None


def test_a_new_name_saves_the_detached_roster_and_keeps_the_old_run(monkeypatch, store):
    fake = _install(monkeypatch, _FakeSt())
    _open_event_run(fake, store)
    intake._run_seeding_resolve(PASTE_ROWS, None)
    intake._apply_pending_seeding_widgets()

    fake.session_state["seeding_event_name"] = "Cup B"

    assert intake._autosave_seeding_run()
    assert _saved_teams(store, "cup-b") == ["Pasted Team A", "Pasted Team B", "Pasted Team C"]
    assert _saved_teams(store) == ["Event Team A", "Event Team B"]


def test_a_corrected_paste_into_a_pasted_run_keeps_its_name(monkeypatch, store):
    fake = _install(monkeypatch, _FakeSt())
    _open_pasted_run(fake, store)

    assert intake._run_seeding_resolve(PASTE_ROWS, None)

    assert _saved_teams(store) == ["Pasted Team A", "Pasted Team B", "Pasted Team C"]
    assert "_seeding_detach_run" not in fake.session_state
    assert fake.session_state["seeding_event_name"] == "Cup A"


# -------- a walk over an open run waits for a name too --------------------


@pytest.fixture
def walker(monkeypatch, store):
    """The real event walk against the store, with the paid scrape stood in for."""
    monkeypatch.setenv("ZENROWS_API_KEY", "test-key")
    monkeypatch.setattr(intake, "_acquire_scrape_lock", _no_lock)
    monkeypatch.setattr(intake, "make_zenrows_fetcher", lambda *_a, **_kw: (lambda url: ""))
    monkeypatch.setattr(intake, "resolve_master_ids", lambda teams, **_kw: ({}, []))
    monkeypatch.setattr(intake, "default_seeding_base_dir", lambda: store / "recovery")

    def walk(event_id: str, *, complete: bool = True) -> None:
        roster = _roster(_team(0), _team(1), event_id=event_id, divisions_found=2 if complete else 40)
        monkeypatch.setattr(intake, "scrape_event_roster", _RecordingScrape(roster))
        with contextlib.suppress(_Rerun):
            intake._run_event_roster_scrape(
                f"https://system.gotsport.com/org_event/events/{event_id}", None, limit_groups=None if complete else 2
            )

    return walk


def _notice_texts(fake: _FakeSt) -> list[str]:
    return [text for _level, text in fake.session_state.get("_seeding_notices") or []]


def test_walking_another_event_over_an_open_run_detaches_and_still_matches(monkeypatch, store, walker):
    fake = _install(monkeypatch, _FakeSt())
    _open_event_run(fake, store)

    walker("222")

    assert _saved_teams(store) == ["Event Team A", "Event Team B"]
    assert fake.session_state["_seeding_assessment"]["completed"] == [0, 1]
    assert any("not the saved run 'Cup A'" in text for text in _notice_texts(fake))
    assert not any("Matching paused" in text for text in _notice_texts(fake))


def test_probing_the_saved_event_keeps_its_full_walk_and_says_why(monkeypatch, store, walker):
    fake = _install(monkeypatch, _FakeSt())
    _open_event_run(fake, store)

    walker("111", complete=False)

    assert _saved_teams(store) == ["Event Team A", "Event Team B"]
    assert any("covers less than the complete saved run 'Cup A'" in text for text in _notice_texts(fake))
    assert fake.session_state["_seeding_assessment"]["completed"] == [0, 1]


def test_rewalking_the_saved_event_replaces_it_under_its_name(monkeypatch, store, walker):
    fake = _install(monkeypatch, _FakeSt())
    _open_event_run(fake, store)

    walker("111")

    assert _saved_teams(store) == ["Team 0", "Team 1"]
    assert not _notice_texts(fake)
    assert fake.session_state["seeding_event_name"] == "Cup A"


def test_an_older_event_save_reopens_as_its_event_and_saves_in_place(monkeypatch, store):
    fake = _install(monkeypatch, _FakeSt())
    parsed = parse_roster(EVENT_ROWS)
    path = save_run(SeedingRun("GotSport Event 111 · U10 Probe", parsed.rows, _unresolved(parsed)), base_dir=store)
    legacy = json.loads(path.read_text(encoding="utf-8"))
    legacy.pop("assessment", None)
    legacy.pop("source_url", None)
    path.write_text(json.dumps(legacy), encoding="utf-8")
    monkeypatch.setattr(intake, "load_seeding_run_file", lambda slug: load_run(slug, base_dir=store))
    fake.session_state.update(_seeding_overrides={})

    assert intake._load_seeding_run(path.parent.name)
    intake._apply_pending_seeding_widgets()

    assert intake._autosave_seeding_run()
    assert load_run(path.parent.name, base_dir=store).source_url == EVENT_111
    assert "_seeding_detach_run" not in fake.session_state


def test_a_paste_named_like_an_event_reopens_as_a_paste(monkeypatch, store):
    _install(monkeypatch, _FakeSt())
    parsed = parse_roster(PASTE_ROWS)
    assessment = {"coverage": "unknown", "source_kind": "Paste team list", "source_url": ""}
    path = save_run(
        SeedingRun("GotSport Event 111 · Pasted", parsed.rows, _unresolved(parsed), assessment=assessment),
        base_dir=store,
    )
    monkeypatch.setattr(intake, "load_seeding_run_file", lambda slug: load_run(slug, base_dir=store))

    assert intake._load_seeding_run(path.parent.name)

    assert intake.st.session_state["_seeding_pending_event_url"] == ""
    assert intake.st.session_state["_seeding_result_event_id"] is None


# -------- a name that another run already owns ----------------------------


def test_a_name_another_run_owns_is_refused_with_its_name_shown(monkeypatch, store):
    fake = _install(monkeypatch, _FakeSt())
    _open_event_run(fake, store, name="STX Cup (Boys)")
    before = (store / "stx-cup-boys" / "seeding_run.json").read_bytes()
    fake.session_state["seeding_event_name"] = "STX Cup - Boys"

    assert not intake._autosave_seeding_run()

    assert (store / "stx-cup-boys" / "seeding_run.json").read_bytes() == before
    assert fake.session_state["_seeding_save_error"] is True, "the lasting could-not-save banner did not turn on"
    _next_run(fake)
    assert any("'STX Cup (Boys)'" in message for message in fake.errors)


def test_a_failed_write_is_reported_after_the_rerun_that_follows_it(monkeypatch, store):
    fake = _install(monkeypatch, _FakeSt())
    _open_event_run(fake, store)

    def disk_full(_run, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr(intake, "save_seeding_run_file", disk_full)

    assert not intake._autosave_seeding_run()
    _next_run(fake)
    assert fake.warnings == ["Could not save this run: disk full"]


def test_an_interrupted_import_is_reported_after_the_rerun_that_follows_it(monkeypatch, store):
    fake = _install(monkeypatch, _FakeSt())
    _open_event_run(fake, store)
    fake.session_state["_seeding_assessment"] = {**fake.session_state["_seeding_assessment"], "fingerprint": "another"}

    assert not intake._autosave_seeding_run()
    _next_run(fake)
    assert any("The import was interrupted" in message for message in fake.warnings)


# -------- messages raised before a rerun survive it -----------------------


def test_a_notice_is_shown_once(monkeypatch):
    fake = _install(monkeypatch, _FakeSt())
    intake._add_seeding_notice("warning", "Something to read")
    intake._add_seeding_notice("warning", "Something to read")

    _next_run(fake)
    assert fake.warnings == ["Something to read"]
    _next_run(fake)
    assert fake.warnings == []


def test_a_notice_interrupted_while_drawn_waits_for_the_next_run(monkeypatch):
    fake = _install(monkeypatch, _FakeSt())
    intake._add_seeding_notice("warning", "Something to read")

    def interrupted(_message):
        raise _Rerun()

    monkeypatch.setattr(fake, "warning", interrupted)
    with contextlib.suppress(_Rerun):
        intake._render_seeding_notices()

    assert fake.session_state["_seeding_notices"] == [("warning", "Something to read")]


def test_an_interrupted_detach_is_retried_whole(monkeypatch):
    class StopAtSlug(_FakeSessionState):
        def __setitem__(self, key, value):
            if key == "_seeding_loaded_slug" and not self.__dict__.get("stopped"):
                self.__dict__["stopped"] = True
                raise _Rerun()
            super().__setitem__(key, value)

    fake = _install(monkeypatch, _FakeSt())
    fake.session_state = StopAtSlug()
    fake.session_state.update(seeding_event_name="Cup A", _seeding_loaded_slug="cup-a", _seeding_detach_run=True)

    with pytest.raises(_Rerun):
        intake._apply_pending_seeding_widgets()
    assert intake._seeding_run_name() == ""
    intake._apply_pending_seeding_widgets()

    assert fake.session_state["_seeding_loaded_slug"] is None
    assert "_seeding_detach_run" not in fake.session_state


def test_a_refused_paste_does_not_rerun_over_its_own_message(monkeypatch, store):
    fake = _install(monkeypatch, _FakeSt(buttons={None: True}, text={"seeding_roster_text": PASTE_ROWS}))
    monkeypatch.setattr(fake, "radio", lambda _label, options, **_kw: options[1])
    monkeypatch.setattr(intake, "list_seeding_runs", lambda: [])
    monkeypatch.setattr(intake, "_autosave_seeding_run", lambda **_kw: False)
    intake._park_seeding_result((parse_roster(EVENT_ROWS), _unresolved(parse_roster(EVENT_ROWS))), event_id=None)
    fake.session_state.update(_seeding_overrides={}, _seeding_assessment={}, _seeding_active_step=1)

    with contextlib.suppress(_Rerun):
        intake._render_seeding_tab(None)

    assert fake.reruns == 0
    assert any("Name and save the current run" in message for message in fake.errors)


# -------- typed inputs survive a view switch ------------------------------

VIEW_SWITCH_APP = """
import streamlit as st
import tournament_intake as app
app._init_session_state()
if st.radio("View", ["Seeding", "Backtest"], key="active_view") == "Seeding":
    app._render_seeding_tab(None)
"""


@pytest.fixture
def switcher(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("MATCHBALANCE_SEEDING_DIR", str(tmp_path))
    monkeypatch.setattr(intake, "reports_dir", lambda: tmp_path)
    return AppTest.from_string(VIEW_SWITCH_APP, default_timeout=15).run()


def _switch_away_and_back(app) -> None:
    app.radio(key="active_view").set_value("Backtest").run()
    assert not app.exception
    app.radio(key="active_view").set_value("Seeding").run()
    assert not app.exception


def test_the_run_name_event_url_and_paste_survive_a_view_switch(switcher):
    app = switcher
    app.text_input(key="seeding_event_name").input("Workflow Cup").run()
    app.text_input(key="seeding_event_url").input(EVENT_111).run()
    app.radio(key="_seeding_source").set_value("Paste team list").run()
    app.text_area(key="seeding_roster_text").input(PASTE_ROWS).run()
    app.checkbox(key="_seeding_paste_complete").check().run()

    _switch_away_and_back(app)

    assert app.text_input(key="seeding_event_name").value == "Workflow Cup"
    assert app.radio(key="_seeding_source").value == "Paste team list"
    assert app.text_area(key="seeding_roster_text").value == PASTE_ROWS
    assert app.checkbox(key="_seeding_paste_complete").value is True
    app.radio(key="_seeding_source").set_value("GotSport event").run()
    assert app.text_input(key="seeding_event_url").value == EVENT_111


def test_a_loaded_runs_name_wins_over_the_kept_one(switcher):
    app = switcher
    app.text_input(key="seeding_event_name").input("Typed Cup").run()
    app.radio(key="active_view").set_value("Backtest").run()

    app.session_state["_seeding_pending_name"] = "Loaded Cup"
    app.radio(key="active_view").set_value("Seeding").run()

    assert not app.exception
    assert app.text_input(key="seeding_event_name").value == "Loaded Cup"
    _switch_away_and_back(app)
    assert app.text_input(key="seeding_event_name").value == "Loaded Cup"


def test_a_loaded_run_clears_a_paste_box_that_was_hidden(switcher):
    app = switcher
    app.radio(key="_seeding_source").set_value("Paste team list").run()
    app.text_area(key="seeding_roster_text").input(PASTE_ROWS).run()
    app.radio(key="_seeding_source").set_value("GotSport event").run()

    app.session_state["_seeding_pending_name"] = "Loaded Cup"
    app.run()
    app.run()
    app.radio(key="_seeding_source").set_value("Paste team list").run()

    assert not app.exception
    assert app.text_area(key="seeding_roster_text").value == ""


def test_a_notice_raised_while_the_tab_draws_shows_in_that_run(switcher, monkeypatch):
    app = switcher
    controls = intake._render_seeding_run_controls

    def controls_that_refuse(client=None):
        intake._add_seeding_notice("error", "Raised mid-render")
        controls(client)

    monkeypatch.setattr(intake, "_render_seeding_run_controls", controls_that_refuse)
    app.run()

    assert [item.value for item in app.error] == ["Raised mid-render"]


def test_the_tab_shows_a_waiting_notice_once(switcher):
    app = switcher
    app.session_state["_seeding_notices"] = [("warning", "Carried across the rerun")]

    app.run()
    assert [item.value for item in app.warning] == ["Carried across the rerun"]
    app.run()
    assert not app.warning
