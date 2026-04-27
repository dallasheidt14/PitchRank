"""Pin Shell 05's ``render_division_container`` body invocation contract.

Replaces the Shell 04 ↔ Shell 05 contract test: the stub raises
``NotImplementedError``; the live implementation must invoke the body
exactly once, escape division names that contain HTML, and be reachable
from ``_render_triage_left_pane`` without crashing under a stubbed
Streamlit surface.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.tournaments.division_render import render_division_container
from src.tournaments.storage import (
    CohortConstraints,
    CohortStructure,
    DivisionStructure,
)


def test_render_division_container_invokes_body_once(monkeypatch):
    """The live container is a thin wrapper — body must run exactly once."""
    counter = {"n": 0}

    def body() -> None:
        counter["n"] += 1

    fake_container = MagicMock()
    fake_container.__enter__ = MagicMock(return_value=fake_container)
    fake_container.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("src.tournaments.division_render.st.container", lambda **_kw: fake_container)
    monkeypatch.setattr("src.tournaments.division_render.st.markdown", MagicMock())

    render_division_container("Premier", body)
    assert counter["n"] == 1


def test_render_division_container_escapes_html(monkeypatch):
    """Division names with HTML are escaped before reaching ``st.markdown``."""
    fake_container = MagicMock()
    fake_container.__enter__ = MagicMock(return_value=fake_container)
    fake_container.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("src.tournaments.division_render.st.container", lambda **_kw: fake_container)
    captured: list[str] = []
    monkeypatch.setattr(
        "src.tournaments.division_render.st.markdown",
        lambda payload, **_kw: captured.append(payload),
    )

    render_division_container("<script>alert(1)</script>", lambda: None)
    assert captured, "st.markdown should be called once"
    assert "<script>" not in captured[0]
    assert "&lt;script&gt;" in captured[0]


def test_render_triage_left_pane_calls_live_container(monkeypatch):
    """Smoke-test that ``_render_triage_left_pane`` reaches the live container.

    Guards the Shell 04 ↔ Shell 05 same-commit discipline gap: the
    ``try/except NotImplementedError`` fallback is gone, so any future
    regression that re-introduces a stub or skips the call site fails here
    without requiring a Streamlit runtime.
    """
    import tournament_intake

    invocations: list[str] = []

    def fake_container(division_name, body):
        invocations.append(division_name)
        body()

    monkeypatch.setattr(tournament_intake, "render_division_container", fake_container)
    # Stub every Streamlit surface the body callback touches. A
    # MagicMock-as-context-manager handles ``with st.container(...)`` and
    # ``with st.form(...)``; bare callables handle markdown / button /
    # caption / number_input / text_input / selectbox / columns / form.
    fake_st = MagicMock()
    fake_st.session_state = {}

    def fake_columns(spec, **_kw):
        widths = spec if isinstance(spec, list) else range(int(spec))
        return [MagicMock() for _ in widths]

    fake_st.columns = fake_columns
    fake_st.button = MagicMock(return_value=False)
    fake_st.form_submit_button = MagicMock(return_value=False)
    monkeypatch.setattr(tournament_intake, "st", fake_st)

    monkeypatch.setattr(
        tournament_intake,
        "_render_division_editor",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        tournament_intake,
        "_render_division_body",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        tournament_intake,
        "_render_pool_preview",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        tournament_intake,
        "_render_add_division_form",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        tournament_intake,
        "read_frozen_medians",
        lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError),
    )

    structure = CohortStructure(
        age_group="u14",
        gender="Male",
        divisions=(
            DivisionStructure(
                name="Premier",
                team_count=4,
                pool_sizes=(4,),
                advancement="ROUND_ROBIN",
            ),
        ),
    )
    tournament_intake._render_triage_left_pane(
        cohort_records=[],
        registry_by_pid={},
        team_state={},
        resolved_team_by_id={},
        division_groups={"Premier": []},
        structure_for_cohort=structure,
        age="u14",
        gender="Male",
        event_key="gotsport__45224__2026",
        scenario="default",
        supabase_client=None,
    )

    assert invocations == ["Premier"]


def test_constraints_panel_compatible_with_live_dataclass():
    """``_render_constraints_panel`` should accept the live ``CohortConstraints`` shape."""
    constraint = CohortConstraints(cohort_age_group="u14", cohort_gender="Male")
    assert constraint.avoid_same_club_early is True
    assert constraint.rematch_avoidance_scope == "same_event"
