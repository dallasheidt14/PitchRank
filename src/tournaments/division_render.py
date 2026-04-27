"""Shell 04 ↔ Shell 05 division-container rendering surface.

Shell 04 (triage UI) calls ``render_division_container`` for each division
inside a cohort to draw the division card + invoke the per-division body.
Shell 05 ships the real implementation: a bordered ``st.container`` with
an HTML-escaped header above the body callback.
"""

from __future__ import annotations

import html
from collections.abc import Callable

import streamlit as st

__all__ = ["render_division_container"]


def render_division_container(division_name: str, body: Callable[[], None]) -> None:
    """Render a single division card with its body.

    Mirrors Shell 04's ``_render_team_row`` border style — every row /
    division uses ``st.container(border=True)`` for visual symmetry.
    ``division_name`` originates from operator input; escape before
    interpolating into a markdown block.
    """
    with st.container(border=True):
        st.markdown(f"**{html.escape(division_name)}**")
        body()
