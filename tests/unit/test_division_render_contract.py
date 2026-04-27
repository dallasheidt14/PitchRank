"""Pin the Shell 04 ↔ Shell 05 ``render_division_container`` contract.

Until Shell 05 lands, ``render_division_container`` raises
``NotImplementedError`` and the triage UI falls back to a placeholder
hint. The xfail-marked test below flips to xpass once Shell 05 commits a
real implementation that invokes ``body`` exactly once — that flip is
the signal Shell 04 needs to drop the fallback.
"""

from __future__ import annotations

import pytest

from src.tournaments.division_render import render_division_container


def test_stub_raises_not_implemented_until_shell_05_lands():
    with pytest.raises(NotImplementedError, match="Shell 05"):
        render_division_container("Premier", lambda: None)


@pytest.mark.xfail(
    reason="Shell 05 ships the real implementation",
    raises=NotImplementedError,
    strict=True,
)
def test_render_division_container_invokes_body_once():
    call_count = {"n": 0}

    def body() -> None:
        call_count["n"] += 1

    render_division_container("Super Elite", body)
    assert call_count["n"] == 1
