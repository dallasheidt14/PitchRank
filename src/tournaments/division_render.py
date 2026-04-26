"""Shell 04 ↔ Shell 05 division-container rendering contract.

Shell 04 (triage UI) calls ``render_division_container`` for each division
inside a cohort to draw the division card + invoke the per-division body.
Shell 05 (structure input forms) replaces the stub with the real
implementation — until then, the stub raises ``NotImplementedError`` and
the triage UI catches it to render an "enter structure first" hint.

Both shells agree on this signature today so Shell 04 can ship before
Shell 05 lands.
"""

from __future__ import annotations

from collections.abc import Callable

__all__ = ["render_division_container"]


def render_division_container(division_name: str, body: Callable[[], None]) -> None:
    """Render a single division card with its body.

    Stub implementation — Shell 05 ships the real surface (a Streamlit
    container + structure-input header above the body). Until then, Shell
    04 catches the ``NotImplementedError`` once per cohort and surfaces a
    placeholder.
    """
    raise NotImplementedError("Shell 05 owns the division container surface.")
